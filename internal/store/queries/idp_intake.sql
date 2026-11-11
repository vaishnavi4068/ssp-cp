-- name: FindSubmissionByIdempotency :one
SELECT submission_id FROM idp.submission WHERE apm_id = $1 AND idempotency_key = $2;

-- name: GetRequestBySubmission :one
SELECT request_id FROM idp.request WHERE submission_id = $1 ORDER BY submitted_at ASC LIMIT 1;

-- name: InsertSubmission :one
INSERT INTO idp.submission (submission_id, channel, apm_id, submitted_by, idempotency_key, raw_payload, raw_payload_sha256)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING submission_id, channel, apm_id, submitted_by, idempotency_key, raw_payload, raw_payload_sha256, submitted_at;

-- name: InsertResource :one
INSERT INTO idp.resource (
  resource_id, state_unit_id, kind, name, parent_resource_id, resource_key, tf_address, apm_id,
  lifecycle, gate, sync_status, current_request_id, current_approval_id
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, 'proposed', 'REQUESTED', 'PENDING', $9, $10
)
RETURNING resource_id, state_unit_id, kind, name, parent_resource_id, resource_key, tf_address, apm_id,
          lifecycle, gate, sync_status, current_request_id, current_approval_id, created_at, updated_at, deleted_at;

-- name: InsertRequest :one
INSERT INTO idp.request (
  request_id, submission_id, resource_id, kind, action, schema_version, requested_spec, requested_spec_sha256,
  source_pointer, status, requested_by, temporal_workflow_id
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9, 'PENDING_APPROVAL', $10, $11
)
RETURNING request_id, submission_id, resource_id, kind, action, schema_version, requested_spec,
          requested_spec_sha256, source_pointer, base_approval_id, status, status_reason,
          temporal_workflow_id, requested_by, submitted_at, updated_at;

-- name: InsertApproval :one
INSERT INTO idp.approval (approval_id, request_id, resource_id, gate_key, gate_version, status)
VALUES ($1, $2, $3, $4, $5, 'PENDING')
RETURNING approval_id, request_id, resource_id, gate_key, gate_version, status, guardrail_trace,
          approved_spec, approved_spec_sha256, policy_evaluation_id, temporal_workflow_id,
          decided_at, valid_until;

-- name: InsertApprovalDecision :one
INSERT INTO idp.approval_decision (
  decision_id, approval_id, approver_key, approver_identity, phase, mandatory, status
) VALUES ($1, $2, $3, $4, $5, $6, 'pending')
RETURNING decision_id, approval_id, approver_key, approver_identity, phase, mandatory, status,
          sla_deadline, responded_by, response_comment, responded_at, escalation_count, escalated_to;
