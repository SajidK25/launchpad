# Architecture: Deploy Launchpad Production on Proxmox

> **Date:** 2026-10-09
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** Standalone brief — `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md`; see Inferred Requirements and confirmed architecture interview decisions
> **Tasks:** TASKS-deploy-proxmox-production.md
> **Type:** infrastructure

## Architecture Summary

Run Launchpad on the existing shared Ubuntu 24.04.4 x86-64 Proxmox VM at `192.168.0.98`, with isolated Compose resources and public access through Cloudflare Tunnel at `launchpad.t99ltd.com`. GitHub Actions builds private GHCR images and automatically deploys the exact verified image digests from `main` through service-token-protected SSH. Retain MinIO for local development while adapting production storage to private R2, with authenticated, bounded API uploads instead of direct browser-to-R2 uploads. Use maintenance deployments, schema-aware recovery, and encrypted weekly backups with additional database/configuration backups before migrations. This architecture supersedes the source guide's earlier VM builds, direct R2 PUT proposals, and dedicated-VM assumptions; it does not implement launch scheduling or publication.

## Inferred Requirements (if Mode B / no REQ)

These IDs capture the brief and subsequently confirmed decisions, rather than inventing a separate product requirements document.

| ID | Inferred Requirement | Source |
|---|---|---|
| R1 | Deploy at `https://launchpad.t99ltd.com` on the shared VM without a public IP and preserve existing staging services. | Brief; shared-host confirmation |
| R2 | Build on GitHub Actions, publish private GHCR images, automatically deploy verified `main` releases by immutable digest. | Build, automatic-release, registry confirmations |
| R3 | Authenticate deployment using an Access service token and SSH key; verify SSH host identity; separate registry pull credentials. | Credential confirmations |
| R4 | Support MinIO locally and private R2 in production without cloud credentials in normal CI. | Storage decision |
| R5 | Route production uploads through an authenticated API enforcing existing byte limits before R2 storage, preserving ownership and finalization behavior. | Upload boundary and footprint confirmations |
| R6 | Permit maintenance windows and stop writers for migration; automatically restore images only when schema is unchanged. | Maintenance/recovery confirmations |
| R7 | Keep runtime secrets in protected service-specific VM files, separate from source, images, and CI. | Secret storage confirmation |
| R8 | Back up PostgreSQL and runtime configuration weekly and before migrations; back up media weekly; encrypt and retain snapshots for 30 days. | Backup confirmations |
| R9 | Use separate backup credentials and buckets, Restic, local media staging with disk checks, and independent recovery-key custody. | Backup tool and final summary confirmations |
| R10 | Verify production compatibility using a separate private R2 validation bucket and protected credentials. | Verification confirmation |
| R11 | Preserve existing profiles, product review, private media, notifications, local development, and shared-host workloads. | Brief and confirmed scope |

## High-Level Structure

```text
GitHub: SajidK25/launchpad (main)
  quality gate -> linux/amd64 builds -> private GHCR -> release manifest
                                                       |
GitHub-hosted deploy runner -- Access token + SSH key --+
                                                       v
Shared Proxmox VM 192.168.0.98
  /srv/launchpad: deployment controller, manifests, release state, locks
  /etc/launchpad: service-specific secrets and backup configuration
  launchpad-production Compose project
    web -> api -> PostgreSQL / Redis / private R2
           worker -> PostgreSQL / Redis / R2 / Resend API
           scheduler -> PostgreSQL / Redis
    migration service -> PostgreSQL
  systemd timers -> encrypted backups -> private R2 backup repositories

Visitors -> Cloudflare Tunnel -> loopback web ingress -> frontend/API/WebSockets
Browser media upload -> same-origin API -> bounded temporary file -> R2 staging
Local browser upload -> existing signed MinIO form -> MinIO staging
Both -> existing completion action -> validation -> private clean media
```

The application retains its modular monolith and separate API, worker, and scheduler processes. PostgreSQL remains authoritative. No application service gains Docker access. Host deployment/backup operations are distinct from domain scheduler work.

The web binding is proposed as `127.0.0.1:18080`; a preflight must prove availability. Existing tunnel reuse depends on its management mode and reachability, which cannot be inspected from the current workstation because the operator SSH key is on another machine. No production or tunnel action has been performed during planning.

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|---|---|---|---|
| Runtime | Existing Docker images, Ubuntu 24.04 x86-64, `linux/amd64` | New VM/provider or different CPU target | Matches confirmed available shared host |
| Image delivery | Two private GHCR packages, digest-pinned | VM builds, floating tags | Avoid production build load and make releases reproducible |
| CI | GitHub-hosted Actions; existing shared quality gate | Self-hosted runner | Follows the user's established tunnel deployment model |
| SSH ingress | Access Service Auth token plus dedicated key and pinned host key | Everyone/Bypass | Adds an independent gate before SSH authentication |
| Storage | Configured MinIO/R2 provider with shared S3 object operations | R2-only development, unchanged endpoint substitution | Keeps isolated development while addressing real provider differences |
| Production uploads | Raw-body API transfer with bounded temporary file | Direct signed R2 PUT | Preserve ingress byte limits before objects reach storage |
| Release handling | Maintenance and coordinated application restart | Mixed-version rolling deployment | Current application requires exact Alembic head |
| Backup | Restic repositories over S3; rclone for media staging | Plain mirrored copies | Encrypted historical snapshots preserve earlier object versions |
| Backup scheduling | Dedicated host systemd timers | Application scheduler | Recovery operations remain independent of the application release |

R2 compatibility is grounded in [Cloudflare's S3 operation support](https://developers.cloudflare.com/r2/api/s3/api/): current bucket-policy probes cannot be reused. Browser-form POST is unsupported by R2, as documented under [presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/). The chosen authenticated API upload path removes the need for production browser-to-R2 CORS or upload DNS. Restic retention semantics must follow its [official retention documentation](https://github.com/restic/restic/blob/master/doc/060_forget.rst); rclone's [R2 integration](https://developers.cloudflare.com/r2/examples/rclone/) supports the staging copy.

## Patterns & Conventions

- **Thin transports:** product/user services authorize and coordinate uploads; repositories own upload metadata. Shared storage code does not import feature repositories.
- **Provider configuration:** one codebase, explicit provider and region, no fallback from broken production R2 to development storage.
- **Generated contracts:** OpenAPI remains the source for frontend upload types; no hand-maintained replacement types.
- **Bounded operations:** byte counting, finite transfer deadlines, upload slots, bounded storage SDK retries, and safe errors protect the shared VM.
- **Release identity:** commit SHA plus Python/web image digests and schema head identify a release; tags are informational.
- **Project isolation:** every Compose command uses `launchpad-production`, explicit production configuration, and stable named volumes. No host-wide prune, network teardown, or restart.
- **Forward-compatible migrations:** add a new revision; never edit applied migrations. Record production constraints in an ADR as required by `AGENTS.md`.

## Data Models

### Profile upload metadata

**Purpose:** retain authoritative intent limits for authenticated byte transfer, which the current `photo_uploads` record does not preserve.

| Field | Type / Constraint | Notes |
|---|---|---|
| Existing ID/account/staging key/expiry/state | Existing constraints retained | Feature-owned authorization and lifecycle |
| `declared_byte_count` | Nullable integer, when present 1..5,242,880 | New intents always populate; legacy records may lack it |
| `declared_media_type` | Nullable supported image type | New intents always populate; distinguish declaration from validated output |
| Existing clean key/byte count/media type | Existing validated-result fields | Do not repurpose these fields as declarations |

**Relationships:** existing account foreign key is unchanged.

**Lifecycle:** intent pending -> bounded transfer -> existing completion -> cleaned; expired intents remain unusable. Legacy pending intents without declarations cannot use the new R2 transfer endpoint and return a safe conflict prompting a new intent. Existing completed photos remain valid. Local legacy completion behavior is retained where safe; no migration deletes user media.

### Product assets

Existing pending assets already retain declared size, media type, expiry, and owner through their product. Reuse these for transfer authorization. No additional product-state transition or product table is needed for this design. Once clean, transfer is forbidden; existing byte/type fields continue to represent validated output after finalization.

### Release manifest and deployment state

**Purpose:** bind deployment/recovery to verified release artifacts, outside the application database.

| Field | Type / Constraint | Notes |
|---|---|---|
| Commit | Full hexadecimal Git SHA | Must correspond to the successful pipeline |
| Python/web images | Approved GHCR package plus `sha256` digest | Reject other registries, mutable tags, and malformed references |
| Platform | `linux/amd64` | Matches VM |
| Schema revision | Single expected migration head from built release | Compared with actual database before/after migration |
| Workflow run identity | Repository, run ID, attempt | Traceability and manual redeployment verification |
| Deployment state | Release ID, previous ID, stage, timestamps | Persist atomically after each material phase; successful pointer only after readiness |
| Backup reference | Repository/snapshot identifiers, no secrets | Links pre-migration recovery material |

**Lifecycle:** built -> verified -> transferred -> preparing -> maintenance -> migrated -> starting -> healthy, or failed with last known stage retained. Serialize automatic/manual deployments using one VM lock. Manual redeployment accepts a previously verified manifest, never arbitrary image inputs.

### Backup snapshots

Separate encrypted Restic repositories for database/configuration and media. Snapshots carry stable host/path grouping, snapshot kind, release/schema metadata, and completion timestamp. Weekly and pre-migration database snapshots include a restorable database dump and protected runtime configuration, including outbox keys. Retain at least all snapshots within the latest 30-day window and the latest successful snapshot; failed backup runs do not prune. This is a minimum recovery window, not an exact-to-the-second deletion guarantee.

Media staging is recreated for each successful run and preserves object-key paths in the encrypted snapshot. Live deletions can disappear from a new snapshot, but previous snapshots retain those objects for the retention window. An object created and deleted between weekly snapshots is not recoverable from that schedule. The snapshot process is not a cross-service atomic point-in-time backup; restoration must reconcile database references with available media snapshots and live objects.

## API Contracts / Interfaces

### Upload intent and transfer

**Boundary:** authenticated REST; existing create-intent and complete endpoints remain.

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| POST | `/api/v1/me/profile/photo-uploads` | Create declared profile intent | Existing response plus explicit transfer metadata |
| POST | `/api/v1/me/products/{product_id}/assets` | Create declared product intent | Existing response plus explicit transfer metadata |
| PUT | `/api/v1/me/profile/photo-uploads/{upload_id}/content` | Transfer raw bytes to R2 staging through API | 204; safe 401/403/404/409/413/415/429/503 errors |
| PUT | `/api/v1/me/products/{product_id}/assets/{asset_id}/content` | Transfer owned editable-product bytes | Same errors and 204 semantics |
| POST | Existing `.../{id}/complete` endpoints | Validate/promote private staged image | Existing completion response and idempotent successful completion |

Intent responses retain `upload_url`, `fields`, `expires_in`, and their current ID field. Add `upload_method` (`POST` or `PUT`), `upload_transport` (`storage_form` or `authenticated_api`), and required non-secret headers. MinIO returns its existing POST URL and fields; R2 returns a relative same-origin API path, PUT, empty fields, and the declared content type. No R2 credential or direct object upload URL reaches the browser.

**Auth requirements:** active owning account, existing product edit eligibility, Origin and CSRF checks for API transfer. Transfer metadata never grants authority independently of the session. CSRF tokens are supplied through existing identity state, not persisted in upload instructions. The client sends credentials only to the authenticated same-origin path and omits cookies/CSRF on external MinIO form uploads.

**Transfer coordination:** authenticate and inspect the intent before accepting bytes; buffer with a finite deadline and byte-count limit of the declared maximum, capped at 5 MiB, regardless of `Content-Length`. Use a per-process semaphore with explicit finite limits and return retryable overload errors rather than queue indefinitely. After buffering, acquire the feature's row locks, recheck session/account eligibility, expiry, ownership, and state, then perform the bounded R2 staging write while that feature operation owns its locks. Never hold a database transaction while waiting for a slow browser body. Product transfer and completion use the existing account/product/asset lock order; profile transfer and completion use the same profile-upload row locking discipline. Rate-limit prior to body buffering.

Only staging objects may be overwritten by a retry while pending. A successful transfer is not completion; image decoding/type validation and metadata stripping remain in completion. An R2 write followed by a database failure may leave a staging object; retry and existing expiry cleanup must handle it. Finalization is serialized with transfer; once finalized, a delayed transfer must be refused before any write. Local signed-form uploads remain bounded by their existing policy and late-staging cleanup.

### Internal storage and service interfaces

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| Storage configuration | Provider, region, endpoint, bucket, credentials | Select `minio`/`r2`; local `us-east-1`, R2 `auto` | Invalid production config fails startup |
| Storage staging write | `put_staging(object_key, bounded_file, content_type)` | Provider-neutral private S3 write | Typed safe storage error; never arbitrary caller-provided keys |
| Bounded receiver | Shared upload reader accepting stream, limit, deadline | Count/spool bytes outside feature transaction | Closed temp file on all exits; size/timeout/overload errors |
| Feature transfer | Product/Profile service transfer operation | Recheck authority and coordinate repository/storage | Typed domain errors mapped by routes |
| Storage readiness | Existing probe interface with provider support | Supported metadata call such as permitted `HeadBucket` for R2 | Denied/unavailable remains unhealthy; no policy calls on R2 |
| Migration | `python -m app.migrate` | Reuse serialized PostgreSQL migration helper only | Nonzero on failure; no storage administration |

The R2 runtime probe verifies access, not bucket privacy. Provisioning checks use the dashboard/control plane to establish disabled public access, independently of runtime credentials. Preserve existing application-mediated private reads; do not switch media reads to public bucket URLs.

### Deployment and backup boundaries

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| Deploy | `scripts/deploy_production.sh <release-manifest-path>` | Validate, lock, pull, back up, migrate, start, verify | Nonzero plus safe stage/result record |
| Backup | `scripts/backup_production.sh <database-or-media> <reason>` | Encrypted weekly/pre-migration recovery snapshot | Snapshot reference only after success |
| Restore guidance | `docs/PRODUCTION_RECOVERY.md` | Operator-led isolated restore/reconciliation | Never implicit destructive database rollback |
| Local readiness | `/api/v1/health/ready` through loopback web ingress | Dependencies and matching schema | Existing safe readiness response |
| Public readiness | Same endpoint at public hostname | Verify tunnel plus application | Bounded retries and deadline |

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|---|---|---|
| Products | Product intent/transfer/completion authorization and state | Its repository, named member access service, shared storage/upload interfaces |
| Users | Profile intent/transfer/completion authorization and state | Its repository, existing member/session interfaces, shared storage/upload interfaces |
| Shared storage | S3 object operations and provider-aware client/probe construction | SDK/configuration; no feature repositories |
| Shared uploads | Bounded byte intake, temporary resources | Transport stream abstraction; no product decisions |
| Frontend upload helper | Execute generated transfer instruction safely | Identity CSRF accessor and generated API types |
| Deployment controller | Image/manifest validation, service coordination and release state | Docker/Compose, protected VM config, backup entry point |
| Backup host services | Snapshot scheduling, copying, encryption, retention | Read-only media access, backup repositories; no application credentials in CI |

## Change Footprint

### New files / modules

| Path | Purpose | Pattern reference |
|---|---|---|
| `.github/workflows/production-deploy.yml` | Gate, image builds/publication, manifest, authenticated deployment | Existing quality workflow and supplied staging workflow |
| `.github/workflows/r2-validation.yml` | Protected validation against separate R2 bucket | Existing quality gate isolation |
| `compose.production.yaml` | Digest images, stable volumes, explicit secrets, no MinIO/Mailpit | Existing Compose service commands |
| `scripts/deploy_production.sh` | Locked release controller and schema-aware recovery | Supplied staging script, redesigned for production |
| `scripts/backup_production.sh` | Database/config and media backup modes | Confirmed Restic design |
| `scripts/validate_r2.py` | Bounded compatibility checks using validation-owned keys | Existing storage integration boundaries |
| `infra/systemd/launchpad-backup-database.service`, `.timer` | Weekly database/config backup | Host systemd convention |
| `infra/systemd/launchpad-backup-media.service`, `.timer` | Weekly media backup | Host systemd convention |
| `infra/docker/web.production.conf` | Production proxy, maintenance, raw-body size/time controls | Existing `web.conf` |
| `apps/api/app/migrate.py` | Production DB-only preparation entry point | `bootstrap.py` and `Database.prepare` |
| `apps/api/app/shared/storage/uploads.py` | Bounded upload receive resources | Shared typed storage errors |
| `apps/web/src/uploads/client.ts` | Common generated-instruction executor | Existing product/profile upload clients |
| `apps/api/alembic/versions/0011_profile_upload_declarations.py` | Add declared profile metadata; use next available revision if numbering advances | Existing forward migrations |
| `docs/adr/0007-production-deployment-storage.md` | Record deployment, contracts, privacy, and recovery decisions | Existing ADR convention; use next free number |
| `docs/PRODUCTION_RECOVERY.md` | Backup key custody, restore, reconciliation, incident operation | Existing operational documentation |
| `tests/integration/test_production_uploads.py`, `tests/quality/test_production_deployment.py` | Verification surfaces for later task design | Existing integration/quality organization |

### Modified files / modules

| Path | What changes here |
|---|---|
| `apps/api/app/shared/config/settings.py` | Provider/region, production endpoint validation, bounded upload settings; R2 path does not require a browser storage endpoint |
| `.env.example`, `compose.yaml`, `compose.checks.yaml` | Document/wire local provider defaults while retaining isolated MinIO |
| `apps/api/app/main.py` | Construct provider-aware storage/probes/upload resources |
| `apps/api/app/shared/storage/objects.py` | Transfer instructions and bounded server-side staging writes; keep validation/private reads |
| `apps/api/app/shared/storage/client.py` | R2-compatible bounded readiness |
| `apps/api/app/bootstrap.py` | Explicit local-only provisioning guard; production uses migration entry point |
| `apps/api/app/modules/users/models.py` | Declared profile upload fields |
| `apps/api/app/modules/users/repository.py` | Persist declarations and lock/recheck pending upload records |
| `apps/api/app/modules/users/service.py` | Own profile transfer/finalization authorization and coordination |
| `apps/api/app/modules/users/routes.py`, `schemas.py` | Raw-byte endpoint, safe errors, additive intent contract |
| `apps/api/app/modules/products/routes.py`, `schemas.py` | Product raw-byte endpoint and additive intent contract |
| `apps/api/app/modules/products/service.py`, `repository.py` | Pending-state transfer coordination using existing ownership and lock conventions |
| `apps/web/src/products/client.ts`, `useProducts.ts` | Pass full upload instructions to common executor |
| `apps/web/src/profiles/ProfileScreens.tsx`, `client.ts` | Move hardcoded form transfer into common executor |
| `packages/contracts/openapi.json`, `src/generated.ts` | Regenerate intent/transfer contracts |
| `apps/worker/worker.py` | Provider-aware storage client and explicit required secrets |
| `infra/docker/web.Dockerfile`, `python.Dockerfile` | Reproducible image build/production configuration and runtime permissions |
| `.github/workflows/quality.yml`, `scripts/quality/run.sh` | Preserve PR/dev coverage and incorporate meaningful new checks without bypass |
| Existing storage/config/user/product tests and frontend upload checks | Adjust changed constructor/contracts and protect both providers |
| `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md`, `docs/development.md` | Align with final architecture, GHCR, shared VM, API upload, weekly backups |

### Deleted / replaced

| Path | Reason |
|---|---|
| No existing files deleted | Local stack and unrelated features remain supported |
| Profile screen's inline form-only transfer | Replaced by common upload executor |
| Source guide's direct R2 browser upload/VM build proposals | Superseded by confirmed API transfer and CI-build decisions |

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|---|---|
| `apps/api/app/shared/storage/provision.py` | Local MinIO administrative operations must never run against R2 |
| `apps/api/app/shared/db/database.py` | Exact migration head drives maintenance and rollback constraints |
| `apps/api/app/shared/security/csrf.py`, `rate_limit.py` | New byte endpoints must enforce existing request security |
| `apps/web/src/identity/client.ts` | Existing CSRF state must be reused, not copied into a second token store |
| `apps/api/app/modules/products/permissions.py` | Existing editable-state/owner policies apply at transfer time |
| `apps/api/app/shared/events/dispatcher.py` | Deferred purge and notifications must still use correct provider wiring |
| `apps/worker/scheduler.py`, `health.py` | Coordinated rollout and fresh progress checks, not historical logs |
| `infra/docker/web.conf` | Local routing must continue to work independently of production configuration |
| `scripts/quality/contracts.sh` | Generated contracts remain authoritative |
| `tests/integration/test_storage.py`, `test_bootstrap.py`, `test_startup_order.py` | Local provisioning/startup assumptions |
| `tests/integration/test_product_deletion.py`, `test_profile_privacy.py`, `test_notification_live.py` | Cleanup, privacy, and tunnel/live regressions |

## Areas of Impact

| Area | Impact | Risk (L/M/H) | Why |
|---|---|---|---|
| Shared production host | Deployment/backup operations alongside staging | H | Docker account can control other workloads; strict command scoping is essential |
| Upload security | New authenticated byte routes and buffer lifecycle | H | Authorization, replay, resource exhaustion, and races |
| Storage | R2 operation support and private access | H | Successful local emulation does not prove R2 compatibility |
| Schema/rollout | Profile fields and exact-head guard | H | Old images may refuse a changed schema |
| Backup/recovery | Historical media, encrypted secrets, restore | H | Unverified restore or lost key makes backups ineffective |
| Frontend/contracts | New upload instructions | M | Both product and profile clients must ship together |
| Notifications/background work | Provider wiring and maintenance interruption | M | Purges and emails must retry correctly |
| Local development | Preserve existing MinIO and disposable configuration | M | Provider changes must not introduce cloud dependency |
| Public product behavior | No new scheduling/publication functionality | L | Separate feature remains outside this deployment scope |

**Contract changes:** additive upload intent fields and new raw-body PUT endpoints; generated frontend clients and consumers change together. No GraphQL contract or notification event change is intended. Deployment manifest is a new operator interface.

**Cross-cutting ripples:** authentication/CSRF, rate limiting, schema migration, configuration, outbox cleanup, generated contracts, image provenance, telemetry, backup keys, and production recovery.

## Cross-Cutting Concerns

- **Errors:** safe typed domain/storage errors mapped consistently; size rejection is 413, stale/expired state is conflict, overload is retryable, and storage unavailability never becomes a false success. Failed deployments preserve maintenance/stage records and do not erase evidence.
- **Logging & metrics:** record release digest/commit, stage, timings, readiness outcome, last successful backup age, upload rejection class, and storage latency. Never log file content, cookies, credentials, signed form fields, object URLs, or private object keys. Backup logs report counts/bytes and snapshot IDs, not raw configuration.
- **Auth / authz:** existing owner policies and active account checks apply to both transfer and completion. GitHub `production` environment permits `main`, with automatic deployment and no required human approval. Validation environment secrets remain unavailable to untrusted PR code. SSH uses Access service token plus dedicated key; verified host key is mandatory.
- **Performance:** use finite body/storage deadlines, max 5 MiB accepted bytes per upload, bounded concurrency, SDK work off the event loop, and disk-budget checks before media backup. Exact upload timeout/concurrency defaults are configurable operational values; choose conservative values during task implementation and document their resource budget. Do not assert the separate launch-volume target is met by this deployment alone.
- **Security:** runtime R2 credentials access only the production media bucket; backup credentials access separate repositories. A machine-account registry credential must actually have read permission on both private packages, not merely the token scope. CI publishes with repository `GITHUB_TOKEN`. Deployment secrets are step-environment inputs, never shell-source interpolation. The operator key on another machine is not reused as the CI key.
- **Migrations / rollout:** Python image shared by API/worker/scheduler/migrate. Pull both images before maintenance. Stop writers/background work, complete an encrypted pre-migration backup, migrate under the existing PostgreSQL preparation lock, start all application services, and verify schema/readiness/progress. Compare actual database revision after any failure; if revision is changed or unknown, no automatic image rollback. Initial deployment without a previous release remains failed/maintenance on failure.

### Production routing and maintenance

Use one web ingress for React, REST, GraphQL, and WebSockets. Configure a maintenance marker accessible to the web container: public user routes return a safe maintenance response while the deployment controller probes private readiness. Keep the readiness route available for the required public tunnel check without reopening ordinary writes. Set maintenance before draining/stopping application processes. Existing sockets are terminated by API restart and reconnect afterward.

Raw-body endpoint limits exist in both Nginx and application code. Trust forwarded HTTPS metadata only on the controlled connector path; forwarded header trust must match actual connector placement. Never cache authenticated/private-media responses. Production browser upload instructions use the app origin; R2 endpoint and region remain backend settings.

### Release pipeline and controller

Repository: `https://github.com/SajidK25/launchpad.git`. Packages: `ghcr.io/sajidk25/launchpad-api` and `ghcr.io/sajidk25/launchpad-web`, both private. Build jobs run after the shared gate and validate built image startup/contracts before declaring the manifest verified. Pin third-party actions/tool versions and base-image digests through reviewed updates.

Deploy job consumes artifacts from the same successful workflow execution. Protect against arbitrary manifest shell content by structured validation and fixed package names. The VM pull account has `read:packages`; CI has only the needed publish permission in the build job and SSH secrets in the production deploy job. Reject unsupported platform, missing digests, and divergent release/schema identities before maintenance. Automatic and manual operations share a lock; an interrupted SSH connection must leave a recorded stage that an operator can recover. No claim of zero downtime is made.

### Backups and key custody

Weekly host timers run even when the application scheduler is stopped, with persistent missed-run handling and a shared lock preventing overlap with deployments. Pre-migration database/configuration backup failure blocks migration. Database dump tooling must match the running PostgreSQL major version. Backup artifacts include release/schema identifiers and enough role/configuration information to rebuild the database. Restore does not automatically overwrite a live database.

Use a fresh bounded local media staging directory for each run, populated from R2 with read-only media credentials. Free-space checks and a configured staging byte budget protect the shared filesystem. Do not upload an incomplete copy as a successful backup; skip retention on failure. Back up only from the declared media bucket; never recursively include backup buckets. Apply retention through Restic, not an R2 lifecycle rule deleting repository pack objects.

Unattended backups require a protected runtime Restic password on the VM. Keep an independently verified recovery copy outside both the VM and R2, and outside any archive that requires that same password to decrypt. Protected VM credentials do not provide isolation from compromise of the Docker host; the accepted shared-host risk also applies to backups. Recovery exercises must use an isolated target and check database/media references, restored outbox keys, and application readiness.

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|---|---|---|---|
| A1 | Shared VM with explicit Launchpad resource names | Dedicated VM | User selected existing host and accepted Docker-wide access | R1, R11 |
| A2 | CI builds private digest-pinned GHCR images | VM builds, tags | Reproducible deployment with less VM load | R2 |
| A3 | Automatic verified `main` releases | Manual approval each time | Confirmed release policy | R2 |
| A4 | Access token + SSH key + host-key pin | Bypass + SSH alone | Independent deployment authentication and host identity | R3 |
| A5 | MinIO locally, private R2 production | One provider everywhere | Offline/isolated development plus chosen production storage | R4 |
| A6 | Authenticated bounded API uploads | Direct R2 signed PUT | Preserve ingress size enforcement | R5 |
| A7 | Bounded buffer before R2; recheck/lock before write | Unbounded forwarding or trusting Content-Length | Reject oversized bytes and serialize finalization safely | R5, R11 |
| A8 | Maintenance and schema-aware rollback | Rolling mixed-version upgrade | Existing exact-head checks constrain recovery | R6 |
| A9 | Service-specific protected VM secrets | Secrets in repository or application build | Confirmed operating model and least exposure | R7 |
| A10 | Weekly backups plus pre-migration database/config | Daily backups | User-selected frequency with explicit recovery window | R8 |
| A11 | Restic repositories, 30-day snapshots, local media copy | Mirroring deletions | Recover earlier media and encrypted configuration | R8, R9 |
| A12 | Protected runtime unlock plus independent recovery copy | Key only on VM or only inside encrypted backup | Automation and lost-VM recovery both work | R9 |
| A13 | Separate protected R2 validation | Production credentials in PR CI | Provider evidence without exposing production data | R10 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|---|---|
| R2 is unavailable for 30 seconds | Bounded SDK deadlines; safe retryable failure; no completion success; privacy retained |
| Slow or oversize browser upload | Authentication/rate limit first, bounded buffer/deadline and concurrency; reject before R2 write |
| Transfer races with completion or deletion | Buffer outside transaction, then feature lock/recheck; same lock ordering as completion prevents late writes after clean state |
| API dies after staging write | Pending state and expiry cleanup permit retry/reclamation; no object becomes public |
| Two pushes/manual deploys overlap | CI concurrency and VM lock prevent shared-state races; pending intermediate CI runs may be superseded |
| Image pull fails | Existing release stays running; maintenance has not started |
| Migration or post-migration startup fails | Inspect actual schema; rollback only if unchanged, otherwise retain maintenance and require forward fix/restore |
| SSH disconnects during deployment | Persist stage/current/previous identities; VM lock and recovery runbook prevent blind concurrent retry |
| Backup exceeds free disk budget | Abort before exhausting shared disk; report failure; do not prune old snapshots or proceed with migration requiring backup |
| Media/database grows substantially | Size/time metrics and budgets reveal capacity boundary; no unbounded copy or claim that weekly schedule scales indefinitely |
| VM is lost | Restore from encrypted R2 snapshots using independent recovery credentials; expect weekly recovery gaps and reconcile media |

### Backward — regression risk per touched area (brownfield only)

| Touched area | What could regress | How we'd know / mitigation |
|---|---|---|
| Local bootstrap/config/Compose | Development requires cloud credentials or breaks MinIO setup | Existing isolated quality gate remains required |
| Profile and product uploads | Form-only client, lost CSRF, wrong body encoding | Generated contracts, both consumer paths, local plus protected R2 verification |
| Shared storage/private reads | Accidental public media or wrong endpoint | Existing privacy checks and provider-specific validation |
| Profile migration | Existing completed photos no longer resolve | Nullable declaration fields preserve legacy completed records |
| Completion/cleanup | Transfer replay overwrites clean media; stale staging survives | Shared lock discipline and existing deletion/expiry coverage |
| Worker/scheduler/events | New settings break startup, mail, or purge retries | Fresh health and outbox/cleanup regression coverage |
| Proxy/security | Secure cookies, CSRF, WebSockets fail through HTTPS tunnel | Public-origin checks and live reconnect evidence |
| Database compatibility | Previous image cannot start after schema advance | Actual schema comparison and no automatic downgrade |
| Shared VM staging | Global cleanup/restart disrupts unrelated application | Explicit project/port/volume checks and absence of global operations |
| Backup/recovery | Snapshot exists but lacks keys or media | Isolated restore evidence and independent recovery-key custody |

## Open Questions

- Existing tunnel configuration, connector location, management mode, and free loopback port.
  - **Impact if unresolved:** routing or port collision could disrupt staging.
  - **Suggested default:** validate `127.0.0.1:18080`; operator configures routes without replacing the existing connector service.
- VM CPU/RAM allocation, safe temporary disk budget, PostgreSQL size, and operational maintenance timeout.
  - **Impact if unresolved:** cannot establish backup/upload capacity or maintenance duration.
  - **Suggested default:** conservative configurable limits, mandatory preflight and staging evidence; no capacity assertion from the login banner.
- R2 account endpoint, production/validation/backup bucket names, and credentials; GHCR machine account/package permissions.
  - **Impact if unresolved:** implementation can be completed, but real cloud validation and deployment remain blocked.
  - **Suggested default:** separately provision named resources using protected operator inputs; never placeholders in a live deployment.
- Weekly backup day/time and recovery password custodian.
  - **Impact if unresolved:** timers and lost-VM recovery cannot be operationally signed off.
  - **Suggested default:** configurable off-peak UTC schedule and documented independent key custody before activation.
- Current VM security updates and pending restart.
  - **Impact if unresolved:** readiness of the host is unverified and a reboot can affect staging.
  - **Suggested default:** operator-coordinated maintenance before initial production use; no unattended OS upgrade or shared-host reboot in the application pipeline.

These are operator inputs and deployment prerequisites, not alternative architecture choices. The architecture and its file footprint were explicitly confirmed in the interview; implementation must report unperformed infrastructure checks honestly.

## Out of Scope

- Launch scheduling/publication and new public discovery features (separate confirmed requirements slice).
- Moving or modifying the existing staging application and its infrastructure (shared host must preserve it).
- Kubernetes, microservices, multi-node availability, and zero-downtime deployment (not required for this initial target).
- Direct production browser-to-R2 uploads or public bucket/custom-domain media access (confirmed API-mediated design).
- Automatic destructive database rollback or restoration over a live database (operator-led recovery only).
- Claiming production readiness without actual R2, tunnel, backup/restore, and deployment evidence (operator access still required).

