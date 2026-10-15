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

Mailpit is available at http://localhost:8025 with the default development Compose ports. The
eyeball-test override below maps its web UI to http://localhost:8028 to avoid a local port conflict. If
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

Product submission is disabled by default outside local/check environments via
`LAUNCHPAD_PRODUCTS_ENABLED=false`. The product schema is additive through migration
`0005_product_drafts_submission`; founder-selected topic labels require `0006_product_topic_labels`,
and the submission-history lookup index is added by `0007_product_submission_idx`. API
and worker readiness require the exact current migration head, so pre-0007 binaries are not a
rollback target after this rollout.

For a controlled release, keep `LAUNCHPAD_PRODUCTS_ENABLED=false`, drain every pre-0007 API, worker,
and scheduler binary, apply migrations through 0007, then start the 0007-compatible API and typed
worker. Verify readiness, worker/scheduler health, and migration head before setting
`LAUNCHPAD_PRODUCTS_ENABLED=true`. If a release must be rolled back, set it back to `false` but keep
the 0007-compatible API/worker images and schema in place. Do not downgrade the database or restore an older email-only worker:
it cannot safely consume product events. Local and quality Compose configurations intentionally
enable products to exercise the feature; production must explicitly opt in only after the compatible
rollout is healthy.

Roles and suspension are managed only by the restricted operator CLI, never a public endpoint. Run
it from the repository's operator environment with `LAUNCHPAD_DATABASE_URL` injected through the
approved secret manager (do not print it or place credentials in shell history or logs). Use a stable, accountable actor
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

### Production transactional email

Production transactional email is sent through Resend by the worker. Provision
`LAUNCHPAD_RESEND_API_KEY` from the approved secret manager directly into the worker environment;
keep it out of API and scheduler environments, source control, command history, and logs. The worker
also needs `LAUNCHPAD_MAIL_SENDER` set to a verified Resend sender. `.env.example` contains only an
empty placeholder, and local/check environments continue to use Mailpit SMTP.

The outbox retains bounded retries and uses the stable event ID as Resend's idempotency key. Resend
retains idempotency keys for 24 hours, so automatic retry stays within the provider window. For an
ambiguous replay after that window, inspect the outbox delivery state and the provider receipt before
manually replaying; do not blindly resend, since the original email may already have been accepted.

### Review workflow rollout

Keep `LAUNCHPAD_REVIEW_WRITES_ENABLED=false` during rollout. Apply forward migrations through the
target release's declared schema head (including `0010_review_read_indexes` for the original review
release); then start a compatible worker with the Resend key before any API can write review events.
Deploy the compatible API with review writes still disabled, drain all old API and worker processes,
and verify API readiness, worker health, and outbox processing. Only then enable review writes. If
writes need to be disabled, turn the flag off and keep the compatible binaries and schema in place so
committed decisions and queued events remain readable and dispatchable. Do not downgrade immutable
review history as part of rollback.

For local review development, use only the development values in `.env.example` with the
`launchpad-dev` Compose project. The API, worker, and scheduler use the local Redis service for
queues and account-scoped notification hints; Mailpit receives transactional messages at
http://localhost:8025. Do not add a production Resend key or production database/storage settings to
the local environment. Keep the review write flag enabled only in development/check environments;
the production value is an explicit operator-controlled rollout setting.

#### Review outcome delivery incidents

A successful staff decision is committed together with its immutable decision row and founder inbox
item. An email delay or failure does not reverse that decision. First confirm the decision and inbox
item in the application, then inspect worker logs for the outbox event ID, event type, failure class,
and `dead_lettered` flag. Logs must not include feedback, recipient addresses, tokens, payloads, or
provider keys.

An authorized operator can inspect delivery state using metadata only:

```sql
SELECT o.id, o.event_type, o.state, o.attempts, o.available_at,
       o.claimed_at, o.completed_at, d.message_id, d.sent_at
FROM outbox_messages AS o
LEFT JOIN email_deliveries AS d ON d.event_id = o.id
WHERE o.event_type = 'review.outcome_email_requested.v1'
  AND o.state IN ('pending', 'claimed', 'dead', 'completed')
ORDER BY o.available_at, o.id;
```

`pending` means the bounded retry schedule can still process the notice; `claimed` means a worker
currently owns it; `completed` with an `email_deliveries` row means the worker recorded provider
acceptance. A `dead` event does not tell you whether Resend accepted the message before the worker
failed. Preserve the event ID and inspect the Resend receipt using the idempotency key
`launchpad-<event-id>` through the authorized provider console. Never copy recipient details or
provider payloads into shared logs or tickets.

Resend retains idempotency keys for 24 hours. Within that window, retrying the exact event with its
original ID and payload is protected by the provider key. After that window, do not automatically or
blindly replay: if Resend confirms acceptance, record the reconciliation and do not send again; if
acceptance is unclear, leave the event for operator follow-up; if Resend definitively confirms no
acceptance, have an authorized operator coordinate a controlled recovery that preserves the original
event ID. There is no supported public replay command. Do not edit ciphertext, generate a new event
ID, or bypass the review transaction. The durable decision and inbox remain available while the mail
incident is resolved.

For metrics and incident notes, use event type, event ID, failure class, attempt count, and whether
the event is pending or dead. Do not record review feedback, email address, authentication/session
tokens, encrypted payload, Resend key, signed media URL, or private object key.

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

## Eyeball-test product draft submission

This short manual pass exercises one founder and one reviewer in the local development stack. It
creates test accounts, products, and private media; use disposable local data only. It does not
approve or launch products.

Before the first start, confirm the development ports are free and the existing `launchpad_default`
Docker network is empty:

```sh
docker ps --format '{{.Names}} {{.Ports}}'
docker network inspect launchpad_default
```

If any required port (8080, 8000, 9000, 9001, 1027, or 8028) is occupied, stop here and resolve the
port conflict without stopping another project. The temporary override below maps Mailpit to host
ports 1027/8028 to avoid the existing service on 1025; the app still uses Mailpit's internal port
1025. If `launchpad_default` is missing or has containers from another project, do not reuse it; ask
the Docker administrator to free network capacity or provide an approved isolated network. Do not
prune Docker resources. On later starts, the network may already contain this project's
`launchpad-dev-*` containers; proceed only when all attached containers belong to this project. When
the network is empty before first startup, create this temporary
Compose override so this project can reuse it without allocating another Docker subnet:

```sh
cat > /tmp/launchpad-dev-network.yaml <<'YAML'
networks:
  default:
    external: true
    name: launchpad_default
services:
  mailpit:
    ports: !override
      - 127.0.0.1:1027:1025
      - 127.0.0.1:8028:8025
YAML
```

Build and start the complete development stack, then check service state and readiness:

```sh
docker compose -p launchpad-dev -f compose.yaml -f /tmp/launchpad-dev-network.yaml up -d --build
docker compose -p launchpad-dev -f compose.yaml -f /tmp/launchpad-dev-network.yaml ps
curl --fail --silent --show-error http://localhost:8080/api/v1/health/ready
```

Open the app at [http://localhost:8080](http://localhost:8080) and Mailpit at
[http://localhost:8028](http://localhost:8028). Keep the browser on `localhost` throughout this test;
the API's signed image-upload URL is expected to use `http://localhost:9000`, not the internal
Docker hostname `minio`. If an upload fails, inspect the browser Network panel's signed URL host
first. Do not expose the bucket or make product objects public. Only investigate a development-only
MinIO CORS setting if the URL is `localhost:9000` and the browser still reports an origin failure;
production origin validation must remain unchanged.

1. Register two fresh, disposable accounts: founder A and reviewer B. Use passwords that meet the
   local password policy. Registration should give the same generic response whether an address is
   new or already registered.
2. In Mailpit, open B's verification message and follow its `localhost:8080/verify` link. Leave A
   unverified for now.
3. Sign in as A and open `/products`. Create a product draft, enter a name and pitch, and wait for
   the save status to say “Saved”. Copy the draft URL from the address bar, reload, and confirm the
   content remains.
4. Sign out, then try opening A's draft as B and as a signed-out visitor. Neither should see its
   content or media. Sign back in as A and verify that the draft remains editable while the account
   is unverified.
5. As A, attempt to submit before verifying the email. Confirm submission is blocked and the draft
   stays private. Verify A from Mailpit, then return to the draft.
6. Complete the required fields: name (up to 80 characters), pitch (up to 160), description (up to
   5,000), an HTTPS website, and 1–3 topics (up to 40 characters each). Upload one logo and at least
   one screenshot in JPEG, PNG, or WebP format, each no larger than 5 MB. Wait for each upload to
   finish validation and attachment.
7. Try submitting once with a required field missing. Confirm the page identifies the missing
   information and does not submit. Restore the field, wait until saving finishes, then submit for
   review. Confirm the founder view says it is in review and does not make the product public.
8. Temporarily grant reviewer access to B through the audited operator CLI. Look up B's ID in the
   local development database, then set the role:

   ```sh
   docker compose -p launchpad-dev -f compose.yaml -f /tmp/launchpad-dev-network.yaml exec -T postgres \
     psql -U launchpad_development -d launchpad_development -Atc \
     "SELECT id FROM accounts WHERE email_key = lower('REVIEWER_B_EMAIL')"
   docker compose -p launchpad-dev -f compose.yaml -f /tmp/launchpad-dev-network.yaml run --rm --no-deps \
     -v "$PWD/scripts/operators/manage_accounts.py:/workspace/scripts/operators/manage_accounts.py:ro" \
     api python scripts/operators/manage_accounts.py --actor local-eyeball-test \
     --account-id '<reviewer-b-uuid>' set-role --role reviewer
   ```

   Replace `REVIEWER_B_EMAIL` with B's address and `<reviewer-b-uuid>` with the returned UUID; do
   not put passwords or verification tokens in commands. Sign out and back in as B so the session
   reflects the new role, then open `/products/review`. Confirm A's submission appears in the queue
   and its current details and private media are visible to the reviewer.
9. Restore B to the ordinary member role by repeating the audited operator command with
   `set-role --role member`. The CLI is mounted read-only into a one-off container for this command;
   it is intentionally not included in the API image. Sign B out and back in, then confirm
   `/products/review` is unavailable to B again. No moderation decision is part of this eyeball test.

If something fails, note the page, action, visible message, and failing request/status from the
browser Network panel. Avoid recording credentials, verification tokens, cookies, signed URLs, or
private object keys. Preserve the development volumes while investigating; the documented reset
below is only for disposable data and is not needed to rerun this test.

## Deliberate reset of a disposable project

This is the only command in this guide that deletes data. Use it only after checking the exact project name and only for a disposable environment:

```sh
docker compose -p launchpad-dev -f compose.yaml -f /tmp/launchpad-dev-network.yaml down --volumes --remove-orphans
```

It removes the named PostgreSQL, Redis, and MinIO volumes belonging to `launchpad-dev`, together with that project's containers. Because the override declares `launchpad_default` as external, it leaves that shared network in place. It does not affect a different project's containers or volumes. Never substitute a global Docker prune command.

## Cloud storage and production deployment

MinIO is the local, S3-compatible private object store. Production uses a private Cloudflare R2 bucket through the same storage boundary and routes uploads through authenticated, size-limited API endpoints. Do not put R2 credentials in local files, development Compose configuration, logs, or ordinary CI output. See [the Proxmox production deployment guide](PRODUCTION_DEPLOYMENT_PROXMOX.md), [ADR 0007](adr/0007-production-deployment-storage.md), and the [production recovery runbook](PRODUCTION_RECOVERY.md) for the production decisions and operator requirements. Those documents describe the implementation and recovery procedure; they do not establish that production infrastructure or a restore has been verified.
