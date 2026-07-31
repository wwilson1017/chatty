# Handoff — Together AI "Invalid API key" on Railway

## Branch
`claude/together-ai-chatty-railway-htc5n1` (2 commits ahead of `master` as of this handoff, not yet merged: `8ceefcc`, `e213db4`)

## The problem
Connecting a Together AI API key on the Railway-deployed instance
(`chatty-tom.up.railway.app`) fails with:

```
API error 400: Invalid Together AI API key
```

**The key is not the problem.** Confirmed by hitting Together's API directly
from outside Chatty:

```bash
curl -i https://api.together.xyz/v1/models -H "Authorization: Bearer <key>"
# -> HTTP/2 200, full JSON model list
```

So the deployed backend is failing before/instead of getting a real answer
from Together, and the error message was masking whatever that real failure
is.

⚠️ The key used in that curl test (`tgp_v1_sH2P...PgsPSnWs`) was pasted into
chat and is considered burned — **revoke it in the Together dashboard and
generate a fresh one** before further testing.

## What's already fixed on this branch

1. **`8ceefcc`** (PR #135, merged to master) — the *original* bug:
   `TogetherProvider.validate()` used to probe a chat completion against a
   hardcoded model (`Qwen/Qwen3.5-7B`) that Together had deprecated. Any
   failure of that probe — not just a bad key — got relabeled "Invalid
   Together AI API key". Fixed by validating with a model-agnostic
   `client.models.list()` call instead (same pattern already used for
   OpenAI). Also refreshed `TOGETHER_MODELS`/`TOGETHER_DEFAULT_MODEL`, the
   `tiers.py` fallback, and added Together pricing entries.
   - Confirmed this fix IS live on the deployed Railway instance (deployment
     screenshot showed the merge commit deployed successfully).
   - **But the 400 persisted after this fix** — proving the root cause is
     something else, since a plain `models.list()` call still fails in the
     deployed environment even though it succeeds from outside.

2. **`e213db4`** (PR #136, open, not yet merged) — diagnostic follow-up:
   `validate()` now stores the real exception as `self.last_error`, and
   `/api/providers/together/connect` includes it in the 400 response detail
   instead of the generic "Invalid Together AI API key" string. **This has
   not been tested yet** — need to merge, redeploy, and retry connecting to
   see what the actual error text says.

## Next steps (why moving local)

Faster iteration loop than merge → wait for Railway rebuild → retest each
time. Locally:

1. `git fetch origin claude/together-ai-chatty-railway-htc5n1 && git checkout claude/together-ai-chatty-railway-htc5n1`
2. Run the backend per `CLAUDE.md` (`cd backend && ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload`) — or just `python run.py` from repo root.
3. Generate a **fresh** Together API key (the old one is burned — see above).
4. Try connecting it via Settings → Providers → Together AI, or directly:
   ```bash
   curl -X POST http://127.0.0.1:8000/api/providers/together/connect \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <your chatty JWT>" \
     -d '{"api_key": "<fresh together key>"}'
   ```
5. With PR #136's change in place, the error detail (if it still fails)
   should now say `Together AI rejected the key: <real exception text>`
   instead of the generic message — that tells us what's actually breaking.
6. **If it works locally but fails on Railway**: points to something
   Railway-environment-specific — check:
   - Railway's 6 project env vars (seen in the deploy screenshot) for any
     `HTTP_PROXY`/`HTTPS_PROXY`/custom CA var that could intercept or break
     outbound HTTPS to `api.together.xyz` specifically (other providers
     apparently work fine, so this would have to be Together-domain-specific
     — e.g. an egress allowlist).
   - Outbound network policy / firewall rules on the Railway project.
   - Whether the container's `openai` package version resolves differently
     than local (check `requirements.txt` pin vs what's actually installed
     in the Railway build).
7. **If it fails identically locally**: the bug is in Chatty's code path,
   not Railway's environment — the detailed error from step 5 should point
   directly at it (auth header format, httpx/openai client config, etc.).

## Files touched so far
- `backend/core/providers/together_provider.py`
- `backend/core/providers/router.py`
- `backend/core/providers/tiers.py`
- `backend/core/providers/pricing.py`
- `backend/core/providers/PRICING.md`
- `backend/core/providers/credentials.py`
- `backend/core/providers/__init__.py`

## Open PRs
- #135 — merged
- #136 — open, needs merge + redeploy (or just pull locally, it's already on this branch)
