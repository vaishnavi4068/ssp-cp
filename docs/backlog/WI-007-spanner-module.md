---
id: WI-007
title: Spanner module (ssp-module-spanner) — spanner_instance and spanner_database reusing the four-gate pipeline
repo: ssp-module-spanner
target_repos:
  - ssp-module-spanner
  - ssp-cp
  - ssp-workers
status: ready
adr_refs:
  - ADR-SVC-002
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
  - ADR-BP-001
  - ADR-BP-002
  - ADR-BP-003
  - ADR-CLD-GCP-001
  - ADR-AUT-001
  - ADR-AUT-002
  - ADR-AUT-003
spec_refs:
  - specs/examples/spanner.gates.json
  - specs/naming/naming-spec.json
  - specs/data-model/spp_state_model.sql
depends_on:
  - WI-001
  - WI-002
  - WI-003
  - WI-004
  - WI-005
blockers:
  - BLK-001 (GitHub App spp-factory credentials for live factory PR push)
  - BLK-002 (KMS key URI in us-east1: TODO from user)
  - BLK-003 (Runner GCP service account email in <spp-factory-host-project-id>: TODO)
factory_stations:
  - impact (requirements-impact)
  - plan (change-plan)
  - build (iac-module, policy-and-compliance, control-plane)
  - gate (validation)
  - review (change-review)
  - approval (human gate: Manoj, Dwayne, Norm)
  - merge (control-plane)
  - reconcile (drift-and-reconciliation, standards-feedback)
---

# WI-007: Cloud Spanner Module (`ssp-module-spanner`) Reusing the Pipeline

## Goal

Implement the **`ssp-module-spanner`** repository (`modules/instance` for `spanner_instance` and `modules/database` for `spanner_database`) and its OPA/Rego policy packages (`idp.gcp.spanner_instance`, `idp.gcp.spanner_database`), reusing the four-gate control plane (`ssp-cp`), Temporal reconciler + K8s Job runner (`ssp-workers`), internal OPA + Conftest policy pipeline (`WI-003`), and alert-only drift job (`WI-005`) without adding any new database tables or changing core reconciler logic.

## Target Repositories

- **[`github.com/vaishnavi4068/ssp-module-spanner`](https://github.com/vaishnavi4068/ssp-module-spanner)** (`modules/instance`, `modules/database`, `policies/`, `schemas/spanner.schema.json`, `examples/`, `tests/`).
- **`github.com/vaishnavi4068/ssp-cp` & `github.com/vaishnavi4068/ssp-workers`** (verifying multi-resource submission splitting `/resources/0` + `/resources/1`, parent-child `parent_resource_id` resolution, `spanner_data_owner` gate, and `PRQ-003`/`PRQ-004` lifecycle tasks).

## Inputs (`ssp-doc` `main`)

### Governing ADRs
- **[`ADR-SVC-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/endpoint-service/ADR-SVC-002-spanner-instance-and-database.md):** Cloud Spanner Instance (`spanner_instance`) and Database (`spanner_database`) Specification —
  - Two distinct kinds (`spanner_instance` root kind; `spanner_database` with `parent_kind = "spanner_instance"`).
  - **Single-region `us-east1` override (`SPN-CFG-001`):** `config = "regional-us-east1"` in **all** environments (`nonprod` and `prod`) and tiers (`Tier 1..4`) (no `nam3` multi-region, no `regional-us-east4`).
  - **Tier & environment guardrails:** `SPN-EDT-001/002` (`STANDARD` for non-autoscaled Tier 2–4 `nonprod`, `ENTERPRISE` if autoscaled, `ENTERPRISE_PLUS` for Tier 1 or `prod`), `SPN-BKP-001` (instance `default_backup_schedule_type = "AUTOMATIC"`), `SPN-BKP-002` (database `backup_schedule = null` for Tier 2–4 `nonprod`, explicit daily backup schedule for Tier 1 / `prod`), `SPN-DEL-001` (instance `force_destroy = false`), `SPN-DEL-002` (database `deletion_protection = true` and `enable_drop_protection = true`), `SPN-ENC-001` (database CMEK `kms_key_names` in `locations/us-east1`), `SPN-IAM-001` (deny `roles/spanner.databaseReader` at the instance level when `metadata.tenancy == "shared"`), `PRQ-003` (`enable_service:spanner.googleapis.com`), `PRQ-004` (`vpc_sc_project_membership`).
  - **Five Spanner quirks:** 1) No GCP labels on `spanner_database` (labels only on `spanner_instance`), 2) `/deletion_protection` in `drift_ignore_paths`, 3) `/ddl` in `drift_ignore_paths` (owned by app migration pipeline post-create), 4) `/processing_units` ignored in drift only when `autoscaling_config != null` (flagged as `medium` drift when provisioned capacity is changed out-of-band), 5) `SPN-IAM-001` shared-tenancy instance IAM restriction (`REQ-1..5`, `GR-1..4`).
- **[`ADR-GLB-006`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-006-naming-and-labeling-conventions.md) & [`ADR-GLB-008`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-008-label-and-tag-standard.md):** `SPN-NAME-001` (`{lob}-{env}-{app}[-{purpose}]`, max 64 chars), `SPN-NAME-002` (`{app}[_{purpose}]` snake_case, max 30 chars), `SPN-NAME-003` (`{LOB} {App}[ {Purpose}] ({env})` display name shortening to `4..30` chars recorded in `guardrail_trace`), and 8 mandatory labels on `spanner_instance` (with `environmentsubtype` dropped and `spanner_database` exempt from GCP labels).
- **[`ADR-GLB-009`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-009-resource-kind-registry.md):** `idp.resource_kind` seed rows for `spanner_instance` (`tfvars_collection = "spanner_instances"`, `tf_address_template = 'module.spanner_instance["{name}"]'`, `drift_ignore_paths = ARRAY['/force_destroy']`) and `spanner_database` (`parent_kind = 'spanner_instance'`, `tfvars_collection = "spanner_databases"`, `tf_address_template = 'module.spanner_database["{instance}/{name}"]'`, `drift_ignore_paths = ARRAY['/ddl', '/deletion_protection']`).
- **[`ADR-BP-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-003-roles-and-approver-governance.md):** `spanner_data_owner` v1 gate (`data_owner` phase 0 -> `dbaas_reviewer` phase 1 with `skip_condition = "metadata.environment not in ('prod') and metadata.resolved.app_tier != '1'"`; `sandbox`/`dev`/`qa`/`test`/`pdev`/`pqa`/`preprod` all mapped to `nonprod`; human approval mandatory for all deletes).
- **[`ADR-GLB-001..005`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-001-global-architecture-overview.md), [`ADR-GLB-007`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-007-governance-gates-and-policy-rego.md), [`ADR-BP-001..002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-002-build-order-and-phasing.md), [`ADR-CLD-GCP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/per-cloud/gcp/ADR-CLD-GCP-001-runtime-platform-gke-and-temporal.md), [`ADR-AUT-001..003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-001-terraform-execution-k8s-job.md).**

### Governing Specifications (`ssp-doc/specs/`)
- **[`specs/examples/spanner.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/spanner.gates.json):** End-to-end Spanner instance + database walkthrough across `submission` (`/resources/0`, `/resources/1`), `requested`, `approved` (`guardrail_trace`), `expected` (`spanner_instances["<lob>-nonprod-orders"]` and `spanner_databases["<lob>-nonprod-orders/orders"]` in `rev-000002`), `observed`, and `drift_example` (`processing_units` `100 -> 300`).
- **[`specs/naming/naming-spec.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/naming/naming-spec.json):** `spanner_instance`, `spanner_display_name`, and `spanner_database` rules and test vectors.
- **[`specs/data-model/spp_state_model.sql`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/data-model/spp_state_model.sql):** Seed rows for `spanner_data_owner`, `spanner_instance`, and `spanner_database`.

## Scope & Implementation Requirements

1. **Terraform Modules in `ssp-module-spanner` (`modules/instance/` & `modules/database/`):**
   - **`modules/instance` (`spanner_instances` entry shape from `specs/examples/spanner.gates.json`):**
     - Manage `google_spanner_instance` and authoritative per-role `google_spanner_instance_iam_binding`.
     - Enforce `config == "regional-us-east1"` (`SPN-CFG-001`), `edition` in `{"STANDARD", "ENTERPRISE", "ENTERPRISE_PLUS"}` (`SPN-EDT-001/002`), `processing_units` validation (`100..900` in steps of `100` or multiples of `1000` when `autoscaling_config == null`), `default_backup_schedule_type == "AUTOMATIC"` (`SPN-BKP-001`), `force_destroy == false` (`SPN-DEL-001`), 8 mandatory `labels` (`LBL-001/002`, no `environmentsubtype`), and `iam_bindings` (`group:` and `serviceAccount:` only).
     - Output `cloud_resource_id = "projects/${var.project}/instances/${google_spanner_instance.this.name}"`, `state`, and `observed_projection`.
   - **`modules/database` (`spanner_databases` entry shape from `specs/examples/spanner.gates.json`):**
     - Manage `google_spanner_database`, optional `google_spanner_backup_schedule` (`SPN-BKP-002`), and authoritative per-role `google_spanner_database_iam_binding`.
     - Enforce `database_dialect == "GOOGLE_STANDARD_SQL"`, `encryption_config.kms_key_names` non-empty in `locations/us-east1` (`SPN-ENC-001`; key path `TODO` from user), `deletion_protection == true` and `enable_drop_protection == true` (`SPN-DEL-002`), `ddl` list (with `lifecycle { ignore_changes = [ddl] }` / `drift_ignore_paths = ['/ddl', '/deletion_protection']` per Quirk 2 & 3), and **no `labels` attribute** (Quirk 1).
     - Output `cloud_resource_id = "projects/${var.project}/instances/${var.instance}/databases/${google_spanner_database.this.name}"` and `observed_projection`.
2. **Rego Policy Packages & JSON Schema (`policies/`, `schemas/spanner.schema.json`):**
   - Author `schemas/spanner.schema.json` (closing the `[NOT CAPTURED]` gap noted in `ADR-SVC-002 OQ-3`, including `if/then` edition and tier rules) and Rego packages `idp.gcp.spanner_instance` and `idp.gcp.spanner_database` with unit tests (`*_test.rego`).
   - Enforce `SPN-NAME-001..003`, `SPN-CFG-001`, `SPN-EDT-001/002`, `SPN-BKP-001/002`, `SPN-DEL-001/002`, `SPN-ENC-001`, `SPN-IAM-001` (denying `roles/spanner.databaseReader` on `spanner_instance` when `metadata.tenancy == "shared"`), `LBL-001/002`, and `PRQ-003/004`.
3. **Pipeline Reuse Verification (`ssp-cp` & `ssp-workers`):**
   - Verify that submitting the composite payload in `specs/examples/spanner.gates.json` creates two linked `idp.request` rows (`source_pointer = "/resources/0"` for `spanner_instance` and `"/resources/1"` for `spanner_database` with `parent_resource_id` pointing to the instance), routes through `spanner_data_owner` (skipping `dbaas_reviewer` for Tier 2 `nonprod` and requiring `dbaas_reviewer` for Tier 1 or `prod`), composes `rev-000002` in `gs://<spp-factory-host-project-id>-spp-tfstate/projects/<project_id>/expected/rev-000002/terraform.tfvars.json` alongside existing `gcs_buckets` (`expected_revision_member.change = 'unchanged'` for the bucket and `'added'` for the Spanner instance and database), and executes `tf-plan-<20hex>` and `tf-apply-<20hex>` in `spp-platform` with zero schema or reconciler code changes.

## Acceptance Criteria

1. `./gates/scripts/run_gate.sh` from `spp-factory-foundation` passes all 7 stages on `ssp-module-spanner` (`yamllint`, `lint_adrs.py`, `validate_schema.py`, `opa test`, `conftest test`, `terraform fmt/validate/test` with `mock_provider "google"`, and `tfsec`).
2. `opa test -v` and `.tftest.hcl` verify:
   - `config` is always `"regional-us-east1"` (rejecting `nam3` and `regional-us-east4`).
   - `SPN-NAME-002` rejects hyphenated database names (`orders-history`) and accepts snake_case (`orders`, `orders_history`).
   - `SPN-NAME-003` shortens display names exceeding 30 characters (`"SPP Ledgerengine (prod)"`) and records the change in `guardrail_trace`.
   - `SPN-IAM-001` rejects `roles/spanner.databaseReader` on `spanner_instance` when `tenancy == "shared"` and allows it when `tenancy == "dedicated"`.
   - `spanner_database` emits no `labels` key in `terraform.tfvars.json` (Quirk 1) and ignores `/ddl` and `/deletion_protection` in drift scans (Quirks 2 & 3).
   - `spanner_data_owner` skips `dbaas_reviewer` for Tier 2–4 `nonprod` (including inputs normalized from `pdev`/`pqa`/`preprod`) and requires `dbaas_reviewer` after `data_owner` for Tier 1 or `prod`.
3. Composing `rev-000002` on a project that already has `gcs_bucket` from `rev-000001` preserves the bucket as `change = 'unchanged'` in `idp.expected_revision_member` and performs zero writes to the bucket's `idp.resource_observed` row on re-observation (`specs/examples/gcs_bucket.gates.json`).

## Dependencies & Blockers

- **Depends On:** `WI-001` (`ssp-cp`), `WI-002` (`ssp-workers`), `WI-003` (OPA/Conftest policy gates), `WI-004` (`ssp-module-gcs-bucket`), `WI-005` (Drift job).
- **External Blockers (`TODO`):**
  - **`BLK-001`:** GitHub App `spp-factory` credentials (`GITHUB_APP_ID`: `TODO`, `GITHUB_APP_INSTALLATION_ID`: `TODO`, key in Secret Manager `spp-factory-github-app-key` in `<spp-factory-host-project-id>`: `TODO`).
  - **`BLK-002`:** Cloud KMS CMEK key URI in `us-east1` (`projects/<spp-factory-host-project-id>/locations/us-east1/keyRings/<TODO>/cryptoKeys/<TODO>`) from user.
  - **`BLK-003`:** Runner GCP Service Account email (`<TODO-runner-sa>@<spp-factory-host-project-id>.iam.gserviceaccount.com`) from user.

## Factory Stations & Role Skills (`spp-factory-foundation`)

| Station | Role Skill (`agents/skills/<role>/SKILL.md`) | Station Deliverable for `WI-007` |
| :--- | :--- | :--- |
| **1. `impact`** | `requirements-impact` | Maps `ADR-SVC-002`, `ADR-GLB-006..009`, `ADR-BP-003`, and `specs/examples/spanner.gates.json` to `ssp-module-spanner`. |
| **2. `plan`** | `change-plan` | Maps `SPN-*`, `PRQ-003/004`, and the 5 Spanner quirks to `.tftest.hcl`, `opa test`, and reconciler integration tests. |
| **3. `build`** | `iac-module`, `policy-and-compliance`, `control-plane` | Implements `modules/instance`, `modules/database`, `schemas/spanner.schema.json`, `policies/spanner_*.rego`, and `examples/`. |
| **4. `gate`** | `validation` | Runs 7-stage `gates/scripts/run_gate.sh` (max 3 rework retries before `BLOCKED`). |
| **5. `review`** | `change-review` | Confirms `regional-us-east1` only, 5 Spanner quirks handled, human delete approval enforced, and `TODO` KMS key placeholder. |
| **6. `approval`** | Human Gate | Architect (`Manoj`), Approvers (`Dwayne`, `Norm`), and DBA/Ops (`Karen`) review and approve PR. |
| **7. `merge`** | `control-plane` | Merges PR to `ssp-module-spanner` `main` and tags `v1.0.0`. |
| **8. `reconcile`** | `drift-and-reconciliation`, `standards-feedback` | Verifies `rev-000002` multi-kind composition and `processing_units` drift scenario. |
