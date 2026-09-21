# Launchpad

Launchpad is a local-first foundation for a daily product-launch platform. It runs the web application, API, worker, scheduler, PostgreSQL, Redis, MinIO, and Mailpit through Docker Compose.

Linux with Docker Engine and the Docker Compose plugin is the supported local development platform for this foundation. No host Python or Node installation, cloud account, or cloud credentials are required.

## Start locally

From the repository root, choose a project name that is unique on your machine and start the complete environment:

```sh
docker compose -p launchpad-dev up -d --build
```

Compose waits for PostgreSQL and MinIO, then runs the preparation process before starting the API, worker, and scheduler. Open http://localhost:8080 and confirm that the page reports **Connected**.

The development web page is available at http://localhost:8080, the API at http://localhost:8000, the MinIO API and console at http://localhost:9000 and http://localhost:9001, and Mailpit at http://localhost:8025. All published ports bind to loopback.

For checks, recovery, data-preservation guidance, and the deliberate reset procedure, read [the development guide](docs/development.md).

## Local-only credentials

The values in [`.env.example`](.env.example) describe local development defaults. They are not production credentials. Local object storage is private MinIO; Cloudflare R2 is reserved for future staging and production work.
