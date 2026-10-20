package middleware

import "net/http"

// Auth is a scaffold pass-through. JWT verification is not implemented.
func Auth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
	})
}
