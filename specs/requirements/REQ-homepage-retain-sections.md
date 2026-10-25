# Requirements: Keep Existing Homepage Sections Below Today’s Launches

> **Date:** 2026-10-25
> **Type:** feature
> **Source:** verbal brief and user-provided previous homepage screenshot; `specs/requirements/REQ-guest-launch-discovery.md`; `specs/requirements/REQ-redesign-frontend-neobrutalism.md`
> **Phase:** 1 of 5 (Requirement Engineering)

## Summary

Keep the homepage’s “Today’s launches” public release section as the first main content, while restoring the sections that appeared on the previous homepage beneath it. Visitors should be able to discover today’s products and still find the existing account actions, launch-process explanation, reassurance panel, and footer.

## Problem & Motivation

The current homepage emphasizes today’s public releases, but the previous homepage also explained how Launchpad works and gave visitors clear registration and sign-in actions. Replacing those sections made that context and guidance disappear. This change preserves the daily discovery experience while restoring the supporting homepage content for guests and signed-in visitors.

## Users & Consumers

- **Guests** — need to browse today’s launches and understand how to submit and publish a product.
- **Founders and members** — need the same public launch list and the existing account/workspace entry points.
- **Stakeholders and QA reviewers** — need to confirm the homepage contains both daily discovery and the previous supporting sections.

## Functional Requirements

Each requirement is specific, testable, and assigned an ID for traceability.

| ID | Requirement | Acceptance Criterion |
|----|-------------|----------------------|
| R1 | Put the “PUBLIC RELEASES / Today’s launches” section before the previous homepage content on `/`. | On the homepage, the public releases section is the first main content section. The previous hero, launch-process section, reassurance panel, and footer appear after it, in that order. |
| R2 | Retain the previous homepage hero and its account actions below today’s launches. | The hero copy, “Create your account” and “Sign in” actions, and its launch-date supporting text remain visible below the public releases section and their actions continue to work. |
| R3 | Retain the four-step launch-process section below the hero. | The homepage continues to show Prepare, Get reviewed, Choose a date, and Publish, with their existing explanatory content, after the hero. |
| R4 | Retain the “Know where your launch stands” reassurance panel and the footer after the launch-process section. | Both sections remain present below the launch-process cards in their previous order and retain their existing content and behavior. |
| R5 | Keep the supporting homepage sections available independently of the daily launch-list result. | While launches are loading, when there are no launches, and when the launch request fails, the corresponding loading, empty, or retryable error state appears in the releases section and all retained homepage sections remain rendered below it. |
| R6 | Preserve the approved Launchpad visual direction and responsive behavior while restoring the homepage hierarchy. | At 320-pixel mobile width and common desktop widths, the list and retained sections remain readable and ordered without page-level horizontal scrolling; headings, links, and buttons remain keyboard accessible with visible focus. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criterion |
|----|-------------|----------------------|
| N1 | The homepage must remain understandable to keyboard and assistive-technology users after the section order changes. | Keyboard navigation follows the visual order from launches through the retained sections, and each section has a meaningful heading or landmark. |

## Behaviors & Domain Rules

### Homepage hierarchy

- Today’s public launches remain the first main content and the primary guest discovery task.
- The previous homepage sections follow the launches section in their established order: marketing hero and account actions; four-step launch process; “Know where your launch stands” reassurance panel; footer.
- The retained sections keep their existing copy, action destinations, and meaning. The request is to preserve and reposition them, not rewrite the onboarding or launch workflow.
- The launch list’s loading, empty, and failed states belong within the releases section; none removes or replaces the retained sections.
- The same homepage content is available to guests and signed-in users, subject to the existing behavior of account actions.

**Why these rules matter:**
- Daily discovery stays prominent while the homepage continues to explain what Launchpad offers and what founders can do next.
- Rendering the supporting sections regardless of launch-list state prevents a quiet launch day or service outage from turning the homepage into an incomplete page.
- Keeping existing copy and destinations avoids changing the already established onboarding and publication workflow as part of a layout adjustment.

**Common mistakes:**
- Removing the previous hero or treating its account buttons as redundant after adding the launches list.
- Rendering the retained sections only after a successful launch-list response.
- Moving or omitting the launch-process cards, reassurance panel, or footer instead of preserving their order below the launches section.
- Changing archive, product-detail, or founder-calendar pages as part of this homepage-only change.

## Edge Cases & Failure Modes

| Scenario | Decision | Rationale |
|----------|----------|-----------|
| There are no launches today. | Show the existing empty state in the releases section, followed by all previous homepage sections in order. | An empty day should not remove the homepage explanation or account actions. |
| The launch-list request fails. | Show its retryable error in the releases section and keep the previous homepage sections visible below it. | Visitors need both a clear error and the rest of the page while the public feed is unavailable. |
| The launch list is still loading. | Keep the supporting sections rendered below the loading state. | The page remains useful without waiting for the list request. |
| A visitor opens the homepage at a narrow mobile width. | Stack the sections in the same specified order and allow content to wrap without page-level horizontal scrolling. | Restored content must remain usable on small screens. |
| A signed-in member opens the guest homepage. | Show the same public launches and retained informational sections; preserve the existing signed-in navigation/account behavior. | Authentication should not hide public discovery or its supporting content. |

## Decisions Log

| # | Decision | Alternatives Considered | Chosen Because |
|---|----------|-------------------------|----------------|
| 1 | Keep “Today’s launches” first, then restore all existing homepage sections below it in their previous order. | Put the marketing hero first; keep only some sections; remove supporting content. | The visitor’s primary task remains launch discovery, while the screenshot’s existing workflow explanation and account actions remain available. |
| 2 | Preserve the existing section copy and behavior while changing the hierarchy. | Rewrite the hero and onboarding steps as part of the redesign. | The request is to retain existing content and improve its placement, not change the product message or workflow. |
| 3 | Keep existing sections visible in loading, empty, and error states for today’s launches. | Hide the rest of the page until the list succeeds. | Homepage context and account actions should not depend on launch-feed availability. |
| 4 | Limit this change to the guest homepage. | Change archive pages, public product details, or founder launch scheduling at the same time. | Those routes have distinct purposes and are not part of the requested homepage layout correction. |

## Scope Boundaries

### In Scope

- Place today’s public releases first on the guest homepage.
- Restore and retain the hero/account actions, four-step process, reassurance panel, and footer beneath the daily releases section.
- Preserve the existing order, content, and behavior of those supporting sections.
- Keep all supporting sections rendered while the daily list is loading, empty, or failed.
- Preserve responsive and accessible navigation through the revised page order.

### Out of Scope

- Changes to launch listing data, card fields, sorting, pagination, voting, or ranking (reason: this change concerns homepage composition only).
- Changes to dated archives, product detail pages, or founder launch scheduling (reason: the user requested the guest homepage layout).
- Rewriting marketing copy, changing account workflows, or redesigning the visual system (reason: existing content and approved visual direction are to be retained).

## Open Questions

None. The requested order, retained sections, content preservation, and behavior during loading, empty, and failed list states are defined by the user’s instruction and previous homepage screenshot.

---
_This requirements document is the input for the **plan-architecture** skill._
_Next step: `/plan-architecture from: specs/requirements/REQ-homepage-retain-sections.md`_
