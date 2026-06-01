# Coach Lessons

> Instincts extracted from development sessions. Scores reflect real-world effectiveness.
> Format: `[score]` **When** trigger → **do** action → **because** reason

## Deploy & Infrastructure

- `[0.70]` **When** running the backend from a git worktree → **do** use the absolute venv path (`/Users/willwilson/ai/chatty/.venv/bin/python`), not relative (`../../.venv/bin/python`) → **because** worktrees live under `.claude/worktrees/<name>/backend/` and the relative path resolves to a nonexistent location
