# Requirements: Stakeholder Demo Data Seeding

> **Date:** 2026-10-26
> **Type:** feature
> **Source:** Verbal brief; `docs/roadmap.md`; `docs/development.md`; `docs/PRODUCTION_DEPLOYMENT_PROXMOX.md`
> **Phase:** 1 of 5 (Requirement Engineering)

## Summary

Create a repeatable demo-data seeding capability for local development and the specifically designated Proxmox demo/staging environment. It will create fictional, login-ready founders and a reviewer, public profiles and launched products, plus a small set of private workflow and in-app notification examples so stakeholders can explore the features implemented so far.

The VM is currently configured and deployed with production settings and is publicly reachable at `launchpad.t99ltd.com`, but the owner designates it as the demo/staging target for this work. The seed must never run against a real production target or a VM containing real customer data.

## Problem & Motivation

Stakeholders need realistic data to explore Launchpad without manually creating many accounts, uploading profile photos and product media, and moving products through the review and launch workflow. Without a prepared dataset, the public catalog, founder profiles, archives, reviewer queue, and founder workspace are difficult to demonstrate consistently.

This seed is for demonstration of currently implemented capabilities. It must preserve unrelated operator/test records, avoid contacting real people, and retain reviewed products and immutable launch archives.

## Users & Consumers

- **Product owner/operator** — prepares and refreshes demo data in local development and the explicitly designated VM demo/staging environment.
- **Stakeholder/visitor** — browses fictional public profiles, today's launches, archives, product details, and discovery topics.
- **Demo founder** — signs in with an issued credential and explores founder profile and product workflow examples.
- **Demo reviewer** — signs in to inspect the staff review queue and review examples.
- **Engineering and QA** — verify seeding, rerun, collision, cleanup, privacy, and environment-safety behavior.

## Functional Requirements

| ID | Requirement | Acceptance Criterion |
|----|-------------|----------------------|
| R1 | Support local development and only the explicitly designated Proxmox demo/staging target. Real production environments are not seed targets. | A local run succeeds against the selected development stack. A VM run requires explicit designation of the named demo/staging target and confirmation that it contains no real customer data. An unapproved or real production target is rejected before any writes. |
| R2 | Add demo data alongside existing operator/test records without changing records not owned by this seed. | A before/after comparison shows all non-seed records unchanged. A matching account or product that is not seed-owned causes the run to abort with a safe conflict report. |
| R3 | Create at least 20 distinct fictional founder accounts, each verified and able to sign in. | After a successful seed, at least 20 seed-owned founder accounts exist, all are verified, and each has a usable unique credential. |
| R4 | Give each demo founder a public profile with a distinct synthetic photo and the profile details needed for a complete public page. | At least 20 public founder profiles appear with distinct synthetic photos, display names, short bios, links, and their associated products. No real person's photo or identity is used. |
| R5 | Provide safe credentials for the demo accounts and one reviewer account. | The seed creates one verified reviewer account with reviewer-only access and no admin account. Unique randomly generated passwords for all new demo accounts are written once to a private credential file; passwords are not printed to logs or sent by email. Ordinary reruns do not change passwords; password rotation is a separate explicit action. |
| R6 | Create at least 20 distinct fictional products that have launched and are publicly viewable, with at least one launched product owned by each seeded founder. | The public launch catalog contains at least 20 distinct seed-owned launched products. Each has a unique name and complete public summary, description, website link, logo, screenshot media, and topic assignments. Product links and media are fictional demo content and do not point to real third-party product sites. |
| R7 | Make public launch discovery and topic browsing demonstrable. | On the first successful run, launched products cover the target's current UTC date and the preceding seven UTC dates, with at least one product for today and at least one archived date. Products use varied topics across at least three topics, so catalog search and topic filters return distinguishable results. Reruns preserve the original launch dates and do not move launched products. |
| R8 | Create one additional fictional product example for each useful non-launched workflow state: draft, submitted for review, changes requested, rejected, approved but not scheduled, and scheduled. | The founder workspace shows one seed-owned example in each listed state; the reviewer workspace shows the submitted example. Unpublished examples and their media remain private from public profile, catalog, search, and product-detail reads. The scheduled example has a valid future launch date. |
| R9 | Create in-app review and publication notification examples without triggering outbound email. | Demo founder inboxes contain representative review and publication notices. No seed operation sends or queues email through Resend, SMTP, or another external mail provider. |
| R10 | Make normal seeding safe to repeat and recover from interruption. | Repeating a completed run creates no duplicate accounts, profiles, products, or notifications and preserves existing demo passwords and launch dates. If a run stops partway through, successfully created demo records remain and a rerun repairs missing seed-owned records without duplicating them. |
| R11 | Provide an explicit cleanup action limited by the product retention rules. | Cleanup removes only seed-owned records that have never been reviewed. It preserves reviewed, rejected, approved, scheduled, and launched product records, their audit history, and completed launch archives. It never removes or changes non-seed records. |
| R12 | Report what the seed operation created, reused, skipped, or could not complete without revealing secrets or private data. | The completion report includes counts by account/profile/product/workflow/notification category and a safe summary of failures. It does not include passwords, credential-file contents, storage keys, private product content, or unrelated account details. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criterion |
|----|-------------|----------------------|
| N1 | Protect credentials and avoid external communications during seeding. | The credential file is private to its owner, is excluded from source control and ordinary logs, and is not overwritten on normal reruns. No outbound mail is generated by the seed. |
| N2 | Keep public visibility and audit boundaries intact. | Public reads expose only launched products and explicitly published profiles. Reviewed products and archived launches remain retained and unchanged by cleanup. |
| N3 | Fail safely when the target or dependencies are not ready. | An unsafe target, real customer data on the VM, unavailable database/storage, or invalid required media is reported clearly; no unsafe target is written. Partial valid seed data can be repaired by a rerun. |

## Behaviors & Domain Rules

### Demo identities and public content

- Demo names, email identities, bios, links, product names, copy, logos, screenshots, and profile photos are fictional and distinct.
- Founder accounts are verified so stakeholders can sign in without relying on email delivery. Each founder owns at least one launched product and a public profile.
- The reviewer account has reviewer access only. Seed data never creates or grants admin access.
- Public products are distributed over the first run's target-side UTC date and the previous seven UTC dates. Launched dates remain fixed on reruns because past launch archives are immutable.
- Launched products use varied topic assignments to exercise public search and topic browsing. Draft and other unpublished workflow examples remain private.

### Lifecycle and notifications

- In addition to the public catalog, seed one example for draft, submitted, changes requested, rejected, approved-but-unscheduled, and scheduled.
- Seed representative in-app review/publication notices, but suppress delivery and queuing through all external mail providers.
- This requirement does not create vote history, rank snapshots, or vote-related notices.

### Reruns, conflicts, and cleanup

- Normal runs reconcile only records owned by this seed. They preserve generated passwords and launched dates.
- A conflicting email or other stable seed identity belonging to an unowned account/product is a hard error; the seed must not take it over or silently skip it.
- Successful work from an interrupted run remains. A later run repairs only missing seed-owned records.
- Cleanup is separate and explicit. It may remove seed-owned products only before review; reviewed decisions and launched archive data are retained for audit.
- VM seeding is allowed only for the named demo/staging VM after the operator confirms that no real customer data is present. Existing operator/test records may remain and must not be changed. Other production environments are never eligible.

**Why these rules matter:**
- Fictional, verified accounts make the stakeholder walkthrough usable without sending messages to real people.
- Keeping reviewed and launched examples protects the audit trail and immutable public history already established by product rules.
- Explicit target selection and additive ownership prevent a demo operation from changing real production or unrelated records.

**Common mistakes:**
- Treating a production deployment label as permission to seed any production environment; only the specifically designated VM demo/staging target is eligible.
- Recreating passwords or shifting launch dates during ordinary reruns, which breaks stakeholder access and archive history.
- Making draft, submitted, or scheduled products visible publicly to make the demo look fuller.
- Sending real Resend/SMTP messages as a side effect of creating accounts or review notices.
- Cleaning up reviewed or launched products despite their audit and archive retention rules.

## Edge Cases & Failure Modes

| Scenario | Decision | Rationale |
|----------|----------|-----------|
| Seed is pointed at an unapproved production target or at the named VM without explicit demo/staging designation. | Abort before writing data. | Prevents the demonstration utility from being used as a production data mutation tool. |
| The named VM contains real customer data. | Refuse VM seeding; require a designated customer-free demo/staging state. | This is the explicit condition for using the publicly reachable VM as a demo target. |
| Existing operator/test records are present. | Add seed-owned records while leaving all existing records unchanged. | The owner approved additive seeding alongside non-customer records. |
| A generated demo email or stable product identity matches an unowned record. | Abort and report a safe conflict; do not overwrite or skip it. | Protects account ownership and prevents ambiguous dataset contents. |
| The database or object storage becomes unavailable partway through the run. | Keep successfully created seed-owned records, report the failure without secrets, and allow an idempotent rerun to repair missing items. | Supports recovery without all-or-nothing loss across many records and media assets. |
| A cleanup is requested after products have entered review or launched. | Remove only never-reviewed seed-owned records; retain all reviewed/launched records and archive history. | Preserves the agreed audit-retention and immutable-archive rules. |
| A rerun occurs on a later UTC day. | Keep the first successful run's launch dates; do not move previously launched products. | Prevents rewriting public history and keeps archive links stable. |
| An in-app notice would normally trigger email delivery. | Store the in-app demo notice without queuing or sending external email. | Demo identities are not real mailboxes and the VM has a production mail provider configured. |

## Decisions Log

| # | Decision | Alternatives Considered | Chosen Because |
|---|----------|------------------------|----------------|
| 1 | Seed local development and the specifically named Proxmox VM as demo/staging; never seed real production. | Local only; any deployment with confirmation. | Stakeholders need the deployed demo while production data remains protected. |
| 2 | Allow operator/test records on the VM, but require the VM to be demo/staging and free of real customer data; never modify unowned records. | Require an empty database; allow coexistence with customer data. | Preserves safe operator/test setup while maintaining the user's no-customer-data condition. |
| 3 | Create at least 20 verified founders and public profiles with unique synthetic avatars, plus one verified reviewer and no admin account. | Require manual account creation; create a shared-password set; grant admin. | Gives stakeholders usable founder/reviewer access with synthetic identities and least privilege. |
| 4 | Generate distinct random passwords and write them to a private one-time credential file; preserve them on reruns and rotate only explicitly. | Shared password; reset on each run; manual setup. | Makes accounts usable while avoiding reusable shared secrets and credential churn. |
| 5 | Create at least 20 complete fictional launched listings, one per founder, with distinct product media and varied topics. | Minimal records; omit screenshots. | Supports realistic catalog, topic, profile, and product-detail walkthroughs. |
| 6 | Spread launches across the first run's current UTC date and previous seven UTC dates; keep dates fixed on reruns. | All launches today; archives only; shift dates each run. | Demonstrates today's launches and archives without rewriting launch history. |
| 7 | Add one example for each of six non-launched lifecycle states. | Public catalog only; only pending/change-request examples. | Gives founders and reviewer a representative workflow to explore. |
| 8 | Add in-app review/publication notifications, but do not send or queue external email. | No notices; send to configured addresses; test inbox only. | Demonstrates the in-app notification UI without contacting real recipients. |
| 9 | Keep voting/ranking data out of this seed. | Add vote and rank scenarios in the same seed. | Keeps the selected public-catalog/lifecycle slice bounded; voting/ranking can be seeded separately. |
| 10 | Make runs idempotent and repair interrupted runs; abort on unowned identity collisions. | Append new records; replace all data; overwrite matches. | Supports safe retries and prevents unintended account takeover or duplication. |
| 11 | Cleanup only never-reviewed seed-owned products; retain reviewed/launched records and immutable archives. | Full deletion; no cleanup; full deletion on local only. | Respects audit retention and archive immutability. |

## Scope Boundaries

### In Scope
- Local development and the specifically designated customer-free Proxmox demo/staging target.
- At least 20 verified founder accounts, public profiles, unique synthetic profile photos, complete launched products, and a reviewer-only demo account.
- Public launch dates for today and the prior seven UTC days, archive/catalog/topic coverage, and six representative private workflow states.
- Representative in-app review/publication notices with all external mail suppressed.
- Safe credentials, idempotent reruns, interruption recovery, conflict detection, bounded cleanup, and a safe completion report.

### Out of Scope
- Running against any real production environment or a VM containing real customer data (reason: demo content must not contaminate customer data).
- Vote histories, live ranking, rank snapshots, and vote moderation scenarios (reason: kept separate from this seed slice).
- Email verification walkthroughs, password-reset email walkthroughs, and outbound email (reason: seeded accounts are preverified and seeding must never contact real recipients).
- Comments/replies, follows/feeds, and Google sign-in (reason: not currently implemented according to the roadmap/client brief).
- Deleting reviewed or launched demo records (reason: audit retention and immutable archives).

## Open Questions

- None. The target boundary, demo dataset, credentials, lifecycle coverage, notification side effects, rerun behavior, and cleanup policy were confirmed in the requirements interview.

---
_This requirements document is the input for the **plan-architecture** skill._
_Next step: `/plan-architecture from: specs/requirements/REQ-demo-data-seeding.md`_
