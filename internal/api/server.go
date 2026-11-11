package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"os"

	"github.com/go-chi/chi/v5"
	"github.com/vaishnavi4068/ssp-cp/internal/api/gen"
	"github.com/vaishnavi4068/ssp-cp/internal/api/handlers"
	"github.com/vaishnavi4068/ssp-cp/internal/assistant"
	"github.com/vaishnavi4068/ssp-cp/internal/api/middleware"
	"github.com/vaishnavi4068/ssp-cp/internal/idp"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/store"
)

// NewHandler returns the control-plane HTTP handler.
// Generated operations are mounted at /v1 (SSP-API-001) and return 501.
// Legacy idp HTTP lives at /api/v1 (see internal/idp).
// /healthz and /readyz report process liveness only; dependency checks are not implemented.
func NewHandler() http.Handler {
	r := chi.NewRouter()
	if cors := os.Getenv("SSP_CORS_ORIGINS"); cors != "" {
		r.Use(middleware.CORS(cors))
	}
	r.Use(middleware.RequestID)
	r.Use(middleware.OTel)
	r.Use(middleware.Auth)
	r.Use(middleware.Persona)
	r.Use(middleware.Entitlement)
	r.Use(middleware.Idempotency)
	r.Use(middleware.RateLimit)
	r.Get("/healthz", rootHealth)
	idpStack := idp.NewStack()
	r.Get("/readyz", readyHandler(idpStack.Backend))
	idpStack.HTTP.Mount(r)

	strict := gen.NewStrictHandlerWithOptions(handlers.New(), nil, gen.StrictHTTPServerOptions{
		RequestErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			middleware.WriteProblem(w, http.StatusBadRequest, "bad_request", "Bad Request")
		},
		ResponseErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, err error) {
			if errors.Is(err, handlers.ErrNotImplemented) {
				middleware.WriteProblem(w, http.StatusNotImplemented, "not_implemented", "Not Implemented")
				return
			}
			if errors.Is(err, assistant.ErrUnavailable) {
				middleware.WriteProblem(w, http.StatusServiceUnavailable, "assistant_unavailable", "Sidekick is disabled. Set SSP_ASSISTANT_ENABLED=true and SSP_ASSISTANT_API_KEY in local-dev/.env (see ssp-doc/local-dev/README.md).")
				return
			}
			if errors.Is(err, handlers.ErrBadRequest) {
				middleware.WriteProblem(w, http.StatusBadRequest, "bad_request", "Bad Request")
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

func rootHealth(w http.ResponseWriter, r *http.Request) {
	writeHealth(w, http.StatusOK, map[string]any{"status": "ok", "service": "ssp-cp"})
}

func readyHandler(b store.Backend) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if b == nil {
			writeHealth(w, http.StatusServiceUnavailable, map[string]any{"status": "not_ready"})
			return
		}
		if err := b.Ready(r.Context()); err != nil {
			writeHealth(w, http.StatusServiceUnavailable, map[string]any{"status": "not_ready", "error": err.Error()})
			return
		}
		writeHealth(w, http.StatusOK, map[string]any{"status": "ready"})
	}
}

func writeHealth(w http.ResponseWriter, code int, payload map[string]any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(payload)
}
