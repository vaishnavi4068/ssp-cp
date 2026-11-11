package store

import (
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/google/uuid"
)

type Memory struct {
	mu sync.RWMutex

	StateUnits   map[string]*StateUnit
	Submissions  map[string]*Submission
	Resources    map[string]*Resource
	Requests     map[string]*ResourceRequest
	Approvals    map[string]*Approval
	Decisions    map[string]*ApprovalDecision
	Kinds        map[string]ResourceKind
	Gates        map[string]GateConfig
	Idempotency  map[string]string // apm+key -> request_id
	policyEvals  map[string][]PolicyEvaluation
	gateEvents   []GateEvent
	lifecycleTasks map[string][]LifecycleTask
}

func NewMemory() *Memory {
	m := &Memory{
		StateUnits:  map[string]*StateUnit{},
		Submissions: map[string]*Submission{},
		Resources:   map[string]*Resource{},
		Requests:    map[string]*ResourceRequest{},
		Approvals:   map[string]*Approval{},
		Decisions:   map[string]*ApprovalDecision{},
		Kinds:       map[string]ResourceKind{},
		Gates:       map[string]GateConfig{},
		Idempotency: map[string]string{},
	}
	m.seedKinds()
	m.seedGates()
	return m
}

func (m *Memory) seedKinds() {
	m.Kinds["gcs_bucket"] = ResourceKind{
		Kind: "gcs_bucket", Cloud: "gcp", Enabled: true, DisplayName: "GCS Bucket",
		TFVarsCollection: "gcs_buckets", TFAddressTemplate: `module.gcs_bucket["{name}"]`,
		OPAPackage: "idp.gcp.gcs_bucket", ApprovalGateKey: "gcs_bucket_owner", SchemaVersion: "1.0.0",
	}
	m.Kinds["spanner_instance"] = ResourceKind{
		Kind: "spanner_instance", Cloud: "gcp", Enabled: true, DisplayName: "Spanner Instance",
		TFVarsCollection: "spanner_instances", TFAddressTemplate: `module.spanner_instance["{name}"]`,
		OPAPackage: "idp.gcp.spanner_instance", ApprovalGateKey: "spanner_data_owner", SchemaVersion: "1.0.0",
	}
	m.Kinds["spanner_database"] = ResourceKind{
		Kind: "spanner_database", Cloud: "gcp", Enabled: true, DisplayName: "Spanner Database",
		TFVarsCollection: "spanner_databases", TFAddressTemplate: `module.spanner_database["{instance}/{name}"]`,
		OPAPackage: "idp.gcp.spanner_database", ApprovalGateKey: "spanner_data_owner",
		ParentKind: "spanner_instance", SchemaVersion: "1.0.0",
	}
}

func (m *Memory) seedGates() {
	gcsGate := map[string]any{
		"order": "sequential", "self_approval": "deny",
		"approvers": []map[string]any{{"key": "bucket_owner", "ticket_field": "/metadata/owner", "mandatory": true, "sla_days": 5}},
	}
	bGCS, _ := json.Marshal(gcsGate)
	m.Gates["gcs_bucket_owner"] = GateConfig{GateKey: "gcs_bucket_owner", Version: 1, Config: bGCS}

	spannerGate := map[string]any{
		"order": "sequential", "self_approval": "deny",
		"approvers": []any{
			map[string]any{"key": "data_owner", "ticket_field": "/metadata/owner", "mandatory": true, "sla_days": 5},
			map[string]any{
				"key": "dbaas_reviewer", "role": "dbaas_reviewer", "mandatory": true,
				"skip_condition": "metadata.environment not in ('prod') and metadata.resolved.app_tier != '1'",
				"sla_days": 3,
			},
		},
	}
	bSp, _ := json.Marshal(spannerGate)
	m.Gates["spanner_data_owner"] = GateConfig{GateKey: "spanner_data_owner", Version: 1, Config: bSp}
}

func (m *Memory) EnsureStateUnit(projectID, lob, env, apm string) *StateUnit {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, su := range m.StateUnits {
		if su.ScopeID == projectID {
			return su
		}
	}
	id := uuid.New().String()
	su := &StateUnit{
		ID: id, Cloud: "gcp", ScopeID: projectID, LOB: lob, Environment: env, APMID: apm,
		StateBucket: "microdrive-dev-spp-tfstate",
		ExecutorIdentity: fmt.Sprintf("idp-tf@%s.iam.gserviceaccount.com", projectID),
		Status: "active",
	}
	m.StateUnits[id] = su
	return su
}

func (m *Memory) FindResourceByKindName(kind, name string) *Resource {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, r := range m.Resources {
		if r.Kind == kind && r.Name == name {
			return r
		}
	}
	return nil
}

func (m *Memory) SaveSubmission(s *Submission) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.Submissions[s.ID] = s
}

func (m *Memory) SaveRequest(r *ResourceRequest) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.Requests[r.ID] = r
}

func (m *Memory) SaveResource(r *Resource) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.Resources[r.ID] = r
}

func (m *Memory) SaveApproval(a *Approval) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.Approvals[a.ID] = a
}

func (m *Memory) SaveDecision(d *ApprovalDecision) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.Decisions[d.ID] = d
}

func (m *Memory) GetRequest(id string) (*ResourceRequest, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.Requests[id]
	if !ok {
		return nil, fmt.Errorf("request not found")
	}
	return r, nil
}

func (m *Memory) GetApproval(id string) (*Approval, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	a, ok := m.Approvals[id]
	if !ok {
		return nil, fmt.Errorf("approval not found")
	}
	return a, nil
}

func (m *Memory) ListDecisions(approvalID string) []*ApprovalDecision {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var out []*ApprovalDecision
	for _, d := range m.Decisions {
		if d.ApprovalID == approvalID {
			out = append(out, d)
		}
	}
	return out
}

func (m *Memory) ResourceByID(id string) *Resource {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.Resources[id]
}

func (m *Memory) StateUnitByID(id string) *StateUnit {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.StateUnits[id]
}

func (m *Memory) Now() time.Time { return time.Now().UTC() }
