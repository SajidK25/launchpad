# ADR 0006: Private-by-default profiles and gated member media

## Status

Accepted.

## Context

Members need to edit a profile before they are ready to publish it. A missing required
field must not leave stale public data visible, and uploaded photos must remain private
even when a profile is unpublished. Privacy transitions also need an auditable member
notice without coupling the request to SMTP availability.

## Decision

Each account owns one PostgreSQL profile whose default visibility is private. The owner
may edit display name, bio, links, and a cleaned photo while signed in. Publication is
allowed only when the profile is complete (display name, non-empty bio, at least one
valid link, and photo) and the email is verified. Removing a required field from a
published profile automatically makes it private and inserts one privacy-notice outbox
event in the same transaction; the member may explicitly unpublish at any time.

Photos use private, scoped staging uploads followed by server-side content validation,
metadata stripping, and re-encoding. The API returns a cleaned image only after checking
current visibility and caller policy, with `no-store`; direct bucket access, staging
URLs, private object keys, GraphQL private profiles, and unknown/private public IDs are
never exposed. Public profile reads therefore consult PostgreSQL visibility rather than
browser, Redis, or cached success state. Email payloads are authenticated-encrypted and
the worker owns SMTP delivery and retry.

## Consequences

Incomplete drafts are safe to save and remain private. Public visibility can be withdrawn
immediately without waiting for cache expiry or object deletion, and privacy notices are
durable across mail outages. The owner receives a stable private view while outsiders get
the same absence response for private and unknown profiles. This records architecture
decisions A7–A10 and requirements R9–R12 and N1–N4.
