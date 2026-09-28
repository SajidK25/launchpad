# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: T12 task review |
| **Target** | `specs/tasks/TASKS-add-member-identity-profiles.md` — Task T12 |
| **Date** | 2026-09-24 |
| **Tech Stack** | Python 3.12, FastAPI, Strawberry GraphQL, async SQLAlchemy/PostgreSQL, Redis, S3-compatible storage, pytest |
| **Checks Run** | Task completion, requirement coverage, security/authz/private reads, GraphQL limits, code quality, error handling, async/race, database patterns, test coverage, config/composition |
| **Checks Skipped** | Frontend/React/TypeScript/accessibility, migrations, performance, documentation (outside T12 scope) |
| **Files Changed** | 11 T12-scoped implementation/test/config/task artifacts (workspace also contains prior T1–T11 changes) |
| **Lines Changed** | Approximately +631 / -16 in the current tracked workspace diff; T12 includes new untracked transport/test files |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered and T12 footprint scoped
- [x] Tech stack detected: Python/FastAPI/Strawberry/async SQLAlchemy/PostgreSQL/pytest/S3
- [x] Context read (AGENTS.md, CLAUDE.md, REQ, ARCH, TASKS, and review instructions)
- [x] Triage proposed and developer confirmed
- [x] 3 checks dispatched: completion/requirements; security/authz/config; quality/error handling/races/database/tests
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Verdict: Changes requested — not merge-ready

The T12 transport shape is appropriately thin, uses the profile service for visibility decisions, returns private/unknown public profiles as `null`/404, and keeps photo responses uncached. The slice is not completion-ready: the required end-to-end REST, GraphQL, photo-gating, and immediate-withdrawal scenarios are not exercised, the GraphQL guard is not a real depth/allowlist control, and the check API receives storage-bootstrap credentials it does not need.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion / requirements | 0 | 1 | 1 | 0 | 0 |
| Security / authorization / config | 0 | 2 | 0 | 0 | 0 |
| Code quality / error handling / races | 0 | 0 | 3 | 0 | 0 |
| Test coverage / async / database | 0 | 0 | 0 | 0 | 0 |
| **Total** | **0** | **3** | **4** | **0** | **0** |

## Findings

### 🟠 High — T12 acceptance scenarios lack transport/integration coverage

`apps/api/app/modules/users/tests/test_routes.py:39-128` and `test_graphql.py` only cover route registration, origin rejection, one public mapping, and the absence of a mutation root. `tests/integration/test_profile_privacy.py:160-245` exercises service-level privacy/outbox behavior, not REST/GraphQL/photo reads. There are no assertions for owner draft reads/actions, private-vs-unknown photo equivalence, `no-store`, direct storage denial, old-photo URLs after withdrawal, or the required query-limit rejection. These are explicit T12 verification scenarios (R9–R11, N1, N4).

**Fix:** add end-to-end tests against the assembled API and storage boundary for owner/visitor/private/unknown profiles, publication/unpublication, photo status/body/headers, immediate withdrawal through prior URLs, and deep/unapproved GraphQL operations.

### 🟠 High — GraphQL query controls are bypassable and do not satisfy the limit contract

`apps/api/app/modules/users/routes.py:301-304` rejects only the substring `mutation` and counts opening braces in the request body. GraphQL GET requests, aliases, introspection, and syntactically different/deep documents can bypass or defeat this heuristic, causing repeated resolver/database work. It is not an operation allowlist or a real depth/complexity control, despite the T12 requirement.

**Fix:** enforce POST-only operations, parse and validate the document, apply Strawberry-supported depth/complexity limits, and use an explicit operation allowlist or persisted operation identifiers. Test GET, aliases, introspection, deep, and mutation requests.

### 🟠 High — API check container is given storage-bootstrap credentials

`compose.checks.yaml:151-155` injects `LAUNCHPAD_BOOTSTRAP_STORAGE_ACCESS_KEY_ID` and `LAUNCHPAD_BOOTSTRAP_STORAGE_SECRET_ACCESS_KEY` into the API process. Those credentials are for bucket/user provisioning and are not required by request handling; exposing them to a compromised API expands the storage blast radius and violates least privilege.

**Fix:** keep bootstrap credentials only on the provisioning/prepare process and leave the API with its scoped runtime storage identity.

### 🟡 Medium — `became_private` reports a state instead of a transition

`apps/api/app/modules/users/routes.py:156` sets `became_private` from the final visibility. Editing an already-private draft therefore reports `true` even though no public-to-private transition occurred, which can trigger a false notification in clients.

**Fix:** return the service’s actual transition (`was_public and became_private`) and add a regression test for editing an already-private draft.

### 🟡 Medium — broad exception mapping masks unexpected failures

The mutation and upload handlers (`routes.py:151-154, 173-175, 191-196, 226-227, 263-264`) catch every `Exception` and map unknown failures to HTTP 400. Programming errors and unexpected infrastructure failures are therefore misreported as client errors and lose centralized 500/error logging semantics.

**Fix:** catch only known domain/infrastructure exceptions; let unexpected exceptions reach the centralized handler with structured, secret-free logging.

### 🟡 Medium — storage promotion and database completion can orphan objects

`routes.py:246-264` promotes/deletes storage objects before the database completion transaction is durably committed. A lost race or database failure after promotion leaves a clean object without a matching completed row (and the staging object already removed).

**Fix:** make completion idempotent with a compensating cleanup/reconciliation path, or persist a durable state transition before promotion and safely retry/repair object-store operations.

### 🟡 Medium — T12 scope/evidence does not document all changed dependencies

T12 changes `apps/api/app/modules/auth/sessions.py` and `compose.checks.yaml`, although they are not listed in the task’s Files Expected/also-touches section. These changes may be necessary, but undocumented scope drift makes ownership and review incomplete.

**Fix:** document the dependency and rationale in T12 (or move the change to its owning task), then rerun the scoped review.

## Requirement Coverage

| Requirement | Status | Review conclusion |
|---|---|---|
| R9 | Partial | Service privacy rules exist, but owner/private transport reads and outsider denial are not covered. |
| R10 | Partial | Publication service gates remain present; REST publication and transport authorization are untested. |
| R11 | Partial | Withdrawal/automatic privacy exists in the service; immediate API/GraphQL/photo withdrawal is untested. |
| N1 | Partial | Private-by-default and no-store code paths exist; photo equivalence/direct-storage denial lacks end-to-end proof. |
| N4 | Partial | Read-only GraphQL schema exists; bounded/allowlisted query behavior is not implemented or tested. |

## Manual Checks Required

- [ ] Run the assembled API against PostgreSQL, Redis, and MinIO and execute the new end-to-end T12 privacy/photo/GraphQL scenarios.
- [ ] Confirm the API process no longer receives storage-bootstrap credentials after the compose change.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

- Add the missing T12 transport/integration coverage, especially immediate photo withdrawal and private/unknown equivalence.
- Replace the brace/substring GraphQL guard with real POST, depth/complexity, and allowlist controls.
- Remove bootstrap storage credentials from the API container.

### Should Address (🟡 Medium)

- Report `became_private` only for an actual transition.
- Narrow exception handling and preserve centralized 500/error observability.
- Make storage completion retryable/reconcilable and document T12 dependency scope.

### Nice to Have (💭 Low)

- None identified in this slice.

---
*Generated by Review — 2026-09-24*
