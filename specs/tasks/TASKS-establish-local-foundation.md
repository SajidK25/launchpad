# Tasks

> **Date:** 2026-09-19
> **Phase:** 3 of 5 (Task Generation)
> **Architecture source:** specs/architecture/ARCH-establish-local-foundation.md
> **Requirements source:** specs/requirements/REQ-establish-local-foundation.md

All 13 task scopes, verification plans and the dependency order were confirmed by the developer. This is greenfield work: there are no pre-existing runtime contracts to regression-test. Every task nevertheless guards the medium/high-risk behavior it introduces and preserves the existing source documents.

Execute one task at a time in the approved order. Each task must produce mode-appropriate evidence before completion and remain suitable for one conventional commit. TDD tasks require recorded RED → GREEN → REFACTOR evidence; test-after tasks assert each increment before completion; UI tasks require recorded human verification. Never substitute this document for execution evidence.

**Verification command convention:** run Python commands through `docker compose -f compose.checks.yaml run --rm python-checks …`, integration commands through that file's `integration` service, and JavaScript commands through `web-checks`. T1 supplies the first tool service; T2 supplies isolated infrastructure/fixtures; later tasks extend only the services they need. T12 consolidates existing checks rather than postponing all verification until CI exists. Use explicit unique project identities and disposable credentials for integration runs. Configure services so missing prerequisites fail visibly rather than silently using development resources.

For every test-plan task, run the listed test files through the applicable container runner and complete the affected lint/format/type checks. File/module and package markers necessary for importability are allowed within the listed new directories; no unrelated architecture or feature work is authorized. Lockfile changes belong to the task adding the dependency, and are verified by locked installation.

**Protected context:** `AGENTS.md`, `CLAUDE.md`, all three files under `docs/source/`, the linked REQ and the linked ARCH must remain unchanged. The ARCH Tasks header already names this file correctly. Compare protected-file content against a pre-task snapshot, including when files are untracked. Documentation is protected context, not an existing runtime API; do not invent behavioral tests solely to test Markdown.

**Global exclusions:** no product/account features, domain jobs, R2 provisioning, staging/production deployment, speculative GraphQL/WebSocket interfaces, telemetry collectors/dashboards, generated imagery, production load testing or non-Linux support claims. All tasks inherit these exclusions in addition to their own scope limits.

**Files shared across tasks:** “Modified files” below means files introduced by earlier tasks in this same approved new footprint, not edits to an existing application. Shared Compose, dependency and fixture files may change only for the named task's responsibility. Scaffolding/configuration and generated artifacts can exceed the usual 2–4 production-file target; they remain bounded by the approved 13-task split.

---

## Task T1: Establish the Python container toolchain

> **Status:** done
> **Verification:** checklist
> **Effort:** m
> **Priority:** high
> **Depends on:** None
> **Satisfies REQs:** R1, R6, N1, N3, N4
> **Footprint slice:** Python manifest/lockfile, Python image, exclusions, minimal Compose check service
> **High-risk areas touched:** Developer environment (M); build reproducibility and configuration exposure (M)

### Description

Create the container-only Python execution baseline for every later task. Provide locked dependencies and runnable quality tools without adding application startup or product behavior.

### Verification Checklist

- [ ] **Build** — `docker compose -f compose.checks.yaml build python-checks` on Linux; expected: image builds without host Python; required package files are present (R1, R6, N3).
- [ ] **Reproducible install** — repeat the locked image build and compare the dependency lockfile before/after; expected: installation consumes the lock unchanged; base image has an exact pin, not a floating tag (N4).
- [ ] **Tool availability** — run `python -m ruff --version`, `python -m mypy --version`, and `python -m pytest --version` through the python-checks service; expected: all return success and tool versions (R6).
- [ ] **Baseline checks** — run `python -m ruff check .`, `python -m ruff format --check .`, and the configured mypy command through python-checks; expected: introduced files pass; no collected pytest tests is explicitly reported and never converted into passing-test evidence (R6, R7).
- [ ] **Build exclusion** — build with a disposable local secret-marker file and inspect the resulting image from a container; expected: marker is absent while application package files remain present; remove only the disposable marker afterward (N1).
- [ ] **Source preservation** — compare the protected source documents against their pre-task hashes; expected: instructions, source guidance, REQ and ARCH are unchanged (N3).

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** Python packaging and container tooling; Ruff, mypy, pytest, and the approved backend libraries. **Decisions:** A1, A9, A12. Keep T1 independently executable: its minimal Compose tool service precedes the infrastructure added in T2. A package marker and exclusion files are scaffold overhead, not separate feature logic. Resolve supported releases and pin them; do not claim version-only invocations validate application behavior.
- **High-risk callouts:** Developer environment (M); build reproducibility and configuration exposure (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not add database preparation, readiness endpoints, business modules, or host-runtime requirements.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `pyproject.toml` — Python packaging, typed-tool configuration and dependencies.
- `requirements.lock` — exact Python dependency resolution.
- `infra/docker/python.Dockerfile` — pinned Python application/check image.
- `.dockerignore` — exclude local secrets and unnecessary build content.
- `.gitignore` — exclude local credentials, caches and generated runtime evidence.
- `compose.checks.yaml` — initial python-checks service only.
- `apps/api/app/__init__.py` — minimal importable package marker.

**Modified files:**

- None.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T2: Isolate development and integration infrastructure

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T1
> **Satisfies REQs:** R1, R6, R7, R8, R9, N1, N3, N4
> **Footprint slice:** Development Compose dependencies; isolated check Compose services; cross-service fixtures
> **High-risk areas touched:** CI/check resource isolation (H); developer environment (M); persistence/privacy (H)

### Description

Provide real PostgreSQL, Redis and MinIO for local development and independently named check environments. Verify that concurrent checks and their cleanup cannot affect development data.

### Test Plan

#### Test File(s)

- `tests/integration/test_environment_isolation.py`
- `tests/conftest.py`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Service availability** — GIVEN fresh disposable services, WHEN containerized clients connect to PostgreSQL, Redis and MinIO, THEN connections succeed without external accounts; required dependency absence fails rather than skips. _(verifies R1, R6, R7, N3)_
- **Environment isolation** — GIVEN development and check environments with separate credentials/volumes, WHEN check credentials attempt to use development resources, THEN access is denied and configuration references no development volume. _(verifies R6, R9, N4; isolation risk guard)_
- **Concurrent projects** — GIVEN two unique check project identities, WHEN both start and write distinguishable fixture data, THEN no host-port, volume, credential or resource-name collisions occur. _(verifies R6, N4; ARCH concurrency stress)_
- **Safe cleanup** — GIVEN development and two check projects containing sentinel data, WHEN one check project is removed, THEN development and the other check project retain their records and objects. _(verifies R9; high-risk cleanup guard)_
- **Development persistence** — GIVEN fixture records and sample objects in a disposable instance of the development definition, WHEN ordinary stop/start recreates containers without removing volumes, THEN the records and objects remain unchanged. _(verifies R9; REQ restart edge case)_
- **Visible failure** — GIVEN one required dependency unavailable, WHEN a dependent integration check executes, THEN verification is nonzero, identifies the dependency and exposes no credential. _(verifies R7, N1; dependency-failure edge case)_
- **Network boundary** — GIVEN rendered development Compose configuration, WHEN published ports are inspected, THEN PostgreSQL/Redis have none and every published development port is loopback-bound. _(verifies R1, N1, N3)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules:** Compose and cross-service fixtures. **Decisions:** A1, A8, A10, A12. Use real services and explicit per-project credentials; unique project names alone are not credential isolation. Fixture-created tables/buckets are test-only until T4/T5 supply preparation. No cleanup may target the developer's actual environment. Fixtures must fail if services are absent, never silently skip. The local mail catcher is infrastructure only and is not a readiness dependency. Do not give application containers the Docker socket; container orchestration can run through the host Docker CLI.
- **High-risk callouts:** CI/check resource isolation (H); developer environment (M); persistence/privacy (H). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not implement migration or private-bucket provisioning logic; do not introduce product tables. Exercise reset/persistence only on disposable environments.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `compose.yaml` — development dependencies, persistent volumes, loopback bindings and local mail catcher.
- `tests/conftest.py` — explicit disposable environment fixtures.
- `tests/integration/test_environment_isolation.py` — service, persistence and cleanup assertions.

**Modified files:**

- `compose.checks.yaml` — isolated infrastructure services and integration runner; do not inherit development volumes.
- `requirements.lock and pyproject.toml` — only fixture/runtime dependencies needed by this task.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T3: Validate configuration and sanitize structured diagnostics

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T1
> **Satisfies REQs:** R4, R10, N1, N3
> **Footprint slice:** Shared configuration, local settings example and shared observability
> **High-risk areas touched:** Configuration/logging exposure (M); infrastructure privilege separation (M)

### Description

Establish validated local settings and reusable safe JSON diagnostics. Fail configuration before infrastructure work and preserve separate bootstrap/runtime credential boundaries.

### Test Plan

#### Test File(s)

- `apps/api/app/shared/config/tests/test_settings.py`
- `apps/api/app/shared/observability/tests/test_logging.py`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Local defaults** — GIVEN the documented local configuration, WHEN settings load, THEN no cloud account or external credential is required. _(verifies R4)_
- **Invalid values** — GIVEN a required value with no safe default is missing, empty or malformed, WHEN settings are validated, THEN validation fails before any infrastructure operation. _(verifies R4; REQ configuration edge case)_
- **Actionable configuration error** — GIVEN invalid secret-bearing configuration, WHEN validation fails, THEN the setting needing correction is identified but its value is absent. _(verifies R4, R10, N1)_
- **Structured correlation** — GIVEN a component operation inside request context, WHEN a diagnostic is emitted, THEN JSON contains severity, component, operation, outcome and the request ID; concurrent contexts do not leak IDs. _(verifies N1; observability risk guard)_
- **Secret protection** — GIVEN exception/configuration inputs containing recognizable secret, URL and object-content sentinels, WHEN failures are logged, THEN no credential, credential-bearing connection string or object body is exposed. _(verifies N1; disclosure risk guard)_
- **Credential separation** — GIVEN bootstrap credentials exist but required runtime credentials are invalid, WHEN runtime settings load, THEN they cannot silently fall back to administrative credentials. _(verifies R4, N1, N3)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** shared config and observability; Pydantic and JSON logging support. **Decisions:** A3, A6. Use complete annotations and typed settings. JSON log context should support T7 middleware without introducing HTTP assembly here. Redaction alone is not permission to dump settings or exception payloads. Inline field documentation and the local example satisfy this task's R10 contribution; full workflow documentation is T13.
- **High-risk callouts:** Configuration/logging exposure (M); infrastructure privilege separation (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not wire HTTP middleware, introduce a collector/dashboard, or implement account authentication.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `apps/api/app/shared/config/settings.py` — typed settings and local defaults.
- `.env.example` — documented local-only values and credential separation.
- `apps/api/app/shared/observability/logging.py` — JSON logging and request context support.
- `apps/api/app/shared/config/tests/test_settings.py` — settings contracts.
- `apps/api/app/shared/observability/tests/test_logging.py` — diagnostic contracts.

**Modified files:**

- `pyproject.toml and requirements.lock` — required configuration/logging dependencies only.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T4: Establish migrations and serialized database preparation

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T2, T3
> **Satisfies REQs:** R2, R3, R9, N1, N2, N3
> **Footprint slice:** Shared database access, Alembic configuration and baseline migration
> **High-risk areas touched:** Database preparation (H); schema compatibility (M)

### Description

Create async database lifecycle support, a valid baseline migration and the session-level preparation lock. Verify real PostgreSQL behavior for concurrent attempts, failure and safe retry.

### Test Plan

#### Test File(s)

- `tests/integration/test_database_preparation.py`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Fresh baseline** — GIVEN an empty disposable PostgreSQL database, WHEN baseline migration runs, THEN expected revision is established without product tables. _(verifies R2, N3)_
- **Repeat preservation** — GIVEN applied baseline and sentinel records in a test-only table, WHEN migration runs again, THEN revision and records are preserved. _(verifies R2, R9)_
- **Concurrent lock ownership** — GIVEN two independent sessions, WHEN both attempt preparation, THEN only one holds the stable advisory lock; the next rechecks applied state after acquisition. _(verifies R3; ARCH concurrency stress)_
- **Bounded wait** — GIVEN another session holds the lock, WHEN lock acquisition reaches its configured timeout, THEN failure is visible and no migration is applied by the waiting caller. _(verifies R3, N1)_
- **Crash and session loss** — GIVEN preparation owns a session lock, WHEN the session is terminated, THEN another attempt can acquire the released lock and the old attempt cannot reconnect and continue without ownership. _(verifies R3; ARCH crash stress)_
- **Transactional failure** — GIVEN a disposable failure-inducing migration, WHEN it fails after beginning schema changes, THEN partial schema changes and false completion revision are absent. _(verifies R2; REQ preparation-failure edge case)_
- **Revision compatibility** — GIVEN missing, older or unexpected newer revision state, WHEN compatibility is inspected, THEN incompatibility is reported without applying a downgrade. _(verifies N2, R9)_
- **Resource release** — GIVEN success and failure preparation paths, WHEN each finishes, THEN connections and locks are released so subsequent preparation can proceed. _(verifies R3, N3; resource-lifecycle risk guard)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** shared db and Alembic, SQLAlchemy async and PostgreSQL driver. **Decisions:** A2, A10. Lock ownership must survive migration commits on the controlled session and terminate on session loss. Use a stable documented key and a bounded acquisition deadline. Failure migrations and sentinel tables exist only in disposable verification fixtures; do not rewrite a shared migration or manufacture domain tables. Keep migration state inspection suitable for T7's bounded readiness probe.
- **High-risk callouts:** Database preparation (H); schema compatibility (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not run storage setup, implement the combined bootstrap command, or provide automatic downgrades.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `apps/api/app/shared/db/database.py` — async connection/session lifecycle, revision inspection and lock boundary.
- `apps/api/alembic.ini` — migration configuration.
- `apps/api/alembic/env.py` — controlled migration connection integration.
- `apps/api/alembic/versions/0001_foundation.py` — baseline without artificial product tables.
- `tests/integration/test_database_preparation.py` — PostgreSQL preparation verification.

**Modified files:**

- `tests/conftest.py` — database isolation/failure fixtures only.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T5: Prepare private MinIO storage and bounded access

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T2, T3
> **Satisfies REQs:** R8, R9, N1, N2, N3
> **Footprint slice:** Shared storage runtime client, local provisioning and storage integration checks
> **High-risk areas touched:** Object privacy and preservation (H); blocking I/O and credentials (M)

### Description

Provide private local bucket preparation and a portable application storage boundary. Establish safe repeated provisioning and bounded read-only probes without introducing product media APIs.

### Test Plan

#### Test File(s)

- `tests/integration/test_storage.py`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Fresh private bucket** — GIVEN empty local MinIO with local bootstrap credentials, WHEN provisioning executes, THEN required private bucket exists without cloud access. _(verifies R8)_
- **Repeat preserves contents** — GIVEN private bucket containing a sample object, WHEN preparation repeats, THEN bucket is reused and object bytes remain unchanged. _(verifies R8, R9)_
- **Anonymous denial** — GIVEN a sample object in prepared storage, WHEN an unsigned direct read is attempted, THEN object access is denied. _(verifies R8, N1)_
- **Unexpected public policy** — GIVEN a disposable bucket permits public access, WHEN preparation inspects it, THEN preparation fails with a safe corrective diagnostic without changing policy or deleting objects. _(verifies R8, N1; ARCH public-storage stress)_
- **Credential privileges** — GIVEN separate runtime and bootstrap identities, WHEN runtime access and bucket-administration operations are attempted, THEN required runtime access succeeds but bucket administration is denied. _(verifies N1, N3)_
- **Typed safe failures** — GIVEN unavailable storage, invalid credentials or access denial, WHEN storage operations run, THEN distinct internal failures omit credential and object sentinels. _(verifies N1; REQ dependency edge case)_
- **Read-only probe** — GIVEN prepared private storage, WHEN probe runs, THEN no object write, deletion or object enumeration occurs. _(verifies N2; storage preservation guard)_
- **Timeout and event-loop safety** — GIVEN a slow storage transport, WHEN a bounded probe executes while another coroutine makes progress, THEN operation times out within its budget without blocking the event loop or leaving unbounded work. _(verifies N2, N3)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** shared storage and selected pinned S3 client. **Decisions:** A3, A5, A6. Keep portable application operations separate from MinIO administration. Runtime permission must allow the approved read-only privacy assessment without permitting policy mutation; verify least privilege explicitly. Bound underlying transport timeouts as well as outer coroutine deadlines. Use real MinIO for privacy/persistence checks and controlled slow transport doubles for deterministic timing.
- **High-risk callouts:** Object privacy and preservation (H); blocking I/O and credentials (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not provision R2, create public buckets for application use, implement upload/download endpoints, or migrate frontend assets to object storage.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `apps/api/app/shared/storage/client.py` — bounded application access and read-only probe support.
- `apps/api/app/shared/storage/provision.py` — private local bucket preparation.
- `tests/integration/test_storage.py` — real MinIO verification.

**Modified files:**

- `tests/conftest.py` — disposable private/public bucket and credential fixtures.
- `pyproject.toml and requirements.lock` — pinned S3 client dependency.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T6: Orchestrate preparation and gated startup

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T4, T5
> **Satisfies REQs:** R1, R2, R3, R4, R8, R9, R10, N1, N2
> **Footprint slice:** Bootstrap command and Compose preparation/startup relationships
> **High-risk areas touched:** Database/storage partial completion (H); stale setup evidence and lifecycle (M)

### Description

Connect validated configuration, database serialization and private storage provisioning into the dedicated preparation command. Gate dependent startup on its successful completion and preserve successful work across failures.

### Test Plan

#### Test File(s)

- `tests/integration/test_bootstrap.py`
- `tests/integration/test_startup_order.py`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Automatic fresh preparation** — GIVEN fresh disposable services, WHEN the Compose startup path runs, THEN database/private storage preparation completes before dependent consumers start. _(verifies R1, R2, R8, N2)_
- **Failed preparation blocks startup** — GIVEN invalid required configuration or a failing preparation step, WHEN startup runs, THEN command is nonzero, consumers stay blocked and diagnostics are actionable and sanitized. _(verifies R4, R10, N1, N2)_
- **Partial completion retry** — GIVEN database migration succeeds but storage initialization fails, WHEN dependency is corrected and bootstrap retries, THEN committed schema and sentinel data remain while storage setup completes. _(verifies R2, R8, R9; ARCH partial-failure stress)_
- **Concurrent commands** — GIVEN two complete bootstrap commands, WHEN both start against the same database, THEN serialization covers the full database/storage sequence and the second rechecks actual state. _(verifies R3)_
- **Interrupted preparation** — GIVEN bootstrap holds the lock, WHEN it is terminated and then retried, THEN lock releases and retry completes without deleting records or objects. _(verifies R3, R9; ARCH crash stress)_
- **Changed preparation inputs** — GIVEN a previous successful preparation container and changed migration/configuration inputs, WHEN the startup/update workflow is invoked, THEN preparation reruns instead of trusting historical container completion. _(verifies R2, R10, N2)_
- **Ordinary restart** — GIVEN prepared state with sample data, WHEN services restart normally, THEN records/objects persist with no reset or automatic downgrade. _(verifies R9; persistence risk guard)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules:** bootstrap and Compose. **Decisions:** A2, A10. Keep the session lock throughout both phases; loss of ownership aborts work. Database and MinIO do not share a transaction, so retry inspects actual state. Document the explicit preparation rerun command in Compose usage comments now; T13 transfers the verified workflow into the guide. Use disposable gated consumers until T7/T8 add real processes; do not reference missing source files in a completed task.
- **High-risk callouts:** Database/storage partial completion (H); stale setup evidence and lifecycle (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not add business side effects, HTTP-triggered setup, automatic destructive recovery, or future application entry points merely to satisfy startup tests.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `apps/api/app/bootstrap.py` — dedicated preparation command.
- `tests/integration/test_bootstrap.py` — combined preparation/recovery assertions.
- `tests/integration/test_startup_order.py` — startup dependency assertions.

**Modified files:**

- `compose.yaml` — preparation service and gated consumer relationships as consumers become available.
- `compose.checks.yaml` — bootstrap and disposable consumer verification support.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T7: Implement bounded readiness and safe health contracts

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T6
> **Satisfies REQs:** R5, N1, N2, N3
> **Footprint slice:** Health feature, API assembly, dependency probes and request-log wiring
> **High-risk areas touched:** False readiness and stale contracts (M); resource leakage and secret disclosure (M)

### Description

Expose the approved liveness/readiness endpoints through thin FastAPI routes and typed schemas. Aggregate real dependency probes under a three-second deadline and return only safe public status.

### Test Plan

#### Test File(s)

- `apps/api/app/modules/health/tests/test_service.py`
- `apps/api/app/modules/health/tests/test_routes.py`
- `tests/integration/test_health_dependencies.py`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Independent liveness** — GIVEN an API process with an unavailable dependency, WHEN GET /api/v1/health/live executes, THEN 200 with exactly the alive status is returned. _(verifies R5, N2)_
- **All dependencies ready** — GIVEN database access, expected revision, Redis and private storage are valid, WHEN readiness runs, THEN 200 with ready status is returned only when all probes succeed. _(verifies R5, N2)_
- **Safe dependency failure** — GIVEN each probe in turn fails, including incompatible schema, WHEN readiness runs, THEN 503 with only unavailable status is returned, without internal detail. _(verifies R5, N1, N2)_
- **Concurrent bounded deadline** — GIVEN probes including a stalled transport, WHEN readiness executes, THEN probes overlap, the three-second overall deadline is enforced and outstanding work/resources are cancelled/released. _(verifies N2; timing/resource guard)_
- **Fresh recovery** — GIVEN a dependency fails and later recovers, WHEN new readiness requests run, THEN status changes unavailable to ready without preparation or data reset. _(verifies R5; ARCH 30-second outage stress)_
- **HTTP contract** — GIVEN health routes without login, WHEN responses and exported schemas are examined, THEN documented codes/shapes match and Cache-Control is no-store. _(verifies R5, N3)_
- **Sanitized request logs** — GIVEN an identified request triggers a dependency exception containing secret sentinels, WHEN HTTP handling completes, THEN logs retain request ID and safe category while response/logs omit credentials and object contents. _(verifies N1)_
- **Read-only scope** — GIVEN prepared dependencies and stopped workers, WHEN readiness runs with operation recording, THEN no migrations, bucket creation, object writes/enumeration or product scans occur and worker health is not aggregated. _(verifies N2, N3; future table-growth guard)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** health feature and FastAPI assembly; Pydantic, async infrastructure adapters. **Decisions:** A4–A7. Write failing service/HTTP assertions first, then adapters and real-service verification. Keep the public status schema separate from diagnostic probe details. No cached success. Use deterministic clock/transport controls for deadline contracts and integration evidence for genuine disconnections. The five small production files separate the already approved service/probe/transport boundaries; do not broaden the feature. No 10-million-row load fixture is needed: verify that health performs metadata work only.
- **High-risk callouts:** False readiness and stale contracts (M); resource leakage and secret disclosure (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not add auth flows, GraphQL/WebSocket surfaces, domain repositories, cached readiness success, or any preparation side effect to a request.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `apps/api/app/main.py` — resource lifecycle, health routing and request context.
- `apps/api/app/modules/health/routes.py` — thin HTTP mapping.
- `apps/api/app/modules/health/schemas.py` — public and internal typed results.
- `apps/api/app/modules/health/service.py` — concurrent bounded readiness aggregation.
- `apps/api/app/modules/health/probes.py` — database, Redis and storage adapters.
- `apps/api/app/modules/health/tests/test_service.py` — service contracts.
- `apps/api/app/modules/health/tests/test_routes.py` — HTTP contracts.
- `tests/integration/test_health_dependencies.py` — real dependency failure/recovery.

**Modified files:**

- `compose.yaml and compose.checks.yaml` — API service, readiness/liveness checks and prepared startup gate.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T8: Run independently healthy worker and scheduler processes

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T6, T7
> **Satisfies REQs:** R1, R6, R7, N1, N3
> **Footprint slice:** Worker/scheduler entry points, progress health and Compose process wiring
> **High-risk areas touched:** Background stalls and misleading process health (M)

### Description

Establish separate Dramatiq worker and scheduler processes without adding product jobs. Make health depend on loop progress and required connections rather than process existence alone.

### Test Plan

#### Test File(s)

- `tests/integration/test_background_processes.py`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Separate gated startup** — GIVEN prepared environment, WHEN background services start, THEN distinct worker and scheduler processes run only after preparation succeeds. _(verifies R1, N3)_
- **Healthy loop progress** — GIVEN each process starting normally, WHEN its health check executes, THEN success occurs only with fresh loop progress and required connections. _(verifies R6, R7)_
- **Stalled live process** — GIVEN a live process whose actual work loop stops progressing, WHEN freshness expires, THEN health fails even though the process still exists. _(verifies R7; ARCH background stress)_
- **Required connection loss** — GIVEN a running process, WHEN its required dependency fails, THEN health becomes unsuccessful and diagnostics omit secrets. _(verifies R7, N1)_
- **Recovery** — GIVEN failed connection or stopped progress is restored, WHEN the process resumes progressing, THEN health recovers without mutation of persisted application data. _(verifies R1, N3)_
- **Independent API readiness** — GIVEN healthy API dependencies, WHEN worker or scheduler is stopped, THEN API readiness remains ready. _(verifies N3; health-boundary guard)_
- **No product side effects** — GIVEN empty broker and prepared database, WHEN both processes start, THEN no product jobs, business schedules or domain events are created. _(verifies N3; scope guard)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** worker/scheduler, Dramatiq and Redis. **Decisions:** A1, A4. Heartbeats must be driven by the monitored loop, not a separate always-running timer that masks a stall. Keep freshness limits explicit in configuration/check documentation. Share the Python image; no new service architecture or business actor is justified here.
- **High-risk callouts:** Background stalls and misleading process health (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not invent notification jobs, outbox tables, business schedules, or API aggregation of background health.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `apps/worker/worker.py` — worker entry point.
- `apps/worker/scheduler.py` — scheduler entry point without business schedules.
- `apps/worker/health.py` — bounded local progress/connection health.
- `tests/integration/test_background_processes.py` — process health and isolation.

**Modified files:**

- `compose.yaml and compose.checks.yaml` — separate services gated on preparation with independent checks.
- `pyproject.toml and requirements.lock` — approved background dependencies only.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T9: Build the web toolchain and generated REST contracts

> **Status:** not started
> **Verification:** checklist
> **Effort:** m
> **Priority:** high
> **Depends on:** T7
> **Satisfies REQs:** R1, R5, R6, R7, N1, N3, N4
> **Footprint slice:** Frontend workspace/tooling, web image and proxy, OpenAPI/TypeScript artifacts
> **High-risk areas touched:** Contract drift (M); build reproducibility and frontend secret exposure (M)

### Description

Provide a containerized strict-TypeScript frontend build and reproducible OpenAPI type generation. Serve compiled assets independently of API/storage availability while proxying relative health requests.

### Verification Checklist

- [ ] **Container build** — `docker compose -f compose.checks.yaml build web-checks` and the development web image build; expected: locked installation and compiled production build succeed without host Node (R1, R6, N3).
- [ ] **Frontend tools** — run the workspace lint, format-check, typecheck and test commands through web-checks; expected: ESLint/Prettier/strict TypeScript succeed; Vitest runs and absent tests are explicitly non-passing evidence (R6, R7).
- [ ] **Stable generation** — run the documented containerized OpenAPI export and TypeScript generation twice; expected: generated artifacts are identical and types describe T7 responses (R6, N4).
- [ ] **Drift detection** — alter a disposable generated artifact, run the contracts check, then regenerate it; expected: drift produces nonzero; regeneration restores a clean result without hand-maintained response types (R6, R7).
- [ ] **Independent assets** — request the compiled frontend with API and MinIO unavailable; expected: HTML/assets remain served from the web container (R5).
- [ ] **Proxy behavior** — request relative health URLs with the backend available, then unavailable; expected: requests reach the API when healthy and backend failure is not rewritten as successful SPA HTML (R5).
- [ ] **Bundle safety** — build with recognizable infrastructure credential sentinels in server-only settings and inspect the served bundle; expected: no credential/admin configuration appears in browser assets (N1).

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** web tooling, contracts and proxy; React, Vite, Tailwind, TypeScript, ESLint, Prettier, Vitest. **Decisions:** A3, A7, A9, A12. Choose and pin an OpenAPI-to-TypeScript generator compatible with the exported schema. Boilerplate config files are explicit footprint overhead; this task adds no connectivity state logic. A shell page is enough to verify compiled-asset serving. Generator execution stays containerized; its script may orchestrate containers via Docker CLI.
- **High-risk callouts:** Contract drift (M); build reproducibility and frontend secret exposure (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not implement T10 request/state logic, T11 status styling, GraphQL/WebSocket generation, R2 hosting, or browser-visible server credentials.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `package.json and package-lock.json` — locked JavaScript workspace/tooling.
- `apps/web/package.json, apps/web/tsconfig.json, apps/web/vite.config.ts` — frontend build and strict typing.
- `apps/web/eslint.config.js and apps/web/.prettierrc.json` — frontend quality configuration.
- `apps/web/index.html and apps/web/src/main.tsx` — minimal mountable shell, not connectivity presentation.
- `infra/docker/web.Dockerfile and infra/docker/web.conf` — compiled-asset runtime and API proxy.
- `packages/contracts/package.json, packages/contracts/openapi.json, packages/contracts/src/generated.ts` — generated schema/types and generator command.
- `scripts/quality/contracts.sh` — schema export/regeneration drift command.

**Modified files:**

- `compose.yaml and compose.checks.yaml` — independently started web runtime and web-checks tool service.
- `.dockerignore and .gitignore` — frontend dependency/build cache exclusions only.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T10: Implement typed browser connectivity state

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T9
> **Satisfies REQs:** R5, N2, N3
> **Footprint slice:** Web readiness client and TanStack Query state boundary
> **High-risk areas touched:** False success, stale state and unbounded requests (M)

### Description

Implement connectivity fetching and state transitions separately from the visual page. Consume generated REST types and ensure only a fresh valid readiness response can produce connected state.

### Test Plan

#### Test File(s)

- `apps/web/src/connectivity/connectivity.test.tsx`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Initial state** — GIVEN an unresolved initial request, WHEN connectivity is observed, THEN state never reports connected before successful evaluation. _(verifies R5, N2)_
- **Valid ready response** — GIVEN HTTP 200 with the expected ready body, WHEN request completes, THEN connected state is produced. _(verifies R5)_
- **Unavailable transport** — GIVEN 503, network error or failed proxy, WHEN request completes, THEN unavailable state is produced. _(verifies R5; REQ outage edge case)_
- **Malformed response** — GIVEN unexpected status value, invalid body or wrong success shape, WHEN response is interpreted, THEN it cannot produce connected state. _(verifies R5; ARCH malformed-response stress)_
- **Bounded timeout** — GIVEN an unresponsive request, WHEN the documented client deadline passes, THEN unavailable appears without indefinite retries; timeout budget allows the server three-second deadline. _(verifies N2)_
- **Fresh failure replaces success** — GIVEN a previous ready result, WHEN a fresh evaluation fails, THEN cached success cannot keep the displayed state connected. _(verifies R5, N2; stale-state guard)_
- **Recovery on refresh** — GIVEN previous unavailable state followed by healthy backend, WHEN page/query lifecycle refreshes, THEN a new request runs and connected state returns. _(verifies R5; REQ recovery edge case)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** typed client and TanStack Query; Vitest/component-test support. **Decisions:** A5, A7, A9. Generated types do not validate arbitrary runtime JSON; verify the minimal expected response shape without duplicating a handwritten API interface. Use deterministic fake timers and transport doubles. Select a finite client timeout greater than the server deadline, document it, and ensure retries do not extend it indefinitely.
- **High-risk callouts:** False success, stale state and unbounded requests (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not style the page, create new status requirements, add automatic polling, or hand-maintain REST response types.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `apps/web/src/connectivity/client.ts` — typed relative request with bounded timeout and response validation.
- `apps/web/src/connectivity/useConnectivity.ts` — TanStack Query state integration.
- `apps/web/src/connectivity/connectivity.test.tsx` — request/state contracts.

**Modified files:**

- `apps/web/package.json and package-lock.json` — TanStack Query and component-test dependencies.
- `apps/web/src/main.tsx` — query provider wiring only.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T11: Present an accessible connectivity page

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T10
> **Satisfies REQs:** R5, N2, N3
> **Footprint slice:** Web page, status presentation, styles and component seams
> **High-risk areas touched:** Incorrect state presentation and accessibility (M)

### Description

Present the approved loading, Connected and Unavailable states using the existing connectivity boundary. Provide an accessible minimal page that remains usable on mobile and desktop.

### Verification Checklist

- [ ] **Visible states** — drive pending, successful and failed connectivity states; expected: loading never implies success; success displays Connected and failure displays Unavailable (R5, N2).
- [ ] **Visible recovery** — make backend unavailable, restore it and refresh; expected: Unavailable changes to Connected after the fresh successful check (R5).
- [ ] **Responsive presentation** — inspect at 375px and 1280px widths; expected: text remains readable with no horizontal scrolling or clipped status (N3).
- [ ] **Accessible status** — inspect semantics, contrast and assistive-technology announcements; expected: status has text independent of color, meaningful structure and accessible updates (N3).
- [ ] **Keyboard operation** — navigate every interactive control by keyboard, if controls exist; expected: controls are usable with visible focus; record not applicable if the page has no controls (N3).
- [ ] **Human evidence** — capture loading, Connected and Unavailable screenshots and record viewport/check results; expected: human review is explicitly recorded; screenshots alone do not claim human approval (R5).
- [ ] **Component seams** — run `docker compose -f compose.checks.yaml run --rm web-checks npm run test --workspace apps/web`; expected: render/state/accessibility assertions pass without duplicating T10 transport tests (R5, N2).

#### Testable Seams

- `apps/web/src/App.test.tsx`: pending/connected/unavailable text and absence of false initial success.
- `apps/web/src/App.test.tsx`: semantic page structure and accessible status announcements; keyboard/focus checks for any implemented controls.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** web presentation, React and Tailwind. **Decisions:** A3, A7, A9; AGENTS frontend rules. Use the already approved minimal demonstration scope. docs/source/inspiration.md has been read; no external visual research or generated imagery is needed. Preserve client failure behavior from T10. Human verification must be obtained during implementation before marking this ui task done.
- **High-risk callouts:** Incorrect state presentation and accessibility (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not create a branded launch-platform homepage, add unrelated controls, generate images, or replace the request/state module.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `apps/web/src/App.tsx` — semantic connectivity page.
- `apps/web/src/styles.css` — responsive Tailwind-based presentation.
- `apps/web/src/App.test.tsx` — rendering and accessibility seams.

**Modified files:**

- `apps/web/src/main.tsx` — mount page and styles while preserving query provider.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T12: Consolidate quality gates and GitHub Actions

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T8, T11
> **Satisfies REQs:** R5, R6, R7, R9, N1, N4
> **Footprint slice:** Shared quality orchestration, scanner/browser images, isolated check wiring and CI
> **High-risk areas touched:** Check isolation and cleanup (H); false passes and secret-bearing evidence (M)

### Description

Connect the already runnable task-level checks into the complete local and GitHub Actions quality gate. Include containerized browser and security verification with reliable nonzero failure propagation and isolated resource cleanup.

### Test Plan

#### Test File(s)

- `tests/quality/test_gate_failures.py`
- `tests/integration/test_environment_isolation.py`
- `tests/browser/connectivity.spec.ts`

#### Test Scenarios

##### Behavior, Failure Handling and Risk Guards

- **Command parity** — GIVEN documented local orchestration and GitHub Actions workflow, WHEN both select verification commands, THEN the same Compose commands run instead of separate CI-only implementations. _(verifies R6, N4)_
- **Gate coverage** — GIVEN complete foundation implementation, WHEN the full gate runs, THEN format/lint/types/tests/migrations/contracts/scans/builds execute and deferred GraphQL/WebSocket gates are explicitly not applicable. _(verifies R6, R7)_
- **Failure propagation** — GIVEN a controlled failing category, WHEN the orchestrator runs, THEN overall result is nonzero and identifies the category, including failures behind output capture. _(verifies R7)_
- **Unavailable evidence** — GIVEN missing dependency, scanner execution error or unavailable vulnerability database, WHEN the relevant check runs, THEN no success or skipped-pass is reported. _(verifies R7; ARCH scanner-failure stress)_
- **Security findings** — GIVEN controlled secret/high-severity/lower-severity fixtures, WHEN scanner result handling executes, THEN secrets and high-severity findings block success while lower findings remain visible. _(verifies R7, N1)_
- **Safe parallel execution** — GIVEN development data and concurrent gate projects, WHEN one gate completes/fails and cleans up, THEN other check and development records/objects remain intact. _(verifies R9, N4; isolation risk guard)_
- **Browser lifecycle** — GIVEN real web/API/dependency services, WHEN containerized Playwright observes healthy, failed and recovered dependencies, THEN Connected, Unavailable and refreshed Connected appear with no host Node requirement. _(verifies R5, R6)_
- **Safe evidence** — GIVEN check failures including secret sentinels in internal inputs, WHEN CI captures diagnostics/artifacts, THEN useful results are retained without credentials or private object contents. _(verifies N1, N4)_

##### Regression Guard

This task has no brownfield runtime caller. Its preservation, privacy, failure and isolation assertions above guard the applicable ARCH medium/high-risk areas. Preserve protected context through content comparison; do not modify documentation to make an implementation fit.

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules/libraries:** orchestration, GitHub Actions, Playwright and pinned security scanners. **Decisions:** A8, A9, A12. Category scripts must preserve nonzero exits; do not mask failures with tee/log capture or allow-failure configuration. Use synthetic scanner outputs for deterministic propagation tests plus actual scanner invocation; do not commit real secrets or intentionally vulnerable application dependencies. Isolated projects need distinct credentials as well as names. Root-level orchestration uses host Docker CLI; all language tooling/scanners/browser drivers run in containers. No application-container Docker socket. Real hosted CI execution may depend on repository hosting availability: document the limitation rather than invent a successful GitHub run.
- **High-risk callouts:** Check isolation and cleanup (H); false passes and secret-bearing evidence (M). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not add deployment workflows, cloud credentials, speculative transports, production load tests or global Docker cleanup commands.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `scripts/quality/run.sh` — shared gate orchestration and category reporting.
- `scripts/quality/security.sh` — dependency/image/secret scan invocation.
- `infra/docker/quality.Dockerfile and infra/docker/browser.Dockerfile` — pinned scanner/browser tooling.
- `.github/workflows/quality.yml` — Linux CI invoking shared commands.
- `tests/quality/test_gate_failures.py` — orchestrator and scanner-outcome verification.
- `tests/browser/connectivity.spec.ts and tests/browser/playwright.config.ts` — running-surface browser checks.

**Modified files:**

- `compose.checks.yaml` — complete quality and browser services using isolated resources.
- `package.json and package-lock.json` — pinned Playwright/test scripts.
- `tests/integration/test_environment_isolation.py` — consolidated gate cleanup coverage.
- `scripts/quality/contracts.sh` — integrate existing drift command without changing contract ownership.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

## Task T13: Document and verify the complete development workflow

> **Status:** not started
> **Verification:** checklist
> **Effort:** m
> **Priority:** medium
> **Depends on:** T12
> **Satisfies REQs:** R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, N1, N2, N3, N4
> **Footprint slice:** README, Linux development guide and approved architectural decision records
> **High-risk areas touched:** Developer setup (M); destructive-reset instructions and recovery (H)

### Description

Write cold-readable setup, verification and recovery instructions using the commands validated in preceding tasks. Record confirmed architecture decisions and verify the documented end-to-end workflow on disposable Linux environments.

### Verification Checklist

- [ ] **Fresh setup** — execute the written Linux prerequisites/startup commands from a fresh disposable checkout; expected: automatic preparation completes and browser shows Connected without host Python/Node or cloud credentials (R1, R2, R4, R5, R8, R10, N3).
- [ ] **Documented checks** — run each documented verification command and compare the reported category list to T12; expected: commands work; passing, failing and not-applicable results are distinguished; no missing check is called passing (R6, R7, N4).
- [ ] **Failure recovery** — follow written guidance for missing configuration, unavailable services and interrupted/partial preparation; expected: diagnostics identify correction and safe retry; no secrets are revealed and recovery preserves state (R2, R3, R4, R10, N1, N2).
- [ ] **Preservation** — place sample records/files in a disposable development environment and execute documented stop/start; expected: records and files remain unchanged (R9).
- [ ] **Explicit reset** — execute the documented reset only against a deliberately named disposable environment; expected: documentation names data to be deleted and only selected environment volumes are cleared; other projects survive (R9, R10).
- [ ] **Application update** — follow the migration/configuration update and incompatible-revision recovery instructions; expected: preparation reruns as required and recovery never automatically downgrades or resets data (R2, R9, R10).
- [ ] **Decision traceability** — compare the four ADRs with the approved architecture decisions and requirement IDs; expected: preparation, health, storage and check isolation rationale/alternatives match the approved design (N3).
- [ ] **Scope and source guard** — review platform/provider claims and compare protected source-document hashes; expected: only Linux support is promised, R2 remains future infrastructure, and instructions/source/REQ/ARCH are unchanged (N3).

### Implementation Notes

- **Pattern reference:** linked ARCH Change Footprint, Module Boundaries and Patterns & Conventions; AGENTS.md and engineering guide. No pre-existing application pattern is available.
- **Modules:** documentation and ADRs. **Decisions:** A1–A12. Reuse earlier verified command output where it remains applicable, but execute the fresh documented workflow to detect omissions. Include exact Compose project/volume targeting and make reset visibly separate from startup/recovery. State local defaults are not production credentials. Existing files are untracked in this repository, so use pre-task hashes/content comparison, not git diff alone, to establish source preservation. Six documents are a single documentation deliverable, not new runtime logic.
- **High-risk callouts:** Developer setup (M); destructive-reset instructions and recovery (H). The verification plan above exercises these boundaries; do not declare done on successful startup alone.

### Scope Boundaries

- Do not change source instructions, requirements or architecture; promise non-Linux support; add staging deployment steps; or perform destructive verification against a developer environment.
- Follow the global exclusions and implement only this task's approved footprint.

### Files Expected

**New files:**

- `README.md` — entry point, prerequisites, startup and links.
- `docs/development.md` — full check/recovery/preservation/reset workflow.
- `docs/adr/0001-preparation-ownership.md` — serialization and partial-failure recovery rationale.
- `docs/adr/0002-health-contracts.md` — health scope, deadline and minimal responses.
- `docs/adr/0003-private-object-storage.md` — MinIO/R2 and frontend-asset separation.
- `docs/adr/0004-check-isolation.md` — local/CI parity and resource isolation.

**Modified files:**

- None.

**Must NOT modify:**

- `AGENTS.md`, `CLAUDE.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md` — protected source guidance.
- `specs/requirements/REQ-establish-local-foundation.md` and `specs/architecture/ARCH-establish-local-foundation.md` — read-only approved inputs.
- Unlisted feature modules or another task's behavior; shared-file changes must stay within the ownership specified above.

---

Next: invoke `$dev-pipeline:implement T1 from: specs/architecture/ARCH-establish-local-foundation.md`. After implementation, use plan-qa → execute-qa for the running browser/API/background surfaces alongside review.
