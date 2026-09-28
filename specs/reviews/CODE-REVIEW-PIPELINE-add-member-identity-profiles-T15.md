# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: ARCH-add-member-identity-profiles |
| **Target** | T15 — Accessible account and recovery screens |
| **Date** | 2026-09-24 |
| **Tech Stack** | React 19, TypeScript strict, TanStack Query, Vite, Vitest, Playwright |
| **Checks Run** | Task completion, requirement coverage, code quality, test coverage, security, error handling, TypeScript, async/runtime behavior, React patterns, accessibility |
| **Checks Skipped** | Database/migration/Express/config-dependency checks — no applicable backend, schema, or dependency changes |
| **Files Changed** | T15 identity UI, app shell, styles, browser test, task evidence |
| **Lines Changed** | T15 scope includes new identity UI and browser coverage; exact repository diff count is obscured by pre-existing untracked work |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered and T15 scope inspected
- [x] Tech stack detected: React, TypeScript, TanStack Query, Vitest, Playwright
- [x] Context read (AGENTS.md, CLAUDE.md, REQ, ARCH, TASKS)
- [x] Triage proposed and developer confirmed
- [x] 3 review bundles dispatched: UI/security, quality/tests, task/requirements
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to specs/reviews/

## Verdict: ❌ FAIL

T15 has a useful accessible shell and passing component/browser regression checks, but it is not merge-ready. The sign-out control does not revoke the server session, verification/resend failures can become unhandled promise rejections, and the top-level route owner does not reliably restore the connectivity page after navigation to `/`. The task checklist is also marked complete beyond the evidence currently supplied.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion / requirements | 0 | 1 | 2 | 0 | 0 |
| Security | 0 | 1 | 0 | 0 | 0 |
| Error handling / async | 0 | 2 | 1 | 0 | 0 |
| React / runtime | 0 | 1 | 0 | 0 | 0 |
| Accessibility | 0 | 0 | 1 | 0 | 0 |
| Test coverage | 0 | 1 | 1 | 0 | 0 |
| **Total** | **0** | **6** | **5** | **0** | **0** |

## Findings

### 🟠 High — Sign-out never revokes the session

**File:** `apps/web/src/identity/Screens.tsx:362-375`

The profile landing page’s “Sign out” button only calls `navigate("/")`; it never invokes `client.logout()` or `useLogout`. The HTTP-only session remains valid, so the UI claims the member signed out while the server still authenticates the cookie. This violates R3 and the session-revocation invariant.

**Fix:** Use the logout mutation, await successful revocation/cache clearing, then navigate to the sign-in or connectivity route. Add a test asserting the logout request and unauthenticated follow-up.

### 🟠 High — Verification and resend failures create unhandled rejections

**Files:** `apps/web/src/identity/Screens.tsx:220-223, 249-255`

`VerifyPage.submit()` awaits `verify.mutateAsync()` without catching rejection, and the resend button calls `void resend.mutateAsync()` without a rejection handler. Invalid/expired/rate-limited/network failures can therefore surface as unhandled promise rejections instead of the safe status messages already rendered by the component.

**Fix:** Catch both mutation promises and preserve generic error/status messaging. Add rejected verification and resend interaction tests.

### 🟠 High — Root route restoration is broken after identity navigation

**Files:** `apps/web/src/App.tsx:17-21`, `apps/web/src/identity/Screens.tsx:31-47`

`App` selects the connectivity shell from `window.location.pathname` only during its own render, while `navigate()` dispatches `popstate` only to `IdentityRoutes`. Navigating from an identity route to `/` does not cause `App` to re-evaluate, so the identity tree remains mounted and `/` falls back to sign-in rather than the existing connectivity page.

**Fix:** Make the top-level route owner subscribe to `popstate`, use one routing state owner, or perform a full same-origin navigation after logout. Add a browser assertion that `/` restores the connectivity page.

### 🟠 High — T15 UI verification evidence is incomplete

**Task:** `specs/tasks/TASKS-add-member-identity-profiles.md` T15 checklist

The checklist is fully marked `[x]`, but current evidence covers only labels/focus, registration generic copy, static reset landing, route navigation, and connectivity. It does not verify known-vs-unknown reset equivalence, explicit verification POST behavior, expired/superseded/rate-limited paths, successful sign-in/reset navigation, mutation error/loading announcements, desktop behavior, or the same-origin Secure-cookie flow.

**Fix:** Add component/browser assertions or provide explicit manual UI evidence for each unchecked seam; do not mark the checklist complete until those observations are recorded.

### 🟡 Medium — Token values remain in browser URLs after use

**Files:** `apps/web/src/identity/Screens.tsx:216-219, 311-315`

Verification/reset tokens remain in browser history and the address bar after the page reads them. One-use recovery values can consequently be exposed through copied URLs, history, or referrer behavior.

**Fix:** Replace the URL with a token-free path immediately after reading the token while retaining it only in transient component state; never include it in errors or analytics.

### 🟡 Medium — Form errors are not associated with fields

**File:** `apps/web/src/identity/Screens.tsx` form fields and `FormMessage`

Errors are standalone live regions without `aria-describedby`/`aria-invalid` associations, and sign-in uses `noValidate`, disabling native required-field feedback. This does not satisfy the T15 field-error accessibility expectation for malformed submissions.

**Fix:** Associate field and summary errors with inputs, expose invalid state, and either retain native validation or implement equivalent accessible client guidance.

### 🟡 Medium — Mutation interaction coverage is too narrow

**Files:** `apps/web/src/identity/Screens.test.tsx`, `tests/browser/member-identity.spec.ts`

Tests do not exercise sign-in success/error, verification success/error, resend rejection, recovery rejection, reset success navigation, or sign-out/session invalidation. The current browser test is navigation-focused, so the high-risk failures above remain undetected.

**Fix:** Add mutation outcome tests and an authenticated lifecycle browser path.

### 🟡 Medium — Task footprint and evidence do not reconcile

**Task:** T15 Files Expected

The task lists `apps/web/src/main.tsx`, `apps/web/package.json`, and `package-lock.json` as possible modified files, but the implementation did not touch them. Either document why no changes were required or update the generated task artifact through the normal workflow; do not leave the scope record ambiguous.

## Manual Checks Required

- [ ] Confirm desktop and mobile visual hierarchy, focus order, and error announcement behavior for all five identity screens after the fixes.
- [ ] Confirm same-origin Secure-cookie behavior in the isolated browser environment.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

1. Implement real server-side sign-out and cache/session cleanup.
2. Catch verification and resend mutation failures.
3. Fix top-level route ownership so `/` restores connectivity.
4. Complete T15 UI verification evidence and mutation lifecycle tests.

### Should Address (🟡 Medium)

1. Remove tokens from the URL after reading/submitting them.
2. Associate errors with form controls and preserve accessible validation.
3. Reconcile the task footprint record.

---
*Generated by Review — 2026-09-24*
