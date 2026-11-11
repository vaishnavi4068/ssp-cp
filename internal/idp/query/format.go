package query

import (
	"encoding/json"
	"time"

	"github.com/vaishnavi4068/ssp-cp/internal/idp/store"
)

// FormatRequestDetail matches Python get_request_detail shape (core fields).
func FormatRequestDetail(b *store.RequestBundle) map[string]any {
	if b == nil || b.Request == nil {
		return nil
	}
	req := b.Request
	var doc map[string]any
	_ = json.Unmarshal(req.RequestedSpec, &doc)
	out := map[string]any{
		"request_id": req.ID, "submission_id": req.SubmissionID, "resource_id": req.ResourceID,
		"kind": req.Kind, "action": req.Action, "schema_version": req.SchemaVersion,
		"status": req.Status, "status_reason": req.StatusReason, "requested_by": req.RequestedBy,
		"temporal_workflow_id": req.TemporalWorkflowID,
		"submitted_at": req.SubmittedAt.Format(time.RFC3339),
		"requested": map[string]any{
			"document": doc, "requested_spec_sha256": req.RequestedSpecSHA256,
		},
	}
	if b.Submission != nil {
		out["submission"] = map[string]any{
			"submission_id": b.Submission.ID, "channel": b.Submission.Channel, "apm_id": b.Submission.APMID,
			"submitted_by": b.Submission.SubmittedBy, "idempotency_key": b.Submission.IdempotencyKey,
			"raw_payload_sha256": b.Submission.RawPayloadSHA256,
		}
	}
	if b.Resource != nil {
		out["resource"] = map[string]any{
			"resource_id": b.Resource.ID, "resource_key": b.Resource.ResourceKey, "name": b.Resource.Name,
			"tf_address": b.Resource.TFAddress, "gate": b.Resource.Gate, "lifecycle": b.Resource.Lifecycle,
			"sync_status": b.Resource.SyncStatus,
		}
		out["resource_id"] = b.Resource.ID
	}
	if b.Approval != nil {
		var approved any
		if len(b.Approval.ApprovedSpec) > 0 {
			_ = json.Unmarshal(b.Approval.ApprovedSpec, &approved)
		}
		decisions := make([]map[string]any, 0, len(b.Decisions))
		for _, d := range b.Decisions {
			row := map[string]any{
				"decision_id": d.ID, "approver_key": d.ApproverKey, "approver_identity": d.ApproverIdentity,
				"phase": d.Phase, "mandatory": d.Mandatory, "status": d.Status,
				"responded_by": d.RespondedBy, "response_comment": d.ResponseComment,
			}
			if d.RespondedAt != nil {
				row["responded_at"] = d.RespondedAt.Format(time.RFC3339)
			}
			decisions = append(decisions, row)
		}
		apr := map[string]any{
			"approval_id": b.Approval.ID, "gate_key": b.Approval.GateKey, "gate_version": b.Approval.GateVersion,
			"status": b.Approval.Status, "approved_spec": approved, "approved_spec_sha256": b.Approval.ApprovedSpecSHA256,
			"decisions": decisions, "lifecycle_tasks": []any{},
		}
		if b.Approval.DecidedAt != nil {
			apr["decided_at"] = b.Approval.DecidedAt.Format(time.RFC3339)
		}
		out["approval"] = apr
	}
	out["policy_evaluations"] = []any{}
	return out
}

// FormatKindRow maps registry row for GET /api/v1/kinds.
func FormatKindRow(k store.ResourceKind) map[string]any {
	return map[string]any{
		"kind": k.Kind, "tfvars_collection": k.TFVarsCollection,
		"opa_package": k.OPAPackage, "approval_gate_key": k.ApprovalGateKey,
		"tf_address_template": k.TFAddressTemplate,
	}
}
