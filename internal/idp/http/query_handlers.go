package http

import (
	"fmt"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/intake"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/store"
)

// QueryHandler serves read/list endpoints matching Python main.py.
type QueryHandler struct {
	Backend store.Backend
	Intake  *intake.Service
}

func (q *QueryHandler) mount(r chi.Router) {
	r.Get("/requests", q.listRequests)
	r.Get("/approvals", q.listApprovals)
	r.Get("/approvals/{approvalID}", q.getApproval)
	r.Get("/resources", q.listResources)
	r.Get("/status", q.listResources)
	r.Get("/resources/{resourceID}", q.getResource)
	r.Post("/state-units/{stateUnitID}/freeze", q.freezeStateUnit)
	r.Post("/state-units/{stateUnitID}/unfreeze", q.unfreezeStateUnit)
}

func (q *QueryHandler) listRequests(w http.ResponseWriter, r *http.Request) {
	kind := r.URL.Query().Get("kind")
	status := r.URL.Query().Get("status")
	ids, err := q.Backend.ListRequestIDs(r.Context(), kind, status)
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	items := make([]map[string]any, 0, len(ids))
	for _, id := range ids {
		d, err := q.Intake.GetRequest(r.Context(), id)
		if err != nil {
			continue
		}
		items = append(items, d)
	}
	writeJSON(w, http.StatusOK, map[string]any{"requests": items})
}

func (q *QueryHandler) listApprovals(w http.ResponseWriter, r *http.Request) {
	status := r.URL.Query().Get("status")
	ids, err := q.Backend.ListApprovalIDs(r.Context(), status)
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	var items []map[string]any
	for _, id := range ids {
		apr, err := q.Backend.GetApproval(r.Context(), id)
		if err != nil {
			continue
		}
		detail, _ := q.Intake.GetRequest(r.Context(), apr.RequestID)
		if detail == nil {
			continue
		}
		if a, ok := detail["approval"].(map[string]any); ok {
			a["request_id"] = apr.RequestID
			items = append(items, a)
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"approvals": items})
}

func (q *QueryHandler) getApproval(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "approvalID")
	apr, err := q.Backend.GetApproval(r.Context(), id)
	if err != nil {
		// Python also accepts request_id on this path.
		req, err2 := q.Intake.GetRequest(r.Context(), id)
		if err2 != nil {
			writeErr(w, http.StatusNotFound, err)
			return
		}
		writeJSON(w, http.StatusOK, req)
		return
	}
	detail, err := q.Intake.GetRequest(r.Context(), apr.RequestID)
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusOK, detail)
}

func (q *QueryHandler) listResources(w http.ResponseWriter, r *http.Request) {
	rows, err := q.Backend.ListResourceStatus(r.Context(), "")
	if err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"resources": rows})
}

func (q *QueryHandler) getResource(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "resourceID")
	rows, err := q.Backend.ListResourceStatus(r.Context(), id)
	if err != nil || len(rows) == 0 {
		writeErr(w, http.StatusNotFound, fmt.Errorf("resource not found"))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": rows[0], "observed": nil, "drift_findings": []any{}})
}

func (q *QueryHandler) freezeStateUnit(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "stateUnitID")
	if err := q.Backend.SetStateUnitStatus(r.Context(), id, "frozen"); err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	su, _ := q.Backend.StateUnitByID(r.Context(), id)
	writeJSON(w, http.StatusOK, map[string]any{"state_unit_id": id, "scope_id": su.ScopeID, "status": "frozen"})
}

func (q *QueryHandler) unfreezeStateUnit(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "stateUnitID")
	if err := q.Backend.SetStateUnitStatus(r.Context(), id, "active"); err != nil {
		writeErr(w, statusFromErr(err), err)
		return
	}
	su, _ := q.Backend.StateUnitByID(r.Context(), id)
	writeJSON(w, http.StatusOK, map[string]any{"state_unit_id": id, "scope_id": su.ScopeID, "status": "active"})
}
