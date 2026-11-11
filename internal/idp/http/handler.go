package http

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/vaishnavi4068/ssp-cp/internal/api/middleware"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/approval"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/intake"
)

type Handler struct {
	Intake   *intake.Service
	Approval *approval.Service
}

func (h *Handler) Mount(r chi.Router) {
	r.Route("/api/v1", func(r chi.Router) {
		r.Get("/healthz", func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":"ok","api":"idp"}`))
		})
		r.Get("/kinds", h.listKinds)
		r.Post("/submissions", h.createSubmission)
		r.Post("/submissions/spanner-stack", h.spanerStack)
		r.Post("/requests", h.createSubmission)
		r.Get("/requests/{requestID}", h.getRequest)
		r.Post("/approvals/{approvalID}/decisions", h.recordDecision)
		r.Post("/requests/{approvalID}/decisions", h.recordDecision)
		r.Post("/requests/{approvalID}/approve", h.recordDecisionApprove)
	})
}

func (h *Handler) listKinds(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"kinds": h.Intake.ListKinds()})
}

func (h *Handler) createSubmission(w http.ResponseWriter, r *http.Request) {
	var body intake.CreateRequest
	if err := decodeJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	out, err := h.Intake.SubmitCreate(r.Context(), body, actor(r))
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

func (h *Handler) spanerStack(w http.ResponseWriter, r *http.Request) {
	var body intake.SpannerStackRequest
	if err := decodeJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	out, err := h.Intake.SubmitSpannerStack(r.Context(), body, actor(r))
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

func (h *Handler) getRequest(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "requestID")
	out, err := h.Intake.GetRequest(r.Context(), id)
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

func (h *Handler) recordDecision(w http.ResponseWriter, r *http.Request) {
	approvalID := chi.URLParam(r, "approvalID")
	var body approval.DecisionInput
	if err := decodeJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	if body.Status == "" {
		body.Status = "approved"
	}
	out, err := h.Approval.RecordDecision(r.Context(), approvalID, body, actor(r))
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

func (h *Handler) recordDecisionApprove(w http.ResponseWriter, r *http.Request) {
	approvalID := chi.URLParam(r, "approvalID")
	body := approval.DecisionInput{Status: "approved"}
	out, err := h.Approval.RecordDecision(r.Context(), approvalID, body, actor(r))
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

func actor(r *http.Request) string {
	if v := r.Header.Get("X-SSP-User"); v != "" {
		return v
	}
	return "requester@example.com"
}

func decodeJSON(r *http.Request, dest any) error {
	defer r.Body.Close()
	lim := io.LimitReader(r.Body, 4<<20)
	dec := json.NewDecoder(lim)
	dec.DisallowUnknownFields()
	return dec.Decode(dest)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, err error) {
	if code == http.StatusNotFound {
		middleware.WriteProblem(w, code, "not_found", err.Error())
		return
	}
	if code == http.StatusUnprocessableEntity {
		middleware.WriteProblem(w, code, "validation_error", err.Error())
		return
	}
	middleware.WriteProblem(w, code, "error", err.Error())
}

func statusFromErr(err error) int {
	if err == nil {
		return http.StatusOK
	}
	msg := err.Error()
	if strings.Contains(msg, "not found") {
		return http.StatusNotFound
	}
	if strings.Contains(msg, "denied") || strings.Contains(msg, "must") || strings.Contains(msg, "invalid") || strings.Contains(msg, "GCS-") || strings.Contains(msg, "SPN-") {
		return http.StatusUnprocessableEntity
	}
	if errors.Is(err, errSequential) {
		return http.StatusConflict
	}
	if strings.Contains(msg, "earlier approver") {
		return http.StatusConflict
	}
	return http.StatusBadRequest
}

var errSequential = errors.New("sequential")
