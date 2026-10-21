# ssp-cp — SPP Control Plane Core (`WI-001`) & OPA Policy Gates (`WI-003`)

Python FastAPI Control Plane API (`ssp-cp`) and Open Policy Agent (`OPA`) policy gate bundle for the **Self-Service Provisioning Platform (SPP)** on **Google Cloud Platform (GCP)** (`us-east1`).

## Implemented Scope (`WI-001` & `WI-003`, GCS Bucket Feature)

1. **FastAPI Control Plane Service (`app/`):**
   - `POST /api/v1/requests` (and `POST /api/v1/submissions`): Synchronous intake normalization (`APM12345 -> apm12345` via `^APM\d{5}$` case-insensitive, `restrict -> restricted`, `sandbox|dev|qa|test|pdev|pqa|preprod -> nonprod`, `lifecycle_rules` default `[]`), idempotency deduplication on `(apm_id, idempotency_key)`, OPA evaluation at `stage = 'requested'`, and persistence to `idp.submission`, `idp.request`, `idp.policy_evaluation`, `idp.approval`, `idp.approval_decision`, and `idp.gate_event`.
   - `GET /api/v1/requests` & `GET /api/v1/requests/{request_id}`: Full four-gate inspection (`requested`, `approved`, `guardrail_trace`, `decisions`, `lifecycle_tasks`, `policy_evaluations`).
   - `GET /api/v1/approvals`, `GET /api/v1/approvals/{approval_id}`, & `POST /api/v1/approvals/{approval_id}/decisions` (also `/api/v1/requests/{id}/approve`): Role-based sequential approvals (`gcs_bucket_owner` v1 per `ADR-BP-003`), strict `self_approval = "deny"`, universal human approval requirement for all deletes in `nonprod` and `prod` (`AUTO_APPROVED` / `auto_approved` forbidden on `action = 'delete'`), OPA evaluation at `stage = 'approved'` applying the 10-entry `guardrail_trace`, and starting the Temporal workflow **`GcsBucketProvisionWorkflow`** on the platform Temporal server (`temporal-frontend.spp-temporal.svc.cluster.local:7233`, namespace `platform`).
   - `GET /api/v1/resources`, `GET /api/v1/status`, & `GET /api/v1/resources/{resource_id}`: Resource status read model backed by `idp.v_resource_status`, `idp.resource_observed`, and `idp.drift_finding`.
   - `GET /api/v1/audit`: Append-only `idp.gate_event`, `idp.cp_audit_log`, and `idp.policy_evaluation` records.
   - `POST /api/v1/state-units/{state_unit_id}/freeze` & `/unfreeze`: Per-project kill switch (`INV-9`).
   - Local Argon2id authentication (`/api/v1/auth/login`, `/api/v1/auth/change-password`, `/api/v1/auth/logout`, `/api/v1/auth/users/{username}/unlock`, `/api/v1/me`) matching the factory console (`ADR-GLB-005`), plus CORS for `ssp-ui`.

2. **AlloyDB for PostgreSQL Schema & Migrations (`db/`):**
   - Alembic migration (`db/migrations/versions/0001_initial_idp_state_model.py`) from `db/spp_state_model.sql` (`specs/data-model/spp_state_model.sql`): all 18 `idp` tables, `idp.v_resource_status` view, `idp.k8s_job_name(operation_id, phase)` function, immutability triggers (`request_guard`, `approval_guard`, `expected_revision_guard`, `gate_event_guard`), secret-rejection `CHECK` constraints, and seed rows.
   - Configured for AlloyDB (`cluster: spp-alloydb`, `instance: spp-alloydb-primary`, private IP `10.80.140.2:5432`, database `spp_platform`, user `postgres`, `sslmode=require`, password from Secret Manager secret `spp-alloydb-postgres-password`), while also supporting a plain `DATABASE_URL` for local/CI tests.

3. **OPA Rego Policies & Manifests (`policy/`, `deploy/k8s/opa-deployment.yaml`):**
   - Clean-slate Rego (`import rego.v1`) packages `idp.common`, `idp.naming`, `idp.labels`, and `idp.gcp.gcs_bucket`:
     - Naming rules (`GCS-NAME-001..003`, `NAM-APM-001` `^APM\d{5}$`, `NAM-RSV-001`, `NAM-IMM-001`, `NAM-LEG-001`, `SPN-NAME-001..002`).
     - 8 mandatory labels (`sppappid`, `costcenter`, `environmenttype`, `primarylob`, `datasensitivity`, `owner`, `provisionedby`, `idp_resource_id`) with `environmentsubtype` dropped/forbidden and `environmenttype` restricted to `nonprod` | `prod` (`LBL-001`, `LBL-002`).
     - GCS guardrails (`GCS-UBLA-001`, `GCS-PAP-001`, `GCS-ENC-001` using CMEK key `projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek`, `GCS-RET-001`, `GCS-RET-003`, `GCS-SDP-001`, `GCS-DEL-001`, `PRQ-001..002`, `us-east1` only, lifecycle default `[]`).
   - Standalone plain OPA server `Deployment` manifest in namespace `spp-policy` (`deploy/k8s/opa-deployment.yaml` and Helm template `deploy/helm/spp-cp/templates/opa.yaml`) with internal-only ClusterIP `Service` (`:8181`) and `NetworkPolicy`.

4. **Build & Deployment (`Dockerfile`, `cloudbuild.yaml`, `deploy/helm/spp-cp/`):**
   - `cloudbuild.yaml` builds and pushes `us-east1-docker.pkg.dev/microdrive-dev/spp/spp-cp:<sha>`.
   - Helm chart `deploy/helm/spp-cp` targets namespace `spp-platform` (internal only, scheduled on `spp-pool` with `nodeSelector: workload=spp` and toleration `dedicated=spp:NoSchedule`).

## Running Tests Locally

```bash
make test
```
