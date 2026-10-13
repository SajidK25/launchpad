# QA Plan: Founder Product Drafts and Submission

> **Date:** 2026-10-02
> **Specs:** [REQ](../requirements/REQ-add-product-draft-submission.md) · [ARCH](../architecture/ARCH-add-product-draft-submission.md) · [TASKS](../tasks/TASKS-add-product-draft-submission.md) · [Review](../reviews/CODE-REVIEW-PIPELINE-add-product-draft-submission.md)
> **Environment:** `$QA_BASE_URL` (isolated local Compose project; default `http://localhost:8080`)
> **Driver:** Playwright via `/tmp/qa-browser.mjs` + Docker Compose, curl, and psql
> **Operator steps:** 1 — see §4
> **Results:** written by `/execute-qa` to `specs/qa/QA-RESULTS-add-product-draft-submission.md`

## 0. Scope

This plan covers private founder drafts, validated media, verified-email submission, review queue behavior, withdrawal/resubmission, suspension policy, private media access and cleanup, origin/CSRF boundaries, and the reviewed T1–T20 product slice. It deliberately excludes review decisions, approval/rejection, scheduling, launch/public discovery, production data, and real external mail. Automated T1–T20 regression checks remain mandatory; this plan adds running-server and human-observable checks.

## 1. Shell Setup

Run from the repository root. Use a dedicated Compose project; do not reuse or remove existing containers, networks, or volumes. The project name isolates named volumes from the developer stack.

```sh
set -eu
export COMPOSE_PROJECT_NAME=launchpad-product-qa
export QA_BASE_URL="${QA_BASE_URL:-http://localhost:8080}"
export QA_ORIGIN=http://localhost:8080
compose() { docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.yaml "$@"; }
api() { curl --silent --show-error --include -H "Origin: $QA_ORIGIN" "$QA_BASE_URL$1"; }
db() { compose exec -T postgres psql -U launchpad_development -d launchpad_development -At -v ON_ERROR_STOP=1 "$@"; }
account_id() { db -v email="$1" -c "SELECT id FROM accounts WHERE email_key = lower(:'email')"; }
operator() { compose run --rm --no-deps -v "$PWD/scripts/operators/manage_accounts.py:/workspace/scripts/operators/manage_accounts.py:ro" api python scripts/operators/manage_accounts.py "$@"; }
set -a; . .env.qa.local; set +a
mkdir -p specs/qa/evidence
```

Read values only from `.env.qa.local`: `QA_MEMBER_A_EMAIL`, `QA_MEMBER_A_PASSWORD`, `QA_MEMBER_B_EMAIL`, and `QA_MEMBER_B_PASSWORD`. Never print or paste credentials, verification tokens, session cookies, or signed URLs into results. Keep A unverified until QA-02. Accounts must be fresh disposable addresses for this isolated database. If either address already exists, stop and use new QA aliases; do not delete or repurpose an existing account.

Copy the browser driver outside the repository so the QA run does not create a source-tree artifact, then start its persistent session in a separate terminal:

```sh
cp /home/tech99/.codex/plugins/cache/foyzulkarim-skills/dev-pipeline/6.3.0/skills/execute-qa/qa-browser.mjs /tmp/qa-browser.mjs
node /tmp/qa-browser.mjs serve --base "$QA_BASE_URL"
```

Use `node /tmp/qa-browser.mjs <command>` for browser steps. The driver accepts targets prefixed by `text=`, `role=`, or `css=`. For image upload, use its `eval` command to create a tiny PNG in a canvas, assign a `File` through `DataTransfer` to the relevant `input[type=file]`, and dispatch the input's `change` event; do not use an external object URL as evidence of successful attachment. Mailpit's local UI is `http://localhost:8025`; this absolute URL is an intentional local test-service surface. Its messages contain local verification links; do not copy their tokens into the shell or results.

To grant/revoke temporary reviewer access or suspend/resume an account, resolve the ID using `account_id` and run the audited operator command in a one-off container with the CLI mounted read-only. The operator CLI is intentionally not included in the API image:

```sh
operator --actor qa-product-plan --account-id "$(account_id "$QA_MEMBER_B_EMAIL")" set-role --role reviewer
operator --actor qa-product-plan --account-id "$(account_id "$QA_MEMBER_B_EMAIL")" set-role --role member
operator --actor qa-product-plan --account-id "$(account_id "$QA_MEMBER_A_EMAIL")" suspend
operator --actor qa-product-plan --account-id "$(account_id "$QA_MEMBER_A_EMAIL")" resume
```

Only run those commands against the isolated QA accounts. Restore B to `member` and A to unsuspended at the end, even if an earlier case fails. If restoration fails, stop and report it; do not continue using the altered identities.

## 2. Preconditions

| ID | Check | Command | Expected |
|---|---|---|---|
| P0 | Automated suite | `COMPOSE_PROJECT_NAME=launchpad-qa-gate sh scripts/quality/run.sh` | All quality categories pass, including migrations, contracts, builds, security, integration, and browser checks. A failure stops the run. |
| P1 | Required local tools and config | `command -v docker curl node; test -f .env.qa.local; set -a; . .env.qa.local; set +a; test -n "$QA_MEMBER_A_EMAIL"; test -n "$QA_MEMBER_B_EMAIL"; test -n "$QA_MEMBER_A_PASSWORD"; test -n "$QA_MEMBER_B_PASSWORD"` | Docker, curl, Node, and disposable account credentials are available; values are not printed. |
| P2 | Isolated local stack and ports | `compose up -d` then `compose ps` | Services start in fresh project `launchpad-product-qa`; Postgres, Redis, MinIO, Mailpit, API, web, worker, and scheduler are healthy/running, with this Compose file's localhost ports available (8080, 8000, 9000, 9001, 1025, 8025). If a port is occupied, stop and request a port override; do not stop another project or prune Docker resources. |
| P3 | Migration/readiness | `curl --fail --silent --show-error "$QA_BASE_URL/api/v1/health/ready"` and `db -c 'SELECT version_num FROM alembic_version'` | Readiness is successful and Alembic is at the repository's current head, including revision `0007_product_submission_idx`. |
| P4 | Browser session | `node /tmp/qa-browser.mjs status` after `serve` | Browser daemon is connected to `$QA_BASE_URL`. |
| P5 | Fresh identities | `test -z "$(account_id "$QA_MEMBER_A_EMAIL")" && test -z "$(account_id "$QA_MEMBER_B_EMAIL")"` | Both founder addresses are unused in this isolated database before registration. |

Environment note: a prior attempt reported `all predefined address pools have been fully subnetted`. If P0 or P2 encounters this, record the exact failure and stop. Do not run `docker network prune`, `docker system prune`, remove volumes, or alter global Docker address pools as part of this QA plan.

## 3. Identities

All accounts are disposable and belong only to `launchpad-product-qa`. Cases run serially because they share identities, database rows, Mailpit, MinIO, rate limits, and queue state.

| Identity | Driver | Used for |
|---|---|---|
| `qa-member-a` (`env:QA_MEMBER_A_EMAIL`, `env:QA_MEMBER_A_PASSWORD`) | browser + bash | QA-01–QA-06; founder and suspension checks; unverified until QA-02 |
| `qa-member-b` (`env:QA_MEMBER_B_EMAIL`, `env:QA_MEMBER_B_PASSWORD`) | browser + bash | QA-01, QA-03–QA-06; second founder, then temporary reviewer |
| Unauthenticated visitor | browser + bash | QA-01, QA-03, QA-05–QA-06 |

Create A and B through `/register` in the running app. Keep A unverified through draft creation and the blocked submission attempt in QA-02; verify A via Mailpit only afterward. Verify B before its first submission. Registration has a generic public response; do not infer account existence from response wording. A/B are never used in parallel browser contexts.

## 4. Operator Handoffs

| Case | Trigger | Exact action |
|---|---|---|
| QA-06 | Founder/reviewer UI journeys and desktop/mobile layouts are loaded | “At both 390×844 and 1280×900, inspect the founder editor and staff queue. Use keyboard-only navigation through every control, then use a screen reader to verify save, error, and alert announcements and distinguish screenshot previews. Check for clipped content or horizontal page overflow. Save screenshots to `specs/qa/evidence/QA-06-founder-390x844.png`, `specs/qa/evidence/QA-06-founder-1280x900.png`, `specs/qa/evidence/QA-06-reviewer-390x844.png`, and `specs/qa/evidence/QA-06-reviewer-1280x900.png`. Reply done when finished.” |

## 4a. Lanes

Serial plan — one lane (`lane1`) containing QA-01 through QA-06 and the migration/deploy checks. The same identities, their role/suspension state, product rows, asset storage, Mailpit, Redis throttles, and database are shared; no case may run concurrently. Operator-handoff case QA-06 is pinned to lane 1.

## 5. Registration, private drafts, and ownership

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-01 | R1–R4, R8, N1–N2 | browser + bash | none | 1. `[browser]` Open fresh contexts and register A (`env:QA_MEMBER_A_EMAIL`, `env:QA_MEMBER_A_PASSWORD`) and B (`env:QA_MEMBER_B_EMAIL`, `env:QA_MEMBER_B_PASSWORD`). Repeat A's registration once to check the existing-account response shape. **Guard:** compare status/body shape only; registration responses are intentionally generic.<br>2. `[browser]` In Mailpit, verify B by opening B's verification message and following its local link; leave A unverified. **Guard:** do not copy token values into commands, screenshots, or notes.<br>3. `[browser]` Sign in as unverified A, navigate to `/products`, create a draft, edit its name and pitch, and wait for “Saved”.<br>4. `[browser]` Reload `/products/<A_PRODUCT_ID>` and verify saved text remains.<br>5. `[browser]` Sign in as B and open `/products/<A_PRODUCT_ID>` directly; then sign out and open the same route as a visitor.<br>6. `[bash]` Promote B to reviewer with the audited operator command in §1, sign in again, and navigate to `/products/review` before A submits. | `[assert]` First and repeated registration responses have the same generic status/body shape and disclose no account state.<br>[assert] B's verification link targets `http://localhost:8080/verify`; B is verified while A remains unverified.<br>[assert] Unverified A can draft and save; the UI identifies that submission requires verified email.<br>[assert] Autosaved content survives reload and the save indicator reaches its saved state.<br>[assert] B and the visitor see the unavailable/hidden state and no A draft content or media.<br>[assert] Reviewer queue has no entry for A's private draft. |

## 6. Validated media and submission

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-02 | R5–R10, N1–N4 | browser | none | 1. `[browser]` As unverified A, open the private draft and fill name, pitch, and 1–3 topic names (one new proposal), leaving description and website empty.<br>2. `[browser]` Attempt submission before verification; observe the verification-gate message and confirm the product remains a private draft.<br>3. `[browser]` Create/select a tiny PNG logo and screenshot using the canvas/DataTransfer procedure in §1; wait until each upload is validated and attached.<br>4. `[browser]` In Mailpit, verify A via the newest verification message/link. **Guard:** do not copy token values into commands, screenshots, or notes.<br>5. `[browser]` Attempt submission while description and website are still missing; then fill them and wait for save completion.<br>6. `[browser]` Use `route abort '**/api/v1/graphql'` only after the editor has loaded; submit through the REST command, observe the post-commit refresh notice, then use `route clear` and reload. **Guard:** remove the GraphQL abort before the reload so the page can reconcile with persisted state. | `[assert]` Unverified A cannot submit; no review entry is created, and the draft remains private.<br>[assert] Supported logo and screenshot become validated/attached; both appear complete in the submission checklist.<br>[assert] Incomplete submission is blocked with field-specific errors and saved draft fields remain present.<br>[assert] A committed submission remains pending when the follow-up GraphQL refresh fails, and the notice clearly says submission succeeded but the latest view could not be refreshed.<br>[assert] After clearing the route and reloading, A still sees the pending state; retry/reload does not create a duplicate queue entry. |

## 7. Review queue, duplicate handling, and media privacy

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-03 | R8, R10, R13–R15, N1–N3 | browser + bash | none | 1. `[browser]` Sign in as B, create and complete a second product draft using the same HTTPS website as A, select an equivalent topic spelling with different capitalization/outer spaces, upload required media, and submit.<br>2. `[browser]` Open `/products/review`; open both queue entries and inspect ordering, current media, duplicate flag, and staff-only flags.<br>3. `[browser]` As A, make a valid pending edit and save; return as B and reload the queue.<br>4. `[browser]` As an unauthenticated visitor, open A's pending product route and the direct app-signed media URL copied from A's network response. **Guard:** only test the app/API-signed URL; never request or disclose raw MinIO object keys/credentials.<br>5. `[bash]` Query product/submission counts with `db` using the QA owners and known test product IDs; do not emit email addresses or tokens. | `[assert]` Same-site submission is accepted into review and marked possible duplicate; A and B see no identifying details about the other founder's match.<br>[assert] Equivalent new topic names resolve without duplicate topic rows; proposed topics remain private until a launch workflow makes them eligible for public choice lists (automated privacy coverage is in P0).<br>[assert] Reviewer queue is ordered oldest-first; the edit does not change A's original submission time/order.<br>[assert] Reviewer can read current submitted content and media; the visitor cannot read pending media or product details by direct URL.<br>[assert] Exactly one pending submission exists for each submitted product; no raw object key or storage credential appears in returned content. |

## 8. Suspension, withdrawal, resubmission, and deletion

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-04 | R11, R13–R17, N2–N4 | browser + bash | none | 1. `[bash]` Use audited `suspend` for A; reload A's current session and pending-product page.<br>2. `[browser]` Attempt to create another draft and edit/upload the pending item as A, then withdraw; confirm the UI prompt.<br>3. `[browser]` As B reviewer, reload `/products/review` and verify the suspended flag; then restore A with `resume`.<br>4. `[browser]` Resubmit A's complete draft; as B reviewer verify the resubmission is at the back of the queue; then sign in as A, withdraw it again, and open its editor.<br>5. `[browser]` Delete A's private draft through the confirmation UI; immediately try its old editor route and previously observed app-signed media URL as visitor and owner.<br>6. `[bash]` Verify `db` has no product/active-submission row for the deleted product and that a purge outbox event exists. **Guard:** do not select/decrypt or print outbox payloads; the event may be retried asynchronously, but authorization revocation must be immediate.<br>7. `[bash]` Restore B to role `member` using the audited command in §1. | `[assert]` Suspension blocks A's draft creation, edits, and uploads but preserves the existing staff-visible submission and suspended-founder indicator.<br>[assert] A can withdraw while suspended; the queue no longer returns that pending entry.<br>[assert] After suspension is lifted, resubmission creates a new queue position behind earlier entries; it does not reuse the withdrawn period.<br>[assert] Successful deletion immediately hides the product and media and removes database product/active-submission state; retryable failure behavior and late signed uploads are covered by P0 integration tests.<br>[assert] Purge event is durable; no object key or product content is printed or exposed by API responses.<br>[assert] B is a member and A is unsuspended at case end. |

P0's automated suite is the regression driver for concurrent same-product submission, draft/pending caps, asset-intent rate limits, late staging uploads after deletion, failed-deletion retry, CSRF failures, and response contracts. These checks are not repeated with shared browser state because their concurrency and rate-limit setup is isolated and deterministic in the suite.

## 9. Origin, CSRF, and capability checks

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-05 | R1, R9, R14, R17, N1–N2 | bash + browser | none | 1. `[bash]` Run `db -c 'SELECT count(*) FROM products'` and retain the result as `before`.<br>2. `[bash]` Run `curl --silent --show-error --include -X POST "$QA_BASE_URL/api/v1/me/products" -H 'Content-Type: application/json' --data '{}'`. **Guard:** send no session cookie or CSRF value; this isolates the missing-origin rejection before authentication.<br>3. `[bash]` Repeat the same request with `-H 'Origin: http://untrusted.invalid'`.<br>4. `[bash]` Run `db -c 'SELECT count(*) FROM products'` and compare with `before`.<br>5. `[browser]` As visitor, navigate to `/products/review` and to an A product route using its known test ID.<br>6. `[browser]` As regular verified member A (B is returned to member in QA-04), open `/products/review` directly.<br>7. `[bash]` Run `sh scripts/quality/contracts.sh`. | `[assert]` Both requests return HTTP 403 and `{"detail":"request rejected"}`; product count is unchanged.<br>[assert] Visitor sees sign-in/unavailable states and no private details.<br>[assert] Non-staff member cannot read the review queue or staff detail even by direct route/API query.<br>[assert] Contracts check exits zero and generated schemas include product REST and GraphQL surfaces. |

## 10. Responsive and accessible product journeys

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-06 | R2, R4, R6, R11, R14, N5 | browser | operator handoff in §4 | 1. `[browser]` Sign in as A, navigate to `/products/<A_PRODUCT_ID>`, trigger a save, validation error, and upload alert by dispatching an unsupported SVG file to the upload input; inspect status/alert roles and field associations.<br>2. `[browser]` Sign in as B reviewer and navigate to `/products/review/<A_PRODUCT_ID>`; inspect media labels and queue actions.<br>3. `[browser]` Hand off the loaded surfaces for the exact mobile/desktop, keyboard, screen-reader inspection in §4; save screenshots at the four requested viewport/surface combinations. | `[assert]` Save and error messages are exposed as status/alert content and invalid fields are programmatically associated with their visible errors.<br>[assert] Logo and each screenshot preview have distinguishable accessible names.<br>[judge-visual] Founder and reviewer screens at 390×844 and 1280×900 remain usable — pass if primary actions are visible or reachable by normal scrolling, no horizontal page overflow occurs, and hierarchy makes private/pending state and errors apparent.<br>[judge] Keyboard and screen-reader operability — pass if every action is reachable and operable without a pointer, save/error/alert changes are announced, and media previews have distinct spoken names; fail on an unannounced state change or ambiguous preview name. |

## 11. Migration / Deploy Risk

1. `[bash local-only]` Start the isolated stack with `compose up -d`; assert the `prepare` service completes successfully before API readiness.
2. `[bash local-only]` Query `alembic_version`; assert current head is applied, including revision `0007_product_submission_idx`'s product-submission index.
3. `[bash local-only]` Re-run preparation with `compose run --rm prepare`; assert it exits 0 and readiness remains successful.
4. `[bash local-only]` Assert `/api/v1/health/ready` is successful and no migration tracebacks are returned. **Guard:** do not edit or downgrade migrations; use only the project-scoped QA database.
5. `[bash local-only]` Verify the product-submission product index exists with a read-only `pg_indexes` query; do not alter index state during QA.

## 12. Regression Smoke

After the feature cases, verify `/api/v1/health/live` and `/api/v1/health/ready`, reload the founder workspace and reviewer queue, inspect browser console errors, check worker/scheduler services remain healthy, and rerun `sh scripts/quality/contracts.sh`. Touched-but-not-changed auth, storage, GraphQL composition, web proxy, and startup/readiness surfaces receive smoke coverage only; no public launch behavior is inferred.

## 13. Coverage Map

| Changed file | Covered by |
|---|---|
| `apps/api/app/modules/products/models.py` | QA-03, QA-04, QA-05, Migration / Deploy Risk |
| `apps/api/alembic/versions/0007_product_submission_product_index.py` | P0, Migration / Deploy Risk |
| `apps/api/app/modules/products/tests/test_assets.py` | P0, QA-02, QA-04–QA-05 |
| `apps/api/app/modules/products/tests/test_routes.py` | P0, QA-01–QA-02, QA-06 |
| `apps/api/app/shared/storage/objects.py` | P0, QA-02, QA-04–QA-05 |
| `apps/api/app/shared/storage/tests/test_objects.py` | P0, QA-02, QA-04–QA-05 |
| `apps/web/src/products/ProductScreens.tsx` | QA-01–QA-04, QA-06 |
| `tests/integration/test_product_deletion.py` | P0, QA-04–QA-05 |
| `tests/integration/test_product_schema.py` | P0, QA-03, Migration / Deploy Risk |
| `tests/integration/test_product_submission.py` | P0, QA-02–QA-05 |
| `docs/development.md` | P0/context consistency, Regression Smoke |
| `specs/requirements/REQ-add-product-draft-submission.md` | Traceability across QA-01–QA-06 |
| `specs/architecture/ARCH-add-product-draft-submission.md` | Traceability across QA-01–QA-06, Migration / Deploy Risk |
| `specs/tasks/TASKS-add-product-draft-submission.md` | P0 and all case coverage; regression smoke |
| `specs/reviews/CODE-REVIEW-PIPELINE-add-product-draft-submission.md` | P0 and QA-02–QA-06 review-remediation checks |

## 14. Out of Scope

- Reviewer decisions, approval/rejection, requested changes, scheduling, launch, and public product/topic discovery.
- Real SMTP/inboxes, production deployments, shared development data, and cross-environment account reuse.
- Destructive Docker cleanup, global network-pool changes, volume deletion, or manual database repair.
- Re-testing unrelated identity/profile/voting behavior beyond the registration/verification prerequisite and required-product verification gate.
- Full manual testing of every browser/assistive-technology combination; QA-06 is a focused operator observation at the agreed viewport sizes.
