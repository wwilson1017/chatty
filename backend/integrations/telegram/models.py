"""Telegram integration — Pydantic request/response models."""

from pydantic import BaseModel


class SetBotTokenRequest(BaseModel):
    agent_id: str
    bot_token: str


class ResetRegistrationRequest(BaseModel):
    agent_id: str
