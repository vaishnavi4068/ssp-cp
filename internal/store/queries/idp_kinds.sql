-- name: GetResourceKind :one
SELECT kind, cloud, parent_kind, display_name, schema_uri, schema_version, tf_module_source,
       tfvars_collection, tf_address_template, opa_package, approval_gate_key, drift_ignore_paths,
       legacy_resource_type, enabled, created_at
FROM idp.resource_kind
WHERE kind = $1 AND enabled = true;

-- name: ListResourceKinds :many
SELECT kind, cloud, parent_kind, display_name, schema_uri, schema_version, tf_module_source,
       tfvars_collection, tf_address_template, opa_package, approval_gate_key, drift_ignore_paths,
       legacy_resource_type, enabled, created_at
FROM idp.resource_kind
WHERE enabled = true
ORDER BY kind ASC;

-- name: GetApprovalGate :one
SELECT gate_key, version, config, enabled, updated_by, updated_at
FROM idp.approval_gate_config
WHERE gate_key = $1 AND enabled = true;

-- name: GetApmAlias :one
SELECT apm_id, alias, app_tier, created_at
FROM idp.apm_alias
WHERE apm_id = $1;

-- name: GetStateUnitByScope :one
SELECT state_unit_id, cloud, scope_type, scope_id, lob, environment, apm_id, state_bucket,
       state_prefix, executor_identity, current_expected_rev, applied_expected_rev, status,
       created_at, updated_at
FROM idp.state_unit
WHERE cloud = 'gcp' AND scope_id = $1;

-- name: InsertStateUnit :one
INSERT INTO idp.state_unit (
  cloud, scope_type, scope_id, lob, environment, apm_id, state_bucket, state_prefix, executor_identity, status
) VALUES (
  'gcp', 'project', $1, $2, $3, $4, 'microdrive-dev-spp-tfstate', sqlc.arg(state_prefix), sqlc.arg(executor_identity), 'active'
)
RETURNING state_unit_id, cloud, scope_type, scope_id, lob, environment, apm_id, state_bucket,
          state_prefix, executor_identity, current_expected_rev, applied_expected_rev, status,
          created_at, updated_at;
