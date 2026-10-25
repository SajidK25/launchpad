# Tasks

## Task T1: Restore Homepage Sections Below Today’s Launches

> **Status:** done
> **Verification:** ui
> **Effort:** s
> **Priority:** medium
> **Depends on:** None
> **Satisfies REQs:** R1, R2, R3, R4, R5, R6, N1
> **Footprint slice:** Modified: `HomePage.tsx`, `home.css`, `LaunchDiscovery.tsx`, `RankedLaunchCard.tsx`, `HomePage.test.tsx`, `App.test.tsx`, `LaunchScreens.test.tsx`, `RankedLaunchCard.test.tsx`, `tests/browser/frontend-accessibility.spec.ts`
> **High-risk areas touched:** Public homepage composition (M); shared launch discovery heading behavior (M)

### Description

Restore the previous homepage hero and account actions, four-step launch-process section, and reassurance panel beneath the existing Today’s launches section. Preserve the current feed, authentication, outage, and shared-shell behavior while making the discovery heading the homepage H1 and leaving archive discovery at its current H2 level.

### Verification Checklist

- **Homepage section order and content** — open `/`; expected: the PUBLIC RELEASES / Today’s launches section is first, followed by the prior hero and account actions, Prepare / Get reviewed / Choose a date / Publish cards, the “Know where your launch stands” panel, and the shared footer, with the retained copy and action destinations intact. _(verifies R1, R2, R3, R4)_
- **Heading outline and keyboard order** — inspect the homepage heading outline and navigate with Tab; expected: Today’s launches is the H1, the restored hero is H2, later sections have meaningful headings, and focus follows the displayed content order with visible focus. _(verifies R1, R6, N1)_
- **Discovery descendant heading levels** — render the actual `LaunchDiscovery` with `headingLevel="h1"` for empty and populated responses; expected: empty-state and product titles are H2. Render it with its default H2; expected: card titles remain H3. _(verifies R1, N1; closes review finding)_
- **Browser heading and keyboard focus** — run the guest discovery Playwright scenario; expected: actual page H1/child heading levels are correct, Tab from Create your account reaches Sign in, reverse Tab returns, and keyboard focus has a visible outline. _(verifies R1, R6, N1; closes manual review finding)_
- **Feed state independence** — use component tests to render loading, empty, and error feed states; expected: each state remains inside the discovery section and all retained sections still render after it. On the running page, confirm the feed’s loading, empty, or retryable error presentation does not hide the supporting content. _(verifies R5; covers ARCH forward stress scenarios)_
- **Responsive layout** — inspect at 320px and a common desktop width; expected: sections remain in the specified order, text and cards remain readable, and the document has no page-level horizontal scrolling. _(verifies R6)_
- **Account and outage behavior** — exercise guest, eligible founder, reviewer/admin, failed-session, and connectivity-outage states; expected: existing CTA destinations, safe guest fallback, and outage recovery action remain unchanged. _(guards ARCH backward-regression risk for `HomePage.tsx`; verifies R2)_
- **Signed-in retained content** — render the homepage as a signed-in member; expected: the hero, process heading and all four steps, and reassurance panel remain visible alongside the workspace action. _(verifies R2, R3, R4; closes review coverage gap)_
- **Archive heading regression** — open an archive and run its component regression test; expected: shared discovery still uses its default H2 and archive date/navigation behavior is unchanged. _(guards ARCH backward-regression risk for `LaunchScreens.tsx`; verifies R1, N1)_
- **Public shell and route regression** — run `npm run test --workspace @launchpad/web -- src/App.test.tsx src/shell/AppShell.test.tsx src/routing.test.ts`; expected: the updated application homepage assertion passes, and unchanged public shell/footer composition, archive and existing launch routes, and lightweight navigation tests pass. _(guards ARCH backward-regression risks for `App.tsx`, `AppShell.tsx`, and `routing.ts`; verifies R4)_
- **Application homepage assertion** — in `App.test.tsx`, expect Today’s launches as H1 and the restored hero as H2 while retaining the current outage and shell checks. _(verifies R1, N1)_
- **Frontend quality gates** — run `npm run test --workspace @launchpad/web`, `npm run typecheck --workspace @launchpad/web`, and `npm run build --workspace @launchpad/web`; expected: tests, TypeScript type checking, and production build all pass.

#### Testable Seams

- `HomePage.test.tsx`: semantic order, heading levels, retained section copy/actions, and all static homepage sections rendered with mocked loading/empty/error discovery content.
- `HomePage.test.tsx`: existing guest/member/reviewer routing, session failure fallback, and outage recovery action.
- `App.test.tsx`: application-level homepage heading hierarchy and retained public-shell/outage behavior.
- `LaunchScreens.test.tsx`: actual discovery H1 with H2 empty/card descendants, default H2 with H3 card descendants, and existing public archive navigation.
- `RankedLaunchCard.test.tsx`: card-title heading level default and override.
- `tests/browser/frontend-accessibility.spec.ts`: rendered heading hierarchy, action keyboard order, and visible focus outline.
- Browser/UI: 320px and desktop layout, focus visibility/order, full page content and shared footer placement.

### Implementation Notes

- **Module(s):** `apps/web/src/home` composes the page; `apps/web/src/launches/LaunchDiscovery.tsx` owns discovery section and heading semantics; `PublicShell` continues to provide the shared footer.
- **Pattern reference:** Previous homepage markup and styles in repository history; current session-aware actions in `HomePage.tsx`; existing discovery/archive composition in `LaunchDiscovery.tsx` and `LaunchScreens.tsx`.
- **Key decisions:** Follow ARCH A1–A5. Keep Today’s launches first and H1; restore existing content and order below it; leave supporting sections unconditional across feed states; preserve the discovery H2 default for archive pages; keep the shared footer in the shell.
- **Libraries:** Existing React, TypeScript, Testing Library, Vitest, and Vite setup; no new dependency.
- **High-risk callouts:** The discovery component is shared by archive screens. Default the optional heading level to its current H2 and explicitly opt the homepage into H1; use the archive regression test to catch cross-route semantic changes.

### Scope Boundaries

- Do NOT change public launch data, cards, ranking, voting, or pagination.
- Do NOT change dated archives, product detail pages, founder scheduling, routes, APIs, data models, authentication, or deployment configuration.
- Do NOT rewrite existing homepage copy or change account action destinations and behavior.
- Do NOT move or duplicate the shared footer into `HomePage`.
- Limit implementation changes to the homepage composition/styles, semantic heading options for discovery cards, and the tests listed in the ARCH footprint.

### Files Expected

_Anchored on ARCH's Change Footprint — every entry below maps to a specific Footprint row._

**New files:**
- None.

**Modified files:**
- `apps/web/src/home/HomePage.tsx` (move discovery before the restored sections, pass H1 heading level, and preserve current outage/session/navigation behavior)
- `apps/web/src/home/home.css` (restore prior hero, workflow, reassurance, and responsive styles)
- `apps/web/src/home/HomePage.test.tsx` (replace obsolete absence/compact-hero assertions and cover order, content, feed-state independence, and existing behaviors)
- `apps/web/src/App.test.tsx` (update the previous compact-hero H1 expectation; preserve outage and public-shell assertions)
- `apps/web/src/launches/LaunchDiscovery.tsx` (render title at the requested H1/H2 level, with H2 as the default)
- `apps/web/src/launches/LaunchScreens.test.tsx` (assert homepage discovery descendants are H2 and archive discovery retains default H2)
- `apps/web/src/votes/RankedLaunchCard.tsx` (render product title at optional H2/H3 level, default H3)
- `apps/web/src/votes/RankedLaunchCard.test.tsx` (cover card-title heading levels)
- `tests/browser/frontend-accessibility.spec.ts` (verify actual heading hierarchy and keyboard focus order/visibility)

**Must NOT modify:**
- `apps/web/src/App.tsx` (shell and route composition remains a regression boundary)
- `apps/web/src/shell/AppShell.tsx` (shared footer remains shell-owned)
- `apps/web/src/launches/LaunchScreens.tsx` (archive composition remains unchanged)
- `apps/web/src/launches/launches.css` (discovery and archive styles remain unchanged)
- `apps/web/src/routing.ts` (existing route behavior remains unchanged)
- Any API, contract, database, generated type, deployment, or unrelated workspace files.

---
