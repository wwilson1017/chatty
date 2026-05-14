"""Chatty — Auto-triage classifier.

Routes messages to the appropriate model tier using:
1. Heuristic fast-path (greetings/acks -> light)
2. Provider-specific classifier (three-way top/mid/light, biased toward top)
3. Per-conversation upward-only cache
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from core.providers.credentials import CredentialStore
from core.providers.tiers import TRIAGE_CLASSIFIERS

logger = logging.getLogger(__name__)

_TRIAGE_GREETINGS = frozenset({
    "hi", "hey", "hello", "good morning", "good afternoon", "good evening",
    "morning", "afternoon", "evening", "howdy", "sup", "yo", "hiya",
    "whats up", "what's up", "greetings",
})

_TRIAGE_ACKS = frozenset({
    "thanks", "thank you", "thx", "ty", "great", "perfect", "awesome",
    "got it", "ok", "okay", "cool", "sounds good", "nice", "sweet",
})

_TIER_RANK = {"light": 0, "mid": 1, "top": 2}

_MAX_CACHE_SIZE = 500
_conversation_tier_cache: OrderedDict[str, str] = OrderedDict()

_TRIAGE_SYSTEM_PROMPT = (
    "Classify this message. Reply with ONLY one word: TOP, MID, or LIGHT.\n\n"
    "TOP — complex reasoning, analysis, planning, creative work, code generation, "
    "multi-step tasks, anything requiring deep understanding or nuance. "
    "When in doubt, choose TOP.\n"
    "MID — summarization, simple explanations, Q&A with context, formatting, translation.\n"
    "LIGHT — simple greetings, acknowledgments, yes/no questions, trivial lookups."
)

_MAX_INPUT_CHARS = 500


def _should_fast_path_light(text: str) -> bool:
    normalized = text.strip().lower().rstrip("!.?,;:")
    return normalized in _TRIAGE_GREETINGS or normalized in _TRIAGE_ACKS


def _cache_get(conversation_id: str) -> str | None:
    tier = _conversation_tier_cache.get(conversation_id)
    if tier is not None:
        _conversation_tier_cache.move_to_end(conversation_id)
    return tier


def _cache_set(conversation_id: str, tier: str) -> None:
    _conversation_tier_cache[conversation_id] = tier
    _conversation_tier_cache.move_to_end(conversation_id)
    while len(_conversation_tier_cache) > _MAX_CACHE_SIZE:
        _conversation_tier_cache.popitem(last=False)


def _max_tier(a: str, b: str) -> str:
    return a if _TIER_RANK.get(a, -1) >= _TIER_RANK.get(b, -1) else b


def _parse_tier(raw: str) -> str:
    upper = raw.strip().upper()
    if "LIGHT" in upper:
        return "light"
    if "MID" in upper:
        return "mid"
    return "top"


def extract_classifier_credentials(provider: str, store: CredentialStore) -> dict:
    """Extract the right credentials for the triage classifier, matching get_ai_provider() logic."""
    _, profile = store.get_active_profile(provider_override=provider)
    if not profile:
        return {}

    if provider == "anthropic":
        if profile.get("type") == "setup_token":
            return {"api_key": profile.get("token", "")}
        return {"api_key": profile.get("key", "")}

    elif provider == "openai":
        if profile.get("type") == "api_key":
            return {"api_key": profile.get("key", "")}
        if profile.get("type") == "chatgpt_oauth":
            return {"api_key": profile.get("access", ""), "use_chatgpt_api": True}
        return {"api_key": profile.get("access", "")}

    elif provider == "google":
        if profile.get("type") == "api_key":
            return {"api_key": profile.get("key", "")}
        return {"access_token": profile.get("access", "")}

    return {}


_CLASSIFIER_TIMEOUT = 5


async def _classify_anthropic(text: str, creds: dict) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=creds["api_key"], timeout=_CLASSIFIER_TIMEOUT)
    response = await client.messages.create(
        model=TRIAGE_CLASSIFIERS["anthropic"],
        max_tokens=5,
        system=_TRIAGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text[:_MAX_INPUT_CHARS]}],
    )
    return response.content[0].text


async def _classify_openai(text: str, creds: dict) -> str:
    import openai
    kwargs: dict = {"api_key": creds["api_key"], "timeout": _CLASSIFIER_TIMEOUT}
    if creds.get("use_chatgpt_api"):
        from core.providers.openai_provider import CHATGPT_PROXY_URL
        kwargs["base_url"] = CHATGPT_PROXY_URL
    client = openai.AsyncOpenAI(**kwargs)
    response = await client.chat.completions.create(
        model=TRIAGE_CLASSIFIERS["openai"],
        max_completion_tokens=20,
        messages=[
            {"role": "system", "content": _TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": text[:_MAX_INPUT_CHARS]},
        ],
    )
    return response.choices[0].message.content or ""


async def _classify_google(text: str, creds: dict) -> str:
    import asyncio
    import google.generativeai as genai
    if creds.get("api_key"):
        genai.configure(api_key=creds["api_key"])
    elif creds.get("access_token"):
        genai.configure(credentials=_google_oauth_creds(creds["access_token"]))
    model = genai.GenerativeModel(
        TRIAGE_CLASSIFIERS["google"],
        system_instruction=_TRIAGE_SYSTEM_PROMPT,
    )
    response = await asyncio.wait_for(
        model.generate_content_async(
            text[:_MAX_INPUT_CHARS],
            generation_config=genai.types.GenerationConfig(max_output_tokens=5),
        ),
        timeout=_CLASSIFIER_TIMEOUT,
    )
    return response.text or ""


def _google_oauth_creds(access_token: str):
    from google.oauth2.credentials import Credentials
    return Credentials(token=access_token)


_CLASSIFY_DISPATCH = {
    "anthropic": _classify_anthropic,
    "openai":    _classify_openai,
    "google":    _classify_google,
}


async def classify_tier(
    user_message: str,
    provider: str,
    credentials: dict,
    conversation_id: str | None = None,
    has_attachments: bool = False,
) -> tuple[str, str]:
    """Classify a message into a model tier.

    Returns (tier, method) where tier is "top"/"mid"/"light"
    and method is "heuristic"/"classifier"/"cached"/"skip".
    """
    if has_attachments:
        return ("top", "skip")

    # Upward-only cache check
    cached_tier = None
    if conversation_id:
        cached_tier = _cache_get(conversation_id)

    if _should_fast_path_light(user_message):
        tier = "light"
        if cached_tier:
            tier = _max_tier(cached_tier, tier)
        if conversation_id:
            _cache_set(conversation_id, tier)
        return (tier, "heuristic")

    # If cached, promote upward only
    classify_fn = _CLASSIFY_DISPATCH.get(provider)
    if not classify_fn or (not credentials.get("api_key") and not credentials.get("access_token")):
        return ("top", "skip")

    try:
        raw = await classify_fn(user_message, credentials)
        tier = _parse_tier(raw)
        if cached_tier:
            tier = _max_tier(cached_tier, tier)
        if conversation_id:
            _cache_set(conversation_id, tier)
        return (tier, "classifier")
    except Exception as e:
        logger.warning("Triage classifier failed for %s, defaulting to top: %s", provider, e)
        return ("top", "skip")
