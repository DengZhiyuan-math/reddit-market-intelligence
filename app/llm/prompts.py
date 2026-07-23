"""Prompt payloads for LLM ambiguity review."""

from app.llm.models import AmbiguityReviewRequest

REQUIRED_OUTPUT_FIELDS = [
    "is_relevant",
    "relevance_score",
    "quality_score",
    "intent_label",
    "persona_label",
    "pain_points",
    "buying_signal",
    "urgency_level",
    "reason",
    "confidence",
]


def build_ambiguity_review_prompt(request: AmbiguityReviewRequest) -> dict:
    """Build a JSON-ready prompt contract for one ambiguous content item."""

    return {
        "system": (
            "You are a strict relevance classifier for a Reddit market research system. "
            "Return JSON only."
        ),
        "instructions": [
            "Decide whether this ambiguous Reddit text is relevant to the research topic.",
            "Use the provided labels when they fit; otherwise use UNKNOWN or UNRELATED.",
            "Do not invent facts beyond the provided text and metadata.",
            "Return JSON only with exactly the required fields.",
        ],
        "required_output_fields": REQUIRED_OUTPUT_FIELDS,
        "allowed_urgency_levels": ["none", "low", "medium", "high"],
        "input": {
            "topic": request.topic,
            "business_context": request.business_context,
            "text": request.text,
            "source_type": request.source_type,
            "source_id": request.source_id,
            "subreddit": request.subreddit,
            "language": request.language,
            "scores": {
                "relevance_score": request.relevance_score,
                "quality_score": request.quality_score,
                "ambiguity_score": request.ambiguity_score,
            },
            "labels": {
                "classification_labels": request.classification_labels,
                "persona_labels": request.persona_labels,
                "pain_point_labels": request.pain_point_labels,
            },
            "metadata": request.metadata,
        },
    }
