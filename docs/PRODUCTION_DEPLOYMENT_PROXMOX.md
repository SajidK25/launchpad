# Production deployment on the shared Proxmox host

**Status:** implementation documented; production readiness is not established. The VM, Cloudflare routes, GitHub environment, R2 credentials, backups, and recovery path require operator provisioning and evidence.

## Deployment shape

Launchpad runs as an isolated Docker Compose project on the shared Ubuntu 24.04.4 Proxmox VM (`192.168.0.98`). The VM has no public IP. Cloudflare Tunnel serves `https://launchpad.t99ltd.com` to the loopback-bound web service, and a Cloudflare Access service-token policy protects the deployment SSH route. GitHub Actions builds Linux/amd64 API and web images, publishes them to private GHCR, and automatically deploys the exact successful `main` workflow release by immutable digest.

```text
Visitors -> Cloudflare Tunnel -> 127.0.0.1:18080 -> web -> API
GitHub Actions -> Access service token + pinned SSH host key -> deploy account
API / worker / scheduler -> PostgreSQL, Redis, private Cloudflare R2
Local development / normal CI -> PostgreSQL, Redis, MinIO
```

This is a shared-host arrangement. Docker access can control the entire VM, and host resource contention or compromise can affect staging and Launchpad. Keep Proxmox management private and retain a LAN/Proxmox-console operator recovery route. The hostname, port, and resource usage must be checked against existing staging services before installation.

## Operator preflight

Before enabling production releases, record and verify each item:

- **Shared host:** Ubuntu 24.04.4 x86-64, Docker Engine and Compose plugin, Git, SSH, `flock`, time synchronization, adequate disk/RAM/CPU, and no conflicting project, volume, network, port, or systemd unit. The controller performs its own Compose/project/volume/network/port preflight.
- **Tunnel:** the existing connector can reach the VM, or a dedicated connector is provisioned. Route `launchpad.t99ltd.com` to `http://127.0.0.1:18080` when the connector shares the VM; route `launchpad-ssh.t99ltd.com` to SSH. Do not overwrite staging tunnel configuration or reuse an occupied connector unit. Keep database, Redis, Docker, and Proxmox management off public routes.
- **SSH and Access:** dedicated `deploy` account and Actions key; independently obtained and pinned VM host key; Access SSH application with a dedicated service-auth token; strict host-key verification. Docker group membership is privileged access. Keep a private operator route if Access or the tunnel is unavailable.
- **Repository and registry:** private packages `ghcr.io/sajidk25/launchpad-api` and `ghcr.io/sajidk25/launchpad-web`; VM pull credential has read-only package access. The workflow publishes only from protected `main` after the same-run quality gate and records digests, commit, workflow run, and Alembic head in its manifest.
- **GitHub:** protected `main`; production environment limited to `main`; environment secrets `PRODUCTION_SSH_PRIVATE_KEY`, `PRODUCTION_SSH_KNOWN_HOSTS`, `CF_ACCESS_CLIENT_ID`, and `CF_ACCESS_CLIENT_SECRET`. Keep SSH and service-token values out of logs and command text. A deployment is automatic after a successful eligible workflow; workflow dispatch is also restricted to `main`.
- **Runtime files:** provision `/srv/launchpad/{bin,state,incoming}` and `/etc/launchpad`. Runtime environment files are `postgres.env`, `redis.env`, `api.env`, `worker.env`, `scheduler.env`, and `migrate.env`; restrict them to the deploy/runtime owner with mode `0600`. Provision `/etc/launchpad/backup-database.env` and `backup-media.env` separately. Do not copy development defaults into production.
- **R2:** private production bucket, public access disabled, no public custom domain, bucket-scoped runtime credentials, and endpoint/region `auto`. R2 administration credentials are for provisioning only. The API accepts bounded authenticated uploads; browsers do not upload directly to R2. Resend credentials belong only in `worker.env`.
- **Backup:** distinct encrypted Restic database/configuration and media repositories, separate credentials, protected password file, independent recovery-key copy, read-only R2 media credentials, local staging capacity and byte limit. Enable the weekly timers only after a test backup and an isolated restore exercise.

Useful host preflight commands (run on the VM by an operator):

```sh
docker version
docker compose version
ss -Hln
docker ps --all --format '{{.Names}} {{.Ports}}'
docker volume ls
docker network ls
systemctl list-unit-files 'launchpad-*'
```

The preflight is an observation step. Do not remove resources that might belong to staging to make Launchpad fit.

## Production Compose and configuration

The source of truth is [`compose.production.yaml`](../compose.production.yaml). It fixes project name `launchpad-production`, uses digest-addressed API/web images, stable named PostgreSQL/Redis volumes, bounded logs, health checks, and service-specific files under `/etc/launchpad`. It publishes only web on loopback (`127.0.0.1:18080` by default). The web service joins the isolated internal ingress network shared with the API and a separate non-internal bridge for Docker host port publication; the API does not join that host-publish network. PostgreSQL and Redis have no host ports. Production does not start MinIO or Mailpit. The `migrate` service is a one-shot `ops` profile.

The controller is [`scripts/deploy_production.sh`](../scripts/deploy_production.sh). Its entry point consumes a workflow-generated release manifest, validates repository/ref/commit/digests/schema identity, acquires a shared lock, checks Compose and host resource ownership, pulls the exact images, creates a pre-migration database/config snapshot, enters maintenance, stops writers, migrates, starts and checks API/worker/scheduler, verifies local and public readiness, and records the release. It restores prior images only when the schema still equals the previous release. After an interrupted first deployment, it can resume only when the durable failed-attempt record shows a recovery-required readiness failure at the exact schema in the new verified manifest, the maintenance marker remains, and no current release is recorded; it then skips backup/migration and retries service startup/readiness. Otherwise it stops writers and leaves maintenance active for operator recovery. It does not downgrade migrations or overwrite a changed database.

Install the reviewed controller and Compose file at `/srv/launchpad/bin/deploy_production.sh` and `/srv/launchpad/compose.production.yaml`; the workflow transfers a verified manifest to `/srv/launchpad/incoming`. Keep those VM entry points owned and writable only by the operator/deploy administration path. Production network ports and environment scopes are defined in Compose; do not add ports to expose PostgreSQL, Redis, or Docker.

### Storage and email

MinIO remains the local development and isolated-CI provider. Production uses private Cloudflare R2 through the shared S3-compatible storage boundary. Production configuration fails closed when R2 settings are absent or invalid. Product and profile uploads pass through authenticated API endpoints that enforce byte limits and validate staged object size/content before finalization. Application-authorized reads remain private and mediated by the API.

R2 is not the only prerequisite: provision the private bucket and CORS policy for the deployed origin, then use the protected `R2 validation` GitHub workflow with a separate non-production bucket and credentials. Ordinary PR/quality CI has no R2 secrets. Resend is the production transactional email provider; inject `LAUNCHPAD_RESEND_API_KEY` into the worker only.

## Release operation

The production workflow is [`.github/workflows/production-deploy.yml`](../.github/workflows/production-deploy.yml). PRs and pushes run the shared quality gate; eligible `main` runs then build and publish the images and deploy their immutable digests through Access-protected SSH. A per-production concurrency group prevents overlapping deployments. CI does not build on the VM, deploy `dev`, or rely on a separate workflow's result for the release commit.

For a planned operator deployment, verify the GitHub run's commit, successful quality/build jobs, manifest, and deployment result. The normal automated pipeline handles migration backup, maintenance, migration, rollout and health checks. Do not invoke a second deployment while the shared lock is held. Check the VM deployment record and service health without printing environment files or credentials:

```sh
docker compose --project-name launchpad-production \
  --file /srv/launchpad/compose.production.yaml \
  --env-file /srv/launchpad/state/current-release.env ps
curl --fail --silent --show-error http://127.0.0.1:18080/api/v1/health/ready
curl --fail --silent --show-error https://launchpad.t99ltd.com/api/v1/health/ready
```

Production deployment is not authorized by this document alone. Provision infrastructure and secrets, complete the verification record, and use the normal protected workflow. Never deploy local or unverified tags.

## Backup schedule and recovery

[`scripts/backup_production.sh`](../scripts/backup_production.sh) creates encrypted database/configuration snapshots weekly and before migrations; private media is copied from R2 to bounded local staging and backed up weekly. Database and media use separate Restic repositories and credentials. Systemd timers are scheduled weekly at 03:00 UTC for database/configuration and 04:00 UTC for media, with persistent missed-run handling. Retention is 30 days. Backup operations share the deployment lock. Media recovery therefore has a weekly recovery-point gap; it is not continuous mirroring.

See [`PRODUCTION_RECOVERY.md`](PRODUCTION_RECOVERY.md) for operator-led database, configuration, media, and release recovery. Backups and restores must be exercised on an isolated target before production data is accepted. A successful backup command is not restore evidence.

## Voting rollout and rollback

Launch scheduling and anonymous launch reads remain disabled by default. On a designated,
customer-free staging VM, persist the independently verified launch rollout by installing
`/etc/launchpad/runtime.env` as `root:deploy` mode `0640` with
`LAUNCHPAD_LAUNCHES_ENABLED=true`. That staging target may additionally set
`LAUNCHPAD_DEMO_HOME_LATEST_LAUNCH_ENABLED=true` so an empty UTC day shows the newest populated
launch date on the homepage without rewriting its immutable archive. The deployment controller
validates this non-secret policy and preserves it across verified releases and schema-safe image
rollback. Both settings default to `false`; disable the demo fallback before accepting customer
data. See the development guide's production launch feature-switch section for operational details.

Voting is independently gated by `LAUNCHPAD_VOTE_WRITES_ENABLED` (Compose default
`false`). Keep launch scheduling enabled as needed; do not enable vote writes until
the release migration is applied and the matching API, worker, and scheduler are
healthy. The API and worker must use the same
`LAUNCHPAD_VOTE_SCORE_HALF_LIFE_SECONDS` value; the initial value is `21600` seconds
(six hours) for staging calibration.

Before enabling, configure the Turnstile public site key as the GitHub repository
variable `VITE_TURNSTILE_SITE_KEY` and build/deploy the web image with it. Put
`LAUNCHPAD_TURNSTILE_SECRET_KEY`, `LAUNCHPAD_VOTE_ACCOUNT_VELOCITY_LIMIT`, and
`LAUNCHPAD_VOTE_SOURCE_VELOCITY_LIMIT` in `/etc/launchpad/api.env`, then deploy the
verified release. Keep the Turnstile secret API-only; do not copy it to worker or
web environment files. The production API refuses to start with vote writes enabled
if its required Turnstile verification settings are missing or invalid. Risk limits
must be calibrated in staging; this guide does not prescribe numeric thresholds.
Production source velocity uses the visitor IP from Cloudflare's `CF-Connecting-IP`
header, forwarded by Nginx to the API. Keep the web origin bound to `127.0.0.1` and
reachable through the dedicated Cloudflare Tunnel path only; do not publish the
origin port on a LAN or public interface.

After migration, choose the first UTC launch date on which voting is intended to
exist. The simplest rollout is to use the current UTC date. To persist that date
before opening writes, execute this idempotent statement through the production
PostgreSQL service using an authorized operator session; it never overwrites an
existing value:

```sql
INSERT INTO voting_feature_state (singleton_id, enabled_from, created_at)
VALUES (1, (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date, CURRENT_TIMESTAMP)
ON CONFLICT (singleton_id) DO NOTHING;
SELECT enabled_from FROM voting_feature_state WHERE singleton_id = 1;
```

The first accepted vote also initializes this row to the API's current UTC date if
the operator did not initialize it. Do not backdate it casually: pre-voting archive
dates intentionally have no vote ranks. With configuration and the UTC date
verified, enable writes by recreating only the API:

```sh
sudo -u deploy env LAUNCHPAD_VOTE_WRITES_ENABLED=true docker compose \
  --project-name launchpad-production \
  --file /srv/launchpad/compose.production.yaml \
  --env-file /srv/launchpad/state/current-release.env \
  up -d api
sudo -u deploy docker compose \
  --project-name launchpad-production \
  --file /srv/launchpad/compose.production.yaml \
  --env-file /srv/launchpad/state/current-release.env \
  exec -T api python -c 'from app.shared.config.settings import load_settings; print(load_settings().vote_writes_enabled)'
```

Verify the output is `True`, API readiness is healthy, worker and scheduler are
healthy, and outbox/projection lag is being monitored. Test a verified member vote
against a launched product without using staff or founder accounts. Do not query or
copy vote identity data into operational reports. Closed-date snapshots are
immutable; staff invalidation updates current state but cannot rewrite an archive.

For rollback, disable new vote commands while leaving the compatible API, worker,
scheduler, schema, and outbox intact:

```sh
sudo -u deploy env LAUNCHPAD_VOTE_WRITES_ENABLED=false docker compose \
  --project-name launchpad-production \
  --file /srv/launchpad/compose.production.yaml \
  --env-file /srv/launchpad/state/current-release.env \
  up -d api
sudo -u deploy docker compose \
  --project-name launchpad-production \
  --file /srv/launchpad/compose.production.yaml \
  --env-file /srv/launchpad/state/current-release.env \
  exec -T api python -c 'from app.shared.config.settings import load_settings; print(load_settings().vote_writes_enabled)'
```

Confirm `False`; keep worker and scheduler running until already committed events
drain. Do not downgrade the vote migration, delete receipts/audit data, or edit
completed snapshots to roll back. The existing weekly PostgreSQL/configuration
backup and pre-migration backup policy applies. Preserve the voting start date for
restart; validate backups with an isolated restore rather than assuming a successful
backup command proves recoverability. Peak concurrency, Turnstile thresholds, and
idempotency receipt retention remain staging/operations calibration items.

## Readiness gates

Do not claim production readiness until an operator has evidence for all of these:

- host/tunnel/SSH/Access prerequisites and clean-room preflight;
- successful same-run quality gate and amd64 image builds with digests;
- production Compose rendered with the provisioned secret files and verified network/port ownership;
- forward migration and preservation of existing profile-photo objects;
- local MinIO product/profile upload, invalid-size rejection, retry and private-read behavior;
- deployment failure injection and schema-aware recovery behavior;
- encrypted database/config and media backup plus isolated restoration and reconciliation;
- protected R2 validation, or a recorded pending status naming missing operator inputs;
- public tunnel readiness, only after the host and Access prerequisites are provisioned.

Never represent unavailable VM, R2, tunnel, or restore checks as passing. Launch scheduling/publication is outside this deployment architecture.
