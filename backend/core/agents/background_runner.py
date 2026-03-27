"""Chatty — Provider-agnostic background AI execution.

Used by reminders and scheduled actions to run AI turns in the background
without SSE streaming. Works with any configured AI provider (Anthropic,
OpenAI, Gemini).
"""

import asyncio
import json
import logging
from dataclasses import dataclass

from core.providers import get_ai_provider
from core.providers.credentials import CredentialStore
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class BackgroundResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


async def _run_turn(
    system_prompt: str,
    user_message: str,
    tool_defs: list[dict],
    registry: ToolRegistry,
    max_iterations: int = 5,
    model_override: str | None = None,
) -> BackgroundResult:
    """Run a single AI turn asynchronously, executing tools as needed."""
    store = CredentialStore()
    provider = get_ai_provider(
        agent_model=model_override,
    )
    if not provider:
        return BackgroundResult(text="No AI provider configured")

    # Convert tool defs to provider format (strip 'kind')
    provider_tools = []
    kind_map = {}
    for td in tool_defs:
        kind_map[td["name"]] = td.get("kind", "context")
        provider_tools.append({
            "name": td["name"],
            "description": td.get("description", ""),
            "input_schema": td.get("input_schema", {}),
        })

    messages = [{"role": "user", "content": user_message}]
    accumulated_text = ""

    for _ in range(max_iterations):
        tool_calls_this_turn = []
        turn_text = ""

        async for event in provider.stream_turn(messages, provider_tools, system_prompt):
            etype = event.get("type", "")

            if etype == "text":
                turn_text += event["text"]
                accumulated_text += event["text"]
            elif etype == "_turn_complete":
                tool_calls_this_turn = event.get("tool_calls", [])
                stop_reason = event.get("stop_reason", "stop")

                if stop_reason != "tool_use" or not tool_calls_this_turn:
                    return BackgroundResult(text=accumulated_text or "(no response)")

        if not tool_calls_this_turn:
            return BackgroundResult(text=accumulated_text or "(no response)")

        # Execute tools
        results = []
        for tc in tool_calls_this_turn:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            kind = kind_map.get(tool_name, "context")
            result = await registry.execute_tool(tool_name, tool_args, kind)
            results.append({
                "tool_use_id": tc.get("id", ""),
                "tool_name": tool_name,
                "content": json.dumps(result),
            })

        messages = provider.add_tool_results(messages, tool_calls_this_turn, results)

    return BackgroundResult(text=accumulated_text or "(max iterations reached)")


def run_background_turn(
    system_prompt: str,
    user_message: str,
    tool_defs: list[dict],
    registry: ToolRegistry,
    max_iterations: int = 5,
    model_override: str | None = None,
) -> BackgroundResult:
    """Synchronous wrapper for running a background AI turn.

    Creates a new event loop if needed (e.g., from APScheduler thread).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an existing event loop — run in a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                _run_turn(system_prompt, user_message, tool_defs, registry, max_iterations, model_override)
            )
            return future.result(timeout=300)
    else:
        return asyncio.run(
            _run_turn(system_prompt, user_message, tool_defs, registry, max_iterations, model_override)
        )
