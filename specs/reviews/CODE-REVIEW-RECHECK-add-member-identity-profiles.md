# Re-review Report

**Original report:** `CODE-REVIEW-PIPELINE-add-member-identity-profiles.md`  
**Date:** 2026-09-25  
**Findings addressed:** 8 of 8

| # | Original finding | Status | Verification |
|---|---|---|---|
| 1 | Password-reset email linked to nonexistent `/reset-password` route | ✅ Resolved | Service now emits `/reset?token=...`; integration coverage asserts the email path and browser identity checks pass. |
| 2 | Secure-cookie documentation conflicted with local Compose/browser URL | ✅ Resolved | README/development guide now document the supported `http://localhost:8080` loopback Secure-cookie behavior and HTTPS requirement outside localhost. |
| 3 | GraphQL was incorrectly documented as not applicable | ✅ Resolved | Development guide and ADR 0004 document GraphQL contract generation; only WebSocket is not applicable. |
| 4 | T17 evidence was prose-only | ✅ Resolved | Added `specs/qa/QA-RESULTS-T17-add-member-identity-profiles.md` with commands, outcomes, isolation, and drill evidence. |
| 5 | Storage provider exceptions could escape bootstrap unsafely | ✅ Resolved | Provisioning now normalizes provider/admin exceptions to `StorageProvisioningError` without leaking provider details. Existing storage and full Python tests pass. |
| 6 | Profile-link DB constraint was weaker than the URL policy | ✅ Resolved | Added forward migrations `0003_profile_link_hardening` and `0004_profile_link_query`; ORM constraint matches HTTPS host/path/query policy without credentials/fragments/whitespace. Migration and identity regressions pass (17 tests). |
| 7 | Profile errors/notices lacked action associations | ✅ Resolved | Save, publish, and unpublish controls now reference the live error message with `aria-describedby`; field associations remain intact. Web tests and lint pass. |
| 8 | Frontend clients trusted generated-type casts without shape validation | ✅ Resolved | Identity, REST profile, upload, completion, and GraphQL boundaries now validate required response shapes before hooks consume them. Web tests and strict TypeScript pass. |

## Verification

- Full isolated gate passed after the primary fixes: 132 Python/integration tests, 37 web tests, format/lint/types, migrations, contracts, builds, security scans, and 2 browser tests.
- After the final forward migration adjustment, targeted migration and identity regressions passed: 17 tests.
- `git diff --check` passed.

## Updated Verdict: ✅ PASS
