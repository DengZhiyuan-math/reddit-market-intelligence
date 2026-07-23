"""Embedding provider contracts for relevance routing."""

import hashlib
import math
from typing import Protocol

from pydantic import BaseModel, Field


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
    """Placeholder boundary for a future OpenAI-compatible embeddings adapter."""

    def __init__(self, *, model: str, provider: str = "codex-gpt-5.2") -> None:
        self.model = model
        self.provider = provider

    def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        """Raise until Phase 6 runtime wires a concrete API client."""

        raise NotImplementedError(
            "OpenAI-compatible embedding calls require a configured API client; "
            "use DeterministicEmbeddingProvider for tests/offline runs."
        )


def embedding_text_hash(text: str) -> str:
    """Return a stable hash for embedding cache/update decisions."""

    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return [token.strip(".,!?;:()[]{}\"'").casefold() for token in text.split() if token.strip()]

