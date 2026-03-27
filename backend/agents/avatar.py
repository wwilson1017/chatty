"""
Chatty — Avatar generation via DALL-E 3.

Generates character avatar options from the agent's personality/identity
context files, downloads the chosen image, and stores it locally + GCS.
Requires an OpenAI OAuth token (from the credential store).
"""

import asyncio
import logging
from pathlib import Path

import httpx
from openai import (
    APIConnectionError,
    AsyncOpenAI,
    APIError,
    APITimeoutError,
    BadRequestError,
    RateLimitError,
)

from core.storage import upload_file

logger = logging.getLogger(__name__)


def _build_dalle_prompt(identity: str, soul: str, agent_name: str) -> str:
    """Construct a DALL-E prompt from the agent's personality context."""
    personality_hints = ""
    if soul:
        personality_hints = soul[:300]
    if identity:
        personality_hints += "\n" + identity[:200]

    return (
        f"A friendly, professional AI assistant character portrait named {agent_name}. "
        f"Digital art style, warm and approachable, suitable as a chat avatar. "
        f"Clean circular composition, soft gradient background. "
        f"The character should feel unique and personable. "
        f"Personality cues: {personality_hints[:200]}. "
        f"Style: modern digital illustration, no text, no logos."
    )


def _backoff_delay(attempt: int, retry_after: str | None = None) -> float:
    """Calculate backoff delay, respecting Retry-After header if present."""
    if retry_after:
        try:
            return min(float(retry_after), 30.0)
        except ValueError:
            pass
    return 2 ** (attempt + 1)


async def _generate_single_avatar(
    client: AsyncOpenAI,
    prompt: str,
    index: int,
    max_retries: int = 1,
) -> str | None:
    """Generate a single avatar image with retry logic. Returns URL or None."""
    for attempt in range(max_retries + 1):
        try:
            response = await client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size="1024x1024",
                quality="standard",
            )
            url = response.data[0].url
            logger.info("Avatar gen [%d] succeeded on attempt %d", index, attempt + 1)
            return url
        except BadRequestError as e:
            logger.error(
                "Avatar gen [%d] prompt rejected (HTTP %d): %s",
                index, e.status_code, e.message,
            )
            return None
        except RateLimitError as e:
            if attempt < max_retries:
                retry_after = (
                    e.response.headers.get("retry-after")
                    if e.response else None
                )
                delay = _backoff_delay(attempt, retry_after=retry_after)
                logger.warning(
                    "Avatar gen [%d] rate limited, retrying in %.1fs", index, delay,
                )
                await asyncio.sleep(delay)
                continue
            logger.error("Avatar gen [%d] rate limit exhausted", index)
            return None
        except APITimeoutError:
            if attempt < max_retries:
                logger.warning("Avatar gen [%d] timed out, retrying", index)
                continue
            logger.error("Avatar gen [%d] timed out after %d attempts", index, max_retries + 1)
            return None
        except APIConnectionError as e:
            if attempt < max_retries:
                delay = _backoff_delay(attempt)
                logger.warning(
                    "Avatar gen [%d] connection error, retrying in %.1fs: %s",
                    index, delay, e,
                )
                await asyncio.sleep(delay)
                continue
            logger.error("Avatar gen [%d] connection error after retries: %s", index, e)
            return None
        except APIError as e:
            status = getattr(e, "status_code", None) or 0
            if status >= 500 and attempt < max_retries:
                delay = _backoff_delay(attempt)
                logger.warning(
                    "Avatar gen [%d] server error %d, retrying in %.1fs",
                    index, status, delay,
                )
                await asyncio.sleep(delay)
                continue
            logger.error("Avatar gen [%d] API error %d: %s", index, status, e.message)
            return None
    return None


async def generate_avatar_options(
    identity_md: str,
    soul_md: str,
    agent_name: str,
    openai_token: str,
    count: int = 3,
) -> list[str]:
    """Generate avatar image options using DALL-E 3.

    Returns a list of temporary URLs that expire after ~1 hour.
    """
    if not openai_token:
        raise ValueError("OpenAI not connected")

    prompt = _build_dalle_prompt(identity_md, soul_md, agent_name)
    client = AsyncOpenAI(api_key=openai_token, timeout=30.0, max_retries=0)

    async def _staggered_call(index: int) -> str | None:
        if index > 0:
            await asyncio.sleep(index * 0.5)
        return await _generate_single_avatar(client, prompt, index)

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[_staggered_call(i) for i in range(count)]),
            timeout=100.0,
        )
    except asyncio.TimeoutError:
        logger.error("Avatar generation hit 100s global timeout")
        raise RuntimeError("Avatar generation timed out — please retry")

    urls = [url for url in results if url is not None]
    if not urls:
        raise RuntimeError(
            f"All {count} avatar generation attempts failed — check server logs"
        )

    logger.info("Avatar generation: %d/%d succeeded", len(urls), count)
    return urls


async def download_and_save_avatar(
    url: str,
    data_dir: Path,
    gcs_prefix: str,
) -> str:
    """Download an avatar image and save it locally + to GCS."""
    data_dir.mkdir(parents=True, exist_ok=True)
    avatar_path = data_dir / "avatar.png"

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        avatar_path.write_bytes(resp.content)

    upload_file(avatar_path, gcs_prefix + "avatar.png")

    logger.info("Avatar saved to %s and synced to GCS", avatar_path)
    return str(avatar_path)
