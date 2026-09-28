# ADR 0004: Local and CI checks share isolated Compose commands

## Status

Accepted.

## Context

Checks must be reproducible in Linux CI and locally without touching developer data. Separate CI-only implementations drift, while shared default credentials or volumes can contaminate development state.

## Decision

Use `compose.checks.yaml` with check-only credentials and named volumes. The shared `scripts/quality/run.sh` orchestrates Python, frontend, contract, migration, build, security, and Playwright checks; GitHub Actions invokes that same script. Scanner and browser tools run in pinned containers, while the host only orchestrates Docker.

## Consequences

Every category propagates failure, including unavailable scanners and controlled failures. The contracts category generates and checks the shipped REST/OpenAPI and GraphQL schema/operation artifacts. WebSocket is explicitly not applicable because this foundation has no WebSocket feature. A unique `COMPOSE_PROJECT_NAME` keeps check data separate from development data. This implements architecture decisions A8, A9, and A12 and requirements R6, R7, R9, and N4.
