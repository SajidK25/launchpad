# QA Plan: Member Identity and Private Profiles

> **Date:** 2026-09-25
> **Specs:** [REQ](../requirements/REQ-add-member-identity-profiles.md) · [ARCH](../architecture/ARCH-add-member-identity-profiles.md) · [Review](../reviews/CODE-REVIEW-RECHECK3-add-member-identity-profiles.md)
> **Environment:** `$QA_BASE_URL` (isolated Compose stack; default browser base is `http://web:8080`)
> **Driver:** Playwright via `scripts/qa-browser.mjs` + Docker Compose, curl, and psql
> **Operator steps:** 0
> **Results:** written by `/execute-qa` to `specs/qa/QA-RESULTS-add-member-identity-profiles.md`

## 0. Scope

This plan covers the running identity, email, private-storage, profile, REST, GraphQL, and web surfaces delivered by the member identity slice. It deliberately excludes product creation, voting, staff authorization, social sign-in, MFA, account deletion, and public search. All cases run serially because they share isolated database, mailbox, Redis, storage, and disposable identities.

## 1. Shell Setup

Run from the repository root. Commands use the isolated project name `launchpad-qa` and never the development volumes.

```sh
export COMPOSE_PROJECT_NAME=launchpad-qa
export QA_BASE_URL="${QA_BASE_URL:-http://localhost:8080}"
compose() { docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.checks.yaml "$@"; }
api() { curl --fail-with-body --silent --show-error -H 'Origin: http://localhost:8080' "$QA_BASE_URL$1"; }
mailpit() { compose exec -T mailpit wget -qO- "http://localhost:8025$1"; }
db() { compose exec -T postgres psql -U launchpad_check -d launchpad_check -At -c "$1"; }
```

Use environment-provided values only for credentials and test addresses: `env:QA_MEMBER_A_EMAIL`, `env:QA_MEMBER_A_PASSWORD`, `env:QA_MEMBER_B_EMAIL`, `env:QA_MEMBER_B_PASSWORD`, and `env:QA_UNKNOWN_EMAIL`. Do not place secrets in commands, screenshots, or results. The browser daemon is started once for the run:

```sh
cp /home/tech99/.codex/plugins/cache/foyzulkarim-skills/dev-pipeline/6.3.0/skills/execute-qa/qa-browser.mjs scripts/qa-browser.mjs
node scripts/qa-browser.mjs serve --base "$QA_BASE_URL"
```

Mailpit messages are read through its API inside the Compose network. Database checks are local-only because they require the check Postgres container; against a remote base, record those steps as skipped with the remote API equivalent noted in the case guard.

## 2. Preconditions

| ID | Check | Command | Expected |
|---|---|---|---|
| P0 | Automated suite | `COMPOSE_PROJECT_NAME=launchpad-qa sh scripts/quality/run.sh` | All quality categories pass, including migrations, contracts, builds, security, and browser smoke tests |
| P1 | Isolated services | `compose up -d postgres redis minio mailpit && compose run --rm prepare` | Postgres, Redis, MinIO, and Mailpit are healthy; preparation exits 0 |
| P2 | Base URL | `curl --fail --silent --show-error "$QA_BASE_URL/" >/dev/null` | Web application responds successfully |
| P3 | Disposable identities | Verify `QA_MEMBER_A_*`, `QA_MEMBER_B_*`, and `QA_UNKNOWN_EMAIL` are set without printing values | All required identity variables resolve |
| P4 | Browser driver | `node scripts/qa-browser.mjs status` after `serve` | Daemon is connected to the resolved base |

A failed precondition stops the run. P0 red means the cases do not begin.

## 3. Identities

All identities are disposable and scoped to this isolated Compose project. The single serial lane prevents session, rate-limit, mailbox, and profile-state collisions.

| Identity | Driver | Used for |
|---|---|---|
| `qa-member-a` (`env:QA_MEMBER_A_EMAIL`, `env:QA_MEMBER_A_PASSWORD`) | browser + bash | QA-01–QA-08 |
| `qa-member-b` (`env:QA_MEMBER_B_EMAIL`, `env:QA_MEMBER_B_PASSWORD`) | browser + bash | QA-03, QA-06 |
| `qa-unknown` (`env:QA_UNKNOWN_EMAIL`) | bash | QA-01, QA-04 |

## 4. Operator Handoffs

None. Mail delivery is verified through the isolated Mailpit API; no real inbox or external service is required.

## 4a. Lanes

Serial plan — one lane (`lane1`) containing QA-01 through QA-08 and migration/deploy checks. Cases share identities, mutable profile rows, rate limits, Mailpit, Redis, and the check database; no case may run concurrently.

## 5. Account registration and password policy

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-01 | R1, R2, R8, N2 | bash + browser | none | 1. `[bash]` POST a valid registration for `qa-member-a` with the environment password.<br>2. `[bash]` Repeat registration with the same address and password.<br>3. `[bash]` Register `QA_UNKNOWN_EMAIL` with a seven-character password, a known-compromised password, a 64+-character password containing spaces, and a symbol-bearing password.<br>4. `[bash]` Read account count and verification/profile visibility for `qa-member-a` with `db`.<br>5. `[browser]` Navigate to `/signin`; open the registration route; fill the valid address/password and submit. **Guard:** compare response status/body shape rather than wording tied to account existence; registration responses are intentionally generic.<br>6. `[browser]` Assert the confirmation state and field errors. | `[assert]` First and repeated valid registrations return the same public accepted response/status.<br>[assert] Invalid short and compromised passwords are rejected; no account is created for those attempts.<br>[assert] A 64+-character spaced password is accepted when otherwise valid.<br>[assert] Account count for the canonical address is exactly one; its profile is private and email is unverified.<br>[assert] Registration confirmation does not disclose whether the address already existed.<br>[assert] Field errors are associated with their controls and no password/token value is rendered. |

## 6. Verification and publication gate

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-02 | R4, R5, R10, N1 | bash + browser | none | 1. `[bash]` Request verification twice for `qa-member-a` and retrieve both messages from Mailpit.<br>2. `[bash]` Redeem the older token, then the newest token through the verification endpoint.<br>3. `[bash]` Alter the newest token and retry it.<br>4. `[browser]` Sign in as `qa-member-a`, navigate to `/profile`, and attempt publication before completing required fields.<br>5. `[browser]` Complete display name, ≤160-character bio, supported photo, and one HTTPS link; publish. **Guard:** use the returned profile version for each mutation to avoid intentionally triggering the optimistic-concurrency error.<br>6. `[bash]` Read the public profile REST/GraphQL responses. | `[assert]` The older verification link is rejected after the newer request; the newest valid link verifies exactly once.<br>[assert] Altered or reused tokens do not verify the account and return a safe failure.<br>[assert] Unverified/incomplete publication is rejected and remains private.<br>[assert] A complete verified profile publishes successfully and is visible through public REST and GraphQL reads.<br>[assert] Private challenge tokens are absent from response bodies and logs. |

## 7. Sessions, CSRF, sign-out, and private editing

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-03 | R3, R9, N1, N4 | browser + bash | none | 1. `[browser]` Create a browser context and sign in as `qa-member-a`.<br>2. `[browser]` Navigate from `/signin` to `/profile`, edit the private draft, and save; then reload the route.<br>3. `[bash]` Repeat the profile PATCH without the session CSRF header and with an altered token.<br>4. `[browser]` Sign out and request the session endpoint.<br>5. `[browser]` Create a second context for `qa-member-b`; attempt to open `qa-member-a`'s private profile and photo URL directly. **Guard:** test direct URLs as an unauthenticated visitor and as the other member; do not infer privacy from a hidden navigation link. | `[assert]` The draft survives route transitions and reloads; the mutation remains authorized after the route change.<br>[assert] Missing and altered CSRF tokens return 403 and do not change the profile.<br>[assert] Sign-out clears the session; subsequent session/profile requests return 401/403 as specified.<br>[assert] Another member cannot read private profile details or photo bytes by direct URL.<br>[assert] No console errors occur during the browser journey. |

## 8. Password recovery and all-device invalidation

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-04 | R6, R7, R8, N2, N3 | bash + browser | none | 1. `[bash]` Request recovery for `qa-member-a` and `QA_UNKNOWN_EMAIL` with identical well-formed request shape.<br>2. `[bash]` Compare public responses and retrieve two reset messages for `qa-member-a` from Mailpit.<br>3. `[bash]` Redeem the older link, then the newest link with a valid new password.<br>4. `[bash]` Retry the newest link and an altered/expired-form token.<br>5. `[browser]` Sign in with the new password; verify the old password fails; inspect the reset notice in Mailpit.<br>6. `[bash]` Use a second pre-reset session cookie and call `/api/v1/auth/session`. | `[assert]` Known and unknown well-formed recovery requests have equivalent public status/body shape.<br>[assert]`The older, reused, altered, and expired reset links cannot change a password.<br>[assert]`A valid reset changes only the intended account, preserves email-verification state, and accepts the agreed password policy.<br>[assert]`All pre-reset sessions, including the second device, are invalid after reset; a new sign-in is required.<br>[assert]`A password-change notice is present in Mailpit and contains no raw reset token. |

## 9. Publication requirements and automatic privacy

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-05 | R10, R11, R12, N3 | browser + bash | none | 1. `[browser]` As the verified owner, publish a complete profile.<br>2. `[browser]` Remove the bio or last link and save the edit.<br>3. `[bash]` Read the owner and public profile endpoints immediately; inspect Mailpit for the privacy-change notice.<br>4. `[bash]` Temporarily make SMTP unavailable, perform another edit that removes a publication requirement, restore SMTP, and run the worker retry path. **Guard:** assert the profile state immediately after the edit, before checking mail; email delivery is asynchronous and must not gate privacy.<br>5. `[browser]` Verify the page notice and republish only after restoring all required fields. | `[assert]` Removing a required item saves the edit and changes visibility to private in the same response/transaction.<br>[assert]`The owner sees an actionable privacy-state notice; the public route stops exposing the profile immediately.<br>[assert]`A privacy-change email is delivered once after Mailpit recovery; retries do not duplicate the privacy transition.<br>[assert]`Republishing requires verification and all required fields again. |

## 10. Private media and public profile reads

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-06 | R9, R10, R11, N1 | bash + browser | none | 1. `[bash]` Create a staged JPEG/PNG/WebP upload within 5 MB and complete it as `qa-member-a`.<br>2. `[bash]` Request the photo URL and profile REST/GraphQL reads before publication, as a visitor, and as `qa-member-b`.<br>3. `[browser]` Publish the complete profile and load the public profile and photo as a visitor.<br>4. `[browser]` Unpublish the profile, then reload the same public profile and photo URLs.<br>5. `[bash]` Attempt an unsupported media type, >5 MB upload, non-HTTPS link, and malformed link. | `[assert]` Private profile and photo details/bytes are denied on REST, GraphQL, direct object, and public routes before publication and after unpublication.<br>[assert]`Published profile and photo are readable only after the verified owner publishes them.<br>[assert]`Unsupported, oversized, and invalid-link inputs are rejected with field-safe errors; the private draft remains intact.<br>[assert]`No storage credential, private object key, or signed URL for an unpublished object appears in public responses. |

## 11. Responsive and accessible journeys

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-07 | N4 | browser | none | 1. `[browser]` Set a 390×844 viewport and navigate through sign-in, registration, recovery, and profile editor.<br>2. `[browser]` Use keyboard Tab/Shift+Tab to reach every input, link, submit button, and publication action.<br>3. `[browser]` Submit invalid values and inspect each invalid field's `aria-invalid`, `aria-describedby`, and visible error.<br>4. `[browser]` Set a 1280×900 viewport and repeat the core navigation; capture screenshots for mobile and desktop. | `[assert]` Every interactive control is keyboard reachable and has an accessible name.<br>[assert]`Invalid controls expose `aria-invalid="true"` and point to visible, relevant error text.<br>[assert]`The privacy notice is exposed as status/alert text and is not conveyed by color alone.<br>[judge-visual] Mobile and desktop layouts remain usable without clipped primary actions — pass if all required controls are visible or reachable by normal scrolling and no horizontal page overflow is present. |

## 12. Mail/outbox resilience and deploy risk

| ID | Req | Driver | Operator | Steps | Expected |
|---|---|---|---|---|---|
| QA-08 | R5–R7, R12, N3 | bash local-only | none | 1. `[bash local-only]` Insert or create a due privacy notice, stop Mailpit/SMTP, and run the worker dispatch command.<br>2. `[bash local-only]` Confirm the profile privacy state and outbox retry metadata with `db`.<br>3. `[bash local-only]` Restart Mailpit, rerun scheduler/worker dispatch, and query Mailpit by stable message ID.<br>4. `[bash local-only]` Create an expired verification/reset event and confirm it is suppressed while a privacy notice remains retryable.<br>5. `[bash local-only]` Re-run `compose run --rm prepare` against the existing database and query the current Alembic head. **Guard:** direct Postgres and worker commands are local-only; on a remote environment use the host's migration/job runner and record the substituted command. | `[assert]` SMTP failure does not roll back or re-publicize the profile edit; the outbox event remains retryable.<br>[assert]`After recovery, exactly one privacy notice is delivered and delivery metadata is retained.<br>[assert]`Expired verification/reset links are not sent; eligible privacy notices still dispatch.<br>[assert]`Preparation is idempotent and the database reaches the current migration head without a readiness regression. |

## 13. Migration / Deploy Risk

1. `[bash local-only]` Start the isolated stack from empty volumes and run `compose run --rm prepare`; assert exit 0 and current migration head.
2. `[bash local-only]` Re-run `prepare` without clearing volumes; assert no destructive migration or duplicate-constraint error.
3. `[bash local-only]` Start API and web only after `prepare` completes; assert `/health/ready` is successful and the API does not expose migration tracebacks.
4. `[bash local-only]` Verify the profile-link constraints accept valid HTTPS query strings and reject unsafe schemes/blank links.

## 14. Regression Smoke

Run once after all cases: existing health/connectivity browser smoke, startup-order checks, worker/scheduler progress checks, contract generation/checks, and the unchanged foundation migration/readiness checks. Touched-but-not-changed health, worker, proxy, and build surfaces are smoke-only; no new feature behavior is inferred from them.

## 15. Coverage Map

| Changed file | Covered by |
|---|---|
| `README.md` | Regression smoke |
| `AGENTS.md`, `CLAUDE.md` | P0/context verification |
| `apps/api/alembic/versions/0003_harden_profile_link_constraint.py`, `apps/api/alembic/versions/0004_profile_link_query_constraint.py` | QA-08, Migration / Deploy Risk |
| `apps/api/app/bootstrap.py`, `apps/api/app/main.py` | P1, QA-08, Regression Smoke |
| `apps/api/app/modules/auth/routes.py`, `schemas.py`, `service.py`, `sessions.py`, `tests/test_routes.py` | QA-01–QA-04 |
| `apps/api/app/modules/users/__init__.py`, `graphql.py`, `models.py`, `policies.py`, `repository.py`, `routes.py`, `schemas.py`, `service.py`, `tests/*` | QA-02, QA-03, QA-05, QA-06 |
| `apps/api/app/shared/storage/client.py`, `objects.py`, `provision.py`, `shared/storage/tests/*` | QA-06, QA-08 |
| `apps/web/src/App.tsx`, `App.test.tsx`, `styles.css`, `identity/*`, `profiles/*` | QA-01–QA-07 |
| `packages/contracts/openapi.json`, `operations.graphql`, `schema.graphql`, `package.json`, `src/generated.ts`, `src/graphql.generated.ts` | P0, QA-02–QA-06 |
| `scripts/quality/contracts.sh`, `scripts/quality/generate_graphql_types.py`, `scripts/quality/run.sh` | P0, Regression Smoke |
| `tests/integration/test_member_identity.py`, `test_profile_privacy.py`, `test_storage.py` | P0, QA-01–QA-06, QA-08 |
| `tests/browser/member-identity.spec.ts` | P0, QA-01, QA-03, QA-07 |
| `docs/adr/0002-health-contracts.md`, `0004-check-isolation.md`, `0005-member-sessions-recovery.md`, `0006-profile-privacy-email.md`, `docs/development.md`, `docs/source/*` | Regression Smoke / documentation consistency |
| `specs/architecture/*`, `specs/context/*`, `specs/requirements/*`, `specs/tasks/*`, `specs/qa/*`, `specs/reviews/*` | Artifact consistency and regression smoke |

## 16. Out of Scope

- Product, founder, voting, staff-role, suspension, moderation, account-deletion, and public-search behavior.
- Google sign-in, passkeys, MFA, email-address changes, notification preferences, and real external mailboxes.
- Production or any environment sharing production data.
