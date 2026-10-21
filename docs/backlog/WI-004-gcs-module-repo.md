---
id: WI-004
title: GCS module repo (ssp-module-gcs-bucket) — us-east1, CMEK, optional lifecycle_rules, retention_locked=false, force_destroy=false
repo: ssp-module-gcs-bucket
status: ready
adr_refs:
  - ADR-SVC-001
  - ADR-GLB-001
  - ADR-GLB-002
  - ADR-GLB-003
  - ADR-GLB-004
  - ADR-GLB-005
  - ADR-GLB-006
  - ADR-GLB-007
  - ADR-GLB-008
  - ADR-GLB-009
  - ADR-BP-002
  - ADR-BP-003
  - ADR-CLD-GCP-001
  - ADR-AUT-001
  - ADR-AUT-002
  - ADR-AUT-003
spec_refs:
  - specs/examples/gcs_bucket.gates.json
  - specs/naming/naming-spec.json
  - specs/data-model/spp_state_model.sql
depends_on:
  - WI-001
  - WI-002
  - WI-003
blockers:
  - BLK-001 (GitHub App spp-factory credentials + creation of repo ssp-module-gcs-bucket)
  - BLK-002 (KMS key URI in us-east1: TODO from user)
  - BLK-003 (Runner GCP service account email in microdrive-dev: TODO)
factory_stations:
  - impact (requirements-impact)
  - plan (change-plan)
  - build (iac-module, policy-and-compliance)
  - gate (validation)
  - review (change-review)
  - approval (human gate: Manoj, Dwayne, Norm)
  - merge (control-plane)
  - reconcile (drift-and-reconciliation, standards-feedback)
---

# WI-004: GCS Bucket Module Repository (`ssp-module-gcs-bucket`)

## Goal

Create and implement the **`ssp-module-gcs-bucket`** repository (scaffolded from `spp-factory-foundation/templates/resource-repo/`) for SPP's first vertical slice (`kind = "gcs_bucket"`, `tfvars_collection = "gcs_buckets"`, `tf_address_template = 'module.gcs_bucket["{name}"]'`), enforcing **`us-east1` only**, **CMEK encryption** (`kms_key_name` path marked `TODO` from user), **`lifecycle_rules` defaulting to `[]`** (optional user-configurable), **`retention_locked = false` by default** (`GCS-RET-003`), and **`force_destroy = false`** (`GCS-DEL-001`: never force-delete non-empty buckets).

## Target Repository

- **`github.com/vaishnavi4068/ssp-module-gcs-bucket`** *(to be created; referenced in `idp.resource_kind` seed row as `git::https://github.com/vaishnavi4068/ssp-module-gcs-bucket.git//modules/bucket?ref=v1.0.0`)*.

## Inputs (`ssp-doc` `main`)

### Governing ADRs
- **[`ADR-SVC-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/endpoint-service/ADR-SVC-001-first-vertical-slice-gcs-bucket.md):** First Vertical Slice — GCS Bucket (`gcs_bucket`) End-to-End and Guardrails — Complete four-gate contract, `GCS-UBLA-001` (`uniform_bucket_level_access = true`), `GCS-PAP-001` (`public_access_prevention = "enforced"`), `GCS-ENC-001/002` (CMEK key in `locations/us-east1`), `GCS-RET-001` (`retention_days = 90` -> `retention_period = 7776000` seconds when `versioning == false`), `GCS-RET-003` (`retention_locked = false` -> `is_locked = false`), `GCS-SDP-001` (`soft_delete_retention_days = 7` -> `retention_duration_seconds = 604800` seconds), `GCS-DEL-001` (`force_destroy = false`), `autoclass = false`, optional user-configurable `lifecycle_rules` (default `[]`), authoritative per-role `iam_bindings` (`google_storage_bucket_iam_binding`), and `cloud_resource_id = "projects/_/buckets/<name>"` (`REQ-1..6`, `GR-1..4`).
- **[`ADR-GLB-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-001-global-architecture-overview.md) & [`ADR-GLB-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-002-languages-and-technology-stack.md):** Terraform `>= 1.10.0`, `hashicorp/google` provider, offline `terraform test` with `mock_provider "google"`, `tfsec` (`ADR-GLB-002 REQ-4`).
- **[`ADR-GLB-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-003-four-state-model.md) & [`ADR-GLB-004`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-004-data-model-and-database.md):** Composed project-level `terraform.tfvars.json` (`gcs_buckets` map) in `gs://microdrive-dev-spp-tfstate/projects/<project_id>/expected/rev-NNNNNN/`.
- **[`ADR-GLB-005`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-005-identity-and-authentication.md):** Ambient provider credentials via per-project SA impersonation; zero hardcoded credentials or keys.
- **[`ADR-GLB-006`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-006-naming-and-labeling-conventions.md) & [`ADR-GLB-008`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-008-label-and-tag-standard.md):** Bucket naming `{lob}-{env}-{app}-{purpose}-{suffix}` (`GCS-NAME-001..003`, `env` in `nonprod`|`prod`) and **8 mandatory labels** (`sppappid`, `costcenter`, `environmenttype`, `primarylob`, `datasensitivity`, `owner`, `provisionedby`, `idp_resource_id`; no `environmentsubtype`).
- **[`ADR-GLB-007`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-007-governance-gates-and-policy-rego.md) & [`ADR-GLB-009`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-009-resource-kind-registry.md):** `idp.resource_kind` entry for `gcs_bucket` (`drift_ignore_paths = ARRAY['/force_destroy']`, `approval_gate_key = 'gcs_bucket_owner'`).
- **[`ADR-BP-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-002-build-order-and-phasing.md), [`ADR-BP-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-003-roles-and-approver-governance.md), [`ADR-CLD-GCP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/per-cloud/gcp/ADR-CLD-GCP-001-runtime-platform-gke-and-temporal.md), [`ADR-AUT-001..003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-001-terraform-execution-k8s-job.md):** Phase 3 headless GCS E2E slice, `gcs_bucket_owner` approval gate, and 7-stage factory gate verification.

### Governing Specifications (`ssp-doc/specs/`)
- **[`specs/examples/gcs_bucket.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/gcs_bucket.gates.json):** Canonical `requested.document`, `approved.document`, `expected.entry` (`gcs_buckets["<lob>-nonprod-orders-landing-a1b2"]`), and `observed.projection`.
- **[`specs/naming/naming-spec.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/naming/naming-spec.json):** `gcs_bucket` naming rules and 8 mandatory labels.
- **[`specs/data-model/spp_state_model.sql`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/data-model/spp_state_model.sql):** `idp.resource_kind` seed row for `gcs_bucket`.

## Scope & Implementation Requirements

1. **Terraform Module (`modules/bucket/{versions.tf,variables.tf,main.tf,outputs.tf}`):**
   - Require Terraform `>= 1.10.0` and `hashicorp/google` (`>= 6.0`).
   - Accept the exact `expected.entry` object structure from `specs/examples/gcs_bucket.gates.json`:
     - `project` (`string`)
     - `name` (`string`: validated against `^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$`, max 63 chars, no `goog` prefix or `google`/`g00gle` substring)
     - `location` (`string`: variable validation enforcing `var.location == "us-east1"`)
     - `storage_class` (`string`, default `"STANDARD"`, allowed `"STANDARD"`, `"NEARLINE"`, `"COLDLINE"`, `"ARCHIVE"`)
     - `uniform_bucket_level_access` (`bool`, default `true`, variable validation enforcing `true`, `GCS-UBLA-001`)
     - `public_access_prevention` (`string`, default `"enforced"`, variable validation enforcing `"enforced"`, `GCS-PAP-001`)
     - `versioning` (`bool`, default `false`)
     - `autoclass` (`bool`, default `false`)
     - `default_kms_key_name` (`string`, required non-empty CMEK CryptoKey ID in `locations/us-east1`, `GCS-ENC-001`; example fixtures use `projects/microdrive-dev/locations/us-east1/keyRings/<TODO>/cryptoKeys/<TODO>` or `projects/<lob>-kms-nonprod/locations/us-east1/keyRings/<lob>-nonprod-use1/cryptoKeys/gcs-default`)
     - `retention_policy` (`object({ retention_period = number, is_locked = optional(bool, false) })`, where `retention_period >= 7776000` [90 days] when `versioning == false`, and **`is_locked` defaults to `false`** per `GCS-RET-003`)
     - `soft_delete_policy` (`object({ retention_duration_seconds = number })`, default `604800` [7 days], `GCS-SDP-001`)
     - `lifecycle_rules` (`list(object(...))`, **default `[]`** per user override; supports optional user-configured `Delete` and `SetStorageClass` rules)
     - `labels` (`map(string)`, variable validation enforcing presence of all **8 mandatory keys**: `sppappid`, `costcenter`, `environmenttype` in `nonprod`|`prod`, `primarylob`, `datasensitivity`, `owner`, `provisionedby`, `idp_resource_id`, and forbidding `environmentsubtype`)
     - `iam_bindings` (`map(list(string))`, rendered as authoritative per-role `google_storage_bucket_iam_binding` resources so out-of-band IAM grants are detected as drift; variable validation allowing only `group:` and `serviceAccount:` members)
     - `force_destroy` (`bool`, default `false`, variable validation enforcing `var.force_destroy == false` so the module **never force-deletes non-empty buckets**, `GCS-DEL-001`).
   - Output `cloud_resource_id` (`"projects/_/buckets/${google_storage_bucket.this.name}"`), `self_link`, `url`, `name`, and `observed_projection` (matching `specs/examples/gcs_bucket.gates.json`).
2. **JSON Schema, Examples & Rego Policies (`policies/`, `examples/`, `tests/`):**
   - Author `schemas/gcs_bucket.schema.json` (closing the `[NOT CAPTURED]` gap noted in `ADR-SVC-001 OQ-4`), `examples/requested.json`, and `examples/approved.json` matching `specs/examples/gcs_bucket.gates.json`.
   - Author `policies/gcs_bucket.rego` and `policies/gcs_bucket_test.rego` (`package idp.gcp.gcs_bucket`) enforcing all `GCS-*` and `LBL-*` rules.
   - Author credential-free `tests/gcs_bucket.tftest.hcl` using `mock_provider "google"` testing:
     1. Default compliant bucket in `us-east1` with `lifecycle_rules = []`, `retention_policy.is_locked = false`, `force_destroy = false`, and CMEK.
     2. Compliant bucket with optional user-configured `lifecycle_rules` (`Delete` at 180 days, `SetStorageClass` to `NEARLINE` at 30 days).
     3. Negative tests (`expect_failures`) for `location = "US"`, `force_destroy = true`, `public_access_prevention = "inherited"`, missing mandatory labels, or presence of `environmentsubtype`.

## Acceptance Criteria

1. `./gates/scripts/run_gate.sh` from `spp-factory-foundation` passes all 7 stages on `ssp-module-gcs-bucket`:
   - Stage 1: YAML workflow lint passes.
   - Stage 2: Local `ADR.md` / `ADR-SVC-001` lint passes.
   - Stage 3: `examples/requested.json` and `examples/approved.json` pass JSON Schema validation with zero secrets.
   - Stage 4: `opa test` passes 100% of Rego unit tests.
   - Stage 5: `conftest test` passes on `examples/requested.json` and `examples/approved.json`.
   - Stage 6: `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`, and `terraform test` (`mock_provider "google"`) pass with zero cloud credentials.
   - Stage 7: `tfsec` reports 0 critical/high/medium security findings.
2. Variable validations and Rego policies reject `location != "us-east1"`, `force_destroy == true`, `retention_locked == true` (unless explicitly unlocked by a records-management rule), `environmentsubtype` label, or `user:`/`allUsers`/`allAuthenticatedUsers` IAM members.
3. End-to-end headless API test (with `WI-001..003`) provisions a `gcs_bucket` in `microdrive-dev` (`us-east1`) once blockers `BLK-002` (KMS key URI) and `BLK-003` (runner SA) are supplied, writing `Expected` and `Observed` state to `gs://microdrive-dev-spp-tfstate`.

## Dependencies & Blockers

- **Depends On:** `WI-001` (`ssp-cp`), `WI-002` (`ssp-workers`), `WI-003` (OPA/Conftest policy gates).
- **External Blockers (`TODO`):**
  - **`BLK-001`:** GitHub App `spp-factory` credentials (`GITHUB_APP_ID`: `TODO`, `GITHUB_APP_INSTALLATION_ID`: `TODO`, key in Secret Manager `spp-factory-github-app-key`: `TODO`) and creation of repository `github.com/vaishnavi4068/ssp-module-gcs-bucket`.
  - **`BLK-002`:** Cloud KMS CMEK key URI in `us-east1` (`projects/microdrive-dev/locations/us-east1/keyRings/<TODO>/cryptoKeys/<TODO>`) from user.
  - **`BLK-003`:** Runner GCP Service Account email (`<TODO-runner-sa>@microdrive-dev.iam.gserviceaccount.com`) from user.

## Factory Stations & Role Skills (`spp-factory-foundation`)

| Station | Role Skill (`agents/skills/<role>/SKILL.md`) | Station Deliverable for `WI-004` |
| :--- | :--- | :--- |
| **1. `impact`** | `requirements-impact` | Maps `ADR-SVC-001`, `ADR-GLB-006..009`, and `specs/examples/gcs_bucket.gates.json` to `ssp-module-gcs-bucket`. |
| **2. `plan`** | `change-plan` | Maps `GCS-UBLA-001`, `GCS-PAP-001`, `GCS-ENC-001`, `GCS-RET-001/003`, `GCS-SDP-001`, `GCS-DEL-001`, `LBL-001/002`, and optional `lifecycle_rules` to `.tftest.hcl` and `*_test.rego` cases. |
| **3. `build`** | `iac-module`, `policy-and-compliance` | Scaffolds `ssp-module-gcs-bucket` (`modules/bucket/`, `policies/`, `schemas/gcs_bucket.schema.json`, `examples/`, `tests/`). |
| **4. `gate`** | `validation` | Runs full 7-stage `gates/scripts/run_gate.sh` (max 3 rework retries before `BLOCKED`). |
| **5. `review`** | `change-review` | Verifies `us-east1` only, `lifecycle_rules = []` default, `retention_locked = false` default, `force_destroy = false`, and `TODO` KMS key placeholder. |
| **6. `approval`** | Human Gate | Architect (`Manoj`) and Approvers (`Dwayne`, `Norm`) review and approve PR. |
| **7. `merge`** | `control-plane` | Merges PR and tags release `v1.0.0` matching `idp.resource_kind.tf_module_source`. |
| **8. `reconcile`** | `drift-and-reconciliation`, `standards-feedback` | Verifies `Expected` vs. `Observed` projection parity on `gcs_bucket`. |
