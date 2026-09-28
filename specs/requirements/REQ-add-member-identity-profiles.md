# Requirements: Add Member Identity and Profiles

> **Date:** 2026-09-21
> **Type:** feature
> **Source:** docs/source/launchpad-client-brief.md; docs/source/engineering-guide.md; AGENTS.md; CLAUDE.md; confirmed requirements interview
> **Phase:** 1 of 5 (Requirement Engineering)

## Summary

Let people create an email-and-password account, sign in, verify their email, recover a forgotten password, and manage a profile. Accounts start with an incomplete, private profile; a verified member chooses when to publish a complete one. This establishes a trustworthy member identity for later founder and community features without making an unverified or incomplete profile public.

## Problem & Motivation

The local foundation is complete, but Launchpad has no member accounts. The product cannot safely identify founders, allow members to prepare a profile, or later enforce verified-email voting. The client also requires password recovery and public member profiles. Delivering these together gives a member a usable account journey while protecting unpublished personal information and avoiding account-discovery leaks.

## Users & Consumers

- Prospective members — create an account without revealing whether another person has registered a particular address.
- Unverified members — sign in, edit their private profile, and obtain another verification email.
- Verified members — publish, edit, or hide their profile and recover account access.
- Visitors — see only profiles that members have explicitly published.
- Future voting and founder features — determine whether a member has verified their email; they do not gain voting or product behavior in this slice.

## Functional Requirements

Each requirement is specific, testable, and assigned an ID for traceability.

| ID | Requirement | Acceptance Criterion |
|----|-------------|----------------------|
| R1 | Register with an email address and password; create one account per address according to a consistent address-comparison policy. | A new valid address creates one unverified account with a private profile. Concurrent attempts with the same address cannot create two accounts. Malformed addresses and passwords that fail the stated policy are rejected without creating an account. |
| R2 | Keep the public registration response independent of whether an address is already registered. | The same public confirmation is shown for a well-formed address whether registration created an account or found an existing one. An existing account and its password are unchanged; only its mailbox may receive private next-step guidance. |
| R3 | Allow members to sign in and sign out using their email and password. | Correct credentials open a member session, including for an unverified member; sign-out ends that session. Incorrect credentials, unknown accounts, and unavailable accounts receive the same generic sign-in failure. An unverified session can view and edit only that member's private profile, not publish it or pass the verified-email eligibility check. |
| R4 | Verify control of the registered email address before granting verified-member privileges. | A valid verification link marks only its intended account verified once. Before that event, the member cannot publish a profile and is not eligible for later voting. An expired, used, superseded, or altered link has no effect and offers a safe route to request another. |
| R5 | Let a member request a replacement verification link. | The newest issued verification link remains usable for 60 minutes; issuing it invalidates earlier verification links. Repeated requests are limited, and a delayed or failed email never marks an address verified. |
| R6 | Let a member request password recovery without disclosing account existence. | For a well-formed address, the public response is the same whether an account exists or not. A real account may receive a reset link; an unknown address cannot reset any account. Repeated requests are limited. |
| R7 | Reset a password through a valid recovery link, including for an unverified member. | A reset link expires after 60 minutes and works once; a newly issued reset link invalidates earlier reset links. A valid reset changes only the intended account's password, leaves its email-verification state unchanged, ends all its existing sessions on every device, sends a change notice, and requires normal sign-in afterward. Invalid, used, superseded, and expired links cannot change a password. |
| R8 | Apply the agreed password policy at registration and reset. | Passwords shorter than 8 characters or known to be compromised are rejected. Passwords of at least 64 characters and passwords containing spaces are accepted when otherwise valid. Capitals, numbers, and symbols are allowed but no mixture is required. |
| R9 | Give each member a private, editable profile immediately after registration. | The owner can save and revisit an incomplete profile while signed in, whether or not their email is verified. A visitor or another member cannot obtain private profile details or its photo through direct profile access or public discovery. |
| R10 | Let a verified member explicitly publish a complete profile. | Publication succeeds only with a display name, a photo, a nonempty one-line bio of at most 160 characters, and at least one valid public HTTPS link. The photo must be JPEG, PNG, or WebP and at most 5 MB. A complete published profile is visible to visitors; an incomplete or unverified profile remains private. |
| R11 | Let an owner edit, unpublish, and later republish their profile. | The owner can make a published profile private immediately. Removing a required item from a published profile saves the edit and makes the profile private immediately; the page tells the owner what happened and an email is sent. Republishing requires a verified email and all publication requirements again. |
| R12 | Preserve the profile change when notification delivery is delayed. | If the email service is unavailable during an edit that makes a profile private, the edit and privacy change still succeed, the owner sees the page message, and the email is delivered after service recovery without duplicate privacy changes. |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criterion |
|----|-------------|----------------------|
| N1 | Keep credentials, recovery links, unpublished profile data, and private photos confidential. | Public responses and diagnostics reveal no password, token, private profile content, or private photo location. Only the owner can access unpublished profile details and photos, including by direct link. |
| N2 | Resist account enumeration and automated abuse across registration, sign-in, verification resend, and reset requests. | Existing and unknown addresses receive equivalent public registration/reset outcomes; login failures are generic; address and source-based request limits stop repeated automated attempts without permanently locking a member out. Differences in response timing must not trivially disclose account existence. |
| N3 | Make account and profile state changes reliable under retries, concurrent requests, and mail outages. | Concurrent registration preserves one account per address; a recovery or verification link cannot be redeemed twice; a successful password reset ends all earlier sessions; delayed email work remains deliverable after recovery. No partial failure exposes a profile or grants verified status. |
| N4 | Preserve accessible, usable account and profile journeys on desktop and mobile. | A member can complete registration, sign-in, verification, recovery, private-profile editing, publication, and unpublication with a keyboard and on a phone. Field errors and privacy-state changes are understandable without relying only on color. |

## Behaviors & Domain Rules

### Account access and verification

Registration requires an email and password. An account starts unverified and has a private profile. Unverified members can sign in and edit that profile, but verification is required before publication or future voting. A successful password reset does not verify the email. Sign-out ends the current session; resetting a password ends every existing session, including the one on which the request originated. The member signs in normally after a reset.

For well-formed registration and reset requests, public responses do not identify whether an address exists. Address comparison must be consistent across registration, sign-in, verification, and recovery so spelling or case variations do not create conflicting identities. Malformed input can receive a field-validation error. Requests for a new verification or reset link invalidate earlier links of the same purpose; each link lasts 60 minutes and is single use. One purpose does not silently complete the other.

### Profile privacy and publication

A profile remains private until its verified owner chooses to publish it. The owner can save incomplete drafts. Publication requires a display name, supported photo no larger than 5 MB, one-line bio no longer than 160 characters, and at least one public HTTPS link. The owner may unpublish at any time. If an edit removes a publication requirement, the edit is saved and the profile becomes private in the same user-visible action. The page explains the change immediately and an email notification follows, even if delivery must be retried.

**Why these rules matter:**

- Email verification establishes mailbox control for later voting and public identity, while restricted pre-verification access lets a member prepare a profile.
- Generic public responses reduce account enumeration; a private email can guide the real account holder.
- Link expiry, single use, and replacement limit the damage from an exposed or stale message.
- Immediate privacy changes prevent incomplete profiles and private photos from lingering in public views.
- Ending every session after a reset makes an old or stolen session unusable.

**Common mistakes:**

- Treating sign-in or password reset as proof of email ownership.
- Returning “email already registered” from registration or “no account found” from recovery.
- Changing a password without ending sessions on other devices.
- Rejecting an edit that makes a published profile incomplete, rather than saving it and making the profile private.
- Hiding a private profile page while leaving its photo or stale public copy reachable.
- Treating an email outage as permission to leave an incomplete profile public or to drop its notification.

## Edge Cases & Failure Modes

| Scenario | Decision | Rationale |
|----------|----------|-----------|
| A submitted email is missing, malformed, or differs only by an equivalent form under the account's comparison policy. | Reject malformed input; apply one comparison policy consistently and never create a second account for the same canonical address. | Prevents ambiguous identities and duplicate accounts. |
| Two registration requests for the same address arrive together. | At most one account is created; both public responses remain generic. | Concurrency must not defeat uniqueness or disclose which request won. |
| A registered member asks to register again. | Leave the existing account and password unchanged; show the generic public response and give private mailbox guidance if appropriate. | Avoids enumeration and unauthorized account changes. |
| An unverified member signs in or requests password recovery. | Allow restricted sign-in and recovery; neither action verifies the email. | Recovery must work without bypassing the verification gate. |
| Someone requests several verification or reset messages, including simultaneously. | Limit request volume. The most recently issued link of each purpose supersedes earlier ones; an older link fails safely. | Honors the confirmed latest-link rule while reducing inbox flooding and link invalidation abuse. |
| A link is altered, expired, already used, or from a previous request. | Do not verify or reset; show a safe failure and offer a way to request a fresh link. | A stale message cannot change identity state. |
| Verification or reset email delivery is delayed or unavailable. | Do not grant verification or reset access without a valid redeemed link. Preserve eligible mail for retry and expose an honest request state. | Mail outages must not become security bypasses or lost recovery opportunities. |
| A password is too short, compromised, very long, or contains spaces or symbols. | Enforce the 8-character minimum and compromised-password rejection; support at least 64 characters and spaces without a character-mixture rule. | Matches the confirmed policy without encouraging predictable composition patterns. |
| A reset link is redeemed while the member has several signed-in devices. | Change the password once, end all prior sessions, notify the member, and require a new sign-in. | Recovery must remove possible attacker access on every device. |
| A profile is incomplete or its owner has not verified their email. | Keep it private; deny publication and public reads while allowing the owner to edit it. | Draft identity details are not public content. |
| A photo is unsupported, over 5 MB, or a required link is not a valid public HTTPS URL. | Reject publication with a field-specific explanation; preserve the private draft. | Required content must be safe and understandable to correct. |
| Two profile edits or publish/unpublish actions overlap. | The resulting profile and its visibility must satisfy the publication rule together; an incomplete profile cannot remain public. | A race must not leak a profile that no longer qualifies for publication. |
| A published member removes the photo, empties the bio, or deletes the last link. | Save the edit, make the profile private immediately, show an on-page notice, and send an email even if delivery is delayed. | The user's requested edit succeeds without leaving an invalid public profile. |
| A profile is made private after it was public. | Public discovery and direct access stop exposing profile details and its photo; the owner can still view and edit them. | “Private” must be effective across all public surfaces. |
| Registration, sign-in, reset, or email requests are automated at high volume. | Apply request limits by account/address and source, keep public errors generic, and avoid permanent lockout solely from hostile attempts. | Protects accounts and mailboxes without allowing easy denial of service. |

## Decisions Log

| # | Decision | Alternatives Considered | Chosen Because |
|---|----------|-------------------------|----------------|
| 1 | Keep registration, sign-in, verification, recovery, and profiles in one identity slice. | Split account access and profiles into separate REQs. | The developer explicitly chose one slice containing the complete account journey. |
| 2 | Allow restricted sign-in and private-profile editing before email verification. | Block sign-in until verification. | Members can prepare their profile while verified-email privileges stay gated. |
| 3 | Use generic public registration and reset responses. | Explicitly disclose that an email is already registered. | The developer preferred stronger protection against account enumeration. |
| 4 | Make verification and reset links single use, valid for 60 minutes, with new requests invalidating earlier links of that purpose. | Keep older links active or use a different expiry. | The developer selected a short, predictable recovery window and latest-link behavior. |
| 5 | Allow password recovery for unverified accounts without verifying them. | Require verification before recovery or treat recovery as verification. | Members must regain access without bypassing the verification requirement. |
| 6 | End all sessions on every device after a successful password reset. | Keep current or other sessions active. | Stolen sessions should not survive recovery. |
| 7 | Require at least 8 password characters, support at least 64 and spaces, reject compromised passwords, and impose no character-mixture rule. | Require 15 characters or a mix of capitals, digits, and symbols. | The developer chose an 8-character minimum after considering the stronger 15-character recommendation; the no-mixture rule avoids predictable patterns. |
| 8 | Keep profiles private until a verified member explicitly publishes a complete one, and permit later unpublication. | Publish by default or make publication permanent. | Members control exposure of their personal details. |
| 9 | Require display name, photo, one-line bio, and at least one public HTTPS link for publication. Accept JPEG, PNG, or WebP photos up to 5 MB and bios up to 160 characters. | Make photo, bio, or link optional or accept broader limits. | The developer confirmed these as the minimum useful public profile and bounded inputs. |
| 10 | Save an edit that makes a published profile incomplete, make it private immediately, and notify on the page and by email. | Reject the edit or leave the incomplete profile public. | The requested edit is honored while privacy remains correct. |
| 11 | Deliver the privacy-change email after recovery if mail is unavailable; do not delay the profile change. | Fail the edit until email delivery succeeds. | Email availability must not control immediate profile privacy. |

## Scope Boundaries

### In Scope

- Email/password registration, sign-in, sign-out, email verification, verification resend, password reset, and password-change notice.
- Restricted access before verification and a verified-email eligibility signal for later features.
- Private profile drafts; photo, bio, name, and public HTTPS links; explicit publication and unpublication.
- Automatic unpublication plus immediate page notice and reliable email notice when an edit makes a published profile incomplete.
- Privacy, input validation, request limiting, retries, and accessible desktop/mobile journeys for these flows.

### Out of Scope

- Google sign-in, passkeys, multifactor authentication, and changing the registered email (reason: separate identity expansions).
- Staff roles, suspension, account deletion, and moderation (reason: separate authorization and governance slices).
- Creating products, founder status, voting, or public product lists (reason: these features can consume identity later; they are not delivered here).
- A notification bell, preference center, or general notification inbox (reason: only the two account/profile email notices and the immediate page notice are needed here).
- Public search, feeds, and profile-product discovery (reason: later product slices; private-profile visibility still applies to any public read in this slice).
- Architecture choices, storage layout, transport contracts, and implementation tasks (reason: later workflow phases decide how to meet these requirements).

## Open Questions

None blocks this slice. Later identity work will need separate decisions for email-address changes, Google sign-in, stronger authentication, and account deletion.

---
_This requirements document is the input for the **plan-architecture** skill._
_Next step: `/plan-architecture from: specs/requirements/REQ-add-member-identity-profiles.md`_
