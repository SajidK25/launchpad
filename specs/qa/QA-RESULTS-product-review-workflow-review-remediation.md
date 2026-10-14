# Review Remediation UI Evidence

Date: 2026-10-06

## T13: Product review screens

Inspected the staff decision form and founder correction page at 390px and 1280px using the existing mocked-browser captures. The staff form stacks review metadata, content, and decision controls at 390px; the feedback field and decision action remain visible in the page flow. At 1280px, the same detail content is presented in the wider workspace. The founder correction page was captured at both widths and shows the change request feedback with the editable product form. No clipped controls or horizontal overflow are visible in the captures.

Artifacts:

- `specs/qa/artifacts/product-review-workflow/t13-staff-390.png`
- `specs/qa/artifacts/product-review-workflow/t13-staff-1280.png`
- `specs/qa/artifacts/product-review-workflow/t13-founder-390.png`
- `specs/qa/artifacts/product-review-workflow/t13-founder-1280.png`

## T15: Notification bell

Inspected the open bell with one unread notice at 390px and 1280px. The panel stays within the viewport and the notice remains legible. The 1280px capture also shows the keyboard focus indicator on the bell trigger.

Artifacts:

- `specs/qa/artifacts/product-review-workflow/t15-bell-open-390.png`
- `specs/qa/artifacts/product-review-workflow/t15-bell-open-1280.png`

The zero and many unread states are covered by component-level assertions, but viewport captures for those two states were not available during this remediation. Screen-reader behavior was not manually exercised. The implementation includes a polite live status and route-focus handling; the automated assertions are in `apps/web/src/notifications/NotificationBell.test.tsx` and `apps/web/src/App.test.tsx`.

## Other verification limits

Update — 2026-10-06: The targeted `ProductScreens.staff.test.tsx` suite passed (9 tests), web TypeScript checking passed, the Docker web production build passed, and `/api/v1/health/ready` returned ready after restarting the development web service.

The Python test suites and the complete web test suite were not run. Ruff and web lint were not run; Ruff and workspace lint dependencies are unavailable in the host environment. Manual screen-reader inspection and bell viewport captures for zero and multiple unread items remain outstanding.
