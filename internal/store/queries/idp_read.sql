-- name: GetRequestRow :one
SELECT request_id, submission_id, resource_id, kind, action, schema_version, requested_spec,
       requested_spec_sha256, source_pointer, base_approval_id, status, status_reason,
       temporal_workflow_id, requested_by, submitted_at, updated_at
FROM idp.request WHERE request_id = $1;

-- name: ListRequests :many
SELECT request_id, submission_id, resource_id, kind, action, schema_version, requested_spec,
       requested_spec_sha256, source_pointer, base_approval_id, status, status_reason,
       temporal_workflow_id, requested_by, submitted_at, updated_at
FROM idp.request
WHERE (sqlc.narg(kind_filter)::text IS NULL OR kind = sqlc.narg(kind_filter))
  AND (sqlc.narg(status_filter)::text IS NULL OR status = sqlc.narg(status_filter))
ORDER BY submitted_at DESC;

-- name: GetResource :one
SELECT resource_id, state_unit_id, kind, name, parent_resource_id, resource_key, tf_address, apm_id,
       lifecycle, gate, sync_status, current_request_id, current_approval_id, created_at, updated_at, deleted_at
FROM idp.resource WHERE resource_id = $1;

-- name: GetApprovalByID :one
SELECT approval_id, request_id, resource_id, gate_key, gate_version, status, guardrail_trace,
       approved_spec, approved_spec_sha256, policy_evaluation_id, temporal_workflow_id,
       decided_at, valid_until
FROM idp.approval WHERE approval_id = $1;

-- name: GetApprovalByRequest :one
SELECT approval_id, request_id, resource_id, gate_key, gate_version, status, guardrail_trace,
       approved_spec, approved_spec_sha256, policy_evaluation_id, temporal_workflow_id,
       decided_at, valid_until
FROM idp.approval WHERE request_id = $1;

-- name: ListApprovals :many
SELECT approval_id, request_id, resource_id, gate_key, gate_version, status, guardrail_trace,
       approved_spec, approved_spec_sha256, policy_evaluation_id, temporal_workflow_id,
       decided_at, valid_until
FROM idp.approval
WHERE (sqlc.narg(status_filter)::text IS NULL OR status = sqlc.narg(status_filter))
ORDER BY decided_at DESC NULLS LAST;

-- name: ListApprovalDecisions :many
SELECT decision_id, approval_id, approver_key, approver_identity, phase, mandatory, status,
       sla_deadline, responded_by, response_comment, responded_at, escalation_count, escalated_to
FROM idp.approval_decision WHERE approval_id = $1 ORDER BY phase ASC;

-- name: UpdateApprovalDecision :exec
UPDATE idp.approval_decision
SET status = $2, responded_by = $3, response_comment = $4, responded_at = now()
WHERE decision_id = $1;

-- name: UpdateRequestStatus :exec
UPDATE idp.request SET status = $2, status_reason = sqlc.narg(status_reason), updated_at = now()
WHERE request_id = $1;

-- name: UpdateApprovalApproved :exec
UPDATE idp.approval
SET status = 'APPROVED', approved_spec = $2, approved_spec_sha256 = $3, guardrail_trace = $4,
    decided_at = now(), valid_until = now() + interval '30 days'
WHERE approval_id = $1;

-- name: UpdateApprovalDenied :exec
UPDATE idp.approval SET status = 'DENIED', decided_at = now() WHERE approval_id = $1;

-- name: UpdateResourceGate :exec
UPDATE idp.resource SET gate = $2, current_approval_id = $3 WHERE resource_id = $1;

-- name: GetSubmission :one
SELECT submission_id, channel, source_ref, apm_id, submitted_by, on_behalf_of, idempotency_key,
       raw_payload, raw_payload_sha256, submitted_at
FROM idp.submission WHERE submission_id = $1;

-- name: ListResourceStatus :many
SELECT resource_id, resource_key, kind, name, apm_id, project_id, lob, lifecycle, gate, sync_status,
       request_id, action, request_status, submitted_at, approval_id, approval_status, decided_at,
       expected_revision_no, expected_revision_status, exists_in_cloud, observed_changed_at, open_drift_count
FROM idp.v_resource_status
WHERE (sqlc.narg(resource_id_filter)::uuid IS NULL OR resource_id = sqlc.narg(resource_id_filter))
ORDER BY submitted_at DESC NULLS LAST;

-- name: UpdateStateUnitStatus :exec
UPDATE idp.state_unit SET status = $2, updated_at = now() WHERE state_unit_id = $1;

-- name: GetStateUnit :one
SELECT state_unit_id, cloud, scope_type, scope_id, lob, environment, apm_id, state_bucket,
       state_prefix, executor_identity, current_expected_rev, applied_expected_rev, status,
       created_at, updated_at
FROM idp.state_unit WHERE state_unit_id = $1;
