# Tasks

> **Date:** 2026-10-20

## Task T1: Establish the pathname routing contract

> **Status:** done
> **Verification:** tdd
> **Effort:** s
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R2–R12, N6
> **Footprint slice:** New: `routing.ts`, `routing.test.ts`; replacement later: the route matching in `App.tsx` and the navigation helper in `identity/Screens.tsx`.
> **High-risk areas touched:** Root composition and routing (high); session and role presentation (high).

### Description

Extract a pure, typed pathname classifier and the existing History API navigation contract into one routing module. This establishes explicit public, account, founder, reviewer, and unavailable route identities for later shell composition without moving authorization into route parsing.

### Test Plan

#### Test File(s)

- `apps/web/src/routing.test.ts`

#### Test Scenarios

##### Route classification

- **Home and account routes** — GIVEN `/`, `/signin`, `/register`, `/verify`, `/recover`, and `/reset` WHEN classified THEN each produces its explicit public surface rather than a sign-in fallback _(verifies R2, R3, R4, R6)_
- **Private route precedence** — GIVEN `/profile`, `/products`, `/products/{id}`, `/launches`, `/products/review`, and `/products/review/{id}` WHEN classified THEN founder and reviewer routes are distinct and review paths cannot be parsed as product detail _(verifies R4, R7–R11; guards routing regression)_
- **Public identifiers** — GIVEN `/public/{accountId}` or `/launches/{productId}` with valid encoding WHEN classified THEN the appropriate public route carries the decoded identifier _(verifies R7, R11)_
- **Safe unknown paths** — GIVEN malformed percent encoding, an empty identifier, unsupported nesting, or an unknown path WHEN classified THEN the safe unavailable route is returned without throwing or revealing private state _(verifies R12, N6; REQ public-unavailable edge case)_

##### Navigation and regression

- **History contract** — GIVEN a destination and optional state WHEN `navigate` runs THEN it pushes the state and pathname and dispatches exactly one `popstate` event _(verifies R5; guards notification focus and back/forward navigation)_
- **No authorization authority** — GIVEN a recognized private path WHEN classified THEN the result contains route identity and parameters only and uses no session/client dependency _(verifies R4, N6; guards root and identity boundaries)_

### Implementation Notes

- **Module(s):** `apps/web/src/routing.ts`.
- **Pattern reference:** Existing route matching in `App.tsx` and `ProductScreens.tsx`; `navigate` in `identity/Screens.tsx`.
- **Key decisions:** A1, A10; route classification never grants access, and stable client ownership stays in `App`.
- **Libraries:** Browser History API and TypeScript only.
- **High-risk callouts:** Preserve review-route precedence and the `focusProductMain` history state used by notification navigation.

### Scope Boundaries

- Only establish route classification and browser navigation; later tasks migrate callers and render shells.
- Do not add a router dependency, redirects, session fetching, private data, or feature imports.

### Files Expected

**New files:**

- `apps/web/src/routing.ts` — typed route classifier and navigation helper.
- `apps/web/src/routing.test.ts` — deterministic RED → GREEN contract coverage.

**Modified files:** None.

**Must NOT modify:**

- `apps/web/src/App.tsx`, `apps/web/src/identity/Screens.tsx`, and feature screens — their migration belongs to later tasks.
- `apps/web/src/identity/client.ts`, `apps/web/src/identity/useIdentity.ts`, and `packages/contracts/` — stable identity and generated contract behavior.

---

## Task T2: Add semantic primitives and a safe error boundary

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R1, R5, R8–R12, R15, N1, N2, N6
> **Footprint slice:** New: `ui/Primitives.tsx`, `ui/Primitives.test.tsx`, `ui/AppErrorBoundary.tsx`, `ui/AppErrorBoundary.test.tsx`.
> **High-risk areas touched:** Visual system and responsive behavior (high); root composition and routing (high).

### Description

Create small semantic components for repeated page structure and non-success states. Add an application error boundary that removes a failed descendant tree and offers recovery without exposing exception details or private content.

### Test Plan

#### Test File(s)

- `apps/web/src/ui/Primitives.test.tsx`
- `apps/web/src/ui/AppErrorBoundary.test.tsx`

#### Test Scenarios

##### Structural semantics

- **Page identity and panel semantics** — GIVEN headings, supporting copy, actions, and a section/article choice WHEN rendered THEN heading relationships are clear, actions stay outside heading text, and no nested main landmark appears _(verifies R1, R5, N1)_
- **Native actions** — GIVEN link and command actions WHEN rendered THEN navigation is an anchor, commands are buttons of safe default type, and disabled commands expose their state _(verifies R5–R11, N1)_
- **Accessible pagination** — GIVEN page position and boundary handlers WHEN rendered THEN a labelled navigation region announces position, disables unavailable directions, and invokes only enabled handlers _(verifies R9, R10, R15, N1)_

##### States and resilience

- **Textual status** — GIVEN each named variant WHEN a badge or banner renders THEN visible copy remains and warning/error versus informational semantics are appropriate _(verifies R8–R12, N1, N2)_
- **Contextual non-success states** — GIVEN loading, empty, and unavailable inputs WHEN rendered THEN each retains explanation, loading is polite, empty is not an error, and recovery controls appear only when supplied _(verifies R12, R15, N1, N2, N6)_
- **Render failure** — GIVEN a descendant that throws WHEN caught THEN failed content disappears, a branded heading and reload/home actions appear, and exception text, stack, identifiers, and private content are absent _(verifies R12, N6; ARCH render-failure stress case)_
- **Healthy pass-through** — GIVEN a healthy descendant WHEN wrapped THEN its content renders unchanged and no fallback appears _(guards root-composition regression)_

### Implementation Notes

- **Module(s):** `apps/web/src/ui/`.
- **Pattern reference:** Existing panels, buttons, badges, form messages, and empty states in `styles.css`, `ProductScreens.tsx`, and `LaunchScreens.tsx`.
- **Key decisions:** A4, A5, A9; primitives receive presentation content and do not own domain hooks or feature copy.
- **Libraries:** React and TypeScript strict mode.
- **High-risk callouts:** Native semantics and safe fallback output are tested before shared styles are introduced.

### Scope Boundaries

- Only provide the agreed primitives and error boundary; T3 owns their CSS and T6 mounts the boundary.
- Do not add a form builder, data table framework, client logging, monitoring, or server-state store.

### Files Expected

**New files:**

- `apps/web/src/ui/Primitives.tsx` — semantic structural and state components.
- `apps/web/src/ui/Primitives.test.tsx` — component contract tests.
- `apps/web/src/ui/AppErrorBoundary.tsx` — safe render-failure fallback.
- `apps/web/src/ui/AppErrorBoundary.test.tsx` — fallback and pass-through tests.

**Modified files:** None.

**Must NOT modify:**

- `apps/web/src/App.tsx`, `apps/web/src/styles.css`, `apps/web/src/main.tsx`, feature hooks/clients, and `packages/contracts/`.

---

## Task T3: Establish the shared visual foundation

> **Status:** done
> **Verification:** checklist
> **Effort:** m
> **Priority:** critical
> **Depends on:** T2
> **Satisfies REQs:** R1, R5–R13, R15, N1–N5, N7
> **Footprint slice:** New: `ui/tokens.css`, `ui/components.css`; modified: `styles.css` shared import/reset layer. Feature-specific rule migration remains with T7–T12.
> **High-risk areas touched:** Visual system and responsive behavior (high); build and deployment (low).

### Description

Define the approved palette, dimensions, focus behavior, reduced-motion rules, and shared component recipes in CSS custom properties. Keep the stylesheet entry deterministic so later feature tasks can migrate visual rules without disrupting the current routes.

### Verification Checklist

- **Palette tokens** — expected: cream `#f6f3e9`, sky blue `#a8e5ff`, yellow `#ffde59`, coral `#ffaaa4`, white, and black `#111` are centralized; any supporting green/blue preserve existing launch colors _(R1, R13, R14, N2)_
- **Dimension tokens** — expected: type, content widths, spacing, border widths, hard shadow offsets, focus outline, and control sizing support both compact lists and display headings _(R1, R15, N3, N4, N7)_
- **Shared recipes** — expected: headings, panels, actions, badges, banners, lifecycle states, pagination, forms, lists, media, and action groups use named variants and do not encode meaning through color alone _(R1, R5–R13, N1, N2)_
- **Focus** — expected: links, buttons, inputs, textareas, and selects have a high-contrast `:focus-visible` treatment; disabled state remains visible; no reset suppresses focus without replacement _(N1, N2)_
- **Reflow and motion** — expected: `min-width: 0`, wrapping, stackable controls, and reduced-motion styles cover 320-pixel and zoom constraints without relying on animation for meaning _(R15, N3–N5)_
- **Import order** — expected: `styles.css` loads Tailwind first, then shared tokens and component recipes, while existing feature styles remain active until their feature task migrates them _(guards stylesheet regression)_
- **Mechanical gate** — run `npm run typecheck`, `npm run build`, and `git diff --check`; expected: each exits zero and Vite resolves all CSS imports.

### Implementation Notes

- **Module(s):** `apps/web/src/ui/`, root stylesheet entry.
- **Pattern reference:** Palette and hard-shadow rules in `launches/launches.css`; legacy shared controls in `styles.css`.
- **Key decisions:** A4, A7, A8, A11; keep Tailwind 4 and use local CSS/SVG conventions.
- **Libraries:** Existing Tailwind 4 and Vite CSS pipeline.
- **High-risk callouts:** Preserve loaded legacy feature CSS until each migration; verify focus and contrast visually in T4–T12.

### Scope Boundaries

- Only establish shared style contracts and the root import/reset layer; feature layouts migrate in their owning tasks.
- Do not add a UI framework, imagery, a new palette, or a runtime styling dependency.

### Files Expected

**New files:**

- `apps/web/src/ui/tokens.css` — approved theme and accessibility tokens.
- `apps/web/src/ui/components.css` — shared semantic recipes.

**Modified files:**

- `apps/web/src/styles.css` — add deterministic imports and global reset while preserving still-needed feature rules.

**Must NOT modify:**

- `apps/web/src/main.tsx` — single stylesheet entry and Query provider.
- Feature screens, hooks/clients, `packages/contracts/`, and backend code.

---

## Task T4: Build public and workspace shells

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1, T2, T3
> **Satisfies REQs:** R1, R4, R5, R10, R12, R13, N1–N4, N6, N7
> **Footprint slice:** New: `shell/AppShell.tsx`, `shell/AppShell.test.tsx`, `shell/shell.css`. Global screen mounts occur in T6.
> **High-risk areas touched:** Session and role presentation (high); root composition (high); visual system (high); notifications (medium).

### Description

Provide one public frame and one session-aware workspace frame with role navigation, a single bell placement, skip link, logout, and a responsive disclosure menu. The workspace shell gates private children until the existing shared session query establishes eligibility.

### Verification Checklist

- **Public frame** — expected: signed-out public/account content has one brand/header, public navigation, skip link, main landmark, and footer; private destinations are absent _(R1, R4, N1, N6)_
- **Pending/failed session** — expected: branded neutral or safe recovery content appears while a session is pending/failed; no private child, bell, reviewer label, or founder data flashes _(R12, N6; REQ session-expiry edge case)_
- **Role navigation** — expected: member primary paths lead to products, launches, profile, and permitted notifications; reviewer primary paths emphasize the review queue/history and allowed account paths; losing reviewer access removes staff links _(R4, R9, R10, N6)_
- **Disclosure keyboard flow** — expected: at 320 pixels, opening the menu moves focus inside, Escape closes and restores focus, selecting a destination closes it, and route/sign-out changes reset it; desktop navigation remains inline _(R4, N1, N3)_
- **Global visual hierarchy** — expected: shared palette, heavy borders, hard shadows, focus ring, and compact controls remain legible at desktop, 320 pixels, and 200% zoom with long labels _(R1, R13, N2–N4, N7)_
- **Logout and notification placement** — expected: sign-out uses the existing mutation/recovery behavior and one bell mount occupies its designated header slot without hiding nav or content _(R10, N1, N6)_
- **Verification evidence** — expected: record component test output and a rendered narrow/desktop shell inspection; if inspected through a temporary preview, do not commit a preview route _(guards shell integration)_

#### Testable Seams

- `AppShell.test.tsx`: session pending/401/role change, one bell mount, allowed links, logout failure, disclosure `aria-expanded`/focus/Escape/close-on-navigation.
- Existing identity session hook behavior and Query key remain unchanged; verify shared cache use and no duplicate session authority.

### Implementation Notes

- **Module(s):** `apps/web/src/shell/`.
- **Pattern reference:** Current `ProductFrame`, `launch-topbar`, `useCurrentSession`, `useLogout`, and `NotificationBell`.
- **Key decisions:** A2, A3, A4, A10; shell presents eligibility, feature/backend policies still authorize.
- **Libraries:** React, TanStack Query through existing hooks, CSS/Tailwind.
- **High-risk callouts:** Pending/stale session rendering and notification remounts are privacy and live-update risks; check them at the shell boundary.

### Scope Boundaries

- Only build shell presentation and session-aware framing; T6 mounts it globally, T11 adapts bell internals.
- Do not edit identity hooks, notification transport, or backend authorization rules.

### Files Expected

**New files:**

- `apps/web/src/shell/AppShell.tsx` — public/workspace shells and responsive nav.
- `apps/web/src/shell/AppShell.test.tsx` — session and keyboard behavior seams.
- `apps/web/src/shell/shell.css` — shell layout.

**Modified files:** None.

**Must NOT modify:**

- `apps/web/src/main.tsx`, `apps/web/src/identity/useIdentity.ts`, `apps/web/src/identity/client.ts`, `apps/web/src/notifications/useNotifications.ts`, and feature data clients.

---

## Task T5: Create the production homepage

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T2, T3, T4
> **Satisfies REQs:** R1–R3, R12–R14, N1–N7
> **Footprint slice:** New: `home/HomePage.tsx`, `home/HomePage.test.tsx`, `home/home.css`; root integration and browser connectivity update occur in T6 and T13.
> **High-risk areas touched:** Homepage and connectivity (medium); visual system (high); session and role presentation (high).

### Description

Replace the developer-facing root card with a public landing page that explains the existing prepare → review → schedule → publish journey. Keep account-aware actions privacy safe and display connectivity only as an outage/recovery state while the landing content remains available.

### Verification Checklist

- **Honest landing story** — expected: a visitor understands submission, staff review, booking, and public publication; registration and sign-in actions are findable; discovery, rankings, votes, comments, and search are not advertised _(R2, R14)_
- **Account actions** — expected: signed-out or unresolved session shows only public actions; a resolved member sees a workspace path; no private content is printed during pending/error state _(R3, N6)_
- **Connectivity recovery** — expected: loading/healthy states retain the landing page; outage adds branded failure guidance and a retry action; successful retry clears the outage without replacing the page _(R3, R12; REQ outage edge case)_
- **Responsive hierarchy** — expected: hero and journey sections remain readable at desktop, 320 pixels, and 200% zoom; primary actions and status stay above decoration, with visible keyboard focus and reduced motion _(R1, R13, N1–N5, N7)_
- **Original assets and copy** — expected: only approved palette, typography, geometric marks, local SVG, and existing product media are used; the page does not reproduce reference-site branding/layout/copy _(R13, R14)_

#### Testable Seams

- `HomePage.test.tsx`: signed-out/signed-in/pending calls to action; connectivity loading/healthy/unavailable/recovered; retry handler; no unbuilt feature promises.
- Existing `useConnectivity.ts` and `connectivity/client.ts`: preserve the readiness request and retry behavior.

### Implementation Notes

- **Module(s):** `apps/web/src/home/`.
- **Pattern reference:** Current root card in `App.tsx`, approved palette in `launches.css`, existing connectivity hook.
- **Key decisions:** A6–A8, A10; connectivity belongs to `HomePage` and does not become a global route hook.
- **Libraries:** React, existing identity/connectivity hooks, shared UI/CSS.
- **High-risk callouts:** Keep landing content visible through readiness failures and avoid private CTA flashes while session resolves.

### Scope Boundaries

- Only describe currently available functionality; no new discovery, rankings, search, or community actions.
- No generated/stock images or changes to connectivity API behavior.

### Files Expected

**New files:**

- `apps/web/src/home/HomePage.tsx` — landing and recovery states.
- `apps/web/src/home/HomePage.test.tsx` — account/connectivity component seams.
- `apps/web/src/home/home.css` — landing composition.

**Modified files:** None.

**Must NOT modify:**

- `apps/web/src/connectivity/useConnectivity.ts`, `apps/web/src/connectivity/client.ts`, `apps/web/src/identity/useIdentity.ts`, and generated/backend contracts.

---

## Task T6: Integrate routing, shells, and homepage in App

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1, T2, T3, T4, T5
> **Satisfies REQs:** R1–R5, R10, R12, N1, N3, N6, N7
> **Footprint slice:** Modified: `App.tsx`, `App.test.tsx`, `styles.css`; replaced: root connectivity card, root route branches, duplicate bell mount at the root.
> **High-risk areas touched:** Root composition and routing (high); session and role presentation (high); homepage (medium).

### Description

Compose the new route classifier, public/workspace shells, homepage, and error boundary at the existing React root. Preserve stable identity/product client lifetimes, History API route changes, and the notification-to-product focus contract.

### Test Plan

#### Test File(s)

- `apps/web/src/App.test.tsx`
- `apps/web/src/home/HomePage.test.tsx`

#### Test Scenarios

##### Route and state composition

- **Public and account surfaces** — GIVEN root, account, public profile, and public launch routes WHEN opened directly or through history THEN the matching public shell/content renders without workspace content _(verifies R2–R5, N6)_
- **Founder and reviewer surfaces** — GIVEN private product, profile, launch, and review routes WHEN session resolves THEN the correct workspace shell and feature route render once; while pending, children remain absent _(verifies R4, R10, N6)_
- **Unknown or malformed route** — GIVEN an unsupported path WHEN opened THEN the safe branded unavailable state renders without defaulting to sign-in or exposing private content _(verifies R12, N6)_

##### Regression and resilience

- **Stable clients and CSRF** — GIVEN repeated navigation and rerenders WHEN route state changes THEN identity/product factories are each called once and the same client instance reaches feature routes _(guards `identity/client.ts`, `products/client.ts`, and ARCH root regression)_
- **Focus handoff** — GIVEN `focusProductMain` history state WHEN a notification opens a product THEN the product main landmark receives focus and the state is cleared _(guards existing notification destination behavior)_
- **Connectivity isolation** — GIVEN non-home navigation WHEN rendered THEN homepage readiness is not queried; root home continues showing content through readiness failure _(guards `useConnectivity.ts` and conditional-hook regression)_
- **Render failure** — GIVEN a descendant throws WHEN composed under App THEN the safe error-boundary recovery appears without failed private content _(verifies R12, N6; ARCH forward stress case)_
- **Query provider and bundle** — GIVEN the existing `main.tsx` Query provider and stylesheet entry WHEN App renders/builds THEN no second provider/root is created and all CSS imports resolve _(guards `main.tsx` and build footprint)_

### Implementation Notes

- **Module(s):** `App.tsx`, root stylesheet entry.
- **Pattern reference:** Existing stable `useState` client factories and product-main focus effect in `App.tsx`.
- **Key decisions:** A1–A3, A6, A9, A10; route classification is separate from authorization.
- **Libraries:** React, TanStack Query through the existing provider, Vite CSS imports.
- **High-risk callouts:** This is the only global composition change; test direct navigation, popstate, session pending, and stable client identity.

### Scope Boundaries

- Integrate only previously defined modules; feature layout changes remain in T7–T12.
- Do not alter backend contracts, Query key definitions, or `main.tsx`.

### Files Expected

**New files:** None.

**Modified files:**

- `apps/web/src/App.tsx` — route/shell/home/error-boundary composition.
- `apps/web/src/App.test.tsx` — integration regression coverage.
- `apps/web/src/styles.css` — complete shared import manifest while preserving feature CSS until migration.

**Must NOT modify:**

- `apps/web/src/main.tsx`, `apps/web/src/identity/client.ts`, `apps/web/src/identity/useIdentity.ts`, `apps/web/src/connectivity/useConnectivity.ts`, `apps/web/src/connectivity/client.ts`, and generated/backend contracts.

---

## Task T7: Redesign account access screens

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T6
> **Satisfies REQs:** R1, R5, R6, R12, R13, N1–N4, N6, N7
> **Footprint slice:** New: `identity/identity.css`; modified: `identity/Screens.tsx`, `identity/Screens.test.tsx`, `styles.css`; replacement: the identity-owned navigation export and legacy account styles.
> **High-risk areas touched:** Account and profile surfaces (medium); root routing (high); visual system (high).

### Description

Move account screens into the public shell's visual language while preserving registration, verification, sign-in, recovery, reset, signed-out, and session-expiry outcomes. Transfer navigation ownership to the routing module and keep form state, validation, and safe error copy in the identity feature.

### Verification Checklist

- **All account states** — expected: each existing account route has the same brand/header rhythm, clear form title, validation, success/failure feedback, and next action _(R6, R12)_
- **Keyboard form flow** — expected: labels, tab order, focus ring, disabled submit, and error associations work on sign-in, registration, verification, recovery, and reset _(R6, N1, N2)_
- **Recovery privacy** — expected: generic recovery copy still avoids account-existence disclosure; entered values stay available after retryable failure where the current flow permits _(R6, N6; REQ failed-form edge case)_
- **Responsive forms** — expected: 320-pixel and 200% zoom layouts retain labels, controls, error copy, and actions without horizontal scrolling; long messages wrap _(N3, N4)_
- **Navigation regression** — expected: internal account links and successful sign-in/sign-out still navigate through the shared helper; browser back/forward returns the correct screen _(R5; guards former `navigate` export)_

#### Testable Seams

- `Screens.test.tsx`: route selection, form validation/submit, generic recovery, success/failure state, and navigation import migration.
- Existing `identity/client.ts` and `useIdentity.ts` tests continue to guard CSRF, cookies, and cache invalidation.

### Implementation Notes

- **Module(s):** `identity/`, stylesheet entry.
- **Pattern reference:** Current `Screens.tsx` form controls and `styles.css` identity selectors.
- **Key decisions:** A4, A5, A10; account inputs remain native and domain behavior stays in identity hooks.
- **Libraries:** React, shared UI primitives, existing identity hooks.
- **High-risk callouts:** Preserve form values, neutral recovery wording, and session mutation behavior while moving layout.

### Scope Boundaries

- Redesign only existing account states and import paths; no new account rules or API fields.
- Do not change identity client, session hook, generated types, or backend auth.

### Files Expected

**New files:**

- `apps/web/src/identity/identity.css` — account-specific responsive layout.

**Modified files:**

- `apps/web/src/identity/Screens.tsx` — shared presentation and routing import.
- `apps/web/src/identity/Screens.test.tsx` — account behavior and semantics.
- `apps/web/src/styles.css` — import identity-owned styles and remove migrated rules.

**Must NOT modify:**

- `apps/web/src/identity/client.ts`, `apps/web/src/identity/useIdentity.ts`, `apps/web/src/main.tsx`, and API/generated contracts.

---

## Task T8: Redesign private and public profiles

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T7
> **Satisfies REQs:** R1, R5, R7, R12, R13, N1–N4, N6
> **Footprint slice:** New: `profiles/profiles.css`; modified: `profiles/ProfileScreens.tsx`, `profiles/ProfileScreens.test.tsx`, `styles.css`.
> **High-risk areas touched:** Account and profile surfaces (medium); visual system (high); session and role presentation (high).

### Description

Apply shared hierarchy and state treatments to private profile editing and eligible public profile display. Preserve photo upload, completeness, publish/unpublish decisions, and indistinguishable unavailable states for private or missing public profiles.

### Verification Checklist

- **Private editor** — expected: member can identify current visibility, edit fields/photo/links, see completeness criteria, save, publish or unpublish, and receive contextual validation/feedback _(R7, R12)_
- **Public profile** — expected: eligible profile shows only public fields/media; private or missing profile shows the same safe unavailable treatment without identifying private existence _(R7, N6; REQ public-privacy edge case)_
- **Pending and failed states** — expected: loading, upload progress, invalid link/bio, failed save, and publication changes retain page context and entered values where the current flow permits _(R12; REQ failed-form edge case)_
- **Responsive and keyboard** — expected: form labels, links, file input, actions, focus, long links, 320-pixel layout, and 200% zoom remain usable _(N1–N4)_
- **Shell alignment** — expected: the private page fits the workspace shell, the public page fits the public shell, and neither adds a second global header/main landmark _(R1, R5)_

#### Testable Seams

- `ProfileScreens.test.tsx`: private/public eligibility, upload/save/publish paths, validation, safe unavailable state, and signed-out recovery.
- Existing `profiles/client.ts` and `useProfile.ts` behavior stays covered by their own tests.

### Implementation Notes

- **Module(s):** `profiles/`, stylesheet entry.
- **Pattern reference:** Current `ProfileShell` and profile CSS selectors in `styles.css`.
- **Key decisions:** A2, A4, A5, A12; profile service behavior and publication eligibility remain authoritative.
- **Libraries:** Existing profile hooks, React, shared UI/CSS.
- **High-risk callouts:** Preserve private/public rendering gates and typed upload flow while changing page structure.

### Scope Boundaries

- Only redesign existing profile views; no publication rule, upload contract, or profile field change.
- No public discovery link or new profile content.

### Files Expected

**New files:**

- `apps/web/src/profiles/profiles.css` — private/public profile layout.

**Modified files:**

- `apps/web/src/profiles/ProfileScreens.tsx` — shell-compatible profile presentation.
- `apps/web/src/profiles/ProfileScreens.test.tsx` — profile state and privacy seams.
- `apps/web/src/styles.css` — import profile styles and remove migrated rules.

**Must NOT modify:**

- `apps/web/src/profiles/client.ts`, `apps/web/src/profiles/useProfile.ts`, `apps/web/src/identity/useIdentity.ts`, `packages/contracts/`, and backend profile policy.

---

## Task T9: Redesign the founder product workspace

> **Status:** not started
> **Verification:** ui
> **Effort:** l
> **Priority:** high
> **Depends on:** T8
> **Satisfies REQs:** R1, R5, R8, R12, R13, R15, N1–N4, N6, N7
> **Footprint slice:** New: `products/products.css`; modified: `products/ProductScreens.tsx`, `products/ProductScreens.test.tsx`, `products/ProductScreens.staff.test.tsx`, `styles.css`; replacement: `ProductFrame` global header.
> **High-risk areas touched:** Founder product workflow (high); reviewer workflow (high); visual system (high); session and role presentation (high).

### Description

Reorganize the founder list, detail, editor, media, topics, status, and lifecycle actions within the workspace shell. Keep product state and mutations in their current feature hooks while making status, next steps, validation, review feedback, and destructive options easy to distinguish.

### Verification Checklist

- **List states** — expected: zero, one, and full-page results show compact status, identity, next action, and available paging without oversized cards or hidden controls _(R8, R15)_
- **Editor and media** — expected: create/edit, topics, logo, screenshots, ordering, autosave, and upload states remain discoverable; missing or numerous media never obscures essential actions _(R8, R12; REQ media edge case)_
- **Lifecycle** — expected: submit, withdraw, changes requested, approval, scheduling eligibility, rejection, and permitted deletion preserve the same available actions and show status with text as well as color _(R8, N2, N6)_
- **Failure recovery** — expected: validation, save conflict, upload failure, and command failure appear next to the task while entered content remains available where current behavior permits _(R12; REQ failed-form edge case)_
- **Reviewer gate** — expected: a member cannot see staff-only data or navigation; an eligible reviewer still reaches the reviewer route after the global `ProductFrame` header is removed _(R9, N6)_
- **Dense responsive layout** — expected: long names/URLs/feedback and full galleries reflow at 320 pixels and 200% zoom; all form controls, dialogs, and actions remain keyboard reachable _(R15, N1, N3, N4)_
- **Visual continuity** — expected: founder pages consume shared tokens/primitives without a second global header or notification mount; focus and status remain stronger than decorative shadows _(R1, R13, N7)_

#### Testable Seams

- `ProductScreens.test.tsx`: create/list/editor/media/autosave/submit/withdraw/delete/conflict and status text.
- `ProductScreens.staff.test.tsx`: reviewer eligibility and signed-out/role-loss behavior.
- Existing `products/client.ts`, `useProducts.ts`, and `format.ts` tests guard network/autosave/byte formatting; do not move state into the shell.

### Implementation Notes

- **Module(s):** `products/ProductScreens.tsx`, product CSS, stylesheet entry.
- **Pattern reference:** Current product editor and `ProductFrame`; shared shell and primitives from T2/T4.
- **Key decisions:** A2, A4, A5, A10, A12; server-side permissions and product lifecycle remain unchanged.
- **Libraries:** React, existing product hooks, TanStack Query, shared UI/CSS.
- **High-risk callouts:** ProductScreens is the largest stateful component; preserve autosave, media ordering, validation associations, and `product-main` focus target.

### Scope Boundaries

- Redesign founder product presentation only; reviewer decision screen redesign belongs to T10.
- Do not change product rules, generated types, signed media URLs, hook behavior, or backend authorization.

### Files Expected

**New files:**

- `apps/web/src/products/products.css` — founder and reviewer feature styles, initially founder rules.

**Modified files:**

- `apps/web/src/products/ProductScreens.tsx` — shell-compatible founder presentation and removed global frame.
- `apps/web/src/products/ProductScreens.test.tsx` — founder behavior and semantic seams.
- `apps/web/src/products/ProductScreens.staff.test.tsx` — reviewer eligibility regression guard for the route wrapper.
- `apps/web/src/styles.css` — import product styles and remove migrated product rules.

**Must NOT modify:**

- `apps/web/src/products/client.ts`, `apps/web/src/products/useProducts.ts`, `apps/web/src/products/format.ts`, `packages/contracts/`, and backend product policies.

---

## Task T10: Redesign the reviewer workflow

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T9
> **Satisfies REQs:** R1, R5, R9, R12, R13, R15, N1–N4, N6, N7
> **Footprint slice:** Modified: `products/ProductReviewScreens.tsx`, `products/ProductReviewScreens.test.tsx`, `products/products.css`, and reviewer expectations in `products/ProductScreens.staff.test.tsx` when required by shared markup.
> **High-risk areas touched:** Reviewer workflow (high); visual system (high); session and role presentation (high).

### Description

Apply the shared visual system to the pending queue, approved-review history, review detail, risk indicators, decision forms, and confirmation states. Keep reviewer data, commands, paging, and mandatory feedback rules in the current feature layer.

### Verification Checklist

- **Queues and history** — expected: empty, single, and full pages remain compact and scannable; pending and approved history are clearly distinguished and paging works _(R9, R15)_
- **Review detail** — expected: product content/media, submission context, duplicate and suspension indicators, and status are legible with text/icon cues independent of color _(R9, N2)_
- **Decision forms** — expected: approval, rejection, and changes-requested controls retain required feedback, confirmation, pending, and failure states without losing entered text _(R9, R12; REQ failed-form edge case)_
- **Access changes** — expected: signed-out or no-longer-reviewer state removes staff detail/nav and shows a safe destination without a private-content flash _(R9, N6; REQ role-loss edge case)_
- **Dense responsive layout** — expected: long pitches/feedback, full queues, media, warnings, and action groups reflow at 320 pixels and 200% zoom with keyboard focus preserved _(R15, N1, N3, N4)_
- **Shared theme** — expected: panels, flags, buttons, and status treatments match founder/public visual language while preserving reviewer scan priority _(R1, R13, N7)_

#### Testable Seams

- `ProductReviewScreens.test.tsx`: pending/approved paging, flags, review detail, decision constraints, confirmation, errors, and safe public/private states.
- `ProductScreens.staff.test.tsx`: reviewer route guard; existing `reviewClient.test.ts` and `useReviewProducts.test.tsx` guard unchanged data behavior.

### Implementation Notes

- **Module(s):** reviewer screens and shared product feature CSS.
- **Pattern reference:** Existing staff queue/detail forms in `ProductReviewScreens.tsx` and product rules migrated in T9.
- **Key decisions:** A2, A4, A5, A12; preserve review command and feedback semantics.
- **Libraries:** Existing product review hooks and shared UI/CSS.
- **High-risk callouts:** Distinguish risk flags and decision consequences; preserve direct-route authorization.
- **Footprint correction:** ARCH names `products/reviewClient.ts` as a touched-only file, but the repository has `products/client.ts` and `products/reviewClient.test.ts`; guard the real client contract without creating a new reviewer client module.

### Scope Boundaries

- Only redesign reviewer presentation; do not change review policy, decision payload, queue behavior, or public visibility.
- Do not create a new reviewer data service or client.

### Files Expected

**New files:** None.

**Modified files:**

- `apps/web/src/products/ProductReviewScreens.tsx` — review queue/detail/decision presentation.
- `apps/web/src/products/ProductReviewScreens.test.tsx` — reviewer behavior and semantics.
- `apps/web/src/products/products.css` — reviewer feature layout and states.
- `apps/web/src/products/ProductScreens.staff.test.tsx` — update route-wrapper expectations only if reviewer markup changes require it.

**Must NOT modify:**

- `apps/web/src/products/client.ts`, `apps/web/src/products/useReviewProducts.ts`, `apps/web/src/products/reviewClient.test.ts`, `packages/contracts/`, and backend review policy.

---

## Task T11: Integrate the notification bell and inbox presentation

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T10
> **Satisfies REQs:** R1, R4, R10, R12, R13, R15, N1–N4, N6
> **Footprint slice:** New: `notifications/notifications.css`; modified: `notifications/NotificationBell.tsx`, `notifications/NotificationBell.test.tsx`, `styles.css`.
> **High-risk areas touched:** Notifications (medium); session and role presentation (high); visual system (high).

### Description

Adapt the existing live notification trigger and inbox to the single workspace-shell location. Keep unread announcements, read commands, WebSocket updates, error recovery, and product destination focus while making zero, one, many, and large-count states usable.

### Verification Checklist

- **Count states** — expected: zero, one, many, and a large unread count fit the header; visible bounded count remains understandable and the accessible label retains the exact number _(R10, N4; REQ count edge case)_
- **Inbox states** — expected: loading, empty, available, unavailable, unread, and read items use the shared panel/status language and remain scannable at full-page result size _(R10, R12, R15)_
- **Live/read behavior** — expected: WebSocket updates change count without remount duplication, read succeeds or leaves item unread on failure, and status announcements remain polite _(R10, N1; ARCH reconnection stress case)_
- **Keyboard and destination** — expected: trigger/inbox are keyboard operable; Escape restores trigger focus; opening an item navigates to the product and focuses its main landmark _(R10, N1, N6)_
- **Responsive privacy** — expected: 320-pixel/200%-zoom inbox does not overlap or clip controls; session loss removes the bell and private items immediately _(N3, N4, N6)_

#### Testable Seams

- `NotificationBell.test.tsx`: unread changes and accessible count, read failure rollback, Escape/focus, destination focus, and session loss.
- Existing `notifications/client.ts` and `useNotifications.ts` tests guard WebSocket transport and reconnection.

### Implementation Notes

- **Module(s):** notification presentation and stylesheet entry.
- **Pattern reference:** Existing `NotificationBell.tsx` and `styles.css` notification selectors; T4 shell placement.
- **Key decisions:** A3, A4, A10; one shell mount and unchanged notification data ownership.
- **Libraries:** Existing notification hooks, React, shared UI/CSS.
- **High-risk callouts:** Preserve live announcement wording/focus restoration and avoid a second WebSocket subscription.

### Scope Boundaries

- Only change bell/inbox presentation and layout; no new notification types, channels, or read semantics.
- Do not change WebSocket protocol, hook/cache behavior, or backend inbox rules.

### Files Expected

**New files:**

- `apps/web/src/notifications/notifications.css` — trigger, badge, and inbox layout.

**Modified files:**

- `apps/web/src/notifications/NotificationBell.tsx` — shell-friendly UI and bounded visible count.
- `apps/web/src/notifications/NotificationBell.test.tsx` — count, live, read, and focus seams.
- `apps/web/src/styles.css` — import notification styles and remove migrated rules.

**Must NOT modify:**

- `apps/web/src/notifications/client.ts`, `apps/web/src/notifications/useNotifications.ts`, `apps/web/src/identity/useIdentity.ts`, and generated/backend contracts.

---

## Task T12: Redesign launch scheduling and public product pages

> **Status:** not started
> **Verification:** ui
> **Effort:** l
> **Priority:** high
> **Depends on:** T11
> **Satisfies REQs:** R1, R5, R11–R15, N1–N4, N6, N7
> **Footprint slice:** Modified: `launches/LaunchScreens.tsx`, `launches/LaunchScreens.test.tsx`, `launches/launches.css`, `styles.css`; replacement: duplicated launch header/theme foundations.
> **High-risk areas touched:** Launch scheduling and public launch page (medium); visual system (high); session and role presentation (high).

### Description

Bring the founder launch calendar, booking history, preferences, publication failures, and public launched-product page into the shared shells and theme. Preserve UTC cutoff/capacity messaging, booking commands, preference updates, safe public access, and product media behavior.

### Verification Checklist

- **Founder calendar** — expected: approved/scheduled/launched eligibility, UTC cutoff, daily capacity, booking history, and next actions are legible from the product list _(R11, R15)_
- **Booking actions** — expected: book, reschedule, cancel, pending, conflict, and publication-failure states keep current command behavior and clearly distinguish saved versus failed changes _(R11, R12; REQ failed-form edge case)_
- **Preferences** — expected: six existing notification choices remain labelled, keyboard reachable, saveable, and visibly confirmed or failed _(R11, N1)_
- **Public product** — expected: eligible launched product shows identity, pitch, description, topics, launch date, website, logo/gallery; private, missing, or unavailable product reveals no unpublished details _(R11, R12, N6; REQ public-unavailable edge case)_
- **Media and long content** — expected: absent/many screenshots, long names/URLs, and full booking results reflow without displacing key actions or creating page overflow _(R15, N3, N4)_
- **Shared responsive identity** — expected: launch screens use common tokens, borders, shadows, focus, and shells at desktop, 320 pixels, and 200% zoom; no duplicate header/bell remains _(R1, R13, R14, N1–N3, N7)_

#### Testable Seams

- `LaunchScreens.test.tsx`: existing booking/preference/public-product states, failure reasons, media omission, safe unavailable, and shell-compatible landmarks.
- Existing `launches/client.ts` and `useLaunches.ts` tests guard command payloads, cache updates, and public query behavior.

### Implementation Notes

- **Module(s):** `launches/`, stylesheet entry.
- **Pattern reference:** Existing `LaunchScreens.tsx` and `launches.css`; shared shells/tokens from T3/T4.
- **Key decisions:** A2, A4, A5, A7, A12; approved launch palette remains the theme source.
- **Libraries:** Existing launch/product hooks, React, shared UI/CSS.
- **High-risk callouts:** Preserve booking state transitions, failure notices, UTC copy, signed media behavior, and public privacy while removing duplicate layout foundations.

### Scope Boundaries

- Only redesign current scheduling and public product surfaces; no launch discovery, voting, rankings, or publication-rule changes.
- Do not change launch clients/hooks, REST/GraphQL contracts, or backend scheduling.

### Files Expected

**New files:** None.

**Modified files:**

- `apps/web/src/launches/LaunchScreens.tsx` — shared-shell founder/public presentation.
- `apps/web/src/launches/LaunchScreens.test.tsx` — launch and public privacy seams.
- `apps/web/src/launches/launches.css` — feature-only layouts using shared tokens.
- `apps/web/src/styles.css` — finalize import order and remove migrated legacy launch/global rules.

**Must NOT modify:**

- `apps/web/src/launches/client.ts`, `apps/web/src/launches/useLaunches.ts`, `apps/web/src/products/client.ts`, `packages/contracts/`, and backend scheduling/publication code.

---

## Task T13: Verify cross-route browser behavior and accessibility

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** T6, T7, T8, T9, T10, T11, T12
> **Satisfies REQs:** R1–R15, N1–N7
> **Footprint slice:** New: `tests/browser/frontend-accessibility.spec.ts`, `tests/browser/frontend-navigation.spec.ts`; modified: `tests/browser/connectivity.spec.ts`, `tests/browser/member-identity.spec.ts`, `package.json`, `package-lock.json`.
> **High-risk areas touched:** Accessibility verification (medium); root routing (high); visual system (high); all redesigned feature surfaces (medium/high).

### Description

Add browser-level regression and axe coverage against the running frontend after all redesigned routes are integrated. Update existing identity/connectivity journeys to assert the production homepage and shared shells, while checking private route gating, keyboard behavior, narrow/zoom layouts, and safe public failures.

### Test Plan

#### Test File(s)

- `tests/browser/frontend-accessibility.spec.ts`
- `tests/browser/frontend-navigation.spec.ts`
- `tests/browser/connectivity.spec.ts`
- `tests/browser/member-identity.spec.ts`

#### Test Scenarios

##### Public and account journeys

- **Honest homepage and connectivity** — GIVEN healthy, failed, and recovered readiness WHEN visiting `/` THEN production content remains, unavailable guidance/retry appears only on failure, and existing account actions remain reachable _(verifies R2, R3, R12; guards `connectivity/client.ts` and `useConnectivity.ts`)_
- **Account keyboard journey** — GIVEN signed-out visitor at 320 pixels WHEN tabbing sign-in → registration → recovery and changing history THEN focus order, headings, and generic recovery copy stay correct _(verifies R6, N1, N3; guards `identity/client.ts`)_
- **Public privacy** — GIVEN private/missing profile or unpublished/missing product WHEN opening its public path THEN one safe unavailable treatment appears without private content or distinct existence clues _(verifies R7, R11, R12, N6)_

##### Workspace and cross-route regression

- **Founder/reviewer nav** — GIVEN authenticated member or reviewer state WHEN opening workspace routes THEN correct role links and one bell appear; pending/expired/role-loss states show no private content _(verifies R4, R9, R10, N6; guards `useIdentity.ts`)_
- **Mobile disclosure and focus** — GIVEN 320-pixel viewport WHEN opening/closing menu by keyboard, selecting a destination, or following a notification THEN focus restores/moves correctly and destination main is focused _(verifies R4, R10, N1, N3; guards notification and route behavior)_
- **Representative tasks** — GIVEN prepared founder/reviewer browser fixtures WHEN viewing products, review decisions, launches, and public launched product THEN statuses, paging, validation, warnings, booking controls, and media are present and operable _(verifies R5, R8, R9, R11, R15; guards unchanged feature hooks/clients)_

##### Accessibility and resilience

- **Automated accessibility** — GIVEN representative homepage, account, founder, reviewer, profile, and public launch states WHEN axe runs THEN no serious/critical accessibility violations remain in the rendered page _(verifies N1, N2; guards shared CSS/landmarks)_
- **Narrow/zoom/reduced motion** — GIVEN 320-pixel viewport, 200% browser zoom, long content, and reduced-motion preference WHEN representative routes render THEN no page-level horizontal scroll, clipped actions, hidden required information, or motion-only cues appear _(verifies N3–N5, N7; REQ long-content/media edge cases)_

### Implementation Notes

- **Module(s):** `tests/browser/`, root development dependency metadata.
- **Pattern reference:** Existing `connectivity.spec.ts`, `member-identity.spec.ts`, and Playwright configuration.
- **Key decisions:** A11, A13; axe runs in test tooling only, with current image pipeline and no runtime dependency.
- **Libraries:** Existing Playwright; add pinned `@axe-core/playwright` development dependency.
- **High-risk callouts:** Browser checks need deterministic authenticated fixtures or request interception for private routes; do not embed production credentials or call live production mutation endpoints. Keep manual keyboard/zoom visual QA as a separate post-implementation gate.

### Scope Boundaries

- Verify existing functionality and redesign outcomes only; no new backend fixtures or product capabilities.
- Do not modify Playwright base configuration, generated contracts, API/worker code, or production deployment files unless a demonstrated blocker is resolved through the approved architecture process.

### Files Expected

**New files:**

- `tests/browser/frontend-accessibility.spec.ts` — representative axe and accessibility browser checks.
- `tests/browser/frontend-navigation.spec.ts` — cross-route role, focus, and responsive browser checks.

**Modified files:**

- `tests/browser/connectivity.spec.ts` — production homepage availability behavior.
- `tests/browser/member-identity.spec.ts` — account and public-profile journey expectations.
- `package.json` — root development dependency for axe.
- `package-lock.json` — matching pinned dependency graph.

**Must NOT modify:**

- `tests/browser/playwright.config.ts` — existing browser base URL and runner setup remain the verification entry point.
- `apps/web/src/main.tsx`, `packages/contracts/`, API/worker code, database migrations, and production deployment configuration.

---
