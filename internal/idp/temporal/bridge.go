package temporal

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"sync"

	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
)

// ProvisionPayload mirrors the Python temporal_bridge contract for GcsBucketProvisionWorkflow.
type ProvisionPayload struct {
	RequestID          string          `json:"request_id"`
	ApprovalID         string          `json:"approval_id"`
	ResourceID         string          `json:"resource_id"`
	StateUnitID        string          `json:"state_unit_id"`
	ProjectID          string          `json:"project_id"`
	Action             string          `json:"action"`
	ApprovedSpec       json.RawMessage `json:"approved_spec"`
	ApprovedSpecSHA256 string          `json:"approved_spec_sha256"`
	TriggeredBy        string          `json:"triggered_by"`
	StateBucket        string          `json:"state_bucket"`
}

// Bridge starts downstream Temporal workflows when approvals complete (ssp-workers).
type Bridge struct {
	Enabled   bool
	Workflow  string
	Namespace string
	TaskQueue string
	Address   string

	mu     sync.Mutex
	client client.Client
}

func NewBridge() *Bridge {
	return &Bridge{
		Enabled:   os.Getenv("SSP_TEMPORAL_ENABLED") == "true",
		Workflow:  envOr("SSP_TEMPORAL_GCS_WORKFLOW", "GcsBucketProvisionWorkflow"),
		Namespace: envOr("SSP_TEMPORAL_NAMESPACE", "ssp"),
		TaskQueue: envOr("SSP_TEMPORAL_TASK_QUEUE", "ssp-control"),
		Address:   envOr("SSP_TEMPORAL_ADDRESS", "localhost:7233"),
	}
}

func (b *Bridge) StartProvision(ctx context.Context, p ProvisionPayload) error {
	workflowID := "req-" + p.RequestID
	if !b.Enabled {
		log.Printf("temporal: offline mode; would start %s %s", b.Workflow, workflowID)
		return nil
	}
	c, err := b.getClient(ctx)
	if err != nil {
		log.Printf("temporal: unreachable (%v); audit-only mode for %s", err, workflowID)
		return nil
	}
	opts := client.StartWorkflowOptions{ID: workflowID, TaskQueue: b.TaskQueue}
	_, err = c.ExecuteWorkflow(ctx, opts, b.Workflow, map[string]any{
		"request_id": p.RequestID, "approval_id": p.ApprovalID, "resource_id": p.ResourceID,
		"state_unit_id": p.StateUnitID, "project_id": p.ProjectID, "action": p.Action,
		"approved_spec": json.RawMessage(p.ApprovedSpec), "approved_spec_sha256": p.ApprovedSpecSHA256,
		"triggered_by": p.TriggeredBy, "state_bucket": p.StateBucket,
	})
	if err != nil {
		var started *serviceerror.WorkflowExecutionAlreadyStarted
		if errors.As(err, &started) {
			log.Printf("temporal: %s already started", workflowID)
			return nil
		}
		return fmt.Errorf("temporal start %s: %w", b.Workflow, err)
	}
	log.Printf("temporal: started %s workflow_id=%s", b.Workflow, workflowID)
	return nil
}

func (b *Bridge) getClient(ctx context.Context) (client.Client, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.client != nil {
		return b.client, nil
	}
	c, err := client.DialContext(ctx, client.Options{HostPort: b.Address, Namespace: b.Namespace})
	if err != nil {
		return nil, err
	}
	b.client = c
	return c, nil
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
