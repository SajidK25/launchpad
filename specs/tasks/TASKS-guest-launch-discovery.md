# Tasks

> **Date:** 2026-10-22

## Task T1: Add the public date-filtered launch projection

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** None
> **Satisfies REQs:** R1, R3, R5, R6, R7, N3
> **Footprint slice:** Modified: products repository (launched-only UTC range query, keyset ordering, batched card associations); products service (date resolution, page bounds, projection, cursor validation); product read tests.
> **High-risk areas touched:** Products API and persistence (M).

### Description

Add the product-owned service and repository read for bounded pages of launches on a UTC day. The service distinguishes an omitted homepage date from an explicit archive date, enforces public visibility, and returns stable cursor pages.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_reads.py

#### Test Scenarios

##### Public UTC-Day Projection

- **uses the API clock for an omitted date** — GIVEN a fixed UTC service clock WHEN the listing is requested without a date THEN todayDate and selectedDate equal the current UTC date (verifies R1)
- **filters an explicit archive date** — GIVEN launched products on adjacent UTC dates WHEN one date is requested THEN only products in its inclusive-start/exclusive-next-day interval appear (verifies R5)
- **returns an empty page for an empty past date** — GIVEN a valid past date with no launches WHEN requested THEN the result has no items or cursor (REQ edge case)
- **excludes all non-launched states** — GIVEN draft, submitted, changes-requested, rejected, approved, and scheduled products alongside launched products WHEN queried THEN only launched products appear (verifies R6, N3; REQ scheduled-product edge case)

##### Ordering, Cursors, and Bounded Reads

- **orders case-insensitively and resolves ties by ID** — GIVEN names differing only by case and equal normalized names WHEN the same date is read repeatedly THEN order follows lower(name), id and does not imply ranking (verifies R3)
- **continues a date-bound cursor without skips or duplicates** — GIVEN more items than one page WHEN successive pages are loaded THEN results preserve the full deterministic order and a cursor for another date is rejected (verifies R3, R5)
- **enforces page-size bounds** — GIVEN omitted, valid, zero, negative, and above-maximum first values WHEN the service reads THEN default is 20, 1–50 are accepted, and other values raise typed validation (ARCH paging decision)
- **rejects malformed cursors and future dates** — GIVEN invalid cursor/date input WHEN the service is called THEN typed validation is returned without product data (REQ future-date edge case; verifies N3)
- **batch-loads card associations** — GIVEN a page containing multiple products WHEN card projections are built THEN logo metadata and topic labels use page-bounded batch reads rather than per-product queries (ARCH scale scenario)

### Implementation Notes

- **Module(s):** app.modules.products.repository and app.modules.products.service.
- **Pattern reference:** ProductService.owner_list, ProductRepository.list_owner_products, ProductService.public_projection, and existing read cursor helpers.
- **Key decisions:** API-computed UTC today; half-open UTC timestamp range; lower(name), id order; date-bound cursor; fetch first + 1; explicit card projection; logo URLs resolved through the existing public media boundary.
- **Libraries:** Existing async SQLAlchemy and pytest; no new dependency.
- **High-risk callouts:** Filter launched state in the repository before media resolution. Tests cover lifecycle privacy, date boundaries, cursor stability, and batching.

### Scope Boundaries

- Do NOT create a discovery backend module or import another feature repository.
- Do NOT return descriptions, screenshots, founder fields, or unpublished products.
- Do NOT change booking, publication worker, or asset access behavior.
- Only implement the service/repository projection and read tests; GraphQL and index migration are separate.

### Files Expected

**New files:**
- None.

**Modified files:**
- apps/api/app/modules/products/repository.py (launched-only date query and batch logo/topic reads)
- apps/api/app/modules/products/service.py (UTC date/page/cursor rules and public card projection)
- apps/api/app/modules/products/tests/test_reads.py (projection, paging, privacy, and batching tests)

**Must NOT modify:**
- apps/api/app/modules/products/routes.py (reuse and preserve public asset behavior)
- apps/api/app/modules/launches/service.py and apps/worker/worker.py (publication owns launched_at)

---

## Task T2: Add the launched-date query index

> **Status:** not started
> **Verification:** test-after
> **Effort:** s
> **Priority:** medium
> **Depends on:** T1
> **Satisfies REQs:** R1, R5, R6
> **Footprint slice:** New: migration 0014_public_launch_discovery_index.py; Modified: product model index metadata and model tests.
> **High-risk areas touched:** PostgreSQL migration (L); Products API and persistence (M).

### Description

Add a partial index on launched_at for launched products so the daily range query can efficiently select its UTC date. Keep the migration additive and reversible, without changing product data or lifecycle state.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_models.py
- Existing migrations category in scripts/quality/run.sh

#### Test Scenarios

##### Index Metadata and Migration

- **declares matching partial model metadata** — GIVEN Product model metadata WHEN indexes are inspected THEN the index targets launched_at and has the status-launched predicate (supports R1, R5, R6)
- **upgrades and downgrades cleanly** — GIVEN the previous migration head WHEN the new migration is applied and reverted on the check database THEN the index is created and removed (ARCH rollback scenario)
- **preserves product rows** — GIVEN launched and non-launched rows WHEN migration runs THEN counts, statuses, and launched_at values are unchanged (guards migration regression risk)
- **passes the migration quality category** — GIVEN the migration is present WHEN sh scripts/quality/run.sh runs in the configured check environment THEN its migrations category passes

### Implementation Notes

- **Module(s):** Product model metadata and Alembic migration.
- **Pattern reference:** apps/api/alembic/versions/0013_launch_booking_history_index.py and Product model Index declarations.
- **Key decisions:** Index only launched_at for rows with status launched; no unrelated index or data migration.
- **Libraries:** Existing SQLAlchemy, Alembic, PostgreSQL; no new dependency.
- **High-risk callouts:** Confirm upgrade and downgrade; consider index-build I/O on a large products table.

### Scope Boundaries

- Do NOT change product data, lifecycle constraints, or existing migrations.
- Do NOT add a new table.
- Only add matching partial-index metadata and migration.

### Files Expected

**New files:**
- apps/api/alembic/versions/0014_public_launch_discovery_index.py (add/drop the partial index)

**Modified files:**
- apps/api/app/modules/products/models.py (declare matching partial index)
- apps/api/app/modules/products/tests/test_models.py (assert index column and predicate)

**Must NOT modify:**
- apps/api/app/modules/products/service.py and repository.py (T1 owns query behavior)
- Existing applied migrations

---

## Task T3: Expose public launches through GraphQL

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T1, T2
> **Satisfies REQs:** R1, R2, R5, R6, R7, N3
> **Footprint slice:** Modified: product GraphQL resolver/types, shared root composition/allowlist, GraphQL operation and generated schema/types, GraphQL and composition tests.
> **High-risk areas touched:** GraphQL composition and generated contracts (M); Products API and persistence (M).

### Description

Expose the T1 projection as an anonymous publicLaunches(date, first, after) query. Compose it only into schemas that already expose public product reads, and regenerate the schema and TypeScript operation types using the existing contract workflow.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_graphql.py
- tests/integration/test_graphql_composition.py
- Contract generation: sh scripts/quality/contracts.sh

#### Test Scenarios

##### Anonymous GraphQL Projection

- **returns only approved card fields** — GIVEN launched and unpublished products WHEN anonymous publicLaunches runs THEN it returns date metadata and only ID, name, pitch, topics, and logo URL for launched products (verifies R1, R2, R6, N3)
- **supports today and archive requests** — GIVEN omitted and explicit dates WHEN queried THEN omitted date delegates to API UTC today and the selected archive date is returned (verifies R1, R5)
- **maps invalid inputs safely** — GIVEN a future date, invalid page size, or malformed cursor WHEN queried THEN a sanitized error is returned without product data (verifies R7, N3; REQ future-date edge case)

##### Composition and Contract

- **composes only into intended schemas** — GIVEN supported feature configurations WHEN schemas are built THEN publicLaunches appears with public product reads and remains absent from profile-only/product-disabled schemas (guards ARCH composition risk)
- **keeps root allowlisting strict** — GIVEN a private or unknown root field WHEN query validation runs THEN it remains rejected while publicLaunches is allowed (guards ARCH composition risk)
- **preserves publicProduct** — GIVEN an existing launched product WHEN publicProduct is queried THEN its existing projection remains available and unchanged (guards existing public-detail behavior)
- **preserves existing launch booking reads** — GIVEN a schema configuration that includes launch reads WHEN the root fields are inspected THEN viewerLaunchBookings and viewerLaunchNotificationPreferences remain present (guards ARCH reduced-schema regression risk)
- **regenerates contract outputs** — GIVEN the updated operation WHEN sh scripts/quality/contracts.sh runs THEN schema and generated operation types match server schema and source operation (N2)

### Implementation Notes

- **Module(s):** app.modules.products.graphql, app.graphql, packages/contracts.
- **Pattern reference:** PublicProductQuery and public_product in products/graphql.py; _ALLOWED_ROOT_FIELDS and schema variants in app/graphql.py.
- **Key decisions:** Thin resolver delegates to ProductService; use T1's date and projection rules; do not add private fields; regenerate generated artifacts.
- **Libraries:** Existing Strawberry GraphQL and contract scripts; no new dependencies.
- **High-risk callouts:** Root composition is a medium-risk public boundary. Cover intended feature combinations and ensure private roots remain blocked.

### Scope Boundaries

- Do NOT add REST endpoints, mutations, subscriptions, or a discovery backend module.
- Do NOT expose unpublished data or fields beyond the approved projection/date metadata.
- Do NOT hand-edit generated schema or TypeScript files.

### Files Expected

**New files:**
- None.

**Modified files:**
- apps/api/app/modules/products/graphql.py (page/item types and resolver)
- apps/api/app/graphql.py (supported schema composition and root allowlist)
- apps/api/app/modules/products/tests/test_graphql.py (anonymous result and validation)
- tests/integration/test_graphql_composition.py (feature configurations and regression guards)
- packages/contracts/operations.graphql (publicLaunches operation)
- packages/contracts/schema.graphql (generated schema)
- packages/contracts/src/graphql.generated.ts (generated result/operation types)

**Must NOT modify:**
- apps/api/app/modules/products/service.py and repository.py (T1 owns public read behavior)
- apps/api/app/modules/launches/graphql.py and service.py (booking reads remain unchanged)

---

## Task T4: Add the anonymous web query and paging state

> **Status:** not started
> **Verification:** tdd
> **Effort:** s
> **Priority:** high
> **Depends on:** T3
> **Satisfies REQs:** R1, R4, R7
> **Footprint slice:** Modified: launches GraphQL client, TanStack Query hooks, client tests, query-state tests.
> **High-risk areas touched:** GraphQL composition and generated contracts (M); Guest homepage and launches UI (M).

### Description

Add the web client and query state for today's and archive pages. The homepage request stays anonymous and omits date; archive requests send the selected date, and cursors reset when UTC day changes.

### Test Plan

#### Test File(s)
- apps/web/src/launches/client.test.ts
- apps/web/src/launches/useLaunches.test.ts

#### Test Scenarios

##### Anonymous Client

- **fetches today without session initialization** — GIVEN a signed-out identity client WHEN today is requested THEN GraphQL variables omit date and ensureSession is not called (verifies R1)
- **sends an archive date and cursor** — GIVEN a selected date and next cursor WHEN the client fetches THEN date, page size, and cursor are sent using generated result types (verifies R4)
- **surfaces request errors** — GIVEN GraphQL returns an error WHEN the client resolves THEN it rejects through the existing request error and does not synthesize an empty page (verifies R7)

##### Query State

- **loads the next page for the same date** — GIVEN a page with nextCursor WHEN more is requested THEN that cursor and date are used and results append (verifies R4)
- **resets today's cursor pages at UTC midnight** — GIVEN pages from the prior day WHEN midnight invalidation fires THEN old cursors are cleared and a fresh date-omitted request resolves the API date (ARCH midnight decision)
- **refetches on focus without polling** — GIVEN a stale tab regains focus WHEN query state updates THEN today's feed refetches and no interval polling is configured (verifies R1)
- **keeps empty and failure states distinct** — GIVEN successful empty data and a failed request WHEN query state is read THEN only the successful response is empty; failure remains retryable (verifies R7)

### Implementation Notes

- **Module(s):** apps/web/src/launches client and query hooks.
- **Pattern reference:** Existing graphql authenticated=false support, usePublicProduct, and launch query keys.
- **Key decisions:** Use generated operation types; do not initialize a session; use distinct today/archive keys; reset pages at midnight; refetch on focus, no polling.
- **Libraries:** Existing TypeScript, TanStack Query, generated contracts, Vitest; no new dependencies.
- **High-risk callouts:** Ensure midnight cannot reuse yesterday's cursor; preserve the distinction between empty and failed requests.

### Scope Boundaries

- Do NOT add WebSockets, continuous polling, or hand-maintained API types.
- Do NOT change server behavior.
- Only add client and query behavior required by discovery UI.

### Files Expected

**New files:**
- None.

**Modified files:**
- apps/web/src/launches/client.ts (anonymous public query)
- apps/web/src/launches/useLaunches.ts (date/cursor state and refresh behavior)
- apps/web/src/launches/client.test.ts (anonymous/archive variables)
- apps/web/src/launches/useLaunches.test.ts (paging, errors, midnight/focus)

**Must NOT modify:**
- packages/contracts/schema.graphql and src/graphql.generated.ts (T3 owns generated outputs)
- apps/web/src/routing.ts, App.tsx, and home/HomePage.tsx (later composition tasks)

---

## Task T5: Build the shared public discovery list

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T4
> **Satisfies REQs:** R2, R3, R4, R7, R8, N1, N2
> **Footprint slice:** New shared LaunchDiscovery view; modified launches stylesheet and launch screen tests.
> **High-risk areas touched:** Guest homepage and launches UI (M); Browser navigation (M, UI boundary only).

### Description

Create a reusable public list for homepage and archive use, with date controls, compact cards, loading/empty/error states, retry, and cursor-based Load more. Use the approved Launchpad visual direction and accessible responsive controls.

### Verification Checklist

- **Render the product card** — Given a page item — expected: logo, name, pitch, topics, and a working /launches/{id} detail link appear; descriptions, screenshots, and ranking claims do not (verifies R2, R3, N3)
- **Show loading, empty, and failure states** — Given each respective query state — expected: loading indicator, clear empty-day message, or separate error with retry (verifies R7; REQ empty/failure edge cases)
- **Navigate dates** — Given a selected date — expected: previous/next changes one UTC day, direct selection includes empty dates through todayDate, and future dates are disabled (verifies R4)
- **Load more** — Given a nextCursor — expected: an accessible control appends the next page and disappears when no cursor remains (ARCH paging decision)
- **Wrap long content** — Given long names and pitches — expected: content wraps without overlap or page-level horizontal scroll (REQ long-content edge case)
- **Use keyboard and assistive technology** — Given keyboard-only navigation — expected: semantic headings, labeled controls, logical focus order, visible focus, and operable links (verifies N2)
- **Fit viewports** — Given 320px mobile and desktop widths — expected: cards and actions remain usable without page-level horizontal scrolling (verifies N1, R8)
- **Preserve public details** — Given an existing detail page — expected: its fields and media behavior remain unchanged (guards ARCH regression for LaunchScreens.tsx)

#### Testable Seams
- Render states and card fields in apps/web/src/launches/LaunchScreens.test.tsx.
- Handler behavior for dates, detail navigation, retry, and Load more.
- Semantic headings, accessible names, and focusable controls.

### Implementation Notes

- **Module(s):** apps/web/src/launches.
- **Pattern reference:** PublicLaunchPage, launches.css, and shared Action/status/empty-state primitives.
- **Key decisions:** One shared list; API todayDate bounds selection; API order/cursor are authoritative; only card fields are exposed; no rank claims.
- **Libraries:** Existing React, TypeScript, TanStack Query, CSS, Vitest; no new dependencies.
- **High-risk callouts:** Check keyboard use, long founder content, and responsive behavior; preserve existing public details.

### Scope Boundaries

- Do NOT add search, topic filters, votes, ranking, comments, or upcoming launches.
- Do NOT duplicate the list for homepage and archive.
- Do NOT change homepage composition; T6 owns it.

### Files Expected

**New files:**
- apps/web/src/launches/LaunchDiscovery.tsx (shared card/list/date/state rendering)

**Modified files:**
- apps/web/src/launches/launches.css (responsive neobrutalist list styles)
- apps/web/src/launches/LaunchScreens.test.tsx (UI seams and public-detail regression guard)

**Must NOT modify:**
- apps/api/app/modules/products/routes.py and apps/api/app/modules/launches/service.py (reuse current public-media and booking boundaries)
- apps/web/src/home/HomePage.tsx and home.css (T6 owns home layout)

---

## Task T6: Make today's launches primary on the homepage

> **Status:** not started
> **Verification:** ui
> **Effort:** s
> **Priority:** high
> **Depends on:** T5
> **Satisfies REQs:** R1, R8, N1, N2
> **Footprint slice:** Modified: HomePage, home stylesheet, and homepage tests.
> **High-risk areas touched:** Guest homepage and launches UI (M).

### Description

Compose the shared discovery list into the homepage as primary content while retaining a compact introduction. Preserve signed-out account actions, signed-in workspace entry, and connectivity outage messaging.

### Verification Checklist

- **Prioritize today's list** — Given a homepage load — expected: the daily launch list is primary and the marketing introduction is compact (verifies R1)
- **Retain discovery states** — Given loading, empty, error, and populated responses — expected: the homepage shows the shared list behavior (verifies R1, R7)
- **Preserve signed-out actions** — Given a visitor without a session — expected: registration and sign-in actions remain visible and work (verifies R1)
- **Preserve signed-in actions** — Given verified founder/member and reviewer sessions — expected: correct workspace/review action remains available (verifies R1; guards account-action regression)
- **Preserve outage messaging** — Given unavailable connectivity — expected: existing outage banner and retry remain visible (guards HomePage regression)
- **Check responsive keyboard use** — Given 320px and desktop widths with keyboard-only navigation — expected: content, actions, and focus indicators remain usable without page-level horizontal scroll (verifies N1, N2, R8)

#### Testable Seams
- Homepage render states for signed-out, signed-in, reviewer, and outage.
- Primary-list/compact-intro hierarchy.
- Keyboard-visible focus and narrow viewport observation.

### Implementation Notes

- **Module(s):** apps/web/src/home.
- **Pattern reference:** Existing HomePage session/workspace selection, connectivity hook, and shared LaunchDiscovery from T5.
- **Key decisions:** Today's launches primary; compact intro; preserve account and outage actions; approved visual direction.
- **Libraries:** Existing React, TypeScript, TanStack Query, CSS; no new dependencies.
- **High-risk callouts:** Verify workspace/reviewer actions and outage banner during homepage restructuring.

### Scope Boundaries

- Do NOT remove registration, sign-in, workspace, review, or outage actions.
- Do NOT change API, card, or archive behavior.
- Do NOT add marketing sections beyond the compact existing introduction.

### Files Expected

**New files:**
- None.

**Modified files:**
- apps/web/src/home/HomePage.tsx (compose primary list and compact intro)
- apps/web/src/home/home.css (responsive hierarchy)
- apps/web/src/home/HomePage.test.tsx (session actions, hierarchy, outage regression)

**Must NOT modify:**
- apps/web/src/identity and apps/web/src/connectivity (preserve existing contracts)
- specs/requirements/REQ-guest-launch-discovery.md (planning decision already recorded)

---

## Task T7: Add and compose dated archive routes

> **Status:** not started
> **Verification:** tdd
> **Effort:** s
> **Priority:** high
> **Depends on:** T5
> **Satisfies REQs:** R4, R5
> **Footprint slice:** Modified: route classifier, App composition, LaunchScreens route integration, route/App/launch screen tests.
> **High-risk areas touched:** Browser navigation (M); Guest homepage and launches UI (M).

### Description

Add the reloadable /launches/archive/YYYY-MM-DD route and render the shared list in the public shell. Exact route matching must preserve founder /launches and existing public detail /launches/{productId}.

### Test Plan

#### Test File(s)
- apps/web/src/routing.test.ts
- apps/web/src/App.test.tsx
- apps/web/src/launches/LaunchScreens.test.tsx

#### Test Scenarios

##### Archive Route Classification

- **classifies a real archive date** — GIVEN /launches/archive/2026-10-20 WHEN classified THEN it resolves to a public archive route carrying that date (verifies R4, R5)
- **rejects invalid dates and segments** — GIVEN malformed or impossible calendar dates and wrong segment counts WHEN classified THEN the route is unavailable (REQ date-selection edge case)
- **preserves existing launch routes** — GIVEN /launches or /launches/{productId} WHEN classified THEN founder calendar and public details retain their route types (guards routing regression)

##### App Composition

- **renders a direct archive load publicly** — GIVEN an archive URL loaded directly WHEN App renders THEN its shared list uses PublicShell without requiring a session (verifies R4)
- **preserves calendar and detail screens** — GIVEN existing founder calendar or public detail URLs WHEN App renders THEN each keeps its current view/shell (guards ARCH routing regression)
- **keeps navigation reloadable** — GIVEN previous/next selection WHEN the date changes THEN the URL changes and reloading resolves the same date (verifies R4, R5)

### Implementation Notes

- **Module(s):** apps/web/src/routing.ts, App.tsx, launches/LaunchScreens.tsx.
- **Pattern reference:** classifyRoute, navigate, existing /launches route, and PublicLaunchPage.
- **Key decisions:** Exact archive path; real-date validation; public shell; preserve founder calendar and detail routes.
- **Libraries:** Existing lightweight routing and React; no new dependency.
- **High-risk callouts:** The archive shares a prefix with two existing routes; exact segment matching and regression tests protect them.

### Scope Boundaries

- Do NOT change booking, scheduling, publication, or public product-detail contracts.
- Do NOT add a routing library or query-string archive.
- Only add archive classification and compose the shared list.

### Files Expected

**New files:**
- None.

**Modified files:**
- apps/web/src/routing.ts (strict archive classifier)
- apps/web/src/App.tsx (public archive composition)
- apps/web/src/launches/LaunchScreens.tsx (shared list route integration)
- apps/web/src/routing.test.ts (date validation and route regression)
- apps/web/src/App.test.tsx (shell and existing-route regression)
- apps/web/src/launches/LaunchScreens.test.tsx (founder calendar/detail regression)

**Must NOT modify:**
- apps/api/app/modules/launches/service.py and apps/worker/worker.py (publication remains unchanged)
- Founder booking behavior under /launches (guard existing behavior only)

---

## Task T8: Document local guest discovery checks

> **Status:** not started
> **Verification:** checklist
> **Effort:** xs
> **Priority:** medium
> **Depends on:** T6, T7
> **Satisfies REQs:** R4
> **Footprint slice:** Modified: developer guide with guest routes and local smoke-check.
> **High-risk areas touched:** None.

### Description

Document the homepage and dated archive routes plus a concise local check for populated, empty, and failed states. This helps developers inspect the feature without changing product scope or production procedures.

### Verification Checklist

- **Document guest routes** — Given docs/development.md — expected: it names / and /launches/archive/YYYY-MM-DD, bounds selection to current UTC date, and distinguishes founder /launches and public /launches/{productId} (verifies R4)
- **Document local smoke-check** — Given a developer following the new section — expected: instructions identify the existing local stack and populated/empty/error, retry, and product-detail observations without real production credentials
- **Check references and formatting** — Given the edited guide — expected: commands/files match existing setup guidance and git diff --check exits 0

### Implementation Notes

- **Module(s):** Developer documentation.
- **Pattern reference:** Existing setup and manual product guidance in docs/development.md.
- **Key decisions:** Keep guest routes distinct from founder calendar/detail; use local disposable data and documented setup commands.
- **Libraries:** None.
- **High-risk callouts:** None.

### Scope Boundaries

- Do NOT add production credentials, deployment procedures, or a new QA framework.
- Do NOT revise the REQ or ARCH.
- Only add local route and smoke-check guidance.

### Files Expected

**New files:**
- None.

**Modified files:**
- docs/development.md (guest routes and local smoke-check)

**Must NOT modify:**
- specs/requirements/REQ-guest-launch-discovery.md (scope decision already recorded)
- docs/PRODUCTION_DEPLOYMENT_PROXMOX.md and docs/PRODUCTION_RECOVERY.md (production procedures are unrelated)

---

_UI and checklist tasks use human-observed verification supported by focused component tests. The quality gate and /plan-qa → /execute-qa remain independent post-implementation checks for this runnable API and UI surface._
