# Launchpad Engineering Guide

Architecture, coding standards, delivery plan, and production readiness for the Launchpad product-launch platform.

## 1. Architecture decisions

Build Launchpad as a **modular monolith**: one FastAPI domain codebase, deployed as separate API, worker, and scheduler processes. This keeps the product simple to operate while allowing each runtime concern to scale independently.

| Concern | Decision |
|---|---|
| Backend | FastAPI, SQLAlchemy 2 async, Alembic, Pydantic |
| Command API | REST endpoints |
| Read API | Strawberry GraphQL |
| Real time | FastAPI WebSockets with Redis pub/sub fan-out |
| Database | PostgreSQL is the source of truth |
| Cache and jobs | Redis with Dramatiq |
| Files | S3 or Cloudflare R2 with private, signed URLs |
| Frontend | React, TypeScript, Vite, Tailwind, TanStack Query |

FastAPI owns HTTP, GraphQL, and WebSocket endpoints. The worker handles asynchronous tasks, and the scheduler only enqueues due jobs. Do not begin with separate microservices.

## 2. Repository and module boundaries

```text
launchpad/
  apps/
    web/                         # React application
    api/app/
      modules/
        auth/ users/ products/ launches/ votes/ comments/
        feeds/ notifications/ moderation/ analytics/
      shared/
        db/ security/ events/ storage/ config/ observability/
    worker/                      # Dramatiq workers and scheduler
  packages/contracts/            # Generated OpenAPI and GraphQL client types
  infra/docker/
  infra/terraform/
  specs/                         # dev-pipeline artifacts
  docs/source/                   # Client brief and this guide
```

- A feature owns its routes, resolvers, services, repositories, models, tests, and permissions.
- Keep REST routes and GraphQL resolvers thin. Domain services make business decisions.
- Do not import another module's repository directly; expose a small service interface instead.
- Put helpers in `shared` only when they are genuinely cross-domain.
- Write one-page ADRs for decisions affecting data, security, deployment, or public contracts.
- Each feature is incomplete without migration, tests, observability, and documentation.

## 3. Data model and integrity

Core tables:

- Identity: `users`, `identities`, `sessions`, `email_verifications`, `password_resets`
- Product workflow: `products`, `product_assets`, `product_topics`, `reviews`, `launch_slots`
- Community: `votes`, `comments`, `comment_reports`, `product_reports`, `follows`
- Notifications: `notification_preferences`, `notifications`, `outbox_messages`, `email_deliveries`
- Analytics: `product_views`, `referral_events`, `daily_product_metrics`, `exports`
- Staff: `staff_actions`, `suspensions`, `takedowns`

Enforce critical product rules in PostgreSQL using foreign keys, unique indexes, check constraints, and transactions. Frontend validation is never the final authority.

- Use UUIDv7 or ULID identifiers and UTC `timestamptz` values.
- Use soft deletion with a moderation status for public content.
- Enforce one active vote using a partial unique index on member and product.
- Use row locking or a serializable transaction when reserving a limited launch slot.
- Never expose unpublished product fields through API responses, GraphQL resolvers, search indexes, caches, logs, analytics, or storage URLs.

## 4. Lifecycle and authorization

Product lifecycle:

```text
draft -> submitted -> changes_requested | rejected | approved
approved -> scheduled -> launched
any visible state -> removed or suspended (authorized staff only)
```

Centralize transitions in one domain service and record every staff action in an append-only audit log.

| Role | Permission summary |
|---|---|
| Visitor | Read only launched public content, profiles, topics, archives, and search |
| Member | Verified users can vote, comment, follow, report, and manage their profile/preferences |
| Founder | Member permissions plus own product drafts and submissions |
| Reviewer | Review queue, request changes, approve/reject, and resolve reports |
| Admin | Reviewer permissions plus suspensions, takedowns, featuring, and staff management |

Use named policies such as `product.edit`, `product.review`, `comment.moderate`, and `member.suspend`. Apply them in both REST dependencies and GraphQL permissions.

## 5. API design

Use REST for side-effecting commands and external boundaries:

- Login, password reset, email verification, and OAuth callbacks
- Product create, submit, schedule, and moderation actions
- Vote commands, uploads, export requests, downloads, and webhooks

Use GraphQL for read-heavy UI composition:

- Front page, past launch days, rankings, product pages, profiles, topics, feeds, search, notifications, and founder dashboard views

Rules:

- Version REST under `/api/v1` and publish OpenAPI.
- Generate TypeScript clients from REST and GraphQL schemas in CI.
- Use cursor pagination and stable sorting.
- Apply GraphQL depth, selection, and complexity limits; use persisted queries for public traffic.
- Return documented error codes only; never expose stack traces.
- Require idempotency keys for commands such as votes, scheduling, exports, and moderation.

## 6. Ranking, voting, and real time

PostgreSQL records every valid vote. Redis holds rebuildable leaderboard/cache state only. Update Redis after database commit through an outbox consumer.

Use a time-decayed score while a launch day is active:

```text
score(product, now) = sum(exp(-lambda * age_in_hours) for each valid vote)
```

Tune `lambda` from staging data; do not use unexplained magic values. At the daily cutoff, snapshot the final order in `daily_product_rankings`. Archive pages must read this immutable snapshot.

Vote eligibility:

- Verified email only
- No self-voting
- No suspended account
- Product already launched
- One active vote per member/product

Publish WebSocket events only after commit, and send only safe values such as product ID, current vote count, and ranking patch. Authenticate sockets and authorize subscriptions.

## 7. Background jobs and notifications

Use the transactional outbox pattern. In the same transaction that changes business state, insert an outbox event. A worker claims it, sends notification/email, records delivery, and retries safely. This prevents lost notifications during email-provider outages.

Use jobs for:

- Email verification and password reset
- Review outcome and comment notifications
- Launch reminders and launch publication
- Daily and weekly email digests
- Asynchronous CSV exports
- Daily ranking snapshots

Use exponential backoff with jitter, idempotency keys, deduplication per recipient/event, and a dead-letter state. Check notification preferences immediately before sending.

## 8. Search, feeds, analytics, and caching

- Start search with PostgreSQL full-text search and trigram indexes. Add Meilisearch/OpenSearch only when scale or relevance justifies it.
- Build follow feeds using cursor-paginated queries.
- Capture views and referrers asynchronously, filter bots, and use rollups for dashboards.
- Cache public pages and leaderboard slices, with cache keys including date, topic, and visibility state.
- Define TTL and invalidation ownership for every cache. All cache state must be rebuildable from PostgreSQL.

## 9. Security and anti-abuse

- Use Argon2id password hashing and secure HTTP-only, Secure, SameSite cookies.
- Store secrets in a cloud secret manager; never in Git, Docker images, browser bundles, logs, or errors.
- Validate media type and size; use random object keys, signed private URLs, and remove metadata.
- Apply rate limits, account/IP velocity checks, verified-email gates, CAPTCHA escalation, suspicious-vote flags, and human review.
- Use TLS, CSP, CSRF protection, CORS allowlists, output escaping, dependency scanning, and least-privilege permissions.
- Do not automatically ban someone from one weak anti-abuse signal or rely solely on hidden device fingerprinting.

## 10. Frontend standards

- Enable TypeScript strict mode, ESLint, Prettier, and Tailwind design tokens.
- Use semantic, accessible components and a small reusable component library.
- Keep server state in TanStack Query; keep UI-only state local or in a small store.
- Do not manually maintain API interfaces; generate them from the contracts.
- Make public pages responsive, keyboard accessible, SEO-aware, and equipped with canonical/Open Graph metadata.
- Use optimistic votes only with rollback and reconciliation against the authoritative server response.

## 11. Testing and quality gates

| Layer | Required coverage |
|---|---|
| Unit | State transitions, ranking, permissions, preferences, fraud rules |
| Integration | Migrations, constraints, transactions, locks, outbox, cache invalidation |
| Contract | REST/OpenAPI and GraphQL schema, auth matrix, pagination, errors, idempotency |
| End to end | Sign-up, submission/review/launch, votes, comments, reports, exports |
| Security | Authorization bypass, CSRF, rate limits, upload validation, dependency and secret scans |
| Load | Front-page reads, vote spikes, WebSockets, ranking close, worker retries |

Run integration tests against real PostgreSQL and Redis services in CI, not SQLite substitutes. Use a deterministic clock for launch and ranking tests.

## 12. Delivery and operations

- Local Docker Compose: web, API, worker, scheduler, PostgreSQL, Redis, and a mail catcher.
- Pull-request gates: format/lint, type checking, unit/integration tests, clean migration test, schema diff, security scan, image build.
- Deploy to staging first with a backup and forward-compatible migration plan.
- Use health checks and rolling or blue/green deployments.
- Add OpenTelemetry traces, JSON logs, metrics, error tracking, queue-depth alerts, uptime checks, and backup verification.
- Maintain runbooks for email backlog, launch-day incident, bad moderation action, cache flush, export backlog, and database restore.

## 13. Delivery sequence

1. Discovery and ADRs: launch timezone, cutoff, review rules, legal/privacy decisions, priority backlog.
2. Foundation: monorepo, Docker, CI, configuration, PostgreSQL/Redis, migrations, observability.
3. Identity and RBAC: authentication, Google OAuth, verification, profiles, sessions, permissions.
4. Product workflow: drafts, uploads, submit/review actions, audit records, scheduling.
5. Public launch: front page, archives, product pages, topics, search, responsive UI.
6. Community: votes, comments, follows, reports, real-time updates.
7. Notifications and jobs: outbox, preferences, retries, digests, reminders.
8. Founder dashboard: views, referrals, rank, queued private exports.
9. Hardening and release: load tests, threat review, backups, runbooks, monitoring, acceptance.

## 14. Definition of done

- Acceptance criteria pass on desktop and mobile.
- Each role and product state transition has authorization and visibility tests.
- Database migrations and API contracts are reviewed.
- Logs, metrics, trace context, and safe error behavior exist.
- Accessibility checks cover keyboard navigation, labels, focus order, contrast, and screen readers.
- No high-severity dependency findings or leaked secrets.
- Staging acceptance, rollback plan, and operational runbook are complete before production release.

## 15. Coding-agent workflow

Use dev-pipeline artifacts as the source of truth:

```text
specs/requirements/REQ-<slug>.md
  -> specs/architecture/ARCH-<slug>.md
  -> specs/tasks/TASKS-<slug>.md
  -> implementation, review, and QA artifacts
```

Work one sprint-sized vertical slice at a time. Have the agent read `AGENTS.md`, the relevant requirement, architecture, and task file before modifying code. Use the task's required verification mode, make one conventional commit per completed task, then run review and—when applicable—the QA gate.
