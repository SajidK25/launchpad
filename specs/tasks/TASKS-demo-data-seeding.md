# Tasks

## Task T1: Add the demo seed ownership ledger

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** None
> **Satisfies REQs:** R2, R7, R10, R11, N2
> **Footprint slice:** New operations package/model/repository and Alembic ownership-ledger migration.
> **High-risk areas touched:** Database migrations (low); seed ownership and retention (medium).

### Description

Add PostgreSQL records for one seed dataset per approved target and a stable-key mapping for every seed-owned entity. Persist the first-attempt UTC date anchor and serialize same-target reconciliation, so an interrupted run can resume without shifting already published dates or claiming unrelated records.

### Test Plan

#### Test File(s)
- `apps/api/app/operations/demo_seed/tests/test_persistence.py`

#### Test Scenarios

##### Migration and Existing Data

- **upgrades ledger schema from 0016 without changing domain rows** — GIVEN existing accounts and products at revision 0016 WHEN the new migration is applied THEN both ledger tables, constraints, and indexes exist and the original domain rows are unchanged _(guards R2, N2)_
- **upgrades a fresh database to head** — GIVEN an empty PostgreSQL database WHEN the normal migration chain runs THEN the schema reaches the latest revision and both ledger tables are usable _(guards ARCH migration rollout)_
- **preserves ownership data on downgrade** — GIVEN at least one dataset/artifact row WHEN Alembic downgrades the ledger revision THEN downgrade is refused without deleting the ownership record; GIVEN an empty ledger WHEN downgraded THEN the new schema objects are removed _(approved T1 downgrade rule; protects R11)_

##### Dataset and Artifact Persistence

- **keeps the initial UTC anchor on reconciliation** — GIVEN a dataset created on UTC date D WHEN it is loaded/reconciled on D+1 THEN its anchor remains D _(verifies R7, R10)_
- **constrains stable keys by target** — GIVEN an artifact key `founder-01` for target A WHEN inserted again for target A THEN the unique constraint rejects it, while the same key for target B is allowed _(verifies R2, R10)_
- **serializes concurrent operations for one target** — GIVEN two sessions reconciling the same target WHEN both acquire the target lock THEN only one holds it at a time and unique artifact ownership remains intact _(verifies R10; ARCH forward-stress scenario)_

### Implementation Notes

- **Module(s):** `app.operations.demo_seed` owns the ledger; it does not own feature records.
- **Pattern reference:** Follow SQLAlchemy model/repository conventions in `apps/api/app/modules/launches/models.py` and `apps/api/app/modules/launches/repository.py`; migration style in `apps/api/alembic/versions/0016_votes_and_daily_rankings.py`.
- **Key decisions:** One dataset row per target; artifact key unique within target; first-attempt date anchor remains fixed; ledger records survive cleanup. The downgrade guard was approved during task planning because deleting ownership while leaving domain data makes later cleanup unsafe.
- **Libraries:** Existing SQLAlchemy 2 async, PostgreSQL, and Alembic stack; no new dependency.
- **High-risk callouts:** Keep migration additive and do not add seed marker columns to accounts/products. Use a target-scoped advisory lock plus database uniqueness as the concurrency backstop.

### Scope Boundaries

- Do NOT create or mutate auth, profile, product, launch, or notification records in this task.
- Do NOT add any HTTP endpoint or Compose service.
- Only implement operations-owned persistence and migration behavior.

### Files Expected

**New files:**
- `apps/api/app/operations/__init__.py` (operations package marker)
- `apps/api/app/operations/demo_seed/__init__.py` (seed package marker)
- `apps/api/app/operations/demo_seed/models.py` (dataset/artifact mappings)
- `apps/api/app/operations/demo_seed/repository.py` (target lock and stable-key persistence)
- `apps/api/app/operations/demo_seed/tests/test_persistence.py` (PostgreSQL/migration coverage)
- `apps/api/alembic/versions/0017_demo_seed_ownership.py` (additive ledger schema)

**Modified files:**
- `tests/integration/test_vote_schema.py` (advance the expected migration head and include the additive ownership tables)

**Must NOT modify:**
- `apps/api/app/modules/auth/models.py`, `apps/api/app/modules/users/models.py`, and `apps/api/app/modules/products/models.py` (ledger ownership must not add markers to feature tables)
- Existing Alembic revisions (already-shared migration history)
- `scripts/deploy_production.sh` (seeding is not part of deployment)

---

## Task T2: Provision verified demo accounts through auth

> **Status:** done
> **Verification:** tdd
> **Effort:** s
> **Priority:** high
> **Depends on:** T1
> **Satisfies REQs:** R3, R5, R10, N1
> **Footprint slice:** New auth-owned demo account provisioning service and tests; existing audited staff-role service is reused.
> **High-risk areas touched:** Auth and staff audit (medium).

### Description

Add an internal auth-owned operation to create verified fictional accounts from stable identities and supplied random passwords. It hashes passwords with the existing Argon2id helper and skips verification challenges and outbound email; reviewer access is applied through the existing audited staff-management service, with no admin creation.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/auth/tests/test_provisioning.py`
- Existing regression coverage: `apps/api/app/modules/auth/tests/test_registration.py` and `test_staff.py` (do not modify unless a test change is necessary and separately approved).

#### Test Scenarios

##### Demo Account Provisioning

- **creates a verified account without email side effects** — GIVEN a new fictional identity and generated password WHEN auth provisioning runs THEN the account is verified, the stored value is an Argon2id hash, and no verification challenge or email outbox event exists _(verifies R3, R5, N1)_
- **does not change an already owned account on retry** — GIVEN an account already proven seed-owned by the operations caller WHEN provisioning is retried THEN its password hash, verification time, and role remain unchanged _(verifies R5, R10)_
- **rejects an unowned identity collision** — GIVEN an account with the planned email but no seed ownership WHEN provisioning is attempted THEN the operation reports a safe conflict and leaves the account unchanged _(verifies R2; REQ collision edge case)_

##### Reviewer Role and Regression Guard

- **grants reviewer through audited staff management** — GIVEN a verified seed-owned member WHEN the operator grants reviewer through `StaffManagementService.set_role` THEN role is `reviewer`, an `AccountAdminAction` records the operator actor, and role is never `admin` _(verifies R5)_
- **rejects elevation of an unverified account** — GIVEN an unverified account WHEN reviewer role is requested THEN staff management rejects the change without an audit entry or role mutation _(guards existing auth rule)_
- **preserves public registration verification flow** — GIVEN a normal public registration WHEN `RegistrationService.register` runs THEN its existing verification challenge and email request behavior remains intact _(guards ARCH backward-regression risk for `apps/api/app/modules/auth/service.py`)_

### Implementation Notes

- **Module(s):** `app.modules.auth` owns account creation, verification state, password hashing, and role audit.
- **Pattern reference:** Follow `apps/api/app/modules/auth/service.py`, `repository.py`, and `staff.py`; reuse the Argon2id password helper rather than duplicating it.
- **Key decisions:** Provisioning is internal and does not use the public registration transport. The operations layer checks the ownership ledger before reusing an account; auth does not import the operations repository.
- **Libraries:** Existing auth, Argon2id, SQLAlchemy, and pytest dependencies only.
- **High-risk callouts:** Never weaken the normal registration path or make a demo account admin. The tests assert both the suppressed seed flow and unchanged public registration behavior.

### Scope Boundaries

- Do NOT generate/print credentials here; password values are supplied by the operations command and later captured by the host wrapper.
- Do NOT add public auth routes, alter signup, or change the verification/email worker.
- Only implement auth-owned verified account provisioning; reuse existing staff auditing.

### Files Expected

**New files:**
- `apps/api/app/modules/auth/provisioning.py` (operator-only account provisioning interface)
- `apps/api/app/modules/auth/tests/test_provisioning.py` (hashing, side effects, collision, role audit)

**Modified files:**
- None

**Must NOT modify:**
- `apps/api/app/modules/auth/service.py` (public registration and verification behavior; regression covered above)
- `apps/worker/worker.py` (transactional email worker remains enabled and unchanged)
- Auth public routes or generated API contracts

---

## Task T3: Publish demo profiles with validated synthetic photos

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T1, T2
> **Satisfies REQs:** R4, R10, N2
> **Footprint slice:** Users-owned demo profile/photo provisioning method and focused tests.
> **High-risk areas touched:** Users/profile media (medium); storage validation (medium).

### Description

Add a narrow users-owned provisioning operation that accepts a verified demo account and synthetic photo bytes, validates/finalizes them through the existing private storage path, and publishes a complete public profile. Stable seed ownership is supplied by the operations layer; the users module remains responsible for profile completeness, photo ownership, and visibility.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/users/tests/test_provisioning.py`
- Existing profile regression coverage: `apps/api/app/modules/users/tests/test_profile.py`.

#### Test Scenarios

##### Profile and Photo Provisioning

- **publishes a complete profile with validated media** — GIVEN a verified account and valid synthetic photo bytes WHEN provisioning runs THEN storage contains a cleaned private photo and the profile is public with display name, bio, links, and photo key _(verifies R4, N2)_
- **rejects malformed or unsupported photos** — GIVEN invalid, oversized, or unsupported image bytes WHEN provisioning runs THEN no public profile points at them and the operation returns a safe validation failure _(verifies R4, N3)_
- **rejects another account's photo metadata** — GIVEN a clean photo owned by account A WHEN account B tries to publish it THEN the profile/photo association is rejected _(verifies R4, N2)_
- **reconciles an already owned profile without duplicates** — GIVEN a ledger-owned profile with validated photo and links WHEN the same seed fixture is retried THEN it does not create a second profile, link set, or photo upload _(verifies R10)_
- **preserves ordinary profile publication checks** — GIVEN a normal profile command WHEN the existing profile service publishes it THEN verified-account, completeness, and validated-photo checks remain required _(guards ARCH backward-regression risk for `apps/api/app/shared/storage/objects.py` and existing profile behavior)_

### Implementation Notes

- **Module(s):** `app.modules.users` owns profile lifecycle and photo association; `app.operations.demo_seed` supplies bytes and stable identity.
- **Pattern reference:** `apps/api/app/modules/users/service.py`, `repository.py`, and `apps/api/app/shared/storage/objects.py`.
- **Key decisions:** Do not insert `Profile` or `PhotoUpload` rows from the operations package. Use private storage validation/finalization and existing publication rules.
- **Libraries:** Existing Pillow/S3 storage stack and pytest; no new dependency.
- **High-risk callouts:** A demo-only shortcut must not allow unchecked media or bypass account/photo ownership. Invalid-media and cross-owner cases cover this risk.

### Scope Boundaries

- Do NOT create product logos/screenshots in this task.
- Do NOT expose photo bytes or object keys publicly beyond existing profile behavior.
- Only implement verified-account profile provisioning through the users-owned service.

### Files Expected

**New files:**
- `apps/api/app/modules/users/tests/test_provisioning.py` (profile/photo provisioning and privacy checks)

**Modified files:**
- `apps/api/app/modules/users/service.py` (narrow operator provisioning operation)

**Must NOT modify:**
- `apps/api/app/shared/storage/objects.py` (shared validation and private-storage behavior; covered by regression scenarios)
- Auth repositories/models or product media models (no cross-feature persistence)

---

## Task T4: Suppress email for seed review notifications

> **Status:** done
> **Verification:** tdd
> **Effort:** s
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R9, N1
> **Footprint slice:** Notification service delivery policy for review and launch notices plus regression tests.
> **High-risk areas touched:** Notifications/email outbox (high).

### Description

Add an explicit notification-service policy that seed composition can use to persist review inbox notifications and live-change events without creating review email-request events. Preserve the current email-enabled default and use the existing per-channel launch preferences to keep launch notices in-app-only for demo accounts.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/notifications/tests/test_service.py`
- `apps/api/app/modules/notifications/tests/test_launch_events.py` or `test_launch_preferences.py`

#### Test Scenarios

##### Review Notice Delivery

- **keeps regular review delivery unchanged** — GIVEN default `NotificationService` WHEN a review outcome is recorded THEN inbox, review-email request, and notification-change events are persisted _(guards ARCH backward-regression risk for `apps/worker/worker.py`; verifies current behavior)_
- **suppresses only email for seed review notices** — GIVEN seed-configured in-app-only `NotificationService` WHEN a review outcome is recorded THEN the inbox and notification-change event exist and no email-request event exists _(verifies R9, N1)_

##### Launch Channel Preferences

- **keeps launch notice in-app with email disabled** — GIVEN in-site enabled and email disabled for a launch channel WHEN the launch notice is recorded THEN the inbox and live-change event exist but no email-request event exists _(verifies R9, N1)_
- **omits launch notice when both channels are disabled** — GIVEN both launch channels disabled WHEN the notice is recorded THEN no inbox item or dispatch event is created _(verifies existing preference semantics)_

### Implementation Notes

- **Module(s):** `app.modules.notifications` owns notification records and dispatch intents.
- **Pattern reference:** `apps/api/app/modules/notifications/service.py` and its existing `test_service.py`; event dispatch contract in `apps/api/app/shared/events/tests/test_review_dispatch.py`.
- **Key decisions:** Seed-specific email suppression is explicit and defaults off only in the seed composition; normal users and production reviews keep current behavior. Do not disable the worker or provider credentials.
- **Libraries:** Existing notification/outbox/pytest stack only.
- **High-risk callouts:** Production worker consumes due email events. Assert exact event types for seed and default composition; do not change worker handling.

### Scope Boundaries

- Do NOT change notification worker, dispatcher, Resend/SMTP config, or default user preferences.
- Do NOT suppress in-app inbox or notification-change events.
- Only add the explicit notification-service behavior needed for this seed operation.

### Files Expected

**New files:**
- None

**Modified files:**
- `apps/api/app/modules/notifications/service.py` (explicit email suppression policy)
- `apps/api/app/modules/notifications/tests/test_service.py` (default vs seed policy)
- `apps/api/app/modules/notifications/tests/test_launch_events.py` or `test_launch_preferences.py` (channel behavior)

**Must NOT modify:**
- `apps/worker/worker.py` (email worker stays active; tested through unchanged event contracts)
- `apps/api/app/shared/events/dispatcher.py` and its event names/payloads
- `apps/api/app/modules/auth/service.py` (demo account email suppression is isolated in auth provisioning)

---

## Task T5: Seed private product lifecycle examples

> **Status:** done
> **Verification:** tdd
> **Effort:** l
> **Priority:** high
> **Depends on:** T1, T2, T3, T4
> **Satisfies REQs:** R8, R9, R10, N2
> **Footprint slice:** Operations fixture manifest and orchestration for draft, submitted, changes-requested, rejected, approved-unscheduled, and scheduled products.
> **High-risk areas touched:** Products/review (high); notifications/email outbox (high); launches (high for the scheduled example).

### Description

Compose the existing auth, users, product, review, launch-booking, and notification services to create one private example in each agreed non-launched workflow state. Use real submission/review decisions and audit records, keep every item private, and make reruns reconcile the same seed keys without duplicate products, submissions, decisions, or notifications.

### Test Plan

#### Test File(s)
- `apps/api/app/operations/demo_seed/tests/test_private_products.py`

#### Test Scenarios

##### Private Product Lifecycle

- **keeps a complete draft private** — GIVEN a draft with validated logo, screenshot, and topics WHEN public catalog/search/detail reads run THEN the draft is absent _(verifies R8, N2)_
- **shows the submitted example only in the reviewer queue** — GIVEN a complete submitted example WHEN the reviewer queue is read THEN its pending submission is visible to staff and no public read exposes it _(verifies R8, N2)_
- **records changes-requested and rejection decisions** — GIVEN the two corresponding submitted examples WHEN the seeded reviewer decides them through `ProductService.decide_review` THEN decisions, feedback, and submission states are persisted and both products remain private _(verifies R8, R9, N2)_
- **keeps approved-unscheduled example private and unbooked** — GIVEN the approved example WHEN the owner workspace is read THEN it is approved, has a real approved review decision, and has no launch booking or public presence _(verifies R8, N2)_
- **books a private scheduled example into the future** — GIVEN an approved product WHEN the normal launch booking service books a valid future UTC date THEN it is scheduled with an active booking but remains absent from public reads _(verifies R8, N2)_
- **creates review inbox notices without email** — GIVEN the seeded review decisions WHEN their outbox events are inspected THEN founders have in-app notices and no review email-request events exist _(verifies R9, N1)_
- **repairs private examples idempotently** — GIVEN all six seed keys have been created WHEN the fixture set is rerun THEN there are no duplicate products, submissions, decisions, bookings, or notices _(verifies R10)_

### Implementation Notes

- **Module(s):** `app.operations.demo_seed` coordinates; products/launches/notifications keep their own rules and persistence.
- **Pattern reference:** Existing command composition in `apps/api/app/modules/products/service.py`, review tests in `apps/api/app/modules/products/tests/test_review_service.py`, and booking tests in `apps/api/app/modules/launches/tests/test_service.py`.
- **Key decisions:** Use stable fixture keys and ledger ownership. Use normal product submission and review services; only the seed composition gets in-app-only notice behavior. Review decisions are retained and make the corresponding examples ineligible for cleanup.
- **Libraries:** Existing async SQLAlchemy, product/launch/notification services, private storage, and pytest only.
- **High-risk callouts:** All six products remain private; only the reviewer queue sees the pending example. Tests check public reads and actual review audit rather than only status strings.

### Scope Boundaries

- Do NOT create the 20 public launched products in this task; that is T6.
- Do NOT synthesize product state with direct writes or bypass private-media validation.
- Do NOT add new review/launch public contracts or create vote history.

### Files Expected

**New files:**
- `apps/api/app/operations/demo_seed/fixtures.py` (stable synthetic identities/content/topic and asset manifest)
- `apps/api/app/operations/demo_seed/tests/test_private_products.py` (PostgreSQL-backed lifecycle and privacy coverage)

**Modified files:**
- `apps/api/app/operations/demo_seed/service.py` (orchestrate the six private product examples)

**Must NOT modify:**
- `apps/api/app/modules/products/service.py` and product public read contracts (use existing service behavior; privacy/audit guarded above)
- `apps/api/app/modules/launches/service.py` and `apps/worker/worker.py` (use existing schedule/publication and event handling)
- Product, booking, or notification repositories directly from the operations package

---

## Task T6: Seed public launches across the UTC archive window

> **Status:** done
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T1, T2, T3, T4, T5
> **Satisfies REQs:** R6, R7, R9, R10, N2
> **Footprint slice:** Extend operations fixtures/orchestration for at least 20 complete launched products and historical UTC publication.
> **High-risk areas touched:** Products/review (high); launches/archives (high); notifications/email outbox (high); private storage (medium).

### Description

Create at least 20 complete fictional launched products, one per demo founder, using the target ledger's fixed UTC anchor and the existing review, booking, and publication services. Use an injected seed clock to reach the anchor day and prior seven dates without relaxing public date rules; preserve product IDs/dates on reruns and create no vote/rank data.

### Test Plan

#### Test File(s)
- `apps/api/app/operations/demo_seed/tests/test_public_launches.py`

#### Test Scenarios

##### Public Catalog and Historical Publication

- **creates one complete public launch per founder** — GIVEN 20 ledger-owned founders and valid fixtures WHEN public-launch seeding completes THEN every founder owns a distinct launched product with summary, description, fictional website, validated logo/screenshot, and topics _(verifies R6)_
- **covers anchor day and preceding seven dates** — GIVEN the ledger anchor D WHEN launch fixtures are assigned THEN products cover D and every date D-1 through D-7 with at least one on D and one archived date _(verifies R7)_
- **uses real booking and publication history** — GIVEN each approved product WHEN seed time books and publishes it through domain services THEN booking outcome, launched timestamp, version, and normal outbox events are present _(verifies R6, R7, N2)_
- **returns only launched products publicly** — GIVEN private lifecycle examples and launched seed products WHEN public list/search/detail reads run THEN only launched products are exposed _(verifies R6, R8, N2)_
- **does not move or duplicate launches on rerun** — GIVEN launched fixtures on their first dates WHEN seeding is rerun on a later UTC day THEN IDs/dates are preserved and record counts do not increase _(verifies R7, R10, N2)_
- **keeps votes/ranks and email out of the seed** — GIVEN the seed's publication events WHEN votes, rank snapshots, and outbox email types are inspected THEN no vote/rank rows and no launch email-request events exist, while in-app live notices remain _(verifies R9, N1 and vote exclusion)_

### Implementation Notes

- **Module(s):** `app.operations.demo_seed` composes `ProductService` and `LaunchBookingService`; the existing `votes` feature is not invoked.
- **Pattern reference:** `apps/api/app/modules/launches/service.py`, `apps/api/app/modules/products/service.py`, and `apps/worker/worker.py` publication flow/tests.
- **Key decisions:** Use the persisted first-attempt UTC anchor; inject time only into the seed composition; normal booking eligibility and product transitions remain unchanged. Seeded launch email preferences are off.
- **Libraries:** Existing service stack and test dependencies only.
- **High-risk callouts:** Published archives cannot be cleaned or shifted. Verify all content, fixture identity, media, and dates before publication; a later correction requires separate takedown/correction capability.

### Scope Boundaries

- Do NOT add or seed votes, ranking snapshots, or vote notifications.
- Do NOT edit public discovery APIs/UI or relax launch booking policy.
- Do NOT mutate launched records during reruns or cleanup.

### Files Expected

**New files:**
- `apps/api/app/operations/demo_seed/tests/test_public_launches.py` (publication, dates, privacy, and idempotency)

**Modified files:**
- `apps/api/app/operations/demo_seed/service.py` (seed public launch timeline)
- `apps/api/app/operations/demo_seed/fixtures.py` (20+ public product fixtures and date assignment)

**Must NOT modify:**
- `apps/api/app/modules/products/service.py`, `apps/api/app/modules/launches/service.py`, and their public contracts (normal behavior is reused and regression tested)
- `apps/worker/worker.py` (email and publication worker behavior stays active and unchanged)
- Vote or rank models/repositories (no vote history is required)

---

## Task T7: Add safe operator commands and bounded cleanup

> **Status:** in progress
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T1, T2, T3, T4, T5, T6
> **Satisfies REQs:** R1, R2, R5, R10, R11, R12, N1, N3
> **Footprint slice:** Seed CLI, target gate, collision reporting, cleanup, explicit credential rotation, and secret-free summary.
> **High-risk areas touched:** Auth/staff audit (medium); products/review (high); Compose/VM operations (high).

### Description

Expose `seed`, `cleanup`, and explicit `rotate-credentials` operations through the Python module CLI. Reject unsafe production targets before dependency access; for the designated VM require the root-owned marker, exact target ID, and per-run no-customer-data acknowledgement. Cleanup must prove ledger ownership and absence of review decisions, and reporting must not reveal secrets or private/unrelated records.

### Test Plan

#### Test File(s)
- `apps/api/app/operations/demo_seed/tests/test_cli.py`
- `apps/api/app/operations/demo_seed/tests/test_cleanup.py`

#### Test Scenarios

##### Target Gate and Collision Safety

- **accepts the fixed development target** — GIVEN local development settings WHEN the CLI selects `local-development` THEN it proceeds to dependency checks _(verifies R1)_
- **rejects production before database/storage access** — GIVEN production settings without an approved marker WHEN any mutating command runs THEN it exits before opening database or storage clients _(verifies R1, N3; REQ unsafe-target edge case)_
- **requires the designated VM marker, matching target, and attestation** — GIVEN production mode WHEN marker is absent, not root-owned, unreadable, mismatched, or `--confirm-no-customer-data` is absent THEN the command fails closed; with all conditions satisfied it accepts only that target _(verifies R1, N3)_
- **aborts on an unowned identity collision** — GIVEN a matching account/product key absent from the ledger WHEN seed preflight runs THEN no domain writes occur and the diagnostic names only a safe fixture key _(verifies R2; REQ collision edge case)_

##### Cleanup, Credentials, and Reporting

- **deletes only a seed-owned never-reviewed draft** — GIVEN a ledger-owned draft WHEN cleanup runs THEN the product is deleted through product-owned behavior and unrelated products are unchanged _(verifies R11)_
- **withdraws and deletes a never-reviewed pending submission** — GIVEN a ledger-owned submitted product with no review decision WHEN cleanup runs THEN the submission is withdrawn through `ProductService` before the draft deletion path _(verifies R11)_
- **retains any reviewed or launched product** — GIVEN seed-owned products with review decisions or launched/scheduled state WHEN cleanup runs THEN product, audit, bookings, and archives remain unchanged _(verifies R11, N2)_
- **keeps normal credentials and explicitly scopes rotation** — GIVEN an ordinary rerun or explicit rotation selection WHEN the credential operation runs THEN normal seed preserves existing password hashes and rotation affects only selected ledger-owned accounts _(verifies R5, R10)_
- **keeps diagnostics secret-free** — GIVEN seed, cleanup, or rotation success/failure WHEN stdout/stderr summaries are captured THEN logs contain no passwords, private product copy, object keys/secrets, or unrelated identities _(verifies R12, N1)_

### Implementation Notes

- **Module(s):** CLI in `app.operations.demo_seed`; domain operations remain with auth/users/products/launches/notifications.
- **Pattern reference:** Safe diagnostics in `apps/api/app/bootstrap.py`; target marker and lifecycle decisions in ARCH A1–A9; deletion gate in `apps/api/app/modules/products/service.py`.
- **Key decisions:** Gate production before opening dependencies; compare root-owned marker and explicit ID; cleanup uses service-level withdraw/delete paths and ledger ownership; normal seed never rotates passwords.
- **Libraries:** Existing argparse/asyncio, settings, database, and pytest libraries; no new dependency.
- **High-risk callouts:** A wrong target or cleanup scope can change public data. Tests use injected settings/files/dependencies to prove the failure path occurs before writes.

### Scope Boundaries

- Do NOT add any HTTP/admin route or invoke commands from GitHub Actions/deployment.
- Do NOT alter `scripts/deploy_production.sh` or Compose files here; T8 wires the command.
- Do NOT delete accounts, profiles, reviewed products, bookings, audit, or launch archives.

### Files Expected

**New files:**
- `apps/api/app/operations/demo_seed/cli.py` (seed/cleanup/rotation commands and target gate)
- `apps/api/app/operations/demo_seed/tests/test_cli.py` (target checks, collision, safe output)
- `apps/api/app/operations/demo_seed/tests/test_cleanup.py` (ownership and retention behavior)

**Modified files:**
- `apps/api/app/operations/demo_seed/service.py` (cleanup, rotation coordination, and safe summaries)

**Must NOT modify:**
- `scripts/deploy_production.sh` and GitHub deployment workflow (seeding is a manual operator action)
- `apps/worker/worker.py` and mail-provider configuration
- Product/launch repositories directly from operations code

---

## Task T8: Wire Compose operation, private credentials, assets, and documentation

> **Status:** not started
> **Verification:** checklist
> **Effort:** l
> **Priority:** critical
> **Depends on:** T1, T2, T3, T4, T5, T6, T7
> **Satisfies REQs:** R1, R4, R5, R6, R9, R12, N1, N3
> **Footprint slice:** Local/production Compose ops services, module entry point, host wrapper and credentials handling, fixture assets, ignore rules, and operator guide.
> **High-risk areas touched:** Products/media (medium); notification/email outbox (high); Compose/VM operations (high).

### Description

Make the approved one-shot command usable in local development and on the designated VM without exposing an HTTP endpoint or tying it to deployment. The wrapper captures credential output into a private host file, reruns reuse that file through stdin, and the fixture bundle and operator guide make the full demo reproducible.

### Verification Checklist

- **Shell wrapper syntax and lint** — run `bash -n scripts/seed_demo.sh` and `shellcheck scripts/seed_demo.sh`; expected: both exit successfully.
- **Local Compose service** — render `docker compose --profile ops config --format json`; expected: demo seed service is one-shot under `ops`, uses local PostgreSQL/MinIO settings, has no published ports, restart is disabled, and logging driver is `none`.
- **Production Compose service** — on the designated VM, render production Compose using the installed release environment; expected: pinned API image, R2/API env, backend-only network, read-only root-owned marker, no ports, `ops` profile, restart disabled, and logging driver `none`; default Compose startup/deployment does not run it.
- **Host credential handling** — run wrapper in a disposable local demo target; expected: generated credentials are written once to a host file with mode `0600`, the wrapper refuses to overwrite it, reruns feed it through stdin, and no password appears in terminal summaries or retained Docker logs.
- **Fixture bundle audit** — use fixture manifest/count and existing image-validation tests; expected: 20 distinct synthetic founder avatars and unique fictional logo/screenshot files for all 26 product examples, accepted by current image validators, with no real identities or third-party product sites. Asset creation uses the configured Higgsfield MCP per `AGENTS.md`.
- **Operator guide and local demo** — follow `docs/DEMO_DATA_SEEDING.md` on local Compose; expected: the guide explains credentials, target selection, cleanup limits, and all required feature records are visible; it explicitly requires a human VM/customer-data check and states seeding is never part of deployment.

### Implementation Notes

- **Module(s):** Compose host wrapper, `app.operations.demo_seed` entry point, and operator docs.
- **Pattern reference:** Existing `compose.yaml`, `compose.production.yaml`, `scripts/deploy_production.sh`, and `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md`.
- **Key decisions:** Use a local `ops` profile and production pinned image; mount VM marker read-only; publish no ports; set logging driver `none`; host wrapper uses `umask 077`, atomic file creation, no overwrite, and existing-file stdin on rerun. Never invoke the seed from the deployment controller/workflow.
- **Libraries:** Docker Compose, Bash, ShellCheck; no new runtime dependency.
- **High-risk callouts:** Production Compose points at the production-configured VM. Render/configure it without running the seed; only an operator may run after marker and no-customer-data checks.

### Scope Boundaries

- Do NOT run the seed on the VM or against any production-configured database as part of implementation or deployment automation.
- Do NOT add production ports, alter R2 credentials, or modify the deploy controller/workflow.
- Do NOT substitute remote/third-party assets or generate images without the configured Higgsfield MCP; if it is unavailable, stop the asset subtask and request access.
- Only wire local/approved-VM Compose operation and the explicitly approved fixtures/docs.

### Files Expected

**New files:**
- `scripts/seed_demo.sh` (host-side command and private credential capture/reuse)
- `apps/api/app/operations/demo_seed/__main__.py` (module command entry point)
- `apps/api/app/operations/demo_seed/assets/` (20 avatars and unique product fixture media, produced with Higgsfield)
- `docs/DEMO_DATA_SEEDING.md` (local and VM operator steps, guard, credentials, cleanup limits)

**Modified files:**
- `compose.yaml` (local one-shot `ops` service using MinIO/local database)
- `compose.production.yaml` (pinned-image one-shot `ops` service with read-only marker, backend network, and no host ports)
- `.gitignore` (exclude local private credential output)

**Must NOT modify:**
- `scripts/deploy_production.sh` or `.github/workflows/*` (seeding is never automatic)
- `apps/worker/worker.py`, settings, or provider credentials (worker stays active; email suppression is seed-specific)
- `.env.example` (unrelated working-tree edit; do not stage or overwrite it)

---

_Generated from `specs/architecture/ARCH-demo-data-seeding.md` and `specs/requirements/REQ-demo-data-seeding.md`._
_Next step: `/implement T1 from: specs/architecture/ARCH-demo-data-seeding.md`_
