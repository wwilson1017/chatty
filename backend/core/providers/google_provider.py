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

# Fields not supported by Gemini's Schema protobuf
_UNSUPPORTED_SCHEMA_FIELDS = {"default", "examples", "additionalProperties"}


def _clean_schema(schema: dict) -> dict:
    """Recursively strip fields that Gemini's FunctionDeclaration doesn't support."""
    if not isinstance(schema, dict):
        return schema
    result = {k: v for k, v in schema.items() if k not in _UNSUPPORTED_SCHEMA_FIELDS}
    if "properties" in result:
        result["properties"] = {
            k: _clean_schema(v) for k, v in result["properties"].items()
        }
    if "items" in result and isinstance(result["items"], dict):
        result["items"] = _clean_schema(result["items"])
    return result

GOOGLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]


class GoogleProvider(AIProvider):
    def __init__(self, access_token: str = "", api_key: str = "", model: str = "gemini-2.0-flash"):
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
            schema = _clean_schema(t.get("input_schema", {}))
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
        system_prompt: "str | tuple[str, str]",
    ) -> AsyncGenerator[dict, None]:
        if isinstance(system_prompt, tuple):
            system_prompt = "\n".join(system_prompt)
        try:
            import google.generativeai as genai
            from google.generativeai import protos
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
            role = m.get("role", "user")
            content = m.get("content", "")

            if isinstance(content, list):
                # Structured parts: function calls or function responses
                parts = []
                for part_data in content:
                    if not isinstance(part_data, dict):
                        continue
                    if part_data.get("_type") == "function_call":
                        parts.append(protos.Part(
                            function_call=protos.FunctionCall(
                                name=part_data["name"],
                                args=part_data.get("args", {}),
                            )
                        ))
                    elif part_data.get("_type") == "function_response":
                        parts.append(protos.Part(
                            function_response=protos.FunctionResponse(
                                name=part_data["name"],
                                response=part_data.get("response", {}),
                            )
                        ))
                if parts:
                    gemini_role = "model" if role == "assistant" else "user"
                    history.append(protos.Content(role=gemini_role, parts=parts))
            elif isinstance(content, str) and content:
                gemini_role = "model" if role != "user" else "user"
                history.append(protos.Content(
                    role=gemini_role,
                    parts=[protos.Part(text=content)],
                ))

        model_kwargs = {
            "model_name": self.model,
            "system_instruction": system_prompt,
        }
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools

        model = genai.GenerativeModel(**model_kwargs)
        chat = model.start_chat(history=history)

        # Last user message — may be plain text or structured function responses
        last_content = messages[-1].get("content", "") if messages else ""
        if isinstance(last_content, list):
            # Structured parts (function responses after tool execution)
            parts = []
            for part_data in last_content:
                if isinstance(part_data, dict) and part_data.get("_type") == "function_response":
                    parts.append(protos.Part(
                        function_response=protos.FunctionResponse(
                            name=part_data["name"],
                            response=part_data.get("response", {}),
                        )
                    ))
            send_msg = protos.Content(role="user", parts=parts) if parts else ""
        else:
            send_msg = last_content

        full_text = ""
        tool_calls = []

        try:
            response = await chat.send_message_async(send_msg, stream=True)

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
        """Append model function calls + user function responses to messages.

        Gemini requires the conversation history to contain:
        1. A model message with FunctionCall parts
        2. A user message with FunctionResponse parts
        These are stored as structured dicts and converted to protos in stream_turn().
        """
        # Model's function calls
        fc_parts = []
        for tc in tool_calls:
            fc_parts.append({
                "_type": "function_call",
                "name": tc["name"],
                "args": tc.get("args", {}),
            })
        assistant_msg = {"role": "assistant", "content": fc_parts}

        # User's function responses
        fr_parts = []
        for r in results:
            fr_parts.append({
                "_type": "function_response",
                "name": r.get("tool_name", ""),
                "response": {"result": str(r["content"])},
            })
        user_msg = {"role": "user", "content": fr_parts}

        return messages + [assistant_msg, user_msg]

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
