package store

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/vaishnavi4068/ssp-cp/internal/store/db"
)

func (p *Postgres) RecordPolicyEvaluation(ctx context.Context, pe PolicyEvaluation) (string, error) {
	eid := pe.ID
	if eid == "" {
		eid = uuid.NewString()
	}
	viol, _ := json.Marshal(pe.Violations)
	mut, _ := json.Marshal(pe.Mutations)
	row, err := p.q.InsertPolicyEvaluation(ctx, db.InsertPolicyEvaluationParams{
		EvaluationID: pgUUIDMust(eid), Stage: pe.Stage, RequestID: pgUUIDMust(pe.RequestID),
		OpaPackage: pe.OPAPackage, BundleRevision: pe.BundleRevision, InputSha256: pe.InputSHA256,
		Decision: pe.Decision, Violations: viol, Mutations: mut,
	})
	if err != nil {
		return "", err
	}
	return uuidStr(row.EvaluationID), nil
}

func (p *Postgres) ListPolicyEvaluations(ctx context.Context, requestID string) ([]PolicyEvaluation, error) {
	rows, err := p.q.ListPolicyEvaluationsByRequest(ctx, pgUUIDMust(requestID))
	if err != nil {
		return nil, err
	}
	out := make([]PolicyEvaluation, 0, len(rows))
	for _, r := range rows {
		out = append(out, PolicyEvaluation{
			ID: uuidStr(r.EvaluationID), Stage: r.Stage, RequestID: uuidStr(r.RequestID),
			OPAPackage: r.OpaPackage, BundleRevision: r.BundleRevision, InputSHA256: r.InputSha256,
			Decision: r.Decision, Violations: r.Violations, Mutations: r.Mutations, EvaluatedAt: r.EvaluatedAt.Time,
		})
	}
	return out, nil
}

func (p *Postgres) RecordGateEvent(ctx context.Context, ev GateEvent) error {
	_, err := p.q.InsertGateEvent(ctx, db.InsertGateEventParams{
		StateUnitID: pgUUID(ev.StateUnitID), ResourceID: pgUUIDMust(ev.ResourceID), RequestID: pgUUIDMust(ev.RequestID),
		Gate: ev.Gate, EventType: ev.EventType, Actor: ev.Actor, Detail: ev.Detail,
	})
	return err
}

func (p *Postgres) RecordLifecycleTask(ctx context.Context, task LifecycleTask) error {
	_, err := p.q.InsertLifecycleTask(ctx, db.InsertLifecycleTaskParams{
		ResourceID: pgUUIDMust(task.ResourceID), ApprovalID: pgUUIDMust(task.ApprovalID),
		Phase: task.Phase, TaskType: task.TaskType, TaskKey: task.TaskKey, Spec: task.Spec,
	})
	return err
}

func (p *Postgres) ListLifecycleTasks(ctx context.Context, approvalID string) ([]LifecycleTask, error) {
	rows, err := p.q.ListLifecycleTasksByApproval(ctx, pgUUIDMust(approvalID))
	if err != nil {
		return nil, err
	}
	out := make([]LifecycleTask, 0, len(rows))
	for _, r := range rows {
		out = append(out, LifecycleTask{
			ID: uuidStr(r.TaskID), ResourceID: uuidStr(r.ResourceID), ApprovalID: uuidStr(r.ApprovalID),
			Phase: r.Phase, TaskType: r.TaskType, TaskKey: r.TaskKey, Spec: r.Spec, Status: r.Status,
		})
	}
	return out, nil
}

func (p *Postgres) ListAudit(ctx context.Context, resourceID, requestID string, limit int) (AuditSnapshot, error) {
	if limit <= 0 {
		limit = 100
	}
	var resUUID, reqUUID pgtype.UUID
	if resourceID != "" {
		resUUID = pgUUIDMust(resourceID)
	}
	if requestID != "" {
		reqUUID = pgUUIDMust(requestID)
	}
	snap := AuditSnapshot{}
	gateRows, err := p.q.ListGateEvents(ctx, db.ListGateEventsParams{Column1: resUUID, Column2: reqUUID, Limit: int32(limit)})
	if err == nil {
		for _, g := range gateRows {
			var detail any
			_ = json.Unmarshal(g.Detail, &detail)
			snap.GateEvents = append(snap.GateEvents, map[string]any{
				"event_id": g.EventID, "occurred_at": g.OccurredAt.Time, "gate": g.Gate,
				"event_type": g.EventType, "actor": g.Actor, "detail": detail,
				"resource_id": uuidStr(g.ResourceID), "request_id": uuidStr(g.RequestID),
			})
		}
	}
	logRows, err := p.q.ListCpAuditLogs(ctx, db.ListCpAuditLogsParams{Column1: resUUID, Column2: reqUUID, Limit: int32(limit)})
	if err == nil {
		for _, a := range logRows {
			var detail any
			_ = json.Unmarshal(a.Details, &detail)
			snap.AuditLogs = append(snap.AuditLogs, map[string]any{
				"audit_id": uuidStr(a.AuditID), "occurred_at": a.OccurredAt.Time, "actor_username": a.ActorUsername,
				"actor_role": a.ActorRole, "action_type": a.ActionType, "reason": a.Reason, "details": detail,
			})
		}
	}
	if requestID != "" {
		peRows, err := p.q.ListPolicyEvaluationsByRequest(ctx, pgUUIDMust(requestID))
		if err == nil {
			for _, pe := range peRows {
				snap.PolicyEvaluations = append(snap.PolicyEvaluations, map[string]any{
					"evaluation_id": uuidStr(pe.EvaluationID), "stage": pe.Stage, "decision": pe.Decision,
					"opa_package": pe.OpaPackage, "evaluated_at": pe.EvaluatedAt.Time,
				})
			}
		}
	}
	return snap, nil
}

func (p *Postgres) Ready(ctx context.Context) error {
	_, err := p.q.PingResourceKind(ctx)
	return err
}

func (p *Postgres) GetResourceObserved(ctx context.Context, resourceID string) (map[string]any, bool, error) {
	row, err := p.q.GetResourceObserved(ctx, pgUUIDMust(resourceID))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	var projection any
	_ = json.Unmarshal(row.Projection, &projection)
	return map[string]any{
		"resource_id": uuidStr(row.ResourceID), "exists_in_cloud": row.ExistsInCloud,
		"cloud_resource_id": textVal(row.CloudResourceID), "projection": projection,
		"projection_sha256": row.ProjectionSha256, "changed_at": row.ChangedAt.Time,
	}, true, nil
}

func (p *Postgres) ListDriftFindings(ctx context.Context, resourceID string) ([]map[string]any, error) {
	rows, err := p.q.ListDriftFindings(ctx, pgUUIDMust(resourceID))
	if err != nil {
		return nil, err
	}
	out := make([]map[string]any, 0, len(rows))
	for _, d := range rows {
		var exp, obs any
		_ = json.Unmarshal(d.ExpectedValue, &exp)
		_ = json.Unmarshal(d.ObservedValue, &obs)
		out = append(out, map[string]any{
			"drift_id": uuidStr(d.DriftID), "drift_kind": d.DriftKind, "attribute_path": d.AttributePath,
			"expected_value": exp, "observed_value": obs, "severity": d.Severity, "status": d.Status,
			"detected_at": d.DetectedAt.Time,
		})
	}
	return out, nil
}
