"""Chatty — WhatsApp Pydantic request models."""

from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    agent_slug: str


class ResetRegistrationRequest(BaseModel):
    agent_slug: str
