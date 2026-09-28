# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: T14 task review |
| **Target** | `specs/tasks/TASKS-add-member-identity-profiles.md` — Task T14 |
| **Date** | 2026-09-24 |
| **Tech Stack** | TypeScript, React, TanStack Query, generated REST/OpenAPI and GraphQL contracts, Vitest |
| **Checks Run** | Task completion/requirements, TypeScript strictness, code quality, security/CSRF, cache invalidation, error handling, upload behavior, test coverage |
| **Checks Skipped** | Backend/database/migrations, UI/accessibility/layout, performance, documentation (outside T14 scope) |
| **Files Changed** | 9 T14 client/hook/test artifacts plus task evidence |
| **Lines Changed** | New identity/profile clients, hooks, and tests; prior workspace contains unrelated T1–T13 changes |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered and T14 footprint scoped
- [x] Tech stack detected: TypeScript/React/TanStack Query/Vitest
- [x] Context read (AGENTS.md, CLAUDE.md, REQ, ARCH, TASKS, and review instructions)
- [x] Triage proposed and developer confirmed
- [x] 3 checks dispatched: completion/requirements; security/cache/errors; TypeScript/quality/tests
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Verdict: Changes requested — not merge-ready

The T14 clients correctly consume generated REST/GraphQL types, send cookie credentials and CSRF headers, and keep server state in TanStack Query. The high-risk cache and upload guarantees are incomplete: account switching can expose prior cached profile data, several required invalidation scenarios are untested, upload lifecycle hooks are absent, and failed mutations can clear valid authenticated state.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion / requirements | 0 | 3 | 1 | 0 | 0 |
| Security / cache / error handling | 0 | 1 | 3 | 0 | 0 |
| TypeScript / code quality / tests | 0 | 0 | 1 | 0 | 0 |
| **Total** | **0** | **4** | **5** | **0** | **0** |

## Findings

### 🟠 High — login retains the previous account’s private profile cache

`apps/web/src/identity/useIdentity.ts:17-23` only writes the new session query. Existing `profiles/*` queries remain cached when a browser signs into a different account without first logging out, so the newly signed-in account can briefly render the prior account’s private viewer/profile/photo data.

**Fix:** remove or invalidate all profile and photo queries on successful login before/with `setQueryData`; add an account-switching regression test.

### 🟠 High — identity invalidation acceptance scenarios are not verified

`apps/web/src/identity/useIdentity.test.tsx:40-47` only checks that logout eventually reports success. It does not seed or inspect session/profile cache state, and there are no tests for verification success, password-reset success, revocation, or failed reset behavior. The task explicitly requires these invalidation semantics.

**Fix:** seed protected query keys, run verify/logout/reset mutations, and assert exact cache removal/invalidation on success and preservation/refetch behavior on failure.

### 🟠 High — privacy invalidation and upload-failure scenarios are not verified

`apps/web/src/profiles/useProfile.test.tsx:40-52` checks only mutation `isSuccess`; it does not assert viewer/public/photo cache reconciliation for update, publish, unpublish, or automatic privacy. No test covers rejected photo creation, failed completion, expired staging, or ensuring no published-image state is introduced.

**Fix:** add cache-seeded publish/unpublish/automatic-private tests and rejected upload/finalization tests asserting typed recoverable errors and no public/photo cache.

### 🟠 High — no TanStack Query upload lifecycle hooks

`apps/web/src/profiles/client.ts:85-105` exposes imperative upload methods, but `apps/web/src/profiles/useProfile.ts:5-39` provides no mutation hook for create/complete/fetch photo. The declared `profileKeys.photo` is never consumed, so upload pending/error state and privacy reconciliation are bypassed by the query layer.

**Fix:** add typed upload mutations (and a photo query where appropriate), wire failure/reconciliation behavior through query invalidation, and test the lifecycle.

### 🟡 Medium — failed logout/reset mutations clear valid local state

`apps/web/src/identity/useIdentity.ts:27-35` and `:48-55` clear session/profile caches in `onSettled`, including CSRF, network, expired-token, or server failures. The server session may remain active while the UI hides it; a failed password reset should not discard a valid current session.

**Fix:** clear all-device/session caches only on successful logout/reset. On failure, retain or refetch session state and surface the error.

### 🟡 Medium — revoked session data can remain alongside a query error

`apps/web/src/identity/useIdentity.ts:9-14` does not clear dependent caches when `currentSession` changes from success to a 401/revocation error. TanStack Query may retain prior data alongside the error, allowing consumers that read `data` directly to show stale protected controls.

**Fix:** remove session/profile caches on unauthorized/revoked responses or enforce an error-aware session selector; add a revocation test.

### 🟡 Medium — GraphQL non-JSON failures escape as raw `SyntaxError`

`apps/web/src/profiles/client.ts:52-66` unconditionally calls `response.json()`. An HTML proxy error, empty 502, or malformed body throws `SyntaxError` instead of the typed `ProfileRequestError` used by REST, so callers cannot reliably show a recoverable failure.

**Fix:** parse through `safeJson`, validate the GraphQL envelope, and normalize non-JSON/malformed responses to `ProfileRequestError`; add a regression test.

### 🟡 Medium — response casts trust unvalidated runtime JSON

`apps/web/src/identity/client.ts:50-51` and `profiles/client.ts:49,62-66` cast arbitrary response JSON directly to generated types. Generated TypeScript only protects compilation; malformed or incompatible server data can reach hooks and fail during field access.

**Fix:** validate required response envelopes/fields at the client boundary or add a runtime schema parser for session/profile/upload responses.

### 🟡 Medium — missing identity request hooks

The identity client supports registration, verification-request, and password-reset-request methods, but `useIdentity.ts` exposes no corresponding mutations. Their pending/error and settled cache behavior is therefore not represented in the query layer and must be added or explicitly deferred to T15.

**Fix:** add the supported request hooks with typed mutation state and tests, or document a deliberate T15 handoff in the task contract.

## Requirement Coverage

| Requirement | Status | Review conclusion |
|---|---|---|
| R3–R7 | Partial | Typed identity actions exist, but verification/reset/revocation cache semantics are not fully implemented or tested. |
| R9–R12 | Partial | Profile mutations and upload clients exist, but upload hooks and privacy/photo cache reconciliation are incomplete. |
| N1 | Partial | Credentials/CSRF are sent, but account-switch and stale-cache paths can expose prior private state. |
| N4 | Partial | Strict TypeScript passes; high-risk client-state acceptance scenarios are under-tested. |

## Manual Checks Required

- [ ] Verify account switching in a browser with two authenticated accounts and inspect viewer/profile/photo state during transition.
- [ ] Verify a real expired upload and failed finalization leave no public/photo cache state.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

- Clear protected profile caches on successful login/account switching.
- Add identity, privacy, and upload cache regression tests matching all T14 high-risk scenarios.
- Provide TanStack Query upload lifecycle hooks.

### Should Address (🟡 Medium)

- Make logout/reset cache clearing success-only and clear state on session revocation.
- Normalize GraphQL/non-JSON responses and validate runtime response envelopes.
- Add identity request hooks or explicitly defer them to T15.

### Nice to Have (💭 Low)

- None identified.

---
*Generated by Review — 2026-09-24*
