# Architecture: Establish Local Development Foundation

> **Date:** 2026-09-19
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** specs/requirements/REQ-establish-local-foundation.md
> **Tasks:** TASKS-establish-local-foundation.md
> **Type:** infrastructure

## Architecture Summary

Create the approved Launchpad monorepo with separate web, API, worker, and scheduler processes, operated locally through Docker Compose. A dedicated preparation process serializes database migration and private MinIO storage initialization before application processes start; ordinary restarts preserve persisted data. A minimal React page consumes a generated REST readiness contract and reports whether the API and required dependencies are usable. Local and GitHub Actions verification use the same containerized commands with isolated data, explicit failure reporting, and no host Python or Node requirement. Linux is the verified host platform for this slice; shared deployment and product features remain deferred.

## High-Level Structure

```text
Browser -> web container -> API health routes -> health service
                                              | PostgreSQL + migration state
                                              | Redis
                                              | private MinIO bucket

PostgreSQL / Redis / MinIO become healthy
                    |
             preparation process
          database lock + migrations
          private storage preparation
                    |
           API / worker / scheduler

Developer or GitHub Actions -> Compose check environment
                           -> isolated services, volumes, quality commands
```

The frontend starts independently of API preparation so startup failures can be displayed. The web container serves frontend assets and proxies relative API requests to the API service, giving the browser one local origin. PostgreSQL and Redis need no published host ports. Any published web or MinIO development ports bind to loopback.

The API, preparation process, worker, and scheduler share the Python domain package and configuration conventions. Worker and scheduler are separate entry points with independently observable process health, but this slice introduces no business jobs, schedules, or domain events. A local mail catcher follows the engineering guide; it is not a readiness dependency because no email feature exists yet.

All application paths are new. Existing instructions and source documents remain authoritative and unchanged.

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|------|----------|-------------------------|-----------|
| Backend | Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2 async, Alembic | Different frameworks or synchronous request persistence | Required stack; preserves the approved direction (N3). |
| Persistence | PostgreSQL; Redis for rebuildable supporting state and Dramatiq broker | SQLite integration environment; Redis as authority | Matches runtime semantics and project invariants (R1, R6, N3). |
| Frontend | React, strict TypeScript, Vite, Tailwind, TanStack Query | Handwritten server-state management | Required stack; generated contracts avoid duplicate API definitions (R5–R6, N3). |
| Process management | Docker Compose with health and successful-preparation dependencies | Setup inside every application process | Centralizes preparation and avoids concurrent migration ownership (R1–R3). |
| Object storage | Private MinIO locally; S3-compatible boundary targeting Cloudflare R2 later | Public local buckets; host filesystem objects | Confirmed providers and privacy requirements (R8–R9, N3). |
| Frontend assets | Web container | MinIO/R2 asset hosting | Confirmed separation keeps the verification page independent of storage availability (R5, R8). |
| Background runtime | Dramatiq worker plus separate scheduler entry point | Business actors added solely to demonstrate infrastructure | Preserves process boundaries without adding product behavior (R1, N3). |
| Python verification | Ruff lint/format, mypy, pytest | Multiple overlapping lint tools; host execution | Confirmed tooling and container-only workflow (R6–R7). |
| Frontend verification | ESLint, Prettier, TypeScript, Vitest; containerized Playwright | Manual-only browser verification | Confirmed checks cover code and the running browser surface (R5–R7). |
| Contracts | OpenAPI-generated TypeScript types; regeneration diff gate | Hand-maintained types; empty GraphQL/WebSocket interfaces | Only REST exists in this slice; other transports arrive with consuming features (R6, N3). |
| Automation | GitHub Actions invokes shared Compose quality commands | Separate CI implementations of checks | Confirmed provider and command parity (R6–R7, N4). |
| Diagnostics | JSON logs, request IDs, health diagnostics | Dedicated telemetry collector and dashboards now | Confirmed foundation observability boundary (N1–N2). |
| Reproducibility | Committed Python/JavaScript lockfiles and exact container image pins | Floating dependency/image tags | Repeatable local and automated verification (N4). |

Exact supported package releases and image digests must be resolved and committed during implementation rather than treated as floating defaults. Security scanner and contract-generator package selections must satisfy the interfaces and gates below; no vendor-specific behavior is required by this design.

Technical references checked during planning: [Compose startup conditions](https://docs.docker.com/compose/how-tos/startup-order/), [PostgreSQL advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS), and [R2 S3 compatibility](https://developers.cloudflare.com/r2/api/s3/api/). The storage boundary must use operations supported by both providers; local bucket administration is separate from portable application access.

## Patterns & Conventions

- **Modular monolith:** feature-owned transport, schemas, services, probes, and verification; routes delegate decisions to services. Follow AGENTS.md and the engineering guide.
- **Named boundaries:** health consumes shared connection/storage interfaces; it does not import future feature repositories.
- **Dedicated preparation:** setup is a command, not an HTTP side effect or a readiness probe. It validates configuration before mutation.
- **Safe repeated operations:** existing migration history and bucket state determine remaining work. An existing private bucket is reused; existing objects are never deleted by setup.
- **Fail visibly:** required checks, preparation, and configuration failures produce unsuccessful status and sanitized diagnostics.
- **Container-only verification:** language tools, contract generation, security scanners, and browser drivers run in containers. Docker/Compose orchestration uses the host Docker engine; it does not require installing language toolchains or exposing the Docker socket to application containers.
- **No speculative domain model:** no users, products, outbox, or authorization subsystem is introduced without the relevant feature. Preparation metadata is operational state, not user-visible business state.

## Data Models

### Database Migration State

**Purpose:** identify which version of the foundation schema has been applied.

| Field | Type / Constraint | Notes |
|-------|-------------------|-------|
| Alembic revision identifier | Required migration-managed string | The applied revision must match the application's expected migration head. |

**Relationships:** no product entities or foreign keys in this slice. Alembic owns its version table; the application does not maintain a competing migration ledger.

**Lifecycle:** absent on first use → established by preparation → advanced by forward-compatible migrations. Startup never automatically downgrades or recreates the database. The initial migration establishes a valid baseline without introducing artificial product tables.

### Private Object Storage

**Purpose:** persistent local application-object storage compatible with the future R2 boundary.

| Field | Type / Constraint | Notes |
|-------|-------------------|-------|
| Bucket name | Required validated configuration | Deterministic for the environment; check environments use independent storage. |
| Object key | Opaque string within bucket | No public object-listing or upload API in this slice. |
| Object contents | Private bytes | Preserved across ordinary restarts; never logged. |
| Access configuration | No anonymous object access | Provisioning verifies privacy without silently rewriting an existing public policy. |

**Relationships:** no database records reference objects yet.

**Lifecycle:** bucket absent → created privately → verified and reused. Contents persist until the developer deliberately invokes the documented reset operation. Application storage access uses limited credentials; bootstrap administration and application access are separate configuration concerns.

### Process Health State

**Purpose:** distinguish worker/scheduler loop progress from a merely existing process.

**Key fields:** process identity and last-progress timestamp, local to each container and not authoritative business data.

**Relationships:** none. No dependency on the API health endpoints.

**Lifecycle:** absent during startup → refreshed by the running process loop → stale on a stalled loop → discarded when the container is replaced. Container checks require recent progress and required connection availability; API readiness does not aggregate these checks.

## API Contracts / Interfaces

### Health HTTP API

**Boundary:** HTTP API, versioned under `/api/v1`.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|------------------|
| GET | `/api/v1/health/live` | Process responsiveness | `200`, `{"status":"alive"}`. |
| GET | `/api/v1/health/ready` | Dependency and preparation readiness | `200`, `{"status":"ready"}`; `503`, `{"status":"unavailable"}` on failed checks or timeout. |

**Auth requirements:** no login; responses contain no product data, dependency topology, credentials, or internal exceptions. Local exposure is loopback-only. Both responses use typed Pydantic schemas and `Cache-Control: no-store`.

Readiness runs concurrent bounded probes under a three-second total server deadline. It checks database connectivity and the expected migration revision, Redis access, and authenticated access to the prepared private bucket, including local privacy configuration. Readiness never applies migrations, creates buckets, scans product records, or writes probe objects. Probe cancellation and transport timeouts must release resources; blocking storage SDK work cannot execute on the request event loop.

### Health Service and Dependency Probes

**Boundary:** internal typed service interfaces.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|------------------|
| Evaluate | `HealthService.readiness() -> ReadinessResult` (async) | Aggregate checks within deadline | Ready/unavailable result; safe diagnostic codes remain internal. |
| Database probe | `DatabaseProbe.check() -> ProbeResult` (async) | Connectivity and migration compatibility | Available or typed connection/schema failure. |
| Redis probe | `RedisProbe.check() -> ProbeResult` (async) | Broker/cache connectivity | Available or typed connection failure. |
| Storage probe | `StorageProbe.check() -> ProbeResult` (async) | Access to prepared private storage | Available or typed access, configuration, or availability failure. |

**Auth requirements:** internal composition only; infrastructure clients obtain credentials from validated configuration. Route code consumes the aggregate result, not probe exception details.

### Preparation Command

**Boundary:** local container command, invoked as the dedicated preparation service.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|------------------|
| Prepare | `python -m app.bootstrap` | Validate configuration, serialize preparation, migrate database, ensure private storage | Exit `0` after success; nonzero for configuration, lock timeout, migration, or storage failure. |

**Auth requirements:** local infrastructure credentials; never expose preparation through HTTP. The preparation service owns setup privileges; runtime services do not need bucket administration or schema-change operations.

A session-level PostgreSQL advisory lock with a stable, documented application key serializes cooperating preparation commands against the same database. Hold the dedicated session throughout migration and storage preparation, use a bounded lock wait, and fail if lock ownership is lost. Migrations use the controlled connection/session lifecycle; reconnection must not silently continue work without the lock. Release the lock and close the session on completion. No cross-service atomic transaction is claimed: committed migrations remain when storage initialization fails, and a retry re-evaluates both systems.

Compose waits for dependency health and successful preparation before starting API, worker, and scheduler. The documented startup/update workflow must explicitly rerun the preparation service when migration or configuration inputs change; it must not trust a previously completed container as evidence that a new application revision is prepared. A simple restart preserves state and readiness rejects an incompatible schema.

### Browser and Verification Interfaces

**Boundary:** frontend consumer and developer/CI commands.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|------------------|
| Browser read | Relative readiness request through the web container | Display connectivity using generated REST types and TanStack Query | “Connected” only for a valid ready response; “Unavailable” for errors, invalid responses, or timeouts. |
| Quality commands | Documented Compose commands for each quality category | Same checks locally and in GitHub Actions | Zero only for successful completion; nonzero for failed or unavailable checks. |
| Explicit reset | Separately documented environment-scoped command | Delete selected local persisted data deliberately | Names the affected database/storage volumes; never part of ordinary startup or recovery. |

No stale successful browser result may mask a failed refresh. The browser has a bounded transport timeout allowing the server's three-second deadline to complete; retries cannot prolong the initial check indefinitely. Initial loading must not display a false “Connected.” Refresh after recovery triggers a fresh evaluation.

Quality categories comprise formatting, linting, typing, unit/integration/browser checks, clean and repeat migration validation, generated-contract drift, dependency/image/secret scanning, and container builds. GraphQL/WebSocket contract gates are documented as not applicable until those interfaces exist. Scanner execution failures and unavailable vulnerability data are failures, not clean results. High-severity findings and detected secrets block readiness for review under the engineering guide; lower findings remain visible.

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|------------------|----------------|----------------------|
| API assembly | Compose routes and shared resource lifecycles | Health module and shared infrastructure |
| Health module | Schemas, thin routes, readiness service, probes, feature verification | Shared configuration, connection, storage, logging interfaces |
| Shared configuration | Typed validation and environment-specific defaults | Configuration libraries; no feature imports |
| Shared database | Async connections and migration integration | SQLAlchemy/driver/configuration |
| Shared storage | Portable application access plus separately owned local provisioning | S3 client/configuration; no domain repositories |
| Bootstrap | Preparation lock, migration and storage orchestration | Shared infrastructure; never frontend or transport routes |
| Worker/scheduler | Independent process lifecycles and health | Shared Python package, Redis/Dramatiq; no product jobs yet |
| Web | Connectivity presentation and server state | Generated contracts, TanStack Query; no direct infrastructure credentials |
| Contracts | Generated OpenAPI and client type artifacts | Exported API schema; no hand-maintained duplicate response interfaces |
| Quality orchestration | Isolated supporting services and shared verification commands | Containers and disposable check resources; no development volumes |

## Change Footprint

### New files / modules

| Path | Purpose | Pattern reference |
|------|---------|-------------------|
| `compose.yaml` | Development services, health dependencies, preparation, named volumes, loopback exposure | Engineering guide §12; R1–R5, R8–R9 |
| `compose.checks.yaml` | Independently runnable check environment without development volume mounts | Confirmed isolation decision; R6–R7 |
| `infra/docker/` | Application, worker, web, browser and quality image definitions | Engineering guide repository layout |
| `.dockerignore`, `.gitignore`, `.env.example` | Build exclusions, generated/private-file exclusions, safe documented local settings | R4, N1 |
| `pyproject.toml`, Python lockfile | Shared Python package/dependency and check configuration | Required typed Python stack |
| `package.json`, JavaScript lockfile | Frontend/contracts workspace and quality configuration | Required strict TypeScript stack |
| `apps/api/app/main.py` | API assembly and resource lifecycle | Thin transport convention |
| `apps/api/app/modules/health/` | Routes, schemas, services, probes, and feature-owned checks | Feature module ownership |
| `apps/api/app/shared/config/` | Validated settings and local defaults | Shared-only infrastructure convention |
| `apps/api/app/shared/db/` | Connection management and preparation lock support | PostgreSQL authority and async sessions |
| `apps/api/alembic.ini`, `apps/api/alembic/` | Migration configuration and baseline revision | Forward-compatible migrations |
| `apps/api/app/shared/storage/` | Runtime storage access and private local provisioning boundary | MinIO/R2 constraint |
| `apps/api/app/shared/observability/` | Safe structured logging and request correlation | N1 |
| `apps/api/app/bootstrap.py` | Dedicated setup command | R2–R3, R8 |
| `apps/worker/worker.py`, `apps/worker/scheduler.py`, `apps/worker/health.py` | Separate process entry points and progress checks | Engineering guide process separation |
| `apps/web/` | Vite application, connectivity page, styles, query setup and frontend checks | Engineering guide frontend standards |
| `packages/contracts/` | OpenAPI export and generated TypeScript artifacts | Generated contracts requirement |
| `tests/` | Cross-service verification and disposable infrastructure fixtures | Real PostgreSQL/Redis/MinIO checks |
| `scripts/quality/` | Shared verification orchestration and applicability reporting | R6–R7, N4 |
| `.github/workflows/quality.yml` | GitHub Actions invocation and results collection | Confirmed CI platform |
| `README.md`, `docs/development.md` | Setup, verification, failure recovery, preservation and deliberate reset | R10 |
| `docs/adr/` | Concise records for preparation ownership, health contracts, storage and check isolation | Engineering guide ADR requirement |

Directory entries denote new modules whose internal files follow the stated ownership, not an implementation task sequence. No established application file exists to mirror.

### Modified files / modules

None required. The Linux support question in the REQ is resolved by the subsequent confirmed architecture decision recorded here; the requirements artifact remains unchanged.

### Deleted / replaced

None.

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|------|----------------|
| `AGENTS.md`, `CLAUDE.md` | Source of stack, scope, feature ownership, and verification rules |
| `docs/source/engineering-guide.md` | Governs layout and future interfaces; this slice explicitly defers unneeded transports and full telemetry |
| `docs/source/launchpad-client-brief.md` | Product context and privacy invariants; no product behavior implemented |
| `docs/source/inspiration.md` | Future public UI guidance; the foundation verification page is not a product design exercise |
| `specs/requirements/REQ-establish-local-foundation.md` | Acceptance and traceability source; confirmed later decisions resolve its host-support question |

## Areas of Impact

| Area | Impact | Risk (L/M/H) | Why |
|------|--------|--------------|-----|
| Developer environment | First repeatable startup and recovery workflow | M | Container permissions, configuration, or networking can prevent setup |
| Database preparation | Establish migration history and serialization | H | Incorrect locking or retry behavior can damage state |
| Object storage | Establish private persistent local objects | H | Incorrect policies can disclose files; resets can destroy them |
| API/frontend contract | First generated readiness contract | M | False readiness or stale generated types undermine the demonstration |
| Background processes | Establish separate independently checked runtimes | M | Process existence alone does not prove progress |
| CI/check resources | Add automated verification with isolated data | H | Accidental sharing could erase development data or produce false results |
| Logs/configuration | Establish diagnostic and secret-handling conventions | M | Unsafe exception/config logging can disclose secrets |
| Future feature teams | Establish module layout and contract generation | M | Later work must preserve ownership and generated-interface conventions |
| Documentation | Linux setup, recovery and reset expectations | L | No existing runtime instructions are replaced |

**Contract changes:** no existing public contract changes. New health responses are consumed by the connectivity page, container checks, and verification; generated artifacts define their shared types. No domain events, GraphQL operations, or WebSocket messages are introduced.

**Cross-cutting ripples:** preparation privileges, storage privacy, configuration validation, migration compatibility, check isolation, build reproducibility, and logging are shared foundation concerns. No feature flags, user authorization changes, or deployments are included.

## Cross-Cutting Concerns

- **Errors:** infrastructure exceptions map to typed internal probe failures and safe HTTP status. Logs identify dependency and error category without raw credentials, connection strings, object bodies, or browser-visible traces. Setup and checks return nonzero on failure; retries are bounded and explicit.
- **Logging & metrics:** JSON logs include timestamp, severity, process/component, request ID where applicable, operation, duration, and safe result code. Successful preparation is informational; readiness failure is a warning; failed setup/check execution is an error. Basic health and duration diagnostics are included; a metrics backend, OpenTelemetry collector, dashboards, and production alerting are deferred by approval.
- **Auth / authz:** health routes are intentionally unauthenticated and contain only minimal operational status. Private objects deny anonymous access. Bootstrap credentials are separate from limited runtime access and never enter frontend bundles. An existing public bucket fails preparation rather than triggering an unapproved policy rewrite.
- **Performance:** readiness has a three-second overall bound with concurrent finite probes. Migration-state lookup is bounded metadata work; no product scans, object enumeration, or cached readiness success. Worker/scheduler checks independently detect stale progress. Production load targets remain out of scope.
- **Security:** defaults are explicitly local-only and published ports bind to loopback. Required empty/invalid configuration fails before side effects. Logs redact secret-bearing fields and avoid dumping settings. Image/dependency/secret scanning runs through containers, with a nonzero result when scanning cannot finish.
- **Migrations / rollout:** initial local schema preparation uses Alembic and PostgreSQL serialization. This slice restricts migrations to safely repeatable, transactional preparation; published migrations are never rewritten. Updates rerun preparation before the new application is accepted as ready. A failed storage step does not roll back committed schema changes. Recovery uses a corrective migration or compatible application revision; no automatic downgrade or reset. There is no staging/production rollout in scope.
- **Verification isolation:** checks use a separate Compose project and volumes, distinct database/storage credentials, and no development service/volume inheritance. CI jobs use unique project identities. Cleanup targets only the check project's resources; explicit development reset is a separate documented command. Builds use the existing Docker engine without granting application containers engine access.

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|----------|--------------|----------------|---------------|
| A1 | Approved monorepo with separate containerized processes | Host runtime setup; unified API/worker process | Required direction and consistent local workflow | R1, R6, N3 |
| A2 | Dedicated serialized preparation with safe retries | Setup inside every process; manual preparation | Avoids competing setup and preserves successful partial work | R2, R3, R8, R9 |
| A3 | Private MinIO locally, R2 later; web assets in web container | Public buckets; object-hosted frontend bundle | User-selected providers and independent frontend reachability | R5, R8, N3 |
| A4 | Separate liveness/readiness and independent worker health | Process-only health; aggregate idle workers into browser status | Gives the browser a precise usable-dependency signal | R5, N2 |
| A5 | Three-second concurrent readiness deadline | Unbounded checks; cached successful readiness | Bounded failure reporting and fresh recovery evaluation | R5, N2 |
| A6 | Minimal HTTP status and sanitized JSON diagnostics | Detailed public dependency errors; full telemetry stack now | Protects secrets and respects confirmed observability scope | R4, R5, N1 |
| A7 | Generated REST contracts; defer unused transports | Handwritten response types; scaffold empty GraphQL/WebSocket behavior | Prevents type drift without speculative features | R5, R6, N3 |
| A8 | GitHub Actions and local Compose share isolated checks | CI-only scripts; checks against development data | Repeatable evidence and protection of developer state | R6, R7, R9, N4 |
| A9 | Ruff/mypy/pytest and ESLint/Prettier/TypeScript/Vitest/Playwright | Host tools; manual-only verification | Confirmed tooling covers code and browser behavior | R6, R7 |
| A10 | Persistent data, explicit reset, forward corrective recovery | Automatic reset/downgrade on setup error | Avoids destructive recovery and preserves work | R2, R9, R10 |
| A11 | Verify Linux this sprint; defer other host claims | Promise unverified cross-platform support | Resolves the REQ's open support question with a tested promise | R1, R10 |
| A12 | Lockfiles and pinned images; security checks fail on execution errors | Floating dependencies; silently skipped scans | Reproducible and honest verification | R6, R7, N4 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|----------|--------------------------|
| Required dependency is down for 30 seconds | Readiness reports unavailable within three seconds. New requests check fresh state; recovery does not run migrations or clear data. |
| Two preparation processes start simultaneously | Same-database advisory lock serializes them; the second re-evaluates completed state, with a bounded wait and visible failure if it cannot acquire the lock. |
| Database migration succeeds, then MinIO preparation fails | Application startup remains blocked. Retry reuses committed schema state and finishes storage setup without undoing successful work. |
| Preparation crashes while holding its lock | Session termination releases the lock. Retry inspects actual migration/bucket state rather than trusting a completion marker. Loss of the session aborts ongoing preparation. |
| Existing bucket unexpectedly allows public access | Preparation fails with a safe corrective diagnostic. It neither deletes objects nor silently rewrites policy. |
| New code starts against an old or newer incompatible schema | Readiness fails until preparation succeeds or a compatible application revision is restored. No automatic downgrade. |
| Future tables grow from 10K to 10M rows | Health checks remain connection and migration-metadata probes without application-table scans. Production capacity validation remains outside this sprint. |
| Developer restarts services or recreates containers | Named development volumes retain database records and objects; only deliberate reset removes them. |
| Checks run while development is active or CI jobs overlap | Independent Compose identities, credentials and volumes prevent collisions and development cleanup. |
| Scanner or integration dependency cannot be reached | Relevant check fails and overall verification remains unsuccessful. Missing evidence cannot become a pass. |
| Worker/scheduler process exists but its loop stops progressing | Independent health checks detect stale progress; browser readiness stays scoped to API dependencies. |
| Browser receives a malformed response or proxy failure | It shows unavailable; it cannot infer connection success merely from an HTTP response or an old cached success. |

### Backward — regression risk per touched area (brownfield only)

Not applicable: the repository has no existing application, deployed contract, data migration, or runtime caller. Forward risks for all new medium/high-impact areas are captured above. Existing guidance remains unchanged.

## Open Questions

No unresolved product or architectural decisions block this artifact. The REQ's host-support question is resolved by A11. Exact dependency releases, image digests, scanner packages, and generator packages are implementation selections constrained by this document; they do not authorize a change in scope, runtime stack, or verification behavior.

## Out of Scope

- Accounts, product workflows, domain tables, business jobs, notifications, and user authorization systems (later requirements slices).
- Product media upload/download APIs and R2 provisioning (only local private storage infrastructure is delivered).
- Shared staging/production deployment, cloud accounts, and hosting configuration (explicitly deferred).
- GraphQL and WebSocket surfaces without consuming product features (their required technologies remain the future direction).
- Dedicated telemetry collector, dashboards, production alerting, capacity targets and load testing (approved foundation boundary).
- macOS and Windows/WSL2 support claims (only Linux is verified this sprint).
- Public product UI, generated images, task breakdowns, implementation sequencing and test-case specifications (outside Phase 2).
