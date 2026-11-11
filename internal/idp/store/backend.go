package store

import (
	"context"
	"time"
)

// Backend is the persistence contract for the idp plane (memory or Postgres/sqlc).
type Backend interface {
	Now() time.Time

	// Catalog
	GetKind(ctx context.Context, kind string) (ResourceKind, error)
	ListKinds(ctx context.Context) ([]ResourceKind, error)
	GetGate(ctx context.Context, gateKey string) (GateConfig, error)
	ResolveApm(ctx context.Context, apmID string) (alias, appTier string)

	// Intake / mutations
	EnsureStateUnit(ctx context.Context, projectID, lob, env, apm string) (*StateUnit, error)
	FindIdempotentRequest(ctx context.Context, apmID, idempotencyKey string) (requestID string, found bool, err error)
	PersistIntake(ctx context.Context, in IntakePersist) error

	// Reads
	GetRequestBundle(ctx context.Context, requestID string) (*RequestBundle, error)
	ListRequestIDs(ctx context.Context, kindFilter, statusFilter string) ([]string, error)
	ListApprovalIDs(ctx context.Context, statusFilter string) ([]string, error)
	ListResourceStatus(ctx context.Context, resourceID string) ([]map[string]any, error)

	// Approval updates
	UpdateDecision(ctx context.Context, decisionID, status, respondedBy, comment string) error
	ListDecisions(ctx context.Context, approvalID string) ([]*ApprovalDecision, error)
	FinalizeApproval(ctx context.Context, fin ApprovalFinalize) error
	GetApproval(ctx context.Context, approvalID string) (*Approval, error)
	GetRequest(ctx context.Context, requestID string) (*ResourceRequest, error)
	ResourceByID(ctx context.Context, resourceID string) (*Resource, error)
	StateUnitByID(ctx context.Context, stateUnitID string) (*StateUnit, error)
	SetStateUnitStatus(ctx context.Context, stateUnitID, status string) error

	// Events / audit (Python parity)
	RecordPolicyEvaluation(ctx context.Context, pe PolicyEvaluation) (string, error)
	ListPolicyEvaluations(ctx context.Context, requestID string) ([]PolicyEvaluation, error)
	RecordGateEvent(ctx context.Context, ev GateEvent) error
	RecordLifecycleTask(ctx context.Context, task LifecycleTask) error
	ListLifecycleTasks(ctx context.Context, approvalID string) ([]LifecycleTask, error)
	ListAudit(ctx context.Context, resourceID, requestID string, limit int) (AuditSnapshot, error)
	Ready(ctx context.Context) error
	GetResourceObserved(ctx context.Context, resourceID string) (map[string]any, bool, error)
	ListDriftFindings(ctx context.Context, resourceID string) ([]map[string]any, error)
}

type PolicyEvaluation struct {
	ID              string
	Stage           string
	RequestID       string
	OPAPackage      string
	BundleRevision  string
	InputSHA256     string
	Decision        string
	Violations      []byte
	Mutations       []byte
	EvaluatedAt     time.Time
}

type GateEvent struct {
	StateUnitID string
	ResourceID  string
	RequestID   string
	Gate        string
	EventType   string
	Actor       string
	Detail      []byte
}

type LifecycleTask struct {
	ID         string
	ResourceID string
	ApprovalID string
	Phase      string
	TaskType   string
	TaskKey    string
	Spec       []byte
	Status     string
}

type AuditSnapshot struct {
	GateEvents        []map[string]any
	AuditLogs         []map[string]any
	PolicyEvaluations []map[string]any
}

// IntakePersist captures one resource intake transaction.
type IntakePersist struct {
	Submission       *Submission
	Resource         *Resource
	Request          *ResourceRequest
	Approval         *Approval
	Decisions        []*ApprovalDecision
	ParentResourceID string
}

// ApprovalFinalize writes approved gate state.
type ApprovalFinalize struct {
	ApprovalID         string
	ApprovedSpec       []byte
	ApprovedSpecSHA256 string
	GuardrailTrace     []byte
	RequestStatus      string
	ResourceGate       string
	Denied             bool
	RequestReason      string
}

// RequestBundle is the Python get_request_detail aggregate (subset filled by backend).
type RequestBundle struct {
	Request    *ResourceRequest
	Submission *Submission
	Resource   *Resource
	Approval   *Approval
	Decisions  []*ApprovalDecision
}
