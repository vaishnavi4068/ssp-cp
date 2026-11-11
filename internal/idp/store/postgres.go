package store

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/vaishnavi4068/ssp-cp/internal/store/db"
)

// Postgres implements Backend using sqlc + pgx (idp schema).
type Postgres struct {
	pool *pgxpool.Pool
	q    *db.Queries
}

func OpenPostgresFromEnv() (Backend, error) {
	dsn := os.Getenv("SSP_DATABASE_URL")
	if dsn == "" {
		dsn = os.Getenv("DATABASE_URL")
	}
	if dsn == "" {
		return nil, fmt.Errorf("no database url")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return &Postgres{pool: pool, q: db.New(pool)}, nil
}

func (p *Postgres) Now() time.Time { return time.Now().UTC() }

func (p *Postgres) GetKind(ctx context.Context, kind string) (ResourceKind, error) {
	row, err := p.q.GetResourceKind(ctx, kind)
	if err != nil {
		return ResourceKind{}, err
	}
	return ResourceKind{
		Kind: row.Kind, TFVarsCollection: row.TfvarsCollection, TFAddressTemplate: row.TfAddressTemplate,
		OPAPackage: row.OpaPackage, ApprovalGateKey: textVal(row.ApprovalGateKey),
	}, nil
}

func (p *Postgres) ListKinds(ctx context.Context) ([]ResourceKind, error) {
	rows, err := p.q.ListResourceKinds(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]ResourceKind, 0, len(rows))
	for _, row := range rows {
		out = append(out, ResourceKind{
			Kind: row.Kind, TFVarsCollection: row.TfvarsCollection, TFAddressTemplate: row.TfAddressTemplate,
			OPAPackage: row.OpaPackage, ApprovalGateKey: textVal(row.ApprovalGateKey),
		})
	}
	return out, nil
}

func (p *Postgres) GetGate(ctx context.Context, gateKey string) (GateConfig, error) {
	row, err := p.q.GetApprovalGate(ctx, gateKey)
	if err != nil {
		return GateConfig{}, err
	}
	return GateConfig{GateKey: row.GateKey, Version: int(row.Version), Config: row.Config}, nil
}

func (p *Postgres) ResolveApm(ctx context.Context, apmID string) (alias, appTier string) {
	row, err := p.q.GetApmAlias(ctx, apmID)
	if err != nil {
		return "orders", "2"
	}
	return row.Alias, textVal(row.AppTier)
}

func (p *Postgres) EnsureStateUnit(ctx context.Context, projectID, lob, env, apm string) (*StateUnit, error) {
	row, err := p.q.GetStateUnitByScope(ctx, projectID)
	if err == nil {
		return mapStateUnit(row), nil
	}
	prefix := fmt.Sprintf("projects/%s", projectID)
	execID := fmt.Sprintf("idp-tf@%s.iam.gserviceaccount.com", projectID)
	ins, err := p.q.InsertStateUnit(ctx, db.InsertStateUnitParams{
		ScopeID: projectID, Lob: pgText(lob), Environment: pgText(env), ApmID: pgText(apm),
		StatePrefix: prefix, ExecutorIdentity: execID,
	})
	if err != nil {
		return nil, err
	}
	return mapStateUnit(ins), nil
}

func (p *Postgres) FindIdempotentRequest(ctx context.Context, apmID, key string) (string, bool, error) {
	sid, err := p.q.FindSubmissionByIdempotency(ctx, db.FindSubmissionByIdempotencyParams{ApmID: apmID, IdempotencyKey: key})
	if err != nil {
		return "", false, nil
	}
	rid, err := p.q.GetRequestBySubmission(ctx, sid)
	if err != nil {
		return "", false, nil
	}
	return uuidStr(rid), true, nil
}

func (p *Postgres) PersistIntake(ctx context.Context, in IntakePersist) error {
	tx, err := p.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	q := p.q.WithTx(tx)
	if in.Submission != nil {
		_, err = q.InsertSubmission(ctx, db.InsertSubmissionParams{
			SubmissionID: pgUUIDMust(in.Submission.ID), Channel: in.Submission.Channel, ApmID: in.Submission.APMID,
			SubmittedBy: in.Submission.SubmittedBy, IdempotencyKey: in.Submission.IdempotencyKey,
			RawPayload: in.Submission.RawPayload, RawPayloadSha256: in.Submission.RawPayloadSHA256,
		})
		if err != nil {
			return err
		}
	}
	if in.Resource != nil {
		parent := pgUUID(in.Resource.ParentResourceID)
		_, err = q.InsertResource(ctx, db.InsertResourceParams{
			ResourceID: pgUUIDMust(in.Resource.ID), StateUnitID: pgUUIDMust(in.Resource.StateUnitID),
			Kind: in.Resource.Kind, Name: in.Resource.Name, ParentResourceID: parent,
			ResourceKey: in.Resource.ResourceKey, TfAddress: in.Resource.TFAddress, ApmID: in.Resource.APMID,
			CurrentRequestID: pgUUIDMust(in.Resource.CurrentRequestID), CurrentApprovalID: pgUUIDMust(in.Resource.CurrentApprovalID),
		})
		if err != nil {
			return err
		}
	}
	if in.Request != nil {
		_, err = q.InsertRequest(ctx, db.InsertRequestParams{
			RequestID: pgUUIDMust(in.Request.ID), SubmissionID: pgUUIDMust(in.Request.SubmissionID),
			ResourceID: pgUUIDMust(in.Request.ResourceID), Kind: in.Request.Kind, Action: in.Request.Action,
			SchemaVersion: in.Request.SchemaVersion, RequestedSpec: in.Request.RequestedSpec,
			RequestedSpecSha256: in.Request.RequestedSpecSHA256, SourcePointer: pgText(in.Request.SourcePointer),
			RequestedBy: in.Request.RequestedBy, TemporalWorkflowID: pgText(in.Request.TemporalWorkflowID),
		})
		if err != nil {
			return err
		}
	}
	if in.Approval != nil {
		_, err = q.InsertApproval(ctx, db.InsertApprovalParams{
			ApprovalID: pgUUIDMust(in.Approval.ID), RequestID: pgUUIDMust(in.Approval.RequestID),
			ResourceID: pgUUIDMust(in.Approval.ResourceID), GateKey: pgText(in.Approval.GateKey),
			GateVersion: pgInt4(in.Approval.GateVersion),
		})
		if err != nil {
			return err
		}
	}
	for _, d := range in.Decisions {
		_, err = q.InsertApprovalDecision(ctx, db.InsertApprovalDecisionParams{
			DecisionID: pgUUIDMust(d.ID), ApprovalID: pgUUIDMust(d.ApprovalID), ApproverKey: d.ApproverKey,
			ApproverIdentity: d.ApproverIdentity, Phase: int32(d.Phase), Mandatory: d.Mandatory,
		})
		if err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (p *Postgres) GetRequestBundle(ctx context.Context, requestID string) (*RequestBundle, error) {
	rid := pgUUIDMust(requestID)
	row, err := p.q.GetRequestRow(ctx, rid)
	if err != nil {
		return nil, err
	}
	req := mapRequestRow(row)
	res, err := p.q.GetResource(ctx, row.ResourceID)
	if err != nil {
		return nil, err
	}
	sub, _ := p.q.GetSubmission(ctx, ridToUUID(row.SubmissionID))
	aprRow, _ := p.q.GetApprovalByRequest(ctx, rid)
	var decs []*ApprovalDecision
	if aprRow.ApprovalID.Valid {
		rows, _ := p.q.ListApprovalDecisions(ctx, aprRow.ApprovalID)
		for _, d := range rows {
			decs = append(decs, mapDecisionRow(d))
		}
	}
	return &RequestBundle{
		Request: req, Resource: mapResourceRow(res),
		Submission: mapSubmissionRow(sub), Approval: mapApprovalByRequestRow(aprRow), Decisions: decs,
	}, nil
}

func (p *Postgres) ListRequestIDs(ctx context.Context, kindFilter, statusFilter string) ([]string, error) {
	rows, err := p.q.ListRequests(ctx, db.ListRequestsParams{
		KindFilter:   pgText(kindFilter), StatusFilter: pgText(statusFilter),
	})
	if err != nil {
		return nil, err
	}
	var ids []string
	for _, r := range rows {
		ids = append(ids, uuidStr(r.RequestID))
	}
	return ids, nil
}

func (p *Postgres) ListApprovalIDs(ctx context.Context, statusFilter string) ([]string, error) {
	rows, err := p.q.ListApprovals(ctx, pgText(statusFilter))
	if err != nil {
		return nil, err
	}
	var ids []string
	for _, a := range rows {
		ids = append(ids, uuidStr(a.ApprovalID))
	}
	return ids, nil
}

func (p *Postgres) ListResourceStatus(ctx context.Context, resourceID string) ([]map[string]any, error) {
	var filter pgtype.UUID
	if resourceID != "" {
		filter = pgUUIDMust(resourceID)
	}
	rows, err := p.q.ListResourceStatus(ctx, filter)
	if err != nil {
		return nil, err
	}
	out := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		out = append(out, map[string]any{
			"resource_id": uuidStr(r.ResourceID), "resource_key": r.ResourceKey, "kind": r.Kind, "name": r.Name,
			"apm_id": r.ApmID, "project_id": r.ProjectID, "lob": textVal(r.Lob),
			"lifecycle": r.Lifecycle, "gate": r.Gate, "sync_status": r.SyncStatus,
		})
	}
	return out, nil
}

func (p *Postgres) UpdateDecision(ctx context.Context, decisionID, status, respondedBy, comment string) error {
	return p.q.UpdateApprovalDecision(ctx, db.UpdateApprovalDecisionParams{
		DecisionID: pgUUIDMust(decisionID), Status: status, RespondedBy: pgText(respondedBy), ResponseComment: pgText(comment),
	})
}

func (p *Postgres) ListDecisions(ctx context.Context, approvalID string) ([]*ApprovalDecision, error) {
	rows, err := p.q.ListApprovalDecisions(ctx, pgUUIDMust(approvalID))
	if err != nil {
		return nil, err
	}
	out := make([]*ApprovalDecision, 0, len(rows))
	for _, d := range rows {
		out = append(out, mapDecisionRow(d))
	}
	return out, nil
}

func (p *Postgres) FinalizeApproval(ctx context.Context, fin ApprovalFinalize) error {
	if fin.Denied {
		if err := p.q.UpdateApprovalDenied(ctx, pgUUIDMust(fin.ApprovalID)); err != nil {
			return err
		}
		apr, err := p.q.GetApprovalByID(ctx, pgUUIDMust(fin.ApprovalID))
		if err != nil {
			return err
		}
		return p.q.UpdateRequestStatus(ctx, db.UpdateRequestStatusParams{
			RequestID: apr.RequestID, Status: "DENIED", StatusReason: pgText(fin.RequestReason),
		})
	}
	if err := p.q.UpdateApprovalApproved(ctx, db.UpdateApprovalApprovedParams{
		ApprovalID: pgUUIDMust(fin.ApprovalID), ApprovedSpec: fin.ApprovedSpec,
		ApprovedSpecSha256: pgText(fin.ApprovedSpecSHA256), GuardrailTrace: fin.GuardrailTrace,
	}); err != nil {
		return err
	}
	apr, err := p.q.GetApprovalByID(ctx, pgUUIDMust(fin.ApprovalID))
	if err != nil {
		return err
	}
	if err := p.q.UpdateRequestStatus(ctx, db.UpdateRequestStatusParams{
		RequestID: apr.RequestID, Status: fin.RequestStatus, StatusReason: pgtype.Text{},
	}); err != nil {
		return err
	}
	return p.q.UpdateResourceGate(ctx, db.UpdateResourceGateParams{
		ResourceID: apr.ResourceID, Gate: fin.ResourceGate, CurrentApprovalID: apr.ApprovalID,
	})
}

func (p *Postgres) GetApproval(ctx context.Context, approvalID string) (*Approval, error) {
	row, err := p.q.GetApprovalByID(ctx, pgUUIDMust(approvalID))
	if err != nil {
		return nil, err
	}
	return mapApprovalIDRow(row), nil
}

func (p *Postgres) GetRequest(ctx context.Context, requestID string) (*ResourceRequest, error) {
	row, err := p.q.GetRequestRow(ctx, pgUUIDMust(requestID))
	if err != nil {
		return nil, err
	}
	return mapRequestRow(row), nil
}

func (p *Postgres) ResourceByID(ctx context.Context, resourceID string) (*Resource, error) {
	row, err := p.q.GetResource(ctx, pgUUIDMust(resourceID))
	if err != nil {
		return nil, err
	}
	return mapResourceRow(row), nil
}

func (p *Postgres) StateUnitByID(ctx context.Context, stateUnitID string) (*StateUnit, error) {
	row, err := p.q.GetStateUnit(ctx, pgUUIDMust(stateUnitID))
	if err != nil {
		return nil, err
	}
	return mapStateUnit(row), nil
}

func (p *Postgres) SetStateUnitStatus(ctx context.Context, stateUnitID, status string) error {
	return p.q.UpdateStateUnitStatus(ctx, db.UpdateStateUnitStatusParams{
		StateUnitID: pgUUIDMust(stateUnitID), Status: status,
	})
}

// helpers
func textVal(t pgtype.Text) string {
	if t.Valid {
		return t.String
	}
	return ""
}
func pgText(s string) pgtype.Text {
	if s == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: s, Valid: true}
}
func pgInt4(n int) pgtype.Int4 { return pgtype.Int4{Int32: int32(n), Valid: true} }
func pgUUID(s string) pgtype.UUID {
	if s == "" {
		return pgtype.UUID{}
	}
	var u pgtype.UUID
	_ = u.Scan(s)
	return u
}
func pgUUIDMust(s string) pgtype.UUID {
	u, err := uuid.Parse(s)
	if err != nil {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: u, Valid: true}
}
func uuidStr(u pgtype.UUID) string {
	if !u.Valid {
		return ""
	}
	id, _ := uuid.FromBytes(u.Bytes[:])
	return id.String()
}
func ridToUUID(u pgtype.UUID) pgtype.UUID { return u }

func mapStateUnit(row db.IdpStateUnit) *StateUnit {
	return &StateUnit{
		ID: uuidStr(row.StateUnitID), ScopeID: row.ScopeID, LOB: textVal(row.Lob),
		Environment: textVal(row.Environment), APMID: textVal(row.ApmID), StateBucket: row.StateBucket,
		ExecutorIdentity: row.ExecutorIdentity, Status: row.Status,
	}
}

func mapRequestRow(row db.IdpRequest) *ResourceRequest {
	return &ResourceRequest{
		ID: uuidStr(row.RequestID), SubmissionID: uuidStr(row.SubmissionID), ResourceID: uuidStr(row.ResourceID),
		Kind: row.Kind, Action: row.Action, SchemaVersion: row.SchemaVersion, RequestedSpec: row.RequestedSpec,
		RequestedSpecSHA256: row.RequestedSpecSha256, SourcePointer: textVal(row.SourcePointer),
		Status: row.Status, StatusReason: textVal(row.StatusReason), RequestedBy: row.RequestedBy,
		TemporalWorkflowID: textVal(row.TemporalWorkflowID), SubmittedAt: row.SubmittedAt.Time,
	}
}

func mapResourceRow(row db.IdpResource) *Resource {
	return &Resource{
		ID: uuidStr(row.ResourceID), StateUnitID: uuidStr(row.StateUnitID), Kind: row.Kind, Name: row.Name,
		ParentResourceID: uuidStr(row.ParentResourceID), ResourceKey: row.ResourceKey, TFAddress: row.TfAddress,
		APMID: row.ApmID, Lifecycle: row.Lifecycle, Gate: row.Gate, SyncStatus: row.SyncStatus,
		CurrentRequestID: uuidStr(row.CurrentRequestID), CurrentApprovalID: uuidStr(row.CurrentApprovalID),
	}
}

func mapSubmissionRow(row db.IdpSubmission) *Submission {
	return &Submission{
		ID: uuidStr(row.SubmissionID), Channel: row.Channel, APMID: row.ApmID, SubmittedBy: row.SubmittedBy,
		IdempotencyKey: row.IdempotencyKey, RawPayload: row.RawPayload, RawPayloadSHA256: row.RawPayloadSha256,
		SubmittedAt: row.SubmittedAt.Time,
	}
}

func mapApprovalIDRow(row db.GetApprovalByIDRow) *Approval {
	return &Approval{
		ID: uuidStr(row.ApprovalID), RequestID: uuidStr(row.RequestID), ResourceID: uuidStr(row.ResourceID),
		GateKey: textVal(row.GateKey), GateVersion: int(row.GateVersion.Int32), Status: row.Status,
		ApprovedSpec: row.ApprovedSpec, ApprovedSpecSHA256: textVal(row.ApprovedSpecSha256),
		GuardrailTrace: row.GuardrailTrace,
	}
}

func mapApprovalByRequestRow(row db.GetApprovalByRequestRow) *Approval {
	return &Approval{
		ID: uuidStr(row.ApprovalID), RequestID: uuidStr(row.RequestID), ResourceID: uuidStr(row.ResourceID),
		GateKey: textVal(row.GateKey), GateVersion: int(row.GateVersion.Int32), Status: row.Status,
		ApprovedSpec: row.ApprovedSpec, ApprovedSpecSHA256: textVal(row.ApprovedSpecSha256),
		GuardrailTrace: row.GuardrailTrace,
	}
}

func mapDecisionRow(d db.ListApprovalDecisionsRow) *ApprovalDecision {
	return &ApprovalDecision{
		ID: uuidStr(d.DecisionID), ApprovalID: uuidStr(d.ApprovalID), ApproverKey: d.ApproverKey,
		ApproverIdentity: d.ApproverIdentity, Phase: int(d.Phase), Mandatory: d.Mandatory, Status: d.Status,
		RespondedBy: textVal(d.RespondedBy), ResponseComment: textVal(d.ResponseComment),
	}
}
