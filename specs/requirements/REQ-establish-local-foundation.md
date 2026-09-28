# Requirements: Establish Local Development Foundation

> **Date:** 2026-09-19
> **Type:** infrastructure
> **Source:** docs/source/launchpad-client-brief.md; docs/source/engineering-guide.md; confirmed requirements interview
> **Phase:** 1 of 5 (Requirement Engineering)

## Summary

Establish a reproducible local development environment and automated quality checks for Launchpad, a daily product-launch platform. Developers can start the application through Docker Compose, verify frontend-to-backend connectivity in a browser, and run all checks without installing Python or Node on their host. This sprint establishes the foundation for later product features; it does not deliver accounts, product workflows, or shared deployments.

## Problem & Motivation

The repository currently contains product and engineering guidance but no application implementation. Before delivering user-facing features, the team needs a dependable way to start the application, preserve development data, diagnose failures, and detect broken changes. Without this foundation, developer setup and verification can diverge and failures can be mistaken for successful startup or passing checks.

## Users & Consumers

- Developers — start and verify the application locally without host language runtimes or external service accounts.
- Reviewers and maintainers — see reliable automated evidence that proposed changes satisfy the applicable quality gates.
- Automated change checks — run the same quality commands available to developers and report unsuccessful or incomplete verification visibly.

## Functional Requirements

| ID | Requirement | Acceptance Criterion |
|----|-------------|----------------------|
| R1 | Provide a documented Docker Compose workflow for starting the local application and its required supporting services. | From a fresh checkout on a supported host with Docker Compose available, a developer following the instructions can start the environment without installing Python or Node on the host or obtaining external service accounts. |
| R2 | Automatically prepare the local database before the application reports ready. | Fresh startup prepares the database without a separate preparation command. Repeat startup succeeds without resetting existing data. Failed preparation prevents readiness and reports an actionable error. |
| R3 | Make preparation safe when startup is repeated or preparation overlaps. | Two overlapping preparation attempts do not leave conflicting or partially applied preparation; readiness is withheld until successful preparation is established. |
| R4 | Supply safe local development defaults wherever possible and reject missing required configuration that has no safe default. | The documented standard setup requires no external credentials. Removing a required value with no safe default causes a visible startup failure that identifies what needs correction without revealing secret values. |
| R5 | Provide a minimal browser page that verifies frontend-to-backend connectivity and required-service readiness. | The page shows “Connected” when the backend and required services are ready. It shows “Unavailable” when the backend is unreachable or a required service is unavailable, without exposing internal errors. Refreshing after recovery restores “Connected.” |
| R6 | Run all developer quality checks through Docker Compose and provide equivalent automated checks for proposed changes. | Documented Compose commands execute formatting, linting, type checks, tests, migration validation, generated API contract checks, security scans, and container builds wherever applicable to this slice, without host Python or Node. The automated workflow runs the same quality commands; applicability is documented so an omitted check cannot be mistaken for a pass. |
| R7 | Require successful execution of every applicable quality gate. | A failing check or a check unable to execute, including because a required supporting service is unavailable, makes the overall verification unsuccessful and identifies the affected check. |
| R8 | Provide local S3-compatible object storage using MinIO and prepare required private storage automatically. | Fresh local startup prepares the required private storage without a separate manual setup step or external storage account. Repeat startup preserves stored files. Unauthenticated direct access to a stored object is denied. |
| R9 | Preserve local database records and stored files across ordinary restarts; provide an explicit documented reset action. | Data and a stored sample file remain available after the documented stop/start workflow. Clearing persisted data requires the separately documented reset action, which identifies what will be deleted. |
| R10 | Document setup, verification, and recovery for the supported local workflow. | A developer can follow the documentation to start the environment, open the verification page, run checks, diagnose missing configuration and unavailable services, retry failed preparation, and deliberately reset local data. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criterion |
|----|-------------|----------------------|
| N1 | Diagnostic output must be useful without exposing secrets or private content. | Configuration and service-failure exercises produce actionable diagnostics without secret values, stored object contents, or browser-visible stack traces. |
| N2 | Readiness must reflect successful preparation and required-service availability rather than merely a running process. | Failed preparation or an unavailable required service cannot produce the browser’s “Connected” state; successful recovery can be verified by refreshing. |
| N3 | Preserve the approved engineering direction and storage-provider constraints. | Architecture and subsequent verification trace this slice to the approved engineering guide. Object storage uses MinIO locally and targets Cloudflare R2 for future staging and production; deploying or connecting to R2 is not necessary to pass this sprint. |
| N4 | Quality evidence must be reproducible across local and automated execution. | Both environments use the documented Compose quality commands. Any environment-specific prerequisites are documented, and unavailable prerequisites result in unsuccessful verification rather than a silent pass. |

## Behaviors & Domain Rules

### Startup and readiness

The standard development workflow uses Docker Compose. Database and required private object storage preparation happen automatically. Repeated preparation preserves existing data, and overlapping preparation must not leave conflicting or partial changes. The application is ready only after successful preparation and while required services are available.

### Browser verification

The browser page is a foundation demonstration, not a public product page. Its visible connectivity states are “Connected” and “Unavailable.” Recovery must be observable on refresh; automatic live recovery is not required by this scope.

### Storage and configuration

MinIO supplies local object storage, with Cloudflare R2 recorded as the provider constraint for later staging and production. Required storage is private. Development defaults eliminate the need for external accounts or credentials; they are not production configuration. This requirement does not add a product upload or download feature.

### Automated checks

All applicable quality gates must complete successfully before a change is considered ready. A check that cannot run is unsuccessful, not skipped as a passing result. Checks cover the actual foundation delivered; this sprint does not create future product features merely to exercise a quality category.

**Why these rules matter:**
- Automatic preparation makes fresh setup demonstrable and avoids undocumented manual prerequisites.
- Preservation and safe repeated preparation prevent ordinary development actions from destroying work.
- Truthful readiness distinguishes a running frontend from a usable application environment.
- Private storage and safe diagnostics establish confidentiality expectations before product data exists.
- Shared quality commands reduce disagreement between local results and automated verification.

**Common mistakes:**
- Reporting “Connected” because the page renders, without checking backend and required-service readiness.
- Requiring host Python or Node for a quality command despite containerized application startup.
- Resetting storage or database contents during an ordinary restart.
- Treating an unavailable test dependency as a skipped success.
- Making local storage publicly readable for convenience or requiring a cloud account for local startup.

## Edge Cases & Failure Modes

| Scenario | Decision | Rationale |
|----------|----------|-----------|
| Fresh checkout has no local data or prepared storage. | Startup prepares the database and required private storage automatically. | Developers should not need undocumented setup actions. |
| Required configuration is absent or empty with no safe default. | Stop startup visibly and identify the corrective action without exposing secrets. | An apparently successful but unusable environment is misleading. |
| Preparation fails before completion. | Withhold readiness, report the failure, and allow a safe retry after correction. | Partial preparation must not be presented as a working environment. |
| Two preparation attempts overlap. | Prevent conflicting or partially applied preparation; report ready only after successful preparation. | Concurrent startup must not corrupt the development environment. |
| A required service becomes unavailable. | Show “Unavailable”; checks dependent on that service cannot pass. | Availability and verification must reflect actual dependencies. |
| An unavailable service recovers. | Refreshing the page shows “Connected” once all readiness conditions are met. | Developers need an observable recovery signal. |
| The developer stops and starts the environment with existing records and files. | Preserve both; deletion requires the explicit reset action. | Restarts are routine and must not destroy development work. |
| Someone requests a stored object without authorization. | Deny direct access; do not disclose the object through diagnostics. | Local storage must preserve the project’s privacy baseline. |
| A quality check fails or cannot execute. | Overall verification is unsuccessful and identifies the affected check. | Missing evidence must not be interpreted as passing evidence. |
| Production-sized traffic or very large datasets are proposed for this sprint. | Defer production capacity testing and associated targets. | This slice verifies local development and automated checks, not production scale. |

## Decisions Log

| # | Decision | Alternatives Considered | Chosen Because |
|---|----------|-------------------------|----------------|
| 1 | Start with the Foundation slice. | Begin with registration and email verification or a larger product slice. | A demonstrable development baseline precedes product feature delivery. |
| 2 | Limit delivery to local development and automated checks. | Include a shared staging environment. | The user selected the narrower scope to avoid deployment work in this sprint. |
| 3 | Use Docker Compose for the application and all quality checks. | Require developers to install host language runtimes for some commands. | The user confirmed a consistent container-based workflow with no host Python or Node requirement. |
| 4 | Include a minimal browser connectivity page. | Demonstrate readiness only through command-line checks. | The user wants frontend-to-backend verification in a browser. |
| 5 | Prepare the database and local storage automatically, preserving existing data. | Require separate manual preparation commands. | The user selected automatic preparation and confirmed safe repeat startup. |
| 6 | Use safe local defaults without external accounts or credentials. | Require external service setup before local startup. | The user confirmed an independently runnable local environment. |
| 7 | Require every applicable check to complete successfully. | Treat unavailable checks as passing or silently omit them. | The confirmed scope requires visible, trustworthy quality evidence. |
| 8 | Use private MinIO locally and Cloudflare R2 for future staging and production. | The source guide allowed other S3-compatible storage choices. | The user explicitly selected the providers; local work must not require a cloud account. |

## Scope Boundaries

### In Scope
- Local application and required supporting services started through Docker Compose.
- Automatic, safely repeatable database and private local storage preparation.
- Safe local configuration defaults, actionable failures, and readiness reporting.
- A minimal browser page showing frontend-to-backend connectivity and readiness.
- Persistent local data and files, plus a deliberate documented reset workflow.
- Container-executed quality checks and automated checks for proposed changes.
- Setup, verification, and recovery documentation.
- MinIO for local object storage; Cloudflare R2 recorded as a future environment constraint.

### Out of Scope
- Shared staging and production deployment, hosting, and R2 provisioning (reason: explicitly deferred).
- Accounts, authentication flows, profiles, product submissions, reviews, scheduling, launches, votes, comments, feeds, search, notifications, analytics, and staff tools (reason: later product slices).
- Product media upload/download flows and production static-asset delivery behavior (reason: this sprint supplies private storage infrastructure only).
- Public product-page design or generated visual assets (reason: the browser page exists only to verify connectivity).
- Production capacity targets, load testing, and production operational rollout (reason: this slice targets local development and automated verification).
- Architecture details and implementation tasks (reason: subsequent workflow phases own them).

## Open Questions

- Which host operating systems must be explicitly supported and verified?
  - **Impact if unresolved:** Documentation must not claim cross-platform support without corresponding verification. Docker Compose is confirmed, but the host support matrix is not.
  - **Suggested default:** Verify the current Linux development environment first; confirm any macOS or Windows/WSL2 support before promising it. This is a proposal, not an approved support restriction.

---
_This requirements document is the input for the **plan-architecture** skill._
_Next step: `/plan-architecture from: specs/requirements/REQ-establish-local-foundation.md`_
