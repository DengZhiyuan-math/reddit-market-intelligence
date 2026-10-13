"""Thin stage adapters and explicit factories for installed model transports."""

from dataclasses import asdict
import json

from app.config import Settings
from app.llm.transport import ModelTransport, ModelUnavailable, RunBudget


class RealTopicPlanner:
    def __init__(self, transport):
        self.transport = transport
        self.last_result = None

    def generate(self, context):
        from app.topic_planning.models import TopicPlan
        from app.topic_planning.prompts import build_topic_planner_prompt

        self.last_result = self.transport.complete(
            build_topic_planner_prompt(asdict(context)), TopicPlan
        )
        return TopicPlan.model_validate(self.last_result.output)


class RealReviewProvider:
    def __init__(self, transport):
        self.transport = transport
        self.provider, self.model = transport.provider, transport.model

    def review(self, request):
        from app.llm.models import AmbiguityReviewOutput, LlmReviewProviderResult
        from app.llm.prompts import build_ambiguity_review_prompt

        result = self.transport.complete(
            json.dumps(build_ambiguity_review_prompt(request)), AmbiguityReviewOutput
        )
        return LlmReviewProviderResult(
            output=result.output,
            provider=result.provider,
            model=result.model,
            raw_response_json=result.audit(),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


class RealSignalProvider:
    def __init__(self, transport):
        self.transport = transport
        self.provider, self.model = transport.provider, transport.model

    def extract(self, request):
        from app.analysis.models import SignalExtractionOutput, SignalExtractionProviderResult
        from app.analysis.prompts import build_signal_extraction_prompt

        result = self.transport.complete(
            json.dumps(build_signal_extraction_prompt(request)), SignalExtractionOutput
        )
        return SignalExtractionProviderResult(
            output=result.output,
            provider=result.provider,
            model=result.model,
            raw_response_json=result.audit(),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


def _transport(settings, provider, model, budget):
    return ModelTransport(settings, provider, model, budget)


def topic_provider(settings: Settings, budget: RunBudget | None = None):
    from app.topic_planning.planner import DeterministicTopicPlanner

    if settings.topic_planner_provider == "deterministic":
        return DeterministicTopicPlanner()
    return RealTopicPlanner(
        _transport(settings, settings.topic_planner_provider, settings.topic_planner_model, budget)
    )


def review_provider(settings: Settings, budget: RunBudget | None = None):
    from app.llm.gateway import DeterministicReviewProvider

    if settings.llm_review_provider in {"deterministic", "codex-local"}:
        return DeterministicReviewProvider()
    return RealReviewProvider(
        _transport(settings, settings.llm_review_provider, settings.llm_review_model, budget)
    )


def signal_provider(settings: Settings, budget: RunBudget | None = None):
    from app.analysis.gateway import DeterministicSignalProvider

    if settings.signal_extraction_provider in {"deterministic", "codex-local"}:
        return DeterministicSignalProvider()
    return RealSignalProvider(
        _transport(
            settings, settings.signal_extraction_provider, settings.signal_extraction_model, budget
        )
    )


def embedding_provider(settings: Settings, budget: RunBudget | None = None):
    from app.processing.embeddings import (
        DeterministicEmbeddingProvider,
        OpenAICompatibleEmbeddingProvider,
    )

    if settings.embedding_provider in {"deterministic", "lexical", "codex-gpt-5.2"}:
        return DeterministicEmbeddingProvider(dimensions=settings.embedding_dimensions)
    if settings.embedding_provider == "openai-compatible":
        return OpenAICompatibleEmbeddingProvider(
            model=settings.embedding_model, settings=settings, budget=budget
        )
    raise ModelUnavailable(f"Unknown embedding provider: {settings.embedding_provider}")
