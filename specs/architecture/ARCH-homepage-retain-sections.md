# Architecture: Retain Homepage Sections Below Today’s Launches

> **Date:** 2026-10-25
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** `specs/requirements/REQ-homepage-retain-sections.md`
> **Tasks:** `TASKS-homepage-retain-sections.md`
> **Type:** feature

## Architecture Summary

Recompose the existing public homepage so the shared Today’s launches discovery section is its first main content, followed by the previously used marketing hero and account actions, four-step launch process, reassurance panel, and the existing shared footer. Restore the prior homepage content and neobrutalist styles while preserving current session-aware actions, outage behavior, and the public launch feed’s loading, empty, and error states. Make the discovery section heading configurable so the homepage can use it as the H1 while archive pages retain their existing H2. This is a frontend-only change: routes, API contracts, product data, and launch behavior remain unchanged.

## High-Level Structure

```text
PublicShell (existing public navigation and shared footer)
└── HomePage
    ├── Connectivity outage notice (only when unavailable)
    ├── LaunchDiscovery (first main section; homepage heading is H1)
    │   ├── loading / empty / retryable error / launch cards
    │   └── existing anonymous query and pagination behavior
    ├── Restored hero (H2, account/workspace actions)
    ├── Four-step launch process
    └── Reassurance panel

Public archive route
└── LaunchDiscovery (default H2, unchanged archive composition)
```

The homepage renders `LaunchDiscovery` and the retained informational sections as siblings. Feed state therefore affects only the discovery section; it does not gate the hero, workflow explanation, or reassurance panel. `PublicShell` continues to render the shared footer after the page content.

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|------|----------|-------------------------|-----------|
| Page composition | Compose the existing `LaunchDiscovery` first in `HomePage`, then restore the previous sections | Duplicate discovery markup; move launches to another route; place the hero first | Reuses the existing feed and fulfills the required homepage order without changing discovery behavior (R1, R5). |
| Retained content | Restore prior hero, account/workspace actions, four workflow cards, reassurance panel, copy, and styling | Rewrite copy or retain only selected sections | This request preserves existing content and behavior while changing page hierarchy (R2–R4, R6). |
| Heading hierarchy | Add a heading-level option to `LaunchDiscovery`; homepage passes H1 and archive consumers retain default H2 | Keep discovery H2 and make the later hero H1; alter all consumers | Makes the first and primary homepage section the page H1 while keeping archive semantics unchanged (R1, N1). |
| Feed state independence | Keep the static sections as unconditional siblings after `LaunchDiscovery` | Conditionally render them after successful feed loading | Prevents loading, empty, or failed feed results from hiding useful homepage content (R5). |
| Styling | Restore and adapt the existing homepage neobrutalist CSS and responsive rules | Add a new design system or copy another product’s layout | Follows the approved visual direction and existing Launchpad styles (R6). |
| Footer | Keep the footer in the existing `PublicShell` | Duplicate it in `HomePage` | The shared shell already provides the footer after route content, preventing duplicate markup and preserving consistency (R4). |

## Patterns & Conventions

- **Feature composition** — `HomePage` composes the existing launches feature; it does not implement feed fetching or card rendering itself.
- **Independent query state** — loading, empty, error, pagination, and ranking behavior remain owned by `LaunchDiscovery` and its existing hooks.
- **Accessible document outline** — Today’s launches is the homepage H1; the retained hero title is H2; subsequent section titles follow a meaningful hierarchy. The archive keeps its current H2.
- **Session-aware actions** — preserve the existing verified-member, reviewer/admin, guest, and session-error action behavior in `HomePage`.
- **Approved visual direction** — use existing neobrutalist primitives and the previous homepage’s established colors, borders, shadows, and responsive behavior; inspiration is directional and not copied.
- **Lightweight navigation** — retain existing internal-link interception and route destinations.

## Data Models

No data model changes. The page consumes the existing public launch-list projection and existing identity/session state; it introduces no persisted entity, field, lifecycle, or migration.

## API Contracts / Interfaces

No API contract changes.

### `LaunchDiscovery` heading option

**Boundary:** Internal React component interface.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|-----------|-----------------|---------|------------------|
| Component prop | Optional `headingLevel: "h1" \| "h2"`, default `"h2"` | Selects the semantic level of the existing discovery title while keeping its text, section, query, and interactions unchanged. Homepage passes `"h1"`; archive callers omit the prop. | No new runtime errors; the value controls the rendered heading element. |

**Auth requirements:** None added. Existing public discovery and session behavior remains unchanged.

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|------------------|----------------|---------------------|
| `apps/web/src/home` | Compose discovery and retained homepage content; preserve account actions and outage recovery | Existing identity, connectivity, routing, launches component, and UI primitives |
| `apps/web/src/launches/LaunchDiscovery.tsx` | Own public launch section, feed state and cards; expose a semantic heading-level option | Existing launches query and ranking/card components |
| `apps/web/src/shell/AppShell.tsx` | Continue to provide shared public navigation and footer | Existing shell styling and route frame; no homepage-specific duplication |
| `apps/web/src/launches/LaunchScreens.tsx` | Continue composing the discovery component for public archive screens | `LaunchDiscovery` with its default H2 heading |

## Change Footprint

_The concrete answer to "where does this land in the codebase?" — produced during the Phase D2 walk._

### New files / modules

| Path | Purpose | Pattern reference |
|------|---------|-------------------|
| None | This is a bounded update to existing homepage and discovery components. | Existing home and launches feature modules. |

### Modified files / modules

| Path | What changes here |
|------|-------------------|
| `apps/web/src/home/HomePage.tsx` | Place `LaunchDiscovery` before the restored hero, four-step workflow, and reassurance panel; pass H1 heading level; preserve outage banner, session-aware actions, and archive navigation. |
| `apps/web/src/home/home.css` | Restore the previous hero, workflow cards, reassurance panel, and responsive styles; integrate spacing with the first-position discovery section. |
| `apps/web/src/home/HomePage.test.tsx` | Replace assertions that the old sections are absent; cover section order, heading levels, retained copy/actions, feed-state independence, and existing session/outage behavior. |
| `apps/web/src/App.test.tsx` | Update the application-level homepage heading assertion to expect Today’s launches as H1 and the restored hero as H2, while retaining the public-shell and outage assertions. |
| `apps/web/src/launches/LaunchDiscovery.tsx` | Support H1 or H2 rendering for its title, defaulting to H2 so existing archive use remains unchanged. |
| `apps/web/src/launches/LaunchScreens.test.tsx` | Verify the discovery section retains its default H2 when used by archive screens. |

### Deleted / replaced

| Path | Reason |
|------|--------|
| None | Existing sections and the discovery component are retained and recomposed. |

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|------|----------------|
| `apps/web/src/App.tsx` | Places homepage and public archives inside the existing public shell; routes remain unchanged. |
| `apps/web/src/shell/AppShell.tsx` | Supplies the shared footer that must remain after homepage content; do not duplicate it in `HomePage`. |
| `apps/web/src/launches/LaunchScreens.tsx` | Archive consumers share `LaunchDiscovery`; default heading behavior must preserve archive semantics. |
| `apps/web/src/launches/launches.css` | Owns discovery styling; this change should not alter archive or card behavior there. |
| `apps/web/src/routing.ts` | Existing internal links continue to use the current lightweight route mechanism. |

## Areas of Impact

| Area | Impact | Risk (L/M/H) | Why |
|------|--------|--------------|-----|
| Public homepage composition | Discovery becomes first content; prior informational sections return beneath it | M | Main hierarchy and page height change; section order, feed-state and responsive behavior need coverage. |
| Application-level homepage regression tests | Update expected H1/H2 while preserving outage and shell assertions | M | The old compact-hero H1 expectation conflicts with the approved homepage H1; the application test protects integration behavior. |
| Shared launch discovery | Adds an optional heading-level setting | M | The same component is used by archives; preserving the default H2 prevents a cross-route accessibility regression. |
| Identity and navigation actions | Existing CTA behavior remains but is restored below the discovery list | L | No auth or destination changes; layout order and keyboard traversal are affected. |
| Public shell/footer | No code change; footer follows the longer homepage | L | Shared shell already wraps page content and owns the footer. |
| API, database, and deployment data | No change | L | This is frontend-only and introduces no contract, persistence, or migration impact. |

**Contract changes:** Internal React component prop only (`headingLevel`, optional and defaulting to current behavior). No REST, GraphQL, URL, or external client contract changes.

**Cross-cutting ripples:** Accessibility heading hierarchy and keyboard reading order; responsive layout and CSS; homepage component tests. No auth policy, telemetry, migrations, feature flags, or backend deployment changes.

## Cross-Cutting Concerns

- **Errors:** Existing launch query errors remain localized to the discovery section and retain the retry action; the rest of the page stays rendered (R5).
- **Logging & metrics:** No new logging or metrics; existing query observability is unchanged.
- **Auth / authz:** No authorization changes. Existing identity/session logic continues choosing guest, founder, or reviewer actions.
- **Performance:** No additional requests or polling. The same discovery query and pagination behavior are used; the restored content is static markup.
- **Security:** No new data or media surfaces. Public listing authorization and private product isolation remain unchanged.
- **Migrations / rollout:** No database migration or API rollout. Ship as a web frontend release; rollback by restoring the previous web release/image.

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|----------|--------------|----------------|----------------|
| A1 | Render Today’s launches as the first main homepage section, followed by all prior homepage sections in their established order. | Put the marketing hero first; omit some supporting sections. | Preserves daily discovery priority while restoring the content requested in the brief and screenshot. | R1, R2, R3, R4 |
| A2 | Keep the hero, account actions, workflow content, and reassurance copy/behavior intact. | Rewrite copy, destinations, or product guidance during the layout adjustment. | The requested change is placement and retention, not a product-message or workflow change. | R2, R3, R4 |
| A3 | Keep supporting sections rendered regardless of feed loading, empty, or error state. | Gate the rest of the page on feed success. | Maintains useful guidance and account entry points during normal loading and service failure. | R5 |
| A4 | Make Today’s launches the homepage H1; render the restored hero title as H2; keep archive discovery H2 by default. | Keep the later hero as H1; globally change archive heading levels. | Aligns the semantic outline with the required visual/content priority without changing archive pages. | R1, R6, N1 |
| A6 | Update the existing application-level homepage heading expectation with the new hierarchy. | Keep the obsolete expectation and leave the application regression suite failing. | The old assertion names the compact hero as H1; updating it verifies the approved page while retaining outage and shell coverage. | R1, N1 |
| A5 | Reuse existing neobrutalist styles and the shared shell footer. | Create a new visual system or duplicate footer markup. | Preserves the approved design direction and shell ownership. | R4, R6 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|----------|----------------------------|
| Public launch request times out or fails. | The discovery component shows its existing retryable error; static homepage sections remain rendered below it. |
| Daily launch list is empty or still loading. | Existing empty/loading presentation remains inside the first section; restored hero, workflow, and reassurance remain visible. |
| Viewport is 320 pixels wide. | Existing mobile-first styles are restored and adjusted so cards and sections stack and text wraps without page-level horizontal scrolling. |
| A release needs rollback. | Restore the previous web image/release; no persisted data or API contract needs rollback. |

### Backward — regression risk per touched area (brownfield only)

| Touched area (from Change Footprint) | What could regress | How we'd know / mitigation |
|-------------------------------------|--------------------|----------------------------|
| `HomePage.tsx` and `HomePage.test.tsx` | Feed may accidentally move below the supporting sections, or session/outage actions may disappear during composition. | Assert semantic section order and cover guest, member, reviewer, session failure, outage, and feed-state cases. |
| `App.test.tsx` | Integration expectation for the previous compact-hero H1 becomes stale; outage and public-shell assertions could be lost while updating it. | Assert Today’s launches H1 and the restored hero H2; retain existing outage and shell assertions. |
| `home.css` | Restored styles may overflow at narrow sizes or obscure focus indicators. | Verify 320px and desktop layouts; check keyboard focus visibility and text wrapping. |
| `LaunchDiscovery.tsx` and `LaunchScreens.test.tsx` | Heading prop may alter archive markup or break section labeling. | Default to H2 and assert archive use remains H2; homepage explicitly requests H1. |
| `AppShell.tsx` (touched but not changed) | Footer could be duplicated or appear before the retained sections if moved into the page. | Leave shell ownership unchanged; verify footer follows the full page content. |

## Open Questions

None. The homepage order, retained content, loading/empty/error behavior, mobile/accessibility expectations, and H1 selection are confirmed in the requirement and this planning session.

## Out of Scope

- Changes to launch data, cards, ranking, voting, or pagination (reason: discovery behavior is already implemented and this change is composition-only).
- Changes to dated archives, product detail pages, or founder scheduling (reason: this requirement is limited to the guest homepage).
- Backend, database, API, authentication, or deployment changes (reason: existing contracts and behavior suffice).
- Rewriting the existing homepage copy or changing account workflows (reason: content and behavior are to be retained).
