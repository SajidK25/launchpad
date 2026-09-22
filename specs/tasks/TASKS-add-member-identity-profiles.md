# Tasks

## Task T1: Add identity schema and current-head readiness

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R1, R4, R7, R9–R12, N3
> **Footprint slice:** New identity/profile/outbox Alembic revision and profile model mapping; modified database expected-head logic, health probe, migration/health integration checks
> **High-risk areas touched:** Migrations and readiness (H); authentication and profile integrity (H)

### Description

Create the forward-only PostgreSQL schema for accounts, sessions, challenges, profiles, photo uploads, outbox, and delivery records with the ARCH's constraints and indexes. Make preparation and readiness compare against the application's current Alembic head rather than the foundation revision, preserving serialized startup and its existing health contract.

### Test Plan

#### Test File(s)

- `tests/integration/test_database_preparation.py`
- `tests/integration/test_health_dependencies.py`
- `tests/integration/test_startup_order.py` (run unchanged as a regression guard)

#### Test Scenarios

##### Schema and compatibility

- **Fresh and repeat preparation** — GIVEN an empty disposable PostgreSQL database WHEN preparation runs twice THEN the new head, tables, uniqueness/foreign-key/check constraints, and indexes exist without clearing previously inserted fixture data _(verifies R1, R9, N3)_.
- **Incompatible revision** — GIVEN a missing, older, or newer revision WHEN readiness runs THEN it reports unavailable within its existing bound; the current head reports ready _(verifies N3; ARCH schema stress)_.
- **Concurrent preparation and failure** — GIVEN overlapping preparation or a deliberately failing disposable migration WHEN callers run THEN the advisory lock serializes work, failure leaves no false head, and a corrected retry succeeds _(verifies N3; ARCH forward stress)_.

##### Regression guards

- **Bootstrap and health preservation** — GIVEN the new revision WHEN the unchanged bootstrap and health routes run THEN preparation still gates API/worker/scheduler and the existing response shape/deadline holds _(guards ARCH backward risk for `apps/api/app/bootstrap.py`, `apps/api/alembic/env.py`, and health routes/service/tests)_.
- **Metadata-scale probe** — GIVEN many account rows WHEN readiness runs THEN it consults migration metadata and required services, not the account table _(guards ARCH 10M-row stress and `apps/api/app/modules/health/service.py`)_.

### Implementation Notes

- **Module(s):** shared DB and health; the schema belongs to auth/users/shared events as defined in ARCH Data Models.
- **Pattern reference:** `apps/api/alembic/versions/0001_foundation.py`, `apps/api/app/shared/db/database.py`, `apps/api/app/modules/health/probes.py`.
- **Key decisions:** A2, A10. Preserve the existing migration and lock; derive the expected head from the packaged migration scripts. The profile mapping introduced here is completed by later users-module tasks.
- **Libraries:** existing Alembic, SQLAlchemy 2 async, asyncpg.
- **High-risk callouts:** A false-compatible revision can start code against the wrong schema; checks cover fresh, repeat, mismatch, and failure without modifying development data.

### Scope Boundaries

- Do not edit or downgrade `0001_foundation.py`; do not add product/vote/staff tables.
- Do not add routes, email delivery, or profile behavior in this schema task.

### Files Expected

**New files:**

- `apps/api/alembic/versions/0002_member_identity_profiles.py` — forward schema and indexes, following the baseline migration.
- `apps/api/app/modules/users/models.py` — initial profile/link/photo table mapping owned by users.

**Modified files:**

- `apps/api/app/shared/db/database.py` — derive and check current Alembic head.
- `apps/api/app/modules/health/probes.py` — use current-head compatibility rather than fixed foundation revision.
- `tests/integration/test_database_preparation.py` and `tests/integration/test_health_dependencies.py` — new-head assertions and mismatch coverage.
- `tests/integration/test_bootstrap.py` — replace its foundation-only assertion with the current-head contract.

**Must NOT modify:**

- `apps/api/alembic/versions/0001_foundation.py`, `apps/api/app/bootstrap.py`, `apps/api/alembic/env.py` — existing migration/serialized preparation.
- `apps/api/app/modules/health/routes.py`, `apps/api/app/modules/health/service.py`, `apps/api/app/modules/health/tests/test_routes.py`, `tests/integration/test_startup_order.py` — unchanged health/startup contracts.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

### Verification Evidence

- Isolated `COMPOSE_PROJECT_NAME=launchpad-t1-identity sh scripts/quality/run.sh` passed after rebuilding the `prepare` image with revision `0002_member_identity_profiles`.
- Ruff format/lint passed; mypy reported no issues in 27 source files; pytest passed 42 tests; web tests passed 11; Playwright connectivity passed 1.
- Migration tests cover fresh/repeat/concurrent preparation, transaction rollback, uniqueness, foreign keys, publication checks, and missing/older/newer revision rejection. Existing health/startup/storage checks passed unchanged.
- Contract generation/check, image builds, and security scan passed; the latter found 0 vulnerabilities.

---

## Task T2: Configure isolated identity, mail, and upload prerequisites

> **Status:** done
> **Verification:** checklist
> **Effort:** m
> **Priority:** high
> **Depends on:** None
> **Satisfies REQs:** N1, N2, N3
> **Footprint slice:** Modified validated settings, example environment, Python manifest/lock, development/check Compose, and isolated fixtures
> **High-risk areas touched:** Local/CI configuration (M); authentication secrets (H); check isolation (M)

### Description

Provide the pinned libraries and validated local/check configuration required by account, GraphQL, encryption, SMTP, and photo work. Keep runtime secrets server-only and preserve separate check resources and startup dependencies before the feature modules begin using them.

### Verification Checklist

- [x] **Locked image** — build `python-checks` twice with `docker compose -f compose.checks.yaml build python-checks`; expected: required pinned libraries install from an unchanged lock without host Python.
- [x] **Safe settings failures** — run configuration checks with missing/malformed nonlocal mail origin, sender, encryption key, or browser upload endpoint; expected: nonzero failure names the field, never its value (N1).
- [x] **Local/check separation** — render both Compose definitions and exercise check fixtures; expected: distinct PostgreSQL/MinIO credentials and volumes, check-only mail, loopback development ports, and no development-volume mount (N3).
- [x] **Secret exclusion** — inspect built images and browser assets with disposable secret markers; expected: markers and mail/encryption/storage keys are absent while application package files remain (N1).
- [x] **Startup regression** — run unchanged startup/isolation checks; expected: API/worker/scheduler still wait for preparation, and removal of a check project leaves development data intact (N3).

### Implementation Notes

- **Module(s):** shared configuration and check infrastructure.
- **Pattern reference:** `apps/api/app/shared/config/settings.py`, `.env.example`, `compose.checks.yaml`, `tests/conftest.py`.
- **Key decisions:** A3, A6–A9. Local-only defaults may use Mailpit and disposable keys; nonlocal environments must supply explicit validated secrets. Pin versions during implementation, with no external account required for local checks.
- **Libraries:** Argon2id, Strawberry, authenticated encryption, email validation, image decoding, and SMTP support selected and locked here.
- **High-risk callouts:** Configuration errors must precede side effects; fixtures must never fall back to developer volumes or expose values in diagnostics.

### Scope Boundaries

- Do not implement an account API, start mailing users, connect to cloud storage, or weaken the existing private bucket.
- Do not grant the API bootstrap credentials or publish non-loopback local dependencies.

### Files Expected

**New files:** None.

**Modified files:**

- `apps/api/app/shared/config/settings.py`, `.env.example` — typed mail/outbox/cookie/upload settings and safe errors.
- `pyproject.toml`, `requirements.lock` — pinned Python dependency set.
- `compose.yaml`, `compose.checks.yaml` — isolated mail and required per-process environment; later tasks extend only their named runtime needs.
- `tests/conftest.py` — explicit disposable mail/storage identity fixtures.

**Must NOT modify:**

- `infra/docker/web.conf`, `infra/docker/web.Dockerfile`, `infra/docker/browser.Dockerfile` — proxy and build-output regression guards.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

### Verification Evidence

- Two isolated `python-checks` builds succeeded with unchanged `requirements.lock` SHA-256 `e2ae50b70be8a974a6bc5e348a93fa64835aa59a8f9264590bbd4ff33daac455`; `python -m pip check` reported no broken requirements.
- A production-settings matrix rejected eight missing/malformed/insecure cases by field name without printing the supplied sentinel. A distinct 32-byte key and HTTPS origins passed; the disposable local key was rejected in production.
- Both Compose files rendered with distinct check/development users and volumes. Check Mailpit accepted an SMTP connection and returned HTTP 200 from its API; development published ports were loopback-only, check Mailpit published none, and API runtime environments contained no bootstrap storage key.
- Built web assets contained no disposable sentinel, outbox key, or storage credential; web image environment had no `LAUNCHPAD_` values. The Python image retained application code without embedding runtime environment keys.
- Full isolated `COMPOSE_PROJECT_NAME=launchpad-t2-config sh scripts/quality/run.sh` passed: Ruff, mypy (27 files), pytest (42), web tests (11), contracts, builds, security (0 vulnerabilities), and browser connectivity (1). The exact `launchpad-t2-config` project and its three check volumes were removed; other Launchpad volumes remained.

---

## Task T3: Implement credential and request-security primitives

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T2
> **Satisfies REQs:** R1, R8, N1, N2
> **Footprint slice:** New shared/security password, email-key, random-token/digest, and CSRF primitives plus focused tests
> **High-risk areas touched:** Authentication and recovery (H); rate/abuse security boundary (M)

### Description

Provide small typed primitives that auth and users services can use without duplicating credential logic. The rules cover Argon2id storage, the agreed password policy, consistent address comparison, and secrets suitable for one-time links and session-bound CSRF.

### Test Plan

#### Test File(s)

- `apps/api/app/shared/security/tests/test_passwords.py`
- `apps/api/app/shared/security/tests/test_identity_primitives.py`

#### Test Scenarios

##### Credentials and identifiers

- **Argon2id round trip** — GIVEN an accepted password WHEN it is stored and verified THEN the stored value is an Argon2id hash, not plaintext, and a wrong password fails _(verifies R8, N1)_.
- **Confirmed password boundaries** — GIVEN 7, 8, 64-plus-character, spaced, symbol-bearing, and blocklisted passwords WHEN evaluated THEN only short or known-compromised values are rejected; no character mix is demanded _(verifies R8; REQ input edge)_.
- **Canonical email identity** — GIVEN case/IDNA variations and provider aliases WHEN normalized THEN equivalent casing has one comparison key, original delivery spelling is retained, and dot/plus aliases are not rewritten _(verifies R1, N2; REQ duplicate edge)_.

##### Secret boundaries

- **One-time entropy and digest** — GIVEN two generated link/session secrets WHEN inspected THEN each has at least 32 random bytes, distinct digests, and no raw value in stored-form serialization _(verifies N1; ARCH challenge design)_.
- **CSRF binding** — GIVEN a token from one session WHEN checked against another or altered value THEN validation fails; the correct session-bound token succeeds _(verifies N1)_.
- **Safe diagnostics** — GIVEN invalid email/password/token input containing sentinel secrets WHEN validation fails THEN errors and structured logs identify category without reproducing raw values _(verifies N1; ARCH backward logging risk)_.

### Implementation Notes

- **Module(s):** `app.shared.security` only.
- **Pattern reference:** typed shared settings and sanitized logging under `apps/api/app/shared/`.
- **Key decisions:** A3–A6. Use secure randomness; hash high-entropy tokens rather than Argon2id; normalize password text consistently before blocklist/hash checks. Record RED → GREEN → REFACTOR evidence.
- **Libraries:** locked Argon2id and email-validation libraries from T2; standard cryptographic randomness/digest helpers.
- **High-risk callouts:** A mismatched canonicalization or leaked token would undermine all later flows; boundary and sentinel tests run before consumers are added.

### Scope Boundaries

- Do not create accounts, sessions, routes, or an online breach-query dependency.
- Do not add MFA or mandatory password character-composition rules.

### Verification Evidence

- TDD RED confirmed the focused security tests failed at collection while the T3 modules were absent; GREEN then passed all 11 focused tests after the primitives were implemented.
- New security modules passed Ruff formatting/lint and strict mypy checks.
- Full isolated `COMPOSE_PROJECT_NAME=launchpad-t3-security sh scripts/quality/run.sh` passed: Ruff, mypy (34 files), pytest (53), web tests (11), contracts, builds, security (0 vulnerabilities), and browser connectivity (1). The disposable T3 project and its three check volumes were removed afterward.

### Files Expected

**New files:**

- `apps/api/app/shared/security/passwords.py`, `email.py`, `tokens.py`, `csrf.py` and versioned local blocklist asset — focused shared primitives.
- `apps/api/app/shared/security/tests/test_passwords.py`, `test_identity_primitives.py` — deterministic contract tests.

**Modified files:** None.

**Must NOT modify:**

- `apps/api/app/shared/observability/logging.py` — existing redaction convention; guard its behavior through tests.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

---

## Task T4: Persist encrypted transactional email events

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T1, T2
> **Satisfies REQs:** R2, R5–R7, R12, N1, N3
> **Footprint slice:** New shared/events outbox model/repository and shared/email encrypted payload codec with tests
> **High-risk areas touched:** Email/outbox and background processes (H); confidential recovery links (H)

### Description

Create the durable event boundary that account and profile services will insert inside their own transactions. Encrypt recipient/template/link payloads at rest, claim due messages safely, and retain retry state without making Redis the authority.

### Test Plan

#### Test File(s)

- `apps/api/app/shared/events/tests/test_outbox.py`
- `apps/api/app/shared/email/tests/test_codec.py`
- `tests/integration/test_identity_mail.py`

#### Test Scenarios

##### Persistence and confidentiality

- **Atomic event** — GIVEN a state change and outbox insert in one transaction WHEN it commits or rolls back THEN both appear or neither appears _(verifies R5–R7, R12, N3)_.
- **Encrypted payload** — GIVEN a recipient and raw challenge-link sentinel WHEN encoded and stored THEN neither is readable in the database or diagnostics, and only the matching configured key decrypts _(verifies N1)_.
- **Versioned key failure** — GIVEN unknown key ID or altered ciphertext WHEN decoded THEN delivery fails safely without exposing plaintext or dropping retry visibility _(verifies N1, N3)_.

##### Dispatch state

- **Concurrent claim** — GIVEN one due event and two claimants WHEN both try to claim THEN only one owns the current attempt and the other cannot duplicate its state change _(verifies N3; ARCH concurrency stress)_.
- **Crash and retry** — GIVEN an abandoned claim WHEN its lease expires THEN the event becomes due again with bounded attempts/backoff; completed ciphertext is cleared and delivery metadata remains _(verifies R12, N3; ARCH worker-restart stress)_.
- **Expired link separation** — GIVEN expired challenge mail and an unsent privacy notice WHEN due work is selected THEN the expired link is not deliverable, while the privacy notice remains retryable _(verifies R5–R7, R12)_.

### Implementation Notes

- **Module(s):** `app.shared.events` and `app.shared.email` transport/codec only.
- **Pattern reference:** async PostgreSQL access in `apps/api/app/shared/db/database.py` and shared typed errors; ARCH outbox model.
- **Key decisions:** A2, A4, A7. The producing service owns its domain transaction; event IDs are stable, payload encryption is authenticated and versioned, and claim/retry is idempotent. Record RED → GREEN → REFACTOR evidence.
- **Libraries:** SQLAlchemy 2 async and authenticated-encryption library pinned in T2.
- **High-risk callouts:** A DB rollback must never leave an email event, and a committed privacy notice must never depend on Redis memory alone.

### Scope Boundaries

- Do not send SMTP here or add a generic notification inbox/preferences system.
- Do not store raw challenge tokens, full links, or mail payloads as readable database fields.

### Verification Evidence

- Codec tests passed for authenticated encryption, plaintext exclusion, unknown-key rejection, and tamper detection; integration tests passed for transaction rollback, one-winner concurrent claims, lease recovery, ciphertext clearing, and retained delivery metadata.
- Full isolated `COMPOSE_PROJECT_NAME=launchpad-t4-outbox sh scripts/quality/run.sh` passed: Ruff, mypy (41 files), pytest (57), web tests (11), contracts, builds, security (0 vulnerabilities), and browser connectivity (1). The disposable T4 and focused integration projects and volumes were removed afterward.

### Files Expected

**New files:**

- `apps/api/app/shared/events/models.py`, `repository.py`, `outbox.py` — shared event envelope and claim state.
- `apps/api/app/shared/email/codec.py` — encrypted versioned payload boundary.
- `apps/api/app/shared/events/tests/test_outbox.py`, `apps/api/app/shared/email/tests/test_codec.py`, `tests/integration/test_identity_mail.py` — focused and real-DB assertions.

**Modified files:** None.

**Must NOT modify:**

- `apps/worker/health.py` and `tests/integration/test_startup_order.py` — background contract belongs to T5 and stays intact.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

---

## Task T5: Dispatch outbox email through the worker

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T2, T4
> **Satisfies REQs:** R5–R7, R12, N3
> **Footprint slice:** New shared email transport/dispatch registry; modified worker, scheduler, and background integration checks; T2's mail configuration consumed
> **High-risk areas touched:** Email/outbox and background processes (H); local/check configuration (M)

### Description

Replace the heartbeat-only background loop with real, durable outbox dispatch while preserving independent worker and scheduler progress health. The scheduler enqueues due IDs; the worker claims from PostgreSQL and sends through SMTP with safe retry, using Mailpit in isolated local/check environments.

### Test Plan

#### Test File(s)

- `tests/integration/test_identity_mail.py`
- `tests/integration/test_background_processes.py`
- `tests/integration/test_startup_order.py` (run unchanged)

#### Test Scenarios

##### Delivery and failure

- **Due mail delivery** — GIVEN a due outbox event and live Mailpit WHEN scheduler and worker run THEN exactly one delivery record is written and Mailpit receives the expected message ID/type _(verifies R5–R7, R12)_.
- **SMTP outage** — GIVEN Mailpit unavailable for 30 seconds WHEN a privacy notice is due THEN the profile change remains committed, the event stays retryable, and delivery succeeds after recovery _(verifies R12, N3; ARCH forward stress)_.
- **Expired link handling** — GIVEN a verification/reset event whose link expired during the outage WHEN the worker resumes THEN it does not email that stale link and a fresh request remains possible _(verifies R5–R7)_.
- **Redis outage or worker restart** — GIVEN a committed event WHEN Redis is temporarily absent or an actor dies after claim THEN PostgreSQL retains the event and re-dispatch becomes possible without repeating the domain transition _(verifies N3; ARCH forward stress)_.

##### Regression guards

- **Real process progress** — GIVEN a stopped dispatch scan or stalled worker WHEN health is checked THEN stale progress fails; an idle but advancing loop remains healthy _(guards ARCH backward risk for `apps/worker/health.py` and `tests/integration/test_background_processes.py`)_.
- **Preparation gate** — GIVEN an unprepared check project WHEN worker/scheduler start THEN existing Compose completion dependencies still prevent premature work _(guards `tests/integration/test_startup_order.py`)_.

### Implementation Notes

- **Module(s):** worker/scheduler runtime, `app.shared.email`, `app.shared.events`.
- **Pattern reference:** `apps/worker/worker.py`, `apps/worker/scheduler.py`, `apps/worker/health.py` and the existing check Compose Mailpit style.
- **Key decisions:** A7, A10. Worker claims by event ID and records attempt outcomes; a stable message ID reduces duplicate delivery, but ambiguous SMTP acknowledgement may still duplicate an email. Do not report health from a loop that is not scanning/dispatching.
- **Libraries:** existing Dramatiq/Redis; SMTP transport selected in T2.
- **High-risk callouts:** At-least-once delivery must not become at-least-once account/profile mutation; the outage/restart tests guard that boundary.

### Scope Boundaries

- Do not put account/profile state in Redis or add product jobs/schedules.
- Do not change the existing API readiness contract to include worker health.

### Verification Evidence

- Existing worker/scheduler progress and preparation-gate regression tests passed unchanged; new assertions confirm the entry points use durable outbox dispatch and scheduler due-work hints.
- Mailpit integration covered stable delivery IDs, expired challenge suppression, privacy-notice delivery, SMTP failure/recovery, and PostgreSQL retryability.
- Full isolated `COMPOSE_PROJECT_NAME=launchpad-t5-dispatch sh scripts/quality/run.sh` passed: Ruff, mypy (43 files), pytest (61), web tests (11), contracts, builds, security (0 vulnerabilities), and browser connectivity (1). Disposable T5 and focused integration projects/volumes were removed afterward.

### Files Expected

**New files:**

- `apps/api/app/shared/email/transport.py` and `apps/api/app/shared/events/dispatcher.py` — SMTP send and registered event dispatch.

**Modified files:**

- `apps/worker/worker.py`, `apps/worker/scheduler.py` — process due work and retain progress checks.
- `tests/integration/test_identity_mail.py`, `tests/integration/test_background_processes.py` — delivery and process assertions.
- `compose.yaml`, `compose.checks.yaml` — only the worker/scheduler runtime environment and Mailpit dependency supplied by T2.

**Must NOT modify:**

- `apps/worker/health.py`, `tests/integration/test_startup_order.py` — run as regression guards.
- `apps/api/app/modules/health/routes.py` and `service.py` — API health remains separate.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

---

## Task T6: Register one private account and verify its email

> **Status:** not started
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T1, T3, T4
> **Satisfies REQs:** R1, R2, R4, R5, R9, N1–N3
> **Footprint slice:** New auth account/challenge model, repository, service and users private-profile bootstrap service/repository; new member-identity integration checks
> **High-risk areas touched:** Authentication and recovery (H); profile privacy (H); transactional outbox (H)

### Description

Build the transactional registration and email-verification domain behavior before exposing routes. Registration creates exactly one unverified account and its private profile through a named users service boundary, plus a durable verification event; resend and token consumption obey the approved 60-minute latest-link rule.

### Test Plan

#### Test File(s)

- `apps/api/app/modules/auth/tests/test_registration.py`
- `apps/api/app/modules/auth/tests/test_verification.py`
- `tests/integration/test_member_identity.py`
- `tests/integration/test_identity_mail.py`

#### Test Scenarios

##### Registration and privacy

- **Atomic new member** — GIVEN a valid new email/password WHEN registration commits THEN one unverified account, one private profile, one challenge, and one encrypted email event exist together _(verifies R1, R4, R9, N3)_.
- **Generic existing account** — GIVEN a canonical email already registered WHEN registration repeats THEN the public result is indistinguishable from new registration and existing password/profile stay unchanged _(verifies R2, N2; REQ duplicate edge)_.
- **Concurrent equivalent addresses** — GIVEN simultaneous case variants WHEN both register THEN a unique constraint permits one account/profile and no conflicting verification events _(verifies R1, N3; ARCH concurrency stress)_.

##### Verification and failures

- **Valid one-use proof** — GIVEN the current token WHEN explicitly consumed before 60 minutes THEN only that account becomes verified; a repeat or wrong-purpose token cannot verify it _(verifies R4; REQ link edge)_.
- **Resend ordering** — GIVEN overlapping resends WHEN both finish THEN the newest issued link works and older/expired/altered links fail safely _(verifies R5, N3; ARCH overlap stress)_.
- **Mail outage and rollback** — GIVEN mail unavailable or a failed transaction WHEN registration/resend executes THEN no request-time mail marks verification and no partial account/profile/event survives rollback _(verifies R1, R5, N1, N3)_.

### Implementation Notes

- **Module(s):** `app.modules.auth` and the named `users.ProfileBootstrap` service boundary.
- **Pattern reference:** `apps/api/app/modules/health/` feature separation and `apps/api/app/shared/db/database.py` async transaction pattern.
- **Key decisions:** A1–A2, A4–A5, A7. Auth must not import a users repository; the users service owns private-profile creation inside the same DB transaction. This cross-module bootstrap seam makes this the one larger domain task; record RED → GREEN → REFACTOR evidence.
- **Libraries:** T3 security primitives, SQLAlchemy 2 async, T4 encrypted outbox.
- **High-risk callouts:** Duplicate races and partial failures must not produce two identities or a public draft; the real-DB scenarios guard both.

### Scope Boundaries

- Do not implement staff status, Google sign-in, product ownership, or profile publication.
- Do not put raw tokens into account tables, logs, or unencrypted outbox fields.

### Files Expected

**New files:**

- `apps/api/app/modules/auth/models.py`, `repository.py`, `service.py` — account/challenge ownership and domain transitions.
- `apps/api/app/modules/users/repository.py`, `service.py` — minimal named private-profile bootstrap, extended by T11.
- `apps/api/app/modules/auth/tests/test_registration.py`, `test_verification.py`, `tests/integration/test_member_identity.py` — unit and real-DB evidence.

**Modified files:**

- `tests/integration/test_identity_mail.py` — verification event remains durable and secret-safe.

**Must NOT modify:**

- `apps/api/app/modules/health/`, `apps/api/app/bootstrap.py` — existing readiness/preparation boundaries.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

---

## Task T7: Enforce revocable sessions and abuse controls

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T2, T3, T6
> **Satisfies REQs:** R3, N1, N2
> **Footprint slice:** New auth session/policy and shared rate-limit services; modified auth repository/service; focused auth tests
> **High-risk areas touched:** Authentication and recovery (H); rate limiting and Redis (M)

### Description

Implement sign-in, sign-out, session resolution, verification-aware member access, CSRF/Origin checks, and independent abuse limits. PostgreSQL sessions remain authoritative and expire at the approved 24-hour idle/seven-day absolute bounds; Redis only enforces temporary request limits.

### Test Plan

#### Test File(s)

- `apps/api/app/modules/auth/tests/test_sessions.py`
- `apps/api/app/modules/auth/tests/test_rate_limits.py`
- `tests/integration/test_member_identity.py`

#### Test Scenarios

##### Session and authorization

- **Restricted sign-in** — GIVEN correct credentials on an unverified account WHEN sign-in succeeds THEN the member may resolve/edit only their private identity context and cannot pass `require_verified` _(verifies R3)_.
- **Generic failure** — GIVEN unknown/wrong credentials WHEN sign-in runs THEN both have the same safe failure class and comparable work, without identifying the account _(verifies R3, N2)_.
- **Revocation and time bounds** — GIVEN active sessions WHEN sign-out or 24-hour idle/seven-day absolute expiry occurs THEN the affected session no longer authorizes, while unrelated sessions remain until reset _(verifies R3, N1)_.
- **CSRF and Origin** — GIVEN a valid cookie with missing, wrong-session, or cross-origin CSRF context WHEN an unsafe action is attempted THEN it fails before domain mutation _(verifies N1)_.

##### Abuse and infrastructure

- **Independent limits** — GIVEN distributed attempts against one address and broad attempts from one source WHEN thresholds are crossed THEN either bucket imposes a temporary cooldown without permanent account lockout _(verifies N2; REQ high-volume edge)_.
- **Redis outage** — GIVEN unavailable Redis WHEN a sensitive account action needs limiting THEN it fails closed with a safe response and existing PostgreSQL sessions remain authoritative _(verifies N2; ARCH forward stress)_.

### Implementation Notes

- **Module(s):** `app.modules.auth` and `app.shared.security`.
- **Pattern reference:** existing shared Redis health probe and typed service errors; ARCH session model.
- **Key decisions:** A2–A3, A6. Use opaque cookie secrets backed by digests, session epoch and revocation; limits use separate address and source keys. Record RED → GREEN → REFACTOR evidence.
- **Libraries:** SQLAlchemy async and Redis from the foundation; T3 CSRF/password helpers.
- **High-risk callouts:** A Redis failure must not bypass throttling, and an unverified session must not gain publish eligibility; tests cover both.

### Scope Boundaries

- Do not use stateless JWTs or frontend token storage; do not implement MFA or staff authorization.
- Do not add permanent locks solely from failed requests.

### Files Expected

**New files:**

- `apps/api/app/modules/auth/sessions.py`, `policies.py` and `apps/api/app/shared/security/rate_limit.py` — session and abuse boundaries.
- `apps/api/app/modules/auth/tests/test_sessions.py`, `test_rate_limits.py` — deterministic service assertions.

**Modified files:**

- `apps/api/app/modules/auth/repository.py`, `service.py` — persist/revoke sessions and expose named member access.
- `tests/integration/test_member_identity.py` — real database/Redis session assertions.

**Must NOT modify:**

- `apps/api/app/modules/health/probes.py` — Redis health is an existing separate concern.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

---

## Task T8: Recover passwords without preserving old access

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T4, T6, T7
> **Satisfies REQs:** R6–R8, N1–N3
> **Footprint slice:** Modified auth challenge/session repository and service; recovery tests and durable notice evidence
> **High-risk areas touched:** Authentication and recovery (H); encrypted mail (H)

### Description

Implement generic reset requests and one-use recovery for verified and unverified accounts. A successful reset updates the password, consumes the newest valid challenge, revokes every device through the session epoch, and inserts a change notice in one transaction without signing the member in.

### Test Plan

#### Test File(s)

- `apps/api/app/modules/auth/tests/test_recovery.py`
- `tests/integration/test_member_identity.py`
- `tests/integration/test_identity_mail.py`

#### Test Scenarios

##### Recovery behavior

- **Generic request** — GIVEN known and unknown well-formed addresses WHEN reset is requested THEN the public result is identical and the unknown address changes no account _(verifies R6, N2)_.
- **Newest one-use link** — GIVEN old, altered, expired, used, and current reset tokens WHEN submitted THEN only the current unexpired token changes the intended password once _(verifies R7, N3; REQ link edge)_.
- **Unverified recovery** — GIVEN an unverified member WHEN a valid reset completes THEN the new password works but `verified_at` remains unset and no authenticated session is created _(verifies R7)_.
- **Password boundaries** — GIVEN short, compromised, 64-plus-character, and spaced new passwords WHEN reset is attempted THEN T3's policy applies without consuming a token on invalid password _(verifies R8; REQ input edge)_.

##### Race and failure

- **All devices and concurrent login** — GIVEN multiple active sessions plus an old-password login racing the reset WHEN both settle THEN all pre-reset sessions fail, old-password login cannot produce a usable session, and normal new-password sign-in is required _(verifies R7, N3; ARCH race stress)_.
- **Notice atomicity** — GIVEN a reset transaction that fails after password selection WHEN rolled back THEN hash, epoch, challenge, and encrypted change-notice state all retain their prior values _(verifies R7, N3)_.

### Implementation Notes

- **Module(s):** `app.modules.auth`, using shared security and outbox interfaces.
- **Pattern reference:** T6 account/challenge service and T7 session epoch contract.
- **Key decisions:** A2, A4, A6–A7. Serialize reset and sign-in on account row; link purpose never changes verification state. Record RED → GREEN → REFACTOR evidence.
- **Libraries:** T3 password/token helpers; SQLAlchemy async; T4 encrypted outbox.
- **High-risk callouts:** Testing the login/reset race and transaction rollback is necessary to prevent a stolen session from surviving recovery.

### Scope Boundaries

- Do not auto-login after reset or treat reset as email verification.
- Do not implement email-address change, MFA recovery, or security questions.

### Files Expected

**New files:**

- `apps/api/app/modules/auth/tests/test_recovery.py` — service contract.

**Modified files:**

- `apps/api/app/modules/auth/repository.py`, `service.py`, `sessions.py` — challenge, hash, epoch, and all-device revocation.
- `tests/integration/test_member_identity.py`, `tests/integration/test_identity_mail.py` — real transaction and notice assertions.

**Must NOT modify:**

- `apps/api/app/shared/security/passwords.py` — reuse T3 policy without weakening it.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

---

## Task T9: Expose safe authentication REST actions

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T6, T7, T8
> **Satisfies REQs:** R1–R8, N1–N3
> **Footprint slice:** New auth REST schemas/routes; modified API assembly; auth transport tests while health routes stay unchanged
> **High-risk areas touched:** Authentication and recovery (H); API/frontend contracts (M)

### Description

Expose the approved versioned registration, login/session/logout, verification, and recovery actions through thin Pydantic/FastAPI routes. Wire services into `create_app` while keeping the health-only test factory and existing readiness contract intact.

### Test Plan

#### Test File(s)

- `apps/api/app/modules/auth/tests/test_routes.py`
- `apps/api/app/modules/health/tests/test_routes.py` (run unchanged)
- `tests/integration/test_member_identity.py`

#### Test Scenarios

##### Transport contracts

- **Endpoint shapes** — GIVEN valid requests to every ARCH auth action WHEN called through HTTP THEN documented status/body/cookie shape is returned without exposing ORM fields _(verifies R1–R8)_.
- **Generic response classes** — GIVEN existing/new registration and known/unknown reset address WHEN routed THEN both pairs have the same safe public status/body; wrong/unknown login is generic _(verifies R2–R3, R6, N2)_.
- **Link scanners and errors** — GIVEN an email URL opened with GET, then a user POSTs a token WHEN handled THEN only the POST consumes it; invalid/expired tokens and validation/rate errors have safe codes and no traces _(verifies R4–R8, N1)_.
- **Cookie and CSRF at HTTP boundary** — GIVEN a real signed-in cookie WHEN Origin/CSRF is missing or incorrect THEN unsafe actions are refused; correct same-origin requests work and logout clears access _(verifies R3, N1)_.

##### Regression guards

- **Health-only factory** — GIVEN injected `HealthService` WHEN `create_app` is used by the existing route tests THEN live/ready responses and their deadline remain unchanged _(guards ARCH backward risk for `main.py` and health routes/service/tests)_.
- **Dependency failure** — GIVEN Redis or PostgreSQL unavailable WHEN a sensitive action executes THEN a safe non-success response appears without stack trace or secret values _(verifies N1–N3; ARCH forward stress)_.

### Implementation Notes

- **Module(s):** auth REST transport and API assembly.
- **Pattern reference:** `apps/api/app/modules/health/routes.py`, `schemas.py`, `apps/api/app/main.py`.
- **Key decisions:** A1, A3–A4, A9–A10. Routes translate typed service errors; use fixed trusted web origin for email links; do not consume a token on GET. OpenAPI is regenerated in T13.
- **Libraries:** FastAPI/Pydantic and existing resource lifecycle.
- **High-risk callouts:** A transport shortcut must not bypass policy checks or reveal account existence; route tests exercise real HTTP behavior.

### Scope Boundaries

- Do not add profile publication, GraphQL mutations, or frontend UI here.
- Do not change `/api/v1/health/live` or `/api/v1/health/ready` behavior.

### Files Expected

**New files:**

- `apps/api/app/modules/auth/routes.py`, `schemas.py`, `tests/test_routes.py` — typed thin transport and tests.

**Modified files:**

- `apps/api/app/main.py` — compose auth resources/routes without breaking health-only injection.
- `tests/integration/test_member_identity.py` — actual HTTP/session path assertions.

**Must NOT modify:**

- `apps/api/app/modules/health/routes.py`, `service.py`, `tests/test_routes.py` — health regression guards.
- `apps/api/app/bootstrap.py` and `apps/api/alembic/env.py` — preparation contract.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

---

## Task T10: Private photo storage and validated staging

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T2
> **Satisfies REQs:** R9–R11, N1
> **Footprint slice:** private object operations and runtime storage policy
> **High-risk areas touched:** storage privilege boundary, media validation, private-photo confidentiality

### Description

Add the prefix-scoped runtime storage permissions and the bounded signed-staging/object operations needed by the profile service. Validate actual image bytes and size, re-encode to strip metadata, and keep staging and final objects private. No photo URL may bypass a later visibility check.

### Test Plan

#### Test File(s)

- `tests/integration/test_profile_privacy.py`
- `apps/api/app/shared/storage/tests/test_objects.py`
- `tests/integration/test_storage.py` (run unchanged)

#### Test Scenarios

##### Storage boundary

- **Runtime policy** — GIVEN the provisioned runtime identity WHEN it accesses allowed staging/final prefixes THEN only the intended object operations work; anonymous, cross-prefix, and direct public reads are denied _(verifies N1; guards ARCH storage privilege risk)_.
- **Signed staging constraints** — GIVEN a requested upload WHEN the signed policy is issued THEN it is restricted to one staging object, approved content type, at most 5 MB, short expiry, and strict configured CORS; expired or changed-object submissions fail _(verifies R9–R10, N1)_.
- **Actual content validation** — GIVEN JPEG, PNG, WebP, malformed bytes, disguised content types, or an oversized body WHEN finalized THEN only valid bounded images are accepted and re-encoded without metadata _(verifies R9–R10, N1)_.
- **Private finalization** — GIVEN a valid staged image WHEN finalized THEN its final object remains private; staging is never exposed through public delivery or a durable public URL _(verifies N1)_.
- **Failure cleanup** — GIVEN failed validation, interrupted finalize, and stale staging WHEN cleanup runs THEN only owned bounded staging objects are removed and no unrelated object is touched _(verifies N1; ARCH forward stress)_.

##### Regression guards

- **Existing storage probe** — GIVEN the foundation private bucket WHEN readiness and anonymous-denial tests run THEN their read-only behavior remains unchanged _(guards `shared/storage/client.py` and `tests/integration/test_storage.py`)_.

### Implementation Notes

- **Module(s):** shared storage object adapter and provisioning.
- **Pattern reference:** `apps/api/app/shared/storage/client.py`, `provision.py`; existing storage integration fixture.
- **Key decisions:** A8. The adapter returns opaque object identifiers, never public URLs. Profile authorization and HTTP photo delivery belong to T11–T12. Separate validation from policy so both are directly testable.
- **Libraries:** pinned image library from T2 and existing S3-compatible client.
- **High-risk callouts:** A signed upload is not proof of safe bytes. Re-encode before promotion; keep direct MinIO access private. Do not expand readiness identity beyond the approved prefixes.

### Scope Boundaries

- Do not add profile state rules, API photo responses, or a public bucket.
- Do not change the existing read-only storage probe or anonymous-denial test.

### Files Expected

**New files:**

- `apps/api/app/shared/storage/objects.py` and `tests/test_objects.py` — bounded private object operations and tests.
- `tests/integration/test_profile_privacy.py` — storage-boundary integration cases, extended in T11–T12.

**Modified files:**

- `apps/api/app/shared/storage/provision.py` — prefix-scoped policy and strict upload CORS.

**Must NOT modify:**

- `apps/api/app/shared/storage/client.py`, `tests/integration/test_storage.py` — run as unchanged regressions.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH.

---

## Task T11: Private profile, publication, and automatic privacy

> **Status:** not started
> **Verification:** tdd
> **Effort:** l
> **Priority:** high
> **Depends on:** T1, T4, T7, T10
> **Satisfies REQs:** R9–R12, N1–N3
> **Footprint slice:** users domain service, repository, authorization policy, and atomic privacy notice
> **High-risk areas touched:** publication invariant, concurrent edits, outbox atomicity, cross-module authorization

### Description

Complete the `users` service and repository begun at profile bootstrap. A private draft stays editable by its owner, including before verification, but cannot be viewed publicly. Publication requires verified membership, display name, validated photo, nonempty one-line bio no longer than 160 characters, and at least one public HTTPS link. Saving an edit that removes a required field from a published profile must atomically save the edit, make it private, and enqueue exactly one notification.

### Test Plan

#### Test File(s)

- `apps/api/app/modules/users/tests/test_profile.py`
- `tests/integration/test_profile_privacy.py`
- `tests/integration/test_identity_mail.py`

#### Test Scenarios

##### Domain rules

- **Private draft** — GIVEN a newly registered unverified member WHEN editing or querying their own draft THEN changes persist, while an outsider's public lookup yields no profile/photo _(verifies R9, N1)_.
- **Publication gate** — GIVEN verified and unverified members with complete/incomplete profiles WHEN publishing THEN only a verified profile with name, validated photo, nonempty one-line bio of at most 160 characters, and at least one public HTTPS link becomes visible _(verifies R10)_.
- **Invalid fields** — GIVEN malformed or non-HTTPS links, overlong/multiline bio, or an unvalidated photo reference WHEN saved/published THEN typed errors or a private draft result preserve the invariant _(verifies R9–R10, N1)_.
- **Automatic privacy** — GIVEN a published profile WHEN a required item is removed THEN the edit persists, visibility becomes private in the same transaction, and one privacy-notice outbox event is stored _(verifies R11–R12)_.
- **Mail outage** — GIVEN unavailable SMTP WHEN that edit commits THEN privacy and the owner notice state are durable; retry sends one email without repeating the privacy transition _(verifies R12, N2–N3)_.
- **Manual withdrawal and republish** — GIVEN a published profile WHEN the owner unpublishes and later republishes THEN the first transition is immediate and the latter rechecks verification/completeness _(verifies R11)_.
- **Concurrent writers** — GIVEN racing edits/publications WHEN row versions or locks resolve THEN no incomplete public profile survives and duplicate notices are not emitted _(verifies R11–R12, N3)_.

### Implementation Notes

- **Module(s):** `users` domain, repository, policies; integration with named `auth.MemberAccess` service, outbox, and photo adapter.
- **Pattern reference:** `apps/api/app/modules/health/` feature layout and T6 `users.ProfileBootstrap` seam.
- **Key decisions:** A1–A2, A7–A8. Keep persistence in the users repository and authorization in a named policy. Use a PostgreSQL transaction/locking strategy for profile and outbox state; use opaque photo IDs.
- **Libraries:** SQLAlchemy async, existing typed domain errors.
- **High-risk callouts:** RED → GREEN → REFACTOR. Start with failing service tests. Email delivery is not in the edit transaction, but the encrypted outbox record is.

### Scope Boundaries

- No HTTP/GraphQL transport, frontend state, or public image URL here.
- No direct import of the auth repository; consume named member-access interface.

### Files Expected

**New files:**

- `apps/api/app/modules/users/policies.py` and `tests/test_profile.py` — named authorization and domain tests.

**Modified files:**

- `apps/api/app/modules/users/repository.py`, `service.py`, `models.py` — extend T6 bootstrap into full profile lifecycle.
- `tests/integration/test_profile_privacy.py`, `tests/integration/test_identity_mail.py` — transactional privacy and notification cases.

**Must NOT modify:**

- `apps/api/app/modules/auth/repository.py` — cross-module repository boundary.
- `apps/api/app/shared/storage/client.py` and `tests/integration/test_storage.py` — storage regressions.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH.

---

## Task T12: Profile REST, GraphQL reads, and gated photo delivery

> **Status:** not started
> **Verification:** test-after
> **Effort:** l
> **Priority:** high
> **Depends on:** T9, T11
> **Satisfies REQs:** R9–R11, N1, N4
> **Footprint slice:** users transport, GraphQL read composition, API assembly
> **High-risk areas touched:** private reads, photo withdrawal, API/GraphQL contract

### Description

Add thin REST profile actions and image delivery, plus read-only Strawberry GraphQL owner/public queries. Resolve visibility on every read, returning `null` for private or unknown public profiles and a safe authorization error for unauthorized owner reads. Keep private/unknown photo responses indistinguishable and uncached.

### Test Plan

#### Test File(s)

- `apps/api/app/modules/users/tests/test_routes.py`
- `apps/api/app/modules/users/tests/test_graphql.py`
- `tests/integration/test_profile_privacy.py`
- `apps/api/app/modules/health/tests/test_routes.py` (run unchanged)

#### Test Scenarios

##### Transport and privacy

- **Owner actions** — GIVEN owner and non-owner requests WHEN editing/publishing/unpublishing THEN only the owner succeeds; 401/403/409/422 are safe and documented as appropriate _(verifies R9–R11, N1)_.
- **GraphQL visibility** — GIVEN owner, visitor, published, private, and unknown profiles WHEN querying THEN owner sees their draft, a visitor sees only published fields, and private/unknown public results are `null` without private-field leakage _(verifies R9–R11, N1, N4)_.
- **Photo read** — GIVEN public, private, and nonexistent photos WHEN requesting via API THEN only authorized reads succeed with `Cache-Control: no-store`; private/unknown outsiders get the same 404 and direct storage access is denied _(verifies N1)_.
- **Immediate withdrawal** — GIVEN a previously published profile WHEN a required edit or unpublish commits THEN the next public GraphQL and photo reads reveal nothing, including through a prior API URL _(verifies R11, N1)_.
- **Query limits** — GIVEN deep or unapproved GraphQL operations WHEN sent THEN allowlist/depth controls reject them safely; profile mutations are unavailable _(verifies N1, N4)_.

##### Regression guards

- **Health-only factory** — GIVEN injected health dependencies WHEN existing health tests run THEN the live/ready contracts and bounded readiness remain unchanged _(guards `main.py` composition)_.

### Implementation Notes

- **Module(s):** users REST routes, Pydantic schemas, Strawberry query resolvers, app composition.
- **Pattern reference:** health route schemas and T9 auth route composition.
- **Key decisions:** A8–A10. Recheck current visibility in service on every photo request; never redirect to a durable storage URL. Keep GraphQL read-only and Pydantic response fields explicit. T13 generates downstream contracts.
- **Libraries:** FastAPI, Pydantic, Strawberry GraphQL.
- **High-risk callouts:** Distinguish owner auth errors from public `null` while making outsider private/absent photo responses identical. No cacheable image response.

### Scope Boundaries

- Do not add GraphQL mutations or duplicate publication rules in resolvers/routes.
- Do not alter health routes or health-only test injection path.

### Files Expected

**New files:**

- `apps/api/app/modules/users/routes.py`, `graphql.py`, `schemas.py` — thin transports.
- `apps/api/app/modules/users/tests/test_routes.py`, `test_graphql.py` — transport verification.

**Modified files:**

- `apps/api/app/main.py` — compose users endpoints and read schema.
- `tests/integration/test_profile_privacy.py` — end-to-end read and photo withdrawal assertions.

**Must NOT modify:**

- `apps/api/app/modules/health/routes.py`, `service.py`, `tests/test_routes.py` — run unchanged.
- `apps/api/app/shared/storage/client.py` and `tests/integration/test_storage.py`.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH.

---

## Task T13: Generated REST and GraphQL contracts

> **Status:** not started
> **Verification:** checklist
> **Effort:** m
> **Priority:** high
> **Depends on:** T9, T12
> **Satisfies REQs:** N4
> **Footprint slice:** generated schemas/types and isolated quality gate
> **High-risk areas touched:** contract drift, frontend type safety, CI parity

### Description

Extend the existing contract generation/check path to include Strawberry's GraphQL schema and operation types alongside OpenAPI. The checked-in artifacts must be reproducible, and the quality gate must fail when either source schemas or generated clients drift.

### Verification Checklist

- [ ] Generate the REST schema and typed client from current auth/profile routes; verify identity actions and photo responses appear, while existing health response shapes remain unchanged _(verifies N4)_.
- [ ] Generate GraphQL schema and operation types from the actual read schema; verify private-owner/public profile selections typecheck in strict web TypeScript _(verifies N4)_.
- [ ] Change a source REST or GraphQL field without regeneration in an isolated check and confirm the contract gate fails; restore the source after the drill _(guards source-only drift)_.
- [ ] Change a generated REST or GraphQL artifact without changing the source and confirm the gate fails; restore the artifact _(guards generated-only drift)_.
- [ ] Run `scripts/quality/contracts.sh` and the applicable quality steps from `scripts/quality/run.sh`; GraphQL gate is active and WebSocket checks remain explicitly not applicable _(verifies N4; guards CI parity)_.
- [ ] Confirm the shared CI script and security scan still cover pinned dependencies and generated outputs without modifying the workflow or security script _(guards ARCH touched-but-unchanged files)_.

### Implementation Notes

- **Module(s):** contract package and quality scripts.
- **Pattern reference:** existing `packages/contracts` generation and `scripts/quality/contracts.sh`.
- **Key decisions:** A9. Generate from running/source API definitions; never hand-maintain duplicate response interfaces. Keep generator deterministic in the isolated check environment.
- **Libraries:** pinned OpenAPI and GraphQL codegen tooling from T2.
- **High-risk callouts:** A generated artifact is not proof of sync unless both direction-of-drift checks pass. Preserve the existing health contract.

### Scope Boundaries

- Do not implement UI or hand-author client model types.
- Do not add a WebSocket feature or alter CI/security scripts that already call the shared gate.

### Files Expected

**New files:**

- `packages/contracts/schema.graphql` and `packages/contracts/src/graphql.generated.ts` — generated GraphQL artifacts.

**Modified files:**

- `packages/contracts/package.json`, `openapi.json`, `src/generated.ts` — generation command and REST artifact.
- `scripts/quality/contracts.sh`, `scripts/quality/run.sh` — two-schema drift check.
- `package.json`, `package-lock.json`, `apps/web/package.json` — only if required to pin/check generation tooling.

**Must NOT modify:**

- `.github/workflows/quality.yml`, `scripts/quality/security.sh`, `infra/docker/web.Dockerfile`, `infra/docker/browser.Dockerfile` — run as parity regressions.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH.

---

## Task T14: Typed web identity and profile state

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T13
> **Satisfies REQs:** R3–R12, N1, N4
> **Footprint slice:** generated-contract consumers and TanStack Query state
> **High-risk areas touched:** stale verification/privacy cache, CSRF, upload failure

### Description

Build typed identity and profile clients/hooks against generated REST and GraphQL contracts. Keep server state in TanStack Query, send cookie credentials and CSRF on unsafe actions, and invalidate identity/profile reads on sign-out, reset, publish, unpublish, and automatic privacy transitions.

### Test Plan

#### Test File(s)

- `apps/web/src/identity/client.test.ts`, `useIdentity.test.tsx`
- `apps/web/src/profiles/client.test.ts`, `useProfile.test.tsx`
- Existing `apps/web/src/connectivity/` tests (run unchanged)

#### Test Scenarios

##### Client state

- **Generated contract use** — GIVEN auth and profile requests WHEN compiled in strict TypeScript THEN payloads/results derive from generated REST/GraphQL types, with no hand-maintained duplicate response interfaces _(verifies N4)_.
- **Cookie and CSRF** — GIVEN a signed-in browser WHEN unsafe actions run THEN same-origin credentials and current CSRF value are sent; absent/expired CSRF produces a safe failure without a partial optimistic state _(verifies R3, N1)_.
- **Identity invalidation** — GIVEN verification, sign-out, or successful password reset WHEN settled THEN session and verified-member queries are invalidated; stale protected controls disappear on error or revocation _(verifies R3–R7, N1)_.
- **Privacy invalidation** — GIVEN publish, manual unpublish, or required-field removal WHEN settled THEN owner/public/photo queries reconcile with server visibility; cached public data is not retained after automatic privacy _(verifies R10–R12, N1)_.
- **Upload failure** — GIVEN expired staging authorization, rejected content, or failed finalization WHEN uploading THEN the client surfaces a recoverable error and never displays an unvalidated image as published _(verifies R9–R10, N1)_.
- **Connectivity regression** — GIVEN the existing connectivity request WHEN its tests run THEN connected/unavailable state remains unchanged _(guards existing app behavior)_.

### Implementation Notes

- **Module(s):** typed web request layer and query hooks.
- **Pattern reference:** existing `apps/web/src/connectivity/` and TanStack Query provider.
- **Key decisions:** A3, A8–A9. Use browser credentials rather than storing a bearer/session token. Invalidate affected query keys after the server response, with rollback or refetch on failure.
- **Libraries:** TanStack Query; generated contract package.
- **High-risk callouts:** RED → GREEN → REFACTOR. Model visibility as server state; do not trust an optimistic public flag.

### Scope Boundaries

- No new pages, layout, or generated imagery here.
- No manual API response types or direct public storage URLs.

### Files Expected

**New files:**

- `apps/web/src/identity/client.ts`, `useIdentity.ts` and their tests — typed identity calls/state.
- `apps/web/src/profiles/client.ts`, `useProfile.ts` and their tests — typed profile calls/state.

**Modified files:**

- None expected; only adjust existing provider wiring if tests demonstrate it is necessary.

**Must NOT modify:**

- `apps/web/src/connectivity/`, `apps/web/src/App.test.tsx`, `tests/browser/connectivity.spec.ts` — unchanged regression surface.
- `packages/contracts/src/generated.ts`, `graphql.generated.ts` — regenerate in T13, never hand-edit here.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH.

---

## Task T15: Accessible account and recovery screens

> **Status:** not started
> **Verification:** ui
> **Effort:** l
> **Priority:** high
> **Depends on:** T9, T14
> **Satisfies REQs:** R1–R8, N1–N2
> **Footprint slice:** web identity routes/forms and browser verification
> **High-risk areas touched:** account enumeration, accessible form flow, connectivity routing

### Description

Add mobile-first registration, sign-in, email verification/resend, and password recovery screens using T14 state. Show safe generic registration/reset responses and clear expired/limited-link paths. Verification links are displayed via a GET landing page but consumed only through explicit POST action. Retain the existing connectivity page at `/`.

### Verification Checklist

- [ ] At desktop and mobile widths, register/sign-in/verify/resend/reset forms have visible labels, error summaries, focus order, keyboard operation, and announced status messages _(verifies R1–R8)_.
- [ ] Existing/new registration and known/unknown reset addresses display the same generic success copy; wrong-account details are never shown _(verifies R2, R6, N1–N2)_.
- [ ] Verification/recovery links opened by GET do not consume tokens; explicit confirmation does, while expired, superseded, and rate-limited paths explain safe next steps _(verifies R4–R7)_.
- [ ] Sign-in creates a usable private-profile navigation path, and successful reset returns to sign-in while other signed-in devices are revoked _(verifies R3, R7, R9)_.
- [ ] Component tests cover submit/error/loading/accessible notice seams; browser flow covers mobile and keyboard use in the isolated environment _(verifies R1–R8, N1)_.
- [ ] `/` still shows the existing connected/unavailable page; existing App and connectivity browser tests pass unchanged _(guards ARCH routing regression)_.

#### Testable Seams

- Explicit form submission and status text; safe generic response; link-consumption action; focus/error state; route-to-private-profile; `/` connectivity fallback.

### Implementation Notes

- **Module(s):** identity UI, app routes, browser spec.
- **Pattern reference:** existing `App.tsx`, `styles.css`, `apps/web/src/connectivity/`; `docs/source/inspiration.md` for direction only.
- **Key decisions:** A3–A4, A9. Use generated clients/hooks from T14. Treat backend validation and throttling as authority; client checks improve guidance only.
- **Libraries:** React, TanStack Query, approved router; semantic native form elements.
- **High-risk callouts:** Never put a recovery token into logs, analytics, or a rendered error. Exercise the same-origin secure-cookie local path in browser tests.

### Scope Boundaries

- No profile editor/public page yet; T16 owns those.
- No branding/layout/content copied from inspiration sites; no generated image asset.

### Files Expected

**New files:**

- `apps/web/src/identity/` form/page components and component tests.
- `tests/browser/member-identity.spec.ts` — account browser paths, extended in T16.

**Modified files:**

- `apps/web/src/App.tsx`, `main.tsx`, `styles.css` — routing and accessible page shell.
- `apps/web/package.json`, `package-lock.json` — pinned router tooling if not already added in T13.

**Must NOT modify:**

- `apps/web/src/connectivity/`, `apps/web/src/App.test.tsx`, `tests/browser/connectivity.spec.ts` — regression guards.
- `infra/docker/web.conf`, `infra/docker/web.Dockerfile`, `infra/docker/browser.Dockerfile` — test existing proxy/build behavior.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH.

---

## Task T16: Private editor and public profile UI

> **Status:** not started
> **Verification:** ui
> **Effort:** l
> **Priority:** high
> **Depends on:** T12, T14, T15
> **Satisfies REQs:** R9–R12, N1
> **Footprint slice:** owner/private and visitor/public profile routes
> **High-risk areas touched:** immediate privacy feedback, inaccessible private photos, mobile/keyboard flows

### Description

Build the owner draft editor, photo upload, publication/unpublication controls, and public profile view. The owner can sign in and edit while private. Removing a required item from a published profile saves the change, switches to private immediately, and displays an accessible notification that email will follow. Visitors see only currently published profile content.

### Verification Checklist

- [ ] Owner can edit a private draft after sign-in, including while unverified; visitor gets no private details or photo _(verifies R9, N1)_.
- [ ] Editor guides display name, validated photo, one-line bio ≤160 characters, and HTTPS link requirements; only a verified complete profile can publish _(verifies R10)_.
- [ ] Upload UI handles valid image, oversize/type error, expiry, and failed finalize with clear recovery; it never renders an unvalidated staged image as published _(verifies R9–R10, N1)_.
- [ ] Removing a required item from a published profile saves the edit, immediately displays a private-state notice, and removes the public page/photo on refetch; mail failure does not undo the edit _(verifies R11–R12)_.
- [ ] Manual unpublish and later republish work; republish rechecks completeness and verification _(verifies R11)_.
- [ ] Mobile and keyboard paths support edit, upload, publish/unpublish, and notices; component tests exercise status/error/loading seams and browser test confirms outsider privacy _(verifies R9–R12, N1)_.
- [ ] Existing connectivity page and account screens still work; unchanged App/connectivity tests pass _(guards ARCH UI regression)_.

#### Testable Seams

- Owner versus visitor queries, form validation messages, upload status, publication control state, auto-private notice, immediate public/photo refetch, and keyboard focus after status change.

### Implementation Notes

- **Module(s):** profiles UI and browser path.
- **Pattern reference:** T15 route shell, T14 query hooks, existing app styling; `docs/source/inspiration.md` for direction only.
- **Key decisions:** A8–A9. Display the server's privacy decision; local completeness checks are guidance, not authority. Public image rendering uses gated API reads only.
- **Libraries:** React, TanStack Query, generated GraphQL/REST clients.
- **High-risk callouts:** Avoid stale public profile/photo caches after required-field removal. Keep private photos out of DOM data, analytics, and direct object URLs.

### Scope Boundaries

- No staff moderation, product-launch UI, or image generation.
- No hand-maintained response types or direct storage links.

### Files Expected

**New files:**

- `apps/web/src/profiles/` editor/public-view components and component tests.

**Modified files:**

- `apps/web/src/App.tsx`, `styles.css` — profile routes and responsive presentation.
- `tests/browser/member-identity.spec.ts` — profile/privacy browser flow.

**Must NOT modify:**

- `apps/web/src/connectivity/`, `apps/web/src/App.test.tsx`, `tests/browser/connectivity.spec.ts`.
- `packages/contracts/src/generated.ts`, `graphql.generated.ts` — generation-owned artifacts.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH.

---

## Task T17: Documentation, recovery drills, and full quality gate

> **Status:** not started
> **Verification:** checklist
> **Effort:** m
> **Priority:** high
> **Depends on:** T1–T16
> **Satisfies REQs:** R1–R12, N1–N4
> **Footprint slice:** operator documentation and final cross-system evidence
> **High-risk areas touched:** production recovery, isolation, regression coverage

### Description

Document the implemented account and profile lifecycle, mail/recovery operations, private photo boundary, local secure-cookie behavior, and forward migration recovery. Record approved architecture decisions in two ADRs, then run the complete isolated quality gate and failure drills before marking the slice complete.

### Verification Checklist

- [ ] `README.md` and `docs/development.md` describe registration/verification, 60-minute superseding links, recovery/all-device revocation, private-by-default profiles, publish/auto-private notices, private photos, local same-origin cookies, and operational mail recovery _(verifies R1–R12, N1)_.
- [ ] ADR 0005 records session/recovery/password decisions and ADR 0006 records profile privacy, gated media, and encrypted durable email decisions; both match the shipped behavior _(verifies N1–N3)_.
- [ ] Run `scripts/quality/run.sh` in its isolated Compose project and retain evidence for Ruff, formatter, typing, pytest, contracts, frontend build/tests, browser checks, and security checks _(verifies N1–N4)_.
- [ ] Drill missing PostgreSQL, Redis, mail, and pending-schema conditions: each fails closed or reports not-ready safely, with no secret/private-data leakage, and recovery succeeds without resetting developer data _(verifies N1–N3)_.
- [ ] Run unchanged preparation/startup/health/storage/connectivity/browser regressions; verify current migration-head readiness, bounded health, worker/scheduler progress, and `/` connectivity remain intact _(guards all ARCH touched-but-unchanged hotspots)_.
- [ ] Verify no forbidden edits to source context, foundation migration, CI/security scripts, or unrelated feature modules; inspect git diff for secrets, generated drift, and accidental public object URLs _(verifies N1–N4)_.

### Implementation Notes

- **Module(s):** operator docs, ADRs, full-system verification.
- **Pattern reference:** existing `README.md`, `docs/development.md`, `docs/adr/`, `scripts/quality/run.sh`.
- **Key decisions:** A1–A10. Capture concrete command/results and failure-mode evidence, not just a checklist tick. Route any discovered product-code fix back to its owning earlier task and rerun affected checks.
- **Libraries:** existing isolated Compose/check tooling.
- **High-risk callouts:** Preserve developer databases and volumes. Run failure drills only against the isolated check environment; no destructive migration or data reset.

### Scope Boundaries

- No new feature behavior or opportunistic refactor in this closeout task.
- QA planning/execution is a separate workflow after implementation, not a substitute for task verification.

### Files Expected

**New files:**

- `docs/adr/0005-member-sessions-recovery.md`, `docs/adr/0006-profile-privacy-email.md` — decision records.

**Modified files:**

- `README.md`, `docs/development.md` — developer/operator guidance.

**Must NOT modify:**

- `apps/api/alembic/versions/0001_foundation.py`, `apps/api/app/bootstrap.py`, `apps/api/alembic/env.py` — foundation and startup boundary.
- `.github/workflows/quality.yml`, `scripts/quality/security.sh`, existing health/storage/connectivity tests — run unchanged.
- `AGENTS.md`, `CLAUDE.md`, `docs/source/`, linked REQ and ARCH — protected inputs.

---
