# Coach Lessons

> Instincts extracted from development sessions. Scores reflect real-world effectiveness.
> Format: `[score]` **When** trigger → **do** action → **because** reason

## Code & Architecture

- `[0.70]` **When** extracting a shared function from a module that others import → **do** keep a re-export in the original module and update all internal callers to the new location → **because** external callers (tests, plugins) may import from the old path; re-export prevents silent breakage while the new canonical path is established
- `[0.70]` **When** replacing `getattr(obj, "attr", fallback)` with an explicit parameter → **do** verify every call site passes the parameter, or keep the `getattr` fallback at the entry point → **because** the `_slug` UnboundLocalError was introduced by removing `getattr` in the outer function without ensuring callers pass the new arg

## Deploy & Infrastructure

- `[0.70]` **When** running the backend from a git worktree → **do** use the absolute venv path (`/Users/willwilson/ai/chatty/.venv/bin/python`), not relative (`../../.venv/bin/python`) → **because** worktrees live under `.claude/worktrees/<name>/backend/` and the relative path resolves to a nonexistent location
