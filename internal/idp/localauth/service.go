package localauth

import (
	"context"
	"crypto/subtle"
	"fmt"
	"net/http"
	"strings"
	"time"
)

type Service struct {
	Store  Store
	Config Config
	lim    *rateLimiter
}

func NewService(store Store, cfg Config) *Service {
	return &Service{Store: store, Config: cfg, lim: newRateLimiter()}
}

type Profile struct {
	Username           string     `json:"username"`
	Email              string     `json:"email"`
	DisplayName        string     `json:"display_name"`
	Role               string     `json:"role"`
	MustChangePassword bool       `json:"must_change_password"`
	CSRFToken          string     `json:"csrf_token"`
	LastLoginAt        *time.Time `json:"last_login_at,omitempty"`
}

func (s *Service) Login(ctx context.Context, username, password, clientIP string) (Profile, Session, error) {
	username = stringsTrimLower(username)
	if !s.lim.allow("ip:"+clientIP, s.Config.LoginRateLimitWindowSec, s.Config.LoginRateLimitMax) ||
		!s.lim.allow("user:"+username, s.Config.LoginRateLimitWindowSec, s.Config.LoginRateLimitMax) {
		return Profile{}, Session{}, fmt.Errorf("rate limited")
	}
	user, err := s.Store.GetUser(ctx, username)
	if err != nil || !user.IsActive {
		_ = s.Store.InsertAudit(ctx, username, "anonymous", clientIP, "login_failed", "invalid user", nil)
		return Profile{}, Session{}, fmt.Errorf("invalid username or password")
	}
	now := time.Now().UTC()
	if user.LockedUntil != nil && user.LockedUntil.After(now) {
		return Profile{}, Session{}, fmt.Errorf("account locked")
	}
	if !VerifyPassword(user.PasswordHash, password) {
		_ = s.Store.UpdateUserAfterLogin(ctx, username, false, s.Config.LockoutMaxAttempts, s.Config.LockoutDurationSec)
		return Profile{}, Session{}, fmt.Errorf("invalid username or password")
	}
	_ = s.Store.UpdateUserAfterLogin(ctx, username, true, 0, 0)
	sess := Session{
		SessionID: NewSessionID(), Username: user.Username, CSRFToken: NewCSRFToken(),
		CreatedAt: now, LastSeen: now,
		ExpiresAt: now.Add(time.Duration(s.Config.SessionAbsoluteTimeoutSec) * time.Second),
	}
	if err := s.Store.CreateSession(ctx, sess); err != nil {
		return Profile{}, Session{}, err
	}
	_ = s.Store.InsertAudit(ctx, user.Username, user.Role, clientIP, "login_success", "login", nil)
	return Profile{
		Username: user.Username, Email: user.Email, DisplayName: user.DisplayName, Role: user.Role,
		MustChangePassword: user.MustChangePassword, CSRFToken: sess.CSRFToken,
	}, sess, nil
}

func (s *Service) SessionUser(ctx context.Context, r *http.Request) (*User, *Session, error) {
	if s.Config.AuthDisabled {
		u := actorFromHeader(r)
		if u == "" {
			u = "requester"
		}
		return &User{Username: u, Email: u + "@example.com", Role: "developer", IsActive: true}, nil, nil
	}
	cookie, err := r.Cookie(s.Config.CookieName)
	if err != nil || cookie.Value == "" {
		return nil, nil, fmt.Errorf("not authenticated")
	}
	sess, err := s.Store.GetSession(ctx, cookie.Value)
	if err != nil || sess.Revoked {
		return nil, nil, fmt.Errorf("invalid session")
	}
	now := time.Now().UTC()
	if now.After(sess.ExpiresAt) {
		_ = s.Store.RevokeSession(ctx, sess.SessionID)
		return nil, nil, fmt.Errorf("session expired")
	}
	if now.Sub(sess.LastSeen) > time.Duration(s.Config.SessionIdleTimeoutSec)*time.Second {
		_ = s.Store.RevokeSession(ctx, sess.SessionID)
		return nil, nil, fmt.Errorf("session idle timeout")
	}
	user, err := s.Store.GetUser(ctx, sess.Username)
	if err != nil || !user.IsActive {
		return nil, nil, fmt.Errorf("user inactive")
	}
	_ = s.Store.TouchSession(ctx, sess.SessionID)
	return user, sess, nil
}

func (s *Service) RequireActive(ctx context.Context, r *http.Request) (*User, *Session, error) {
	user, sess, err := s.SessionUser(ctx, r)
	if err != nil {
		return nil, nil, err
	}
	if user.MustChangePassword {
		return nil, nil, fmt.Errorf("must_change_password")
	}
	if sess != nil && mutating(r.Method) {
		token := r.Header.Get("X-CSRF-Token")
		if token == "" || subtle.ConstantTimeCompare([]byte(token), []byte(sess.CSRFToken)) != 1 {
			return nil, nil, fmt.Errorf("csrf")
		}
	}
	return user, sess, nil
}

func (s *Service) RequireApprover(ctx context.Context, r *http.Request) (*User, error) {
	user, _, err := s.RequireActive(ctx, r)
	if err != nil {
		return nil, err
	}
	switch user.Role {
	case "approver", "bucket_owner", "architect", "operations", "data_owner", "dbaas_reviewer":
		return user, nil
	default:
		return nil, fmt.Errorf("forbidden")
	}
}

func actorFromHeader(r *http.Request) string {
	if v := r.Header.Get("X-SSP-User"); v != "" {
		return strings.TrimSpace(v)
	}
	return ""
}

func mutating(m string) bool {
	switch m {
	case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
		return true
	default:
		return false
	}
}

func stringsTrimLower(s string) string {
	return strings.ToLower(strings.TrimSpace(s))
}
