# Production deployment implementation evidence

**Date:** 2026-10-10 (UTC)  
**Scope:** T22 of [the production deployment task plan](../tasks/TASKS-deploy-proxmox-production.md)  
**Environment:** isolated local Docker checks; no production credentials or VM access used

## Completed checks

| Area | Evidence |
| --- | --- |
| Quality gate | `COMPOSE_PROJECT_NAME=launchpad-production-t22 sh scripts/quality/run.sh` passed: Ruff format/lint, mypy (136 source files), migrations, 396 Python tests passed, 1 protected R2 integration test skipped by its credential gate, web formatting/lint/typecheck, 19 frontend test files (97 tests), generated contracts, image builds, npm audit (0 production vulnerabilities), Trivy, and 2 browser checks. |
| Operational script tests | `docker compose --project-name launchpad-production-t22 --file compose.checks.yaml run --rm --no-deps python-checks python -m pytest -q scripts/tests/test_deploy_production.py scripts/tests/test_backup_production.py scripts/tests/test_validate_r2.py` passed: 46 tests. These cover deterministic failure handling; they do not constitute a real backup restore. |
| Product upload | `tests/integration/test_product_api.py` now exercises an authenticated bounded upload against the local MinIO-backed store: oversized body returns 413, retry with valid WebP succeeds, completion marks it clean, and private storage read returns the exact bytes and media type. Focused test passed; it also passed in the full gate. |
| Profile media and migration | `tests/integration/test_profile_privacy.py` passed in the full gate (4 tests), including compatibility of completed legacy profile media and private staged-to-clean object lifecycle. Migration suite passed; production migration head is `0011_profile_upload_declarations`. |
| Production images | Built `linux/amd64` production API and web images. API digest: `sha256:4c712d31397eb36c7343d34f56b8abd8748b624d7a53829bf9878eee0a71b1a8`. Web digest: `sha256:74c714bd9371b081b7291abf03a7bf2db2c57040b614e78e392d5aa1acc5d2a9`. Image configuration/history inspection found no application secrets or secret build arguments. |
| Production Compose | Rendered with project `launchpad-production` and the `ops` profile. Seven services rendered; no MinIO or Mailpit. Only the web service published a port, bound to loopback; PostgreSQL and Redis had no published ports. A fake Resend key appeared only in worker environment. Temporary placeholder env files were used; no production config was read. |

The first focused integration invocation used the unit-test container and failed setup because that container intentionally lacks integration-service environment variables. It was rerun with the integration service, which supplied PostgreSQL, Redis, MinIO, and Mailpit; the test passed.

## Operator checks still pending

| Check | Missing inputs and boundary |
| --- | --- |
| Protected R2 validation | No isolated validation bucket or credentials are provisioned here. The protected workflow needs repository variables `LAUNCHPAD_R2_VALIDATION_BUCKET`, `LAUNCHPAD_R2_PRODUCTION_BUCKET`, and `LAUNCHPAD_R2_ACCOUNT_ID`, plus secrets `LAUNCHPAD_R2_VALIDATION_ENDPOINT_URL`, `LAUNCHPAD_R2_VALIDATION_ACCESS_KEY_ID`, and `LAUNCHPAD_R2_VALIDATION_SECRET_ACCESS_KEY`. The R2 integration test was therefore skipped; production storage was not contacted. |
| Backup and isolated restore | No Restic repository URLs, repository passwords, backup credentials, or isolated restore target are available on this machine. Database/config and historical media restore were not run. Provision distinct backup and media repository credentials, then follow [the recovery runbook](../../docs/PRODUCTION_RECOVERY.md) in an isolated target. |
| VM and tunnel deployment | The SSH private key is on another machine, as previously reported. The production deploy key, verified VM host key, Cloudflare Access service-token credentials, and provisioned production tunnel/SSH route are not available here. No VM preflight or production deployment was attempted. |

No production R2 bucket, VM, tunnel, or backup repository was accessed. These checks remain operator prerequisites and this record is not a production-readiness declaration.
