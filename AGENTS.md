# Launchpad Engineering Instructions

## Purpose and source of truth

Launchpad is a daily product-launch platform. Product and engineering context lives in:

- `docs/source/launchpad-client-brief.md` — original client requirements
- `docs/source/engineering-guide.md` — approved engineering direction
- `specs/requirements/REQ-*.md` — sprint-sized, verified requirements
- `specs/architecture/ARCH-*.md` — architecture-only designs
- `specs/tasks/TASKS-*.md` — implementation tasks and verification modes

Read the applicable requirement, architecture, and task documents before changing code. Do not implement work that is not in the active task.

## Required stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2 async, Pydantic, Alembic, pytest
- APIs: REST for commands and integrations; Strawberry GraphQL for read composition; FastAPI WebSockets for live updates
- Data: PostgreSQL is authoritative; Redis is cache, rate limiting, pub/sub, and Dramatiq broker only
- Frontend: React, TypeScript strict mode, Vite, Tailwind, TanStack Query
- Background work: Dramatiq workers plus a scheduler process
- Storage: S3-compatible private storage with signed upload/download URLs

## Architecture rules

- Build a modular monolith. Keep separate deployable API, worker, and scheduler processes; do not add microservices without an ADR.
- Organize FastAPI code by feature module. Each feature owns routes, GraphQL resolvers, services, repositories, models, schemas, tests, and permissions.
- REST routes and GraphQL resolvers are thin transport layers. Business decisions belong in services; persistence belongs in repositories.
- Do not import one feature's repository from another. Cross module boundaries through a named service interface or domain event.
- Use PostgreSQL constraints and transactions for business invariants. Client-side checks are not the final authority.
- Keep cache state rebuildable. Never use Redis as the sole record of a vote, launch, user, or audit event.

## Security and product invariants

- No unpublished product or media may be available through REST, GraphQL, search, cache, logs, analytics, or storage URLs.
- Require verified email for voting. A founder cannot vote for their own product. One active vote per member/product.
- Keep product transitions explicit: draft -> submitted -> changes requested/rejected/approved -> scheduled -> launched. Staff removal/suspension is audited.
- Use named authorization policies and enforce them at REST, GraphQL, and service boundaries.
- Hash passwords with Argon2id. Use HTTP-only, Secure, SameSite cookies. Never expose secrets or stack traces.
- Insert outbox events in the same database transaction as user-visible state changes. Workers must be idempotent and retry safely.
- Archived daily ranks are immutable after cutoff.

## Python and FastAPI standards

- Use complete type annotations. Run Ruff, formatter, mypy or pyright, and pytest for affected work.
- Use Pydantic schemas at API boundaries; never return ORM models directly.
- Use async database sessions consistently. Avoid blocking I/O in request handlers.
- Write forward-compatible Alembic migrations. Never rewrite a migration already shared or applied.
- Parameterize all queries. Review indexes for all new `WHERE`, `JOIN`, and `ORDER BY` patterns.
- Return typed domain errors from services; map them to safe REST/GraphQL responses at the transport layer.

## Frontend standards

- TypeScript strict mode is mandatory. Do not hand-maintain API types; generate from REST and GraphQL schemas.
- Keep server state in TanStack Query and UI-only state local or in a small dedicated store.
- Build accessible, semantic, keyboard-operable, mobile-first components.
- Optimistic updates require a rollback path and reconciliation with the server response.

## Quality workflow

- Follow dev-pipeline artifacts and each task's verification mode: `tdd`, `test-after`, `ui`, or `checklist`.
- For `tdd`, work RED -> GREEN -> REFACTOR. For every task, provide verification evidence before declaring it complete.
- Include tests, migrations, observability, and documentation with every completed feature.
- Use small conventional commits, one completed task per commit.
- Stop and request confirmation for destructive migrations, irreversible changes, secrets, authorization changes, or ambiguity in requirements.

## Product and design references

Read `docs/source/inspiration.md` before planning public-facing product or UI work.

Use Product Hunt only for feature-pattern research and Nick Launches only for visual direction.
Never copy branding, layouts, copy, screenshots, assets, or proprietary behavior.

When a task explicitly needs a generated visual asset, use the configured Higgsfield MCP.
Do not generate imagery unless the task needs it.
