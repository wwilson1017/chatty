"""
Chatty — AgentConfig dataclass.

Provider-agnostic agent configuration. The AI provider and model
are resolved at runtime via CredentialStore, not stored here.
"""

from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Configuration for an agent instance."""

    agent_id: str
    agent_name: str
    slug: str

    # Optional personality override (falls back to generic onboarding prompt)
    personality: str = ""

    # Provider override — if empty, uses the globally active provider
    provider_override: str = ""
    model_override: str = ""

    # Feature flags
    gmail_enabled: bool = False
    calendar_enabled: bool = False

    # Context directory (absolute path)
    context_dir: str = ""

    # GCS prefix for this agent's data
    gcs_prefix: str = ""

    # Chat history DB path (absolute path)
    chat_db_path: str = ""

    # Onboarding
    onboarding_complete: bool = False

    # Training topics (used by onboarding)
    training_topics: list[str] = field(default_factory=list)
