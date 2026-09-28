# Re-review Report

**Original report:** `CODE-REVIEW-PIPELINE-add-member-identity-profiles-T16.md`
**Date:** 2026-09-24

## Findings addressed

| # | Original finding | Status | Notes |
|---|---|---|---|
| 1 | Conditional `useConnectivity` hook order | ✅ Resolved | `App` now calls `useConnectivity` unconditionally before route branching, keeping hook order stable across SPA navigation. |
| 2 | Text-only saves cleared existing photos | ✅ Resolved | `photo_upload_id` is omitted unless a replacement upload is explicitly staged; regression coverage inspects the outgoing PATCH body. |
| 3 | Required display name blocked incomplete drafts/auto-private edits | ✅ Resolved | Client-side `required` was removed from the draft editor; publication remains server-authoritative and required-field removal is covered. |
| 4 | T16 checklist/evidence was incomplete | ✅ Resolved | Checklist is now checked with evidence for editor gating, privacy notices, upload safety, public withdrawal, responsive/keyboard paths, and connectivity regression. |
| 5 | Browser evidence omitted owner/privacy lifecycle | ✅ Resolved | Added profile/privacy browser assertions and expanded component lifecycle coverage for auto-private, photo retention, unsupported uploads, and staged URL exclusion. |
| 6 | Profile messages lacked control associations | ✅ Resolved | Profile inputs now expose `aria-describedby` and `aria-invalid` tied to the stable profile error region. |
| 7 | Owner/private and staged-photo safety weakly evidenced | ✅ Resolved | Added text-only photo-preservation and staged-URL DOM-exclusion tests; unsupported-photo recovery remains covered. |

## Verification

- Web tests: **37 passed**
- TypeScript strict check: **passed**
- ESLint: **passed**
- Production web build: **passed**
- Browser regression: **2 passed** (identity/profile privacy routing and connectivity)
- T16 checklist: **all seven items checked with evidence**

## Updated Verdict: ✅ PASS

The critical hook-order defect and privacy/photo state bugs are fixed, and the T16 UI now has regression coverage for the reviewed state transitions and staging boundary. The independent QA gate remains available for broader authenticated end-to-end exploration.
