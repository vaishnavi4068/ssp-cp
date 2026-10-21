---
id: WI-002
title: Temporal workers (ssp-workers) — render Expected to GCS, TF K8s Jobs in spp-platform, record Observed, and rollback
repo: ssp-workers
status: ready
adr_refs:
  - ADR-GLB-001
  - ADR-GLB-002
  - ADR-GLB-003
  - ADR-GLB-004
  - ADR-GLB-005
  - ADR-GLB-006
  - ADR-GLB-007
  - ADR-GLB-009
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
depends_on:
  - WI-001
blockers:
  - BLK-001 (GitHub App spp-factory credentials for live factory PR push)
  - BLK-003 (Runner GCP service account email in microdrive-dev: TODO)
factory_stations:
  - impact (requirements-impact)
  - plan (change-plan)
  - build (control-plane, drift-and-reconciliation)
  - gate (validation)
  - review (change-review)
  - approval (human gate: Manoj, Dwayne, Norm)
  - merge (control-plane)
  - reconcile (drift-and-reconciliation, standards-feedback)
---

# WI-002: Temporal Workers & K8s Job Runner (`ssp-workers`)

## Goal

Build the Python Temporal workers (`ssp-workers`) polling the `platform` Temporal namespace on GKE `md-dev` to orchestrate `RequestWorkflow`, `ApprovalGateWorkflow`, and `StateUnitReconcilerWorkflow`: rendering immutable `Expected` revisions (`ifGenerationMatch=0`) to `gs://microdrive-dev-spp-tfstate`, executing Terraform `plan` and `apply` as deterministic Kubernetes Jobs (`tf-<phase>-<20hex>`) in namespace `spp-platform`, recording `Observed` state pointers in GCS and `<= 2 KB` non-sensitive projections in AlloyDB, and supporting rollback by re-applying the last approved specification.

## Target Repository

- **`github.com/vaishnavi4068/ssp-workers`** (deployed in Kubernetes namespace `spp-platform` on GKE `md-dev`, connected to `temporal-frontend.spp-temporal.svc.cluster.local:7233` on Temporal namespace `platform`).

## Inputs (`ssp-doc` `main`)

### Governing ADRs
- **[`ADR-AUT-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-001-terraform-execution-k8s-job.md):** Temporal Orchestration and Terraform Execution via Deterministic Kubernetes Jobs — Workflows `RequestWorkflow` (`req-<request_id>`), `ApprovalGateWorkflow` (`apr-<request_id>`), `StateUnitReconcilerWorkflow` (`su-gcp-<project_id>` via `signal-with-start`), 7-step reconciler loop, `operation_id = "op:<state_unit_id>:r<revision_no>:<phase>:<run_key>"`, deterministic K8s Job name `k8s_job_name(operation_id, phase) = "tf-" + phase.replace("_", "-") + "-" + sha256(operation_id)[:20]` in namespace `spp-platform`, `AlreadyExists` reattachment on retry, and `tf_exit_code` (`0`, `1`, `2`) handling (`REQ-1..5`, `GR-1..4`).
- **[`ADR-AUT-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-002-day-2-operations-scope.md):** Day-2 Operations, Drift Detection, and Deletion Governance — Rollback/update via new revision referencing prior `Approved` spec (`base_approval_id`), `destroy_without_delete_request` blocking, and `pre_apply`/`post_apply` lifecycle tasks (`REQ-1..3`, `GR-1..3`).
- **[`ADR-AUT-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-003-software-factory-adr-flow.md):** Software Factory ADR Flow and Verification Gates.
- **[`ADR-CLD-GCP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/per-cloud/gcp/ADR-CLD-GCP-001-runtime-platform-gke-and-temporal.md):** Runtime Platform — GKE `md-dev`, tainted `spp-pool` (`nodeSelector: workload=spp`, toleration `dedicated=spp:NoSchedule`), K8s namespace `spp-platform`, Temporal server `temporal-frontend.spp-temporal.svc.cluster.local:7233`, Temporal namespace `platform` (`REQ-1..5`).
- **[`ADR-GLB-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-001-global-architecture-overview.md) & [`ADR-GLB-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-002-languages-and-technology-stack.md):** Python `3.11+`, `temporalio` SDK, official `kubernetes` Python client, `google-cloud-storage`; no non-deterministic I/O inside `@workflow.defn` (`ADR-GLB-002 REQ-2`, `GR-3`).
- **[`ADR-GLB-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-003-four-state-model.md) & [`ADR-GLB-004`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-004-data-model-and-database.md):** GCS state layout in `gs://microdrive-dev-spp-tfstate/projects/<project_id>/` (`default.tfstate`, `default.tflock`, `expected/rev-NNNNNN/{terraform.tfvars.json, manifest.json, plan.json}`, `logs/<k8s_job_name>.log`), optimistic concurrency on `state_unit.current_expected_rev`, and `<= 2 KB` (`< 2000` bytes) `idp.resource_observed.projection` upserted only when `projection_sha256` changes (`REQ-3..6`).
- **[`ADR-GLB-005`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-005-identity-and-authentication.md):** Workload Identity for runner Jobs in `spp-platform` (`<TODO-runner-sa>@microdrive-dev.iam.gserviceaccount.com`) impersonating the target project's executor SA (`state_unit.executor_identity`), plus two-level kill switch (`INV-9`).
- **[`ADR-GLB-007`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-007-governance-gates-and-policy-rego.md) & [`ADR-GLB-009`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-009-resource-kind-registry.md):** Invariants `INV-1..INV-9` and dynamic `tfvars_collection` composition from `idp.resource_kind`.
- **[`ADR-BP-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-002-build-order-and-phasing.md) & [`ADR-BP-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-003-roles-and-approver-governance.md):** Sequential `ApprovalGateWorkflow` timers, follow-ups, manager escalation, 13-day `max_wait_days` auto-close, and 30-day `valid_until`.

### Governing Specifications (`ssp-doc/specs/`)
- **[`specs/data-model/spp_state_model.sql`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/data-model/spp_state_model.sql):** Tables `idp.expected_revision`, `idp.expected_revision_member`, `idp.tf_operation`, `idp.observation`, `idp.resource_observed`, `idp.lifecycle_task`, `idp.gate_event`, and SQL function `idp.k8s_job_name`.
- **[`specs/naming/naming-spec.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/naming/naming-spec.json):** Platform identifier regexes (`operation_id`, `k8s_job_name`, `k8s_namespace = "spp-platform"`, `state_bucket = "microdrive-dev-spp-tfstate"`, `artifact_uri`, `state_uri`, `logs_uri`).
- **[`specs/examples/gcs_bucket.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/gcs_bucket.gates.json) & [`specs/examples/spanner.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/spanner.gates.json):** Expected/Observed DB row and projection examples (`tf-plan-eba5f9ebf4fafecad8e9`, `tf-apply-b85d57b4511c03e98373`).

## Scope & Implementation Requirements

1. **Temporal Workflows on `platform` Namespace (`ADR-AUT-001`, `ADR-BP-003`):**
   - `RequestWorkflow` (`req-<request_id>`): Drives `REQUESTED -> APPROVED`, invokes `ApprovalGateWorkflow` (`apr-<request_id>`), materializes `idp.lifecycle_task` rows (`pre_apply`: `ad_group`, `vpc_sc_ingress`, `vpc_sc_project_membership`, `enable_service`; `post_apply`: `notify_owner`, `backup_enroll`), and signals `StateUnitReconcilerWorkflow` (`su-gcp-<project_id>`) via `signal-with-start` (`approval_ready {approval_id}`).
   - `ApprovalGateWorkflow` (`apr-<request_id>`): Handles `approval_response {decision_id, status, responded_by, comment}` signals, sequential phases (`run_after_approver_keys`), `skip_condition` evaluation, SLA reminders, manager escalation, 13-day `max_wait_days` expiration, and `self_approval = "deny"`.
   - `StateUnitReconcilerWorkflow` (`su-gcp-<project_id>`): Serializes all state-file runs for a single GCP project (`INV-8`) and supports `continue-as-new` without dropping queued signals.
2. **Render `Expected` Revision to `gs://microdrive-dev-spp-tfstate` (`ADR-GLB-003`, `ADR-GLB-009`):**
   - Compose `projects/<project_id>/expected/rev-NNNNNN/terraform.tfvars.json` and `manifest.json` from all active `idp.approval` records in the state unit (`expected_revision_member.change` in `unchanged | added | modified | removed`), grouped by `idp.resource_kind.tfvars_collection` (`gcs_buckets`, `spanner_instances`, `spanner_databases`).
   - Write artifacts to `gs://microdrive-dev-spp-tfstate` with **`ifGenerationMatch=0`** (create-only, `INV-5`) and record `artifact_uri`, `artifact_generation`, and canonical `artifact_sha256` in `idp.expected_revision`.
   - Advance `idp.state_unit.current_expected_rev` using optimistic concurrency (`WHERE current_expected_rev IS NOT DISTINCT FROM :prev_rev`).
   - Verify `INV-6` before planning: every member's `approved_spec_sha256` in `manifest.json` must equal `idp.approval.approved_spec_sha256` in AlloyDB (otherwise mark `status = 'BLOCKED'`, `blocked_reason = 'approved_hash_mismatch'`).
3. **Deterministic Kubernetes Job Terraform Execution in `spp-platform` (`ADR-AUT-001`):**
   - Check kill switch `idp.state_unit.status != 'frozen'` (`INV-9`) before launching `plan` or `apply`.
   - Derive `operation_id = f"op:{state_unit_id}:r{revision_no}:{phase}:{run_key}"` and `k8s_job_name = f"tf-{phase.replace('_', '-')}-{sha256(operation_id)[:20]}"` (matching `idp.k8s_job_name`).
   - Launch one Kubernetes Job per run in namespace `spp-platform` (`nodeSelector: workload=spp`, toleration `dedicated=spp:NoSchedule`, non-root security context, Workload Identity KSA bound to `<TODO-runner-sa>@microdrive-dev.iam.gserviceaccount.com` impersonating `state_unit.executor_identity`).
   - Reattach idempotently on `409 AlreadyExists` when an activity retries, polling Job completion and recording `tf_exit_code` (`0`, `1`, `2`), `state_serial_before`, `state_serial_after`, `state_lineage`, and `logs_uri` (`gs://microdrive-dev-spp-tfstate/projects/<project_id>/logs/<k8s_job_name>.log`) in `idp.tf_operation` (`INV-7`).
   - In the `plan` Job, run `terraform init`, `terraform plan -out=planfile -detailed-exitcode`, `terraform show -json planfile > plan.json`, upload `plan.json` to `expected/rev-NNNNNN/plan.json`, and run `conftest` policy checks against `plan.json` (wired with `WI-003`, `INV-4`). Block with `blocked_reason = 'destroy_without_delete_request'` if `destroy > 0` or `replace > 0` lacks an explicit human-approved delete request.
   - In the `apply` Job, apply the exact saved `planfile` from the `plan` step (`INV-5`).
4. **Record `Observed` State & Support Rollback (`ADR-GLB-003`, `ADR-GLB-004`, `ADR-BP-002`):**
   - After `apply` completes, write `idp.observation` (`source = 'post_apply'`, `state_uri = "gs://microdrive-dev-spp-tfstate/projects/<project_id>/default.tfstate"`, `state_generation`, `state_serial`).
   - Extract per-resource values from `terraform show -json`, strip all paths flagged under `sensitive_values`, enforce `< 2000` bytes (`resource_observed_projection_small`), compute `projection_sha256`, and upsert `idp.resource_observed` **only when `projection_sha256` changes** (`WHERE ro.projection_sha256 IS DISTINCT FROM EXCLUDED.projection_sha256`).
   - **Rollback:** Implement rollback by rendering and applying a new `Expected` revision (`rev-(N+1)`) that restores the resource's last known-good `idp.approval` specification (`approved_spec` / `approved_spec_sha256`), running through the same `plan` (verifying zero unapproved destroys) and `apply` Job pipeline.

## Acceptance Criteria

1. `k8s_job_name("op:af42f828-3378-5ee2-8e9b-2378d2314f97:r1:plan:1", "plan")` returns `"tf-plan-eba5f9ebf4fafecad8e9"` and `"op:af42f828-3378-5ee2-8e9b-2378d2314f97:r1:apply:1"` returns `"tf-apply-b85d57b4511c03e98373"`, matching `specs/examples/gcs_bucket.gates.json` and SQL `idp.k8s_job_name`.
2. Temporal workflow replay and unit tests verify:
   - `StateUnitReconcilerWorkflow` serializes concurrent `approval_ready` signals for the same project (`INV-8`).
   - `state_unit.status == 'frozen'` halts `plan` and `apply` Job creation (`INV-9`).
   - Mismatched `approved_spec_sha256` between AlloyDB and `manifest.json` transitions the revision to `BLOCKED` (`blocked_reason = 'approved_hash_mismatch'`, `INV-6`).
   - Activity retry when a K8s Job already exists (`409 AlreadyExists`) reattaches to the in-flight Job instead of creating a duplicate Job (`INV-7`).
3. Re-observing an unchanged resource (such as the `gcs_bucket` during `rev-000002` in `specs/examples/gcs_bucket.gates.json`) produces the identical `projection_sha256` and performs zero updates to `idp.resource_observed`.
4. Rollback test verifies that triggering a rollback on a failed or undesired update composes a new `Expected` revision (`rev-(N+1)`) from the prior approved specification and re-applies it cleanly through `tf-plan-*` and `tf-apply-*`.

## Dependencies & Blockers

- **Depends On:** `WI-001` (`ssp-cp` AlloyDB `idp` schema and models).
- **External Blockers (`TODO`):**
  - **`BLK-001`:** GitHub App `spp-factory` credentials (`GITHUB_APP_ID`: `TODO`, `GITHUB_APP_INSTALLATION_ID`: `TODO`, key in Secret Manager `spp-factory-github-app-key` in `microdrive-dev`: `TODO`).
  - **`BLK-003`:** Runner GCP Service Account email (`<TODO-runner-sa>@microdrive-dev.iam.gserviceaccount.com`) and target project executor SA email (`<TODO-executor-sa>@<project_id>.iam.gserviceaccount.com`) for live GKE Workload Identity and Terraform backend execution against `gs://microdrive-dev-spp-tfstate`.

## Factory Stations & Role Skills (`spp-factory-foundation`)

| Station | Role Skill (`agents/skills/<role>/SKILL.md`) | Station Deliverable for `WI-002` |
| :--- | :--- | :--- |
| **1. `impact`** | `requirements-impact` | Maps `ADR-AUT-001..002`, `ADR-GLB-003..005`, and `ADR-CLD-GCP-001` to `ssp-workers` workflows, activities, and runner container image. |
| **2. `plan`** | `change-plan` | Execution Change Plan mapping `INV-4..INV-9`, `k8s_job_name`, GCS `ifGenerationMatch=0`, and rollback to Temporal replay and unit tests. |
| **3. `build`** | `control-plane`, `drift-and-reconciliation` | Python Temporal workflows/activities, K8s Job launcher, Terraform runner entrypoint script, and Helm manifests for `spp-platform`. |
| **4. `gate`** | `validation` | Runs `pytest`, Temporal workflow replay tests, and `gates/scripts/run_gate.sh` (max 3 retries). |
| **5. `review`** | `change-review` | Verifies zero in-worker Terraform execution, deterministic Job naming, `gs://microdrive-dev-spp-tfstate` paths, and `TODO` placeholders. |
| **6. `approval`** | Human Gate | Architect (`Manoj`) and Approvers (`Dwayne`, `Norm`) review and approve PR. |
| **7. `merge`** | `control-plane` | Merges PR to `ssp-workers` `main`. |
| **8. `reconcile`** | `drift-and-reconciliation`, `standards-feedback` | Verifies worker health on `md-dev` (`spp-platform`) and records feedback. |
