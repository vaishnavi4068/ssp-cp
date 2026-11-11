# Python → Go control plane (full migration tracker)

Branch `cursor/full-go-parity-b7b7` closes remaining gaps vs the retired FastAPI idp plane.

## Run

```bash
# migrations (idp + ssp schemas)
SSP_DATABASE_URL=postgres://postgres:postgres@localhost:5432/spp_platform go run ./cmd/migrate up

# API (Postgres when DATABASE_URL / SSP_DATABASE_URL set; else in-memory)
SSP_OPA_SKIP=true SSP_AUTH_DISABLED=true go run ./cmd/api   # dev without cookies
# or login via POST /api/v1/auth/login (bootstrap users in idp.cp_user seed / memory store)
```

## Parity matrix

| Area | Python | Go status |
|------|--------|-----------|
| idp DDL + seeds | `db/spp_state_model.sql` | `db/migrations/0002_idp_state_model.sql` |
| sqlc / pgx store | SQLAlchemy | `internal/store/queries/idp_*.sql` + `internal/idp/store/postgres.go` |
| Intake GCS + Spanner stack | `submit_resource_request` / WI-007 | `internal/idp/intake` (+ idempotency key replay) |
| Approvals + dbaas skip | `record_approval_decision` | `internal/idp/approval` |
| Request detail shape | `get_request_detail` | `internal/idp/query/format.go` (policy_evaluations, lifecycle_tasks) |
| List requests/approvals/resources | `main.py` §3–5 | `internal/idp/http/query_handlers.go` (+ observed/drift on resource GET) |
| State unit freeze | `main.py` §6 | `query_handlers.go` |
| Temporal dispatch | `TemporalBridge` | `internal/idp/temporal` (`SSP_TEMPORAL_ENABLED=true`) |
| Local auth (ADR-GLB-005) | `app/auth.py` | `internal/idp/localauth` + session cookies, CSRF, lockout |
| Audit aggregate | `GET /api/v1/audit` | `Backend.ListAudit` + `GET /api/v1/audit` |
| Policy evaluation rows | `opa_client.evaluate_and_record` | `internal/idp/opa/record.go` → `idp.policy_evaluation` |
| Lifecycle tasks | materialized on intake | `RecordLifecycleTask` on intake + sqlc reads on request detail |
| Gate events | intake / approve | `RecordGateEvent` on intake + approval |
| `/readyz` DB check | Alembic + `resource_kind` probe | `PingResourceKind` in `internal/api/server.go` |
| Kinds registry fields | full DB row | `FormatKindRow` + Postgres `ListResourceKinds` |
| Retire FastAPI | `app/` on `main` | **Removed** — use Go only |

## Tests

```bash
SSP_OPA_SKIP=true SSP_AUTH_DISABLED=true go test ./...
opa test policy/idp
```

## Workers

`GcsBucketProvisionWorkflow` runs in **ssp-workers** (Go worker on `spp-gcs-provisioning`). Go **ssp-cp** starts the workflow; it does not register provision workflows in `cmd/worker`.
