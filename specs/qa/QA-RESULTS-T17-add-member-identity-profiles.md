# T17 Quality and Recovery Results

**Date:** 2026-09-25  
**Environment:** isolated Docker Compose project `launchpad-final`  
**Data policy:** developer volumes were not reset or removed.

## Full quality gate

Command:

```sh
COMPOSE_PROJECT_NAME=launchpad-final sh scripts/quality/run.sh
```

Result: **PASS**

- Ruff format/lint: passed.
- mypy: passed for 74 source files.
- Python/integration tests: 132 passed.
- Prettier, ESLint, strict TypeScript: passed.
- Web tests: 37 passed.
- Migrations and REST/GraphQL contracts: passed.
- Python, web, and browser images: built successfully.
- Security scan: 0 vulnerabilities; source/image secret scans passed.
- Playwright browser checks: 2 passed.
- WebSocket: not applicable; no WebSocket feature exists.

## Failure and readiness drills

Command:

```sh
docker compose -p launchpad-final -f compose.checks.yaml run --rm integration \
  python -m pytest tests/integration/test_health_dependencies.py \
  tests/integration/test_environment_isolation.py \
  tests/integration/test_identity_mail.py -q
```

Result: **14 passed**. The targeted suite covers bounded missing-PostgreSQL failure,
Redis/storage readiness, stale/unexpected migration heads, SMTP failure with retry, and
environment isolation. The controlled failure propagation probe also behaved as designed:

```sh
LAUNCHPAD_QUALITY_ONLY=controlled-failure sh scripts/quality/run.sh
```

It exited nonzero and printed `controlled-failure`.

Preparation was rerun without resetting volumes, and the worker and scheduler both
reached `healthy` status. Browser connectivity and member-identity regression checks
passed as part of the full gate.

After the final forward migration that preserved valid HTTPS query-string links,
`tests/integration/test_database_preparation.py` and
`tests/integration/test_member_identity.py` passed together: **17 passed**.

## Isolation note

An initial attempt to allocate a fresh `launchpad-t17` project was rejected by Docker
because all predefined address pools were exhausted. No cleanup or destructive command
was used; the same checks were run successfully in the existing isolated
`launchpad-final` project.
