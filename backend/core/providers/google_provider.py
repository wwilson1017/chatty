"""
Chatty — Google Gemini provider.

Streaming via google.generativeai with function calling.
Uses the user's OAuth access token (same token covers Gemini + Gmail + Calendar).
"""

import json
import logging
from typing import AsyncGenerator

from core.providers.base import AIProvider

logger = logging.getLogger(__name__)

GOOGLE_MODELS = [
    "gemini-2.0-flash-exp",
    "gemini-2.0-pro-exp",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]


class GoogleProvider(AIProvider):
    def __init__(self, access_token: str = "", api_key: str = "", model: str = "gemini-2.0-flash-exp"):
        super().__init__(model=model)
        self.access_token = access_token
        self.api_key = api_key

    @property
    def provider_name(self) -> str:
        return "google"

    def _format_tools(self, tools: list[dict]) -> list:
        """Convert internal tool format to Gemini function declarations."""
        try:
            import google.generativeai as genai
            from google.generativeai.types import FunctionDeclaration, Tool
        except ImportError:
            return []

        declarations = []
        for t in tools:
            schema = t.get("input_schema", {})
            declarations.append(FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=schema,
            ))

        if declarations:
            return [Tool(function_declarations=declarations)]
        return []

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncGenerator[dict, None]:
        try:
            import google.generativeai as genai
            from google.oauth2.credentials import Credentials
        except ImportError:
            yield {"type": "error", "error": "google-generativeai package not installed"}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return

        # Configure with API key or OAuth token
        if self.api_key:
            genai.configure(api_key=self.api_key)
        else:
            credentials = Credentials(token=self.access_token)
            genai.configure(credentials=credentials)

        gemini_tools = self._format_tools(tools)

        # Build Gemini history (all but last user message)
        history = []
        for m in messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            content = m.get("content", "")
            if isinstance(content, str) and content:
                history.append({"role": role, "parts": [content]})

        model_kwargs = {
            "model_name": self.model,
            "system_instruction": system_prompt,
        }
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools

        model = genai.GenerativeModel(**model_kwargs)
        chat = model.start_chat(history=history)

        # Last user message
        last_msg = messages[-1].get("content", "") if messages else ""

        full_text = ""
        tool_calls = []

        try:
            response = await chat.send_message_async(last_msg, stream=True)

            async for chunk in response:
                # Text chunks
                if hasattr(chunk, "text") and chunk.text:
                    full_text += chunk.text
                    yield {"type": "text", "text": chunk.text}

                # Function calls
                if chunk.candidates:
                    for candidate in chunk.candidates:
                        if not candidate.content.parts:
                            continue
                        for part in candidate.content.parts:
                            if hasattr(part, "function_call") and part.function_call:
                                fc = part.function_call
                                call_id = f"call_{len(tool_calls)}"
                                args = dict(fc.args) if fc.args else {}
                                tool_calls.append({
                                    "id": call_id,
                                    "name": fc.name,
                                    "args": args,
                                    "input_json": json.dumps(args),
                                })
                                yield {"type": "tool_start", "tool": fc.name, "tool_use_id": call_id}
                                yield {"type": "tool_args", "tool": fc.name, "tool_use_id": call_id, "args": args}

            stop_reason = "tool_use" if tool_calls else "stop"

        except Exception as e:
            logger.error("Gemini API error: %s", e)
            yield {"type": "error", "error": f"AI service error: {str(e)}"}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return

        yield {
            "type": "_turn_complete",
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
        }

    def add_tool_results(
        self,
        messages: list[dict],
        tool_calls: list[dict],
        results: list[dict],
    ) -> list[dict]:
        """Append function call + function response to messages."""
        # For Gemini we store these as special message entries that get
        # converted to Parts in the next stream_turn() call.
        # We use a simplified approach: store as tool_result role entries.
        tool_result_msgs = []
        for r in results:
            tool_result_msgs.append({
                "role": "tool",
                "tool_use_id": r["tool_use_id"],
                "tool_name": r.get("tool_name", ""),
                "content": str(r["content"]),
            })
        return messages + tool_result_msgs

    async def list_models(self) -> list[str]:
        return GOOGLE_MODELS

    async def validate(self) -> bool:
        try:
            import google.generativeai as genai
            if self.api_key:
                genai.configure(api_key=self.api_key)
            else:
                from google.oauth2.credentials import Credentials
                credentials = Credentials(token=self.access_token)
                genai.configure(credentials=credentials)
            list(genai.list_models())
            return True
        except Exception:
            return False
