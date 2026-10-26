# Architecture: Stakeholder Demo Data Seeding

> **Date:** 2026-10-26
> **Phase:** 2 of 5 (System Architecture)
> **Requirements source:** `specs/requirements/REQ-demo-data-seeding.md`
> **Tasks:** `TASKS-demo-data-seeding.md`
> **Type:** feature

## Architecture Summary

Add a one-shot operations command, packaged in the existing API image and run through an explicit Compose `ops` profile, to seed local development or the single designated Proxmox demo/staging VM. An operations-owned manifest and artifact ledger records the UTC date anchor and stable ownership keys so reruns can repair partial work and cleanup can prove ownership. The orchestrator uses narrow auth and profile provisioning interfaces and the existing product review, launch-booking, publication, and notification services; it does not write feature tables directly. The VM path is fail-closed behind a root-owned target marker, matching target acknowledgement, and a per-run no-customer-data attestation, while generated credentials are captured into a private host file outside container logs.

## High-Level Structure

```text
Operator
  └─ scripts/seed_demo.sh
       └─ docker compose --profile ops run --rm demo-seed
            └─ app.operations.demo_seed CLI
                 ├─ target/safety preflight
                 ├─ demo-seed manifest + artifact ledger (PostgreSQL)
                 ├─ Auth provisioning → verified founder/reviewer accounts
                 ├─ Users provisioning → validated photos + public profiles
                 ├─ Products service → private examples and normal review transitions
                 ├─ Launch service → normal booking and publication transitions
                 ├─ Notifications service → inbox notices, no email requests
                 └─ shared private object storage → R2 on VM / MinIO locally
```

The operator wrapper captures credential-only stdout into an owner-private file created with `umask 077`; progress and the completion summary use stderr and contain no secrets. The seed service uses Docker's `none` logging driver so the credential stream is not retained by the container logging driver. The first invocation stores a target UTC anchor before creating records. Each subsequent operation is serialized by a database advisory lock and reconciles stable seed keys against the ledger. Local Compose uses the existing development services and MinIO. Production Compose is used only on the designated VM, with its normal R2 credentials and an `ops`-profile seed service; it does not start a public endpoint or run as part of deployment automation.

## Tech Choices

| Area | Decision | Alternatives Considered | Rationale |
|---|---|---|---|
| Operator entry point | Python CLI in the API image, invoked by a host-side Compose wrapper | HTTP endpoint; standalone host Python install; GitHub Actions workflow | Keeps mutations off public routes and uses the same dependency and feature code in local and VM environments (R1, N1). |
| Domain writes | Narrow provisioning interfaces in auth/users, then existing product, review, launch, and notification services | Direct SQL/ORM inserts from the orchestration module | Preserves module ownership, privacy checks, review audit, launch capacity/state transitions, and event behavior (R2–R9, N2). |
| Ownership and reruns | Operations-owned dataset manifest and stable artifact ledger in PostgreSQL | Marker columns in every feature table; infer ownership from email/name prefixes | Centralizes target, date-anchor, and ownership data without changing public feature records; unledgered collisions fail closed (R2, R7, R10, R11). |
| Historical launch dates | Use the launch/product service clocks with an operator-controlled seed timeline, then execute normal publication transition | Directly set `products.status`/`launched_at`; shift dates on every rerun | Creates dates in the first attempt’s UTC window while retaining normal state transitions and immutable archives (R6–R8, R10–R11). |
| Media | Checked-in synthetic fixture assets uploaded through shared private storage and feature-owned validation paths | Remote image URLs; public third-party images; unvalidated database keys | Keeps storage private, makes demos deterministic, and avoids real identities or third-party product sites (R4, R6, N2). |
| Email suppression | Seed-specific notification composition writes inbox and live-change events but excludes email-request events; launch email preferences are disabled for seeded accounts | Disable the production email worker; temporarily remove Resend settings | Prevents seed-created email from escaping while keeping the production worker and normal in-app notice paths active (R5, R9, N1). |
| VM target protection | Root-owned marker + matching target ID + per-invocation customer-data acknowledgement | Trust `LAUNCHPAD_ENVIRONMENT`; allow any production host with a flag | The VM is deployed with production configuration, so its intended demo role must be separately and visibly opted in (R1, N3). |

## Patterns & Conventions

- **Operations orchestration** — the new operator package coordinates feature-owned interfaces; it does not own account, profile, product, booking, or notification business rules.
- **Named feature boundaries** — auth/users expose only the provisioning operations needed by this tool; product and launch flows are composed through their existing services. The orchestrator never imports feature repositories.
- **Idempotency ledger** — each dataset has a target key, schema/data-set version, creation time, and immutable UTC date anchor. Each artifact maps a stable seed key and artifact kind to its created domain ID. Ledger keys are uniquely constrained.
- **Collision is an error** — a matching email, website key, or other stable identity without a ledger ownership entry is reported as an unowned collision; it is never adopted or overwritten.
- **Normal transition history** — review decisions, booking records, product events, and publication timestamps are produced through their feature services. Do not synthesize reviewed/launched state with direct row updates.
- **No email side effect** — seeded review decisions still create the founder inbox notification and live-change outbox event, but the seed-specific notification composition omits the review email request. Seeded launch preferences disable email channels while retaining in-app channels. Account provisioning marks verification complete without creating a verification challenge or email event.
- **Private, reproducible fixtures** — fixture bytes are local, fictional, and passed through the same image validation and private storage finalization path used by normal profile/product uploads.
- **Project conventions** — Python 3.12+, async SQLAlchemy, FastAPI modular boundaries, PostgreSQL as source of truth, private object storage, typed service interfaces, and Compose-only deployment follow `AGENTS.md` and the existing codebase.

## Data Models

### DemoSeedDataset

**Purpose:** Identifies one authorized demo dataset for a specific environment target and preserves the date basis across interruptions.

**Key fields:**

| Field | Type / Constraint | Notes |
|---|---|---|
| `target_id` | text, primary key | Stable target name such as `local-development` or the explicitly designated VM ID; never a hostname inferred from a URL. |
| `dataset_version` | text, required | Supports future additive data-set changes without silently changing ownership semantics. |
| `anchor_utc_date` | date, required | Captured on the first attempt, before domain writes; recovery and reruns use the same eight-day launch window. |
| `created_at` | timestamptz, required | First operation time in UTC. |
| `updated_at` | timestamptz, required | Most recent successful reconciliation/cleanup update. |

**Relationships:** One dataset owns many `DemoSeedArtifact` rows. This is an operations ownership relationship; it does not grant ownership of unrecorded domain entities.

**Lifecycle:** Created during the first authorized attempt → persists across failures and reruns → retained after cleanup as an audit/ownership record.

### DemoSeedArtifact

**Purpose:** Maps a stable synthetic fixture identity to the domain record created for it.

**Key fields:**

| Field | Type / Constraint | Notes |
|---|---|---|
| `id` | UUID, primary key | Internal ledger row ID. |
| `target_id` | text, foreign key to `DemoSeedDataset` | Prevents ownership from crossing environments. |
| `seed_key` | text, required | Stable fixture key such as `founder-01`, `reviewer`, or `product-launched-01`; unique per target. |
| `artifact_kind` | constrained text, required | Account, profile, product, booking, or notification. |
| `entity_id` | UUID, required | Domain-owned ID; polymorphic and resolved only by the owning feature service. |
| `created_at` | timestamptz, required | Used for safe reconciliation and operator summaries. |

**Relationships:** Many artifact rows belong to one dataset. Domain IDs do not cascade delete from the ledger; reviewed/launched records may outlive cleanup.

**Lifecycle:** Inserted in the same transaction as its associated domain record where possible → checked on rerun → retained for reviewed/launched records and cleanup audit.

## API Contracts / Interfaces

### Demo seed command

**Boundary:** Local operator CLI inside a Compose one-shot container; no HTTP API.

**Operations:**

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| Seed | `python -m app.operations.demo_seed seed --target-id <id> [--confirm-no-customer-data]` | Preflight, reconcile accounts/profiles/products/notifications, and emit only newly generated credentials on stdout. | Nonzero exit for unapproved target, missing customer-data acknowledgement, schema/storage unavailable, media failure, or unowned identity collision; secret-free summary on stderr. |
| Cleanup | `python -m app.operations.demo_seed cleanup --target-id <id> [--confirm-no-customer-data]` | Remove only ledger-owned products that have no review history, using product-owned deletion behavior; a pending submission is withdrawn through `ProductService.withdraw_submission` before `delete_draft`. Retain all accounts/profiles and all reviewed/launched history. | Nonzero exit on unsafe target, any review decision, or failed ownership/state check; counts and retained reasons on stderr. |
| Rotate credentials | `python -m app.operations.demo_seed rotate-credentials --target-id <id> [--confirm-no-customer-data]` | Explicitly rotate selected seed-owned accounts and emit replacement credentials to a new private host file. Never called by `seed`. | Rejects unowned accounts, unknown keys, or unsafe target; never prints passwords in logs. |

The host wrapper creates or reuses a private credentials manifest. On first run it captures credential-only stdout in a mode-0600 host file using a temporary file and atomic rename, preserving that file even if the seed later fails. On reruns it passes the existing file as protected stdin so missing accounts use their original assigned passwords. It refuses to overwrite an existing credential file; explicit rotation writes a separate file.

**Auth requirements:** The command is available only to an operator with Docker access to the named Compose project. On the VM, both the root-owned target marker and matching CLI target ID are required, along with `--confirm-no-customer-data`. The marker is mounted read-only and is not a secret. Local development has a fixed local target ID and does not use the VM bypass.

### Feature provisioning interfaces

**Boundary:** Internal named service APIs, never HTTP and never cross-feature repository imports.

**Operations:**

| Method/Op | Path / Signature | Purpose | Errors / Returns |
|---|---|---|---|
| Provision account | Auth-owned method accepting stable identity, pre-generated password, verified state, and operator actor | Create or resolve a ledger-owned account; hash password with Argon2id; do not issue verification email. | Collision on an unowned email; returns account ID and whether it was created. |
| Provision profile | Users-owned method accepting account ID, profile fields, fixture bytes, and deterministic seed key | Stage/finalize a validated private photo, then publish the complete profile using users rules. | Rejects unverified/missing accounts, invalid fixture, incomplete profile, or unowned profile. |
| Product lifecycle | Existing `ProductService` create/edit/asset/submit/review interfaces | Build listings and produce actual submission and review decisions/audit records. | Existing typed domain errors; owner/staff rules remain authoritative. |
| Launch lifecycle | Existing `LaunchBookingService.book` and `ProductService.publish_scheduled_product` plus booking outcome recording | Book each historical date using an injected seed clock and run its normal publication transition; schedule the private scheduled example in a real future window. | Capacity/state/date conflicts fail that artifact and leave prior successful records repairable. |
| Seed notification | Notification-owned service composition for in-app-only review and launch notices | Persist inbox entries and live-change outbox events without email-request events; seeded launch email preferences are off. | Database/outbox failure rolls back the corresponding domain transaction. |

## Module Boundaries

| Module / Package | Responsibility | Allowed Dependencies |
|---|---|---|
| `app.operations.demo_seed` | Target gate, orchestration, manifest reconciliation, credential stream, cleanup/rotation command, safe summary | Named auth/users/products/launches/notifications service interfaces; shared database, storage, settings. No feature repositories. |
| `app.modules.auth` | Verified demo account provisioning and existing audited reviewer role change | Auth repository and password policy; profile bootstrap interface for account creation as already established. |
| `app.modules.users` | Validated synthetic photo finalization and complete public profile publication | Auth `MemberAccess` port and shared private object store. |
| `app.modules.products` | Product content/assets, submission lifecycle, review decisions, retention-aware unreviewed deletion | Auth member/staff ports, notifications port, shared private storage. |
| `app.modules.launches` | Booking/capacity validation, launch dates, publication outcomes | Named products access port, existing outbox and notification contracts. |
| `app.modules.notifications` | Inbox notice persistence and channel-specific dispatch intent | Auth account access and shared outbox; seed composition disables email requests only for this one-shot run. |
| Compose host wrapper | Select local or designated VM Compose configuration, validate private output file, invoke one-shot service | Docker Compose CLI and operator-provided target/attestation; no app data access. |

## Change Footprint

_The concrete answer to "where does this land in the codebase?" — produced during the Phase D2 walk._

### New files / modules

| Path | Purpose | Pattern reference |
|---|---|---|
| `apps/api/app/operations/__init__.py` | Mark the internal operations package. | Existing `apps/api/app/modules/*/__init__.py` convention. |
| `apps/api/app/operations/demo_seed/__init__.py` | Package the seed command. | `apps/api/app/bootstrap.py`. |
| `apps/api/app/operations/demo_seed/__main__.py` | Enable `python -m app.operations.demo_seed`. | `apps/api/app/bootstrap.py` and `apps/api/app/migrate.py`. |
| `apps/api/app/operations/demo_seed/cli.py` | Parse seed/cleanup/rotation targets, enforce acknowledgements, and separate secret stdout from safe stderr. | `apps/api/app/bootstrap.py` safe CLI diagnostics. |
| `apps/api/app/operations/demo_seed/service.py` | Coordinate manifest, feature service calls, lifecycle examples, reruns, and cleanup. | Service construction in `apps/api/app/modules/products/service.py`; no repository imports across modules. |
| `apps/api/app/operations/demo_seed/repository.py` | Persist and lock seed dataset/artifact ownership records. | Feature repository transaction/query conventions. |
| `apps/api/app/operations/demo_seed/models.py` | Define operations-owned PostgreSQL models. | Feature-local SQLAlchemy models. |
| `apps/api/app/operations/demo_seed/fixtures.py` | Define stable synthetic identities, product copy, topic mapping, dates, and asset manifest. | Existing typed schemas/data fixtures. |
| `apps/api/app/operations/demo_seed/assets/` | Hold fictional profile avatars, product logos, and screenshots. | Shared storage image validation requirements; visual assets must be produced with the configured Higgsfield MCP. |
| `apps/api/app/operations/demo_seed/tests/` | Cover target gate, collisions, ledger rerun/recovery, no-email behavior, cleanup retention, and safe reporting. | `apps/api/app/modules/products/tests/` and `apps/api/app/modules/launches/tests/`. |
| `apps/api/alembic/versions/0017_demo_seed_ownership.py` | Add the dataset and artifact ledger tables/indexes without touching feature histories. | Latest revision `0016_votes_and_daily_rankings.py`. |
| `scripts/seed_demo.sh` | Host entry point for either Compose target; private credential capture/reuse and target arguments. | Existing `scripts/deploy_production.sh` shell safety conventions. |
| `docs/DEMO_DATA_SEEDING.md` | Operator instructions for local and designated VM use, target marker installation, credential handling, lifecycle coverage, and cleanup limits. | `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md`. |

### Modified files / modules

| Path | What changes here |
|---|---|
| `apps/api/app/modules/auth/provisioning.py` | Add an auth-owned, email-suppressed path to create verified demo accounts with the existing Argon2id hash helper and stable identity collision checks. |
| `apps/api/app/modules/auth/staff.py` | Reuse `StaffManagementService.set_role` for reviewer elevation; do not add admin provisioning. Only modify if an actor/clock seam is needed without weakening existing audit requirements. |
| `apps/api/app/modules/users/service.py` | Add a narrow provisioning operation that runs fixture bytes through existing photo staging/finalization validation and publishes a complete profile. |
| `apps/api/app/modules/notifications/service.py` | Allow an explicit seed composition to suppress email request events while retaining inbox rows and live-change events; normal default delivery behavior remains unchanged. |
| `compose.yaml` | Add a one-shot `ops`-profile demo seed service on the existing development network, using MinIO and local DB configuration; disable container log retention for this service. |
| `compose.production.yaml` | Add a one-shot `ops`-profile service using the pinned API image, R2/API environment, private backend network, read-only target marker mount, no host ports, and no container log retention. |
| `.gitignore` | Exclude the local private demo credential output directory/file pattern from source control. |

### Deleted / replaced

| Path | Reason |
|---|---|
| None | The work adds an operator capability and does not replace existing signup, review, launch, or deployment flows. |

### Touched but not changed (silent-regression hotspots)

| Path | Why it matters |
|---|---|
| `apps/api/app/modules/auth/service.py` | Public registration must continue issuing its normal verification challenge; demo provisioning is a separate operator-only path. |
| `apps/api/app/modules/products/service.py` | Public review, product state, asset ownership, publication, and retained audit semantics must remain unchanged; cleanup reuses the existing withdraw/delete gates and must never bypass the decision-history check. |
| `apps/api/app/modules/launches/service.py` | Booking eligibility, daily capacity, schedule events, and normal publication outcomes are reused with injected time; their public rules must not be loosened. |
| `apps/api/app/shared/storage/objects.py` | MinIO and R2 image validation/finalization protects profile and product media; the seed must use it rather than store unchecked keys. |
| `apps/worker/worker.py` | The live worker consumes outbox email and launch events; seed-created notifications must not create email event types that its running process could send. |
| `scripts/deploy_production.sh` | Seeding must not be coupled to deploy, migration, rollback, or automatic production workflow execution. |
| `apps/api/app/shared/config/settings.py` | Production configuration and R2 settings remain authoritative; the target marker is a separate operator gate and not a general production-mode override. |

## Areas of Impact

| Area | Impact | Risk (L/M/H) | Why |
|---|---|---|---|
| Auth and staff audit | Adds verified synthetic identities and a reviewer role through explicit operator operations. | Medium | A missed boundary could create password/email side effects or elevate an unowned account. |
| Users/profile media | Adds many public synthetic profiles and private-storage objects. | Medium | Images must pass current validation and remain associated with the owning accounts. |
| Products/review | Creates launched catalog examples and private lifecycle examples, with genuine review history. | High | A seed bug can expose unpublished content or create durable reviewed/public data that cleanup cannot remove. |
| Launches/archives | Populates today and seven historical UTC dates and a future scheduled example. | High | Public archive dates are immutable and launch capacity/time rules are production invariants. |
| Notifications/email outbox | Adds representative founder inbox items while suppressing all email requests. | High | A review-email event could be consumed by the live production worker and sent through Resend. |
| Compose and VM operations | Adds an explicit one-shot service and root-owned target marker gate. | High | VM runs production Compose against a publicly reachable deployment; wrong target selection could mutate real production. |
| Database migrations | Adds two operations-owned ledger tables and uniqueness/lookup constraints. | Low | Additive tables do not rewrite feature data; deployment must apply the migration before seed execution. |
| Storage and fixture assets | Uploads fictional image fixtures into R2 or MinIO. | Medium | Invalid media or a wrong bucket could fail partway; stable keys and cleanup behavior need to be owner-scoped. |

**Contract changes:** No public REST, GraphQL, WebSocket, OpenAPI, or browser contract changes. Adds only an internal CLI contract, two database tables, and Compose operator services.

**Cross-cutting ripples:** New migration; Docker Compose ops profile; target-specific operator marker; host credential file handling; no-email notification composition; test fixture assets; operator documentation. No GitHub Action or deployment-controller changes.

## Cross-Cutting Concerns

- **Errors:** Target and collision errors are typed seed-operation failures with stable safe messages. Per-artifact failures include the fixture key and stage, not account details or private content. Dependency failure aborts new work; already committed artifacts and their ledger entries remain available for rerun repair.
- **Logging & metrics:** Emit counts by artifact kind and created/reused/skipped/failed outcome. Never log passwords, credential manifests, object-store credentials, profile/product private text, full database URLs, or unrelated identities. Credential bytes are isolated to stdout consumed by the host wrapper.
- **Auth / authz:** There is no HTTP route. Docker operator access is the outer authorization boundary. Production-mode authorization additionally requires the root-owned target marker, exact target ID match, and explicit customer-data attestation. Reviewer role is granted through audited `StaffManagementService`; no admin account or role is created.
- **Performance:** The dataset is bounded (20 founders/products, one reviewer, six workflow records). Use stable-key indexed ledger lookups and batched ownership reads; avoid table scans or unbounded per-record reads. Image validation/upload is sequential or bounded to storage capacity.
- **Security:** Use fictional `.example` domains and synthetic assets. Hash randomly generated passwords with the existing Argon2id helper. Host wrapper uses `umask 077`, atomic file creation, refuses overwrite, and keeps files outside source control. A rerun reads existing credential material through stdin; normal output omits it. Never trust the Compose service alone to authorize the VM target.
- **Migrations / rollout:** Deploy the migration and seed code via the existing image workflow first; confirm the target DB is at the expected migration head. Local Compose preparation applies migrations through its normal path. The production-profile service does not migrate; operators run the existing migration/deployment process before invoking it. Disabling/removing the marker prevents future VM seed operations; it does not delete already published demo records.

## Architecture Decisions Log

| # | Decision | Alternatives | Chosen Because | Satisfies REQs |
|---|---|---|---|---|
| A1 | Use a Compose-only one-shot Python operator command in both environments. | HTTP endpoint, direct host script with a separate Python install, or CI workflow. | Keeps the mutation surface private and reuses the pinned application image and runtime config. | R1, R12, N1 |
| A2 | Put orchestration and ownership in `app.operations.demo_seed`; use narrow feature-owned provisioning/service interfaces. | Direct SQL from one cross-cutting module. | Keeps domain persistence/rules with their feature owners and respects the modular-monolith boundary. | R2–R11, N2 |
| A3 | Persist a seed dataset manifest and per-artifact stable ownership ledger. | Add markers to every feature row or infer ownership from synthetic names. | Supports safe conflict detection, partial recovery, fixed dates, and cleanup without ambiguous ownership. | R2, R7, R10, R11 |
| A4 | Capture the UTC date anchor on the first attempt and preserve it after interruption. | Recompute each run or wait until full success to record the anchor. | Recovery can add missing launches without moving already published archive entries. | R7, R10, R11 |
| A5 | Use current state-transition services and controlled seed clocks to create historical launch examples. | Directly insert reviewed/launched states or weaken past-date validation. | Preserves review audit, capacity/booking records, and public lifecycle semantics. | R6–R8, N2 |
| A6 | Permit the production-configured VM only with a root-owned marker, matching target ID, and per-run no-customer-data acknowledgement. | Treat production environment labels as sufficient, or allow any production target with a generic flag. | The named VM is publicly reachable and uses production settings; narrow opt-in prevents a broad bypass. | R1, R2, N3 |
| A7 | Emit generated credentials once through host-captured, private stdout; reuse them from the existing private file for recovery; rotate only with a separate explicit command. | Print to terminal/logs, shared password, or regenerate each run. | Supports unique login credentials and interrupted recovery without routine secret churn. | R5, R10, N1 |
| A8 | Suppress verification email at account provisioning and review email at notification composition; disable launch email preferences for seeded accounts. | Disable the production worker or remove provider credentials. | Avoids external communications while preserving normal inbox and live notification behavior. | R9, N1 |
| A9 | Cleanup only ledger-owned products with no review history; retain accounts and every reviewed/launched artifact. | Full dataset deletion or deleting only from the local environment. | Meets audit retention and archive immutability requirements, including on the designated VM. | R11, N2 |
| A10 | Store synthetic image fixtures locally and upload through current private media validation. | Third-party/public links or unchecked object keys. | Makes the demo deterministic, fictional, and compatible with MinIO and R2. | R4, R6, N2 |

## Risk & Stress-Test Scenarios

### Forward — runtime failure scenarios

| Scenario | How the Design Handles It |
|---|---|
| A caller points the command at an unmarked production host or the wrong VM ID. | The command checks target/environment and marker equality before opening a write transaction; failure exits before any writes. |
| The VM marker exists but the operator does not attest that the VM is free of customer data. | The per-run acknowledgement is mandatory on the production-configured target; absence blocks the command. Existing operator/test records are left untouched. |
| Two seed commands start together. | A target-scoped PostgreSQL advisory lock serializes reconciliation; database uniqueness on target/seed key remains the final duplicate guard. |
| PostgreSQL or R2/MinIO fails after some records were created. | Each artifact is committed with its ledger entry; the original date anchor and credential file remain. The safe summary reports the stage, and rerun repairs missing keys without changing completed accounts/passwords/dates. |
| An unowned account or website key matches a planned fixture. | Preflight reports a safe stable-key collision and aborts that item/run; no record is adopted or updated. |
| A seed review accidentally enqueues an email event while the production worker is running. | Design-level guarantee: seed notification composition emits only inbox/live events and account verification creates no email event. Tests must inspect outbox event types; worker configuration remains untouched. |
| A fixture image is malformed or over limits. | Shared image validation fails before profile/product publication; the artifact remains incomplete and can be repaired on rerun. |
| A public demo listing contains incorrect content after publication. | Cleanup intentionally cannot erase or rewrite it. Keep fixture validation and complete preflight ahead of publication; resolve through a separate product takedown/correction capability, outside this seed scope. |

### Backward — regression risk per touched area (brownfield only)

| Touched area (from Change Footprint) | What could regress | How we'd know / mitigation |
|---|---|---|
| Auth provisioning | Public registration might stop creating verification challenges, or seed accounts might use weaker hashing. | Keep `RegistrationService.register` behavior untouched; reuse Argon2id helper and prove outbox remains empty for verification mail in seed-specific tests. |
| Users profile service/storage | Public profile photo requirements could be bypassed by seed-only code. | Require the same cleaned-photo metadata and publication validation; use invalid fixture and wrong-owner scenarios. |
| Notification service | Normal reviews could lose email, or seed reviews could retain email. | Default behavior remains email-enabled; explicit seed policy is scoped to seed composition. Verify both normal and seed review event sets. |
| Product and launch workflows | Product state could be set directly, capacities ignored, or past-date validation loosened for everyone. | Reuse services with injected clock only in the operations composition; public route and default-clock behavior unchanged. |
| Production Compose/deployment | One-shot service could enter normal startup, bind a host port, retain credential output in logs, or run during deploy. | Keep it under `ops`, restart `no`, no published ports, use the `none` logging driver, and do not invoke it from deploy workflow/controller; inspect resolved Compose config in verification. |
| Worker and outbox | Existing unrelated email events could be affected by disabling worker/provider settings. | Do not alter worker settings or provider credentials; only seed-generated email-request event types are prohibited. |

## Open Questions

- The configured Higgsfield MCP required by `AGENTS.md` is not exposed in this planning session, so synthetic avatar/logo/screenshot asset production cannot be confirmed here.
  - **Impact if unresolved:** The seed implementation can be designed and tested against fixture paths, but the agreed 20+ distinct image fixtures cannot be generated in this environment.
  - **Suggested default:** Make asset production a task prerequisite and generate/validate checked-in fictional fixture files in a session with the configured Higgsfield MCP; do not substitute real third-party images or bypass shared validation.

## Out of Scope

- Public REST, GraphQL, WebSocket, or admin UI for seeding (reason: this is a private operator capability).
- Running seed commands in GitHub Actions, as part of deployment, or against any other production target (reason: only local and the explicitly designated customer-free VM are approved).
- Vote history, ranking snapshots, or vote-related notifications (reason: explicitly excluded by the REQ).
- Deleting reviewed, rejected, approved, scheduled, or launched products, review audit, or launch archives (reason: retention and immutability requirements).
- Mail delivery or email-verification walkthroughs for demo accounts (reason: all outbound mail is suppressed by the seed).

---
_This architecture document is the input for **generate-tasks**._
_Next step: `/generate-tasks from: specs/architecture/ARCH-demo-data-seeding.md`_
