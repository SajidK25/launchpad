# Requirements: Staging Seeded Homepage

> **Date:** 2026-10-29
> **Type:** fix
> **Source:** User-provided staging screenshot and running local homepage

## Summary

Make the public root page match the running local homepage: marketing hero first, launch discovery
second, then the existing workflow, reassurance, and shared footer. Keep dated archives focused on
their selected date. On the explicitly customer-free demo/staging target, an empty UTC day may show
the newest populated launch date without changing launch history.

## Requirements

- **R1:** `/` renders the existing hero first as H1 and launch discovery second as H2; all existing
  session-aware actions, supporting sections, outage states, accessibility, and responsive behavior
  remain available.
- **R2:** `/launches/archive/YYYY-MM-DD` remains an exact-date, archive-only surface.
- **R3:** The demo fallback is disabled by default and enabled only by validated host policy.
- **R4:** With the fallback enabled, an omitted-date ranking read selects the newest public launch
  date on or before UTC today; explicit dates never fall back and no available launch remains empty.
- **R5:** The homepage says **Latest launches** and displays the actual UTC date when fallback occurs;
  it must not call a past date “today,” and voting remains closed for that date.
- **R6:** Existing seed records, dates, counts, audit history, and credentials are not mutated.

## Acceptance

On `launchpad.t99ltd.com`, `/` uses the local hero-first composition and shows the October 27 demo
products as the latest populated day while `/launches/archive/2026-10-27` remains archive-only.
Production-compatible defaults retain strict UTC-today behavior.
