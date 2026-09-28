# Claude Code Entry Instructions

Read and follow `AGENTS.md` before making any plan or code change.

For the current work, read these files in order:

1. `specs/requirements/REQ-*.md`
2. `specs/architecture/ARCH-*.md`
3. `specs/tasks/TASKS-*.md`
4. `docs/source/launchpad-client-brief.md` and `docs/source/engineering-guide.md` when additional product or architecture context is needed

Use the dev-pipeline workflow:

```text
/plan-requirements -> /plan-architecture -> /generate-tasks -> /implement -> /review
```

Run `/plan-qa` and `/execute-qa` after implementation when the change has a runnable UI, API, authentication, or background-job surface.

Do not implement the whole application in one request. Work on one sprint-sized vertical slice and one task at a time. Ask one focused clarification question when a product decision is missing; never silently invent product rules.

For product or UI work, also read `docs/source/inspiration.md`.
