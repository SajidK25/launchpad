# Review Report

## Metadata

| Field | Value |
|-------|-------|
| **Review Mode** | Pipeline: T13 task review |
| **Target** | `specs/tasks/TASKS-add-member-identity-profiles.md` — Task T13 |
| **Date** | 2026-09-24 |
| **Tech Stack** | Python 3.12, FastAPI, Strawberry GraphQL, TypeScript, Vite, OpenAPI, pytest, Docker quality checks |
| **Checks Run** | Task completion/requirements, contract generation/drift, code quality, security/config, TypeScript strictness, test coverage, runtime behavior, CI parity |
| **Checks Skipped** | React/accessibility, database/migration, performance, async patterns, documentation (no relevant T13 changes) |
| **Files Changed** | 8 T13-scoped artifacts (including generated files) |
| **Lines Changed** | Approximately +2,035 / -22 in tracked T13 artifacts; generated GraphQL files are new |

## Review Process

- [x] Preflight checks passed
- [x] Diff gathered and T13 footprint scoped
- [x] Tech stack detected: Python/FastAPI/Strawberry/TypeScript/OpenAPI/pytest/Docker
- [x] Context read (AGENTS.md, CLAUDE.md, REQ, ARCH, TASKS, and review instructions)
- [x] Triage proposed and developer confirmed
- [x] 3 checks dispatched: completion/requirements; contract/security/config; TypeScript/quality/tests
- [x] Results collected and deduplicated
- [x] Report compiled
- [x] Verdict determined
- [x] Report saved to `specs/reviews/`

## Verdict: Changes requested — not merge-ready

The T13 pipeline successfully emits REST and Strawberry SDL artifacts, activates the contract category, and passed the full quality gate and both drift drills. It does not yet satisfy the generated-client contract: GraphQL operation types are a hand-maintained heredoc, and REST `--check` trusts the checked-in OpenAPI source instead of comparing it with the running application. The generated OpenAPI also advertises a GraphQL GET/GraphiQL response that the runtime rejects.

### Finding Counts

| Category | 🔴 | 🟠 | 🟡 | 💭 | ⚠️ |
|----------|-----|-----|-----|-----|-----|
| Task completion / requirements | 0 | 1 | 0 | 0 | 0 |
| Contract generation / security / config | 0 | 0 | 1 | 0 | 0 |
| Code quality / TypeScript / test coverage | 0 | 1 | 0 | 0 | 0 |
| **Total** | **0** | **2** | **1** | **0** | **0** |

## Findings

### 🟠 High — GraphQL operation types are not generated from the schema

`scripts/quality/contracts.sh:13-70` writes all GraphQL models, operation types, and query documents from a literal shell heredoc. `packages/contracts/package.json:8` only invokes `openapi-typescript`; no GraphQL codegen tool or parser consumes `schema.graphql` plus operation documents. The drift check therefore proves that the same heredoc reproduces itself, not that `graphql.generated.ts` matches Strawberry’s schema. A schema or operation change can leave frontend types stale while the gate remains green, violating ARCH A9 and T13/N4.

**Fix:** add a pinned GraphQL codegen dependency/configuration driven by the generated SDL and checked-in operation documents, emit `graphql.generated.ts` from that source, and retain the reproducibility comparison in `contracts.sh --check`.

### 🟠 High — REST contract check does not detect stale OpenAPI artifacts

`scripts/quality/contracts.sh:73-86` saves the checked-in `openapi.json`, regenerates only `src/generated.ts` from that same file, and compares the result. It never regenerates `app.openapi()` during `--check`. A REST route/schema change can therefore leave both `openapi.json` and `src/generated.ts` stale while the contract gate passes. The recorded T13 source-drift drill only proves the GraphQL path.

**Fix:** in `--check`, generate a temporary OpenAPI document from the assembled app, compare it with the checked-in `openapi.json`, then generate and compare `src/generated.ts` from the temporary source. Add and record a REST source-drift drill.

### 🟡 Medium — OpenAPI advertises unsupported GraphQL GET behavior

The generated `packages/contracts/openapi.json` describes `GET /api/v1/graphql` as a successful GraphiQL/200 operation, while the runtime context in `apps/api/app/modules/users/routes.py` rejects all non-POST requests with 405. Consumers may follow the generated contract and issue unsupported GET requests.

**Fix:** disable GraphiQL/GET in the Strawberry router if POST-only is intended, or explicitly represent the 405 behavior and add a contract/runtime assertion before regenerating OpenAPI.

## Requirement Coverage

| Requirement | Status | Review conclusion |
|---|---|---|
| N4 | Partial | REST artifacts and strict TypeScript checks exist, but source-to-generated GraphQL and REST drift guarantees are incomplete. |

## Manual Checks Required

- [ ] Confirm the intended GraphQL client operation set and whether GET/GraphiQL should be disabled or represented as unsupported in the public contract.

## Prioritized Action Items

### Must Fix (🔴 Critical / 🟠 High)

- Replace the GraphQL heredoc with pinned schema/operation-driven code generation.
- Make REST `--check` regenerate and compare the running app’s OpenAPI source, then add the REST drift drill.

### Should Address (🟡 Medium)

- Align GraphQL GET behavior between Strawberry runtime and generated OpenAPI.

### Nice to Have (💭 Low)

- None identified.

---
*Generated by Review — 2026-09-24*
