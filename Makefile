.PHONY: generate lint test itest build bundle-policy

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

test:
	go test ./...
	$(OPA) test policy/platform

itest:
	go test ./test/integration/...

build:
	docker build -t ssp-cp:dev .

bundle-policy:
	go run ./cmd/policyctl build
