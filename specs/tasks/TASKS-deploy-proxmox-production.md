# Tasks

## Task T1: Add explicit storage-provider configuration

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** None
> **Satisfies REQs:** R4, R7, R11
> **Footprint slice:** Modified: settings, local env/Compose; tests for configuration
> **High-risk areas touched:** Storage H; Local development M

### Description

Add explicit MinIO/R2 provider and region settings, preserving local defaults while requiring valid R2 settings in production. Invalid production configuration must fail closed instead of selecting local credentials implicitly.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/config/tests/test_settings.py`
- `tests/integration/test_environment_isolation.py`

#### Test Scenarios

##### Provider Configuration
- Local defaults choose MinIO and `us-east-1` without cloud credentials _(verifies R4, R11)_
- Valid production settings select R2 and `auto` _(verifies R4)_
- Missing, malformed, or insecure production storage endpoint/credentials fail with safe configuration errors _(verifies R4, R7)_
- Production does not fall back to MinIO when R2 settings are absent or invalid _(verifies R4)_
- Existing Resend API key remains worker-only under production validation _(guards ARCH backward-regression risk for `settings.py`)_

### Implementation Notes
- **Module(s):** shared configuration
- **Pattern reference:** `apps/api/app/shared/config/settings.py`
- **Key decisions:** A5, A9
- **Libraries:** Pydantic settings already in use
- **High-risk callouts:** Do not put cloud credentials into defaults or `.env.example`.

### Scope Boundaries
- Do NOT add R2 credentials or a Cloudflare dependency to local CI.
- Only add settings required by the architecture.

### Files Expected
**New files:**
- None

**Modified files:**
- `apps/api/app/shared/config/settings.py` (provider/region selection and production validation)
- `.env.example`, `compose.yaml`, `compose.checks.yaml` (retain local MinIO configuration)
- `apps/api/app/shared/config/tests/test_settings.py`
- `tests/integration/test_environment_isolation.py`

**Must NOT modify:**
- `apps/api/app/shared/storage/provision.py` (local MinIO provisioning is a separate task)
- `.env.qa.local` (operator-local configuration)

## Task T2: Make shared storage R2-compatible

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R4, R5, R11
> **Footprint slice:** Modified: shared storage client and object adapter; provider-specific tests
> **High-risk areas touched:** Storage H

### Description

Configure shared S3 clients from the selected provider settings and replace R2-incompatible bucket-policy readiness calls. Preserve private reads, deletion, and MinIO signed form uploads.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/storage/tests/test_objects.py`
- `tests/integration/test_storage.py`
- `tests/integration/test_health_dependencies.py`

#### Test Scenarios

##### R2 and MinIO Operations
- R2 client uses the configured account endpoint and `auto` signing region _(verifies R4)_
- R2 readiness uses only supported metadata operations and never requests bucket policy _(verifies R4)_
- Denied access, missing bucket, and timeout remain unhealthy _(verifies R4; ARCH storage outage)_
- R2 staging write/read/delete preserve private keys and object bytes _(verifies R4)_
- MinIO signed POST and private object behavior remain unchanged _(verifies R4, R11)_

### Implementation Notes
- **Module(s):** shared storage and health probes
- **Pattern reference:** `apps/api/app/shared/storage/client.py`, `objects.py`
- **Key decisions:** A5; runtime access probe does not establish public-bucket privacy
- **Libraries:** existing boto3/botocore
- **High-risk callouts:** R2 does not implement bucket policy operations; do not treat access denied as success.

### Scope Boundaries
- Do NOT change browser upload transport here.
- Do NOT make R2 buckets public or use public object URLs.

### Files Expected
**New files:**
- None

**Modified files:**
- `apps/api/app/shared/storage/client.py`
- `apps/api/app/shared/storage/objects.py`
- `apps/api/app/main.py` (provider-aware client construction)
- `apps/worker/worker.py` (provider-aware storage construction)
- `apps/api/app/modules/health/probes.py`
- `apps/api/app/shared/storage/tests/test_objects.py`
- `tests/integration/test_storage.py`, `tests/integration/test_health_dependencies.py`

**Must NOT modify:**
- `apps/api/app/shared/storage/provision.py` (MinIO-only operations)
- `apps/api/app/modules/users/routes.py`, `apps/api/app/modules/products/routes.py` (owned by T7)

## Task T3: Add bounded upload intake

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T1
> **Satisfies REQs:** R5, R11
> **Footprint slice:** New shared bounded upload receiver and focused tests
> **High-risk areas touched:** Upload security H; shared-host performance H

### Description

Create a reusable bounded receiver for raw uploads that counts actual bytes, applies a deadline and concurrency limit, and cleans temporary resources on every exit. It must reject oversized input regardless of `Content-Length` before any storage write.

### Test Plan

#### Test File(s)
- `apps/api/app/shared/storage/tests/test_uploads.py`

#### Test Scenarios

##### Bounds and Resource Cleanup
- Accept within-limit body and preserve exact bytes _(verifies R5)_
- Reject actual bytes above the declared/max limit with no storage operation _(verifies R5; ARCH oversized upload)_
- Missing or false `Content-Length` cannot bypass counting _(verifies R5)_
- Slow/disconnected body hits finite deadline and closes its temporary resource _(verifies R5; ARCH API interruption)_
- Concurrent limit returns bounded overload and releases capacity after completion/failure _(verifies R5; ARCH slow upload)_
- Temporary resource and semaphore are released after exception/cancellation _(verifies R11)_

### Implementation Notes
- **Module(s):** new shared upload utility
- **Pattern reference:** typed errors in `apps/api/app/shared/storage/objects.py`
- **Key decisions:** A6, A7
- **Libraries:** standard-library temporary file and async primitives; no unnecessary dependency
- **High-risk callouts:** Never hold a database transaction while waiting for the browser body.

### Scope Boundaries
- Do NOT add feature authorization or R2 writes to the utility.
- Use configurable conservative limits, with 5 MiB as the architecture maximum.

### Files Expected
**New files:**
- `apps/api/app/shared/storage/uploads.py`
- `apps/api/app/shared/storage/tests/test_uploads.py`

**Modified files:**
- None

**Must NOT modify:**
- `apps/api/app/shared/security/rate_limit.py` (consume existing rate-limit interface)

## Task T4: Persist profile upload declarations

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** None
> **Satisfies REQs:** R5, R11
> **Footprint slice:** Profile upload model/repository and forward migration
> **High-risk areas touched:** Schema/rollout H

### Description

Persist the declared size and media type on profile upload intents so the production transfer endpoint can enforce intent limits. Nullable additions preserve completed and pending legacy records; pending legacy records without declarations cannot use the new raw transfer route.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/users/tests/test_profile.py`
- `apps/api/app/modules/users/tests/test_routes.py`
- `tests/integration/test_profile_privacy.py`
- New migration assertions in `tests/integration/test_storage.py` or a focused migration test

#### Test Scenarios

##### Migration and Compatibility
- Fresh database reaches one new head with nullable declaration columns _(verifies R5)_
- Existing completed profile media remains readable after upgrade _(verifies R11; ARCH migration regression)_
- Existing pending row without declarations remains represented and is refused for API transfer _(verifies R5)_
- New intent persists declared size/type separately from validated final metadata _(verifies R5)_
- Invalid stored declarations cannot be used to bypass size/type validation _(verifies R5)_

### Implementation Notes
- **Module(s):** Users model/repository and Alembic
- **Pattern reference:** `apps/api/app/modules/users/models.py`, latest migration
- **Key decisions:** A7; forward-only migration
- **Libraries:** existing SQLAlchemy/Alembic
- **High-risk callouts:** No destructive rewrite or deletion of existing profile photos.

### Scope Boundaries
- Do NOT change existing completed photo metadata semantics.
- Use the next free Alembic revision if numbering changes before implementation.

### Files Expected
**New files:**
- `apps/api/alembic/versions/0011_profile_upload_declarations.py` (or next free revision)
- Focused migration test if existing integration test cannot express compatibility clearly

**Modified files:**
- `apps/api/app/modules/users/models.py`
- `apps/api/app/modules/users/repository.py`
- `apps/api/app/modules/users/tests/test_profile.py`
- `apps/api/app/modules/users/tests/test_routes.py`
- `tests/integration/test_profile_privacy.py`

**Must NOT modify:**
- `apps/api/app/shared/db/database.py` (migration lock/head contract remains unchanged)

## Task T5: Coordinate profile upload transfer

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T2, T3, T4
> **Satisfies REQs:** R5, R11
> **Footprint slice:** Profile service/repository transfer and state locking
> **High-risk areas touched:** Upload security H; schema H

### Description

Add an owner-authorized profile transfer operation that rechecks active account, pending state, declared limits, and expiry after bounded intake. Serialize transfer with completion so a delayed or retried write cannot replace finalized media.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/users/tests/test_profile.py`
- `apps/api/app/modules/users/tests/test_routes.py`

#### Test Scenarios

##### Profile Transfer Authorization and State
- Only the authenticated active account owner can transfer _(verifies R5)_
- Expired, completed, absent, and legacy undeclared intents refuse transfer _(verifies R5)_
- Eligibility changed during buffering is rechecked before storage write _(verifies R5; ARCH transfer race)_
- Competing transfer/completion cannot write after cleaned state _(verifies R5; ARCH transfer race)_
- Storage outage leaves retryable pending state and no false completion _(verifies R5; ARCH R2 outage)_
- Existing completed photos remain available _(verifies R11)_

### Implementation Notes
- **Module(s):** Users service/repository, shared storage/upload interface
- **Pattern reference:** `apps/api/app/modules/users/service.py`, repository lock conventions
- **Key decisions:** A6, A7
- **Libraries:** existing async SQLAlchemy and storage adapter
- **High-risk callouts:** Lock after body buffering; recheck row state before the storage write.

### Scope Boundaries
- Do NOT bypass the existing completion validation and metadata-stripping path.
- Do NOT make profile media public.

### Files Expected
**New files:**
- None

**Modified files:**
- `apps/api/app/modules/users/service.py`
- `apps/api/app/modules/users/repository.py`
- `apps/api/app/modules/users/tests/test_profile.py`
- `apps/api/app/modules/users/tests/test_routes.py`

**Must NOT modify:**
- `apps/api/app/modules/users/models.py` (declarations owned by T4)
- `apps/api/app/modules/users/schemas.py`, `routes.py` (contract/transport owned by T7)

## Task T6: Coordinate product asset transfer

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T2, T3
> **Satisfies REQs:** R5, R11
> **Footprint slice:** Product service/repository transfer and state locking
> **High-risk areas touched:** Upload security H; storage H

### Description

Add a product asset transfer operation using existing owner, editable-state, expiry, declared-size/type, and pending-asset rules. Serialize it against completion and deletion without changing private media handling.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/products/tests/test_assets.py`
- `apps/api/app/modules/products/tests/test_media.py`
- `tests/integration/test_product_deletion.py`

#### Test Scenarios

##### Product Transfer Authorization and State
- Only active owner of an editable product transfers bytes _(verifies R5)_
- Pending asset rejects expiry, mismatched declaration, and invalid state _(verifies R5)_
- Owner/product eligibility is checked again after buffering _(verifies R5; ARCH transfer race)_
- Concurrent transfer and completion produce one clean result _(verifies R5)_
- Completion failure does not expose staged bytes or mark asset clean _(verifies R5; ARCH R2 outage)_
- Existing attachment order, private reads, and delayed purge behavior remain intact _(verifies R11; ARCH deletion regression)_

### Implementation Notes
- **Module(s):** Products service/repository and shared storage
- **Pattern reference:** `apps/api/app/modules/products/service.py` asset transitions and lock order
- **Key decisions:** A6, A7
- **Libraries:** existing async SQLAlchemy/storage adapter
- **High-risk callouts:** Reuse product/account/asset lock order and existing purge events.

### Scope Boundaries
- Do NOT alter product lifecycle or draft attachment semantics.
- Do NOT allow transfer to clean/final object keys.

### Files Expected
**New files:**
- None

**Modified files:**
- `apps/api/app/modules/products/service.py`
- `apps/api/app/modules/products/repository.py`
- `apps/api/app/modules/products/tests/test_assets.py`
- `apps/api/app/modules/products/tests/test_media.py`
- `tests/integration/test_product_deletion.py`

**Must NOT modify:**
- `apps/api/app/modules/products/permissions.py` (existing authorization policy remains)
- `apps/api/app/modules/products/routes.py`, `schemas.py` (owned by T7)

## Task T7: Expose authenticated upload contracts

> **Status:** done
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T5, T6
> **Satisfies REQs:** R5, R7, R11
> **Footprint slice:** Product/profile schemas and REST routes; API integration tests
> **High-risk areas touched:** Upload security H; contract changes M

### Description

Keep existing intent and completion endpoints while adding explicit transport instructions and authenticated raw-byte PUT endpoints for production. Enforce existing session, Origin, CSRF, owner, edit-state, rate-limit, and safe-error behavior before storing bytes.

### Test Plan

#### Test File(s)
- `apps/api/app/modules/users/tests/test_routes.py`
- `apps/api/app/modules/products/tests/test_assets.py`
- `tests/integration/test_product_api.py`
- `tests/integration/test_profile_privacy.py`
- Generated OpenAPI assertions through `tests/quality/test_graphql_generation.py`

#### Test Scenarios

##### HTTP Upload Contract
- MinIO intent returns POST form instructions; R2 intent returns same-origin PUT instructions _(verifies R4, R5)_
- Valid authenticated transfer returns 204 and can then be completed _(verifies R5)_
- Missing session, bad Origin/CSRF, wrong owner, suspended account, and noneditable product are rejected _(verifies R5, R7)_
- Rate limit is applied before body consumption; oversized actual body returns 413 _(verifies R5; ARCH slow/oversize upload)_
- Wrong type, stale intent, storage outage return safe mapped errors and no success state _(verifies R5)_
- Existing intent fields and completion response remain available _(verifies R11)_

### Implementation Notes
- **Module(s):** Users/Products transport and schemas
- **Pattern reference:** existing CSRF/origin checks in `users/routes.py` and `products/routes.py`
- **Key decisions:** A6, A7; additive contract
- **Libraries:** existing FastAPI/Pydantic
- **High-risk callouts:** Never accept a caller-supplied object key or expose credentials.

### Scope Boundaries
- Do NOT change GraphQL contracts.
- Do NOT send storage credentials or API CSRF headers to MinIO.

### Files Expected
**New files:**
- None

**Modified files:**
- `apps/api/app/modules/users/routes.py`, `schemas.py`
- `apps/api/app/modules/products/routes.py`, `schemas.py`
- `apps/api/app/modules/users/tests/test_routes.py`
- `apps/api/app/modules/products/tests/test_assets.py`
- `tests/integration/test_product_api.py`, `tests/integration/test_profile_privacy.py`
- `packages/contracts/openapi.json` (regenerated)

**Must NOT modify:**
- `apps/api/app/shared/security/csrf.py`, `rate_limit.py` (reuse existing policies)
- `apps/api/app/modules/products/permissions.py` (reuse product authorization)

## Task T8: Generate contracts and add shared frontend uploader

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T7
> **Satisfies REQs:** R5, R11
> **Footprint slice:** Generated OpenAPI client types and new shared frontend uploader
> **High-risk areas touched:** Frontend contracts M; Upload security H

### Description

Regenerate API types and add one frontend helper that executes the server-provided transfer instruction. It must preserve the MinIO form flow and use current session/CSRF state only for same-origin authenticated API transfers.

### Test Plan

#### Test File(s)
- New `apps/web/src/uploads/client.test.ts`
- `tests/quality/test_graphql_generation.py` (OpenAPI generation contract)

#### Test Scenarios

##### Upload Instruction Execution
- Generated types reflect new method/transport/headers fields _(verifies R5)_
- MinIO instruction submits form fields with POST and omits credentials _(verifies R4, R5)_
- Same-origin instruction sends raw bytes with PUT, credentials, content type, and current CSRF token _(verifies R5, R7)_
- Cross-origin API instruction is refused before fetch _(verifies R7)_
- Non-2xx transfer response becomes a safe typed client error _(verifies R5)_
- Failed transfer does not invoke completion _(verifies R5)_

### Implementation Notes
- **Module(s):** frontend contracts and shared upload utility
- **Pattern reference:** `apps/web/src/identity/client.ts`, `products/client.ts`
- **Key decisions:** A6, A7; generated rather than hand-maintained types
- **Libraries:** existing fetch clients/Vitest
- **High-risk callouts:** Preserve cookie/CSRF boundary between same-origin API and external storage.

### Scope Boundaries
- Do NOT alter product/profile screen flows in this task.
- Do NOT put CSRF tokens in local storage or upload intent persistence.

### Files Expected
**New files:**
- `apps/web/src/uploads/client.ts`
- `apps/web/src/uploads/client.test.ts`

**Modified files:**
- `packages/contracts/src/generated.ts` (regenerated)
- `packages/contracts/openapi.json` (regenerated if T7 did not commit final schema)

**Must NOT modify:**
- `apps/web/src/identity/client.ts` (reuse its existing token accessor)

## Task T9: Integrate product and profile upload clients

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T8
> **Satisfies REQs:** R4, R5, R11
> **Footprint slice:** Product/profile upload consumers and client tests
> **High-risk areas touched:** Frontend contracts M; Upload security H

### Description

Replace each screen/client's form-only transfer with the shared executor, while preserving current validation, completion, save/submit sequencing, and user feedback. Both profile photos and product assets must support provider-selected instructions without environment-specific frontend branching.

### Test Plan

#### Test File(s)
- `apps/web/src/products/client.test.ts`
- `apps/web/src/products/useProducts.test.ts`
- `apps/web/src/profiles/ProfileScreens.test.tsx`
- `apps/web/src/profiles/client.test.ts`

#### Test Scenarios

##### Existing Upload Flows
- Product asset intent, transfer, completion, and attachment use returned instructions _(verifies R5)_
- Product submission waits for outstanding uploads and does not submit a failed transfer _(verifies R5, R11)_
- Profile photo transfer completes before photo is attached on profile save _(verifies R5)_
- Existing client-side type/size messaging remains intact _(verifies R11)_
- Retry after transfer error reuses a valid pending intent without duplicate completion _(verifies R5)_
- Existing profile privacy and product draft behavior remain unaffected _(verifies R11)_

### Implementation Notes
- **Module(s):** Products and Profiles web
- **Pattern reference:** `products/client.ts`, `ProfileScreens.tsx`
- **Key decisions:** A5, A6
- **Libraries:** existing React/Vitest
- **High-risk callouts:** Profile and product paths currently contain separate inline form upload logic.

### Scope Boundaries
- Do NOT add new upload UI or change visual design.
- Do NOT change server-side validation rules.

### Files Expected
**New files:**
- None

**Modified files:**
- `apps/web/src/products/client.ts`, `useProducts.ts`
- `apps/web/src/products/client.test.ts`, `useProducts.test.ts`
- `apps/web/src/profiles/ProfileScreens.tsx`, `client.ts`
- `apps/web/src/profiles/ProfileScreens.test.tsx`, `client.test.ts`

**Must NOT modify:**
- `apps/web/src/identity/client.ts` (source of CSRF token state)

## Task T10: Wire provider-aware runtime and local development

> **Status:** done
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T1, T2, T3, T7
> **Satisfies REQs:** R4, R7, R11
> **Footprint slice:** API/worker storage construction, local config, environment isolation
> **High-risk areas touched:** Storage H; Local development M; notifications M

### Description

Wire provider settings consistently through API and worker storage clients and preserve MinIO for local development and isolated CI. Production services receive only the R2 credentials they need, with Resend still worker-only.

### Test Plan

#### Test File(s)
- `tests/integration/test_startup_order.py`
- `tests/integration/test_bootstrap.py`
- `tests/integration/test_environment_isolation.py`
- `apps/worker/tests/test_email_selection.py`
- `tests/integration/test_review_outbox.py`

#### Test Scenarios

##### Runtime Wiring
- Local compose starts without R2 credentials and creates/uses MinIO bucket _(verifies R4, R11)_
- API and worker receive consistent provider/region and bucket settings _(verifies R4)_
- Production API/worker startup fails safely for invalid provider settings _(verifies R4)_
- R2 runtime credentials are absent from unrelated scheduler/web services _(verifies R7)_
- Resend delivery and existing outbox retry behavior remain valid _(verifies R11)_

### Implementation Notes
- **Module(s):** shared configuration, API, worker, local Compose
- **Pattern reference:** `apps/api/app/main.py`, `apps/worker/worker.py`, `compose.yaml`
- **Key decisions:** A5, A9
- **Libraries:** existing Compose/runtime
- **High-risk callouts:** No implicit MinIO fallback in production.

### Scope Boundaries
- Do NOT add MinIO to production Compose.
- Do NOT provision production R2 buckets during routine app startup.

### Files Expected
**New files:**
- None

**Modified files:**
- `apps/api/app/main.py`, `apps/worker/worker.py`
- `compose.yaml`, `compose.checks.yaml`, `.env.example`
- `tests/integration/test_startup_order.py`, `test_bootstrap.py`, `test_environment_isolation.py`
- `apps/worker/tests/test_email_selection.py`, `tests/integration/test_review_outbox.py`

**Must NOT modify:**
- `apps/api/app/shared/storage/provision.py` (local MinIO administrator remains local)

## Task T11: Separate production migrations from MinIO bootstrap

> **Status:** done
> **Verification:** test-after
> **Effort:** s
> **Priority:** critical
> **Depends on:** T1, T4
> **Satisfies REQs:** R4, R6, R11
> **Footprint slice:** New production migration entry point and local bootstrap guard
> **High-risk areas touched:** Schema/rollout H; local startup M

### Description

Add a database-only production migration command that reuses the existing serialized preparation lock and schema-head verification. Keep storage provisioning local to MinIO and preserve local startup ordering.

### Test Plan

#### Test File(s)
- New `tests/integration/test_production_migrations.py`
- `tests/integration/test_database_preparation.py`
- `tests/integration/test_bootstrap.py`
- `tests/integration/test_startup_order.py`

#### Test Scenarios

##### Migration Entry Point
- Production migration succeeds without storage endpoint or bootstrap credentials _(verifies R4, R6)_
- Concurrent migration takes existing preparation lock and verifies expected head _(verifies R6; ARCH concurrent deployment)_
- Migration failure exits nonzero and does not run storage administration _(verifies R6)_
- Local bootstrap still migrates and provisions MinIO _(verifies R11)_
- Exact-head compatibility rejection remains intact _(verifies R6; ARCH migration failure)_

### Implementation Notes
- **Module(s):** API app startup/operations and database preparation
- **Pattern reference:** `apps/api/app/bootstrap.py`, `shared/db/database.py`
- **Key decisions:** A8; add migration, do not rewrite history
- **Libraries:** existing Alembic/SQLAlchemy
- **High-risk callouts:** Pre-migration backup is deployment responsibility, not migration command.

### Scope Boundaries
- Do NOT downgrade schema automatically.
- Do NOT modify `Database.prepare` locking semantics.

### Files Expected
**New files:**
- `apps/api/app/migrate.py`
- `tests/integration/test_production_migrations.py`

**Modified files:**
- `apps/api/app/bootstrap.py` (explicit local provisioning boundary)
- `tests/integration/test_database_preparation.py`, `test_bootstrap.py`, `test_startup_order.py`

**Must NOT modify:**
- `apps/api/app/shared/db/database.py` (reuse existing serialization contract)

## Task T12: Build production images and configure proxy behavior

> **Status:** done
> **Verification:** checklist
> **Effort:** m
> **Priority:** high
> **Depends on:** T7, T9, T10, T11
> **Satisfies REQs:** R1, R2, R5, R6, R11
> **Footprint slice:** Python/web image build and production Nginx proxy configuration
> **High-risk areas touched:** Public routing H; upload security H; frontend M

### Description

Prepare images for production deployment and configure a production proxy for the HTTPS tunnel, raw-body limits, maintenance state, and authenticated WebSockets. Existing local web configuration remains usable.

### Verification Checklist
- [x] Build Python and web images for `linux/amd64`; expected: successful build and recorded digest for each image.
- [x] Inspect image contents; expected: no runtime secret/config file and non-root application process where supported.
- [x] Start web/API locally; expected: SPA routes, `/api/`, and WebSocket upgrade reach correct services.
- [x] Enable maintenance; expected: public routes show maintenance while private readiness remains testable.
- [x] Send raw body at and over configured limit; expected: allowed bytes pass and oversized request is rejected before app/storage.
- [x] Simulate HTTPS tunnel forwarding; expected: secure session cookie and Origin validation see correct public scheme only from trusted path.
- [x] Confirm authenticated/private-media routes are not cached and existing local proxy still works.

### Implementation Notes
- **Module(s):** Docker images and Nginx
- **Pattern reference:** `infra/docker/python.Dockerfile`, `web.Dockerfile`, `web.conf`
- **Key decisions:** A2, A8; image digest and same-origin API uploads
- **Libraries:** existing Docker/Nginx
- **High-risk callouts:** Trusted forwarded headers depend on actual connector placement.

### Scope Boundaries
- Do NOT install tunnel connector or alter host configuration in this task.
- Do NOT expose non-web ports.

### Files Expected
**New files:**
- `infra/docker/web.production.conf`

**Modified files:**
- `infra/docker/python.Dockerfile`, `web.Dockerfile`
- `infra/docker/web.production.conf` (if generated/created as new, keep local config unchanged)

**Must NOT modify:**
- `infra/docker/web.conf` (local routing remains stable)

## Task T13: Define isolated production Compose configuration

> **Status:** done
> **Verification:** checklist
> **Effort:** m
> **Priority:** critical
> **Depends on:** T12
> **Satisfies REQs:** R1, R3, R4, R7, R11
> **Footprint slice:** New production Compose stack and service-specific configuration
> **High-risk areas touched:** Shared host H; deployment security H; storage H

### Description

Define a standalone production Compose project for the shared VM, using digest image references, persistent named volumes, private dependencies, and scoped secrets. Explicit resource names and a preflight prevent collisions with staging.

### Verification Checklist
- [x] Render Compose with sanitized test inputs; expected: valid configuration, fixed project `launchpad-production`, no development credentials, MinIO, or Mailpit.
- [x] Inspect service environment; expected: Resend only worker, R2 only storage-using services, no secret on web.
- [x] Start isolated stack; expected: service health checks respond correctly and PostgreSQL/Redis volumes persist after container recreation. Application readiness remained unavailable as expected with fake R2 credentials.
- [x] Inspect bindings; expected: only configured web loopback port published; database and Redis unpublished.
- [ ] Run conflict preflight against an occupied port/volume/project name; expected: fail before any mutation. **Deferred to T18 by developer decision.**
- [ ] Verify all deployment operations name this project and no global prune/restart is present. **Deferred to T18 with the deployment controller.**
- [x] Confirm unrelated staging Compose project and volumes are not selected by rendered commands.

### Implementation Notes
- **Module(s):** production runtime/deployment configuration
- **Pattern reference:** `compose.yaml`
- **Key decisions:** A1, A5, A9; port default 18080 only after availability check
- **Libraries:** Compose plugin
- **High-risk callouts:** Same Docker host means Docker access is host-wide; strict command scoping limits accidents, not compromise.

### Scope Boundaries
- Do NOT modify staging Compose files.
- Do NOT include actual production secrets in the repository.

### Files Expected
**New files:**
- `compose.production.yaml`

**Modified files:**
- None

**Must NOT modify:**
- `compose.yaml`, `compose.checks.yaml` (local/check setup)

## Task T14: Implement encrypted database/configuration backups

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T13
> **Satisfies REQs:** R8, R9
> **Footprint slice:** Database/config backup script and failure/retention behavior
> **High-risk areas touched:** Backup/recovery H; secrets H

### Description

Add encrypted Restic backups for a database dump and required protected runtime configuration, invoked weekly and before migrations. Failed or incomplete backups must never prune prior snapshots or report success.

### Test Plan

#### Test File(s)
- New `scripts/tests/test_backup_production.py` or `tests/quality/test_backup_production.py`

#### Test Scenarios

##### Database and Configuration Backup
- Snapshot includes valid database dump, schema/release metadata, config and outbox keys _(verifies R8)_
- Snapshot repository is encrypted and accepts only dedicated backup credentials _(verifies R8, R9)_
- Weekly/pre-migration invocation records kind and database version _(verifies R8)_
- Dump, encryption, R2, or disk failure exits nonzero and does not prune _(verifies R8; ARCH backup failure)_
- Retention preserves snapshots for 30 days and latest successful snapshot _(verifies R8)_
- Isolated restore recovers DB schema and required keys without touching live DB _(verifies R8, R9; ARCH VM loss)_

### Implementation Notes
- **Module(s):** host backup tooling
- **Pattern reference:** `scripts/` quality/operator scripts
- **Key decisions:** A10–A12; Restic
- **Libraries:** pinned Restic tooling and compatible PostgreSQL dump client
- **High-risk callouts:** Keep runtime unlock file protected and independent recovery copy outside VM/R2.

### Scope Boundaries
- Do NOT automatically restore over production.
- Do NOT expose backup credentials to application containers or GitHub Actions.

### Files Expected
**New files:**
- `scripts/backup_production.sh`
- Focused backup script test

**Modified files:**
- None

**Must NOT modify:**
- `apps/api/app/modules/products` (backup does not change product behavior)

## Task T15: Implement bounded media backup snapshots

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** high
> **Depends on:** T14
> **Satisfies REQs:** R8, R9
> **Footprint slice:** Media staging/copy and Restic snapshot behavior
> **High-risk areas touched:** Backup/recovery H; shared disk H

### Description

Extend backup tooling to copy the configured R2 media bucket into a fresh bounded local staging directory and snapshot it weekly. Earlier snapshots must preserve deleted/replaced objects for the 30-day retention period.

### Test Plan

#### Test File(s)
- `scripts/tests/test_backup_production.py` or `tests/quality/test_backup_production.py`

#### Test Scenarios

##### Media Snapshot
- Copy reads only configured production media bucket using read-only identity _(verifies R8, R9)_
- Free-space/byte budget failure aborts before declaring snapshot successful _(verifies R9; ARCH disk failure)_
- Interrupted/partial copy does not create successful snapshot or run retention _(verifies R9)_
- Source deletion after a successful snapshot leaves object in earlier retained snapshot _(verifies R8)_
- Recovery can retrieve historical media without enumerating backup repositories as source _(verifies R9; ARCH VM loss)_
- Run verifies database references can be reconciled; absent copies do not produce false success _(verifies R8)_

### Implementation Notes
- **Module(s):** host media backup
- **Pattern reference:** T14 backup script; Cloudflare R2 rclone guidance
- **Key decisions:** A11, A12; local media staging with disk checks
- **Libraries:** pinned rclone and Restic
- **High-risk callouts:** Weekly snapshots cannot recover objects created and deleted between runs.

### Scope Boundaries
- Do NOT mirror deletions into historical backup snapshots.
- Do NOT back up R2 backup buckets recursively.

### Files Expected
**New files:**
- None (extend `scripts/backup_production.sh` and its tests)

**Modified files:**
- `scripts/backup_production.sh`
- Focused backup tests

**Must NOT modify:**
- Production media API/read paths

## Task T16: Install weekly backup timers

> **Status:** done
> **Verification:** checklist
> **Effort:** s
> **Priority:** high
> **Depends on:** T14, T15
> **Satisfies REQs:** R8, R9
> **Footprint slice:** New host service and timer unit files
> **High-risk areas touched:** Backup/recovery H; shared host M

### Description

Schedule database/configuration and media backups weekly with systemd timers, persistent missed-run handling, and a lock shared with deployments. Installation must leave existing staging units untouched.

### Verification Checklist
- [x] Validate unit syntax; expected: `systemd-analyze verify` succeeds.
- [x] Inspect timer schedule; expected: configurable off-peak UTC weekly schedule and persistent catch-up.
- [x] Start each service in dry-run/test mode; expected: correct backup kind and logs without secret values.
- [x] Hold deployment lock and trigger backup; expected: one operation waits/fails safely, no overlap.
- [x] Install/disable units in isolated systemd test; expected: only Launchpad units change.
- [x] Failed backup reports nonzero and triggers alert/log evidence.

### Implementation Notes
- **Module(s):** host systemd
- **Pattern reference:** existing host/systemd conventions if present; otherwise systemd unit standards
- **Key decisions:** A10–A12
- **Libraries:** systemd
- **High-risk callouts:** Run independently of application scheduler and preserve staging host services.

### Scope Boundaries
- Do NOT reboot the VM or alter staging service units.
- Do NOT activate timers before credentials/key custody are provisioned.

### Files Expected
**New files:**
- `infra/systemd/launchpad-backup-database.service`, `.timer`
- `infra/systemd/launchpad-backup-media.service`, `.timer`

**Modified files:**
- `scripts/backup_production.sh` (timer-specific modes if needed)

**Must NOT modify:**
- Existing systemd units owned by staging or cloudflared

## Task T17: Validate release manifests and persist deployment state

> **Status:** done
> **Verification:** tdd
> **Effort:** m
> **Priority:** critical
> **Depends on:** T13
> **Satisfies REQs:** R2, R3, R6, R11
> **Footprint slice:** Release manifest validation, shared lock, release state
> **High-risk areas touched:** Shared host H; deployment security H

### Description

Implement safe validation for workflow-produced releases and persistent deployment state on the VM. Only fixed private GHCR packages, approved platform, full commit, and verified workflow manifest may proceed; automatic and manual deploys share a lock.

### Test Plan

#### Test File(s)
- New `scripts/tests/test_deploy_production.py`

#### Test Scenarios

##### Manifest and State
- Accept structurally valid release with two digests and verified run identity _(verifies R2)_
- Reject mutable tags, malformed digest, wrong package, wrong platform, or shell metacharacters before Docker command _(verifies R2, R3)_
- Reject divergent commit/run/image/schema identity _(verifies R2)_
- Concurrent invocation cannot mutate state while lock is held _(verifies R6; ARCH overlapping deploy)_
- Failure persists last stage without advancing successful-release pointer _(verifies R6; ARCH disconnect)_
- Secrets never appear in stdout/stderr/state record _(verifies R3, R7)_

### Implementation Notes
- **Module(s):** host deployment controller
- **Pattern reference:** `scripts/` quality shell and operator scripts
- **Key decisions:** A2–A4, A8
- **Libraries:** POSIX/bash plus structured JSON parser already available on VM
- **High-risk callouts:** Validate structured fields and use fixed package names; never evaluate manifest as shell.

### Scope Boundaries
- Do NOT accept arbitrary registry/package from manual input.
- Do NOT store secrets in release manifest.

### Files Expected
**New files:**
- `scripts/deploy_production.sh` (manifest validation and state foundation)
- `scripts/tests/test_deploy_production.py`

**Modified files:**
- None

**Must NOT modify:**
- `scripts/development*` or staging application scripts

## Task T18: Implement maintenance rollout and schema-aware recovery

> **Status:** not started
> **Verification:** tdd
> **Effort:** l
> **Priority:** critical
> **Depends on:** T14, T17
> **Satisfies REQs:** R1, R2, R6, R11
> **Footprint slice:** Deployment script lifecycle, maintenance state, health/recovery docs behavior
> **High-risk areas touched:** Schema/rollout H; shared host H; backup H

### Description

Extend the locked controller to pull images before maintenance, back up before migration, stop writers, migrate, start the exact release, and verify readiness and fresh process health. Restore old images only if the schema is unchanged; otherwise retain maintenance and report operator recovery requirements.

### Test Plan

#### Test File(s)
- `scripts/tests/test_deploy_production.py`
- New `tests/quality/test_production_deployment.py` for repository-side contracts

#### Test Scenarios

##### Rollout and Recovery
- Image pull failure occurs before maintenance; current release stays running _(verifies R2; ARCH image pull)_
- Failed pre-migration backup blocks writers/migration changes _(verifies R6, R8)_
- Success follows maintenance → writers stopped → migration → services start → health → pointer update _(verifies R6)_
- Unchanged schema failure restores previous digest set and checks health _(verifies R6; ARCH rollback)_
- Changed/unknown schema failure leaves maintenance and does not auto-downgrade _(verifies R6)_
- Worker/scheduler check uses fresh health command, not historical logs _(verifies R11)_
- Public and local readiness retry to fixed deadline; failure keeps stage visible _(verifies R1, R6)_
- No previous release leaves initial failed deployment safely in maintenance _(verifies R6)_

### Implementation Notes
- **Module(s):** deployment controller, web maintenance, migration/health orchestration
- **Pattern reference:** ARCH rollout lifecycle; `apps/worker/* --health`; readiness endpoint
- **Key decisions:** A8; no zero-downtime claim
- **Libraries:** existing Compose, curl, flock
- **High-risk callouts:** Compare actual DB revision after failure before any image rollback.

### Scope Boundaries
- Do NOT restore database automatically over production.
- Do NOT issue global Docker cleanup/restart commands.

### Files Expected
**New files:**
- `tests/quality/test_production_deployment.py`

**Modified files:**
- `scripts/deploy_production.sh`
- `infra/docker/web.production.conf`
- `scripts/tests/test_deploy_production.py`

**Must NOT modify:**
- `apps/api/app/shared/db/database.py` exact-head contract
- `apps/worker/scheduler.py`, `health.py` progress contract

## Task T19: Add automatic GHCR build and production deployment workflow

> **Status:** not started
> **Verification:** checklist
> **Effort:** l
> **Priority:** critical
> **Depends on:** T12, T16, T18
> **Satisfies REQs:** R1, R2, R3, R6, R7
> **Footprint slice:** Production GitHub Actions image build/publish/deploy workflow
> **High-risk areas touched:** Supply chain H; deployment secrets H

### Description

Add a protected automatic `main` pipeline that runs quality checks, builds amd64 Python/web images, publishes both private GHCR images by digest, creates a structured manifest, and deploys the same workflow release through Access-protected SSH. PRs and `dev` pushes never deploy.

### Verification Checklist
- [ ] Validate workflow syntax and action pinning; expected: workflow parser passes with pinned actions/tools.
- [ ] Simulate PR and `dev` events; expected: tests only, no secrets and no deploy job.
- [ ] Simulate failed quality/build; expected: no publish/deploy.
- [ ] Simulate successful `main` run; expected: two private packages, digests and manifest share commit/run identity.
- [ ] Inspect token permissions; expected: package write only in build job, environment secrets only in deploy job.
- [ ] Stub SSH; expected: Access token plus key, strict known-host checking, nonzero on failure, cleanup of temporary credential files.
- [ ] Run concurrent main updates; expected: one deployment at a time and deployed artifact matches its verified run.
- [ ] Confirm workflow logs redact secrets and never print environment.

### Implementation Notes
- **Module(s):** GitHub Actions
- **Pattern reference:** `.github/workflows/quality.yml`; staging workflow supplied by user
- **Key decisions:** A2–A4; private packages and service-token SSH
- **Libraries:** pin action SHAs and cloudflared checksum per ARCH
- **High-risk callouts:** Never interpolate secrets into shell source or use `StrictHostKeyChecking no`.

### Scope Boundaries
- Do NOT execute deployment from PRs or `dev`.
- Do NOT put runtime/R2/backup secrets in GitHub Actions.

### Files Expected
**New files:**
- `.github/workflows/production-deploy.yml`

**Modified files:**
- `.github/workflows/quality.yml` (only if shared build/check reuse requires a safe adjustment)

**Must NOT modify:**
- `.github/workflows` staging workflows in the separate National Ag Exchange repository

## Task T20: Add protected R2 validation workflow

> **Status:** not started
> **Verification:** test-after
> **Effort:** m
> **Priority:** high
> **Depends on:** T9, T10, T11, T13
> **Satisfies REQs:** R4, R5, R10, R11
> **Footprint slice:** R2 validation tool and protected cloud integration workflow
> **High-risk areas touched:** Storage H; cloud secrets H

### Description

Provide an explicit protected integration path using dedicated validation credentials and a separate private R2 bucket. Standard PR quality checks continue using MinIO without cloud secrets.

### Test Plan

#### Test File(s)
- `tests/integration/test_r2_validation.py` (credential-gated, explicit invocation)
- `scripts/tests/test_validate_r2.py`

#### Test Scenarios

##### Provider Validation and Safety
- Validation covers signed/proxied upload, finalize, private read, deletion, and health probe _(verifies R4, R5, R10)_
- Wrong bucket/account or absent validation flag refuses to run _(verifies R10)_
- Cleanup removes only generated validation key prefixes _(verifies R10)_
- Missing R2 credentials skips only explicitly gated integration and does not turn ordinary quality green by omission _(verifies R10, R11)_
- Untrusted pull request has no cloud credentials _(verifies R10)_
- Production bucket identifier cannot be selected as validation target _(verifies R10)_

### Implementation Notes
- **Module(s):** storage integration/CI
- **Pattern reference:** `tests/integration/test_storage.py`, shared quality gate
- **Key decisions:** A13; protected R2 separate from production and MinIO
- **Libraries:** existing boto3 and GitHub environment protection
- **High-risk callouts:** Never allow automated cleanup outside validation-owned keys.

### Scope Boundaries
- Do NOT put cloud secrets in ordinary PR workflow.
- Do NOT run destructive checks against production bucket.

### Files Expected
**New files:**
- `scripts/validate_r2.py`
- `scripts/tests/test_validate_r2.py`
- `tests/integration/test_r2_validation.py`
- `.github/workflows/r2-validation.yml`

**Modified files:**
- `scripts/quality/run.sh` only to define a clearly separate protected integration invocation, if needed

**Must NOT modify:**
- Existing MinIO-only pull request service credentials/configuration

## Task T21: Record deployment ADR and operator runbooks

> **Status:** not started
> **Verification:** checklist
> **Effort:** m
> **Priority:** high
> **Depends on:** T16, T18, T20
> **Satisfies REQs:** R1-R10
> **Footprint slice:** Deployment ADR, deployment guide, recovery guide, development docs
> **High-risk areas touched:** Backup/recovery H; shared host H

### Description

Document the final production decisions, VM/tunnel prerequisites, secret provisioning, automatic pipeline, weekly backups, and operator-led recovery. Align the earlier deployment guide with the decisions confirmed during architecture planning.

### Verification Checklist
- [ ] Compare guide against `compose.production.yaml` and workflow; expected: no obsolete VM-build/direct-R2-upload instructions.
- [ ] Follow clean-room preflight as an operator; expected: tunnel, port, GHCR, secret, and backup prerequisites are explicit.
- [ ] Follow database and media restore runbooks in isolated target; expected: commands, key custody, reconciliation, and data-loss window are clear.
- [ ] Confirm architecture ADR documents MinIO/R2, shared host risk, CI image build, upload boundary, and schema-aware recovery.
- [ ] Verify no real credentials or private key material appears in documentation.

### Implementation Notes
- **Module(s):** engineering docs and ADR
- **Pattern reference:** `docs/adr/0001-*` through latest; `docs/development.md`
- **Key decisions:** all A1–A13
- **Libraries:** documentation only
- **High-risk callouts:** State the shared Docker host and weekly media recovery gap plainly.

### Scope Boundaries
- Do NOT claim production readiness until operator checks and restoration evidence exist.
- Do NOT alter the confirmed schedule/frequency or credential arrangement.

### Files Expected
**New files:**
- `docs/adr/0007-production-deployment-storage.md` (or next free number)
- `docs/PRODUCTION_RECOVERY.md`

**Modified files:**
- `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md`
- `docs/development.md`

**Must NOT modify:**
- Product requirements/architecture except task metadata row

## Task T22: Integrate checks and record evidence

> **Status:** not started
> **Verification:** checklist
> **Effort:** m
> **Priority:** high
> **Depends on:** T1-T21
> **Satisfies REQs:** R1-R11
> **Footprint slice:** Cross-feature quality gate and implementation evidence
> **High-risk areas touched:** All M/H Areas of Impact

### Description

Run the integrated local and protected provider checks, verify generated contracts/images and deployment safety, and record evidence without implying unperformed VM/R2 recovery checks passed. This task produces the implementation evidence artifact used before independent review and QA.

### Verification Checklist
- [ ] Run `sh scripts/quality/run.sh`; expected: every configured quality category passes with local MinIO and no cloud secrets.
- [ ] Build production Python/web images; expected: successful amd64 images with digest and no baked secrets.
- [ ] Validate production Compose render; expected: fixed project, no MinIO/Mailpit, correct secret scopes, no unexpected published ports.
- [ ] Run migration suite and old-data profile-photo regression; expected: forward migration and existing media preserved.
- [ ] Exercise profile/product upload end-to-end locally via MinIO, including rejection/retry/private-read behavior.
- [ ] Run deployment script failure injection; expected: no staging/global changes, correct maintenance and schema-aware recovery.
- [ ] Run backup and isolated restoration evidence; expected: encrypted database/config and historical media recover with separate keys.
- [ ] Run protected R2 validation if credentials/config are provisioned; otherwise mark it pending with exact missing operator input.
- [ ] Run tunnel/host deployment only when operator provisioned SSH, Access, verified host key, tunnel, and VM inputs; otherwise mark pending honestly.
- [ ] Save a dated verification record with commands, results, image digests, migration head, and unresolved external checks.

### Implementation Notes
- **Module(s):** project integration and operational verification
- **Pattern reference:** `scripts/quality/run.sh`, existing QA results artifact conventions
- **Key decisions:** A1–A13
- **Libraries:** existing quality and deployment tools
- **High-risk callouts:** A local green gate is not production R2, tunnel, or restore evidence.

### Scope Boundaries
- Do NOT deploy to production without operator-provisioned infrastructure and a deliberate deployment execution.
- Do NOT replace independent review or manual QA.

### Files Expected
**New files:**
- Dated deployment verification/evidence document under `specs/qa/`

**Modified files:**
- `.github/workflows/quality.yml`, `scripts/quality/run.sh` only for explicitly required integrated checks

**Must NOT modify:**
- Existing staging services or unrelated product feature code

---

Dependency summary: T1–T3 and T4 can start independently; T5/T6 converge at T7. T8/T9 then feed runtime wiring and production image setup. Migration and deployment foundations precede Compose, backups, and workflow rollout. T22 closes only after the preceding task evidence is recorded.
