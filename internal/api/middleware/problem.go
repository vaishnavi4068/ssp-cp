package middleware

import (
	"encoding/json"
	"net/http"
)

// Problem is an RFC 9457 problem detail. SSP-API-003.
type Problem struct {
	Type   string `json:"type"`
	Title  string `json:"title"`
	Status int    `json:"status"`
}

// WriteProblem writes an application/problem+json body and status.
func WriteProblem(w http.ResponseWriter, status int, code, title string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(Problem{
		Type:   "https://ssp/errors/" + code,
		Title:  title,
		Status: status,
	}); err != nil {
		return
	}
}
