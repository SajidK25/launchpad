# Requirements: Add Launch Scheduling and Publication

> **Date:** 2026-10-08
> **Type:** feature
> **Source:** `docs/roadmap.md` (recommended next work, item 2), `docs/source/launchpad-client-brief.md`, `docs/source/engineering-guide.md`, `docs/source/inspiration.md`, `AGENTS.md`, `specs/requirements/REQ-product-review-workflow.md`; requirements interview and confirmed decision summary
> **Phase:** 1 of 5 (Requirement Engineering)

## Summary

Founders with approved products can reserve a launch day, change or cancel their booking before launch, and have their product automatically published on a basic public product page. Scheduling uses one UTC calendar, limits each founder to two launches per day, and keeps unpublished content private. Launch reminders, live announcements, and failure notices keep founders informed while respecting separate email and in-site preferences.

## Problem & Motivation

The existing workflow ends with a private, approved product. Founders need to choose when their reviewed work becomes public, and visitors need a product page they can actually open after publication. This roadmap slice connects approval to publication without requiring the later discovery and community features. Predictable dates, safe capacity handling, and explicit outage behavior prevent unexpected publication and lost bookings.

## Users & Consumers

- **Founders** — schedule their own approved products, manage bookings, understand outcomes, control launch notices, and update permitted content after launch.
- **Reviewers and admins** — retain the existing ability to return unlaunched approved work for changes, including cancellation of any associated booking.
- **Visitors and members** — read launched product pages and media without gaining access to unpublished work or private review information.
- **Operations staff** — understand delayed or failed launches and assess publication against the agreed timing and volume target.
- **Notification recipients** — receive relevant launch notices through their selected channels without confusing duplicates or obsolete reminders.

## Functional Requirements

Each requirement is specific, testable, and assigned an ID for traceability.

| ID | Requirement | Acceptance Criterion |
|---|---|---|
| R1 | Use one platform-wide launch calendar with a daily boundary at 00:00 UTC. Clearly label scheduling dates and times as UTC. | Founders in different local timezones see the same eligible launch dates and the same UTC launch boundary for a booking. |
| R2 | An eligible founder can schedule only their own approved product, for tomorrow through 90 days ahead inclusive, measured by the current UTC date. | An owned approved product accepts dates at both boundaries. Today, past dates, dates 91 days ahead, missing or invalid dates, another founder's product, and products in other states are refused without changing the product. Existing account eligibility and suspension rules remain enforced. |
| R3 | Limit each founder to two products per UTC launch day, with no platform-wide daily cap. | A founder can reserve two products for one day but cannot reserve a third; another founder can still book that day. Concurrent attempts cannot exceed the limit. |
| R4 | Let founders reschedule their scheduled products to another eligible date strictly before the original scheduled launch time. Preserve the original booking if the new booking cannot succeed. | A valid change releases the old slot and reserves the new one. An invalid date, full personal daily allocation, or failed change leaves the original date and slot intact. |
| R5 | Let founders cancel strictly before scheduled launch time, returning the product to approved and releasing the slot. | Cancellation before midnight leaves the product approved and private, with its former slot available. Cancellation and rescheduling at or after the scheduled midnight fail even if publication is delayed. |
| R6 | Automatically publish eligible scheduled products when their launch day begins, keeping all public product details and media private until publication. | A visitor cannot read the product or its media before publication; after successful publication, its public page and media become readable without sign-in and the founder sees launched status. Repeated processing does not launch it again. |
| R7 | Recover delayed publication during the original UTC launch day. If that entire day is missed, return the product to approved for the founder to reschedule. | Recovery within the booked date publishes the eligible product. Recovery at or after the following midnight does not publish the missed booking, leaves the product private and approved, and records the missed-day reason. |
| R8 | Block publication when the founder is suspended before publication, release the booking, and require a new booking after reinstatement. | A suspended founder's scheduled product stays private and loses its reservation. Reinstatement does not restore or automatically publish the old booking; the founder must choose a new eligible date. |
| R9 | When authorized staff return a scheduled product for changes, cancel its booking, release its slot, and suppress pending reminders for that booking. Preserve existing review feedback and staff audit behavior. | The product follows the existing private changes-requested workflow. After resubmission and approval, no former booking is restored; the founder chooses a new date. |
| R10 | Provide a basic public product page showing name, pitch, description, logo, screenshots, website link, topics, and launch date. Exclude private review feedback, scheduling history, and private account details. | A launched page presents all listed product fields and media. A visitor cannot obtain the excluded information through the page or its supporting public reads. |
| R11 | Keep approved and scheduled product content locked against founder edits. After launch, permit only description and links to change under the existing content validation rules. | Before launch, direct founder content edits fail. After launch, valid description/link edits appear on the public page, while name, pitch, logo, screenshot, and topic changes fail without altering them. |
| R12 | Send a reminder 24 hours before launch, or immediately when a booking is made less than 24 hours before launch. Each new booking date gets its own reminder. | An enabled channel receives the reminder at the applicable trigger. Rescheduling suppresses pending old reminders and creates the appropriate reminder for the new booking, even if the previous reminder was already delivered. Repeated requests for the same booking do not create duplicate reminders. |
| R13 | Suppress undelivered reminders after cancellation, replacement of the booking, return for changes, blocked launch, or arrival of the scheduled launch time. | A pending reminder checked after any of these events is not delivered. Recovery from an email outage after launch time does not send an obsolete reminder. |
| R14 | Send a product-is-live notice only after successful publication, through enabled email and in-site channels. | A successful launch produces one logical live notice per enabled channel; approved, scheduled, blocked, or missed-day products do not produce a successful-launch notice. Still-relevant live notices survive delivery outages. |
| R15 | Explain missed-day and suspension-blocked launches in the founder dashboard and send launch-failure notices through enabled channels. | Each such failure has a persistent founder-visible reason and an email and in-site notice when enabled. The dashboard reason remains available even when both channels are disabled. |
| R16 | Provide separate email and in-site switches for each of three notice types: reminder, live announcement, and launch failure. Default all six switches to enabled and check current choices before delivery. | Founders can save and reload each independent choice. Disabling one channel/type suppresses its pending delivery without disabling another channel/type or hiding dashboard status. |
| R17 | Integrate launch notices into the existing persistent notification bell and live unread behavior. | An enabled in-site launch notice persists, updates the connected recipient's list/count without refresh, and follows existing individual-open read marking. Opening the bell alone does not mark notices read; reconnecting restores the correct history and unread count. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criterion |
|---|---|---|
| N1 | During normal operation, publish up to 1,000 eligible products sharing a midnight cutoff within one minute of 00:00 UTC. | With 1,000 valid bookings due at one cutoff, every product is publicly readable within 60 seconds after that cutoff, with none exposed beforehand. |
| N2 | Preserve one coherent booking and publication outcome under concurrent actions, repeated requests, and interrupted processing. | Competing booking requests never overbook a founder's day; failed rescheduling preserves the old booking; retries do not create duplicate launches or logical notices. Recovering from interruption follows the same-day/missed-day rules. |
| N3 | Keep unpublished product details and media private, and keep account and review information private after publication. | Visitors and other founders cannot retrieve unpublished content through public pages, direct reads, media access, search, or other public surfaces. Published reads contain only the agreed public information. |
| N4 | Delivery outages must not lose still-relevant notices or undo a successful product action. Recheck relevance and preferences before delivery. | With email unavailable, booking/publication outcomes remain recorded and dashboard/in-site behavior remains available as applicable. Recovery delivers eligible notices without duplicate logical notices and drops obsolete reminders. |
| N5 | All frontend views in this slice use Brutalism & Neobrutalism while remaining mobile-friendly, accessible, and understandable. | Scheduling, booking management, preferences, dashboard states, and public product views use thick black borders, hard offset shadows, and loud flat colours guided by `docs/source/inspiration.md`. At approximately 390px and 1280px widths, required actions work without horizontal overflow; keyboard access, visible focus, labels, readable contrast, and perceivable status/error messages are present. |
| N6 | Keep private notices restricted to their intended recipient and enforce scheduling/editing permissions regardless of how an action is attempted. | Another account receives no private launch notice or unread event and cannot schedule, cancel, reschedule, or edit the founder's product. Invalid/repeated requests do not bypass capacity or timing rules. |

## Behaviors & Domain Rules

### Calendar, capacity, and booking lifecycle

The launch calendar uses UTC, independent of the founder's local timezone. If the current UTC date is D, eligible new dates are D+1 through D+90 inclusive. A chosen date starts at 00:00 UTC. There is no same-day booking.

Only approved products proceed to scheduling. Each founder may have at most two products allocated to a given launch day; other founders have their own allocations. The 1,000-product performance target is a supported volume, not a platform booking cap.

Successful rescheduling replaces the booking and frees the old allocation. An unsuccessful attempt preserves the old booking. Cancellation returns the product to approved. Neither action is allowed at or after the original scheduled midnight, including while publication is waiting to complete. Retrying the same booking must not consume another slot or create another reminder.

### Publication and eligibility changes

Products stay private until successful publication. Normal publication completes within one minute after midnight. If processing is delayed, the product may still publish during its chosen UTC day. Once that entire day has elapsed, the missed booking must not publish on a later date: the product returns to approved and the founder must choose again.

Suspension before actual publication blocks the launch and releases the booking. Reinstatement does not reinstate the booking. Staff returning scheduled content for changes also cancel the reservation and pending reminders; the existing review explanation and audit rules apply, and a new approval does not restore the former date.

### Public page and editable content

Publication introduces one basic public product page with the agreed product fields and media. It does not introduce discovery listings, rankings, search, or community interactions. Private review information, scheduling history, and private account details do not become public alongside the product.

Approved and scheduled content remains locked. Staff correction requests continue through the existing review path. Once launched, founders can change description and links only, using existing validation. This specifically extends the earlier review requirements' prelaunch edit lock for products that have now launched.

### Notifications and preferences

A reminder is due 24 hours before launch; a closer booking triggers it immediately. A changed date creates a reminder for the new booking and suppresses any undelivered reminder for the old one. Already delivered historical notices need not be recalled, but they must not cause a new duplicate for the same booking. No pending reminder is sent at or after scheduled launch time, even if publication has been delayed.

Successful publication produces a live notice. A missed entire day or suspension-blocked launch produces a failure notice and a dashboard explanation. These are three distinct preference categories, each with independent email and in-site choices, enabled by default. Preferences are checked before delivery, and dashboard explanations do not depend on them. Existing persistent bell, live unread updates, individual read marking, and private-recipient behavior carry forward.

### Visual direction

Every frontend view delivered or changed for this slice follows the confirmed Brutalism & Neobrutalism direction: raw HTML character, thick black borders, hard offset shadows, and loud flat colours. Use `docs/source/inspiration.md` as the reference guidance without copying branding, layouts, copy, or assets. The user's explicit visual direction governs this slice while accessible controls and mobile usability remain required.

**Why these rules matter:**

- One UTC boundary makes dates and cutoff behavior consistent worldwide.
- Tomorrow-first booking gives products a full planned launch day; the 90-day window bounds future reservations.
- A per-founder limit follows the brief without imposing an unapproved platform-wide scarcity limit.
- Preserving old bookings on a failed move prevents accidental loss of an agreed date.
- Same-day recovery preserves the founder's intended date; a missed day requires a fresh choice rather than an unexpected later launch.
- Checking suspension and review eligibility before publication protects the approval boundary.
- Channel-specific preferences and expiry of stale reminders keep notices useful and under founder control.
- A basic public page makes the scheduling-to-publication slice independently demonstrable.

**Common mistakes:**

- Using the browser's local date for eligibility or treating two launches as a platform-wide limit.
- Allowing a cancellation after midnight because background publication has not finished.
- Releasing the original booking before knowing whether a reschedule can succeed.
- Publishing a product merely because its scheduled time passed, even after its entire launch day was missed.
- Restoring old bookings automatically after reinstatement or reapproval.
- Sending stale reminders after launch time or duplicate notices after retries.
- Publishing private review/account information along with product content.
- Allowing edits to approved content or to locked postlaunch fields.

## Edge Cases & Failure Modes

| Scenario | Decision | Rationale |
|---|---|---|
| The founder supplies no date, an invalid value, today, a past day, or a day beyond D+90. | Refuse the booking and preserve current state; identify the invalid choice. | Only the confirmed inclusive window is eligible. |
| The founder's local calendar differs from UTC near midnight. | Use and label the UTC calendar. | All founders share the same capacity and cutoff definition. |
| Two requests compete for the founder's last daily slot. | Only an allocation within the two-product limit succeeds. | Concurrency must not bypass the product limit. |
| A reschedule targets a day that becomes full before completion. | Refuse the move and retain the old reservation. | A failed change must not cost the founder their booking. |
| A booking or cancellation request is repeated after an uncertain response. | Preserve the single effective outcome and do not create duplicate reservations or notices. | Retrying must be safe. |
| Cancellation or rescheduling arrives exactly at scheduled 00:00 UTC. | Refuse it; follow the original booking's publication and outage rules. | The cutoff is based on time, not processing progress. |
| Publication resumes later on the booked UTC day. | Publish if the product remains eligible. | Recovery still honors the chosen date. |
| Publication resumes at or after the next midnight. | Return the missed product to approved, keep it private, and record/send the failure outcome. | Avoid an unexpected launch date. |
| The founder is suspended before publication, including during a publication delay. | Block publication, release the slot, and require a new booking after reinstatement. | Publication eligibility must hold when publication takes place. |
| Staff return scheduled content for changes. | Cancel the booking and pending reminders and follow the existing review feedback/audit path. | Unapproved corrections cannot publish under an old booking. |
| A reminder already went out before rescheduling. | Create the appropriate reminder for the new booking and suppress any remaining old pending reminder. | Founders need the corrected date without repeat deliveries for the same booking. |
| Email recovers after the scheduled launch time. | Drop undelivered reminders; deliver still-relevant live/failure notices according to preferences. | Old reminders become misleading, while outcomes remain useful. |
| A founder disables a notice channel while its delivery is pending. | Honor the current preference before delivery. | Pending work must not override the founder's choice. |
| Both failure-notice channels are disabled. | Keep the dashboard reason visible. | Product state must remain understandable independently of messaging preferences. |
| Processing is interrupted during booking or publication. | Recover to one coherent result without an extra slot, duplicate launch, or duplicate logical notice. | Partial processing must not violate the lifecycle. |
| Many founders share one launch cutoff. | Support 1,000 products within the one-minute target; enforce limits per founder. | The agreed scale target is distinct from a global booking cap. |
| A visitor guesses an unpublished page or media address. | Deny access until actual publication. | A booking must not disclose commercially sensitive work. |

## Decisions Log

| # | Decision | Alternatives Considered | Chosen Because |
|---|---|---|---|
| 1 | Use one platform calendar and 00:00 UTC cutoff. | Founder-local calendars or another shared timezone. | Consistent worldwide days without daylight-saving changes. |
| 2 | Permit D+1 through D+90 inclusive. | Same-day launches or unrestricted future booking. | Founders plan full launch days within a bounded horizon. |
| 3 | Allow two launches per founder per day and no platform-wide cap. | A shared platform daily cap. | The user confirmed the client brief's founder-specific limit. |
| 4 | Allow changes and cancellation strictly before scheduled midnight; cancellation returns to approved. | No cancellation or changes while delayed publication is processing. | Founders retain control before a predictable cutoff. |
| 5 | Preserve the original booking when a reschedule fails. | Release first and leave the product unbooked on failure. | A failed request should not destroy a valid reservation. |
| 6 | Recover publication within the same UTC day; require rebooking after an entirely missed day. | Publish automatically on a later day. | Avoid launching on a date the founder did not choose. |
| 7 | Suspension blocks publication and requires a new booking after reinstatement. | Automatically restore or publish the old booking. | A launch requires current eligibility and a deliberate date choice. |
| 8 | Returning scheduled content for changes releases its booking and requires another date after approval. | Retain the booking through further review. | An old reservation must not publish work requiring review. |
| 9 | Include a basic public product page in this slice. | Defer all public views to discovery work. | Publication needs an independently visible result. |
| 10 | Permit only description and link edits after launch; retain prelaunch locks. | Defer postlaunch edits or allow wider edits. | Follow the client brief while preserving reviewed identity and media. |
| 11 | Include reminders, live announcements, and launch-failure notices. | Defer launch communication or provide only successful-launch notices. | Founders need preparation, confirmation, and explanations of failed launches. |
| 12 | Remind at 24 hours, immediately for closer bookings, and again for a changed date; expire pending reminders at launch time. | Fixed reminders that ignore late bookings, reschedules, or outages. | Notices should describe the current upcoming booking. |
| 13 | Provide six independent, default-on channel/type switches checked before delivery. | One global switch or shared email/in-site controls. | Founders can keep useful channels without receiving unwanted notices. |
| 14 | Keep dashboard failure reasons visible regardless of preferences. | Rely entirely on notifications for explanations. | Disabling messaging must not hide the product's outcome. |
| 15 | Support 1,000 products at one cutoff, public within one minute under normal operation. | Leave timing and volume unspecified. | Establish a measurable launch-day target. |
| 16 | Apply Brutalism & Neobrutalism to all frontend views in this slice. | Leave visual direction unspecified. | The user explicitly chose this direction with the repository's inspiration guidance. |

## Scope Boundaries

### In Scope

- Founder scheduling, rescheduling, cancellation, UTC eligibility, and per-founder capacity.
- Automatic publication, same-day recovery, missed-day handling, and existing suspension/review eligibility integration.
- Basic public product pages and public access to published product media only.
- Postlaunch description/link edits with all other agreed content locked.
- Launch reminders, live announcements, failure notices, dashboard explanations, and launch-specific preference controls.
- Existing bell and live unread behavior for new launch notice types.
- Privacy, permissions, concurrency, safe retries, accessible mobile interactions, visual direction, and the agreed publication-volume target.
- Verification evidence and operating guidance for the scheduling/publication behavior.

### Out of Scope

- Today's listings, past-day archives, rankings, topics browsing, and search (reason: next discovery roadmap slice).
- Voting, comments, follows, feeds, and other community interactions (reason: later community work).
- General notification preference management, digests, and unrelated notice types (reason: only the three launch categories are pulled into this slice).
- New suspension administration, takedown tools, or general moderation features (reason: this slice responds to existing eligibility changes).
- Broad site redesign outside views delivered or changed for this slice (reason: the confirmed design direction applies to the scoped frontend work).
- Founder analytics, exports, payments, featured-slot sales, and jobs (reason: separate or deferred product capabilities).
- Changes to reviewed-product retention, deletion policy, or rejection appeals (reason: preserve the existing review decisions).

## Open Questions

- None blocking this requirements slice. The user confirmed the complete decision summary as accurate on 2026-10-08. Architecture and task planning must preserve these product decisions and keep the implementation focused on the scheduling-to-publication workflow.

---
_This requirements document is the input for the **plan-architecture** skill._
_Next step: `/plan-architecture from: specs/requirements/REQ-add-launch-scheduling-publication.md`_
