"""Chatty — Provider-agnostic background AI execution.

Used by reminders and scheduled actions to run AI turns in the background
without SSE streaming. Works with any configured AI provider (Anthropic,
OpenAI, Gemini).
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from core.providers import get_ai_provider
from core.providers.credentials import CredentialStore
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class BackgroundResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_log: list[dict] = field(default_factory=list)
    model_used: str = ""
    error: bool = False


async def _run_turn(
    system_prompt: "str | tuple[str, str]",
    user_message: str,
    tool_defs: list[dict],
    registry: ToolRegistry,
    max_iterations: int = 5,
    model_override: str | None = None,
    provider_override: str | None = None,
    on_iteration: Callable[[int], bool] | None = None,
) -> BackgroundResult:
    """Run a single AI turn asynchronously, executing tools as needed."""
    store = CredentialStore()
    provider = get_ai_provider(
        agent_provider=provider_override,
        agent_model=model_override,
    )
    if not provider:
        return BackgroundResult(text="No AI provider configured", error=True)

    model_used = getattr(provider, "model", "") or ""

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
    tool_log: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for iteration in range(max_iterations):
        if on_iteration is not None and iteration > 0:
            if not on_iteration(iteration):
                return BackgroundResult(
                    text="(lease lost -- aborted)",
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    model_used=model_used,
                    tool_log=tool_log,
                    error=True,
                )

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

                usage = event.get("usage", {})
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)

                if stop_reason == "error":
                    return BackgroundResult(
                        text=accumulated_text or "(provider error)",
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        model_used=model_used,
                        tool_log=tool_log,
                        error=True,
                    )

                if stop_reason != "tool_use" or not tool_calls_this_turn:
                    return BackgroundResult(
                        text=accumulated_text or "(no response)",
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        model_used=model_used,
                        tool_log=tool_log,
                        error=not accumulated_text,
                    )

        if not tool_calls_this_turn:
            return BackgroundResult(
                text=accumulated_text or "(no response)",
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                model_used=model_used,
                tool_log=tool_log,
                error=not accumulated_text,
            )

        # Execute tools
        results = []
        for tc in tool_calls_this_turn:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            kind = kind_map.get(tool_name, "context")

            t0 = time.monotonic()
            result = await registry.execute_tool(tool_name, tool_args, kind)
            duration_ms = int((time.monotonic() - t0) * 1000)

            result_str = json.dumps(result)
            tool_log.append({
                "tool": tool_name,
                "args": json.dumps(tool_args)[:200],
                "result": result_str[:500],
                "duration_ms": duration_ms,
            })

            results.append({
                "tool_use_id": tc.get("id", ""),
                "tool_name": tool_name,
                "content": result_str,
            })

        messages = provider.add_tool_results(messages, tool_calls_this_turn, results)

    return BackgroundResult(
        text=accumulated_text or "(max iterations reached)",
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        model_used=model_used,
        tool_log=tool_log,
        error=True,
    )


def run_background_turn(
    system_prompt: "str | tuple[str, str]",
    user_message: str,
    tool_defs: list[dict],
    registry: ToolRegistry,
    max_iterations: int = 5,
    model_override: str | None = None,
    provider_override: str | None = None,
    on_iteration: Callable[[int], bool] | None = None,
    source: str | None = None,
) -> BackgroundResult:
    """Synchronous wrapper for running a background AI turn.

    Creates a new event loop if needed (e.g., from APScheduler thread).
    When ``source`` is provided (e.g. "whatsapp"), logs a chat event
    after execution. Scheduled actions pass source=None since they
    already log via history.py.
    """
    t0 = time.time()

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    _run_turn(system_prompt, user_message, tool_defs, registry,
                              max_iterations, model_override, provider_override,
                              on_iteration)
                )
                result = future.result(timeout=300)
        else:
            result = asyncio.run(
                _run_turn(system_prompt, user_message, tool_defs, registry,
                          max_iterations, model_override, provider_override,
                          on_iteration)
            )
    except Exception as exc:
        if source:
            try:
                from core.agents.activity_log import log_chat_event
                log_chat_event(
                    agent=getattr(registry, "agent_slug", "unknown"),
                    source=source,
                    status="error",
                    result_summary=str(exc)[:500],
                    duration_ms=int((time.time() - t0) * 1000),
                )
            except Exception:
                logger.warning("Activity log write failed", exc_info=True)
        raise

    if source:
        try:
            from core.agents.activity_log import log_chat_event
            log_chat_event(
                agent=getattr(registry, "agent_slug", "unknown"),
                source=source,
                status="error" if result.error else "ok",
                result_summary=result.text[:500],
                tool_calls=result.tool_log or None,
                model_used=result.model_used,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                duration_ms=int((time.time() - t0) * 1000),
            )
        except Exception:
            logger.warning("Activity log write failed", exc_info=True)

    return result
