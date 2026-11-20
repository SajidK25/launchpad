# ADR 0010: Public discussion uses durable bounded threads and live invalidation

## Status

Accepted.

## Context

Launched products need a public conversation surface without making discussion a route around product visibility, allowing unbounded page reads, or depending on Redis for durable state. Posting must tolerate retries and concurrent activity, preserve current public attribution, and remain useful when live delivery is interrupted. The first release supports top-level comments and exactly one reply level; it does not include editing, deletion, reactions, notifications, reporting, moderation, anonymous posting, staff posting, or deeper nesting.

## Decision

The modular monolith owns discussion in `apps/api/app/modules/comments`. PostgreSQL is authoritative for immutable visible entries and durable idempotency receipts. One `comments` table represents roots and replies; depth, parent, product, body, moderation status, and composite self-reference constraints enforce one-level same-product topology. Migration `0017_comments_replies` is additive. It must be applied forward and is not a production rollback target after compatible code is deployed.

The comments module crosses product and user ownership through named service interfaces:

- `ProductDiscussionAccess` decides whether a product is currently public and may lock it for posting.
- `CommentAuthorAttributionAccess` resolves current display name, validated photo, and optional public-profile link without exposing private profile fields.
- `CommentAuthorActivityAccess` lets the users module prevent clearing a required display name or validated photo while visible discussion entries exist.

Comments never import another feature's repository. Product visibility gates every GraphQL read, command, public author-photo read, live ticket, socket admission, and periodic socket revalidation. Current author attribution is batched for reads. A private profile removes the profile link but does not make a public entry anonymous.

Public composition uses bounded Strawberry GraphQL queries: `productDiscussion` pages newest-first roots and includes only the three newest replies in chronological display order; `commentReplies` pages earlier replies for one visible root. Authenticated commands use CSRF-protected REST routes with an `Idempotency-Key`. The service validates eligibility, plain text, one-level topology, rolling limits, duplicate text, and product visibility inside the transaction. A confirmed new command returns `201`; an exact durable replay returns `200` with `replayed=true`. The browser never presents an unconfirmed optimistic entry.

Every committed entry inserts an encrypted `comment.created.v1` outbox event in the same PostgreSQL transaction. The worker revalidates the stored entry and public product before publishing an identifier-only frame through Redis. Product-scoped FastAPI WebSockets use short-lived HMAC tickets derived with domain separation from the configured outbox key. Frames contain only product, comment, and nullable parent identifiers. They are invalidation hints, not replicated discussion state. New roots and replies for unloaded parents wait behind a notice; replies for loaded parents invalidate that reply query. Reconnection invalidates roots and every loaded reply page. `discussion.closed` clears discussion projections and stops that live session.

Redis remains rebuildable delivery infrastructure for rate limiting, pub/sub, and connection leases. A Redis interruption can delay or lose hints, but PostgreSQL reads, durable posting, and outbox state remain authoritative. After reconnection, bounded GraphQL refetches reconcile missed activity without discarding local drafts.

Rollout uses two flags with a strict dependency: `LAUNCHPAD_COMMENTS_ENABLED` mounts reads, public author photos, tickets, live delivery, and worker publication; `LAUNCHPAD_COMMENT_WRITES_ENABLED` admits posting and is invalid unless the feature flag is also enabled. The production sequence is additive migration, compatible code with both flags off, reads/live on, then writes on. Rollback disables writes and then the feature while retaining the compatible code, migration, entries, receipts, and pending outbox work. Production data is never downgraded or deleted as a flag rollback.

## Alternatives considered

- Separate comment and reply tables were rejected because one constrained self-reference expresses the bounded topology and supports shared safeguards.
- REST reads and GraphQL mutations were rejected in favor of the repository's GraphQL composition and REST command conventions.
- GraphQL subscriptions and database polling were rejected because product-scoped FastAPI WebSockets already fit the live boundary and identifier-only invalidation limits payload sensitivity.
- Publishing from the request handler was rejected because it can lose events after a committed entry; transactional outbox publication is durable and retryable.
- Redis counters or streams as the record of discussion were rejected because Redis is not authoritative and must remain rebuildable.
- Unlimited nesting, optimistic publication, and a global client discussion store were rejected because they complicate mobile presentation, rollback, and race reconciliation.

## Consequences

Discussion reads remain bounded and public only with a public launched product. PostgreSQL constraints and row locks carry invariants under concurrency. Exact command retries create at most one entry, while repeated text and rolling burst limits remain separate policies. Public attribution remains current, so users with visible entries cannot clear their display name or validated photo; they may replace either and may keep the profile private.

Live delivery is eventually fresh rather than authoritative. Clients must keep drafts and notice/socket state local, refetch after reconnection, and tolerate duplicate or missing invalidations. Operators must preserve the outbox key, Redis, trusted origins, and compatible worker configuration, but must never log comment bodies, body fingerprints, tickets, raw IP addresses, emails, storage keys, encrypted payloads, or private-product facts. Safe operational signals are event type/ID, failure class, attempt count, dead-letter state, aggregate rejection counts, and connection/reconnect counts.

Deferred capabilities require separate requirements and authorization rules. This decision does not establish editing, deletion, reactions, notifications, reporting, moderation, staff participation, anonymous participation, or more than one reply level.
