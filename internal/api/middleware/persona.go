package middleware

import "net/http"

// Persona is a scaffold pass-through. Persona checks are not implemented.
func Persona(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
	})
}
