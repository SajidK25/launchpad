# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: ARCH-add-member-identity-profiles |
| **Target** | `specs/architecture/ARCH-add-member-identity-profiles.md` + linked requirements/tasks |
| **Date** | 2026-09-25 |
| **Tech Stack** | Python 3.12, FastAPI, SQLAlchemy/Alembic, PostgreSQL, Redis, React/TypeScript/Vite, TanStack Query, pytest/Vitest/Playwright, Docker Compose |
| **Checks Run** | Task completion, requirements, code quality, security, error handling, database/migration, documentation, config/dependencies, TypeScript, React, async/runtime, accessibility |
| **Checks Skipped** | Express-specific (FastAPI stack); standalone performance (no additional high-confidence issue after database/code review) |
| **Files Changed** | 49 status entries (19 tracked diff files plus untracked feature/spec files); tracked diff +2898/-63 |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered (49 status entries; tracked diff +2898/-63)
- [x] Tech stack detected
- [x] Context read (`AGENTS.md`, `CLAUDE.md`, REQ, ARCH, TASKS)
- [x] Triage proposed and developer confirmed
- [x] 12 checks dispatched: task completion, requirement coverage, code quality, security, error handling, database patterns, migration, documentation, config/dependencies, TypeScript strictness, React/async/runtime, accessibility
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Verdict: ❌ FAIL

The implementation has strong test and quality-gate evidence, and the earlier hook-order/photo-retention issues are resolved. However, a valid password-reset email currently lands on an unrecognized frontend route, and the operator documentation contradicts both the shipped GraphQL checks and the actual local Secure-cookie setup. These high-severity contract/documentation gaps must be fixed before merge.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion / requirements | 0 | 2 | 1 | 0 | 0 |
| Security | 0 | 1 | 0 | 0 | 0 |
| Documentation | 0 | 1 | 0 | 0 | 0 |
| Error handling / observability | 0 | 0 | 1 | 0 | 0 |
| Database / migration | 0 | 0 | 1 | 0 | 0 |
| Accessibility | 0 | 0 | 1 | 0 | 0 |
| TypeScript strictness | 0 | 0 | 2 | 0 | 0 |
| **Total** | **0** | **4** | **6** | **0** | **0** |

## Findings

### 🟠 High — Recovery email links to a nonexistent web route

**Location:** `apps/api/app/modules/auth/service.py:220-225`; `apps/web/src/identity/Screens.tsx:37-43`

`PasswordResetService` emits `/reset-password?token=...`, while `screenForPath()` only recognizes `/reset`. A member clicking a valid recovery email is routed to the sign-in screen and cannot redeem the token. This violates R6/R7 and is a core recovery outage.

**Recommendation:** Emit `/reset?token=...` or add the `/reset-password` route, then add an end-to-end email-link-to-reset-screen assertion.

### 🟠 High — Local Secure-cookie documentation conflicts with the supported Compose/browser URL

**Location:** `README.md:15,38-40`; `compose.yaml:97`; `compose.checks.yaml:206`

The documented startup path is `http://localhost:8080`, while the identity guidance says local verification uses an `https://localhost` Secure-cookie flow. The check browser is configured for `http://web:8080`. A developer following the documented path cannot reproduce the stated cookie verification behavior.

**Recommendation:** Document the actual supported localhost Secure-cookie setup, or change the local/check configuration and instructions together so the cookie behavior is reproducible.

### 🟠 High — Quality guide falsely says GraphQL is not applicable

**Location:** `docs/development.md:50`; also stale `docs/adr/0004-check-isolation.md:17`

The guide says GraphQL is not applicable, but T12/T13 ship the GraphQL resolver/schema and the quality script reports GraphQL contract coverage. This misleads operators about an active API surface and its verification.

**Recommendation:** State that GraphQL schema/operation generation is covered by the contracts gate; only WebSocket is currently not applicable. Reconcile ADR 0004.

### 🟠 High — T17 evidence is prose-only for high-risk recovery drills

**Location:** `specs/tasks/TASKS-add-member-identity-profiles.md:1219-1223`; `specs/qa/`

The task records aggregate counts but retains no command transcript or QA/results artifact for the full gate and dependency/recovery drills. The checklist explicitly requires concrete results, leaving these claims difficult to audit later.

**Recommendation:** Add a durable QA results/evidence artifact containing commands, outcomes, and the isolated project used.

### 🟡 Medium — Provider failures can escape bootstrap as raw exceptions

**Location:** `apps/api/app/shared/storage/provision.py:42-51,85-87`; `apps/api/app/bootstrap.py`

Some bucket/CORS/policy operations can raise provider exceptions directly, while bootstrap only maps `StorageProvisioningError`. A dependency failure may therefore produce an unsafe traceback rather than the documented bounded preparation diagnostic.

**Recommendation:** Normalize provider/admin exceptions into `StorageProvisioningError` at the storage boundary and add drills for each preparation failure path.

### 🟡 Medium — Profile-link database constraint is weaker than the public-link policy

**Location:** `apps/api/alembic/versions/0002_member_identity_profiles.py:121-133`

The constraint accepts values matching `^https://[^/ ]+`, which can admit credentials, fragments, malformed hosts, or whitespace cases that the application policy rejects. Direct SQL or future writers can bypass the intended invariant.

**Recommendation:** Align the database constraint with the canonical URL policy where feasible, or explicitly make the service boundary the sole invariant owner and test all writers.

### 🟡 Medium — Profile errors/notices are not associated with their controls

**Location:** `apps/web/src/profiles/ProfileScreens.tsx:99-130,134-189,358-374`

Save/upload/publish errors and automatic-private notices are announced as live regions without `aria-describedby`/`aria-invalid` associations to the affected controls. Screen-reader users receive generic feedback without a correction target.

**Recommendation:** Add stable message IDs and field/action associations while keeping the privacy transition as a separate global status.

### 🟡 Medium — Auth and profile clients trust casts after only an object check

**Location:** `apps/web/src/identity/client.ts:46-50`; `apps/web/src/profiles/client.ts:49-53,66-74`

Payloads are cast to generated types without validating required fields. Malformed session, upload, or profile responses can reach strict UI code as undefined values.

**Recommendation:** Add endpoint-specific runtime decoders or a schema parser tied to generated contract types.

## Positive Review Notes

- The full isolated quality gate passed: Ruff, mypy, 132 backend/integration tests, Prettier, ESLint, strict TypeScript, 37 web tests, migrations, contracts, builds, security scans, and 2 browser tests.
- Current `App` hook ordering is stable; earlier conditional-hook concern is resolved.
- Profile edits omit `photo_upload_id` unless explicitly changed; earlier photo-retention concern is resolved.
- PostgreSQL remains authoritative for sessions, challenges, profile visibility, and outbox transitions; no additional N+1 or unbounded-query issue was identified.

## Manual Checks Required

- [ ] Confirm the supported local Secure-cookie workflow manually in a browser after the documentation/configuration decision is corrected.
- [ ] Click a real Mailpit password-reset link and complete the reset flow after the route fix.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

1. Fix the password-reset email route mismatch and add an end-to-end assertion.
2. Reconcile the GraphQL quality documentation and ADR 0004.
3. Reconcile the Secure-cookie documentation with the actual Compose/browser setup.
4. Preserve auditable T17 quality/recovery evidence in a QA/results artifact.

### Should Address (🟡 Medium)

1. Normalize storage-provider bootstrap exceptions.
2. Strengthen or document the profile-link database invariant.
3. Associate profile errors/notices with their controls.
4. Validate REST/GraphQL response payloads at the frontend boundary.

---
*Generated by Review — 2026-09-25*
