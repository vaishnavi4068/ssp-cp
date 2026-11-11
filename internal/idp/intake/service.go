package intake

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"

	"github.com/vaishnavi4068/ssp-cp/internal/idp/hash"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/naming"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/opa"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/query"
	"github.com/vaishnavi4068/ssp-cp/internal/idp/store"
)

type Service struct {
	Store store.Backend
	OPA   *opa.Client
}

type CreateRequest struct {
	APIVersion     string         `json:"api_version"`
	Kind           string         `json:"kind"`
	Action         string         `json:"action"`
	IdempotencyKey string         `json:"idempotency_key"`
	Channel        string         `json:"channel"`
	Metadata       map[string]any `json:"metadata"`
	Spec           map[string]any `json:"spec"`
}

type SpannerStackRequest struct {
	Template        string           `json:"template"`
	TemplateVersion string           `json:"template_version"`
	Channel         string           `json:"channel"`
	IdempotencyKey  string           `json:"idempotency_key"`
	Resources       []map[string]any `json:"resources"`
}

func (s *Service) SubmitCreate(ctx context.Context, in CreateRequest, requestedBy string) (map[string]any, error) {
	if in.Kind != "gcs_bucket" {
		return nil, fmt.Errorf("kind %q: only gcs_bucket is implemented on this endpoint; use /submissions/spanner-stack for Spanner", in.Kind)
	}
	meta := in.Metadata
	apm := naming.NormalizeAPM(fmt.Sprint(meta["apm_id"]))
	env, err := naming.NormalizeEnvironment(fmt.Sprint(meta["environment"]))
	if err != nil {
		return nil, err
	}
	lob := naming.NormalizeLOB(fmt.Sprint(meta["lob"]))
	projectID := fmt.Sprint(meta["project_id"])
	spec := in.Spec
	name := fmt.Sprint(spec["name"])
	app := "orders"
	if labels, ok := meta["labels"].(map[string]any); ok {
		if a, ok := labels["app"].(string); ok {
			app = a
		}
	}
	if name == "" {
		purpose := "landing"
		if pt, ok := spec["purpose_token"].(string); ok && pt != "" {
			purpose = pt
		}
		name = naming.BuildGCSBucketName(lob, env, app, purpose, naming.RandomSuffix4())
		spec["name"] = name
	}
	if err := naming.ValidateGCSBucketName(name, env, lob); err != nil {
		return nil, err
	}
	doc := map[string]any{
		"api_version": coalesce(in.APIVersion, "idp.spp/v1"),
		"kind":        in.Kind,
		"action":      coalesce(in.Action, "create"),
		"metadata":    meta,
		"spec":        spec,
	}
	doc["metadata"].(map[string]any)["environment"] = env
	doc["metadata"].(map[string]any)["apm_id"] = apm
	return s.persistSubmission(ctx, doc, in, requestedBy, projectID, lob, env, apm, "/resources/0", "")
}

func (s *Service) SubmitSpannerStack(ctx context.Context, in SpannerStackRequest, requestedBy string) (map[string]any, error) {
	if in.Template != "spanner-instance-with-databases" || len(in.Resources) != 2 {
		return nil, fmt.Errorf("template spanner-instance-with-databases requires exactly two resources")
	}
	inst := in.Resources[0]
	db := in.Resources[1]
	if fmt.Sprint(inst["kind"]) != "spanner_instance" || fmt.Sprint(db["kind"]) != "spanner_database" {
		return nil, fmt.Errorf("resources must be spanner_instance then spanner_database")
	}
	instMeta, _ := inst["metadata"].(map[string]any)
	dbMeta, _ := db["metadata"].(map[string]any)
	instSpec, _ := inst["spec"].(map[string]any)
	dbSpec, _ := db["spec"].(map[string]any)
	env, err := naming.NormalizeEnvironment(fmt.Sprint(instMeta["environment"]))
	if err != nil {
		return nil, err
	}
	lob := naming.NormalizeLOB(fmt.Sprint(instMeta["lob"]))
	apm := naming.NormalizeAPM(fmt.Sprint(instMeta["apm_id"]))
	projectID := fmt.Sprint(instMeta["project_id"])
	app := "orders"
	if labels, ok := instMeta["labels"].(map[string]any); ok {
		if a, ok := labels["app"].(string); ok {
			app = a
		}
	}
	instName := fmt.Sprint(instSpec["name"])
	dbName := fmt.Sprint(dbSpec["name"])
	dbSpec["instance"] = instName
	if err := naming.ValidateSpannerInstanceName(instName, lob, env, app); err != nil {
		return nil, err
	}
	if err := naming.ValidateSpannerDatabaseName(dbName, app); err != nil {
		return nil, err
	}
	instSpec["display_name"] = coalesce(fmt.Sprint(instSpec["display_name"]), naming.GenerateSpannerDisplayName(lob, app, env))
	instSpec["config"] = coalesce(fmt.Sprint(instSpec["config"]), "regional-us-east1")

	subID := uuid.New().String()
	raw, _ := json.Marshal(in)
	sub := &store.Submission{
		ID: subID, Channel: coalesce(in.Channel, "api"), APMID: apm, SubmittedBy: requestedBy,
		IdempotencyKey: coalesce(in.IdempotencyKey, subID), RawPayload: raw,
		RawPayloadSHA256: hash.MustCanonicalSHA256(in), SubmittedAt: s.Store.Now(),
	}
	su, err := s.Store.EnsureStateUnit(ctx, projectID, lob, env, apm)
	if err != nil {
		return nil, err
	}
	_ = s.Store.PersistIntake(ctx, store.IntakePersist{Submission: sub})

	instDoc := map[string]any{"api_version": "idp.spp/v1", "kind": "spanner_instance", "action": "create", "metadata": instMeta, "spec": instSpec}
	dbDoc := map[string]any{"api_version": "idp.spp/v1", "kind": "spanner_database", "action": "create", "metadata": dbMeta, "spec": dbSpec}
	instMeta["environment"] = env
	instMeta["apm_id"] = apm
	dbMeta["environment"] = env
	dbMeta["apm_id"] = apm

	instRes, instReq, err := s.createOne(ctx, instDoc, su, subID, requestedBy, "/resources/0", "", apm)
	if err != nil {
		return nil, err
	}
	dbRes, dbReq, err := s.createOne(ctx, dbDoc, su, subID, requestedBy, "/resources/1", instRes.ID, apm)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"submission_id": subID,
		"request_ids":   []string{instReq.ID, dbReq.ID},
		"instance_request": s.detail(instReq, instRes),
		"database_request": s.detail(dbReq, dbRes),
	}, nil
}

func (s *Service) persistSubmission(ctx context.Context, doc map[string]any, in CreateRequest, requestedBy, projectID, lob, env, apm, pointer, parentID string) (map[string]any, error) {
	subID := uuid.New().String()
	raw, _ := json.Marshal(in)
	sub := &store.Submission{
		ID: subID, Channel: coalesce(in.Channel, "api"), APMID: apm, SubmittedBy: requestedBy,
		IdempotencyKey: coalesce(in.IdempotencyKey, subID), RawPayload: raw,
		RawPayloadSHA256: hash.MustCanonicalSHA256(in), SubmittedAt: s.Store.Now(),
	}
	su, err := s.Store.EnsureStateUnit(ctx, projectID, lob, env, apm)
	if err != nil {
		return nil, err
	}
	if err := s.Store.PersistIntake(ctx, store.IntakePersist{Submission: sub}); err != nil {
		return nil, err
	}
	res, req, err := s.createOne(ctx, doc, su, subID, requestedBy, pointer, parentID, apm)
	if err != nil {
		return nil, err
	}
	return s.detail(req, res), nil
}

func (s *Service) createOne(ctx context.Context, doc map[string]any, su *store.StateUnit, subID, requestedBy, pointer, parentID, apm string) (*store.Resource, *store.ResourceRequest, error) {
	kind := fmt.Sprint(doc["kind"])
	meta, _ := doc["metadata"].(map[string]any)
	spec, _ := doc["spec"].(map[string]any)
	name := fmt.Sprint(spec["name"])
	kindMeta, err := s.Store.GetKind(ctx, kind)
	if err != nil {
		return nil, nil, err
	}
	instance := ""
	if kind == "spanner_database" {
		instance = fmt.Sprint(spec["instance"])
	}
	tfAddr := naming.RenderTFAddress(kindMeta.TFAddressTemplate, name, instance)
	rid := uuid.New().String()
	reqID := uuid.New().String()
	aprID := uuid.New().String()

	opaIn := map[string]any{
		"stage": "requested", "cloud": "gcp",
		"resource_id": rid, "document": doc,
	}
	opaRes, err := s.OPA.Evaluate(ctx, kindMeta.OPAPackage, opaIn)
	if err != nil {
		return nil, nil, err
	}
	if opaRes.Decision == "deny" {
		return nil, nil, fmt.Errorf("opa denied: %v", opaRes.Violations)
	}

	reqSpec, _ := json.Marshal(doc)
	res := &store.Resource{
		ID: rid, StateUnitID: su.ID, Kind: kind, Name: name, ParentResourceID: parentID,
		ResourceKey: fmt.Sprintf("gcp:%s:%s:%s", su.ScopeID, kind, name), TFAddress: tfAddr,
		APMID: apm, Lifecycle: "proposed", Gate: "REQUESTED", SyncStatus: "PENDING",
		CurrentRequestID: reqID, CurrentApprovalID: aprID, CreatedAt: s.Store.Now(),
	}
	req := &store.ResourceRequest{
		ID: reqID, SubmissionID: subID, ResourceID: rid, Kind: kind, Action: "create",
		SchemaVersion: "1.0.0", RequestedSpec: reqSpec, RequestedSpecSHA256: hash.MustCanonicalSHA256(doc),
		SourcePointer: pointer, Status: "PENDING_APPROVAL", RequestedBy: requestedBy,
		TemporalWorkflowID: "req-" + reqID, SubmittedAt: s.Store.Now(),
	}
	gate, err := s.Store.GetGate(ctx, kindMeta.ApprovalGateKey)
	if err != nil {
		return nil, nil, err
	}
	apr := &store.Approval{
		ID: aprID, RequestID: reqID, ResourceID: rid, GateKey: kindMeta.ApprovalGateKey,
		GateVersion: gate.Version, Status: "PENDING",
	}
	decs := s.seedDecisions(apr, gate, meta)
	if err := s.Store.PersistIntake(ctx, store.IntakePersist{
		Resource: res, Request: req, Approval: apr, Decisions: decs,
	}); err != nil {
		return nil, nil, err
	}
	return res, req, nil
}

func (s *Service) seedDecisions(apr *store.Approval, gate store.GateConfig, meta map[string]any) []*store.ApprovalDecision {
	var decs []*store.ApprovalDecision
	var cfg struct {
		Approvers []struct {
			Key          string `json:"key"`
			TicketField  string `json:"ticket_field"`
			Role         string `json:"role"`
			Mandatory    bool   `json:"mandatory"`
		} `json:"approvers"`
	}
	_ = json.Unmarshal(gate.Config, &cfg)
	for i, a := range cfg.Approvers {
		identity := a.Role
		if a.TicketField == "/metadata/owner" {
			identity = fmt.Sprint(meta["owner"])
		}
		decs = append(decs, &store.ApprovalDecision{
			ID: uuid.New().String(), ApprovalID: apr.ID, ApproverKey: a.Key,
			ApproverIdentity: identity, Phase: i, Mandatory: a.Mandatory, Status: "pending",
		})
	}
	return decs
}

func (s *Service) detail(req *store.ResourceRequest, res *store.Resource) map[string]any {
	var spec map[string]any
	_ = json.Unmarshal(req.RequestedSpec, &spec)
	return map[string]any{
		"request_id": req.ID,
		"resource_id": res.ID,
		"kind": req.Kind,
		"status": req.Status,
		"source_pointer": req.SourcePointer,
		"spec": spec,
		"resource": map[string]any{
			"resource_id": res.ID,
			"name": res.Name,
			"tf_address": res.TFAddress,
			"gate": res.Gate,
		},
		"approval": map[string]any{
			"approval_id": res.CurrentApprovalID,
			"gate_key":    kindApprovalGate(s, req.Kind),
			"status":      "PENDING",
		},
	}
}

func kindApprovalGate(s *Service, kind string) string {
	k, err := s.Store.GetKind(context.Background(), kind)
	if err != nil {
		return ""
	}
	return k.ApprovalGateKey
}

func (s *Service) GetRequest(ctx context.Context, id string) (map[string]any, error) {
	bundle, err := s.Store.GetRequestBundle(ctx, id)
	if err != nil {
		return nil, err
	}
	return query.FormatRequestDetail(bundle), nil
}

func coalesce(v, def string) string {
	if v == "" {
		return def
	}
	return v
}

// ListKinds returns catalog entries for GET /api/v1/kinds.
func (s *Service) ListKinds(ctx context.Context) ([]map[string]any, error) {
	kinds, err := s.Store.ListKinds(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]map[string]any, 0, len(kinds))
	for _, k := range kinds {
		out = append(out, query.FormatKindRow(k))
	}
	return out, nil
}
