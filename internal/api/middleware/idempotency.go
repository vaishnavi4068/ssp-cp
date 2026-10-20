package middleware

import "net/http"

// Idempotency is a scaffold pass-through. Idempotency-Key replay is not implemented.
func Idempotency(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
	})
}
