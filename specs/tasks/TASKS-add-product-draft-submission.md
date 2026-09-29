# Tasks

## Task T1: Add Product and Authorization Schema

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R1, R7, R10, R13, R16, N2, N3
> **Footprint slice:** New product models and 0005 migration; modified auth models; schema-readiness regression guard.
> **High-risk areas touched:** Auth/session and operator access; product transactions and queue; database/contract pipeline and release gate.

### Description

Add additive account role/suspension/audit fields and product, submission-period, topic, association, and asset tables. Database constraints and indexes establish the private-state, uniqueness, and queue foundations without changing prior migrations.

### Test Plan

#### Test File(s)
- tests/integration/test_product_schema.py
- apps/api/app/modules/products/tests/test_models.py

#### Test Scenarios

##### Migration and Constraints

- **upgrades from current head** — GIVEN revision 0004 WHEN preparation runs THEN revision 0005 applies and existing account/profile rows remain readable _(verifies N3)_.
- **defaults to member access** — GIVEN an existing or new account WHEN 0005 is applied THEN role is member and suspension is null _(verifies R1, N2)_.
- **permits one active submission period** — GIVEN a product with a pending period WHEN a second pending period is inserted THEN the database rejects it, while historical withdrawn periods remain valid _(verifies R10, R13)_.
- **enforces topic and media row constraints** — GIVEN equivalent topic keys or invalid asset type/size/position WHEN persisted THEN unique/check constraints reject the invalid row _(verifies R7, N3)_.
- **indexes bounded reads** — GIVEN the new tables WHEN indexes are inspected THEN founder/status, pending queue order, website key, and topic key access paths exist _(verifies R13, R16)_.

##### Regression Guard

- **keeps exact-head readiness** — GIVEN a 0004 database and a 0005 binary WHEN compatibility is checked THEN it fails until migration; the dynamic head check remains unchanged _(guards backward-regression risk for apps/api/app/shared/db/database.py and apps/api/alembic/env.py)_.

### Implementation Notes

- **Module(s):** auth models, products models, Alembic.
- **Pattern reference:** apps/api/app/modules/users/models.py and apps/api/alembic/versions/0002_member_identity_profiles.py.
- **Key decisions:** A2, A3, A4, A5, A10; use additive defaults, partial unique pending index, and keyset queue index.
- **Libraries:** SQLAlchemy 2, Alembic, PostgreSQL, pytest.
- **High-risk callouts:** Schema and old binary must not be assumed compatible merely because columns are additive; the readiness scenario checks the exact revision.

### Scope Boundaries

- Do NOT rewrite revisions 0001–0004 or add launch/reviewer-decision tables.
- Only add schema needed for private drafts, current pending periods, staff status, and audit.

### Files Expected

**New files:**
- apps/api/app/modules/products/models.py (product-owned mappings).
- apps/api/alembic/versions/0005_product_drafts_submission.py (additive schema).
- tests/integration/test_product_schema.py; apps/api/app/modules/products/tests/test_models.py (verification).

**Modified files:**
- apps/api/app/modules/auth/models.py (role, suspension, audit mapping).

**Must NOT modify:**
- apps/api/app/shared/db/database.py; apps/api/alembic/env.py (exact-head behavior is a regression guard).
- Existing migration revisions (shared history).

---

## Task T2: Resolve Live Role and Suspension Through Auth

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R1, R9, R14, N2
> **Footprint slice:** Modified auth repository, sessions, policies; new named auth access service.
> **High-risk areas touched:** Auth/session and operator access; product transactions and queue.

### Description

Expose current account verification, role, and suspension through an auth-owned interface that products can call without importing an auth repository. Keep authorization fresh for active sessions and provide a row lock for quota-changing product commands.

### Test Plan

#### Test File(s)
- apps/api/app/modules/auth/tests/test_sessions.py
- apps/api/app/modules/auth/tests/test_policies.py
- apps/api/app/modules/auth/tests/test_staff.py

#### Test Scenarios

##### Live Authorization

- **reflects role changes on an existing session** — GIVEN an active member session WHEN an operator changes the account role THEN the next resolution sees the new role _(verifies R14, N2)_.
- **requires verified unsuspended staff** — GIVEN member, unverified reviewer, suspended reviewer, and verified active reviewer WHEN queue policy runs THEN only the last is allowed _(verifies R14, N2)_.
- **applies suspension exceptions** — GIVEN a suspended founder WHEN product policies are evaluated THEN create/edit/upload/submit/delete are denied but withdrawal remains allowed _(verifies R9, R14)_.
- **provides account lock and batch flags** — GIVEN simultaneous founder commands or a page of founder IDs WHEN named access is used THEN one account lock serializes changes and flags are fetched in one bounded batch _(verifies R16, N2)_.

##### Regression Guard

- **preserves session authentication** — GIVEN an existing valid, expired, or revoked session WHEN resolved THEN previous validity and CSRF behavior is unchanged _(guards backward-regression risk for apps/api/app/modules/auth/tests/test_sessions.py)_.

### Implementation Notes

- **Module(s):** auth only; products consume a named interface later.
- **Pattern reference:** apps/api/app/modules/auth/sessions.py, repository.py, policies.py.
- **Key decisions:** A1, A2, A4; role alone never grants draft access and suspension need not revoke a session to take effect in product policy.
- **Libraries:** SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Recheck PostgreSQL state rather than trusting a login-time claim; keep lock ordering consistent with session resolution.

### Scope Boundaries

- Do NOT add a public staff-management endpoint or change password/session lifetime rules.
- Only establish current auth state and named access needed by product policies and quotas.

### Files Expected

**New files:**
- apps/api/app/modules/auth/staff.py (named account-state and batch access interface).
- apps/api/app/modules/auth/tests/test_policies.py; apps/api/app/modules/auth/tests/test_staff.py (verification).

**Modified files:**
- apps/api/app/modules/auth/repository.py (current/locked/batched account queries).
- apps/api/app/modules/auth/sessions.py (role/suspension in live member context).
- apps/api/app/modules/auth/policies.py (named staff/suspension checks).

**Must NOT modify:**
- apps/api/app/modules/auth/tests/test_sessions.py (existing session regression suite is run unchanged).
- apps/api/app/modules/users/service.py (profile behavior is not the product authorization boundary).
- apps/api/app/shared/db/database.py (readiness unchanged).

---

## Task T3: Provision Staff and Suspension With an Audit Trail

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** T2
> **Satisfies REQs:** R14, N2
> **Footprint slice:** New operator command; auth staff service; modified auth self-session schemas/routes.
> **High-risk areas touched:** Auth/session and operator access; database/contract pipeline and release gate.

### Description

Provide a restricted operator command for role grants/revocations and suspension/resumption, recording each action durably. Add self-visible role and suspension to login/session contracts so the UI can route appropriately without granting privilege through client state.

### Test Plan

#### Test File(s)
- apps/api/app/modules/auth/tests/test_staff.py
- apps/api/app/modules/auth/tests/test_routes.py
- tests/integration/test_operator_accounts.py

#### Test Scenarios

##### Operator Actions

- **audits every privilege change** — GIVEN a verified account WHEN the operator grants/revokes reviewer/admin or suspends/resumes THEN before/after state and operator actor are recorded atomically _(verifies R14, N2)_.
- **does not expose public mutation** — GIVEN an ordinary browser session WHEN it probes auth routes THEN no role/suspension management route exists _(verifies N2)_.
- **shows current self-state** — GIVEN an account whose role or suspension changed WHEN login/session is requested THEN the response has live role/suspension without trusting a client claim _(verifies R14)_.
- **keeps suspended submission visible to staff** — GIVEN a pending product from a newly suspended founder WHEN account state is queried THEN the suspended flag remains available for staff projection _(verifies R14)_.

##### Regression Guard

- **preserves identity responses** — GIVEN registration, verification, password reset, and existing login clients WHEN their routes run THEN generic/security behavior and existing response fields remain valid _(guards backward-regression risk for apps/api/app/modules/auth/tests/* and apps/web/src/identity/*.test.ts*)_.

### Implementation Notes

- **Module(s):** auth and restricted operator script.
- **Pattern reference:** apps/api/app/modules/auth/service.py and routes.py.
- **Key decisions:** A2; operator access is a deployment trust boundary, not an HTTP permission.
- **Libraries:** FastAPI, Pydantic, SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Audit and role mutation must share one transaction; never log credentials or session secrets.

### Scope Boundaries

- Do NOT add staff invitation, self-promotion, admin UI, or product reviewer decisions.
- Only role/suspension operations and self-session disclosure are in scope.

### Files Expected

**New files:**
- scripts/operators/manage_accounts.py (restricted audited command).
- tests/integration/test_operator_accounts.py (operator verification).

**Modified files:**
- apps/api/app/modules/auth/staff.py (audited mutation service).
- apps/api/app/modules/auth/schemas.py; apps/api/app/modules/auth/routes.py (self-session contracts).
- apps/api/app/modules/auth/tests/test_staff.py (operator coverage).

**Must NOT modify:**
- apps/api/app/modules/auth/tests/test_routes.py; test_registration.py; test_recovery.py; test_verification.py (existing behavior is regression-checked unchanged).
- apps/api/app/modules/users/routes.py (profile actions are not staff management).

---

## Task T4: Validate Product Content and Canonical Topics

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T1
> **Satisfies REQs:** R4, R5, R7, R8, R15, N1, N3
> **Footprint slice:** New products schemas, service validation, repository topic/website persistence.
> **High-risk areas touched:** Product transactions and queue; private media/storage.

### Description

Define the optional draft input contract and strict supplied-value validation, plus canonical topic and website keys. Equivalent topic names reuse one database row without revealing another founder's private association.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_validation.py
- apps/api/app/modules/products/tests/test_topics.py

#### Test Scenarios

##### Product Fields

- **accepts incomplete draft** — GIVEN omitted or blank optional fields WHEN a draft is validated THEN it may remain private and incomplete _(verifies R4)_.
- **rejects invalid supplied content** — GIVEN overlong name/pitch/description, multiline pitch, or malformed/non-HTTPS website WHEN supplied THEN field-specific validation rejects it _(verifies R4, R5; REQ edge case)_.
- **requires complete submission fields** — GIVEN whitespace-only or missing required text/site WHEN completeness is checked THEN submission fails without a review entry _(verifies R5, N3)_.

##### Topic and Website Keys

- **reuses equivalent topic under race** — GIVEN two founders entering AI Tools and surrounding-space/case variants WHEN persisted concurrently THEN one canonical topic row exists _(verifies R7; ARCH forward stress-test)_.
- **enforces topic bounds** — GIVEN blank, over-40-character, duplicate, or fourth topic choice WHEN submission topics are validated THEN a field-specific error prevents an invalid selection _(verifies R7; REQ edge case)_.
- **keeps proposals private** — GIVEN another founder's unlaunched topic WHEN topic choices are requested THEN neither its name nor association is returned; typing that name may still reuse its key _(verifies R8, N1)_.
- **canonicalizes exact website link without uniqueness** — GIVEN equivalent scheme/host/default-port forms or a distinct path WHEN keys are built THEN exact equivalents compare equal while distinct paths remain distinct and duplicate URLs are allowed _(verifies R15)_.

### Implementation Notes

- **Module(s):** products schemas, service, repository.
- **Pattern reference:** apps/api/app/modules/users/schemas.py and service.py; database uniqueness in users models.
- **Key decisions:** A5; use trimmed case-folded topic key and indexed exact-link website key.
- **Libraries:** Pydantic, SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Service responses must never reveal another founder's private topic display casing or matching product.

### Scope Boundaries

- Do NOT publish topic proposals or add search/public product reads.
- Only validate/persist fields relevant to private drafts and submission readiness.

### Files Expected

**New files:**
- apps/api/app/modules/products/schemas.py; service.py; repository.py (product boundary and persistence).
- apps/api/app/modules/products/tests/test_validation.py; test_topics.py (RED-first tests).

**Modified files:**
- None.

**Must NOT modify:**
- apps/api/app/modules/users/models.py (profile links remain separate).
- Existing public discovery/search code (not in this slice).

---

## Task T5: Create and Version Private Drafts

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T2, T4
> **Satisfies REQs:** R1, R3, R14, R16, N1, N2, N3, N4
> **Footprint slice:** Products service/repository/policies for creation, owner save, outbox, and draft capacity.
> **High-risk areas touched:** Product transactions and queue; auth/session and operator access.

### Description

Implement private draft creation and versioned saving for signed-in founders, including unverified founders. Lock the owner account for capacity checks and compare expected product version so concurrent requests cannot silently overwrite one another.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_drafts.py
- tests/integration/test_product_drafts.py

#### Test Scenarios

##### Draft Ownership and Versions

- **creates unverified private draft** — GIVEN an unverified signed-in member WHEN creating a draft THEN only that owner can reopen it and it is absent from staff queue _(verifies R1, N1)_.
- **rejects stale edit** — GIVEN two tabs at version 1 WHEN the first saves version 2 and the second saves version 1 THEN the second receives conflict and saved content stays at version 2 _(verifies R3; REQ edge case)_.
- **blocks suspended edits** — GIVEN a suspended founder WHEN creating or saving THEN product policy denies the mutation without changing the row _(verifies R14, N2)_.

##### Capacity and Atomicity

- **holds ten-draft cap under concurrency** — GIVEN nine drafts WHEN two create requests race THEN exactly one succeeds and the other gets a quota error _(verifies R16, N4; ARCH forward stress-test)_.
- **rolls back event with failed save** — GIVEN a persistence failure WHEN create/save runs THEN neither visible state nor its outbox event commits _(verifies N3)_.
- **keeps owner lookup private** — GIVEN a different member or visitor WHEN querying a draft THEN no product identifiers/content are disclosed _(verifies R1, N1)_.

### Implementation Notes

- **Module(s):** products service/repository/policies, named auth access.
- **Pattern reference:** apps/api/app/modules/users/service.py and policies.py; apps/api/app/shared/events/outbox.py.
- **Key decisions:** A1, A3, A4; lock owner for count, then product for edits; PostgreSQL is authoritative.
- **Libraries:** SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Counter checks must be serialized; typed errors distinguish stale version from capacity without exposing private rows.

### Scope Boundaries

- Do NOT implement browser autosave UI here or allow public product reads.
- Only server-side create/save/owner invariants and transactional events.

### Files Expected

**New files:**
- apps/api/app/modules/products/policies.py (named owner/suspension checks).
- apps/api/app/modules/products/tests/test_drafts.py; tests/integration/test_product_drafts.py (verification).

**Modified files:**
- apps/api/app/modules/products/service.py; repository.py (draft lifecycle and quota).

**Must NOT modify:**
- apps/api/app/modules/auth/repository.py (cross-feature access through T2 interface).
- apps/api/app/modules/users/tests/* (profile behavior regression-checked later).

---

## Task T6: Submit, Edit, and Withdraw Submission Periods

> **Status:** done
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T5
> **Satisfies REQs:** R5, R6, R7, R9, R10, R11, R12, R13, R14, R16, N2, N3, N4
> **Footprint slice:** Products service/repository submission-period state machine.
> **High-risk areas touched:** Product transactions and queue; auth/session and operator access.

### Description

Atomically submit only a current, complete draft from a verified unsuspended owner, while making repeat submission idempotent. Preserve the original pending period and queue position on complete edits; close it on explicit withdrawal and create a fresh period on resubmission.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_submissions.py
- tests/integration/test_product_submission.py

#### Test Scenarios

##### Submission and Pending Edit

- **requires current complete verified draft** — GIVEN missing text/media/topic, stale version, unverified or suspended owner WHEN submitting THEN no period is created and the existing draft remains _(verifies R5–R7, R9, N3; REQ edge case)_.
- **deduplicates retry** — GIVEN a successful submit WHEN the same submit is repeated or races another call THEN one pending period remains and the current response is returned _(verifies R10; ARCH forward stress-test)_.
- **enforces three-pending cap** — GIVEN two pending products WHEN two distinct drafts submit concurrently THEN only one additional pending period commits _(verifies R16, N4)_.
- **accepts only complete pending edits** — GIVEN a pending item WHEN a complete version is saved THEN version advances but submitted_at stays; an incomplete edit leaves the saved version untouched _(verifies R11, R13; REQ edge case)_.

##### Withdrawal and Freshness

- **withdraws despite draft cap or suspension** — GIVEN ten drafts or a suspended founder with a pending product WHEN withdrawing THEN its period closes and the product becomes a private draft _(verifies R11, R14, R16; REQ edge case)_.
- **resubmits at queue back** — GIVEN a withdrawn product WHEN it is resubmitted THEN a new submission ID and timestamp appear after older pending entries _(verifies R13)_.
- **invalidates stale review token** — GIVEN a submission ID/version observed before a pending edit or withdrawal WHEN freshness is checked THEN that pair is no longer current; no reviewer decision endpoint is added _(verifies R12 as agreed for this slice)_.

### Implementation Notes

- **Module(s):** products service/repository.
- **Pattern reference:** transaction/version handling in apps/api/app/modules/users/service.py; PostgreSQL partial unique index from T1.
- **Key decisions:** A3, A4; one current period, expected version, founder lock for pending count.
- **Libraries:** SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Every state, topic, asset reference, period, and outbox event must commit together; race outcomes must be singular.

### Scope Boundaries

- Do NOT implement approve/reject/change-request actions or notifications.
- Only submission, complete pending edits, withdrawal, and freshness contract.

### Files Expected

**New files:**
- apps/api/app/modules/products/tests/test_submissions.py; tests/integration/test_product_submission.py (verification).

**Modified files:**
- apps/api/app/modules/products/service.py; repository.py (period transitions and pending cap).

**Must NOT modify:**
- apps/worker/scheduler.py (generic due-work hint unchanged).
- Reviewer workflow modules (not present or in scope).

---

## Task T7: Extend Private Storage for Product Images

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R4, R6, R17, N1, N3
> **Footprint slice:** Shared private-object adapter and provisioning policy for product-scoped keys.
> **High-risk areas touched:** Private media/storage.

### Description

Add bounded product-staging and product-clean object operations to the existing private S3 pattern. Validate actual bytes and strip metadata before a product image becomes clean, while retaining the profile adapter's key guard and local upload behavior.

### Test Plan

#### Test File(s)
- apps/api/app/shared/storage/tests/test_objects.py
- apps/api/app/shared/storage/tests/test_provision.py
- apps/api/app/modules/products/tests/test_storage.py

#### Test Scenarios

##### Product Objects

- **issues bounded upload** — GIVEN supported JPEG/PNG/WebP type and size at most 5 MB WHEN an upload is requested THEN the signed POST permits only its scoped staging key and bounded expiry _(verifies R6, N1)_.
- **validates actual bytes** — GIVEN spoofed MIME, oversized bytes, or malformed image WHEN finalized THEN no clean attached image results; valid bytes are re-encoded without metadata _(verifies R4, R6; REQ edge case)_.
- **contains key access** — GIVEN a profile key, another account/product key, or arbitrary path WHEN product adapter reads/deletes THEN it refuses access _(verifies N1)_.
- **fails safely on S3 outage** — GIVEN storage read/write failure WHEN finalizing THEN a safe error is returned and no product is considered review-ready _(verifies N3; ARCH forward stress-test)_.

##### Regression Guard

- **keeps profile storage working** — GIVEN existing profile upload and cleanup cases WHEN run after policy extension THEN profile prefixes, browser CORS, and private-photo validation still pass _(guards backward-regression risk for apps/api/app/shared/storage/tests/*)_.

### Implementation Notes

- **Module(s):** shared storage adapter with product-scoped operations.
- **Pattern reference:** apps/api/app/shared/storage/objects.py and provision.py.
- **Key decisions:** A7; direct signed upload only, no public GET or client-controlled object key.
- **Libraries:** boto3, Pillow, pytest.
- **High-risk callouts:** The runtime policy must add only product prefixes; profile prefixes and origin handling must remain intact.

### Scope Boundaries

- Do NOT add public bucket ACLs, direct S3 download presigns, or image generation.
- Only private product image upload/validation/object operations.

### Files Expected

**New files:**
- apps/api/app/modules/products/tests/test_storage.py (product-scoped storage tests).

**Modified files:**
- apps/api/app/shared/storage/objects.py; provision.py (bounded product prefix/validation support).
- apps/api/app/shared/storage/tests/test_objects.py; test_provision.py (regression coverage).

**Must NOT modify:**
- apps/api/app/modules/users/models.py; service.py (profile domain remains separate).
- apps/api/app/shared/storage/client.py (no new storage service).

---

## Task T8: Manage Product Asset Intents and Attachments

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T5, T7
> **Satisfies REQs:** R4, R6, R9, N1, N3, N4
> **Footprint slice:** Product asset service/repository, Pydantic contracts, and upload intent/completion routes.
> **High-risk areas touched:** Private media/storage; product transactions and queue.

### Description

Persist owner-scoped upload intents and promote validated images to clean assets before a versioned product edit can attach them. Bound pending intents and enforce one attached logo plus at most ten ordered screenshots.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_assets.py
- apps/api/app/modules/products/tests/test_routes.py

#### Test Scenarios

##### Asset Lifecycle

- **creates scoped intent** — GIVEN an active owner WHEN requesting a supported bounded image upload THEN an expiring asset record and signed staging POST are returned _(verifies R6, N4)_.
- **rejects bad completion** — GIVEN wrong bytes, unsupported format, over-5-MB content, or missing staged object WHEN completing THEN the asset is not clean or attachable _(verifies R4, R6; REQ edge case)_.
- **attaches only clean assets** — GIVEN another owner's asset, a pending/failed asset, two logos, or an eleventh screenshot WHEN saving attachments THEN the update is rejected without changing the saved product _(verifies R6, N1, N3)_.
- **blocks suspended upload** — GIVEN a suspended owner WHEN requesting or completing an intent THEN the action is denied _(verifies R9, N2)_.
- **cleans promotion failures** — GIVEN successful S3 promotion followed by DB failure WHEN completion returns error THEN the object remains inaccessible and durable cleanup is arranged _(verifies N3; ARCH forward stress-test)_.

### Implementation Notes

- **Module(s):** products service/repository/routes/schemas.
- **Pattern reference:** apps/api/app/modules/users/routes.py photo-upload flow and PhotoUpload model.
- **Key decisions:** A4, A7; product row lock serializes completion/deletion and clean state is not equivalent to attached state.
- **Libraries:** FastAPI, Pydantic, SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Signed POST is write-only; never return an object key as a read URL.

### Scope Boundaries

- Do NOT let an in-progress upload satisfy submission completeness.
- Only product logo/screenshot intents, validation, attachment, and bounded cleanup.

### Files Expected

**New files:**
- apps/api/app/modules/products/routes.py; apps/api/app/modules/products/tests/test_assets.py; test_routes.py (product transport and tests).

**Modified files:**
- apps/api/app/modules/products/service.py; repository.py; schemas.py (asset lifecycle and typed contracts).

**Must NOT modify:**
- apps/api/app/modules/users/routes.py (profile upload flow is a regression guard).
- apps/api/app/shared/storage/client.py (no new public object client).

---

## Task T9: Route Product Outbox Events to Typed Worker Handlers

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** T4, T7
> **Satisfies REQs:** R17, N1, N3
> **Footprint slice:** Shared outbox completion/dispatcher, worker loop, product-owned handler in its service boundary.
> **High-risk areas touched:** Outbox/worker and rollout; private media/storage.

### Description

Make worker dispatch exhaustive by event type so product state events and media-purge commands cannot be interpreted as email. Preserve email delivery idempotence and add idempotent, retryable object purge semantics with operational visibility.

### Test Plan

#### Test File(s)
- apps/api/app/shared/events/tests/test_dispatcher.py
- apps/api/app/modules/products/tests/test_events.py
- tests/integration/test_background_processes.py

#### Test Scenarios

##### Typed Dispatch

- **never emails product events** — GIVEN a product event and an email sender spy WHEN worker dispatch runs THEN only its product handler executes _(verifies N1, N3)_.
- **preserves email behavior** — GIVEN verification/reset events and retries WHEN dispatched THEN each delivery remains idempotent and product handling does not alter mail semantics _(guards backward-regression risk for apps/worker/worker.py and existing identity mail)_.
- **purges idempotently** — GIVEN already-missing or unreferenced product keys WHEN purge is retried THEN it completes safely; referenced keys are not deleted _(verifies R17, N3)_.
- **retries outage and surfaces dead work** — GIVEN transient S3 outage or exhausted attempts WHEN purge runs THEN it retries or is visibly dead-lettered for replay rather than silently succeeding _(verifies R17; ARCH forward stress-test)_.
- **keeps scheduler/readiness behavior** — GIVEN due mixed events WHEN generic scheduler and worker health checks run THEN due hints still work without event-specific scheduler changes _(guards backward-regression risk for apps/worker/scheduler.py)_.

### Implementation Notes

- **Module(s):** shared events, product events, worker.
- **Pattern reference:** apps/api/app/shared/events/dispatcher.py and outbox.py; apps/worker/worker.py.
- **Key decisions:** A8, A9, A10; typed worker must be deployed before feature activation.
- **Libraries:** SQLAlchemy 2 async, boto3, pytest.
- **High-risk callouts:** Non-email completion must not create EmailDelivery rows, and every unknown type must fail closed with observable state.

### Scope Boundaries

- Do NOT replace PostgreSQL outbox with Redis-only work or add a new process.
- Only product event routing and cleanup; email behavior stays compatible.

### Files Expected

**New files:**
- apps/api/app/modules/products/tests/test_events.py (product event verification).
- apps/api/app/shared/events/tests/test_dispatcher.py (typed-dispatch coverage).

**Modified files:**
- apps/api/app/shared/events/outbox.py; dispatcher.py; apps/worker/worker.py (typed completion/dispatch).
- apps/api/app/modules/products/service.py (named product-event handling boundary).
- tests/integration/test_background_processes.py (worker regression guard).

**Must NOT modify:**
- apps/worker/scheduler.py (generic due-work behavior).
- apps/api/app/shared/email/transport.py (email delivery semantics unchanged).

---

## Task T10: Delete Private Drafts With Durable Purge

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T6, T8, T9
> **Satisfies REQs:** R16, R17, N1, N3
> **Footprint slice:** Product deletion service/repository/route and purge-event payload through the shared outbox.
> **High-risk areas touched:** Product transactions and queue; private media/storage; outbox/worker and rollout.

### Description

Allow an unsuspended owner to hard-delete only a private draft after storage availability preflight. Commit metadata removal and encrypted purge work together, revoke app-gated reads immediately, and sweep outstanding upload keys after signed POST expiry.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_deletion.py
- tests/integration/test_product_deletion.py

#### Test Scenarios

##### Delete Contract

- **rejects wrong state or actor** — GIVEN a submitted product, another member, or suspended owner WHEN deleting THEN no product/media metadata changes _(verifies R17, N2)_.
- **retains draft on preflight failure** — GIVEN storage unavailable before commit WHEN delete runs THEN a retryable error is returned and the draft remains accessible _(verifies R17; REQ edge case)_.
- **revokes access and frees capacity** — GIVEN a successful draft deletion WHEN owner/staff reads or quota count run THEN the draft/media are unavailable and one draft slot is free _(verifies R16, R17, N1)_.
- **retries postcommit purge** — GIVEN storage failure after database commit WHEN worker retries THEN physical deletion eventually completes without reviving the product _(verifies R17; ARCH forward stress-test)_.
- **removes late signed upload** — GIVEN an upload URL valid when draft deletion commits WHEN client POSTs before expiry THEN the delayed purge removes that staging key after expiry _(verifies R17, N1)_.

### Implementation Notes

- **Module(s):** products service/repository/routes and shared outbox.
- **Pattern reference:** apps/api/app/modules/users/routes.py storage error mapping; shared outbox transactional add.
- **Key decisions:** A8; PostgreSQL and S3 are not atomic, so successful API deletion means immediate inaccessibility plus durable purge.
- **Libraries:** SQLAlchemy 2 async, boto3, pytest.
- **High-risk callouts:** Precommit failure preserves draft; postcommit failure is monitored/retried, never falsely reported as rollback.

### Scope Boundaries

- Do NOT delete pending submissions or promise synchronous physical object removal.
- Only confirmed private-draft deletion and its cleanup work.

### Files Expected

**New files:**
- apps/api/app/modules/products/tests/test_deletion.py; tests/integration/test_product_deletion.py (verification).

**Modified files:**
- apps/api/app/modules/products/service.py; repository.py; routes.py (delete, event, cleanup boundary).

**Must NOT modify:**
- apps/api/app/modules/users/service.py (profile deletion is not in scope).
- apps/worker/scheduler.py (delayed event remains generic).

---

## Task T11: Serve Session-Bound Private Product Media

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T7, T8, T10
> **Satisfies REQs:** R6, R14, R17, N1, N2
> **Footprint slice:** Product media signing in service and modified products route/policies.
> **High-risk areas touched:** Private media/storage; auth/session and operator access.

### Description

Return short-lived app-signed media URLs bound to the current opaque session, then recheck current product, asset attachment, and owner/pending-staff permission on every GET. Do not expose direct S3 GET presigns or make a once-issued URL a permanent authorization grant.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_media.py
- apps/api/app/modules/products/tests/test_routes.py

#### Test Scenarios

##### Signed Reads

- **binds signature to session and expiry** — GIVEN a URL from session A WHEN session B, a changed path, or an expired signature uses it THEN access is denied _(verifies N1)_.
- **allows current authorized viewers** — GIVEN an attached clean asset WHEN its owner or verified unsuspended staff viewing a pending item requests it THEN bytes stream with no-store and nosniff headers _(verifies R6, R14)_.
- **revokes staff on withdrawal** — GIVEN a staff URL issued for pending media WHEN founder withdraws THEN a later GET returns hidden even before signature expiry _(verifies R11, N1)_.
- **revokes detached and deleted assets** — GIVEN a former asset URL WHEN asset is detached or draft deleted THEN access is denied despite a still-valid signature _(verifies R17, N1)_.
- **hides other founders and storage faults** — GIVEN visitor/other member or S3 outage WHEN reading THEN private identity is not disclosed and only the authorized caller receives a safe availability error _(verifies N1, N2; ARCH forward stress-test)_.

### Implementation Notes

- **Module(s):** products service, routes, policies.
- **Pattern reference:** apps/api/app/modules/users/routes.py profile-photo gate.
- **Key decisions:** A7, A8; HMAC path/expiry with session secret plus mandatory live database authorization.
- **Libraries:** FastAPI, hmac/hashlib, SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Never log signatures or object keys; no direct object URL may survive deletion as a bypass.

### Scope Boundaries

- Do NOT create a public product/media resolver or direct S3 download URL.
- Only private owner and current pending-staff media reads.

### Files Expected

**New files:**
- apps/api/app/modules/products/tests/test_media.py (signing/authorization tests).

**Modified files:**
- apps/api/app/modules/products/routes.py; service.py; policies.py; tests/test_routes.py (gated read and regression coverage).

**Must NOT modify:**
- apps/api/app/modules/users/routes.py (profile photo route remains unchanged).
- apps/api/app/shared/storage/client.py (no public S3 client).

---

## Task T12: Expose Product REST Commands Safely

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** T6, T8, T10, T11
> **Satisfies REQs:** R1, R4, R9, R10, R11, R16, R17, N1, N2, N4
> **Footprint slice:** Products REST routes/schemas and bounded action rate-limit policy within those product boundaries.
> **High-risk areas touched:** Auth/session and operator access; product transactions and queue; private media/storage.

### Description

Complete the REST command surface for create, save, submit, withdraw, delete, and media actions. Apply existing exact-Origin and CSRF checks, map typed domain errors to safe statuses, and bound high-frequency operations without weakening withdrawal.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_routes.py
- tests/integration/test_product_api.py

#### Test Scenarios

##### Transport and Security

- **exposes command contracts** — GIVEN an authenticated owner WHEN each documented REST action succeeds THEN Pydantic responses contain current ID/version/status without ORM or private key leakage _(verifies R1, R9–R11)_.
- **rejects untrusted browser actions** — GIVEN missing/untrusted Origin or CSRF WHEN a mutation runs THEN it receives the same generic rejection as existing browser actions _(verifies N2)_.
- **maps safe errors** — GIVEN wrong owner, stale version, invalid fields, quota, throttle, or dependency outage WHEN routed THEN 404/409/422/429/503 surfaces safely and field errors identify only the caller's fields _(verifies R4, R16, R17, N1)_.
- **bounds rapid actions** — GIVEN repeated autosave/upload attempts WHEN rate policy triggers THEN the account is limited without corrupting its latest saved draft _(verifies N4; REQ edge case)_.
- **does not trap withdrawal** — GIVEN Redis outage or a founder above draft cap WHEN withdrawing THEN the operation remains available and queue entry closes _(verifies R11, R16; ARCH forward stress-test)_.

##### Regression Guard

- **preserves existing identity/profile routes** — GIVEN prior auth and profile mutation requests WHEN new product routes are mounted THEN origin/CSRF and route matching remain unchanged _(guards backward-regression risk for apps/api/app/modules/auth/tests/* and apps/api/app/modules/users/tests/*)_.

### Implementation Notes

- **Module(s):** products REST transport, shared request-security primitives.
- **Pattern reference:** apps/api/app/modules/users/routes.py and apps/api/app/modules/auth/routes.py.
- **Key decisions:** A1, A6; routes remain thin and browser-facing commands keep existing origin/CSRF policy.
- **Libraries:** FastAPI, Pydantic, Redis rate limiting, pytest.
- **High-risk callouts:** A 404 must not distinguish nonexistent from another founder's private resource.

### Scope Boundaries

- Do NOT add GraphQL mutations, reviewer decisions, or a non-browser bypass to product commands.
- Only transport, rate bounds, and safe error mapping for already-defined services.

### Files Expected

**New files:**
- tests/integration/test_product_api.py (API verification).

**Modified files:**
- apps/api/app/modules/products/routes.py; schemas.py; tests/test_routes.py (complete command transport).

**Must NOT modify:**
- apps/api/app/modules/users/routes.py; apps/api/app/modules/auth/routes.py (existing browser-action behavior is regression-checked).
- apps/api/app/shared/security/csrf.py (reuse exact validation).

---

## Task T13: Build Owner and Staff Read Projections

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T2, T6, T8
> **Satisfies REQs:** R1, R8, R12, R13, R14, R15, N1, N2, N4
> **Footprint slice:** Product service/repository read projections for owner lists, staff queue/detail, topics, duplicate and suspension flags.
> **High-risk areas touched:** Product transactions and queue; auth/session and operator access; shared GraphQL/profile reads.

### Description

Provide policy-enforced read models for a founder's private products and a staff member's current pending queue. Use bounded keyset paging, indexed duplicate lookup, and batched live founder state without exposing other founders' drafts or proposals.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_reads.py
- apps/api/app/modules/products/tests/test_queue.py

#### Test Scenarios

##### Privacy and Current State

- **returns only owner's private work** — GIVEN drafts/pending items for multiple founders WHEN owner list/detail runs THEN only the actor's items appear; visitors and other members learn nothing _(verifies R1, N1)_.
- **limits staff to pending** — GIVEN pending, withdrawn, and never-submitted drafts WHEN staff reads THEN only current pending details/media and submission ID/version appear _(verifies R12, R14, N1)_.
- **keeps topic proposals hidden** — GIVEN another founder's private topic WHEN choices are read THEN it is absent until first launch; own selected label may remain visible to its owner _(verifies R8, N1)_.
- **shows live staff-only flags** — GIVEN same canonical website or a newly suspended founder WHEN queue/detail runs THEN staff sees possible-duplicate/suspended flags but a founder sees no matching private product _(verifies R14, R15)_.

##### Queue Performance

- **preserves oldest-first cursor order** — GIVEN pending edits and withdrawn/resubmitted periods WHEN paging THEN order uses original active-period timestamp and stable ID without duplicates or skips _(verifies R13)_.
- **bounds large pages without N+1** — GIVEN many pending rows WHEN a bounded page is requested THEN founder flags are batched and website key/indexed lookup is used _(verifies N4; ARCH forward stress-test)_.

### Implementation Notes

- **Module(s):** products read service/repository; auth batch access interface.
- **Pattern reference:** apps/api/app/modules/users/service.py owner/public read split.
- **Key decisions:** A1, A3, A5; staff only sees submitted current state, not historical or draft content.
- **Libraries:** SQLAlchemy 2 async, pytest.
- **High-risk callouts:** Duplicate detection may inspect private product rows internally but must not return matching identities to founders.

### Scope Boundaries

- Do NOT add visitor/public product, search, or public topic discovery.
- Only owner and verified unsuspended staff projections plus bounded topic choices.

### Files Expected

**New files:**
- apps/api/app/modules/products/tests/test_reads.py; test_queue.py (read/queue coverage).

**Modified files:**
- apps/api/app/modules/products/service.py; repository.py; policies.py (read projections and policy).

**Must NOT modify:**
- apps/api/app/modules/users/graphql.py (profile composition is T14).
- apps/api/app/modules/auth/repository.py (use T2 named batch interface).

---

## Task T14: Compose Product and Profile GraphQL Reads

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** critical
> **Depends on:** T13
> **Satisfies REQs:** R1, R8, R12, R14, R15, N1, N2
> **Footprint slice:** New product GraphQL fields and app schema composer; modified users GraphQL/routes, preserving existing profile fields.
> **High-risk areas touched:** Shared GraphQL/profile reads; auth/session and operator access.

### Description

Compose product owner/staff fields with the existing profile reads on one bounded POST-only Strawberry endpoint. Move shared GraphQL context/validation out of users routes without changing profile field signatures or their privacy behavior.

### Test Plan

#### Test File(s)
- apps/api/app/modules/products/tests/test_graphql.py
- tests/integration/test_graphql_composition.py
- apps/api/app/modules/users/tests/test_graphql.py (run unchanged)

#### Test Scenarios

##### New Read Contract

- **reads only authorized product fields** — GIVEN owner, verified staff, visitor, and other member WHEN querying product fields THEN each sees only permitted current data _(verifies R1, R14, N1)_.
- **exposes freshness and flags safely** — GIVEN a pending edit, duplicate link, or suspended founder WHEN queue/detail fields resolve THEN staff sees current submission ID/version and flags without leaking private matches to founders _(verifies R12, R14, R15)_.
- **blocks unsafe queries** — GIVEN mutation, introspection, alias/fragments, excess depth/page size, or forbidden root WHEN submitted THEN bounded read validation rejects it safely _(verifies N1, N4)_.
- **hides private topic proposal** — GIVEN another founder's unlaunched topic WHEN topicChoices is queried THEN no proposal association or name is exposed _(verifies R8, N1)_.

##### Regression Guard

- **preserves profile GraphQL** — GIVEN existing viewerProfile/publicProfile queries WHEN run through the composed schema THEN fields, privacy, and generated operation shapes are unchanged _(guards backward-regression risk for apps/api/app/modules/users/tests/test_graphql.py and apps/web/src/profiles/*)_.

### Implementation Notes

- **Module(s):** app GraphQL composition, products GraphQL, users GraphQL field export.
- **Pattern reference:** apps/api/app/modules/users/graphql.py and its context in users/routes.py.
- **Key decisions:** A1, A6; services—not resolvers—own authorization, with a second check in the resolver transaction.
- **Libraries:** Strawberry, graphql-core, pytest.
- **High-risk callouts:** Changing query-root allowlist/depth must not open introspection or weaken public-profile privacy.

### Scope Boundaries

- Do NOT add GraphQL mutations, a second endpoint, or public product fields.
- Only compose existing profile and new private product/staff reads.

### Files Expected

**New files:**
- apps/api/app/graphql.py; apps/api/app/modules/products/graphql.py (schema composition and product fields).
- apps/api/app/modules/products/tests/test_graphql.py; tests/integration/test_graphql_composition.py (verification).

**Modified files:**
- apps/api/app/modules/users/graphql.py; routes.py (export profile fields; move GraphQL context ownership).

**Must NOT modify:**
- apps/api/app/modules/users/tests/test_graphql.py (existing regression suite is run unchanged).
- apps/web/src/profiles/* (profile consumer stays compatible).

---

## Task T15: Gate Product Activation and Regenerate Contracts

> **Status:** not started
> **Verification:** checklist
> **Effort:** m
> **Priority:** critical
> **Depends on:** T3, T9, T12, T14
> **Satisfies REQs:** N1, N3
> **Footprint slice:** Settings, app wiring, local/check Compose, contract script and generated REST/GraphQL contracts.
> **High-risk areas touched:** Database/contract pipeline and release gate; shared GraphQL/profile reads; outbox/worker and rollout.

### Description

Add disabled-by-default product activation, mount product REST/GraphQL only when enabled, and configure local/check runs to exercise the feature. Regenerate OpenAPI and GraphQL operation types from the enabled schema and document the exact-head rollout constraint in the verification evidence.

### Verification Checklist

- **Production default off** — expected: settings validation and an API instance without LAUNCHPAD_PRODUCTS_ENABLED expose neither product routes nor product GraphQL fields.
- **Local/check explicitly on** — expected: docker compose config for compose.yaml and compose.checks.yaml shows the product flag enabled only on intended API/check services, with no new service or secret.
- **Compatible startup** — expected: preparation advances to 0005 and API/worker readiness succeeds against 0005; an old-head binary is not described or tested as a safe rollback.
- **Generated contracts match** — run sh scripts/quality/contracts.sh --check; expected: exit 0, profile operations unchanged, product operations and expanded self-session types present.
- **No early producer** — expected: with feature off, no browser-accessible product command can create a product outbox event even while the typed worker is deployed.
- **Profile/health regression** — expected: existing profile GraphQL and health/integration checks still pass without relaxing schema compatibility.

### Implementation Notes

- **Module(s):** shared settings, app composition, Compose, contracts.
- **Pattern reference:** apps/api/app/main.py, settings.py, scripts/quality/contracts.sh.
- **Key decisions:** A6, A9, A10; controlled cutover to compatible 0005 API/worker precedes activation.
- **Libraries:** Pydantic, FastAPI, Strawberry, Docker Compose, OpenAPI/GraphQL generators.
- **High-risk callouts:** Contract generation must run with the product gate on, while production remains off until the typed worker is verified.

### Scope Boundaries

- Do NOT loosen apps/api/app/shared/db/database.py readiness or assume old 0004 images can restart after migration.
- Only feature gating, wiring, local/check config, and generated contracts.

### Files Expected

**New files:**
- None.

**Modified files:**
- apps/api/app/shared/config/settings.py; apps/api/app/main.py (flag and conditional routing).
- compose.yaml; compose.checks.yaml (explicit local/check enablement).
- scripts/quality/contracts.sh (generate enabled schema).
- packages/contracts/operations.graphql; schema.graphql; openapi.json; src/generated.ts; src/graphql.generated.ts (generated operation/response contracts).
- apps/api/app/shared/config/tests/test_settings.py (flag validation coverage).

**Must NOT modify:**
- apps/api/app/shared/db/database.py; apps/api/app/modules/health/* (exact-head readiness stays intact).
- apps/worker/scheduler.py (generic event hints remain intact).

---

## Task T16: Build Typed Product Client and Autosave State

> **Status:** not started
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T15
> **Satisfies REQs:** R2, R3, R6, R9, R11, N4, N5
> **Footprint slice:** New web products client/query hooks; modified identity client for current role/session hydration.
> **High-risk areas touched:** Web editor/staff queue; database/contract pipeline and release gate.

### Description

Build a generated-type REST/GraphQL client and TanStack Query hooks for product reads/mutations. The autosave controller serializes debounced saves, retains local edits through failures/conflicts, and prevents Submit from outrunning the final successful save.

### Test Plan

#### Test File(s)
- apps/web/src/products/client.test.ts
- apps/web/src/products/useProducts.test.ts
- apps/web/src/identity/client.test.ts (run unchanged)

#### Test Scenarios

##### Typed Requests

- **uses generated contracts and cookies** — GIVEN product reads/commands WHEN client sends them THEN it uses generated request/operation types, credentials, and current CSRF token _(verifies N2)_.
- **hydrates deep-link session** — GIVEN a signed-in browser loading a product URL directly WHEN identity session loads THEN role/suspension and CSRF are ready before a mutation _(verifies R1, N5)_.
- **waits for clean upload and final save** — GIVEN in-progress image validation or autosave WHEN Submit is requested THEN it waits for a successful current version or stops with a blocker _(verifies R6, R9; REQ edge case)_.

##### Autosave Resilience

- **announces only persisted save** — GIVEN rapid edits WHEN debounced serialized saves run THEN saving/saved states reflect server acknowledgement, not local typing _(verifies R2, N4)_.
- **retains failed edits and retries connection loss** — GIVEN network failure WHEN a save fails THEN fields stay local and Not saved is shown; reconnection retries the latest values _(verifies R2; ARCH forward stress-test)_.
- **stops stale overwrite** — GIVEN a 409 from another tab WHEN autosave runs THEN local edits remain and automatic retry pauses for conflict resolution _(verifies R3)_.

### Implementation Notes

- **Module(s):** web products data layer, identity client.
- **Pattern reference:** apps/web/src/profiles/client.ts and useProfile.ts; apps/web/src/identity/client.ts.
- **Key decisions:** A3, A6; server state in TanStack Query and transient edit state local, no optimistic save without rollback.
- **Libraries:** React, TypeScript strict, TanStack Query, Vitest.
- **High-risk callouts:** Never show Saved before server acknowledgement or auto-retry a 409 into data loss.

### Scope Boundaries

- Do NOT hand-maintain API types or build visual screens here.
- Only client/hook/autosave behavior behind the later UI.

### Files Expected

**New files:**
- apps/web/src/products/client.ts; useProducts.ts; client.test.ts; useProducts.test.ts (typed data layer and tests).

**Modified files:**
- apps/web/src/identity/client.ts (live role/suspension and deep-link session readiness).

**Must NOT modify:**
- apps/web/src/identity/*.test.ts* (existing identity regressions run unchanged).
- apps/web/src/profiles/* (profile client remains compatible).

---

## Task T17: Build the Accessible Founder Product Editor

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T16
> **Satisfies REQs:** R1, R2, R3, R4, R5, R6, R7, R9, R11, R16, R17, N5
> **Footprint slice:** Founder product screen, App route, identity navigation, responsive styles.
> **High-risk areas touched:** Web editor/staff queue; auth/session and operator access.

### Description

Build the founder's mobile-first private draft/editor journey using the typed hooks. Make save, conflict, validation, upload, submission, withdrawal, and deletion outcomes visible and keyboard/assistive-technology usable.

### Verification Checklist

- **Phone and desktop editor** — expected: at approximately 390px and 1280px, all required fields, selected media, topics, and primary actions are visible without horizontal overflow.
- **Save and conflict states** — expected: Saving, Saved, and Not saved are announced; failed/stale saves keep typed values and offer a clear retry or conflict choice.
- **Submission blockers** — expected: missing/over-limit fields associate errors with controls; pending/failed/eleventh screenshot raises an alert toast; Submit waits for final save.
- **Pending choices** — expected: a complete pending edit keeps its queue place; an incomplete one keeps the unsaved local values and explains withdrawal; explicit withdrawal returns the editor to private draft.
- **Topics and limits** — expected: founder can select or type 1–3 topics, and draft/pending capacity errors explain the relevant 10/3 limit without disclosing another founder's work.
- **Deletion confirmation** — expected: confirmation precedes permanent deletion; storage failure leaves the draft on screen with a retryable message; suspended owner cannot delete but can withdraw.
- **Keyboard and existing routes** — expected: focus order and labels work without a mouse, and existing sign-in/profile routes still navigate as before.

#### Testable Seams

- apps/web/src/products/ProductScreens.test.tsx checks conditional states, handlers, alert/live regions, validation associations, and keyboard-operable controls.
- apps/web/src/App.test.tsx checks narrow product routing and existing profile/identity route regression.

### Implementation Notes

- **Module(s):** web products UI and App routing.
- **Pattern reference:** apps/web/src/profiles/ProfileScreens.tsx and apps/web/src/identity/Screens.tsx; docs/source/inspiration.md for original visual direction only.
- **Key decisions:** A3, A7, A8; UI cannot treat local state as persisted or S3 upload as validated.
- **Libraries:** React, TypeScript strict, Tailwind/current styles, Testing Library/Vitest.
- **High-risk callouts:** Saved/Not saved and irreversible deletion must be unambiguous to screen readers and sighted users.

### Scope Boundaries

- Do NOT add public product pages, reviewer decisions, or copied reference-site layout/assets.
- Only founder list/editor and actions defined in REQ.

### Files Expected

**New files:**
- apps/web/src/products/ProductScreens.tsx; ProductScreens.test.tsx (founder journey and component coverage).

**Modified files:**
- apps/web/src/App.tsx; App.test.tsx (product route and existing-route guard).
- apps/web/src/styles.css; apps/web/src/identity/Screens.tsx (responsive editor and navigation).

**Must NOT modify:**
- apps/web/src/profiles/* (existing profile behavior is a regression guard).
- apps/web/src/identity/*.test.ts* (existing identity tests run unchanged).

---

## Task T18: Build the Accessible Staff Review Queue View

> **Status:** not started
> **Verification:** ui
> **Effort:** m
> **Priority:** high
> **Depends on:** T16, T17
> **Satisfies REQs:** R12, R13, R14, R15, N1, N5
> **Footprint slice:** Product staff queue/detail screens and responsive styles.
> **High-risk areas touched:** Web editor/staff queue; shared GraphQL/profile reads.

### Description

Display only current pending submissions to verified unsuspended staff, with oldest-first paging, current content/media, and visible suspended-founder and possible-duplicate flags. The view carries submission ID/version for a later decision workflow but has no decision buttons in this slice.

### Verification Checklist

- **Queue order and paging** — expected: oldest pending entries appear first, pending edits do not move a card, and withdrawal/resubmission appears at the back without duplicate cards.
- **Current detail and flags** — expected: opening an entry shows latest content/media, submission version, suspended-founder flag, and staff-only possible-duplicate flag.
- **Access and privacy** — expected: visitors, ordinary members, and suspended staff see no private queue data; withdrawn/draft content disappears from staff view.
- **Phone and desktop operation** — expected: at approximately 390px and 1280px, list/detail remain readable without horizontal overflow and all controls work by keyboard.
- **No premature moderation** — expected: there are no approve, reject, changes-requested, schedule, or launch controls.

#### Testable Seams

- apps/web/src/products/ProductScreens.staff.test.tsx checks conditional authorized/forbidden states, order/flags, current detail, focus/labels, and absence of decision controls.

### Implementation Notes

- **Module(s):** web products staff UI.
- **Pattern reference:** apps/web/src/profiles/ProfileScreens.tsx for accessible states; product read hooks from T16.
- **Key decisions:** A3, A5, A6; staff flags never become founder-facing details.
- **Libraries:** React, TypeScript strict, TanStack Query, Testing Library/Vitest.
- **High-risk callouts:** A stale queue card must refresh to current version; do not visually imply a reviewer decision action exists.

### Scope Boundaries

- Do NOT implement reviewer decisions or public listing/discovery.
- Only staff pending queue and current detail.

### Files Expected

**New files:**
- apps/web/src/products/ProductScreens.staff.test.tsx (staff view coverage within the product screen module).

**Modified files:**
- apps/web/src/products/ProductScreens.tsx (product route switch to staff view).
- apps/web/src/styles.css (responsive queue/detail styling).

**Must NOT modify:**
- apps/web/src/profiles/* (existing public/private profile view remains unchanged).
- apps/web/src/identity/*.test.ts* (identity regression suite runs unchanged).

---

## Task T19: Document Operations and Run the Full Gate

> **Status:** not started
> **Verification:** checklist
> **Effort:** s
> **Priority:** high
> **Depends on:** T18
> **Satisfies REQs:** R1–R17, N1–N5
> **Footprint slice:** Development/operations documentation and verification of every modified high-risk area; no new product behavior.
> **High-risk areas touched:** Auth/session and operator access; product transactions and queue; private media/storage; shared GraphQL/profile reads; outbox/worker and rollout; web editor/staff queue; database/contract pipeline and release gate.

### Description

Document staff provisioning, the private-media and deletion lifecycle, feature activation/rollback, and diagnostics. Run the repository-wide quality gate and reconcile any failing existing behavior before declaring the whole feature ready.

### Verification Checklist

- **Operator instructions** — expected: docs/development.md names the restricted role/suspension command, audit trail, and withdrawal exception without suggesting a public promotion endpoint.
- **Media and deletion instructions** — expected: docs explain private signed upload/app-gated read, immediate access revocation, delayed purge, preflight failure, and how to inspect/replay stuck purge work without logging object keys.
- **Safe release/rollback** — expected: docs explicitly drain old 0004 binaries, migrate, start compatible typed worker/API with feature off, verify, then enable; rollback disables feature on 0005-compatible images, never old email-only worker.
- **Full quality command** — run sh scripts/quality/run.sh with an isolated Compose project; expected: formatter, Ruff, mypy, pytest, web format/lint/types/tests, migrations, contracts, builds, security, and browser categories pass.
- **Regression surfaces** — expected: existing auth/profile/storage/email/scheduler/health suites pass unchanged, and no public route, resolver, log, or storage URL exposes unpublished product/topic/media data.
- **Observability** — expected: action IDs/state/error classes and queue/purge health are diagnosable; private content, signatures, object keys, and token values are absent from logs.

### Implementation Notes

- **Module(s):** development documentation and full pipeline.
- **Pattern reference:** docs/development.md and scripts/quality/run.sh.
- **Key decisions:** A1–A10; the approved two-stage release and deletion compromise must be accurately documented.
- **Libraries:** existing Docker Compose, pytest, Ruff, mypy, Vitest, browser checks.
- **High-risk callouts:** Do not mark the feature done while a dead purge event or private-data leak remains unexplained.

### Scope Boundaries

- Do NOT deploy to production, downgrade shared migrations, or implement deferred reviewer/launch flows.
- Only documentation, diagnostics confirmation, and comprehensive verification.

### Files Expected

**New files:**
- None.

**Modified files:**
- docs/development.md (operator, media, rollout, and troubleshooting guide).

**Must NOT modify:**
- apps/api/app/shared/db/database.py; apps/api/alembic/env.py; apps/api/app/modules/health/* (exact-head readiness is preserved).
- apps/worker/scheduler.py; apps/web/src/profiles/*; existing auth/identity regression test files (run unchanged).

---
