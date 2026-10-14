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
