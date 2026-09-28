# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: T11 task review |
| **Target** | `specs/tasks/TASKS-add-member-identity-profiles.md` — Task T11 |
| **Date** | 2026-09-24 00:24 |
| **Tech Stack** | Python 3.12, FastAPI, async SQLAlchemy/PostgreSQL, pytest, encrypted outbox |
| **Checks Run** | Task completion, requirement coverage, security/authz, code quality, test coverage, error handling, async/race patterns, database patterns |
| **Checks Skipped** | Frontend/React/TypeScript/accessibility, Express/JavaScript runtime, performance, config/dependencies, migration, documentation (outside T11 scope) |
| **Files Changed** | 6 scoped implementation/test artifacts plus task evidence |
| **Lines Changed** | Approximately +548 / -6 in the scoped artifacts (untracked files included by line count) |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered and T11 footprint scoped
- [x] Tech stack detected: Python/FastAPI/async SQLAlchemy/PostgreSQL/pytest
- [x] Context read (AGENTS.md, CLAUDE.md, REQ, ARCH, TASKS, and review instructions)
- [x] Triage proposed and developer confirmed
- [x] 3 checks dispatched: completion/requirements; quality/tests/error handling/races; security/authz/database
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Verdict: Changes requested — not merge-ready

The users service has a sound repository boundary, optimistic conditional write, private-by-default model, and transactional outbox shape. The T11 slice still has security and correctness gaps: a profile can claim an arbitrary clean-photo key, owner operations do not resolve the authenticated member through the named access boundary, and the high-risk race/outbox-failure scenarios in the task are not actually covered by the checked-in tests. The task evidence also claims nine domain tests while the reviewed file contains six test functions (one parameterized), so the completion evidence is inconsistent.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion / requirements | 0 | 2 | 1 | 0 | 0 |
| Security / authorization | 0 | 2 | 1 | 0 | 0 |
| Code quality / error handling | 0 | 0 | 3 | 0 | 0 |
| Test coverage / async-race | 0 | 0 | 0 | 0 | 0 |
| Database patterns | 0 | 0 | 0 | 0 | 0 |
| **Total** | **0** | **4** | **5** | **0** | **0** |

## Findings

### 🟠 High — profile photo is validated by key shape only

`apps/api/app/modules/users/policies.py` accepts any key matching `profile-clean/<uuid>/<uuid>`. Neither `update_profile()` nor `publish()` verifies a `PhotoUpload` record, owner/account match, `state='cleaned'`, clean-key match, media type, or byte limit. A caller can forge a key or attach another member’s object and publish it, violating the validated-photo invariant (R10/N1).

**Fix:** introduce a named photo/storage access interface and lock/verify the upload record before saving or publishing; add wrong-owner, wrong-state, missing-record, and size/type tests.

### 🟠 High — owner operations do not enforce the named authentication boundary

`ProfileService.update_profile()` and `unpublish()` authorize from the caller-supplied `actor_id` and do not call `MemberAccess`. `get_owner()` only compares UUIDs. A future transport or internal caller that supplies an arbitrary account UUID can reach owner operations without resolving the current authenticated member/session context.

**Fix:** resolve the current member through `MemberAccess` at the service boundary and apply `require_owner` to that authenticated identity; keep verification as a separate publication policy.

### 🟠 High — required concurrency and atomicity scenarios are unproven

The T11 task explicitly requires racing edits/publications, stale-version resolution, and duplicate-notice suppression. The checked-in profile tests do not exercise concurrent writers, duplicate private transitions, or outbox insertion failure/rollback. The conditional repository update exists, but its behavior is not demonstrated at the service/integration boundary.

**Fix:** add concurrent transaction tests covering stale versions, incomplete-publication prevention, one notification, and rollback when outbox persistence fails.

### 🟠 High — SMTP outage/retry scenario is absent and evidence overstates coverage

No T11 test performs a profile edit, fails delivery, verifies durable private state and a retryable privacy event, then recovers delivery and asserts exactly one message. Existing generic outbox tests do not prove this profile transition. The task evidence says nine domain tests passed, while the reviewed domain test file contains six test functions (one parameterized).

**Fix:** add the profile-edit → failed dispatch → retry integration test and correct the task evidence to match the checked-in tests and command output.

### 🟡 Medium — publication trusts persisted values without full policy validation

`publish()` calls `require_complete()` but does not rerun `validate_profile_fields()` against persisted links and photo/name/bio values. Rows written by a migration, repair job, or another repository path can satisfy the weaker database link constraint while violating the service URL policy (for example credentials, fragments, or malformed hosts).

**Fix:** validate the complete candidate at the repository/service publication boundary, or make the persisted invariant equally strict; add out-of-band-invalid-row tests.

### 🟡 Medium — malformed URLs can leak raw `ValueError`

`urlsplit()` in `_is_public_https_url()` can raise for malformed bracketed hosts. That exception escapes instead of becoming the typed `ProfileValidationError` expected at the domain boundary.

**Fix:** catch `ValueError`, return `False`, and test malformed URL inputs.

### 🟡 Medium — optimistic version is not supplied by callers

The service locks and reads the current profile, then saves using that freshly read version. It exposes no `expected_version`, so stale editors can be silently last-write-wins rather than receiving `ProfileConflictError`/409 as intended by the architecture.

**Fix:** accept and pass an expected version for update/publish/unpublish, preserving the repository conditional update.

### 🟡 Medium — service result contains an ORM model

`ProfileResult` carries a SQLAlchemy `Profile` instance. This is safe only while transports remain absent; it conflicts with the project rule that API/GraphQL boundaries return typed schemas and can accidentally expose private fields when T12 wires the service.

**Fix:** map rows to an explicit immutable profile DTO inside the users service.

### 🟡 Medium — infrastructure failures have no typed service context

Privacy-notice codec/outbox errors correctly propagate to preserve transaction rollback, but the service does not distinguish or wrap infrastructure failures. A transport could misclassify these as validation/conflict errors and observability lacks structured, secret-free context.

**Fix:** define/map a typed outbox/infrastructure error at the transport boundary and log structured failure metadata without payload secrets.

## Requirement Coverage

| Requirement | Status | Review conclusion |
|---|---|---|
| R9 | Partial | Private owner drafts and public lookup gating exist; validated photo ownership is not enforced. |
| R10 | Partial | Verification and field completeness are gated; photo validation is format-only and publication does not revalidate persisted values. |
| R11 | Partial | Automatic privacy and manual withdrawal exist; concurrency and stale-writer behavior are unproven. |
| R12 | Partial | Encrypted outbox insertion exists; profile-specific outage/retry behavior is not tested. |
| N1 | Partial | Public/private filtering exists; arbitrary clean keys can bypass the photo invariant. |
| N2 | Partial | No new enumeration response was introduced, but profile-specific retry evidence is missing. |
| N3 | Partial | Conditional update and transaction-compatible ordering exist; service-level conflict and failure tests are missing. |

## Manual Checks Required

- [ ] Confirm the intended authenticated-member adapter for `MemberAccess` and photo-upload validation before T12 transport wiring.
- [ ] Run the new concurrent/outbox outage integration tests against PostgreSQL, Redis, MinIO, and the mail test server once added.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

- Enforce cleaned, owned, account-matching photo uploads through a named service/repository boundary.
- Resolve authenticated ownership through `MemberAccess` for every owner mutation.
- Add concurrency, rollback, duplicate-notice, and SMTP outage/retry coverage; reconcile the T11 evidence.

### Should Address (🟡 Medium)

- Revalidate persisted publication fields and harden malformed URL handling.
- Add caller-provided expected-version conflict handling.
- Return a typed profile DTO and map outbox infrastructure errors for transports/observability.

### Nice to Have (💭 Low)

- None identified in this slice.

---
*Generated by Review — 2026-09-24 00:24*
