# SSP application runtime stack (Go-first)

| Repo | Application runtime | Notes |
|------|---------------------|--------|
| **ssp-cp** | **Go** | API, idp `/api/v1`, sqlc, migrations, OpenAPI `/v1` stubs |
| **ssp-workers** | **Go** | Workflows + image CMD; cluster activities via Python bridge until native port |
| **ssp-ui** | **Go** portal server + **TypeScript** SPA | `cmd/portal` serves the Vite build; browser UI stays React/TS |
| **ssp-module-*** | **Terraform + Rego** | No application runtime (IaC/policy only) |
| **ssp-doc** | Markdown / JSON Schema | Specs only |

Python is not used for **ssp-cp**. **ssp-workers** retires `python -m workers.main`; remaining Python is activity implementation behind the Go worker process.
