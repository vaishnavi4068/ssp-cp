package middleware

import "net/http"

// RateLimit is a scaffold pass-through. Rate limits are not implemented.
func RateLimit(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
	})
}
