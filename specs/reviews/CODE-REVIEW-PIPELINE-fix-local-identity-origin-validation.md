# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: `ARCH-fix-local-identity-origin-validation` |
| **Target** | `specs/architecture/ARCH-fix-local-identity-origin-validation.md` |
| **Date** | 2026-09-26 |
| **Tech Stack** | Python 3.12, FastAPI, Pydantic, SQLAlchemy, pytest, Docker Compose, React/TypeScript/Vitest/Playwright |
| **Checks Run** | Task completion, requirement coverage, code quality, security, test coverage, error handling, configuration/dependencies, documentation |
| **Checks Skipped** | Database/migration, performance, React/TypeScript/accessibility/runtime/async/Express, general migration review — no applicable changes in this slice |
| **Files Changed** | 14 |
| **Lines Changed** | +1609 / -13 |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered (14 scoped files, +1609/-13 lines)
- [x] Tech stack detected
- [x] Context read (REQ, ARCH, TASKS, AGENTS.md, CLAUDE.md)
- [x] Triage proposed and developer confirmed
- [x] 3 grouped reviewer checks dispatched: task/requirements, security/configuration, quality/tests/error/docs
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Verdict: ❌ FAIL

The implementation has a sound architectural boundary and the quality pipeline passes, including 157 backend/integration tests, 38 web tests, contracts, builds, security, and browser checks. However, the declared T3 acceptance plan is not fully verified: several identity actions, exact HTTP rejection contracts, and state-safety guarantees lack route-level evidence. These are merge-blocking completion gaps for a security-sensitive origin change.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion / requirement coverage | 0 | 3 | 3 | 0 | 0 |
| Security / configuration | 0 | 0 | 1 | 1 | 0 |
| Code quality / tests / errors / docs | 0 | 1 | 0 | 0 | 0 |
| **Total** | **0** | **4** | **3** | **1** | **0** |

## Task Completion / Requirement Coverage

| # | Severity | File | Line | Issue | Recommendation |
|---|----------|------|------|-------|----------------|
| 1 | 🟠 High | `tests/integration/test_member_identity.py` | 33–73 | T3 verification covers registration, login, session, and logout for each origin, but not verification requests/verification, password-reset request/reset, or successful profile mutations from either approved origin. | Add success-path integration coverage for every auth/profile action named in R1/R2, using both `localhost:8080` and `127.0.0.1:8080`. |
| 2 | 🟠 High | `apps/api/app/modules/auth/tests/test_routes.py` 95–124; `apps/api/app/modules/users/tests/test_routes.py` 52–70 | — | R3/R4/N1 require the exact generic HTTP rejection contract, but route tests assert only status or absence of a traceback; primitive tests assert only exception type. | Assert `403` and exactly `{"detail":"request rejected"}` for missing and untrusted origins at auth/profile HTTP boundaries. |
| 3 | 🟠 High | Auth/profile route tests and integration fixtures | — | N2 requires rejected registration, recovery, and profile mutations to leave account/session/challenge/profile/outbox state unchanged; no rejected HTTP request is followed by database state assertions. | Add rejected-request snapshots/assertions proving no user-visible state or outbox rows are created or changed. |
| 4 | 🟡 Medium | `apps/api/app/shared/config/tests/test_settings.py` | T1 test section | T1 declares a singular-link-origin regression guard for auth/users services and bootstrap, but settings tests do not assert generated URLs or storage provisioning still use singular `mail_web_origin`. | Add a focused regression assertion or explicitly relocate the guard to T3 and record it there. |
| 5 | 🟡 Medium | `apps/api/app/shared/security/tests/test_identity_primitives.py` | T2 test section | T2 declares compatibility coverage for `check_origin`/`check_csrf` aliases, but tests call only `validate_origin`/`require_csrf` directly. | Invoke both aliases explicitly with valid and invalid cases. |
| 6 | 🟡 Medium | `specs/tasks/TASKS-fix-local-identity-origin-validation.md` | 240–247 | T4 is marked done but its checklist records expected outcomes only; actual Compose/config/quality command evidence is not captured in the task artifact. | Add command/output evidence or link the quality-run evidence to the task record before closing the task. |

### Review Comments

- **Finding 1:** I noticed the new parameterized integration test proves the shared auth session path across origins, but the task’s own plan names recovery, verification, and profile mutation success paths too. Those routes could still be wired differently. Would it make sense to add one authenticated/fixture-backed success assertion per action family for both loopback origins?
- **Finding 2:** The generic response is a privacy/security contract, not just a status code. Would it make sense to assert the exact JSON body at the route boundary for missing and mismatched origins?
- **Finding 3:** Origin rejection is required to happen before persistence. Could the tests issue rejected requests and then query the relevant tables/outbox so a future ordering regression cannot pass unnoticed?

### Coverage Checklist

- [x] `apps/api/app/shared/config/settings.py` — parsing, normalization, malformed values, production isolation ✅
- [x] `apps/api/app/shared/security/csrf.py` — collection matching, missing/mismatch rejection, CSRF ordering ✅
- [x] Auth/profile route modules — collection wiring ✅; complete action success and exact rejection/state assertions ⚠️ → Findings 1–3
- [x] Runtime Compose/env/docs — explicit values and quality pipeline ✅; task artifact evidence incomplete ⚠️ → Finding 6

## Security / Configuration

| # | Severity | File | Line | Issue | Recommendation |
|---|----------|------|------|-------|----------------|
| 7 | 🟡 Medium | `apps/api/app/shared/config/settings.py` | 224–231 | Production enforces HTTPS for `mail_web_origin` and upload URLs but not for `trusted_web_origins`; documentation says production origins must be HTTPS, yet `http://...` can be configured and trusted. | Reject non-HTTPS trusted origins when `environment == "production"`, with a settings test. |
| 8 | 💭 Low | `apps/api/app/shared/config/settings.py` | 89–99 | The parser accepts some malformed host strings such as `http://foo bar:8080` because it checks only that a hostname exists. | Reject whitespace/control characters and validate hostname syntax strictly. |

### Review Comments

- **Finding 7:** I noticed the production safety checks protect the singular mail/upload URLs but omit the new browser allowlist. Would it make sense to enforce HTTPS for every production trusted origin so the documented deployment invariant is enforced at startup?
- **Finding 8:** This is low risk because browsers will not normally emit such an origin, but strict hostname validation would align the parser with the fail-closed malformed-entry requirement.

### Coverage Checklist

- [x] Exact scheme/host/port matching ✅
- [x] Missing/untrusted origin rejection ✅
- [x] Generic route error mapping ✅
- [x] Production/local configuration separation ✅; production HTTPS enforcement ⚠️ → Finding 7
- [x] Malformed URL rejection ✅ for common components; hostname strictness ⚠️ → Finding 8

## Code Quality / Tests / Errors / Documentation

**Result:** No additional high-confidence findings beyond Findings 1–6. Ruff, mypy, backend/integration tests, web checks, contract generation, builds, security scanning, and browser checks all passed during implementation verification.

### Coverage Checklist

- [x] Naming, imports, type annotations, and module boundaries ✅
- [x] Error propagation and generic client responses ✅
- [x] Test isolation and integration execution ✅, with acceptance-depth gaps recorded above
- [x] Documentation reflects local and production configuration ✅

## Manual Checks Required

- [ ] In a real production-like deployment, confirm `LAUNCHPAD_TRUSTED_WEB_ORIGINS` contains only intended HTTPS origins and excludes localhost unless deliberately approved.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

1. Add success-path coverage for verification, recovery, and profile mutations from both approved loopback origins.
2. Assert the exact generic `403` response body for missing/untrusted origins.
3. Assert rejected HTTP requests leave account, session, challenge, profile, and outbox state unchanged.

### Should Address (🟡 Medium)

4. Add or relocate the singular `mail_web_origin` regression guard.
5. Add explicit alias compatibility tests.
6. Record T4 checklist command evidence in the task/review record.
7. Enforce HTTPS for production trusted origins.

### Nice to Have (💭 Low)

8. Tighten hostname validation for malformed configured origins.

---
*Generated by Review — 2026-09-26*
