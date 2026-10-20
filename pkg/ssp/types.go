package ssp

// Shared types imported by ssp-workers. Shapes follow
// ssp-doc/30-infra/33-terraform-worker-on-gke.md and 10-product/14-policy-spec.md.
// No behaviour.

// RunInput is the Terraform run request.
type RunInput struct {
	RunID           string   `json:"run_id"`
	Attempt         string   `json:"attempt"`
	Kind            string   `json:"kind"`
	TenantID        string   `json:"tenant_id"`
	TenantProject   string   `json:"tenant_project"`
	TenantSA        string   `json:"tenant_sa"`
	LobID           string   `json:"lob_id"`
	StateBucket     string   `json:"state_bucket"`
	StatePrefix     string   `json:"state_prefix"`
	ExpectedURI     string   `json:"expected_uri"`
	ArtifactsURI    string   `json:"artifacts_uri"`
	PlanFromRunURI  string   `json:"plan_from_run_uri"`
	PolicyBundleURI string   `json:"policy_bundle_uri"`
	BatchInstances  []string `json:"batch_instances"`
	RunClass        string   `json:"run_class"`
}

// RunResult is the runner result.json payload plus the Job name.
type RunResult struct {
	State   string         `json:"state"`
	Summary map[string]any `json:"summary"`
	JobName string         `json:"job_name"`
}

// PolicyInput is the request-stage or plan-stage document.
type PolicyInput struct {
	Stage     string         `json:"stage"`
	Order     map[string]any `json:"order,omitempty"`
	Params    map[string]any `json:"params,omitempty"`
	Tenant    map[string]any `json:"tenant,omitempty"`
	Principal map[string]any `json:"principal,omitempty"`
	Estimate  map[string]any `json:"estimate,omitempty"`
	Budget    map[string]any `json:"budget,omitempty"`
	Catalog   map[string]any `json:"catalog,omitempty"`
	Plan      map[string]any `json:"plan,omitempty"`
}

// Bundle identifies a policy bundle by digest and URI.
type Bundle struct {
	Digest string `json:"digest"`
	URI    string `json:"uri"`
}

// OrderEvent is one order audit event.
type OrderEvent struct {
	EventID   int64          `json:"event_id"`
	OrderID   string         `json:"order_id"`
	At        string         `json:"at"`
	Actor     string         `json:"actor"`
	FromState string         `json:"from_state,omitempty"`
	ToState   string         `json:"to_state,omitempty"`
	Type      string         `json:"type"`
	Detail    map[string]any `json:"detail,omitempty"`
}
