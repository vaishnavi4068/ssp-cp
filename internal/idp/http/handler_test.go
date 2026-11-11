package http_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/vaishnavi4068/ssp-cp/internal/idp"
)

func TestMain(m *testing.M) {
	_ = os.Setenv("SSP_OPA_SKIP", "true")
	os.Exit(m.Run())
}

func TestGCSIntakeAndApprove(t *testing.T) {
	stack := idp.NewStack()
	r := chi.NewRouter()
	stack.HTTP.Mount(r)

	payload := map[string]any{
		"api_version": "idp.spp/v1",
		"kind":        "gcs_bucket",
		"action":      "create",
		"metadata": map[string]any{
			"apm_id": "apm12345", "project_id": "spp-nonprod-orders-svc",
			"environment": "nonprod", "lob": "spp", "owner": "bucket.owner@example.com",
			"labels": map[string]any{"app": "orders"},
		},
		"spec": map[string]any{
			"name": "spp-nonprod-orders-landing-a1b2", "location": "us-east1",
			"storage_class": "STANDARD", "versioning": false,
		},
	}
	b, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/submissions", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("submit status=%d body=%s", rec.Code, rec.Body.String())
	}
	var created map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	approval := created["approval"].(map[string]any)
	approvalID := approval["approval_id"].(string)

	dec := map[string]any{"status": "approved", "approver_key": "bucket_owner"}
	db, _ := json.Marshal(dec)
	apReq := httptest.NewRequest(http.MethodPost, "/api/v1/approvals/"+approvalID+"/decisions", bytes.NewReader(db))
	apReq.Header.Set("Content-Type", "application/json")
	apReq.Header.Set("X-SSP-User", "bucket.owner@example.com")
	apRec := httptest.NewRecorder()
	r.ServeHTTP(apRec, apReq)
	if apRec.Code != http.StatusOK {
		t.Fatalf("approve status=%d body=%s", apRec.Code, apRec.Body.String())
	}
}

func TestSpannerStackIntake(t *testing.T) {
	stack := idp.NewStack()
	r := chi.NewRouter()
	stack.HTTP.Mount(r)

	payload := map[string]any{
		"template": "spanner-instance-with-databases",
		"resources": []map[string]any{
			{
				"kind": "spanner_instance",
				"metadata": map[string]any{
					"apm_id": "apm00172", "project_id": "spp-nonprod-orders-svc",
					"environment": "nonprod", "lob": "spp", "owner": "owner@example.com",
					"labels": map[string]any{"app": "orders"},
				},
				"spec": map[string]any{"name": "spp-nonprod-orders", "compute": map[string]any{"processing_units": 100}},
			},
			{
				"kind": "spanner_database",
				"metadata": map[string]any{"apm_id": "apm00172", "project_id": "spp-nonprod-orders-svc", "environment": "nonprod"},
				"spec":   map[string]any{"instance": "spp-nonprod-orders", "name": "orders"},
			},
		},
	}
	b, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/submissions/spanner-stack", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}
