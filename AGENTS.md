# AGENTS.md — ssp-cp

This repository implements the SSP specification in `ssp-doc` (synced copy in `docs/specs/`, run `make sync-specs`). Read, in this order, before any change:

1. `docs/specs/00-constitution/` (principles, locked decisions, glossary, definition of done, tiers)
2. The spec files your task cites (`docs/specs/90-tasks/<task>.md` lists them)
3. `docs/specs/40-repos/<this repo>.md` for structure and binding notes

Rules of engagement are in `.cursor/rules/`. Summary: specs are the contract; locked decisions never move; tests first and cite requirement IDs; no secrets; generated code is regenerated; protected paths are off limits; no real-environment commands from the agent; after three failed gate iterations stop and report.

Make targets: `make generate lint test build` (see Makefile). PR title `[<task-id>] <summary>`; body lists spec IDs, tier, blast radius, test evidence.
