# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: ARCH-add-member-identity-profiles |
| **Target** | T16 — Private editor and public profile UI |
| **Date** | 2026-09-24 |
| **Tech Stack** | React 19, TypeScript strict, TanStack Query, Vite, Vitest, Playwright |
| **Checks Run** | Task completion, requirement coverage, code quality, test coverage, security/privacy, accessibility, React patterns, TypeScript, async/runtime, performance |
| **Checks Skipped** | Database/migration/Express/config-dependency checks — no applicable T16 changes |
| **Files Changed** | 6 implementation/test/task-scope files plus existing T15 browser surface |
| **Lines Changed** | Approximately +650 / -22 in the T16 footprint, including new profile UI and tests |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered and T16 scope inspected
- [x] Tech stack detected: React, TypeScript, TanStack Query, Vitest, Playwright
- [x] Context read (AGENTS.md, CLAUDE.md, REQ, ARCH, TASKS)
- [x] Triage proposed and developer confirmed
- [x] 3 review bundles dispatched: UI/security, quality/tests, task/requirements
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to specs/reviews/

## Verdict: ❌ FAIL

T16 adds a coherent private editor/public profile surface with generated clients, validation guidance, gated photo rendering, and passing automated checks. It is not merge-ready because the App conditionally changes its hook order during SPA navigation, ordinary profile saves can delete an existing photo, and the required privacy/upload lifecycle evidence is incomplete.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| React/runtime | 1 | 0 | 0 | 0 | 0 |
| Security/privacy | 0 | 2 | 0 | 0 | 0 |
| Task completion/requirements | 0 | 2 | 1 | 0 | 0 |
| Accessibility | 0 | 0 | 1 | 0 | 0 |
| Test coverage/quality | 0 | 1 | 1 | 0 | 0 |
| **Total** | **1** | **5** | **3** | **0** | **0** |

## Findings

### 🔴 Critical — `useConnectivity` is conditionally called

**File:** `apps/web/src/App.tsx:19-30`

`useConnectivity()` is called only when `path === "/"`. Since `path` changes during SPA navigation, moving between `/profile`/`/public/...` and `/` changes the number and order of hooks invoked by `App`, which can trigger React’s “Rendered more/fewer hooks than during the previous render” runtime error.

**Fix:** Call `useConnectivity` unconditionally before the route branch, or isolate the connectivity page into a child component with stable hook ordering. Add an in-app SPA transition regression test.

### 🟠 High — Normal profile edits explicitly clear existing photos

**File:** `apps/web/src/profiles/ProfileScreens.tsx:99-114`

Every save sends `photo_upload_id: photoUploadId`, while `photoUploadId` starts as `null`. The API interprets an explicit `null` as remove-photo, so editing only a name, bio, or link deletes the current photo and may automatically make a published profile private.

**Fix:** Omit `photo_upload_id` when no new upload/removal was explicitly selected. Add a regression test proving a text-only edit retains an existing photo.

### 🟠 High — Required display name prevents the required-field removal flow

**File:** `apps/web/src/profiles/ProfileScreens.tsx:179-184`

The display-name input has HTML `required`, preventing an owner from saving an incomplete private draft and preventing a published owner from removing the display name so the server can perform the required automatic-private transition.

**Fix:** Allow incomplete private drafts to save; use the checklist as guidance and let the server enforce publication completeness. Add an auto-private removal test.

### 🟠 High — T16 checklist is marked complete without the required UI evidence

**Task:** `specs/tasks/TASKS-add-member-identity-profiles.md` T16

T16 is marked `done`, but its seven UI checklist items remain unchecked. Current tests cover editor rendering, HTTPS guidance, public rendering, and unsupported MIME rejection; they do not verify authenticated owner editing, valid upload/finalization, automatic privacy notices, unpublish/republish, public withdrawal after privacy changes, or keyboard focus after status changes.

**Fix:** Add the missing component/browser evidence, or leave T16 in progress until the UI checklist is actually observed and recorded.

### 🟠 High — Browser evidence does not exercise the owner privacy lifecycle

**File:** `tests/browser/member-identity.spec.ts:3-31`

The browser flow checks identity navigation, one unavailable public route, and connectivity restoration. It does not drive the owner editor, publish/unpublish, photo lifecycle, automatic-private notice, or public-content withdrawal.

**Fix:** Add an authenticated owner flow and visitor assertions after unpublish/required-field removal, including keyboard interaction with visibility/status controls.

### 🟡 Medium — Profile status/error messages lack control associations

**File:** `apps/web/src/profiles/ProfileScreens.tsx:99-130, 358-374`

Save, upload, publish, and auto-private messages are standalone live regions. They are not associated with the affected form/action controls via stable IDs and `aria-describedby`/`aria-invalid`, so screen-reader users receive generic feedback without a clear target.

**Fix:** Associate field/action errors with their controls while retaining the global privacy notice as an `aria-live` status.

### 🟡 Medium — Owner/private behavior and photo safety are weakly evidenced

**Files:** `apps/web/src/profiles/ProfileScreens.test.tsx`, `tests/browser/member-identity.spec.ts`

No test demonstrates an authenticated unverified owner editing privately, failed finalization leaving no published image, valid upload-to-complete behavior, or that staging/signed upload URLs never enter the DOM.

**Fix:** Add focused tests for owner-vs-outsider behavior, upload failure/expiry, and DOM exclusion of staging URLs.

## Manual Checks Required

- [ ] Verify the full editor at mobile and desktop widths with keyboard-only publish/unpublish and status-notice focus behavior.
- [ ] Verify an authenticated unverified owner can edit privately while an outsider sees no private fields/photo.
- [ ] Verify a published profile becomes inaccessible immediately after removing a required field.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

1. Stabilize App hook ordering across SPA routes.
2. Preserve existing photos on text-only saves and permit incomplete draft saves.
3. Complete the T16 UI checklist with authenticated privacy/upload lifecycle evidence.

### Should Address (🟡 Medium)

1. Associate profile status/errors with their controls.
2. Add owner/private and staging-photo safety tests.

---
*Generated by Review — 2026-09-24*
