# ADR 0002: Readiness is a bounded, minimal health contract

## Status

Accepted.

## Context

The local browser needs one safe answer about whether the API can use required dependencies. Detailed probe failures can disclose internals, and unbounded checks leave users with stale successful state.

## Decision

The API exposes a minimal readiness response. It probes PostgreSQL, Redis, and private storage concurrently with a three-second deadline. The web client uses the generated REST contract and displays **Connected** only after a valid ready response; failed or timed-out refreshes display **Unavailable**.

## Consequences

Readiness avoids credentials, stack traces, and dependency internals in public responses and logs. GraphQL and WebSocket health surfaces are deferred until a feature consumes them. This implements architecture decisions A5, A6, and A7 and requirements R4, R5, N1, and N2.
