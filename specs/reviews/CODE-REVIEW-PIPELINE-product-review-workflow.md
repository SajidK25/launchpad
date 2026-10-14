# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: ARCH-product-review-workflow |
| **Target** | `specs/architecture/ARCH-product-review-workflow.md` and committed implementation `88d7204^..HEAD` |
| **Date** | 2026-10-05 17:33 UTC |
| **Tech Stack** | Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, pytest; React, TypeScript strict, Vite, Vitest; PostgreSQL, Redis, Dramatiq; Docker, Nginx; OpenAPI/GraphQL generated contracts |
| **Checks Run** | Task Completion, Requirement Coverage, Code Quality, Test Coverage, Performance, Security, Error Handling, Configuration & Dependencies, TypeScript Strictness, Runtime Behavior, Async Patterns, React Patterns, Database Patterns, Migration & Breaking Changes, Accessibility |
| **Checks Skipped** | Documentation (no documentation files in the committed implementation diff); Express Patterns (not an Express application) |
| **Files Changed** | 78 |
| **Lines Changed** | +9,852 / -165 |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered (78 files, 10,017 changed lines)
- [x] Tech stack detected: Python/FastAPI/PostgreSQL/Redis and React/TypeScript/Vite, plus Docker/Nginx and generated contracts
- [x] Context read (AGENTS.md, CLAUDE.md, REQ, ARCH, TASKS)
- [x] Triage proposed and developer confirmed
- [x] 15 checks dispatched: Task Completion, Requirement Coverage, Code Quality, Test Coverage, Performance, Security, Error Handling, Configuration & Dependencies, TypeScript Strictness, Runtime Behavior, Async Patterns, React Patterns, Database Patterns, Migration & Breaking Changes, Accessibility
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to specs/reviews/

## Verdict: ❌ FAIL

The implementation follows the main architecture for review transactions, owner-scoped notifications, private approval, and production email delivery. Two acceptance criteria remain weakly asserted: privacy across all review outcomes and exactly-once delivery recovery. Add targeted regression assertions before merging; several medium operational, UI accessibility, and maintainability issues should also be addressed.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task Completion | 0 | 0 | 0 | 1 | 1 |
| Requirement Coverage | 0 | 2 | 0 | 0 | 0 |
| Code Quality & Conventions | 0 | 0 | 1 | 0 | 0 |
| Test Coverage & Quality | 0 | 0 | 1 | 0 | 0 |
| Performance | 0 | 0 | 1 | 0 | 0 |
| Security | 0 | 0 | 1 | 0 | 0 |
| Error Handling & Observability | 0 | 0 | 0 | 0 | 0 |
| Configuration & Dependencies | 0 | 0 | 1 | 0 | 0 |
| TypeScript Strictness | 0 | 0 | 1 | 0 | 0 |
| Runtime Behavior | 0 | 0 | 0 | 0 | 0 |
| Async Patterns | 0 | 0 | 0 | 0 | 0 |
| React / Next.js Patterns | 0 | 0 | 0 | 0 | 0 |
| Database Patterns | 0 | 0 | 1 | 1 | 0 |
| Migration & Breaking Changes | 0 | 0 | 0 | 0 | 0 |
| Accessibility | 0 | 0 | 2 | 0 | 0 |
| **Total** | **0** | **2** | **9** | **2** | **1** |

### Task Completion

**REQs:** 10/13 fully verified; 2 weak; 1 manual evidence gap. Requirement Coverage details the two weak criteria. Test evidence here is static; the reviewers did not run tests.

| REQ | Status | Evidence |
|-----|--------|----------|
| R1 | ✅ Verified | `test_review_service.py`, `test_review_routes.py`, `test_product_review_api.py` cover decisions, authorization, and retries. |
| R2 | ✅ Verified | `test_product_review_transitions.py` covers approved return; review-read integration and screen tests cover founder outcomes. |
| R3 | ✅ Verified | Review service/API and screen tests cover required feedback and correction editing. Corrected resubmission queue ordering is separately untested (Test Coverage finding). |
| R4 | ✅ Verified | Review transition/API and screen tests cover rejection and locked founder state. |
| R5 | ✅ Verified | Transition integration tests cover stale and competing decisions; hook tests cover stale refresh. |
| R6 | ✅ Verified | Notification/outbox and Resend adapter tests cover persisted notifications and provider behavior. |
| R7 | ✅ Verified | Migration/model/service tests cover decision history and constraints. |
| R8 | ✅ Verified | Transition tests cover reviewed-product deletion after later withdrawal. |
| R9 | ✅ Verified | Notification read/live integration and client/hook/bell tests cover persistence and live reconciliation. |
| N1 | 🟠 Weak | `test_review_dispatch.py` covers retry scheduling after delivery failure, but does not assert eventual retry delivers exactly once; provider-key expiry/replay behavior is not covered. |
| N2 | ⚠️ Manual evidence incomplete | T13/T15 UI tasks lack committed viewport inspection evidence for the product screens and bell zero/one/many states. |
| N3 | 🟠 Weak | `test_product_review_reads.py` checks some non-owner/visitor GraphQL reads, but does not assert that every review outcome remains hidden across public API/search and direct media surfaces. Existing media tests cover generic private products, not the new outcome states. |
| N4 | ✅ Verified | `test_notification_live.py` and `test_live.py` cover account-scoped hints and persisted reads after disconnect. |

**Verification Plan:** T1–T15 have the specified test files and most test assertions. The static checks found these gaps:

| Task | Status | Evidence |
|------|--------|----------|
| T1–T9 | ✅ Tests exist | Schema, service, REST/GraphQL, notification, outbox, and Resend tests are present. |
| T10 | ⚠️ Partial | Settings and Compose changes exist, but `.env.example` is absent from the committed diff even though T10 lists it and its configuration checklist requires it. See Configuration & Dependencies. |
| T11–T12 | ✅ Artifacts/tests exist | Generated REST/GraphQL contracts and typed client/hook tests are present. |
| T13 | ⚠️ Manual evidence incomplete | Component tests cover review seams; no committed 390px/1280px viewport observations were found. |
| T14 | ✅ Tests exist | Notification client/hook tests cover reads, invalidation, reconnect, and session changes. |
| T15 | ⚠️ Manual evidence incomplete | Bell tests cover empty, updated count, read behavior, navigation, and Escape; committed viewport evidence does not cover zero/one/many states. |

**Change Footprint Adherence:** The expected implementation files are present. The only Must-NOT overlap is `apps/api/app/modules/products/tests/test_graphql.py`, which was changed with the developer’s prior explicit approval. T15 also adds a persisted `product_id` link, migration, and API/contract changes following the developer’s selected owner-only destination; the task/architecture footprint does not yet document that extension. 💭 Update the architecture/task footprint for traceability.

**Areas of Impact (M/H risk):** Product lifecycle, privacy, notification delivery, WebSocket scoping, and rollout have regression tests. The gaps for privacy and retry recovery are listed under Requirement Coverage. T13/T15 UI inspection evidence remains incomplete.

### Coverage Checklist

- [x] REQ IDs traced through ARCH/TASKS to implementation and test assertions; N1/N3 weak and N2 manual as detailed above.
- [x] T1–T15 verification modes and expected artifacts checked; UI evidence gap recorded for T13/T15.
- [x] Must-NOT paths checked; the GraphQL assertion update had prior explicit user approval.
- [x] High-risk privacy, transactional delivery, audit retention, and live account scoping checked against tests.

**Scope:** ⚠️ The user-selected notification destination is implemented, but its persisted-link footprint is not reflected in ARCH/TASKS. No unrelated committed files were identified.

**ARCH Decisions:** ✅ The implementation follows the documented transactional outbox, private approval, immutable audit, Resend, and account-scoped live-update decisions. The selected stored product link extends the documented data relationship.

### Requirement Coverage

**Suite run:** Not executed — assertions audited statically only.

**Criteria:** 10/13 covered · 2 weak · 0 uncovered · 1 manual. N2 is listed under Task Completion to avoid counting the same UI evidence gap twice.

| Req | Criterion (abridged) | Test evidence | Run | Status |
|-----|----------------------|---------------|-----|--------|
| R1 | Authorized, idempotent decision | `test_product_review_api.py`, `test_review_service.py` | 🛑 Static only | ✅ Covered |
| R2 | Approval remains private and locks founder edits | transition/read tests, `ProductReviewScreens.test.tsx` | 🛑 Static only | ✅ Covered |
| R3 | Required feedback, private correction and resubmission | service/API tests; resubmission ordering/correction assertion missing | 🛑 Static only | ✅ Covered; see Test Coverage |
| R4 | Rejection final and private | transition/API tests | 🛑 Static only | ✅ Covered |
| R5 | Stale/concurrent decisions refused | `test_product_review_transitions.py` | 🛑 Static only | ✅ Covered |
| R6 | Durable in-site and email outcomes | notification/outbox and Resend tests | 🛑 Static only | ✅ Covered |
| R7 | Immutable staff decision history | migration/model/service tests | 🛑 Static only | ✅ Covered |
| R8 | Owner-only actions and reviewed-product retention | transition/service tests | 🛑 Static only | ✅ Covered |
| R9 | Persistent, individually read, live-updated inbox | notification integration and frontend tests | 🛑 Static only | ✅ Covered |
| N1 | Delivery retries safely without duplicates | retry scheduling asserted; eventual one-time delivery after retry not asserted | 🛑 Static only | 🟠 Weak |
| N2 | Accessible responsive review/bell surfaces | UI checklist evidence absent/incomplete; see Task Completion | — | ⚠️ Manual |
| N3 | All review outcomes remain private on every read/media surface | partial GraphQL visibility coverage; no state-by-state direct media/public-surface assertions | 🛑 Static only | 🟠 Weak |
| N4 | Account-private live hints and persisted offline history | notification live/read integration tests | 🛑 Static only | ✅ Covered |

**Review Comments**

1. **N1 — retry recovery:** I noticed the dispatcher tests verify that failed sends are rescheduled, but not that a later successful retry completes exactly once. Could you add a failure-then-success assertion that checks both provider calls and durable event state? Thoughts?
2. **N3 — privacy coverage:** The product must remain private after each possible review result, including direct media access. Could you extend integration assertions across approved, rejected, and changes-requested states for visitor/other-member API and media attempts? This would make the confidentiality requirement fail visibly if a future read path regresses. What do you think?

### Code Quality & Conventions

| # | Severity | File | Line | Issue | Recommendation |
|---|----------|------|------|-------|----------------|
| 1 | 🟡 Medium | `apps/web/src/products/ProductScreens.tsx` | 314 | The review queue, approved list, review detail, and decision panel expand an already large screen module from about 1,745 to 2,100 lines despite being a distinct workflow. | Move staff review screens and helpers into a dedicated module, leaving route selection in `ProductScreens.tsx`. |

**Review Comment:** Would it make sense to move the staff review components into a dedicated module? This keeps founder product editing and staff review easier to navigate independently. Thoughts?

### Coverage Checklist

- [x] Changed API, worker, and web code reviewed for module boundaries, complexity, types, and project conventions.
- [x] Changed tests, contracts, and quality tooling reviewed for placement and consistency.

### Test Coverage & Quality

| # | Severity | File | Line | Issue | Recommendation |
|---|----------|------|------|-------|----------------|
| 1 | 🟡 Medium | `apps/api/app/modules/products/service.py` | 964 | `submit_draft` accepts `changes_requested` and creates a new period, but no committed test covers resubmitting corrected content after a change request. The existing integration scenario requests changes and resubmits without exercising a correction or queue ordering. | Add a PostgreSQL integration test that requests changes, saves a correction, resubmits while other products are pending, and asserts a new period queues last while the previous period/decision remains intact. Include the pending-cap case required by T3. |

**Review Comment:** I noticed the existing reviewed-product retention scenario calls resubmit without testing the founder correction and queue position. Could you add the correction/resubmit case with an earlier waiting submission and assert the new period is last? Thoughts?

### Coverage Checklist

- [x] Review service, repository, routes, and UI behaviors traced to changed tests.
- [x] Transaction, stale-action, retry, and boundary assertions reviewed; corrected resubmission is the identified gap.

### Performance

| # | Severity | File | Line | Issue | Impact | Recommendation |
|---|----------|------|------|-------|--------|----------------|
| 1 | 🟡 Medium | `apps/api/app/shared/events/dispatcher.py` | 92–120 | The worker holds its transaction and `FOR UPDATE SKIP LOCKED` batch while it sends each email sequentially. | A 20-message batch with 10-second Resend timeouts can hold row locks for up to about 200 seconds, delaying later batches. | Claim work separately from provider I/O, then record each result in a short transaction while preserving retries and idempotency. |

**Review Comment:** Would it make sense to release claimed-row locks before provider calls and persist each delivery result in a shorter transaction? A slow batch currently holds locks across sequential network waits. Thoughts?

### Coverage Checklist

- [x] Outbox batch bound and worker transaction lifetime traced through `worker.py` and `dispatch_due`.
- [x] Notification reads and product review query bounds checked; no other performance issue found.

### Security

| # | Severity | File | Line | Issue | Risk | Recommendation |
|---|----------|------|------|-------|------|----------------|
| 1 | 🟡 Medium | `apps/api/app/modules/notifications/live.py` | 67–95 | The authenticated notification WebSocket has no per-account connection cap or handshake rate limit. | One signed-in account can open many sockets, each retaining a Redis subscription and periodic session revalidation work, consuming API/Redis capacity. | Add a per-account connection cap or handshake limit and release the account slot on disconnect. |

**Review Comment:** I noticed valid sessions can open an uncapped number of notification sockets. Could you bound active sockets per account and clean up that count on disconnect? Thoughts?

### Coverage Checklist

- [x] Notification and product routes/services checked for authentication, ownership, CSRF/origin validation, and input bounds.
- [x] WebSocket handshake/session checks and provider/config secret handling checked; connection abuse is Finding #1.

### Error Handling & Observability

**Result:** ✅ No findings.
**Files reviewed:** notification REST/GraphQL/live paths, product review routes/services, outbox/Resend/worker paths, notification and product clients.

### Configuration & Dependencies

| # | Severity | File | Line | Issue | Recommendation |
|---|----------|------|------|-------|----------------|
| 1 | 🟡 Medium | `apps/api/app/shared/config/settings.py` | 52 | Production worker startup now requires `LAUNCHPAD_RESEND_API_KEY`, but the committed implementation does not update `.env.example` or deployment documentation even though T10 lists the example file and checklist. | Commit the placeholder setting and provisioning guidance; keep the secret scoped to the worker environment. |

**Review Comment:** Could you document the new worker-only Resend key in the committed environment example and deployment instructions? That gives deployers a clear provisioning step without injecting the secret into the API process. Thoughts?

### Coverage Checklist

- [x] Settings, Compose service environments, Nginx WebSocket proxy, dependency manifests, and worker provider selection checked.
- [x] Resend key remains worker-only; committed environment example/documentation is missing.

### TypeScript Strictness

| # | Severity | File | Line | Issue | Recommendation |
|---|----------|------|------|-------|----------------|
| 1 | 🟡 Medium | `apps/web/src/notifications/client.ts` | 86 | `markRead` casts parsed `unknown` JSON to `NotificationRead` after checking only that it is an object, allowing malformed fields through the REST boundary. | Validate required fields such as `product_id`, `kind`, and `read_at` before returning, following `assertProductState`. |

**Review Comment:** I noticed `markRead` trusts any object response as `NotificationRead`. Could you validate the required fields so a malformed API response cannot enter typed client state? Thoughts?

### Coverage Checklist

- [x] Changed notification/product clients, hooks, bell, app shell, and generated contract types checked for unsafe assertions and nullability.
- [x] Only the unchecked mark-read response assertion was identified.

### Runtime Behavior

**Result:** ✅ No findings.
**Files reviewed:** changed app shell, notification components/client/hooks, product screens/clients, generated contracts.

### Async Patterns

**Result:** ✅ No findings.
**Files reviewed:** notification API/live/service paths, event dispatcher/worker, notification and product async clients/hooks.

### React / Next.js Patterns

**Result:** ✅ No findings.
**Files reviewed:** changed React app shell, notification bell/hooks/client, product screens and hooks.

### Database Patterns

| # | Severity | File | Line | Issue | Impact | Recommendation |
|---|----------|------|------|-------|--------|----------------|
| 1 | 🟡 Medium | `apps/api/app/modules/products/repository.py` | 536–557 | `list_approved_reviews` filters approved submissions and pages by `closed_at, id`, but no index supports that state/order pattern. | As history grows, a request for at most 51 results can scan and sort historical submission rows. | Add a partial index for approved submissions ordered by `closed_at` and the query tie-breaker, then confirm with a production-like query plan. |
| 2 | 💭 Low | `apps/api/alembic/versions/0009_notification_product_link.py` | 27–34 | The new `notifications.product_id` foreign key has no index. Current inbox queries do not filter on this field. | Product restrict/delete checks may scan notifications as inbox history grows. | Add an index if product-level FK checks or future reads need this path to remain efficient. |

**Review Comment:** The approved-review cursor query has no matching partial index. Could you add one for approved submission state and the paging order, then verify its plan with realistic history volume? Thoughts?

### Coverage Checklist

- [x] Review and notification repositories, write services, ORM mappings, and migrations checked for transaction scope, query bounds, and indexing.
- [x] Approved-review paging index gap and notification product FK index opportunity recorded.

### Tracing Notes

- `ProductRepository.list_approved_reviews` is called by the staff-approved review page; this is an occasional bounded read, but its `closed_at, id` ordering lacks a matching index.
- `NotificationService.inbox` serves frequent bounded reads; recipient and unread indexes support its query paths.
- `ProductService.decide_review` performs the state, decision, notification, and outbox writes in the caller transaction.

### Migration & Breaking Changes

**Result:** ✅ No findings.
**Files reviewed:** migrations 0008/0009, API schemas/routes/GraphQL, outbox event types, settings, Compose, generated contracts.

### Accessibility

| # | Severity | File | Line | Issue | WCAG | Recommendation |
|---|----------|------|------|-------|------|----------------|
| 1 | 🟡 Medium | `apps/web/src/notifications/NotificationBell.tsx` | 69–79 | The changing unread count is hidden from assistive technology; changing the button name alone does not announce an off-focus update. | WCAG 2.1 SC 4.1.3 Status Messages | Expose a polite live status for unread-count changes, avoiding duplicate announcements when opening/focusing the bell. |
| 2 | 🟡 Medium | `apps/web/src/notifications/NotificationBell.tsx` | 54–58 | Selecting a notice removes the focused button and navigates to the product route without moving focus to destination content. | WCAG 2.1 SC 2.4.3 Focus Order | Move focus to the destination heading or main landmark after internal navigation. |

**Review Comments**

1. Screen reader users may not hear that new review notifications arrived because the count is hidden and the trigger name changes without focus. Could a polite status announce the updated unread count? Thoughts?
2. Would it make sense to move focus to the product heading after this in-app navigation? The selected inbox button disappears, which can leave keyboard and screen-reader users at the document body. Thoughts?

Other reviewed controls use semantic buttons and labels; keyboard dismissal/focus return and visible focus styling are present.

### Coverage Checklist

- [x] Notification bell trigger/list semantics, labels, keyboard controls, and dynamic count announcement checked.
- [x] Product review forms, route focus behavior, colors, and focus indicators checked.

## Manual Checks Required

- [ ] Complete T13 product review screen inspection at 390px and 1280px and record the observations.
- [ ] Inspect T15 bell at 390px and 1280px with zero, one, and many notifications; verify no overflow and record the observations.
- [ ] Verify the notification bell and route transition with a screen reader after addressing the accessibility findings.
- [ ] Confirm the approved-review index plan with production-like data (`EXPLAIN ANALYZE`).

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

- Add assertions for privacy across approved, rejected, and changes-requested outcomes on public product/API and direct media surfaces (N3).
- Add a failure-then-success outbox test asserting eventual exactly-once email delivery and persisted completion (N1).

### Should Address (🟡 Medium)

- Cover corrected resubmission and queue ordering after a change request.
- Avoid holding outbox row locks during sequential provider network calls.
- Cap authenticated notification WebSocket connections per account.
- Add an approved-review paging index.
- Document the worker-only Resend key in the committed environment example/deployment instructions.
- Validate the `markRead` REST response before treating it as `NotificationRead`.
- Announce unread-count changes to assistive technology and move focus to the destination after navigation.
- Split staff review screens from the large `ProductScreens.tsx` module.

### Nice to Have (💭 Low)

- Consider an index on `notifications.product_id` for product-level FK checks as notification history grows.
- Record the selected owner-only notification product link in the ARCH/TASKS change footprint.

---
*Generated by Review — 2026-10-05 17:33 UTC*

## Remediation follow-up — 2026-10-06

Implementation follow-up is recorded in the working tree; the original verdict above remains the
review's historical result. The reported code and coverage findings now have corresponding fixes or
regression coverage: retry identity and durable completion, outcome-state privacy and media reads,
corrected resubmission ordering/cap, short outbox claim transactions, account connection leases,
approved-review and notification indexes, response validation, accessible count announcements and
navigation focus, staff-screen extraction, Resend provisioning guidance, and notification-link
architecture/task traceability.

UI evidence is saved under `specs/qa/artifacts/product-review-workflow/`. T13 captures staff and
founder screens at both target widths. T15 captures one unread notice at both widths; zero/many
viewport captures and hands-on screen-reader inspection remain outstanding. The index plan is
covered by schema assertions, but realistic-volume `EXPLAIN ANALYZE` evidence remains outstanding.
Automated test suites were not run during this follow-up.
