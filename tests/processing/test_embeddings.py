from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import ContentEmbeddingRecord, RelevanceDecisionRecord
import app.db.models  # noqa: F401
from app.processing.embeddings import DeterministicEmbeddingProvider, embedding_text_hash
from app.processing.models import AMBIGUOUS
from app.processing.repository import ProcessingRepository
from tests.processing.test_repository import seed_project, seed_raw_post


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_settings_include_embedding_and_threshold_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_provider == "codex-gpt-5.2"
    assert settings.relevance_accept_threshold == 0.72
    assert settings.relevance_reject_threshold == 0.35


def test_deterministic_embedding_provider_is_stable() -> None:
    provider = DeterministicEmbeddingProvider(dimensions=8)

    first = provider.embed(["same"])[0]
    second = provider.embed(["same"])[0]

    assert first.vector == second.vector
    assert first.model == "deterministic-hash-v1"
    assert first.provider == "deterministic"
    assert first.dimensions == 8


def test_repository_upserts_content_embedding_and_decision() -> None:
    session = make_session()
    project, query = seed_project(session)
    seed_raw_post(session, project, query)
    repository = ProcessingRepository(session)
    [(content_item, _created)] = repository.materialize_raw_content_items(project=project)
    embedding = DeterministicEmbeddingProvider(dimensions=8).embed([content_item.cleaned_text or ""])[0]

    row, inserted = repository.upsert_content_embedding(
        content_item=content_item,
        embedding=embedding,
        text_hash=embedding_text_hash(content_item.cleaned_text or ""),
    )
    same_row, inserted_again = repository.upsert_content_embedding(
        content_item=content_item,
        embedding=embedding,
        text_hash=embedding_text_hash(content_item.cleaned_text or ""),
    )
    decision = repository.record_relevance_decision(
        content_item=content_item,
        run_id=None,
        decision=AMBIGUOUS,
        score=0.5,
        reason="Embedding similarity 0.500 routed to ambiguous.",
        output_json={
            "accept_threshold": 0.72,
            "reject_threshold": 0.35,
            "provider": embedding.provider,
        },
    )
    repository.update_relevance_routing(
        content_item=content_item,
        final_status=AMBIGUOUS,
        relevance_score=0.5,
        ambiguity_score=0.9,
        llm_review_required=True,
    )

    assert inserted is True
    assert inserted_again is False
    assert row.id == same_row.id
    assert row.embedding_model == embedding.model
    assert row.dimensions == 8
    assert row.vector_json["vector"] == embedding.vector
    assert row.text_hash == embedding_text_hash(content_item.cleaned_text or "")
    assert decision.output_json["accept_threshold"] == 0.72
    assert content_item.llm_review_required is True
    assert session.scalars(select(ContentEmbeddingRecord)).all() == [row]
    assert session.scalars(select(RelevanceDecisionRecord)).all() == [decision]

