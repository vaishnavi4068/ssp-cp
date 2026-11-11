package middleware

import "net/http"

// Entitlement is a scaffold pass-through. Entitlement checks are not implemented.
func Entitlement(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
	})
}
