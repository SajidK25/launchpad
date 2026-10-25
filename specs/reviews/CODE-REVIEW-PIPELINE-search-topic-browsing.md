# Code Review — Search and Topic Browsing

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: `ARCH-search-topic-browsing` |
| **Target** | `dev` at `903dcc4` plus local review remediations (uncommitted) |
| **Date** | 2026-10-24 |
| **Tech Stack** | Python 3.12, FastAPI, async SQLAlchemy, PostgreSQL/Alembic, Strawberry GraphQL, React, TypeScript, TanStack Query, Vitest, Playwright |
| **Checks Run** | Requirement coverage, task completion, code quality, React patterns, security, database patterns, migration safety; aggregate quality pipeline; catalog p95 baseline |
| **Checks Skipped / Manual** | Protected R2 validation; production-like concurrent load; production migration-role permissions |
| **Original Feature Diff** | 32 files, +3,417 / -63 lines. Local remediation adds changes in 8 feature files; `.env.example` and planning artifacts are pre-existing user work and were left untouched. |

## Verdict: ⚠️ PASS WITH MANUAL CHECKS

The implementation and review findings are addressed. The final aggregate quality pipeline passed, including backend and web suites, contract checks, security scans, builds, and browser tests. Two production-only conditions remain unverified: concurrent search performance at the required scale and permissions for the production migration role. The protected R2 validation test also remains skipped by design outside its protected workflow.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Requirement coverage | 0 | 0 | 0 | 0 | 1 |
| Task completion | 0 | 0 | 0 | 0 | 0 |
| React patterns | 0 | 0 | 0 | 0 | 0 |
| Code quality | 0 | 0 | 0 | 0 | 0 |
| Migration safety | 0 | 0 | 0 | 0 | 1 |
| Security | 0 | 0 | 0 | 0 | 0 |
| Database patterns | 0 | 0 | 0 | 0 | 0 |
| **Total** | **0** | **0** | **0** | **0** | **2** |

## Requirement Coverage

**Criteria:** 20/21 covered · 0 weak · 0 uncovered · 1 manual.

| Req | Criterion (abridged) | Evidence | Run | Status |
|-----|----------------------|----------|-----|--------|
| R1 | Guest/member Discover; home and archive routes remain | App route and browser suites | ✅ Executed | ✅ Covered |
| R2 | Case-insensitive partial search over name, pitch, description; 200-char limit | `test_reads.py`: pitch-only search, exact 200 accepted, 201 rejected | ✅ Executed | ✅ Covered |
| R3 | Launched-only topic choices, OR semantics, max 20 selected | API topic tests and `DiscoverPage.test.tsx` | ✅ Executed | ✅ Covered |
| R4 | Text AND topic filters | API test excludes a text match with none of the selected topics | ✅ Executed | ✅ Covered |
| R5 | Newest-first, name and ID tie-breaks | API ordering and cursor continuation across dates and duplicate names | ✅ Executed | ✅ Covered |
| R6 | Card media, product details, and links | UI test checks logo source/alt and both detail links | ✅ Executed | ✅ Covered |
| R7 | Bounded paging and duplicate-free Load more | UI and hook tests | ✅ Executed | ✅ Covered |
| R8 | URL filters restore on open/reload/history navigation | Route tests, URL navigation regression, browser suite | ✅ Executed | ✅ Covered |
| R9 | Retryable failure; filters retained through retry | UI test retries while search and topic filters are active | ✅ Executed | ✅ Covered |
| R10 | All non-launched statuses stay private | API tests cover draft, submitted, changes-requested, rejected, approved, scheduled | ✅ Executed | ✅ Covered |
| N1 | p95 ≤1s at 10,000 launched products under production-like load | Local serial benchmark only; production-like concurrency not run | ⚠️ Manual | ⚠️ Manual |
| N2 | Mobile/desktop usability and keyboard operation | Browser keyboard traversal and 320px/desktop overflow checks | ✅ Executed | ✅ Covered |
| N3 | No unpublished data in results, options, or UI | API, GraphQL, and UI privacy assertions | ✅ Executed | ✅ Covered |
| E1–E3 | Blank filters, no-match state, invalid input | UI tests | ✅ Executed | ✅ Covered |
| E4 | Failure retry preserves filters | Filtered failure/retry UI test | ✅ Executed | ✅ Covered |
| E5 | Topics OR together while text remains required | API AND/OR behavior tests | ✅ Executed | ✅ Covered |
| E6 | Approved/scheduled products stay private | API privacy fixtures/assertions | ✅ Executed | ✅ Covered |
| E7 | Long content fits narrow screens | 320px browser check | ✅ Executed | ✅ Covered |
| E8 | Saved filtered URL restores search/topics | Browser history and URL tests | ✅ Executed | ✅ Covered |

No orphaned production files were found.

## React Patterns, Code Quality, and Security

- URL-backed filters now drive query keys and displayed selections during history navigation; regression coverage verifies updated query props.
- `DiscoverPage` delegates filter controls and results presentation to `DiscoverFilters` and `DiscoverResults`.
- `packages/contracts/operations.graphql` is formatted with the repository-pinned Prettier.
- Security review found no issues. Anonymous results and topic options remain limited to launched products; query input and cursors are bounded and safely handled.
- Database review found no issues. Catalog pages are bounded, related data is batch-loaded, and migration indexes match the search and ordering paths.
- Task completion review found no scope drift from the approved REQ/ARCH/TASKS.

## Migration Safety

**Result:** ⚠️ Manual check required. The migration is additive and local migration checks passed. The production migration role's ability to create/use `pg_trgm` and build the indexes cannot be verified from this checkout.

## Verification Results

- `sh scripts/quality/run.sh`: **passed (exit 0)**.
- Backend: **467 passed, 1 skipped**. The skipped test requires the protected R2 validation workflow. The run reported 67 dependency deprecation warnings.
- Web: **193 passed**; formatting, lint, typecheck, and production build passed.
- GraphQL/API contracts, configured builds, and security checks passed; npm audit reported zero vulnerabilities.
- Browser suite: **9 passed**.
- Targeted 10,000-product local catalog benchmark: p95 **0.018s** across 80 serial reads at concurrency 1. This is a local baseline, not production-like performance evidence.
- `git diff --check`: passed after remediation.

## Remaining Manual Checks

- [ ] Run the 10,000-product workload with documented production-like concurrency and record p95 (N1).
- [ ] Confirm the production migration principal can use `pg_trgm` and build the required indexes before rollout.

## Prioritized Actions

### Must Fix

None.

### Before Production Rollout

- Complete the production-like concurrent search benchmark.
- Verify production migration-role permissions.

---
*Updated after review remediation — 2026-10-24.*
