# Architecture: Staging Seeded Homepage

> **Date:** 2026-10-29
> **Requirements:** `specs/requirements/REQ-staging-seeded-homepage.md`

## Design

- `HomePage` composes the existing hero before `LaunchDiscovery`, with H1/H2 semantics matching
  visual order. Archive composition is unchanged.
- `VoteReadService` applies an optional omitted-date fallback before choosing live, snapshot, or
  unranked reads. It asks the products service for the latest public launch date; products owns the
  indexed PostgreSQL query and exposes no private state.
- `LAUNCHPAD_DEMO_HOME_LATEST_LAUNCH_ENABLED` defaults to false. The API context passes it into the
  read service. No GraphQL shape changes: existing `todayDate` remains actual UTC today and
  `selectedDate` identifies the fallback date.
- The root-owned runtime-policy file is the only deployed override. The controller validates and
  persists the flag through verified rollout and schema-safe rollback alongside launch visibility.

## Safety

Explicit dates, product-specific reads, archive routes, launch records, and seed ownership are
unchanged. The fallback selects only `status = launched` rows before the exclusive end of UTC today.
Disable it before the target accepts customer data.
