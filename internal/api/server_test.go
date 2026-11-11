package api

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// SSP-API-001 operations are served under /v1.
// SSP-API-003 unimplemented operations return an RFC 9457 problem with status 501.
// SSP-API-005 every response carries X-Request-Id.
func TestOperationsReturn501(t *testing.T) {
	srv := httptest.NewServer(NewHandler())
	t.Cleanup(srv.Close)

	ops := []struct {
		method string
		path   string
	}{
		{http.MethodGet, "/v1/catalog/services"},
		{http.MethodGet, "/v1/catalog/services/gcp.bucket"},
		{http.MethodGet, "/v1/catalog/services/gcp.bucket/versions/1.0.0"},
		{http.MethodGet, "/v1/destinations"},
		{http.MethodGet, "/v1/destinations/tenant/context"},
		{http.MethodPost, "/v1/orders/preflight"},
		{http.MethodPost, "/v1/orders"},
		{http.MethodGet, "/v1/orders"},
		{http.MethodGet, "/v1/orders/ord_01ARZ3NDEKTSV4RRFFQ69G5FAV"},
		{http.MethodGet, "/v1/orders/ord_01ARZ3NDEKTSV4RRFFQ69G5FAV/events"},
		{http.MethodGet, "/v1/orders/ord_01ARZ3NDEKTSV4RRFFQ69G5FAV/code"},
		{http.MethodPost, "/v1/orders/ord_01ARZ3NDEKTSV4RRFFQ69G5FAV/cancel"},
		{http.MethodPost, "/v1/orders/ord_01ARZ3NDEKTSV4RRFFQ69G5FAV/signoff"},
		{http.MethodGet, "/v1/tenants/tenant/resources"},
		{http.MethodGet, "/v1/resources/ri"},
		{http.MethodGet, "/v1/tenants/tenant/drift"},
		{http.MethodGet, "/v1/runs?tenant_id=tenant"},
		{http.MethodGet, "/v1/runs/run"},
		{http.MethodGet, "/v1/runs/run/logs"},
		{http.MethodPost, "/v1/runs/run/retry"},
		{http.MethodGet, "/v1/ops/fleet"},
		{http.MethodGet, "/v1/ops/tenants"},
		{http.MethodPost, "/v1/ops/controls/pause"},
		{http.MethodPost, "/v1/ops/controls/resume"},
		{http.MethodPost, "/v1/ops/controls/killswitch"},
		{http.MethodPost, "/v1/ops/tenants/tenant/reconcile"},
		{http.MethodPost, "/v1/ops/tenants/tenant/drift-scan"},
		{http.MethodPost, "/v1/ops/tenants/tenant/break-glass"},
		{http.MethodPost, "/v1/imports"},
		{http.MethodGet, "/v1/imports/imp"},
		{http.MethodPut, "/v1/imports/imp/mapping"},
		{http.MethodPost, "/v1/imports/imp/dry-run"},
		{http.MethodPost, "/v1/imports/imp/execute"},
		{http.MethodPost, "/v1/assistant/conversations"},
		{http.MethodPost, "/v1/assistant/conversations/conv/messages"},
	}
	if len(ops) != 35 {
		t.Fatalf("expected 35 operations, got %d", len(ops))
	}

	for _, op := range ops {
		t.Run(op.method+" "+op.path, func(t *testing.T) {
			var body io.Reader
			if op.method != http.MethodGet {
				body = strings.NewReader(`{}`)
			}
			req, err := http.NewRequest(op.method, srv.URL+op.path, body)
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Idempotency-Key", "scaffold")
			if body != nil {
				req.Header.Set("Content-Type", "application/json")
			}
			res, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() {
				if err := res.Body.Close(); err != nil {
					t.Errorf("close body: %v", err)
				}
			})
			if res.StatusCode != http.StatusNotImplemented {
				b, readErr := io.ReadAll(res.Body)
				if readErr != nil {
					t.Fatal(readErr)
				}
				t.Fatalf("status %d, want 501, body %s", res.StatusCode, b)
			}
			if got := res.Header.Get("X-Request-Id"); got == "" {
				t.Fatal("missing X-Request-Id")
			}
			if ct := res.Header.Get("Content-Type"); !strings.Contains(ct, "application/problem+json") {
				t.Fatalf("content-type %q", ct)
			}
			var problem struct {
				Type   string `json:"type"`
				Title  string `json:"title"`
				Status int    `json:"status"`
			}
			if err := json.NewDecoder(res.Body).Decode(&problem); err != nil {
				t.Fatal(err)
			}
			if problem.Status != http.StatusNotImplemented || problem.Type != "https://ssp/errors/not_implemented" {
				t.Fatalf("problem %+v", problem)
			}
		})
	}
}

func TestHealth(t *testing.T) {
	srv := httptest.NewServer(NewHandler())
	t.Cleanup(srv.Close)
	for _, path := range []string{"/healthz", "/readyz"} {
		res, err := http.Get(srv.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() {
			if err := res.Body.Close(); err != nil {
				t.Errorf("close body: %v", err)
			}
		})
		if res.StatusCode != http.StatusOK {
			t.Fatalf("%s status %d", path, res.StatusCode)
		}
		if res.Header.Get("X-Request-Id") == "" {
			t.Fatalf("%s missing X-Request-Id", path)
		}
	}
}
