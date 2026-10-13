# Architecture: Founder Product Drafts and Submission

> **Date:** 2026-09-29
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** `specs/requirements/REQ-add-product-draft-submission.md`
> **Tasks:** TASKS-add-product-draft-submission.md
> **Type:** feature

## Architecture Summary

Add a `products` feature module to the existing FastAPI modular monolith, with PostgreSQL as the authority for private drafts, media references, topics, submission periods, quotas, and queue order. Product-topic associations retain each founder's selected label separately from the shared canonical topic identity, so private proposals can be reused without revealing another founder's casing. REST commands perform versioned, transactional changes; the existing read-only Strawberry endpoint composes owner and staff product reads with the current profile reads. Auth supplies live verification, role, and suspension state through a named service boundary, while an operator-only audited command provisions staff and suspension. Private S3-compatible storage accepts bounded signed uploads and serves app-signed, authorization-rechecked downloads; an expanded typed outbox worker purges media after durable deletion.

## High-Level Structure

```text
React product pages ── REST commands ──► products routes ──► products service
          │                                  │                    │
          └── GraphQL reads ──► composed schema                  ├── products repository ──► PostgreSQL
                                      │                          ├── auth access interface ──► accounts
                                      └── products read service  ├── private image adapter ──► S3
                                                                 └── outbox ──► typed worker ──► S3 purge
```

`products` owns product decisions and persistence. `auth` owns account role/suspension and operator changes; `users` continues to own profiles. Existing profile fields remain on `/api/v1/graphql`; no public product field is introduced. The API, worker, and scheduler remain separate deployments of the same monolith, and no new broker, search index, or service is added. (R1–R17, N1–N4)

Product routes and product GraphQL fields are gated by `LAUNCHPAD_PRODUCTS_ENABLED` (default false in production). The flag permits a schema-compatible API/worker cutover before product event producers become reachable; local and check Compose configurations enable the feature explicitly. (N3)

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|---|---|---|---|
| Application | Existing FastAPI, SQLAlchemy 2 async, Strawberry, React/TypeScript, TanStack Query | A separate product service or second GraphQL endpoint | Preserves the modular-monolith boundary and one read contract; avoids new deployment and auth surfaces. (R1, R14, N1) |
| Authority/concurrency | PostgreSQL transactions, row locks, constraints, optimistic `version` | Redis counters, last-write-wins, client-only limits | Counts and current content stay coherent under simultaneous requests; Redis can be rebuilt. (R3, R10, R12, R16, N2–N3) |
| Queue | Separate submission-period rows, indexed by `(submitted_at, id)` | Timestamp only on product; external queue | Retains withdrawal/resubmission history and stable queue seniority without duplicate active entries. (R10–R13) |
| Topics | Unique normalized topic key plus an owner-selected label on each private association | Per-product strings; exposing shared private canonical casing | Reuses equivalent names under concurrent creation while reopening the founder's own spelling without revealing another founder's proposal. (R7–R8, N1) |
| Media | Existing private S3-compatible bucket, signed staging POST, byte validation/re-encoding, app-signed gated download | Public object URLs; direct long-lived S3 GET URLs | Existing upload pattern is reused; every download can recheck access after withdrawal or deletion. The API carries download bandwidth. (R6, R17, N1) |
| Async work | Existing PostgreSQL outbox with event-type dispatch in the worker | Best-effort deletion in request; Redis-only queue | A committed deletion has durable, idempotent physical purge and cannot be misrouted as email. (R17, N3) |
| Staff provisioning | Audited operator-only command; no HTTP promotion endpoint | Environment role list; self-service or public admin endpoint | Deployment access is the trust boundary, and role/suspension changes have a durable audit trail. (R14, N2) |
| Release gate | Product endpoints off by default, explicitly enabled after compatible worker is healthy | Enable on binary deploy; restart an older binary after migration | The existing readiness check requires the exact packaged Alembic head, so a reversible feature switch must remain within the new schema-compatible build. (N3) |

## Patterns & Conventions

- **Feature ownership** — products routes/resolvers stay thin, business decisions live in its service, and persistence in its repository; it never imports another feature's repository. Auth exposes named account-state/lock and batch staff-status interfaces. (AGENTS.md; R9, R14, N2)
- **Versioned aggregate** — all content/state changes compare an expected product version, lock the product row, and increment version on success. A supplied topic selection is replaced in that same save and version bump; an omitted selection is unchanged. A stale draft save returns a conflict without overwriting local browser state. (R2–R3, R7, R11–R12)
- **Submission periods** — a product has zero or one open period; valid pending edits update the same period's current version, whereas withdrawal closes it and resubmission creates another. (R10–R13)
- **Transactional outbox** — each user-visible product state change inserts a minimal encrypted event in the same transaction; product handlers are explicitly distinct from email delivery. Physical object deletion is retryable and idempotent. (AGENTS.md; N3)
- **Private-by-default reads** — resolvers and services both enforce named owner/staff policies; no unlaunched product, association, or media gets a visitor-facing resolver or public storage URL. Owner and permitted staff projections read the association's selected label, not another founder's canonical topic display name. (AGENTS.md; R8, N1–N2)
- **Generated contracts** — OpenAPI and GraphQL operation types are regenerated from schemas and operations, not hand-maintained. (AGENTS.md; N5)

## Data Models

### Account authorization extension

**Purpose:** Keep current identity and staff status in auth rather than copying it into products.

| Field | Type / Constraint | Notes |
|---|---|---|
| `accounts.role` | `member`, `reviewer`, or `admin`; non-null, default `member` | Reviewer/admin queue access also requires verified email and no suspension. |
| `accounts.suspended_at` | nullable timestamp | Live product policy input; existing sessions are not treated as cached authorization. |
| `account_admin_actions` | actor, target account, action, before/after metadata, timestamp | Append-only audit for operator role and suspension changes; no passwords or tokens. |

**Relationships:** One account owns many products. Auth's named service supplies current account state and a per-account lock for quota-changing product commands; the products repository does not import `AuthRepository`.

**Lifecycle:** New registrations remain `member` and unsuspended; audited operator actions can grant/revoke staff access or suspend/resume. Suspension blocks product creation, editing, uploads, submission, and draft deletion, but permits pending withdrawal. (R1, R9, R14, R16, N2)

### Product

**Purpose:** One founder-owned private listing and its current content/state.

| Field | Type / Constraint | Notes |
|---|---|---|
| `id`, `founder_id` | UUID primary key; account FK | Owner identity is immutable. |
| `status` | `draft` or `submitted` in this slice | Later review/launch transitions require additive design; never infer publication from submission. |
| `version` | nonnegative integer | Increments on content and state transitions; expected-version comparison prevents lost updates. |
| `name`, `pitch`, `description`, `website_url` | nullable, bounded text; HTTPS website when supplied | Drafts may be incomplete; supplied values are validated; submitted fields must be complete. |
| `website_key` | nullable canonical exact-link key, indexed | Lowercase scheme/host, normalize default port and empty root path; retain meaningful path/query. Staff-only duplicate detection, never unique. |
| `created_at`, `updated_at` | timestamps | Private owner ordering and operational diagnostics. |

**Relationships:** One founder; many assets and up to three current topic links; many historical submission periods, at most one open.

**Lifecycle:** Create `draft` → versioned draft edits → `submitted` → complete pending edits on same period or explicit withdrawal to `draft` → optional resubmission in a new period. Only a draft can be hard-deleted in this slice. Product content and associations are removed transactionally on deletion; minimal outbox/audit metadata may remain without content. (R1–R5, R9–R13, R15–R17)

### ProductSubmission

**Purpose:** One arrival period in the staff queue and a stable future review-decision target.

| Field | Type / Constraint | Notes |
|---|---|---|
| `id`, `product_id` | UUID primary key; product FK | New ID on every resubmission. |
| `state` | `pending` or `withdrawn` | A partial unique index permits one `pending` row per product. |
| `submitted_at`, `closed_at` | timestamps | Original timestamp never changes on pending edits; withdrawn row gets `closed_at`. |
| `product_version` | nonnegative integer | Updated with valid pending edits; later reviewer decisions must provide submission ID and version. |

**Relationships:** Many periods per product until product deletion. Queue index covers `state = 'pending'`, `submitted_at`, `id` for keyset pagination.

**Lifecycle:** Created atomically with a valid verified submission, updated in the same transaction as a pending edit, closed on withdrawal; never exposed outside owner/staff reads. (R10–R13, N1–N3)

### Topic and ProductTopic

**Purpose:** Canonical topic reuse without leaking unpublished proposals.

| Field | Type / Constraint | Notes |
|---|---|---|
| `topics.id`, `display_name` | UUID; trimmed name ≤40 characters | Shared canonical display is used for launched general choices, never to reconstruct a private founder selection. |
| `topics.name_key` | unique case-folded, trimmed key | Database unique index resolves concurrent equivalent creation. |
| `topics.first_launched_at` | nullable timestamp | Public eligibility only after a later launch workflow sets it; null proposals are not public suggestions. |
| `product_topics.product_id`, `topic_id`, `position` | FKs; unique product/topic and product/position | Ordered current selection: 0–3 on a draft, 1–3 while submitted. |
| `product_topics.selected_label` | Non-null trimmed text, 1–40 characters | Founder-supplied spelling for this association; owner/staff reads use it, and other founders never receive it. |

**Relationships:** Many-to-many products/topics. A supplied selection replaces all current associations and their selected labels in request order; omission leaves them unchanged. Two founders may link the same topic ID with different selected labels. Owner reads may show their own selected proposals; general choices list contains only launched topics, so typing an already-private name may reuse its row without disclosing another product or its original casing. Unreferenced private topics can be cleaned without making them visible. (R7–R8, N1)

### ProductAsset

**Purpose:** Owner-scoped upload intent, validation result, and current logo/screenshot reference.

| Field | Type / Constraint | Notes |
|---|---|---|
| `id`, `product_id`, `kind` | UUIDs, product FK, `logo` or `screenshot` | Object keys include owner/product/asset identifiers under product-only prefixes. |
| `state` | `pending`, `clean`, `failed`, or `detached` | Only validated clean, attached assets satisfy submission requirements. |
| `staging_key`, `clean_key` | private unique keys | Never returned as public object URLs. |
| `media_type`, `byte_count` | allowed image type; `1..5242880` bytes | Actual bytes are decoded/re-encoded before clean state. |
| `position`, `expires_at`, `attached_at` | nullable position/timestamps | One attached logo and at most ten ordered attached screenshots; bounded pending uploads expire. |

**Relationships:** Many assets per product, but current attached set has at most one logo and ten screenshots, enforced by service transaction plus database indexes/constraints where row-local. Detached, expired, failed, and deleted-product keys are purged via outbox events.

**Lifecycle:** Signed pending upload → validated clean object → attach through versioned product edit → detach/purge on replacement or deletion. Product row locks serialize completion against deletion; a late signed POST after deletion is covered by a delayed purge after its expiry. (R4, R6, R17, N1, N3–N4)

## API Contracts / Interfaces

### Founder and staff REST commands

**Boundary:** Pydantic-backed REST under `/api/v1`, with existing exact trusted-origin and CSRF checks for browser mutations. All paths use cookie sessions and safe typed service errors.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| `POST` | `/me/products` | Create private draft if founder has room. | `201` product ID/version; `401/403`, quota `409`, throttle `429`, dependency `503`. |
| `PATCH` | `/me/products/{id}` with `version` and changed fields/asset IDs/optional `topic_names` | Auto-save supplied valid draft fields or a complete pending version. Omitted topics remain unchanged; supplied topics replace the ordered selection. | `200` current version/state; stale `409`; field `422`; forbidden/hidden `403/404`. |
| `POST` | `/me/products/{id}/submit` with expected version | Submit latest saved complete draft; repeated request for an already-pending product returns its one current period. | `200` submission ID/version; stale/limit `409`, incomplete `422`, unverified/suspended `403`. |
| `POST` | `/me/products/{id}/withdraw` with submission ID and expected version | Close active period and return to private draft; bypass draft cap and suspension block. | `200` draft version; stale or changed state `409`, hidden `404`. |
| `DELETE` | `/me/products/{id}` with expected version | After UI confirmation, storage availability preflight then hard-delete draft/associations with purge event. | `204` inaccessible immediately; `409` stale/not draft; `503` precommit storage outage leaves draft. |
| `POST` | `/me/products/{id}/assets` with kind, type, size | Issue one short-lived, bounded signed POST and persist intent. | `201` URL/fields/expiry/asset ID; `422/429/503`. |
| `POST` | `/me/products/{id}/assets/{asset_id}/complete` | Validate actual bytes and privately promote. | `200` clean asset ID/type/size; `409/422/503`. |
| `PUT` | `/me/products/{id}/assets` with `{version, logo_asset_id, screenshot_asset_ids}` | Atomically replace a draft's complete media selection; `logo_asset_id` is nullable to clear it and screenshot IDs are ordered. Only clean assets belonging to this draft with the matching kind may be attached. | `200` current product ID/status/new version; stale or invalid selection `409`, hidden/forbidden `404/403`, throttle `429`, dependency failure `503`. |
| `GET` | `/products/{id}/assets/{asset_id}` with short-lived app signature | Recheck session, owner or pending-staff policy, asset attachment, and product state before streaming. | `200` private image, `404` hidden/unavailable, `503` storage fault; `no-store`. |

**Auth requirements:** Signed-in owner may create/read/edit a draft before verification; verified unsuspended owner is required for submission. Suspended owner may withdraw, but not create/edit/upload/submit/delete. Reviewer/admin staff must be verified and unsuspended to see pending products; they never acquire access to private drafts merely by role. Product policies run in routes and again in services. No product mutation is available through GraphQL. (R1, R9, R11, R14, R17, N1–N2)

**Topic-save contract:** `topic_names` is an optional full replacement, not an incremental add/remove operation. Only an absent field means unchanged; explicit `null` is invalid. A supplied empty list clears a draft's selection; a submitted product must retain 1–3 valid, distinct normalized topics. Rejected or stale saves leave the associations, product version, pending submission version, queue timestamp, and outbox unchanged. Successful pending saves keep the existing submission period and its `submitted_at`. (R7–R8, R11, N1–N3)

**Asset-attachment contract:** `PUT /me/products/{id}/assets` is a full replacement on a private draft, not an incremental attach/detach command. Its body requires the current `version`, a nullable `logo_asset_id`, and an ordered `screenshot_asset_ids` list of at most ten UUIDs; the response returns `ProductStateResponse` with the incremented version. It reuses `ProductService.attach_assets`, which locks and versions the product, checks ownership/draft state and clean asset kind, and schedules purge for detached media in the same transaction. The browser completes upload validation before attachment, flushes autosave before replacement, adopts only the returned version, and retains local edits on a `409`; media on a pending submission is read-only until the founder withdraws it back to draft. (R3, R6, R9, R11, N1–N3)

### Composed GraphQL reads

**Boundary:** Existing POST-only `/api/v1/graphql`, still one bounded query operation without mutations or introspection; owner/staff data is `no-store`.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| Query | `viewerProducts(first, after)` | Cursor-page the founder's own drafts and pending items. | Product summaries and current versions; auth required. |
| Query | `viewerProduct(id)` | Owner's private editor snapshot, ordered selected topics with the founder's own labels, validated assets, and current submission ID. | Own product or hidden/not found. |
| Query | `reviewQueue(first, after)` | Oldest-first pending entries with current versions, duplicate flag, and live suspended-founder flag. | Staff only; bounded keyset page. |
| Query | `reviewProduct(id)` | Current complete pending content/media plus submission ID/version for later stale-decision checks. | Staff only; withdrawn entries disappear. |
| Query | `topicChoices(query, first)` | Launched topics and caller's own selected proposals only; selected proposals use the association label and duplicate topic IDs are collapsed. | No other founder's private proposals or canonical private casing; bounded prefix search. |

Existing `viewerProfile` and `publicProfile` fields and contracts remain unchanged. Image fields contain short-lived app-signed API URLs bound to the current session, not S3 object URLs. Query-root allowlisting and depth/size bounds are updated for the new fields; the service rechecks authorization inside the resolver transaction rather than trusting a stale context snapshot. (R1, R7–R8, R12–R15, N1–N2)

### Named module and event interfaces

**Boundary:** Internal service protocols and encrypted outbox events, not cross-feature repository imports.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| Auth access | `current_account(session, account_id, lock=False)` | Live verified/role/suspension state; lock on quota-changing commands. | Auth-owned account summary or absent. |
| Auth access | `founder_states(session, account_ids)` | Batch suspended flags for staff queue, avoiding N+1 queries. | ID-keyed summaries. |
| Product service | `save_draft` / `save_pending` with actor, expected version, changed content, and optional `topic_names` | Validate/normalize a supplied ordered selection; preserve it when omitted. A draft accepts 0–3; a pending item requires 1–3 after the edit. | Current aggregate/read model or typed validation/conflict error. |
| Product repository | `replace_product_topics(session, product_id, selections)` | Replace ordered `ProductTopic` associations and their founder-selected labels in the caller's transaction, using topic IDs resolved through the existing unique-key upsert. | No independent commit or event. |
| Product read service | `owner_list/detail`, `staff_queue/detail`, `topic_choices` | Policy-enforced read projections. | Private typed read models only. |
| Events | `product.created.v1`, `product.saved.v1`, `product.submitted.v1`, `product.withdrawn.v1`, `product.deleted.v1`, `product.asset_changed.v1`, `product.media_purge.v1` | Durable state notifications, upload-state changes, and cleanup work; encrypted minimal IDs/versions/keys. | Typed handler; no product event reaches email sender. |

The product service writes events with the state transaction. For a topic-changing save, topic upserts, association and selected-label replacement, product version, pending-period version (when applicable), and one `product.saved.v1` event commit or roll back together. Existing save callers that omit `topic_names` retain their behavior. The read repository returns owner labels from `product_topics.selected_label`; canonical `topics.display_name` is reserved for launched general choices. Media-purge handlers check that a key is no longer referenced, tolerate already-missing objects, retry transient S3 failures, and surface persistent failures for replay. The scheduler's existing due-work hint can remain generic; PostgreSQL is the durable queue. (R7–R8, R11, R17, N1, N3)

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|---|---|---|
| `app.modules.products` | Product state, topics, media metadata, submission periods, owner/staff policies and projections | Shared DB/storage/events/security plus named auth access service; never auth/users repositories. |
| `app.modules.auth` | Account/session truth, role/suspension policies, audited operator mutations | Its own repository and shared DB/events; no products repository. |
| `app.modules.users` | Profile behavior and profile GraphQL fields | Existing dependencies; no product data access. |
| `app.graphql` | Compose product and profile fields, shared context, bounded query validation | Named module read services; no domain decisions. |
| `app.shared.storage` | Private object operations, media validation, scoped key handling, storage policy | S3 client only; no auth or product persistence decision. |
| `app.shared.events` + worker | Claim, route, complete, retry, and dead-letter typed outbox events | Typed handlers and shared adapters; email and product effects stay separate. |
| `apps/web/src/products` | Founder editor and staff queue with generated API types | Identity client/session, TanStack Query, generated contracts; no hand-maintained schema types. |

## Change Footprint

_Concrete brownfield map. Paths are design targets, not an implementation order._

### New files / modules

| Path | Purpose | Pattern reference |
|---|---|---|
| `apps/api/app/modules/products/{models,repository,service,schemas,policies,routes,graphql}.py` | Product-owned state, transport, and reads. | `app/modules/users/*` and `app/modules/auth/policies.py`. |
| `apps/api/app/modules/products/tests/*` | Product service, policy, transport, concurrency, privacy, and storage coverage. | `app/modules/users/tests/*`. |
| `apps/api/app/modules/auth/staff.py`, `scripts/operators/manage_accounts.py` | Named auth access/operator changes and audited staff/suspension provisioning. | `app/modules/auth/service.py`; new restricted CLI surface. |
| `apps/api/app/graphql.py` | One composed profile/product schema, request context, and bounded read-query validator. | Existing `app/modules/users/graphql.py` and GraphQL context in users routes. |
| `apps/api/alembic/versions/0005_product_drafts_submission.py` | Original additive auth/product schema revision, implemented before the selected-label extension; do not rewrite it. | Prior `0004_profile_link_query` revision. |
| `apps/api/alembic/versions/0006_product_topic_selected_labels.py` | Forward-only additive association-label column; backfill existing rows from normalized `topics.name_key`, then require a trimmed, nonblank label of at most 40 characters. Do not rewrite `0005`. | Current `0005_product_drafts_submission.py` head and `product_topics` constraints. |
| `apps/api/app/modules/products/tests/{test_reads,test_queue}.py` | Owner/staff privacy, ordered cursor paging, live flags, and selected-label projection checks. | Existing product service/repository tests. |
| `apps/web/src/products/{client,useProducts}.ts`, `apps/web/src/products/ProductScreens.tsx`, and related test files | Typed REST/GraphQL clients, autosave state, private editor, staff queue, alerts, accessible mobile UI. | `apps/web/src/profiles/*`. |

### Modified files / modules

| Path | What changes here |
|---|---|
| `apps/api/app/main.py` | Conditionally wire product REST and composed GraphQL fields under the product feature flag; retain profile-only reads when disabled. |
| `apps/api/app/modules/auth/{models,repository,sessions,policies,schemas,routes}.py` | Persist/expose live role and suspension, provide named access/locks, and return role/suspension in self-session contracts without changing public auth flows. |
| `apps/api/app/modules/products/models.py` | Map `ProductTopic.selected_label` as a required association value; retain existing topic identity and ordering constraints. |
| `apps/api/app/modules/products/{service,repository}.py` | Persist each founder's selected label with versioned topic replacements and provide owner/staff read projections that never use another founder's private canonical casing. |
| `apps/api/app/modules/products/policies.py` | Add the named verified, unsuspended reviewer/admin read policy while preserving owner-only draft access. |
| `apps/api/app/modules/products/{schemas,routes}.py`, `apps/api/app/modules/products/tests/{test_topics,test_routes,test_assets}.py`, `tests/integration/test_product_api.py` | Expose and verify versioned content/topic commands and the draft-only full asset-attachment replacement; reuse the existing product service operation and safe transport policies. |
| `apps/api/app/modules/products/tests/test_topics.py`, `tests/integration/test_product_schema.py` | Verify new association labels, legacy backfill, database constraints, and no cross-founder casing exposure. |
| `apps/api/app/modules/users/{graphql,routes}.py` | Export profile fields to the schema composer and move GraphQL context ownership; retain profile REST behavior and field shapes. |
| `apps/api/app/shared/storage/{objects,provision}.py` | Generalize image primitives or add product-scoped adapter; allow only product staging/clean prefixes and preserve profile prefix guards/CORS. |
| `apps/api/app/shared/events/{outbox,dispatcher}.py`, `apps/worker/worker.py` | Dispatch by event type; add non-email completion and idempotent product purge handling. |
| `apps/api/app/shared/config/settings.py`, `compose.yaml`, `compose.checks.yaml` | Add disabled-by-default product gate; explicitly enable local/check runs and keep production activation separate from binary deployment. |
| `apps/web/src/{App.tsx,styles.css}` | Route to founder/staff product views and add responsive, accessible UI styling. |
| `apps/web/src/identity/{client.ts,Screens.tsx}` | Surface current role/suspension, hydrate session/CSRF on product deep links, and navigate to permitted product views. |
| `scripts/quality/contracts.sh`, `packages/contracts/{operations.graphql,schema.graphql,openapi.json,src/generated.ts,src/graphql.generated.ts}` | Generate the composed GraphQL schema and typed operations plus REST/session OpenAPI contracts, including the versioned asset-attachment command. Generated outputs are not hand-edited. |
| `apps/web/src/products/{client,useProducts}.ts` and related tests | Send the generated attachment request and synchronize its acknowledged product version with serialized autosave state. |
| `docs/development.md` | Document product boundary, private media lifecycle, operator provisioning, and rollout/operations without changing the source briefs. |

### Deleted / replaced

| Path | Reason |
|---|---|
| None | Existing public/profile behavior stays in place; only the users-only GraphQL router construction is replaced by composition. |

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|---|---|
| `apps/api/app/modules/auth/tests/*`, `apps/api/app/modules/users/tests/*` | Existing registration, session, profile, and public-photo behavior depends on modified auth and GraphQL seams. |
| `apps/web/src/profiles/*`, `apps/web/src/identity/*.test.ts*` | Existing profile queries and CSRF/session navigation must still work after route/schema/session expansion. |
| `apps/api/app/shared/db/database.py`, `apps/api/alembic/env.py` | Schema readiness already resolves current migration head dynamically; no hard-coded revision change is needed. |
| `apps/worker/scheduler.py` | It hints all due outbox rows generically; event-specific behavior belongs in the worker. |
| `apps/api/app/modules/health/*` | Existing readiness must still reflect exact schema compatibility; do not relax it to mask a wrong binary/schema pair. |

## Areas of Impact

| Area | Impact | Risk (L/M/H) | Why |
|---|---|---|---|
| Auth/session and operator access | New role/suspension truth and staff policies. | H | Incorrect defaults, stale authorization, or unaudited privilege changes would expose private work. |
| Product transactions and queue | New aggregate, optimistic locking, ordered topic and selected-label replacement, submission periods, and quotas. | H | Concurrent edits/requests can create lost work, mismatched topic/version/label state, or duplicate queue entries unless locks and constraints agree. |
| Product REST and generated contracts | Add a versioned full asset-selection replacement over the existing service operation. | M | A stale version or weak transport validation could detach the wrong media or admit an unattached/unvalidated asset; reuse service invariants and generate the contract from OpenAPI. |
| Private media/storage | New key prefixes, gated downloads, deferred purge. | H | A stale signed URL, missing key guard, or purge gap can leak or retain unlaunched media. |
| Shared GraphQL/profile reads | One composed schema/context replaces users-only builder. | H | Existing profile reads or query bounds can regress; private product fields must never appear publicly. |
| Outbox/worker and rollout | Email dispatcher becomes typed and handles storage cleanup. | H | Old workers would misroute new events; silent dead letters could retain deleted media. |
| Web editor/staff queue | New autosave/upload/queue UI and session hydration. | M | Offline saves, stale versions, and inaccessible status feedback can mislead founders. |
| Database/contract pipeline and release gate | Additive `0006` association-label migration, generated contracts, and explicit activation flag. | H | Legacy rows need a privacy-safe backfill; exact migration-head readiness rejects an old binary after schema upgrade, so API/worker images must be `0006`-compatible. |

**Contract changes:** Self login/session responses add role/suspension fields; `/api/v1/graphql` keeps profile fields and adds private product/queue fields; product REST paths and generated OpenAPI types include the versioned full asset-selection replacement. Existing profile response and image routes are unchanged. Product events are new internal versioned contracts, never interpreted as email payloads.

**Cross-cutting ripples:** Auth policy, operator audit, private-bucket policy, migration head (`0006` after existing `0005`), worker event routing, telemetry, rate limits, feature-gated route/schema registration, contract generation, browser deep links, and deployment ordering all change. No Redis authority, search indexing, public product page, or new service is introduced.

## Cross-Cutting Concerns

- **Errors:** Services raise typed validation, conflict, forbidden, quota, and infrastructure errors. REST maps them to field-specific `422`, stale/state/quota `409`, rate `429`, safe `401/403`, indistinguishable hidden-resource `404`, and retryable `503`; GraphQL hides unauthorized private identity/details. Auto-save keeps local edits on failure, retries network failures only, and pauses for explicit resolution on `409`. A pending incomplete edit, including an invalid or empty topic replacement, is rejected without changing its topics or saved version; attachment conflicts likewise retain local selection and require a current-version refresh before retry. (R2–R4, R7, R11, N1–N2)
- **Logging & metrics:** Log action type, product/submission/event IDs, latency, state, and error class; never log content, topics, private URLs, image bytes, tokens, or object keys. Count autosave failures/conflicts, upload validation failures, queue age/depth, duplicate flags, purge retries/dead letters, and unauthorized attempts; alert on stuck purges. (N1, N4)
- **Auth / authz:** Resolve account state from PostgreSQL per request and recheck it in product services/resolvers. Role alone does not grant draft access; only owner sees drafts and only verified, unsuspended reviewer/admin sees pending queue. Mutations retain exact browser Origin + CSRF checks; operator CLI has no browser route. Withdrawal is the suspension exception; deletion is not. (R1, R9, R14, N1–N2)
- **Performance:** Lock one founder account on quota-changing commands before counting; use product row lock/version for saves and attachment replacement; keyset-page owner lists and staff queue with partial indexes, bounded `first`, batched staff flags, and indexed website-key duplicate existence checks. Ordered selected labels load through the existing `(product_id, position)` index, without per-item topic lookups. Debounce and serialize browser autosaves; cap asset intents and rate-limit mutating actions. Detached/unattached objects remain bounded by existing delayed purge work. Redis outage does not weaken authoritative quotas; withdrawal remains available. (R2–R3, R13, R15–R16, N4)
- **Security:** Validate HTTPS URLs and supplied text on API and database row-local constraints; perform byte-level image decoding/re-encoding with metadata stripping, size/type checks, scoped key validation, and private bucket ACL. App-signed media URLs use an HMAC over path and short expiry keyed by the opaque current session secret; every GET also rechecks database authorization and current attachment, so revocation does not depend on URL expiry. Responses are `no-store`, `nosniff`. Staging POST expiry is bounded and cannot grant reads. Proposed topics and other founders' selected labels are excluded from all public and unauthorized read surfaces; typing a matching private name never returns another founder's canonical casing or associations. (R4–R8, R17, N1)
- **Migrations / rollout:** Keep shared revision `0005` unchanged and add forward revision `0006` for `product_topics.selected_label`. Add it nullable, backfill legacy associations from the normalized `topics.name_key` (not the first founder's private `display_name`), then enforce non-null, trimmed 1–40-character values. This deliberately cannot restore pre-`0006` founder-specific casing; all new selections preserve their own label. Extend storage runtime policy for product-only prefixes. In a controlled cutover from the existing `0005` schema, drain older binaries, prepare to `0006`, then start `0006`-compatible typed worker and API with `LAUNCHPAD_PRODUCTS_ENABLED=false`; verify worker health/event routing before enabling the same API build. Check/local Compose explicitly enable the feature for contract generation and checks. Exact packaged-head readiness means an old `0005` image cannot restart after migration; roll back the feature with a `0006`-compatible disabled build, not a schema downgrade or old worker. (R7–R8, N1–N3)
- **Deletion atomicity:** Before commit, verify storage availability; if it is unavailable, return `503` and retain the draft. On success, hard-delete product metadata and persist encrypted purge work in the same PostgreSQL transaction; app-gated media access stops immediately. Physical deletion may finish later, with delayed cleanup after outstanding upload URLs expire. A postcommit outage retries/alerts rather than resurrecting the draft; this is the explicitly approved cross-system compromise. (R17, N1, N3)

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|---|---|---|---|
| A1 | New products module, separate from auth/users, with named auth interface. | Put products in users or import auth repository. | Preserves feature ownership and testable authorization boundary. | R1, R9, R14, N2 |
| A2 | Add live account role/suspension and audited operator-only management; suspended owners may withdraw only. | Environment staff list; public promotion; block withdrawal. | Current, reviewable staff access without trapping a suspended founder. | R9, R14, N2 |
| A3 | Product version plus explicit submission-period rows and partial unique pending index. | Product timestamp only; client-side queue dedupe. | Prevents stale overwrite/decision and preserves fair queue history. | R3, R10–R13, N2–N3 |
| A4 | Serialize founder quota changes via auth-owned account lock and enforce product invariants in PostgreSQL. | Redis quota counters; eventual reconciliation. | Holds limits under concurrent requests and keeps one authority. | R10, R16, N3–N4 |
| A5 | Canonical unique topic key, private proposal visibility, exact canonical website key for staff-only duplicate flag. | Per-product topics; public proposals; unique website. | Reuses equivalent topics without leaking private associations or rejecting legitimate products. | R7–R8, R15, N1 |
| A6 | One composed read-only GraphQL endpoint plus REST commands. | Second GraphQL endpoint; GraphQL mutations; all REST reads. | Follows existing read/command split while preserving profile consumers. | R1–R2, R14, N1 |
| A7 | Signed private staging uploads and app-signed, authorization-rechecked downloads. | Public media; direct S3 GET presigns. | Deletion/access changes take effect immediately for downloads despite S3's URL revocation limits. | R6, R17, N1 |
| A8 | DB hard deletion with preflight and durable typed outbox purge, including delayed sweep. | Synchronous multi-object delete; claim physical atomicity across PG/S3. | Gives immediate inaccessibility, retryable physical purge, and truthful precommit failure. | R17, N1, N3 |
| A9 | Typed outbox dispatch, worker-first rollout, no scheduler rewrite. | Reuse email-only dispatcher; Redis-only job. | Prevents sending product payloads as email and preserves durable retries/rollback safety. | R17, N3 |
| A10 | Gate product routes/schema fields in the current schema-compatible API; production default off. | Enable immediately; roll back to an older migration-head image. | Exact migration-head readiness makes old-image rollback unsafe; the gate permits worker verification before event production and a safe feature rollback. | N1, N3 |
| A11 | Save an optional full ordered topic replacement through the existing versioned draft/pending command and product repository. | A separate topic route; transport-owned association writes; incremental add/remove commands. | One aggregate lock/version and transaction keep topic links, pending-period version, and outbox consistent; omission preserves existing callers. | R7–R8, R11, N1–N3 |
| A12 | Store each founder's selected topic label on `ProductTopic` in additive revision `0006`; backfill legacy rows from normalized topic key. | Reuse shared `Topic.display_name`; show only lowercased keys forever; rewrite `0005`. | New owner reads retain exact approved spelling without leaking the first founder's private casing, while a privacy-safe backfill and forward revision preserve applied-migration history. | R7–R8, N1, N3 |
| A13 | Expose asset selection as a versioned full-replacement `PUT` that reuses `ProductService.attach_assets`, returning the new product version; keep replacement draft-only and serialize it with browser autosave. | Attach each upload on completion; add GraphQL mutation; use incremental detach/attach calls; permit attachment changes on a pending submission. | Upload validation stays distinct from attachment, one product lock/transaction preserves ordering and cleanup, stale selections cannot overwrite a newer draft, and pending edits remain complete without altering media. | R3, R6, R9, R11, N1–N3 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|---|---|
| API/network unavailable for 30 seconds during autosave or submission. | Browser retains unsaved values, announces “Not saved,” serializes/retries autosave on reconnection, and does not submit until the latest save returns a version. A timeout retry of an already-submitted product returns its one current pending period. |
| Two tabs save the same draft, or edit/withdraw races a future reviewer decision. | Product row/version and submission ID serialize changes; stale mutation gets `409` and keeps local values. Future decision must compare current submission ID/version and status in its transaction. |
| Two requests create the eleventh draft or fourth pending item; two founders propose equivalent topics. | Founder account lock serializes quota checks; partial unique index bars duplicate pending periods; topic key unique/upsert resolves naming race. |
| A pending edit clears topics, a stale save changes topics, or a topic/event write fails midway. | Validate the resulting 1–3 topics before mutation; product row/version serializes saves; one transaction rolls back topic rows/associations, product and pending versions, and outbox together. The pending queue timestamp does not move on a valid edit. |
| Two founders select differently capitalized names that resolve to one still-private topic. | Each association stores its own selected label; owner and permitted staff projections read that label, while general choices omit the unlaunched topic and no read exposes another association or the shared private display name. |
| `0006` runs over existing `0005` topic associations, or an older image is restarted after migration. | Backfill from bounded normalized `name_key`, not the original private canonical casing; enforce the new association constraint only after backfill. Exact-head readiness refuses the older image; use a `0006`-compatible disabled build for rollback. |
| Storage is unavailable before deletion, fails after commit, or receives a signed POST after deletion. | Preflight failure leaves draft; postcommit purge retries with alert/dead-letter replay; app-gated GET returns hidden immediately; delayed purge after POST expiry removes late staging keys. |
| S3 upload fails halfway or validated media promotion succeeds while DB transaction fails. | Asset remains non-attached/non-submittable; expired/unattached keys are scheduled for cleanup. Submitted state and all references are committed together or not at all. |
| A clean upload completes while another tab saves, or attachment replacement races a draft deletion. | Product row lock and expected version serialize the attachment with saves/deletion; one action wins, the other returns a safe conflict/not-found result. The UI retains its selected IDs and reloads the current version before retrying; unattached clean objects remain inaccessible and are removed by delayed purge. |
| Asset replacement is retried after a timeout or selects a stale/foreign/unvalidated asset. | Full replacement with the current version is idempotent after a successful retry; service ownership, clean-state, kind, and draft checks reject invalid IDs without changing attachments or version. |
| API contract deploys before or after the web editor, or OpenAPI generation fails. | The additive PUT leaves existing POST upload routes unchanged; deployable API can accept the command before the UI uses it. Contract check fails the quality gate if generated request/response types drift, and no migration is required. |
| Queue grows from 10K to 10M periods. | Partial pending index and `(submitted_at,id)` cursor pagination avoid full scans/offset drift; staff flags and duplicate checks are batched/indexed. Historical periods remain off the active queue index. |
| Redis is unavailable or worker restarts mid-purge. | PostgreSQL constraints still enforce quotas and privacy; rate-limited nonessential mutations fail safely, withdrawal remains possible, and claimed outbox work is retried idempotently. |
| Product activation fails or a rollback is needed after writing product events. | Disable the feature in the `0006`-compatible API while keeping the typed worker until events drain. Do not restart an older `0005` image, which fails exact-head readiness, or put an email-only dispatcher in front of product events. |

### Backward — regression risk per touched area (brownfield only)

| Touched area (from Change Footprint) | What could regress | How we'd know / mitigation |
|---|---|---|
| Auth models/sessions/routes and identity client | Registration defaults, login/session response, verification, recovery, CSRF hydration, or active sessions. | Additive defaults, live authorization fields, existing auth/identity regression suite, and no change to password/session semantics. |
| Users GraphQL/routes and composed schema | Existing profile fields, query guard, private-profile visibility, or image route. | Preserve exact profile field signatures, rerun profile GraphQL/route and generated-contract checks; leave profile REST/media rules intact. |
| Storage object adapter/provisioning | Profile prefix guards, MIME validation, local browser upload CORS, or least-privilege runtime policy. | Product-specific prefix guard/policy additions, existing storage tests, and private-object checks across both prefix families. |
| Outbox dispatcher/worker/scheduler | Verification/reset email misdelivery, duplicate mail, dropped jobs, or worker readiness. | Exhaustive event-type routing, retain email delivery idempotence, leave scheduler generic, and monitor unknown/dead events. |
| Migration head/database readiness and Compose settings | API/worker startup against wrong schema, legacy-label backfill, accidentally enabled producers, or unsafe old-image rollback. | Forward `0006` migration with normalized-key backfill, disabled production default, check/local explicit enablement, exact-head readiness, and rollback through a compatible disabled build only. |
| Product topic save/read callers | Label writes omit the founder's spelling or private read projections expose canonical casing; legacy associations lack a label. | Store selected label in the same versioned transaction; owner/staff projections use the association label, migrate old rows from normalized keys, and run save/privacy regression checks. |
| Contracts and frontend routing | Profile query type drift, deep-link session/CSRF failures, or unrelated `/profile` routes. | Generated contract checks plus existing App/profile/identity UI regressions; product route matching is narrow. |
| Existing product save callers | Omitted topic input accidentally clears associations or alters autosave semantics. | Optional service/REST field means “unchanged” when absent; exercise prior save tests and explicit omission/replacement integration cases. |
| Existing compose/check images | New media prefix or worker behavior absent in deployed image. | Build/run current separate API/worker/scheduler checks; no new service or secret requirement. |

## Open Questions

- None for this slice. The future review-decision workflow must use the recorded submission ID and version; the future launch workflow must explicitly set topic public eligibility rather than inferring it from submission.

## Out of Scope

- Reviewer approval, rejection, change requests, and outcome notices (reason: later review-workflow slice).
- Scheduling, launch/public product pages, public topic discovery, and search indexing (reason: later launch/discovery slices; no unpublished data may leak in the meantime).
- Votes, comments, rankings, follows, jobs, payments, and additional identity settings (reason: separate slices).

## Post-review hardening addendum (2026-10-02)

The original rollout design above records the approved T1–T20 migration head of `0006`. Review
hardening adds forward-only migration `0007_product_submission_idx`, a full index on
`product_submissions.product_id` for history lookup and product-cascade performance. It does not
change the feature boundaries or revise `0005`/`0006`. The current operational schema head is now
`0007`; exact-head readiness and rollback therefore require matching `0007`-compatible API and
worker binaries, with `LAUNCHPAD_PRODUCTS_ENABLED=false` during rollout/rollback as documented in
`docs/development.md`.
