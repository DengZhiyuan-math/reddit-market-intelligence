"""Embedding provider contracts for relevance routing."""

import hashlib
import math
from typing import Protocol
from urllib.parse import urlsplit

import requests

from pydantic import BaseModel, Field

from app.config import Settings
from app.llm.transport import ModelUnavailable, RunBudget


class EmbeddingResult(BaseModel):
    """One embedding vector plus audit metadata."""

    vector: list[float] = Field(min_length=1)
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    dimensions: int = Field(ge=1)


class EmbeddingProvider(Protocol):
    """Provider seam for deterministic, Codex/OpenAI, or future embedding backends."""

    def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed a batch of texts."""


class DeterministicEmbeddingProvider:
    """Offline-safe lexical embedding provider for tests and local smoke runs."""

    def __init__(
        self,
        *,
        dimensions: int = 64,
        model: str = "deterministic-hash-v1",
        provider: str = "deterministic",
    ) -> None:
        self.dimensions = dimensions
        self.model = model
        self.provider = provider

    def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        """Return stable normalized vectors without network calls."""

        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> EmbeddingResult:
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return EmbeddingResult(
            vector=vector,
            model=self.model,
            provider=self.provider,
            dimensions=self.dimensions,
        )


class OpenAICompatibleEmbeddingProvider:
    """Bounded indexed embedding requests using the installed HTTP client."""

    def __init__(
        self,
        *,
        model: str,
        provider: str = "openai-compatible",
        settings: Settings | None = None,
        budget: RunBudget | None = None,
    ) -> None:
        self.model = model
        self.provider = provider
        self.settings = settings or Settings()
        self.budget = budget or RunBudget()

    def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        """Validate response indices, vector dimensions and finite values."""
        settings = self.settings
        if not settings.model_api_key:
            raise ModelUnavailable("Embedding API key is missing")
        base = settings.model_api_base_url.rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ModelUnavailable("Embedding endpoint must be HTTPS without embedded credentials")
        self.budget.model_attempt()
        try:
            response = requests.post(
                base + "/embeddings",
                headers={"Authorization": "Bearer " + settings.model_api_key.get_secret_value()},
                json={
                    "model": self.model,
                    "input": texts,
                    "dimensions": settings.embedding_dimensions,
                },
                timeout=self.budget.timeout(settings.model_timeout_seconds),
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise ValueError("HTTP failure")
            body = response.json()
            indexed = {}
            for row in body["data"]:
                index, vector = row["index"], row["embedding"]
                if type(index) is not int or index in indexed or index < 0 or index >= len(texts):
                    raise ValueError("Invalid embedding index")
                if len(vector) != settings.embedding_dimensions or any(
                    type(value) not in (int, float) or not math.isfinite(value) for value in vector
                ):
                    raise ValueError("Invalid embedding vector")
                indexed[index] = EmbeddingResult(
                    vector=vector,
                    model=body.get("model") or self.model,
                    provider="openai-compatible",
                    dimensions=len(vector),
                )
            if set(indexed) != set(range(len(texts))):
                raise ValueError("Missing embedding index")
        except Exception as exc:
            self.budget.audit.append(
                {
                    "provider": "openai-compatible",
                    "model": self.model,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "cost_estimate": None,
                }
            )
            raise ModelUnavailable("Embedding call failed or returned invalid vectors") from None
        self.budget.audit.append(
            {
                "provider": "openai-compatible",
                "model": body.get("model") or self.model,
                "usage": body.get("usage"),
                "cost_estimate": None,
                "status": "validated",
            }
        )
        return [indexed[index] for index in range(len(texts))]


def embedding_text_hash(text: str) -> str:
    """Return a stable hash for embedding cache/update decisions."""

    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return [token.strip(".,!?;:()[]{}\"'").casefold() for token in text.split() if token.strip()]
