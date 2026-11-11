# Python → Go control plane (full migration tracker)

Branch `cursor/go-control-plane-b7b7` targets **same behavior** as FastAPI on `origin/main`.

## Run

```bash
# migrations (idp + ssp schemas)
SSP_DATABASE_URL=postgres://postgres:postgres@localhost:5432/spp_platform go run ./cmd/migrate up

# API (Postgres when DATABASE_URL / SSP_DATABASE_URL set; else in-memory)
SSP_OPA_SKIP=true go run ./cmd/api
```

## Parity matrix

| Area | Python | Go status |
|------|--------|-----------|
| idp DDL + seeds | `db/spp_state_model.sql` | `db/migrations/0002_idp_state_model.sql` |
| sqlc / pgx store | SQLAlchemy | `internal/store/queries/idp_*.sql` + `internal/idp/store/postgres.go` |
| Intake GCS + Spanner stack | `submit_resource_request` / WI-007 | `internal/idp/intake` |
| Approvals + dbaas skip | `record_approval_decision` | `internal/idp/approval` |
| Request detail shape | `get_request_detail` | `internal/idp/query/format.go` |
| List requests/approvals/resources | `main.py` §3–5 | `internal/idp/http/query_handlers.go` |
| State unit freeze | `main.py` §6 | `query_handlers.go` |
| Temporal dispatch | `TemporalBridge` | `internal/idp/temporal` (`SSP_TEMPORAL_ENABLED=true`) |
| Local auth (ADR-GLB-005) | `app/auth.py` | **Next:** `internal/idp/localauth` + cookies |
| Audit aggregate | `GET /api/v1/audit` | **Next:** gate_event + cp_audit_log queries |
| Policy evaluation rows | `opa_client.evaluate_and_record` | **Next:** insert `idp.policy_evaluation` |
| Lifecycle tasks | materialized on approve | **Next:** `idp.lifecycle_task` inserts |
| `/readyz` DB check | Alembic + `resource_kind` probe | **Next:** wire in `internal/api/server.go` |
| Retire FastAPI | `app/` on `main` | **Removed** — Python `app/`, Alembic, and pytest suites deleted; use Go only |

## Workers

`GcsBucketProvisionWorkflow` remains in **ssp-workers** (Python today). Go cp **starts** the workflow; it does not register that workflow in `cmd/worker` (same as Python cp).

## Export

After auth + audit parity tests pass against Postgres, merge this branch and remove Python `app/` from `main`.
