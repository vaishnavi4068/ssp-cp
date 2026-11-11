package store

import (
	"context"
	"encoding/json"
	"fmt"
)

// MemoryBackend adapts Memory to Backend.
type MemoryBackend struct{ *Memory }

func NewMemoryBackend() *MemoryBackend { return &MemoryBackend{Memory: NewMemory()} }

func (m *MemoryBackend) GetKind(_ context.Context, kind string) (ResourceKind, error) {
	k, ok := m.Kinds[kind]
	if !ok {
		return ResourceKind{}, fmt.Errorf("unsupported kind %q", kind)
	}
	return k, nil
}

func (m *MemoryBackend) ListKinds(_ context.Context) ([]ResourceKind, error) {
	out := make([]ResourceKind, 0, len(m.Kinds))
	for _, k := range m.Kinds {
		out = append(out, k)
	}
	return out, nil
}

func (m *MemoryBackend) GetGate(_ context.Context, gateKey string) (GateConfig, error) {
	g, ok := m.Gates[gateKey]
	if !ok {
		return GateConfig{}, fmt.Errorf("gate %q not found", gateKey)
	}
	return g, nil
}

func (m *MemoryBackend) ResolveApm(_ context.Context, apmID string) (alias, appTier string) {
	return "orders", "2"
}

func (m *MemoryBackend) EnsureStateUnit(ctx context.Context, projectID, lob, env, apm string) (*StateUnit, error) {
	return m.Memory.EnsureStateUnit(projectID, lob, env, apm), nil
}

func (m *MemoryBackend) FindIdempotentRequest(_ context.Context, apmID, key string) (string, bool, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, sub := range m.Submissions {
		if sub.APMID == apmID && sub.IdempotencyKey == key {
			for _, req := range m.Requests {
				if req.SubmissionID == sub.ID {
					return req.ID, true, nil
				}
			}
		}
	}
	return "", false, nil
}

func (m *MemoryBackend) PersistIntake(_ context.Context, in IntakePersist) error {
	if in.Submission != nil {
		m.SaveSubmission(in.Submission)
	}
	if in.Resource != nil {
		m.SaveResource(in.Resource)
	}
	if in.Request != nil {
		m.SaveRequest(in.Request)
	}
	if in.Approval != nil {
		m.SaveApproval(in.Approval)
	}
	for _, d := range in.Decisions {
		if d != nil {
			m.SaveDecision(d)
		}
	}
	return nil
}

func (m *MemoryBackend) GetRequestBundle(ctx context.Context, requestID string) (*RequestBundle, error) {
	req, err := m.Memory.GetRequest(requestID)
	if err != nil {
		return nil, err
	}
	res := m.Memory.ResourceByID(req.ResourceID)
	var sub *Submission
	m.mu.RLock()
	sub = m.Submissions[req.SubmissionID]
	var apr *Approval
	if res != nil && res.CurrentApprovalID != "" {
		apr, _ = m.Memory.GetApproval(res.CurrentApprovalID)
	}
	m.mu.RUnlock()
	var decs []*ApprovalDecision
	if apr != nil {
		decs = m.Memory.ListDecisions(apr.ID)
	}
	return &RequestBundle{Request: req, Submission: sub, Resource: res, Approval: apr, Decisions: decs}, nil
}

func (m *MemoryBackend) ListRequestIDs(_ context.Context, kindFilter, statusFilter string) ([]string, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var ids []string
	for _, r := range m.Requests {
		if kindFilter != "" && r.Kind != kindFilter {
			continue
		}
		if statusFilter != "" && r.Status != statusFilter {
			continue
		}
		ids = append(ids, r.ID)
	}
	return ids, nil
}

func (m *MemoryBackend) ListApprovalIDs(_ context.Context, statusFilter string) ([]string, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var ids []string
	for _, a := range m.Approvals {
		if statusFilter != "" && a.Status != statusFilter {
			continue
		}
		ids = append(ids, a.ID)
	}
	return ids, nil
}

func (m *MemoryBackend) ListResourceStatus(_ context.Context, resourceID string) ([]map[string]any, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var out []map[string]any
	for _, res := range m.Resources {
		if resourceID != "" && res.ID != resourceID {
			continue
		}
		var req *ResourceRequest
		if res.CurrentRequestID != "" {
			req = m.Requests[res.CurrentRequestID]
		}
		row := map[string]any{
			"resource_id": res.ID, "resource_key": res.ResourceKey, "kind": res.Kind, "name": res.Name,
			"apm_id": res.APMID, "lifecycle": res.Lifecycle, "gate": res.Gate, "sync_status": res.SyncStatus,
		}
		if req != nil {
			row["request_id"] = req.ID
			row["request_status"] = req.Status
			row["submitted_at"] = req.SubmittedAt
		}
		out = append(out, row)
	}
	return out, nil
}

func (m *MemoryBackend) UpdateDecision(_ context.Context, decisionID, status, respondedBy, comment string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	d, ok := m.Decisions[decisionID]
	if !ok {
		return fmt.Errorf("decision not found")
	}
	d.Status = status
	d.RespondedBy = respondedBy
	d.ResponseComment = comment
	now := m.Now()
	d.RespondedAt = &now
	return nil
}

func (m *MemoryBackend) ListDecisions(_ context.Context, approvalID string) ([]*ApprovalDecision, error) {
	return m.Memory.ListDecisions(approvalID), nil
}

func (m *MemoryBackend) FinalizeApproval(_ context.Context, fin ApprovalFinalize) error {
	apr, err := m.Memory.GetApproval(fin.ApprovalID)
	if err != nil {
		return err
	}
	req, err := m.Memory.GetRequest(apr.RequestID)
	if err != nil {
		return err
	}
	res := m.Memory.ResourceByID(apr.ResourceID)
	if fin.Denied {
		apr.Status = "DENIED"
		now := m.Now()
		apr.DecidedAt = &now
		req.Status = "DENIED"
		req.StatusReason = fin.RequestReason
		return nil
	}
	apr.Status = "APPROVED"
	apr.ApprovedSpec = fin.ApprovedSpec
	apr.ApprovedSpecSHA256 = fin.ApprovedSpecSHA256
	apr.GuardrailTrace = fin.GuardrailTrace
	now := m.Now()
	apr.DecidedAt = &now
	req.Status = fin.RequestStatus
	if res != nil {
		res.Gate = fin.ResourceGate
	}
	return nil
}

func (m *MemoryBackend) GetApproval(ctx context.Context, id string) (*Approval, error) {
	return m.Memory.GetApproval(id)
}

func (m *MemoryBackend) GetRequest(ctx context.Context, id string) (*ResourceRequest, error) {
	return m.Memory.GetRequest(id)
}

func (m *MemoryBackend) ResourceByID(ctx context.Context, id string) (*Resource, error) {
	return m.Memory.ResourceByID(id), nil
}

func (m *MemoryBackend) StateUnitByID(ctx context.Context, id string) (*StateUnit, error) {
	return m.Memory.StateUnitByID(id), nil
}

func (m *MemoryBackend) SetStateUnitStatus(_ context.Context, stateUnitID, status string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	su, ok := m.StateUnits[stateUnitID]
	if !ok {
		return fmt.Errorf("state unit not found")
	}
	su.Status = status
	return nil
}

// GateConfigJSON decodes approvers for intake seeding.
func GateConfigJSON(g GateConfig) map[string]any {
	var out map[string]any
	_ = json.Unmarshal(g.Config, &out)
	return out
}
