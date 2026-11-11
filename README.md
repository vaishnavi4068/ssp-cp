# ssp-cp — SPP Control Plane

Go control plane (`cmd/api`, `cmd/worker`, `cmd/migrate`). The **idp** four-gate API lives under `internal/idp/` at `/api/v1/*` (intake, approvals, resources, state-unit freeze). OpenAPI **`/v1`** order/tenant routes remain scaffold stubs until wired to `ssp` schema.

Policies: `policy/idp/` (GCS + Spanner). Database: goose `db/migrations` (`ssp` + `idp` schemas); use `SSP_DATABASE_URL` and `go run ./cmd/migrate up`.

See [docs/MIGRATION-GO.md](docs/MIGRATION-GO.md) for Python → Go parity and env vars.

## Tests

```bash
make test
```
