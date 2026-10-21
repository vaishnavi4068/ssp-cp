---
id: WI-001
title: Control plane core (ssp-cp) — FastAPI on GKE md-dev and AlloyDB four-gate schema
repo: ssp-cp
status: ready
adr_refs:
  - ADR-GLB-001
  - ADR-GLB-002
  - ADR-GLB-003
  - ADR-GLB-004
  - ADR-GLB-005
  - ADR-GLB-006
  - ADR-GLB-007
  - ADR-GLB-008
  - ADR-GLB-009
  - ADR-BP-001
  - ADR-BP-002
  - ADR-BP-003
  - ADR-CLD-GCP-001
  - ADR-AUT-001
  - ADR-AUT-002
  - ADR-AUT-003
spec_refs:
  - specs/data-model/spp_state_model.sql
  - specs/naming/naming-spec.json
  - specs/examples/gcs_bucket.gates.json
  - specs/examples/spanner.gates.json
depends_on: []
blockers:
  - BLK-001 (GitHub App spp-factory credentials for live factory PR push)
  - BLK-004 (User cost approval required before provisioning live AlloyDB in microdrive-dev)
factory_stations:
  - impact (requirements-impact)
  - plan (change-plan)
  - build (control-plane, policy-and-compliance)
  - gate (validation)
  - review (change-review)
  - approval (human gate: Manoj, Dwayne, Norm)
  - merge (control-plane)
  - reconcile (drift-and-reconciliation, standards-feedback)
---

# WI-001: Control Plane Core (`ssp-cp`)

## Goal

Build the Python FastAPI control plane API (`ssp-cp`) deployed directly on GKE `md-dev` in namespace `spp-platform` (exposed via GKE Ingress / LoadBalancer with **no Apigee / API Forge**), backed by **AlloyDB for PostgreSQL** (`spp_platform` in `microdrive-dev`, `us-east1`) implementing the 18-table `idp` schema from `specs/data-model/spp_state_model.sql`, persisting `Requested` and `Approved` gates in AlloyDB with zero secrets, enforcing role-based sequential approvals per `ADR-BP-003`, and guaranteeing that nothing is deleted without explicit human approval.

## Target Repository

- **`github.com/vaishnavi4068/ssp-cp`** (Kubernetes namespace `spp-platform` on GKE cluster `md-dev` in project `microdrive-dev`, region `us-east1`, node pool `spp-pool` with `nodeSelector: workload=spp` and toleration `dedicated=spp:NoSchedule`).

## Inputs (`ssp-doc` `main`)

### Governing ADRs
- **[`ADR-GLB-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-001-global-architecture-overview.md):** Global Architecture Overview — GCP-only (`us-east1`) scope, 2.0 project layout, synchronous `Requested` writes to PostgreSQL without invoking Temporal on initial intake write (`REQ-1..3`, `GR-1..4`).
- **[`ADR-GLB-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-002-languages-and-technology-stack.md):** Languages and Technology Stack — Python `3.11+`, `FastAPI`, `Pydantic v2`, `SQLAlchemy 2.x`, `Alembic`, `psycopg` / `google-cloud-alloydb-connector`, `argon2-cffi`, `httpx` (`REQ-1`, `GR-1`).
- **[`ADR-GLB-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-003-four-state-model.md):** Four-Gate Provisioning State Model and Storage Layout — `Requested` and `Approved` in full in AlloyDB (zero secrets, `INV-1`); `Expected` and `Observed` pointers/hashes, `<= 2 KB` (`< 2000` bytes) `idp.resource_observed.projection`, and `idp.drift_finding` rows in AlloyDB; canonical JSON SHA-256 hash chain (`canonical_sha256`, `REQ-1..7`).
- **[`ADR-GLB-004`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-004-data-model-and-database.md):** Data Model and Centralized PostgreSQL Database (AlloyDB for PostgreSQL) — Dedicated AlloyDB cluster/instance (`spp_platform` in `microdrive-dev`, `us-east1`), schema `idp` (18 tables + `idp.v_resource_status` view), SQL function `idp.k8s_job_name(operation_id, phase)`, immutability triggers (`request_guard`, `approval_guard`, `expected_revision_guard`, `gate_event_guard`), secret-rejection `CHECK` constraints (`submission_no_secret_values`, `request_no_secret_values`, `approval_no_secret_values`), and `approval_no_auto_approve_delete` (`REQ-1..7`, `GR-1..4`).
- **[`ADR-GLB-005`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-005-identity-and-authentication.md):** Identity, Workload Identity, and Authentication — GKE Workload Identity (`microdrive-dev.svc.id.goog`, zero static JSON keys), direct GKE deployment (no Apigee/API Forge, `OQ-2`), Argon2id local login now with Secret Manager bootstrap passwords, mandatory first-login password rotation, `__Host-` session cookies, CSRF protection, rate limiting, and 5-attempt lockout (`REQ-1..6`, `GR-1..4`).
- **[`ADR-GLB-006`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-006-naming-and-labeling-conventions.md):** Naming Conventions and Identifier Patterns — Token validation (`lob`, `env` in `nonprod` | `prod` with no hyphen, `app` from `idp.apm_alias`, `purpose`, 4-char random `suffix`), rules `GCS-NAME-001..003`, `SPN-NAME-001..003`, `NAM-RSV-001`, `NAM-IMM-001`, `NAM-LEG-001` (`REQ-1..5`).
- **[`ADR-GLB-007`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-007-governance-gates-and-policy-rego.md):** Governance Gates, Guardrails, Invariants, and Policy (Rego) — Three-stage policy evaluation (`requested`, `approved`, `plan`) persisted in `idp.policy_evaluation`, `guardrail_trace` recording, invariants `INV-1..INV-9`, `us-east1`-only constraint, and mandatory human approval for any delete/destroy/replace in any environment (`REQ-1..6`, `GR-1..5`).
- **[`ADR-GLB-008`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-008-label-and-tag-standard.md):** Label and Tag Standard — 8 mandatory labels (`sppappid`, `costcenter`, `environmenttype`, `primarylob`, `datasensitivity`, `owner`, `provisionedby`, `idp_resource_id`), `environmentsubtype` dropped everywhere, and `LBL-001`/`LBL-002` normalization (`REQ-1..6`).
- **[`ADR-GLB-009`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-009-resource-kind-registry.md):** Resource Kind Registry — `idp.resource_kind` catalog and seed rows (`gcs_bucket`, `spanner_instance`, `spanner_database`) (`REQ-1..4`).
- **[`ADR-BP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-001-ownership-map-and-governance.md):** Ownership Map and Stakeholder Governance — Non-bypassable Operations Gate; ServiceNow/CMDB kept as a non-blocking post-MVP interface placeholder only (`REQ-1..5`).
- **[`ADR-BP-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-002-build-order-and-phasing.md):** Product Build Order and Delivery Phasing — Phase 2 Control-Plane Skeleton preceding Phase 3 headless GCS vertical slice (`REQ-1..4`).
- **[`ADR-BP-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-003-roles-and-approver-governance.md):** Roles, Personas, and Approval Gate Governance — `idp.approval_gate_config` (`gcs_bucket_owner` v1, `spanner_data_owner` v1), sequential approvers (`bucket_owner`, `data_owner`, `dbaas_reviewer` with `skip_condition`), `self_approval = "deny"`, SLA/escalation metadata, 30-day `valid_until`, and mandatory human approval on all deletes (`REQ-1..5`, `GR-1..3`).
- **[`ADR-CLD-GCP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/per-cloud/gcp/ADR-CLD-GCP-001-runtime-platform-gke-and-temporal.md):** Runtime Platform — GKE `md-dev`, tainted `spp-pool` (`workload=spp` / `dedicated=spp:NoSchedule`), namespace `spp-platform`, direct GKE Ingress/LoadBalancer exposure, and Temporal namespace `platform` (`REQ-1..6`).
- **[`ADR-AUT-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-001-terraform-execution-k8s-job.md), [`ADR-AUT-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-002-day-2-operations-scope.md), [`ADR-AUT-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-003-software-factory-adr-flow.md):** Workflow IDs (`req-<request_id>`, `apr-<request_id>`, `su-gcp-<project_id>`), Day-2 `update`/`delete`/`import` request semantics (`base_approval_id`), `state_unit.status = 'frozen'` kill switch (`INV-9`), and factory verification gates.

### Governing Specifications (`ssp-doc/specs/`)
- **[`specs/data-model/spp_state_model.sql`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/data-model/spp_state_model.sql):** Reconstructed PostgreSQL 15+ / AlloyDB DDL for schema `idp` (18 tables: `approval_gate_config`, `resource_kind`, `apm_alias`, `state_unit`, `resource`, `submission`, `request`, `policy_evaluation`, `approval`, `approval_decision`, `expected_revision`, `expected_revision_member`, `tf_operation`, `observation`, `resource_observed`, `drift_finding`, `lifecycle_task`, `gate_event`, plus view `idp.v_resource_status`).
- **[`specs/naming/naming-spec.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/naming/naming-spec.json):** Naming templates, token patterns, reserved words, validation rules (`GCS-NAME-*`, `SPN-NAME-*`, `NAM-*`, `LBL-001/002`), and test vectors.
- **[`specs/examples/gcs_bucket.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/gcs_bucket.gates.json) & [`specs/examples/spanner.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/spanner.gates.json):** Canonical four-gate database row and document fixtures.

## Scope & Implementation Requirements

1. **Alembic Migrations & SQLAlchemy 2.x Store (`specs/data-model/spp_state_model.sql`):**
   - Translate `specs/data-model/spp_state_model.sql` into versioned Alembic migrations targeting AlloyDB database `spp_platform` (schema `idp`).
   - Include all 18 tables, deferred foreign keys (`resource_current_request_fk`, `resource_current_approval_fk`), `idp.k8s_job_name(p_operation_id, p_phase)`, `idp.touch_updated_at()`, immutability triggers (`request_guard`, `approval_guard`, `expected_revision_guard`, `gate_event_guard`), `idp.v_resource_status`, and seed rows (`approval_gate_config` for `gcs_bucket_owner` v1 and `spanner_data_owner` v1, `apm_alias`, and `resource_kind` for `gcs_bucket`, `spanner_instance`, `spanner_database`).
   - Preserve explicit comments for any `[Unverified (source gap)]` columns noted in `ADR-GLB-004 OQ-2`.
2. **Direct FastAPI Service on GKE `md-dev` (No Apigee / API Forge):**
   - Expose health/readiness endpoints (`/healthz`, `/readyz`), local Argon2id authentication (`/api/v1/auth/login`, `/api/v1/auth/change-password`, `/api/v1/auth/logout`, `/api/v1/auth/users/{username}/unlock` per `ADR-GLB-005`), resource kind catalog endpoints (`/api/v1/kinds`), intake submission & request endpoints (`POST /api/v1/submissions`, `GET /api/v1/requests/{request_id}`), approval decision endpoints (`POST /api/v1/approvals/{approval_id}/decisions`), resource status & gate inspection endpoints (`GET /api/v1/resources`, `GET /api/v1/resources/{resource_id}` backed by `idp.v_resource_status`, `idp.resource_observed`, and `idp.drift_finding`), and state unit freeze/unfreeze kill-switch endpoints (`POST /api/v1/state-units/{state_unit_id}/freeze`, `/unfreeze` per `INV-9`).
   - Provide Helm/Kubernetes manifests for namespace `spp-platform` on GKE `md-dev` (`nodeSelector: workload=spp`, toleration `dedicated=spp:NoSchedule`, Workload Identity annotation, direct GKE Ingress / internal LoadBalancer Service).
3. **Gate 1 (`Requested`) Intake & Normalization (`ADR-GLB-003`, `ADR-GLB-006`, `ADR-SVC-001`):**
   - Write `idp.submission` (`UNIQUE (apm_id, idempotency_key)`) and `idp.request` synchronously to AlloyDB without routing the initial write through Temporal (`ADR-GLB-001 REQ-3`).
   - Normalize raw intake values (`"restrict" -> "restricted"`, `"APM0017299" -> "apm0017299"`, `"<LOB>" -> "<lob>"`, `"sandbox"|"dev"|"qa"|"test"|"pdev"|"pqa"|"preprod" -> "nonprod"`).
   - Compute `canonical_sha256` (`sort_keys=True, separators=(",", ":")`) for `raw_payload_sha256` and `requested_spec_sha256`.
   - Enforce naming rules from `specs/naming/naming-spec.json` (`GCS-NAME-001..003` with 4-char random suffix draw up to 5 attempts, `SPN-NAME-001..002`, `NAM-RSV-001`, `NAM-IMM-001`, `NAM-LEG-001`).
   - Reject any secret-bearing keys or values (`INV-1`) and any region other than `us-east1`.
4. **Gate 2 (`Approved`) Enrichment & Role-Based Approvals (`ADR-BP-003`, `ADR-GLB-007`, `ADR-GLB-008`):**
   - Call the internal OPA service (wired with `WI-003`) at `stage = 'requested'` and `stage = 'approved'`, writing rows to `idp.policy_evaluation` and recording every guardrail mutation (`GCS-*`, `SPN-*`, `LBL-001/002`, `PRQ-001..004`) in `idp.approval.guardrail_trace`.
   - Pin `gate_key` and `gate_version` from `idp.approval_gate_config` on `idp.approval` and create per-approver rows in `idp.approval_decision`:
     - `gcs_bucket_owner` v1: sequential `bucket_owner` (`/metadata/owner`, `sla_days = 5`, `max_follow_ups = 4`, manager escalation `manager_sla_days = 2`).
     - `spanner_data_owner` v1: sequential `data_owner` (`/metadata/owner`), then `dbaas_reviewer` (skipped when `metadata.environment not in ('prod') and metadata.resolved.app_tier != '1'`).
   - Enforce `self_approval = "deny"`: reject any approval decision where `responded_by` equals `requested_by`, `submitted_by`, or `on_behalf_of`.
   - Enforce universal human approval for deletes: reject `AUTO_APPROVED` on `idp.approval` and `auto_approved` on `idp.approval_decision` whenever `action == 'delete'` in **any** environment (`nonprod` or `prod`).

## Acceptance Criteria

1. Alembic `upgrade head` and `downgrade base` succeed cleanly against a PostgreSQL 15+ / AlloyDB test instance, creating all 18 tables, view `idp.v_resource_status`, function `idp.k8s_job_name`, triggers, constraints, and seed rows from `specs/data-model/spp_state_model.sql`.
2. Database trigger and constraint unit tests prove:
   - `request_guard` blocks updates to `requested_spec`, `action`, `kind`, or `schema_version` on `idp.request`.
   - `approval_guard` blocks mutations to `approved_spec`, `approved_spec_sha256`, or `guardrail_trace` once `idp.approval.status <> 'PENDING'`.
   - `expected_revision_guard` blocks mutations to `artifact_uri`, `artifact_generation`, `artifact_sha256`, or `manifest` on `idp.expected_revision`.
   - `gate_event_guard` blocks `DELETE` and any `UPDATE` other than setting `published_at` on `idp.gate_event`.
   - `submission_no_secret_values`, `request_no_secret_values`, and `approval_no_secret_values` reject payloads containing secret keys (`password`, `private_key`, `client_secret`, `api_key`, `token`, `secret_value`).
   - `approval_no_auto_approve_delete` rejects `status = 'AUTO_APPROVED'` when `approved_spec->>'action' = 'delete'`.
3. Naming & label unit tests pass all 13 naming test vectors, 3 display-name shortening vectors, and `LBL-001`/`LBL-002` normalization vectors in `specs/naming/naming-spec.json` (confirming `environmentsubtype` is never emitted and `environmenttype` is `nonprod` | `prod`).
4. API integration tests verify:
   - Synchronous `POST /api/v1/submissions` persists `idp.submission` and `idp.request` (`gate = 'REQUESTED'`) with idempotency deduplication on `(apm_id, idempotency_key)`.
   - Self-approval (`responded_by == requested_by`) returns `403 Forbidden` (`ADR-BP-003`).
   - Delete requests (`action = 'delete'`) in both `nonprod` and `prod` require explicit human approval and cannot be auto-approved (`ADR-BP-003`, `ADR-GLB-007`).
   - Local Argon2id login enforces `must_change_password = true` on initial Secret Manager bootstrap login, CSRF validation, and 5-attempt lockout (`ADR-GLB-005`).
5. Kubernetes/Helm manifests for `ssp-cp` target namespace `spp-platform` on `md-dev` with `nodeSelector: workload=spp`, toleration `dedicated=spp:NoSchedule`, and direct GKE Ingress/Service (no Apigee/API Forge).

## Dependencies & Blockers

- **Upstream Specs:** `ssp-doc` `main` (ready).
- **External Blockers (`TODO`):**
  - **`BLK-001`:** GitHub App `spp-factory` credentials (`GITHUB_APP_ID`: `TODO`, `GITHUB_APP_INSTALLATION_ID`: `TODO`, private key in Secret Manager `spp-factory-github-app-key` in `microdrive-dev`: `TODO`) required for live factory branch push/PR creation.
  - **`BLK-004`:** Explicit **user cost approval (`TODO`)** required before creating the live AlloyDB for PostgreSQL cluster/instance in `microdrive-dev` (`us-east1`), plus CMEK key URI (`BLK-002`: `TODO`) if CMEK-encrypted AlloyDB is enabled at creation. (All local/CI tests run against ephemeral PostgreSQL 15+ containers without creating cloud infrastructure.)

## Factory Stations & Role Skills (`spp-factory-foundation`)

| Station | Role Skill (`agents/skills/<role>/SKILL.md`) | Station Deliverable for `WI-001` |
| :--- | :--- | :--- |
| **1. `impact`** | `requirements-impact` | Impact report mapping `ADR-GLB-001..009`, `ADR-BP-001..003`, and `specs/data-model/spp_state_model.sql` to `ssp-cp` packages and migrations. |
| **2. `plan`** | `change-plan` | File-by-file Execution Change Plan mapping every `REQ-*`, `GR-*`, and `SC-*` to `pytest` and SQL constraint tests. |
| **3. `build`** | `control-plane`, `policy-and-compliance` | FastAPI app, SQLAlchemy/Alembic `idp` schema migrations, naming/label validator, approval gate engine, and K8s manifests. |
| **4. `gate`** | `validation` | Runs `pytest`, `ruff`/`mypy`, schema validation, and `gates/scripts/run_gate.sh` (max 3 rework retries before `BLOCKED`). |
| **5. `review`** | `change-review` | Audits diff for zero secrets, no company names (`SPP` only), no Apigee, `us-east1` only, and `ADR-*` traceability. |
| **6. `approval`** | Human Gate | Architect (`Manoj`) and Approvers (`Dwayne`, `Norm`) review and approve PR. |
| **7. `merge`** | `control-plane` | Merges PR to `ssp-cp` `main`. |
| **8. `reconcile`** | `drift-and-reconciliation`, `standards-feedback` | Records run metrics and feeds any DDL/schema lessons back into `ssp-doc`. |
