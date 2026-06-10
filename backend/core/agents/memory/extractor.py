"""Automatic knowledge extraction from conversation messages.

Extracts structured facts (subject-predicate-object triples) from recent
conversation turns using the agent's configured AI provider. Runs as a
background task at each knowledge checkpoint.
"""

import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Extract structured facts from the conversation below. For each fact, provide:
- subject: the entity (person, project, company, concept)
- predicate: the relationship or property
- object: the value
- memory_type: one of (person, decision, preference, insight, reference, milestone)
- confidence: 0.0-1.0 (only extract clearly stated facts, not implications)

Rules:
- Only extract facts explicitly stated in the messages
- Skip greetings, small talk, and meta-conversation
- Prefer atomic facts (one relationship per entry)
- Use present tense for current facts, past tense for historical

Return a JSON array. If no facts to extract, return [].

Example output:
[{"subject": "John", "predicate": "works at", "object": "Acme Corp", "memory_type": "person", "confidence": 0.9}]
"""

# Rate limiting: track last extraction time per conversation
_last_extraction: dict[str, float] = {}
_MIN_INTERVAL_SECONDS = 60


async def extract_facts_from_messages(
    messages: list[dict],
    data_dir: str,
    gcs_prefix: str,
    agent_config: dict,
) -> dict:
    """Extract facts from recent messages and store them.

    Returns {extracted: int, skipped: int, error: str|None}.
    """
    # Rate limit per agent
    conv_key = data_dir
    now = time.time()
    if conv_key in _last_extraction and (now - _last_extraction[conv_key]) < _MIN_INTERVAL_SECONDS:
        return {"extracted": 0, "skipped": 0, "error": "rate_limited"}
    _last_extraction[conv_key] = now

    # Check opt-in setting
    if not agent_config.get("auto_extract_facts", True):
        return {"extracted": 0, "skipped": 0, "error": "disabled"}

    # Filter to last 4 user/assistant messages
    recent = [m for m in messages if m.get("role") in ("user", "assistant")][-4:]
    if not recent:
        return {"extracted": 0, "skipped": 0}

    # Skip trivial content
    total_chars = sum(len(m.get("content", "")) for m in recent)
    if total_chars < 50:
        return {"extracted": 0, "skipped": 0, "error": "trivial_content"}

    # Build extraction messages
    conversation_text = "\n".join(
        f"{m['role'].upper()}: {m.get('content', '')}" for m in recent
    )

    try:
        facts_json = await _call_extraction_api(conversation_text, agent_config)
        if not facts_json:
            return {"extracted": 0, "skipped": 0}

        parsed = json.loads(facts_json)
        # OpenAI json_object mode may wrap the array in a dict
        if isinstance(parsed, dict):
            # Look for a list value in the response
            facts = None
            for v in parsed.values():
                if isinstance(v, list):
                    facts = v
                    break
            if facts is None:
                return {"extracted": 0, "skipped": 0, "error": "invalid_response"}
        elif isinstance(parsed, list):
            facts = parsed
        else:
            return {"extracted": 0, "skipped": 0, "error": "invalid_response"}

        # Store facts
        from .search_tools import _get_db
        db = _get_db(data_dir, gcs_prefix)

        extracted = 0
        skipped = 0
        for fact in facts:
            if not _valid_fact(fact):
                continue

            # Dedup against active facts
            existing = db.query_facts(
                subject=fact["subject"],
                predicate=fact["predicate"],
                include_expired=False,
                limit=5,
                track_retrieval=False,
            )

            # Check for exact duplicates
            duplicate = False
            for existing_fact in existing:
                if (existing_fact["subject"].lower() == fact["subject"].lower() and
                    existing_fact["predicate"].lower() == fact["predicate"].lower()):
                    if existing_fact["object"].lower() == fact["object"].lower():
                        duplicate = True
                        break
                    else:
                        # Object changed — expire old fact
                        db.invalidate_fact(existing_fact["id"])

            if duplicate:
                skipped += 1
                continue

            db.add_fact(
                subject=fact["subject"],
                predicate=fact["predicate"],
                object_=fact["object"],
                created_by="auto_extractor",
                confidence=min(float(fact.get("confidence", 0.8)), 0.9),
                memory_type=fact.get("memory_type"),
            )
            extracted += 1

        if extracted > 0:
            try:
                db.backup_to_gcs()
            except Exception:
                pass

        return {"extracted": extracted, "skipped": skipped}

    except asyncio.TimeoutError:
        return {"extracted": 0, "skipped": 0, "error": "timeout"}
    except Exception as e:
        logger.debug("Fact extraction failed: %s", e)
        return {"extracted": 0, "skipped": 0, "error": str(e)}


async def _call_extraction_api(conversation_text: str, agent_config: dict) -> str | None:
    """Call the cheapest available model for extraction."""
    import httpx
    from core.providers.credentials import CredentialStore

    store = CredentialStore()
    active_provider = store.data.get("active_provider", "")
    profiles = store.data.get("profiles", {})

    # Skip for Ollama-only (local models too slow for background extraction)
    if active_provider == "ollama":
        return None

    timeout = httpx.Timeout(10.0)

    if active_provider == "anthropic":
        return await _extract_anthropic(conversation_text, profiles, timeout)
    elif active_provider == "openai":
        return await _extract_openai(conversation_text, profiles, timeout)
    elif active_provider == "google":
        return await _extract_google(conversation_text, profiles, timeout)

    return None


async def _extract_anthropic(text: str, profiles: dict, timeout) -> str | None:
    import httpx
    profile = profiles.get("anthropic:default", {})
    api_key = profile.get("key") or profile.get("token")
    if not api_key:
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "system": _EXTRACTION_PROMPT,
                "messages": [{"role": "user", "content": text}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0]["text"]
    return None


async def _extract_openai(text: str, profiles: dict, timeout) -> str | None:
    import httpx
    profile = profiles.get("openai:default", {})
    api_key = profile.get("key") or profile.get("access")
    if not api_key:
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": _EXTRACTION_PROMPT},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 1024,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0]["message"]["content"]
    return None


async def _extract_google(text: str, profiles: dict, timeout) -> str | None:
    import httpx
    from core.providers.oauth import refresh_google_token

    profile = profiles.get("google:default", {})
    if not profile.get("refresh"):
        return None
    token_data = await refresh_google_token(profile["refresh"])
    access_token = token_data.get("access_token") if token_data else None
    if not access_token:
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "system_instruction": {"parts": [{"text": _EXTRACTION_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": text}]}],
                "generationConfig": {"maxOutputTokens": 1024},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "")
    return None


def _valid_fact(fact: dict) -> bool:
    """Validate a fact dict has required fields."""
    return bool(
        isinstance(fact, dict)
        and fact.get("subject", "").strip()
        and fact.get("predicate", "").strip()
        and fact.get("object", "").strip()
    )
