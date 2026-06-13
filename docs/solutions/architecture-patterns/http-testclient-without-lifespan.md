---
title: HTTP test tier with FastAPI TestClient — running without lifespan and isolating module-level data paths
date: 2026-06-12
category: architecture-patterns
module: backend/tests/conftest.py, backend/main.py, backend/agents/router.py
tags: [testing, fastapi, testclient, fixtures, monkeypatch, isolation, sse, auth]
problem_type: pattern
---

## Context

Chatty's backend had 505 service-level tests but zero coverage of the HTTP layer
(route handlers, auth dependencies, request/response shapes, SSE streaming). We
needed an HTTP test tier as a safety net before a refactor that merges the three
hand-rolled tool-execution loops into one `AgentTurnRunner`. The constraints:
purely additive, no behavior changes, suite stays fast (<10s, no network), and —
critically — tests must never read or destroy real developer data under
`backend/data/`.

`main.py` builds `app` at import time with all routers mounted, but **all**
filesystem/DB/scheduler initialization lives in the `lifespan` function (data-dir
mkdirs, APScheduler, every DB `init_db`). The whole approach hinges on one fact:
`TestClient(main.app)` used **without** a `with` block never runs lifespan, so
tests get the full route table with no schedulers and no startup disk writes.

## Guidance

### 1. Verify the app is import-side-effect-free, then skip lifespan

```python
from fastapi.testclient import TestClient
import main
client = TestClient(main.app)   # NO `with` block → lifespan never runs
```

Pin this invariant with a sentinel test: the health endpoint reads
`getattr(request.app.state, "db_statuses", {})`, and `app.state.db_statuses` is
only set inside lifespan. So `GET /api/health` returning `databases == {}` proves
lifespan never ran. Make the fixture self-defending against any future test that
*does* run lifespan on the shared module-level `app`:
`monkeypatch.delattr(main.app.state, "db_statuses", raising=False)`.

### 2. Sweep for module-level path constants — including import-time captures

The non-obvious hazard: patching a `DATA_DIR` in its source module does **not**
patch copies other modules captured at import time via `from x import DATA_DIR`,
nor constants *derived* from it (`SHARED_DATA_DIR = db.DATA_DIR`). In this codebase
five such hazards existed beyond the obvious ones; one (`agents.router.DATA_DIR`,
a captured copy used by delete-agent's `shutil.rmtree(DATA_DIR / slug)`) would have
**rmtree'd the real agents directory** from a delete test. A shared `http_env`
fixture patches every one to `tmp_path`:

```python
import agents.router as router_mod              # captured copy of engine.DATA_DIR
import integrations.registry as registry_mod    # mkdirs on access
import integrations.pending_setup as pending_mod # create-agent reads AND deletes it
import core.providers.credentials as creds_mod   # chat route reads real auth-profiles
import core.admin_settings as admin_mod          # mtime-cached settings
import core.agents.shared_context.service as shared_service  # SHARED_DATA_DIR = db.DATA_DIR
import core.agents.reminders.db as reminders_db  # activity log; get_db() raises if uninit
import branding.storage as branding_storage      # public /logo route serves real file
# ... monkeypatch.setattr each to tmp_path subdirs
```

Reminders is special: chat completion logging calls `reminders.db.get_db()`, which
**raises `RuntimeError` when uninitialized** (and the surrounding catch is
`(ImportError, OSError)` only), so without lifespan every chat test dies mid-stream.
The fixture must `_setup_connection()` a tmp reminders DB.

### 3. Reset LRU/instance caches in setup AND teardown

`agents.engine._get_initialized_db` / `_get_initialized_memory_db` are
`@lru_cache` keyed by slug; `core.agents.memory.db._instances` is a module dict with
no `close()` API. Clear them at setup (so a same-named agent in a later test doesn't
get a previous test's DB) and close+clear at teardown (so tmp-dir SQLite handles
don't leak). Order matters: tear down `http_env` before `agent_db` so
`close_all_agent_dbs()` runs against a still-live registry connection.

### 4. Auth: override the dependency, not the token

```python
main.app.dependency_overrides[get_current_user] = lambda: {"sub": "user", "role": "admin"}
# teardown: pop ONLY our key — app is a module-global shared across tests
main.app.dependency_overrides.pop(get_current_user, None)
```

A patch-free `anon_client` (same `http_env`, no override) drives 401 tests.

### 5. Parametrized 401 sweep — strict 401, documented allowlist

Walk `main.app.routes`, keep only `APIRoute` (skips static `Mount`), substitute
`{param}` with `"x"`, assert **strictly 401**. FastAPI resolves dependencies (where
`get_current_user` raises) before body/path-param validation, so no body and dummy
params still yield 401 — never a masking 422. Allowlist the intentionally tokenless
routes with a code comment each (login, health, OAuth callback, secret-header
webhooks). Add a separate test that no `Mount` sub-app lives under `/api` (the
sweep can't see inside mounted sub-apps), and for each allowlisted webhook add a
test that its alternate auth rejects a missing/wrong secret — otherwise the
allowlist hides a "route went fully open" regression.

### 6. SSE chat over TestClient

`client.post(...)` buffers the finite mock stream into `.text`; parse `data: {json}`
lines (strip before `json.loads` so a stray `\r` can't silently drop an event).
Drive the engine with the existing `MockAIProvider` (`set_responses([turn_events])`).
For the approved-tool resume path, send the frontend's literal `[Approved] <tool>`
user message and record what reaches the provider — the engine strips that
placeholder and reconstructs `tool_use`/`tool_result` blocks; a generic message
silently bypasses the strip branch and the test passes while production leaks the
placeholder.

## Why This Matters

The pattern gives fast, hermetic HTTP coverage (≈237 tests in ~2s) with zero real
disk side effects — verified by `git status` showing nothing changed under
`backend/data/` after a full run. The isolation sweep is the load-bearing part:
without it, ordinary-looking CRUD tests read live credentials, leak dev
integrations into the tool set, and can delete real agent data.

## When to Apply

Any FastAPI app where (a) `app` is built at import time but startup work lives in
`lifespan`, and (b) routes touch module-level path/DB constants. Before writing the
fixtures, grep the routes-under-test for every `DATA_DIR` / `*_PATH` / `*_FILE`
constant they reach — directly and via import-time captures — and patch all of
them. The auth sweep and the webhook-secret tests are cheap and catch an entire
class of future "forgot the `Depends`" / "left the webhook open" bugs.
