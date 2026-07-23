from __future__ import annotations

from pathlib import Path

import pytest

from app.demo.eval_sample import (
    count_by_pain_point,
    count_by_persona,
    count_by_relevance,
    default_eval_sample_path,
    load_eval_samples,
)


def test_default_eval_sample_loads_and_is_sorted() -> None:
    samples = load_eval_samples()

    assert len(samples) >= 10
    assert [sample.sample_id for sample in samples] == sorted(sample.sample_id for sample in samples)


def test_sample_has_required_positive_and_negative_coverage() -> None:
    samples = load_eval_samples()
    combined = "\n".join(f"{sample.title}\n{sample.body}\n{sample.notes}" for sample in samples).lower()
    relevance_counts = count_by_relevance(samples)
    persona_counts = count_by_persona(samples)
    pain_counts = count_by_pain_point(samples)

    assert relevance_counts["relevant"] >= 7
    assert relevance_counts["unrelated"] >= 3
    assert "zurich" in combined or "zuerich" in combined
    assert "gymnasium" in combined
    assert "matura" in combined
    assert "eth" in combined
    assert "ai homework" in combined
    assert persona_counts["EXPAT_PARENT"] >= 1
    assert pain_counts["CANNOT_FIND_TRUSTED_TUTOR"] >= 1
    assert pain_counts["TOO_EXPENSIVE"] >= 1
    assert any(sample.expected_urgency_level == "high" for sample in samples)


def test_sample_is_synthetic_and_has_no_reddit_identifiers() -> None:
    text = default_eval_sample_path().read_text(encoding="utf-8").lower()

    assert "synthetic" in text
    assert "reddit.com/" not in text
    assert "u/" not in text
    assert "permalink" not in text
    assert "reddit_post_id" not in text


def test_loader_raises_clear_error_for_malformed_json(tmp_path: Path) -> None:
    sample_path = tmp_path / "bad.jsonl"
    sample_path.write_text('{"sample_id": "zt-999"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid eval sample row at line 1"):
        load_eval_samples(sample_path)


def test_loader_raises_clear_error_for_unknown_labels(tmp_path: Path) -> None:
    sample_path = tmp_path / "bad-label.jsonl"
    sample_path.write_text(
        (
            '{"sample_id":"zt-999","source_type":"reddit_post","subreddit":"test",'
            '"title":"Synthetic bad label","body":"Synthetic bad label body",'
            '"language":"en","expected_relevance":true,'
            '"expected_intent_label":"BAD_LABEL","expected_persona_label":"PARENT",'
            '"expected_pain_points":[],"expected_urgency_level":"low",'
            '"expected_buying_signal":false,"notes":"Synthetic malformed fixture."}'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported intent label"):
        load_eval_samples(sample_path)
