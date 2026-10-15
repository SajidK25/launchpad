# Production recovery runbook

This runbook is an operator procedure, not evidence that a restore has been exercised. Test it on an isolated VM/network and isolated R2 target before accepting production data. Never point restore commands at the live Compose project or production bucket during an exercise.

## Recovery prerequisites

- Private Proxmox/LAN console access to the shared host. Cloudflare or GitHub access may be the failed component.
- A disposable isolated Ubuntu/Docker target with enough disk for the selected snapshot, correct PostgreSQL major version, and no route to production users.
- Independently stored Restic recovery password, database and media repository locations, and their separate Restic credentials. The password must not be recovered solely from the encrypted repository it unlocks.
- Encrypted configuration snapshot containing the Compose file, release environment, PostgreSQL/Redis/API/worker/scheduler/migrate environment files, and release metadata. Handle the restored files as live secrets; keep mode `0600` and do not print them.
- For media restoration, the separate media repository credentials and a separate empty/private R2 recovery bucket or isolated S3-compatible target. Do not write into production during a drill.

The database/configuration backup has a weekly recovery point plus a pre-migration snapshot. Media is backed up weekly, so changes since the latest successful media snapshot may be lost. The pre-migration snapshot covers database/configuration, not media.

## Identify and restore an encrypted snapshot to an isolated directory

Load the repository URL, Restic password file, and the appropriate backup credentials from an approved secret manager into the operator environment. Do not put credentials in shell history, a command argument, or a log. For database/configuration, set `RESTIC_REPOSITORY` to the database repository; for media, use the distinct media repository. Use the backup S3 endpoint/region expected by that repository.

List and inspect snapshots, then select the full snapshot ID after checking its kind, reason, timestamp, schema revision, and release commit:

```sh
restic snapshots --tag database
restic snapshots --tag media
restic ls <snapshot-id>
```

Restore only to a fresh isolated path. `restic restore` writes files beneath the target and does not contact the application database or R2 bucket:

```sh
install -d -m 0700 /var/tmp/launchpad-recovery/database
restic restore <database-snapshot-id> --target /var/tmp/launchpad-recovery/database
```

Inspect metadata and configuration locally using an authorized operator account. Do not paste their contents into tickets or logs. Confirm the selected snapshot contains `database.dump`, `metadata.json`, `configuration/`, the matching schema/release, and the expected files before proceeding. Stop if any item is missing or the snapshot identity is uncertain.

## Isolated PostgreSQL recovery

1. Create a new isolated Compose project and volume on the recovery target. Use the snapshot's PostgreSQL configuration to initialize the matching PostgreSQL major version. Keep all ports unexposed or bound only to loopback; do not reuse `launchpad-production` as the project name.
2. Copy `database.dump` into the isolated PostgreSQL container and validate it with the matching `pg_restore --list` before loading it.
3. Restore into a newly initialized empty database using the configured application database user. The backup uses a custom `pg_dump` archive with `--no-owner --no-privileges`; PostgreSQL initialization must create the expected role/database first.

Example command shape (replace the container and database names with the isolated project values; never use a production container):

```sh
docker exec -i <isolated-postgres-container> pg_restore \
  --exit-on-error --no-owner --no-privileges \
  --username=<application-database-user> \
  --dbname=<isolated-database> < /var/tmp/launchpad-recovery/database/<restored-path>/database.dump
```

Verify the `alembic_version` revision matches `metadata.json`, key tables and row counts are plausible, and profile/product media references correspond to the media snapshot being restored. Do not apply migrations or start writers until the database and media snapshots are known to be compatible. The database restore is for an isolated target; restoring over live production requires a separate incident/change decision, stopped writers, and an explicit data-loss plan.

## Isolated media recovery and reconciliation

Restore the selected media snapshot to a separate directory:

```sh
install -d -m 0700 /var/tmp/launchpad-recovery/media
restic restore <media-snapshot-id> --target /var/tmp/launchpad-recovery/media
```

The snapshot contains `objects/` plus `metadata.json`. Inspect metadata for bucket, snapshot time, schema/release, object count, byte count, and database-reference count. Upload the `objects/` tree only to an empty, private recovery bucket using separate, least-privilege credentials. Keep public access disabled. Do not copy the recovery tree into production R2 as part of a test.

Reconcile the restored database's `profiles.photo_key` and clean `product_assets.clean_key` values against the restored object tree/bucket. Check that every referenced key exists, no unexpected public access is enabled, and API reads remain authorization-checked. Record missing references, extra objects, counts, checksums, and any deliberate exclusions. A media snapshot is valid only when its metadata and referenced database revision are compatible.

## Application and release validation

Use the encrypted configuration and recorded immutable image digests from the same snapshot/release. In the isolated project, render Compose, start dependencies, run readiness checks, and verify API/worker/scheduler health. Test representative authorized and unauthorized private-media reads without exposing object-store URLs. Keep outbound email disabled or routed to a test sink during a drill. Do not connect an isolated restore to production Redis, R2, mail, hostname, tunnel, or user traffic.

For an application-only failure, the deployment controller can restore previous images only when the database schema still matches the previous release. If the schema changed, keep writers stopped and prefer a forward-compatible fix. Database restoration is a separate operator-led operation because it can discard writes made after the snapshot. The controller deliberately does not downgrade the database.

For an interrupted initial deployment, the controller supports a narrow resume path: the maintenance marker and failed deployment record must remain intact, the prior attempt must be in `maintenance_recovery_required` after a readiness failure, and the verified incoming image manifest must name the exact schema already present in PostgreSQL. The controller then skips migration and retries startup/readiness; it does not fabricate a previous release or restore a database. If any condition is missing or the schema differs, stop and use an operator-led recovery plan instead. Install the reviewed controller and Compose changes on the VM before submitting a new verified deployment.

## Evidence to retain

Record date, operator, isolated target identifier, snapshot IDs/timestamps, repository types, release commit, schema revision, restore commands, PostgreSQL and media reconciliation results, readiness and worker/scheduler outcomes, elapsed time, data-loss window, and follow-up actions. Never record secrets, private keys, raw environment-file contents, signed URLs, session values, or object credentials. An untested procedure or a successful backup alone is not a completed recovery exercise.
