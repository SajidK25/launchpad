# Requirements: Founder Product Drafts and Submission

> **Date:** 2026-09-29
> **Type:** feature
> **Source:** `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `AGENTS.md`; product decisions confirmed in the requirements interview
> **Phase:** 1 of 5 (Requirement Engineering)

## Summary

Founders need a private place to prepare a product listing over time and submit a complete version to staff for review. This slice provides automatic draft saving, bounded and validated product content, private image uploads and proposed topics, and a fair review queue entry without making any unlaunched product public.

## Problem & Motivation

The client brief calls for founders to save unfinished product listings, return later, and have every submission reviewed before it appears anywhere on the site. Without this workflow, founders cannot prepare a launch safely and staff cannot receive reviewable submissions. Founders benefit from reliable editing and clear save status; reviewers benefit from a complete, current, oldest-first queue that identifies possible duplicates and suspended accounts. The privacy boundary matters because product details and media may be commercially sensitive before launch.

## Users & Consumers

- **Founders** — signed-in members preparing their own products, editing or withdrawing pending submissions, and seeing whether their work is saved and ready for review.
- **Reviewers and admins** — staff viewing submitted products and their current content in an oldest-first queue, including possible-duplicate and suspended-founder flags.
- **Visitors and other members** — must not discover private drafts, submitted products, proposed topics, or unlaunched media.

## Functional Requirements

Each requirement is specific, testable, and assigned an ID for traceability.

| ID | Requirement | Acceptance Criterion |
|---|---|---|
| R1 | A signed-in member may create and return to private product drafts before verifying their email. Only the founder may view or edit an unfinished or withdrawn draft. | An unverified member can create, leave, and reopen their draft; another member and a visitor cannot view it, and staff do not see it in the review queue. |
| R2 | Draft changes save automatically, with visible saving, saved, and failed states. A failed save retains current edits on screen and retries after connectivity returns. | Editing a draft produces a saved state after persistence; a simulated connection failure shows “Not saved” without clearing the fields, and reconnection saves those edits. Reopening a draft shows its last successfully saved content. |
| R3 | Concurrent edits by the same founder cannot silently overwrite newer saved work. | When two tabs or devices edit the same draft, a stale save is stopped, the local edits remain available, and the founder is prompted to resolve the conflict. |
| R4 | A private draft may omit submission-required fields, but supplied values must respect the stated formats and limits. | A blank field can remain in a draft; an overlong name, pitch, description, or topic, an invalid website link, or an unsupported or oversized image is rejected with a field-specific error. |
| R5 | Submission requires a nonblank name of at most 80 characters, a nonblank one-line pitch of at most 160 characters, a nonblank description of at most 5,000 characters, and a valid HTTPS product website link. | Submission is blocked for missing, whitespace-only, over-limit, malformed, or non-HTTPS values, and succeeds when all text and website rules are met alongside the other required content. |
| R6 | Submission requires one validated logo and 1–10 validated screenshots. Accepted image formats are JPEG, PNG, and WebP, with a 5 MB maximum per image. | Submission cannot proceed with no logo, no screenshot, more than 10 screenshots, a failed or still-validating image, an unsupported format, or an image over 5 MB; an alert toast explains an upload blocker. |
| R7 | Founders may select or type 1–3 topics for submission. A new topic name is at most 40 characters; names are matched after trimming surrounding spaces and ignoring capitalization so existing topics are reused. | `AI Tools` and ` ai tools ` resolve to one topic; blank, overlong, or more than three topic choices block submission. |
| R8 | Newly proposed topics remain invisible to others until a product using them launches. | A visitor or other member cannot discover a proposed topic from a draft or pending submission; it becomes eligible for public visibility only when the associated product launches in a later workflow. |
| R9 | A verified, unsuspended founder may submit only the latest successfully saved, complete version of a draft. Submission waits for an in-progress save and stops visibly if that save fails. | Submitting during a save includes the final edit; a failed save produces no review entry. An unverified or suspended founder cannot submit. |
| R10 | Repeated submission attempts for the same product create at most one pending review entry. | Double-clicking Submit or retrying after a timeout leaves one pending submission with its current status and no duplicate queue entries. |
| R11 | A founder may edit a pending submission while keeping it complete and may explicitly withdraw it to a private draft. An incomplete edit is not saved to the pending submission. | A valid pending edit appears to staff as the latest version; removing a required field leaves the pending version intact, retains the founder’s local edit, and explains that withdrawal is needed for incomplete work. Withdrawal removes the product from the queue. |
| R12 | Review decisions must apply only to the latest saved submission version. When a founder changes or withdraws a submission after a reviewer opens it, the outdated decision cannot take effect. | An attempt to decide using an older view is rejected with a refresh prompt; if withdrawal and a decision race, only the first completed action takes effect and the other actor sees the changed status. |
| R13 | The staff queue is oldest-first by original submission time. Editing a pending submission does not change its place; withdrawing and submitting again creates a new place at the back. | Pending entries remain in original submission order after edits; a withdrawn and resubmitted product appears after entries submitted earlier. |
| R14 | Staff can view submitted products, including their current details and media, with a visible suspended-founder flag when relevant. A suspended founder cannot edit or submit existing work. | Staff can open a pending submission from a suspended founder and see the flag; that founder’s edit and submission attempts are blocked. |
| R15 | A submitted product sharing an HTTPS website link with another product is allowed into review and marked as a possible duplicate for staff. Private products belonging to other founders are not disclosed to the submitter. | A second submission with the same website enters the queue with a possible-duplicate flag; its founder sees no identifying details of the matching product. |
| R16 | A founder may have at most 10 private drafts and 3 pending submissions. Withdrawal always succeeds even if it temporarily raises the draft count above 10; further draft creation is blocked until the count falls below the limit. | The next draft or pending submission over its limit is blocked with an understandable message; withdrawing at the draft limit succeeds; deleting a draft frees a slot. |
| R17 | A founder may permanently delete a private draft after confirming the action, including its uploaded images. A failed deletion leaves the draft available with a retryable error. | A successful deletion makes the draft and images unavailable and cannot be undone; a simulated deletion failure reports failure and leaves the draft accessible for retry. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criterion |
|---|---|---|
| N1 | No unlaunched product content, media, or proposed topic may be exposed to visitors or other founders through any read surface or direct media access. | Privacy checks across product reads, search and topic discovery, image access, and error responses reveal none of this content before launch. |
| N2 | Staff and founder actions must respect ownership, verification, suspension, and current state even when requests are repeated or concurrent. | Attempts by a different member, an unverified submitter, or a suspended founder are denied; simultaneous edits, withdrawals, and submissions produce one coherent outcome. |
| N3 | Product, topic, image, and review-entry changes must never leave a partially submitted listing when a step fails. | A simulated failure during submission leaves the product in its previous state with no orphan review entry or newly visible content. |
| N4 | Automatic saving and upload attempts must be bounded so one account cannot overwhelm the service or staff queue. | Rapid repeated actions are limited without losing the last valid saved draft, and the per-founder draft and pending limits hold under simultaneous attempts. |
| N5 | Founder and staff experiences must work on a phone and be usable by keyboard and assistive technology. Save state, field errors, conflict prompts, and upload alert toasts must be perceivable. | Desktop and mobile acceptance checks can complete the draft-to-submission path by keyboard, and save/error/alert messages are announced or associated with their relevant controls. |

## Behaviors & Domain Rules

### Draft and submission lifecycle

A signed-in member becomes a founder by creating a product draft. The product begins private, may be incomplete, and remains available for later editing. A complete draft can enter the pending review queue only after the founder verifies their email. While pending, the founder can save complete edits without losing queue seniority or withdraw the product. Withdrawal returns it to a private draft; a later submission is a new queue arrival. Draft deletion is permanent after confirmation. Approval, rejection, requests for changes, scheduling, and launch are later workflows.

### Review freshness and fairness

Staff see the latest pending version. A reviewer cannot decide on a version that changed or was withdrawn after they opened it. Queue order follows the first successful submission for the current pending period; valid edits do not reset that time. This protects founders who fix minor mistakes while ensuring staff decide on content they actually saw.

### Content and privacy

Drafts may lack required content, but pending submissions must remain complete. A new topic typed by a founder is a private proposal until a product using it launches. Matching names are reused, including case and surrounding-space variants, without exposing another founder’s private association with that topic. All product media remains private before launch. Staff can see submitted content; they do not see unfinished or withdrawn drafts in their review queue.

**Why these rules matter:**

- Verified-email gating and pending limits reduce low-cost queue abuse without preventing early drafting.
- Explicit withdrawal prevents an accidental incomplete edit from costing a founder their queue position.
- Latest-version review prevents staff from approving or rejecting content they never saw.
- Private proposed topics and media preserve the brief’s no-leak promise for unlaunched products.
- Permitting same-website submissions with a staff flag allows legitimate distinct products to be judged by a person.

**Common mistakes:**

- Treating a saved draft as submitted, or making a pending product public before launch.
- Showing an unsaved draft as saved after an offline or failed request.
- Silently replacing a newer draft from another tab or accepting a review decision on stale content.
- Moving a pending edit to the back of the queue or automatically withdrawing it after a temporary incomplete edit.
- Publishing a newly typed topic as soon as it is submitted.
- Blocking withdrawal only because the founder is at the draft limit.

## Edge Cases & Failure Modes

| Scenario | Decision | Rationale |
|---|---|---|
| A founder supplies missing, blank, wrong-format, or over-limit content. | Save an incomplete private draft where possible; reject invalid supplied values and block submission until all required content is valid. | Founders can work incrementally without placing an unreviewable item in the queue. |
| An image upload fails, is still being checked, exceeds 5 MB, has the wrong format, or would be an eleventh screenshot. | Keep other saved draft work; block submission and show an alert toast or field error. | A review submission must contain validated media, and the founder needs a clear recovery path. |
| An automatic save fails because the service or connection is unavailable. | Retain current on-screen edits, mark them not saved, and retry when the connection returns. | Avoid false confidence and accidental loss of current work. |
| Two tabs or devices save competing edits. | Stop the stale overwrite and let the founder resolve which content to keep. | Do not silently discard newer work. |
| Submit is clicked while save is in progress or repeatedly after a timeout. | Wait for the latest save; create at most one review entry, or no entry if the save fails. | Prevent stale submissions and duplicate work for staff. |
| A reviewer decides while a founder saves an edit or withdraws. | Only the first completed valid action takes effect; stale reviewer decisions require a refresh. | The review outcome must match the current submission state. |
| A pending edit removes required content. | Reject that pending edit, retain the founder’s local content, and offer explicit withdrawal to continue as a draft. | Preserve queue position unless the founder chooses to give it up. |
| A founder withdraws with already 10 drafts. | Allow withdrawal; block creating additional drafts until the count is below 10. | A founder must never be forced to keep an unwanted submission under review. |
| Another product uses the same HTTPS website. | Accept the new submission with a staff-visible possible-duplicate flag; reveal no private match to the founder. | Staff can judge whether the products are truly distinct without leaking private work. |
| The founder is suspended after submitting. | Block founder editing and submission, keep the existing record staff-visible, and show the suspended flag. | Staff retain context while suspension has immediate effect. |
| Image storage fails during permanent draft deletion. | Report deletion failure and leave the draft accessible for retry. | Do not claim permanent deletion before it succeeds. |
| A large number of accounts or repeated actions target drafts and the queue. | Enforce per-founder active limits and bounded action rates while preserving a single authoritative current state. | Protect staff capacity and prevent queue flooding. |

## Decisions Log

| # | Decision | Alternatives Considered | Chosen Because |
|---|---|---|---|
| 1 | Allow unverified private drafts; require verified email to submit. | Require verification before drafting; allow unverified submissions. | Early preparation is useful, while review queue entry needs a stronger identity check. |
| 2 | Allow complete edits and explicit withdrawal while pending; reject stale review decisions. | Lock pending submissions; auto-withdraw on edits; allow stale decisions. | Founders retain control without letting staff decide on content they did not see. |
| 3 | Keep queue position on valid pending edits; resubmission after withdrawal goes to the back. | Move every edit to the back; retain place even after withdrawal. | Minor corrections should not reset a fair first-arrival order. |
| 4 | Auto-save drafts with visible status, retry, and conflict protection. | Manual Save only; silent last-write-wins. | Founders can leave and resume without mistaking failed or conflicting edits for saved work. |
| 5 | Require all listed fields at submission, including one logo, 1–10 screenshots, and 1–3 topics; use the agreed text, image, and HTTPS limits. | Permit sparse submissions; defer media validation. | Staff receive complete reviewable listings. |
| 6 | Permit founder-typed topics, reuse equivalent names, and keep new topics private until launch. | Fixed topic list; immediately public proposed topics. | Founders can describe new categories without exposing unreviewed content. |
| 7 | Allow the same website in multiple submissions with a staff-only possible-duplicate flag. | Automatically reject the second website. | Staff can distinguish genuinely different products. |
| 8 | Limit each founder to 10 private drafts and 3 pending submissions; allow withdrawal above the draft limit. | Unlimited active work; block withdrawal at the limit. | These starting limits bound storage and review load without trapping a founder in review. |
| 9 | Make confirmed draft deletion permanent; keep the draft available if deletion fails. | Recovery window; show success before media removal. | Founders can free space without a misleading deletion confirmation. |

## Scope Boundaries

### In Scope

- Founder draft creation, automatic saving, editing, return visits, conflict handling, and permanent deletion.
- Product text, HTTPS website, logo, screenshot, and topic input and validation.
- Private topic proposals and equivalent-name reuse.
- Verified and unsuspended submission, pending edit, explicit withdrawal, duplicate flagging, and active-work limits.
- Oldest-first staff queue entry and staff access to current submitted content with suspension and possible-duplicate flags.
- Failure and privacy behavior needed to demonstrate the draft-to-review handoff.

### Out of Scope

- Reviewer approval, rejection, and change-request actions and founder outcome notices (reason: next review-workflow slice).
- Launch-day selection, per-day launch limits, scheduling, publication, public product pages, and topic discovery after launch (reason: later launch and discovery slices).
- Votes, comments, follows, rankings, search, feeds, featured slots, jobs, and payments (reason: separate product slices or excluded from this version).
- Google sign-in and account settings beyond the existing identity capabilities (reason: separate identity work).

## Open Questions

- None for this slice. Later review and launch slices will define staff decisions and the public transition for new topics.

---
_This requirements document is the input for the **plan-architecture** skill._
_Next step: `/plan-architecture from: specs/requirements/REQ-add-product-draft-submission.md`_
