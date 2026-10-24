# Tasks

## Task T1: Implement Launched Catalog Search and Topic Reads

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** None
> **Satisfies REQs:** R2, R3, R4, R5, R6, R7, R10, N3
> **Footprint slice:** Modified: product models, repository, and service; product `test_reads.py`.
> **High-risk areas touched:** Products read service/repository (H); privacy boundary for topics (H).

### Description

Implement the products-domain read behavior for searching and browsing the full launched catalog. Keep filtering, bounds, deterministic paging, and public projections within the products module so later GraphQL and web tasks can consume a stable service contract.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_reads.py`

#### Test Scenarios

##### Public Catalog Matching

- **matches partial terms case-insensitively across public fields** — GIVEN launched products with matching name, pitch, or description text WHEN a partial mixed-case search is submitted THEN each matching product is returned _(verifies R2)_
- **requires every term but allows terms in different fields** — GIVEN products where query terms occur across name, pitch, and description WHEN a multi-term query is submitted THEN only products matching every term somewhere across those fields are returned _(verifies R2)_
- **treats SQL wildcard characters as literal search input** — GIVEN search text containing `%` or `_` WHEN the catalog is searched THEN those characters do not broaden matching beyond the literal query _(verifies R2, N3)_
- **applies topic OR and text AND semantics** — GIVEN products associated with different selected topics and a text query WHEN one or more topic IDs are selected THEN a result must match the text and at least one selected topic, without duplicate products _(verifies R3, R4)_

##### Public Scope and Ordering

- **limits results and topic options to currently launched products** — GIVEN products and topics in launched and unpublished states WHEN catalog and public topic reads run THEN unpublished products and topics without a current launched association are absent _(verifies R3, R10, N3)_
- **orders by launch date, normalized name, and deterministic ID** — GIVEN products launched on different dates and same-date names including identical names WHEN results are read THEN newest dates come first and ties have stable name/ID order _(verifies R5)_
- **returns only the public card projection and batches visible card data** — GIVEN a page with logos, topics, and private product fields WHEN the service returns the page THEN it includes only approved public card fields and reads associations only for visible page IDs _(verifies R6, N3)_

##### Bounds, Pagination, and Regression Guard

- **enforces query, topic, page, and cursor bounds** — GIVEN text over 200 characters, more than 20 topic IDs, page sizes outside 1–50, malformed cursors, or cursors from different filters WHEN the service is called THEN it returns the established typed validation error _(verifies R2, R3, R7; REQ edge case)_
- **continues a keyset page without duplicates or reordering** — GIVEN more matches than one page WHEN the next cursor is used with the same filters THEN the next page continues after the prior page and no product is repeated _(verifies R5, R7)_
- **preserves existing daily launch reads** — GIVEN existing date-filtered public launch data WHEN daily/archive service reads execute alongside the catalog implementation THEN their date selection, ordering, card fields, and paging remain unchanged _(guards ARCH backward-regression risk for `apps/api/app/modules/products/repository.py` and `service.py`)_

### Implementation Notes

- **Module(s):** `app.modules.products.repository`, `app.modules.products.service`, and product models.
- **Pattern reference:** Existing `list_public_launches` and `ProductService.public_launches` implementations in the products repository/service.
- **Key decisions:** A2, A3, A4, A5, A8, and A9; use launched-only predicates, `EXISTS` for topic matching, parameterized escaped partial matching, and a cursor bound to normalized filters.
- **Libraries:** Existing SQLAlchemy/PostgreSQL stack; do not add a hosted search dependency.
- **High-risk callouts:** Keep the repository query and topic options strictly public; existing founder `topicChoices` includes private proposals and must remain separate.

### Scope Boundaries

- Do NOT add GraphQL fields, frontend behavior, caching, ranking, typo correction, or a search service in this task.
- Do NOT change existing topic proposal behavior or launch lifecycle state.
- Only implement the products-domain service/repository contract and its listed tests.

### Files Expected

**New files:**
- None.

**Modified files:**
- `apps/api/app/modules/products/models.py` (declare the search/order and reverse topic association indexes in metadata)
- `apps/api/app/modules/products/repository.py` (launched-only catalog and topic option reads, filter predicates, deterministic keyset paging, narrow projections and visible-page association reads)
- `apps/api/app/modules/products/service.py` (public catalog/topic services, normalization, validation, cursor binding and public projections)
- `apps/api/app/modules/products/tests/test_reads.py` (TDD scenarios above)

**Must NOT modify:**
- `apps/api/app/modules/products/tests/test_topics.py` (founder topic proposal behavior remains unchanged; privacy guard is covered through the separate public read)
- `apps/api/app/modules/launches` (launch lifecycle and booking remain unchanged)
- Any GraphQL, contract, web, migration, or documentation paths assigned to later tasks.

### TDD Sequence

1. Add failing repository/service tests for matching, topic semantics, ordering, bounds, and cursor behavior.
2. Implement repository projections and service validation/cursors until the tests pass.
3. Refactor and confirm the regression guard for existing daily launch reads still passes.

---

## Task T2: Expose Catalog Reads and Add PostgreSQL Search Indexes

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T1
> **Satisfies REQs:** R2, R3, R4, R6, R7, R10, N1, N3
> **Footprint slice:** New: migration `0015`; modified: product GraphQL, GraphQL composition, GraphQL operations/schema/generated types; product GraphQL tests, GraphQL composition integration tests, production migration integration tests.
> **High-risk areas touched:** PostgreSQL schema and migration (M); GraphQL composition and contracts (M); privacy boundary for topics (H); release and migration operations (M).

### Description

Expose T1's read services through the existing anonymous products GraphQL boundary and publish the additive generated contracts. Add the PostgreSQL extension and partial indexes required for the agreed substring search and stable order, with verification that the migration preserves existing data and that public composition never exposes unpublished products or topic proposals.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_graphql.py`
- `tests/integration/test_graphql_composition.py`
- `tests/integration/test_production_migrations.py`

#### Test Scenarios

##### GraphQL Contract and Privacy

- **composes public catalog reads whenever launch reads are enabled** — GIVEN public launch reads are enabled and private product reads are disabled WHEN the composed schema is inspected and queried anonymously THEN catalog and topic fields are available without requiring a session _(verifies R1, R10)_
- **maps invalid catalog inputs to safe GraphQL errors** — GIVEN an overlong query, too many topics, invalid page size, or malformed/mismatched cursor WHEN the public field is queried THEN the response uses the existing safe error mapping and reveals no stack trace or private data _(verifies R2, R3, R7, N3; REQ edge case)_
- **does not expose private products or founder topic proposals** — GIVEN a signed-in founder with private topic proposals and products in non-launched states WHEN catalog or topic reads are queried THEN only launched products and topics attached to currently launched products appear _(verifies R10, N3; guards ARCH backward-regression risk for `apps/api/app/modules/products/tests/test_topics.py`)_
- **returns the public card schema and cursor contract** — GIVEN an anonymous catalog request WHEN the query succeeds THEN GraphQL returns public summary fields and an optional next cursor without private description/media fields _(verifies R6, R7, N3)_

##### Migration and Performance

- **upgrades and downgrades only the catalog indexes** — GIVEN the previous migration head and existing product rows WHEN the new revision is upgraded and downgraded THEN required `pg_trgm` and launched-only indexes are present after upgrade, feature indexes are removed after downgrade, the extension remains installed, and product data is unchanged _(verifies N1; guards ARCH backward-regression risk for `0015_public_catalog_search.py`)_
- **measures first-page p95 at 10,000 launched products** — GIVEN a seeded PostgreSQL catalog of 10,000 launched products and a documented production-like workload/concurrency WHEN representative blank, short-term, multi-term, and topic-filtered searches are measured THEN first-page p95 is at most one second and the run records environment, workload, and concurrency _(verifies N1)_
- **surfaces database read failure safely** — GIVEN the catalog repository raises a database failure WHEN GraphQL handles the request THEN it returns the established safe public read error rather than an empty page or raw exception _(verifies R9; ARCH forward-stress scenario)_

### Implementation Notes

- **Module(s):** `app.modules.products.graphql`, `app.graphql`, Alembic, and `packages/contracts`.
- **Pattern reference:** Existing `PublicProductQuery.publicLaunches`, `_ALLOWED_ROOT_FIELDS`, migration `0014_public_launch_discovery_index.py`, and current contract generation workflow.
- **Key decisions:** A1, A2, A3, A8, and A9; include the catalog fields whenever public launch reads are enabled, and keep resolvers thin.
- **Libraries:** Existing Strawberry GraphQL, Alembic, PostgreSQL `pg_trgm`, and GraphQL contract tooling.
- **High-risk callouts:** Confirm the production migration role can create/use `pg_trgm`; migration failure must stop rollout before code requires the indexes. Keep safe root allowlist and generated contracts in sync.

### Scope Boundaries

- Do NOT add a Redis cache, hosted search engine, relevance ranking, or any new authentication requirement.
- Do NOT return description text or private media in catalog cards; description is a match field only.
- Only expose the T1 service contract, generate the stated GraphQL contracts, and add the stated additive migration.

### Files Expected

**New files:**
- `apps/api/alembic/versions/0015_public_catalog_search.py` (add `pg_trgm` and launched-only text/order/topic indexes after `0014_public_launch_index`)

**Modified files:**
- `apps/api/app/modules/products/graphql.py` (catalog page/topic types and thin anonymous resolvers)
- `apps/api/app/graphql.py` (root allowlist and launch-read composition)
- `packages/contracts/operations.graphql` (catalog and topic operations)
- `packages/contracts/schema.graphql` (generated additive schema)
- `packages/contracts/src/graphql.generated.ts` (generated operation types; regenerate, do not hand-edit)
- `apps/api/app/modules/products/tests/test_graphql.py` (public fields, validation, anonymous access)
- `tests/integration/test_graphql_composition.py` (composition modes, publication/privacy, safe failure)
- `tests/integration/test_production_migrations.py` (upgrade/downgrade, extension/index and data preservation)

**Must NOT modify:**
- `apps/api/app/modules/products/tests/test_topics.py` (founder proposal operation remains owner-scoped and unchanged)
- `apps/api/app/shared/config/settings.py` (no new flag or search-service configuration)
- `apps/api/app/modules/launches` (publication and scheduling are unchanged)

### Verification Evidence

- Backend regression set: 51 passed, including product GraphQL/read/topic tests, composition/privacy, and migration checks.
- `sh scripts/quality/contracts.sh --check`: passed; generated GraphQL contracts are current.
- Ruff check, Ruff format check, and targeted mypy for GraphQL production/test modules: passed.
- 10,000 launched-product performance scenario: 80 serial first-page reads (20 each for blank, short-term, multi-term, and topic-filtered queries) measured p95 at 0.021 seconds in the local Docker check environment. Concurrency profile was 1; this is a local baseline, not a production load test.

---

## Task T3: Add Catalog Client and Filter-Keyed Query Hooks

> **Status:** done
> **Verification:** tdd
> **Effort:** s
> **Priority:** high
> **Depends on:** T2
> **Satisfies REQs:** R3, R7, R8, R9
> **Footprint slice:** Modified: launches GraphQL client and TanStack Query hooks; launches client and hook tests.
> **High-risk areas touched:** None.

### Description

Add typed browser reads for the public catalog and its launched-only topic choices, then expose them through TanStack Query with filter-aware keys and infinite paging. This provides the data layer for the Discover view while keeping URL interpretation and presentation in the subsequent UI tasks.

### Test Plan

#### Test File(s)
- `apps/web/src/launches/client.test.ts`
- `apps/web/src/launches/useLaunches.test.ts`

#### Test Scenarios

##### Client Requests

- **sends catalog filters and cursor through the generated operation** — GIVEN search text, selected topic IDs, page size, and an optional cursor WHEN the client fetches a catalog page THEN it sends those variables and returns the typed public page _(verifies R2, R3, R7)_
- **sends selected IDs when hydrating topic labels** — GIVEN topic IDs persisted in a filtered URL WHEN the client fetches topic choices THEN it requests labels for those IDs alongside bounded suggestions _(verifies R3, R8)_
- **forwards cancellation and handles safe read failures** — GIVEN a caller abort signal or a failed GraphQL response WHEN either public read executes THEN the signal reaches the request and failures remain rejected for retry handling _(verifies R9; REQ edge case)_

##### Query State

- **keys infinite results by normalized active filters** — GIVEN equivalent normalized search/topic selections WHEN a catalog hook is created THEN results use the stable filter key and different filters cannot share cached pages _(verifies R2, R3, R8)_
- **resets pages and cancels stale work on filter changes** — GIVEN an in-flight page sequence WHEN active filters change THEN old work is cancelled/ignored and the new query begins from its first page _(verifies R7, R8)_
- **appends pages using the returned cursor and stops at the end** — GIVEN pages with and without a next cursor WHEN Load more is requested through the hook THEN the next page uses the returned cursor and no further page is requested after the final page _(verifies R7)_

### Implementation Notes

- **Module(s):** `apps/web/src/launches/client.ts` and `useLaunches.ts`.
- **Pattern reference:** Existing `fetchPublicLaunches` and `usePublicLaunches` client/query implementations.
- **Key decisions:** A5 and A6; bind query cache entries to normalized filters and use infinite query paging.
- **Libraries:** Existing generated contracts and TanStack Query.
- **High-risk callouts:** Filter changes must not append stale pages from a prior search; keep selected topic IDs in the query key.

### Scope Boundaries

- Do NOT add URL synchronization, route composition, visual components, a new router, or a separate data cache.
- Do NOT change existing daily, archive, or founder booking hooks.
- Only add catalog/topic read methods and their query hooks.

### Files Expected

**New files:**
- None.

**Modified files:**
- `apps/web/src/launches/client.ts` (anonymous catalog and topic option reads with abort signal support)
- `apps/web/src/launches/useLaunches.ts` (filter-keyed infinite catalog and topic option hooks)
- `apps/web/src/launches/client.test.ts` (request variables, abort and failure behavior)
- `apps/web/src/launches/useLaunches.test.ts` (query keys, reset/cancel, cursor paging)

**Must NOT modify:**
- `apps/web/src/home/HomePage.tsx` (homepage remains focused on today's launches)
- Existing public card, route, shell, and style files assigned to T4/T5.

### Verification Evidence

- Focused launches client and query-hook suite: 22 passed, including unchanged daily/archive hook behavior.
- Web typecheck and ESLint: passed.
- Prettier check for all four changed frontend files: passed.

### TDD Sequence

1. Add failing client tests for both operations, variables, cancellation, and errors.
2. Add failing hook tests for filter-keyed pages, reset/cancel, and cursors.
3. Implement the client and hooks, then confirm existing `usePublicLaunches` tests remain unchanged and passing.

---

## Task T4: Build Discover Filters and Reusable Public Launch Cards

> **Status:** done
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T3
> **Satisfies REQs:** R2, R3, R4, R6, R7, R8, R9, N2, N3
> **Footprint slice:** New: Discover page and shared public card; modified: daily/archive card composition and launch styles; Discover and launch screen tests.
> **High-risk areas touched:** Existing daily/archive public cards (M); privacy boundary for result summaries (H).

### Description

Create the visitor-facing Discover experience with search, a searchable multi-select topic filter, public catalog cards, and Load more. Extract the existing public launch card so daily/archive screens keep their current fields and destinations while Discover reuses the same approved summary presentation.

### Verification Checklist

- **Blank filters show the full catalog state** — expected: with empty search and no selected topics, the page shows the newest-first result cards and a usable Load more action only when another page exists.
- **Search and topic interactions apply the agreed combination** — expected: typing a partial query and selecting multiple launched topics updates results using all-term text matching and any-selected-topic semantics.
- **Input bounds are clear and preserve valid filter state** — expected: more than 200 characters or 20 selected topics shows actionable validation without silently rewriting the visitor’s valid current filters.
- **No-results and request-failure states differ** — expected: a valid zero-match query shows a no-results state; a failed request shows retry and retains the filters.
- **Pagination appends results** — expected: Load more appends the next page once, does not duplicate existing cards, and disappears when there is no next cursor.
- **Keyboard and narrow-screen interaction works** — expected: search, topic suggestions/chips, clear/remove controls, pagination, and product links are keyboard operable with visible focus; at 320px and desktop widths no page-level horizontal scrolling occurs.
- **Daily/archive card behavior is preserved** — expected: current daily and archive cards retain their public fields and existing detail links after extraction.
- **Public fields only are rendered** — expected: result cards contain the approved public summary and no private description/media data _(verifies N3)_.

#### Testable Seams
- Render loading, populated, empty, no-results, validation, and retryable error states.
- Exercise search and topic selection/removal handlers, including the 20-topic maximum.
- Assert accessible labels, keyboard-operable picker and pagination, and public card links.

### Implementation Notes

- **Module(s):** `apps/web/src/launches`.
- **Pattern reference:** `LaunchDiscovery.tsx`, `LaunchScreens.tsx`, existing public form/status primitives, and `docs/source/inspiration.md`.
- **Key decisions:** A2, A6, A7, and A8; use the existing public shell and style direction without copying reference-site layouts or branding.
- **Libraries:** Existing React, TypeScript, TanStack Query hooks from T3, and project UI primitives.
- **High-risk callouts:** Shared card extraction can regress daily/archive behavior, and every screen state must remain within the launched-only response contract.

### Scope Boundaries

- Do NOT move full-catalog search onto the homepage or alter archive date selection/order.
- Do NOT add ranking, typo correction, recommendations, private fields, or a new routing dependency.
- Only build the Discover content and reusable card presentation; route and public navigation wiring belongs to T5.

### Verification Evidence

- Discover and daily/archive regression tests: 23 passed.
- Web typecheck and ESLint: passed.
- Prettier formatted the Discover page, shared card, daily/archive composition, styles, and UI tests.
- Results remain limited to the public card projection; the integration contract supplies no description or private media fields.

### Files Expected

**New files:**
- `apps/web/src/launches/DiscoverPage.tsx` (filter, results, pagination and status-state composition)
- `apps/web/src/launches/PublicLaunchCard.tsx` (shared existing public card presentation)
- `apps/web/src/launches/DiscoverPage.test.tsx` (render and interaction seams)

**Modified files:**
- `apps/web/src/launches/LaunchDiscovery.tsx` (use the shared card without changing daily/archive behavior)
- `apps/web/src/launches/launches.css` (responsive filter, result, chip, and state styling)
- `apps/web/src/launches/LaunchScreens.test.tsx` (daily/archive card regression guards)

**Must NOT modify:**
- `apps/web/src/home/HomePage.tsx` (today’s launches remain the primary homepage content)
- `apps/web/src/launches/LaunchScreens.tsx` (public details/archive/founder calendar composition stays unchanged)
- `apps/web/src/shell/AppShell.tsx` and routing files assigned to T5.

---

## Task T5: Wire Discover Navigation and Document the Smoke Check

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T4
> **Satisfies REQs:** R1, R8, N2, N3
> **Footprint slice:** Modified: route classification, App location state, public shell navigation/style; route, App and shell tests; browser accessibility spec; development smoke-check and roadmap.
> **High-risk areas touched:** Public web routing and URL state (M); release and migration operations (M).

### Description

Make Discover directly reachable at `/discover`, add it to guest/public navigation, and propagate search-string history changes so reload, back, and forward restore the selected filters. Add browser accessibility coverage and concise development smoke-check documentation; update the roadmap entry when this feature is implemented.

### Verification Checklist

- **Direct route and navigation work** — expected: signed-out and signed-in visitors can open `/discover` directly and through the public Discover link.
- **URL filter state survives navigation** — expected: a filtered URL restores search and selected topics after reload; browser back/forward restores prior filter states without stale results.
- **Existing routes stay intact** — expected: `/`, dated archives, public launch details, account routes, and founder/reviewer workspace routes continue to classify and render as before.
- **Responsive public navigation remains usable** — expected: Discover link remains reachable at 320px and desktop without page-level horizontal overflow.
- **Browser accessibility scenario passes** — expected: `tests/browser/frontend-accessibility.spec.ts` covers signed-out/signed-in Discover, keyboard topic selection, URL restoration, 320px layout, and Axe with no new violations.
- **Development smoke-check documentation is actionable** — expected: `docs/development.md` describes search, topic combinations, URL persistence, no-results, retry, and Load more checks that can be followed against a running local app.
- **Roadmap reflects implementation completion** — expected: `docs/roadmap.md` moves search/topic browsing to built only after T1–T4 are complete.

#### Testable Seams
- Route classification for `/discover` and precedence for existing public/workspace routes.
- App location updates for query-string `popstate` and Discover rendering.
- Public navigation link rendering while workspace navigation remains unchanged.

### Implementation Notes

- **Module(s):** `apps/web/src/routing.ts`, `App.tsx`, and `shell/AppShell.tsx`; browser tests and development docs.
- **Pattern reference:** Existing `classifyRoute`, `navigate`, `App` popstate listener, and public/workspace shell separation.
- **Key decisions:** A6 and A7; use lightweight pathname navigation and reflect query state in the URL without introducing a router.
- **Libraries:** Existing React/Vitest and Playwright/Axe browser suite.
- **High-risk callouts:** Query-only location changes must trigger restoration; keep Discover link in public navigation and avoid changing founder/reviewer workspace navigation.

### Scope Boundaries

- Do NOT change homepage content, archive semantics, product detail routing, or workspace destinations.
- Do NOT mark the roadmap item built before the feature tasks are complete.
- Only wire the approved route/navigation and document/verify the shipped feature.

### Files Expected

**New files:**
- None.

**Modified files:**
- `apps/web/src/routing.ts` (classify `/discover` without shadowing current routes)
- `apps/web/src/App.tsx` (render Discover in `PublicShell` and track location search on history changes)
- `apps/web/src/shell/AppShell.tsx` (add the public Discover link only)
- `apps/web/src/shell/shell.css` (keep public navigation usable at mobile widths)
- `apps/web/src/routing.test.ts` (route classification and precedence)
- `apps/web/src/App.test.tsx` (direct route and query/history restoration)
- `apps/web/src/shell/AppShell.test.tsx` (public Discover link and unchanged workspace navigation)
- `tests/browser/frontend-accessibility.spec.ts` (signed-in/out, keyboard, URL, viewport, and Axe coverage)
- `docs/development.md` (local smoke-check flow)
- `docs/roadmap.md` (move this feature to built after implementation)

**Must NOT modify:**
- `apps/web/src/home/HomePage.tsx` (homepage stays focused on today's launches)
- `apps/web/src/launches/LaunchScreens.tsx` (archive, detail, and founder calendar behavior remains unchanged)
- Production deployment or tunnel configuration (not part of guest catalog discovery).

---

_All tasks are scoped to `specs/architecture/ARCH-search-topic-browsing.md` and its linked requirements. Implement in dependency order, one task and one conventional commit at a time._
