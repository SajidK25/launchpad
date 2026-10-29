# Tasks: Staging Seeded Homepage

## T1: Match the local homepage and select the latest demo day

> **Verification:** test-after + UI
> **Satisfies:** R1-R6

- Reorder the existing homepage and update heading/browser regressions.
- Add accurate latest-day wording without changing explicit archive behavior.
- Add the product-owned latest-public-date read and opt-in ranking selection.
- Persist the default-off setting through Compose and the validated deployment controller.
- Cover default-off, populated-today, empty-today, no-launch, explicit-date, policy-validation,
  rollback, component wording, heading hierarchy, responsive layout, and staging smoke checks.

Do not reseed, rewrite launch dates, alter GraphQL types, duplicate archive markup, or change voting
eligibility.
