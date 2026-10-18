# Architecture: Launch Scheduling and Publication

> **Date:** 2026-10-17
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** `specs/requirements/REQ-add-launch-scheduling-publication.md`
> **Tasks:** TASKS-add-launch-scheduling-publication.md
> **Type:** feature

## Architecture Summary

Add a `launches` feature to the existing FastAPI modular monolith. PostgreSQL will own booking history, the two-per-founder/day allocation invariant, launch outcomes, and notification preferences; the `products` feature remains the authority for product content and lifecycle transitions through named service interfaces. REST commands create, replace, or cancel bookings and update notice preferences, while the composed GraphQL API supplies founder launch state and a public projection limited to launched products. The existing encrypted outbox and worker will process reminders and publications idempotently, with bounded concurrency added to meet the 1,000-launch/60-second target; the existing notification inbox, WebSocket invalidation, and Resend transport will deliver notices. A reversible feature flag and forward-only migration gate rollout, and a distinct `/launches/{product_id}` public route avoids collision with the signed-in `/products/{id}` editor.

## High-Level Structure

```text
Founder React UI ── REST booking/preferences ──► launches routes/service
       │                                               │
       └── GraphQL founder launch state ──────────────┤
                                                       ├── PostgreSQL
                                                       │   bookings, preferences,
                                                       │   product state, notices, outbox
                                                       └── products named lifecycle port
                                                                  │
Visitors ── /launches/{id} + public GraphQL/media ──► products public projection
                                                                  ▲
PostgreSQL due outbox ──► worker ──► launch handler ───────────────┘
                                   ├── Resend email
                                   └── durable inbox + notification.changed.v1
                                                └── Redis pub/sub ──► authenticated WebSocket
```

`launches` owns booking records, eligibility windows, per-founder capacity, reminders, and launch-specific dashboard reads. It calls products through named service interfaces to validate approved content, perform the `approved → scheduled → launched` transition, publish a public projection, or return an ineligible product to `approved`. Product review calls a named launches interface in the same transaction when staff return scheduled content for changes. Neither feature imports the other's repository.

Bookings and their timed outbox work are committed together. A due worker rechecks the active booking, exact UTC date, product state, account suspension, and current preferences before acting. The product becomes public only after the product lifecycle transition commits. Public product reads and public media access check persisted `launched` state; the public contract excludes review feedback, booking history, and account details.

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|---|---|---|---|
| Feature boundary | New `launches` module coordinating through product service ports | Put all launch logic in `products`; separate deployable service | The repository guide names launches as a feature boundary; a module retains domain focus without adding a deployment. Products keeps lifecycle/content ownership. |
| Booking authority | PostgreSQL booking history and transactions | Redis counters or a date-only field on `products` | PostgreSQL is authoritative; booking identity supports reschedule history, reminder deduplication, recovery, and audit. Redis remains rebuildable. |
| Per-founder capacity | Lock the founder account before product/booking rows; count active bookings for the UTC date and enforce within the transaction | Global cap, best-effort count, or standalone slot allocator | Serializes a founder's competing bookings without imposing a platform-wide limit; failed rescheduling leaves the old booking active. |
| Timed work | Existing encrypted transactional outbox with `available_at` for reminder/publication events | New scheduler/broker, Redis-only delayed jobs, or request-time publication | Reuses durable claims/retry/idempotency and survives worker restarts. PostgreSQL remains the source of truth. |
| API | REST commands and composed Strawberry GraphQL reads | GraphQL mutations or a second read API | Follows the established engineering guide and current product/notification boundaries. |
| Email and live notice | Existing worker Resend adapter, notification rows, Redis account channel, authenticated WebSocket | Synchronous API email or direct event content over sockets | Keeps actions independent of provider availability; inbox is durable and Redis carries only invalidation hints. |
| Worker throughput | Bounded concurrent handling with independent DB transactions per event and configurable worker replicas | Sequential batch processing or unbounded task fan-out | Current worker handles claimed events sequentially; bounded parallelism is needed for N1 while protecting PostgreSQL and Resend. |
| Public URL | `/launches/{product_id}` | Reuse `/products/{id}` or introduce a slug | Existing `/products/{id}` is the authenticated editor; REQ does not require slug uniqueness or slug migration. |
| Rollout | Additive migration, launch flag off until compatible API and worker are deployed; rollback by disabling commands and rolling forward | Destructive downgrade or enabling with old workers | Existing runtime requires the exact Alembic head, and old workers dead-letter unknown events; forward-only rollout preserves committed bookings. |

## Patterns & Conventions

- **Named module ports** — launches and products exchange domain operations through protocols over the caller's `AsyncSession`; neither feature imports the other's repository.
- **PostgreSQL serialization** — booking commands lock account before product/booking rows, consistently ordered; all count, date replacement, state transition, and outbox insertion happen in one transaction.
- **Booking identity and idempotency** — every successful booking date has a stable booking ID; founder-scoped command keys and canonical fingerprints are retained in booking history for create/reschedule and cancellation replay checks. Timed events and notice uniqueness are keyed to booking ID. Replays resolve to one effective booking and one logical notice.
- **Transactional outbox** — booking, cancellation, publication, and persistent notice outcomes insert corresponding events in their owning state transaction. External email and Redis calls occur in the worker after commit.
- **Private-by-default projections** — product service supplies a public projection only when status is `launched`; private asset access is separately gated before media delivery.
- **Generated contracts** — OpenAPI, GraphQL schema, operations, and TypeScript types are regenerated using `scripts/quality/contracts.sh`; no hand-maintained API types.
- **UI direction** — new booking, preference, dashboard, and public screens use original Brutalism & Neobrutalism styling per `docs/source/inspiration.md`, while preserving semantic controls, keyboard support, and responsive layouts.
- **Project standards** — FastAPI transport layers stay thin; Pydantic validates commands; domain services own decisions; migrations are forward-compatible; tests use PostgreSQL and Redis rather than SQLite substitutes.

## Data Models

### Product lifecycle extension

**Purpose:** Keep publication state explicit on the existing product aggregate.

| Field | Type / Constraint | Notes |
|---|---|---|
| `Product.status` | Check includes `scheduled`, `launched` | `approved` remains private; `scheduled` remains private; only `launched` is public. |
| `Product.version` | Existing nonnegative integer | Increment on schedule, cancel, reschedule, publication, failure return, staff correction, and permitted post-launch edits. |
| `Product.launched_at` | Nullable UTC `timestamptz` | Set once on successful publication; public launch date derives from the booking's UTC date. |
| `Product.launch_failure_reason` | Nullable bounded enum/text, owner-only | Stores missed-day or suspension-blocked explanation; clear on a new booking. |

**Relationships:** Product remains owned by one account and retains existing submissions, decisions, assets, and topic associations. The active booking references the product; public reads join through the product service and never expose private review relations.

**Lifecycle:** `approved → scheduled → launched`; cancellation and missed-day/suspension failure return `scheduled → approved`; staff correction performs `scheduled → changes_requested` and closes the active booking in the same transaction. `launched` permits only the requirement's description/link fields to change.

**Review audit compatibility:** Extend the `ProductReviewDecision` transition constraint to permit `from_status = 'scheduled'` only with `outcome = 'changes_requested'`. Keep the existing submitted and approved transitions and immutable decision records intact.

### LaunchBooking

**Purpose:** Preserve each selected launch date and safely coordinate capacity, delayed work, and notices.

| Field | Type / Constraint | Notes |
|---|---|---|
| `id` | UUIDv7 primary key | Stable identity for delayed work, reschedule replacement, and notice deduplication. |
| `product_id` | Required FK to `products.id` | Product service owns state; launches owns booking rows. |
| `founder_id` | Required FK to `accounts.id` | Capacity and owner queries are founder-scoped. |
| `launch_date` | Required SQL `date` | Interpreted only as a UTC calendar date. |
| `launch_at` | Required UTC `timestamptz` | Exactly 00:00 UTC for `launch_date`; indexed for due work and dashboard queries. |
| `state` | Check: `scheduled`, `replaced`, `cancelled`, `launched`, `missed_day`, `suspension_blocked`, `returned_for_changes` | Historical booking outcome; only `scheduled` consumes a slot. |
| `idempotency_key`, `request_fingerprint` | Required bounded text fields | Persist the founder-scoped command key and canonical request fingerprint on the booking created by a booking/reschedule command; a key replay with a different fingerprint conflicts. |
| `closed_by_idempotency_key`, `close_request_fingerprint` | Nullable bounded text fields | Persist the founder-scoped cancel key and canonical fingerprint when a founder cancels; internal lifecycle closure leaves them null. |
| `failure_reason` | Nullable bounded enum/text | Populated for missed-day or suspension block and exposed only to the founder. |
| `created_at`, `closed_at` | Required/nullable UTC timestamps | Immutable creation time and outcome time. |

**Relationships:** Many historical bookings belong to one product and founder. Partial unique index permits at most one `scheduled` booking per product. Unique indexes scope each non-null idempotency key to its founder. Indexes cover `(founder_id, launch_date)` for active capacity counts and `(state, launch_at)` for due work. Active capacity is enforced by locking the founder account row, then counting active bookings in the same transaction; no platform-wide cap is added.

**Lifecycle:** Create after validating approved ownership and `D+1..D+90`; reschedule closes the old row as `replaced` and creates a new row atomically; cancel closes as `cancelled`; successful publication closes as `launched`; disqualification closes with its failure/review outcome. History is retained and never included in public reads.

### LaunchNotificationPreference

**Purpose:** Store independent founder choices for each required notice type and channel.

| Field | Type / Constraint | Notes |
|---|---|---|
| `account_id` | Account FK, primary key | One preference set per founder. |
| `reminder_email`, `reminder_in_site` | Boolean, default true | Reminder channel controls. |
| `live_email`, `live_in_site` | Boolean, default true | Successful publication channel controls. |
| `failure_email`, `failure_in_site` | Boolean, default true | Missed/suspension failure channel controls. |
| `updated_at` | Required UTC timestamp | Last preference save. |

**Relationships:** One account has one preference set. Missing row means all six defaults are enabled; first save materializes the row. Dashboard failure reason does not depend on preferences.

### Notification extension

**Purpose:** Reuse the existing persistent inbox and live unread behavior for launch notices.

| Field | Type / Constraint | Notes |
|---|---|---|
| `review_decision_id` | Existing unique FK becomes nullable | Retains review notice linkage. |
| `launch_booking_id` | Nullable FK to `launch_bookings`, restricted delete | Links a launch notice to its immutable booking identity. |
| `kind` | Existing review kinds plus `launch_reminder`, `launch_live`, `launch_failed` | Constraints require exactly one valid review/launch source. |
| Source uniqueness | Unique by `(launch_booking_id, kind)`; existing review decision uniqueness retained | Prevents duplicate in-site notices on event retry; a rescheduled booking has a new ID. |

**Relationships:** Each notice is recipient-scoped and references either its review decision or its launch booking, never both. Existing cursor, unread, product destination, and individual read behavior remain.

**Lifecycle:** An enabled in-site notice is inserted when its reminder/publication/failure event is processed; its account-scoped `notification.changed.v1` invalidation is inserted in the same transaction. Historical notices remain readable after reschedule or cancellation.

### Outbox event types

| Event | Producer / due time | Consumer behavior |
|---|---|---|
| `launch.reminder_requested.v1` | Booking transaction; `max(now, launch_at - 24h)` | Recheck booking is still active, current UTC time is before launch, and channel preferences; create in-site notice and email delivery intent only for enabled channels. |
| `launch.publish_requested.v1` | Booking transaction; `launch_at` | Recheck current booking/product/account; publish if still eligible on the booked date, otherwise persist missed-day or suspension outcome. |
| `launch.notice_email_requested.v1` | Reminder/publication outcome transaction | Worker rechecks the current preference and booking/notice relevance immediately before Resend; uses stable outbox ID for provider idempotency. |
| `notification.changed.v1` | In-site notice transaction | Reuse existing account-private Redis invalidation publisher; client refetches PostgreSQL-backed inbox and unread count. |

All events use the existing encrypted outbox envelope, claim lease, retry/dead-letter handling, and event ID. Worker state handlers and external email delivery remain distinct so a provider outage cannot undo publication.

## API Contracts / Interfaces

### Launch booking REST boundary

**Boundary:** Cookie-authenticated REST commands under `/api/v1`.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| `POST` | `/me/products/{product_id}/launch-booking`; `{launch_date, expected_version}`; `Idempotency-Key` | Book an approved owned product | Booking ID, UTC date/time, product status/version; 401/403/404/409/422/429/503. |
| `PUT` | Same path and body | Replace an active booking before original launch time; target capacity is reserved before replacing old row | New booking ID/date; invalid/full target preserves old booking; 409 at/after original launch boundary. |
| `DELETE` | Same path; expected version and idempotency key | Cancel before original 00:00 UTC; return product to approved | Updated status/version; 401/403/404/409/429/503. |
| `PUT` | `/me/launch-notification-preferences`; six booleans | Save independent email/in-site choices | Current six values and `updated_at`; 401/403/422/429/503. |

Commands require the existing session, exact trusted Origin and CSRF checks, rate limit, current active founder state, owner policy, expected product version, and idempotency. UTC date range is evaluated by the service clock, not browser timezone.

### GraphQL read boundary

**Boundary:** Existing POST-only composed Strawberry schema.

| Method/Op | Path / Signature | Purpose | Auth / Visibility |
|---|---|---|---|
| GraphQL | `viewerLaunchBookings(first, after)` | Owner's current bookings, product status, UTC date, and persistent failure explanation | Active signed-in owner only; no schedule history outside owner view. |
| GraphQL | `viewerLaunchNotificationPreferences` | Return saved values or six enabled defaults | Owner session only. |
| GraphQL | `publicProduct(id)` | Public page projection: name, pitch, description, logo, screenshots, website link, topics, launch date | Anonymous; returns no product unless status is `launched`; excludes feedback, account details, and booking history. |

Root fields are added to `apps/api/app/graphql.py` allowlist and the products-enabled schema composition. Public response is `Cache-Control`-safe and only cacheable by a future explicit visibility-aware policy; the initial implementation should avoid introducing a public cache.

### Public product/media boundary

**Boundary:** Anonymous page at `/launches/{product_id}`, composed GraphQL read, and product media HTTP route.

The route bypasses the signed-in founder editor shell but calls only the launched public projection. The asset route rechecks product `launched` state before fetching from private S3-compatible storage and returns only the allowed product asset. It never exposes raw object keys or a long-lived private storage URL. Return 404 for non-launched/missing content to avoid state disclosure.

### Internal interfaces

| Interface | Direction | Responsibility |
|---|---|---|
| `LaunchProductAccess` | launches → products | Owner-safe approved lookup, scheduled transition, publication transition, and launched public projection; operates in caller transaction. |
| `ProductLaunchBookings` | products → launches | Close active booking as `returned_for_changes` when staff return scheduled content; same transaction suppresses reminders by current booking check. |
| `LaunchNotificationAccess` | launches/worker → notifications | Load six preferences, record launch inbox item and notification invalidation through named notification services; no repository import. |
| `LaunchOutboxAccess` | launches/notifications → shared events | Add encrypted events with explicit `available_at` in caller transaction. |

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|---|---|---|
| `app.modules.launches` | Booking rules/history, UTC horizon, founder/date capacity, reminder/publication orchestration, owner dashboard reads | Own models/repository; named auth/product/notification ports; shared outbox. No products or auth repository imports. |
| `app.modules.products` | Product aggregate, lifecycle and content transitions, assets, review workflow, owner-safe public projection | Own repository/models; named launch-booking invalidator; auth access; shared events/storage. |
| `app.modules.notifications` | Launch preferences, generic owner-scoped inbox records, unread/read behavior and live invalidation | Own repository/models; named auth and launch-event source contracts; shared outbox/Redis. No product repository import. |
| `app.modules.auth` | Live account verification, role/suspension checks and account-row lock | Own repository; exposes existing `AuthAccessService.current_account(..., lock=True)` contract. |
| `app.shared.events`, `apps/worker` | Encrypted outbox persistence, event dispatch, retries, Resend and Redis publishers | Typed event contracts and named feature handlers; no product lifecycle rules in dispatcher. |
| `apps/web` | Founder booking/preferences/dashboard and anonymous launch page | Generated contracts, REST/GraphQL clients, TanStack Query; no authorization authority. |

## Change Footprint

_The concrete answer to "where does this land in the codebase?" — produced during the Phase D2 walk._

### New files / modules

| Path | Purpose | Pattern reference |
|---|---|---|
| `apps/api/app/modules/launches/__init__.py` | Public module boundary and router factory | `apps/api/app/modules/notifications/__init__.py` |
| `apps/api/app/modules/launches/{models,repository,service,policies,schemas,routes,graphql}.py` | Booking persistence, rules, REST commands, owner/public reads, typed domain errors | Corresponding layers under `apps/api/app/modules/products/` |
| `apps/api/app/modules/launches/tests/` | Booking, concurrency, publication, privacy, idempotency, preference, and event coverage | `apps/api/app/modules/products/tests/` |
| `apps/api/alembic/versions/0012_launch_scheduling_publication.py` | Forward-only booking/preferences tables, indexes, product and notification constraints; chains from `0011_profile_upload_declarations` | `apps/api/alembic/versions/0008_product_review_notifications.py` |
| `apps/web/src/launches/client.ts` | REST/GraphQL launch client over generated types | `apps/web/src/products/client.ts` |
| `apps/web/src/launches/useLaunches.ts` | TanStack Query reads, commands, invalidation, and live notification refresh integration | `apps/web/src/products/useProducts.ts`, `apps/web/src/notifications/useNotifications.ts` |
| `apps/web/src/launches/LaunchScreens.tsx` | Founder booking/dashboard/preferences and public launch route screens | `apps/web/src/products/ProductScreens.tsx` |
| `apps/web/src/launches/launches.css` | Scoped Brutalism & Neobrutalism views | `apps/web/src/styles.css` |
| `apps/web/src/launches/LaunchScreens.test.tsx` | Responsive route, state, accessibility, and public projection UI coverage | Existing product/profile screen tests |

### Modified files / modules

| Path | What changes here |
|---|---|
| `apps/api/app/modules/products/models.py` | Extend product status check and add launch timestamp/failure fields; extend the review decision transition check for scheduled return-to-changes while retaining existing audit data. |
| `apps/api/app/modules/products/repository.py` | Add named launch lifecycle/public projection access while keeping queries in products. |
| `apps/api/app/modules/products/service.py` | Add versioned schedule/publication/failure and post-launch edit transitions; invoke booking invalidation atomically for staff return-to-changes. |
| `apps/api/app/modules/products/policies.py`, `schemas.py`, `routes.py` | Add lifecycle/edit policies, expanded status/input schemas, and a launched-only public media gate. |
| `apps/api/app/modules/products/graphql.py` | Compose an anonymous launched-only public projection and owner launch state without exposing review fields. |
| `apps/api/app/modules/notifications/models.py` | Add launch notice kinds/source linkage and six preference fields/table while preserving review notice constraints. |
| `apps/api/app/modules/notifications/repository.py`, `service.py` | Read/update preferences, create idempotent launch inbox notices, preserve recipient-scoped unread/read behavior. |
| `apps/api/app/modules/notifications/graphql.py`, `routes.py` | Expose owner preference read and preference update command through existing composition/security patterns. |
| `apps/api/app/shared/events/dispatcher.py` | Register launch event categories and route to typed launch handlers separately from email delivery. |
| `apps/worker/worker.py` | Construct launch/publication and launch email handlers; process bounded parallel event batches in isolated sessions; recheck live preference/relevance immediately before Resend. |
| `apps/api/app/main.py` | Mount launch routes and include launch read fields under the launch feature flag. |
| `apps/api/app/graphql.py` | Add launches to schema composition/context and root read allowlist. |
| `apps/api/app/modules/users/routes.py` | Pass independent product and launch flags to the composed GraphQL router. |
| `apps/api/app/shared/config/settings.py`, `.env.example` | Add `launches_enabled` reversible flag (off by default outside explicit local/check setup) and bounded worker concurrency configuration. |
| `compose.yaml`, `compose.checks.yaml`, `compose.production.yaml` | Set launch feature flag per environment and configure worker concurrency without adding a service. |
| `apps/web/src/App.tsx` | Route `/launches/{product_id}` before authenticated product editor routing; preserve `/products/{id}` behavior. |
| `apps/web/src/styles.css` | Import scoped launch styles and ensure existing global tokens do not override the feature styling. |
| `docs/development.md` | Document UTC booking/cancel boundaries, reminder/publication timing, missed-day and suspension recovery, launch feature-flag rollout, due outbox/worker monitoring, and operator recovery steps. |
| `packages/contracts/openapi.json`, `schema.graphql`, `operations.graphql`, `src/generated.ts`, `src/graphql.generated.ts` | Regenerate command, query, and frontend types from the authoritative schemas/operations. |
| `scripts/quality/contracts.sh` and API/web tests | Verify generated contracts, feature-flag schema, visibility, state transitions, notification compatibility, and screens. |
| `apps/api/app/modules/products/tests/test_graphql.py` | Update exact composed-root expectations for the launch-enabled schema while retaining the products-only and feature-disabled assertions. |

### Deleted / replaced

| Path | Reason |
|---|---|
| None | Existing product, review, outbox, scheduler, worker, notification, and email infrastructure remains; it gains the launch domain and event types. |

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|---|---|
| `apps/api/app/modules/auth/staff.py`, `apps/api/app/modules/auth/repository.py` | `current_account(..., lock=True)` is the existing serialization boundary; keep founder eligibility current and lock order consistent. |
| `apps/api/app/shared/events/outbox.py`, `apps/api/app/shared/events/models.py` | Existing due time, claim, retry, and completion contracts are reused; preserve event ID and lease semantics. |
| `apps/worker/scheduler.py` | It enqueues due IDs at a bounded rate; verify its role against the worker's direct database claim loop and do not make publication depend on Redis-only timing. |
| `apps/api/app/modules/notifications/live.py`, `apps/web/src/notifications/NotificationBell.tsx`, `useNotifications.ts` | Account-bound socket and individual read state are reused; no private launch payload may be published to Redis. |
| `apps/api/app/shared/storage/objects.py` | Private object store stays private; public asset access must recheck launched state before storage retrieval. |
| `apps/api/app/modules/products/tests/test_review_service.py`, `test_review_routes.py`, `test_review_graphql.py`, `apps/api/app/modules/notifications/tests/` | Review audit, preexisting notification kind/source constraints, and account scoping must continue to pass after additive launch notice support. |
| `apps/api/app/modules/products/tests/test_assets.py`, `test_media.py`, `test_reads.py` | Existing private media and private product read behavior are sensitive to newly public fields and statuses. |
| `apps/api/app/graphql.py` root-field allowlist behavior | The root field allowlist and disabled schema are exact; public reads must remain available only under the correct launch flag and status check. |
| `apps/api/app/shared/db/database.py`, `apps/api/alembic/versions/0011_profile_upload_declarations.py` | The runtime requires the declared migration head; preserve the current revision and add a forward-only successor. |
| `apps/worker/worker.py` existing review/auth email handlers | Launch-specific dispatch must not alter Resend idempotency, current verified-recipient checks, or existing transactional email delivery. |
| `apps/web/src/products/ProductScreens.tsx`, `apps/web/src/App.test.tsx` | Existing `/products/{id}` is a private editor route; the new public route must not bypass its session or edit protections. |

## Areas of Impact

_Broader-than-files impact — modules, services, teams, contracts, cross-cutting effects._

| Area | Impact | Risk (L/M/H) | Why |
|---|---|---|---|
| Product lifecycle/review | Add scheduled/launched and return/cancel integration | H | Existing review service and product status assumptions must preserve audit and stop publication on correction. |
| Booking and capacity | New owner commands, UTC window, concurrency invariant, history | H | Concurrent commands and original midnight rules are correctness-critical. |
| Public reads/media | New anonymous GraphQL/page/media paths | H | A faulty allowlist or asset gate can expose unpublished content. |
| Worker/outbox | Timed events, preference/relevance checks, bounded concurrency | H | Backlog, duplicate delivery, or unrecognized events can miss the cutoff or duplicate notices. |
| Notifications/WebSocket | Add six preferences and three launch notice kinds to existing inbox | H | Existing review notification source constraints and account privacy must remain intact. |
| Email provider | Reuse Resend for production launch messages | M | Outage must delay still-relevant notices without rolling back booking/publication. |
| API/GraphQL contracts | New REST commands, owner reads, public projection, preference shape | M | The composed root-field allowlist and generated clients must change together. |
| Frontend | Founder management and anonymous public route; new visual direction | M | Existing authenticated route overlap and mobile/accessibility behavior are key regressions. |
| Database/migration/deploy | Additive revision 0012 and reversible feature flag | H | Production runtime requires exact schema head; old workers cannot safely consume new event types. |
| Operations/load | One-minute publication SLO, queue/worker diagnostics and recovery | H | Existing worker processes events sequentially; throughput must be measured and configured. |

**Contract changes:** REST adds booking and preference commands; GraphQL adds founder booking/preferences and anonymous `publicProduct`; existing product status gains `scheduled` and `launched`; notification kinds and source linkage gain launch variants. React generated contracts and tests consume the updated OpenAPI and GraphQL schema. Outbox adds versioned launch event types consumed only by compatible workers.

**Cross-cutting ripples:** Add `LAUNCHPAD_LAUNCHES_ENABLED` to API/runtime configuration and Compose environments; add bounded event concurrency to the worker; migrate from `0011` to the new head; deploy compatible workers before enabling commands; preserve the existing Cloudflare R2/private storage and production Resend credentials; expose safe metrics for due backlog, processing latency, outcomes, and dead letters.

## Cross-Cutting Concerns

- **Errors:** Map typed launch domain errors to safe REST responses: invalid window/state `422`, full founder/date or stale version/too-late action `409`, hidden product `404`, missing/forbidden session `401/403`, rate limit `429`, dependency failure `503`. Failed reschedules roll back with the existing booking retained. Public reads use `404` for missing and unlaunched products.
- **Logging & metrics:** Emit structured event ID, booking ID, product ID, launch date, attempt, outcome, elapsed time, and failure class. Do not log product content, review feedback, object keys, emails, or secrets. Track due backlog age/count, launches completed within 60 seconds, missed-day/suspension outcomes, retry/dead-letter counts, and notification delivery status.
- **Auth / authz:** Founder commands require current active founder eligibility and owner policy in route and service. Lock founder account before product/booking rows. Staff return uses existing staff policy plus booking invalidation in the same transaction. Public projection/media require persisted `launched` state and include no account/review fields.
- **Performance:** Index active founder/date capacity, current active booking by product, and due state/time. Do not run per-product N+1 auth or asset queries for cutoff work; use bounded payloads and product service projections. Current worker is sequential, so add bounded event concurrency with one transaction/session per event and cap external Resend concurrency. Measure 1,000 due products end-to-end; no global booking cap or unbounded fan-out.
- **Security:** Validate dates as calendar dates, derive UTC midnight server-side, reject invalid and local-time ambiguity. Keep R2 objects private; public asset handler checks `launched` before delivery. Encrypt outbox payloads with existing codec, keep PII out of Redis/WebSocket events, and check preferences at actual channel delivery. Never expose booking history or failure details to other accounts.
- **Migrations / rollout:** Add revision `0012` after `0011`, using additive nullable/defaulted fields, new tables, and replacement checks. Deploy matching API and worker binaries while the feature flag is off, verify migration head and handlers, then enable launches. Rollback disables booking/public routes but preserves compatible workers and committed events; use forward fixes, not migration downgrade or data deletion. Any old worker still running during rollout may dead-letter unknown events, so drain it before enabling launch writes.

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|---|---|---|---|
| A1 | Add a launches module; keep product state/content in products behind named service ports. | Put everything in products; deploy a separate service. | Keeps feature ownership clear without introducing a new deployment or cross-repository imports. | R2–R11, N2–N3, N6 |
| A2 | Persist historical booking rows and product publication/failure state in PostgreSQL. | Redis counters; one mutable date column only. | Durable outcomes, safe recovery, and per-booking reminder identity require relational authority. | R4–R9, R12–R15, N2, N4 |
| A3 | Serialize per-founder/date capacity by locking the founder account, then count active rows in the booking transaction. | Platform-wide cap or non-transactional count. | Guarantees two per founder per UTC day under concurrency without a global cap; supports replacement atomically. | R2–R5, N2 |
| A4 | Use booking-identified encrypted outbox events for reminder and publication, with current-state checks in worker. | In-request scheduling, Redis-only delayed queue, or cron per booking. | Reuses durable delivery/retry infrastructure and enforces same-day/missed-day recovery after outages. | R6–R9, R12–R14, N1–N4 |
| A5 | Extend existing notifications with launch preference and source/kind support; use existing Resend and live inbox path. | Separate notification service or untracked emails. | Keeps the persistent bell/unread state and email operation consistent with current architecture. | R12–R17, N4, N6 |
| A6 | Publish anonymous content at `/launches/{product_id}` using a launched-only projection and gated media route. | Reuse authenticated editor path or require a new slug. | Avoids route collision and new slug uniqueness/migration while exposing only the approved public fields. | R6, R10–R11, N3 |
| A7 | Add bounded parallel worker processing and verify 1,000 launches within 60 seconds. | Keep sequential batches or unbounded concurrency. | Sequential handling cannot reliably meet N1; bounded concurrency protects dependencies while increasing throughput. | N1–N2, N4 |
| A8 | Gate launch endpoints with a reversible flag and roll forward across additive migration. | Enable immediately or downgrade schema to rollback. | Matches strict migration-head readiness and prevents old workers from consuming unknown events. | R6–R9, N2–N4 |
| A9 | Apply Brutalism & Neobrutalism to every new or changed feature view. | Reuse prior neutral visual style. | The REQ records the explicit visual decision and accessibility/mobile constraints. | N5 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|---|---|
| PostgreSQL or worker unavailable across midnight | Booking and due event remain durable. On recovery during the booked UTC date, publication proceeds if still eligible; at/after next midnight, booking is closed as missed and product returns to approved with persistent reason. |
| Two concurrent bookings compete for a founder's second date slot | Account-row lock serializes commands; each transaction recounts active bookings. Only one takes the final slot. Other founders are unaffected. |
| Reschedule target is full or database/outbox insert fails | Target is validated before old booking is closed; the whole transaction rolls back, preserving the old booking, slot, status, and reminder. |
| Worker crashes after claiming or while handling publication | Claim lease recovery requeues work. Product/booking state transition is idempotently checked under lock; one active booking and unique notice constraints prevent duplicate publication/notices. |
| Resend or Redis is unavailable | PostgreSQL booking/publication and in-site notice state remain committed. Email retries check current preference and booking relevance before send; Redis carries only a retryable invalidation hint, and clients can refetch inbox history. |
| 1,000 products share the midnight cutoff | Scheduler/outbox and bounded concurrent workers process due events in parallel with isolated sessions. Load verification measures public readiness within 60 seconds; tune concurrency/replicas without adding a global cap. |
| Table growth from 10K to 10M booking rows | Partial active and due indexes bound hot queries; owner dashboard is cursor-paginated. Retain lifecycle history per audit/product behavior and monitor index growth; no unscoped history scan is allowed. |
| New build fails after migration | Turn off launch commands/public reads using the feature flag; keep compatible worker handlers for committed events and roll forward a fix. Do not downgrade or delete booking history. |

### Backward — regression risk per touched area (brownfield only)

| Touched area (from Change Footprint) | What could regress | How we'd know / mitigation |
|---|---|---|
| Product status constraint and `ProductService` | Review decisions, submission edits, and owner draft behavior may reject new statuses or allow prelaunch edits. | Preserve explicit review transition policies; status-matrix tests cover draft/submitted/changes-requested/approved/scheduled/launched/rejected paths and expected versions. |
| Review service and launch invalidator | Staff return-to-changes could leave a due booking active, or lock ordering could deadlock. | Single transaction closes booking with review transition; consistent account-before-product lock order; test concurrent review/publication and reminder suppression. |
| Notification source/kind constraints | Existing review notifications may fail inserts or owner read queries after nullable source changes. | Add exactly-one-source constraint, retain unique review decision, and run old review notification read/write tests against the new migration. |
| Product media and GraphQL read paths | Adding a public field could leak approved/scheduled assets through existing resolver or signed download URL. | Default-private allowlist; public handler independently queries launched status; existing private media and root-field allowlist tests remain. |
| Outbox dispatcher and worker | Existing auth/review emails could be delayed, misclassified, or sent with changed idempotency. | Keep event categories and handlers distinct; test old handlers, Resend idempotency, and dead-letter unknown types; bound launch concurrency. |
| API schema/feature flags | Launch fields could appear while disabled or product/profile fields could disappear. | Assert enabled/disabled composed schemas and generated contract freshness in quality workflow. |
| Existing `/products/{id}` frontend route | Anonymous routing could mount private editor behavior or session check on public page. | Route `/launches/{id}` separately before private ProductRoutes; test anonymous launched, unlaunched, and editor paths. |
| Scheduler and worker coordination | Redis outage or duplicate due hints could delay work or create duplicate jobs. | PostgreSQL outbox remains source of truth; worker claims with `SKIP LOCKED`; monitor due backlog and verify scheduler/worker relationship during load and outage tests. |
| `docs/development.md` operating guidance | Operators could misinterpret pending, delayed, missed-day, or dead-letter launch outcomes during an incident. | Document UTC boundary, safe recovery steps, feature-flag behavior, and which metrics/log fields distinguish processing failure from a committed product outcome. |

## Open Questions

- None blocking. The developer confirmed the module boundary, PostgreSQL booking model, REST/GraphQL split, notification integration, `/launches/{product_id}` URL, worker-throughput mitigation, and forward-only rollout.

## Out of Scope

- Daily listings, past-day archives, rankings, topic browsing, and search (reason: later discovery slice).
- Voting, comments, follows, feeds, and community interactions (reason: later community slice).
- General notification preference management, digests, and unrelated notice types (reason: only launch reminder/live/failure preferences are required).
- New suspension administration, takedown tools, or general moderation features (reason: use existing eligibility and review paths).
- Slug generation/uniqueness or custom domains (reason: REQ requires a public page but no slug behavior; product ID route avoids a schema decision).
- Broad site redesign outside the views delivered or changed for this feature (reason: visual direction is scoped to launch-related views).
- Analytics, exports, payments, featured slots, and unrelated jobs (reason: deferred product capabilities).
- Changes to reviewed-product retention, deletion policy, or rejection appeals (reason: preserve existing review decisions).
