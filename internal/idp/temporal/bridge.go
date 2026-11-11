package temporal

import (
	"context"
	"encoding/json"
	"log"
	"os"
)

// ProvisionPayload mirrors the Python temporal_bridge contract for GcsBucketProvisionWorkflow.
type ProvisionPayload struct {
	RequestID           string          `json:"request_id"`
	ApprovalID          string          `json:"approval_id"`
	ResourceID          string          `json:"resource_id"`
	StateUnitID         string          `json:"state_unit_id"`
	ProjectID           string          `json:"project_id"`
	Action              string          `json:"action"`
	ApprovedSpec        json.RawMessage `json:"approved_spec"`
	ApprovedSpecSHA256  string          `json:"approved_spec_sha256"`
	TriggeredBy         string          `json:"triggered_by"`
	StateBucket         string          `json:"state_bucket"`
}

// Bridge starts downstream Temporal workflows when approvals complete.
type Bridge struct {
	Enabled   bool
	Workflow  string
	Namespace string
	TaskQueue string
}

func NewBridge() *Bridge {
	return &Bridge{
		Enabled:   os.Getenv("SSP_TEMPORAL_ENABLED") == "true",
		Workflow:  envOr("SSP_TEMPORAL_GCS_WORKFLOW", "GcsBucketProvisionWorkflow"),
		Namespace: envOr("SSP_TEMPORAL_NAMESPACE", "ssp"),
		TaskQueue: envOr("SSP_TEMPORAL_TASK_QUEUE", "ssp-control"),
	}
}

func (b *Bridge) StartProvision(ctx context.Context, p ProvisionPayload) error {
	if !b.Enabled {
		log.Printf("temporal: offline mode; would start %s req-%s", b.Workflow, p.RequestID)
		return nil
	}
	// Temporal wire-up lands with sqlc + worker registration; payload is logged for audit until then.
	_, _ = json.Marshal(p)
	log.Printf("temporal: start %s workflow_id=req-%s (not yet connected)", b.Workflow, p.RequestID)
	return nil
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
