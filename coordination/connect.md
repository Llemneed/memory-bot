# Coordination Board

## Session

- Project: `memory-bot`
- Branch: `main`
- Primary server: `176.109.107.155`
- Server user: `lemneed`
- Server repo: `~/memory-bot`
- Last known deployed commit: `0e8c10b`
- Default planner: `Claude`
- Default executor: `Codex`
- Board status: `idle`

## Current Task

- Task ID: `none`
- Owner: `none`
- Status: `idle`
- Goal: `none`
- Success check: `none`

## Active Locks

- `memory/*` - `none`
- `telegram/*` - `none`
- `llm/*` - `none`
- `database/*` - `none`
- `infra/*` - `none`
- `docs/*` - `none`

## Task Queue

| id | owner | status | scope | goal | done when |
| --- | --- | --- | --- | --- | --- |
| T-001 | none | pending | unassigned | next task not set | planner writes a concrete task |

## Handoff Notes

- Use this file before starting any code change.
- If Claude is planning, update the task row first.
- If Codex is executing, write touched scope, commit, deploy result, and next risk.
- Keep notes short and current; move history to `log.jsonl`.

## Last Outcome

- Coordination layer created.
- Repo and server should stay synchronized through normal git pull/push workflow.
- No active task is locked right now.
