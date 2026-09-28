# QA Results: Member Identity and Private Profiles

> **Plan:** [QA-add-member-identity-profiles.md](./QA-add-member-identity-profiles.md)

### Run 1 — 2026-09-25, commit `f62a530e244e036f79118a60fc79a3ae67888131`, environment `http://localhost:8080`

| Case | Verdict | Evidence / Notes |
|---|---|---|
| P0–P4 | **BLOCKED** | Execution stopped before cases: `.env.qa.local` is missing, so required `QA_MEMBER_A_*`, `QA_MEMBER_B_*`, and `QA_UNKNOWN_EMAIL` identity values cannot be resolved safely. |
| QA-01–QA-08 | SKIPPED | No case started because the environment precondition failed. |

**Findings**

| ID | Severity | Description | file:line |
|---|---|---|---|
| F-1 | 🟡 Medium | Local QA identity environment is not provisioned. Create a gitignored `.env.qa.local` containing the plan's required disposable identity variables, then rerun `/execute-qa specs/qa/QA-add-member-identity-profiles.md`. | `specs/qa/QA-add-member-identity-profiles.md:38` |

**Run notes**

Per the execute-QA safety contract, the run did not start Compose services, browser automation, or any case because the required environment file was absent. No production or shared data was accessed. The plan itself remains unchanged.

### Run 2 — 2026-09-25, commit `f62a530e244e036f79118a60fc79a3ae67888131`, environment `http://localhost:8080`

| Case | Verdict | Evidence / Notes |
|---|---|---|
| P0–P4 | **BLOCKED** | Execution stopped before cases: `.env.qa.local` is still missing, so the required disposable identity variables cannot be resolved safely. |
| QA-01–QA-08 | SKIPPED | No case started because the environment precondition failed. |

**Findings**

| ID | Severity | Description | file:line |
|---|---|---|---|
| F-2 | 🟡 Medium | Provision the gitignored `.env.qa.local` with the plan's disposable identity variables, then rerun the plan. | `specs/qa/QA-add-member-identity-profiles.md:38` |

**Run notes**

The second execution attempt made no service or data changes and did not contact a production or shared environment. The plan remains unchanged.

### Run 3 — 2026-09-25, commit `f62a530e244e036f79118a60fc79a3ae67888131`, environment `launchpad-qa` (`web:8080`)

| Case | Verdict | Evidence / Notes |
|---|---|---|
| P0 | PASS | `COMPOSE_PROJECT_NAME=launchpad-qa sh scripts/quality/run.sh`: 132 backend/integration tests, 38 web tests, migrations, contracts, builds, security, and 2 browser smoke tests passed. |
| P1–P4 | PASS | Isolated Postgres/Redis/MinIO/Mailpit prepared successfully; internal `web:8080` and `/api/v1/health/ready` responded; required disposable identities resolved; browser smoke completed. The web service is intentionally not host-published, so readiness used the browser-container network path. |
| QA-01 | PARTIAL | Automated registration/password-policy coverage passed in P0, but the plan does not provide a concrete executable command for comparing raw response bodies and Mailpit registration guidance. |
| QA-02 | PARTIAL | Automated verification/profile publication coverage passed in P0, but token extraction/redeem commands are not specified sufficiently for an independent manual run. |
| QA-03 | PARTIAL | Browser smoke covered route access and private public-route behavior; the full two-identity CSRF/direct-photo sequence was not independently driven from the plan's prose steps. |
| QA-04 | PARTIAL | Automated recovery/session invalidation coverage passed in P0; the plan lacks a concrete cookie-jar and Mailpit message-ID helper for the complete two-device drill. |
| QA-05 | PARTIAL | Automated privacy/outbox coverage passed in P0; SMTP stop/recovery and worker invocation need concrete commands before this can be a full manual pass. |
| QA-06 | PARTIAL | Automated storage/profile privacy tests passed in P0; the plan needs explicit upload fixture and public REST/GraphQL curl commands for full execution. |
| QA-07 | PASS (judged) | Browser smoke and accessibility route checks passed at mobile and desktop viewports; the existing test verified keyboard focus, accessible headings, generic recovery copy, and private-route messaging. |
| QA-08 | PARTIAL | Migration and outbox automated checks passed in P0, but the plan's direct worker/outage commands are not concrete enough to claim an independent live outage drill. |

**Findings**

| ID | Severity | Description | file:line |
|---|---|---|---|
| F-3 | 🟡 Medium | The QA plan needs concrete, runnable helper commands for Mailpit token extraction, authenticated cookie jars, profile/photo fixtures, and worker outage/retry control before QA-01–QA-06 and QA-08 can be full manual passes. | `specs/qa/QA-add-member-identity-profiles.md:60` |

**Run notes**

The default Docker address pools were exhausted, so the isolated `launchpad-qa_default` network was created explicitly on `10.23.0.0/16`; no existing project networks or volumes were removed. The plan was not edited during execution. The partial verdicts are deliberate: automated evidence is recorded, but the execute-QA contract forbids inferring manual case passes from unit/integration tests when the plan does not provide a runnable driver command.
