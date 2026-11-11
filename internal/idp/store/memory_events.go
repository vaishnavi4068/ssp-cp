package store

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
)

func (m *MemoryBackend) RecordPolicyEvaluation(_ context.Context, pe PolicyEvaluation) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if pe.ID == "" {
		pe.ID = uuid.NewString()
	}
	if pe.EvaluatedAt.IsZero() {
		pe.EvaluatedAt = m.Now()
	}
	if m.policyEvals == nil {
		m.policyEvals = map[string][]PolicyEvaluation{}
	}
	m.policyEvals[pe.RequestID] = append(m.policyEvals[pe.RequestID], pe)
	return pe.ID, nil
}

func (m *MemoryBackend) ListPolicyEvaluations(_ context.Context, requestID string) ([]PolicyEvaluation, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.policyEvals[requestID], nil
}

func (m *MemoryBackend) RecordGateEvent(_ context.Context, ev GateEvent) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.gateEvents == nil {
		m.gateEvents = []GateEvent{}
	}
	m.gateEvents = append(m.gateEvents, ev)
	return nil
}

func (m *MemoryBackend) RecordLifecycleTask(_ context.Context, task LifecycleTask) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if task.ID == "" {
		task.ID = uuid.NewString()
	}
	if m.lifecycleTasks == nil {
		m.lifecycleTasks = map[string][]LifecycleTask{}
	}
	m.lifecycleTasks[task.ApprovalID] = append(m.lifecycleTasks[task.ApprovalID], task)
	return nil
}

func (m *MemoryBackend) ListLifecycleTasks(_ context.Context, approvalID string) ([]LifecycleTask, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.lifecycleTasks[approvalID], nil
}

func (m *MemoryBackend) ListAudit(_ context.Context, resourceID, requestID string, limit int) (AuditSnapshot, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var snap AuditSnapshot
	for _, e := range m.gateEvents {
		if limit > 0 && len(snap.GateEvents) >= limit {
			break
		}
		if resourceID != "" && e.ResourceID != resourceID {
			continue
		}
		if requestID != "" && e.RequestID != requestID {
			continue
		}
		var detail any
		_ = json.Unmarshal(e.Detail, &detail)
		snap.GateEvents = append(snap.GateEvents, map[string]any{
			"event_type": e.EventType, "gate": e.Gate, "actor": e.Actor, "detail": detail,
			"resource_id": e.ResourceID, "request_id": e.RequestID,
		})
	}
	for _, evals := range m.policyEvals {
		for _, pe := range evals {
			if requestID != "" && pe.RequestID != requestID {
				continue
			}
			snap.PolicyEvaluations = append(snap.PolicyEvaluations, map[string]any{
				"evaluation_id": pe.ID, "stage": pe.Stage, "decision": pe.Decision, "opa_package": pe.OPAPackage,
			})
		}
	}
	return snap, nil
}

func (m *MemoryBackend) Ready(context.Context) error {
	if len(m.Kinds) == 0 {
		return fmt.Errorf("catalog not seeded")
	}
	return nil
}

func (m *MemoryBackend) GetResourceObserved(context.Context, string) (map[string]any, bool, error) {
	return nil, false, nil
}

func (m *MemoryBackend) ListDriftFindings(context.Context, string) ([]map[string]any, error) {
	return nil, nil
}
