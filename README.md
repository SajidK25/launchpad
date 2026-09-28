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

## Member identity and profiles

Registration always returns the same accepted response for a valid new or existing
address. The account starts unverified and its profile starts private. A verification
or password-recovery email contains a single-use link that expires after 60 minutes;
requesting another link supersedes the previous one. Password reset changes the
Argon2id hash and revokes every active session, so all signed-in devices must sign in
again. Reset requests are intentionally generic and never disclose whether an address
has an account.

Members can edit their private profile after signing in. A profile needs a display
name, bio, at least one link, and a validated photo before it can be published. Removing
required information from a published profile automatically makes it private and queues
a notice. Photos stay in private object storage: only the owner or a current public
profile can receive the API's short-lived, `no-store` image response; staging upload
URLs and object keys are never public.

The browser uses a host-only, HTTP-only, Secure, SameSite=Lax cookie. The supported
Linux Compose development entry is `http://localhost:8080`; browsers allow Secure
cookies on the loopback `localhost` origin. Check the browser at that exact host (not a
raw container hostname). Non-local deployments must use HTTPS. Transactional mail is
delivered by the worker through Mailpit locally or the configured SMTP service. If mail
is unavailable, the durable outbox retries delivery; operators should inspect the
outbox/worker logs and request a fresh link rather than changing database rows manually.

## Local-only credentials

The values in [`.env.example`](.env.example) describe local development defaults. They are not production credentials. Local object storage is private MinIO; Cloudflare R2 is reserved for future staging and production work.
