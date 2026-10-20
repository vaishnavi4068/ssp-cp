package middleware

import "net/http"

// OTel is a scaffold pass-through. Spans are not started.
func OTel(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
	})
}
