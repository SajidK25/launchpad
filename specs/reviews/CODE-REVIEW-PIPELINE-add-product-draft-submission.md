# Code Review — Founder Product Drafts and Submission

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: ARCH-add-product-draft-submission |
| **Target** | T1–T20 implementation, `a65e1a1` → `a3bd327` |
| **Date** | 2026-10-02 00:52 Asia/Dhaka |
| **Tech Stack** | Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL/Alembic, Strawberry GraphQL, React, strict TypeScript, TanStack Query, pytest, Vitest, Docker Compose |
| **Checks Run** | Task completion; code quality; test coverage; security; documentation; config/dependencies; TypeScript strictness; React patterns; accessibility; async patterns; error handling; database patterns; migration; requirement coverage |
| **Checks Skipped** | Express patterns (FastAPI stack); separate performance/runtime-behavior audits (not selected in confirmed scope) |
| **Files Changed** | 84 |
| **Lines Changed** | +18,099 / -166 |

## Review Process

- [x] Preflight checks passed (remote default-branch lookup was unavailable; local `main` was used)
- [x] Diff gathered (84 files, 18,265 changed lines)
- [x] Tech stack detected: Python/FastAPI, PostgreSQL/SQLAlchemy/Alembic, React/TypeScript/TanStack Query
- [x] Context read (AGENTS.md, CLAUDE.md, linked REQ, ARCH, TASKS)
- [x] Triage proposed and developer confirmed whole-slice, batched review
- [x] 10 domain batches dispatched: task completion; security; database/migration; test coverage; requirement coverage; code quality; documentation; frontend React/TypeScript/accessibility; config/dependencies; async/error handling
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to specs/reviews/

## Verdict: ❌ FAIL

The slice has broad automated coverage and the recorded full quality gate passed. However, review found a high-severity image decompression resource-exhaustion risk, alongside version races and misleading mutation error states in the editor. Several required boundaries lack direct tests, T15 still documents a superseded migration head, and the product UI’s required manual viewport/accessibility verification is not recorded.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion | 0 | 0 | 1 | 0 | 1 |
| Security | 0 | 1 | 0 | 0 | 0 |
| Database patterns | 0 | 0 | 1 | 0 | 0 |
| Migration | 0 | 0 | 0 | 0 | 0 |
| Test coverage | 0 | 0 | 2 | 0 | 0 |
| Requirement coverage | 0 | 0 | 2 | 0 | 0 |
| Code quality | 0 | 0 | 1 | 0 | 0 |
| Documentation | 0 | 0 | 1 | 1 | 0 |
| Config/dependencies | 0 | 0 | 0 | 0 | 0 |
| React patterns | 0 | 0 | 1 | 1 | 0 |
| TypeScript strictness | 0 | 0 | 0 | 0 | 0 |
| Accessibility | 0 | 0 | 0 | 0 | 0 |
| Async patterns / error handling | 0 | 0 | 1 | 0 | 0 |
| **Total** | **0** | **1** | **10** | **2** | **1** |

## Findings

### Task Completion

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| TASK-1 | 🟡 Medium | [TASKS-add-product-draft-submission.md:915](/home/tech99/Launchpad/launchpad/specs/tasks/TASKS-add-product-draft-submission.md:915) | T15’s completed rollout checklist and decision still name migration 0005, while the final architecture and T19 require migration 0006 and 0006-compatible API/typed-worker images. Exact-head readiness rejects a 0005 binary after the later migration. | Update T15’s readiness and cutover evidence to 0006, or explicitly label 0005 as a superseded intermediate milestone. |
| TASK-2 | ⚠️ Manual | [TASKS-add-product-draft-submission.md:1033](/home/tech99/Launchpad/launchpad/specs/tasks/TASKS-add-product-draft-submission.md:1033) | T17/T18 are marked done, but the explicit 390px/1280px, keyboard, and assistive-technology UI checklist observations are not recorded. The product browser suite does not exercise these screens; the full quality gate is not a substitute for these N5 checks. | Record product-specific manual evidence or keep the relevant checklist items explicitly unverified pending QA. |

### Security

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| SEC-1 | 🟠 High | [objects.py:438](/home/tech99/Launchpad/launchpad/apps/api/app/shared/storage/objects.py:438) | Image validation limits compressed bytes but not decoded dimensions/pixel count. Pillow’s decompression-bomb warning is listed in an exception tuple, but warnings are not exceptions by default; the image is then fully decoded/re-encoded. Four concurrent decodes can let authenticated uploads consume excessive CPU/memory or OOM an API worker. | Enforce a safe pixel/dimension ceiling before decoding and promote `Image.DecompressionBombWarning` to an exception in a local warnings filter. Keep limits compatible with accepted media. |

### Database Patterns

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| DB-1 | 🟡 Medium | [0005_product_drafts_submission.py:105](/home/tech99/Launchpad/launchpad/apps/api/alembic/versions/0005_product_drafts_submission.py:105) | `product_submissions.product_id` has a partial index for pending rows, but withdrawn submission-period history is retained and product deletion cascades across all periods. PostgreSQL cannot use the pending-only index for the full foreign-key cascade lookup, so deleting a product can scan an ever-growing history table. | Add a full, non-partial index on `product_submissions(product_id)` while retaining the pending uniqueness and queue indexes. |

### Test Coverage

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| TEST-1 | 🟡 Medium | [test_product_submission.py:247](/home/tech99/Launchpad/launchpad/tests/integration/test_product_submission.py:247) | Same-product submission idempotency is tested sequentially. The concurrent test covers two different products contending for a founder quota, not two requests submitting the same product/version as T6 specifies. | Barrier-start two sessions submitting the same product/version; assert both observe one pending period and only one submission event is committed. |
| TEST-2 | 🟡 Medium | [test_product_deletion.py:248](/home/tech99/Launchpad/launchpad/tests/integration/test_product_deletion.py:248) | Deletion tests cover delayed purge and eventual removal, but do not simulate a signed staging upload successfully writing its object after metadata deletion and before URL expiry, the ordering called out by T10. | Simulate the late write, dispatch purge after expiry/grace, then assert the object is removed while metadata and access remain revoked. |

### Requirement Coverage

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| REQ-1 | 🟡 Medium | [test_product_submission.py:359](/home/tech99/Launchpad/launchpad/tests/integration/test_product_submission.py:359) | R16’s special withdrawal-at-cap behavior is not asserted: withdrawing while at 10 private drafts may create an 11th draft, after which further creation must be blocked until the count falls below 10. Existing tests cover ordinary draft caps and a withdrawal with one product. | Add the 10-draft withdrawal → 11 drafts → blocked creation case, including recovery after a slot is freed. |
| REQ-2 | 🟡 Medium | [test_assets.py:111](/home/tech99/Launchpad/launchpad/apps/api/app/modules/products/tests/test_assets.py:111) | N4’s upload-intent bounds lack boundary assertions. The service caps active intents, but the tests do not assert rejection of an 11th active intent or the upload-intent action rate limit. | Add tests at and over the active-intent cap and for the configured action-rate limit. |
R12 decision-time stale-review enforcement is explicitly deferred to the later reviewer-decision workflow; this review does not treat that out-of-scope behavior as a defect in this slice.

### Code Quality

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| CQ-1 | 🟡 Medium | [ProductScreens.tsx:675](/home/tech99/Launchpad/launchpad/apps/web/src/products/ProductScreens.tsx:675) | `ProductEditorForm` centralizes autosave/conflict state, upload/attachment flows, submission/withdrawal/deletion actions, and the complete editor UI in one very large component. This coupling raises regression risk when changing independent workflows. | Consider extracting focused media and submission hooks/components while retaining a shared version/state boundary. |

### Documentation

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| DOC-1 | 🟡 Medium | [development.md:117](/home/tech99/Launchpad/launchpad/docs/development.md:117) | Release guidance refers to “product activation” and production opt-in without naming the operative `LAUNCHPAD_PRODUCTS_ENABLED` setting, so operators cannot follow the documented off → enable → rollback steps precisely. | Name the flag and describe its false/true/false use in the controlled rollout without exposing secrets. |
| DOC-2 | 💭 Low | [development.md:126](/home/tech99/Launchpad/launchpad/docs/development.md:126) | The operator CLI examples omit the required `LAUNCHPAD_DATABASE_URL`; the CLI exits if it is not injected. The preceding text mentions secret-managed DB access but not the variable name. | State that `LAUNCHPAD_DATABASE_URL` must be injected through the approved secret manager, without printing its value. |

### React Patterns

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| REACT-1 | 🟡 Medium | [ProductScreens.tsx:848](/home/tech99/Launchpad/launchpad/apps/web/src/products/ProductScreens.tsx:848) | `saveMedia()` flushes autosave, then sends the versioned attachment PUT, but product fields remain editable while that PUT is pending. A debounced PATCH can race the PUT using the same version, producing a 409 and leaving either the text edit conflicted or media unapplied. | Serialize attachment through the same versioned mutation boundary, or buffer/disable product edits until attachment acknowledges and adopt the returned version. |
| REACT-2 | 💭 Low | [ProductScreens.tsx:1357](/home/tech99/Launchpad/launchpad/apps/web/src/products/ProductScreens.tsx:1357) | Screenshot choices use the repeated accessible name “Screenshot preview”; multiple images are not distinguishable by image name to a screen-reader user. | Provide a stable ordinal or available filename in each image’s accessible name. |

### Async Patterns / Error Handling

| # | Severity | Location | Finding | Recommendation |
|---|---|---|---|---|
| ASYNC-1 | 🟡 Medium | [ProductScreens.tsx:912](/home/tech99/Launchpad/launchpad/apps/web/src/products/ProductScreens.tsx:912) | A successful submit sets pending state and a success notice before awaiting `reload()`, but the same `try` catches reload failures and reports that submission failed and the private draft remains available. Similar mutation/refresh coupling occurs after attachment and withdrawal. | Separate mutation failures from refresh failures; preserve confirmed server state and report refresh trouble without claiming the committed action failed. |

### Checks With No Findings

- **Migration:** additive forward revisions and exact-head readiness align with the documented rollout; no migration finding.
- **Config/dependencies:** feature-gate defaults and explicit Compose enablement are consistent; no dependencies or lock files changed; no config finding.
- **TypeScript strictness:** no actionable unsafe assertions or typing holes found.
- **Additional security review:** no other authorization, CSRF/origin, private-data exposure, logging, or secret-handling findings beyond SEC-1.
- **Additional async/error review:** worker retry/idempotency and storage cleanup looked sound outside ASYNC-1.

## Manual Checks Required

- [ ] Verify the founder editor and staff queue at approximately 390px and 1280px, including horizontal overflow and keyboard-only operation.
- [ ] Verify save/error/alert announcements and screenshot selection identification with a screen reader.
- [ ] Record product-specific QA evidence; the available browser tests cover connectivity/identity, not the product UI.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

- SEC-1: reject oversized decoded image dimensions/pixel counts before full image decoding and re-encoding.

### Should Address (🟡 Medium)

- DB-1: index all `product_submissions.product_id` rows for cascade lookups.
- TASK-1: align T15 rollout evidence with migration 0006.
- REACT-1: serialize attachment replacement with editor autosave.
- ASYNC-1: do not report committed mutations as failed when only refresh fails.
- TEST-1, TEST-2, REQ-1, REQ-2: add the specified same-product race, late-upload deletion ordering, draft-limit withdrawal, and upload-intent limit/rate-boundary tests.
- DOC-1: document the exact product activation flag and rollback configuration.
- Complete and record TASK-2 manual UI verification.

### Nice to Have (💭 Low)

- DOC-2: identify `LAUNCHPAD_DATABASE_URL` as a required secret-injected operator variable.
- REACT-2: give each screenshot preview a distinct accessible name.

---
*Generated by Review — 2026-10-02 00:52 Asia/Dhaka*
