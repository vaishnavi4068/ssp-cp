-- name: InsertPolicyEvaluation :one
INSERT INTO idp.policy_evaluation (
  evaluation_id, stage, request_id, opa_package, bundle_revision, input_sha256, decision, violations, mutations
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9
)
RETURNING evaluation_id, stage, request_id, revision_id, opa_package, bundle_revision, input_sha256,
          decision, violations, mutations, evaluated_at;

-- name: InsertGateEvent :one
INSERT INTO idp.gate_event (
  event_id, state_unit_id, resource_id, request_id, gate, event_type, actor, detail
) VALUES (
  gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7
)
RETURNING event_id, occurred_at, state_unit_id, resource_id, request_id, gate, event_type, actor, detail, published_at;

-- name: InsertLifecycleTask :one
INSERT INTO idp.lifecycle_task (
  task_id, resource_id, approval_id, phase, task_type, task_key, spec, status
) VALUES (
  gen_random_uuid(), $1, $2, $3, $4, $5, $6, 'PENDING'
)
RETURNING task_id, resource_id, approval_id, phase, task_type, task_key, spec, status, external_ref, attempts, last_error, updated_at;

-- name: ListPolicyEvaluationsByRequest :many
SELECT evaluation_id, stage, request_id, revision_id, opa_package, bundle_revision, input_sha256,
       decision, violations, mutations, evaluated_at
FROM idp.policy_evaluation
WHERE request_id = $1
ORDER BY evaluated_at ASC;

-- name: ListGateEvents :many
SELECT event_id, occurred_at, state_unit_id, resource_id, request_id, gate, event_type, actor, detail, published_at
FROM idp.gate_event
WHERE ($1::uuid IS NULL OR resource_id = $1)
  AND ($2::uuid IS NULL OR request_id = $2)
ORDER BY occurred_at DESC
LIMIT $3;

-- name: ListCpAuditLogs :many
SELECT audit_id, occurred_at, actor_username, actor_role, source_ip, action_type,
       resource_id, request_id, approval_id, reason, details
FROM idp.cp_audit_log
WHERE ($1::uuid IS NULL OR resource_id = $1)
  AND ($2::uuid IS NULL OR request_id = $2)
ORDER BY occurred_at DESC
LIMIT $3;

-- name: ListLifecycleTasksByApproval :many
SELECT task_id, resource_id, approval_id, phase, task_type, task_key, spec, status, external_ref, attempts, last_error, updated_at
FROM idp.lifecycle_task
WHERE approval_id = $1
ORDER BY phase ASC, task_key ASC;

-- name: GetResourceObserved :one
SELECT resource_id, exists_in_cloud, cloud_resource_id, projection, projection_sha256, changed_at
FROM idp.resource_observed
WHERE resource_id = $1;

-- name: ListDriftFindings :many
SELECT drift_id, resource_id, drift_kind, attribute_path, expected_value, observed_value,
       severity, guardrail_rule_id, status, resolution, detected_at
FROM idp.drift_finding
WHERE resource_id = $1
ORDER BY detected_at DESC;

-- name: PingResourceKind :one
SELECT kind FROM idp.resource_kind WHERE enabled = true LIMIT 1;
