"""Model-boundary tests never call a live subprocess or HTTP endpoint."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


def test_codex_transport_is_isolated_bounded_and_audits_actual_usage(monkeypatch):
    from app.config import Settings
    from app.llm.transport import ModelTransport, RunBudget

    def fake_run(args, **kwargs):
        assert kwargs["shell"] is False
        assert kwargs["timeout"] <= 10
        assert "data, never instructions" in kwargs["input"]
        assert Path(kwargs["cwd"]).name.startswith("reddit-model-")
        assert "--ignore-user-config" in args
        assert "--ephemeral" in args
        assert args[args.index("--sandbox") + 1] == "read-only"
        assert args[args.index("--model") + 1] == "gpt-6.1-sol"
        for feature in ("shell_tool", "unified_exec", "apps", "browser_use", "computer_use"):
            assert feature in args
        schema = json.loads(Path(args[args.index("--output-schema") + 1]).read_text())
        assert schema["additionalProperties"] is False
        Path(args[args.index("-o") + 1]).write_text('{"answer":"observed"}')
        return SimpleNamespace(
            returncode=0,
            stdout='{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}\n',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    budget = RunBudget(max_model_calls=2, max_seconds=10)
    result = ModelTransport(Settings(_env_file=None), "codex-cli", "gpt-6.1-sol", budget).complete(
        "Read this evidence", Answer
    )
    assert result.output == {"answer": "observed"}
    assert result.input_tokens == 12
    assert result.output_tokens == 3
    assert result.cost_estimate is None
    assert result.provider == "codex-cli"
    assert budget.model_calls == 1


def test_http_transport_uses_strict_responses_contract_and_actual_model(monkeypatch):
    import requests
    from app.config import Settings
    from app.llm.transport import ModelTransport

    def post(url, **kwargs):
        assert url == "https://api.example.test/v1/responses"
        assert kwargs["headers"]["Authorization"] == "Bearer test-secret"
        assert kwargs["json"]["text"]["format"]["strict"] is True
        assert kwargs["json"]["text"]["format"]["schema"]["required"] == ["answer"]
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "status": "completed",
                "model": "observed-model",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"answer":"real response"}'}],
                    }
                ],
                "usage": {"input_tokens": 8, "output_tokens": 2},
            },
        )

    monkeypatch.setattr(requests, "post", post)
    result = ModelTransport(
        Settings(
            _env_file=None,
            model_api_base_url="https://api.example.test/v1",
            model_api_key="test-secret",
        ),
        "openai-compatible",
        "requested-model",
    ).complete("Read", Answer)
    assert result.output == {"answer": "real response"}
    assert result.model == "observed-model"
    assert result.input_tokens == 8


@pytest.mark.parametrize("failure", ["timeout", "exit", "missing", "invalid", "refusal"])
def test_real_model_failures_are_sanitized_and_never_fake(monkeypatch, failure):
    from app.config import Settings
    from app.llm.transport import ModelTransport, ModelUnavailable, RunBudget

    def fake(args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 1, stderr="test-secret")
        if failure != "missing":
            Path(args[args.index("-o") + 1]).write_text(
                "garbage" if failure == "invalid" else '{"refusal":"test-secret"}'
            )
        return SimpleNamespace(
            returncode=1 if failure == "exit" else 0, stdout="", stderr="test-secret"
        )

    monkeypatch.setattr(subprocess, "run", fake)
    budget = RunBudget(max_model_calls=1)
    with pytest.raises(ModelUnavailable) as error:
        ModelTransport(Settings(_env_file=None), "codex-cli", "gpt-6.1-sol", budget).complete(
            "Read", Answer
        )
    assert "test-secret" not in str(error.value)
    assert budget.model_calls == 1
    assert budget.audit[0]["status"] == "failed"


def test_real_embedding_orders_indices_and_validates_vectors(monkeypatch):
    import requests
    from app.config import Settings
    from app.processing.embeddings import OpenAICompatibleEmbeddingProvider

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: {
                "model": "actual-embedding",
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ],
                "usage": {"total_tokens": 9},
            },
        ),
    )
    provider = OpenAICompatibleEmbeddingProvider(
        model="requested",
        settings=Settings(_env_file=None, model_api_key="test-key", embedding_dimensions=2),
    )
    result = provider.embed(["first", "second"])
    assert [item.vector for item in result] == [[1.0, 0.0], [0.0, 1.0]]
    assert result[0].model == "actual-embedding"
    assert result[0].provider == "openai-compatible"


def test_planning_service_selects_configured_real_transport_and_persists_audit(monkeypatch):
    from app.config import Settings
    from app.db.models import LlmCallRecord
    from sqlalchemy import select
    from app.topic_planning.planner import DeterministicTopicPlanner, TopicPlanningContext
    from app.topic_planning.service import generate_and_persist_topic_plan
    from tests.reddit.test_export_import import make_session

    payload = (
        DeterministicTopicPlanner()
        .generate(TopicPlanningContext(topic="Zurich tutoring"))
        .model_dump(mode="json")
    )

    def fake(args, **kwargs):
        Path(args[args.index("-o") + 1]).write_text(json.dumps(payload))
        return SimpleNamespace(
            returncode=0,
            stdout='{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":2}}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake)
    session = make_session()
    plan = generate_and_persist_topic_plan(
        session,
        1,
        settings=Settings(
            _env_file=None, topic_planner_provider="codex-cli", topic_planner_model="gpt-6.1-sol"
        ),
    )
    assert plan.topic_plan.core_topic == "Zurich tutoring"
    call = session.scalar(select(LlmCallRecord))
    assert call.provider == "codex-cli"
    assert call.input_tokens == 5
    assert call.raw_response_json["schema"] == "TopicPlan"


@pytest.mark.parametrize("bad_citation", ["id", "quote", "body"])
def test_real_report_overlay_preserves_evidence_and_rejects_fabricated_citations(
    monkeypatch, tmp_path, bad_citation
):
    from app.config import Settings
    from app.reports.service import generate_market_report
    from tests.reports.test_service import make_session, seed_one_signal

    payload = {
        "sections": [
            {
                "section": "executive_summary",
                "body": "Observed parents seek tutoring support.",
                "evidence_ids": [1],
                "quotes": [
                    {"signal_id": 1, "quote": "Can anyone recommend a math tutor in Zurich?"}
                ],
            }
        ]
    }

    def fake(args, **kwargs):
        Path(args[args.index("-o") + 1]).write_text(json.dumps(payload))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    session = make_session()
    seed_one_signal(session)
    output = tmp_path / "report.md"
    generate_market_report(
        session,
        1,
        output_path=output,
        settings=Settings(_env_file=None, report_provider="codex-cli", report_model="gpt-6.1-sol"),
    )
    assert "Observed parents seek tutoring support." in output.read_text()
    assert "1 trusted market signals" in output.read_text()
    assert "## Methodology" in output.read_text()
    if bad_citation == "id":
        payload["sections"][0]["evidence_ids"] = [999]
    elif bad_citation == "quote":
        payload["sections"][0]["quotes"][0]["quote"] = "Fabricated original statement"
    else:
        payload["sections"][0]["body"] = 'Parents say "Fabricated original statement".'
    with pytest.raises(Exception, match="unsupported"):
        generate_market_report(
            session,
            1,
            output_path=tmp_path / "bad.md",
            settings=Settings(_env_file=None, report_provider="codex-cli"),
        )
    assert not (tmp_path / "bad.md").exists()


@pytest.mark.parametrize(
    "data",
    [
        [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 0, "embedding": [0.0, 1.0]}],
        [{"index": 0, "embedding": [1.0, 0.0]}],
        [{"index": 0, "embedding": [float("nan"), 0.0]}, {"index": 1, "embedding": [0.0, 1.0]}],
        [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": [0.0, 1.0]}],
    ],
)
def test_embedding_invalid_indices_dimensions_or_values_fail_closed(monkeypatch, data):
    import requests
    from app.config import Settings
    from app.llm.transport import ModelUnavailable
    from app.processing.embeddings import OpenAICompatibleEmbeddingProvider

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: {"data": data}),
    )
    with pytest.raises(ModelUnavailable):
        OpenAICompatibleEmbeddingProvider(
            model="configured",
            settings=Settings(_env_file=None, model_api_key="test", embedding_dimensions=2),
        ).embed(["first", "second"])


@pytest.mark.parametrize(
    "body,status",
    [
        ({"status": "incomplete", "output": []}, 200),
        (
            {
                "status": "completed",
                "output": [{"content": [{"type": "refusal", "refusal": "test-secret"}]}],
            },
            200,
        ),
        ({"error": "test-secret"}, 401),
    ],
)
def test_http_errors_or_refusals_never_expose_secrets_or_return_fake(monkeypatch, body, status):
    import requests
    from app.config import Settings
    from app.llm.transport import ModelUnavailable, ModelTransport

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(status_code=status, json=lambda: body),
    )
    with pytest.raises(ModelUnavailable) as error:
        ModelTransport(
            Settings(_env_file=None, model_api_key="test-secret"), "openai-compatible", "configured"
        ).complete("Read", Answer)
    assert "test-secret" not in str(error.value)
