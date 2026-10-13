# Requirements: Product Review Decisions and Founder Outcomes

> **Date:** 2026-10-03
> **Type:** feature
> **Source:** `docs/roadmap.md`, `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `AGENTS.md`; product decisions confirmed in the requirements interview
> **Phase:** 1 of 5 (Requirement Engineering)

## Summary

Reviewers need to make a clear decision on each pending product submission: approve it, reject it, or request changes. Founders need to understand the outcome and any required corrections, while approved and rejected products remain private until the later launch workflow makes an approved product eligible for publication.

## Problem & Motivation

The current founder workflow ends when a complete submission reaches the staff queue. Reviewers cannot yet resolve submissions, and founders do not receive an outcome. This leaves the product approval lifecycle incomplete and prevents approved products from moving to the later scheduling workflow. Reviewers need a consistent, accountable way to decide; founders need a clear outcome and a usable path to correct fixable issues. An unlaunched product remains commercially sensitive, so no review action may make it public.

## Users & Consumers

- **Reviewers and admins** — inspect pending submissions and record an authorized, accountable outcome.
- **Founders** — see the latest outcome and reviewer feedback, make requested corrections, and resubmit when permitted.
- **Notification recipients and delivery services** — deliver review outcomes in-site and by email, following available preferences and retrying delivery failures.
- **Visitors and other members** — must not see a product or its media before the later launch workflow publishes it.

## Functional Requirements

Each requirement is specific, testable, and assigned an ID for traceability.

| ID | Requirement | Acceptance Criterion |
|---|---|---|
| R1 | An authorized active reviewer or admin may resolve a pending submission as approved, rejected, or changes requested. Each submission period receives at most one effective decision. | A reviewer can complete each supported action for a current pending submission; a member, visitor, or suspended/ineligible staff account cannot; repeated requests do not create duplicate outcomes. |
| R2 | Approval records the outcome and moves the product to an approved state that waits for the later scheduling workflow. Approval does not publish the product or its media. Approved content is locked against founder edits; staff may return it for changes when a correction is needed. | After approval, the founder sees the approved status, cannot edit the approved content, and no visitor or other member can read the product or media. When staff return it for changes, it becomes editable only through the changes-requested path. |
| R3 | A reviewer requesting changes must provide a nonblank explanation of at most 2,000 characters visible to the founder. The product returns to a private editable state, and its founder may correct it and submit it again as a new queue arrival. | A request without an explanation or with an explanation over 2,000 characters is refused; with a valid explanation, the founder sees it and can edit the private product. A valid resubmission appears after submissions already waiting and cannot be decided using an earlier review view. |
| R4 | A reviewer rejecting a submission must provide a nonblank explanation of at most 2,000 characters visible to the founder. Rejection permanently closes that review, leaves the product private, and does not permit that product to be resubmitted. | A rejection without an explanation or with an explanation over 2,000 characters is refused; with a valid explanation, the founder can see the final rejected status and reason, cannot submit that product again, and no public read surface exposes it. |
| R5 | A review decision applies only to the latest saved submission version. If a founder change or withdrawal makes the review stale, or another valid action resolves the submission first, the stale action has no effect and the reviewer is prompted to refresh. | Starting from the same submission version, a concurrent founder update/withdrawal or second reviewer decision yields one coherent result; stale decisions create no outcome, notification, or audit record claiming success. |
| R6 | Founders are told each approval, rejection, or request for changes through an in-site notification and email, subject to notification preferences where those preferences are available. The outcome and relevant founder-visible explanation remain available in the founder's product view. | Each successful decision produces an in-site outcome and an email when allowed by available preferences; the founder can later reopen the product and see its current status and applicable explanation. |
| R7 | Every successful staff review action is durably recorded with the acting staff member, action, and time. Founder-visible feedback is retained with the corresponding decision. | After each successful decision or return-for-changes action, the staff action record identifies who acted, what they did, and when; changes to later state do not erase the prior record. |
| R8 | Founders may only act on products they own and only through the transitions allowed by the latest outcome. A changes-requested product can be edited and resubmitted only when it satisfies the existing submission rules; approved or rejected products cannot be edited by the founder. Once staff has made a review decision, the founder cannot permanently delete that product through the draft flow, even after a later withdrawal. | Attempts to edit, withdraw, or resubmit an approved or rejected product are denied without changing its content or outcome; requested changes permit private editing, and resubmission requires the existing verification, completeness, and suspension rules. Deletion of any product with a staff review decision is refused while the staff action record remains intact. |
| R9 | Review outcomes create a persistent in-site notification visible in the founder's notification bell. While the founder is connected, a new outcome updates the bell and unread count without a page refresh. Opening an individual notification marks it read; opening the bell alone does not. | After a decision, the founder can see its notification and unread count in the bell; an already-connected founder sees the count/list update without refresh. Opening the notification marks only that item read and decreases the count; opening or closing the bell does not mark items read. A notification remains available after disconnecting and returning. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criterion |
|---|---|---|
| N1 | A committed review outcome must not be lost if email delivery is unavailable, and delivery retries must not produce duplicate founder notices. | With email delivery unavailable during a decision, the outcome remains recorded and visible in-site; after delivery recovers, the email is delivered once despite retrying. |
| N2 | Review actions and outcome messages must be understandable and usable on mobile, by keyboard, and with assistive technology. | At approximately 390px and 1280px, reviewers can complete a decision without horizontal overflow; all decision controls and required explanation fields work by keyboard, and the founder receives perceivable status and error messages. |
| N3 | Unlaunched product details and media remain private across all read surfaces and direct media access. | After approval, rejection, or a change request, a visitor and another member cannot retrieve unpublished product content, outcome-only details, or media through product pages, APIs, search, or direct media access. |
| N4 | Live notification events are private to the intended authenticated account, and notification history remains authoritative when a live connection is unavailable. | A connected different account receives no notification event or count change; after a missed/disconnected event, reconnecting and loading notifications returns the correct persisted items and unread count. |

## Behaviors & Domain Rules

### Reviewer decisions

The pending queue presents submissions for review. An active authorized reviewer or admin may approve, reject, or request changes. A request for changes and a rejection require an explanation the founder can read. Approval does not require a corrective explanation.

Approval means the current submitted content passed review and is waiting for the later scheduling workflow. It does not make the product public. Founder edits are locked after approval so approved content cannot change without review. If a correction is needed before launch, staff return the product through the changes-requested path and explain why.

### Founder correction path

When changes are requested, the product remains private and returns to an editable state. The founder can make incomplete edits privately, but may resubmit only after meeting the existing submission requirements and account eligibility rules. Resubmission creates a new queue arrival behind submissions already waiting. Rejection is final for that product submission: the product remains private and cannot be resubmitted.

### Freshness, audit, and notifications

Reviewers decide on the latest saved version. If the founder changes or withdraws the submission after a reviewer opens it, or another reviewer resolves it first, the stale decision is refused. The first valid action to complete takes effect. Every successful staff action is retained with the actor and time.

Founders receive successful outcomes both in-site and by email, subject to available notification preferences. Email outages do not erase the review outcome or the in-site notice; email delivery retries safely. Notifications must not reveal another founder's product or disclose unpublished work to unintended recipients.

**Why these rules matter:**

- Separate change requests from rejection so fixable issues have a correction path while rejection has a clear final meaning.
- Lock approved content so the product staff reviewed is the product later sent to scheduling.
- Keep every outcome private until launch to preserve the client's core confidentiality promise.
- Freshness checks prevent a reviewer from deciding on content that has since changed or been withdrawn.
- Durable staff records and reliable outcome notices support accountability and prevent founders from being left without an answer.

**Common mistakes:**

- Treating approval as publication or allowing the founder to change approved content without another review.
- Treating rejection as an ordinary request for changes or allowing a rejected product to re-enter the queue.
- Applying a decision to an old version after the founder updated or withdrew the submission.
- Recording the decision but losing its email notification when the mail service is down.
- Showing reviewer-only or founder-only information to visitors, other members, or another founder.

## Edge Cases & Failure Modes

| Scenario | Decision | Rationale |
|---|---|---|
| A reviewer requests changes or rejects without entering an explanation. | Refuse the action and leave the submission pending and unchanged. | The founder needs actionable context for a correction or a final outcome. |
| A founder changes or withdraws the submission after the reviewer opened it. | Refuse the stale decision and require the reviewer to reload the current submission. | Staff must decide on the content that is currently pending. |
| Two reviewers decide at nearly the same time. | Only the first valid action takes effect; the other sees that the submission has changed and must refresh. | The product must have one authoritative outcome. |
| A founder receives a request for changes and resubmits while other products are waiting. | Re-enter the queue at the back with a new review arrival. | The new content needs review, and existing submissions retain their place. |
| A founder receives a rejection and tries to edit or resubmit the same product. | Keep rejection final; refuse the founder action and preserve the private rejected record. | Rejection denotes an ineligible or unacceptable submission, rather than a fixable issue. |
| A founder tries to delete a product after a staff decision, including after resubmission and later withdrawal. | Refuse permanent deletion in this workflow and preserve the private product and staff action history. | A status change must not erase the required audit trail; reviewed-product retention and deletion need a separate policy. |
| An approved product needs correction before scheduling or launch. | Staff return it for changes with a founder-visible explanation; the founder cannot change it directly. | Corrections must pass review before the product proceeds. |
| Email delivery fails after a reviewer decision. | Preserve the outcome and in-site notice, retry email delivery, and avoid duplicate notices. | A provider outage must not lose a decision notification or create confusing repeats. |
| A reviewer approves a product and a visitor tries its old URL or media address. | Deny access until the later launch workflow makes it public. | Approval is not publication. |
| A founder opens the notification bell without opening a specific outcome. | Keep all items' read states and the unread count unchanged. | Merely viewing the list does not mean the founder read an outcome. |
| A founder disconnects while an outcome arrives. | Keep the notice in the in-site list and show the correct unread count when the founder returns. | Live delivery may be missed, but the durable outcome must remain available. |

## Decisions Log

| # | Decision | Alternatives Considered | Chosen Because |
|---|---|---|---|
| 1 | Support approve, reject, and request-changes decisions for current pending submissions. | Keep the queue read-only; provide fewer outcome types. | The client brief calls for staff review and all three outcomes. |
| 2 | Approval keeps the product private and locks founder edits until the later scheduling workflow; staff can return it for changes if needed. | Publish on approval; allow direct founder edits after approval. | Launch scheduling and publication are later workflows, and edits after approval must not bypass review. |
| 3 | A change request returns the product to a private editable state; after correction and resubmission it joins the queue at the back. | Keep it pending during edits; preserve its old queue position. | The correction path is clear and the queue remains fair to submissions already waiting. |
| 4 | Rejection permanently closes review for that product and does not allow resubmission. | Return rejected work to draft; allow resubmission after an unspecified delay or appeal. | Rejection should be distinct from a fixable request for changes and remain a meaningful final outcome. |
| 5 | Change requests and rejections require a founder-visible explanation. | Make explanations optional or staff-only. | Founders need to understand what to fix or why review ended. |
| 6 | Send each outcome in-site and by email, honoring preferences where available. | Use only email, only in-site notices, or ignore preferences. | This follows the client's outcome email requirement and in-site notification direction while respecting preference controls when present. |
| 7 | Use the existing latest-version/first-valid-action rule for competing founder and reviewer actions. | Allow a stale decision or let last-write-wins select the result. | Staff must decide on the content they saw, and one outcome must be authoritative. |
| 8 | Retain each successful staff decision with its actor and time. | Keep only current product status without a historical staff record. | The client brief requires an account of staff actions, and the engineering guide calls for an append-only staff audit log. |
| 9 | Limit founder-visible review explanations to 2,000 characters. | Leave explanations unbounded; impose a shorter cap. | The confirmed limit supports useful guidance while keeping notices readable. |
| 10 | Show review outcomes in a persistent bell with a live unread count; mark an item read only when its notification is opened. | Show status only on the product page; require a refresh; mark the whole list read on bell open. | Founders should notice decisions while present and retain an accurate unread count. |
| 11 | Keep products after a staff decision, including if the founder later withdraws a resubmission; reserve permanent deletion for products without review decisions. | Let a founder delete reviewed work while retaining a separate audit record. | A separate retention and deletion policy is needed before reviewed products can be removed without losing staff accountability. |

## Scope Boundaries

### In Scope

- Reviewer/admin approval, rejection, and request-changes outcomes for pending product submissions.
- Required founder-visible feedback for request-changes and rejection.
- Private edit and resubmission path after changes are requested, including a new queue position.
- Final rejected state and edit lock after approval, with a staff path to return approved work for correction.
- Permanent-deletion guard for every product with staff review history, including a later withdrawn draft.
- Founder-visible outcome status and in-site plus email notification, following available preferences and retrying delivery failures.
- A persistent notification bell, unread count, live outcome updates, and individual read marking for outcome notices.
- Audit records for successful staff review actions.
- Stale and concurrent decision behavior, authorization, privacy, and accessible reviewer/founder interactions needed to complete the workflow.

### Out of Scope

- Choosing launch dates, reserving daily launch capacity, scheduling, launch publication, or public product pages (reason: separate roadmap slice).
- Notification preference management (reason: the roadmap schedules notification preferences as supporting platform work; this slice honors preferences where that capability is available).
- Appeals or staff reopening of a permanently rejected product (reason: no appeal path is specified in the client brief; rejection is confirmed as final for this workflow).
- A reviewed-product deletion and retention policy (reason: staff action history must remain intact; a future privacy/retention decision will define removal).
- Public discovery, voting, comments, reports, search, ranking, and community features (reason: separate roadmap slices).
- Staff account provisioning, suspension, takedowns, and general audit administration (reason: these are separate staff operations; this slice records review actions only).

## Open Questions

- None for this slice. Scheduling, notification preference management, and any rejection appeal policy remain separate future product decisions.

---
_This requirements document is the input for the **plan-architecture** skill._
_Next step: `/plan-architecture from: specs/requirements/REQ-product-review-workflow.md`_
