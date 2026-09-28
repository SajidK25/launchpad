# T14 Review Recheck — Member Identity Profiles

## Verdict

Changes requested findings are addressed; the T14 web client slice is ready for merge review.

## Findings resolved

- Login now removes all profile/photo caches before installing the new session.
- Logout/reset clear protected caches only on success; failures retain and invalidate session state.
- Revoked (401) session responses remove session and profile caches.
- Registration, verification-request, and password-reset-request mutations now have hooks.
- Photo upload creation, completion, and photo retrieval now have TanStack Query seams.
- Profile/privacy mutations reconcile viewer/public/photo caches only after success.
- REST and GraphQL clients normalize malformed/non-JSON responses to typed request errors.
- Client response boundaries reject primitive/malformed JSON instead of forwarding unchecked values.
- Regression tests cover account switching, verification/reset invalidation, revocation, privacy cache removal, upload failure, and malformed GraphQL responses.

## Verification evidence

- Focused T14 tests: **13 passed** across identity and profile clients/hooks.
- Web TypeScript strict check: **passed** (`npm run typecheck --workspace=@launchpad/web`).
- Web lint: **passed** (`npm run lint --workspace=@launchpad/web`).
