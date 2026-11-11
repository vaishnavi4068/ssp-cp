package store

import (
	"encoding/json"
	"time"
)

// MemoryStore implements the idp four-gate subset used by the Go control plane (WI-001/WI-007).

type ResourceKind struct {
	Kind              string
	TFVarsCollection  string
	TFAddressTemplate string
	OPAPackage        string
	ApprovalGateKey   string
	ParentKind        string
}

type StateUnit struct {
	ID              string
	Cloud           string
	ScopeID         string
	LOB             string
	Environment     string
	APMID           string
	StateBucket     string
	ExecutorIdentity string
	Status          string
}

type Submission struct {
	ID               string
	Channel          string
	APMID            string
	SubmittedBy      string
	IdempotencyKey   string
	RawPayload       json.RawMessage
	RawPayloadSHA256 string
	SubmittedAt      time.Time
}

type Resource struct {
	ID                 string
	StateUnitID        string
	Kind               string
	Name               string
	ParentResourceID   string
	ResourceKey        string
	TFAddress          string
	APMID              string
	Lifecycle          string
	Gate               string
	SyncStatus         string
	CurrentRequestID   string
	CurrentApprovalID  string
	CreatedAt          time.Time
}

type ResourceRequest struct {
	ID                   string
	SubmissionID         string
	ResourceID           string
	Kind                 string
	Action               string
	SchemaVersion        string
	RequestedSpec        json.RawMessage
	RequestedSpecSHA256  string
	SourcePointer        string
	Status               string
	RequestedBy          string
	TemporalWorkflowID   string
	SubmittedAt          time.Time
}

type Approval struct {
	ID                 string
	RequestID          string
	ResourceID         string
	GateKey            string
	GateVersion        int
	Status             string
	GuardrailTrace     json.RawMessage
	ApprovedSpec       json.RawMessage
	ApprovedSpecSHA256 string
	DecidedAt          *time.Time
}

type ApprovalDecision struct {
	ID               string
	ApprovalID       string
	ApproverKey      string
	ApproverIdentity string
	Phase            int
	Mandatory        bool
	Status           string
	RespondedBy      string
	ResponseComment  string
	RespondedAt      *time.Time
}

type GateConfig struct {
	GateKey string
	Version int
	Config  json.RawMessage
}
