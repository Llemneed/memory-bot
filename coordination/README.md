# Coordination Protocol

This folder is the shared control plane for two-agent work on `memory-bot`.

Default roles:
- `Claude` = planner, reviewer, strategist
- `Codex` = executor, operator, deployer

## Files

- `connect.md` - current board, locks, active tasks, handoff notes
- `handshake.json` - machine-readable state and protocol flags
- `log.jsonl` - append-only event log
- `claude_prompt.md` - ready-to-use prompt for Claude

## Workflow

1. Read `handshake.json`, `connect.md`, and the last entries from `log.jsonl`.
2. Claim exactly one task in `connect.md`.
3. Lock only the files or areas you are actually changing.
4. Do the work.
5. Write a short result into `connect.md`.
6. Append an event to `log.jsonl`.

## Safety Rules

- One owner per task.
- One writer per file area at a time.
- Read the current board before editing code.
- If the plan changes, update `connect.md` first.
- If a deploy happens, record commit, server, and result in `log.jsonl`.
- If blocked, do not guess silently; mark the block in both `connect.md` and `log.jsonl`.

## Locking Convention

Use human-readable locks in `connect.md`:

- `memory/*`
- `telegram/*`
- `llm/*`
- `database/*`
- `infra/*`
- `docs/*`

Keep locks narrow. Release them as soon as the task is done.

## Event Types

Recommended `type` values for `log.jsonl`:

- `init`
- `claim_task`
- `plan`
- `edit`
- `review`
- `deploy`
- `done`
- `blocked`
- `release_lock`

## Default Decision Split

- Claude decides what should be changed next.
- Codex performs edits, runs commands, deploys, and reports results.
- Claude reviews outcomes and sets the next task.
