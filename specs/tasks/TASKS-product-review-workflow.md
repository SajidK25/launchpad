# Tasks

## Task T1: Add Review and Notification Schema

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R1, R2, R3, R4, R7, R8, R9, N3
> **Footprint slice:** New 0008 migration and notification model; modified product and submission models.
> **High-risk areas touched:** Product lifecycle and submission queue; private reads and media; migration and rollout.

### Description

Extend the PostgreSQL lifecycle checks and create immutable review-decision and durable notification tables. Constraints and indexes establish the invariants that later services must preserve without rewriting the existing migration history.

### Test Plan

#### Test File(s)
- `tests/integration/test_product_review_schema.py`
- `apps/api/app/modules/products/tests/test_review_models.py`
- `apps/api/app/modules/products/tests/test_models.py`

#### Test Scenarios

##### Migration and Constraints

- **upgrades current head** — GIVEN a database at revision 0007 WHEN revision 0008 applies THEN existing products, submissions, and accounts remain readable and the new tables exist _(verifies R7; guards backward-regression risk for old migrations)_.
- **permits private correction state** — GIVEN a `changes_requested` product with incomplete fields WHEN it is saved THEN the DB accepts it; incomplete `submitted`, `approved`, or `rejected` rows are refused _(verifies R2, R3, N3)_.
- **enforces period and decision cardinality** — GIVEN a reviewed period WHEN a second initial decision or a second approved-return decision is inserted THEN uniqueness rejects it, while one of each is retained _(verifies R1, R2, R7)_.
- **enforces reason and retention** — GIVEN a reject/change decision with blank or >2,000-character feedback or a reviewed product deletion WHEN persisted THEN constraints/FKs reject it _(verifies R3, R4, R8; REQ edge case)_.
- **indexes bounded reads** — GIVEN the new schema WHEN indexes are inspected THEN pending order, approved cursor, decision history, recipient cursor, and unread-recipient access paths exist _(verifies R9; ARCH 10K-to-10M stress case)_.

### Implementation Notes

- **Module(s):** products models, notifications models, Alembic.
- **Pattern reference:** `apps/api/app/modules/products/models.py` and revision `0005_product_drafts_submission.py`.
- **Key decisions:** A1, A2, A8; no new public product state and no cascade deletion of review records.
- **Libraries:** SQLAlchemy 2, Alembic, PostgreSQL, pytest.
- **High-risk callouts:** Preserve old rows and exact-head readiness; verify changed check constraints against correction edits.

### Scope Boundaries

- Do NOT rewrite revisions 0001–0007 or add scheduling/publication schema.
- Only add schema and mappings specified in ARCH Data Models.

### Files Expected

**New files:**
- `apps/api/alembic/versions/0008_product_review_notifications.py` (forward migration, following product revisions).
- `apps/api/app/modules/notifications/models.py` (notification mapping, following product models).
- `tests/integration/test_product_review_schema.py`; `apps/api/app/modules/products/tests/test_review_models.py` (verification).

**Modified files:**
- `apps/api/app/modules/products/models.py` (new states and review-decision mapping).
- `apps/api/app/modules/products/tests/test_models.py` (extend existing model-constraint expectations).
- `tests/integration/test_product_schema.py` (use the dynamic migration head in its backfill regression assertion).

**Must NOT modify:**
- `apps/api/alembic/versions/0005_product_drafts_submission.py`; `apps/api/alembic/versions/0007_product_submission_product_index.py` (applied/shared history).
- `apps/api/app/shared/db/database.py`; `apps/api/alembic/env.py` (exact-head readiness behavior).

---

## Task T2: Persist Founder Notifications in the Review Transaction

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R6, R7, R9, N1, N4
> **Footprint slice:** New notifications repository, service, and policy boundary; modified named auth recipient access.
> **High-risk areas touched:** Notifications and WebSockets; transactional email; private reads and media.

### Description

Provide the notification service that a product decision calls inside its database transaction. It inserts one durable founder notice and encrypted email/live outbox events, using an auth-owned recipient interface rather than an auth repository import.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/notifications/tests/test_service.py`
- `apps/api/app/modules/auth/tests/test_review_recipient.py`

#### Test Scenarios

##### Transactional Outcome

- **records both channels atomically** — GIVEN a valid decision WHEN the service records its outcome THEN one owner notice and the email/live outbox rows exist in the caller transaction _(verifies R6, R9, N1)_.
- **deduplicates replay** — GIVEN a decision already notified WHEN recording is retried THEN its unique decision mapping prevents a second notice or email request _(verifies R6, N1)_.
- **rolls back together** — GIVEN an outbox insertion failure WHEN the caller rolls back THEN no notice or partial review side effect remains _(verifies N1; ARCH provider-failure stress case)_.
- **uses current verified recipient** — GIVEN an account email or verification change WHEN recipient lookup runs THEN the named auth service returns only the current eligible destination and never exposes another account's email _(verifies R6, N3)_.
- **keeps provider out of transaction** — GIVEN Resend or Redis unavailable WHEN the notification service runs THEN it performs no network delivery and leaves dispatch to the outbox _(verifies N1, N4; ARCH outage stress case)_.

### Implementation Notes

- **Module(s):** notifications, auth named access.
- **Pattern reference:** `apps/api/app/shared/events/outbox.py`, `apps/api/app/modules/auth/staff.py`, product service protocols.
- **Key decisions:** A4, A5, A6; PostgreSQL is authoritative and outbox rows share the review transaction.
- **Libraries:** SQLAlchemy 2 async, encrypted outbox, pytest.
- **High-risk callouts:** Never place feedback or recipient email in logs or a Redis hint; tests cover duplicate and rollback paths.

### Scope Boundaries

- Do NOT add notification preference management or synchronous provider calls.
- Only create review outcome notices and their delivery requests.

### Files Expected

**New files:**
- `apps/api/app/modules/notifications/__init__.py`, `repository.py`, `service.py`, `policies.py` (module boundary, following products/auth layers).
- `apps/api/app/modules/notifications/tests/test_service.py`; `apps/api/app/modules/auth/tests/test_review_recipient.py` (verification).

**Modified files:**
- `apps/api/app/modules/auth/staff.py` (named current verified recipient lookup).

**Must NOT modify:**
- `apps/api/app/shared/events/outbox.py`; `apps/api/app/shared/events/models.py` (reuse encrypted durable contract).
- Auth account/session models (current-state lookup is enough).

---

## Task T3: Enforce Review and Founder Correction Transitions

> **Status:** done
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T1, T2
> **Satisfies REQs:** R1, R2, R3, R4, R5, R7, R8, N1, N3
> **Footprint slice:** Modified product repository, service, and policies for decision, correction, resubmission, and deletion guard.
> **High-risk areas touched:** Product lifecycle and submission queue; private reads and media; notifications and WebSockets.

### Description

Make the product service the sole authority for review decisions and subsequent founder actions. It checks live staff eligibility and the current period/version under a product lock, records immutable actions, and calls the notification service in the same transaction.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_review_service.py`
- `tests/integration/test_product_review_transitions.py`
- `apps/api/app/modules/products/tests/test_submissions.py`

#### Test Scenarios

##### Review Decisions

- **resolves each pending outcome** — GIVEN a current submitted period WHEN eligible staff approve, reject, or request changes THEN one decision, matching private state, actor/time, and founder notice are committed _(verifies R1, R2, R3, R4, R7)_.
- **returns approved work for changes** — GIVEN an approved private product WHEN staff supply valid feedback THEN a second immutable decision is added and founder edits become allowed _(verifies R2, R7; REQ edge case)_.
- **rejects stale and competing actions** — GIVEN a withdrawn/changed period or two reviewers on one version WHEN a stale action arrives THEN it conflicts without audit, state, or notification changes _(verifies R5; ARCH concurrency stress case)_.
- **replays only identical requests** — GIVEN an actor/key already used WHEN the same normalized command repeats THEN the prior result returns; a changed command with that key conflicts _(verifies R1, N1)_.

##### Founder Correction and Regression

- **resubmits behind waiting work** — GIVEN `changes_requested` and other pending products WHEN the founder corrects and resubmits THEN a new period enters the queue last and the old period remains historical _(verifies R3; REQ edge case)_.
- **locks final or approved work** — GIVEN `approved` or `rejected` WHEN the founder edits, withdraws, or submits THEN no content or state changes; media remains private _(verifies R2, R4, R8, N3; REQ edge case)_.
- **retains reviewed products after withdrawal** — GIVEN any prior decision and a later withdrawn draft WHEN founder deletion runs THEN it is denied; an otherwise eligible never-reviewed draft still deletes _(verifies R8; guards existing deletion behavior)_.
- **preserves private-draft cap and existing rules** — GIVEN a change request at the cap WHEN staff resolve it THEN success is not blocked, but new draft creation respects the cap; verified/suspension/completeness rules still gate resubmission _(verifies R3, R8; guards existing submission/quota behavior)_.

### Implementation Notes

- **Module(s):** products service/repository/policies; notification service interface.
- **Pattern reference:** `ProductService.submit_draft`, `withdraw_submission`, `delete_draft`, and repository row/version updates.
- **Key decisions:** A1–A4, A8; unique `(submission_id, from_status)`, stable idempotency key, and explicit state policy.
- **Libraries:** SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Lock ordering must match founder writes; decision and notice must never split across transactions.

### Scope Boundaries

- Do NOT schedule, publish, reopen rejected work, or add staff account management.
- Only implement the states, action records, and founder actions in the REQ.

### Files Expected

**New files:**
- `apps/api/app/modules/products/tests/test_review_service.py`; `tests/integration/test_product_review_transitions.py` (verification).

**Modified files:**
- `apps/api/app/modules/products/repository.py` (locked/versioned decision queries, history, edit/count/delete guards).
- `apps/api/app/modules/products/service.py` (decision transaction, correction/resubmission, owner outcome).
- `apps/api/app/modules/products/policies.py` (named staff, editable, locked, and reviewed-delete policies).
- `apps/api/app/modules/products/tests/test_submissions.py` (retain existing submission expectations under expanded states).

**Must NOT modify:**
- `apps/api/app/shared/storage/objects.py` (signed private media authority).
- `apps/api/app/modules/products/tests/test_assets.py`; `test_media.py`; `test_queue.py` (run existing regression behavior without changing those tests).
- `tests/integration/test_product_submission.py`; `test_product_deletion.py` (run existing never-reviewed period/deletion behavior).

---

## Task T4: Expose the Staff Review REST Command

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T3, T10
> **Satisfies REQs:** R1, R2, R3, R4, R5, N2, N3
> **Footprint slice:** Modified product schemas and REST routes for one gated review command.
> **High-risk areas touched:** Product lifecycle and submission queue; private reads and media; migration and rollout.

### Description

Add the `POST /api/v1/staff/products/{product_id}/review-decisions` command and typed request/response. Reuse cookie, Origin, CSRF, rate-limit, and safe-error patterns; the review flag disables writes while leaving committed reads available.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_review_routes.py`
- `tests/integration/test_product_review_api.py`
- `apps/api/app/modules/products/tests/test_routes.py`

#### Test Scenarios

##### HTTP Contract

- **accepts valid staff outcomes** — GIVEN active reviewer/admin session, current period/version, CSRF, and key WHEN each outcome is posted THEN the response names decision, status, and next version _(verifies R1, R2, R3, R4)_.
- **rejects ineligible callers** — GIVEN visitor/member/unverified/suspended staff WHEN command is posted THEN safe 401/403/404 response and no decision _(verifies R1, N3)_.
- **validates feedback** — GIVEN blank or >2,000-character corrective feedback WHEN posted THEN 422 and unchanged pending state _(verifies R3, R4; REQ edge case)_.
- **maps freshness and key errors** — GIVEN stale version/period or reused key with different payload WHEN posted THEN 409 refresh/conflict without notification _(verifies R5)_.
- **enforces request protection and flag** — GIVEN absent/bad CSRF or Origin, rate-limit exhaustion, or disabled review writes WHEN posted THEN safe denial/429/503 and no state change _(verifies N3; ARCH rollout stress case)_.

### Implementation Notes

- **Module(s):** products HTTP boundary.
- **Pattern reference:** `apps/api/app/modules/products/routes.py` owner commands and `schemas.py` Pydantic models.
- **Key decisions:** A3, A10; REST is a thin command layer and the idempotency key is mandatory.
- **Libraries:** FastAPI, Pydantic, pytest.
- **High-risk callouts:** Do not leak product existence or raw feedback in transport errors.

### Scope Boundaries

- Do NOT add a GraphQL mutation or a public review endpoint.
- Only expose the approved ARCH decision contract.

### Files Expected

**New files:**
- `apps/api/app/modules/products/tests/test_review_routes.py`; `tests/integration/test_product_review_api.py` (verification).

**Modified files:**
- `apps/api/app/modules/products/schemas.py` (review input/output and status union).
- `apps/api/app/modules/products/routes.py` (staff command and safe error mapping).
- `apps/api/app/modules/products/tests/test_routes.py` (extend route contract expectations).

**Must NOT modify:**
- Auth session/account models (reuse live session service).
- `apps/api/app/shared/storage/objects.py` (private media path).

---

## Task T5: Compose Founder and Staff Review Reads

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T3
> **Satisfies REQs:** R2, R3, R4, R5, R6, R7, N3
> **Footprint slice:** Modified product GraphQL read types, queue/detail, and approved staff discovery.
> **High-risk areas touched:** Private reads and media; product lifecycle and submission queue; frontend and contracts.

### Description

Extend the existing read composition so a founder can reopen the latest outcome and staff can find approved work for correction. Preserve owner/staff isolation and oldest-first pending order.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_review_graphql.py`
- `tests/integration/test_product_review_reads.py`

#### Test Scenarios

##### Authorized Reads

- **shows founder outcome and feedback** — GIVEN approval, rejection, change request, or approved return WHEN the owner queries detail THEN current status and applicable feedback appear without staff-only metadata _(verifies R2, R3, R4, R6)_.
- **keeps queue snapshot fresh** — GIVEN pending period/version WHEN staff read queue and detail THEN both expose the command identity/version and existing oldest-first order _(verifies R5; guards existing queue behavior)_.
- **finds approved work** — GIVEN multiple approved products WHEN staff page `approvedReviews` and open detail THEN they can find and return the chosen product without accessing rejected/other states there _(verifies R2, R7)_.
- **denies foreign/public reads** — GIVEN another founder or visitor WHEN they query outcome, approved list, or media-linked detail THEN no unlaunched content or reviewer feedback is returned _(verifies N3; REQ privacy edge case)_.
- **preserves existing roots** — GIVEN existing viewer/profile product operations WHEN new fields are composed THEN their previous fields and access errors remain valid _(guards ARCH GraphQL backward-regression risk)_.

### Implementation Notes

- **Module(s):** products GraphQL; product service/repository interfaces from T3.
- **Pattern reference:** `ProductQuery`, `staff_queue`, `staff_detail`, `owner_detail`.
- **Key decisions:** A1, A2, A9; GraphQL is read-only, and approved remains private.
- **Libraries:** Strawberry GraphQL, pytest.
- **High-risk callouts:** Enforce named policies before fetching private details; do not infer visibility from status alone.

### Scope Boundaries

- Do NOT expose public launch, search, ranking, or staff-only audit fields to founders.
- Only add review read fields and approved correction discovery.

### Files Expected

**New files:**
- `apps/api/app/modules/products/tests/test_review_graphql.py`; `tests/integration/test_product_review_reads.py` (verification).

**Modified files:**
- `apps/api/app/modules/products/graphql.py` (founder outcome, review identity, approved list/detail).

**Must NOT modify:**
- `apps/api/app/modules/users/routes.py` (profile route contract).
- `apps/api/app/modules/products/tests/test_graphql.py`; `test_queue.py` (existing regressions run as-is).
- `apps/api/app/shared/storage/objects.py` (signed media policy).

---

## Task T6: Read and Mark Individual Notifications

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T2
> **Satisfies REQs:** R6, R9, N3, N4
> **Footprint slice:** Notification repository/service read methods plus new schemas and GraphQL inbox composition.
> **High-risk areas touched:** Notifications and WebSockets; private reads and media; frontend and contracts.

### Description

Provide bounded owner-only notification reads and an idempotent one-item read operation in the notification service. Expose the GraphQL inbox resolver; the HTTP route and shared read-root wiring follow in T7. Opening the bell is a read and must not change any item's state.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/notifications/tests/test_reads.py`

#### Test Scenarios

##### Inbox and Read State

- **pages recipient history** — GIVEN many notices for two founders WHEN one founder requests a bounded cursor page THEN only their notices return in stable order with their unread count _(verifies R9, N4; ARCH scale case)_.
- **marks one item once** — GIVEN two unread notices WHEN the owner opens one THEN only it receives `read_at`, count falls by one, and a second identical PUT changes nothing _(verifies R9)_.
- **keeps bell-open read-only** — GIVEN an unread inbox WHEN only the list is queried THEN count/read timestamps remain unchanged _(verifies R9; REQ edge case)_.
- **denies cross-account access** — GIVEN another account or visitor WHEN they query or mark a notification THEN no item or count leaks and no read state changes _(verifies N3, N4)_.
- **publishes read invalidation durably** — GIVEN a first read-state change WHEN it commits THEN one live outbox hint is stored; a no-op retry adds none _(verifies R9, N4; ARCH duplicate-hint stress case)_.
- **keeps read composition private** — GIVEN a resolver call with a foreign or absent member context WHEN notifications are requested THEN no other recipient's rows or count are returned _(guards private-read regression risk)_.

### Implementation Notes

- **Module(s):** notifications HTTP/GraphQL boundary and shared GraphQL root.
- **Pattern reference:** `apps/api/app/modules/products/graphql.py`, `routes.py`, and `app/graphql.py`.
- **Key decisions:** A4, A7; PostgreSQL count and item state are authoritative.
- **Libraries:** FastAPI, Strawberry GraphQL, pytest.
- **High-risk callouts:** Scope every repository read/update by live account ID and bound page size.

### Scope Boundaries

- Do NOT implement notification preferences, bulk mark-read, or other notification types.
- Only read review notices and mark one owned notice read.

### Files Expected

**New files:**
- `apps/api/app/modules/notifications/schemas.py`, `graphql.py` (typed inbox boundary, following products module).
- `apps/api/app/modules/notifications/tests/test_reads.py` (verification).

**Modified files:**
- `apps/api/app/modules/notifications/repository.py`, `service.py` (bounded owner reads, unread count, one-item read and live outbox insertion).

**Must NOT modify:**
- `apps/api/app/modules/users/routes.py` (profile read transport).
- `apps/api/app/shared/events/outbox.py`; `models.py` (reuse live event persistence).

---

## Task T7: Bind Account-Scoped Notification WebSockets

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T2, T6
> **Satisfies REQs:** R9, N3, N4
> **Footprint slice:** New notification read route and live endpoint; modified API and GraphQL router registration.
> **High-risk areas touched:** Notifications and WebSockets; private reads and media; migration and rollout.

### Description

Wire the notification REST/GraphQL read surfaces and add a cookie-authenticated, exact-Origin WebSocket that subscribes only to the current account's Redis channel. The socket sends a small invalidation hint, revalidates sessions, and leaves persisted reads available after disconnect.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/notifications/tests/test_routes.py`
- `apps/api/app/modules/notifications/tests/test_live.py`
- `tests/integration/test_notification_live.py`

#### Test Scenarios

##### Connection Security

- **binds correct account** — GIVEN two connected founders WHEN an event is published for one THEN only that account receives a hint without product details _(verifies N4, N3)_.
- **rejects bad handshake** — GIVEN missing/revoked cookie or untrusted Origin WHEN connecting THEN the socket is rejected without subscribing _(verifies N4)_.
- **closes after revocation** — GIVEN an authenticated connection WHEN account/session becomes ineligible THEN revalidation closes it before further hints _(verifies N4; ARCH auth regression case)_.
- **recovers missed hints** — GIVEN Redis outage or disconnected socket WHEN the founder reconnects and reads GraphQL inbox THEN persisted items/count match PostgreSQL _(verifies R9, N4; REQ disconnect edge case)_.
- **wires one-item REST read** — GIVEN an owned item and valid CSRF/Origin WHEN PUT is sent THEN one item is marked read; a foreign ID is hidden and a repeat is idempotent _(verifies R9, N3)_.
- **keeps old API routes** — GIVEN product/profile routes WHEN live router is registered THEN prior route and GraphQL availability remains unchanged _(guards backward-regression risk for `apps/api/app/modules/users/routes.py`)_.

### Implementation Notes

- **Module(s):** notifications live endpoint, API composition.
- **Pattern reference:** `apps/api/app/main.py`, auth session service, trusted-origin utility.
- **Key decisions:** A5, A10; Redis hints are account-scoped and disposable.
- **Libraries:** FastAPI WebSockets, Redis pub/sub, pytest.
- **High-risk callouts:** Avoid subscribing before session/Origin checks; handle pub/sub cancellation and reconnect cleanly.

### Scope Boundaries

- Do NOT send feedback or notification history over WebSocket.
- Only deliver an account-scoped invalidation hint for existing inbox reads.

### Files Expected

**New files:**
- `apps/api/app/modules/notifications/routes.py`, `live.py` (one-item command and authenticated WebSocket, following API session patterns).
- `apps/api/app/modules/notifications/tests/test_routes.py`, `test_live.py`; `tests/integration/test_notification_live.py` (verification).

**Modified files:**
- `apps/api/app/graphql.py` (notification query and safe read root).
- `apps/api/app/main.py` (register inbox HTTP and WebSocket; preserve reads while review writes disabled).

**Must NOT modify:**
- Auth session/account models (reuse live resolution).
- `apps/api/app/modules/users/routes.py` (existing profile route).

---

## Task T8: Dispatch Review Email and Live Events

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T2, T3
> **Satisfies REQs:** R6, R9, N1, N4
> **Footprint slice:** Modified event dispatcher and worker wiring for two new event types.
> **High-risk areas touched:** Event dispatch; transactional email; notifications and WebSockets.

### Description

Register typed handlers for review outcome email and account-scoped Redis invalidation. Reuse encrypted outbox claim/retry/dead-letter behavior and keep existing auth email and product event handling intact.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/events/tests/test_review_dispatch.py`
- `tests/integration/test_review_outbox.py`
- `apps/api/app/modules/products/tests/test_events.py`

#### Test Scenarios

##### Dispatch and Recovery

- **routes both new types** — GIVEN committed review email/live events WHEN worker dispatches THEN the appropriate sender/publisher is called and each event completes once _(verifies R6, R9)_.
- **retries provider or Redis outage** — GIVEN transient failures WHEN dispatch runs THEN events remain retryable and the committed decision/inbox remain readable _(verifies N1, N4; ARCH 30-second outage case)_.
- **tolerates duplicate live publish** — GIVEN a crash after publish before ack WHEN the event retries THEN duplicate hints are safe and the inbox remains singular _(verifies N4; ARCH worker-crash case)_.
- **fails closed for bad payload** — GIVEN corrupt, unknown, or wrong-account event payload WHEN dispatch runs THEN it is dead-lettered or rejected safely without publishing private data _(verifies N3, N4)_.
- **preserves existing dispatch** — GIVEN auth verification/reset, product state, and media purge events WHEN worker dispatches THEN existing email/product behavior remains _(guards backward-regression risk for `outbox.py`, `models.py`, `test_dispatcher.py`)_.

### Implementation Notes

- **Module(s):** shared event dispatcher, worker.
- **Pattern reference:** `dispatch_due`, `OutboxRepository`, worker's product handler construction.
- **Key decisions:** A4–A6, A10; new handlers must be deployed before review writes are enabled.
- **Libraries:** encrypted outbox, Redis, pytest.
- **High-risk callouts:** Old workers dead-letter unknown types; enforce compatible-worker-first rollout.

### Scope Boundaries

- Do NOT change outbox storage semantics or place private feedback in Redis.
- Only add typed review email and notification changed dispatch.

### Files Expected

**New files:**
- `apps/api/app/shared/events/tests/test_review_dispatch.py`; `tests/integration/test_review_outbox.py` (verification).

**Modified files:**
- `apps/api/app/shared/events/dispatcher.py` (typed email/live handlers and allowlist).
- `apps/worker/worker.py` (construct event publisher and handler wiring).
- `apps/api/app/modules/products/tests/test_events.py` (align product event allowlist expectations).

**Must NOT modify:**
- `apps/api/app/shared/events/outbox.py`; `apps/api/app/shared/events/models.py` (existing encrypted retry/delivery contract).
- `apps/api/app/shared/events/tests/test_dispatcher.py` (run existing cases as regression guard).

---

## Task T9: Send Production Transactional Email Through Resend

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T8, T10
> **Satisfies REQs:** R6, N1, N3
> **Footprint slice:** New Resend transport; modified worker sender selection for every production transactional email.
> **High-risk areas touched:** Transactional email; event dispatch; migration and rollout.

### Description

Add an async Resend API adapter behind the existing email sender contract and select it for all production transactional email. Keep Mailpit SMTP for local/check use and preserve stable outbox message identity through retries.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/email/tests/test_resend.py`
- `apps/worker/tests/test_email_selection.py`

#### Test Scenarios

##### Provider Contract

- **sends with stable key** — GIVEN a valid encrypted email event WHEN the Resend adapter sends THEN it uses the configured sender and stable outbox-derived idempotency key _(verifies R6, N1)_.
- **classifies transient failure** — GIVEN timeout, rate limit, or 5xx WHEN send runs THEN the event remains retryable without logging secret, recipient, or feedback _(verifies N1, N3; ARCH outage case)_.
- **classifies permanent failure** — GIVEN a nonretryable provider response WHEN send runs THEN the existing dead-letter path records a safe failure class _(verifies N1)_.
- **selects by environment** — GIVEN production or local/check settings WHEN worker starts THEN production uses Resend and local/check use SMTP Mailpit _(verifies R6; guards existing local auth email)_.
- **preserves existing templates** — GIVEN verification, recovery, and profile email events WHEN sent through the selected transport THEN their current subject/body intent and delivery recording remain valid _(guards backward-regression risk for shared email/outbox)_.
- **deduplicates an ambiguous retry** — GIVEN a send acknowledged by provider but worker crash before DB completion WHEN retried inside provider key retention THEN one provider message results; later manual replays follow the documented reconciliation path _(verifies N1; ARCH worker-crash case)_.

### Implementation Notes

- **Module(s):** shared email transport, worker sender construction.
- **Pattern reference:** `apps/api/app/shared/email/transport.py`, `apps/worker/worker.py`, and existing `EmailSender` protocol.
- **Key decisions:** A6; use the pinned async HTTP client and stable event-derived key.
- **Libraries:** existing async HTTP client, Resend API, pytest.
- **High-risk callouts:** Resend's finite key-retention window requires bounded automatic retries and explicit operator reconciliation for later ambiguous replays.

### Scope Boundaries

- Do NOT change existing email template product rules or expose Resend credentials to API/scheduler.
- Only replace production transport and add its failure handling.

### Files Expected

**New files:**
- `apps/api/app/shared/email/resend.py` (async API sender, following `transport.py`).
- `apps/api/app/shared/email/tests/test_resend.py`; `apps/worker/tests/test_email_selection.py` (verification).

**Modified files:**
- `apps/worker/worker.py` (production Resend versus local/check SMTP selection).

**Must NOT modify:**
- `apps/api/app/shared/email/transport.py` (local/check SMTP path).
- `apps/api/app/shared/events/outbox.py`; `models.py` (stable message identity and retry state).

---

## Task T10: Configure Review Writes and Production Mail Safely

> **Status:** done
> **Verification:** checklist
> **Effort:** s
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R1, R6, N1, N3
> **Footprint slice:** Modified settings, environment example, and both Compose definitions.
> **High-risk areas touched:** Transactional email; migration and rollout; event dispatch.

### Description

Define a separate review-write flag and worker-only Resend settings. Local/check services keep Mailpit and enable review development; production configuration fails closed if the worker lacks the Resend settings required to send transactional email.

### Verification Checklist

- **Settings validation** — run `pytest apps/api/app/shared/config/tests/test_settings.py`; expected: production worker config rejects absent/invalid Resend key or sender, while local/check SMTP defaults remain accepted _(verifies R6, N1)_.
- **Config examples** — inspect `.env.example` and both Compose files; expected: review flag, provider settings, and Redis connection names are consistent, and secret values are placeholders only _(verifies N3)_.
- **Service routing** — inspect API, worker, and scheduler env declarations; expected: Resend key is required only by worker and is not injected into API/scheduler _(verifies N3)_.
- **Feature rollback** — inspect settings default and disabled behavior; expected: disabling review writes leaves founder drafts and committed outcome/inbox reads available _(verifies R1; ARCH rollback case)_.
- **Compose validity** — run `docker compose -f compose.yaml config` and `docker compose -f compose.checks.yaml config`; expected: both exit successfully without unresolved required keys in local/check mode.

### Implementation Notes

- **Module(s):** shared config and deployment manifests.
- **Pattern reference:** `apps/api/app/shared/config/settings.py`, `.env.example`, existing Compose env blocks.
- **Key decisions:** A6, A10; review flag gates writes only and provider validation is process/environment specific.
- **Libraries:** Pydantic settings, Docker Compose.
- **High-risk callouts:** Do not make production API boot require a worker-only secret; tests and config inspection cover it.

### Scope Boundaries

- Do NOT create real credentials or change unrelated infrastructure.
- Only configure review writes, Resend production mail, and existing Redis/Mailpit integration.

### Files Expected

**New files:**
- None.

**Modified files:**
- `apps/api/app/shared/config/settings.py` (review flag and worker-specific Resend validation).
- `.env.example` (document placeholder configuration).
- `compose.yaml`; `compose.checks.yaml` (local/check review and worker provider wiring).
- `apps/api/app/shared/config/tests/test_settings.py` (configuration assertions).

**Must NOT modify:**
- Existing auth/session models or migrations (configuration does not change identity state).

---

## Task T11: Regenerate Review and Notification Contracts

> **Status:** done
> **Verification:** checklist
> **Effort:** s
> **Priority:** high
> **Depends on:** T4, T5, T6, T7, T10
> **Satisfies REQs:** R1, R2, R6, R9, N3
> **Footprint slice:** Modified contract generation script; regenerated OpenAPI, GraphQL schema/operations, and strict TS types.
> **High-risk areas touched:** Frontend and contracts; private reads and media; migration and rollout.

### Description

Generate client contracts from the completed REST and GraphQL boundaries and add operations for approved staff work and founder notifications. Keep the generated TypeScript source authoritative for frontend tasks.

### Verification Checklist

- **REST contract** — run `sh scripts/quality/contracts.sh`; expected: OpenAPI includes review decision and one-item read commands with typed status and error shapes _(verifies R1, R9)_.
- **GraphQL contract** — inspect generated schema/operations; expected: owner outcome, `approvedReviews`, and `viewerNotificationInbox` appear with owner/staff scopes and no public product root _(verifies R2, R6, N3)_.
- **Generated types** — run `npm run typecheck`; expected: strict generated status unions and operation results compile without hand-edited generated declarations _(verifies R1, R9)_.
- **Drift check** — run `sh scripts/quality/contracts.sh --check`; expected: exit 0 and generated files unchanged _(guards contract pipeline regression)_.
- **Flagged generation** — inspect script/Compose invocation; expected: schema generation includes products and review surfaces even when production review writes default off _(verifies R1; ARCH rollout case)_.

### Implementation Notes

- **Module(s):** contract artifacts and quality script.
- **Pattern reference:** existing `scripts/quality/contracts.sh` and `packages/contracts` operations.
- **Key decisions:** A3, A5, A10; commands remain REST, reads remain GraphQL, and the review write flag does not erase schema.
- **Libraries:** Strawberry GraphQL, OpenAPI, TypeScript codegen.
- **High-risk callouts:** Contract drift can make the UI silently assume obsolete two-state products; generated union check is required.

### Scope Boundaries

- Do NOT hand-maintain generated API types or add public review mutations.
- Only regenerate contracts for architecture-approved fields and routes.

### Files Expected

**New files:**
- None.

**Modified files:**
- `scripts/quality/contracts.sh` (include review surfaces in generation/check).
- `packages/contracts/openapi.json`; `packages/contracts/schema.graphql`; `packages/contracts/operations.graphql` (generated/declared contracts).
- `packages/contracts/src/generated.ts`; `packages/contracts/src/graphql.generated.ts` (generated types).

**Must NOT modify:**
- `apps/api/app/modules/users/routes.py` (profile route is regression guard).
- Generated files by hand; they must come from the script/codegen.

---

## Task T12: Add Typed Product Review Client State

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T11
> **Satisfies REQs:** R1, R2, R3, R4, R5, R8
> **Footprint slice:** Modified product REST/GraphQL client and TanStack Query hooks.
> **High-risk areas touched:** Frontend and contracts; product lifecycle and submission queue.

### Description

Expose typed review command and approved-list reads to product screens, with query invalidation for staff and founder views. Handle expanded statuses and stale-response reconciliation without treating client checks as authorization.

### Test Plan

#### Test File(s)
- `apps/web/src/products/reviewClient.test.ts`
- `apps/web/src/products/useReviewProducts.test.tsx`
- `apps/web/src/products/client.test.ts`
- `apps/web/src/products/useProducts.test.ts`

#### Test Scenarios

##### Typed Commands and State

- **posts full decision identity** — GIVEN a staff action WHEN client sends it THEN product ID, period ID, expected version, outcome, feedback, CSRF, and idempotency key match generated contract _(verifies R1, R5)_.
- **handles all statuses** — GIVEN draft, submitted, changes requested, approved, or rejected response WHEN parsed THEN each maps to a distinct typed state without defaulting to draft _(verifies R2, R3, R4, R8)_.
- **reconciles success** — GIVEN a successful decision WHEN mutation settles THEN queue, approved list, staff detail, and owner detail keys are invalidated/refetched; the live notification client handles inbox invalidation _(verifies R1, R2)_.
- **handles stale conflict** — GIVEN 409 from the command WHEN hook settles THEN optimistic local state rolls back and current server detail is fetched _(verifies R5)_.
- **preserves old founder flows** — GIVEN create/save/withdraw/delete/submit in previous states WHEN hooks run THEN their request shapes and cache keys still work _(guards backward-regression risk for product client/hooks)_.

### Implementation Notes

- **Module(s):** React product data client and hooks.
- **Pattern reference:** `apps/web/src/products/client.ts`, `useProducts.ts`.
- **Key decisions:** A1, A3, A9; use generated contracts and TanStack Query for server state.
- **Libraries:** React, TanStack Query, generated TypeScript types, Vitest.
- **High-risk callouts:** Keep rollback/reconciliation on failed optimistic actions; no new hand-written API types.

### Scope Boundaries

- Do NOT render UI or infer reviewer rights from local status alone.
- Only add typed data access and state transitions needed by review screens.

### Files Expected

**New files:**
- `apps/web/src/products/reviewClient.test.ts`; `useReviewProducts.test.tsx` (verification).

**Modified files:**
- `apps/web/src/products/client.ts` (review command/approved read and status parsing).
- `apps/web/src/products/useProducts.ts` (review hooks and invalidation).
- `apps/web/src/products/client.test.ts`; `useProducts.test.ts` (align existing client and hook expectations).

**Must NOT modify:**
- `apps/web/src/profiles/ProfileScreens.tsx` (profile regression surface).
- `apps/web/src/products/ProductScreens.staff.test.tsx` (run existing staff regression cases as-is).

---

## Task T13: Complete Staff and Founder Product Screens

> **Status:** done
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T12
> **Satisfies REQs:** R1, R2, R3, R4, R5, R6, R8, N2, N3
> **Footprint slice:** Modified product screens for decision controls, founder feedback/correction, locked outcomes, and approved staff list.
> **High-risk areas touched:** Frontend and contracts; private reads and media; product lifecycle and submission queue.

### Description

Present reviewer decisions and founder outcome paths in the existing product workspace. Make corrective feedback clear, keep approved/rejected work read-only for founders, and expose the staff path to return approved work for changes.

### Verification Checklist

- **Staff decisions at 390px and 1280px** — inspect pending detail for approve/reject/change actions; expected: no horizontal overflow, visible outcome choice, keyboard-operable controls _(verifies R1, N2)_.
- **Required explanation and stale state** — submit blank/>2,000-character feedback or a stale version; expected: perceivable inline error and no success state until server confirms _(verifies R3, R4, R5; REQ edge cases)_.
- **Founder correction** — inspect change-requested detail and edit/resubmit path; expected: explanation visible, private partial edits allowed, next submission appears at the back of queue _(verifies R3, R6, R8)_.
- **Locked outcomes** — inspect approved/rejected founder detail; expected: status and applicable reason visible, no edit/delete/resubmit action, no visitor access _(verifies R2, R4, R8, N3)_.
- **Approved staff discovery** — inspect approved list/detail and return action; expected: staff can find a product, provide reason, and move it to correction state _(verifies R2)_.
- **Regression layout** — inspect existing draft and submitted views at both widths; expected: create, save, withdraw, queue navigation, and private media affordances remain usable _(guards existing product-screen behavior)_.
- **Component seams** — run `npm run test --workspace=@launchpad/web`; expected: review screen and existing product component tests pass.

#### Testable Seams

- Component tests cover status branches, decision handler payload, required feedback, stale-error message, keyboard labels, and absent founder actions for locked states.

### Implementation Notes

- **Module(s):** React product screens.
- **Pattern reference:** `StaffReviewQueue`, `StaffReviewDetail`, `ProductHome`, and editor in `ProductScreens.tsx`.
- **Key decisions:** A1, A3, A8, A9; no client-side authority and approved remains private.
- **Libraries:** React, Tailwind, existing design tokens, Testing Library.
- **High-risk callouts:** Screen state must follow server response and announce errors/status accessibly.

### Scope Boundaries

- Do NOT add scheduling, launch publication, public product pages, or new imagery.
- Only implement reviewer/founder review interactions and existing workspace integration.

### Files Expected

**New files:**
- `apps/web/src/products/ProductReviewScreens.test.tsx` (testable seams).

**Modified files:**
- `apps/web/src/products/ProductScreens.tsx` (decision panel, feedback, correction, locked and approved states).
- `apps/web/src/products/ProductScreens.test.tsx` (align existing founder-screen expectations).

**Must NOT modify:**
- `apps/web/src/profiles/ProfileScreens.tsx` (profile route regression guard).
- `apps/web/src/products/ProductScreens.staff.test.tsx` (run existing staff cases as-is).

---

## Task T14: Add Typed Notification Client and Live Reconciliation

> **Status:** in progress
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T7, T11
> **Satisfies REQs:** R9, N3, N4
> **Footprint slice:** New notification client and TanStack Query hooks with WebSocket invalidation.
> **High-risk areas touched:** Notifications and WebSockets; frontend and contracts.

### Description

Provide typed inbox paging, unread count, one-item read command, and session-scoped live invalidation to the bell. On reconnect, refetch persisted state so a missed hint cannot leave the UI stale.

### Test Plan

#### Test File(s)
- `apps/web/src/notifications/client.test.ts`
- `apps/web/src/notifications/useNotifications.test.tsx`

#### Test Scenarios

##### Inbox Reconciliation

- **reads page and count** — GIVEN an authenticated founder WHEN the hook loads THEN generated GraphQL fields populate the bounded page and unread count _(verifies R9)_.
- **marks only selected item** — GIVEN multiple notices WHEN client opens one THEN it calls that ID's REST command and reconciles count/list from server _(verifies R9)_.
- **handles live hint** — GIVEN an account-scoped WebSocket hint WHEN received THEN inbox queries invalidate without using event data as authoritative product content _(verifies R9, N3, N4)_.
- **recovers disconnect** — GIVEN missed event while disconnected WHEN socket reconnects or page remounts THEN the inbox refetches and shows persisted correct count _(verifies N4; REQ edge case)_.
- **cleans up session switch** — GIVEN sign-out or another authenticated account WHEN connection changes THEN old socket/query state is cleared and cannot surface prior account notices _(verifies N3, N4)_.

### Implementation Notes

- **Module(s):** frontend notifications data layer.
- **Pattern reference:** product `client.ts`/`useProducts.ts`, app identity client.
- **Key decisions:** A4, A5, A7; database reads are authoritative and live messages are hints only.
- **Libraries:** TanStack Query, WebSocket, generated TypeScript types, Vitest.
- **High-risk callouts:** Connection ownership follows live session, not a cached account string alone.

### Scope Boundaries

- Do NOT add notification preferences or stream feedback in WebSocket payloads.
- Only support review outcome inbox/read/live behavior.

### Files Expected

**New files:**
- `apps/web/src/notifications/client.ts`, `useNotifications.ts` (typed client and hooks, following products).
- `apps/web/src/notifications/client.test.ts`, `useNotifications.test.tsx` (verification).

**Modified files:**
- None.

**Must NOT modify:**
- `apps/web/src/profiles/ProfileScreens.tsx` (profile UI regression surface).
- Generated contract files by hand (T11 owns them).

---

## Task T15: Mount an Accessible Live Notification Bell

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T14
> **Satisfies REQs:** R6, R9, N2, N3, N4
> **Footprint slice:** New notification bell component; modified authenticated app shell.
> **High-risk areas touched:** Notifications and WebSockets; frontend and contracts; private reads and media.

### Description

Mount the notification bell on authenticated founder pages, showing persistent outcome items and a live unread count. Opening the bell only reveals the list; opening one item marks it read and navigates to its authorized product detail.

### Verification Checklist

- **Visible state at 390px and 1280px** — inspect bell with zero, one, and many unread notices; expected: count and list fit without horizontal overflow and remain perceivable _(verifies R9, N2)_.
- **Keyboard and screen reader** — tab, enter/space, Escape, and focus return work; expected: button name, count, list items, and outcome updates are announced appropriately _(verifies N2)_.
- **Open without reading** — open and close the bell; expected: no mark-read request and unchanged unread count _(verifies R9; REQ edge case)_.
- **Open one outcome** — select one item; expected: only it is marked read, count falls, and owner product detail opens with the full authorized explanation _(verifies R6, R9)_.
- **Live and reconnect** — while connected, create an outcome, then disconnect/reconnect; expected: live count updates without refresh and missed events reconcile from persisted inbox _(verifies R9, N4)_.
- **Session/privacy regression** — sign out or navigate to a public/other-account page; expected: former founder notices disappear and existing profile/product navigation remains usable _(verifies N3; guards `ProfileScreens.tsx` route behavior)_.
- **Component seams** — run `npm run test --workspace=@launchpad/web`; expected: bell and existing profile/product component tests pass.

#### Testable Seams

- Component tests cover bell labels/count, list-open no-write, one-item handler, live-update announcement, session cleanup, and keyboard focus behavior.

### Implementation Notes

- **Module(s):** notification UI and shared React app shell.
- **Pattern reference:** `apps/web/src/App.tsx`, product navigation, existing profile shell and styles.
- **Key decisions:** A5, A7; one-item read only and live hint triggers authoritative refetch.
- **Libraries:** React, TanStack Query, existing styling system, Testing Library.
- **High-risk callouts:** Authenticated shell placement must not expose notices on public/profile pages for another account.

### Scope Boundaries

- Do NOT add bulk read, preferences, broad notification types, or a new visual asset.
- Only mount the review-outcome bell and its live unread behavior.

### Files Expected

**New files:**
- `apps/web/src/notifications/NotificationBell.tsx`, `NotificationBell.test.tsx` (bell and component seams, following product/profile screens).

**Modified files:**
- `apps/web/src/App.tsx` (session-scoped bell/live mount).

**Must NOT modify:**
- `apps/web/src/profiles/ProfileScreens.tsx` (existing route and profile UI are regression guards).

---

## Task T16: Record Review Decisions and Operating Procedure

> **Status:** not started
> **Verification:** checklist
> **Effort:** s
> **Priority:** medium
> **Depends on:** T8, T9, T10, T15
> **Satisfies REQs:** R7, N1, N3, N4
> **Footprint slice:** New review/notification ADR; modified development guide for rollout and operations.
> **High-risk areas touched:** Migration and rollout; transactional email; observability and operations.

### Description

Record the approved state/audit, notification, privacy, Resend, and rollout decisions in an ADR. Document the local setup and production procedure for migration, worker compatibility, feature enablement, delivery failures, and safe rollback.

### Verification Checklist

- **ADR completeness** — inspect ADR against ARCH decisions A1–A10; expected: state/audit, account-scoped hints, Resend production, and write-flag rationale are all recorded _(verifies R7, N3)_.
- **Local setup** — follow development guide with example variables; expected: Mailpit and Redis use is clear and no real credentials appear in tracked files _(verifies N1, N4)_.
- **Production rollout** — inspect documented order; expected: migrate forward, deploy compatible API/worker, drain old worker, enable review writes, and retain read access on rollback _(verifies N1, N3; ARCH old-worker stress case)_.
- **Failure operations** — inspect retry/dead-letter and Resend ambiguous replay guidance; expected: operator can distinguish committed decision from delayed notice and avoid automatic duplicate email after key retention _(verifies N1)_.
- **Telemetry/privacy** — inspect log/metric examples; expected: identifiers and failure classes only, no feedback, address, token, or API key _(verifies N3, N4)_.

### Implementation Notes

- **Module(s):** architecture records and operations documentation.
- **Pattern reference:** `docs/adr/0006-profile-privacy-email.md`, `docs/development.md`.
- **Key decisions:** A1–A10, especially A6/A10; worker-first rollout and production Resend apply to all transactional mail.
- **Libraries:** None.
- **High-risk callouts:** Document finite Resend idempotency retention and manual reconciliation rather than claiming unlimited duplicate prevention.

### Scope Boundaries

- Do NOT publish the application, create secrets, or define future notification preference/retention policies.
- Only document this workflow's decisions and operating procedures.

### Files Expected

**New files:**
- `docs/adr/0007-product-review-notifications.md` (decision record, following existing ADRs).

**Modified files:**
- `docs/development.md` (Resend/local config, rollout, retry/replay, rollback).

**Must NOT modify:**
- `docs/source/launchpad-client-brief.md`; `docs/source/engineering-guide.md` (source of truth remains intact).

---
