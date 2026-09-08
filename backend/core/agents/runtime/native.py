"""
Chatty — native runtime: today's ai_service.chat() loop behind the seam.

`prepare` is the provider construction that used to live at the top of
agents/router.py::_stream_chat (so "No AI provider configured" is still an
HTTP 400 before any streaming starts); `stream_turn` is the auto-triage plus
the ai_service.chat() call that used to be its event_generator body.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from fastapi import HTTPException

from core.providers.credentials import CredentialStore
from core.agents import ai_service

from .base import AgentRuntime, RequestCtx, TurnPlan

logger = logging.getLogger(__name__)


class NativeRuntime(AgentRuntime):
    name = "chatty"

    async def prepare(self, *, agent, config, conversation_id, request_ctx: RequestCtx,
                      chat_service, provider_factory=None, **kw) -> TurnPlan:
        store = CredentialStore()
        # model_override takes absolute precedence — skip all tier logic
        triage_info: dict | None = None
        resolved_model = config.model_override or None
        if not resolved_model and config.model_tier != "auto":
            from core.providers.tiers import resolve_tier_model
            provider_key = config.provider_override or store.data.get("active_provider", "")
            resolved_model = resolve_tier_model(provider_key, config.model_tier)
            triage_info = {"tier": config.model_tier, "method": "manual"}

        provider = provider_factory(
            agent_provider=config.provider_override or None,
            agent_model=resolved_model,
            agent_model_tier=config.model_tier if not resolved_model else None,
        )
        if not provider:
            raise HTTPException(status_code=400, detail="No AI provider configured")
        return TurnPlan(
            runtime=self.name,
            context_dir=config.context_dir,
            gcs_prefix=config.gcs_prefix,
            data={"provider": provider, "store": store, "triage_info": triage_info,
                  "provider_factory": provider_factory},
        )

    async def stream_turn(self, plan: TurnPlan, *, agent, config, registry, chat_service,
                          ctx_manager, messages, tool_mode, approved_tool,
                          request_ctx: RequestCtx, integration_tool_defs, integration_tool_modes,
                          playbook_expansion, anthropic_api_key,
                          **kw) -> AsyncGenerator[str, None]:
        provider = plan.data["provider"]
        store = plan.data["store"]
        triage_info = plan.data["triage_info"]
        provider_factory = plan.data["provider_factory"]
        conversation_id = kw.get("conversation_id")

        # Run auto-triage if tier is "auto" and we haven't resolved yet
        if not triage_info and config.model_tier == "auto" and not config.model_override:
            skip_triage = (request_ctx.training_mode or request_ctx.plan_mode
                           or approved_tool is not None)
            if not skip_triage:
                from core.providers.tiers import supports_auto_triage
                provider_key = config.provider_override or store.data.get("active_provider", "")
                if supports_auto_triage(provider_key):
                    from core.providers.triage import classify_tier, extract_classifier_credentials
                    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
                    raw_content = last_user.get("content", "") if last_user else ""
                    user_text = raw_content if isinstance(raw_content, str) else " ".join(
                        p.get("text", "") for p in raw_content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                    creds = extract_classifier_credentials(provider_key, store)
                    tier, method = await classify_tier(
                        user_message=user_text,
                        provider=provider_key,
                        credentials=creds,
                        conversation_id=conversation_id,
                        has_attachments=request_ctx.has_attachments,
                    )
                    triage_info = {"tier": tier, "method": method}
                    if tier != "top":
                        from core.providers.tiers import resolve_tier_model
                        resolved = resolve_tier_model(provider_key, tier)
                        if resolved:
                            new_provider = provider_factory(
                                agent_provider=config.provider_override or None,
                                agent_model=resolved,
                            )
                            if new_provider:
                                provider = new_provider

        async for event in ai_service.chat(
            config=config,
            provider=provider,
            registry=registry,
            ctx_manager=ctx_manager,
            messages=messages,
            training_mode=request_ctx.training_mode,
            training_type=request_ctx.training_type,
            plan_mode=request_ctx.plan_mode,
            import_mode=request_ctx.import_mode,
            conversation_id=conversation_id,
            chat_service=chat_service,
            anthropic_api_key=anthropic_api_key,
            integration_tool_defs=integration_tool_defs or None,
            tool_mode=tool_mode,
            approved_tool=approved_tool,
            integration_tool_modes=integration_tool_modes,
            triage_info=triage_info,
            playbook_expansion=playbook_expansion,
        ):
            yield event
