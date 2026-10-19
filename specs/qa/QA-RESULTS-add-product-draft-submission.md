# QA Results: Founder Product Drafts and Submission

> **Plan:** [QA-add-product-draft-submission.md](./QA-add-product-draft-submission.md)

### Run 1 — 2026-10-02, commit `a3bd327862e21339988803ff408f84f9e97c3719`, environment local `http://localhost:8080`

| Case | Verdict | Evidence / Notes |
|---|---|---|
| P0 — automated quality gate | **FAIL** | `COMPOSE_PROJECT_NAME=launchpad-qa-gate sh scripts/quality/run.sh` stopped while creating `launchpad-qa-gate_default`: Docker reported `all predefined address pools have been fully subnetted`. No quality category ran. |
| P1–P5 — setup and environment preconditions | SKIPPED | Execution stopped at failed P0 as required by the plan. |
| QA-01–QA-06 | SKIPPED | No browser or API test cases were started. |

**Findings**

| ID | Severity | Description | file:line |
|---|---|---|---|
| F-1 | Environment blocker | The Docker daemon has exhausted its predefined address pools and cannot allocate the isolated QA project's default network. This is host Docker state, not a confirmed application defect. The plan prohibits pruning networks or changing global address pools. | Docker daemon state (no repository file) |

**Run notes**

- `launchpad-dev` was left running and untouched. The failed P0 created no QA project network or test containers.
- No QA credentials were loaded, no accounts or products were created, and no browser cases ran.
- Resume only after a Docker administrator provides network capacity for a separate `launchpad-qa-gate` project. Do not reuse the development network or run Docker prune commands under this plan.

### Run 2 — 2026-10-15, commit `e078a5b`, environment local `http://localhost:8080`

| Case | Verdict | Evidence / Notes |
|---|---|---|
| P0 — automated quality gate | PASS | `COMPOSE_PROJECT_NAME=launchpad-qa-gate sh scripts/quality/run.sh`: Python/integration 402 passed, 1 skipped (protected R2 validation); web 99 passed; format, lint, types, migrations, contracts, builds, security (0 npm vulnerabilities), and browser checks (2 passed) completed successfully. The isolated QA gate network was created successfully, so the prior Docker address-pool blocker is cleared. |
| P1 — required local tools and config | PASS | Docker, curl, Node, `.env.qa.local`, and all four required disposable-account variables were present. Credential values were not printed. |
| P2 — isolated local stack and ports | PASS (after operator-selected override) | Initial API bind to host port 8000 failed with `Bind for 0.0.0.0:8000 failed: port is already allocated`. Per plan, only `launchpad-product-qa` was stopped. The operator selected host port 8001; Compose config confirmed `127.0.0.1:8001->8000/tcp`, and Postgres, Redis, MinIO, Mailpit, API, web, worker, and scheduler started. |
| P3 — migration/readiness | PASS | `http://localhost:8080/api/v1/health/ready` returned `{"status":"ready"}`; isolated database revision is `0011_profile_upload_declarations`, the repository's current head. |
| P4 — browser session | PASS | QA browser daemon connected to `http://localhost:8080` with a headless Chromium context. |
| P5 — fresh identities | PASS | Isolated QA database contained zero accounts before registration. |
| QA-01 — registration, private drafts, and ownership | **FAIL** | After replacing invalid inputs with reserved `.example.com` addresses, A and B registered (HTTP 202); repeating A registration returned the same generic response. B verified through Mailpit; A remained unverified through draft creation, autosave, and reload. B saw “Product unavailable” and no private text; the reviewer queue did not show A's draft. An unauthenticated visitor saw no private text, but the page stayed on “Checking your account…” and logged two 401 resource errors instead of resolving to sign-in/unavailable. |
| QA-02 — media and submission | **FAIL** | Unverified A could not submit; the UI showed the verification gate and kept the draft private. Generated PNG logo/screenshot uploads validated and attached; incomplete submission showed field-specific errors. After A verified and completed the draft, the GraphQL-abort check returned REST submit HTTP 200 and DB state `submitted` with one pending row. The UI showed “Product unavailable” instead of a clear “submission succeeded, latest view could not be refreshed” notice. Clearing the abort and reloading displayed the committed pending submission. |
| QA-03 — queue, duplicate handling, and media privacy | PASS | A and B submitted products with the same HTTPS site; both were marked possible duplicate, A remained first, and reviewer details showed current content and loaded logo/screenshot previews. Topic inputs `QA workflow topic` and `QA WORKFLOW TOPIC` resolved to one private unlaunched topic row. A's valid pending edit saved and left its original queue time/order unchanged. After signing out reviewer B, direct access to A's signed media URL returned HTTP 404. Reviewer detail for each product did not reveal the other product's title. |
| QA-04 — suspension, withdrawal, resubmission, deletion | PARTIAL — remaining URL check skipped by user | The suspended founder could not create a draft (button disabled), edit (Playwright fill rejected the disabled field), or upload (file inputs disabled); withdrawal remained enabled and succeeded after confirming. Staff detail showed “Founder account suspended.” After resuming A, resubmission moved behind B; a second withdrawal succeeded. After the QA-06 handoff, A withdrew and deleted its private draft through the UI. Product, submission, and asset row counts for that product are all 0. Outbox contains completed `product.deleted.v1` and three durable pending `product.media_purge.v1` events; pending purge is retryable by design. B was restored to member and both disposable accounts are unsuspended. Per user direction, the remaining check using the previously observed signed media URL was skipped; that URL was not retained for a post-deletion fetch. |
| QA-05 — origin, CSRF, and capability checks | **FAIL** | Both unauthenticated POSTs (missing Origin and `http://untrusted.invalid`) returned HTTP 403 with `{"detail":"request rejected"}`; product count stayed at 2. Visitor review route remained on “Checking your account…” with no product titles. Verified non-staff A saw “This queue is not available for your account” and no product titles. Contract generation passed with `BUILDKIT_PROGRESS=quiet` after the documented first invocation captured fresh Docker build output into `openapi.json`; the three generated contract files were restored, then regenerated successfully after images were built. |
| QA-06 — responsive and accessible journeys | PARTIAL — screenshot evidence skipped by user | A's editor autosave request returned HTTP 200; missing website produced a role=alert and `aria-invalid` with a matching described error element; unsupported SVG produced a role=alert. Reviewer detail loaded both images with distinct alt text (“Product logo”, “Product screenshot”) and exposed review actions. The operator replied `done` to the requested keyboard-only, screen-reader, and 390×844/1280×900 inspection handoff. Per user direction, screenshot evidence verification was skipped; the four requested PNGs were not found under `specs/qa/evidence/`. The manual judgment therefore has no screenshot artifacts in this workspace. |

**Findings**

| ID | Severity | Description | file:line |
|---|---|---|---|
| F-1 | UX defect | Anonymous visitors opening a private product or `/products/review` remain on “Checking your account…” after `/api/v1/auth/session` returns 401; the page emits 401 console errors. Private product content stayed hidden. | `apps/web/src/products/ProductScreens.tsx:72-88` |
| F-2 | UX defect | When REST submission commits but the subsequent GraphQL refresh is aborted, the database contains a pending submission, but the editor renders “Product unavailable” and omits the promised success-with-refresh-warning notice. Reload after clearing the abort correctly shows “Submitted for review.” | `apps/web/src/products/ProductScreens.tsx:681-687` |
| F-3 | Verification tooling | A cold `sh scripts/quality/contracts.sh` invocation redirected Compose BuildKit progress into `packages/contracts/openapi.json`, making contract generation fail. Restored generated files from HEAD; the check passed after the images were built and `BUILDKIT_PROGRESS=quiet` was set. | `scripts/quality/contracts.sh:9-11,21-23` |

**Run notes**

- Continuation completed 2026-10-16. The original invalid email inputs were replaced with valid `.example.com` addresses and all registration/verification steps completed. Passwords and verification tokens were not written to results.
- The full isolated quality gate passes; the contract script also passes once Compose build progress is quiet. The initially corrupted generated OpenAPI/GraphQL artifacts were restored and are clean again.
- The operator-selected API host port 8001 resolves the port conflict; the web QA URL remains `http://localhost:8080`. The isolated stack remains running for local inspection, with local Mailpit messages and one submitted QA product remaining in the isolated database. The deleted founder product and its database media references are gone. No production or unrelated Docker projects were touched.
- Migration/deploy risk checks passed on 2026-10-16: isolated `prepare` completed successfully; Alembic is at `0011_profile_upload_declarations`; `ix_product_submissions_product_id`, `ix_product_submissions_pending_queue`, and `ix_product_submissions_approved_page` exist; API live and ready endpoints returned `alive` and `ready` after preparation.
- Regression smoke passed on 2026-10-16: `BUILDKIT_PROGRESS=quiet sh scripts/quality/contracts.sh` exited 0; final `/api/v1/health/live` and `/api/v1/health/ready` checks passed; API, Postgres, Redis, MinIO, Mailpit, web, worker, and scheduler were running, with healthy healthchecks where configured. The temporary browser daemon was stopped.
- At the user's direction, the remaining QA-04 signed-URL check and QA-06 screenshot evidence verification were skipped. The operator had confirmed the manual UI inspection; no screenshots are attached to this workspace.

### Run 3 — 2026-10-17, working tree based on `e078a5b`, environment local checks

| Finding | Verdict | Evidence |
|---|---|---|
| F-1 — anonymous session resolution | FIXED | A 401 now resolves the current-session query to a signed-out value without removing its active query. Founder product and reviewer routes both render the sign-in state. Regression tests pass. |
| F-2 — submission followed by failed refresh | FIXED | A failed viewer-product refetch retains the cached editor, reports that submission succeeded but the latest view could not refresh, and does not render “Product unavailable.” Regression test passes. |
| F-3 — contract output contamination | FIXED | The contract script invokes Compose with quiet progress. A fresh-project contract generation completed with exit 0 and left generated contract files unchanged; `contracts.sh --check` also passed. |

**Verification**

- Frontend formatting, lint, typecheck, all 101 web tests, and production build passed in the Docker tooling image.
- `sh -n scripts/quality/contracts.sh` and `git diff --check` passed.
- The complete Python/integration quality suite was not rerun because these changes affect only the web client and contract-generation script.
