"""Embedding service for semantic vector search.

Provides embeddings from the user's configured AI provider. Resolution order:
1. Ollama (if configured + reachable) — free, local
2. OpenAI text-embedding-3-small
3. Google text-embedding-004
4. None — vector features disabled

All providers are normalized to 768 dimensions.
"""

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DIMENSIONS = 768
_OLLAMA_EMBED_MODEL = "nomic-embed-text"


class EmbeddingService:
    """Provider-agnostic embedding generation."""

    def __init__(self):
        self._provider: str | None = None
        self._model: str | None = None
        self._checked = False

    def get_provider_info(self) -> dict | None:
        if not self._provider:
            return None
        return {
            "provider": self._provider,
            "model": self._model,
            "dimensions": DIMENSIONS,
        }

    async def is_available(self) -> bool:
        if self._checked:
            return self._provider is not None
        await self._detect_provider()
        return self._provider is not None

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not await self.is_available():
            return None
        try:
            if self._provider == "ollama":
                return await self._embed_ollama(texts)
            elif self._provider == "openai":
                return await self._embed_openai(texts)
            elif self._provider == "google":
                return await self._embed_google(texts)
        except Exception as e:
            logger.warning("Embedding failed (%s): %s", self._provider, e)
            # Reset on auth failures so next call re-detects provider
            if "401" in str(e) or "403" in str(e) or "auth" in str(e).lower():
                self._checked = False
                self._provider = None
            return None
        return None

    async def embed_single(self, text: str) -> list[float] | None:
        result = await self.embed([text])
        if result and len(result) > 0:
            return result[0]
        return None

    async def _detect_provider(self):
        """Detect the best available embedding provider."""
        self._checked = True

        from core.providers.credentials import CredentialStore
        store = CredentialStore()
        profiles = store.data.get("profiles", {})

        # 1. Try Ollama
        ollama_profile = profiles.get("ollama:default", {})
        if ollama_profile.get("type") == "ollama_local" and ollama_profile.get("base_url"):
            base_url = ollama_profile["base_url"].rstrip("/")
            if await self._check_ollama(base_url):
                self._provider = "ollama"
                logger.info("Embedding provider: Ollama (%s, model=%s)", base_url, self._model)
                return

        # 2. Try OpenAI
        openai_profile = profiles.get("openai:default", {})
        openai_key = None
        if openai_profile.get("type") == "api_key":
            openai_key = openai_profile.get("key")
        elif openai_profile.get("type") == "chatgpt_oauth":
            openai_key = openai_profile.get("access")
        if openai_key:
            self._provider = "openai"
            self._model = "text-embedding-3-small"
            logger.info("Embedding provider: OpenAI (text-embedding-3-small)")
            return

        # 3. Try Google
        google_profile = profiles.get("google:default", {})
        if google_profile.get("type") == "oauth" and google_profile.get("access"):
            self._provider = "google"
            self._model = "text-embedding-004"
            logger.info("Embedding provider: Google (text-embedding-004)")
            return

        # 4. Try Anthropic (no native embeddings — skip)
        # Anthropic doesn't offer an embeddings API directly

        logger.info("No embedding provider available — vector search disabled")

    async def _check_ollama(self, base_url: str) -> bool:
        """Check if Ollama is reachable and has an embedding model."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if any embedding model is available
                embed_models = [m for m in models if "embed" in m or "nomic" in m]
                if embed_models:
                    self._model = embed_models[0].split(":")[0]
                    return True
                # Pull nomic-embed-text if not present (don't block on it)
                logger.info("Ollama available but no embedding model found")
                return False
        except Exception:
            return False

    async def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        from core.providers.credentials import CredentialStore
        store = CredentialStore()
        profile = store.data.get("profiles", {}).get("ollama:default", {})
        base_url = profile.get("base_url", "http://localhost:11434").rstrip("/")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/api/embed",
                json={"model": self._model or _OLLAMA_EMBED_MODEL, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["embeddings"]

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        from core.providers.credentials import CredentialStore
        store = CredentialStore()
        profile = store.data.get("profiles", {}).get("openai:default", {})

        api_key = None
        if profile.get("type") == "api_key":
            api_key = profile.get("key")
        elif profile.get("type") == "chatgpt_oauth":
            api_key = profile.get("access")

        if not api_key:
            raise RuntimeError("OpenAI API key not available")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "text-embedding-3-small",
                    "input": texts,
                    "dimensions": DIMENSIONS,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def _embed_google(self, texts: list[str]) -> list[list[float]]:
        from core.providers.credentials import CredentialStore
        from core.providers.oauth import refresh_google_token

        store = CredentialStore()
        profile = store.data.get("profiles", {}).get("google:default", {})

        if profile.get("type") == "oauth" and profile.get("refresh"):
            token_data = await refresh_google_token(profile["refresh"])
            access_token = token_data.get("access_token") if token_data else None
            if not access_token:
                raise RuntimeError("Google token refresh failed")
        else:
            raise RuntimeError("Google credentials not available")

        # Use the REST API directly for embeddings
        async with httpx.AsyncClient(timeout=30.0) as client:
            embeddings = []
            # Google's batch embed endpoint
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "requests": [
                        {
                            "model": "models/text-embedding-004",
                            "content": {"parts": [{"text": t}]},
                            "outputDimensionality": DIMENSIONS,
                        }
                        for t in texts
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("embeddings", []):
                embeddings.append(item["values"])
            return embeddings


# Module-level singleton
_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
