# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: `ARCH-guest-launch-discovery.md` |
| **Target** | Branch `dev`, implementation diff `3a92f9c^..12b4720` plus review-fix working tree |
| **Date** | 2026-10-22 (resolution pass) |
| **Tech Stack** | Python, FastAPI, SQLAlchemy, PostgreSQL, GraphQL/Strawberry, React, TypeScript, TanStack Query, pytest, Vitest |
| **Checks Run** | Original review checks plus API/integration tests, frontend tests, browser accessibility/navigation checks, Ruff, and Prettier |
| **Checks Skipped** | Config/dependencies (no dependency/config changes); Express patterns (FastAPI application); runtime behavior (overlaps selected async and React checks) |
| **Files Changed** | Original review: 36; resolution pass adds targeted fixes and tests |
| **Lines Changed** | Original review diff: +2422 / -325; resolution pass adds regression coverage |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered (36 files, 2747 changed lines)
- [x] Tech stack detected: Python/FastAPI/SQLAlchemy/PostgreSQL/GraphQL and React/TypeScript/TanStack Query
- [x] Context read (project instructions in `AGENTS.md`, linked REQ, ARCH, and TASKS)
- [x] Triage proposed and developer confirmed
- [x] 14 checks dispatched: task completion, requirement coverage, code quality, security, database patterns, migration, performance, error handling, documentation, TypeScript strictness, async patterns, React patterns, accessibility, and test coverage
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Original Review Detail — Findings Closed Below

## Verdict: ✅ PASS — All Actionable Findings Resolved

The feature implements the agreed public launch feed, archives, bounded pagination, and shared guest UI. All 13 code findings from the original review have been addressed. API, migration, frontend, and browser checks pass. No security or type-safety defect was found.

### Resolution summary

| Finding | Resolution | Verification |
|---------|------------|--------------|
| DB-1 | Cursor now carries the database-computed `lower(name)` key; PostgreSQL integration coverage pages Unicode names across boundaries. | API/integration suite: 28 passed. |
| PF-1 | Repository uses narrow product and logo projections without storage keys. | API read tests and query-shape assertions pass. |
| PF-2 | Logos load lazily and decode asynchronously; card rendering is covered. | Frontend tests and populated-card browser scan pass. |
| EH-1 | Launch requests pass TanStack cancellation and use a bounded timeout, with timeout/retry cleanup tests. | Frontend tests: 174 passed. |
| EH-2 | Unexpected GraphQL read failures emit sanitized structured diagnostics correlated by request ID. | GraphQL tests and Ruff checks pass. |
| DOC-1, DOC-2 | README startup guidance and roadmap status now reflect the current guest launch feature. | Documentation diff reviewed. |
| AX-1, AX-2 | Homepage-to-archive navigation moves focus to main; completed, empty, and loading states expose status announcements. | Browser keyboard/focus and Axe checks pass. |
| T-1 | Migration coverage verifies upgrade/downgrade, index removal, and preservation of launched and non-launched rows. | API/integration suite: 28 passed. |
| T-2, T-3 | Tests assert batched lookups use only visible IDs and page sizes 1/50 honor lookahead limits. | API read tests pass. |
| T-4 | Midnight refresh test asserts its timer is cleared on unmount. | Frontend tests: 174 passed. |

Browser verification: 8 scenarios passed, including keyboard archive navigation, focus placement, live status text, populated cards, Axe checks, and 320px overflow checks. A human screen-reader session and a query plan at production-like row counts were not run; these are operational follow-ups, not unresolved code findings.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion | 0 | 0 | 0 | 0 | 0 |
| Requirement coverage | 0 | 0 | 0 | 0 | 1 |
| Code quality | 0 | 0 | 0 | 0 | 0 |
| Security | 0 | 0 | 0 | 0 | 0 |
| Database patterns | 0 | 0 | 0 | 0 | 1 |
| Migration | 0 | 0 | 0 | 0 | 0 |
| Performance | 0 | 0 | 0 | 0 | 0 |
| Error handling | 0 | 0 | 0 | 0 | 0 |
| Documentation | 0 | 0 | 0 | 0 | 0 |
| TypeScript strictness | 0 | 0 | 0 | 0 | 0 |
| Async patterns | 0 | 0 | 0 | 0 | 0 |
| React patterns | 0 | 0 | 0 | 0 | 0 |
| Accessibility | 0 | 0 | 0 | 0 | 1 |
| Test coverage | 0 | 0 | 0 | 0 | 0 |
| **Total remaining** | **0** | **0** | **0** | **0** | **3** |

## Task Completion

No task-level blockers were found. The implementation also updates shared browser regression specs outside the narrow T6 footprint; these edits intentionally verify navigation, accessibility, and connectivity behavior affected by this feature.

## Requirement Coverage

The API enforces launched-only visibility and the UI distinguishes loading, empty, and failure states. API and browser tests cover date, ordering, archive, public projection, and homepage behavior. A manual visual pass against the design references remains an optional product acceptance check.

### Original manual coverage notes

- ⚠️ R8 visual acceptance: a human visual pass against approved design references was not run.
- ✅ N1 responsive behavior: browser automation verifies 320px without page-level horizontal scrolling.
- ✅ N2 keyboard behavior: browser automation verifies date controls, archive navigation, focus, and links.

## Code Quality

No actionable code-quality findings.

## Security

No actionable security findings. The public projection is allowlisted and the read path filters products to the launched state.

## Database Patterns

### Findings

| # | Severity | Location | Finding |
|---|----------|----------|---------|
| DB-1 | 🟡 Medium | `apps/api/app/modules/products/service.py:1970-1974`; `apps/api/app/modules/products/repository.py:528-537` | The cursor normalizes names with Python `str.lower()`, while PostgreSQL orders and compares `lower(name)`. Unicode/collation differences can cause a cursor boundary to disagree with the database and skip or repeat products. Encode a database-computed sort key in the cursor and cover Unicode names across page boundaries using PostgreSQL. |

### Original manual check

- ⚠️ Inspect `EXPLAIN` for the daily listing at representative data volume. The partial `launched_at` index supports the date filter, but the `lower(name), id` ordering may still require a sort.

## Migration

The migration is additive and has a downgrade path; no migration implementation defect was found. Its automated rollback and row-preservation evidence is incomplete; see Task Completion #3 / Test Coverage #1.

## Performance

### Findings

| # | Severity | Location | Finding |
|---|----------|----------|---------|
| PF-1 | 🟡 Medium | `apps/api/app/modules/products/repository.py:529-555` | Listing loads full `Product` rows when the card needs only ID, name, and pitch; the logo batch query also materializes full `ProductAsset` rows including storage keys. Use explicit column projections and a narrow logo projection. This reduces database transfer and keeps storage metadata out of the read model. |
| PF-2 | 🟡 Medium | `apps/web/src/launches/LaunchDiscovery.tsx:130-132` | Card logos are eagerly loaded without a size bound. At 20 cards, original assets up to the configured 5 MiB limit could transfer about 100 MiB; the maximum 50-card page could reach about 250 MiB. Add lazy loading and asynchronous decoding, and consider purpose-sized public thumbnails. |

### Original manual check

- ⚠️ Capture the listing query plan at representative volume and review the cost of sorting on `lower(name), id`.

## Error Handling

### Findings

| # | Severity | Location | Finding |
|---|----------|----------|---------|
| EH-1 | 🟡 Medium | `apps/web/src/launches/client.ts:68-86`; `apps/web/src/launches/useLaunches.ts:54` | The public GraphQL request has no timeout and the query discards TanStack Query's abort signal. A stalled request can leave the page loading indefinitely; changing dates also cannot cancel obsolete work. Pass the query signal, add a bounded timeout, and test timeout/retry behavior. |
| EH-2 | 🟡 Medium | `apps/api/app/modules/products/graphql.py:200-209` | `_safe_read` hides unexpected exceptions from both clients and server logs. Production failures therefore have no resolver-level diagnostic or request correlation. Log a sanitized exception class, operation/resolver, and correlation ID without logging private payloads or variables. |

### Original manual check

- ✅ Retry states and sanitized resolver diagnostics are covered by automated client and GraphQL tests.

## Documentation

### Findings

| # | Severity | Location | Finding |
|---|----------|----------|---------|
| DOC-1 | 🟡 Medium | `README.md:15` | Local startup instructions still tell developers to confirm the root page reports **Connected**. The root now renders guest launch discovery when healthy. Update this check and link to the discovery smoke-check in `docs/development.md`. |
| DOC-2 | 🟡 Medium | `docs/roadmap.md:19-23` | The document claims to show current implementation status but still lists launch scheduling/publication and guest discovery as future work. Move completed work into **Built** and leave only deferred search/topic discovery in that roadmap item. |

## TypeScript Strictness

No actionable TypeScript strictness findings.

## Async Patterns

No separate finding beyond Error Handling #1; the ignored query cancellation signal is included there to avoid duplicate findings.

## React Patterns

No actionable React-pattern findings.

## Accessibility

### Findings

| # | Severity | Location | Finding |
|---|----------|----------|---------|
| AX-1 | 🟡 Medium | `apps/web/src/home/HomePage.tsx:94-97`; `apps/web/src/App.tsx:108-116` | Selecting a past date from the homepage replaces the focused date input with the archive route, but route handling does not move focus to the archive heading or main content. Keyboard users can lose their place. Focus the archive heading/main after this route transition while preserving focus for in-archive date changes. WCAG 2.1 SC 2.4.3. |
| AX-2 | 🟡 Medium | `apps/web/src/launches/LaunchDiscovery.tsx:35-117` | Date navigation announces the transient loading state but not the completed selected date or result count/empty state. Add a polite status message when results complete, including the selected date and zero-result case. WCAG 2.1 SC 4.1.3. |

### Original manual checks

- ✅ Keyboard archive navigation, focus, and 320px populated-card traversal pass browser automation.
- ✅ Axe browser checks pass for loaded and empty launch states.
- ⚠️ A human screen-reader session and desktop visual review remain useful follow-ups.

## Test Coverage

### Findings

| # | Severity | Location | Finding |
|---|----------|----------|---------|
| T-1 | 🟡 Medium | `tests/integration/test_production_migrations.py:156-183` | The migration test upgrades to 0014 and checks index creation plus an approved row, but does not downgrade, assert index removal, or preserve both launched and non-launched row snapshots (including a real `launched_at`). Add a two-row snapshot check across upgrade and downgrade. |
| T-2 | 🟡 Medium | `apps/api/app/modules/products/tests/test_reads.py:241-259` | Tests verify a logo and topic are returned but not that each association method is called once with only visible-page IDs, excluding the lookahead row. Add repository call recording and assert the batching contract. |
| T-3 | 🟡 Medium | `apps/api/app/modules/products/tests/test_reads.py:78-95` | The page-boundary test rejects invalid sizes and checks the default, but does not prove `first=1` and `first=50` are accepted with lookahead limits 2 and 51. |
| T-4 | 💭 Low | `apps/web/src/launches/useLaunches.test.ts:76` | The midnight-refresh test creates a `clearTimeout` spy but never asserts cleanup. Add an unmount assertion that the captured timer is cleared. |

API, GraphQL, contract generation, client, query, component, route, and public-detail regression scenarios are covered by focused tests; verification results are summarized at the top of this report.

## Operational Follow-ups

- [x] Browser automation verified keyboard archive navigation, focus placement, result announcements, populated-card Axe checks, and 320px horizontal overflow.
- [x] Automated frontend/API tests cover retry behavior and sanitized resolver diagnostics.
- [ ] A human screen-reader session remains useful to confirm the announcements with the assistive technology used by customers.
- [ ] Inspect the listing query plan at production-like row counts; current integration coverage verifies correctness, not representative-volume planner behavior.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

None.

### Should Address (🟡 Medium)

All six original should-address items are resolved; see the resolution summary above.

### Nice to Have (💭 Low)

The original low-priority timer cleanup check is resolved and covered by the frontend suite.

---
*Generated by Review — 2026-10-22 14:19 UTC*
