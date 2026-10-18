# Launchpad Production: Client Eyeball Test Guide

**Prepared:** 15 October 2026  
**Environment:** [launchpad.t99ltd.com](https://launchpad.t99ltd.com)  
**Purpose:** A guided manual tour of the Launchpad features available in the current production build.

## What this guide covers

Use this checklist to walk through a member account, a public profile, a private founder product, a staff review, and the founder's review notifications. The production deployment has been confirmed healthy: local and public readiness returned HTTP 200, and the API, web, worker, scheduler, PostgreSQL, and Redis containers were healthy.

This is a live production system. Use test accounts, test product details, and small sample images that are safe to store. Registration, verification, password recovery, and review outcomes can send real transactional email. Review decisions are retained. Rejection is final for that product, so use a separate disposable test product if you exercise rejection.

## Before you begin

- Use an email inbox you control for the founder account. Use a second browser profile or private window for logged-out checks.
- Ask the Launchpad operator to provision a reviewer test account before the session. A member cannot grant themselves reviewer access. Do not share passwords in the test notes.
- Prepare a harmless profile photo, one product logo, and one or two screenshots. Accepted formats are JPEG, PNG, and WebP; each image must be no larger than 5 MB.
- Have a short fictional product name, pitch, description, HTTPS website, and one to three topic labels ready.
- Record each result as **Pass**, **Needs follow-up**, or **Not tested**. Include the screen and action, but never record passwords, email tokens, signed media URLs, or private product content in a shared report.

### Useful pages

| Page | Address |
|---|---|
| Create account | `https://launchpad.t99ltd.com/register` |
| Sign in | `https://launchpad.t99ltd.com/signin` |
| Email verification | Open the link delivered to your test inbox |
| Password recovery | `https://launchpad.t99ltd.com/recover` |
| Member profile | `https://launchpad.t99ltd.com/profile` |
| Founder products | `https://launchpad.t99ltd.com/products` |
| Staff review queue | `https://launchpad.t99ltd.com/products/review` |

The root page is currently a service connection status screen. A public launch feed and public product pages are not part of this build.

## Production deployment at a glance

Launchpad runs in Docker Compose on a private Ubuntu VM hosted by Proxmox. The VM has no public IP. Cloudflare Tunnel carries browser traffic for `launchpad.t99ltd.com` to the web container through a loopback-only port. The web container serves the React app and forwards REST, GraphQL, and live WebSocket traffic to the API. API, worker, and scheduler are separate processes; PostgreSQL stores authoritative data and Redis supports cache, queues, and live-update fanout. Private product and profile media is stored in Cloudflare R2 through authenticated, size-limited API uploads. Resend sends production transactional email.

GitHub Actions runs the quality gate, builds immutable API and web images, and publishes them to private GitHub Container Registry (GHCR). The production workflow connects to the VM through Cloudflare Access and SSH, then the VM controller deploys the verified image digests and checks readiness. Encrypted Restic backups use separate R2 repositories: database/configuration is backed up weekly and before migrations, and media is backed up weekly.

```text
                         ┌──────────────────────────┐
 Browser ── HTTPS ─────> │ Cloudflare DNS + Tunnel  │
                         └────────────┬─────────────┘
                                      │ loopback :18080
                                      v
                         ┌──────────────────────────┐
                         │ Web: React + Nginx       │
                         │ REST / GraphQL / WebSocket│
                         └────────────┬─────────────┘
                                      │ private Compose network
                                      v
                         ┌──────────────────────────┐
                         │ API ── PostgreSQL        │
                         │  │   └─ Redis            │
                         │  ├── Worker ── Resend    │
                         │  └── Scheduler           │
                         └──────┬───────────┬───────┘
                                │           │
                   private media│           │weekly + pre-migration
                                v           v
                         Cloudflare R2   Encrypted Restic
                                         backup repositories

 GitHub Actions ── build/publish ──> Private GHCR images
       └── Cloudflare Access + SSH ──> VM deployment controller
```

The application services and database are not directly exposed to the public internet. The public route terminates at the web service; API calls pass through that web ingress. The VM is shared with other workloads, so the diagram describes network and service roles rather than dedicated hardware.

## 1. Register, verify email, and sign in

1. Open `/register`, enter an email address you control, and create a password of at least eight characters.
2. Submit the form. The message is intentionally generic; check your inbox for the next steps email.
3. Open the verification link. On the Launchpad page, select **Confirm verification**.
4. Confirm the page reports that the email is verified. Return to `/signin`, sign in, and confirm the profile workspace opens.
5. Sign out, sign in again, and confirm the account can be used in a fresh browser session.

**Look for:** safe, understandable success/error messages; verification mail arrives; a verified account can sign in; sign-out ends the session. Repeated registration or recovery messages should not reveal whether an email address already belongs to an account.

## 2. Recover a password

1. Sign out and open `/recover`.
2. Request a recovery email for the founder test account.
3. Open the email link, choose a new password, and submit it.
4. Sign in with the new password. If desired, confirm the previous password no longer works.

**Look for:** a generic confirmation on the recovery form and a usable reset flow. Recovery links expire after 60 minutes and are single-use.

## 3. Complete and publish a member profile

1. While signed in, open `/profile`.
2. Enter a display name, a one-line bio (up to 160 characters), and at least one public HTTPS link.
3. Upload a JPEG, PNG, or WebP profile photo up to 5 MB. Wait for validation, then save the profile.
4. Select **Publish profile**. Confirm the page says the profile is public and offers **View public profile**.
5. Open the public profile link in a private browser window while signed out. Confirm the display name, bio, link, and photo are visible.
6. Return to the signed-in profile and choose to make it private. Refresh the signed-out page; the profile should no longer be available publicly.

**Look for:** the profile starts private, incomplete profiles cannot be published, and the public view contains only the information the member chose to publish. Do not use personal details or a photo the tester does not want public.

## 4. Create a private product draft

1. Open `/products` and select **Create a product draft**.
2. Enter product details. The submission limits are: name up to 80 characters, one-line pitch up to 160, description up to 5,000, HTTPS website, and one to three distinct topics (each up to 40 characters).
3. Pause after editing and wait for the visible save status to indicate the draft is saved. Refresh the page and reopen the product; confirm the latest saved values remain.
4. Upload one logo and at least one screenshot. Use JPEG, PNG, or WebP images up to 5 MB each. Wait for validation, select the uploaded assets, and save the media selection.
5. Confirm the submission checklist reflects the required fields, logo, screenshot, and topics.
6. In a private browser window, try to open the founder product workspace while signed out. Confirm the draft details are not shown.

**Look for:** drafts save automatically and remain private; media is validated before attachment; incomplete content stays editable. The founder can have up to 10 private drafts and 3 active review submissions.

## 5. Submit a product for staff review

1. Return to the complete draft in the founder session.
2. Confirm the email is verified and every submission checklist item is complete.
3. Select **Submit for staff review**. Wait for the confirmation that the product entered the review queue.
4. Open `/products` and confirm the product status is **Submitted** or **In review**.
5. While it is pending, try an allowed content edit and wait for autosave. Confirm the queue place is retained. Optionally use **Withdraw to private draft** and confirm it leaves the queue; resubmitting later returns it to the back of the queue.

**Look for:** unverified accounts cannot submit; the final saved version is submitted; pending edits must remain complete; a withdrawn or unsubmitted product remains private.

## 6. Review the submission as staff

Use the operator-provisioned reviewer account in a separate browser profile.

1. Open `/products/review` and locate the test product in the oldest-first pending queue.
2. Open the product. Review its current name, pitch, description, website, topics, logo, screenshots, submission time, and version.
3. Note any staff-only duplicate or suspended-founder warning if one is shown.
4. Choose **Request changes**, enter a clear explanation, and select **Record review decision**. Feedback is required and limited to 2,000 characters.

**Look for:** the current submission details load, private assets are visible to the reviewer, and a decision is recorded once. A stale review should prompt a refresh instead of applying to changed content.

## 7. Check founder notifications and correct the product

Return to the founder browser. For the live-update check, keep the founder workspace open while the reviewer submits the decision.

1. Confirm the notification bell's unread count updates without refreshing the founder page.
2. Open the bell and select the review update. Confirm it is marked read and opens the affected product.
3. Confirm the requested changes feedback is visible in the founder workspace and an outcome email arrives.
4. Correct the product, wait for the saved state, and resubmit.
5. Return to the staff queue and confirm the resubmission appears as a new arrival at the back of the queue.

**Look for:** in-site notifications persist, the unread count updates live, opening one item marks that item read, and email plus in-site notices describe the same outcome.

## 8. Approve the corrected submission

1. As staff, reopen the resubmission and choose **Approve**. Record the decision.
2. As the founder, confirm the bell/email notice and the product's **Approved** status.
3. Try to edit the approved product as the founder. Confirm its reviewed content is locked.
4. As a signed-out visitor, confirm the approved product and its media are still not publicly available.

**Look for:** approval is recorded and notified, but does not publish the product. Approved products remain private until a future launch workflow exists.

## 9. Optional: test final rejection on a separate product

Rejection is permanent in the current workflow. Only do this with a separate disposable test product after the client/operator agrees.

1. Submit another complete test product.
2. As staff, select **Reject**, enter founder-visible feedback, and record the decision.
3. As the founder, confirm the rejected status, feedback, notification bell item, and email.
4. Confirm that the rejected product cannot be edited or resubmitted and remains private.

## What is not available yet

- Launch date scheduling, rescheduling, capacity selection, and automatic publication.
- Public product pages or a public daily launch feed.
- Voting, comments, follows, search, rankings, feeds, founder analytics, and exports.
- Google sign-in and member notification preference controls.

These items should be treated as future work, not failed tests. The review workflow's final operating procedure/decision record is also still outstanding. This guide records a client eyeball pass only; it does not replace full QA, security review, backup restoration evidence, or launch readiness approval.

## Session result

| Journey | Pass | Needs follow-up | Not tested | Notes |
|---|:---:|:---:|:---:|---|
| Registration, verification, and sign-in | ☐ | ☐ | ☐ | |
| Password recovery | ☐ | ☐ | ☐ | |
| Private and public profile | ☐ | ☐ | ☐ | |
| Product draft, autosave, and private media | ☐ | ☐ | ☐ | |
| Submission and staff queue | ☐ | ☐ | ☐ | |
| Request changes, live notification, and resubmission | ☐ | ☐ | ☐ | |
| Approval remains private | ☐ | ☐ | ☐ | |
| Final rejection (separate test product) | ☐ | ☐ | ☐ | |

**Tester:** __________________________  **Date:** __________________________

**Follow-up items:**

1. ______________________________________________________________________
2. ______________________________________________________________________
3. ______________________________________________________________________
