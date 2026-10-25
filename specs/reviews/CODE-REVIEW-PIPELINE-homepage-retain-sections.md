# Review Report

> **Follow-up:** The findings below were fixed in the working tree on 2026-10-25; see **Finding Resolutions** at the end for changes and verification evidence.

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: `ARCH-homepage-retain-sections` |
| **Target** | Commit `da867a6` (`feat(home): restore sections below launches (T1)`) |
| **Date** | 2026-10-25 14:17 UTC |
| **Tech Stack** | React 19, TypeScript strict, Vite, Vitest |
| **Checks Run** | Task Completion, Code Quality & Conventions, Test Coverage & Quality, React / Next.js Patterns, TypeScript Strictness, Accessibility, Requirement Coverage |
| **Checks Skipped** | Security (no auth/security surface changed); Performance (static composition); Error Handling (existing query errors unchanged); Documentation (no product docs changed); Config/Dependencies (none changed); Runtime Behavior (no runtime primitives changed); Async Patterns (no async code changed); Express Patterns (not used); Database Patterns (no database code); Migration (no contract or migration changes) |
| **Files Changed** | 8 |
| **Lines Changed** | +719 / -53 |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered (8 files, 772 changed lines)
- [x] Tech stack detected: React 19, TypeScript strict, Vite, Vitest
- [x] Context read (`AGENTS.md`, linked REQ, ARCH, and TASKS)
- [x] Triage proposed and developer confirmed
- [x] 7 checks dispatched: Task Completion, Code Quality, Test Coverage, React Patterns, TypeScript Strictness, Accessibility, Requirement Coverage
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Verdict: ⚠️ PASS WITH FINDINGS

The homepage composition follows the approved section order, keeps the supporting content visible in feed states, and preserves the archive heading default. The reported frontend suite, lint, typecheck, and build passed in a temporary verification copy; the UI screenshots cover 320px and 1440px layouts. One medium accessibility issue remains in the heading outline, and keyboard focus/order still needs a manual check.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task Completion | 0 | 0 | 0 | 1 | 2 |
| Code Quality & Conventions | 0 | 0 | 0 | 0 | 0 |
| Test Coverage & Quality | 0 | 0 | 1* | 0 | 0 |
| React / Next.js Patterns | 0 | 0 | 0 | 0 | 0 |
| TypeScript Strictness | 0 | 0 | 0 | 0 | 0 |
| Accessibility | 0 | 0 | 1* | 0 | 1 |
| Requirement Coverage | 0 | 0 | 1* | 0 | 5 |
| **Unique total** | **0** | **0** | **1** | **1** | **5** |

\* These checks refer to the same heading semantics/test coverage issue (#1); it is counted once in the unique total.

## Task Completion

**REQs:** 5/7 verified · 2 manual

| REQ | Status | Evidence |
|-----|--------|----------|
| R1 | ✅ Verified | Homepage test asserts section order; application test asserts the intended H1/H2 through its mock; screenshots show the order. See Finding #1 for a direct assertion of `LaunchDiscovery`'s H1 rendering. |
| R2 | ✅ Verified | `HomePage.test.tsx` asserts the hero copy, UTC note, guest links, and existing founder/reviewer destinations. |
| R3 | ✅ Verified | Homepage test asserts all four step headings; screenshots show the explanatory cards in order. |
| R4 | ✅ Verified | Homepage test asserts the reassurance heading and section order; screenshots show the panel and shared footer after it. |
| R5 | ✅ Verified | `HomePage.test.tsx` covers loading, empty, and error mock states and asserts the supporting sections remain rendered; screenshot shows the error state with the remaining content. |
| R6 | ⚠️ Manual | Screenshots show 320px and 1440px layouts. Keyboard focus/visibility and measured horizontal overflow were not separately evidenced. |
| N1 | ⚠️ Manual | Heading structure is asserted through component mocks; actual keyboard traversal and focus visibility were not evidenced. |

**Verification Plan (ui):** 8/9 verified; one manual item remains.

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 1 | Homepage order and content | ✅ Verified | Component assertions and 320px/1440px screenshots. |
| 2 | Heading outline and keyboard order | ⚠️ Manual | H1/H2 expectation is asserted through mocks; no keyboard traversal evidence. |
| 3 | Feed-state independence | ✅ Verified | Homepage component tests cover loading, empty, and error states; error screenshot confirms static sections remain. |
| 4 | Responsive layout | ✅ Verified | Screenshots at 320px and 1440px show stacked/natural layout without visible horizontal overflow. |
| 5 | Account and outage behavior | ✅ Verified | Existing guest/member/reviewer/session-failure/outage tests remain; implementation reported the full suite passed. |
| 6 | Archive heading regression | ✅ Verified | Archive test asserts default H2 and adjacent-date navigation; implementation reported the full suite passed. |
| 7 | Public shell and route regression | ✅ Verified | Existing application, shell, and routing tests cover the public frame and routes; implementation reported the full suite passed. |
| 8 | Application homepage assertion | ✅ Verified | App test asserts Today’s launches H1 and restored hero H2 while retaining outage coverage. |
| 9 | Frontend quality gates | ✅ Verified | Implementation reported 221 tests, typecheck, lint, build, and Prettier passing in a temporary working-tree copy. |

**Change Footprint Adherence:** The six modified implementation/test files match the task's expected files. No Must-NOT-modify file was touched. The commit also contains the expected ARCH and TASKS artifacts. The linked REQ exists in the current working tree but is untracked and absent from commit `da867a6`; it should be included in the eventual PR source chain.

**Areas of Impact (M/H risk):**

| Area | Risk | Callout addressed? | Regression-guard tests? |
|------|------|-------------------|--------------------------|
| Public homepage composition | M | ✅ | Section order and feed states asserted; responsive screenshots captured. |
| Shared launch discovery heading | M | ✅ | Archive default H2 is asserted; homepage passes H1. Direct component H1 assertion is missing (Finding #1). |

**Scope:** ✅ Respected

**ARCH Decisions:** ✅ Followed

### Task Completion Finding

| # | Severity | File | Line | Issue | Recommendation |
|---|----------|------|------|-------|----------------|
| 2 | 💭 Low | `specs/architecture/ARCH-homepage-retain-sections.md` | 5 | The committed ARCH links `specs/requirements/REQ-homepage-retain-sections.md`, but that REQ is untracked and not part of the reviewed commit. A fresh checkout of this commit cannot follow the stated source chain. | Include the linked REQ in the eventual PR/commit artifact set, while keeping unrelated untracked specs out. |

## Code Quality & Conventions

**Result:** ✅ No findings.

**Files reviewed:** `apps/web/src/App.test.tsx`, `apps/web/src/home/HomePage.test.tsx`, `apps/web/src/home/HomePage.tsx`, `apps/web/src/home/home.css`, `apps/web/src/launches/LaunchDiscovery.tsx`, `apps/web/src/launches/LaunchScreens.test.tsx`.

## Test Coverage & Quality

Finding #1 is shared with Accessibility and Requirement Coverage; it is not counted as a separate issue here.

### Coverage Checklist

- [x] `HomePage.tsx` — section order, retained content, feed states, account/session and outage behavior asserted.
- [x] `LaunchDiscovery.tsx` — archive default H2 asserted; direct H1 rendering is not asserted → Finding #1.
- [x] `home.css` — 320px and desktop layouts inspected in screenshots; this remains visual evidence.
- [x] `App.test.tsx` — homepage H1/H2 and outage behavior asserted using a mocked discovery component.
- [x] `HomePage.test.tsx` — homepage order and loading/empty/error independence asserted using a mocked discovery component.
- [x] `LaunchScreens.test.tsx` — archive default H2 and navigation asserted.

## React / Next.js Patterns

**Result:** ✅ No findings.

**Files reviewed:** `apps/web/src/home/HomePage.tsx`, `apps/web/src/launches/LaunchDiscovery.tsx`, and related tests.

### Tracing Notes

- `App` renders `HomePage` on `/` and `PublicLaunchArchive` on archive routes; both are client-rendered Vite components.
- `HomePage` calls hooks unconditionally, memoizes its client by `identityClient`, and passes `headingLevel="h1"`.
- Archive composition omits the prop, preserving the H2 default.
- `LaunchDiscovery` calls ranking hooks unconditionally; the new heading option does not affect hook order or closures.

## TypeScript Strictness

**Result:** ✅ No findings.

**Files reviewed:** the five changed TypeScript/TSX files.

### Coverage Checklist

- [x] `App.test.tsx` — typed mock prop; no new unsafe cast or suppression.
- [x] `HomePage.test.tsx` — explicit state union and heading prop type.
- [x] `HomePage.tsx` — existing session/navigation types preserved; H1 prop is type-compatible.
- [x] `LaunchDiscovery.tsx` — optional `"h1" | "h2"` prop narrows correctly and defaults to `"h2"`.
- [x] `LaunchScreens.test.tsx` — no new unsafe assertion or suppression.

## Accessibility

### Findings

| # | Severity | File | Line | Issue | WCAG | Recommendation |
|---|----------|------|------|-------|------|----------------|
| 1 | 🟡 Medium | `apps/web/src/launches/LaunchDiscovery.tsx` | 110 | With `headingLevel="h1"`, the empty-state heading remains H3; launched product titles are also H3 in `RankedLaunchCard.tsx:48`. On the homepage this skips H2 between the discovery H1 and those child titles. | WCAG 1.3.1 — Info and Relationships | Make the discovery child-heading levels follow the selected level (H2 under homepage H1, H3 under archive H2), including the product card title; add a direct component assertion for H1. This may require updating the ARCH/TASKS footprint for `RankedLaunchCard.tsx`. |

**Review comment:** Screen-reader users navigating by headings may encounter an H1 followed directly by H3 titles in the homepage launch section. Could the empty-state and product-card headings use H2 when the discovery heading is H1 while retaining H3 for archive pages? Thoughts?

### Manual Verification

- Keyboard focus order/visibility and screen-reader heading navigation were not verified in the browser; the screenshots do not establish those behaviors.

### Coverage Checklist

- [x] `HomePage.tsx` — homepage semantic order and H1/H2 structure; keyboard behavior remains manual.
- [x] `LaunchDiscovery.tsx` — section labeling and dynamic title; child headings skip H2 on the homepage → Finding #1.
- [x] `home.css` — narrow and desktop layout evidence reviewed; global visible-focus styling exists.
- [x] `RankedLaunchCard.tsx` — existing H3 is appropriate under archive H2, but not under homepage H1 → Finding #1.

## Requirement Coverage

**Suite run:** Not executed — static analysis only; assertions were audited, not run.

**Criteria:** 5/12 covered · 2 weak · 5 manual

| Req / Edge | Criterion (abridged) | Test evidence | Run | Status |
|------------|----------------------|---------------|-----|--------|
| R1 | Today’s launches first, then retained sections and footer | `HomePage.test.tsx` asserts section order; `App.test.tsx` asserts H1/H2 through mocks; screenshots show visual order/footer. Actual discovery H1 rendering is not directly tested. | 🛑 Static only | 🟠 Weak — Finding #1 |
| R2 | Hero copy, account actions, UTC note, and destinations retained | `HomePage.test.tsx` asserts copy, hrefs, and workspace routing. | 🛑 Static only | ✅ Covered |
| R3 | Four launch steps and explanatory content remain | Test asserts all four step headings; screenshots show step text/cards. | 🛑 Static only | ⚠️ Manual — UI evidence |
| R4 | Reassurance panel and footer follow the process with prior content | Test asserts reassurance heading and section order; screenshots show panel and footer placement/content. | 🛑 Static only | ⚠️ Manual — UI evidence |
| R5 | Retained sections remain during feed loading/empty/error states | `HomePage.test.tsx` asserts retained sections under all three mock states; `LaunchScreens.test.tsx` covers actual discovery states. | 🛑 Static only | ✅ Covered |
| R6 | 320px/desktop readability, no horizontal scrolling, keyboard focus | Screenshots show 320px and 1440px layouts; keyboard/focus was not exercised and overflow was not measured. | — | ⚠️ Manual |
| N1 | Keyboard order and meaningful headings/landmarks | Tests assert headings through the component mock; no keyboard traversal evidence; child heading hierarchy issue in Finding #1. | 🛑 Static only | ⚠️ Manual |
| Edge: empty | Empty day retains supporting sections | `HomePage.test.tsx` and actual discovery tests assert empty-state behavior. | 🛑 Static only | ✅ Covered |
| Edge: failure | Retryable feed error retains supporting sections | Homepage mock test and actual discovery error/retry tests assert behavior. | 🛑 Static only | ✅ Covered |
| Edge: loading | Supporting sections remain during loading | `HomePage.test.tsx` and actual discovery loading test assert behavior. | 🛑 Static only | ✅ Covered |
| Edge: narrow viewport | Sections stack without horizontal overflow | 320px screenshot shows stacked content; overflow not programmatically checked. | — | ⚠️ Manual |
| Edge: signed-in member | Same public feed and informational content remain for signed-in user | Member test asserts workspace action; the retained informational sections are not asserted in that member-specific test. | 🛑 Static only | 🟠 Weak — add section assertions to the signed-in case |

**Orphan tests:** None identified; session, outage, archive-navigation, and feed-state tests map to the linked requirement and regression scenarios.

**Orphan files:** None among the changed production files; each maps to R1–R6/N1 through ARCH/TASKS.

## Manual Checks Required

- [ ] On the running homepage, use Tab from the start of the page and confirm focus follows visual order through launches, hero actions, workflow links/actions, and footer with a visible focus indicator.
- [ ] Inspect the heading outline with assistive technology after addressing Finding #1; verify H1/H2/H3 nesting on both homepage and archive.
- [ ] Confirm the requirement artifact is included in the eventual PR source chain; it is currently untracked and absent from the reviewed commit.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

None.

### Should Address (🟡 Medium)

1. Fix the homepage discovery child-heading hierarchy and add a test that renders `LaunchDiscovery` with `headingLevel="h1"`; expand ARCH/TASKS if changing `RankedLaunchCard.tsx` is needed.

### Nice to Have (💭 Low)

1. Include the linked REQ artifact in the eventual PR/commit set.
2. Assert the retained static sections in the signed-in member homepage test.

---
*Generated by Review — 2026-10-25 14:17 UTC*

## Finding Resolutions

| Finding | Resolution | Verification |
|---------|------------|--------------|
| Homepage heading hierarchy and direct component coverage | `LaunchDiscovery` renders its empty-state title as H2 when the section title is H1. `RankedLaunchCard` accepts an optional H2/H3 title level; the homepage passes H2 and archive/default usage remains H3. | `LaunchScreens.test.tsx` renders the actual discovery component for empty and populated H1 cases and confirms H2 descendants. `RankedLaunchCard.test.tsx` confirms default H3 and explicit H2. |
| Keyboard focus order and visibility lacked browser evidence | Extended the real-page Playwright scenario to assert homepage H1/H2 levels, Tab from “Create your account” to “Sign in,” reverse Tab, and a visible keyboard focus outline. | Focused Playwright browser test passed against the locally served build. |
| Signed-in homepage content was not asserted | The signed-in member test now checks the retained hero, process heading, all four steps, and reassurance section. | `HomePage.test.tsx` passed. |
| Linked REQ absent from the reviewed commit | The linked `REQ-homepage-retain-sections.md` is included in the follow-up source artifact set. | Present in the follow-up working tree. |

**Follow-up checks:** All 33 frontend test files passed (223 tests); TypeScript typecheck, ESLint, and production build passed. The focused browser keyboard/focus test passed. An initial browser attempt served from the repository root and returned 404; the successful run served `apps/web/dist` from the web app directory.
