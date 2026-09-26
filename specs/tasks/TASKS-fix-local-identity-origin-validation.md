# Tasks

## Task T1: Add fail-closed trusted-origin settings

> **Status:** done
> **Verification:** tdd
> **Effort:** s
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R5, N1, N2
> **Footprint slice:** Modified: `apps/api/app/shared/config/settings.py`; settings tests
> **High-risk areas touched:** Runtime configuration (M)

### Description

Add the required `LAUNCHPAD_TRUSTED_WEB_ORIGINS` setting as a normalized, immutable collection. The loader must accept comma-separated origins, normalize one trailing slash, deduplicate equivalent entries, and fail closed with safe field-only errors for missing, empty, or malformed configuration while leaving singular `mail_web_origin` behavior unchanged.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/config/tests/test_settings.py`

#### Test Scenarios

##### Trusted-origin parsing

- **parses a required origin list** — GIVEN valid comma-separated origins WHEN settings load THEN the collection contains the canonical origins in deterministic order _(verifies R5)_
- **normalizes and deduplicates equivalent entries** — GIVEN a trailing slash and duplicate origin values WHEN settings load THEN one canonical value remains _(verifies R3, N1)_

##### Safe configuration failures

- **rejects missing or empty configuration** — GIVEN no trusted-origin value or only blank entries WHEN settings load THEN startup raises the safe configuration error naming the setting _(verifies R5, N1)_
- **rejects malformed origin components** — GIVEN credentials, path, query, fragment, wildcard, invalid scheme, host, or port WHEN settings load THEN the whole configuration is rejected without echoing supplied values _(verifies R3, R5, N1)_
- **does not inject localhost in production** — GIVEN production settings without local origins WHEN settings load THEN only explicit operator origins are accepted _(verifies R5, N2)_

##### Regression guard

- **preserves singular mail-link origin** — GIVEN valid settings with multiple trusted origins WHEN services read `mail_web_origin` THEN its single canonical value remains unchanged _(guards ARCH backward-regression risk for `apps/api/app/modules/auth/service.py`, `apps/api/app/modules/users/service.py`, and `apps/api/app/bootstrap.py`)_

### Implementation Notes

- **Module(s):** `app.shared.config.settings`
- **Pattern reference:** Existing `Settings`, `load_settings`, `_validate_identity_settings`, and `ConfigurationError` conventions.
- **Key decisions:** Dedicated setting separate from `mail_web_origin`; explicit in every runtime; normalize trailing slash and deduplicate; reject malformed/empty values (A1, A2, A4).
- **Libraries:** Existing Pydantic URL validation and standard-library URL parsing only; no new dependency.
- **High-risk callouts:** Configuration is security-sensitive. Tests must prove production never receives automatic localhost trust and errors never include origin values.

### Scope Boundaries

- Do NOT change `mail_web_origin` semantics or generated email/profile URLs.
- Do NOT infer trust from request host, environment name alone, or wildcard patterns.
- Do NOT add database state, migrations, feature flags, or a new dependency.
- Only implement parsing, normalization, and validation of the trusted-origin setting.

### Files Expected

**New files:**
- None.

**Modified files:**
- `apps/api/app/shared/config/settings.py` (add required trusted-origin configuration and safe validation)
- `apps/api/app/shared/config/tests/test_settings.py` (TDD coverage for parsing, failures, and singular-origin regression)

**Must NOT modify:**
- `apps/api/app/modules/auth/service.py` (singular link origin regression hotspot)
- `apps/api/app/modules/users/service.py` (singular profile-link origin regression hotspot)
- `apps/api/app/bootstrap.py` (production storage CORS uses singular origin)

### TDD Sequence

1. Add failing settings parsing and rejection assertions.
2. Implement normalized collection loading and validation.
3. Refactor only after the full settings test group passes.

## Task T2: Extend the shared exact-origin and CSRF primitive

> **Status:** done
> **Verification:** tdd
> **Effort:** s
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R1, R2, R3, R4, N1, N2
> **Footprint slice:** Modified: `apps/api/app/shared/security/csrf.py`; security primitive tests
> **High-risk areas touched:** Shared security (H)

### Description

Extend the existing origin and CSRF primitive to accept the normalized trusted-origin collection. Preserve exact scheme/hostname/port matching, missing-origin rejection, typed security errors, and the ordering that checks origin before the session-bound CSRF token.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/security/tests/test_identity_primitives.py`

#### Test Scenarios

##### Exact origin matching

- **accepts each configured loopback origin** — GIVEN `http://localhost:8080` or `http://127.0.0.1:8080` in the collection WHEN validated THEN the origin check succeeds _(verifies R1, R2)_
- **accepts an explicitly configured internal check origin** — GIVEN `http://web:8080` in the collection WHEN validated THEN the origin check succeeds _(verifies R1/R2 test-environment support)_
- **rejects missing origin** — GIVEN no `Origin` value WHEN validated THEN `RequestSecurityError` is raised _(verifies R4)_
- **rejects wrong scheme, host, port, path, query, fragment, or untrusted origin** — GIVEN a non-exact request origin WHEN validated THEN the same security error is raised _(verifies R3, N1)_

##### CSRF ordering and compatibility

- **checks origin before token** — GIVEN an untrusted origin and invalid token WHEN CSRF is required THEN the origin error is raised first _(verifies R3, N2)_
- **preserves valid and invalid token behavior** — GIVEN a trusted origin WHEN CSRF is required THEN valid tokens pass and invalid/missing tokens retain the existing failure _(verifies N2)_

##### Regression guard

- **keeps aliases and exception type stable** — GIVEN existing callers use `check_origin`/`check_csrf` aliases WHEN invoked with the collection THEN behavior and `RequestSecurityError` remain compatible _(guards ARCH backward-regression risk for auth/users route callers)_

### Implementation Notes

- **Module(s):** `app.shared.security.csrf`
- **Pattern reference:** Existing `validate_origin`, `require_csrf`, `RequestSecurityError`, and token primitives.
- **Key decisions:** Shared collection-based validator; exact triple matching; no wildcard/localhost special case; origin check precedes CSRF verification (A2, A3).
- **Libraries:** Existing `urllib.parse`, `hmac`, and token helpers; no new dependency.
- **High-risk callouts:** This is the highest-risk security boundary. Keep rejection generic at callers and ensure malformed request origins cannot cause a permissive fallback.

### Scope Boundaries

- Do NOT change route status codes, error detail text, cookies, or token generation.
- Do NOT add route-specific origin logic or bypasses for automated clients.
- Do NOT change email-link or storage-origin behavior.
- Only extend the shared primitive and its direct unit tests.

### Files Expected

**New files:**
- None.

**Modified files:**
- `apps/api/app/shared/security/csrf.py` (collection-based exact matching)
- `apps/api/app/shared/security/tests/test_identity_primitives.py` (multi-origin and fail-closed TDD coverage)

**Must NOT modify:**
- `apps/api/app/modules/auth/routes.py` (owned by T3)
- `apps/api/app/modules/users/routes.py` (owned by T3)
- `apps/api/app/modules/auth/service.py` and `apps/api/app/modules/users/service.py` (link-generation boundary)

### TDD Sequence

1. Add failing multi-origin, missing-origin, and exact-mismatch tests.
2. Extend the primitive signature and matching logic.
3. Run existing CSRF/token tests and refactor only after green.

## Task T3: Wire trusted origins through auth and profile routes

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1, T2
> **Satisfies REQs:** R1, R2, R3, R4, N1, N2
> **Footprint slice:** Modified: `apps/api/app/modules/auth/routes.py`, `apps/api/app/modules/users/routes.py`, auth/users route tests, `tests/integration/test_member_identity.py`
> **High-risk areas touched:** Auth and recovery (M); Member profiles (M); Shared security (H)

### Description

Pass the validated trusted-origin collection into every existing auth and profile origin/CSRF gate. Preserve route paths, authentication rules, generic rejection responses, transaction boundaries, and singular `mail_web_origin` inputs to domain services while proving both host-loopback origins work across the complete identity flow.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/auth/tests/test_routes.py`
- `apps/api/app/modules/users/tests/test_routes.py`
- `tests/integration/test_member_identity.py`
- Existing affected auth/profile integration tests as identified by the current suite

#### Test Scenarios

##### Auth flow wiring

- **accepts localhost origin across auth actions** — GIVEN the configured localhost origin WHEN registration, login, verification request, password-reset request/reset, and logout are invoked with valid inputs THEN existing success responses and state transitions occur _(verifies R1)_
- **accepts loopback-IP origin across auth actions** — GIVEN the configured `127.0.0.1:8080` origin WHEN the same actions are invoked THEN they behave identically _(verifies R2)_

##### Profile flow wiring

- **accepts both trusted origins for profile mutations** — GIVEN an authenticated member and valid CSRF token WHEN private-profile edits, publish/unpublish, and photo mutation actions are invoked THEN existing success behavior remains _(verifies R1, R2)_
- **preserves singular generated links** — GIVEN a trusted-origin request that emits verification, reset, or profile notification mail WHEN the event is inspected THEN generated links still use singular `mail_web_origin` _(guards ARCH backward-regression risk for auth/users services)_

##### Rejection and state safety

- **returns generic rejection for missing/untrusted origins** — GIVEN no origin or an alternate host/scheme/port WHEN any browser-facing identity/profile mutation is invoked THEN response is `403` with `{"detail":"request rejected"}` _(verifies R3, R4, N1)_
- **does not partially mutate state on rejection** — GIVEN a rejected registration, recovery, or profile mutation WHEN the request completes THEN no account/session/challenge/profile/outbox state is created or changed _(verifies N2 and REQ failure edge cases)_

##### Regression guards

- **keeps check-browser origin working** — GIVEN the internal `web:8080` origin used by the isolated check browser WHEN the identity flow runs THEN existing integration/browser setup remains valid _(guards ARCH risk for check runtime)_
- **keeps frontend request contract unchanged** — GIVEN existing identity/profile clients WHEN routes are exercised THEN paths, response bodies, cookies, and CSRF behavior remain unchanged _(guards ARCH risk for `apps/web/src/identity/client.ts` and `apps/web/src/profiles/client.ts`)_

### Implementation Notes

- **Module(s):** `app.modules.auth.routes`, `app.modules.users.routes`, route/integration tests.
- **Pattern reference:** Existing route-local `origin`, `check_origin`, and `check_csrf` closures plus generic `HTTPException` mappings.
- **Key decisions:** Pass collection to transport gates only; leave services and bootstrap on singular `mail_web_origin`; preserve existing contracts (A3, A5).
- **Libraries:** Existing FastAPI, SQLAlchemy test fixtures, and TestClient; no new dependency.
- **High-risk callouts:** Audit every auth/users mutation call site. A missed call site or accidental service wiring would either leave a flow broken or broaden link/storage policy.

### Scope Boundaries

- Do NOT change endpoint paths, response schemas, cookie policy, authz rules, or domain service signatures.
- Do NOT implement a new automated/internal-client authentication path.
- Do NOT change `apps/web/src/identity/client.ts`, `apps/web/src/profiles/client.ts`, or `infra/docker/web.conf`; only guard their existing contracts.
- Only wire the trusted-origin collection through existing route checks and add verification.

### Files Expected

**New files:**
- None.

**Modified files:**
- `apps/api/app/modules/auth/routes.py` (use collection for auth origin/CSRF checks)
- `apps/api/app/modules/users/routes.py` (use collection for profile origin/CSRF checks)
- `apps/api/app/modules/auth/tests/test_routes.py` (auth route coverage)
- `apps/api/app/modules/users/tests/test_routes.py` (profile route coverage)
- `tests/integration/test_member_identity.py` (configured-origin integration coverage)

**Must NOT modify:**
- `apps/api/app/modules/auth/service.py` and `apps/api/app/modules/users/service.py` (singular link origin)
- `apps/api/app/bootstrap.py` (storage CORS origin)
- `apps/web/src/identity/client.ts`, `apps/web/src/profiles/client.ts`, and `infra/docker/web.conf` (contract regression hotspots)

## Task T4: Declare runtime origins and update local guidance

> **Status:** not started
> **Verification:** checklist
> **Effort:** s
> **Priority:** high
> **Depends on:** T1, T3
> **Satisfies REQs:** R1, R2, R5, N1
> **Footprint slice:** Modified: `.env.example`, `compose.yaml`, `compose.checks.yaml`, `docs/development.md`
> **High-risk areas touched:** Runtime configuration (M); Check/browser environment (M)

### Description

Declare the trusted-origin list at each runtime boundary so host-browser manual testing and isolated browser checks both work without implicit trust. Update development guidance to document the two approved loopback origins and the production requirement for explicit operator configuration.

### Verification Checklist

- **Development configuration** — inspect rendered `compose.yaml`; expected: API, worker, and scheduler each receive `LAUNCHPAD_TRUSTED_WEB_ORIGINS` containing exactly `http://localhost:8080` and `http://127.0.0.1:8080`.
- **Check configuration** — inspect rendered `compose.checks.yaml`; expected: check runtime contains both host-loopback origins and `http://web:8080`, with no production-only value injected.
- **Example environment** — inspect `.env.example`; expected: the new setting is documented beside `LAUNCHPAD_MAIL_WEB_ORIGIN` and contains only disposable local values.
- **Documentation** — inspect `docs/development.md`; expected: local manual testing names both supported origins, exact port matching, and explicit production configuration.
- **Compose validation** — run the repository’s compose/config validation command; expected: valid configuration with no missing trusted-origin variable.
- **Quality regression** — run the affected settings, security, integration, and browser/check commands; expected: all existing checks pass and no public response contract changes appear.

### Implementation Notes

- **Module(s):** Compose/env/docs runtime boundary.
- **Pattern reference:** Existing `LAUNCHPAD_MAIL_WEB_ORIGIN` declarations and local security guidance in `docs/development.md`.
- **Key decisions:** Explicit environment-specific values; check-only `web:8080`; no automatic localhost trust in production (A1, A4).
- **Libraries:** None.
- **High-risk callouts:** Configuration must be synchronized across API, worker, scheduler, and check services; a missing value should fail startup rather than silently fall back.

### Scope Boundaries

- Do NOT add wildcard origins, arbitrary ports, or production localhost defaults.
- Do NOT alter `LAUNCHPAD_MAIL_WEB_ORIGIN` values or storage CORS behavior.
- Do NOT change application logic; this task only declares runtime values and documents usage.

### Files Expected

**New files:**
- None.

**Modified files:**
- `.env.example` (document local trusted-origin list)
- `compose.yaml` (development API/worker/scheduler values)
- `compose.checks.yaml` (check runtime host and internal browser values)
- `docs/development.md` (manual local and production configuration guidance)

**Must NOT modify:**
- `apps/api/app/shared/config/settings.py`, `apps/api/app/shared/security/csrf.py`, `apps/api/app/modules/auth/routes.py`, and `apps/api/app/modules/users/routes.py` (owned by T1–T3)
- `apps/api/app/bootstrap.py` and service link-generation modules (singular origin boundary)

---

_Generated from `specs/architecture/ARCH-fix-local-identity-origin-validation.md` and `specs/requirements/REQ-fix-local-identity-origin-validation.md`._
_Next step: `/implement T1 from: specs/architecture/ARCH-fix-local-identity-origin-validation.md`_
