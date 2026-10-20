package api

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
	"github.com/vaishnavi4068/ssp-cp/internal/api/handlers"
	"github.com/vaishnavi4068/ssp-cp/internal/api/middleware"
)

// NewHandler returns the control-plane HTTP handler.
// Generated operations are mounted at /v1 (SSP-API-001) and return 501.
// /healthz and /readyz report process liveness only; dependency checks are not implemented.
func NewHandler() http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.OTel)
	r.Use(middleware.Auth)
	r.Use(middleware.Persona)
	r.Use(middleware.Entitlement)
	r.Use(middleware.Idempotency)
	r.Use(middleware.RateLimit)
	r.Get("/healthz", health)
	r.Get("/readyz", health)

	strict := gen.NewStrictHandlerWithOptions(handlers.New(), nil, gen.StrictHTTPServerOptions{
		RequestErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			middleware.WriteProblem(w, http.StatusBadRequest, "bad_request", "Bad Request")
		},
		ResponseErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			if errors.Is(err, handlers.ErrNotImplemented) {
				middleware.WriteProblem(w, http.StatusNotImplemented, "not_implemented", "Not Implemented")
				return
			}
			middleware.WriteProblem(w, http.StatusInternalServerError, "internal", "Internal Server Error")
		},
	})
	return gen.HandlerWithOptions(strict, gen.ChiServerOptions{
		BaseURL:    "/v1",
		BaseRouter: r,
		ErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			middleware.WriteProblem(w, http.StatusBadRequest, "bad_request", "Bad Request")
		},
	})
}

func health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	if _, err := w.Write([]byte(`{"status":"ok"}`)); err != nil {
		return
	}
}
