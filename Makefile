.PHONY: test test-opa test-py migrate lint

PROJECT_ID ?= microdrive-dev
REGION ?= us-east1
CLUSTER ?= md-dev
NAMESPACE ?= spp-platform
POLICY_NAMESPACE ?= spp-policy
REGISTRY ?= us-east1-docker.pkg.dev/$(PROJECT_ID)/spp
IMAGE_TAG ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo v1.0.0)

test: test-opa test-py

test-opa:
	opa test policy/ -v

test-py:
	PYTHONPATH=. pytest tests/ -v

migrate:
	PYTHONPATH=. python3 -m alembic upgrade head

lint:
	ruff check app/ tests/
