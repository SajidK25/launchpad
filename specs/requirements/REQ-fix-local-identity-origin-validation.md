# Requirements: Fix Local Identity Origin Validation

> **Date:** 2026-09-25
> **Type:** bugfix
> **Source:** verbal bug report (`/api/v1/auth/register` returned generic `request rejected` during local browser testing)
> **Phase:** 1 of 5 (Requirement Engineering)

## Summary

Local browser users cannot currently complete identity actions when they open the application at `http://localhost:8080`, because the request is rejected by origin validation. Correct the local/test configuration so the complete existing identity flow works from the two approved local origins, while production remains restricted to its explicitly configured trusted origins.

## Problem & Motivation

The registration page is unusable during ordinary local testing: a valid request from the host browser receives the generic rejection response before registration begins. The same origin boundary is shared by sign-in, password recovery, and private-profile edits, so fixing only registration would leave the local identity flow inconsistent. This bug blocks development and manual verification; broadening origin trust in production would create an avoidable security risk.

## Users & Consumers

- Local developers and QA users — complete registration, sign-in, recovery, and private-profile edits from a host browser.
- Production members — continue using the existing production trusted-origin policy without local-origin exceptions.
- Automated or internal clients — continue using an explicitly supported non-browser path rather than bypassing browser-origin checks.

## Functional Requirements

Each requirement is specific, testable, and assigned an ID for traceability.

| ID  | Requirement | Acceptance Criterion |
|-----|-------------|----------------------|
| R1 | In explicitly local/test environments, accept browser identity actions from exactly `http://localhost:8080`. | Registration, sign-in, password recovery, and private-profile edits complete successfully from that origin when their existing business validations pass. |
| R2 | In explicitly local/test environments, accept browser identity actions from exactly `http://127.0.0.1:8080`. | The same four actions complete successfully from that origin when their existing business validations pass. |
| R3 | Keep origin matching exact for browser-facing identity actions. | Requests using another host, scheme, port, or otherwise untrusted origin are rejected with the existing generic rejection response and cause no state change. |
| R4 | Reject browser-facing identity actions when the `Origin` header is missing. | A request without an `Origin` header receives the same generic rejection and creates no account, session, recovery action, or profile change. |
| R5 | Gate local-origin trust by explicit environment configuration. | Production rejects both local origins unless they are deliberately present in the production trusted-origin configuration; local mode with missing local-origin configuration fails closed with the same generic rejection. |

## Non-Functional Requirements

| ID  | Requirement | Acceptance Criterion |
|-----|-------------|----------------------|
| N1 | Do not disclose origin configuration or distinguish rejected-origin causes in browser responses. | All missing, untrusted, and misconfigured-origin cases return the same generic rejection detail and no sensitive configuration appears in response bodies or logs exposed to the client. |
| N2 | Preserve existing identity security and state-atomicity guarantees. | Rejected requests do not partially persist users, sessions, recovery state, or profile changes; production trusted-origin behavior remains unchanged. |

## Behaviors & Domain Rules

### Approved local origins

The only local browser origins approved by this change are the exact HTTP origins `http://localhost:8080` and `http://127.0.0.1:8080`. Scheme, hostname, and port all participate in the match; alternate ports and schemes are not equivalent.

### Environment boundary

Local origins are available only when the application is explicitly running in a local/test environment. A request's use of a `localhost` hostname must never activate local trust by itself. Production continues to rely on its configured trusted-origin list.

### Rejection and state safety

Missing or untrusted origins, and local environments where the approved origins are not configured, fail closed with the existing generic rejection response. Rejection occurs before any user-visible identity state is changed.

### Non-browser clients

Automated or internal clients are not granted an implicit browser-origin bypass by this fix. They must use an explicitly supported non-browser path.

**Why these rules matter:**
- Exact matching prevents origin confusion and accidental trust of arbitrary local ports or schemes.
- Explicit environment gating prevents a production deployment from trusting development origins accidentally.
- Generic failures avoid leaking which origin configuration is present.
- No partial state changes preserve account, session, recovery, and profile integrity when a request is rejected.

**Common mistakes:**
- Allowing every `localhost` origin or every port instead of the two exact origins.
- Trusting a local origin merely because the request hostname is `localhost`.
- Fixing registration but leaving sign-in, recovery, or profile mutations blocked.
- Returning a special error that reveals the configured trusted origins.
- Performing any persistence before origin validation completes.

## Edge Cases & Failure Modes

| Scenario | Decision | Rationale |
|----------|----------|-----------|
| Request originates at `http://localhost:8080` in local/test mode | Allow if existing identity validation passes | This is the primary blocked local workflow. |
| Request originates at `http://127.0.0.1:8080` in local/test mode | Allow if existing identity validation passes | This is an explicitly approved equivalent local host. |
| Request uses `localhost:3000`, `127.0.0.1:5173`, HTTPS, another host, or another port | Reject generically; make no state change | Exact scheme/host/port matching avoids accidental origin expansion. |
| Request has no `Origin` header | Reject generically; make no state change | Browser-facing identity actions require a trusted origin. |
| Local/test mode lacks the approved local-origin configuration | Reject generically; make no state change | Misconfiguration must fail closed and must not expose configuration. |
| Production receives either local origin | Reject unless deliberately configured as a trusted production origin | Environment gating prevents development trust from leaking into production. |
| Automated/internal client sends no browser origin | Keep using the explicitly supported non-browser path | This bugfix must not create an undocumented origin bypass. |
| Origin is rejected after a request begins | Persist no user, session, recovery, or profile changes | Origin rejection must be atomic from the user's perspective. |

## Decisions Log

| # | Decision | Alternatives Considered | Chosen Because |
|---|----------|-------------------------|-----------------|
| 1 | Support both exact local origins on the complete identity flow | Registration only; internal Docker hostname only | Developers and QA use host browsers, and the shared origin guard affects all identity actions. |
| 2 | Gate local origins by explicit environment | Trust any request containing `localhost`; allow local origins everywhere | Prevents accidental production exposure. |
| 3 | Require exact scheme, host, and port | Normalize all loopback hosts; allow any local port | Keeps the trust boundary narrow and predictable. |
| 4 | Reject missing/untrusted origins with one generic response | Accept missing origin; return diagnostic origin errors | Preserves browser request integrity without leaking configuration. |
| 5 | Keep internal/non-browser clients on an explicit path | Add an implicit origin bypass | Avoids weakening browser-facing protections. |

## Scope Boundaries

### In Scope
- Correct local/test origin configuration and validation for registration, sign-in, password recovery, and private-profile edits.
- Exact support for `http://localhost:8080` and `http://127.0.0.1:8080`.
- Fail-closed behavior for missing, untrusted, and misconfigured origins.
- Verification that rejected requests do not change identity state.

### Out of Scope
- New registration, authentication, recovery, or profile features (reason: this is an origin-validation bugfix).
- Changes to production trusted origins unless an operator explicitly configures them (reason: preserve deployment policy).
- Definition or implementation of a new automated/internal-client authentication path (reason: separate design and security review).
- Support for arbitrary localhost ports, alternate schemes, or additional hosts (reason: not part of the approved local boundary).

## Open Questions

- None for this sprint-sized bugfix.

---
_This requirements document is the input for the **plan-architecture** skill._
_Next step: `/plan-architecture from: specs/requirements/REQ-fix-local-identity-origin-validation.md`_
