# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: ARCH-voting-and-daily-ranking |
| **Target** | Voting and daily ranking implementation, `c449d32..91dc7fd` |
| **Date** | 2026-10-25 01:57 +06 |
| **Tech Stack** | Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, Redis, Dramatiq, Strawberry GraphQL, React, TypeScript, Vite, WebSockets |
| **Checks Run** | Task completion, requirement coverage, code quality, security, database patterns, migration review, performance, React patterns, accessibility, configuration/dependencies, documentation |
| **Checks Skipped** | Separate test-coverage audit (not in the approved check set); runtime/manual production validation (requires staging/production traffic); migration destructive-data review (no destructive migration identified) |
| **Files Changed** | 81 |
| **Lines Changed** | +10,701 / -34 |

## Review Process

- [x] Preflight checks passed; unrelated working-tree changes were preserved
- [x] Diff gathered (81 files, 10,735 changed lines)
- [x] Tech stack detected: FastAPI/Python, PostgreSQL/Alembic, Redis, React/TypeScript
- [x] Context read (AGENTS.md, REQ, ARCH, TASKS, and review check instructions)
- [x] Triage proposed and developer confirmed
- [x] 11 checks dispatched: task completion, requirement coverage, code quality, security, database patterns, migration review, performance, React patterns, accessibility, configuration/dependencies, documentation
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to specs/reviews/

## Verdict: FAIL

The feature has broad implementation and verification coverage, and the previously run quality gate passed (523 API tests, 217 web tests, 9 browser checks, lint/type/build/security checks; one protected R2 integration test was skipped). The review found four high-severity runtime risks: source-based abuse limits collapse users behind the production tunnel, idle WebSocket disconnects can retain subscriptions, current ranking reads scan and sort the entire launch-day catalog while bypassing the Redis projection, and non-atomic counter expiry can leave permanent throttles. Several product acceptance criteria also need stronger evidence before the feature is considered production-ready.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion | 0 | 0 | 0 | 0 | 1 |
| Requirement coverage | 0 | 0 | 3 | 0 | 2 |
| Code quality | 0 | 1 | 0 | 0 | 0 |
| Security | 0 | 1 | 0 | 0 | 0 |
| Database patterns | 0 | 0 | 0 | 0 | 0 |
| Migration review | 0 | 0 | 0 | 0 | 0 |
| Performance | 0 | 1 | 0 | 0 | 0 |
| React patterns | 0 | 0 | 0 | 0 | 0 |
| Accessibility | 0 | 0 | 1 | 0 | 0 |
| Configuration/dependencies | 0 | 1 | 0 | 0 | 0 |
| Documentation | 0 | 0 | 0 | 0 | 0 |
| **Total** | **0** | **4** | **4** | **0** | **3** |

## Task Completion

| Task | Status | Evidence / gap |
|------|--------|----------------|
| T1–T15 | Implemented | Task checklist and implementation artifacts are present; full quality gate passed. T10–T13 still require staging/browser evidence for live timing, mobile/screen-reader behavior, and deployment-specific challenge settings. See Manual Checks. |

## Requirement Coverage

| Requirement | Status | Evidence / gap |
|-------------|--------|----------------|
| R1 | ✅ Covered | Eligibility and rejection paths are exercised by vote service/route tests. |
| R2 | ✅ Covered | Idempotent vote state, removal, and active-count behavior have tests. |
| R3 | 🟡 Partial | `tests/integration/test_vote_concurrency.py::test_concurrent_casts_leave_at_most_one_active_vote` races two casts only; it does not race cast against withdrawal and verify the last accepted action. |
| R4 | 🟡 Partial | Cutoff policy is implemented and tested at the service level, but no test asserts acceptance immediately before and rejection exactly at 00:00 UTC for both cast and withdrawal. |
| R5 | 🟡 Partial | Tests verify the configured half-life is bound into SQL, but do not demonstrate equal-count newer votes outranking older votes through the actual aggregate and rank path. |
| R6 | ✅ Covered | Deterministic score/count/name/ID tie behavior has coverage. |
| R7 | ⚠️ Manual | Reconnect/reconciliation behavior is implemented. The required <1s voter and <2s viewer timings have not been measured under an agreed staging workload. |
| R8 | ✅ Covered | Snapshot creation, cutoff handling, and immutable archive behavior are covered. |
| R9 | ✅ Covered | Staff review/clear/invalidate actions and audit attribution are covered. |
| R10 | 🟡 Partial | Suspension blocks future actions and there is no automatic invalidation path; an explicit regression assertion that existing votes remain counted after suspension is not evident. |
| R11 | ✅ Covered | Failed command and server-confirmed state handling have coverage. |
| R12 | ✅ Covered | Public ranking uses launched-product access and privacy coverage exists. |
| N1 | ⚠️ Manual | Freshness targets need timed staging evidence; peak workload remains unspecified in the REQ. |
| N2 | 🟡 Partial | Vote controls expose an announced count, but rank changes are rendered without an assistive-technology status announcement. Full screen-reader/browser verification remains outstanding. |
| N3 | 🟡 Partial | Cast/cast uniqueness is tested, but mixed cast/withdraw concurrency and exact-cutoff concurrency are not both demonstrated. |

## Security

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| S1 | 🟠 High | **Source velocity limits can treat all tunnel visitors as one source.** Vote actions and live-ticket issuance key limits from `request.client.host`. Production Nginx replaces `X-Forwarded-For` with `$remote_addr`, and Uvicorn trusts only the web proxy peer. With the Cloudflare Tunnel origin path, the application therefore sees the proxy/tunnel-side address rather than each visitor. A burst from legitimate users can collectively trigger Turnstile escalation and, for live tickets, a shared hard 429. Use a validated client address supplied by trusted Cloudflare ingress (and ensure untrusted clients cannot spoof it), or a source-limit design that does not collapse all visitors behind the tunnel. | `apps/api/app/modules/votes/routes.py:218-263`; `infra/docker/web.production.conf:35,54`; `compose.production.yaml:96-99` |

### Security Review Comments

- The reviewed vote routes retain authentication, origin/CSRF checks, and explicit eligibility checks; this finding concerns the source identity used by velocity enforcement in the actual production proxy chain.
- Do not simply trust arbitrary `X-Forwarded-For` or `CF-Connecting-IP` input. Restrict trust to the known Cloudflare/proxy path and normalize the chosen address at the ingress boundary.

## Performance

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| P1 | 🟠 High | **Each live ranking page scans and sorts every launch-day product, and the GraphQL factory does not wire the Redis projection.** `_live_page` loops through every product page, aggregates vote values in batches, materializes all rank entries, and sorts them even when the client requests a small page or one product's rank. The GraphQL factory supplies only `ProductService` and `VoteRepository` to `VoteReadService`. This makes read cost grow with the full day's catalog and misses the architecture's Redis current-rank path. At the 10,000-product target, a first-page request still performs catalog-wide hydration/aggregation and an in-process sort. Serve current ranks from the Redis projection with PostgreSQL fallback/rebuild, use bounded pagination, and resolve a single product rank without scanning the catalog. | `apps/api/app/modules/votes/service.py:723-760`; `apps/api/app/graphql.py:210-216` |

### Performance Review Comments

- No measured 10,000-product/10M-history benchmark result was available in the review artifacts. Record query count, latency, and cache-miss/rebuild behavior in staging after correcting P1.

## Accessibility

| # | Severity | Finding | WCAG | Location |
|---|----------|---------|------|----------|
| A1 | 🟡 Medium | **Live rank changes are not announced.** Rank values in the public ranked card and product detail render as ordinary text; the vote count has a polite live region, but a changed rank/order does not create a status announcement. A screen-reader user can hear the updated count while missing that the product moved in the ranking. Add a concise polite announcement for rank changes without placing the entire list in a live region, and test a rank update. | 4.1.3 Status Messages | `apps/web/src/votes/RankedLaunchCard.tsx:34`; `apps/web/src/launches/LaunchScreens.tsx:244-250` |

## Configuration / Dependencies

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| C1 | 🟠 High | **Velocity counter increment and expiry are separate Redis commands.** If execution stops after `INCR` creates a key at count 1 but before `EXPIRE`, later calls see count >1 and never add a TTL. The counter can then persist indefinitely and eventually cause permanent source/account throttling. Make increment plus expiry atomic (for example, a small Lua script or transaction) or repair missing TTLs on subsequent increments. | `apps/api/app/modules/votes/routes.py:423-428` |

## Code Quality

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| W1 | 🟠 High | **Idle WebSocket disconnects are not observed.** The handler awaits Redis messages but never reads from the client socket. If a browser disconnects while the channel is idle, the loop can remain alive and retain its Redis pub/sub subscription until a later publish causes a send failure. Repeated navigation/churn can accumulate tasks and subscriptions. Monitor client disconnects (or otherwise bound connection lifetime) and test cleanup when an idle client closes. | `apps/api/app/modules/votes/live.py:153-175` |

## Database Patterns, Migration Review, React Patterns, Documentation

No distinct blocking findings were identified in these approved passes. The reviewed migrations are additive and preserve vote/audit state; query parameterization, module boundaries, generated API contract updates, frontend query-state patterns, and rollout documentation were consistent with the project guidance. This does not replace the outstanding behavior tests and runtime checks listed above.

## Manual Checks Required

- [ ] After resolving S1, verify from multiple real client networks through `launchpad.t99ltd.com` that one visitor's vote velocity does not consume another visitor's source allowance and that live-ticket issuance does not return shared 429s.
- [ ] After resolving P1, run the architecture's staging ranking workload, including the agreed launch-day concurrency and catalog/history sizes; record first-page and product-specific-rank latency and freshness.
- [ ] Verify voter confirmation arrives within 1 second and other connected viewers receive count/rank updates within 2 seconds for vote and removal, with timings recorded.
- [ ] Verify disconnecting an idle WebSocket client promptly releases its Redis subscription and reconnect/tab-focus reconciliation returns current values.
- [ ] Exercise actual Cloudflare Turnstile escalation configuration in staging, including valid, invalid, and unavailable challenge service behavior.
- [ ] Use keyboard and screen reader at mobile and desktop widths to verify cast/remove controls, count updates, and the rank-change announcement.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

1. **S1:** Correct source identity handling for the production Cloudflare Tunnel proxy chain; prevent cross-user rate-limit coupling without trusting spoofable headers.
2. **W1:** Ensure idle WebSocket disconnects are observed and Redis pub/sub is closed promptly.
3. **P1:** Read current ranking from the Redis projection with bounded PostgreSQL fallback/rebuild, and make product-specific rank lookup direct rather than catalog-wide.
4. **C1:** Make velocity counter increment and expiry atomic or repair keys with missing expiry.

### Should Address (🟡 Medium)

1. Add PostgreSQL integration coverage for the cast-versus-withdraw race, checking that serialized accepted actions determine the final active state (R3/N3).
2. Add behavioral score/rank tests with equal vote counts at distinct timestamps and a zero-vote product using the real repository/ranking path (R5).
3. Add explicit tests for exact cutoff boundary behavior and for retaining already-counted votes after account suspension (R4/R10).
4. Announce rank movement/value updates to assistive technology (A1/N2).

### Nice to Have (💭 Low)

None identified.

---
*Generated by Review — 2026-10-25 01:57 +06*

## Remediation Follow-up — 2026-10-25

The implementation findings and behavior-test gaps above have been addressed in the working tree:

| Finding | Resolution | Verification |
|---------|------------|--------------|
| S1 | Production Nginx now forwards Cloudflare's `CF-Connecting-IP` into the trusted API proxy chain as `X-Forwarded-For`; the production web origin remains loopback-bound behind the tunnel. | Production deployment assertions cover the forwarding directive and the API's configured trusted proxy path. Real multi-network Cloudflare verification remains a staging check. |
| W1 | The vote socket now waits for both client receive/disconnect and Redis pub/sub activity, cancelling and gathering the unused waiter and closing the subscription on exit. | Idle disconnect cleanup regression test passed. |
| P1 | Current rankings read bounded pages from a Redis lexicographic projection, with a PostgreSQL rebuild/fallback; direct product rank is resolved from the projection without scanning all products. | Projection tests cover bounded reads, product rank, ordering ties, and zero-vote products. |
| C1 | Velocity increment and first-hit expiry now execute atomically in Redis Lua. | Route regression asserts the atomic operation; route tests passed. |
| R3 / N3 | Added a real PostgreSQL concurrent cast/withdraw race assertion for the final accepted state. | `tests/integration/test_vote_concurrency.py` passed in the focused integration run. |
| R4 | Added just-before and exact-cutoff assertions for vote cast and withdrawal behavior. | Vote service tests passed. |
| R5 | Added an aggregate/rank-path PostgreSQL check demonstrating that newer votes win between equal-count products. | Focused PostgreSQL integration run passed. |
| R10 | Added an explicit assertion that suspension does not silently remove previously counted votes while blocking subsequent actions. | Vote service tests passed. |
| A1 / N2 | Rank values now use concise polite live regions, with an assertion on the rendered attributes. | Frontend test suite passed; manual screen-reader verification remains outstanding. |

### Verification run

- Python focused suite: **34 passed**.
- Focused product-read and vote PostgreSQL integration suite: **16 passed**.
- Frontend format, lint, typecheck, and tests: **217 passed** across 33 files.
- Ruff and API mypy: passed (187 source files).
- Initial raw integration invocation: **518 passed, 14 failed, 1 skipped** because pytest was run directly against a fresh database without first invoking Compose's `prepare` service. The failures reported missing relations such as `launch_bookings`, `products`, and notification tables; this was a test setup omission, not an application schema regression.
- Supported full integration invocation: ran `prepare` and then pytest against a fresh isolated Compose project; **532 passed, 1 skipped** in 83.40 seconds. The only skip is the existing R2 validation test, which runs only in the protected validation workflow.
- Compose integration now depends on `prepare` completing successfully. Verified the direct `docker compose run integration python -m pytest -q` command on a fresh project; Compose started `prepare` automatically and the suite returned **532 passed, 1 skipped** in 77.70 seconds.

### Still requires production-like manual evidence

- Measure voter/viewer update latency and ranking freshness at the agreed staging workload.
- Verify source rate limits from multiple real client networks through Cloudflare Tunnel.
- Exercise configured Turnstile success, rejection, and outage behavior.
- Confirm idle socket resource release and rank announcements using browser/screen-reader tooling.
