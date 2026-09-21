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

The gate reports these passing categories: `format`, `lint`, `types`, `tests`, `web-format`, `web-lint`, `web-types`, `web-tests`, `migrations`, `contracts`, `builds`, `security`, and `browser`. It reports GraphQL and WebSocket as **not applicable** because this foundation has no feature using either transport. Any failed, missing, or unavailable category exits nonzero; a category is never reported as passing by omission. Security checks cover production dependencies, source secrets, and the built web image without exposing an application container to the Docker socket.

To prove that failure propagation is working without running the whole gate:

```sh
LAUNCHPAD_QUALITY_ONLY=controlled-failure sh scripts/quality/run.sh
```

It must exit nonzero and print `controlled-failure`. CI captures command output only; do not add credentials or private object contents to diagnostics.

## Deliberate reset of a disposable project

This is the only command in this guide that deletes data. Use it only after checking the exact project name and only for a disposable environment:

```sh
docker compose -p launchpad-dev down --volumes --remove-orphans
```

It removes the named PostgreSQL, Redis, and MinIO volumes belonging to `launchpad-dev`, together with that project's containers and network. It does not affect a different project such as `launchpad-check` or any other Compose project. Never substitute a global Docker prune command.

## Cloud storage boundary

MinIO is the local, S3-compatible private object store. Staging and production Cloudflare R2 configuration is intentionally outside this foundation; do not put R2 credentials in local files, Compose configuration, logs, or CI output.
