# Launch Scheduling and Publication Review

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: `ARCH-add-launch-scheduling-publication` |
| **Target** | `specs/architecture/ARCH-add-launch-scheduling-publication.md` on `dev` |
| **Date** | 2026-10-18 16:22 UTC |
| **Tech Stack** | Python 3.12, FastAPI, SQLAlchemy async, Alembic, PostgreSQL, Redis, Dramatiq-style worker, React, TypeScript, Vite, TanStack Query, Docker Compose |
| **Checks Run** | Task Completion, Requirement Coverage, Code Quality, Test Coverage, Security, Database Patterns, Migration, Async Patterns, Error Handling, Performance, React Patterns, TypeScript Strictness, Accessibility, Config/Dependencies, Documentation |
| **Checks Skipped** | Express patterns (no Express); JavaScript runtime behavior (no standalone JS runtime changes) |
| **Files Changed** | 77 |
| **Lines Changed** | +12,065 / -54 |

The review compares the launch implementation from `6feee9e` through `700a90a`. The existing working-tree-only `.env.example` edit was excluded. Checks were performed as a static review; no tests were run in this review.

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered (77 files, 12,119 changed lines)
- [x] Tech stack detected: Python/FastAPI, PostgreSQL/SQLAlchemy/Alembic, React/TypeScript, Redis, Docker Compose
- [x] Context read (project instructions, REQ, ARCH, TASKS)
- [x] Triage proposed and developer confirmed
- [x] 15 checks performed: Task Completion, Requirement Coverage, Code Quality, Test Coverage, Security, Database Patterns, Migration, Async Patterns, Error Handling, Performance, React Patterns, TypeScript Strictness, Accessibility, Config/Dependencies, Documentation
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Verdict: ❌ FAIL

The implementation covers the launch feature broadly and keeps the public projection, booking records, and outbox work behind the intended boundaries. The review found a missing automated assertion for the cancellation cutoff, a worker lock-order inversion that can deadlock against cancellation or staff review, and several smaller contract and performance issues. Address the critical coverage gap and the correctness findings before treating the feature as ready to merge or enable in production.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task Completion | 0 | 0 | 1 | 0 | 2 |
| Requirement Coverage | 1 | 0 | 1 | 0 | 1 |
| Code Quality & Conventions | 0 | 0 | 1 | 0 | 0 |
| Test Coverage & Quality | 1* | 0 | 1 | 0 | 0 |
| Security | 0 | 0 | 0 | 0 | 0 |
| Database Patterns | 0 | 0 | 2 | 0 | 0 |
| Migration & Breaking Changes | 0 | 0 | 0 | 0 | 1 |
| Async Patterns | 0 | 0 | 0 | 0 | 0 |
| Error Handling & Observability | 0 | 0 | 1 | 0 | 0 |
| Performance | 0 | 0 | 1 | 0 | 1 |
| React / Next.js Patterns | 0 | 0 | 0 | 0 | 0 |
| TypeScript Strictness | 0 | 0 | 0 | 0 | 1 |
| Accessibility | 0 | 0 | 0 | 0 | 1 |
| Configuration & Dependencies | 0 | 0 | 0 | 0 | 1 |
| Documentation | 0 | 0 | 0 | 0 | 0 |
| **Unique total** | **1** | **0** | **4** | **0** | **3** |

\* Same missing-cancellation-test finding as Requirement Coverage; counted once in the unique total.

## Task Completion

**REQs:** 16/17 have at least one test or specified verification artifact; R4 is only partially asserted and R5 has no backend cancellation assertion. N5 requires manual visual/accessibility evidence.

| REQ | Status | Evidence |
|-----|--------|----------|
| R1–R3 | ✅ Static evidence | UTC/window tests, founder-capacity race test, UTC client test; UI copy still contradicts R3 (Finding #3). |
| R4 | 🟡 Partial | `test_booking_and_replacement_create_distinct_due_work_in_one_transaction` covers successful replacement and new timed events. No assertion covers failed reschedule preserving the old booking or the original-midnight cutoff (Finding #2). |
| R5 | 🔴 Missing assertion | No backend test invokes `LaunchBookingService.cancel`; cancellation before/at/after midnight and slot release are not asserted (Finding #2). |
| R6–R11 | ✅ Static evidence | Product lifecycle, public media, review invalidation, GraphQL projection, and limited-edit tests exist. Runtime was not re-executed for this review. |
| R12–R17 | ✅ Static evidence | Timed outbox, relevance, preferences, inbox deduplication, and worker notification tests exist. |
| N1–N4, N6 | ✅ Static evidence | Load, worker transaction, feature-flag, privacy, and account-scoping assertions are present. Tests were not run in this review. |
| N5 | ⚠️ Manual | UI seam tests exist; no launch-specific viewport screenshots or screen-reader/axe evidence were found. Verify 390px/1280px behavior and keyboard/screen-reader use. |

**Verification Plan:** T1–T18 are marked done. Static review confirms test files and Compose/runbook content exist. T2's cancellation and failed-reschedule scenarios are not covered; T5's route tests do not exercise successful command responses or domain-error status mappings. T15/T16 visual checklist evidence is absent. T17 production Compose validation depends on provisioned VM env files and must be confirmed in the deployment environment.

**Change Footprint Adherence:** Core feature files align with the ARCH footprint. The client eyeball guide artifacts are present in the feature comparison but outside the ARCH footprint; they originated in the earlier user-requested guide update. The active implementation tasks explicitly keep that guide outside T18's footprint.

**Areas of Impact (M/H risk):** Booking/capacity, product lifecycle/review, public reads/media, worker/outbox, notifications, and database/migration are represented by tests. The worker's lock order does not follow the documented serialization order (Finding #1). Production runtime behavior remains a manual rollout check.

**Scope:** Mostly respected; see the pre-existing guide artifact note above.

**ARCH Decisions:** PostgreSQL remains authoritative; APIs are feature-scoped; publication is idempotent; launch commands are feature-flagged; migration is forward-only. Worker lock ordering deviates from the consistent account/product/booking serialization intent.

### Requirement Coverage

**Suite run:** Not executed — static assertion audit only.

**Criteria:** 19/23 covered · 2 weak · 1 uncovered · 1 manual

| Req | Criterion (abridged) | Test evidence | Run | Status |
|-----|----------------------|---------------|-----|--------|
| R1 | UTC calendar and cutoff shown consistently | `test_booking_accepts_tomorrow_and_day_90_as_utc_dates`; client date serialization test | 🛑 static only | ✅ Covered |
| R2 | Own approved product; D+1..D+90; account eligibility | service boundary and account tests; route body tests | 🛑 static only | ✅ Covered |
| R3 | Two per founder/day, concurrent cap, no global cap | `test_concurrent_founder_requests_cannot_take_the_last_daily_slot` asserts a founder reaches two under a race | 🛑 static only | 🟡 Weak — no explicit second-founder same-day assertion; UI says one per founder |
| R4 | Reschedule before original midnight; failed move retains old booking | event integration asserts successful replacement and new events | 🛑 static only | 🟡 Weak — no failed-move preservation or boundary assertion |
| R5 | Cancel before midnight; at/after cutoff rejected and slot released | No backend cancellation test found | — | 🔴 Uncovered — Finding #2 |
| R6 | Private before publication, public after, one-time launch | lifecycle, public media, GraphQL, worker atomicity tests | 🛑 static only | ✅ Covered |
| R7 | Same-day recovery; missed-day returns approved with reason | lifecycle and publication worker tests | 🛑 static only | ✅ Covered |
| R8 | Suspension blocks publication and requires rebooking | lifecycle and worker outcome tests | 🛑 static only | ✅ Covered |
| R9 | Staff return closes booking and preserves audit | `test_scheduled_return_closes_booking_and_review_replay_is_idempotent` | 🛑 static only | ✅ Covered |
| R10 | Public page includes approved fields only | public GraphQL projection and UI tests | 🛑 static only | ✅ Covered |
| R11 | Prelaunch lock; restricted postlaunch edits | product launch lifecycle test | 🛑 static only | ✅ Covered |
| R12 | 24-hour/immediate reminder and new reminder per booking | booking event due-time integration test | 🛑 static only | ✅ Covered |
| R13 | Suppress stale reminders and reminders at cutoff | worker relevance test checks replaced booking and after-launch time | 🛑 static only | ✅ Covered |
| R14 | Live notice only after successful publication; retry safe | worker outcome and notification dedupe tests | 🛑 static only | ✅ Covered |
| R15 | Persistent missed/suspended reason and notices | worker outcome, GraphQL owner-read, and UI state tests | 🛑 static only | ✅ Covered |
| R16 | Six independent default-on preferences and current-choice check | preferences service/repository and UI tests | 🛑 static only | ✅ Covered |
| R17 | Durable bell, live unread invalidation, individual read | notification service/live and hook tests | 🛑 static only | ✅ Covered |
| N1 | 1,000 publications within 60 seconds, none early | `test_one_thousand_due_launches_publish_within_sixty_seconds` asserts cutoff and elapsed time | 🛑 static only | ✅ Covered |
| N2 | Coherent outcomes under concurrent/repeated/interrupted work | capacity race, idempotent booking/notice, atomic worker tests | 🛑 static only | ✅ Covered, except R4/R5 cases above |
| N3 | Unpublished details/media private; public projection excludes private data | launch public media and GraphQL projection tests | 🛑 static only | ✅ Covered |
| N4 | Delivery outage preserves actions and retries relevant notices | notification/outbox replay and relevance tests | 🛑 static only | ✅ Covered |
| N5 | Brutalist UI, responsive and accessible | component tests; no launch visual evidence | — | ⚠️ Manual — viewport and assistive-tech verification |
| N6 | Owner-only operations and recipient-private notices | owner resolver, account checks, and notification tests | 🛑 static only | ✅ Covered |

**Edge cases:** E1 invalid dates (covered); E2 timezone differences (UTC logic/client test, visual timezone behavior manual); E3 concurrent founder capacity (covered); E4 failed full-date reschedule retaining old slot (uncovered with R4); E5 idempotent replay (booking replay tested, cancel replay not tested); E6 midnight boundary for cancel/reschedule (uncovered with R5); E7 same-day recovery (covered); E8 next-day missed handling (covered); E9 suspension (covered); E10 staff return (covered); E11 reschedule after prior reminder (new event identity covered, old reminder suppression only indirectly); E12 email recovery/outage (outbox/relevance assertions, no live provider outage test); E13 changed preference before pending delivery (worker preference assertion); E14 both failure channels off (notification test); E15 interrupted processing (atomicity/retry tests); E16 1,000-item cutoff (integration test); E17 guessed private page/media (public projection/media tests). Runtime and third-party behavior remain unverified in this review.

### Findings

| # | Severity | File | Line | Issue | Recommendation |
|---|----------|------|------|-------|----------------|
| 1 | 🟡 Medium | `apps/worker/worker.py` | 198 | The worker locks the booking before acquiring founder/product locks. Booking commands lock founder → product → booking, and staff review locks product → booking. Concurrent publication/reminder processing can therefore hold the booking while waiting for product as another transaction holds product while waiting for booking, triggering a PostgreSQL deadlock and aborting one operation. | Read the booking without a lock to identify its founder, then acquire locks in the shared order and revalidate booking state before mutation. Add a PostgreSQL concurrency regression test against cancellation/review. |
| 2 | 🔴 Critical | `apps/api/app/modules/launches/service.py` | 353 | No automated backend assertion exercises `cancel`; therefore the agreed cutoff rule (reject at or after 00:00 UTC even while publication is delayed), state transition to approved, and capacity release can regress without a failing test. The T2 test plan also lacks its required failed-reschedule-preserves-old-booking assertion. | Add PostgreSQL-backed service tests for cancel immediately before and exactly at/after cutoff, asserting booking/product state and capacity; add a failed full/invalid reschedule assertion that the old booking remains active. |
| 3 | 🟡 Medium | `apps/web/src/launches/LaunchScreens.tsx` | 402 | The founder dashboard says “ONE PER FOUNDER,” while the confirmed rule and backend allow two products per founder per UTC day. This misstates available capacity and contradicts R3. | Change the visible rule to two products per founder per day and assert the accurate copy in the dashboard test. |
| 4 | 🟡 Medium | `apps/api/app/modules/launches/repository.py` | 37 | The owner history query filters by `founder_id` and sorts all retained booking states by `(created_at, id)`, but the migration only adds a partial active-booking `(founder_id, launch_date)` index. That index cannot serve the historical keyset query, which will scan/sort an increasing history table on dashboard reads. | Add a full index on `(founder_id, created_at DESC, id DESC)` in the migration/model and verify the query plan at production-like history volume. |
| 5 | 🟡 Medium | `apps/api/app/modules/launches/routes.py` | 97 | Every `LaunchConflictError` maps to 409, including dates outside the eligible D+1..D+90 window. T5 explicitly expects out-of-window dates to return 422, while 409 is for state/capacity conflicts; the frontend then presents an invalid date as a stale/full slot. | Distinguish validation/window errors from booking conflicts and map them to 422; add route assertions for both cases. |

### Review Comments

1. **Finding #1:** I noticed the worker takes a booking row lock before the product service acquires the founder and product locks. The booking and review flows use the reverse order, so overlapping work can deadlock at the database. Could we align the worker's acquisition order and add a concurrency regression test?
2. **Finding #2:** I could not find a backend test for `LaunchBookingService.cancel`, even though the midnight cutoff is a hard product invariant. Could we assert the before/at-cutoff cases and old-booking preservation on a failed reschedule?
3. **Finding #3:** The dashboard states one booking per founder/day, but the approved limit is two. Could we update the copy and pin it with a UI assertion?
4. **Finding #4:** The new owner-history query includes closed history but its available founder/date index is partial to active rows. As history grows, this can make every dashboard page scan more rows than necessary. Could we add the matching keyset index and check its query plan?
5. **Finding #5:** An out-of-window date is returned as 409 and described by the UI as a slot conflict. T5 calls for 422 for this validation case. Could we separate invalid date errors from current-state conflicts?

### Coverage Checklist

- [x] T1 migration/model — additive columns/tables/constraints/indexes inspected; forward-only downgrade matches ARCH.
- [x] T2 booking rules — UTC and founder-row serialization inspected; R4/R5 test gaps recorded as Finding #2.
- [x] T3–T4 lifecycle/review integration — versioned transitions and return-for-changes tests inspected; lock interaction recorded as Finding #1.
- [x] T5 REST — origin, CSRF, cookie, schema validation inspected; validation status mismatch recorded as Finding #5.
- [x] T6–T8 notification preferences/outbox — channel preferences, stable IDs, current relevance and recipient checks inspected.
- [x] T9 worker — concurrency bounded and transactions isolated; lock order recorded as Finding #1.
- [x] T10–T13 reads, flag, and generated contracts — allowlist, launch-disabled composition and generated artifacts inspected.
- [x] T14–T16 frontend — UTC helpers, public/private route separation, interaction seams and semantics inspected; R3 copy mismatch recorded as Finding #3.
- [x] T17–T18 runtime/docs — Compose defaults and operations/recovery docs inspected; live production env/rollout remains manual.

### Other Checks

#### Code Quality & Conventions
**Result:** ⚠️ Finding #3 is tracked under Task Completion to avoid duplication. Module boundaries otherwise follow the named service ports; no repository cross-import was found.

#### Test Coverage & Quality
**Result:** ⚠️ Finding #2 is the critical uncovered cancellation behavior. Existing worker, privacy, event, GraphQL, and frontend seam tests assert meaningful outcomes. No tests were run during this review.

#### Security
**Result:** ✅ No findings.
**Files reviewed:** launch routes, GraphQL composition/resolvers, public media route/service, auth access, config, and upload/media boundaries.

#### Database Patterns
**Result:** ⚠️ Finding #1 covers the lock-order deadlock; Finding #4 covers the missing historical owner-query index. Multi-table changes are transaction-scoped and user values are parameterized.

#### Migration & Breaking Changes
**Result:** ✅ No code findings. Migration 0012 is additive, review notification uniqueness is recreated as a partial unique index, and the downgrade intentionally refuses data loss. **Manual:** apply and validate the migration against the provisioned production database before enabling launch writes.

#### Async Patterns
**Result:** ✅ No findings in the changed TypeScript async flows; mutation handlers await their requests and report failures.

#### Error Handling & Observability
**Result:** ⚠️ Finding #5: invalid date/window requests receive a conflict response instead of the planned validation response. Worker error handling retains retry/dead-letter behavior and avoids event payload details in logs.

#### Performance
**Result:** ⚠️ Finding #4. The 1,000-publication integration test exists and asserts the 60-second target, but its result was not rechecked in this review. **Manual:** verify query plans and throughput on the production-like PostgreSQL/worker sizing.

#### React / Next.js Patterns
**Result:** ✅ No findings.
**Files reviewed:** launch screens and query hooks.

#### TypeScript Strictness
**Result:** ✅ No high-risk `any` escape or unsafe assertion identified in the reviewed launch clients/components. **Manual:** compiler output was not rerun in this review.

#### Accessibility
**Result:** ✅ No static blocker identified in labels, semantic controls, or image alternatives. **Manual:** verify keyboard flow and screen-reader announcements; no launch-specific viewport/screen-reader artifact was found.

#### Configuration & Dependencies
**Result:** ✅ No new dependency or committed secret finding. Development/check launch enablement is explicit; production defaults launch writes off and sets bounded worker concurrency. **Manual:** validate the production-rendered Compose config with the real provisioned env files.

#### Documentation
**Result:** ✅ No findings. The runbook documents UTC rules, rollout, monitoring, and recovery; referenced migration and settings are present.

## Manual Checks Required

- [ ] Exercise founder and public launch pages at approximately 390px and 1280px; confirm no horizontal overflow and verify keyboard/screen-reader behavior.
- [ ] Render production Compose config using the VM's provisioned env files, apply migration 0012, and confirm the launch flag remains off until API/worker compatibility is established.
- [ ] Confirm the 1,000-launch cutoff target and owner-history query plan using production-like database and worker capacity.
- [ ] Reproduce concurrent worker publication/reminder processing with cancellation and staff return-for-changes after correcting lock order.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

- Add backend assertions for cancellation timing/state/capacity and failed-reschedule preservation (Finding #2).

### Should Address (🟡 Medium)

- Align worker lock ordering with booking/review transactions (Finding #1).
- Correct the daily-capacity label (Finding #3).
- Add an index for founder booking history keyset reads (Finding #4).
- Map date-window validation errors to 422 as the task spec requires (Finding #5).

### Nice to Have (💭 Low)

- None.

---
*Generated by Review — 2026-10-18 16:22 UTC*
