# Development workflow

This foundation is verified on Linux with Docker Engine and the Docker Compose plugin. Docker is the only required host runtime: Python, Node, browser drivers, and scanners run in containers.

Choose a Compose project name before every command. It scopes containers, networks, and named volumes, which lets several local environments run without sharing data. The examples use `launchpad-dev`; replace it with a unique name for disposable work.

## Start and inspect

```sh
docker compose -p launchpad-dev up -d --build
docker compose -p launchpad-dev ps
```

The `prepare` service applies forward migrations and creates or reuses the private MinIO bucket before the API, worker, and scheduler start. Visit http://localhost:8080. **Connected** means the browser received a ready API response after its PostgreSQL, Redis, and MinIO probes succeeded.

Use these focused diagnostics when startup does not complete:

```sh
docker compose -p launchpad-dev logs --no-color prepare api web worker scheduler
docker compose -p launchpad-dev ps
```

Correct the named configuration or dependency problem and rerun the ordinary startup command. Preparation is safe to retry: it never resets volumes, downgrades migrations, deletes bucket objects, or exposes private objects. The `.env.example` values are development-only values, never production or Cloudflare credentials.

## Stop, restart, and preserve state

```sh
docker compose -p launchpad-dev stop
docker compose -p launchpad-dev up -d
```

An ordinary stop/start preserves the PostgreSQL, Redis, and MinIO named volumes. To confirm this in a disposable environment, write a record and a private object through the running services, stop the project, start it again, and read them back. Do not use global Docker cleanup commands for this workflow.

When application code or configuration changes, rerun:

```sh
docker compose -p launchpad-dev up -d --build
```

The preparation process rechecks migration and bucket state. If a forward migration is incompatible, stop the affected project, restore from a backup or apply a forward corrective migration, then start it again. The project never automatically downgrades a migration or clears persisted data.

## Run the quality gate

Checks use a second Compose file and check-only credentials/volumes. They do not mount or clean the development project. Run the same command locally that GitHub Actions invokes:

```sh
COMPOSE_PROJECT_NAME=launchpad-check sh scripts/quality/run.sh
```

The gate reports these passing categories: `format`, `lint`, `types`, `tests`, `web-format`, `web-lint`, `web-types`, `web-tests`, `migrations`, `contracts`, `builds`, `security`, and `browser`. The contracts category generates and checks the shipped REST/OpenAPI and GraphQL schema/operation types. WebSocket is **not applicable** because this foundation has no WebSocket feature. Any failed, missing, or unavailable category exits nonzero; a category is never reported as passing by omission. Security checks cover production dependencies, source secrets, and the built web image without exposing an application container to the Docker socket.

To prove that failure propagation is working without running the whole gate:

```sh
LAUNCHPAD_QUALITY_ONLY=controlled-failure sh scripts/quality/run.sh
```

It must exit nonzero and print `controlled-failure`. CI captures command output only; do not add credentials or private object contents to diagnostics.

## Account, recovery, and profile operations

The identity endpoints deliberately use privacy-preserving responses. Registration and
password-reset requests return the same accepted result for known and unknown email
addresses. A verification or reset challenge is digest-only in PostgreSQL and is sent
only through the encrypted transactional outbox. Links expire after 60 minutes, and the
latest request supersedes earlier links. A reset consumes the challenge, changes the
Argon2id password, and revokes all sessions (including other devices). Members must
verify their email before publishing or voting; sign-in itself may establish a session
while the account remains unverified.

Every new profile is private. The owner can edit it while signed in, but publication
requires a display name, non-empty bio, at least one valid link, a validated photo, and
a verified email. Removing a required field from a published profile automatically
returns it to private and emits a privacy notice. Public profile and photo reads consult
current PostgreSQL visibility on every request. Private photos are stored in the
private MinIO bucket and served only through the gated API with `Cache-Control:
no-store`; never paste a staging upload URL or object key into a ticket, log, or browser
markup.

The session is an opaque server-side record represented by a host-only HTTP-only
`__Host-` Secure, SameSite=Lax cookie. The supported local entries are exactly
`http://localhost:8080` and `http://127.0.0.1:8080`; Secure cookies are permitted on
loopback localhost. Unsafe browser requests also require the session-bound CSRF value
and a trusted Origin. The local Compose configuration declares both values in
`LAUNCHPAD_TRUSTED_WEB_ORIGINS`; other ports, schemes, and hosts are rejected. For
production, set `LAUNCHPAD_TRUSTED_WEB_ORIGINS` explicitly to the HTTPS web origins
that should be trusted; localhost is never added automatically. Do not disable Secure
cookies or derive email links from the incoming Host header.

### Mail and recovery troubleshooting

Mailpit is available at http://localhost:8025 in the development Compose project. If
SMTP or Mailpit is down, the API keeps the account/profile transaction committed and
the encrypted outbox remains pending for bounded worker retries. Check `prepare`,
`worker`, and `scheduler` logs, restore the configured mail dependency, and request a
new verification/reset email. Do not reset volumes or edit challenge rows. A successful
password reset invalidates every existing session; the member must sign in again on
each device. Expired or superseded links are expected safe failures, not evidence of a
missing account.

### Forward migration recovery

Preparation applies only forward Alembic migrations and compares readiness with the
current migration head. It never downgrades or clears data. If preparation reports a
pending or incompatible revision, stop that Compose project, preserve its named
volumes, restore a compatible backup or apply a corrective forward migration, then
rerun the normal startup command. Re-run the isolated quality project separately; do
not use global Docker prune/reset commands while investigating a developer database.

## Product draft and staff operations

Product submission is disabled by default outside local/check environments. The product schema is
additive through migration `0005_product_drafts_submission`; founder-selected topic labels require
`0006_product_topic_labels`. API and worker readiness require the exact current migration head, so
pre-0006 binaries are not a rollback target after this rollout.

For a controlled release, drain every pre-0006 API, worker, and scheduler binary, apply migrations
through 0006, then start the 0006-compatible API and typed worker with product activation still off.
Verify readiness, worker/scheduler health, and migration head before enabling the feature. If a
release must be rolled back, disable product activation but keep the 0006-compatible API/worker
images and schema in place. Do not downgrade the database or restore an older email-only worker:
it cannot safely consume product events. Local and quality Compose configurations intentionally
enable products to exercise the feature; production must explicitly opt in only after the compatible
rollout is healthy.

Roles and suspension are managed only by the restricted operator CLI, never a public endpoint. Run
it from the repository's operator environment with database access supplied through the approved
secret manager (do not place credentials in shell history or logs). Use a stable, accountable actor
identity; each successful change writes an `account_admin_actions` audit row with before/after state.
For example:

```sh
PYTHONPATH=apps/api python scripts/operators/manage_accounts.py --actor '<operator-identity>' --account-id '<account-uuid>' set-role --role reviewer
PYTHONPATH=apps/api python scripts/operators/manage_accounts.py --actor '<operator-identity>' --account-id '<account-uuid>' suspend
PYTHONPATH=apps/api python scripts/operators/manage_accounts.py --actor '<operator-identity>' --account-id '<account-uuid>' resume
```

The supported roles are `member`, `reviewer`, and `admin`. Suspension blocks founder product
changes, but does not trap an already-submitted product: its founder may still withdraw it. Staff
reviewers/admins see only the current submitted record. Never grant roles by editing rows outside
the audited service/CLI workflow.

## Private media and deletion operations

Product photos use short-lived signed staging uploads to the private object store (currently five
minutes). A successful attachment is still private: reads pass through the API, which checks the
current database visibility and attachment state on every request. The API does not return direct
object-store URLs. Deleting a draft first checks storage availability; if that preflight fails, the
request fails and the draft remains available to retry. Once deletion commits, database state and an
encrypted `product.media_purge.v1` outbox event commit together, revoking access immediately. Physical
purge is asynchronous and retries safely; an outstanding signed staging upload may remain usable
until its short expiry, after which the worker can remove the object.

Check service health and recent failure classes without dumping event payloads:

```sh
docker compose -p launchpad-dev ps
docker compose -p launchpad-dev logs --since=30m --no-color api worker scheduler prepare
```

The API/worker logs identify event ID/type and failure class, not object keys or payloads. If a purge
is stuck, use restricted, audited database access to inspect metadata only:

```sql
SELECT id, event_type, state, attempts, available_at, claimed_at
FROM outbox_messages
WHERE event_type = 'product.media_purge.v1'
  AND state IN ('pending', 'claimed', 'dead')
ORDER BY available_at;
```

Workers retry transient failures with bounded backoff and dead-letter after eight attempts. There is
currently no replay command. After correcting the underlying storage/configuration issue, an
authorized operator may replay one confirmed dead event in a transaction, recording its event ID
in the incident/change log. Do not select or print `encrypted_payload`, `key_id`, storage URLs, or
object keys. Bind the exact inspected event UUID in place of `'<event-uuid>'`:

```sql
BEGIN;
UPDATE outbox_messages
SET state = 'pending', attempts = 0, available_at = now(), claimed_at = NULL,
    completed_at = NULL
WHERE id = '<event-uuid>'
  AND event_type = 'product.media_purge.v1'
  AND state = 'dead'
  AND encrypted_payload IS NOT NULL
RETURNING id, state, attempts;
-- Inspect the result interactively. COMMIT only for exactly one expected row;
-- otherwise issue ROLLBACK and investigate.
```

Keep the database session open after the update until its returned row has been checked; do not run
the whole block non-interactively with an unconditional commit.

The purge handler is idempotent, so a retry after a successful-but-unacknowledged storage delete is
safe. If the event is not eligible for replay or repeatedly dead-letters, preserve the draft/deletion
and event metadata, escalate to the storage/database operator, and do not manually delete objects.

## Deliberate reset of a disposable project

This is the only command in this guide that deletes data. Use it only after checking the exact project name and only for a disposable environment:

```sh
docker compose -p launchpad-dev down --volumes --remove-orphans
```

It removes the named PostgreSQL, Redis, and MinIO volumes belonging to `launchpad-dev`, together with that project's containers and network. It does not affect a different project such as `launchpad-check` or any other Compose project. Never substitute a global Docker prune command.

## Cloud storage boundary

MinIO is the local, S3-compatible private object store. Staging and production Cloudflare R2 configuration is intentionally outside this foundation; do not put R2 credentials in local files, Compose configuration, logs, or CI output.
