package http

import (
	"context"
	"net/http"

	"github.com/vaishnavi4068/ssp-cp/internal/idp/localauth"
)

type ctxKey int

const ctxUserKey ctxKey = 1

func (h *Handler) requireActive(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if h.Auth == nil {
			next.ServeHTTP(w, r)
			return
		}
		user, _, err := h.Auth.RequireActive(r.Context(), r)
		if err != nil {
			if err.Error() == "must_change_password" && r.URL.Path != "/api/v1/auth/change-password" {
				writeErr(w, http.StatusForbidden, err)
				return
			}
			if err.Error() == "csrf" {
				writeErr(w, http.StatusForbidden, err)
				return
			}
			writeErr(w, http.StatusUnauthorized, err)
			return
		}
		ctx := context.WithValue(r.Context(), ctxUserKey, user)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func userFromContext(r *http.Request) *localauth.User {
	if u, ok := r.Context().Value(ctxUserKey).(*localauth.User); ok {
		return u
	}
	return nil
}
