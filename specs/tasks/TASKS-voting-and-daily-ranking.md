# Tasks

## Task T1: Add vote and ranking persistence schema

> **Status:** complete
> **Verification:** test-after
> **Effort:** l
> **Priority:** high
> **Depends on:** None
> **Satisfies REQs:** R2, R3, R8, R9, R10, N3
> **Footprint slice:** New: vote module models/tests and additive Alembic migration; supporting real-PostgreSQL schema integration test.
> **High-risk areas touched:** Votes persistence and policy (H); production migration and archive integrity (H).

### Description

Create durable PostgreSQL tables for vote history, idempotency receipts, risk flags, reviewer decisions, daily ranking snapshots and entries, and the persisted voting start date. The additive migration must preserve all existing product/account data and prevent an automatic downgrade from deleting vote or audit records.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/votes/tests/test_models.py`
- `tests/integration/test_vote_schema.py`

#### Test Scenarios

##### Mapping and Constraints
- **maps all vote feature records** — GIVEN the votes SQLAlchemy mappings WHEN the mapping suite runs THEN vote, receipt, flag, decision, snapshot, entry, and start-date tables expose the required fields and relationships _(supports R2, R3, R8, R9, R10)_
- **enforces active vote and receipt uniqueness** — GIVEN the model metadata WHEN constraints are inspected THEN one active vote per member/product and one receipt per member/idempotency key are enforced by PostgreSQL constraints/indexes _(supports R2, R3, N3)_
- **enforces snapshot uniqueness** — GIVEN a snapshot and entries WHEN constraints are inspected THEN each date has one snapshot and each product/rank appears at most once within it _(supports R8)_

##### Migration Compatibility
- **upgrades from the current head without losing existing data** — GIVEN a disposable database at revision `0015_public_catalog_search` with account and product rows WHEN migration `0016` is applied THEN the vote schema and indexes exist and the seeded rows remain unchanged _(supports R8, R10; guards product/account schema regression)_
- **migrates a fresh database to head** — GIVEN an empty disposable database WHEN the full migration chain runs THEN the database reaches the new head and all vote tables are usable _(supports R2, R8)_
- **refuses destructive downgrade** — GIVEN a database with vote/audit data WHEN the new migration downgrade is invoked THEN it refuses to silently drop the data _(supports R8, R9, R10)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/votes`; `apps/api/alembic/versions`.
- **Pattern reference:** `apps/api/app/modules/launches/models.py`, `apps/api/app/modules/launches/tests/test_models.py`, `apps/api/alembic/versions/0015_public_catalog_search.py`, and `tests/integration/test_production_migrations.py`.
- **Key decisions:** PostgreSQL constraints are authoritative; history and audit are retained; snapshots are unique per UTC date and immutable after creation.
- **Libraries:** Existing SQLAlchemy 2, Alembic, pytest, and PostgreSQL integration stack.
- **High-risk callouts:** M/H persistence and archive invariants are covered by mapping constraints and real migration tests against both an existing schema and a fresh schema.

### Scope Boundaries

- Do NOT implement vote service rules, HTTP routes, ranking projection, or reviewer operations.
- Do NOT rewrite existing migrations or change existing product/account tables except as required for declared foreign keys.
- Only implement the persistence schema and forward-safe migration described in ARCH.

### Files Expected

**New files:**
- `apps/api/app/modules/votes/__init__.py` (feature module package)
- `apps/api/app/modules/votes/tests/__init__.py` (feature test package)
- `apps/api/app/modules/votes/models.py` (vote, receipt, review, snapshot, and enabled-date mappings)
- `apps/api/alembic/versions/0016_votes_and_daily_rankings.py` (additive schema revision)
- `apps/api/app/modules/votes/tests/test_models.py` (mapping and constraint guards)
- `tests/integration/test_vote_schema.py` (real PostgreSQL migration coverage; supporting addition approved during task planning)

**Modified files:**
- None.

**Must NOT modify:**
- `apps/api/app/modules/products/models.py` (existing product schema)
- `apps/api/app/modules/launches/models.py` (existing booking schema)
- Existing Alembic revisions (migration history is append-only)

### TDD Sequence (optional)

1. Add mapping-level constraints and model tests.
2. Add revision `0016` and verify both fresh and existing database migration paths.
3. Verify downgrade protection with retained vote/audit data.

---

## Task T2: Implement vote lifecycle and concurrency rules

> **Status:** complete
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R1, R2, R3, R4, R11, N3
> **Footprint slice:** New: votes repository, service, policies, service/repository/concurrency tests. Uses T1 vote and receipt models.
> **High-risk areas touched:** Votes persistence and policy (H); Products/launches boundary (H).

### Description

Implement the transactional vote and withdrawal domain behavior in the votes module. Enforce verified-member eligibility, no self-voting, launched-product/day cutoff rules, one active vote, idempotent retries, and deterministic concurrent actions while keeping the Products repository behind a named service port.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/votes/tests/test_service.py`
- `apps/api/app/modules/votes/tests/test_repository.py`
- `apps/api/app/modules/votes/tests/test_concurrency.py`

#### Test Scenarios

##### Eligibility and Lifecycle
- **accepts an eligible vote** — GIVEN a verified, unsuspended member and another member's launched product before cutoff WHEN the member votes THEN one active vote, its receipt, and its outbox event are committed together _(verifies R1–R3)_
- **rejects ineligible vote attempts without state changes** — GIVEN an unverified or suspended member, product owner, unlaunched product, closed day, or disabled write switch WHEN the service handles a vote THEN it returns the typed domain error and writes no active vote/receipt/event _(verifies R1, R4, R11; REQ edge cases)_
- **withdraws only an active vote before cutoff** — GIVEN the member's active vote WHEN they withdraw before cutoff THEN its history state changes and one withdrawal event is committed; no-active and cutoff/after-cutoff attempts are rejected _(verifies R2, R4)_

##### Retry and Concurrency
- **replays the same idempotent command** — GIVEN a committed vote and its idempotency key WHEN the same request retries THEN the original result is returned without another active vote or outbox event _(verifies R2, R3; REQ retry edge case)_
- **rejects key reuse with a different request** — GIVEN a receipt for one command WHEN the same key is used with another fingerprint THEN the service returns a conflict and does not mutate vote state _(verifies R3)_
- **flags high-risk activity without removing a confirmed vote** — GIVEN the risk policy identifies suspicious activity and any required challenge succeeds WHEN the command commits THEN the vote remains active, a pending review flag is recorded, and the flag event is durable _(verifies R9, R11)_
- **serializes concurrent vote actions** — GIVEN concurrent cast/cast and cast/withdraw requests for the same member/product WHEN PostgreSQL transactions complete THEN at most one active vote remains and the last committed action determines the state _(verifies R3, N3; ARCH concurrency stress scenario)_

##### Transaction Failure
- **rolls back partial state when outbox insertion fails** — GIVEN an outbox failure during a vote transition WHEN the transaction rolls back THEN neither vote nor idempotency receipt persists and a retry can succeed _(verifies R11; REQ command-failure edge case)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/votes`; consume the named Products voting-context interface.
- **Pattern reference:** `apps/api/app/modules/launches/service.py`, `apps/api/app/modules/launches/repository.py`, `apps/api/app/modules/launches/tests/test_concurrency.py`, and `apps/api/app/modules/products/policies.py`.
- **Key decisions:** A database partial unique constraint is the final one-active-vote guard; serialize each member/product pair; latest committed action wins; same idempotency key with changed fingerprint conflicts; write state and outbox event in one transaction.
- **Libraries:** Existing async SQLAlchemy, FastAPI domain-policy patterns, pytest, and PostgreSQL integration stack.
- **High-risk callouts:** Eligibility and concurrency are business/security invariants; service tests cover all rejection paths and PostgreSQL concurrency tests cover race behavior.

### Scope Boundaries

- Do NOT implement REST/GraphQL transport, Turnstile HTTP verification, Redis rank projection, or frontend behavior.
- Do NOT automatically invalidate a vote because it is flagged or the member account is later suspended.
- Only implement durable vote lifecycle and typed domain errors; transport mapping belongs to T3.

### Files Expected

**New files:**
- `apps/api/app/modules/votes/repository.py` (vote/receipt persistence, locks, and constraint-aware operations)
- `apps/api/app/modules/votes/service.py` (eligibility, cast/withdrawal lifecycle, idempotency, transactional outbox)
- `apps/api/app/modules/votes/policies.py` (named vote eligibility and member authorization errors/policies)
- `apps/api/app/modules/votes/tests/test_service.py` (domain behavior and rollback tests)
- `apps/api/app/modules/votes/tests/test_repository.py` (persistence and idempotency constraints)
- `apps/api/app/modules/votes/tests/test_concurrency.py` (PostgreSQL concurrent action coverage)

**Modified files:**
- None.

**Must NOT modify:**
- `apps/api/app/modules/products/repository.py` (cross-module access uses named Products service port)
- `apps/api/app/modules/notifications/live.py` (private notification transport remains unchanged)
- `apps/web/src/launches/PublicLaunchCard.tsx` (generic discovery card remains unchanged)

### TDD Sequence (optional)

1. Add failing eligibility, state-transition, and idempotency service tests.
2. Implement repository constraints/locking and service behavior until green.
3. Add PostgreSQL race and transactional rollback scenarios, then refactor without weakening database guards.

---

## Task T3: Expose vote commands with risk escalation

> **Status:** complete
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T2
> **Satisfies REQs:** R1, R2, R3, R4, R9, R11, N3
> **Footprint slice:** New: votes request/response schemas, REST routes, and route tests. Modified: API settings and route mounting.
> **High-risk areas touched:** Votes persistence and policy (H); production configuration and deployment (H).

### Description

Expose the vote service through authenticated REST cast/withdrawal commands and add server-side risk escalation using configured velocity signals and Cloudflare Turnstile. Keep the write switch disabled by default, protect Turnstile secrets as server-only configuration, and return safe actionable errors without claiming uncommitted state.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/votes/tests/test_routes.py`

#### Test Scenarios

##### Command Contracts
- **casts a vote using the authenticated session and idempotency key** — GIVEN an eligible member request WHEN `POST /api/v1/votes` is called THEN the route passes actor, product, key, and optional challenge token to the service and returns its confirmed response _(verifies R1–R3)_
- **withdraws a vote using the authenticated session and idempotency key** — GIVEN an eligible member request WHEN `DELETE /api/v1/votes/{product_id}` is called THEN the route delegates the command and returns the confirmed state _(verifies R2–R4)_
- **requires authentication and command key** — GIVEN a guest request or missing/malformed idempotency key WHEN either command is called THEN the route rejects it and makes no service mutation _(verifies R1, R3)_

##### Risk Challenge and Errors
- **challenges only actions classified high-risk** — GIVEN a low-risk command and then a high-risk command WHEN both reach the route/service boundary THEN the low-risk action does not call Turnstile and the high-risk action requires backend verification before acceptance _(verifies R9)_
- **fails closed on invalid or unavailable required challenge** — GIVEN a high-risk command with invalid token or unavailable verifier WHEN the command is attempted THEN it is rejected without reporting success or mutating confirmed vote state _(verifies R9, R11; ARCH Turnstile failure scenario)_
- **maps typed command errors to safe HTTP responses** — GIVEN each eligibility, conflict, cutoff, rate-limit, challenge, and database failure WHEN the route handles it THEN it returns the documented safe status/message and no stack trace or secret _(verifies R1–R4, R11)_
- **keeps write and Turnstile configuration safe by default** — GIVEN default settings and production environment values WHEN settings are loaded THEN vote writes default off and the Turnstile secret is represented as a secret and never returned in errors/log fields _(verifies R11; guards production configuration risk)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/votes`; mount through `apps/api/app/main.py` under the existing product/launch feature gates.
- **Pattern reference:** `apps/api/app/modules/launches/routes.py`, `apps/api/app/modules/launches/schemas.py`, `apps/api/app/modules/launches/tests/test_routes.py`, `apps/api/app/shared/config/settings.py`, and `apps/api/app/shared/email/resend.py` for async HTTP client conventions.
- **Key decisions:** Routes remain thin; domain checks stay in T2 service. Turnstile verification happens server-side only for high-risk requests and fails closed when required verification cannot complete. Exact signal thresholds remain configurable/open per ARCH; do not invent production values.
- **Libraries:** Existing FastAPI/Pydantic/settings stack and async HTTP client already used by the API; no new dependency without an architecture update.
- **High-risk callouts:** Keep Turnstile secret/token and raw network identifiers out of responses/logs. Route tests cover error mapping and no false success on challenge failure.

### Scope Boundaries

- Do NOT implement reviewer decision routes (T7), the public live ticket/WebSocket (T9), or GraphQL reads (T8).
- Do NOT enable vote writes by default or weaken authentication, CSRF, verified-email, or service-level eligibility checks.
- Only implement REST vote/withdrawal transport, settings, and router wiring.

### Files Expected

**New files:**
- `apps/api/app/modules/votes/schemas.py` (bounded request/response schemas)
- `apps/api/app/modules/votes/routes.py` (member vote command routes)
- `apps/api/app/modules/votes/tests/test_routes.py` (command, risk, error, and config behavior)

**Modified files:**
- `apps/api/app/shared/config/settings.py` (default-off vote-write and server-only Turnstile/risk configuration)
- `apps/api/app/main.py` (mount vote command routes under product/launch availability)

**Must NOT modify:**
- `apps/api/app/modules/notifications/live.py` (private notification socket remains unchanged)
- `apps/api/app/modules/products/repository.py` and `apps/api/app/modules/launches/service.py` (use existing feature service boundaries)
- `apps/web/src/launches/PublicLaunchCard.tsx` (generic public card is not part of command transport)

### TDD Sequence (optional)

1. Add failing route contract and error-mapping tests using injected vote-service/verifier fakes.
2. Implement request schemas, route delegation, and server-side challenge integration.
3. Add route/config wiring and verify authentication, default-off behavior, and safe failure responses.

---

## Task T4: Emit a durable event when a product launches

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T1
> **Satisfies REQs:** R5, R12
> **Footprint slice:** Modified: Products service publication transaction and its launch service regression tests.
> **High-risk areas touched:** Products and launches (H); outbox and worker (H).

### Description

Extend successful scheduled-product publication to emit `product.launched.v1` in the same transaction as the product transition. Expose a named, safe voting context through ProductService so the votes module can check launch date, owner, and public status without importing the Products repository.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_service.py` (new test module; this path is named in ARCH but is currently absent)
- `apps/worker/tests/test_launch_worker.py`

#### Test Scenarios

##### Publication Event
- **emits one event on the successful launch transition** — GIVEN a scheduled product whose booking is due WHEN ProductService publishes it THEN the product becomes launched and one `product.launched.v1` event is committed in the same transaction _(supports R5, R12)_
- **publication replay does not duplicate the event** — GIVEN a product already launched by the first call WHEN publication is replayed THEN the event count and product version remain unchanged _(supports R5; guards launch idempotency)_
- **non-launch outcomes do not emit launch membership** — GIVEN a missed, suspension-blocked, or not-yet-due booking WHEN publication is attempted THEN no launched event is inserted _(supports R5)_
- **event failure rolls back launch visibility** — GIVEN outbox insertion fails WHEN the launch transaction completes THEN the product remains unlaunched and retry can publish it once _(supports R11; ARCH outbox failure scenario)_

##### Named Product Port and Privacy
- **returns voting context only for launched public products** — GIVEN launched and private products WHEN the named ProductService port is called THEN it returns only launched product ID, owner, and launch date, and withholds private products and private fields _(supports R12; guards `apps/api/app/modules/products/repository.py`)_
- **preserves UTC publication behavior** — GIVEN existing booking boundary cases WHEN publication runs THEN its UTC date/cutoff behavior remains unchanged _(guards `apps/api/app/modules/launches/service.py`)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/products`.
- **Pattern reference:** `apps/api/app/modules/products/service.py`, `apps/api/app/modules/products/tests/test_launch_lifecycle.py`, and `apps/worker/tests/test_launch_worker.py`.
- **Key decisions:** Emit only after a successful launched transition; event shares its transaction; expose a named service port, never the Products repository.
- **Libraries:** Existing SQLAlchemy and transactional outbox.
- **High-risk callouts:** Product publication and event insertion must be atomic and idempotent; tests cover replay and failure rollback.

### Scope Boundaries

- Do NOT add vote/rank persistence or worker projection behavior here.
- Do NOT change product publication timing, booking capacity, or launch failure policy.
- Only add the safe product port and successful launch event described in ARCH.

### Files Expected

**Modified files:**
- `apps/api/app/modules/products/service.py` (transactional launched event and safe voting-context service port)
- `apps/api/app/modules/products/tests/test_service.py` (launch event and named voting-context tests; ARCH lists it as modified, but the path is absent in this checkout, so create it to honor the named footprint)
- `apps/worker/tests/test_launch_worker.py` (regression coverage for atomic publication wiring)

**Must NOT modify:**
- `apps/api/app/modules/products/repository.py` (public filtering remains its existing responsibility)
- `apps/api/app/modules/launches/service.py` (UTC scheduling policy remains unchanged)

### TDD Sequence (optional)

1. Add launch-event success, replay, and failure-rollback tests.
2. Add the named public voting-context port tests.
3. Implement ProductService changes and verify existing publication behavior remains green.

---

## Task T5: Maintain the live ranking projection from outbox events

> **Status:** not started
> **Verification:** test-after
> **Effort:** l
> **Priority:** critical
> **Depends on:** T2, T4
> **Satisfies REQs:** R5, R7, R11, R12, N1
> **Footprint slice:** New: worker vote-event tests. Modified: vote repository/service projection methods, typed event dispatcher, and worker wiring.
> **High-risk areas touched:** Outbox and worker (H); votes persistence and policy (H); public WebSocket and Redis (H).

### Description

Consume committed vote and product-launch events to keep a rebuildable Redis projection for the active UTC day. Include every launched product, including zero-vote products, apply the six-hour score and deterministic tie order, and publish minimal invalidation hints only after projection updates succeed.

### Test Plan

#### Test File(s)
- `apps/worker/tests/test_vote_worker.py`
- `apps/api/app/shared/events/tests/test_dispatcher.py`

#### Test Scenarios

##### Projection Updates
- **adds launch membership including zero-vote products** — GIVEN `product.launched.v1` for a public product WHEN the worker handles it THEN the product appears at the bottom of that date's rank until it has votes _(verifies R5, R12)_
- **applies vote changes idempotently** — GIVEN a committed cast, withdrawal, or invalidation event WHEN it is handled once or replayed THEN current count/score/order match PostgreSQL exactly and no duplicate contribution appears _(verifies R2, R5, R11)_
- **orders live results deterministically** — GIVEN equal-scoring products with differing counts/names/IDs WHEN the projection is read THEN it applies count, case-insensitive name, and ID tie-breaks _(verifies R5, R6)_

##### Recovery and Dispatch
- **rebuilds a missing projection from PostgreSQL** — GIVEN Redis has lost the current-day key WHEN the ranking projection is requested/rebuilt THEN every launched product and active vote is restored without exposing unpublished products _(verifies R5, R12; ARCH cache-loss scenario)_
- **retries while Redis is unavailable** — GIVEN a Redis publish/update failure WHEN an outbox event is consumed THEN the event is not acknowledged and a retry later converges the projection without losing the database vote _(verifies R7, R11; ARCH 30-second dependency outage)_
- **preserves existing outbox handlers** — GIVEN existing product, launch, notification, and email event types WHEN dispatcher registration is exercised THEN their existing routing/retry behavior is unchanged _(guards `apps/api/app/shared/events/tests/test_dispatcher.py` and `apps/worker/tests/test_launch_worker.py`)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/votes`, `apps/api/app/shared/events`, `apps/worker`.
- **Pattern reference:** `apps/api/app/shared/events/dispatcher.py`, `apps/api/app/shared/events/tests/test_dispatcher.py`, and `apps/worker/worker.py`.
- **Key decisions:** PostgreSQL/outbox is authoritative; Redis is rebuildable; handlers are idempotent; publish only minimal public invalidations; do not include voter identity.
- **Libraries:** Existing Redis, Dramatiq, SQLAlchemy, and typed outbox.
- **High-risk callouts:** Redis outage/retry and event dispatch regression scenarios cover the H-risk worker/projection paths.

### Scope Boundaries

- Do NOT create immutable cutoff snapshots in this task (T6).
- Do NOT add a new scheduler service or queue technology.
- Do NOT publish voter identity or unpublished product data to Redis/pub-sub.

### Files Expected

**New files:**
- `apps/worker/tests/test_vote_worker.py` (projection, rebuild, and event retry coverage)

**Modified files:**
- `apps/api/app/modules/votes/repository.py` (active vote/launch inputs and projection rebuild queries)
- `apps/api/app/modules/votes/service.py` (ranking projection and score update behavior)
- `apps/api/app/shared/events/dispatcher.py` (typed vote and product-launched handler registration)
- `apps/worker/worker.py` (wire projection worker and rebuild path)
- `apps/api/app/shared/events/tests/test_dispatcher.py` (regression coverage for existing event routing)

**Must NOT modify:**
- `apps/api/app/modules/notifications/live.py` (private notification socket stays account-scoped)
- `apps/worker/scheduler.py` (existing durable due-event poller is reused)
- `apps/web/src/launches/PublicLaunchCard.tsx` (ranking UI is a later task)

---

## Task T6: Freeze UTC daily ranking snapshots

> **Status:** not started
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T1, T2, T4, T5
> **Satisfies REQs:** R4, R5, R6, R8, R10, N1
> **Footprint slice:** Snapshot repository/service methods, stable cutoff-event scheduling/handling, and archive tests.
> **High-risk areas touched:** Votes persistence and policy (H); outbox and worker (H); Products and launches (H).

### Description

Schedule one idempotent snapshot event per ranked UTC launch date and persist the final order, score, and active vote count at 00:00 UTC. Archive reads use the snapshot for dates from the persisted voting start date and leave earlier dates in the existing unranked archive behavior.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/votes/tests/test_snapshots.py`
- `apps/worker/tests/test_vote_worker.py`

#### Test Scenarios

##### Snapshot Creation and Immutability
- **freezes the final ranking at cutoff** — GIVEN launched products and active votes at 23:59:59 UTC WHEN the due event runs at cutoff THEN one snapshot stores the exact deterministic rank, score, and counts _(verifies R4–R8)_
- **includes zero-vote products** — GIVEN at least one launched product with no active votes WHEN the snapshot is written THEN that product appears after all voted products _(verifies R5)_
- **replays one snapshot event safely** — GIVEN a completed snapshot WHEN the same stable event is delivered again THEN no duplicate header/entry is created and archived values remain identical _(verifies R8; ARCH duplicate-event scenario)_
- **does not rewrite archives after later invalidation** — GIVEN a closed snapshot WHEN staff later invalidates one of its votes THEN archive order/count/score remain unchanged _(verifies R8, R10)_

##### Date Compatibility and Recovery
- **preserves pre-voting archive behavior** — GIVEN a date before the persisted first-enabled UTC date WHEN archive reads run THEN they use existing ordering and return no fabricated vote/rank fields _(verifies R8, R12)_
- **catches up after worker downtime** — GIVEN the cutoff outbox event remained due while a worker was down WHEN it resumes THEN it creates the same single PostgreSQL-derived snapshot _(verifies R8; ARCH worker-down stress scenario)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/votes`, `apps/worker`.
- **Pattern reference:** `apps/api/app/shared/events/outbox.py`, `apps/api/app/modules/launches/tests/test_events.py`, and `apps/worker/tests/test_launch_worker.py`.
- **Key decisions:** UTC cutoff, stable event identity, atomic header/entry insert, unique date constraint, immutable closed archive, and no historical backfill before the persisted start date.
- **Libraries:** Existing SQLAlchemy, outbox, scheduler poller, and Dramatiq worker.
- **High-risk callouts:** Snapshot idempotence and archive immutability are guarded both at service/database boundaries and in event replay tests.

### Scope Boundaries

- Do NOT alter launch booking rules or rewrite prior archive ordering.
- Do NOT add weekly/monthly/all-time topic leaderboards.
- Only create/read daily snapshots for enabled voting dates.

### Files Expected

**New files:**
- `apps/api/app/modules/votes/tests/test_snapshots.py` (cutoff, archive, and immutability tests)

**Modified files:**
- `apps/api/app/modules/votes/repository.py` (atomic snapshot and archive persistence/read queries)
- `apps/api/app/modules/votes/service.py` (cutoff scheduling and snapshot domain behavior)
- `apps/worker/worker.py` (snapshot due-event handler)
- `apps/worker/tests/test_vote_worker.py` (cutoff event replay and recovery cases)

**Must NOT modify:**
- `apps/api/app/shared/events/outbox.py` and `apps/worker/scheduler.py` (existing due-event semantics are reused)
- `apps/api/app/modules/launches/service.py` (existing UTC booking semantics remain unchanged)

---

## Task T7: Add staff vote-review decisions and audit

> **Status:** not started
> **Verification:** tdd
> **Effort:** l
> **Priority:** high
> **Depends on:** T1, T2
> **Satisfies REQs:** R8, R9, R10, R11
> **Footprint slice:** Vote repository/service/policy and REST routes for pending review and explicit reviewer decisions; review tests.
> **High-risk areas touched:** Votes persistence and policy (H); production authorization (H).

### Description

Implement the authorized review queue and explicit clear/invalidate actions. Flags leave votes counted until staff act; every decision records reviewer, time, outcome, and reason, and invalidation updates live state without changing any closed daily snapshot.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/votes/tests/test_review_service.py`
- `apps/api/app/modules/votes/tests/test_review_routes.py`

#### Test Scenarios

##### Review Authorization and Decisions
- **keeps flagged votes counted until an explicit decision** — GIVEN a pending suspicious-vote flag WHEN it is created and read THEN the vote remains active and contributes to current totals _(verifies R9)_
- **allows only reviewers to read/decide** — GIVEN a member without reviewer permission WHEN queue or decision access is attempted THEN service and transport deny access _(verifies R9; guards named auth policy boundaries)_
- **records a clear decision with attribution** — GIVEN a pending flag WHEN an authorized reviewer clears it with a reason THEN actor, outcome, reason, and time are persisted append-only _(verifies R9)_
- **invalidates only after explicit staff action** — GIVEN a flagged active vote WHEN an authorized reviewer invalidates it THEN live vote state changes and a durable decision/outbox event is written _(verifies R9, R10, R11)_
- **keeps suspended members' existing votes until review** — GIVEN an account suspended after voting WHEN no reviewer action exists THEN its prior vote remains active; after explicit invalidation it no longer contributes _(verifies R10)_
- **does not mutate a closed daily snapshot** — GIVEN an invalidation decision after cutoff WHEN the decision commits THEN only live/current totals change and the prior archive is byte-for-byte equivalent _(verifies R8, R10)_
- **rejects duplicate conflicting review decisions** — GIVEN a flag already decided WHEN a second decision races or conflicts THEN one append-only accepted decision remains authoritative and caller receives a conflict _(verifies R9, R11)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/votes`.
- **Pattern reference:** `apps/api/app/modules/products/policies.py`, `apps/api/app/modules/products/tests/test_review_service.py`, and `apps/api/app/modules/products/tests/test_review_routes.py`.
- **Key decisions:** Human review only; preserve suspension history; decision actor/time/reason are auditable; no post-cutoff snapshot mutation.
- **Libraries:** Existing FastAPI/Pydantic/SQLAlchemy and staff authorization services.
- **High-risk callouts:** Reviewer policy must be enforced at service and REST boundaries; tests cover both and ensure no automatic exclusion.

### Scope Boundaries

- Do NOT build reviewer UI (T13) or GraphQL query composition (T8).
- Do NOT automatically invalidate votes based on flags or suspension.
- Do NOT rewrite archived rankings.

### Files Expected

**New files:**
- `apps/api/app/modules/votes/tests/test_review_service.py`
- `apps/api/app/modules/votes/tests/test_review_routes.py`

**Modified files:**
- `apps/api/app/modules/votes/repository.py` (review queue/decision persistence)
- `apps/api/app/modules/votes/service.py` (review, invalidation, and audit behavior)
- `apps/api/app/modules/votes/policies.py` (named reviewer permission)
- `apps/api/app/modules/votes/routes.py` (review decision command route)

**Must NOT modify:**
- `apps/api/app/modules/notifications/live.py` (private notifications remain unchanged)
- `apps/web/src/shell/AppShell.tsx` (reviewer UI is out of this task)

---

## Task T8: Expose public ranking and reviewer reads in GraphQL

> **Status:** not started
> **Verification:** test-after
> **Effort:** l
> **Priority:** high
> **Depends on:** T2, T6, T7
> **Satisfies REQs:** R5, R6, R8, R9, R12, N1
> **Footprint slice:** Votes GraphQL query module, GraphQL root composition, contract operations/generated types, and schema composition regression tests.
> **High-risk areas touched:** GraphQL/OpenAPI contracts (M); public product privacy (H).

### Description

Expose current-day and archived daily ranking reads plus a reviewer-only pending queue through Strawberry GraphQL. Compose the new query fields with existing roots and regenerate canonical client types while preserving guest-safe product fields and feature-flag behavior.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/votes/tests/test_graphql.py`
- `apps/api/app/modules/products/tests/test_graphql.py`
- `tests/integration/test_graphql_composition.py`
- `tests/quality/test_graphql_generation.py`

#### Test Scenarios

##### Public Ranking Contract
- **returns current rank and API-selected UTC date** — GIVEN no date argument WHEN a guest queries `dailyProductRanking` THEN current public cards, score/count/rank, and selected date are returned _(verifies R5–R7)_
- **looks up one product's daily rank directly** — GIVEN a launched product and active or archived date WHEN a caller supplies its product ID THEN the query returns that product's daily entry without traversing earlier ranking pages; an absent product returns no entry _(verifies R5, R8, R12)_
- **returns snapshot pages for ranked archive dates** — GIVEN a ranked past date and keyset cursor WHEN queried THEN stable snapshot ordering and pagination are returned _(verifies R6, R8)_
- **preserves ranked and pre-voting archives** — GIVEN a ranked past date with a keyset cursor or a date before voting start WHEN queried THEN the first returns stable snapshot ordering and the second preserves existing launch order without fabricated rank/count _(verifies R6, R8)_
- **never exposes unpublished products or voter identity** — GIVEN draft/submitted products and member vote rows WHEN an anonymous query runs THEN only launched public product data appears and no voter identity is present _(verifies R12; guards Products public projection)_
- **includes viewer vote state only for the authenticated viewer** — GIVEN anonymous and verified-member query contexts WHEN the ranking is read THEN only the current verified member's own vote state is composed _(verifies R1, R12)_

##### Reviewer Query and Composition
- **restricts pending review query** — GIVEN reviewer and non-reviewer contexts WHEN `pendingVoteReviews` is queried THEN only authorized staff receive paged account/vote context, with no raw network identifiers _(verifies R9)_
- **preserves existing root fields and flags** — GIVEN products/launch feature flag combinations WHEN the schema is composed THEN all prior allowed root fields remain and vote fields appear only under the intended availability _(guards `apps/api/app/modules/products/tests/test_graphql.py` and root composition)_
- **regenerates contract types from schema sources** — GIVEN canonical GraphQL/OpenAPI operations WHEN generation and quality checks run THEN generated files are current and no handwritten type patch is needed _(guards contract generation risk)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/votes/graphql.py`, `apps/api/app/graphql.py`, `packages/contracts`.
- **Pattern reference:** `apps/api/app/modules/products/graphql.py`, `apps/api/app/graphql.py`, `tests/integration/test_graphql_composition.py`, and `tests/quality/test_graphql_generation.py`.
- **Key decisions:** GraphQL remains read-only; public fields contain launched product projections only; reviewer queue checks named policy; keyset pagination and generated types are mandatory.
- **Libraries:** Existing Strawberry GraphQL and contract generation workspace (`npm run contracts:generate`).
- **High-risk callouts:** Root composition and public privacy are guarded by exact root tests, anonymous query tests, and schema-generation checks.

### Scope Boundaries

- Do NOT add GraphQL mutations or subscriptions; commands remain REST and live updates remain WebSocket invalidations.
- Do NOT alter existing catalog/search query semantics or generated API types by hand.
- Do NOT expose raw IP, voter identity, or unpublished product fields.

### Files Expected

**New files:**
- `apps/api/app/modules/votes/graphql.py` (ranking and review read resolvers)
- `apps/api/app/modules/votes/tests/test_graphql.py` (read authorization/privacy/paging tests)

**Modified files:**
- `apps/api/app/graphql.py` (compose vote queries and allowed roots)
- `apps/api/app/modules/products/tests/test_graphql.py` (update exact root expectations)
- `tests/integration/test_graphql_composition.py` (verify feature flag/root combinations)
- `packages/contracts/operations.graphql` (canonical ranking/review query operations)
- `packages/contracts/src/generated.ts`, `packages/contracts/src/graphql.generated.ts`, `packages/contracts/openapi.json`, and generated GraphQL/OpenAPI files under `apps/web/src/generated/` (regenerate only where source schemas require changes)

**Must NOT modify:**
- `apps/api/app/modules/products/repository.py` (existing public product filter remains authoritative)
- `apps/web/src/launches/PublicLaunchCard.tsx` (generic guest card is changed in neither this task nor the catalog)
- `apps/api/app/modules/notifications/live.py` (private notifications stay separate)

---

---

## Task T9: Add public ranking WebSocket tickets and invalidations

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T3, T5
> **Satisfies REQs:** R7, R12, N1
> **Footprint slice:** New votes live socket module and live tests; modified route/main wiring for ticket and WebSocket endpoints.
> **High-risk areas touched:** Public WebSocket and Redis (H); production authorization (H).

### Description

Add a short-lived, signed, read-only ticket for the current public ranking stream and a separate anonymous-safe WebSocket that sends minimal invalidation hints. Clients re-read GraphQL after an event and after reconnect/focus; the existing account-private notification socket remains unchanged.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/votes/tests/test_live.py`
- `apps/api/app/modules/notifications/tests/test_live.py` (regression guard only; do not modify)

#### Test Scenarios

##### Ticket and Socket Security
- **issues a short-lived current-day ticket** — GIVEN a permitted guest or member client WHEN a ticket is requested THEN it is signed, expires, and is scoped only to the current ranking date _(verifies R7, R12)_
- **rejects invalid, expired, or wrong-origin tickets** — GIVEN an invalid ticket or disallowed origin WHEN the WebSocket opens THEN the connection is denied without revealing internal errors _(verifies R12)_
- **broadcasts only invalidation hints** — GIVEN a vote update WHEN connected clients receive a message THEN it contains no voter identity, raw network data, or unpublished product fields _(verifies R7, R12)_
- **keeps private notification socket authorization intact** — GIVEN existing account-scoped socket clients WHEN vote live transport is added THEN notification authentication/session scoping and event payloads remain unchanged _(guards `apps/api/app/modules/notifications/live.py`)_

##### Recovery
- **does not require delivery of every missed event** — GIVEN a client reconnects after missing messages WHEN it reconnects and re-queries GraphQL THEN current count/rank is reconciled _(verifies R7)_
- **publishes after projection commit** — GIVEN a Redis projection update fails WHEN an event handler retries THEN no invalidation claims state that was not projected and the durable outbox event remains retryable _(verifies R7, R11; ARCH Redis outage scenario)_

### Implementation Notes

- **Module(s):** `apps/api/app/modules/votes/live.py`, `apps/api/app/modules/votes/routes.py`, `apps/api/app/main.py`.
- **Pattern reference:** `apps/api/app/modules/notifications/live.py` and `apps/api/app/modules/notifications/tests/test_live.py` for socket lifecycle and origin/session test techniques only.
- **Key decisions:** Separate public and private sockets; ticket is read-only, short-lived, origin-checked, current-date-scoped, and contains no identity; message tells clients to re-read GraphQL.
- **Libraries:** Existing FastAPI WebSockets, Redis pub/sub, and signed-token utilities.
- **High-risk callouts:** New public route must not alter private notifications; test explicit denial and payload privacy.

### Scope Boundaries

- Do NOT broadcast full rankings or voter-specific data.
- Do NOT reuse or weaken the private notification channel.
- Do NOT add continuous polling; reconnect/focus reconciliation belongs to the web client task.

### Files Expected

**New files:**
- `apps/api/app/modules/votes/live.py` (ticket verification and public ranking socket)
- `apps/api/app/modules/votes/tests/test_live.py` (ticket, origin, payload, and socket recovery tests)

**Modified files:**
- `apps/api/app/modules/votes/routes.py` (live-ticket issuance)
- `apps/api/app/main.py` (mount public live socket route under product/launch availability)

**Must NOT modify:**
- `apps/api/app/modules/notifications/live.py` (private account socket is a regression hotspot)
- `apps/worker/scheduler.py` (existing outbox due-event delivery is unchanged)

---

## Task T10: Render daily ranked launch cards and archives

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T8
> **Satisfies REQs:** R5, R6, R8, R12, N2
> **Footprint slice:** New ranked product card in votes UI; modified public `LaunchDiscovery` and `LaunchScreens` views.
> **High-risk areas touched:** Frontend launch discovery and identity (M); public product privacy (H).

### Description

Show daily rank and active vote count on today’s public launch list, the public product page, and ranked archive dates using the new GraphQL contract. Keep pre-voting dates in their existing unranked order and keep the generic catalog card/search behavior unchanged.

### Verification Checklist

- **Today view** — open the guest homepage with multiple launched products — expected: cards follow API rank, display rank/count, and show zero-vote products after voted products.
- **Archive view** — open a ranked date and a pre-voting date — expected: ranked date shows frozen rank/count; pre-voting date preserves old order and shows no fabricated vote/rank values.
- **Product details** — open a launched product page — expected: public product fields and its current or archived rank/count appear; private products remain unavailable.
- **Loading/error/empty states** — exercise pending, API error, and empty data — expected: accessible status/error messages and a retry affordance where applicable.
- **Responsive and accessible view** — inspect narrow and desktop widths; keyboard through cards and rank information — expected: no horizontal overflow, semantic links, and rank/count not conveyed by color alone.
- **Regression: catalog** — use Discover search/topic filters and the shared generic card — expected: existing catalog ordering, filters, and card content remain unchanged _(guards `apps/web/src/launches/PublicLaunchCard.tsx`)_.
- **Component checks** — run `npm test --workspace=@launchpad/web -- --run` — expected: ranked-card and launch-screen tests pass, including loading, empty, archive, and privacy states.

#### Testable Seams
- Ranked card renders deterministic rank, count, zero-vote marker, and public product fields.
- `LaunchDiscovery` selects ranked current/archive presentation from API date and data.
- `LaunchScreens` avoids rank/count on dates without snapshots.
- Keyboard/focus and live-region semantics announce rank/count without color-only signals.

### Implementation Notes

- **Module(s):** `apps/web/src/votes`, `apps/web/src/launches`.
- **Pattern reference:** `apps/web/src/launches/LaunchDiscovery.tsx`, `LaunchScreens.tsx`, `PublicLaunchCard.tsx`, and their tests.
- **Key decisions:** Use a dedicated ranked card; keep generic catalog card unchanged; honor API-selected UTC date and immutable snapshot values.
- **Libraries:** Existing React, TypeScript, TanStack Query, generated contracts, Vitest, and Testing Library.
- **High-risk callouts:** Public product privacy and existing guest discovery are protected by launched-only response checks and catalog regression tests.

### Scope Boundaries

- Do NOT add vote controls or WebSocket client behavior here (T11/T12).
- Do NOT change search/topic filtering, sorting, pagination, or generic card semantics.
- Do NOT create a rank/count for pre-voting dates.

### Files Expected

**New files:**
- `apps/web/src/votes/RankedLaunchCard.tsx` (public ranked card)
- `apps/web/src/votes/RankedLaunchCard.test.tsx` (render/accessibility states)

**Modified files:**
- `apps/web/src/launches/LaunchDiscovery.tsx` (render ranked cards for daily lists)
- `apps/web/src/launches/LaunchScreens.tsx` (show public product and archive rank/count)
- `apps/web/src/launches/LaunchScreens.test.tsx` (ranked, unranked, and privacy states)

**Must NOT modify:**
- `apps/web/src/launches/PublicLaunchCard.tsx` (generic catalog card stays unchanged)
- `apps/web/src/launches/DiscoverPage.tsx` and `DiscoverFilters.tsx` (catalog search/topic behavior is out of scope)

---

## Task T11: Reconcile live ranking updates in the browser

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T8, T9, T10
> **Satisfies REQs:** R7, R11, N1, N2
> **Footprint slice:** New ranking live hook/client behavior; integration into the public launch discovery view.
> **High-risk areas touched:** Public WebSocket and Redis (H); frontend launch discovery and identity (M).

### Description

Connect the public launch view to the short-lived ranking ticket and invalidation WebSocket. Invalidate/re-read the ranking after an event, reconnect, and tab focus; do not poll continuously or treat an invalidation message as complete ranking state.

### Verification Checklist

- **Live invalidation** — with two guest browser sessions open, cast/remove a vote in an authorized member session — expected: both guest views re-read and show updated count/rank within 2 seconds under the agreed staging profile.
- **Reconnect recovery** — disconnect one guest browser while votes change, reconnect — expected: it re-reads the current GraphQL ranking and converges without replaying every missed event.
- **Tab-focus recovery** — background the page, change votes, return to the tab — expected: one reconciliation query refreshes count/rank.
- **No continuous polling** — leave a page idle — expected: no repeated ranking query loop when no event/focus/reconnect occurs.
- **Dependency degradation** — interrupt Redis/pub-sub during a vote — expected: committed vote is retained, clients do not show unconfirmed state, and they reconcile after reconnect/focus.
- **Component checks** — run `npm test --workspace=@launchpad/web -- --run` — expected: live connection, invalidation, reconnection, and focus tests pass.

#### Testable Seams
- Ticket fetch and WebSocket lifecycle are injected/mocked.
- Invalidation triggers TanStack Query refresh rather than applying untrusted payload data.
- Reconnect/focus reconciliation is bounded and does not create polling.

### Implementation Notes

- **Module(s):** `apps/web/src/votes`, `apps/web/src/launches`.
- **Pattern reference:** `apps/web/src/launches/useLaunches.ts` and `apps/web/src/launches/LaunchDiscovery.tsx` live invalidation patterns.
- **Key decisions:** Short-lived read-only ticket; GraphQL remains source for page state; refresh on event/reconnect/focus, not continuous polling.
- **Libraries:** Existing browser WebSocket, TanStack Query, and test tools.
- **High-risk callouts:** Public stream carries only invalidation and no voter identity; browser reconciles against the privacy-safe GraphQL query.

### Scope Boundaries

- Do NOT alter the authenticated notifications socket or server-side ticket policy (T9 owns server contract).
- Do NOT stream full product/ranking payloads or voter identity.
- Do NOT add permanent background polling.

### Files Expected

**New files:**
- `apps/web/src/votes/useRankingLive.ts` (ticketed live connection and reconciliation hook)
- `apps/web/src/votes/useRankingLive.test.tsx` (event/reconnect/focus tests)

**Modified files:**
- `apps/web/src/launches/LaunchDiscovery.tsx` (connect ranking invalidation to the query)
- `apps/web/src/launches/LaunchScreens.tsx` (reconcile the public product rank display)

**Must NOT modify:**
- `apps/api/app/modules/notifications/live.py` (private transport is unchanged)
- `apps/web/src/launches/PublicLaunchCard.tsx` (catalog card stays outside ranking live behavior)

---

## Task T12: Add member vote controls and safe sign-in return

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T3, T8, T9, T10
> **Satisfies REQs:** R1, R2, R3, R4, R7, R9, R11, N2, N3
> **Footprint slice:** New vote client/hooks/control; modify identity sign-in navigation to preserve only safe internal vote return paths.
> **High-risk areas touched:** Votes persistence and policy (H); frontend launch discovery and identity (M).

### Description

Let a verified member cast or remove a vote from ranked public cards/product pages, with server-confirmed state and clear eligibility/error feedback. Guests who click vote are returned to the same safe internal launch after sign-in; high-risk challenges are shown only when the server requests them.

### Verification Checklist

- **Eligible vote flow** — sign in as a verified member and vote on another founder’s live launch — expected: confirmed state/count/rank appears from the server response.
- **Remove/re-vote flow** — remove before cutoff, then vote again — expected: one active vote at most and the control always reflects reconciled server state.
- **Guest return flow** — click vote as a guest, sign in — expected: return to the same launch and no external `returnTo` URL is accepted.
- **Unverified/suspended/self-vote states** — exercise each account/product case — expected: action is unavailable or rejected with a clear next step and no false count change.
- **Cutoff/error/retry** — trigger cutoff, rate limit, or server failure — expected: last confirmed state remains visible with actionable retry guidance; same idempotency key is used for retries.
- **Turnstile escalation** — trigger a high-risk response — expected: challenge appears only when requested, token is sent to backend, and failed verification leaves confirmed state unchanged.
- **Keyboard/mobile accessibility** — operate vote/remove/challenge controls at narrow and desktop widths — expected: semantic labels, visible focus, and announced count/state changes.
- **Component checks** — run `npm test --workspace=@launchpad/web -- --run` — expected: vote states, failure rollback, challenge, and safe return navigation pass.

#### Testable Seams
- Vote control states: guest, eligible, voted, pending, challenged, rejected, and retryable failure.
- Client includes idempotency key and reconciles from server response.
- Sign-in `returnTo` accepts only same-origin internal paths and preserves existing default navigation.
- Keyboard and live-region semantics are component-tested.

### Implementation Notes

- **Module(s):** `apps/web/src/votes`, `apps/web/src/identity`.
- **Pattern reference:** `apps/web/src/identity/client.ts`, `Screens.tsx`, `useIdentity.ts`, and existing launch query hooks.
- **Key decisions:** No false optimistic confirmation; server remains eligibility authority; safe internal return path; backend-controlled Turnstile escalation.
- **Libraries:** Existing React, TypeScript, TanStack Query, generated REST contracts, and existing Turnstile client integration/config.
- **High-risk callouts:** Vote state must not diverge after failures; identity return path must not be an open redirect; tests cover rollback and safe paths.

### Scope Boundaries

- Do NOT build reviewer UI or change account verification flows.
- Do NOT change the generic public catalog card/search.
- Do NOT accept or trust client-only eligibility or risk decisions.

### Files Expected

**New files:**
- `apps/web/src/votes/client.ts` (vote REST client)
- `apps/web/src/votes/useVotes.ts` (vote mutations and confirmed query state)
- `apps/web/src/votes/VoteControl.tsx` (member/guest action states and challenge presentation)
- `apps/web/src/votes/VoteControl.test.tsx` (interaction, state, and accessibility coverage)

**Modified files:**
- `apps/web/src/launches/LaunchDiscovery.tsx` (place vote controls on ranked daily cards)
- `apps/web/src/launches/LaunchScreens.tsx` (place vote control on public product page)
- `apps/web/src/identity/Screens.tsx` (safe internal return after sign-in)

**Must NOT modify:**
- `apps/api/app/modules/auth` session/verification policies (already authoritative)
- `apps/web/src/launches/PublicLaunchCard.tsx` (generic catalog card remains unchanged)

---

## Task T13: Build the staff vote-review queue UI

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** medium
> **Depends on:** T7, T8
> **Satisfies REQs:** R9, R10, N2
> **Footprint slice:** New staff review queue UI under votes; add authorized route and conditional navigation.
> **High-risk areas touched:** Votes persistence and policy (H); frontend launch discovery and identity (M).

### Description

Provide staff reviewers a paged view of pending suspicious-vote flags and explicit clear/invalidate actions with reason entry. Hide reviewer navigation from non-reviewers and display only permitted account/vote/product context, never raw IP or device identifiers.

### Verification Checklist

- **Reviewer access** — open the review route as reviewer and non-reviewer — expected: reviewer sees pending queue; non-reviewer receives a safe denial and no staff navigation.
- **Flag context** — inspect a pending item — expected: account, vote, product, signal categories, and relevant timeline appear without raw network identifiers.
- **Clear action** — clear a pending flag with a reason — expected: item leaves pending queue and vote remains counted.
- **Invalidate action** — invalidate with a reason — expected: explicit confirmation, updated live result, and audit attribution; closed archive display does not change.
- **Error and retry states** — simulate permission loss, conflict, and API error — expected: safe message, no duplicate decision, and recoverable queue state.
- **Keyboard/accessibility** — operate filters, reason input, and decision controls without a mouse — expected: labeled controls, focus handling, and announced outcomes.
- **Component checks** — run `npm test --workspace=@launchpad/web -- --run` — expected: role-gated route, queue states, and decisions pass.

#### Testable Seams
- Reviewer/non-reviewer conditional route and navigation rendering.
- Queue loading/empty/error/page states.
- Clear/invalidate reason submission and response reconciliation.
- Keyboard-accessible confirmation and status announcements.

### Implementation Notes

- **Module(s):** `apps/web/src/votes`, `apps/web/src/App.tsx`, `apps/web/src/routing.ts`, `apps/web/src/shell/AppShell.tsx`.
- **Pattern reference:** Existing product review screens/navigation and `apps/web/src/launches/LaunchScreens.tsx`.
- **Key decisions:** Backend reviewer policy remains authoritative; display no raw network identifiers; actions require explicit reason and reconcile server state.
- **Libraries:** Existing React, TanStack Query, generated contracts, and UI test stack.
- **High-risk callouts:** UI gating is not authorization; backend denies every non-reviewer. Tests cover both UI and server response behavior.

### Scope Boundaries

- Do NOT change backend authorization/audit behavior (T7 owns it).
- Do NOT automatically invalidate or hide a flagged vote.
- Do NOT add unrelated account administration or product moderation screens.

### Files Expected

**New files:**
- `apps/web/src/votes/ReviewQueue.tsx` (staff queue and decision controls)
- `apps/web/src/votes/ReviewQueue.test.tsx` (role/state/decision coverage)

**Modified files:**
- `apps/web/src/App.tsx` (mount reviewer route)
- `apps/web/src/routing.ts` (review route matching)
- `apps/web/src/shell/AppShell.tsx` (authorized reviewer navigation)

**Must NOT modify:**
- `apps/api/app/modules/auth/staff.py` (reuse named staff access policy)
- `apps/api/app/modules/notifications/live.py` (private notification socket remains unchanged)

---

## Task T14: Configure default-off voting for local and production Compose

> **Status:** not started
> **Verification:** checklist
> **Effort:** s
> **Priority:** high
> **Depends on:** T3
> **Satisfies REQs:** R11, N1
> **Footprint slice:** Runtime configuration in local and production Compose files; no application policy changes.
> **High-risk areas touched:** Production configuration and deployment (H).

### Description

Pass voting and ranking configuration to the intended API/worker services while keeping vote writes disabled by default. Keep the Turnstile secret server-side and make only the public site key available to the web build when required.

### Verification Checklist

- **Local Compose renders** — run `docker compose -f compose.yaml config --quiet` with the documented local environment — expected: exit code 0.
- **Production Compose renders** — run `docker compose -f compose.production.yaml --env-file <release-env-file> config --quiet` with a protected validation env file — expected: exit code 0 without printing values.
- **Default-off behavior** — inspect rendered service environment using a script that prints only booleans/key names — expected: write flag resolves false unless explicitly enabled.
- **Shared score settings** — inspect rendered API and worker configuration — expected: both use the same configured six-hour staging half-life value so projection and snapshot calculations cannot drift.
- **Secret placement** — inspect API, worker, and web service environment — expected: Turnstile secret is available only to API; worker/web do not receive it; public site key may be exposed to web.
- **Existing services preserved** — run `docker compose -f compose.yaml config --services` and production equivalent — expected: API, worker, scheduler, database, cache, and web service names remain present.
- **No sample-secret edits** — inspect staged diff — expected: `.env.example` and existing user configuration changes are preserved.

### Implementation Notes

- **Module(s):** local and production deployment configuration.
- **Pattern reference:** existing environment propagation and least-privilege service configuration in `compose.yaml` and `compose.production.yaml`.
- **Key decisions:** writes default off; secrets never enter the web image/environment; no destructive rollout config.
- **Libraries:** Docker Compose v2.
- **High-risk callouts:** A misrouted secret or accidentally enabled write switch can affect production; rendered-config assertions must not print secret values.

### Scope Boundaries

- Do NOT modify application defaults or settings fields (T3 owns those).
- Do NOT enable production voting as part of this task.
- Do NOT change unrelated services, secrets, or deployment workflow behavior.

### Files Expected

**New files:**
- None.

**Modified files:**
- `compose.yaml` (local vote/ranking settings and safe defaults)
- `compose.production.yaml` (production service configuration and secret boundaries)

**Must NOT modify:**
- `.env.example` (preserve existing environment sample state)
- `scripts/deploy_production.sh` and existing Cloudflare tunnel config (deployment mechanics are outside this feature)

---

## Task T15: Document voting operations and architecture decisions

> **Status:** not started
> **Verification:** checklist
> **Effort:** s
> **Priority:** medium
> **Depends on:** T14
> **Satisfies REQs:** R8, N1
> **Footprint slice:** New voting architecture ADR; local development and Proxmox production deployment documentation.
> **High-risk areas touched:** Production configuration and deployment (H); votes persistence and policy (H).

### Description

Record why PostgreSQL/outbox is authoritative, Redis is rebuildable, and daily snapshots are immutable. Document the local setup and production enable/disable procedure, first-enabled UTC date, Turnstile secret handling, backup/migration expectations, and rollback steps without embedding secret values.

### Verification Checklist

- **ADR completeness** — inspect `docs/adr/0009-voting-and-daily-ranking.md` — expected: data authority, projection, event, archive, and security decisions match ARCH.
- **Local guide** — follow `docs/development.md` — expected: configuration names, default-off behavior, and local verification steps are documented and usable.
- **Production guide** — review `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md` — expected: operator can deploy while writes are off, set first-enabled UTC date, enable voting, inspect health/lag, disable writes for rollback, and keep compatible consumers draining events.
- **Secret review** — search changed docs/ADR for credential-like values — expected: names and instructions only; no actual credentials, tokens, or generated keys.
- **Open decisions retained** — verify peak concurrency, Turnstile thresholds, and idempotency retention remain marked for staging/operations calibration rather than invented as fixed policy.
- **Whitespace/links** — run `git diff --check` and check local Markdown links — expected: no whitespace errors and all referenced files exist.

### Implementation Notes

- **Module(s):** engineering documentation and ADRs.
- **Pattern reference:** existing `docs/adr/` records, `docs/development.md`, and `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md`.
- **Key decisions:** document the approved architecture; do not introduce additional product behavior or operational cadence.
- **Libraries:** Markdown only.
- **High-risk callouts:** Production steps must avoid secret disclosure and must describe a rollback that retains queued event consumers and immutable archives.

### Scope Boundaries

- Do NOT enable production vote writes or publish deployment messages.
- Do NOT create a separate operating runbook beyond the named docs.
- Do NOT resolve open load/risk/retention questions by inventing values.

### Files Expected

**New files:**
- `docs/adr/0009-voting-and-daily-ranking.md` (approved durable architecture decisions)

**Modified files:**
- `docs/development.md` (local voting setup and verification)
- `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md` (production config, rollout, and rollback)

**Must NOT modify:**
- `specs/architecture/ARCH-voting-and-daily-ranking.md` except its existing Tasks header if needed (architecture is read-only in this phase)
- `.env.example` or any secret-bearing deployment env file
