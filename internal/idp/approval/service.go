package approval

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/vaishnavi4068/ssp-cp/internal/idp/hash"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/intake"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/opa"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/store"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/temporal"
)

type Service struct {
	Store    *store.Memory
	OPA      *opa.Client
	Intake   *intake.Service
	Temporal *temporal.Bridge
}

type DecisionInput struct {
	Status      string `json:"status"`
	ApproverKey string `json:"approver_key"`
	DecisionID  string `json:"decision_id"`
	Comment     string `json:"comment"`
}

func (s *Service) RecordDecision(ctx context.Context, approvalID string, in DecisionInput, respondedBy string) (map[string]any, error) {
	apr, err := s.Store.GetApproval(approvalID)
	if err != nil {
		return nil, errNotFound(err)
	}
	req, err := s.Store.GetRequest(apr.RequestID)
	if err != nil {
		return nil, err
	}
	res := s.Store.ResourceByID(apr.ResourceID)
	if res == nil {
		return nil, fmt.Errorf("resource not found")
	}
	decisions := s.Store.ListDecisions(apr.ID)
	if len(decisions) == 0 {
		return nil, fmt.Errorf("no approval decisions")
	}
	sort.Slice(decisions, func(i, j int) bool { return decisions[i].Phase < decisions[j].Phase })

	target := pickDecision(decisions, in)
	if target == nil {
		return nil, fmt.Errorf("matching pending approval decision not found")
	}
	for _, d := range decisions {
		if d.Phase < target.Phase && d.Status != "approved" && d.Status != "auto_approved" {
			return nil, fmt.Errorf("sequential approval gate: earlier approver %q must approve first", d.ApproverKey)
		}
	}

	now := s.Store.Now()
	target.Status = in.Status
	target.RespondedBy = respondedBy
	target.ResponseComment = in.Comment
	target.RespondedAt = &now

	if in.Status == "denied" {
		apr.Status = "DENIED"
		apr.DecidedAt = &now
		req.Status = "DENIED"
		return s.Intake.GetRequest(ctx, req.ID)
	}
	if in.Status == "escalated" {
		return s.Intake.GetRequest(ctx, req.ID)
	}

	var requestedDoc map[string]any
	if err := json.Unmarshal(req.RequestedSpec, &requestedDoc); err != nil {
		return nil, err
	}
	meta, _ := requestedDoc["metadata"].(map[string]any)
	appTier := "2"
	if resolved, ok := meta["resolved"].(map[string]any); ok {
		if t, ok := resolved["app_tier"].(string); ok {
			appTier = t
		}
	}
	s.applySkipConditions(decisions, meta, appTier, now)

	stillPending := false
	for _, d := range decisions {
		if d.Mandatory && d.Status == "pending" {
			stillPending = true
			break
		}
	}
	if stillPending {
		return s.Intake.GetRequest(ctx, req.ID)
	}

	kindMeta := s.Store.Kinds[req.Kind]
	opaIn := map[string]any{
		"stage": "approved", "cloud": "gcp", "app_alias": "orders",
		"resource_id": res.ID, "document": requestedDoc,
	}
	if kms := os.Getenv("SSP_KMS_KEY_PLACEHOLDER"); kms != "" {
		opaIn["kms_key_name"] = kms
	}
	opaRes, err := s.OPA.Evaluate(ctx, kindMeta.OPAPackage, opaIn)
	if err != nil {
		return nil, err
	}
	if opaRes.Decision == "deny" {
		return nil, fmt.Errorf("opa denied at approved stage: %v", opaRes.Violations)
	}

	approvedDoc := deepCopyMap(requestedDoc)
	approvedMeta, _ := approvedDoc["metadata"].(map[string]any)
	if approvedMeta == nil {
		approvedMeta = map[string]any{}
		approvedDoc["metadata"] = approvedMeta
	}
	if opaRes.ComputedLabels != nil {
		labels := map[string]any{}
		for k, v := range opaRes.ComputedLabels {
			labels[k] = v
		}
		approvedMeta["labels"] = labels
	}
	env := fmt.Sprint(approvedMeta["environment"])
	lob := fmt.Sprint(approvedMeta["lob"])
	approvedMeta["resolved"] = map[string]any{
		"app_tier": appTier, "environment_type": env,
		"vpc_sc_perimeter": fmt.Sprintf("%s_%s_restricted_perimeter", lob, env),
		"cost_center_validated": true,
		"resolved_at": now.Format(time.RFC3339),
	}
	if req.Kind == "gcs_bucket" {
		spec, _ := approvedDoc["spec"].(map[string]any)
		kms := opaRes.ResolvedKMSKey
		if kms == "" {
			kms = envOr("SSP_DEFAULT_KMS_KEY", "projects/example/locations/us-east1/keyRings/example/cryptoKeys/example")
		}
		spec["retention_days"] = 90
		spec["retention_locked"] = false
		spec["uniform_bucket_level_access"] = true
		spec["public_access_prevention"] = "enforced"
		spec["kms_key_name"] = kms
		spec["soft_delete_retention_days"] = 7
		spec["force_destroy"] = false
	}
	approvedDoc["prerequisites"] = opaRes.Prerequisites
	approvedDoc["post_apply"] = []map[string]any{{"type": "notify_owner", "target": approvedMeta["owner"]}}
	approvedDoc["approval"] = map[string]any{
		"request_id": req.ID, "requested_spec_sha256": req.RequestedSpecSHA256,
		"gate_key": apr.GateKey, "decided_at": now.Format(time.RFC3339),
	}

	specBytes, _ := json.Marshal(approvedDoc)
	sha := hash.MustCanonicalSHA256(approvedDoc)
	trace, _ := json.Marshal(opaRes.GuardrailTrace)
	apr.ApprovedSpec = specBytes
	apr.ApprovedSpecSHA256 = sha
	apr.GuardrailTrace = trace
	apr.Status = "APPROVED"
	apr.DecidedAt = &now
	req.Status = "APPROVED"
	res.Gate = "APPROVED"

	su := s.Store.StateUnitByID(res.StateUnitID)
	projectID := ""
	stateBucket := "microdrive-dev-spp-tfstate"
	if su != nil {
		projectID = su.ScopeID
		stateBucket = su.StateBucket
	}
	_ = s.Temporal.StartProvision(ctx, temporal.ProvisionPayload{
		RequestID: req.ID, ApprovalID: apr.ID, ResourceID: res.ID,
		StateUnitID: res.StateUnitID, ProjectID: projectID, Action: req.Action,
		ApprovedSpec: specBytes, ApprovedSpecSHA256: sha, TriggeredBy: respondedBy,
		StateBucket: stateBucket,
	})

	out, err := s.Intake.GetRequest(ctx, req.ID)
	if err != nil {
		return nil, err
	}
	out["temporal_workflow_dispatch"] = map[string]any{
		"workflow_name": s.Temporal.Workflow, "workflow_id": "req-" + req.ID,
		"namespace": s.Temporal.Namespace, "task_queue": s.Temporal.TaskQueue,
		"dispatched": s.Temporal.Enabled,
	}
	return out, nil
}

func (s *Service) applySkipConditions(decisions []*store.ApprovalDecision, meta map[string]any, appTier string, now time.Time) {
	env := fmt.Sprint(meta["environment"])
	for _, d := range decisions {
		if d.Status != "pending" || d.ApproverKey != "dbaas_reviewer" {
			continue
		}
		if env != "prod" && appTier != "1" {
			d.Status = "approved"
			d.RespondedBy = "system:skip_condition"
			d.ResponseComment = "Skipped per skip_condition for nonprod tier>1"
			d.RespondedAt = &now
		}
	}
}

func pickDecision(decisions []*store.ApprovalDecision, in DecisionInput) *store.ApprovalDecision {
	if in.DecisionID != "" {
		for _, d := range decisions {
			if d.ID == in.DecisionID {
				return d
			}
		}
		return nil
	}
	if in.ApproverKey != "" {
		for _, d := range decisions {
			if d.ApproverKey == in.ApproverKey {
				return d
			}
		}
		return nil
	}
	for _, d := range decisions {
		if d.Status == "pending" {
			return d
		}
	}
	return nil
}

func deepCopyMap(m map[string]any) map[string]any {
	b, _ := json.Marshal(m)
	var out map[string]any
	_ = json.Unmarshal(b, &out)
	return out
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func errNotFound(err error) error {
	if strings.Contains(err.Error(), "not found") {
		return err
	}
	return err
}
