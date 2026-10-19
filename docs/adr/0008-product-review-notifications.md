# ADR 0008: Product review decisions and founder notifications

## Status

Accepted.

## Context

Staff need to make explicit, auditable decisions on a specific product submission, while founders need private, durable outcomes and actionable feedback. The review decision must remain committed even when email or live delivery is unavailable. No review outcome should expose an unlaunched product or its media publicly.

## Decisions

### Lifecycle and audit

- Product and submission states are explicit. A founder may edit a private draft or a product returned as `changes_requested`; submitted products are reviewed against the current submission ID and product version. A founder may withdraw a pending submission to a private draft.
- `approved` and `rejected` products remain private and locked to the founder. Rejection is terminal in this workflow. Staff may return an approved product for changes through a new immutable decision; that action does not erase the original approval.
- Authorized staff have a separate approved-products list and detail view so they can find eligible products for that return-to-changes action. Public visitors still cannot read approved product content.
- Each effective staff action inserts an immutable `ProductReviewDecision` in PostgreSQL with its actor, submission, reviewed version, outcome, feedback, and idempotency identity. Reviewed products and decisions are retained; founder hard deletion is limited to never-reviewed drafts.
- The REST decision command checks reviewer authorization, locks the product row, validates the submission/version, and requires an idempotency key. Database constraints and the service transaction enforce one effective action per permitted lifecycle step.

### Transactional notifications and privacy

- In one PostgreSQL transaction, the review state change, immutable decision, founder inbox notification, and encrypted outbox event are committed together. A delivery outage cannot undo a staff decision or lose the durable inbox item.
- The inbox and unread count are authoritative in PostgreSQL and scoped to the signed-in recipient. Opening one notification marks only that item read. The notification may expose an owner-only product ID for navigation, but never product content or reviewer-only fields.
- Redis pub/sub carries account-scoped invalidation hints only. The authenticated WebSocket prompts the client to refetch authorized GraphQL data; it does not carry feedback or product content. Redis is not the record of the decision, inbox, or read state.
- Unpublished products and media remain private for every state, including `approved` and `rejected`. Staff access is policy-checked; public product routes and publication are outside this workflow.

### Email delivery

- Production transactional email uses the Resend API through the worker. Local and check environments use SMTP with Mailpit. Only the worker receives the production Resend key.
- Review email is requested through the encrypted transactional outbox after commit. The worker resolves the current eligible recipient and sends a safe status/link notice; it does not put review feedback or private product content in email or logs.
- The stable outbox event ID is the Resend idempotency key. Automatic retry is bounded and stays within Resend's 24-hour idempotency retention. An ambiguous replay after that window requires checking both the outbox delivery record and Resend's provider receipt; never blindly resend. The committed decision and founder inbox remain authoritative while delivery is investigated.

### Rollout and rollback

- Keep `LAUNCHPAD_REVIEW_WRITES_ENABLED=false` during rollout. Apply forward migrations through the target release's declared schema head, start a compatible worker first, and deploy the compatible API with review writes still disabled.
- Drain old API and worker processes and verify migration head, readiness, worker health, and outbox processing before activating review writes.
- If review writes must be disabled, turn off the write flag and keep compatible API/worker binaries and the migrated schema. Existing decisions, inbox reads, and event delivery remain available. Do not downgrade migrations or delete review history as a rollback method.

## Consequences

Staff actions have durable product-specific history, and the founder's inbox works independently of email delivery. Live updates are small, private invalidation hints. Production email failures require worker/outbox operations and may need manual provider reconciliation after the idempotency window. Rollback disables new decisions while preserving reads and committed work. The workflow does not schedule or publish products.

## References

- [Product review workflow architecture](../../specs/architecture/ARCH-product-review-workflow.md)
- [Product review workflow requirements](../../specs/requirements/REQ-product-review-workflow.md)
- [Development and operations guide](../development.md#review-workflow-rollout)
