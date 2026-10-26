---
id: WI-005
title: Drift job — independent refresh scan into Observed, JSON-pointer comparison against Expected, alert-only summaries in AlloyDB
repo: ssp-workers
target_repos:
  - ssp-workers
  - ssp-cp
status: ready
adr_refs:
  - ADR-AUT-002
  - ADR-AUT-001
  - ADR-AUT-003
  - ADR-GLB-001
  - ADR-GLB-003
  - ADR-GLB-004
  - ADR-GLB-005
  - ADR-GLB-006
  - ADR-GLB-007
  - ADR-GLB-008
  - ADR-GLB-009
  - ADR-BP-002
  - ADR-BP-003
  - ADR-SVC-001
  - ADR-SVC-002
  - ADR-CLD-GCP-001
spec_refs:
  - specs/data-model/spp_state_model.sql
  - specs/examples/gcs_bucket.gates.json
  - specs/examples/spanner.gates.json
  - specs/naming/naming-spec.json
depends_on:
  - WI-001
  - WI-002
  - WI-004
blockers:
  - BLK-001 (GitHub App spp-factory credentials for live factory PR push)
  - BLK-003 (Runner GCP service account email in <spp-factory-host-project-id>: TODO)
factory_stations:
  - impact (requirements-impact)
  - plan (change-plan)
  - build (drift-and-reconciliation, control-plane)
  - gate (validation)
  - review (change-review)
  - approval (human gate: Manoj, Dwayne, Norm)
  - merge (control-plane)
  - reconcile (drift-and-reconciliation, standards-feedback)
---

# WI-005: Independent Drift Detection Job (`ssp-workers` & `ssp-cp`)

## Goal

Implement the independent scheduled and on-demand drift detection job (`DriftSchedule` `drift-<project_id>` triggering `tf-refresh-plan-<20hex>` in namespace `spp-platform`) that reads real GCP resources into `Observed` (`gs://<spp-factory-host-project-id>-spp-tfstate/projects/<project_id>/observed/scan-<window>/plan.json`), compares `Observed` against `Expected` via JSON-pointer diff (minus `idp.resource_kind.drift_ignore_paths`), operates strictly in **alert-only mode (no auto-remediation / no auto-reapply)**, and writes short (`<= 2 KB`) projections (`idp.resource_observed`) and structured drift summaries (`idp.drift_finding`) into AlloyDB for PostgreSQL.

## Target Repositories

- **`github.com/vaishnavi4068/ssp-workers`** (`DriftSchedule` `drift-<project_id>`, `refresh_plan` Kubernetes Job execution `tf-refresh-plan-<20hex>`, JSON-pointer drift comparer, severity classifier, and AlloyDB `idp.observation` / `idp.resource_observed` / `idp.drift_finding` / `idp.gate_event` writer).
- **`github.com/vaishnavi4068/ssp-cp`** (Read-only and operator acknowledgment endpoints for `idp.drift_finding` and `idp.v_resource_status.open_drift_count`).

## Inputs (`ssp-doc` `main`)

### Governing ADRs
- **[`ADR-AUT-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-002-day-2-operations-scope.md):** Day-2 Operations, Drift Detection, and Deletion Governance — Temporal Schedule `drift-<project_id>`, `phase = 'refresh_plan'` with schedule window `run_key` (e.g., `2026-10-23T06`), JSON-pointer comparison minus `idp.resource_kind.drift_ignore_paths`, whole-map comparison for `labels` and `iam_bindings`, drift finding kinds (`out_of_band_change`, `config_divergence`, `missing_in_cloud`, `unmanaged_in_cloud`), **alert-only policy (never auto-reapply)**, and `status` (`OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `ACCEPTED`) / `resolution` (`spec_updated`, `accepted_risk`, `resource_deleted`) vocabularies (`REQ-4..5`, `GR-2`, `GR-4`).
- **[`ADR-AUT-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-001-terraform-execution-k8s-job.md):** Deterministic Kubernetes Job naming (`tf-refresh-plan-<20hex>`) in `spp-platform` and `su-gcp-<project_id>` serialization (`INV-7`, `INV-8`).
- **[`ADR-GLB-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-003-four-state-model.md) & [`ADR-GLB-004`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-004-data-model-and-database.md):** Storage split: full `observed/scan-<window>/plan.json` snapshot in `gs://<spp-factory-host-project-id>-spp-tfstate`; narrow `idp.observation` row, `< 2000`-byte `idp.resource_observed.projection` (upserted only when `projection_sha256` changes), and `idp.drift_finding` summary rows in AlloyDB (`REQ-3`, `REQ-6`).
- **[`ADR-GLB-007`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-007-governance-gates-and-policy-rego.md):** Drift severity classification table (`critical`, `high`, `medium`, `low`) and `guardrail_rule_id` linkage (`REQ-6`, `GR-5`).
- **[`ADR-GLB-008`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-008-label-and-tag-standard.md) & [`ADR-GLB-009`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-009-resource-kind-registry.md):** Cloud Asset Inventory correlation via `idp_resource_id` label and per-kind `drift_ignore_paths` (`['/force_destroy']` on `gcs_bucket` and `spanner_instance`; `['/ddl', '/deletion_protection']` on `spanner_database`).
- **[`ADR-SVC-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/endpoint-service/ADR-SVC-001-first-vertical-slice-gcs-bucket.md) & [`ADR-SVC-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/endpoint-service/ADR-SVC-002-spanner-instance-and-database.md):** Concrete drift walkthroughs for `gcs_bucket` (`public_access_prevention` `"enforced" -> "inherited"`, `severity = "critical"`, `guardrail_rule_id = "GCS-PAP-001"`) and `spanner_instance` (`processing_units` `100 -> 300`, `severity = "medium"`).
- **[`ADR-BP-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-002-build-order-and-phasing.md), [`ADR-BP-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-003-roles-and-approver-governance.md), [`ADR-CLD-GCP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/per-cloud/gcp/ADR-CLD-GCP-001-runtime-platform-gke-and-temporal.md), [`ADR-AUT-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-003-software-factory-adr-flow.md).**

### Governing Specifications (`ssp-doc/specs/`)
- **[`specs/data-model/spp_state_model.sql`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/data-model/spp_state_model.sql):** Tables `idp.observation`, `idp.resource_observed` (`CHECK (octet_length(projection::text) < 2000)` `WITH (fillfactor = 80)`), `idp.drift_finding` (`drift_finding_open_uq`), and `idp.v_resource_status`.
- **[`specs/examples/gcs_bucket.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/gcs_bucket.gates.json):** `drift_example` section (`op:af42f828-3378-5ee2-8e9b-2378d2314f97:r2:refresh_plan:2026-10-23T06` -> `tf-refresh-plan-415a15a935cbd63f95e1`).
- **[`specs/examples/spanner.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/spanner.gates.json):** `instance.drift_example` section (`processing_units` `100 -> 300`).

## Scope & Implementation Requirements

1. **Scheduled & On-Demand Refresh-Plan Runner Job (`ADR-AUT-001`, `ADR-AUT-002`):**
   - Register Temporal Schedule `drift-<project_id>` for each active `idp.state_unit` (plus an on-demand API trigger in `ssp-cp`), signaling `StateUnitReconcilerWorkflow` (`su-gcp-<project_id>`) with `drift_scan {window}`.
   - Derive `operation_id = f"op:{state_unit_id}:r{applied_expected_rev}:refresh_plan:{window}"` and `k8s_job_name = idp.k8s_job_name(operation_id, "refresh_plan")` (`tf-refresh-plan-<20hex>`).
   - Run `terraform plan -refresh-only -detailed-exitcode -out=refresh.plan` and `terraform show -json refresh.plan > plan.json` inside the Kubernetes Job in namespace `spp-platform`, uploading `plan.json` to `gs://<spp-factory-host-project-id>-spp-tfstate/projects/<project_id>/observed/scan-<window>/plan.json` without advancing `default.tfstate` `state_serial` (`state_serial_before == state_serial_after`).
2. **JSON-Pointer Drift Comparer & Severity Classification (`ADR-AUT-002`, `ADR-GLB-007`, `ADR-GLB-009`):**
   - For each active member in the state unit's current `Expected` revision, extract the refreshed cloud values from `plan.json` (keyed by `cloud_resource_id` / `tf_address`), strip any `sensitive_values`, verify `< 2000` bytes, and compute the `Observed` projection (`idp.resource_observed.projection`) and `projection_sha256`.
   - Upsert `idp.resource_observed` **only when `projection_sha256` is distinct from the stored hash** (`WHERE ro.projection_sha256 IS DISTINCT FROM EXCLUDED.projection_sha256`).
   - Compare every JSON pointer in the `Expected` `tfvars` entry against the `Observed` projection, **excluding**:
     - `idp.resource_kind.drift_ignore_paths` (`['/force_destroy']` for `gcs_bucket` and `spanner_instance`; `['/ddl', '/deletion_protection']` for `spanner_database`), and
     - `/processing_units` on `spanner_instance` when `autoscaling_config` is non-null (`ADR-SVC-002` Quirk 4).
   - Compare `labels` and `iam_bindings` as whole maps so any out-of-band IAM binding or label change is detected.
   - Classify each differing attribute into `idp.drift_finding` (`drift_kind` in `out_of_band_change | config_divergence | missing_in_cloud | unmanaged_in_cloud`) and assign `severity` (`ADR-GLB-007` §4):
     - `critical`: Security guardrails (`public_access_prevention`, `uniform_bucket_level_access`, `default_kms_key_name` / `encryption_config.kms_key_names`, public IAM principal `allUsers`/`allAuthenticatedUsers`, or any attribute with a `guardrail_rule_id` such as `GCS-PAP-001`).
     - `high`: Data protection and retention (`retention_policy`, `soft_delete_policy`, `version_retention_period`, `backup_schedule`).
     - `medium`: Capacity, storage/lifecycle, and non-public IAM (`storage_class`, `lifecycle_rules`, non-autoscaled `processing_units`, `edition`, `iam_bindings`).
     - `low`: Metadata and labels (`labels`, `display_name`).
3. **Alert-Only Enforcement & Short Postgres Summaries (`ADR-GLB-003`, `ADR-GLB-004`, `ADR-AUT-002`):**
   - **Never auto-remediate or auto-run `terraform apply` on drift.**
   - Insert/update `idp.drift_finding` (`status = 'OPEN'`, deduplicated by partial unique index `drift_finding_open_uq` on `(resource_id, attribute_path) WHERE status IN ('OPEN', 'ACKNOWLEDGED')`), set `idp.resource.sync_status = 'DRIFTED'`, and emit an append-only `idp.gate_event` (`gate = 'OBSERVED'`, `event_type = 'drift.detected'`).
   - Expose drift summary endpoints in `ssp-cp` (`GET /api/v1/drift-findings`, `POST /api/v1/drift-findings/{drift_id}/acknowledge`) and surface `open_drift_count` in `idp.v_resource_status`.

## Acceptance Criteria

1. `k8s_job_name("op:af42f828-3378-5ee2-8e9b-2378d2314f97:r2:refresh_plan:2026-10-23T06", "refresh_plan")` evaluates to `"tf-refresh-plan-415a15a935cbd63f95e1"`, matching `specs/examples/gcs_bucket.gates.json`.
2. Unit and integration tests against the `specs/examples/gcs_bucket.gates.json` drift fixture (`public_access_prevention` switched from `"enforced"` to `"inherited"`) verify:
   - `idp.observation` records `source = "refresh_plan"`, `snapshot_uri = "gs://<spp-factory-host-project-id>-spp-tfstate/projects/<lob>-nonprod-orders-svc/observed/scan-2026-10-23T06/plan.json"`, `state_serial_before = 6`, `state_serial_after = 6`, and `drift_detected = true`.
   - `idp.drift_finding` records `drift_kind = "out_of_band_change"`, `attribute_path = "/public_access_prevention"`, `expected_value = "enforced"`, `observed_value = "inherited"`, `severity = "critical"`, `guardrail_rule_id = "GCS-PAP-001"`, and `status = "OPEN"`.
   - Zero `tf-apply-*` Jobs are launched automatically (strictly alert-only).
3. Unit and integration tests against the `specs/examples/spanner.gates.json` drift fixture (`processing_units` changed out-of-band from `100` to `300` on a non-autoscaled instance) verify `drift_kind = "out_of_band_change"`, `attribute_path = "/processing_units"`, `expected_value = 100`, `observed_value = 300`, `severity = "medium"`, `guardrail_rule_id = null`, `status = "OPEN"`.
4. Ignored-path tests verify that changes to `/force_destroy`, `/ddl`, `/deletion_protection`, or autoscaled `/processing_units` produce zero `idp.drift_finding` rows, and quiet scans with unchanged `projection_sha256` perform zero updates to `idp.resource_observed`.

## Dependencies & Blockers

- **Depends On:** `WI-001` (`ssp-cp` AlloyDB schema), `WI-002` (`ssp-workers` runner infrastructure), `WI-004` (`ssp-module-gcs-bucket` for live vertical-slice drift testing).
- **External Blockers (`TODO`):**
  - **`BLK-001`:** GitHub App `spp-factory` credentials (`GITHUB_APP_ID`: `TODO`, `GITHUB_APP_INSTALLATION_ID`: `TODO`, key in Secret Manager `spp-factory-github-app-key`: `TODO`).
  - **`BLK-003`:** Runner GCP Service Account email (`<TODO-runner-sa>@<spp-factory-host-project-id>.iam.gserviceaccount.com`) for live `terraform plan -refresh-only` execution in `<spp-factory-host-project-id>`.

## Factory Stations & Role Skills (`spp-factory-foundation`)

| Station | Role Skill (`agents/skills/<role>/SKILL.md`) | Station Deliverable for `WI-005` |
| :--- | :--- | :--- |
| **1. `impact`** | `requirements-impact` | Maps `ADR-AUT-002`, `ADR-GLB-003..004`, `ADR-GLB-007`, and `ADR-GLB-009` to `ssp-workers` and `ssp-cp`. |
| **2. `plan`** | `change-plan` | Maps JSON-pointer drift comparer, `drift_ignore_paths`, severity rules, and alert-only invariants to `pytest` fixtures. |
| **3. `build`** | `drift-and-reconciliation`, `control-plane` | Implements `DriftSchedule`, `refresh_plan` runner mode, JSON-pointer drift comparer, AlloyDB persistence, and `ssp-cp` drift endpoints. |
| **4. `gate`** | `validation` | Runs `pytest` against `gcs_bucket.gates.json` and `spanner.gates.json` drift fixtures + `gates/scripts/run_gate.sh` (max 3 retries). |
| **5. `review`** | `change-review` | Confirms alert-only behavior (zero auto-remediation code paths), `< 2000`-byte projection check, and `ADR-*` traceability. |
| **6. `approval`** | Human Gate | Architect (`Manoj`) and Approvers (`Dwayne`, `Norm`) review and approve PR. |
| **7. `merge`** | `control-plane` | Merges PR to `ssp-workers` and `ssp-cp`. |
| **8. `reconcile`** | `drift-and-reconciliation`, `standards-feedback` | Verifies scheduled drift scan metrics and feeds lessons learned into `standards-feedback`. |
