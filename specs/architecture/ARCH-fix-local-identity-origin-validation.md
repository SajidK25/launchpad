# Architecture: Fix Local Identity Origin Validation

> **Date:** 2026-09-25
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** `specs/requirements/REQ-fix-local-identity-origin-validation.md`
> **Tasks:** `TASKS-fix-local-identity-origin-validation.md`
> **Type:** infrastructure

## Architecture Summary

Introduce a dedicated, explicitly configured trusted-browser-origin collection rather than reusing the singular origin used in email links and storage setup. The existing CSRF/origin primitive will compare a request against that collection using exact scheme, hostname, and port matching, while auth and profile routes retain their current generic rejection responses. Development and check Compose configurations will declare their supported host and internal origins explicitly; production will receive only operator-supplied origins. No database, REST path, response-shape, or frontend changes are required.

## High-Level Structure

```text
runtime environment
  ├─ LAUNCHPAD_MAIL_WEB_ORIGIN       -> email/reset/profile links + production storage CORS
  └─ LAUNCHPAD_TRUSTED_WEB_ORIGINS   -> normalized browser origin allowlist
                                      -> auth route origin/CSRF checks
                                      -> profile route origin/CSRF checks

request Origin header
  -> shared origin primitive (exact scheme/host/port)
  -> generic 403 on missing/untrusted origin
  -> route/service state changes only after the check succeeds
```

The application factory loads and validates both settings before building auth and profile routers. The router closures receive the immutable trusted-origin collection; domain services continue to receive only the singular link origin.

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|------|----------|-------------------------|-----------|
| Configuration | Add required `LAUNCHPAD_TRUSTED_WEB_ORIGINS` as a comma-separated origin list | Reuse `LAUNCHPAD_MAIL_WEB_ORIGIN`; infer localhost; JSON-only configuration | Separates browser trust from generated URLs and makes the security boundary auditable (R1–R5, N2). |
| Parsing/normalization | Parse with existing Pydantic/settings validation; normalize one trailing slash and deduplicate equivalent entries | Ignore malformed entries; permit arbitrary URL paths; reject harmless duplicates | Fails closed on mistakes while keeping equivalent configuration deterministic (R3, R5, N1). |
| Request validation | Extend the existing shared origin primitive to accept a collection and compare exact scheme/host/port | Route-specific checks; wildcard host/port matching; localhost special case | One security primitive keeps registration, auth, recovery, and profile behavior consistent (R1–R4, N2). |
| Runtime wiring | Declare origins explicitly in `.env.example`, development Compose, check Compose, and production deployment configuration | Hidden defaults by environment; automatic `localhost` trust | Prevents accidental production expansion and preserves the isolated browser test origin (R5, N1). |

## Patterns & Conventions

- **Shared security primitive** — origin and CSRF checks remain in `apps/api/app/shared/security/csrf.py`; route layers only map its typed security error to the existing generic HTTP response.
- **Settings fail closed** — follow `Settings`/`load_settings` validation and `ConfigurationError` conventions; invalid configuration names fields without echoing values.
- **Thin transport routes** — auth and users routes supply settings to the shared primitive and keep domain services unaware of browser-origin policy.
- **Separate canonical URL concerns** — `mail_web_origin` remains singular for email payload links, profile links, and production storage CORS.
- **Explicit Compose environments** — development, check, and production values are declared at their runtime boundaries rather than inferred from request hosts.

## Data Models

### Trusted web origin configuration

**Purpose:** Represents the finite browser origins allowed to invoke identity mutations and CSRF-protected profile operations.

**Key fields:**

| Field | Type / Constraint | Notes |
|-------|------------------|-------|
| `trusted_web_origins` | Immutable collection of canonical origin strings; required and non-empty | Each value has only scheme, hostname, and optional port; no path, query, fragment, credentials, or wildcard. |
| `mail_web_origin` | Existing singular HTTP origin | Not part of the browser allowlist contract; retained for generated links and storage provisioning. |

**Relationships:**
- Auth and users route factories consume `trusted_web_origins`.
- Auth/users services consume `mail_web_origin` for link generation only.

**Lifecycle:**
- Loaded and normalized at process startup → held immutable for process lifetime → changed only by an explicit configuration update and restart.

## API Contracts / Interfaces

### Shared origin security primitive

**Boundary:** internal security library

**Operations:**

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|------------------|---------|-----------------|
| Validate origin | `validate_origin(origin: str \| None, trusted_origins: Collection[str]) -> None` | Require the request origin to match one configured origin exactly by scheme, hostname, and port. | Raises `RequestSecurityError` for missing, malformed, or unmatched origins; returns nothing on success. |
| Require CSRF | `require_csrf(origin: str \| None, trusted_origins: Collection[str], token: str \| None, expected_digest: bytes) -> None` | Apply origin validation before the existing session-bound CSRF token check. | Same origin error or existing invalid-CSRF error; no state mutation. |

### Auth and profile route boundaries

**Boundary:** HTTP transport

The existing registration, login, verification-request, password-reset-request, password-reset, logout, and profile mutation paths keep their current methods, paths, response bodies, authentication requirements, and status codes. Their route-local origin/CSRF gates receive the trusted-origin collection. Rejected origins continue to map to `403` with `{"detail":"request rejected"}`.

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|------------------|----------------|---------------------|
| `app.shared.config.settings` | Parse, normalize, deduplicate, and validate runtime origins | Pydantic and standard URL parsing; no route/domain imports |
| `app.shared.security.csrf` | Compare request origins and enforce session-bound CSRF | Token primitives and URL parsing; no settings or database imports |
| `app.modules.auth.routes` | Apply browser-origin/CSRF checks to auth commands and map safe HTTP errors | Settings, shared security, auth services |
| `app.modules.users.routes` | Apply browser-origin/CSRF checks to profile mutations and map safe HTTP errors | Settings, shared security, users services |
| Compose/env/docs | Declare runtime-specific origin values | No application logic |

## Change Footprint

_The concrete answer to where this lands in the codebase._

### New files / modules

| Path | Purpose | Pattern reference |
|------|---------|-------------------|
| None | This is a configuration/security extension of existing modules. | Existing settings and CSRF primitives. |

### Modified files / modules

| Path | What changes here |
|------|-------------------|
| `apps/api/app/shared/config/settings.py` | Add the required trusted-origin setting, canonicalization, deduplication, and safe validation. |
| `apps/api/app/shared/security/csrf.py` | Accept a collection of trusted origins while preserving exact matching and security errors. |
| `apps/api/app/modules/auth/routes.py` | Pass the configured collection to registration/login/recovery/verification/session mutation origin and CSRF gates. |
| `apps/api/app/modules/users/routes.py` | Pass the configured collection to profile mutation origin and CSRF gates. |
| `apps/api/app/shared/config/tests/test_settings.py` | Verify required configuration, malformed entries, normalization, deduplication, and production isolation. |
| `apps/api/app/shared/security/tests/test_identity_primitives.py` | Verify multi-origin acceptance and fail-closed exact matching. |
| `tests/integration/test_member_identity.py` | Exercise configured host/internal origins without changing business assertions. |
| Auth/users route tests | Cover generic rejection and state-safe behavior across the shared origin collection. |
| `.env.example` | Document the two approved host-loopback origins. |
| `compose.yaml` | Set development trusted origins to localhost and loopback IP on port 8080. |
| `compose.checks.yaml` | Set check trusted origins to both host-loopback values plus `http://web:8080`. |
| `docs/development.md` | Document the local origins and explicit trusted-origin configuration. |

### Deleted / replaced

| Path | Reason |
|------|--------|
| None | The singular mail/link origin remains intentionally supported. |

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|------|----------------|
| `apps/api/app/modules/auth/service.py` | Generates verification and reset links; must continue using singular `mail_web_origin`. |
| `apps/api/app/modules/users/service.py` | Generates profile notification links; must not receive browser allowlist values. |
| `apps/api/app/bootstrap.py` | Uses singular `mail_web_origin` for production storage CORS; changing it would alter object-storage policy. |
| `apps/web/src/identity/client.ts` and `apps/web/src/profiles/client.ts` | Send same-origin browser requests; no client contract change is expected. |
| `infra/docker/web.conf` | Keeps host header/proxy behavior that produces the browser origin; no proxy rewrite should be added. |

## Areas of Impact

| Area | Impact | Risk (L/M/H) | Why |
|------|--------|--------------|-----|
| Runtime configuration | New required allowlist in every environment | M | Missing or malformed deployment values prevent startup by design. |
| Shared security | Validator contract changes from one origin to a collection | H | Every unsafe auth/profile route depends on this boundary. |
| Auth and recovery | Local registration/sign-in/recovery/verification requests become accepted from both loopback origins | M | A missed route call site could leave one identity action blocked. |
| Member profiles | Local private-profile edits and photo mutations use the same allowlist | M | CSRF and profile state integrity must remain unchanged. |
| Check/browser environment | Internal `web:8080` origin remains explicitly trusted in check only | M | Removing it would break isolated browser QA; exposing it in production would broaden trust. |
| Email/storage links | No contract change; singular link origin remains authoritative | L | Separation reduces accidental coupling. |

**Contract changes:** Internal settings and security-library interfaces change from a singular trusted origin to a collection. Public REST paths, response bodies, cookies, events, email payloads, and GraphQL contracts do not change.

**Cross-cutting ripples:** deployment configuration, local documentation, settings validation, security tests, and browser/integration fixtures. No migration, feature flag, dependency, or telemetry schema is required.

## Cross-Cutting Concerns

- **Errors:** Invalid configuration raises the existing safe startup configuration error. Runtime origin failures remain the existing generic `403` response. No route retries or partial state changes are introduced.
- **Logging & metrics:** Do not log configured origins or request origin values. Preserve existing request-failure logging without adding sensitive configuration fields.
- **Auth / authz:** Origin validation remains before CSRF token validation and before auth/profile state mutations. Authentication and authorization policies are unchanged.
- **Performance:** The allowlist is small, normalized once at startup, and checked in memory; no database, cache, or network work is added.
- **Security:** Reject empty/malformed entries, paths, credentials, wildcards, missing origins, alternate ports/schemes, and nonmatches. Production receives no automatic local origins.
- **Migrations / rollout:** Configuration-only rollout. Update each runtime's environment before restarting API/worker/scheduler processes; rollback is removing the new setting and reverting code/config together. Existing database state is unaffected.

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|----------|--------------|----------------|----------------|
| A1 | Add required `LAUNCHPAD_TRUSTED_WEB_ORIGINS` separate from `LAUNCHPAD_MAIL_WEB_ORIGIN` | Reuse singular mail origin; infer localhost; special-case validator | Keeps browser trust distinct from generated links and makes production policy explicit. | R1, R2, R5, N2 |
| A2 | Normalize one trailing slash and deduplicate equivalent entries; reject all other malformed values | Ignore malformed values; accept arbitrary URL components; reject duplicates | Safe configuration remains deterministic without widening exact matching. | R3, R5, N1 |
| A3 | Make the shared validator accept a collection and retain exact triple matching | Route-specific checks; wildcard matching; localhost special case | Preserves one security boundary for every identity/profile action. | R1–R4, N2 |
| A4 | Configure development/check/production explicitly | Hidden environment defaults; automatic local trust | Prevents accidental production exposure and keeps internal check-browser behavior reproducible. | R1, R2, R5 |
| A5 | Keep route responses and domain services unchanged | New error contract; pass allowlist into link-generating services | Minimizes compatibility risk and avoids leaking configuration. | R3, R4, N1, N2 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|----------|----------------------------|
| A deployment omits or mistypes the trusted-origin list | Startup fails with a field-only configuration error; the API never runs with an accidental empty or broad allowlist. |
| A browser sends no `Origin`, an alternate port, HTTPS, or an untrusted host | Shared validator rejects before CSRF/state work and routes return the same generic 403. |
| A check browser uses the internal `web:8080` origin | Check Compose explicitly includes that origin; development/production do not inherit it. |
| The allowlist grows modestly over time | Normalized in memory and checked linearly; no persistence or query impact. |
| A rollout needs to remove a previously trusted origin | Configuration change plus process restart takes effect atomically; old sessions remain valid but requests from the removed origin are rejected. |

### Backward — regression risk per touched area (brownfield only)

| Touched area (from Change Footprint) | What could regress | How we'd know / mitigation |
|--------------------------------------|--------------------|---------------------------|
| Settings loader | Existing local/test fixtures fail because the new setting is absent or parsing differs | Update settings fixtures and assert safe defaults/configuration errors explicitly. |
| Shared CSRF primitive | A call site still passes a string or matching becomes less exact | Type-check all callers and cover both accepted origins plus rejected scheme/host/port cases. |
| Auth routes | Registration/login/recovery/verification remains tied to singular mail origin | Route-level/integration checks exercise each identity action with both configured local origins. |
| Users routes | Profile mutation or photo flows use the wrong origin collection | Profile route checks cover origin rejection and successful trusted-origin requests. |
| Bootstrap/services | Multi-origin list leaks into email links or storage CORS | Keep singular `mail_web_origin` dependencies unchanged and verify generated URLs remain canonical. |
| Check Compose | Browser tests lose `web:8080` trust | Check runtime configuration includes the internal origin and browser QA remains green. |

## Open Questions

- None. The origin format, environment policy, normalization, rejection behavior, and runtime values were confirmed during architecture planning.

## Out of Scope

- New authentication, recovery, profile, or non-browser-client features (reason: separate product/security work).
- Database migrations or persistence changes (reason: this is configuration and request-validation only).
- Wildcard origins, arbitrary localhost ports, alternate schemes, or automatic origin inference (reason: explicitly rejected by the requirements).

