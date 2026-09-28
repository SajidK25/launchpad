# ADR 0005: Revocable member sessions and confidential recovery links

## Status

Accepted.

## Context

Launchpad needs email/password registration without account enumeration, verified-email
gating, and password recovery that remains safe when a link is forwarded or a member is
signed in on several devices. Requests can outlive an SMTP outage, and a reset must
invalidate credentials already issued to browsers.

## Decision

PostgreSQL is authoritative for accounts, opaque session records, and one-use email
challenges. Session IDs and challenge tokens are stored as digests; only the encrypted
outbox payload and the recipient link carry a raw challenge. Verification and reset links
expire after 60 minutes, and issuing a newer challenge supersedes the prior one. Reset
locks the account transition, updates the Argon2id password hash, increments the session
epoch, revokes every active session, consumes the challenge, and queues a change notice
in the same transaction. Registration and reset-request responses are generic for known
and unknown addresses. The browser receives only a host-only HTTP-only Secure,
SameSite=Lax cookie; unsafe requests additionally require trusted Origin and a
session-bound CSRF value. Redis may rate-limit and dispatch work but is never the source
of identity or revocation truth.

## Consequences

Sign-out and all-device reset revocation are immediate and auditable, while session
activity remains bounded by the 24-hour idle and seven-day absolute limits. SMTP outages
leave a durable encrypted outbox item for bounded, idempotent worker retry. Expired or
superseded links fail safely and never reveal whether an account exists. Local browser
verification must use the supported localhost Secure-cookie flow; non-local deployments
require HTTPS. This records architecture decisions A2–A7 and requirements R1–R8 and
N1–N3.
