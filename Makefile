.PHONY: generate lint test itest build bundle-policy test-opa

OAPI_CODEGEN ?= oapi-codegen
SQLC ?= sqlc
GOLANGCI_LINT ?= golangci-lint
GOVULNCHECK ?= govulncheck
GITLEAKS ?= gitleaks
OPA ?= opa

generate:
	$(OAPI_CODEGEN) -config oapi-codegen.yaml api/openapi.yaml
	$(SQLC) generate
	git diff --exit-code

lint:
	$(GOLANGCI_LINT) run
	$(GOVULNCHECK) ./...
	$(GITLEAKS) detect --no-git --source . --redact

test: test-opa
	SSP_OPA_SKIP=true go test ./...

test-opa:
	$(OPA) test policy/idp -v
	-$(OPA) test policy/platform

itest:
	go test ./test/integration/...

build:
	docker build -t ssp-cp:dev .

bundle-policy:
	go run ./cmd/policyctl build

migrate:
	go run ./cmd/migrate up
