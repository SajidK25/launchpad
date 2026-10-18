# Tasks

## Task T1: Add launch persistence and migration

> **Status:** done
> **Verification:** test-after
> **Effort:** M
> **Priority:** high
> **Depends on:** None
> **Satisfies REQs:** R2–R3, R6–R9, R12–R17, N2
> **Footprint slice:** Add booking/preferences models and migration 0012; extend product lifecycle and notification constraints, including scheduled review audit and founder-scoped idempotency.
> **High-risk areas touched:** Database/migration/deploy; product lifecycle/review; notifications/WebSocket.

### Description

Create the database foundation for scheduling and publication. Persist booking history and launch preferences, extend product and notification mappings, and migrate existing review data forward without data loss.

### Test Plan

#### Test File(s)
- `tests/integration/test_production_migrations.py`
- `apps/api/app/modules/launches/tests/test_models.py` (new)
- `apps/api/app/modules/products/tests/test_review_models.py`

#### Test Scenarios

##### Migration
- **Upgrades from current head** — GIVEN revision `0011_profile_upload_declarations`, WHEN migration 0012 runs, THEN it is the single head and the booking/preferences schema, launch fields/statuses, notification links/kinds, checks, indexes, and foreign keys exist _(verifies R2–R3, R6–R9, R12–R17)_
- **Preserves existing review notices** — GIVEN review notifications exist before migration, WHEN migration 0012 runs, THEN their kinds and review-decision links remain valid and readable _(guards notification persistence)_
- **Keeps migration concurrency safe** — GIVEN concurrent production migration processes, WHEN both complete, THEN the database reaches the new single head _(verifies N2; guards migration locking)_
- **Allows audited scheduled return** — GIVEN a review decision with `from_status='scheduled'`, WHEN its outcome is `changes_requested`, THEN the database accepts it; other scheduled outcomes remain rejected and prior transitions remain valid _(verifies R9)_

##### Model constraints
- **Enforces booking identity and capacity indexes** — GIVEN bookings in supported states, WHEN persisted, THEN only scheduled rows consume slots and a product cannot have multiple scheduled bookings _(verifies R2–R5, N2)_
- **Stores founder-scoped idempotency** — GIVEN booking/reschedule and cancel requests, WHEN their keys/fingerprints are persisted, THEN keys are uniquely scoped to the founder and conflicting fingerprints cannot overwrite them _(verifies N2)_
- **Preserves product and notice model contracts** — GIVEN existing review mappings and new launch rows, WHEN loaded, THEN scheduled/launched fields, enabled preference defaults, valid notice source/kind constraints, and per-booking/kind deduplication are represented _(verifies R6–R17)_

### Implementation Notes
- **Module(s):** `app.modules.launches`, `app.modules.products`, `app.modules.notifications`.
- **Pattern reference:** Feature-owned mappings in `products/models.py` and `notifications/models.py`; forward migration in `0011_profile_upload_declarations.py`.
- **Key decisions:** PostgreSQL owns booking history and preferences. Migration 0012 succeeds 0011; preserve existing review rows and decision audit. Persist founder-scoped request keys/fingerprints on booking history.
- **High-risk callouts:** Existing notification and review constraints must remain compatible. Migration tests seed old data and exercise scheduled return audit.

### Scope Boundaries
- Do NOT implement booking rules, lifecycle services, REST/GraphQL, or worker behavior.
- Do NOT downgrade or delete retained booking/review history.
- Only implement persistence mappings and the forward migration.

### Files Expected

**New files:**
- `apps/api/app/modules/launches/models.py` (booking and preference mappings; follow feature-owned model pattern)
- `apps/api/alembic/versions/0012_launch_scheduling_publication.py` (forward successor to 0011)
- `apps/api/app/modules/launches/tests/test_models.py`

**Modified files:**
- `apps/api/app/modules/products/models.py` (launch fields/status and scheduled review decision constraint)
- `apps/api/app/modules/notifications/models.py` (launch notice source/kinds and six preferences)
- `tests/integration/test_production_migrations.py` (new head and concurrency regression)
- `apps/api/app/modules/products/tests/test_review_models.py` (decision constraint coverage)

**Must NOT modify:**
- `apps/api/app/shared/db/database.py` and `0011_profile_upload_declarations.py` (preserve migration-head behavior and shared revision)
- Existing review service/route/GraphQL and notification behavior tests (retain as regression guards)
- Service, route, worker, and frontend files (later tasks)

---

## Task T2: Implement UTC booking rules and founder capacity

> **Status:** done
> **Verification:** tdd
> **Effort:** M
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R1–R5, N2
> **Footprint slice:** Launch repository, service, and policies for UTC eligibility, per-founder capacity, booking/reschedule/cancel operations, idempotency, and the named product lifecycle port.
> **High-risk areas touched:** Booking and capacity.

### Description

Implement founder booking, reschedule, and cancellation operations. Enforce UTC date boundaries and the two-per-founder daily limit transactionally; failed rescheduling must preserve the original booking.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/launches/tests/test_service.py` (new)
- `apps/api/app/modules/launches/tests/test_concurrency.py` (new; PostgreSQL)

#### Test Scenarios

##### Booking eligibility
- **Accepts UTC date boundaries** — GIVEN a fixed service clock, WHEN tomorrow or day 90 is requested, THEN both dates are accepted as UTC calendar dates _(verifies R1–R2)_
- **Rejects dates outside the window** — GIVEN a fixed clock, WHEN today, a past date, or day 91 is requested, THEN the request is refused without product or booking mutation _(verifies R2)_
- **Enforces existing account/product eligibility** — GIVEN a missing or suspended account, another founder’s product, or a product outside approved, WHEN booking is requested, THEN it is refused without mutation; do not add a new verification requirement beyond existing product eligibility _(verifies R2)_

##### Capacity and concurrency
- **Limits each founder to two per date** — GIVEN two bookings by one founder on a UTC date, WHEN a third is requested, THEN it is refused while another founder can still book that date _(verifies R3)_
- **Serializes the last-slot race** — GIVEN concurrent PostgreSQL requests for one founder’s final daily slot, WHEN both complete, THEN exactly one succeeds _(verifies R3, N2)_

##### Reschedule, cancel, and replay
- **Preserves the old booking on failed reschedule** — GIVEN a scheduled product, WHEN the target date is invalid or full, THEN the original booking remains active and unchanged _(verifies R4, N2)_
- **Replaces a booking atomically** — GIVEN an available date before the original launch time, WHEN rescheduled, THEN the old row is replaced and one new booking becomes active _(verifies R4, N2)_
- **Enforces the original midnight boundary** — GIVEN an active booking, WHEN cancellation occurs before its launch time, THEN it returns to approved and releases capacity; at/after midnight it fails even if publication is delayed _(verifies R5)_
- **Replays idempotently** — GIVEN founder-scoped request keys, WHEN an identical booking/cancel request repeats, THEN its effective result is returned; a reused key with a different fingerprint conflicts without mutation _(verifies N2)_

### Implementation Notes
- **Module(s):** `app.modules.launches`.
- **Pattern reference:** `products/service.py`, `products/repository.py`, and `products/policies.py`; use `AuthAccessService.current_account(..., lock=True)` for account state/lock.
- **Key decisions:** PostgreSQL is authoritative; lock founder before product/booking, count active rows in the transaction, and call products through a named port over the caller’s session. Use T1’s founder-scoped key/fingerprint fields.
- **High-risk callouts:** PostgreSQL race coverage proves capacity serialization and failed reschedules preserve the old slot.

### Scope Boundaries
- Do NOT implement HTTP routes/schemas (T5), product lifecycle adapter (T3), or outbox events (T7).
- Do NOT add a platform-wide cap.
- Only implement booking persistence access and domain operations.

### Files Expected

**New files:**
- `apps/api/app/modules/launches/repository.py` (booking locks, reads, and writes)
- `apps/api/app/modules/launches/service.py` (UTC window, capacity, idempotency, and product port)
- `apps/api/app/modules/launches/policies.py` (typed launch errors and state policies)
- `apps/api/app/modules/launches/tests/test_service.py`
- `apps/api/app/modules/launches/tests/test_concurrency.py`

**Modified files:** None.

**Must NOT modify:**
- Product transition implementation in `products/service.py`/`repository.py` (T3)
- `launches/routes.py`, `schemas.py`, and `__init__.py` (T5)
- Outbox/worker delivery (T7–T9)

---

## Task T3: Add scheduled and launched product lifecycle

> **Status:** done
> **Verification:** tdd
> **Effort:** M
> **Priority:** critical
> **Depends on:** T1, T2
> **Satisfies REQs:** R6–R8, R10–R11, N2–N3
> **Footprint slice:** Product repository, service, policies, and schemas for schedule/publication/failure transitions, launched-only projection, and post-launch edit rules.
> **High-risk areas touched:** Product lifecycle/review; public reads/media.

### Description

Add approved-to-scheduled-to-launched transitions, with same-day recovery and explicit missed-day or suspension outcomes. Provide a launched-only public projection and permit only the agreed description/link edits after launch.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_launch_lifecycle.py` (new)

#### Test Scenarios

##### Lifecycle
- **Schedules only approved products** — GIVEN an approved product and current version, WHEN scheduled, THEN status/version update and content remains private; other states reject the transition _(verifies R6, R11)_
- **Publishes once on the booked day** — GIVEN a current due booking, WHEN publication succeeds, THEN status becomes launched, `launched_at` is set, version increments, and replay has no second effect _(verifies R6, N2)_
- **Handles missed-day recovery** — GIVEN a due product, WHEN processed on the booked UTC date it launches, but processing after that date returns it to approved with a persistent missed-day reason _(verifies R7)_
- **Blocks suspended founders** — GIVEN a suspended founder at publication time, WHEN the event is handled, THEN product stays private, returns to approved with a suspension reason, and reinstatement alone does not launch it _(verifies R8)_

##### Projection and edits
- **Returns only launched public projection** — GIVEN products in approved/scheduled/launched states, WHEN read through the product projection, THEN only launched content is returned and no review, booking-history, or account fields appear _(verifies R6, R10, N3)_
- **Restricts content edits by status** — GIVEN approved/scheduled or launched products, WHEN founder edits are attempted, THEN prelaunch edits fail; after launch only validated description/link changes succeed and name, pitch, media, and topics remain unchanged _(verifies R11)_

### Implementation Notes
- **Module(s):** `app.modules.products`.
- **Pattern reference:** `products/service.py`, `repository.py`, `policies.py`, and `schemas.py` for aggregate transitions, persistence, and validation.
- **Key decisions:** Product owns lifecycle/content; launch coordination uses the named port over the caller’s session; public projection is explicit and launched-only.
- **High-risk callouts:** Tests exercise both the state transition and projection privacy boundary.

### Scope Boundaries
- Do NOT add REST/GraphQL transport (T5/T10), staff booking invalidation (T4), public media delivery (T11), or worker dispatch (T8).
- Only implement product-owned transitions, public projection data, and post-launch edit rules.

### Files Expected

**New files:**
- `apps/api/app/modules/products/tests/test_launch_lifecycle.py`

**Modified files:**
- `apps/api/app/modules/products/repository.py` (lifecycle persistence and public projection access)
- `apps/api/app/modules/products/service.py` (schedule, publish, failure, and post-launch edit operations)
- `apps/api/app/modules/products/policies.py` (status/edit policies)
- `apps/api/app/modules/products/schemas.py` (validated post-launch edit shape)

**Must NOT modify:**
- `products/models.py` (T1 migration/model changes)
- `products/routes.py` and `graphql.py` (later transport tasks)
- Existing review service tests/behavior (T4 integrates scheduled review invalidation)

---

## Task T4: Close scheduled bookings on staff return-for-changes

> **Status:** done
> **Verification:** tdd
> **Effort:** M
> **Priority:** high
> **Depends on:** T1, T2, T3
> **Satisfies REQs:** R9, R13, N2
> **Footprint slice:** Connect staff review return-to-changes with the launches service/repository so active bookings close in the review transaction.
> **High-risk areas touched:** Product lifecycle/review; booking and capacity.

### Description

When staff return scheduled work for changes, commit the product/submission transition, immutable review decision, and booking closure together. Release the slot and make pending reminders for that booking obsolete.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_review_launch_invalidation.py` (new; PostgreSQL)

#### Test Scenarios

##### Atomic review action
- **Closes booking with the review decision** — GIVEN a scheduled product with an active booking, WHEN authorized staff request changes, THEN status/submission/feedback/audit update and booking closes as returned-for-changes, releasing capacity _(verifies R9, N2)_
- **Rolls back both sides** — GIVEN an error in either operation, WHEN the transaction fails, THEN neither decision nor booking closure is committed _(verifies R9, N2)_
- **Makes old reminder irrelevant** — GIVEN a pending reminder for the closed booking, WHEN active booking state is read, THEN the former booking is not current _(verifies R9, R13)_
- **Replays review safely** — GIVEN the same review idempotency key and payload, WHEN replayed, THEN the same decision is returned without duplicate closure/audit _(verifies N2)_

##### Concurrency and regression
- **Serializes review against publication** — GIVEN concurrent staff return and publication transactions, WHEN both finish, THEN one consistent booking/product outcome commits without deadlock or stale active booking _(ARCH stress scenario; R9, N2)_
- **Preserves existing review outcomes** — GIVEN submitted products or approved products without bookings, WHEN existing staff outcomes run, THEN feedback validation, audit, and notices remain unchanged _(guards existing review behavior)_

### Implementation Notes
- **Module(s):** `app.modules.products`, `app.modules.launches`.
- **Pattern reference:** Existing review transaction/idempotency in `products/service.py`; launches service/repository over the caller session.
- **Key decisions:** Product owns staff decisions; launches owns booking persistence. Preserve account-before-product lock order and use one transaction.
- **High-risk callouts:** PostgreSQL race and rollback scenarios check deadlock risk and atomicity.

### Scope Boundaries
- Do NOT change review route/GraphQL transport or send notifications here.
- Do NOT restore bookings after reapproval.
- Only add scheduled-product booking invalidation to the existing review operation.

### Files Expected

**New files:**
- `apps/api/app/modules/products/tests/test_review_launch_invalidation.py`

**Modified files:**
- `apps/api/app/modules/products/service.py` (invoke named launch invalidator in review transaction)
- `apps/api/app/modules/launches/service.py` (review invalidation operation)
- `apps/api/app/modules/launches/repository.py` (close active booking)

**Must NOT modify:**
- Existing `test_review_service.py`, `test_review_routes.py`, `test_review_graphql.py`, and notification tests (regression guards)
- Product model/migration (T1)
- Worker delivery (T8)

---

## Task T5: Add launch booking REST commands

> **Status:** done
> **Verification:** tdd
> **Effort:** M
> **Priority:** high
> **Depends on:** T2
> **Satisfies REQs:** R1–R5, N2
> **Footprint slice:** Launch request/response schemas, authenticated REST routes, and router factory for booking/reschedule/cancel.
> **High-risk areas touched:** Booking and capacity; API contracts.

### Description

Expose booking, rescheduling, and cancellation through cookie-authenticated REST commands. Validate request shape and map typed domain failures safely while keeping business decisions in the launch service.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/launches/tests/test_routes.py` (new)

#### Test Scenarios

##### Commands and validation
- **Creates booking via service** — GIVEN an authenticated founder and valid date, WHEN POST is sent, THEN validated input/key reach the service and response contains booking identity/status/version and UTC time only _(verifies R1–R2)_
- **Routes reschedule/cancel with version and key** — GIVEN an active booking, WHEN PUT/DELETE succeeds, THEN expected version and idempotency key reach service; failed commands do not mutate state _(verifies R4–R5, N2)_
- **Rejects malformed requests before service call** — GIVEN missing/invalid/out-of-window dates or extra/invalid fields, WHEN sent, THEN 422 is returned with no service mutation _(verifies R2)_

##### Security and errors
- **Requires eligible owner** — GIVEN anonymous, suspended, inactive, or non-owner caller, WHEN a command is sent, THEN safe auth response and no mutation _(verifies R2)_
- **Enforces CSRF/origin/rate/idempotency headers** — GIVEN absent or invalid request protections, WHEN sent, THEN request is rejected before service mutation _(verifies N2)_
- **Maps domain failures safely** — GIVEN not-found, conflict, validation, quota, or infrastructure errors, WHEN mapped, THEN expected 404/409/422/429/503 response contains no stack/private content _(verifies R2–R5)_
- **Keeps commands REST-only** — GIVEN API schema composition, WHEN booking commands are exposed, THEN no GraphQL mutation is added _(guards architecture API boundary)_

### Implementation Notes
- **Module(s):** `app.modules.launches`.
- **Pattern reference:** `products/routes.py` and `products/schemas.py` for cookie auth, CSRF, exact-origin checks, strict Pydantic fields, and safe error mapping.
- **Key decisions:** Thin routes call T2. T12 mounts the router behind the launch flag.
- **High-risk callouts:** Route checks cover ownership and request-origin protections before mutation.

### Scope Boundaries
- Do NOT reimplement booking rules (T2), mount the router (T12), or add GraphQL reads (T10).
- Do NOT add preference commands (T6).
- Only implement booking REST schemas, handlers, and router factory.

### Files Expected

**New files:**
- `apps/api/app/modules/launches/schemas.py`
- `apps/api/app/modules/launches/routes.py`
- `apps/api/app/modules/launches/__init__.py`
- `apps/api/app/modules/launches/tests/test_routes.py`

**Modified files:** None.

**Must NOT modify:**
- `app/main.py`, `app/graphql.py`, and `users/routes.py` (T10/T12 wiring)
- Launch service/repository (T2)
- Notification preference routes (T6)

---

## Task T6: Add launch notice preference persistence and updates

> **Status:** done
> **Verification:** tdd
> **Effort:** M
> **Priority:** medium
> **Depends on:** T1
> **Satisfies REQs:** R16
> **Footprint slice:** Notification repository/service/schemas/routes for six independent email and in-site preferences.
> **High-risk areas touched:** Notifications/WebSocket.

### Description

Let founders save and reload separate email and in-site choices for reminders, launch-live notices, and launch failures. Missing preferences read as enabled defaults; updates remain owner-scoped.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/notifications/tests/test_launch_preferences.py` (new; PostgreSQL service coverage)
- `apps/api/app/modules/notifications/tests/test_preference_routes.py` (new)

#### Test Scenarios

##### Preference service
- **Reads defaults without a row** — GIVEN no preference record, WHEN read, THEN six true values are returned without requiring an insert _(verifies R16)_
- **Persists all six independently** — GIVEN a combination of booleans, WHEN saved and reloaded, THEN each saved value is returned _(verifies R16, N2)_
- **Updates one choice only** — GIVEN saved values, WHEN one channel/type changes, THEN other five remain unchanged _(verifies R16)_

##### Route and regression
- **Requires active owner** — GIVEN unauthenticated, suspended, or mismatched owner, WHEN update is requested, THEN it is rejected without mutation _(verifies R16)_
- **Rejects malformed data** — GIVEN missing, extra, or non-boolean fields, WHEN sent, THEN validation fails without mutation _(verifies R16)_
- **Preserves inbox state** — GIVEN existing notices/read state, WHEN preferences are updated, THEN inbox, individual-read, and unread-count values are unchanged _(guards existing notification behavior)_

### Implementation Notes
- **Module(s):** `app.modules.notifications`.
- **Pattern reference:** Existing `notifications/service.py`, repository, schemas, and routes for owner-scoped data and HTTP protection.
- **Key decisions:** Missing preference row means all six channels enabled. T10 exposes the read through GraphQL; this task provides its service read and REST update.
- **High-risk callouts:** Regression check protects existing inbox/read behavior.

### Scope Boundaries
- Do NOT modify preference mapping (T1), GraphQL composition (T10), or event delivery checks (T8).
- Do NOT change live bell/WebSocket behavior.
- Only implement preference service persistence and REST update.

### Files Expected

**New files:**
- `apps/api/app/modules/notifications/tests/test_launch_preferences.py`
- `apps/api/app/modules/notifications/tests/test_preference_routes.py`

**Modified files:**
- `apps/api/app/modules/notifications/repository.py` (preference read/write)
- `apps/api/app/modules/notifications/service.py` (default/read/update behavior)
- `apps/api/app/modules/notifications/schemas.py` (six typed values)
- `apps/api/app/modules/notifications/routes.py` (authenticated update command)

**Must NOT modify:**
- `notifications/models.py` (T1)
- `notifications/graphql.py` (T10)
- Existing notifications tests (regression guards)

---

## Task T7: Create launch events and durable inbox notices

> **Status:** done
> **Verification:** tdd
> **Effort:** M
> **Priority:** high
> **Depends on:** T1, T2, T3, T6
> **Satisfies REQs:** R12–R17, N2–N4
> **Footprint slice:** Produce encrypted booking/outcome events and persist launch notices/invalidation through launch and notification services.
> **High-risk areas touched:** Worker/outbox; notifications/WebSocket.

### Description

Connect bookings and publication outcomes to durable outbox work and inbox notices. Create booking-identified reminder/publication events, preference-aware channel intents, and account-scoped live invalidation without external I/O in the request transaction.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/launches/tests/test_events.py` (new)
- `apps/api/app/modules/notifications/tests/test_launch_events.py` (new)

#### Test Scenarios

##### Event production
- **Schedules reminder/publication atomically** — GIVEN a booking, WHEN committed, THEN publication event is due at UTC launch time and reminder at `max(now, launch_at - 24h)`; under-24-hour bookings remind immediately _(verifies R12, N2)_
- **Uses new booking identity on reschedule** — GIVEN a replacement booking, WHEN its events are created, THEN new work identifies the new booking and old work remains distinct for later relevance checks _(verifies R12–R13)_

##### Notices and delivery intents
- **Persists outcome notices** — GIVEN live, missed-day, or suspension outcomes, WHEN recorded, THEN one owner-only notice per booking/kind has a product destination and failure reason persists regardless of preferences _(verifies R14–R17)_
- **Commits notice/invalidation together** — GIVEN enabled in-site notice, WHEN inserted, THEN its account-scoped `notification.changed.v1` and encrypted email intent share the transaction; payload includes identifiers only _(verifies R14–R17, N3–N4)_
- **Honors channel preferences** — GIVEN current combinations, WHEN intents are materialized, THEN disabled channel/type intents are omitted independently _(verifies R16)_
- **Deduplicates replay** — GIVEN repeated outcome processing, WHEN notices are recorded, THEN there is one logical inbox notice and email intent _(verifies N2, N4)_
- **Preserves review notices** — GIVEN existing review notice behavior, WHEN launch notice paths are added, THEN recipient, read/unread, and review outcome behavior remain unchanged _(regression guard)_

### Implementation Notes
- **Module(s):** `app.modules.launches`, `app.modules.notifications`.
- **Pattern reference:** `shared/events/outbox.py` and `notifications/service.py` for encrypted transactional events and durable inbox writes.
- **Key decisions:** Booking, timed work, notice, and invalidation are written in caller-owned PostgreSQL transactions; workers perform email/Redis operations later.
- **High-risk callouts:** Uniqueness and replay tests prevent duplicate logical notices.

### Scope Boundaries
- Do NOT dispatch events or call Resend/Redis (T8); do NOT add concurrency (T9).
- Do NOT change models (T1), preference REST (T6), or UI (T14–T16).
- Only produce events and durable notices.

### Files Expected

**New files:**
- `apps/api/app/modules/launches/tests/test_events.py`
- `apps/api/app/modules/notifications/tests/test_launch_events.py`

**Modified files:**
- `apps/api/app/modules/launches/service.py` (timed event inserts)
- `apps/api/app/modules/notifications/repository.py` (durable deduplicated notices)
- `apps/api/app/modules/notifications/service.py` (launch outcome/email/invalidation intents)

**Must NOT modify:**
- `app/shared/events/dispatcher.py` and `apps/worker/worker.py` (T8)
- Existing notifications test files (regression guards)
- Notification models (T1)

---

## Task T8: Dispatch launch events and verify delivery relevance

> **Status:** done
> **Verification:** test-after
> **Effort:** M
> **Priority:** high
> **Depends on:** T7
> **Satisfies REQs:** R6–R9, R12–R17, N2, N4
> **Footprint slice:** Register typed launch event categories and construct worker handlers for publication, reminders, email, and inbox invalidation.
> **High-risk areas touched:** Worker/outbox; notifications/WebSocket; email provider.

### Description

Dispatch launch events through the encrypted outbox worker. Recheck booking state, publication eligibility, preferences, and verified recipient immediately before handling or sending notices, while retaining retry/dead-letter behavior.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/events/tests/test_launch_dispatch.py` (new)
- `apps/worker/tests/test_launch_worker.py` (new)

#### Test Scenarios

##### Dispatch and publication
- **Routes typed launch events** — GIVEN reminder/publication/email event types, WHEN dispatched, THEN each reaches its handler; unknown types dead-letter safely and existing auth/product/review/notification handlers remain unchanged _(verifies R12–R17; regression guard)_
- **Rechecks publication eligibility** — GIVEN due event, WHEN handled, THEN current booking, product state, UTC day, and suspension are checked; same-day recovery publishes, missed-day/suspension outcomes persist, replay is idempotent _(verifies R6–R8, N2)_
- **Suppresses obsolete reminders** — GIVEN cancelled/replaced/returned/launched booking or at/after launch time, WHEN reminder is handled, THEN no delivery is created _(verifies R13)_

##### Delivery and retry
- **Rechecks email immediately before Resend** — GIVEN email intent, WHEN prepared for sending, THEN current preferences, booking/notice relevance, and verified recipient are checked; email choice does not suppress an enabled in-site channel _(verifies R12–R16, N4)_
- **Retries transient Resend safely** — GIVEN provider outage, WHEN retried, THEN committed state remains, provider message ID is stable, notices are not duplicated, and obsolete reminders drop _(verifies R12–R14, N2, N4)_
- **Retries Redis invalidation** — GIVEN Redis outage, WHEN invalidation delivery fails, THEN event remains retryable and PostgreSQL inbox/unread count remain available _(verifies R17, N4)_
- **Preserves existing worker handling** — GIVEN auth/product/review-email/notification events, WHEN dispatched, THEN current handlers/outcomes remain unchanged _(regression guard)_

### Implementation Notes
- **Module(s):** `app.shared.events`, `apps.worker`.
- **Pattern reference:** `shared/events/dispatcher.py`, `ReviewOutcomeEmailHandler`, and `NotificationChangedPublisher` in `apps/worker/worker.py`.
- **Key decisions:** Keep email/Redis after commit, use event ID for provider idempotency, use configured Resend in production.
- **High-risk callouts:** Preserve existing transactional emails while adding launch handler categories; tests cover existing and transient paths.

### Scope Boundaries
- Do NOT add bounded parallel dispatch; T9 owns it.
- Do NOT produce booking/outcome events (T7).
- Do NOT call external services from request handlers.
- Only implement typed dispatch and launch worker handlers.

### Files Expected

**New files:**
- `apps/api/app/shared/events/tests/test_launch_dispatch.py`
- `apps/worker/tests/test_launch_worker.py`

**Modified files:**
- `apps/api/app/shared/events/dispatcher.py` (launch event registry/handler routing)
- `apps/worker/worker.py` (launch handler construction)
- `apps/api/app/modules/launches/repository.py` (locked booking lookup and terminal outcome)
- `apps/api/app/modules/launches/service.py` (worker-facing booking outcome boundary)

**Must NOT modify:**
- `shared/events/outbox.py` claim/retry implementation
- Existing dispatcher, review-dispatch, and Resend tests (regression guards)
- Launch and notification event producers (T7)

---

## Task T9: Process cutoff events with bounded concurrency

> **Status:** done
> **Verification:** test-after
> **Effort:** L
> **Priority:** critical
> **Depends on:** T8
> **Satisfies REQs:** N1–N2, N4
> **Footprint slice:** Add configurable bounded event processing with isolated sessions; Compose values are owned by T17.
> **High-risk areas touched:** Worker/outbox; operations/load.

### Description

Process due events concurrently within a configurable limit, using a separate session and transaction per event. Verify that 1,000 eligible products sharing a UTC cutoff become public within 60 seconds.

### Test Plan

#### Test File(s)
- `apps/worker/tests/test_concurrency.py` (new)
- `apps/api/app/shared/config/tests/test_worker_concurrency_settings.py` (new)
- `tests/integration/test_launch_cutoff_load.py` (new; PostgreSQL)

#### Test Scenarios

##### Concurrency
- **Respects worker limit** — GIVEN more due events than configured concurrency, WHEN processed, THEN active handlers never exceed the configured bound _(verifies N1–N2)_
- **Isolates sessions** — GIVEN concurrently processed events, WHEN each runs, THEN each has its own `AsyncSession` and transaction _(verifies N2)_
- **Caps email independently** — GIVEN simultaneous launch email intents, WHEN sent, THEN Resend calls remain within the configured delivery bound _(verifies N4)_
- **Rejects invalid settings** — GIVEN zero, negative, or invalid worker concurrency, WHEN settings load, THEN processing fails configuration safely rather than becoming unbounded _(verifies N1–N2)_

##### Cutoff and recovery
- **Meets one-minute cutoff target** — GIVEN 1,000 eligible PostgreSQL-backed bookings due together, WHEN bounded workers process them, THEN all are publicly readable within 60 seconds and none before cutoff _(verifies N1)_
- **Retries independently** — GIVEN one transient event failure, WHEN other batch events run, THEN they complete independently; the failed item remains retryable without duplicate launch/notice _(verifies N2, N4)_
- **Preserves health progress** — GIVEN worker progress or stall, WHEN health is checked, THEN heartbeat remains fresh during work and stale progress is unhealthy _(regression guard)_

### Implementation Notes
- **Module(s):** `apps.worker`, `app.shared.config`.
- **Pattern reference:** `apps/worker/worker.py`, `apps/worker/health.py`, and validated `Settings` in `shared/config/settings.py`.
- **Key decisions:** PostgreSQL outbox remains authoritative; concurrency is bounded and configurable; every event receives an isolated session; delivery cap is separate.
- **High-risk callouts:** The load test verifies the target, while concurrency tests prevent shared-session use and failure coupling.

### Scope Boundaries
- Do NOT add worker service or unbounded task fan-out.
- Do NOT change event semantics (T8) or Compose values (T17).
- Only implement setting validation and bounded worker processing.

### Files Expected

**New files:**
- `apps/worker/tests/test_concurrency.py`
- `apps/api/app/shared/config/tests/test_worker_concurrency_settings.py`
- `tests/integration/test_launch_cutoff_load.py`

**Modified files:**
- `apps/api/app/shared/config/settings.py` (validated concurrency setting)
- `.env.example` (document worker setting)
- `apps/worker/worker.py` (bounded concurrent event sessions)

**Must NOT modify:**
- Compose files (T17)
- `shared/events/dispatcher.py` event semantics (T8)
- Worker health protocol

---

## Task T10: Add launch GraphQL reads and schema composition

> **Status:** done
> **Verification:** test-after
> **Effort:** M
> **Priority:** high
> **Depends on:** T2, T3, T6
> **Satisfies REQs:** R6, R10, R15–R17, N3, N6
> **Footprint slice:** Add launch owner/public and preference query types; compose them with product/notification reads and update exact root allowlist expectations.
> **High-risk areas touched:** Public reads/media; API/GraphQL contracts.

### Description

Expose owner launch bookings/failure reasons and saved preferences, plus an anonymous launched-only public product projection through the existing bounded read-only GraphQL endpoint. Preserve exact root allowlists and independent feature combinations.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/launches/tests/test_graphql.py` (new)
- `apps/api/app/modules/products/tests/test_graphql.py` (update exact root fields)
- `tests/integration/test_graphql_composition.py`

#### Test Scenarios

##### Query behavior
- **Scopes launch dashboard to founder** — GIVEN bookings/failure reasons for multiple founders, WHEN viewer launch query runs, THEN only the signed-in founder’s data is returned _(verifies R15, N6)_
- **Reads saved/default preferences** — GIVEN saved or absent preference row, WHEN viewer preference query runs, THEN exact values or six enabled defaults are returned to the owner _(verifies R16)_
- **Exposes only launched public projection** — GIVEN products in approved/scheduled/launched states, WHEN anonymous query runs, THEN only launched product fields and public media references are returned, excluding account/review/history fields _(verifies R6, R10, N3)_

##### Composition and privacy
- **Asserts exact schema field sets per flags** — GIVEN products/launches feature combinations, WHEN schemas are built, THEN launch roots appear only when launch feature is included, product-only/profile roots remain correct, and disabled fields are absent _(guards schema composition)_
- **Keeps GraphQL read-only and bounded** — GIVEN launch queries, WHEN schema/query validation runs, THEN there are no mutations/subscriptions and POST-only depth/field/root allowlists still reject unsafe shapes _(guards architecture boundary)_
- **Preserves existing product/profile/notification fields** — GIVEN current reads, WHEN launch fields are composed, THEN existing exact fields and privacy behavior remain _(regression guard)_

### Implementation Notes
- **Module(s):** `app.modules.launches`, `products`, `notifications`, `app.graphql`.
- **Pattern reference:** Existing `ProductQuery`, `NotificationQuery`, `ProfileOnlyQuery`, and `build_router` composition.
- **Key decisions:** Public projection calls product-owned service; launch owner reads require member scope. T12 passes runtime feature flags; T13 regenerates clients.
- **High-risk callouts:** Exact root field tests and anonymous projection checks protect the public privacy boundary.

### Scope Boundaries
- Do NOT mount REST routes or define settings (T12).
- Do NOT add mutations, subscriptions, public cache, or media byte delivery (T11).
- Do NOT hand-maintain frontend API types (T13).
- Only implement GraphQL read types and composition/allowlist behavior.

### Files Expected

**New files:**
- `apps/api/app/modules/launches/graphql.py` (owner bookings and preference read composition)
- `apps/api/app/modules/launches/tests/test_graphql.py`

**Modified files:**
- `apps/api/app/modules/products/graphql.py` (public product read)
- `apps/api/app/modules/notifications/graphql.py` (owner preference read)
- `apps/api/app/modules/launches/repository.py` (bounded owner booking history page)
- `apps/api/app/modules/launches/service.py` (owner-scoped booking history read)
- `apps/api/app/graphql.py` (root composition, allowlist, flag variants)
- `apps/api/app/modules/products/tests/test_graphql.py` (exact root assertions)
- `tests/integration/test_graphql_composition.py` (flag combinations)

**Must NOT modify:**
- `apps/api/app/modules/users/routes.py` and `main.py` runtime flag wiring (T12)
- Generated schema/client artifacts (T13)
- Existing ProductQuery private read semantics

---

## Task T11: Serve media only for launched products

> **Status:** done
> **Verification:** tdd
> **Effort:** M
> **Priority:** critical
> **Depends on:** T1, T3
> **Satisfies REQs:** R6, R10, N3, N6
> **Footprint slice:** Add a public product media route and product-owned access check for launched status and attached clean assets.
> **High-risk areas touched:** Public reads/media.

### Description

Allow anonymous visitors to fetch only the logo and screenshots attached to a launched product. Recheck persisted publication state and asset membership on every request while keeping underlying object storage private.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_launch_public_media.py` (new)

#### Test Scenarios

##### Public media access
- **Serves launched attached media anonymously** — GIVEN a launched product with attached clean logo/screenshot, WHEN a visitor requests the public media route, THEN the correct media bytes/type are returned without sign-in _(verifies R6, R10)_
- **Hides unlaunched media** — GIVEN approved/scheduled/missing products or guessed asset IDs, WHEN requested, THEN 404 is returned before object retrieval _(verifies R6, N3, N6)_
- **Rejects unattached or non-clean assets** — GIVEN private/unattached/pending/failed assets, WHEN requested, THEN they remain inaccessible _(verifies R10, N3)_
- **Does not expose storage internals** — GIVEN valid public media, WHEN response is returned, THEN object key, private signed URL, and account/review fields are absent _(verifies N3)_

### Implementation Notes
- **Module(s):** `app.modules.products` and existing private object storage interface.
- **Pattern reference:** Existing `products/routes.py` and `service.py` private media gate; keep bucket/object store private.
- **Key decisions:** Public media handler checks persisted launched state independently of page/query visibility.
- **High-risk callouts:** A direct guessed URL must not bypass the launch-state check; tests cover status and asset membership.

### Scope Boundaries
- Do NOT make the bucket public or return raw storage keys.
- Do NOT add a public cache or change private signed-media behavior.
- Only implement launched-only public media delivery.

### Files Expected

**New files:**
- `apps/api/app/modules/products/tests/test_launch_public_media.py`

**Modified files:**
- `apps/api/app/modules/products/routes.py` (anonymous public media endpoint)
- `apps/api/app/modules/products/service.py` (public launched asset authorization)
- `apps/api/app/modules/products/repository.py` (launched product and attached clean asset lookup)
- `apps/api/app/modules/products/tests/test_routes.py` (exact route inventory assertion)

**Must NOT modify:**
- `apps/api/app/modules/products/graphql.py` (T10)
- Storage bucket configuration or existing private asset URL signature behavior
- `apps/worker/worker.py`

---

## Task T12: Wire launch routes and reversible feature flag

> **Status:** done
> **Verification:** test-after
> **Effort:** M
> **Priority:** critical
> **Depends on:** T5, T9, T10, T11
> **Satisfies REQs:** R6–R9, N2–N4
> **Footprint slice:** Add launch feature setting and wire REST/GraphQL composition into the API application independently from product flag.
> **High-risk areas touched:** Database/migration/deploy; API/GraphQL contracts.

### Description

Add a reversible launch feature flag and connect launch routes and GraphQL fields to the application. Keep launches independently gated from product/profile behavior so production can deploy compatible code with launches disabled.

### Test Plan

#### Test File(s)
- `tests/integration/test_launch_feature_flag.py` (new)
- Existing application and GraphQL composition tests

#### Test Scenarios

##### Flag behavior
- **Disables launch surfaces by default** — GIVEN production settings without explicit enablement, WHEN the app is built, THEN launch REST routes and GraphQL fields are absent _(verifies N2–N4)_
- **Enables launch surfaces when configured** — GIVEN launch flag enabled, WHEN app is built, THEN booking/preference routes and launch queries are mounted _(verifies R6–R9)_
- **Keeps product flag independent** — GIVEN all combinations of product/launch flags, WHEN app is built, THEN each feature surface follows its own flag and profiles remain available _(regression guard)_
- **Disables without data rollback** — GIVEN committed booking/outbox rows, WHEN launch flag is turned off, THEN commands/public launch reads are hidden while data and compatible worker processing remain available _(verifies N2–N4)_
- **Preserves readiness and existing routes** — GIVEN flag on/off, WHEN health/profile/product routes are inspected, THEN their established behavior remains _(regression guard)_

### Implementation Notes
- **Module(s):** app settings, FastAPI wiring, user/GraphQL composition.
- **Pattern reference:** `main.py`, `users/routes.py`, and existing `products_enabled` handling.
- **Key decisions:** `LAUNCHPAD_LAUNCHES_ENABLED` is reversible and independent. Production defaults off; local/check enablement is explicit in T17.
- **High-risk callouts:** A code rollback must not require schema downgrade or hide worker compatibility for committed events.

### Scope Boundaries
- Do NOT change migration or delete committed data.
- Do NOT configure Compose values (T17) or regenerate contracts (T13).
- Only wire the flag and API surfaces.

### Files Expected

**New files:**
- `tests/integration/test_launch_feature_flag.py`

**Modified files:**
- `apps/api/app/shared/config/settings.py` (reversible flag, default off)
- `.env.example` (document flag)
- `apps/api/app/main.py` (conditionally mount launch routes)
- `apps/api/app/modules/users/routes.py` (pass independent launch/product flags)
- `apps/api/app/graphql.py` (compose launch queries without private product reads)
- `apps/api/app/modules/notifications/routes.py` (gate launch preferences with the launch flag)
- `apps/api/app/modules/products/tests/test_graphql.py` (cover independent root composition and app flags)
- `apps/api/app/modules/notifications/tests/test_preference_routes.py` (enable the preference route in direct router tests)

**Must NOT modify:**
- Compose files (T17)
- Migration 0012 (T1)

---

## Task T13: Regenerate launch API and GraphQL contracts

> **Status:** not started
> **Verification:** test-after
> **Effort:** M
> **Priority:** high
> **Depends on:** T5, T6, T10, T12
> **Satisfies REQs:** R1–R5, R10, R15–R17, N3, N6
> **Footprint slice:** Regenerate authoritative REST/GraphQL contracts and generated TypeScript clients after launch endpoints and queries are final.
> **High-risk areas touched:** API/GraphQL contracts.

### Description

Regenerate OpenAPI, GraphQL schema/operations, and TypeScript types from the completed API contracts. Keep frontend client types generated and ensure the quality contract workflow detects drift.

### Test Plan

#### Test File(s)
- `scripts/quality/contracts.sh`
- Contract generation and frontend/API type checks invoked by that script

#### Test Scenarios

##### Generated contract verification
- **Generates REST booking/preferences shapes** — GIVEN final REST schemas, WHEN contracts regenerate, THEN booking/reschedule/cancel and preference operations/fields are present with correct types _(verifies R1–R5, R16)_
- **Generates GraphQL launch reads** — GIVEN final composed schemas, WHEN contracts regenerate, THEN owner launch/preferences and public projection fields are present _(verifies R10, R15–R17)_
- **Updates generated TypeScript types** — GIVEN contract changes, WHEN generation runs, THEN corresponding client types are generated and no hand-maintained duplicates are introduced _(verifies N6)_
- **Contract check is repeatable** — GIVEN generated artifacts committed, WHEN `sh scripts/quality/contracts.sh` runs again, THEN it passes without generated drift _(regression guard)_
- **Preserves disabled-schema contract** — GIVEN launch feature disabled, WHEN schema contract validation runs, THEN disabled fields remain absent while prior profile/product contracts remain _(verifies N3)_

### Implementation Notes
- **Module(s):** `packages/contracts`, `scripts/quality`.
- **Pattern reference:** Existing contract generation script and generated OpenAPI/GraphQL artifacts.
- **Key decisions:** Source schemas/operations are authoritative; regenerate rather than hand-edit generated TypeScript.
- **High-risk callouts:** Contract consistency protects clients from schema drift; run the full script after generation.

### Scope Boundaries
- Do NOT change domain/API behavior or implement missing endpoints.
- Do NOT manually edit generated TypeScript in place of schema generation.
- Only update generated artifacts and the contract workflow if required to verify them.

### Files Expected

**New files:** None.

**Modified files:**
- `packages/contracts/openapi.json`
- `packages/contracts/schema.graphql`
- `packages/contracts/operations.graphql`
- `packages/contracts/src/generated.ts`
- `packages/contracts/src/graphql.generated.ts`
- `scripts/quality/contracts.sh` (only if needed to include launch operations in the existing generation/check flow)

**Must NOT modify:**
- API source schemas/routes (T5, T6, T10)
- Frontend handwritten API types (use generated output)

---

## Task T14: Add launch frontend clients and query hooks

> **Status:** not started
> **Verification:** tdd
> **Effort:** M
> **Priority:** high
> **Depends on:** T13
> **Satisfies REQs:** R1–R5, R12–R17, N2, N6
> **Footprint slice:** Add typed launch REST/GraphQL client and TanStack Query hooks with cache invalidation and live-notification refresh integration.
> **High-risk areas touched:** Frontend; API contracts.

### Description

Provide generated-type-backed browser clients and query/mutation hooks for booking, reschedule, cancellation, dashboard reads, and preference settings. Integrate with existing notification invalidation so connected founders refresh state safely.

### Test Plan

#### Test File(s)
- `apps/web/src/launches/useLaunches.test.ts` (new)
- `apps/web/src/launches/client.test.ts` (new)

#### Test Scenarios

##### Client and hooks
- **Serializes launch dates as UTC calendar values** — GIVEN a founder booking in any browser timezone, WHEN requested, THEN date and returned midnight remain UTC-labeled and no local-date shift occurs _(verifies R1–R2)_
- **Calls booking commands with versions and keys** — GIVEN schedule/reschedule/cancel mutations, WHEN invoked, THEN generated request types, expected version, and idempotency key are sent _(verifies R2–R5, N2)_
- **Invalidates launch queries after mutations** — GIVEN successful booking changes, WHEN mutation resolves, THEN owner booking/dashboard query state reconciles with server response _(verifies N2)_
- **Stores all six preference choices** — GIVEN preference values, WHEN read/updated, THEN exact independent channel/type choices are sent and cached _(verifies R16)_
- **Refreshes on live notification invalidation** — GIVEN an authenticated account receives notification.changed, WHEN hook receives invalidation, THEN inbox/unread and launch-relevant data refetch without private payload delivery _(verifies R17, N6)_
- **Handles server failures without stale optimism** — GIVEN conflict or network failure, WHEN mutation fails, THEN cached booking state rolls back/reconciles and safe server error is exposed _(verifies N2)_

### Implementation Notes
- **Module(s):** `apps/web/src/launches`.
- **Pattern reference:** `products/client.ts`, `useProducts.ts`, and `notifications/useNotifications.ts`.
- **Key decisions:** TanStack Query owns server state; use generated contracts; do not make browser validation authoritative.
- **High-risk callouts:** Date serialization and optimistic rollback are tested independently.

### Scope Boundaries
- Do NOT hand-maintain API types or build view components (T15/T16).
- Do NOT make client-side capacity or authorization decisions.
- Only implement API clients, query hooks, and cache/live invalidation behavior.

### Files Expected

**New files:**
- `apps/web/src/launches/client.ts`
- `apps/web/src/launches/useLaunches.ts`
- `apps/web/src/launches/client.test.ts`
- `apps/web/src/launches/useLaunches.test.ts`

**Modified files:** None.

**Must NOT modify:**
- Generated contracts (T13)
- Existing notification transport or server state architecture
- UI screens/styles (T15/T16)

---

## Task T15: Build founder launch dashboard and controls

> **Status:** not started
> **Verification:** ui
> **Effort:** L
> **Priority:** high
> **Depends on:** T14
> **Satisfies REQs:** R1–R5, R15–R16, N5–N6
> **Footprint slice:** Founder launch booking/dashboard/preferences screens and signed-in route using launch hooks.
> **High-risk areas touched:** Frontend; booking and capacity.

### Description

Give founders a clear place to book, reschedule, cancel, and monitor launch outcomes, and to set six notice preferences. Use the approved Brutalism & Neobrutalism direction with responsive, accessible controls.

### Verification Checklist

- **Booking states** — Render no booking, scheduled booking, capacity conflict, failed booking, missed-day, suspension-blocked, and launched states; each shows a clear next action/reason.
- **Booking interactions** — Schedule, reschedule, and cancel through hooks; verify confirmation and server errors preserve displayed state appropriately.
- **UTC presentation** — Dates and 00:00 boundary are labeled UTC and remain consistent at browser timezone changes.
- **Preferences** — Six independent switches load saved/default-on values and save one choice without changing the other five.
- **Responsive/accessibility** — At approximately 390px and 1280px, no horizontal overflow; controls are keyboard-operable with visible focus, labels, readable contrast, and perceivable errors/status.

#### Testable Seams
- Render founder dashboard loading, empty, booked, conflict, failure, and launched states.
- Exercise booking, reschedule, cancel, and preference handlers.
- Check accessible names, keyboard operation, and visible validation/status.

### Implementation Notes
- **Module(s):** `apps/web/src/launches`.
- **Pattern reference:** `ProductScreens.tsx`, app routes, generated query hooks; read `docs/source/inspiration.md` before styling.
- **Key decisions:** Original thick borders, offset shadows, loud flat color; semantic controls/mobile-first behavior.
- **High-risk callouts:** Conflicts and failure reasons must be understandable without relying on email.

### Scope Boundaries
- Do NOT build the anonymous public product page (T16).
- Do NOT encode server authorization/capacity in the UI.
- Only implement founder booking/dashboard/preferences views and route.

### Files Expected

**New files:**
- `apps/web/src/launches/LaunchScreens.tsx` (founder views)
- `apps/web/src/launches/launches.css` (scoped styling)
- `apps/web/src/launches/LaunchScreens.test.tsx` (founder view seams)

**Modified files:**
- `apps/web/src/App.tsx` (signed-in founder launch route)
- `apps/web/src/styles.css` (import scoped launch styling)

**Must NOT modify:**
- Existing `/products/{id}` editor access behavior
- Client and query hooks (T14)
- Public route content (T16)

---

## Task T16: Build the anonymous public launch page

> **Status:** not started
> **Verification:** ui
> **Effort:** M
> **Priority:** high
> **Depends on:** T10, T11, T14, T15
> **Satisfies REQs:** R6, R10, N3, N5–N6
> **Footprint slice:** Add `/launches/{product_id}` anonymous view and route while keeping the signed-in product editor isolated.
> **High-risk areas touched:** Public reads/media; frontend.

### Description

Show launched product details and published media to anonymous visitors on a distinct launch route. Keep unlaunched products hidden and preserve the existing authenticated `/products/{id}` editor route.

### Verification Checklist

- **Launched view** — Anonymous visitor sees name, pitch, description, website link, topics, launch date, logo, and screenshots for a launched product.
- **Hidden states** — Approved, scheduled, missing, or unavailable product renders a safe not-found state without private data.
- **Private fields** — Public page contains no review feedback, founder/account details, booking history, or private asset URLs.
- **Route separation** — `/launches/{id}` is public; `/products/{id}` remains session-protected and retains editor behavior.
- **Responsive/accessibility** — At approximately 390px and 1280px, media/actions fit without horizontal overflow; keyboard focus, link names, image alternatives, contrast, and status semantics are usable.

#### Testable Seams
- Render loading, launched, and safe not-found states.
- Check media, website/topic links, and public-field boundaries.
- Check accessible names, image alternatives, and keyboard navigation.

### Implementation Notes
- **Module(s):** `apps/web/src/launches`.
- **Pattern reference:** `ProductScreens.tsx` and `App.tsx`; use T14 hooks/generated contracts and read `docs/source/inspiration.md`.
- **Key decisions:** Public URL is `/launches/{product_id}`; only server projection decides visibility.
- **High-risk callouts:** Route tests/views must never reuse the private editor component in anonymous context.

### Scope Boundaries
- Do NOT add voting, comments, rankings, search, or broad site redesign.
- Do NOT fetch unpublished media or add public caching.
- Only implement the public launch view and distinct route.

### Files Expected

**New files:** None; extend the launch screen module from T15.

**Modified files:**
- `apps/web/src/launches/LaunchScreens.tsx` (public page)
- `apps/web/src/launches/launches.css` (public page styling)
- `apps/web/src/launches/LaunchScreens.test.tsx` (anonymous/privacy route cases)
- `apps/web/src/App.tsx` (public route before private product editor route)

**Must NOT modify:**
- `apps/api/app/modules/products/routes.py` media gate (T11)
- Existing `/products/{id}` authorization behavior
- Out-of-scope discovery/community screens

---

## Task T17: Configure launch environments in Compose

> **Status:** not started
> **Verification:** checklist
> **Effort:** M
> **Priority:** high
> **Depends on:** T9, T12
> **Satisfies REQs:** R6–R9, N1–N4
> **Footprint slice:** Set launch feature flag and bounded worker concurrency for local, check, and production Compose environments.
> **High-risk areas touched:** Database/migration/deploy; operations/load.

### Description

Configure each existing Compose environment for launch rollout and worker limits without adding a service. Keep local/check behavior explicit and production launch commands disabled until operators enable them after compatible API/worker deployment.

### Verification Checklist

- **Local Compose config** — Run `docker compose config --quiet`; expected: valid config and launch flag/worker limit explicitly set for local launch testing.
- **Check Compose config** — Run `docker compose -f compose.checks.yaml config --quiet`; expected: launch feature and concurrency values are explicit, with existing health dependencies intact.
- **Production Compose config** — Run `docker compose -f compose.production.yaml config --quiet` with provisioned env files; expected: launch flag is disabled by default, worker concurrency is configured from secret-free runtime settings, and no new service or host-published database/cache port is introduced.
- **Worker/API environment split** — Inspect rendered service definitions without printing secret values; expected: API, worker, and scheduler keep their separate process/env responsibilities and compatible launch settings.
- **Health/regression** — Existing API, worker, scheduler, database, and Redis health checks remain present and Compose config resolves cleanly.

### Implementation Notes
- **Module(s):** Compose runtime environments.
- **Pattern reference:** Current `compose.yaml`, `compose.checks.yaml`, and `compose.production.yaml` service/env separation.
- **Key decisions:** No microservice/new process; production launches remain opt-in; worker limit is configurable.
- **High-risk callouts:** Production rollout must keep launch flag off until schema and workers are compatible; configuration checks avoid disclosing secrets.

### Scope Boundaries
- Do NOT change application behavior or migration schema.
- Do NOT expose Postgres/Redis or add a new service.
- Only configure existing Compose service environments.

### Files Expected

**New files:** None.

**Modified files:**
- `compose.yaml` (explicit local launch/concurrency settings)
- `compose.checks.yaml` (check environment settings)
- `compose.production.yaml` (production opt-in and worker limit)

**Must NOT modify:**
- Production credentials or env-file secrets
- `apps/worker/worker.py` concurrency implementation (T9)
- API settings/flag wiring (T12)

---

## Task T18: Document launch operations and recovery

> **Status:** not started
> **Verification:** checklist
> **Effort:** S
> **Priority:** high
> **Depends on:** T1–T17
> **Satisfies REQs:** R1–R9, R12–R17, N1–N4
> **Footprint slice:** Add launch UTC, rollout, monitoring, and recovery guidance to `docs/development.md`.
> **High-risk areas touched:** Operations/load; database/migration/deploy.

### Description

Document how operators deploy and monitor launch scheduling/publication and how they distinguish delayed work from missed-day, suspension, or delivery outcomes. Provide safe recovery guidance that preserves booking history and committed events.

### Verification Checklist

- **Booking operating rules** — Guidance states shared UTC calendar, 00:00 UTC cutoff, D+1 through D+90, two-per-founder/day, and strict cancel/reschedule boundary.
- **Rollout/rollback** — Steps explain migration 0012, compatible API/worker deployment, feature flag enable/disable, and forward-fix rollback without downgrade/data deletion.
- **Monitoring** — Document due backlog age/count, launch latency/one-minute target, missed/suspended outcomes, retry/dead-letter counts, and email/inbox delivery status; logs avoid secrets/content.
- **Recovery** — Explain same-day recovery, missed-day return-to-approved/rebook, suspension-blocked/reinstatement/rebook, and how to handle obsolete reminders or provider outages.
- **Operator checkability** — Each referenced command, setting, metric, and file path exists in the repo/deployment design; no procedure implies manually publishing an unpublished product or deleting history.
- **Editorial consistency** — Review links and terminology match the final REQ/ARCH and deployed feature names.

### Implementation Notes
- **Module(s):** Engineering operations documentation.
- **Pattern reference:** Existing `docs/development.md`, `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md`, and production compose/deploy procedures.
- **Key decisions:** PostgreSQL is authoritative; Redis/outbox hints are retryable; migration is forward-only; feature flag is reversible.
- **High-risk callouts:** Recovery instructions must preserve audit history and not bypass eligibility or UTC rules.

### Scope Boundaries
- Do NOT create an unrelated deployment runbook or change production infrastructure.
- Do NOT document unsupported manual database edits as recovery steps.
- Only add launch operating and recovery guidance.

### Files Expected

**New files:** None.

**Modified files:**
- `docs/development.md` (launch operations, monitoring, flag rollout, and recovery)

**Must NOT modify:**
- Product behavior, deployment secrets, or production database state
- Client-facing feature guide (outside this architecture footprint)

---

_For implementation, use `/implement T1 from: specs/architecture/ARCH-add-launch-scheduling-publication.md`. After the running feature is implemented, `/plan-qa` and `/execute-qa` can drive its end-to-end surface independently of `/review`._
