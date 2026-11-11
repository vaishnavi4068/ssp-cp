package http

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/vaishnavi4068/ssp-cp/internal/idp/localauth"
)

type AuthHandlers struct {
	Auth *localauth.Service
}

func (a *AuthHandlers) mountPublic(r chiRouter) {
	if a == nil || a.Auth == nil {
		return
	}
	r.Post("/auth/login", a.login)
	r.Post("/auth/logout", a.logout)
}

func (a *AuthHandlers) mountProtected(r chiRouter) {
	if a == nil || a.Auth == nil {
		return
	}
	r.Get("/auth/me", a.me)
	r.Post("/auth/change-password", a.changePassword)
	r.Post("/auth/unlock", a.unlockUser)
}

type chiRouter interface {
	Get(pattern string, h http.HandlerFunc)
	Post(pattern string, h http.HandlerFunc)
}

func (a *AuthHandlers) login(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	ip := clientIP(r)
	profile, sess, err := a.Auth.Login(r.Context(), body.Username, body.Password, ip)
	if err != nil {
		if strings.Contains(err.Error(), "rate") {
			writeErr(w, http.StatusTooManyRequests, err)
			return
		}
		writeErr(w, http.StatusUnauthorized, err)
		return
	}
	setSessionCookie(w, a.Auth.Config, sess.SessionID)
	writeJSON(w, http.StatusOK, profile)
}

func (a *AuthHandlers) logout(w http.ResponseWriter, r *http.Request) {
	cookie, err := r.Cookie(a.Auth.Config.CookieName)
	if err == nil && cookie.Value != "" {
		_ = a.Auth.Store.RevokeSession(r.Context(), cookie.Value)
	}
	clearSessionCookie(w, a.Auth.Config)
	w.WriteHeader(http.StatusNoContent)
}

func (a *AuthHandlers) me(w http.ResponseWriter, r *http.Request) {
	user, sess, err := a.Auth.SessionUser(r.Context(), r)
	if err != nil {
		writeErr(w, http.StatusUnauthorized, err)
		return
	}
	csrf := ""
	if sess != nil {
		csrf = sess.CSRFToken
	}
	writeJSON(w, http.StatusOK, localauth.Profile{
		Username: user.Username, Email: user.Email, DisplayName: user.DisplayName, Role: user.Role,
		MustChangePassword: user.MustChangePassword, CSRFToken: csrf,
	})
}

func (a *AuthHandlers) changePassword(w http.ResponseWriter, r *http.Request) {
	user, sess, err := a.Auth.SessionUser(r.Context(), r)
	if err != nil {
		writeErr(w, http.StatusUnauthorized, err)
		return
	}
	if sess != nil {
		if token := r.Header.Get("X-CSRF-Token"); token == "" || token != sess.CSRFToken {
			writeErr(w, http.StatusForbidden, errCSRF)
			return
		}
	}
	var body struct {
		CurrentPassword string `json:"current_password"`
		NewPassword     string `json:"new_password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	if !localauth.VerifyPassword(user.PasswordHash, body.CurrentPassword) {
		writeErr(w, http.StatusUnauthorized, errBadPassword)
		return
	}
	hash, err := localauth.HashPassword(body.NewPassword)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err)
		return
	}
	if err := a.Auth.Store.UpdatePassword(r.Context(), user.Username, hash); err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
}

func (a *AuthHandlers) unlockUser(w http.ResponseWriter, r *http.Request) {
	_, _, err := a.Auth.RequireActive(r.Context(), r)
	if err != nil {
		writeErr(w, http.StatusUnauthorized, err)
		return
	}
	var body struct {
		Username string `json:"username"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	if err := a.Auth.Store.UnlockUser(r.Context(), body.Username); err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
}

func setSessionCookie(w http.ResponseWriter, cfg localauth.Config, sessionID string) {
	http.SetCookie(w, &http.Cookie{
		Name: cfg.CookieName, Value: sessionID, Path: "/",
		HttpOnly: true, Secure: cfg.CookieSecure, SameSite: http.SameSiteLaxMode,
	})
}

func clearSessionCookie(w http.ResponseWriter, cfg localauth.Config) {
	http.SetCookie(w, &http.Cookie{
		Name: cfg.CookieName, Value: "", Path: "/", MaxAge: -1, HttpOnly: true, Secure: cfg.CookieSecure,
	})
}

func clientIP(r *http.Request) string {
	if x := r.Header.Get("X-Forwarded-For"); x != "" {
		parts := strings.Split(x, ",")
		return strings.TrimSpace(parts[0])
	}
	return strings.Split(r.RemoteAddr, ":")[0]
}

var errCSRF = fmtError("invalid csrf token")
var errBadPassword = fmtError("invalid current password")

func fmtError(s string) error { return &simpleErr{s: s} }

type simpleErr struct{ s string }

func (e *simpleErr) Error() string { return e.s }
