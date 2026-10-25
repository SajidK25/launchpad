# ADR 0009: Voting and daily ranking

## Status

Accepted.

## Context

Launchpad needs reversible member votes, abuse review, live daily ranking, and a durable daily archive. Vote changes and publication events must remain correct through retries, process restarts, and Redis outages. A ranking archive must not change after its UTC cutoff, including when staff later invalidate a vote.

## Decisions

### Durable state and event delivery

- PostgreSQL is authoritative for append-only vote history, idempotency receipts, risk flags, staff decisions, the first voting-enabled UTC date, and daily ranking snapshots and entries. Constraints and transactions enforce uniqueness and state transitions.
- A vote or staff decision and its outbox event commit in the same PostgreSQL transaction. Workers consume stable event identities idempotently; an unavailable worker delays projections but does not undo committed votes.
- Redis stores only a rebuildable current-day ranking projection and carries ranking invalidation messages. Its lexicographic ordered index encodes the complete score/count/name/ID tie comparator so reads can page current ranks without walking the catalog. It is neither the vote record nor the source for a closed archive; it can be reconstructed from PostgreSQL.

### Ranking and archives

- Current-day rank uses the configured exponential score with an initial six-hour half-life. Score, active vote count, normalized product name, and product ID form the deterministic order.
- The scheduler creates one PostgreSQL snapshot for each enabled UTC launch date at the 00:00 UTC cutoff. Snapshot entries include launches with zero votes. A unique date and idempotent outbox processing prevent duplicate archives.
- Once inserted, a daily snapshot is immutable. A later vote invalidation changes the live projection and all-time vote state but does not rewrite a closed daily archive. Dates before voting is enabled retain their legacy archive behavior and have no fabricated rank.
- The first-enabled UTC date is persisted once. If an operator does not pre-populate it during rollout, the first accepted vote initializes it to the API's current UTC date. Pre-populating the state before enabling writes makes the intended boundary explicit.

### Security and operations

- Voting requires a verified member, excludes a founder's own product, permits one active vote per member/product, and closes vote/withdraw commands at the product launch day's 00:00 UTC cutoff.
- Turnstile escalates high-risk vote actions. The public site key is a web build variable; the verification secret is API-only. Rate/velocity limits are operationally calibrated and are not fixed by this ADR.
- Production source velocity uses Cloudflare's `CF-Connecting-IP` only on the loopback-bound Tunnel ingress; the web proxy replaces the forwarded address passed to the API. The endpoint must remain unreachable except through that trusted ingress. Velocity counter increment and first-hit expiry execute atomically in Redis.
- The public ranking WebSocket observes client receive/disconnect events concurrently with Redis pub/sub reads and always closes its subscription on disconnect or cancellation.
- `LAUNCHPAD_VOTE_WRITES_ENABLED` defaults to false. Deploy the additive schema and compatible API/worker/scheduler first, verify consumers and configuration, then explicitly enable writes. Rollback disables writes while compatible consumers continue draining committed outbox work. Retain vote/audit records, snapshots, and schema; do not downgrade destructively.
- PostgreSQL/configuration backups follow the existing weekly and pre-migration policy. Restore evidence must come from an isolated restore exercise.

## Consequences

Vote history and audit survive cache loss, and current ranks can be rebuilt. Closed daily rankings remain stable after moderation. Redis or worker outages can delay live updates, while PostgreSQL remains available as durable truth. Peak concurrency, Turnstile thresholds, and idempotency receipt retention remain staging/operations calibration decisions.

## References

- [Voting and daily ranking architecture](../../specs/architecture/ARCH-voting-and-daily-ranking.md)
- [Voting and ranking requirements](../../specs/requirements/REQ-voting-and-daily-ranking.md)
- [Development and operations guide](../development.md#voting-and-ranking)
- [Proxmox production deployment guide](../PRODUCTION_DEPLOYMENT_PROXMOX.md#voting-rollout-and-rollback)
