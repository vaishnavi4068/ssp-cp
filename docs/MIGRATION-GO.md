# Python → Go control plane migration

This branch (`cursor/go-control-plane-b7b7`) implements the **idp** intake and approval plane in Go while keeping the OpenAPI **`/v1`** scaffold (501 stubs) for SSP orders/tenants.

## What moved

| Concern | Location |
|--------|----------|
| Gate 1 intake (GCS + Spanner stack) | `internal/idp/intake` |
| Gate 2 approvals | `internal/idp/approval` |
| HTTP (`/api/v1/*`) | `internal/idp/http` |
| OPA bundles | `policy/idp/` |
| In-memory state (interim) | `internal/idp/store` |

## Environment

| Variable | Purpose |
|----------|---------|
| `SSP_OPA_SKIP=true` | Skip OPA in dev/tests |
| `SSP_POLICY_DIR` | Rego root (default `policy/idp`) |
| `SSP_OPA_URL` | Optional OPA HTTP server |
| `SSP_TEMPORAL_ENABLED=true` | Log real Temporal dispatch (wire-up pending) |
| `SSP_DEFAULT_KMS_KEY` | KMS placeholder on approved GCS docs |

## API parity (subset)

- `POST /api/v1/submissions` — `gcs_bucket` create
- `POST /api/v1/submissions/spanner-stack` — WI-007 composite
- `GET /api/v1/requests/{id}`
- `POST /api/v1/approvals/{id}/decisions`
- `GET /api/v1/kinds`

Auth, audit, freeze, and Postgres (`idp` schema) from Python **are not ported yet**; use header `X-SSP-User` for actor email in dev.

## Next steps before company export

1. sqlc + pgx against `idp` schema (or align goose migrations).
2. Port remaining `/api/v1` routes and JWT auth.
3. Connect `approval.Service` to Go Temporal worker (`cmd/worker`).
4. Deprecate Python `origin/main` FastAPI once parity tests pass.
