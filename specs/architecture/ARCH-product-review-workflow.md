# Architecture: Product Review Decisions and Founder Outcomes

> **Date:** 2026-10-03
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** `specs/requirements/REQ-product-review-workflow.md`
> **Tasks:** TASKS-product-review-workflow.md
> **Type:** feature

## Architecture Summary

Extend the existing products module with explicit review transitions and immutable, product-owned staff decision records. A reviewer writes a decision through one REST command guarded by staff authorization, a product row lock, the current submission ID, the expected product version, and an idempotency key. The same PostgreSQL transaction updates product/submission state, inserts the staff decision and founder notification, and inserts encrypted outbox events for email and live invalidation. A worker sends production mail through Resend and publishes account-scoped Redis hints; the founder's GraphQL inbox and product detail remain the authoritative read surfaces, with a WebSocket-driven notification bell in the React shell. Approval and every other unlaunched state remain private; reviewed products retain their audit history and cannot be deleted through the founder draft flow.

## High-Level Structure

```text
Reviewer UI -> REST review route -> ProductService -> ProductRepository -> PostgreSQL
                                        |                    product, period, decision
                                        +-> NotificationService -> notification, encrypted outbox
                                                                  (same transaction)
Worker -> outbox dispatcher -> Resend API (production) / Mailpit SMTP (local/check)
                         \-> Redis account channel -> authenticated WebSocket -> UI refetch
Founder UI -> GraphQL product + notification reads -> authorized services -> PostgreSQL
Founder UI -> REST mark-one-read command -> NotificationService -> PostgreSQL
```

`products` owns review state, decisions, founder content, and staff queue reads. A small `notifications` module owns the durable inbox, unread count, read state, and account-scoped live delivery. The existing shared outbox remains the delivery mechanism. No approval transition invokes scheduling, search indexing, public publication, or public media access. The products module calls a named notification service interface, and notifications obtain the recipient through a named auth service interface rather than importing another feature's repository.

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|---|---|---|---|
| State and audit | Extend `products` state and add immutable `ProductReviewDecision` rows in PostgreSQL | Reuse account-admin audit; store only latest status | Product decisions need their own submission/version linkage and prior actions must survive a later change request (R1, R2, R7). |
| Review command | REST command with expected version, submission ID, and mandatory idempotency key; GraphQL stays read-only | GraphQL mutation; last-write-wins command | Follows project API split and protects against stale tabs and retries (R1, R5). |
| Founder inbox | PostgreSQL notification rows and GraphQL composition; REST mark-read | Redis-only inbox; email-only outcomes | Durable account-scoped history and unread count survive disconnection (R6, R9, N4). |
| Live updates | Redis pub/sub to FastAPI WebSocket, sending an account-scoped invalidation hint | Poll-only; stream full feedback over pub/sub | Meets live bell requirement while keeping product feedback behind authorized reads (R9, N3, N4). |
| Email | Existing encrypted outbox and delivery state; Resend API in production, Mailpit SMTP in local/check | Production SMTP; synchronous provider call in review request | Production provider is user-selected; outbox keeps the decision independent of provider availability (R6, N1). Resend supports a stable idempotency key within its 24-hour retention window: https://resend.com/changelog/idempotency-keys. |
| API client | Existing pinned async HTTP client for Resend adapter | New HTTP dependency; blocking client | Reuses the project's async dependency and keeps worker I/O nonblocking. |
| Rollout | Separate flag for review writes, forward migration, compatible worker before enabling decisions | Enable at migration time | Prevents older workers from dead-lettering new event types; reads of already committed outcomes remain available during a command rollback. |

## Patterns & Conventions

- **Modular monolith** — `products`, `notifications`, and `auth` cross boundaries through services or narrow protocols; routes/resolvers remain thin and repositories own persistence, per `AGENTS.md` and `CLAUDE.md`.
- **Transactional outbox** — product status, submission closure, decision, notification, and corresponding outbox rows commit together. Provider or Redis failures cannot roll back a completed staff action (N1, N4).
- **Database invariants first** — checks, foreign keys, unique constraints, and row locking enforce the lifecycle. The UI may disable controls but does not determine authority (R1, R5, R8).
- **Explicit named policies** — reviewer eligibility, owner read/edit, and reviewed-product deletion are separately enforced by transport and service boundaries (R1, R8, N3).
- **Generated contracts** — REST and GraphQL schemas generate strict TypeScript types; TanStack Query owns server state, with live hints invalidating its notification queries.
- **Private storage discipline** — current signed media access and unpublished visibility rules continue for all review outcomes (N3).

## Data Models

### Product and ProductSubmission

**Purpose:** The product holds current review status and optimistic version; each submission row is one queue arrival and its result.

**Key fields:**

| Field | Type / Constraint | Notes |
|---|---|---|
| `Product.status` | Check: `draft`, `submitted`, `changes_requested`, `approved`, `rejected` | No new public state; `approved` is private. |
| `Product` required-content check | Require complete fields for `submitted`, `approved`, and `rejected`; permit incomplete `draft` and `changes_requested` | Founder can make partial private corrections before resubmission. |
| `Product.version` | Incremented integer | Expected version in every review transition and existing founder commands. |
| `ProductSubmission.state` | Check: `pending`, `withdrawn`, `changes_requested`, `approved`, `rejected` | Records the current result of that queue arrival. |
| `ProductSubmission.closed_at` | Null iff `pending` | Existing period closure rule extended to review results. |
| `ProductSubmission.submitted_at` | Timestamp, indexed with ID | Existing oldest-first queue position; resubmission inserts a new row. |

**Relationships:** One product has many submission periods; at most one pending period per product remains enforced by the existing partial unique index. A period has one initial review decision and may have one later approved-to-changes-requested action.

**Lifecycle:** `draft -> submitted -> approved | rejected | changes_requested`; `approved -> changes_requested` by staff only; `changes_requested -> submitted` by founder correction, creating a new period; `submitted -> draft` by founder withdrawal. A founder can edit private `draft` or `changes_requested`, but can delete only a never-reviewed `draft`. Rejected is terminal in this workflow. Changes requested counts toward the existing private draft cap; a staff decision still succeeds at the cap, after which additional draft creation is blocked until capacity exists.

### ProductReviewDecision

**Purpose:** Immutable staff audit of each effective review action, including an approved product later returned for changes.

**Key fields:**

| Field | Type / Constraint | Notes |
|---|---|---|
| `id` | UUID primary key | Stable audit/notification reference. |
| `submission_id` | FK to `ProductSubmission`, restrict deletion | Binds action to the content review period. |
| `actor_account_id` | FK to account, restrict deletion | Staff actor; retention must preserve identity or use a future explicit anonymization policy. |
| `from_status` | Check: `submitted` or `approved` | Distinguishes initial decision from an approved return. |
| `outcome` | Check: `approved`, `rejected`, `changes_requested` | Approved return permits only `changes_requested`. |
| `reviewed_product_version` | Integer, required | Exact version accepted by the staff command. |
| `feedback` | Null for approval; otherwise trimmed text with length check 1–2,000 | Founder-visible correction or rejection explanation. |
| `idempotency_key`, `request_fingerprint` | Required, unique with actor ID; bounded key and fingerprint | Same request replay returns the original decision; different payload on the same key conflicts. |
| `created_at` | Timestamp, required | Auditable action time. |

**Relationships:** A decision belongs to one submission and one staff account; one notification belongs to one decision and stores its product ID as the owner-only destination. The notification response exposes only this product ID, never product content, and every inbox/read operation remains recipient-scoped. Unique `(submission_id, from_status)` prevents a second initial decision or second return action. Index `(submission_id, created_at DESC, id DESC)` supports history and latest-outcome reads; migration `0010` adds indexes for approved-review cursor paging and notification product FK checks. Foreign keys prohibit cascade removal of reviewed product history.

**Lifecycle:** Insert only on an effective staff action. Never update or delete in this workflow; later outcomes insert new rows. The current submission state can change from approved to changes requested, while the original approval remains in the decision table.

### Notification

**Purpose:** Durable founder inbox item and authoritative read state for one review decision.

**Key fields:**

| Field | Type / Constraint | Notes |
|---|---|---|
| `id` | UUID primary key | Cursor tie-breaker and read-command target. |
| `recipient_account_id` | FK to account, required | Owner scope for every query and update. |
| `review_decision_id` | FK unique, required | Prevents duplicate in-site outcomes for retries. |
| `kind` | Review outcome enum/check | Allows later notification types without reusing product state. |
| `created_at`, `read_at` | Timestamps; `read_at` nullable | Opening one item sets its `read_at` once. |

**Relationships:** One decision creates one founder notification. A notification links to its product through decision and submission; no untrusted product ID is accepted for reads. Index `(recipient_account_id, created_at DESC, id DESC)` supports cursor paging, and a partial unread-recipient index supports the bell count.

**Lifecycle:** Insert in the review transaction. Mark one item read idempotently and add a `notification.changed.v1` outbox event when its read state changes, so the founder's other connected tabs update. Retain it for the future retention policy. Redis carries no authoritative notification state.

### Outbox events and delivery

**Purpose:** Existing encrypted outbox and email-delivery rows transport side effects after commit.

**Key fields:**

| Field | Type / Constraint | Notes |
|---|---|---|
| `review.outcome_email_requested.v1` | Encrypted event payload with decision/recipient identity and safe template data | Worker resolves the authorized/current verified recipient at delivery; no raw feedback in email or logs. |
| `notification.changed.v1` | Encrypted event payload with recipient and notification identity | Emitted on creation and read-state change; worker publishes only an invalidation hint to the recipient channel. |
| Delivery idempotency key | Stable outbox event ID | Passed to Resend; existing retry/dead-letter state remains authoritative. |

**Relationships:** Both events refer to one committed decision/notification. They may be retried independently.

**Lifecycle:** Insert in the decision transaction, dispatch after commit, retry transient failures, and record terminal failures without changing the review decision.

## API Contracts / Interfaces

### Product review command and product reads

**Boundary:** REST command; existing GraphQL read composition.

**Operations:**

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| `POST` | `/api/v1/staff/products/{product_id}/review-decisions`; body `{submission_id, expected_version, outcome, feedback?}`; `Idempotency-Key` header | Resolve pending submission or return approved product for changes | Decision ID, status, new product version; 401/403 unauthorized, 404 hidden/missing, 409 stale or idempotency mismatch, 422 invalid transition/feedback, 429 rate limit, 503 infrastructure. |
| GraphQL | `reviewQueue`, `reviewProduct` | Existing pending queue/detail with current version and period identity | Staff only; unchanged pending ordering; safe GraphQL errors. |
| GraphQL | `approvedReviews(first, after)` | Discover private approved products eligible for staff correction | Staff only, cursor page ordered by approval time and ID. |
| GraphQL | `viewerProducts`, `viewerProduct` | Show private status, current period, and latest applicable founder-visible explanation | Owner only; never include reviewer-only fields. |
| Internal | `ProductService.decide_review(actor, product_id, submission_id, expected_version, outcome, feedback, idempotency_key)` | Own authorization, lock, transition, audit, and notification call | Typed domain result/error; one transaction. |

**Auth requirements:** Verified, active reviewer/admin for staff calls; existing session cookie and Origin/CSRF checks for REST. Founder reads require the owning active account. The service repeats policy checks after lookup and under the product lock. A decision replay with the same actor/key and identical normalized request returns the original result; a different payload conflicts.

### Notification inbox and live channel

**Boundary:** GraphQL read, REST command, FastAPI WebSocket, internal module service.

**Operations:**

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| GraphQL | `viewerNotificationInbox(first, after)` | Cursor page and unread count from PostgreSQL | Owner session only; bounded page size and safe errors. |
| `PUT` | `/api/v1/me/notifications/{id}/read` | Mark exactly one owned item read | Idempotent item/read result; 401, 404, 429, or 503. |
| WebSocket | `/api/v1/me/notifications/live` | Send private `{type: "notifications_changed"}` hint; client refetches inbox | Reject invalid session/Origin; close on auth loss; reconnect triggers refetch. |
| Internal | `NotificationService.record_review_outcome(session, decision, founder_id)` | Insert notification and outbox rows within caller transaction | Unique decision mapping; no external I/O in transaction. |

**Auth requirements:** Resolve the live cookie session and exact trusted Origin at WebSocket handshake; bind a connection to its account ID, subscribe only to that account channel, and periodically revalidate session/account state. GraphQL and REST enforce the same owner policy. Opening the bell performs no write; opening one item invokes only that item's read command.

### Outbox worker and email transport

**Boundary:** Internal event consumer and provider adapter.

**Operations:**

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| Worker handler | `review.outcome_email_requested.v1` | Resolve current verified recipient, render safe generic status/link, send via selected transport | Existing retry/dead-letter protocol; no review rollback. |
| Worker handler | `notification.changed.v1` | Publish account-scoped invalidation hint to Redis | Retry on Redis outage; duplicate hints harmless. |
| Provider adapter | `send(message, idempotency_key)` | Resend API in production, SMTP in local/check | Async timeout; classify transient/rate-limit vs permanent provider errors safely. |

**Auth requirements:** Worker only has provider credentials; API and scheduler do not need a Resend key. The founder link targets an authenticated owner route and carries no private product content. Existing transactional emails also use Resend in production, as requested.

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|---|---|---|
| `app.modules.products` | Review lifecycle, staff decisions, product ownership and privacy | Own repository/models; named auth access and notification service interfaces; shared outbox. |
| `app.modules.notifications` | Inbox, unread count, read marking, account-scoped live endpoint | Own repository/models; named auth access interface; shared events/Redis. No products repository import. |
| `app.modules.auth` | Live staff eligibility, founder recipient address/session | Its own data; exposes named service methods to other features. |
| `app.shared.events`, `app.shared.email`, worker | Encrypted durable dispatch, retry, provider and Redis delivery | Event contracts and service interfaces; no product business transitions. |
| React product/notification UI | Staff and founder presentation; Query invalidation and generated contract use | REST/GraphQL clients, WebSocket hint. No authorization authority. |

## Change Footprint

_The concrete answer to "where does this land in the codebase?" — produced during the Phase D2 walk._

### New files / modules

| Path | Purpose | Pattern reference |
|---|---|---|
| `apps/api/alembic/versions/0008_product_review_notifications.py` | Forward-only status checks, decision and notification tables, constraints and indexes; revision chained to current `0007` head. | Existing product Alembic revisions. |
| `apps/api/alembic/versions/0010_review_read_indexes.py` | Approved-review cursor and notification product FK indexes. | Existing product Alembic revisions. |
| `apps/api/app/modules/notifications/{models,repository,service,policies,schemas,routes,graphql,live}.py` | Durable inbox and read state with owner-scoped product destination, owner policy, GraphQL composition, mark-read command, authenticated WebSocket. | Corresponding `products` and `auth` module layers. |
| `apps/api/app/modules/notifications/tests/` | Module-level behavior and policy coverage for the new boundary. | `apps/api/app/modules/products/tests/`. |
| `apps/api/app/shared/email/resend.py` | Async Resend sender with idempotency header and error classification. | `apps/api/app/shared/email/transport.py`. |
| `apps/web/src/notifications/{client,useNotifications,NotificationBell}.tsx` | Generated-contract client, Query hooks/WebSocket invalidation, accessible bell/inbox. | `apps/web/src/products/` client and hook pattern. |
| `apps/web/src/notifications/*.test.tsx` | Frontend notification behavior coverage. | Existing product/profile screen tests. |
| `docs/adr/0007-product-review-notifications.md` | Record state/audit, delivery, privacy, and production provider decisions. | Existing ADR format. |

### Modified files / modules

| Path | What changes here |
|---|---|
| `apps/api/app/modules/products/models.py` | Expand product/period status checks, add immutable review-decision model, and index approved-review paging. |
| `apps/api/app/modules/notifications/models.py` | Store the product destination on each notice and index its restrictive product FK. |
| `apps/api/app/modules/products/repository.py` | Add lock/version decision access, review history and approved-list queries; widen editable states; guard reviewed deletion and private draft count. |
| `apps/api/app/modules/products/service.py` | Apply review transitions, call notification service in the transaction, expose owner outcome and approved staff reads, preserve existing draft rules. |
| `apps/api/app/modules/products/policies.py` | Add named review and changes-requested edit policies; keep never-reviewed deletion separate. |
| `apps/api/app/modules/products/schemas.py` | Define review input/output and expanded product status; constrain normalized feedback to 2,000 characters. |
| `apps/api/app/modules/products/routes.py` | Add staff decision REST route with CSRF/Origin, rate limit, key and safe domain-error mapping. |
| `apps/api/app/modules/products/graphql.py` | Expose founder outcome, review version/period identity, and approved staff list/detail under existing read policies. |
| `apps/api/app/modules/auth/staff.py` | Expose named current verified recipient lookup without cross-module repository access. |
| `apps/api/app/graphql.py` | Compose notification query, schema context, and read-field allowlist while preserving reads of committed outcomes. |
| `apps/api/app/main.py` | Register review/notification HTTP and WebSocket surfaces; apply the review flag to decision writes. |
| `apps/api/app/shared/events/dispatcher.py` | Recognize typed review email and live notification events with separate handlers and existing retry/dead-letter behavior. |
| `apps/worker/worker.py` | Construct Resend sender for production, SMTP for local/check, and Redis notification publisher. |
| `apps/api/app/shared/config/settings.py`, `.env.example` | Add review flag and worker-only Resend settings; keep local/check SMTP defaults. |
| `compose.yaml`, `compose.checks.yaml` | Enable review locally/checks and pass worker provider/Redis configuration. |
| `apps/web/src/products/{client.ts,useProducts.ts,ProductScreens.tsx}` | Add review command/status rendering, feedback, correction path, approved staff discovery, and decision UI. |
| `apps/web/src/App.tsx`, `apps/web/src/identity/Screens.tsx` | Mount session-scoped notification bell and live connection on authenticated pages; move focus to the main landmark after inbox navigation. |
| `apps/web/src/notifications/NotificationBell.tsx` | Announce unread-count changes through a polite status region and navigate using the recipient-scoped product destination. |
| `packages/contracts/{openapi.json,schema.graphql,operations.graphql}`, `packages/contracts/src/{generated.ts,graphql.generated.ts}` | Regenerate REST/GraphQL contracts and typed operations. |
| `scripts/quality/contracts.sh` | Generate/check contracts with the review feature enabled. |
| `docs/development.md` | Document production Resend settings, live dependencies, rollout, and outbox recovery. |
| Existing product, event, config, contract, and frontend test files | Align affected behavior and generated contract expectations with the new lifecycle. |

### Deleted / replaced

| Path | Reason |
|---|---|
| None | Existing product, outbox, SMTP, and private-storage code remains; the worker selects a different production email transport. |

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|---|---|
| `apps/api/app/shared/events/outbox.py`, `apps/api/app/shared/events/models.py` | Delivery encryption, retry, and message identity are reused; the new handlers must preserve their contract. |
| `apps/api/app/modules/auth` session and account models | WebSocket session validity and email recipient state must use live auth rules. |
| `apps/api/app/shared/storage/objects.py` | Approved and rejected media must remain private under existing signed URL rules. |
| `apps/api/app/modules/users/routes.py`, `apps/web/src/profiles/ProfileScreens.tsx` | Existing authenticated shell/profile flow shares GraphQL and routing infrastructure. |
| `apps/api/alembic/versions/0005_product_drafts_submission.py`, `0007_product_submission_product_index.py` | Old revisions remain untouched; new migration must advance the actual current head. |
| `tests/integration/test_product_submission.py`, `test_product_deletion.py`, `test_product_schema.py` | Existing period, delete, and schema assumptions must still hold for never-reviewed work. |
| `apps/api/app/modules/products/tests/test_assets.py`, `test_media.py`, `test_queue.py`, `test_graphql.py` | Private media, queue order, and staff/owner reads depend on status handling. |
| `apps/api/app/shared/events/tests/test_dispatcher.py`, `apps/web/src/products/ProductScreens.staff.test.tsx` | Worker routing and staff controls have new branches alongside old behavior. |

## Areas of Impact

_Broader-than-files impact — modules, services, teams, contracts, cross-cutting effects._

| Area | Impact | Risk (L/M/H) | Why |
|---|---|---|---|
| Product lifecycle and submission queue | New states, immutable decisions, fresh resubmission periods, reviewed deletion guard | H | Existing founder operations and staff ordering rely on current two-state assumptions. |
| Private reads and media | More private statuses and founder/staff fields across GraphQL and signed media | H | A status allowlist error could expose unlaunched content. |
| Notifications and WebSockets | Durable account-scoped inbox plus live invalidation | H | Account binding, session revocation, and missed events affect privacy and consistency. |
| Transactional email | All production transactional sends move to Resend | H | Worker configuration or provider errors can delay existing auth and new review mail. |
| Event dispatch | New event types and Redis publisher | M | Older workers dead-letter unknown events; duplicates require idempotent handling. |
| Frontend and contracts | New decision UI, founder feedback, bell and generated types | M | Status unions and query invalidation touch existing screens. |
| Migration and rollout | Forward schema and independent review flag | H | Existing API/worker binaries may be incompatible with new rows/events if rollout order is wrong. |
| Observability and operations | Delivery failure and live disconnect signals | M | Operators need to distinguish committed decisions from delayed side effects. |

**Contract changes:** REST adds a staff decision command and one-item read command; GraphQL adds founder notification inbox, approved staff discovery, and review outcome fields; product status unions expand; WebSocket adds a notification invalidation message. Generated TypeScript types and consumers in product screens and the app shell must update together. Outbox event types are internal but workers must know them before review commands are enabled.

**Cross-cutting ripples:** Named auth access for recipient/session checks, feature-flag configuration, encrypted outbox registration, Redis pub/sub, production-only Resend secret handling, forward Alembic migration, generated schema pipeline, and rollout/dead-letter operations. The existing production mail transport switch applies to all transactional email templates, not only review outcomes.

## Cross-Cutting Concerns

- **Errors:** Services return typed forbidden/not-found/conflict/validation/infrastructure errors; REST and GraphQL map them to safe messages. A stale submission/version or competing decision is a conflict prompting refresh. A repeated identical idempotency key returns the prior result; a key reused with different normalized input conflicts. Email/Redis errors happen after commit and use existing retries/dead-letter handling.
- **Logging & metrics:** Record review transition success/conflict with decision ID, product ID, actor ID, and outcome, never feedback or email address. Count review conflicts, notification insert failures, unread query latency, WebSocket connects/disconnects, outbox retry/dead-letter, and provider response class. Correlate outbox event ID with decision ID using safe identifiers.
- **Auth / authz:** Reuse current live reviewer/admin and owner checks in route/resolver and service. Review command requires an authenticated session, exact trusted Origin/CSRF defense, and rate limiting. Inbox SQL always scopes recipient ID; WebSocket binds a live session to one account and revalidates it. Suspended or revoked sessions cannot continue receiving hints.
- **Performance:** Keep pending queue indexed by queue arrival; migration `0010` adds `(closed_at DESC, product_id DESC) WHERE state = 'approved'` for the approved-list cursor and an index on `notifications.product_id` for FK checks. Use bounded cursor pages for staff approved list and notification history; unread count uses a partial index. Avoid N+1 joins for decision summaries. The worker commits bounded outbox claims before provider I/O and persists each result in its own transaction. Redis pub/sub sends one small account hint and is never used as an inbox store. No global channel or per-request full-table count.
- **Security:** Validate feedback at Pydantic and database boundaries, including whitespace normalization and 2,000-character limit. Email and WebSocket carry generic outcome/hint data; full feedback is retrieved only in authorized owner product detail. All unlaunched states retain private storage URLs and GraphQL/REST visibility rules. Resend API key is worker-only and never logged or returned. A reviewed product cannot be hard-deleted via founder draft flow; decision FKs restrict deletion.
- **Migrations / rollout:** Create a new migration after the actual `0007` head; never edit applied revisions. Expand schema first, deploy API/worker that understand new states and event types, drain old workers, then enable review writes. The command route remains in the schema but returns a safe service-unavailable response while the flag is off; outcome and inbox reads remain available. Production startup validates Resend settings in the worker. If review writes are disabled after a problem, existing decisions and inbox data remain readable and workers can drain pending events; founder drafts remain enabled. Reversal of the schema or immutable audit records is not part of an automatic rollback.

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|---|---|---|---|
| A1 | Explicit product/period states, with private editable `changes_requested` and locked private `approved`/`rejected` | Reuse draft for changes; publish approved | Preserves review meaning and confidentiality. | R1–R4, R8, N3 |
| A2 | Product-owned immutable decisions; current period state may evolve after approval | Reuse auth admin actions; overwrite latest outcome | Retains each staff action and allows approved return without erasing approval. | R2, R7 |
| A3 | One REST decision command with period ID, version, row lock, unique decision constraint, and idempotency key | GraphQL mutation; last-write-wins | First valid action wins and retries cannot create duplicate results. | R1, R5, N1 |
| A4 | PostgreSQL notification and outbox writes in the review transaction | Redis-only notice; synchronous send | Outcome and inbox survive provider failure and disconnection. | R6, R9, N1, N4 |
| A5 | Account-scoped Redis hint and WebSocket, then GraphQL refetch | Polling only; stream feedback in event | Live count with authoritative, private read and safe reconnect. | R9, N3, N4 |
| A6 | Resend for all production transactional mail, existing SMTP locally | Production SMTP | User-selected provider plus shared outbox retry contract. | R6, N1 |
| A7 | Individual notification open marks only that item read | Mark all on bell open | Matches the confirmed unread-count behavior. | R9 |
| A8 | Retain any reviewed product and block founder hard deletion | Delete reviewed work; rely on current status only | Preserves immutable staff history even after later withdrawal. | R7, R8 |
| A9 | Approved-products staff list and detail access | Pending-only queue | Makes the approved-to-changes-requested staff action reachable. | R2 |
| A10 | Separate review feature flag and compatible-worker-first rollout | Enable with migration immediately | Avoids old worker dead-letter and permits operational rollback. | N1, N3, N4 |
| A11 | Persist a product ID on each notification and expose it only through recipient-scoped inbox/read responses for owner navigation | Derive arbitrary product routes in the client or include product content in notices | Gives the bell a stable owner-only destination while keeping private product data behind product authorization. | R6, R9, N3 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|---|---|
| Resend or Redis is down for 30 seconds during a staff action | Transaction commits decision, inbox, and events. Worker retries each side effect independently; founder can read the inbox immediately, and reconnect/refetch repairs a missed live hint. |
| Two reviewers decide the same pending period, or one retries after a timeout | Product row lock serializes decisions; expected version, period state, and unique `(submission_id, from_status)` permit one effective action. Identical keyed retry returns the recorded result; other action conflicts. |
| Founder withdraws or changes content while a reviewer has the detail open | Existing founder command and review command use the product lock/version. The later action sees changed state/version and fails safely; no stale decision, audit entry, or notice is inserted. |
| Worker crashes after provider send or Redis publish but before acknowledging outbox | Retry uses stable Resend idempotency key within provider retention; duplicate Redis hints only trigger refetch. A replay after provider idempotency retention expires needs operator reconciliation against `EmailDelivery` and provider receipt before manual resend. |
| Notifications grow from 10,000 to 10 million rows | Recipient cursor and partial unread indexes keep owner queries bounded; no global broadcast or full history scan. Operational retention is a future policy, not implicit deletion. |
| A reviewed product later becomes draft through withdrawal and founder attempts deletion | Decision-existence guard and restrictive FK prevent hard deletion regardless of current product status. |
| New event arrives while an old worker is running | Rollout gates review commands until compatible workers are deployed and old workers drained; a disabled flag stops new review events without removing committed data. |
| Founder loses a WebSocket connection or account authorization changes | Reconnect invalidates inbox queries and reads PostgreSQL; session revalidation closes unauthorized connections and account channels never carry product feedback. |

### Backward — regression risk per touched area (brownfield only)

| Touched area (from Change Footprint) | What could regress | How we'd know / mitigation |
|---|---|---|
| Product models/repository/service and old migration assumptions | Draft creation, quota, withdrawal, queue position, asset edits, and never-reviewed deletion | Keep old transitions and period ordering; extend checks forward and preserve existing product integration coverage. |
| Product GraphQL, shared root query, and profile routes | Another member or visitor might gain product/feedback access; existing profile queries might disappear | Owner/staff policies precede field composition; schema allowlist and existing access coverage include the new roots. |
| Private storage and media | Approved/rejected media might become reachable through signed URLs or stale visibility cache | Treat every new status as unpublished; existing media authorization remains the sole signer. |
| Auth session/account access | Suspended staff might review or revoked users might receive hints | Resolve live account state at command and WebSocket boundaries; close connections on revalidation failure. |
| Shared dispatcher/outbox/worker | Existing auth email could fail when production transport changes; unknown events could dead-letter | Retain event contracts and delivery semantics; deploy compatible workers first and watch retry/dead-letter/provider metrics. |
| Product screens, app shell, generated contracts | Existing drafts or pending products may render incorrectly; notification live state may drift | Exhaustive status handling with generated unions; reconnect/query invalidation and current UI regression coverage. |
| Config, Compose, and contract generation | Production boot might require SMTP or expose missing Resend secret; generated schema may omit gated fields | Validate provider per process/environment; enable review flag during contract generation; check deployment configuration before activation. |

## Open Questions

- None for this slice. Notification preferences, reviewed-product retention/deletion, rejection appeals, and scheduling are explicitly deferred by the requirements. If a preference system is available before implementation, the notification service applies it before email delivery; the in-site review record remains durable.

## Out of Scope

- Scheduling, launch-date capacity, publication, and public product/media pages (reason: separate launch workflow).
- Notification preference management and broad notification categories (reason: this slice honors available preferences but does not create their UI or policy).
- Appeal/reopen of a rejected product and a reviewed-product retention or deletion policy (reason: these require separate product and audit decisions).
- Public discovery, voting, comments, search, ranking, reports, takedowns, and staff provisioning (reason: separate roadmap areas).
