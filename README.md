# ssp-cp

Go control plane (`cmd/api`, `cmd/worker`). The **idp** intake path (`/api/v1/submissions`, approvals) is implemented under `internal/idp/`; OpenAPI **`/v1`** order APIs remain scaffold stubs until sqlc wiring lands.

See [docs/MIGRATION-GO.md](docs/MIGRATION-GO.md) for Python → Go status and env vars.
