# Launchpad Build Status and Roadmap

This page summarizes current implementation status and the recommended product sequence. See the [stakeholder feature-completion report](reports/feature-completion-status-2026-10-06.pdf) or its [editable source](reports/feature-completion-status-2026-10-06.md) for the feature-by-feature summary. The client brief, engineering guide, and feature specifications remain the detailed sources of truth.

## Built

- **Local foundation:** A local modular-monolith development environment is established, with separate API, web, worker, and scheduler processes and supporting database, cache, storage, and mail-catcher services.
- **Identity and profiles:** Email/password accounts, verification and recovery flows, sessions, role-based access, and private-by-default member profiles with explicit publication are implemented. The [identity task list](../specs/tasks/TASKS-add-member-identity-profiles.md) marks its tasks done.
- **Founder product workflow:** Founders can create and autosave private drafts, manage private media and topic selections, submit complete products after email verification, edit or withdraw pending submissions, and view their own work. Staff can access an oldest-first pending queue with current submission details and duplicate/suspension indicators. The [product submission task list](../specs/tasks/TASKS-add-product-draft-submission.md) marks T1–T20 done.
- **Reviewer decisions and founder notifications:** Reviewers can approve, reject, or request changes; founders can read private outcomes, correct and resubmit products, and receive persistent in-site and email notices with live unread updates. Review tasks T1–T15 are marked done; T16, the final decision record and operating procedure, remains open.
- **Launch scheduling and publication:** Approved founders can reserve UTC launch dates within the scheduling window. Daily publication changes eligible products to launched at 00:00 UTC, records the publication transition, and reports recoverable failures through the agreed notification channels. See the launch scheduling and publication architecture/task artifacts for implementation and verification detail.
- **Guest launch discovery:** The public homepage lists today's launched products, and dated archives support direct date selection and adjacent-day navigation. Discovery cards link to existing public product details, keep unpublished products private, and distinguish empty dates from loading failures.
- **Catalog search and topic browsing:** Visitors can search all launched products by name, pitch, or public description and filter with up to 20 launched-product topics. The Discover page keeps filters in the URL and supports paged results.
- **Frontend visual refresh:** The available frontend uses the approved Launchpad Brutalism and Neobrutalism direction, including public and workspace views, with lightweight pathname navigation.

## Verification status

- The identity QA record reports a passing automated quality gate, while several manual scenarios remain partial because the plan did not provide sufficiently concrete execution steps. See the [identity QA results](../specs/qa/QA-RESULTS-add-member-identity-profiles.md).
- The latest product-submission QA run stopped before tests began: Docker could not create its isolated network because the predefined address pools were exhausted. This is a blocked verification run, not evidence that the feature itself failed. See the [product-submission QA results](../specs/qa/QA-RESULTS-add-product-draft-submission.md).
- The review screen's targeted suite (9 tests), TypeScript check, web production build, and local API readiness check passed. The review flow still needs broader QA, screen-reader inspection, and bell viewport captures for zero and multiple unread items. See the [review remediation evidence](../specs/qa/QA-RESULTS-product-review-workflow-review-remediation.md).
- Guest launch discovery passed the implementation review with follow-up findings recorded in the [guest discovery code review](../specs/reviews/CODE-REVIEW-PIPELINE-guest-launch-discovery.md). Keyboard focus, screen-reader date-result announcements, and responsive browser checks remain part of follow-up verification.

## Recommended next work

1. **Close review workflow operations and verification:** Record the approved decisions and finish broader, manual, accessibility, and release checks.
2. **Add community features:** Implement voting, comments and replies, follows and feeds, reports, moderation, and live updates.
3. **Complete supporting platform capabilities:** Add founder analytics and asynchronous exports.
4. **Prepare for release:** Complete security and load testing, operational monitoring and runbooks, backup/restore verification, and staging acceptance.

This sequence follows the [engineering guide's delivery plan](source/engineering-guide.md). The [client brief](source/launchpad-client-brief.md) also calls for Google sign-in; it is not included in the completed identity slice and should be planned as a separate feature.
