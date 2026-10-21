---
id: WI-003
title: Policy gates — internal OPA Deployment on md-dev, API intake/approval evaluation, and Conftest plan gate
repo: ssp-cp
target_repos:
  - ssp-cp
  - ssp-workers
  - ssp-module-gcs-bucket
status: ready
adr_refs:
  - ADR-GLB-001
  - ADR-GLB-002
  - ADR-GLB-003
  - ADR-GLB-004
  - ADR-GLB-006
  - ADR-GLB-007
  - ADR-GLB-008
  - ADR-GLB-009
  - ADR-BP-001
  - ADR-BP-003
  - ADR-SVC-001
  - ADR-CLD-GCP-001
  - ADR-AUT-001
  - ADR-AUT-002
  - ADR-AUT-003
spec_refs:
  - specs/data-model/spp_state_model.sql
  - specs/naming/naming-spec.json
  - specs/examples/gcs_bucket.gates.json
depends_on:
  - WI-001
  - WI-002
blockers:
  - BLK-001 (GitHub App spp-factory credentials for live factory PR push)
  - BLK-002 (KMS key URI in us-east1: TODO from user for live CMEK key allowlist/lookup)
factory_stations:
  - impact (requirements-impact)
  - plan (change-plan)
  - build (policy-and-compliance, control-plane)
  - gate (validation)
  - review (change-review)
  - approval (human gate: Manoj, Dwayne, Norm)
  - merge (control-plane)
  - reconcile (drift-and-reconciliation, standards-feedback)
---

# WI-003: Policy Gates (Plain OPA Server Deployment + Conftest Plan Gate)

## Goal

Deploy a plain **Open Policy Agent (OPA) server `Deployment` (NOT OPA Gatekeeper)** in its own dedicated Kubernetes namespace on GKE `md-dev` (internal ClusterIP only, scheduled on `spp-pool`), loading versioned Rego bundles from a policy repository; integrate `ssp-cp` to call the OPA server at intake (`stage = 'requested'`) and approval (`stage = 'approved'`) and persist all evaluation results and guardrail mutations in `idp.policy_evaluation` and `idp.approval.guardrail_trace`; and execute the **same Rego policies via `conftest`** against Terraform `plan.json` (`terraform show -json <planfile>`) inside the `spp-platform` Terraform Kubernetes Jobs (`stage = 'plan'`) before `terraform apply` can proceed.

## Target Repositories

- **`github.com/vaishnavi4068/ssp-cp`** (OPA HTTP client, `idp.policy_evaluation` persistence at `requested` and `approved` stages, `guardrail_trace` application, and internal OPA server K8s `Deployment`/`Service`/`NetworkPolicy` manifests).
- **`github.com/vaishnavi4068/ssp-workers`** (`conftest` execution in the `tf-plan-<20hex>` runner Job and `stage = 'plan'` `idp.policy_evaluation` persistence before `tf-apply-<20hex>`).
- **Policy Bundle / `ssp-module-gcs-bucket`** (clean-slate Rego packages `idp.common`, `idp.naming`, `idp.labels`, `idp.gcp.gcs_bucket` and `*_test.rego` unit tests; policy bundle repo/location `TODO` if split from `ssp-cp` / module repos).

## Inputs (`ssp-doc` `main`)

### Governing ADRs
- **[`ADR-GLB-007`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-007-governance-gates-and-policy-rego.md):** Governance Gates, Guardrails, Invariants, and Policy (Rego) — Clean-slate Rego (`import rego.v1`, zero reuse from legacy "taxi"), three-stage evaluation (`requested`, `approved`, `plan`) recorded in `idp.policy_evaluation` (`decision IN ('allow', 'deny', 'allow_with_mutations')`), guardrail rule catalog (`GCS-*`, `SPN-*`, `LBL-*`, `PRQ-*`, `NAM-*`), `idp.approval.guardrail_trace`, invariants `INV-1..INV-9`, `us-east1`-only constraint, and human-approval requirement for any delete/destroy/replace (`REQ-1..6`, `GR-1..5`).
- **[`ADR-GLB-006`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-006-naming-and-labeling-conventions.md):** Naming Conventions and Identifier Patterns — Rules `GCS-NAME-001..003`, `SPN-NAME-001..003`, `NAM-RSV-001`, `NAM-IMM-001`, `NAM-LEG-001`, and `env` token restricted to `nonprod` (no hyphen) and `prod` (`REQ-1..5`, `GR-1..4`).
- **[`ADR-GLB-008`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-008-label-and-tag-standard.md):** Label and Tag Standard — **8 mandatory labels** (`sppappid`, `costcenter`, `environmenttype`, `primarylob`, `datasensitivity`, `owner`, `provisionedby`, `idp_resource_id`), **`environmentsubtype` dropped everywhere**, `environmenttype` restricted to `nonprod` | `prod`, and `LBL-001` / `LBL-002` normalization (`REQ-1..6`, `GR-1..3`).
- **[`ADR-SVC-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/endpoint-service/ADR-SVC-001-first-vertical-slice-gcs-bucket.md):** First Vertical Slice — GCS Bucket (`gcs_bucket`) End-to-End and Guardrails — `GCS-UBLA-001` (`uniform_bucket_level_access = true`), `GCS-PAP-001` (`public_access_prevention = "enforced"`), `GCS-ENC-001/002` (`kms_key_name` in `us-east1`), `GCS-RET-001` (`retention_days >= 90` when `versioning == false`), `GCS-RET-003` (`retention_locked = false`), `GCS-SDP-001` (`soft_delete_retention_days = 7`), `GCS-DEL-001` (`force_destroy = false`), `PRQ-001` (`ad_group`), `PRQ-002` (`vpc_sc_ingress`), optional `lifecycle_rules` validation (default `[]`), and IAM principal/role allowlist (`REQ-1..6`, `GR-1..4`).
- **[`ADR-GLB-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-002-languages-and-technology-stack.md), [`ADR-GLB-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-003-four-state-model.md), [`ADR-GLB-004`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-004-data-model-and-database.md), [`ADR-GLB-009`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-009-resource-kind-registry.md):** `OPA v0.69+`, `Conftest v0.56+`, `idp.policy_evaluation` schema, `opa_package` per `idp.resource_kind`.
- **[`ADR-BP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-001-ownership-map-and-governance.md), [`ADR-BP-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-003-roles-and-approver-governance.md), [`ADR-CLD-GCP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/per-cloud/gcp/ADR-CLD-GCP-001-runtime-platform-gke-and-temporal.md), [`ADR-AUT-001..003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-001-terraform-execution-k8s-job.md):** Non-bypassable operations, IAM principal restrictions (`group:` and `serviceAccount:` only), GKE `md-dev` `spp-pool` placement, and `stage = 'plan'` verification (`INV-4`).

### Governing Specifications (`ssp-doc/specs/`)
- **[`specs/naming/naming-spec.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/naming/naming-spec.json):** Naming rules, forbidden prefixes/substrings, label normalization rules, and test vectors.
- **[`specs/data-model/spp_state_model.sql`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/data-model/spp_state_model.sql):** `idp.policy_evaluation` table and `policy_evaluation_subject` `CHECK` constraint (`(stage = 'plan' AND revision_id IS NOT NULL AND request_id IS NULL) OR (stage <> 'plan' AND request_id IS NOT NULL AND revision_id IS NULL)`).
- **[`specs/examples/gcs_bucket.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/gcs_bucket.gates.json):** Complete `guardrail_trace` and `policy_bundle_revision` example.

## Scope & Implementation Requirements

1. **Plain OPA Server Deployment on GKE `md-dev` (NOT Gatekeeper):**
   - Deploy a plain **OPA server (`openpolicyagent/opa:0.69.0+`) `Deployment`** (explicitly **NOT** Kubernetes Gatekeeper / admission webhook) in its own dedicated Kubernetes namespace on GKE `md-dev` (e.g., `spp-policy`; exact namespace name `TODO` if overridden by operator), scheduled onto `spp-pool` (`nodeSelector: workload=spp`, toleration `dedicated=spp:NoSchedule`).
   - Expose OPA **internally only** via a ClusterIP `Service` (`:8181`) with a Kubernetes `NetworkPolicy` permitting ingress on port `8181` **only** from `ssp-cp` and `ssp-workers` in namespace `spp-platform` (zero public ingress).
   - Configure OPA to load versioned Rego bundles (recording `bundle_revision` in `idp.policy_evaluation`) from the policy repository / GCS bundle source (`TODO` bundle URL/repo ref).
2. **Three-Stage Policy Evaluation & `idp.policy_evaluation` Persistence (`ADR-GLB-007`):**
   - **Intake (`stage = 'requested'`):** `ssp-cp` sends the canonical `requested_spec` (`input_sha256 = canonical_sha256(input)`) to OPA (`opa_package` from `idp.resource_kind`), persists the result in `idp.policy_evaluation` (`request_id` set, `revision_id = NULL`), and rejects the request if `decision == 'deny'`.
   - **Approval (`stage = 'approved'`):** `ssp-cp` / `RequestWorkflow` calls OPA to evaluate guardrail rules and compute mutations (`decision IN ('allow', 'allow_with_mutations', 'deny')`), writes the row to `idp.policy_evaluation`, applies mutations to produce `approved_spec`, and records every mutation in `idp.approval.guardrail_trace` (`[{rule_id, path, from, to, reason}]`) linked via `idp.approval.policy_evaluation_id`.
   - **Pre-Apply Plan Gate (`stage = 'plan'`, `INV-4`):** Inside the `tf-plan-<20hex>` Kubernetes Job in `spp-platform`, run **`conftest test`** with the exact same Rego bundle against `plan.json` (`terraform show -json planfile`). Persist the result in `idp.policy_evaluation` (`stage = 'plan'`, `revision_id` set, `request_id = NULL`). If `conftest` fails or if `plan_summary.destroy > 0` or `plan_summary.replace > 0` without an explicit human-approved delete request, mark `idp.expected_revision.status = 'BLOCKED'` (`blocked_reason = 'destroy_without_delete_request'`) and never run `terraform apply`.
3. **Mandatory Rego Policy Rules (`import rego.v1`):**
   - **Global Invariants (`INV-1`):** Reject any secret-bearing keys/values (`password`, `passwd`, `client_secret`, `private_key`, `secret_value`, `api_key`, `token`) at `requested`, `approved`, and `plan`.
   - **Cloud & Region (`ADR-GLB-001`, `ADR-GLB-007`):** Enforce `cloud == "gcp"` and `location == "us-east1"` (or `config == "regional-us-east1"`); reject multi-region `US`, `nam3`, or `us-east4`.
   - **Naming Rules (`ADR-GLB-006`, `specs/naming/naming-spec.json`):**
     - `GCS-NAME-001`: Bucket name matches `{lob}-{env}-{app}-{purpose}-{suffix}` (`max 63` chars, `env` in `{"nonprod", "prod"}` with no hyphen).
     - `GCS-NAME-002`: Reject bucket names starting with `goog` or containing `google` or `g00gle`.
     - `NAM-RSV-001`: Reject `purpose` tokens matching reserved words (`non-prod`, `nonprod`, `prod`, `sandbox`, `dev`, `qa`, `test`, `pdev`, `pqa`, `preprod`, `restricted`, `unrestricted`).
     - `NAM-IMM-001`: Reject `action == "update"` if `spec.name` differs from the existing resource name.
     - `NAM-LEG-001`: Allow existing name on `action == "import"` and inject label `idp_naming = "legacy"`.
   - **8 Mandatory Labels (`ADR-GLB-008`):**
     - `LBL-001`: Compute and require all **8 mandatory labels** (`sppappid`, `costcenter`, `environmenttype`, `primarylob`, `datasensitivity`, `owner`, `provisionedby`, `idp_resource_id`) plus metadata-derived labels (`dataclassification`, `sharedemailaddress`, `tenancy`).
     - **Forbid `environmentsubtype`:** Explicitly deny or strip `environmentsubtype` everywhere; enforce `environmenttype` in `{"nonprod", "prod"}`.
     - `LBL-002`: Normalize all label values (lowercase, replace `[^a-z0-9_-]` with `_`, max 63 chars, drop empty).
   - **GCS Bucket Guardrails (`ADR-SVC-001`):**
     - `GCS-UBLA-001`: `/spec/uniform_bucket_level_access = true`.
     - `GCS-PAP-001`: `/spec/public_access_prevention = "enforced"`.
     - `GCS-ENC-001` / `002`: `/spec/kms_key_name` (`default_kms_key_name`) non-empty and in `locations/us-east1`.
     - `GCS-RET-001`: `/spec/retention_days >= 90` (`7776000` seconds in `plan.json` when `versioning == false`; reject combining retention policy with `versioning == true`).
     - `GCS-RET-003`: `/spec/retention_locked = false` (`retention_policy.is_locked = false` by default).
     - `GCS-SDP-001`: `/spec/soft_delete_retention_days = 7` (`604800` seconds in `plan.json`).
     - `GCS-DEL-001`: `/spec/force_destroy = false` (never force-delete non-empty buckets).
     - **Lifecycle Rules:** Default `lifecycle_rules = []`; validate optional user-supplied `lifecycle_rules` (`Delete`, `SetStorageClass`, noncurrent version cleanup; ensure `Delete` `age_days >= retention_days` when retention is active).
     - **IAM Allowlist & Prerequisites:** Allow only `group:` and `serviceAccount:` members (deny `user:`, `allUsers`, `allAuthenticatedUsers`) and allowlisted Storage roles (`roles/storage.objectAdmin`, `roles/storage.objectViewer`, `roles/storage.objectCreator`; deny `roles/storage.admin`); materialize `PRQ-001` (`ad_group`) and `PRQ-002` (`vpc_sc_ingress` for `restricted` data).

## Acceptance Criteria

1. `opa test -v` passes 100% of positive and negative unit tests covering `GCS-NAME-001..002`, `NAM-RSV-001`, `NAM-IMM-001`, `NAM-LEG-001`, `LBL-001..002` (8 mandatory labels, no `environmentsubtype`, `environmenttype` in `nonprod`|`prod`), `GCS-UBLA-001`, `GCS-PAP-001`, `GCS-ENC-001`, `GCS-RET-001`, `GCS-RET-003`, `GCS-SDP-001`, `GCS-DEL-001`, `PRQ-001..002`, IAM allowlists, and `destroy_without_delete_request`.
2. Calling `ssp-cp` with the `requested.document` from `specs/examples/gcs_bucket.gates.json` evaluates OPA at `stage = 'requested'` and `stage = 'approved'`, writes two rows to `idp.policy_evaluation`, and produces the exact 10-entry `guardrail_trace` in `idp.approval.guardrail_trace`.
3. Running `conftest test` against a mock Terraform `plan.json` in the runner container image passes for a compliant `us-east1` bucket plan and fails when:
   - `location != "us-east1"`,
   - `public_access_prevention != "enforced"`,
   - `uniform_bucket_level_access != true`,
   - `force_destroy != false`,
   - `environmentsubtype` is present or any of the 8 mandatory labels is missing,
   - `default_kms_key_name` is missing or not in `locations/us-east1`, or
   - any resource action in `resource_changes` includes `"delete"` without an approved delete request.
4. Kubernetes manifests deploy a plain OPA server `Deployment` (not Gatekeeper) with internal-only ClusterIP `Service` and `NetworkPolicy` on GKE `md-dev` (`spp-pool`).

## Dependencies & Blockers

- **Depends On:** `WI-001` (`ssp-cp` `idp.policy_evaluation` & `idp.approval` store), `WI-002` (`ssp-workers` `tf-plan-<20hex>` runner Job).
- **External Blockers (`TODO`):**
  - **`BLK-001`:** GitHub App `spp-factory` credentials (`GITHUB_APP_ID`: `TODO`, `GITHUB_APP_INSTALLATION_ID`: `TODO`, key in Secret Manager `spp-factory-github-app-key` in `microdrive-dev`: `TODO`).
  - **`BLK-002`:** Real KMS key URI in `us-east1` (`projects/microdrive-dev/locations/us-east1/keyRings/<TODO>/cryptoKeys/<TODO>`) from user for live `GCS-ENC-001` lookup in `microdrive-dev`.

## Factory Stations & Role Skills (`spp-factory-foundation`)

| Station | Role Skill (`agents/skills/<role>/SKILL.md`) | Station Deliverable for `WI-003` |
| :--- | :--- | :--- |
| **1. `impact`** | `requirements-impact` | Maps `ADR-GLB-006..008` and `ADR-SVC-001` rules to OPA packages, `ssp-cp` evaluator client, and `ssp-workers` `conftest` runner step. |
| **2. `plan`** | `change-plan` | Maps every rule ID (`GCS-*`, `LBL-*`, `NAM-*`, `PRQ-*`) to an `opa test` and `conftest` fixture. |
| **3. `build`** | `policy-and-compliance`, `control-plane` | Authors Rego policies (`import rego.v1`), `*_test.rego` unit tests, OPA K8s `Deployment` manifests, `ssp-cp` OPA client, and `ssp-workers` `conftest` hook. |
| **4. `gate`** | `validation` | Runs `opa test -v`, `conftest test`, and `gates/scripts/run_gate.sh` (max 3 retries). |
| **5. `review`** | `change-review` | Confirms plain OPA Deployment (not Gatekeeper), internal-only ClusterIP, 8 mandatory labels without `environmentsubtype`, and zero invented KMS paths. |
| **6. `approval`** | Human Gate | Architect (`Manoj`), Approvers (`Dwayne`, `Norm`), and Security (`Raju`) review and approve PR. |
| **7. `merge`** | `control-plane` | Merges PR to target repositories. |
| **8. `reconcile`** | `drift-and-reconciliation`, `standards-feedback` | Updates factory gate policies if new edge cases are discovered. |
