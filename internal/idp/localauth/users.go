package localauth

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/alexedwards/argon2id"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/vaishnavi4068/ssp-cp/internal/store/db"
)

type User struct {
	Username           string
	Email              string
	DisplayName        string
	Role               string
	PasswordHash       string
	MustChangePassword bool
	FailedLoginAttempts int
	LockedUntil        *time.Time
	IsActive           bool
}

type Session struct {
	SessionID string
	Username  string
	CSRFToken string
	CreatedAt time.Time
	LastSeen  time.Time
	ExpiresAt time.Time
	Revoked   bool
}

type Store interface {
	GetUser(ctx context.Context, username string) (*User, error)
	UpsertUser(ctx context.Context, u User) error
	UpdateUserAfterLogin(ctx context.Context, username string, success bool, maxAttempts int, lockoutSec int) error
	UnlockUser(ctx context.Context, username string) error
	UpdatePassword(ctx context.Context, username, hash string) error
	CreateSession(ctx context.Context, s Session) error
	GetSession(ctx context.Context, sessionID string) (*Session, error)
	RevokeSession(ctx context.Context, sessionID string) error
	TouchSession(ctx context.Context, sessionID string) error
	InsertAudit(ctx context.Context, actor, role, ip, action, reason string, details map[string]any) error
}

type MemoryStore struct {
	mu       sync.RWMutex
	users    map[string]*User
	sessions map[string]*Session
}

func NewMemoryStore(cfg Config) *MemoryStore {
	m := &MemoryStore{users: map[string]*User{}, sessions: map[string]*Session{}}
	for _, u := range initialUsers {
		pw := resolveBootstrapPassword(cfg, u.Username, u.SecretKey)
		hash, _ := argon2id.CreateHash(pw, argon2id.DefaultParams)
		m.users[u.Username] = &User{
			Username: u.Username, Email: u.Email, DisplayName: u.DisplayName, Role: u.Role,
			PasswordHash: hash, MustChangePassword: true, IsActive: true,
		}
	}
	return m
}

type pgStore struct{ q *db.Queries }

func NewPGStore(q *db.Queries) Store { return &pgStore{q: q} }

func (m *MemoryStore) GetUser(_ context.Context, username string) (*User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	u, ok := m.users[username]
	if !ok {
		return nil, fmt.Errorf("user not found")
	}
	cp := *u
	return &cp, nil
}

func (m *MemoryStore) UpsertUser(_ context.Context, u User) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.users[u.Username] = &u
	return nil
}

func (m *MemoryStore) UpdateUserAfterLogin(_ context.Context, username string, success bool, maxAttempts, lockoutSec int) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	u := m.users[username]
	if u == nil {
		return fmt.Errorf("user not found")
	}
	if success {
		u.FailedLoginAttempts = 0
		u.LockedUntil = nil
		return nil
	}
	u.FailedLoginAttempts++
	if u.FailedLoginAttempts >= maxAttempts {
		t := time.Now().UTC().Add(time.Duration(lockoutSec) * time.Second)
		u.LockedUntil = &t
	}
	return nil
}

func (m *MemoryStore) UnlockUser(_ context.Context, username string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	u := m.users[username]
	if u == nil {
		return fmt.Errorf("user not found")
	}
	u.FailedLoginAttempts = 0
	u.LockedUntil = nil
	return nil
}

func (m *MemoryStore) UpdatePassword(_ context.Context, username, hash string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	u := m.users[username]
	if u == nil {
		return fmt.Errorf("user not found")
	}
	u.PasswordHash = hash
	u.MustChangePassword = false
	return nil
}

func (m *MemoryStore) CreateSession(_ context.Context, s Session) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	cp := s
	m.sessions[s.SessionID] = &cp
	return nil
}

func (m *MemoryStore) GetSession(_ context.Context, sessionID string) (*Session, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	s, ok := m.sessions[sessionID]
	if !ok {
		return nil, fmt.Errorf("session not found")
	}
	cp := *s
	return &cp, nil
}

func (m *MemoryStore) RevokeSession(_ context.Context, sessionID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if s, ok := m.sessions[sessionID]; ok {
		s.Revoked = true
	}
	return nil
}

func (m *MemoryStore) TouchSession(_ context.Context, sessionID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if s, ok := m.sessions[sessionID]; ok {
		s.LastSeen = time.Now().UTC()
	}
	return nil
}

func (m *MemoryStore) InsertAudit(_ context.Context, actor, role, ip, action, reason string, details map[string]any) error {
	_ = actor
	return nil
}

// pgStore methods - stub minimal; full impl via sqlc in auth_handlers flow using Queries directly where needed

func (p *pgStore) GetUser(ctx context.Context, username string) (*User, error) {
	row, err := p.q.GetCpUserByUsername(ctx, username)
	if err != nil {
		return nil, err
	}
	var locked *time.Time
	if row.LockedUntil.Valid {
		t := row.LockedUntil.Time
		locked = &t
	}
	return &User{
		Username: row.Username, Email: row.Email, DisplayName: row.DisplayName, Role: row.Role,
		PasswordHash: row.PasswordHash, MustChangePassword: row.MustChangePassword,
		FailedLoginAttempts: int(row.FailedLoginAttempts), LockedUntil: locked, IsActive: row.IsActive,
	}, nil
}

func (p *pgStore) UpsertUser(ctx context.Context, u User) error {
	return p.q.UpsertCpUserBootstrap(ctx, db.UpsertCpUserBootstrapParams{
		Username: u.Username, Email: u.Email, DisplayName: u.DisplayName, Role: u.Role, PasswordHash: u.PasswordHash,
	})
}

func (p *pgStore) UpdateUserAfterLogin(ctx context.Context, username string, success bool, maxAttempts, lockoutSec int) error {
	if success {
		return p.q.UpdateCpUserLoginSuccess(ctx, username)
	}
	return p.q.UpdateCpUserLoginFailure(ctx, db.UpdateCpUserLoginFailureParams{
		Username: username, MaxAttempts: int32(maxAttempts), LockoutSeconds: int32(lockoutSec),
	})
}

func (p *pgStore) UnlockUser(ctx context.Context, username string) error {
	return p.q.UnlockCpUser(ctx, username)
}

func (p *pgStore) UpdatePassword(ctx context.Context, username, hash string) error {
	return p.q.UpdateCpUserPassword(ctx, db.UpdateCpUserPasswordParams{Username: username, PasswordHash: hash})
}

func (p *pgStore) CreateSession(ctx context.Context, s Session) error {
	_, err := p.q.InsertSession(ctx, db.InsertSessionParams{
		SessionID: s.SessionID, Username: s.Username, CsrfToken: s.CSRFToken, ExpiresAt: pgTime(s.ExpiresAt),
	})
	return err
}

func (p *pgStore) GetSession(ctx context.Context, sessionID string) (*Session, error) {
	row, err := p.q.GetSession(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	return &Session{
		SessionID: row.SessionID, Username: row.Username, CSRFToken: row.CsrfToken,
		CreatedAt: row.CreatedAt.Time, LastSeen: row.LastSeenAt.Time, ExpiresAt: row.ExpiresAt.Time, Revoked: row.Revoked,
	}, nil
}

func (p *pgStore) RevokeSession(ctx context.Context, sessionID string) error {
	return p.q.RevokeSession(ctx, sessionID)
}

func (p *pgStore) TouchSession(ctx context.Context, sessionID string) error {
	return p.q.TouchSession(ctx, sessionID)
}

func (p *pgStore) InsertAudit(ctx context.Context, actor, role, ip, action, reason string, details map[string]any) error {
	b, _ := jsonMarshal(details)
	_, err := p.q.InsertAuditLog(ctx, db.InsertAuditLogParams{
		ActorUsername: actor, ActorRole: role, SourceIp: ip, ActionType: action, Reason: reason, Details: b,
	})
	return err
}

func pgTime(t time.Time) pgtype.Timestamptz { return pgtype.Timestamptz{Time: t, Valid: true} }

// fix pgTime - should use pgtype.Timestamptz

type initialUser struct {
	Username, Email, DisplayName, Role, SecretKey string
}

var initialUsers = []initialUser{
	{"manoj", "manoj@example.com", "Manoj (Architect)", "architect", "manoj"},
	{"dwayne", "dwayne@example.com", "Dwayne (Approver)", "approver", "dwayne"},
	{"norm", "norm@example.com", "Norm (Approver / Operations)", "approver", "norm"},
	{"bucket_owner", "bucket.owner@example.com", "Bucket Owner", "bucket_owner", "bucket_owner"},
	{"requester", "requester@example.com", "Developer Requester", "developer", "requester"},
}

func resolveBootstrapPassword(cfg Config, username, secretKey string) string {
	key := secretKey
	if key == "" {
		key = username
	}
	names := []string{
		fmt.Sprintf("spp-cp-bootstrap-%s", key),
		fmt.Sprintf("spp-cp-bootstrap-%s", username),
	}
	for _, n := range names {
		p := filepath.Join(cfg.BootstrapSecretsDir, n)
		if b, err := os.ReadFile(p); err == nil && len(b) > 0 {
			return string(b)
		}
	}
	if !cfg.AllowDefaultBootstrapPasswords {
		return ""
	}
	return fmt.Sprintf("SppFactory!%s2026", capFirst(username))
}

func capFirst(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

func VerifyPassword(hash, plain string) bool {
	ok, err := argon2id.ComparePasswordAndHash(plain, hash)
	return err == nil && ok
}

func HashPassword(plain string) (string, error) {
	return argon2id.CreateHash(plain, argon2id.DefaultParams)
}

func NewSessionID() string { return uuid.NewString() }

func NewCSRFToken() string { return uuid.NewString() }

func jsonMarshal(v any) ([]byte, error) {
	if v == nil {
		return []byte("{}"), nil
	}
	return json.Marshal(v)
}
