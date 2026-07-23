"""Similarity scoring and low-false-negative relevance routing."""

import math
from typing import Any

from app.processing.models import ACCEPTED, AMBIGUOUS, REJECTED


def build_topic_text(project: Any, topic_plan: Any | None = None) -> str:
    """Build the topic-side text used for similarity scoring."""

    parts: list[str] = [
        getattr(project, "topic", "") or "",
        getattr(project, "region", "") or "",
        " ".join(getattr(project, "target_users", []) or []),
        getattr(project, "business_context", "") or "",
    ]
    plan_json = _plan_json(topic_plan)
    parts.append(str(plan_json.get("core_topic", "")))
    for key in ("primary_keywords", "secondary_keywords", "negative_keywords"):
        values = plan_json.get(key) or []
        if isinstance(values, list):
            parts.extend(str(value) for value in values)
    for term in plan_json.get("locale_vocabulary", []) or []:
        if isinstance(term, dict):
            parts.append(str(term.get("term", "")))
    return " ".join(part for part in parts if part).strip()


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """Calculate cosine similarity for two same-length vectors."""

    if not vector_a or not vector_b or len(vector_a) != len(vector_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vector_a, vector_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def route_similarity(score: float, accept_threshold: float, reject_threshold: float) -> str:
    """Route a similarity score into a relevance band."""

    if score >= accept_threshold:
        return ACCEPTED
    if score <= reject_threshold:
        return REJECTED
    return AMBIGUOUS


def ambiguity_score(score: float, accept_threshold: float, reject_threshold: float) -> float:
    """Return higher ambiguity near the middle of the threshold band."""

    if score >= accept_threshold or score <= reject_threshold:
        return 0.0
    midpoint = (accept_threshold + reject_threshold) / 2
    half_width = (accept_threshold - reject_threshold) / 2
    if half_width <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(score - midpoint) / half_width)


def _plan_json(topic_plan: Any | None) -> dict[str, Any]:
    if topic_plan is None:
        return {}
    if isinstance(topic_plan, dict):
        return topic_plan
    if hasattr(topic_plan, "plan_json"):
        return getattr(topic_plan, "plan_json") or {}
    if hasattr(topic_plan, "model_dump"):
        return topic_plan.model_dump(mode="json")
    return {}

