-- ==========================================================================
-- RECONSTRUCTED AND UNVERIFIED SPECIFICATION
-- Source: Sanitized hand transcription from 70 HEIC photographs of the design
--         package "IDP four-gate data model: GCS bucket and Spanner"
--         (originally idp_state_model.sql, draft dated 21 Oct 2026).
-- Status: Reconstructed and unverified. Lines off-screen or not photographed
--         are marked with explicit [Unverified (source gap): [NOT CAPTURED] ...]
--         or [truncated] comments. Do NOT invent unverified source details.
-- Downstream usage: This DDL becomes versioned Alembic migrations in `ssp-cp`.
--
-- SPP User Decisions & Overrides Applied Everywhere in This File:
--   1. GCP only (`cloud CHECK (cloud IN ('gcp'))`, `scope_type = 'project'`).
--   2. Region `us-east1` only (no multi-region `US` or `nam3`, no `us-east4`).
--   3. Database target: Google Cloud AlloyDB for PostgreSQL (`spp_platform` in
--      `microdrive-dev`, `us-east1`) — NOT Cloud SQL.
--   4. Four gates: Requested & Approved stored in full in AlloyDB (zero secrets);
--      Expected & Observed artifacts stored in GCS (`gs://microdrive-dev-spp-tfstate`);
--      short non-sensitive Observed projections (< 2000 bytes) and drift_finding
--      rows in AlloyDB are allowed.
--   5. Environments: only `nonprod` and `prod` (token `nonprod`, no hyphen).
--      `sandbox`, `dev`, `qa`, `test`, `pdev`, `pqa`, `preprod` all map to `nonprod`
--      everywhere (including the Spanner `dbaas_reviewer` skip_condition).
--   6. Single state bucket: `gs://microdrive-dev-spp-tfstate` for now (no per-LOB
--      state buckets).
--   7. No deletion/destroy/replace of any resource without explicit human
--      approval in ANY environment (`nonprod` or `prod`); no `AUTO_APPROVED` for
--      `action = 'delete'`.
--   8. Drift: alert-only, never auto-reapply (`REMEDIATING` and `'reapplied'`
--      removed; remediation goes through a new approved request).
--   9. Runner K8s Jobs execute in namespace `spp-platform` (ADR-AUT-001).
--
-- Hashes are SHA-256 hex over canonical JSON (sorted keys, compact separators, UTF-8).
-- Status vocabularies are CHECK constraints rather than enums so they can evolve
-- without type migrations.
-- ==========================================================================
BEGIN;

CREATE SCHEMA IF NOT EXISTS idp;

-- ===== Helpers =====
-- K8s Job name for a Terraform operation. Retries of the same operation re-derive
-- the same name, get AlreadyExists, and re-attach instead of re-running.
-- Must match tools/validate_examples.py::k8s_job_name.
CREATE OR REPLACE FUNCTION idp.k8s_job_name(p_operation_id text, p_phase text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
  SELECT 'tf-' || replace(p_phase, '_', '-') || '-'
      || substr(encode(sha256(convert_to(p_operation_id, 'UTF8')), 'hex'), 1, 20)
$$;

CREATE OR REPLACE FUNCTION idp.touch_updated_at()
RETURNS trigger LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END
$$;

-- ===== REGISTRY =====
-- [Unverified (source gap): [NOT CAPTURED: source lines 47-52]]
-- ... (order, approvers[], sla_days, follow-ups, escalation, auto_close).
CREATE TABLE idp.approval_gate_config (
  gate_key    text        PRIMARY KEY,
  version     integer     NOT NULL DEFAULT 1 CHECK (version > 0),
  config      jsonb       NOT NULL,
  enabled     boolean     NOT NULL DEFAULT true,
  updated_by  text        NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE idp.approval_gate_config IS
  'Human approval gates. Approvals pin gate_key + version so changing a gate never orphans in-flight approval signals (a legacy lesson).';

-- One row per resource kind: what schema, module, tfvars collection and policy package it uses.
CREATE TABLE idp.resource_kind (
  kind                 text PRIMARY KEY,
  cloud                text NOT NULL DEFAULT 'gcp' CHECK (cloud IN ('gcp')), -- Override: GCP only (source had ('gcp', 'aws', 'azure'))
  parent_kind          text REFERENCES idp.resource_kind (kind),
  display_name         text NOT NULL,
  schema_uri           text NOT NULL,
  schema_version       text NOT NULL,
  tf_module_source     text NOT NULL,
  tfvars_collection    text NOT NULL,
  tf_address_template  text NOT NULL,
  opa_package          text NOT NULL,
  approval_gate_key    text REFERENCES idp.approval_gate_config (gate_key),
  drift_ignore_paths   text[] NOT NULL DEFAULT '{}',
  legacy_resource_type text,   -- Deferred note: source column name was <legacy>_resource_type
  enabled              boolean NOT NULL DEFAULT true,
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cloud, tfvars_collection)
);
COMMENT ON COLUMN idp.resource_kind.tf_module_source IS 'Pinned module ref (git::...?ref=vX.Y.Z). One repo per Terraform resource module.';
COMMENT ON COLUMN idp.resource_kind.tfvars_collection IS 'Key of this kind''s map in the project tfvars (gcs_buckets, spanner_instances, spanner_databases).';
COMMENT ON COLUMN idp.resource_kind.drift_ignore_paths IS 'JSON pointers excluded from Expected-vs-Observed comparison (Terraform-only or app-owned attributes).';

-- Lookup table mapping apm_id to short app token (18th table in idp schema per diagrams PDF p.2 + naming-spec.json).
-- [Unverified (source gap): [NOT CAPTURED in SQL photos; reconstructed from diagrams PDF p.2 and naming-spec.json]]
CREATE TABLE idp.apm_alias (
  apm_id      text PRIMARY KEY CHECK (apm_id ~ '^apm[0-9]{5}$'),
  alias       text NOT NULL UNIQUE CHECK (alias ~ '^[a-z][a-z0-9]{1,11}$'),
  app_tier    text CHECK (app_tier IN ('1', '2', '3', '4')),
  created_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE idp.apm_alias IS
  'Unverified (source gap): 18th table shown in ER diagram (no FK, dashed line) and referenced by naming-spec.json (idp.apm_alias.alias for metadata.apm_id).';

-- ===== TOPOLOGY =====
-- One row per GCP project = one Terraform state file.
CREATE TABLE idp.state_unit (
  state_unit_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cloud                text NOT NULL DEFAULT 'gcp' CHECK (cloud IN ('gcp')), -- Override: GCP only
  -- [Unverified (source gap): [NOT CAPTURED: source lines 96-104; visible fragment: scope_type CHECK (...); columns below reconstructed from UNIQUE constraints, COMMENTs, and idp.v_resource_status]]
  scope_type           text NOT NULL DEFAULT 'project' CHECK (scope_type IN ('project')), -- Override: GCP project only
  scope_id             text NOT NULL,
  lob                  text,
  environment          text CHECK (environment IN ('nonprod', 'prod')), -- Override: nonprod and prod only
  apm_id               text CHECK (apm_id IS NULL OR apm_id ~ '^apm[0-9]{5}$'),
  state_bucket         text NOT NULL DEFAULT 'microdrive-dev-spp-tfstate' CHECK (state_bucket = 'microdrive-dev-spp-tfstate'), -- Override: single state bucket
  state_prefix         text NOT NULL,
  executor_identity    text NOT NULL,
  current_expected_rev integer,
  applied_expected_rev integer,
  status               text NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'frozen', 'decommissioning', 'retired')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cloud, scope_id),
  UNIQUE (state_bucket, state_prefix)
);
COMMENT ON COLUMN idp.state_unit.state_bucket IS 'Single SPP state bucket gs://microdrive-dev-spp-tfstate in us-east1 (overrides source per-LOB bucket idp-tfstate-<lob>).';
COMMENT ON COLUMN idp.state_unit.state_prefix IS 'GCS backend prefix (projects/<project_id>); state is <prefix>/default.tfstate, lock is <prefix>/default.tflock.';
COMMENT ON COLUMN idp.state_unit.executor_identity IS 'Per-project service account, reached by impersonation from the central platform account.';
COMMENT ON COLUMN idp.state_unit.current_expected_rev IS 'Latest rendered revision_no. Advance with UPDATE ... WHERE current_expected_rev IS NOT DISTINCT FROM :prev [truncated in source]';
COMMENT ON COLUMN idp.state_unit.status IS 'frozen = kill switch for this project: the reconciler refuses plan/apply.';

-- Stable identity of a managed resource across all of its requests.
CREATE TABLE idp.resource (
  resource_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  state_unit_id       uuid NOT NULL REFERENCES idp.state_unit (state_unit_id),
  kind                text NOT NULL REFERENCES idp.resource_kind (kind),
  name                text NOT NULL,
  parent_resource_id  uuid REFERENCES idp.resource (resource_id),
  resource_key        text NOT NULL UNIQUE CHECK (resource_key ~ '^gcp:[^:]+:[a-z][a-z0-9_]*:[^:]+$'),
  tf_address          text NOT NULL,
  apm_id              text NOT NULL CHECK (apm_id ~ '^apm[0-9]{5}$'),
  lifecycle           text NOT NULL DEFAULT 'proposed'
                      CHECK (lifecycle IN ('proposed', 'active', 'deleting', 'deleted', 'abandoned')),
  gate                text NOT NULL DEFAULT 'REQUESTED'
                      CHECK (gate IN ('REQUESTED', 'APPROVED', 'EXPECTED', 'OBSERVED')),
  sync_status         text NOT NULL DEFAULT 'PENDING'
                      CHECK (sync_status IN ('PENDING', 'IN_SYNC', 'DRIFTED', 'FAILED', 'UNKNOWN')),
  current_request_id  uuid,
  current_approval_id uuid,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  deleted_at          timestamptz,
  UNIQUE (state_unit_id, kind, name)
);
COMMENT ON COLUMN idp.resource.resource_key IS 'Deterministic: gcp:<project_id>:<kind>:<name>. Spanner databases use <instance>/<database> as name.';
COMMENT ON COLUMN idp.resource.apm_id IS 'Owning APM. Can differ from state_unit.apm_id, e.g. a tenant database on a shared DBaaS Spanner instance.';
COMMENT ON COLUMN idp.resource.gate IS 'Furthest gate reached by the current request.';
CREATE INDEX resource_apm_idx ON idp.resource (apm_id);
CREATE INDEX resource_attention_idx ON idp.resource (sync_status) WHERE sync_status IN ('DRIFTED', 'FAILED');
-- GCS bucket names are global, not per project.
-- [Unverified (source gap): tail of line 148 and lines 149-156 [NOT CAPTURED]; inferred WHERE kind = 'gcs_bucket']
CREATE UNIQUE INDEX resource_gcs_bucket_name_uq ON idp.resource (name) WHERE kind = 'gcs_bucket';

-- ===== GATE 1: REQUESTED =====
-- One user action (UI form, chat, API call, import, or deferred legacy shim).
CREATE TABLE idp.submission (
  submission_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  channel            text NOT NULL CHECK (channel IN ('ui', 'api', 'chat', 'legacy_shim', 'legacy_provisioning_shim', 'import')),
  source_ref         text,
  apm_id             text NOT NULL CHECK (apm_id ~ '^apm[0-9]{5}$'),
  submitted_by       text NOT NULL,
  on_behalf_of       text,
  idempotency_key    text NOT NULL,
  raw_payload        jsonb NOT NULL,
  raw_payload_sha256 text NOT NULL CHECK (raw_payload_sha256 ~ '^[0-9a-f]{64}$'),
  submitted_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (apm_id, idempotency_key),
  CONSTRAINT submission_no_secret_values CHECK (
    raw_payload::text !~* '"(password|passwd|client_secret|private_key|secret_value|api_key|token)"\s*:')
);
COMMENT ON COLUMN idp.submission.raw_payload IS 'BUSINESS PAYLOAD exactly as received. Kept for audit and re-mapping; never executed.';
COMMENT ON COLUMN idp.submission.source_ref IS 'External reference, e.g. legacy ticket TKT-0000004029 (deferred).';

-- One per resource per change. The canonical requested document is immutable.
CREATE TABLE idp.request (
  request_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id         uuid NOT NULL REFERENCES idp.submission (submission_id),
  resource_id           uuid NOT NULL REFERENCES idp.resource (resource_id),
  kind                  text NOT NULL REFERENCES idp.resource_kind (kind),
  action                text NOT NULL CHECK (action IN ('create', 'update', 'delete', 'import')),
  schema_version        text NOT NULL,
  requested_spec        jsonb NOT NULL,
  requested_spec_sha256 text NOT NULL CHECK (requested_spec_sha256 ~ '^[0-9a-f]{64}$'),
  source_pointer        text,
  base_approval_id      uuid,
  status                text NOT NULL DEFAULT 'SUBMITTED'
                        CHECK (status IN ('SUBMITTED', 'INVALID', 'PENDING_APPROVAL', 'APPROVED',
                                          'DENIED', 'EXPIRED', 'CANCELLED', 'SUPERSEDED')),
  status_reason         text,
  temporal_workflow_id  text UNIQUE,
  requested_by          text NOT NULL,
  submitted_at          timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT request_no_secret_values CHECK (
    requested_spec::text !~* '"(password|passwd|client_secret|private_key|secret_value|api_key|token)"\s*:')
);
COMMENT ON COLUMN idp.request.requested_spec IS 'Canonical envelope {api_version, kind, action, metadata, spec}; validated against <kind>.schema.json#/$defs/requested [truncated in source]';
COMMENT ON COLUMN idp.request.source_pointer IS 'JSON pointer into submission.raw_payload this request was mapped from, e.g. /FormData or /resources/1.';
COMMENT ON COLUMN idp.request.base_approval_id IS 'For update/delete: the approval being changed.';
COMMENT ON COLUMN idp.request.temporal_workflow_id IS 'req-<request_id>; a duplicate start is rejected by Temporal.';
CREATE INDEX request_resource_idx ON idp.request (resource_id, submitted_at DESC);
CREATE INDEX request_open_idx ON idp.request (status) WHERE status IN ('SUBMITTED', 'PENDING_APPROVAL');
CREATE INDEX request_spec_gin ON idp.request USING gin (requested_spec jsonb_path_ops);

-- [Unverified (source gap): [NOT CAPTURED: source lines 205-209 (policy_evaluation header incl. evaluation_id PK, inferred from FK in idp.approval)]]
CREATE TABLE idp.policy_evaluation (
  evaluation_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stage           text NOT NULL CHECK (stage IN ('requested', 'approved', 'plan')),
  request_id      uuid REFERENCES idp.request (request_id),
  revision_id     uuid,
  opa_package     text NOT NULL,
  bundle_revision text NOT NULL,
  input_sha256    text NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
  decision        text NOT NULL CHECK (decision IN ('allow', 'deny', 'allow_with_mutations')),
  violations      jsonb NOT NULL DEFAULT '[]',
  mutations       jsonb NOT NULL DEFAULT '[]',
  evaluated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT policy_evaluation_subject CHECK (
       (stage = 'plan' AND revision_id IS NOT NULL AND request_id IS NULL)
    OR (stage <> 'plan' AND request_id IS NOT NULL AND revision_id IS NULL))
);
COMMENT ON COLUMN idp.policy_evaluation.mutations IS 'Guardrail mutations [{rule_id, op, path, value, reason}] proposed by policy and applied at the Approved gate.';
CREATE INDEX policy_evaluation_request_idx ON idp.policy_evaluation (request_id, stage);
CREATE INDEX policy_evaluation_revision_idx ON idp.policy_evaluation (revision_id) WHERE revision_id IS NOT NULL;

-- ===== GATE 2: APPROVED =====
-- The build contract: requested document + enforced guardrails + approvals.
CREATE TABLE idp.approval (
  approval_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id           uuid NOT NULL UNIQUE REFERENCES idp.request (request_id),
  resource_id          uuid NOT NULL REFERENCES idp.resource (resource_id),
  gate_key             text REFERENCES idp.approval_gate_config (gate_key),
  gate_version         integer,
  status               text NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING', 'APPROVED', 'AUTO_APPROVED', 'DENIED', 'EXPIRED', 'REVOKED')),
  approved_spec        jsonb,
  approved_spec_sha256 text CHECK (approved_spec_sha256 ~ '^[0-9a-f]{64}$'),
  guardrail_trace      jsonb NOT NULL DEFAULT '[]',
  policy_evaluation_id uuid REFERENCES idp.policy_evaluation (evaluation_id),
  temporal_workflow_id text,
  decided_at           timestamptz,
  valid_until          timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  -- [Unverified (source gap): [NOT CAPTURED in SQL lines 250-258; example rows in gcs_bucket.gates.json and spanner.gates.json confirm approval row carries approval_id, request_id, resource_id, gate_key, gate_version, status, approved_spec_sha256, guardrail_trace, temporal_workflow_id, decided_at, valid_until; exact CHECK expression below is inferred]]
  CONSTRAINT approval_spec_when_approved CHECK (
    status NOT IN ('APPROVED', 'AUTO_APPROVED')
    OR (approved_spec IS NOT NULL AND approved_spec_sha256 IS NOT NULL)
  ),
  CONSTRAINT approval_no_secret_values CHECK (
    approved_spec IS NULL OR approved_spec::text !~* '"(password|passwd|client_secret|private_key|secret_value|api_key|token)"\s*:'),
  -- Override: No deletion/destroy/replace of any resource without explicit human approval in ANY environment (no AUTO_APPROVED for deletes)
  CONSTRAINT approval_no_auto_approve_delete CHECK (
    status <> 'AUTO_APPROVED' OR coalesce(approved_spec->>'action', '') <> 'delete'
  )
);
CREATE INDEX approval_resource_idx ON idp.approval (resource_id, created_at DESC);
CREATE INDEX approval_pending_idx ON idp.approval (status) WHERE status = 'PENDING';

-- Per-approver state; mirrors legacy approval_requests.
CREATE TABLE idp.approval_decision (
  decision_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  approval_id       uuid NOT NULL REFERENCES idp.approval (approval_id),
  approver_key      text NOT NULL,
  approver_identity text NOT NULL,
  phase             integer NOT NULL DEFAULT 0 CHECK (phase >= 0),
  mandatory         boolean NOT NULL DEFAULT true,
  status            text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'denied', 'escalated', 'auto_approved', 'expired')),
  sla_deadline      timestamptz,
  follow_up_count   integer NOT NULL DEFAULT 0,
  escalation_count  integer NOT NULL DEFAULT 0,
  escalated_to      text,
  responded_by      text,
  response_comment  text,
  requested_at      timestamptz NOT NULL DEFAULT now(),
  responded_at      timestamptz,
  UNIQUE (approval_id, approver_key)
);
COMMENT ON TABLE idp.approval_decision IS
  'Signal contract (from legacy): approval_response {decision_id, status, responded_by, comment}. Requester may not approve their own request (gate config self_approval = deny) [truncated in source].';
CREATE INDEX approval_decision_sla_idx ON idp.approval_decision (sla_deadline) WHERE status = 'pending';

-- ===== GATE 3: EXPECTED  (pointers; artifacts in object storage) =====
-- A complete, immutable snapshot of the desired state of one state unit.
CREATE TABLE idp.expected_revision (
  revision_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  state_unit_id       uuid NOT NULL REFERENCES idp.state_unit (state_unit_id),
  revision_no         integer NOT NULL CHECK (revision_no > 0),
  parent_revision_no  integer,
  artifact_uri        text NOT NULL,
  artifact_generation bigint NOT NULL,
  artifact_sha256     text NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
  manifest            jsonb NOT NULL,
  plan_uri            text,
  plan_summary        jsonb,
  -- [Unverified (source gap): [NOT CAPTURED in SQL lines 302-309; example rows in gcs_bucket.gates.json and spanner.gates.json confirm columns revision_id, state_unit_id, revision_no, parent_revision_no, artifact_uri, artifact_generation, status ('APPLIED'), plan_summary ({add,change,destroy,replace}); exact SQL types/CHECK constraints below are inferred]]
  status              text NOT NULL DEFAULT 'RENDERED'
                      CHECK (status IN ('RENDERED', 'PLANNED', 'BLOCKED', 'APPLYING', 'APPLIED', 'FAILED', 'SUPERSEDED')),
  blocked_reason      text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (state_unit_id, revision_no)
);
COMMENT ON COLUMN idp.expected_revision.artifact_uri IS 'gs://microdrive-dev-spp-tfstate/projects/<project_id>/expected/rev-NNNNNN/terraform.tfvars.json, written with ifGenerationMatch=0 [truncated in source]';
COMMENT ON COLUMN idp.expected_revision.manifest IS 'Copy of manifest.json: terraform/provider/module pins, members with approved_spec_sha256, secret REFERENCES (never values) [truncated in source]';
COMMENT ON COLUMN idp.expected_revision.plan_summary IS 'Counts only: {add, change, destroy, replace}. The plan itself stays in object storage.';
COMMENT ON COLUMN idp.expected_revision.blocked_reason IS 'e.g. destroy_without_delete_request, approved_hash_mismatch, prerequisite_failed.';

-- Every active resource appears in every revision, including unchanged ones.
CREATE TABLE idp.expected_revision_member (
  revision_id uuid NOT NULL REFERENCES idp.expected_revision (revision_id),
  resource_id uuid NOT NULL REFERENCES idp.resource (resource_id),
  approval_id uuid NOT NULL REFERENCES idp.approval (approval_id),
  change      text NOT NULL CHECK (change IN ('unchanged', 'added', 'modified', 'removed')),
  tf_address  text NOT NULL,
  PRIMARY KEY (revision_id, resource_id)
);
CREATE INDEX expected_revision_member_resource_idx ON idp.expected_revision_member (resource_id);

-- One Terraform run = one Kubernetes Job.
CREATE TABLE idp.tf_operation (
  operation_id         text PRIMARY KEY,
  state_unit_id        uuid NOT NULL REFERENCES idp.state_unit (state_unit_id),
  revision_id          uuid NOT NULL REFERENCES idp.expected_revision (revision_id),
  phase                text NOT NULL CHECK (phase IN ('plan', 'apply', 'refresh_plan', 'destroy_plan', 'import')),
  run_key              text NOT NULL DEFAULT '1',
  k8s_namespace        text NOT NULL DEFAULT 'spp-platform', -- Override: spp-platform (ADR-AUT-001)
  k8s_job_name         text NOT NULL UNIQUE,
  executor_identity    text NOT NULL,
  temporal_workflow_id text NOT NULL,
  temporal_activity_id text,
  status               text NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
  tf_exit_code         integer CHECK (tf_exit_code IN (0, 1, 2)),
  state_serial_before  bigint,
  state_serial_after   bigint,
  state_lineage        text,
  logs_uri             text,
  error                jsonb,
  created_at           timestamptz NOT NULL DEFAULT now(),
  started_at           timestamptz,
  finished_at          timestamptz,
  UNIQUE (revision_id, phase, run_key),
  CONSTRAINT tf_operation_id_format CHECK (
    operation_id LIKE 'op:' || state_unit_id::text || ':r%:' || phase || ':' || run_key),
  CONSTRAINT tf_operation_job_name_derived CHECK (k8s_job_name = idp.k8s_job_name(operation_id, phase)),
  CONSTRAINT tf_operation_job_name_len CHECK (length(k8s_job_name) <= 63)
);
-- [Unverified (source gap): [NOT CAPTURED in SQL lines 356-362; example rows in gcs_bucket.gates.json confirm tf_operation tail columns tf_exit_code, state_serial_before, state_serial_after, state_lineage, logs_uri, started_at, finished_at and phases plan/apply/refresh_plan; index below is inferred]]
CREATE INDEX tf_operation_state_unit_idx ON idp.tf_operation (state_unit_id, created_at DESC);

-- ===== GATE 4: OBSERVED  (pointers + small projection) =====
-- One narrow row per capture of a state unit (post-apply, drift scan, inventory).
CREATE TABLE idp.observation (
  observation_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  state_unit_id    uuid NOT NULL REFERENCES idp.state_unit (state_unit_id),
  source           text NOT NULL CHECK (source IN ('post_apply', 'refresh_plan', 'asset_inventory', 'import')),
  operation_id     text REFERENCES idp.tf_operation (operation_id),
  revision_id      uuid REFERENCES idp.expected_revision (revision_id),
  state_uri        text NOT NULL,
  state_generation bigint,
  state_serial     bigint,
  state_lineage    text,
  snapshot_uri     text,
  drift_detected   boolean,
  captured_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON COLUMN idp.observation.state_uri IS 'gs://microdrive-dev-spp-tfstate/projects/<project_id>/default.tfstate (Terraform GCS backend).';
COMMENT ON COLUMN idp.observation.snapshot_uri IS 'Optional terraform show -json copy. Same bucket = same trust boundary (it can contain sensitive values).';
CREATE INDEX observation_state_unit_idx ON idp.observation (state_unit_id, captured_at DESC);

-- Current Observed projection per resource. Upserted only when the hash changes.
CREATE TABLE idp.resource_observed (
  resource_id               uuid PRIMARY KEY REFERENCES idp.resource (resource_id),
  changed_in_observation_id uuid NOT NULL REFERENCES idp.observation (observation_id),
  exists_in_cloud           boolean NOT NULL,
  cloud_resource_id         text,
  projection                jsonb NOT NULL,
  projection_sha256         text NOT NULL CHECK (projection_sha256 ~ '^[0-9a-f]{64}$'),
  changed_at                timestamptz NOT NULL,
  CONSTRAINT resource_observed_projection_small CHECK (octet_length(projection::text) < 2000)
) WITH (fillfactor = 80);
COMMENT ON TABLE idp.resource_observed IS
  'Small, non-sensitive subset of terraform show -json values, keyed like the Expected entry. Under 2 KB so rows stay out of TOAST; written only on change so repeated scans do not churn [truncated in source].';

-- Expected vs Observed, one row per differing attribute.
CREATE TABLE idp.drift_finding (
  drift_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  resource_id       uuid NOT NULL REFERENCES idp.resource (resource_id),
  observation_id    uuid NOT NULL REFERENCES idp.observation (observation_id),
  revision_id       uuid NOT NULL REFERENCES idp.expected_revision (revision_id),
  drift_kind        text NOT NULL
                    CHECK (drift_kind IN ('out_of_band_change', 'config_divergence', 'missing_in_cloud', 'unmanaged_in_cloud')),
  -- [Unverified (source gap): [NOT CAPTURED in SQL lines 408-411; example rows in gcs_bucket.gates.json and spanner.gates.json confirm columns drift_id, resource_id, observation_id, revision_id, drift_kind, attribute_path, expected_value, observed_value, severity, guardrail_rule_id, status, detected_at; exact SQL types/CHECK constraints below are inferred]]
  attribute_path    text NOT NULL,
  expected_value    jsonb,
  observed_value    jsonb,
  severity          text NOT NULL DEFAULT 'critical'
                    CHECK (severity IN ('critical', 'high', 'medium', 'low')),
  guardrail_rule_id text,
  -- Override: Drift is alert-only, never auto-reapply. Removed 'REMEDIATING' from status and 'reapplied' from resolution.
  status            text NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'ACCEPTED')),
  resolution        text CHECK (resolution IN ('spec_updated', 'accepted_risk', 'resource_deleted')),
  detected_at       timestamptz NOT NULL DEFAULT now(),
  resolved_at       timestamptz
);
COMMENT ON COLUMN idp.drift_finding.guardrail_rule_id IS 'Set when the drift undoes a guardrail (e.g. GCS-PAP-001); these default to critical.';
CREATE UNIQUE INDEX drift_finding_open_uq ON idp.drift_finding (resource_id, attribute_path)
  WHERE status IN ('OPEN', 'ACKNOWLEDGED');

-- ===== CROSS-CUTTING =====
-- Pre-apply prerequisites and post-apply bootstrap, materialized from approved_spec.
CREATE TABLE idp.lifecycle_task (
  task_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  resource_id  uuid NOT NULL REFERENCES idp.resource (resource_id),
  approval_id  uuid NOT NULL REFERENCES idp.approval (approval_id),
  phase        text NOT NULL CHECK (phase IN ('pre_apply', 'post_apply')),
  task_type    text NOT NULL CHECK (task_type IN ('ad_group', 'vpc_sc_ingress', 'vpc_sc_project_membership',
                                                  'enable_service', 'dataportal_register', 'cmdb_register',
                                                  'notify_owner', 'backup_enroll')),
  task_key     text NOT NULL,
  spec         jsonb NOT NULL DEFAULT '{}',
  status       text NOT NULL DEFAULT 'PENDING'
               CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED')),
  external_ref text,
  attempts     integer NOT NULL DEFAULT 0,
  last_error   text,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (approval_id, task_key)
);
COMMENT ON COLUMN idp.lifecycle_task.task_key IS 'Deterministic <task_type>:<target> so re-running a workflow never duplicates a directory-service request or CMDB record.';
COMMENT ON COLUMN idp.lifecycle_task.external_ref IS 'Directory-service request id, perimeter PR, CMDB sys_id (deferred), Data Portal id (deferred).';
CREATE INDEX lifecycle_task_open_idx ON idp.lifecycle_task (status) WHERE status IN ('PENDING', 'RUNNING', 'FAILED');

-- Append-only audit trail and transactional outbox.
CREATE TABLE idp.gate_event (
  event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at   timestamptz NOT NULL DEFAULT now(),
  state_unit_id uuid REFERENCES idp.state_unit (state_unit_id),
  resource_id   uuid REFERENCES idp.resource (resource_id),
  request_id    uuid REFERENCES idp.request (request_id),
  gate          text NOT NULL CHECK (gate IN ('REQUESTED', 'APPROVED', 'EXPECTED', 'OBSERVED')),
  event_type    text NOT NULL,
  actor         text NOT NULL,
  detail        jsonb NOT NULL DEFAULT '{}',
  -- [Unverified (source gap): [NOT CAPTURED: source lines 460-461; published_at referenced by gate_event_unpublished_idx and gate_event_guard]]
  published_at  timestamptz
);
COMMENT ON COLUMN idp.gate_event.event_type IS 'request.submitted, approval.granted, expected.rendered, plan.blocked, apply.succeeded, drift.detected, ...';
COMMENT ON COLUMN idp.gate_event.actor IS 'user:<email> or system:<temporal workflow id>.';
CREATE INDEX gate_event_resource_idx ON idp.gate_event (resource_id, occurred_at DESC);
CREATE INDEX gate_event_unpublished_idx ON idp.gate_event (event_id) WHERE published_at IS NULL;

-- ===== Deferred foreign keys (circular references) =====
ALTER TABLE idp.resource
  ADD CONSTRAINT resource_current_request_fk FOREIGN KEY (current_request_id)
      REFERENCES idp.request (request_id) DEFERRABLE INITIALLY DEFERRED,
  ADD CONSTRAINT resource_current_approval_fk FOREIGN KEY (current_approval_id)
      REFERENCES idp.approval (approval_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE idp.request
  ADD CONSTRAINT request_base_approval_fk FOREIGN KEY (base_approval_id)
      REFERENCES idp.approval (approval_id);

ALTER TABLE idp.policy_evaluation
  ADD CONSTRAINT policy_evaluation_revision_fk FOREIGN KEY (revision_id)
      REFERENCES idp.expected_revision (revision_id);

-- ===== Immutability and housekeeping triggers =====
CREATE OR REPLACE FUNCTION idp.request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.requested_spec        IS DISTINCT FROM OLD.requested_spec
  OR NEW.requested_spec_sha256 IS DISTINCT FROM OLD.requested_spec_sha256
  OR NEW.action                IS DISTINCT FROM OLD.action
  OR NEW.kind                  IS DISTINCT FROM OLD.kind
  OR NEW.resource_id           IS DISTINCT FROM OLD.resource_id
  OR NEW.submission_id         IS DISTINCT FROM OLD.submission_id
  OR NEW.schema_version        IS DISTINCT FROM OLD.schema_version THEN
    RAISE EXCEPTION 'idp.request % is immutable; submit a new request instead', OLD.request_id;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION idp.approval_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'PENDING' THEN
    IF NEW.approved_spec        IS DISTINCT FROM OLD.approved_spec
    OR NEW.approved_spec_sha256 IS DISTINCT FROM OLD.approved_spec_sha256
    OR NEW.guardrail_trace      IS DISTINCT FROM OLD.guardrail_trace
    OR NEW.request_id           IS DISTINCT FROM OLD.request_id THEN
      RAISE EXCEPTION 'idp.approval % is decided; the approved document cannot change', OLD.approval_id;
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status
       AND NOT (OLD.status IN ('APPROVED', 'AUTO_APPROVED') AND NEW.status IN ('REVOKED', 'EXPIRED')) THEN
      RAISE EXCEPTION 'idp.approval % illegal transition % -> %', OLD.approval_id, OLD.status, NEW.status;
    END IF;
  END IF;
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION idp.expected_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.artifact_uri        IS DISTINCT FROM OLD.artifact_uri
  OR NEW.artifact_generation IS DISTINCT FROM OLD.artifact_generation
  OR NEW.artifact_sha256     IS DISTINCT FROM OLD.artifact_sha256
  OR NEW.manifest            IS DISTINCT FROM OLD.manifest
  OR NEW.revision_no         IS DISTINCT FROM OLD.revision_no
  OR NEW.state_unit_id       IS DISTINCT FROM OLD.state_unit_id THEN
    RAISE EXCEPTION 'idp.expected_revision % artifact fields are immutable; render a new revision', OLD.revision_id;
  END IF;
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION idp.gate_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'idp.gate_event is append-only';
  END IF;
  IF (to_jsonb(NEW) - 'published_at') IS DISTINCT FROM (to_jsonb(OLD) - 'published_at') THEN
    RAISE EXCEPTION 'idp.gate_event is append-only (only published_at may be set)';
  END IF;
  RETURN NEW;
END
$$;

CREATE TRIGGER request_guard           BEFORE UPDATE           ON idp.request           FOR EACH ROW EXECUTE FUNCTION idp.request_guard();
CREATE TRIGGER approval_guard          BEFORE UPDATE           ON idp.approval          FOR EACH ROW EXECUTE FUNCTION idp.approval_guard();
CREATE TRIGGER expected_revision_guard BEFORE UPDATE           ON idp.expected_revision FOR EACH ROW EXECUTE FUNCTION idp.expected_revision_guard();
CREATE TRIGGER gate_event_guard        BEFORE UPDATE OR DELETE ON idp.gate_event        FOR EACH ROW EXECUTE FUNCTION idp.gate_event_guard();
CREATE TRIGGER state_unit_touch        BEFORE UPDATE           ON idp.state_unit        FOR EACH ROW EXECUTE FUNCTION idp.touch_updated_at();
CREATE TRIGGER resource_touch          BEFORE UPDATE           ON idp.resource          FOR EACH ROW EXECUTE FUNCTION idp.touch_updated_at();
CREATE TRIGGER lifecycle_task_touch    BEFORE UPDATE           ON idp.lifecycle_task    FOR EACH ROW EXECUTE FUNCTION idp.touch_updated_at();

-- ===== Read model: one row per resource across all four gates =====
CREATE OR REPLACE VIEW idp.v_resource_status AS
SELECT r.resource_id, r.resource_key, r.kind, r.name, r.apm_id,
       su.scope_id AS project_id, su.lob, r.lifecycle, r.gate, r.sync_status,
       rq.request_id, rq.action, rq.status AS request_status, rq.submitted_at,
       ap.approval_id, ap.status AS approval_status, ap.decided_at,
       er.revision_no AS expected_revision_no, er.status AS expected_revision_status,
       ro.exists_in_cloud, ro.changed_at AS observed_changed_at,
       (SELECT count(*) FROM idp.drift_finding d
         WHERE d.resource_id = r.resource_id
           AND d.status IN ('OPEN', 'ACKNOWLEDGED')) AS open_drift_count
FROM idp.resource r
JOIN idp.state_unit su ON su.state_unit_id = r.state_unit_id
LEFT JOIN idp.request rq ON rq.request_id = r.current_request_id
-- [Unverified (source gap): [line 602 NOT CAPTURED; inferred LEFT JOIN idp.approval ap ON ap.approval_id = r.current_approval_id]]
LEFT JOIN idp.approval ap ON ap.approval_id = r.current_approval_id
LEFT JOIN LATERAL (
  SELECT e.revision_no, e.status
  -- [Unverified (source gap): [line 605 NOT CAPTURED; inferred FROM idp.expected_revision_member m]]
  FROM idp.expected_revision_member m
  JOIN idp.expected_revision e ON e.revision_id = m.revision_id
  WHERE m.resource_id = r.resource_id
  ORDER BY e.revision_no DESC
  LIMIT 1
) er ON true
LEFT JOIN idp.resource_observed ro ON ro.resource_id = r.resource_id;

-- ===== Seed: approval gates, apm_alias fixture, and the three kinds =====
-- (module refs and values are placeholders until the per-kind ADRs set them)
INSERT INTO idp.approval_gate_config (gate_key, version, config, updated_by) VALUES
('gcs_bucket_owner', 1, $cfg${
  "order": "sequential",
  "self_approval": "deny",
  "require_human_approval_on_delete": true,
  "approvers": [
    {"key": "bucket_owner", "ticket_field": "/metadata/owner", "mandatory": true,
     "sla_days": 5, "max_follow_ups": 4, "follow_up_interval_days": 1,
     "escalation": {"type": "manager", "manager_sla_days": 2, "max_follow_ups": 1}}
  ],
  "max_wait_days": 13,
  "auto_close": {"enabled": true, "warning_lead_days": 2, "final_reminder_after_days": 1},
  "email_attribute_list": ["/spec/name", "/metadata/project_id", "/metadata/owner"]
}$cfg$::jsonb, 'platform-team'),
('spanner_data_owner', 1, $cfg${
  "order": "sequential",
  "self_approval": "deny",
  "require_human_approval_on_delete": true,
  "approvers": [
    {"key": "data_owner", "ticket_field": "/metadata/owner", "mandatory": true,
     "sla_days": 5, "max_follow_ups": 4, "follow_up_interval_days": 1,
     "escalation": {"type": "manager", "manager_sla_days": 2, "max_follow_ups": 1}},
    {"key": "dbaas_reviewer", "role": "dbaas_reviewer", "mandatory": true, "run_after_approver_keys": ["data_owner"],
     "skip_condition": "metadata.environment not in ('prod') and metadata.resolved.app_tier != '1'",
     "sla_days": 3, "max_follow_ups": 2, "follow_up_interval_days": 1}
  ],
  "max_wait_days": 13,
  "auto_close": {"enabled": true, "warning_lead_days": 2, "final_reminder_after_days": 1}
}$cfg$::jsonb, 'platform-team')
ON CONFLICT (gate_key) DO NOTHING;
-- Override note: sandbox/dev/qa/test/pdev/pqa/preprod all map to 'nonprod' everywhere, including skip_condition above.

INSERT INTO idp.apm_alias (apm_id, alias, app_tier) VALUES
('apm12345', 'orders', '2')
ON CONFLICT (apm_id) DO NOTHING;

INSERT INTO idp.resource_kind
  (kind, cloud, parent_kind, display_name, schema_uri, schema_version, tf_module_source,
   tfvars_collection, tf_address_template, opa_package, approval_gate_key, drift_ignore_paths, legacy_resource_type)
VALUES
-- [Unverified (source gap): [lines 649-652 NOT CAPTURED in SQL: gcs_bucket row; visible SQL tail was ARRAY['/force_destroy'], 'storage-bucket'), while examples/gcs_bucket.gates.json confirms tfvars_collection = 'gcs_buckets' and tf_address_template = 'module.gcs_bucket["{name}"]'; display_name, schema_uri, tf_module_source, and opa_package are inferred]]
('gcs_bucket', 'gcp', NULL, 'Cloud Storage bucket', 'schemas/gcs_bucket.schema.json', '1.0.0',
 'git::https://github.com/vaishnavi4068/ssp-module-gcs-bucket.git//modules/bucket?ref=v1.0.0',
 'gcs_buckets', 'module.gcs_bucket["{name}"]', 'idp.gcp.gcs_bucket', 'gcs_bucket_owner',
 ARRAY['/force_destroy'], 'storage-bucket'),
('spanner_instance', 'gcp', NULL, 'Spanner instance', 'schemas/spanner.schema.json', '1.0.0',
 'git::https://github.com/vaishnavi4068/ssp-module-spanner.git//modules/instance?ref=v1.0.0',
 'spanner_instances', 'module.spanner_instance["{name}"]', 'idp.gcp.spanner_instance', 'spanner_data_owner',
 ARRAY['/force_destroy'], 'spanner-instance'),
('spanner_database', 'gcp', 'spanner_instance', 'Spanner database', 'schemas/spanner.schema.json', '1.0.0',
 'git::https://github.com/vaishnavi4068/ssp-module-spanner.git//modules/database?ref=v1.0.0',
 'spanner_databases', 'module.spanner_database["{instance}/{name}"]', 'idp.gcp.spanner_database', 'spanner_data_owner',
 ARRAY['/ddl', '/deletion_protection'], 'spanner-instance (databases[])')
ON CONFLICT (kind) DO NOTHING;

COMMIT;
