"""Offline-safe deterministic topic planner."""

from dataclasses import dataclass, field
from typing import Protocol

from app.topic_planning.models import (
    DEFAULT_CLASSIFICATION_LABELS,
    DEFAULT_PAIN_POINT_LABELS,
    DEFAULT_PERSONA_LABELS,
    TOPIC_PLAN_SCHEMA_VERSION,
    LocaleVocabularyTerm,
    PlannedSearchQuery,
    TopicPlan,
    dedupe_normalized,
)

MAX_QUERY_STRATEGIES = 24


@dataclass(frozen=True)
class TopicPlanningContext:
    """Project metadata needed to generate a topic plan."""

    topic: str
    region: str | None = None
    languages: list[str] = field(default_factory=list)
    target_users: list[str] = field(default_factory=list)
    business_context: str | None = None
    time_range: str | None = None


class TopicPlannerProvider(Protocol):
    """Provider seam for deterministic and future LLM topic planners."""

    def generate(self, context: TopicPlanningContext) -> TopicPlan:
        """Generate a validated topic plan."""


class DeterministicTopicPlanner:
    """Generate useful topic plans from project metadata without network calls."""

    def generate(self, context: TopicPlanningContext) -> TopicPlan:
        haystack = self._haystack(context)
        keywords = self._keywords(context, haystack)
        subreddits = self._subreddits(haystack)
        locale_vocabulary = self._locale_vocabulary(context, haystack)
        return TopicPlan(
            schema_version=TOPIC_PLAN_SCHEMA_VERSION,
            core_topic=self._core_topic(context),
            market_hypotheses=self._hypotheses(context, haystack),
            primary_keywords=keywords[:8],
            secondary_keywords=keywords[8:18] or keywords[:4],
            negative_keywords=self._negative_keywords(haystack),
            candidate_subreddits=subreddits,
            classification_labels=list(DEFAULT_CLASSIFICATION_LABELS),
            persona_labels=list(DEFAULT_PERSONA_LABELS),
            pain_point_labels=list(DEFAULT_PAIN_POINT_LABELS),
            locale_vocabulary=locale_vocabulary,
            query_strategy=self._query_strategy(keywords, subreddits),
        )

    def _haystack(self, context: TopicPlanningContext) -> str:
        parts = [
            context.topic,
            context.region or "",
            " ".join(context.languages),
            " ".join(context.target_users),
            context.business_context or "",
            context.time_range or "",
        ]
        return " ".join(parts).casefold()

    def _core_topic(self, context: TopicPlanningContext) -> str:
        if context.region and context.region.casefold() not in context.topic.casefold():
            return f"{context.topic} ({context.region})"
        return context.topic

    def _hypotheses(self, context: TopicPlanningContext, haystack: str) -> list[str]:
        hypotheses = [
            "Users ask Reddit for recommendations, pricing, trust signals, and practical next steps.",
            "High-signal posts often describe a concrete problem, location, urgency, or target user.",
        ]
        if self._is_tutoring_context(haystack):
            hypotheses.extend(
                [
                    "Parents are looking for trusted math and science tutoring support.",
                    "Students show urgency around Gymnasium, Matura, IB, or university preparation.",
                    "Expat families need help understanding the Swiss school system and local language expectations.",
                ]
            )
        if context.business_context:
            hypotheses.append(
                "Business positioning should mirror user language before emphasizing product technology."
            )
        return dedupe_normalized(hypotheses)

    def _keywords(self, context: TopicPlanningContext, haystack: str) -> list[str]:
        metadata_keywords = [context.topic, *(context.target_users or []), *(context.languages or [])]
        if context.region:
            metadata_keywords.append(context.region)
        keywords: list[str] = []
        if self._is_tutoring_context(haystack):
            keywords.extend(
                [
                    "tutor Switzerland",
                    "math tutor Zurich",
                    "science tutor Zurich",
                    "private tutor Zurich",
                    "Nachhilfe Zürich",
                    "Mathematik Nachhilfe",
                    "Gymnasium math help",
                    "Matura preparation",
                    "ETH preparation",
                    "Swiss school system help",
                    "my child struggling with math",
                    "looking for tutor",
                    "expensive tutoring",
                    "German homework help",
                    "Swiss school stress",
                    "Matura exam stress",
                ]
            )
            keywords.extend(metadata_keywords)
        else:
            keywords.extend(metadata_keywords)
            keywords.extend(
                [
                    f"{context.topic} reddit",
                    f"{context.topic} recommendations",
                    f"{context.topic} price",
                    f"{context.topic} problem",
                ]
            )
        return dedupe_normalized(keywords)

    def _negative_keywords(self, haystack: str) -> list[str]:
        negative = ["spam", "giveaway", "job posting"]
        if self._is_tutoring_context(haystack):
            negative.extend(["game tutor", "music tutor", "driving instructor", "language exchange only"])
        return dedupe_normalized(negative)

    def _subreddits(self, haystack: str) -> list[str]:
        subreddits = ["AskReddit", "NoStupidQuestions"]
        if "switzerland" in haystack or "zurich" in haystack or "zürich" in haystack:
            subreddits = ["Switzerland", "askswitzerland", "Zurich", "ETHZurich", *subreddits]
        if self._is_tutoring_context(haystack):
            subreddits.extend(["Parenting", "Teachers", "IBO", "education"])
        return dedupe_normalized(subreddits)

    def _locale_vocabulary(
        self,
        context: TopicPlanningContext,
        haystack: str,
    ) -> list[LocaleVocabularyTerm]:
        terms: list[LocaleVocabularyTerm] = [
            LocaleVocabularyTerm(
                term="recommendation",
                language="en",
                category="reddit_intent",
                rationale="Common Reddit phrasing for asking communities where to start.",
            )
        ]
        language_blob = " ".join(context.languages).casefold()
        wants_german = (
            "de" in language_blob
            or "german" in language_blob
            or "switzerland" in haystack
            or "zurich" in haystack
            or "zürich" in haystack
        )
        if self._is_tutoring_context(haystack):
            terms.extend(
                [
                    LocaleVocabularyTerm(
                        term="tutor",
                        language="en",
                        category="tutoring",
                        rationale="Core English term for private academic help.",
                    ),
                    LocaleVocabularyTerm(
                        term="Gymnasium",
                        language="de/en",
                        category="school_path",
                        rationale="Swiss academic-track school term relevant to exam preparation.",
                    ),
                    LocaleVocabularyTerm(
                        term="Matura",
                        language="de/en",
                        category="exam",
                        rationale="Swiss secondary-school leaving exam term.",
                    ),
                    LocaleVocabularyTerm(
                        term="ETH preparation",
                        language="en",
                        category="university_preparation",
                        rationale="Relevant to Zurich STEM and university-prep discussions.",
                    ),
                ]
            )
        if wants_german:
            terms.extend(
                [
                    LocaleVocabularyTerm(
                        term="Nachhilfe",
                        language="de",
                        category="tutoring",
                        rationale="Common German term for tutoring.",
                    ),
                    LocaleVocabularyTerm(
                        term="Zürich",
                        language="de",
                        category="location",
                        rationale="German spelling for Zurich.",
                    ),
                    LocaleVocabularyTerm(
                        term="Mathematik",
                        language="de",
                        category="subject",
                        rationale="German term for mathematics.",
                    ),
                ]
            )
        return self._dedupe_terms(terms)

    def _query_strategy(
        self,
        keywords: list[str],
        subreddits: list[str],
    ) -> list[PlannedSearchQuery]:
        strategy: list[PlannedSearchQuery] = []
        for subreddit in subreddits:
            for keyword in keywords[:8]:
                strategy.append(
                    PlannedSearchQuery(
                        query=keyword,
                        subreddit=subreddit,
                        sort="relevance",
                        time_filter="year",
                        rationale=f"Search r/{subreddit} for high-signal discussion around {keyword}.",
                    )
                )
                if len(strategy) >= MAX_QUERY_STRATEGIES:
                    return strategy
        return strategy

    def _is_tutoring_context(self, haystack: str) -> bool:
        markers = (
            "tutor",
            "tutoring",
            "education",
            "school",
            "gymnasium",
            "matura",
            "eth",
            "math",
            "science",
            "parent",
            "student",
            "expat",
            "nachhilfe",
        )
        return any(marker in haystack for marker in markers)

    def _dedupe_terms(self, terms: list[LocaleVocabularyTerm]) -> list[LocaleVocabularyTerm]:
        seen: set[tuple[str, str]] = set()
        deduped: list[LocaleVocabularyTerm] = []
        for term in terms:
            key = (term.term.casefold(), term.language.casefold())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(term)
        return deduped
