# Tasks

## Task T1: Add the Constrained Comment Persistence Schema

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R4, R5, R6, R7, R11, N1, N3, N5
> **Footprint slice:** New: migration `0017_comments_replies.py`, comments package initializer, comment models, model tests; Modified: production migration and migration-head integration coverage
> **High-risk areas touched:** PostgreSQL schema (H); Product confidentiality (H)

### Description

Create the additive PostgreSQL schema and SQLAlchemy mappings for immutable comments, one-level replies, and durable idempotency receipts. Database constraints must independently enforce thread topology, content bounds, receipt uniqueness, and the indexed access paths required by bounded pagination and posting safeguards.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/comments/tests/test_models.py`
- `tests/integration/test_production_migrations.py`

#### Test Scenarios

##### Mapping and Constraint Shape

- **maps the approved comment and receipt schema** — GIVEN the SQLAlchemy metadata and migrated database WHEN fields, types, defaults, foreign keys, checks, and indexes are inspected THEN the model and migration definitions agree and all foreign keys use the approved restrictive behavior _(verifies R5, R6, R7, R11)_
- **accepts valid root and reply topology** — GIVEN a product, account, and depth-zero root WHEN a same-product depth-one reply references that root THEN PostgreSQL accepts the row _(verifies R5)_
- **rejects invalid thread topology** — GIVEN existing entries WHEN an insert attempts reply-to-reply nesting, cross-product parenting, parent fields on a root, or incomplete parent fields on a reply THEN a database constraint rejects it _(verifies R5 and N1)_
- **enforces content and status bounds** — GIVEN direct inserts WHEN the body is blank, exceeds 2,000 code points, has an invalid fingerprint, or uses an unsupported status THEN persistence rejects it while valid Unicode plain text succeeds _(verifies R4 and N5)_
- **enforces author-scoped idempotency receipts** — GIVEN an existing author/key receipt WHEN another receipt reuses that pair THEN it is rejected, while another author may use the opaque key and every receipt must reference a comment _(verifies R11)_

##### Scale and Regression Guards

- **creates the required bounded-query indexes** — GIVEN migration `0017` WHEN PostgreSQL index metadata is inspected THEN root, reply, author-activity, duplicate-fingerprint, composite-parent, and receipt lookup indexes have the approved ordering and predicates _(verifies R6, R7, R11 and N3; verifies ARCH scale stress-test)_
- **upgrades additively from migration 0016** — GIVEN existing account, product, and vote rows at revision `0016` WHEN the database upgrades to `0017` THEN existing rows and vote constraints remain unchanged, both comment tables are added, and head advances successfully _(guards ARCH backward-regression risk for `apps/api/app/modules/votes/` and the production migration chain)_

### Implementation Notes

- **Module(s):** `app.modules.comments` persistence ownership
- **Pattern reference:** `apps/api/alembic/versions/0016_votes_and_daily_rankings.py`; `apps/api/app/modules/votes/models.py`
- **Key decisions:** A2 constrained self-reference; A14 additive migration and flag-based rollback
- **Libraries:** SQLAlchemy 2, Alembic, PostgreSQL, `uuid6`
- **High-risk callouts:** Composite self-reference and partial index definitions must be tested against PostgreSQL, not only metadata; the migration must not alter existing rows.

### Scope Boundaries

- Do NOT add editing, deletion, moderation actions, or destructive cascades.
- Do NOT rewrite migration `0016` or any earlier shared migration.
- Only implement tables, constraints, indexes, and mappings required by the approved architecture.

### Files Expected

**New files:**
- `apps/api/alembic/versions/0017_comments_replies.py` (add comments and receipts, following migration `0016`)
- `apps/api/app/modules/comments/__init__.py` (declare the feature package)
- `apps/api/app/modules/comments/models.py` (own comment and receipt mappings, following vote models)
- `apps/api/app/modules/comments/tests/test_models.py` (mapping and constraint-shape tests)
- `apps/api/app/modules/comments/tests/` (shared feature test package; concrete test files are owned across T1–T7)

**Modified files:**
- `tests/integration/test_production_migrations.py` (verify additive upgrade from the existing head)
- `tests/integration/test_vote_schema.py` (advance the expected repository head while preserving vote tables)

**Must NOT modify:**
- `apps/api/alembic/versions/0016_votes_and_daily_rankings.py` (shared migration)
- `apps/api/app/modules/votes/` (silent-regression hotspot covered by upgrade checks)
- Existing account or product model definitions (referenced tables remain authoritative)

---

## Task T2: Implement Transactional Discussion Rules and Persistence

> **Status:** done
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R1, R3, R4, R5, R6, R7, R10, R11, R12, R13, N1, N3, N5, N6
> **Footprint slice:** New: comments repository, policies, service, repository/service tests; Modified: products service and comment concurrency integration coverage
> **High-risk areas touched:** PostgreSQL schema (H); Product confidentiality (H); Profile lifecycle (H)

### Description

Implement the comments-owned repository, named policies, and transactional service for reads and posting. The service coordinates product visibility, account eligibility, exact rolling safeguards, idempotency, immutable creation, and same-transaction outbox insertion without importing another feature's repository.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/comments/tests/test_repository.py`
- `apps/api/app/modules/comments/tests/test_service.py`
- `apps/api/app/modules/products/tests/test_service.py`
- `tests/integration/test_comment_concurrency.py`

#### Test Scenarios

##### Eligibility and Visibility

- **permits only eligible community authors** — GIVEN each supported session/account state WHEN posting is evaluated THEN only verified, unsuspended members and founders with complete attribution pass; visitors, unverified, suspended, staff, and incomplete profiles receive typed denials _(verifies R3)_
- **inherits current product visibility** — GIVEN current, archived, scheduled, rejected, removed, and unknown products WHEN discussion is read or posted THEN only current/archived public launches succeed and unavailable states are indistinguishable _(verifies R1, R12 and N1)_
- **rejects invalid reply parents** — GIVEN roots and replies across products WHEN a reply command targets them THEN only a visible same-product root succeeds and invalid targets are never silently reparented _(verifies R5)_

##### Pagination and Safeguards

- **pages roots and replies deterministically** — GIVEN concurrent inserts and large histories WHEN root and earlier-reply cursors advance THEN roots remain newest-first, replies remain chronological, pages remain bounded, and no entry is missed or duplicated _(verifies R6, R7 and N3)_
- **enforces exact rolling account limits** — GIVEN comments and replies across products WHEN the account crosses five entries in 60 seconds or 100 in 24 hours, including concurrent attempts, THEN excess commands fail with a typed retry time and committed counts remain exact _(verifies R11)_
- **rejects recent repeated content at the approved scope** — GIVEN normalized body fingerprints WHEN the same author repeats text on the same product within five minutes THEN it fails, while another author/product or an expired window succeeds _(verifies R11)_
- **replays one request exactly once** — GIVEN retries and key reuse WHEN the fingerprint matches THEN the original entry returns, and when it differs THEN a typed conflict occurs without another entry _(verifies R11 and R13)_

##### Transaction and Race Safety

- **commits or rolls back the complete posting effect** — GIVEN product/account state changes or an injected persistence failure WHEN posting runs under authoritative locks THEN success commits entry, receipt, and encrypted outbox record together; failure commits none and never claims publication _(verifies R10, R12, R13 and N6; verifies ARCH concurrency stress-tests)_

### Implementation Notes

- **Module(s):** comments owns persistence/business rules; products supplies `ProductDiscussionAccess`
- **Pattern reference:** `apps/api/app/modules/votes/repository.py`; `apps/api/app/modules/votes/service.py`; existing public visibility methods in `apps/api/app/modules/products/service.py`
- **Key decisions:** A1, A2, A4, A5, A6, A7, A15
- **Libraries:** SQLAlchemy async sessions, Pydantic-domain dataclasses, existing encrypted outbox codec/repository
- **High-risk callouts:** Acquire account and product locks in a consistent order; never disclose a non-public product through errors, counts, logs, or timing-specific branches.

### Scope Boundaries

- Do NOT add editing, deletion, reporting, moderation, reactions, or nested replies.
- Do NOT use Redis counters or locks as the final authority.
- Only create visible immutable entries after every eligibility and safeguard check succeeds.

### Files Expected

**New files:**
- `apps/api/app/modules/comments/repository.py` (comment persistence and cursor reads, following vote repository patterns)
- `apps/api/app/modules/comments/policies.py` (named policies and typed errors, following vote policies)
- `apps/api/app/modules/comments/service.py` (transactional commands, reads, and service protocols)
- `apps/api/app/modules/comments/tests/test_repository.py` (bounded query and safeguard tests)
- `apps/api/app/modules/comments/tests/test_service.py` (domain policy and transaction tests)
- `tests/integration/test_comment_concurrency.py` (real PostgreSQL race coverage)

**Modified files:**
- `apps/api/app/modules/products/service.py` (add public discussion context and optional row lock)
- `apps/api/app/modules/products/tests/test_service.py` (cover the additive product boundary without changing existing behavior)

**Must NOT modify:**
- `apps/api/app/modules/products/repository.py` (comments crosses through the named service)
- `apps/api/app/modules/auth/` (silent-regression hotspot; existing session/account semantics remain authoritative)
- `apps/api/app/modules/products/graphql.py` (public product contract remains separate)
- `apps/api/app/shared/events/outbox.py` (existing outbox semantics remain authoritative)

### TDD Sequence (optional)

1. Establish policy/body/cursor tests, then repository reads and safeguards.
2. Add command transaction and idempotency tests.
3. Finish with real PostgreSQL concurrency and visibility-transition races.

---

## Task T3: Preserve Current Author Attribution Across Profile Changes

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1, T2
> **Satisfies REQs:** R3, R8, R12, R14, N1, N5
> **Footprint slice:** New: users comment-attribution adapter; Modified: users repository, service, routes, profile tests, route tests, and profile privacy integration coverage
> **High-risk areas touched:** Product confidentiality (H); Profile lifecycle (H)

### Description

Provide the users-owned boundary for batched current attribution and validated photo access, then protect display name and photo from being cleared while visible discussion entries exist. Preserve private-profile choice and all existing profile/photo behavior outside the new invariant.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/users/tests/test_profile.py`
- `apps/api/app/modules/users/tests/test_routes.py`
- `tests/integration/test_profile_privacy.py`
- `tests/integration/test_comment_concurrency.py`

#### Test Scenarios

##### Current Public Attribution

- **batch-resolves only approved attribution** — GIVEN public and private profiles WHEN a bounded account batch is resolved THEN it returns current display name, validated-photo availability, and nullable public-profile link without email or private fields _(verifies R8 and N1)_
- **keeps private-profile authors attributable** — GIVEN an author makes the profile private WHEN discussion attribution is resolved THEN current name/avatar remain available in discussion context and the profile link is null _(verifies R8 and R14)_
- **reads only current validated photos** — GIVEN valid, absent, and invalidated photo state WHEN contextual photo access is requested THEN only the validated current photo is returned and no object key escapes _(verifies R8 and N1)_

##### Profile Lifecycle Guard

- **rejects clearing required attribution** — GIVEN an account with a visible comment or reply WHEN it clears display name or photo THEN the profile transaction fails with the approved conflict and existing attribution remains _(verifies R14)_
- **allows safe attribution updates and privacy changes** — GIVEN visible entries WHEN the author renames, replaces a validated photo, or makes the profile private THEN the update succeeds and current discussion attribution follows it _(verifies R14)_
- **preserves profiles without discussion activity** — GIVEN an account with no visible entries WHEN it performs an otherwise valid clear operation THEN existing profile behavior remains unchanged _(guards ARCH backward-regression risk for users profile updates)_
- **serializes profile clearing against posting** — GIVEN concurrent clear and post transactions WHEN both take the account lock THEN the final state contains either no post with cleared fields or a post with complete attribution, never an anonymous entry _(verifies R12 and R14; verifies ARCH concurrency stress-test)_
- **preserves existing profile and photo privacy contracts** — GIVEN existing public/private profile and `/profiles/{account_id}/photo` requests WHEN exercised after the change THEN their authorization, response, and link behavior remain unchanged _(guards ARCH backward-regression risk for `apps/api/app/modules/users/graphql.py` and existing profile photo routes)_

### Implementation Notes

- **Module(s):** users owns current attribution/profile storage; comments supplies `CommentAuthorActivityAccess`
- **Pattern reference:** existing `ProfileService`, `ProfileRepository`, and photo routes in `apps/api/app/modules/users/`
- **Key decisions:** A6, A7, A8, A12
- **Libraries:** SQLAlchemy async sessions, existing private object storage abstraction, FastAPI/Pydantic
- **High-risk callouts:** Profile updates and posting must acquire the same authoritative account lock; private profile visibility controls only the link, not attribution attached to public speech.

### Scope Boundaries

- Do NOT force an author to publish the full profile.
- Do NOT snapshot attribution into comment rows or invent fallback names/avatars.
- Only add the named discussion-attribution and visible-activity boundaries.

### Files Expected

**New files:**
- `apps/api/app/modules/users/comment_attribution.py` (batch attribution and validated photo boundary)

**Modified files:**
- `apps/api/app/modules/users/repository.py` (bounded batch attribution and photo reads)
- `apps/api/app/modules/users/service.py` (visible-entry guard under account lock)
- `apps/api/app/modules/users/routes.py` (wire activity boundary and map the guard safely)
- `apps/api/app/modules/users/tests/test_profile.py` (profile lifecycle cases)
- `apps/api/app/modules/users/tests/test_routes.py` (transport mapping and existing-route regression cases)
- `tests/integration/test_profile_privacy.py` (private profile discussion attribution)
- `tests/integration/test_comment_concurrency.py` (profile-clear/post race)

**Must NOT modify:**
- `apps/api/app/modules/users/graphql.py` (silent-regression hotspot)
- Existing `/api/v1/profiles/{account_id}/photo` behavior inside `users/routes.py` (contextual discussion photo is separate)
- `apps/api/app/modules/auth/` (account state semantics remain unchanged)

---

## Task T4: Compose Bounded Public Discussion Reads in GraphQL

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T2, T3
> **Satisfies REQs:** R1, R2, R5, R6, R7, R8, N1, N3, N5
> **Footprint slice:** New: comments GraphQL types/resolvers and tests; Modified: composed GraphQL root and composition integration coverage
> **High-risk areas touched:** Product confidentiality (H); Public GraphQL/OpenAPI contracts (M)

### Description

Expose public discussion and earlier-reply pages through independent bounded Strawberry root fields. Compose current attribution in set-based reads, sanitize every failure, and preserve all existing schema variants and query limits.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/comments/tests/test_graphql.py`
- `tests/integration/test_graphql_composition.py`
- `tests/integration/test_comments.py`

#### Test Scenarios

##### Public Discussion Reads

- **returns identical public discussion to signed-out and signed-in readers** — GIVEN a public current or archived launch WHEN both sessions query it THEN content and ordering match _(verifies R1 and R2)_
- **bounds and stabilizes root pages** — GIVEN more than 20 roots and concurrent new activity WHEN pages advance by cursor THEN each page has at most 20 newest-first roots without gaps or duplicates _(verifies R6 and N3)_
- **returns bounded chronological reply context** — GIVEN roots with many replies WHEN discussion loads THEN each root exposes the total count and three newest replies in chronological display order _(verifies R7)_
- **loads earlier replies safely** — GIVEN a valid root WHEN earlier pages load THEN each contains at most 20 chronological replies with a stable earlier cursor _(verifies R7 and N3)_
- **hides invalid or unavailable context** — GIVEN private/removed products, wrong-product parents, or depth-one parents WHEN queried THEN responses disclose no content, attribution, count, or private distinction _(verifies R1, R5, N1 and N5)_
- **batches current attribution** — GIVEN one page with repeated and distinct authors WHEN resolved THEN one bounded attribution call supplies current names, avatars, and nullable profile links without N+1 queries _(verifies R8)_

##### Composition Regression Guard

- **preserves schema variants and query safety** — GIVEN full, products-only, launches-only, and profile-only compositions WHEN schemas and allowlists are inspected THEN comment roots exist only in the approved variants, all prior roots remain, and query size/depth/field limits still apply _(guards ARCH backward-regression risks for `app.graphql`, `products/graphql.py`, and `users/graphql.py`)_

### Implementation Notes

- **Module(s):** comments GraphQL transport; application GraphQL composition
- **Pattern reference:** `apps/api/app/modules/votes/graphql.py`; `apps/api/app/graphql.py`
- **Key decisions:** A3, A6, A12, A13, A15
- **Libraries:** Strawberry GraphQL, SQLAlchemy async sessions, existing GraphQL result sanitizer
- **High-risk callouts:** Unknown and non-public products must remain indistinguishable; resolver work must remain proportional to page size.

### Scope Boundaries

- Do NOT add mutations, subscriptions, or discussion fields directly to the public product payload.
- Do NOT return unbounded replies or private profile fields.
- Only add the two approved read roots and their bounded public projections.

### Files Expected

**New files:**
- `apps/api/app/modules/comments/graphql.py` (bounded discussion fields and cursor types)
- `apps/api/app/modules/comments/tests/test_graphql.py` (resolver and sanitization tests)

**Modified files:**
- `apps/api/app/graphql.py` (compose `CommentQuery`, allow roots, inject factory, sanitize errors)
- `tests/integration/test_graphql_composition.py` (schema variant and prior-root regression checks)
- `tests/integration/test_comments.py` (public read integration cases)

**Must NOT modify:**
- `apps/api/app/modules/products/graphql.py` (existing public product fields remain stable)
- `apps/api/app/modules/users/graphql.py` (existing profile privacy remains stable)
- Existing GraphQL mutation/subscription behavior (none is introduced)

### TDD Sequence (optional)

1. Define projection and cursor behavior with resolver tests.
2. Add unavailable/error sanitization cases.
3. Compose the roots and run every existing schema variant regression.

---

## Task T5: Build Product-Scoped Live Discussion Delivery

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T2
> **Satisfies REQs:** R1, R2, R9, R12, R13, N1, N2, N6
> **Footprint slice:** New: comments live ticket, Redis channel, lease, WebSocket module and focused live tests
> **High-risk areas touched:** Product confidentiality (H); Redis/live delivery (M)

### Description

Implement short-lived product-scoped HMAC tickets and an origin-checked WebSocket that forwards identifier-only Redis invalidations. The socket must periodically revalidate public visibility, apply bounded leases, and fail safely without becoming a prerequisite for ordinary reads or posting.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/comments/tests/test_live.py`
- `tests/integration/test_comment_live.py`

#### Test Scenarios

##### Ticket and Channel Scope

- **verifies a valid product-scoped ticket** — GIVEN a freshly issued ticket WHEN its signature, expiry, version, and product claim are verified THEN only that public product scope is returned _(verifies R1, R2 and N1)_
- **rejects untrusted ticket material** — GIVEN altered, expired, malformed, or differently scoped tickets WHEN verification runs THEN the connection is denied without revealing claims _(verifies N1)_
- **forwards identifiers only** — GIVEN `comment.created` and `discussion.closed` invalidations WHEN frames are sent THEN they contain only the approved product/comment/parent identifiers and never body, author, ticket, or private state _(verifies R9, R12, N1 and N6)_

##### Socket Lifecycle and Resilience

- **subscribes to exactly one product channel** — GIVEN a valid origin and ticket WHEN the WebSocket connects THEN it acquires the bounded product lease, subscribes only to that channel, and releases resources on disconnect _(verifies R9)_
- **closes when discussion becomes unavailable** — GIVEN a connected viewer WHEN the periodic 30-second visibility check finds the product non-public THEN it sends/handles discussion closure and terminates the lease _(verifies R12 and N1)_
- **degrades safely during Redis failure** — GIVEN Redis subscribe/read failure WHEN the socket is active THEN it closes with a retryable status while PostgreSQL read/post paths remain independent _(verifies R13 and N2; verifies ARCH Redis outage stress-test)_
- **bounds copied-ticket and connection flooding** — GIVEN excessive source/product connections or a copied ticket from an invalid origin WHEN admission runs THEN origin, expiry, lease, and connection limits reject the excess without affecting existing vote live channels _(guards ARCH ticket-flood stress-test and backward-regression risk for `apps/api/app/modules/votes/`)_

### Implementation Notes

- **Module(s):** comments live transport and Redis adapter
- **Pattern reference:** `apps/api/app/modules/votes/live.py`; notification Redis pub/sub lifecycle
- **Key decisions:** A9, A10, A15
- **Libraries:** FastAPI WebSockets, `redis.asyncio`, HMAC-SHA256, existing origin validation
- **High-risk callouts:** Recheck product visibility for the whole connection lifetime; tickets and frames must contain no content or identity data.

### Scope Boundaries

- Do NOT add GraphQL subscriptions or make live delivery authoritative.
- Do NOT replay discussion bodies through Redis.
- Only implement product-scoped invalidation and closure frames.

### Files Expected

**New files:**
- `apps/api/app/modules/comments/live.py` (tickets, channels, leases, visibility checks, and WebSocket router)
- `apps/api/app/modules/comments/tests/test_live.py` (ticket/socket unit tests)
- `tests/integration/test_comment_live.py` (live lifecycle and Redis outage coverage)

**Modified files:**
- None.

**Must NOT modify:**
- `apps/api/app/modules/votes/live.py` (silent-regression hotspot)
- `apps/api/app/modules/notifications/` (existing live delivery remains independent)
- Redis as a durable discussion store (prohibited by architecture)

---

## Task T6: Expose Safe Comment Commands, Tickets, and Avatars

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T2, T3, T5
> **Satisfies REQs:** R1, R3, R4, R5, R8, R9, R10, R11, R12, R13, N1, N5, N6
> **Footprint slice:** New: comments Pydantic schemas, REST routes, route tests; Modified: comments integration API coverage
> **High-risk areas touched:** Product confidentiality (H); Profile lifecycle (H); Public GraphQL/OpenAPI contracts (M); Redis/live delivery (M)

### Description

Add thin FastAPI routes for comment/reply commands, public live-ticket issuance, and contextual author photos. Enforce transport security and stable status mapping while delegating every domain decision to the approved comments, products, users, and live service boundaries.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/comments/tests/test_routes.py`
- `tests/integration/test_comments.py`

#### Test Scenarios

##### Command Success and Replay

- **creates confirmed roots and replies** — GIVEN an eligible session, valid CSRF/origin, body, product, and root parent WHEN the command is posted THEN it returns `201` with the confirmed plain-text entry in the requested location _(verifies R4, R5 and R10)_
- **returns exact idempotent replay** — GIVEN a committed request WHEN the same idempotency key and fingerprint are retried THEN it returns `200`, the original entry, and `replayed=true` _(verifies R11 and R13)_

##### Safe Error Mapping

- **maps invalid input without losing user intent** — GIVEN blank, oversized, or malformed body/key input WHEN submitted THEN it returns a safe `400` contract and no publication is claimed _(verifies R4, R13 and N5)_
- **enforces session and request security** — GIVEN missing authentication, invalid origin/CSRF, or an ineligible account WHEN posting is attempted THEN the route returns `401` or `403` as specified and never calls a successful write path _(verifies R3)_
- **hides unavailable resources** — GIVEN unknown, scheduled, removed, or private products and unavailable parents WHEN requested THEN the route returns the same non-disclosing `404` shape _(verifies R1, R12 and N1)_
- **maps posting conflicts and limits** — GIVEN key reuse, repeated text, nested/wrong-product replies, or exceeded rolling limits WHEN submitted THEN the route returns `409` or `429` with `Retry-After` and no duplicate entry _(verifies R5 and R11)_
- **maps infrastructure uncertainty safely** — GIVEN a transactional dependency failure WHEN posting is attempted THEN it returns `503`, excludes sensitive values, and does not report the entry as published _(verifies R13, N5 and N6)_

##### Public Auxiliary Endpoints

- **protects tickets and contextual avatars** — GIVEN public/non-public products and authors with/without visible entries WHEN tickets or photos are requested THEN tickets are origin/source-limited and avatars return only for authorized public context with `no-store` and `nosniff`, without object keys _(verifies R8, R9 and N1)_

### Implementation Notes

- **Module(s):** comments REST transport; users contextual photo boundary; comments live ticket service
- **Pattern reference:** `apps/api/app/modules/votes/routes.py`; public media handling in users/products routes
- **Key decisions:** A4, A7, A10, A12, A15
- **Libraries:** FastAPI, Pydantic, existing CSRF/origin/rate-limit utilities, private storage streaming abstraction
- **High-risk callouts:** Keep domain checks inside the service transaction even when the route pre-validates transport state; never expose why a product is unavailable.

### Scope Boundaries

- Do NOT add edit/delete endpoints, anonymous posting, or staff posting.
- Do NOT reuse the existing public/private profile photo route for discussion authorization.
- Only expose the approved command, ticket, and contextual-avatar contracts.

### Files Expected

**New files:**
- `apps/api/app/modules/comments/schemas.py` (Pydantic request/response contracts)
- `apps/api/app/modules/comments/routes.py` (commands, ticket, avatar, and safe error mapping)
- `apps/api/app/modules/comments/tests/test_routes.py` (transport contract tests)

**Modified files:**
- `tests/integration/test_comments.py` (end-to-end command, media, and visibility coverage)

**Must NOT modify:**
- `apps/api/app/modules/auth/` (session and role semantics are reused unchanged)
- Existing profile photo route behavior (discussion avatar is contextual and separate)
- `apps/api/app/modules/products/routes.py` (comments owns its route surface)

### TDD Sequence (optional)

1. Specify schemas and stable success/error responses.
2. Add secured command routes and idempotency semantics.
3. Add ticket/avatar routes and product-confidentiality integration cases.

---

## Task T7: Publish Comment Invalidations Through the Transactional Outbox

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T1, T2
> **Satisfies REQs:** R9, R10, R12, R13, N1, N2, N6
> **Footprint slice:** New: comments event handler/tests and worker tests; Modified: shared dispatcher/tests, worker wiring, comment live integration, background-process integration
> **High-risk areas touched:** Product confidentiality (H); Outbox dispatcher (M); Redis/live delivery (M)

### Description

Register `comment.created.v1` in the existing encrypted transactional outbox and publish identifier-only invalidations from the worker after revalidating persisted visibility. Preserve retry, dead-letter, idempotency, and every existing dispatcher branch.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/comments/tests/test_events.py`
- `apps/api/app/shared/events/tests/test_dispatcher.py`
- `apps/worker/tests/test_comment_worker.py`
- `tests/integration/test_comment_live.py`
- `tests/integration/test_background_processes.py`

#### Test Scenarios

##### Event Publication

- **keeps the outbox payload identifier-only** — GIVEN a successful comment transaction WHEN `comment.created.v1` is decoded in a test boundary THEN it contains only approved identifiers and no body, author details, ticket, or private product data _(verifies N1 and N6)_
- **publishes a revalidated visible entry** — GIVEN a due event for a still-visible comment and public product WHEN dispatched THEN the worker publishes one correct product-channel invalidation and completes the event _(verifies R9)_
- **suppresses stale or unavailable content** — GIVEN a missing/non-visible comment or non-public product WHEN dispatched THEN no invalidation leaks and the event reaches the approved safe terminal outcome _(verifies R12 and N1)_

##### Retry and Idempotency

- **retries Redis publication failure** — GIVEN a committed comment and transient Redis error WHEN the worker handles the event THEN the comment remains committed, the event remains retryable, and no request path is rolled back _(verifies R10, R13 and N2; verifies ARCH Redis outage stress-test)_
- **handles delayed and duplicate delivery harmlessly** — GIVEN repeated or late delivery WHEN events publish THEN frames remain identifier-only invalidations and authoritative refetch prevents duplicate discussion state _(verifies R9 and R13)_
- **dead-letters malformed permanent events safely** — GIVEN an invalid payload WHEN dispatch runs THEN existing permanent-failure handling applies without sensitive logging _(verifies N6)_

##### Dispatcher Regression Guard

- **preserves all existing event families and worker startup** — GIVEN email, product, launch, notification, vote, and comment events WHEN dispatchers/workers start and process them THEN each reaches its existing handler and completion semantics _(guards ARCH backward-regression risk for `shared/events/dispatcher.py`, `shared/events/outbox.py`, notifications, votes, and worker wiring)_

### Implementation Notes

- **Module(s):** comments event consumer; shared dispatcher; worker process
- **Pattern reference:** `apps/api/app/shared/events/dispatcher.py`; notification publication handlers; `apps/worker/worker.py`; vote worker tests (the architecture's cited `votes/events.py` does not exist)
- **Key decisions:** A9, A15
- **Libraries:** existing encrypted outbox codec/repository, SQLAlchemy async sessions, Redis async publish
- **High-risk callouts:** Revalidation occurs before publication; adding one handler must not change event-family precedence or completion behavior.

### Scope Boundaries

- Do NOT send bodies or attribution through outbox/Redis.
- Do NOT add comment notifications or email delivery.
- Only consume the approved creation event and publish invalidations.

### Files Expected

**New files:**
- `apps/api/app/modules/comments/events.py` (revalidating Redis publication handler)
- `apps/api/app/modules/comments/tests/test_events.py` (event and publication tests)
- `apps/worker/tests/test_comment_worker.py` (worker retry/revalidation tests)

**Modified files:**
- `apps/api/app/shared/events/dispatcher.py` (register comment event family and handler)
- `apps/api/app/shared/events/tests/test_dispatcher.py` (comment branch and existing-family regression tests)
- `apps/worker/worker.py` (construct and inject comment publisher)
- `tests/integration/test_comment_live.py` (outbox-to-Redis integration)
- `tests/integration/test_background_processes.py` (worker configuration/startup coverage)

**Must NOT modify:**
- `apps/api/app/shared/events/outbox.py` (silent-regression hotspot)
- `apps/api/app/modules/notifications/` (no comment notification work)
- Existing vote/product/launch/email event payloads or handlers

---

## Task T8: Wire Comment Runtime Dependencies and Rollout Flags

> **Status:** done
> **Verification:** test-after
> **Effort:** s
> **Priority:** high
> **Depends on:** T3, T4, T5, T6, T7
> **Satisfies REQs:** R1, R3, R9, R11, R12, N1, N2, N6
> **Footprint slice:** Modified: application assembly, shared settings, settings tests, background-process integration
> **High-risk areas touched:** Product confidentiality (H); Public GraphQL/OpenAPI contracts (M); Redis/live delivery (M); Deployment configuration (M)

### Description

Add safe-off comment feature settings and construct the comments routes, GraphQL dependencies, live Redis adapter, attribution/activity boundaries, and worker-compatible services in the application assembly. Enforce that write enablement is impossible unless the overall feature is enabled.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/config/tests/test_settings.py`
- `tests/integration/test_background_processes.py`
- `tests/integration/test_graphql_composition.py`

#### Test Scenarios

##### Settings Validation

- **defaults comment capabilities off** — GIVEN no comment environment values WHEN settings load THEN both feature and write flags are false _(verifies safe rollout for R12)_
- **rejects writes without the feature** — GIVEN writes enabled and comments disabled WHEN settings validate THEN startup fails with a safe configuration error _(verifies N1 and N6)_

##### Runtime Registration

- **registers read-only mode** — GIVEN comments enabled and writes disabled WHEN the app starts THEN public reads/live dependencies are present and posting remains unavailable _(verifies R1, R3 and R9)_
- **registers the full feature** — GIVEN both flags enabled WHEN the app and worker start THEN REST, GraphQL factories, media, live, outbox publisher, and cross-module boundaries are constructed once with the approved dependencies _(verifies R9 and R11)_
- **keeps disabled mode inert** — GIVEN both flags disabled WHEN the app starts THEN comment routes/live infrastructure are unavailable without mutating unrelated feature behavior _(verifies R12 and N2)_

##### Startup Regression Guard

- **preserves existing route combinations** — GIVEN existing health, auth, profile, product, launch, notification, vote, and GraphQL feature combinations WHEN apps are created THEN their prior routes and dependencies remain registered exactly as before _(guards ARCH backward-regression risk for app composition and settings variants)_

### Implementation Notes

- **Module(s):** shared configuration and API composition root
- **Pattern reference:** vote flags and route/live wiring in `apps/api/app/shared/config/settings.py` and `apps/api/app/main.py`
- **Key decisions:** A6, A10, A13, A14
- **Libraries:** Pydantic settings, FastAPI router assembly, sync/async Redis clients
- **High-risk callouts:** Full GraphQL schema stability is handled in T4; runtime flags control availability, not ad hoc schema mutation.

### Scope Boundaries

- Do NOT add hidden default-on behavior or environment-specific bypasses.
- Do NOT embed secrets or open Redis connections when the feature is disabled.
- Only wire dependencies already defined by T3–T7.

### Files Expected

**New files:**
- None.

**Modified files:**
- `apps/api/app/shared/config/settings.py` (add and validate comment flags)
- `apps/api/app/shared/config/tests/test_settings.py` (defaults and dependency invariant)
- `apps/api/app/main.py` (construct and register comments dependencies/routes/live)
- `tests/integration/test_background_processes.py` (worker runtime configuration)
- `tests/integration/test_graphql_composition.py` (runtime/schema availability combinations)

**Must NOT modify:**
- `apps/web/src/App.tsx` (routing is unchanged)
- `apps/api/app/modules/votes/` and `apps/api/app/modules/notifications/` (existing assembly behavior is regression-tested)
- Existing health/auth/product/launch feature-flag semantics

---

## Task T9: Generate and Lock the Discussion API Contracts

> **Status:** not started
> **Verification:** checklist
> **Effort:** s
> **Priority:** high
> **Depends on:** T4, T6, T8
> **Satisfies REQs:** R1, R2, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, N1, N3, N5
> **Footprint slice:** Modified: GraphQL operations/schema, OpenAPI, generated REST/GraphQL TypeScript, contract validation script
> **High-risk areas touched:** Public GraphQL/OpenAPI contracts (M); Product confidentiality (H)

### Description

Define the bounded frontend GraphQL operations, regenerate REST and GraphQL contract artifacts, and extend drift checks for the new discussion surface. Existing generated profile, product, launch, notification, and vote contracts must remain available.

### Verification Checklist

- **Regenerate OpenAPI** — expected: comment, reply, live-ticket, and contextual-avatar endpoints appear with the approved bodies, headers, success responses, and safe error statuses.
- **Regenerate the full GraphQL schema** — expected: `productDiscussion` and `commentReplies` exist in the full schema, while disabled composition variants remain covered by server tests.
- **Validate bounded operations** — expected: operations accept the approved cursor/page variables and request only public entry/attribution fields; no unbounded collection or private field appears.
- **Regenerate strict TypeScript contracts** — expected: REST and GraphQL generation completes and the web TypeScript build accepts the generated types without hand edits.
- **Run `sh scripts/quality/contracts.sh --check`** — expected: exit code 0 and no schema, OpenAPI, operation, or generated-file drift.
- **Inspect regression diff** — expected: existing profile, product, launch, notification, and vote operations/types remain present and unchanged except deterministic generator formatting.

### Implementation Notes

- **Module(s):** shared generated contract package and quality tooling
- **Pattern reference:** existing operations in `packages/contracts/operations.graphql`; `scripts/quality/contracts.sh`
- **Key decisions:** A3, A4, A12, A13
- **Libraries:** OpenAPI generator used by the repository, GraphQL schema/type generator, TypeScript strict mode
- **High-risk callouts:** Generated artifacts must reflect safe public projections exactly; never hand-maintain generated TypeScript or schema files.

### Scope Boundaries

- Do NOT add client operations for editing, deletion, moderation, reports, or notifications.
- Do NOT expose storage keys, profile-private fields, or unbounded replies.
- Only generate contracts from the T4/T6 server surfaces.

### Files Expected

**New files:**
- None.

**Modified files:**
- `packages/contracts/operations.graphql` (add bounded discussion reads)
- `packages/contracts/schema.graphql` (regenerated composed schema)
- `packages/contracts/openapi.json` (regenerated REST contract)
- `packages/contracts/src/generated.ts` (regenerated REST TypeScript)
- `packages/contracts/src/graphql.generated.ts` (regenerated GraphQL operations/types)
- `scripts/quality/contracts.sh` (assert comment contracts remain reproducible and bounded)

**Must NOT modify:**
- Generated files by hand (all changes must come from repository generators)
- Existing public product/profile contract semantics
- Runtime application code (owned by earlier tasks)

---

## Task T10: Reconcile Discussion State in the Web Client

> **Status:** not started
> **Verification:** tdd
> **Effort:** l
> **Priority:** high
> **Depends on:** T9
> **Satisfies REQs:** R6, R7, R9, R10, R11, R12, R13, N2, N3, N5
> **Footprint slice:** New: comments client, TanStack Query hooks, live reconciliation hook, and focused frontend tests
> **High-risk areas touched:** Public GraphQL/OpenAPI contracts (M); Public product UI (M); Redis/live delivery (M)

### Description

Build the generated-contract client and TanStack Query state layer for root/reply pagination, commands, confirmed-result reconciliation, and live invalidations. Keep drafts, notices, loaded-parent tracking, and socket state local while ensuring event/response races never duplicate or falsely publish an entry.

### Test Plan

#### Test File(s)
- `apps/web/src/comments/client.test.ts`
- `apps/web/src/comments/useComments.test.ts`
- `apps/web/src/comments/useCommentsLive.test.ts`

#### Test Scenarios

##### Queries and Commands

- **pages and deduplicates discussion reads** — GIVEN multiple root/reply pages WHEN TanStack Query loads cursors THEN stable keys preserve newest-first roots, chronological replies, and unique IDs _(verifies R6, R7 and N3)_
- **sends secured idempotent commands** — GIVEN comment/reply submissions WHEN the client calls REST THEN it sends credentials, CSRF, and one idempotency key and distinguishes new, replayed, limited, conflict, and retryable responses _(verifies R10, R11 and R13)_
- **shows only confirmed publication** — GIVEN pending, successful, failed, and timed-out commands WHEN state updates THEN no optimistic entry appears, confirmed results appear immediately, and failed/unknown results preserve the draft _(verifies R10 and R13)_
- **deduplicates event-before-response races** — GIVEN a matching live invalidation arrives before the REST result WHEN both reconcile THEN the entry appears once in the correct location _(verifies R9, R10 and R11; verifies ARCH concurrency stress-test)_

##### Live Reconciliation

- **queues new top-level activity behind a notice** — GIVEN a viewer reading loaded pages WHEN a new root event arrives THEN page order does not move until the notice is selected, after which roots refetch _(verifies R9)_
- **routes reply invalidations by parent visibility** — GIVEN reply events for loaded and unloaded parents WHEN handled THEN loaded parent replies refetch and unloaded parent activity increments the notice without an orphan entry _(verifies R9)_
- **reconciles after reconnect without losing drafts** — GIVEN socket interruption WHEN it reconnects THEN root and all loaded reply queries invalidate while unsent drafts and active form state remain _(verifies R13 and N2; verifies ARCH Redis outage stress-test)_
- **closes unavailable discussion safely** — GIVEN `discussion.closed` WHEN received THEN discussion and public-product state invalidate, live delivery stops, confirmed projections clear, and unsent input remains recoverable _(verifies R12 and R13)_

### Implementation Notes

- **Module(s):** `apps/web/src/comments` data and live state
- **Pattern reference:** `apps/web/src/launches/client.ts`; `apps/web/src/launches/useLaunches.ts`; existing notification/vote live clients
- **Key decisions:** A3, A4, A9, A11, A13
- **Libraries:** React, TypeScript strict mode, TanStack Query, browser WebSocket API, generated contracts
- **High-risk callouts:** Keep server state in TanStack Query and never treat a socket frame or timed-out request as publication confirmation.

### Scope Boundaries

- Do NOT introduce a global discussion store or hand-maintained API types.
- Do NOT optimistically show unconfirmed entries.
- Only implement data fetching, command state, local reconciliation, and invalidation behavior; visual composition belongs to T11.

### Files Expected

**New files:**
- `apps/web/src/comments/client.ts` (generated-contract REST and GraphQL adapters)
- `apps/web/src/comments/client.test.ts` (transport and error contract tests)
- `apps/web/src/comments/useComments.ts` (root/reply queries, commands, and confirmed reconciliation)
- `apps/web/src/comments/useComments.test.ts` (query/command state tests)
- `apps/web/src/comments/useCommentsLive.ts` (ticket/socket lifecycle and invalidation handling)
- `apps/web/src/comments/useCommentsLive.test.ts` (race, notice, reconnect, and closure tests)
- `apps/web/src/comments/*.test.ts*` (aggregate architecture footprint; concrete client/hook/component tests are owned by T10–T11)

**Modified files:**
- None.

**Must NOT modify:**
- `packages/contracts/src/generated.ts` or `packages/contracts/src/graphql.generated.ts` by hand
- `apps/web/src/App.tsx` (routing remains unchanged)
- Existing launch/vote/notification query keys or live state

### TDD Sequence (optional)

1. Specify client requests and typed errors.
2. Add bounded query/command reconciliation tests.
3. Add live race, notice, reconnect, and closure behavior.

---

## Task T11: Mount an Accessible Responsive Discussion Surface

> **Status:** not started
> **Verification:** ui
> **Effort:** l
> **Priority:** high
> **Depends on:** T10
> **Satisfies REQs:** R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R13, N4, N5
> **Footprint slice:** New: CommentsSection component/styles/tests and browser scenario; Modified: public launch detail screen/tests and shared styles
> **High-risk areas touched:** Public product UI (M); Product confidentiality (H)

### Description

Mount an original Launchpad discussion section on the existing public product detail page with accessible reading, posting, replying, pagination, notices, and restricted-account states. Preserve existing product, voting, routing, navigation, responsive layout, focus, and reading position behavior.

### Verification Checklist

- **Public visibility states** — expected: current and archived public product pages show discussion to signed-out and signed-in viewers; unavailable product surfaces expose no discussion controls or content _(R1, R2)_
- **Posting eligibility states** — expected: eligible members/founders see forms; signed-out, unverified, suspended, reviewer/admin, and incomplete-profile viewers see their approved read-only action or profile-completion link _(R3)_
- **Bounded thread presentation** — expected: roots display newest-first, reply summaries chronologically, and “View earlier replies” is keyboard-operable without duplicates or reordering _(R5–R7)_
- **Safe text rendering** — expected: markup/script-like content displays literally and cannot execute or alter layout _(R4, N5)_
- **Submission feedback** — expected: confirmed success appears immediately; validation, timeout, conflict, and limit errors retain the draft, remain understandable, and move focus only to the relevant error/control _(R10, R11, R13)_
- **Non-disruptive live activity** — expected: new-root notice does not move reading position or steal typing focus; visible-parent replies update in place; selecting the notice refetches and focuses the discussion heading _(R9)_
- **Accessibility pass** — expected: headings, author links/images, labels, reply controls, notices, errors, and pagination work by keyboard and expose appropriate names/live-region announcements _(N4)_
- **Responsive and regression pass** — expected: supported mobile and desktop widths remain readable without horizontal overflow, while product details, gallery, voting, navigation, and routes behave as before.

#### Testable Seams

- `apps/web/src/comments/CommentsSection.test.tsx`: render/order, eligibility branches, escaped text, handlers, draft retention, notice state, and basic accessibility.
- `apps/web/src/launches/LaunchScreens.test.tsx`: mount only on the public product detail surface and preserve existing product/vote behavior.
- `tests/browser/comments.spec.ts`: keyboard flow, mobile/desktop layout, public/signed-in states, posting, pagination, live notice, and reconnection evidence.

### Implementation Notes

- **Module(s):** comments presentation mounted by the public launch screen
- **Pattern reference:** `apps/web/src/launches/LaunchScreens.tsx`; `apps/web/src/products/products.css`; existing launch screen tests
- **Key decisions:** A7, A11, A12
- **Libraries:** React, generated types, TanStack Query hooks from T10, existing CSS system
- **High-risk callouts:** Follow `docs/source/inspiration.md` for direction only; preserve reader focus/scroll position and never show discussion for an unavailable product.

### Scope Boundaries

- Do NOT copy Product Hunt or Nick Launches branding, layouts, copy, or assets.
- Do NOT add editing, deletion, reactions, moderation, notifications, or more than one reply level.
- Only add the approved discussion section to the existing public product detail page.

### Files Expected

**New files:**
- `apps/web/src/comments/CommentsSection.tsx` (accessible discussion presentation)
- `apps/web/src/comments/CommentsSection.test.tsx` (component seams)
- `apps/web/src/comments/comments.css` (responsive discussion styles)
- `tests/browser/comments.spec.ts` (browser/UI verification)

**Modified files:**
- `apps/web/src/launches/LaunchScreens.tsx` (mount discussion on public product details)
- `apps/web/src/launches/LaunchScreens.test.tsx` (integration and restricted-state coverage)
- `apps/web/src/styles.css` (shared focus/responsive treatment required by discussion)

**Must NOT modify:**
- `apps/web/src/App.tsx` (silent-regression hotspot; routing remains unchanged)
- Existing voting, product gallery, navigation, or workspace components
- Existing launch/product visual identity beyond the local discussion integration

---

## Task T12: Configure Safe Comment Rollout Across Environments

> **Status:** not started
> **Verification:** checklist
> **Effort:** s
> **Priority:** high
> **Depends on:** T8
> **Satisfies REQs:** R12, N1, N2, N6
> **Footprint slice:** Modified: environment example, local Compose, checks Compose, production Compose
> **High-risk areas touched:** Deployment configuration (M); Product confidentiality (H); Redis/live delivery (M)

### Description

Expose explicit safe-off feature and write flags plus required live configuration in local, check, and production Compose environments. Keep secrets external and ensure API/worker configuration is consistent with the staged read/live-before-write rollout.

### Verification Checklist

- **Inspect `.env.example`** — expected: comment feature/write flags and non-secret live settings are documented with safe-off defaults.
- **Run `docker compose -f compose.yaml config`** — expected: configuration renders successfully and API/worker receive the approved comment settings without changing existing services, ports, networks, or health dependencies.
- **Run `docker compose -f compose.checks.yaml config`** — expected: checks can exercise disabled, read-only, and fully enabled combinations with valid flag dependencies.
- **Run `docker compose -f compose.production.yaml config`** — expected: production renders with explicit safe-off rollout values and no embedded ticket/outbox/storage secret.
- **Validate invalid flag combination** — expected: writes enabled while comments are disabled fails settings/startup validation before traffic is served.
- **Compare existing service topology** — expected: database, Redis, API, worker, scheduler, web, storage, mail, and quality service relationships remain unchanged except approved environment propagation.

### Implementation Notes

- **Module(s):** deployment/runtime configuration
- **Pattern reference:** existing product, launch, and vote feature flags across `.env.example` and Compose files
- **Key decisions:** A10, A13, A14
- **Libraries:** Docker Compose variable interpolation; Pydantic settings validation from T8
- **High-risk callouts:** Production rollout is migration → code flags off → reads/live on → writes on; rollback disables flags and never downgrades production data.

### Scope Boundaries

- Do NOT deploy, enable production flags, or introduce secrets in version control.
- Do NOT change service topology or public port exposure.
- Only propagate the approved comment rollout/live settings.

### Files Expected

**New files:**
- None.

**Modified files:**
- `.env.example` (document comment flags and live settings)
- `compose.yaml` (pass local API/worker settings)
- `compose.checks.yaml` (exercise feature variants)
- `compose.production.yaml` (expose explicit production rollout flags)

**Must NOT modify:**
- Secret files or runtime credentials
- Existing service port/network/volume contracts
- Production data or deployment state

---

## Task T13: Document Discussion Architecture and Operations

> **Status:** not started
> **Verification:** checklist
> **Effort:** s
> **Priority:** medium
> **Depends on:** T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12
> **Satisfies REQs:** R1, R3, R5, R9, R11, R12, R13, R14, N1, N2, N3, N6
> **Footprint slice:** New: ADR 0010; Modified: development guide
> **High-risk areas touched:** PostgreSQL schema (H); Product confidentiality (H); Profile lifecycle (H); Redis/live delivery (M); Deployment configuration (M)

### Description

Record the durable architectural decisions and provide accurate development, verification, rollout, rollback, privacy, and live-delivery guidance. Documentation must describe only implemented behavior and retain every approved scope exclusion.

### Verification Checklist

- **Review ADR 0010** — expected: it records module ownership, constrained storage, named product/user boundaries, REST/GraphQL split, transactional outbox, identifier-only invalidation, considered alternatives, and consequences.
- **Review local development instructions** — expected: migration, feature flags, contract generation, targeted tests, WebSocket diagnostics, and Redis-outage behavior have runnable commands matching the repository.
- **Review rollout and rollback** — expected: schema-first deployment, flags-off code, reads/live enablement, writes enablement, flag-based rollback, and no production downgrade match the architecture.
- **Review privacy and observability guidance** — expected: bodies, fingerprints, tickets, raw IPs, emails, storage keys, and private-product facts are explicitly excluded from logs/events/live frames.
- **Review scope language** — expected: docs do not claim editing, deletion, notifications, reporting, moderation, reactions, staff posting, anonymous posting, or unlimited nesting exists.
- **Run documentation hygiene checks** — expected: no template placeholders, broken repository paths, trailing whitespace, or Markdown structural errors remain.

### Implementation Notes

- **Module(s):** architecture decision records and developer operations documentation
- **Pattern reference:** `docs/adr/0002-health-contracts.md`; existing sections in `docs/development.md`
- **Key decisions:** A1–A15
- **Libraries:** Markdown only
- **High-risk callouts:** Document confidentiality and profile-attribution invariants precisely so future moderation/profile work does not bypass them.

### Scope Boundaries

- Do NOT document speculative APIs or deferred product behavior as implemented.
- Do NOT include credentials, real customer data, or operational secrets.
- Only document the approved and verified discussion slice.

### Files Expected

**New files:**
- `docs/adr/0010-comments-replies-live.md` (architecture decisions and consequences)

**Modified files:**
- `docs/development.md` (local setup, flags, generation, tests, rollout, and diagnostics)

**Must NOT modify:**
- Source requirements or architecture decisions
- Historical ADRs
- Deployment state or environment secrets

---
