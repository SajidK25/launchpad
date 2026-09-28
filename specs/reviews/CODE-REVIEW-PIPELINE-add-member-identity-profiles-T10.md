# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: ARCH-add-member-identity-profiles (T10) |
| **Target** | `specs/tasks/TASKS-add-member-identity-profiles.md`, T10 footprint |
| **Date** | 2026-09-23 |
| **Tech Stack** | Python 3.12, FastAPI, boto3/S3, MinIO, Pillow, pytest, mypy, Ruff |
| **Checks Run** | Task completion, requirement coverage, security, code quality, test coverage, error handling, async patterns, configuration/dependencies, database/migration scope |
| **Checks Skipped** | React/TypeScript/accessibility/Express (no frontend or Express changes); performance (not in confirmed scope); documentation (not in confirmed scope) |
| **Files Changed** | 4 T10 files (3 new, 1 modified) |
| **Lines Changed** | +589 / -3 across the T10 footprint (including new files) |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered (4 T10 files, 589 additions / 3 deletions)
- [x] Tech stack detected: Python/FastAPI, boto3/S3, MinIO, Pillow, pytest
- [x] Context read (AGENTS.md, CLAUDE.md, REQ, ARCH, and TASKS)
- [x] Triage proposed and developer confirmed
- [x] 3 checks dispatched: completion/requirements; quality/tests/errors/async; security/config/database
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to specs/reviews/

## Verdict: FAIL — not merge-ready

The T10 implementation has a useful private-object adapter, bounded presigned staging, metadata-stripping re-encoding, and passing implementation evidence. It is not ready to merge because the runtime identity can enumerate the whole bucket, a Pillow security exception can escape as an unhandled server error, and the declared high-risk storage/media scenarios are not fully verified. Strict upload CORS is also not wired into the production preparation path.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion | 0 | 1 | 1 | 0 | 0 |
| Requirement coverage | 0 | 1 | 0 | 0 | 0 |
| Security | 0 | 1 | 2 | 0 | 0 |
| Code quality | 0 | 1 | 1 | 0 | 0 |
| Test coverage | 0 | 1 | 1 | 0 | 0 |
| Error handling | 0 | 1 | 2 | 0 | 0 |
| Async patterns | 0 | 0 | 1 | 0 | 0 |
| Configuration/dependencies | 0 | 0 | 0 | 0 | 0 |
| Database/migration scope | 0 | 0 | 0 | 0 | 0 |
| **Deduplicated total** | **0** | **3** | **6** | **0** | **0** |

## Findings

### F-01 — High: runtime identity can list the entire bucket

**Evidence:** `apps/api/app/shared/storage/provision.py:142-146` grants unconditional `s3:ListBucket` on the bucket. The T10 contract calls for prefix-scoped runtime permissions and explicitly identifies the storage privilege boundary as high risk.

**Impact:** A compromised runtime credential can enumerate unrelated objects, cross-account staging/final keys, and foundation objects. This weakens opaque-photo confidentiality and violates the intended private storage boundary.

**Recommendation:** Remove `s3:ListBucket` from the runtime identity if the adapter does not require it. If a probe requires listing, constrain it with an explicit `s3:prefix` condition limited to the approved profile prefixes and add an integration assertion for cross-prefix denial. Keep administration/probe permissions on the bootstrap identity where possible.

### F-02 — High: image security exceptions can escape validation

**Evidence:** `apps/api/app/shared/storage/objects.py:143-145, 241-267` only normalizes a limited set of Pillow exceptions. Decompression-bomb and other decoder exceptions can be raised outside that set.

**Impact:** Crafted image dimensions or decoder input can produce an uncaught exception and a 500 response instead of a safe typed validation failure, creating a denial-of-service/error-disclosure path at the storage boundary.

**Recommendation:** Catch and normalize relevant Pillow security/decoder exceptions (including decompression-bomb errors) as `ObjectValidationError`; add a crafted oversized-dimension test.

### F-03 — High: T10 high-risk scenarios are under-tested

**Evidence:** `apps/api/app/shared/storage/tests/test_objects.py` covers a PNG happy path, malformed/mismatched bytes, and owned cleanup. `tests/integration/test_profile_privacy.py` covers PNG promotion/private access and cross-account cleanup only.

**Missing task scenarios:** JPEG and WebP validation, oversized final bodies, expired or changed signed submissions, strict CORS behavior, interrupted finalization, runtime cross-prefix/direct-read denial, and complete failure-cleanup behavior.

**Impact:** The task is marked done without executable evidence for several R9–R11/N1 guarantees and the highest-risk media/storage branches.

**Recommendation:** Add focused unit and integration tests for each declared scenario, including provider failures and absence of unintended clean/staging state after failed finalization.

### F-04 — Medium: strict CORS is not wired into the production preparation path

**Evidence:** `StorageProvisioner` only invokes `_configure_upload_cors` when `upload_origin` is supplied (`provision.py:49-50`), while `apps/api/app/bootstrap.py:31-37` constructs it without that value. T10’s task boundary protects bootstrap, so this wiring must be assigned to the owning configuration/bootstrap task rather than silently omitted.

**Impact:** Normal preparation can leave bucket CORS unchanged, so browser signed uploads are not guaranteed to use the approved exact-origin policy.

**Recommendation:** Wire the validated configured web origin through the owning task/configuration boundary, or record an explicit dependency and acceptance test proving T11/T12 performs it.

### F-05 — Medium: private-key validation is prefix-only

**Evidence:** `apps/api/app/shared/storage/objects.py:236-239` accepts any key beginning with `profile-staging/` or `profile-clean/`; it does not enforce the canonical `<prefix>/<UUID>/<UUID>` shape.

**Impact:** An internal caller or future route can request arbitrary objects under those prefixes, bypassing assumptions about opaque IDs and ownership.

**Recommendation:** Validate the exact canonical key structure, or require account/upload identifiers and construct the key internally. Keep public delivery behind the later profile authorization service.

### F-06 — Medium: S3 response bodies are not explicitly closed

**Evidence:** `finalize_staging()` and `get_private()` read `response["Body"]` at `objects.py:130-131` and `167-168` without closing it.

**Impact:** Repeated requests can retain/leak HTTP response resources and reduce connection-pool capacity.

**Recommendation:** Close response bodies in `finally`/context-manager-compatible code after bounded reads; test cleanup on validation and read failures.

### F-07 — Medium: storage failures are inconsistently normalized

**Evidence:** `delete_staging()` and `cleanup_staging()` (`objects.py:177-205`) allow raw `ClientError`/`BotoCoreError` to escape, while `finalize_staging()` maps provider failures to typed domain errors.

**Impact:** Future routes can expose provider-specific details or return inconsistent failures from the same adapter boundary.

**Recommendation:** Normalize provider exceptions consistently to `ObjectOperationError` (or a typed unavailable error) at this boundary.

### F-08 — Medium: image work is unbounded on the default thread pool

**Evidence:** Pillow decode/re-encode and S3 calls are all dispatched with `asyncio.to_thread` (`objects.py:113, 158, 175, 181, 205`), using the process-wide executor.

**Impact:** Concurrent upload abuse can queue CPU/memory-heavy image work and exhaust shared worker capacity.

**Recommendation:** Use a bounded semaphore or dedicated executor for image operations and add a concurrency/resource-limit test.

### F-09 — Medium: integration coverage does not assert runtime permission boundaries

**Evidence:** `tests/integration/test_profile_privacy.py` does not assert runtime listing denial, cross-prefix reads, malformed/oversized finalization, CORS policy, or provider-failure behavior.

**Impact:** Policy regressions can pass despite the runtime identity having broader access than the task allows.

**Recommendation:** Add integration assertions for the runtime IAM boundary and the missing failure cases, especially whole-bucket listing denial.

## Manual Checks Required

- [ ] In a MinIO-compatible environment, verify the provisioned runtime identity cannot list the bucket or read objects outside the approved profile prefixes.
- [ ] Verify the effective bucket CORS configuration is exactly the approved origin, POST-only, and bounded headers/expiry in the real bootstrap/preparation path.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

1. Remove or prefix-scope runtime `s3:ListBucket` (F-01).
2. Normalize Pillow decompression/decoder security failures (F-02).
3. Add the missing high-risk T10 scenario tests before retaining `done` status (F-03).

### Should Address (🟡 Medium)

1. Wire strict CORS through the owning configuration task (F-04).
2. Enforce canonical private object-key shape (F-05).
3. Close S3 response bodies and normalize delete/cleanup provider errors (F-06, F-07).
4. Bound image-operation concurrency and expand runtime integration assertions (F-08, F-09).

### Nice to Have (💭 Low)

None.

---
*Generated by Review — 2026-09-23*
