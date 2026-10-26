---
id: WI-006
title: Portal UI (ssp-ui) — DEFERRED (MVP requests via API; thin form later in Phase 5)
repo: ssp-ui
status: deferred
adr_refs:
  - ADR-BP-002
  - ADR-BP-001
  - ADR-BP-003
  - ADR-GLB-001
  - ADR-GLB-002
  - ADR-GLB-003
  - ADR-GLB-004
  - ADR-GLB-005
  - ADR-GLB-006
  - ADR-GLB-008
  - ADR-GLB-009
  - ADR-CLD-GCP-001
  - ADR-AUT-003
spec_refs:
  - specs/data-model/spp_state_model.sql
  - specs/naming/naming-spec.json
  - specs/examples/gcs_bucket.gates.json
  - specs/examples/spanner.gates.json
depends_on:
  - WI-001
  - WI-002
  - WI-003
  - WI-004
  - WI-005
blockers:
  - Deferred by ADR-BP-002 until Phase 3 (headless GCS E2E via API) and Phase 4 (GCS Day-2 & drift) are proven in <spp-factory-host-project-id>
  - BLK-001 (GitHub App spp-factory credentials + creation of repo ssp-ui when Phase 5 begins)
factory_stations:
  - impact (requirements-impact)
  - plan (change-plan)
  - build (portal-and-catalog)
  - gate (validation)
  - review (change-review)
  - approval (human gate: Manoj, Dwayne, Norm)
  - merge (control-plane)
  - reconcile (drift-and-reconciliation, standards-feedback)
---

# WI-006: Self-Service Portal UI (`ssp-ui` — Deferred)

## Goal

**Deferred (`status: deferred`, Phase 5 per `ADR-BP-002`):** Keep all MVP resource provisioning (`Requested -> Approved -> Expected -> Observed`), approvals, and Day-2 operations headless via the `ssp-cp` REST API during Phases 2–4; once the GCS bucket vertical slice (`WI-004`) and drift detection (`WI-005`) are proven end-to-end via API, deliver a thin, template-driven React self-service form and status view in **`ssp-ui`**.

## Target Repository

- **`github.com/vaishnavi4068/ssp-ui`** *(deferred to Phase 5; when built, deployed in Kubernetes namespace `spp-platform` on the SPP GKE cluster, node pool `spp-pool`)*.

## Inputs (`ssp-doc` `main`)

### Governing ADRs
- **[`ADR-BP-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-002-build-order-and-phasing.md):** Product Build Order and Delivery Phasing —
  - `REQ-2 (MUST)`: Phase 3 (First Vertical Slice) MUST be limited strictly to **GCS bucket (`google_storage_bucket`) end-to-end provisioning via API with no UI** (`ADR-SVC-001`).
  - `REQ-3 (MUST)`: Phase 4 (GCS Day-2 Operations) MUST be completed and verified on the GCS vertical slice before Phase 5 (`ssp-ui` portal + chat) begins.
  - `GR-1`: Do not build `ssp-ui` frontend screens or chat flows during Phases 1–3; prove the headless control plane and GCS vertical slice via API first.
- **[`ADR-GLB-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-001-global-architecture-overview.md) & [`ADR-GLB-002`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-002-languages-and-technology-stack.md):** React `18+`, TypeScript `5.x`, Vite, Tailwind CSS; declarative schema/template-driven catalog forms (`REQ-3`, `GR-2`) so onboarding a new `ssp-module-<type>` never requires rebuilding or redeploying `ssp-ui`.
- **[`ADR-GLB-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-003-four-state-model.md) & [`ADR-GLB-004`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-004-data-model-and-database.md):** UI queries `idp.v_resource_status`, `idp.approval.guardrail_trace`, `idp.resource_observed.projection` (`< 2000` bytes), and `idp.drift_finding` via `ssp-cp` without reading GCS `.tfstate` files.
- **[`ADR-GLB-005`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-005-identity-and-authentication.md):** Local Argon2id login + mandatory first-login password rotation + `__Host-` session cookies + `X-CSRF-Token` header propagation (with future SSO upgrade path).
- **[`ADR-GLB-006`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-006-naming-and-labeling-conventions.md), [`ADR-GLB-008`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-008-label-and-tag-standard.md), [`ADR-GLB-009`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/global/ADR-GLB-009-resource-kind-registry.md):** Live resource name preview from `specs/naming/naming-spec.json` (`nonprod` | `prod`), normalized 8 mandatory labels preview, and dynamic kind discovery from `idp.resource_kind`.
- **[`ADR-BP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-001-ownership-map-and-governance.md), [`ADR-BP-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/business-process/ADR-BP-003-roles-and-approver-governance.md), [`ADR-CLD-GCP-001`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/per-cloud/gcp/ADR-CLD-GCP-001-runtime-platform-gke-and-temporal.md), [`ADR-AUT-003`](https://github.com/vaishnavi4068/ssp-doc/blob/main/adr/automation/ADR-AUT-003-software-factory-adr-flow.md):** Persona permissions (`requester`, `bucket_owner`, `data_owner`, `dbaas_reviewer`, `platform-team`), self-approval denial in the UI, and human approval confirmation dialogs for deletes.

### Governing Specifications (`ssp-doc/specs/`)
- **[`specs/data-model/spp_state_model.sql`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/data-model/spp_state_model.sql):** Read-model view `idp.v_resource_status` and `idp.submission` (`channel IN ('ui', 'api', 'chat', ...)`).
- **[`specs/naming/naming-spec.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/naming/naming-spec.json):** Client-side naming & label preview rules.
- **[`specs/examples/gcs_bucket.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/gcs_bucket.gates.json) & [`specs/examples/spanner.gates.json`](https://github.com/vaishnavi4068/ssp-doc/blob/main/specs/examples/spanner.gates.json):** Gate status and `guardrail_trace` payloads rendered in the UI.

## Scope & Deferred Implementation Plan

1. **MVP Behavior (Phases 2–4 — Current):**
   - **No UI work is executed during `WI-001` through `WI-005`.**
   - All requests (`channel = "api"`), approvals (`POST /api/v1/approvals/{approval_id}/decisions`), status checks (`GET /api/v1/resources`), and drift inspections (`GET /api/v1/drift-findings`) are performed directly against the `ssp-cp` FastAPI REST API.
2. **Later Thin Form Scope (Phase 5 — When Unblocked):**
   - **Dynamic Schema-Driven Request Form:** Render request forms dynamically from `idp.resource_kind.schema_uri` (`schemas/gcs_bucket.schema.json`, `schemas/spanner.schema.json`) asking only minimal business/sizing fields (`apm_id`, `project_id`, `environment` in `nonprod`|`prod`, `purpose`, storage class / processing units, optional `lifecycle_rules`, `access` bindings) with **zero secret input fields** (`ADR-GLB-003`, `ADR-GLB-004`).
   - **Guardrail Trace & Four-Gate Status View:** Display the four-gate progression (`REQUESTED -> APPROVED -> EXPECTED -> OBSERVED`), the injected `guardrail_trace` explanations (`GCS-*`, `SPN-*`, `LBL-001/002`), the `< 2000`-byte `Observed` projection, and any open alert-only drift findings (`open_drift_count`).
   - **Approval Queue:** Allow `bucket_owner`, `data_owner`, and `dbaas_reviewer` personas to approve or deny pending requests (disabling the Approve button when the logged-in user is the requester per `self_approval = "deny"`, and requiring explicit human confirmation on any `delete` request).

## Acceptance Criteria

1. **During MVP (`WI-001..005`):** Zero UI dependencies block `ssp-cp`, `ssp-workers`, `ssp-module-gcs-bucket`, or `ssp-module-spanner`; 100% of provisioning, approval, rollback, and drift flows are exercisable via the `ssp-cp` REST API (`ADR-BP-002 REQ-2`).
2. **When Phase 5 (`WI-006`) Is Triggered:**
   - `ssp-ui` builds cleanly with TypeScript (`tsc --noEmit`), Vite, and Tailwind CSS, and deploys to namespace `spp-platform` on the SPP GKE cluster (`spp-pool`).
   - Adding a new `idp.resource_kind` row and JSON Schema renders the new resource's thin request form dynamically without modifying or redeploying `ssp-ui` React components (`ADR-GLB-002 REQ-3`, `SC-2`).
   - Zero secret fields exist in any UI form (`INV-1`).

## Dependencies & Blockers

- **Depends On:** Completion and verification of `WI-001` (`ssp-cp`), `WI-002` (`ssp-workers`), `WI-003` (OPA policy gates), `WI-004` (`ssp-module-gcs-bucket` E2E), and `WI-005` (Drift job) per `ADR-BP-002`.
- **External Blockers (`TODO`):**
  - **`ADR-BP-002 OQ-2`:** Phase 5 UI prototype baseline sign-off (`TODO` from Dwayne, Norm, Manoj).
  - **`BLK-001`:** GitHub App `spp-factory` credentials (`GITHUB_APP_ID`: `TODO`, `GITHUB_APP_INSTALLATION_ID`: `TODO`, key in Secret Manager `spp-factory-github-app-key`: `TODO`).

## Factory Stations & Role Skills (`spp-factory-foundation`)

| Station | Role Skill (`agents/skills/<role>/SKILL.md`) | Station Deliverable for `WI-006` (When Un-Deferred in Phase 5) |
| :--- | :--- | :--- |
| **1. `impact`** | `requirements-impact` | Maps `ADR-BP-002..003` and `ADR-GLB-002..009` to `ssp-ui` routes and schema renderer. |
| **2. `plan`** | `change-plan` | Execution Change Plan for the thin schema-driven form, approval queue, and 4-gate status view. |
| **3. `build`** | `portal-and-catalog` | Implements React + TypeScript thin form renderer, local auth login/password-rotation screens, and K8s manifests. |
| **4. `gate`** | `validation` | Runs `tsc --noEmit`, `vitest`/`playwright`, and `gates/scripts/run_gate.sh` (max 3 retries). |
| **5. `review`** | `change-review` | Audits diff for template-driven rendering (no hardcoded per-kind forms), zero secret fields, and `SPP` branding only. |
| **6. `approval`** | Human Gate | Architect (`Manoj`) and Approvers (`Dwayne`, `Norm`) review and approve PR. |
| **7. `merge`** | `control-plane` | Merges PR to `ssp-ui` `main`. |
| **8. `reconcile`** | `drift-and-reconciliation`, `standards-feedback` | Verifies deployed UI in `spp-platform` on the SPP GKE cluster. |
