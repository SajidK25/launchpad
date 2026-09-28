# Architecture: Add Member Identity and Profiles

> **Date:** 2026-09-22
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** specs/requirements/REQ-add-member-identity-profiles.md
> **Tasks:** TASKS-add-member-identity-profiles.md
> **Type:** feature

## Architecture Summary

Add separate `auth` and `users` feature modules to the existing FastAPI monolith. PostgreSQL owns accounts, revocable sessions, one-use email challenges, profile visibility, and a transactional email outbox; Redis is used only for rate limiting and Dramatiq dispatch. REST handles account and profile actions, Strawberry GraphQL composes private-owner and public-profile reads, and the React client uses generated contracts. Photos remain in private S3-compatible storage: signed staging uploads are validated before use, and every image read passes a current-visibility check through the API. The existing preparation, readiness, worker/scheduler health, connectivity page, and isolated quality environment remain operational as they gain this feature.

## High-Level Structure

```text
Browser (same-origin web app)
  | REST actions + GraphQL reads + gated photo GET
  v
FastAPI assembly
  |-- auth: accounts, sessions, verification, recovery, policies
  |-- users: draft/public profiles, links, photo lifecycle
  |-- shared: async DB, private objects, outbox, SMTP, logging
  |        |
  |        +-- PostgreSQL: authoritative state + outbox
  |        +-- MinIO: private staging and cleaned profile photos
  |        +-- Redis: limits and Dramatiq messages only
  v
Scheduler: enqueue due outbox IDs and expire staging work
  v
Worker: claim outbox ID, send email through Mailpit/SMTP, record outcome
```

A registration transaction creates an unverified account and private profile, stores a verification challenge digest, and inserts an encrypted email event. The public response is the same for an existing address; that branch never changes the account. Sign-in creates an opaque session; a reset locks the account, changes its Argon2id hash, revokes every session, consumes the challenge, and inserts a change notice atomically. Profile edits lock the profile, save the requested fields, recompute publication eligibility, and enqueue a privacy notice in the same transaction if a published profile becomes private. GraphQL and photo reads evaluate current database visibility, never a Redis or browser-stored visibility flag.

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|------|----------|-------------------------|-----------|
| Feature shape | Separate `auth` and `users` modules with named service interfaces | One combined identity module; cross-module repository imports | Each feature owns its rules and persistence; later voting can consume a verified-member service without depending on profile storage (R3–R11). |
| Authority | PostgreSQL constraints, row locks, and transactions; forward Alembic revision | Redis authority; application-only uniqueness | Provides atomic uniqueness, single-use links, session revocation, and profile visibility under concurrency (R1, R4, R7, R11, N3). |
| Sessions | Random opaque IDs represented by digests in PostgreSQL; HTTP-only, Secure, SameSite cookies | Stateless JWT sessions | Immediate sign-out and all-device reset revocation are direct and auditable (R3, R7, N1). |
| Passwords | Argon2id plus versioned local compromised-password blocklist; NFC normalization and generous bounded input | Fast hash; composition rules; network-only breach lookup | Protects stored credentials and keeps local registration/reset independent of an external lookup (R8, N1–N2). |
| Challenge links | 32 cryptographically random bytes, stored as digests; one active generation per account and purpose | Reusable links; self-contained bearer JWTs | Single use, 60-minute expiry, and newest-link semantics are enforceable in one transaction (R4–R7, N3). |
| Email | Encrypted transactional outbox, Dramatiq dispatch, SMTP delivery | Direct request-time send; Redis-only queue | Mail outage cannot roll back profile privacy or lose a committed notice; raw links are not stored as readable text (R5–R7, R12, N1–N3). |
| Rate limits | Independent account/address and source buckets in Redis; temporary cooldown; fail closed for sensitive actions when unavailable | One combined bucket; permanent account lockout | Resists distributed guessing and address-targeted flooding without making a hostile request permanently deny account access (N2). |
| Photo handling | Signed private staging upload, server validation/re-encoding, gated API read with `no-store` | Public bucket or long-lived direct download URL | Validates actual content and allows immediate withdrawal of public access (R9–R11, N1). |
| API | Versioned REST for actions and image delivery; Strawberry GraphQL for profile composition | REST-only reads; GraphQL mutations | Matches the approved transport split and lets generated frontend types cover both contracts (R3–R11, N4). |
| Local cookie behavior | Keep `Secure` cookies; use the same-origin `localhost` web entry for Linux browser checks, require HTTPS outside local loopback | Disable `Secure` in development | Preserves the required cookie attribute while using the browser's localhost exception locally; production hosts must use HTTPS (N1). |

## Patterns & Conventions

- **Feature ownership** — `auth` owns account, session, challenge, and authorization rules; `users` owns profile, links, and photo-state rules. A feature calls another through a named service interface, never its repository.
- **Thin transports** — REST routes and GraphQL resolvers validate/authorize transport inputs, call typed services, and map typed domain errors to safe responses. They do not return ORM instances.
- **PostgreSQL authority** — unique canonical email and token/session digests use indexes; account/session and profile transitions use transactions and row locks. Redis cannot be the only record of identity or notification state.
- **Transactional outbox** — email events are committed with the user-visible change. Outbox payloads use authenticated encryption with a versioned key identifier; only the worker decrypts them, and payload ciphertext is removed after completion. SMTP delivery is at least once, with stable message IDs and delivery records; an ambiguous SMTP acknowledgement can cause a duplicate email, never a duplicate account/profile transition.
- **Private objects** — the existing bootstrap identity stays separate from the runtime identity. Runtime object permission is restricted to profile staging and cleaned-photo prefixes; neither grants anonymous bucket access. Browser upload signatures are short lived and limited to one staging object and size range. The API never exposes private object keys in GraphQL.
- **Generated contracts** — OpenAPI and GraphQL schema/type artifacts are generated and checked for drift, following the existing REST contract pipeline. No hand-maintained duplicate frontend response interfaces.
- **Foundation preservation** — extend `create_app` composition without breaking health-only test injection, keep the readiness deadline and independent worker/scheduler health, and keep the connectivity route available.

## Data Models

### Account (`auth.accounts`)

**Purpose:** One member identity and its verification/credential state.

| Field | Type / Constraint | Notes |
|-------|-------------------|-------|
| `id` | UUIDv7 primary key | Stable opaque identity for later feature references. |
| `email_display` | validated text, required | Preserved address for delivery/display; never public by default. |
| `email_key` | normalized text, unique, required | NFC/case-insensitive comparison for the entire address, with IDNA domain handling and no provider-specific dot/plus rewriting. |
| `password_hash` | Argon2id encoded hash, required | No plaintext or reversible password storage. |
| `verified_at` | UTC timestamp, nullable | Sole verified-email eligibility signal. |
| `session_epoch` | integer, required | Incremented on reset to invalidate sessions atomically. |
| `created_at`, `updated_at` | UTC timestamps | Operational history. |

**Relationships:** one account has one profile and many sessions/challenges; profile has an account foreign key. No staff/suspension state is introduced in this slice.

**Lifecycle:** registration creates unverified account → valid link sets `verified_at` once; password reset changes the hash and epoch but never verification state. There is no account deletion flow here.

### Session (`auth.sessions`)

**Purpose:** Revocable browser authentication.

| Field | Type / Constraint | Notes |
|-------|-------------------|-------|
| `id`, `account_id` | UUIDv7 primary key; indexed FK | Owner and audit identity. |
| `secret_digest` | unique fixed-length digest | Only a 32-byte random bearer secret reaches the cookie. |
| `session_epoch` | integer, required | Must match account epoch on every authorization check. |
| `created_at`, `last_seen_at`, `idle_expires_at`, `absolute_expires_at` | UTC timestamps | 24-hour idle, seven-day absolute maximum; activity updates may be coalesced. |
| `revoked_at` | UTC timestamp, nullable | Sign-out or reset revocation. |

**Relationships:** many sessions per account, with lookup by digest and account FK.

**Lifecycle:** successful sign-in creates a fresh ID → activity may extend idle expiry within the absolute limit → sign-out, reset, or expiry ends access. Reset and concurrent sign-in serialize on the account row so an old-password login cannot commit a usable post-reset session.

### Verification and reset challenges (`auth.email_verifications`, `auth.password_resets`)

**Purpose:** Separate one-use, one-purpose email proofs.

| Field | Type / Constraint | Notes |
|-------|-------------------|-------|
| `id`, `account_id` | UUIDv7 primary key; indexed FK | A challenge belongs to exactly one account. |
| `token_digest` | unique fixed-length digest | Raw token only appears in encrypted pending email and the recipient's link. |
| `issued_at`, `expires_at` | UTC timestamps | Expiry is 60 minutes after issue. |
| `consumed_at`, `superseded_at` | UTC timestamps, nullable | Enforce single use and newest issued link. |

**Relationships:** each account has many historical challenges of each purpose, at most one current unsuperseded challenge per purpose. Issuance and consumption lock the owning account row.

**Lifecycle:** issued → consumed, superseded, or expired. Verification changes only `verified_at`; reset changes only password/session state. A GET of the email link does not consume a challenge.

### Profile and links (`users.profiles`, `users.profile_links`)

**Purpose:** Private drafts and explicitly published member information.

| Field | Type / Constraint | Notes |
|-------|-------------------|-------|
| `profiles.account_id` | primary key/FK to account | Exactly one profile per account. |
| `display_name`, `bio` | nullable validated text | Draft may be incomplete; published bio is nonempty and at most 160 characters. |
| `photo_key` | nullable private object reference | Points only to a cleaned photo, never raw staging content. |
| `visibility`, `published_at`, `version` | private/public enum; nullable UTC time; monotonic integer | Default private; version supports conditional owner edits and race handling. |
| `profile_links.id`, `account_id`, `url`, `position` | key/FK, HTTPS URL, stable order | Zero or more in draft; at least one required to publish. |

**Relationships:** account 1:1 profile; profile 1:many ordered links. A profile write locks the profile row and checks verified status through `auth.MemberAccess`, with the account row locked when publication is considered.

**Lifecycle:** private incomplete/complete draft → explicit public publication → manual private or automatic private on removal of a required field → optional republish after completeness/verification. The service commits edited fields, visibility, version, and one privacy-notice event together. Public completeness is also guarded by database checks for local fields; the cross-table verified/link rule is enforced by the transactional service boundary.

### Photo upload (`users.photo_uploads`)

**Purpose:** Track a single owner-authorized staging object through validation.

| Field | Type / Constraint | Notes |
|-------|-------------------|-------|
| `id`, `account_id` | UUIDv7 key; owner FK | Only owner may finalize/attach. |
| `staging_key`, `clean_key` | private object keys; clean nullable | Random keys under separate scoped prefixes. |
| `expires_at`, `state` | UTC timestamp; pending/cleaned/expired | Upload authorization is short lived; stale staging objects are eligible for bounded cleanup. |
| `byte_count`, `media_type` | bounded validated metadata | Server derives from actual decoded content, not solely browser claims. |

**Relationships:** upload belongs to account; a profile may point only to its owner's cleaned photo. Staging objects are never served to visitors or accepted as a published photo.

**Lifecycle:** upload intent → private staged object → validate/re-encode/strip metadata → cleaned photo eligible for draft attachment; expired or failed staging is cleaned within its dedicated prefix. A failed database attach leaves only an inaccessible orphan for controlled cleanup.

### Outbox message and email delivery (`shared.events.outbox_messages`, `shared.email.email_deliveries`)

**Purpose:** Durable, retryable mail without request-time SMTP dependency.

| Field | Type / Constraint | Notes |
|-------|-------------------|-------|
| `outbox.id`, `event_type`, `aggregate_id` | UUIDv7 key, versioned type, owning account/profile ID | Dispatch by ID; no domain state in Redis. |
| `encrypted_payload`, `key_id` | authenticated ciphertext, versioned key reference | Contains recipient/template data and any raw challenge link only until sent/expired. |
| `available_at`, `attempts`, `claimed_at`, `completed_at`, `state` | timestamps/counter/status | Due index, retry/backoff, dead-letter visibility. |
| `email_deliveries.event_id`, `message_id`, `sent_at` | unique event FK, stable message ID, UTC timestamp | Prevents intentional duplicate dispatch and supports audit. |

**Relationships:** one outbox message per account/profile notification transition; at most one recorded delivery per message.

**Lifecycle:** transactionally pending → claimed → delivered or retried → dead letter after bounded attempts. Expired verification/reset messages are not sent after their link expires; a member may request a new link. A privacy-change email remains eligible for retry. Ambiguous SMTP acknowledgement may still result in a duplicate email on retry.

## API Contracts / Interfaces

### Authentication REST

**Boundary:** versioned HTTP action API; Pydantic requests/responses, typed service errors, no ORM exposure.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|------------------|
| `POST` | `/api/v1/auth/register` `{email,password}` | Create restricted account and queue verification, or handle existing address privately | `202` same safe confirmation for valid new/existing email; `422` malformed fields; `429` limit; `503` required service unavailable. |
| `POST` | `/api/v1/auth/login` `{email,password}` | Create fresh session cookie and return minimal member state/CSRF token | `200`; generic `401` for unknown/wrong/unavailable account; `429`/`503`. |
| `GET` | `/api/v1/auth/session` | Get current member ID, verification state, and session-bound CSRF token | `200` or `401`; `Cache-Control: no-store`. |
| `POST` | `/api/v1/auth/logout` | Revoke current session and clear cookie | `204` or `401`. |
| `POST` | `/api/v1/auth/verification-requests` | Issue replacement verification link for signed-in unverified member | `202` or safe `401`/`429`/`503`; no public address lookup. |
| `POST` | `/api/v1/auth/verify` `{token}` | Consume valid proof after explicit page action | `200` verified; safe `400` invalid/expired/used; no automatic sign-in. |
| `POST` | `/api/v1/auth/password-reset-requests` `{email}` | Queue reset for known account without disclosing existence | `202` identical known/unknown response; `422`/`429`/`503`. |
| `POST` | `/api/v1/auth/password-resets` `{token,new_password}` | Consume proof, change hash, revoke every session, queue notice | `204`; safe `400` token failure, `422` password policy, `429`/`503`. |

**Auth requirements:** login/registration/reset request and token submission are anonymous but origin-checked and limited. Session/logout/verification resend require a valid session. Authenticated unsafe commands require a session-bound CSRF header; all unsafe browser commands validate the trusted Origin. Cookies are host-only, HTTP-only, Secure, SameSite=Lax, with a seven-day absolute ceiling. Email links use a configured trusted web origin, never the incoming Host header.

### Profile REST and photo resource

**Boundary:** versioned HTTP actions and gated binary resource.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|------------------|
| `PATCH` | `/api/v1/me/profile` `{display_name?,bio?,links?,photo_upload_id?,version}` | Save private/public owner fields; auto-private when incomplete | `200` owner profile and `became_private`; `401`, `409` stale version, `422` invalid input. |
| `POST` | `/api/v1/me/profile/publish` `{version}` | Publish only complete verified profile | `200` public profile state; `401`, `403` unverified, `409` incomplete/stale. |
| `POST` | `/api/v1/me/profile/unpublish` `{version}` | Make profile private immediately | `200`; `401`/`409`. |
| `POST` | `/api/v1/me/profile/photo-uploads` `{filename,content_type,size}` | Create one private signed staging upload intent | `201` short-lived upload URL/form and ID; `401`, `413`/`422`, `429`. |
| `POST` | `/api/v1/me/profile/photo-uploads/{id}/complete` | Inspect and clean the owner upload, making its ID available for a later profile edit | `200` cleaned photo reference; `400` failed validation, `401`/`403`/`404`, `409` expired. |
| `GET` | `/api/v1/profiles/{account_id}/photo` | Stream currently authorized cleaned image from private storage | Image with `no-store`; `404` for absent or private-to-caller, `503` storage unavailable. |

**Auth requirements:** all writes and upload intents require owner session and CSRF. `profile.edit`, `profile.publish`, `profile.view_private`, and `profile.view_public` are named policies enforced in REST, GraphQL, and services. The photo read permits the owner or a visitor while the profile is public. Direct private-bucket requests remain denied. A new upload is not trusted until completion has checked decoded bytes, format, size, and stripped metadata.

### Profile GraphQL

**Boundary:** read-only Strawberry schema, with generated client operations/types.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|------------------|
| Query | `viewerProfile` | Owner draft/public fields and visibility | Authenticated member only; safe auth error when absent. |
| Query | `publicProfile(accountId)` | Public name, bio, links, and gated photo URL | Published profile or `null`; private and unknown IDs are indistinguishable. |

**Auth requirements:** resolvers call `users.ProfileService` and named policies, not repositories. Owner fields never enter public type selections. Query depth/complexity is bounded; public query shape is allowlisted/persisted for traffic. No GraphQL mutations or WebSocket interface are introduced.

### Named internal interfaces and events

**Boundary:** cross-feature service interfaces and outbox producer/consumer registry.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|------------------|
| Access | `auth.MemberAccess.current(session_secret) -> MemberContext` | Resolve revocable session and verified state | Member context or typed unauthenticated error. |
| Access | `auth.MemberAccess.require_verified(member_id) -> VerifiedMember` | Gate publication and future voting | Verified member or typed unverified error. |
| Profile | `users.ProfileService.save/publish/unpublish/read_public/read_owner` | Enforce completeness and privacy in transactions | Typed domain result/error, never ORM objects. |
| Outbox | `auth.verification_requested.v1`, `auth.password_reset_requested.v1`, `auth.password_reset_completed.v1`, `users.profile_became_private.v1` | Stable email dispatch types | Encrypted payload and stable event ID; worker idempotently claims by ID. |

**Auth requirements:** feature repositories remain private to their module. The shared outbox/SMTP layers transport events and messages but make no account or profile policy decisions.

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|------------------|----------------|----------------------|
| `app.modules.auth` | Account state, password policy, sessions, email challenges, auth REST, member-access policy | Shared DB/config/security/events/logging; no `users` repository. |
| `app.modules.users` | Draft/public profile, links, photo intents, visibility, GraphQL, profile REST | Auth named access interface; shared DB/storage/events/logging; no auth repository. |
| `app.shared.security` | Password hashing/blocklist, random secret and CSRF primitives | Crypto libraries/config; no feature repositories. |
| `app.shared.events` | Outbox persistence/claim/dispatch registration | Shared DB and typed event envelope; no feature policy. |
| `app.shared.email` | Encrypted payload codec and SMTP transport | Config/crypto/SMTP; no feature repositories. |
| `app.shared.storage` | Scoped signed staging upload, object validation access, private read | S3 client/config; no account/profile authorization decision. |
| `apps.worker` | Poll/dispatch due IDs and actor progress | Shared event/email services and registered feature handlers. |
| `apps.web` / `packages.contracts` | Accessible routes/forms, TanStack Query state, generated REST/GraphQL consumers | Generated contracts and same-origin APIs only. |

## Change Footprint

_The concrete answer to “where does this land in the codebase?” — produced during the Phase D2 walk._

### New files / modules

| Path | Purpose | Pattern reference |
|------|---------|-------------------|
| `apps/api/app/modules/auth/` (`models.py`, `repository.py`, `service.py`, `routes.py`, `schemas.py`, `policies.py`, tests) | Accounts, sessions, challenges, thin REST, named member-access boundary | Existing `modules/health/` feature layout; engineering guide feature ownership. |
| `apps/api/app/modules/users/` (`models.py`, `repository.py`, `service.py`, `routes.py`, `graphql.py`, `schemas.py`, `policies.py`, tests) | Profiles, links, photo intents, thin actions/read resolvers, visibility | Existing `modules/health/` feature layout; `auth.MemberAccess`. |
| `apps/api/app/shared/security/` | Argon2id, blocklist, token digest, CSRF/session primitives; versioned blocklist asset | Shared-only convention in `app/shared/`. |
| `apps/api/app/shared/events/` and `apps/api/app/shared/email/` | Transactional outbox, encrypted payload codec, SMTP delivery and handler registry | Engineering guide outbox boundary; existing shared infrastructure style. |
| `apps/api/app/shared/storage/objects.py` | Signed staging upload, private object get/write, bounded cleanup operations | Existing `shared/storage/client.py` keeps readiness-only behavior. |
| `apps/api/alembic/versions/0002_member_identity_profiles.py` | Forward migration for account, session, challenge, profile, photo, outbox, delivery records and indexes | Existing `0001_foundation.py`; never rewrite it. |
| `apps/web/src/identity/` and `apps/web/src/profiles/` | Typed account/recovery/profile screens, owner and public views, accessible notices | Existing TanStack Query and `App.tsx` patterns. |
| `packages/contracts/schema.graphql` and `packages/contracts/src/graphql.generated.ts` | Generated GraphQL schema and operation types | Existing generated OpenAPI artifacts. |
| `docs/adr/0005-member-sessions-recovery.md`, `docs/adr/0006-profile-privacy-email.md` | Record security, public-contract, storage, and delivery decisions | Existing one-page ADRs. |
| `tests/integration/test_member_identity.py`, `tests/integration/test_profile_privacy.py`, `tests/integration/test_identity_mail.py`, `tests/browser/member-identity.spec.ts` | Cross-service and browser verification ownership | Existing isolated integration/browser layout. |

### Modified files / modules

| Path | What changes here |
|------|-------------------|
| `apps/api/app/main.py` | Compose auth REST, profile REST/GraphQL, shared resources, and lifecycle without breaking health-only injection. |
| `apps/api/app/shared/config/settings.py`, `.env.example` | Validate mail origin/sender, outbox key, session/cookie and public upload endpoint settings; keep secret values out of errors. |
| `apps/api/app/shared/db/database.py`, `apps/api/app/modules/health/probes.py` | Resolve the app's current Alembic head for preparation/readiness instead of hard-coded `0001_foundation`; preserve bounded health probes. |
| `apps/api/app/shared/storage/provision.py` | Extend runtime identity with prefix-scoped object permissions and strict upload CORS while preserving private bucket checks. |
| `apps/worker/worker.py`, `apps/worker/scheduler.py` | Add durable outbox dispatch and stale-staging maintenance while preserving progress health semantics. |
| `compose.yaml`, `compose.checks.yaml` | Provide isolated mail service/config, API/worker/scheduler keys, browser-reachable staging endpoint and dependencies. |
| `pyproject.toml`, `requirements.lock` | Pin approved auth, GraphQL, crypto, email, and image validation libraries. |
| `apps/web/src/App.tsx`, `apps/web/src/main.tsx`, `apps/web/src/styles.css`, `apps/web/package.json`, `package-lock.json` | Add client routes, mobile/keyboard-ready identity/profile UI and pinned router/GraphQL client tooling while retaining `/` connectivity. |
| `packages/contracts/package.json`, `packages/contracts/openapi.json`, `packages/contracts/src/generated.ts`, `scripts/quality/contracts.sh`, `scripts/quality/run.sh` | Generate/check both REST and GraphQL contracts and make the GraphQL gate applicable; catch source-schema and generated-type drift. |
| `tests/conftest.py`, `tests/integration/test_database_preparation.py`, `tests/integration/test_background_processes.py`, `tests/integration/test_health_dependencies.py` | Extend isolated mail/storage fixtures and adapt old migration/background expectations to real feature work. |
| `README.md`, `docs/development.md` | Document account flow, mail recovery, link expiry, private photos, cookie/local browser behavior, and forward migration recovery. |

### Deleted / replaced

None. The foundation migration, health routes, connectivity page, and protected source/REQ documents remain in place.

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|------|----------------|
| `apps/api/app/bootstrap.py`, `apps/api/alembic/env.py` | Preparation must still hold its advisory lock and gate startup when the new migration runs. |
| `apps/api/app/modules/health/routes.py`, `apps/api/app/modules/health/service.py`, `apps/api/app/modules/health/tests/test_routes.py` | The health-only app factory path and three-second readiness behavior must survive route composition. |
| `apps/api/app/shared/storage/client.py`, `tests/integration/test_storage.py` | Existing read-only readiness and anonymous-denial behavior must survive new object permissions. |
| `apps/worker/health.py`, `tests/integration/test_startup_order.py` | Process progress and startup gating remain distinct from new mail jobs. |
| `apps/web/src/connectivity/`, `apps/web/src/App.test.tsx`, `tests/browser/connectivity.spec.ts` | Existing connected/unavailable UI remains reachable at `/`. |
| `infra/docker/web.conf`, `infra/docker/web.Dockerfile`, `infra/docker/browser.Dockerfile` | Existing same-origin `/api/` proxy and compiled-contract inclusion must carry new routes/artifacts without leaking storage credentials. |
| `.github/workflows/quality.yml`, `scripts/quality/security.sh` | CI invokes the shared gate and security scan; new dependencies and generated artifacts must remain covered. |
| `AGENTS.md`, `CLAUDE.md`, `docs/source/` and `specs/requirements/REQ-add-member-identity-profiles.md` | Approved instructions, product context, and requirement contract are read-only inputs. |

## Areas of Impact

| Area | Impact | Risk (L/M/H) | Why |
|------|--------|--------------|-----|
| Authentication and recovery | First real credentials, sessions, and email proofs | H | Enumeration, token misuse, session races, and reset errors can expose accounts. |
| Profile visibility and media | Private drafts, publication, and immediate unpublication | H | Stale public reads or storage URLs can leak personal information. |
| Email/outbox and background processes | New durable work in formerly heartbeat-only processes | H | Retry, expiry, and ambiguous SMTP completion need bounded, observable behavior. |
| Migrations and readiness | New tables and dynamic expected-head check | H | A revision mismatch can block startup or falsely report readiness. |
| Storage privilege boundary | Prefix-scoped object access and signed staging uploads | H | Overbroad policy or unvalidated upload can expose or retain unsafe media. |
| API/GraphQL contracts and frontend | New actions, reads, generated types, accessible pages | M | Contract drift or cache behavior could display stale privacy/verification state. |
| Rate limiting and Redis | New temporary abuse controls | M | Fail-open behavior permits abuse; overly broad limits deny legitimate members. |
| Local/CI configuration and documentation | Mail/secret settings and quality applicability | M | Missing keys or mail services could yield false success or nonreproducible checks. |

**Contract changes:** New versioned REST account/profile actions and gated image resource, a read-only GraphQL profile schema, generated TypeScript types, and internal versioned email-event names. Existing `/api/v1/health/*` response shape and the connectivity-page contract do not change. Future voting consumes the `auth.MemberAccess.require_verified` interface, not identity tables directly.

**Cross-cutting ripples:** database head resolution; preparation/health tests; runtime MinIO policy; SMTP configuration; outbox encryption key and worker/scheduler progress; browser CSRF/cookie handling; generated REST/GraphQL drift checks; mail/photo integration fixtures and CI security scans.

## Cross-Cutting Concerns

- **Errors:** Services return typed domain errors. REST maps them to documented safe codes; GraphQL returns a safe auth error for private owner reads and `null` for private/unknown public profiles. Outsiders get the same `404` for absent and private photos. Registration/reset success responses stay generic. Storage, DB, Redis, and SMTP exceptions are not returned to browsers. Retries are bounded; invalid or expired links have a safe replacement path.
- **Logging & metrics:** Preserve structured request correlation. Record safe operation/result codes, durations, rate-limit decisions, outbox backlog age/attempts/dead letters, login failure counts, and profile privacy transitions. Never log passwords, full addresses, cookies, CSRF values, challenge tokens/URLs, encrypted payloads, image bytes, or private object keys; use pseudonymous IDs. Account/security failures warrant warning-level diagnostics, failed dispatch error-level, successful transitions informational. No collector/dashboard is introduced.
- **Auth / authz:** `auth.MemberAccess` validates session digest, epoch, expiry, and revocation on each protected request. Named policies operate at REST, GraphQL, and service boundaries. Owner-only profile writes and private reads are checked against the current account; publication additionally requires verified email and completeness. Session-bearing unsafe requests need Origin and CSRF checks. Anonymous reads never reveal private profile existence. Public GraphQL queries have bounded complexity and a persisted/allowlisted operation shape.
- **Performance:** Indexed lookups cover canonical email, token/session digest, public-profile ID, and due outbox messages. No account-table scan appears in sign-in/readiness. Session activity writes are coalesced; profile visibility is read from PostgreSQL, not cached as public success. Photo proxy streams bounded, cleaned images and is deliberately `no-store`; monitor its bandwidth before considering a future revocable edge solution. SMTP/image work never blocks the request event loop; small image validation is offloaded to a bounded thread/process worker.
- **Security:** Passwords use Argon2id with per-password salt and a generous bounded maximum; the policy permits 8–64+ characters, spaces, and no mandatory mix. Verification/reset tokens are high-entropy, digest-only challenges; the encrypted outbox is the only durable carrier of raw email links. Encrypt with an authenticated, versioned key kept outside frontend/images; retain old decryption keys until pending mail drains. Signed staging uploads are object- and size-scoped, expire quickly, and require a server-side actual-content check and re-encode before attachment. The bucket remains private; public photo reads are visibility-gated and uncacheable. Same-origin web access and trusted link origin prevent Host-header link poisoning. Local Linux browser verification uses `localhost` for Secure cookies; non-local deployment requires HTTPS.
- **Migrations / rollout:** Add one forward Alembic revision after `0001_foundation`, including constraints and indexes; never edit the foundation revision. Preparation runs before API/worker/scheduler startup, and readiness compares the database with the code's current head. There is no auto-downgrade or automatic reset. A bad new revision requires a corrective forward migration or restoring a compatible application/database backup. Isolated check environments retain separate credentials/volumes and must prove fresh and repeat migration behavior. Staging/production rollout remains out of scope.

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|----------|--------------|----------------|----------------|
| A1 | Separate auth and users modules behind named services | Combined module; cross-repository imports | Preserves ownership and reusable verified-member gate | R3–R11, N3 |
| A2 | PostgreSQL authority, constraints, locks, revocable server sessions | Redis authority; stateless JWT-only session | Supports uniqueness, single use, and all-device reset | R1, R3–R4, R7, R9–R11, N3 |
| A3 | 24-hour idle/7-day absolute Secure cookie sessions with CSRF | Unlimited sessions; bearer token in web storage | Bounded exposure, immediate server revocation, safer browser boundary | R3, R7, N1 |
| A4 | 60-minute digest-only challenges with latest issuance winning | Reusable/long-lived links; self-contained JWTs | Enforces confirmed link and reset behavior | R4–R7, N1, N3 |
| A5 | Case-insensitive canonical email, original delivery address, no provider alias rewrite | Case-sensitive duplicate accounts; Gmail-specific normalization | Predictable lookup without provider assumptions | R1–R2, N2 |
| A6 | Argon2id, offline blocklist, separate Redis limits that fail closed | Fast hash; mandatory mix; network-only blocklist; permanent lockout | Meets confirmed password policy and abuse resistance | R1, R3, R8, N1–N2 |
| A7 | Encrypted PostgreSQL outbox + Dramatiq/SMTP, stable IDs, retry | Request-time mail; Redis-only queue; plaintext link in outbox | Durable email and confidential challenge links | R2, R5–R7, R12, N1–N3 |
| A8 | Signed private staging, validated/re-encoded photos, gated `no-store` API reads | Public bucket; direct public signed download | Immediate privacy withdrawal and controlled media | R9–R11, N1 |
| A9 | REST actions plus read-only Strawberry GraphQL and generated clients | REST-only profile reads; handwritten frontend types | Approved API split and drift prevention | R3–R11, N4 |
| A10 | Dynamic expected migration head and preserved startup/health contracts | Keep hard-coded `0001_foundation`; bypass readiness | New schema can become ready without false success or failure | N3 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|----------|---------------------------|
| Two people register the same canonical email at once. | Unique index chooses one account; both public responses are generic. Only the winning transaction creates a profile/challenge/outbox event. |
| Two replacement links are requested together, or a stale link is clicked. | Account row serializes issuance; later issuance supersedes earlier. Consumption checks digest, expiry, purpose, and unconsumed/current state under lock. |
| Password reset races with a sign-in using the old password. | Both operations lock the account; login cannot commit a usable old-epoch session after reset, and reset invalidates all prior sessions. |
| Mailpit/SMTP is down for 30 seconds, or the worker restarts after a send. | Committed outbox remains pending and is retried with bounded backoff. An ambiguous send may duplicate an email; account/profile transitions remain single and idempotent. Expired links are not sent later. |
| Redis is unavailable or an attacker floods registration/login/reset. | Sensitive actions fail closed when rate limits cannot be enforced. Independent address/account and source limits create temporary cooldowns, not permanent account lockouts. Readiness already marks Redis unavailable. |
| A published member removes the last link while another request edits/publishes. | Profile version and row lock serialize writes; the committed edited profile becomes private with one privacy event. Public GraphQL and photo reads observe authoritative visibility. |
| An old public photo URL is requested after unpublication. | The API rechecks current visibility on every image GET and sends `no-store`; direct storage access remains denied. |
| A signed upload contains fake media type, oversized bytes, malformed image, or metadata. | Signed policy limits scope/size; finalization checks actual bytes, decodes allowed formats, strips metadata, and never attaches invalid staging data. |
| PostgreSQL holds 10 million accounts or many sessions/messages. | Canonical email, digest, owner, public-profile, and due-message indexes keep auth and dispatcher work bounded; health checks only migration metadata. Proxy-photo bandwidth remains an observed capacity risk, not a hidden cache. |
| New code starts before migration or old code sees the new head. | Preparation gates startup; readiness rejects incompatible revisions. Recovery is a compatible application restore or corrective forward migration, not destructive downgrade. |

### Backward — regression risk per touched area (brownfield only)

| Touched area (from Change Footprint) | What could regress | How we'd know / mitigation |
|--------------------------------------|--------------------|----------------------------|
| `main.py`, health routes/service/tests, `bootstrap.py`, Alembic env | Health-only app construction or preparation lock/startup order breaks when new resources are wired | Preserve factory injection and advisory-lock lifecycle; existing health/startup checks stay in the gate. |
| `database.py`, health probes, migration integration checks | Hard-coded foundation revision or changed expected-head logic falsely accepts/rejects a prepared DB | Fresh/repeat migration and mismatched-head checks cover code/database compatibility. |
| `storage/provision.py`, storage client/integration checks | Runtime policy becomes public or probe loses required bucket reads | Keep anonymous-denial and bounded probe behavior; grant only specific private object prefixes. |
| `worker.py`, `scheduler.py`, worker health and startup tests | Process looks healthy while mail dispatch has stalled, or background work starts before preparation | Tie progress to successful due-work scanning/dispatch loop and dependencies; preserve startup gate and stale-progress check. |
| `App.tsx`, connectivity client/tests, web proxy/build images | New routing or GraphQL artifacts remove existing connectivity page or fail container builds | Retain `/` connectivity route and generated-contract inclusion; existing browser/build checks remain applicable. |
| Contracts/quality scripts, CI/security scripts | New GraphQL or OpenAPI changes go unchecked, or “not applicable” is reported falsely | Compare source-exported schemas and generated types in local/CI gate; change GraphQL applicability while preserving all existing categories. |
| Compose/config/docs/fixtures | New secrets/mail service leak into browser, missing config silently defaults, or check data shares development resources | Validate separation, build exclusions, and isolated check credentials/volumes; document local-only defaults. |

## Open Questions

No unresolved architectural decision blocks this slice. Exact pinned library versions, a versioned offline blocklist distribution, and limit thresholds are implementation selections constrained by the approved behavior above; they do not authorize weaker controls or a new external dependency. Future email-address change, Google sign-in, multifactor authentication, and production photo delivery will need their own design decisions.

## Out of Scope

- Google sign-in, passkeys, multifactor authentication, email-address changes, account deletion, and staff suspension (separate identity/governance slices).
- Product creation, founder status, voting, launch workflows, notification bell/preferences, and public search (later features consume member identity).
- Public bucket access, direct public photo URLs, generic media library, and product-media pipelines (profile privacy needs gated media only).
- Staging/production deployment, R2 provisioning, CDN revocation service, dashboards/collectors, or speculative GraphQL/WebSocket domains (outside this local feature slice).
- Task sequencing, effort estimates, and implementation test scenarios (owned by `TASKS-add-member-identity-profiles.md`).
