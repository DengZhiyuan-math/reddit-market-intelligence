"""Database persistence helpers for content cleaning and relevance routing."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ContentEmbeddingRecord,
    ContentItemRecord,
    PipelineRunRecord,
    ProjectRedditCommentRecord,
    ProjectRedditPostRecord,
    RedditCommentRawRecord,
    RedditPostRawRecord,
    RelevanceDecisionRecord,
    ResearchPlanRecord,
    ResearchProjectRecord,
)
from app.processing.embeddings import EmbeddingResult
from app.processing.cleaner import clean_reddit_text, combine_post_text
from app.processing.language_detector import detect_language, is_allowed_language
from app.processing.models import (
    EMBEDDING_DECISION,
    OFF_LANGUAGE,
    PENDING,
    REJECTED,
    CleanedTextResult,
    ProcessingReason,
    ReasonSeverity,
)
from app.processing.rules import build_reason


class ProjectRawPost(NamedTuple):
    """Project post provenance plus raw post payload."""

    project_post: ProjectRedditPostRecord
    raw_post: RedditPostRawRecord


class ProjectRawComment(NamedTuple):
    """Project comment provenance plus raw comment payload."""

    project_comment: ProjectRedditCommentRecord
    raw_comment: RedditCommentRawRecord


class ProcessingRepository:
    """Repository for cleaning and relevance-routing persistence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_project_by_project_id(self, project_id: int) -> ResearchProjectRecord:
        """Return a database project by its durable project ID."""

        project = self.session.scalar(
            select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == project_id)
        )
        if project is None:
            raise ValueError(f"Project not found in database: {project_id}")
        return project

    def get_selected_research_plan(self, project_db_id: int) -> ResearchPlanRecord | None:
        """Return the selected research plan for a database project if present."""

        return self.session.scalar(
            select(ResearchPlanRecord)
            .where(
                ResearchPlanRecord.project_id == project_db_id,
                ResearchPlanRecord.selected.is_(True),
            )
            .order_by(ResearchPlanRecord.id.desc())
        )

    def start_filtering_run(
        self,
        project_db_id: int,
        run_config: dict,
    ) -> PipelineRunRecord:
        """Create a running pipeline run for filtering."""

        run = PipelineRunRecord(
            project_id=project_db_id,
            stage="filtering",
            status="running",
            run_config=run_config,
            summary={},
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def complete_filtering_run(
        self,
        run_id: int,
        status: str,
        summary,
    ) -> PipelineRunRecord:
        """Persist final filtering run status and summary counters."""

        run = self.session.get(PipelineRunRecord, run_id)
        if run is None:
            raise ValueError(f"Filtering run not found: {run_id}")
        run.status = status
        run.summary = summary.model_dump(mode="json")
        run.completed_at = datetime.now(UTC)
        self.session.flush()
        return run

    def list_raw_project_posts(
        self,
        project_db_id: int,
        limit: int | None = None,
        source_ids: list[str] | None = None,
    ) -> list[ProjectRawPost]:
        """List raw post payloads discovered by a project."""

        statement = (
            select(ProjectRedditPostRecord, RedditPostRawRecord)
            .join(
                RedditPostRawRecord,
                ProjectRedditPostRecord.reddit_post_raw_id == RedditPostRawRecord.id,
            )
            .where(ProjectRedditPostRecord.project_id == project_db_id)
            .order_by(ProjectRedditPostRecord.id)
        )
        if source_ids is not None:
            statement = statement.where(RedditPostRawRecord.reddit_post_id.in_(source_ids))
        if limit is not None:
            statement = statement.limit(limit)
        return [
            ProjectRawPost(project_post=row[0], raw_post=row[1])
            for row in self.session.execute(statement)
        ]

    def list_raw_project_comments(
        self,
        project_db_id: int,
        limit: int | None = None,
        source_ids: list[str] | None = None,
    ) -> list[ProjectRawComment]:
        """List raw comment payloads discovered by a project."""

        statement = (
            select(ProjectRedditCommentRecord, RedditCommentRawRecord)
            .join(
                RedditCommentRawRecord,
                ProjectRedditCommentRecord.reddit_comment_raw_id == RedditCommentRawRecord.id,
            )
            .where(ProjectRedditCommentRecord.project_id == project_db_id)
            .order_by(ProjectRedditCommentRecord.id)
        )
        if source_ids is not None:
            statement = statement.where(RedditCommentRawRecord.reddit_comment_id.in_(source_ids))
        if limit is not None:
            statement = statement.limit(limit)
        return [
            ProjectRawComment(project_comment=row[0], raw_comment=row[1])
            for row in self.session.execute(statement)
        ]

    def get_source_context(self, item: ContentItemRecord) -> dict:
        """Read context from the same project's first captured source snapshots."""

        context = {"subreddit": None, "parent_post": None, "parent_comment": None}
        if item.source_type == "reddit_post":
            rows = self.list_raw_project_posts(
                item.project_id, limit=1, source_ids=[item.source_id]
            )
            if rows:
                context["subreddit"] = rows[0].project_post.subreddit
            return context
        if item.source_type != "reddit_comment":
            return context
        rows = self.list_raw_project_comments(item.project_id, limit=1, source_ids=[item.source_id])
        if not rows:
            return context
        association, raw = rows[0]
        snapshot = association.filters_json.get("source_snapshot")
        pid = snapshot.get("reddit_post_id") if snapshot is not None else raw.reddit_post_id
        parent_id = snapshot.get("parent_id") if snapshot is not None else raw.parent_id
        context["subreddit"] = association.subreddit
        posts = self.list_raw_project_posts(item.project_id, limit=1, source_ids=[pid])
        if posts:
            link, post = posts[0]
            context["subreddit"] = association.subreddit or link.subreddit
            source = link.filters_json.get("source_snapshot")
            source = (
                source
                if source is not None
                else {"title": post.title, "body": post.body, "permalink": post.permalink}
            )
            body = source.get("body") or ""
            context["parent_post"] = {
                "source_id": pid,
                "title": source.get("title"),
                "text": body[:6000],
                "source_url": source.get("permalink"),
                "truncated": len(body) > 6000,
            }
        if parent_id and parent_id.startswith("t1_"):
            parents = self.list_raw_project_comments(
                item.project_id, limit=1, source_ids=[parent_id[3:]]
            )
            if parents:
                link, parent = parents[0]
                source = link.filters_json.get("source_snapshot")
                source = (
                    source
                    if source is not None
                    else {
                        "reddit_post_id": parent.reddit_post_id,
                        "body": parent.body,
                        "permalink": parent.permalink,
                    }
                )
                if source.get("reddit_post_id") == pid:
                    body = source.get("body") or ""
                    context["parent_comment"] = {
                        "source_id": parent_id[3:],
                        "text": body[:2000],
                        "source_url": source.get("permalink"),
                        "truncated": len(body) > 2000,
                    }
        return context

    def upsert_content_item(
        self,
        *,
        project_db_id: int,
        run_id: int | None,
        source_type: str,
        source_id: str,
        source_table: str,
        source_mode: str,
        text: str,
        cleaned: CleanedTextResult,
        language: str | None,
        final_status: str,
        llm_review_required: bool,
    ) -> tuple[ContentItemRecord, bool]:
        """Insert or update a project-scoped content item."""

        existing = self.session.scalar(
            select(ContentItemRecord).where(
                ContentItemRecord.project_id == project_db_id,
                ContentItemRecord.source_type == source_type,
                ContentItemRecord.source_id == source_id,
            )
        )
        reason_payload = [reason.model_dump(mode="json") for reason in cleaned.reasons]
        if existing is not None:
            existing.run_id = run_id
            existing.source_table = source_table
            existing.source_mode = source_mode
            existing.text = text
            existing.cleaned_text = cleaned.cleaned_text
            existing.language = language
            existing.quality_score = cleaned.quality_score
            existing.final_status = final_status
            existing.llm_review_required = llm_review_required
            existing.reason_codes = reason_payload
            self.session.flush()
            return existing, False

        record = ContentItemRecord(
            project_id=project_db_id,
            run_id=run_id,
            source_type=source_type,
            source_id=source_id,
            source_table=source_table,
            source_mode=source_mode,
            text=text,
            cleaned_text=cleaned.cleaned_text,
            language=language,
            quality_score=cleaned.quality_score,
            final_status=final_status,
            llm_review_required=llm_review_required,
            reason_codes=reason_payload,
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def materialize_raw_content_items(
        self,
        *,
        project: ResearchProjectRecord,
        run_id: int | None = None,
        limit: int | None = None,
        source_scope: dict[str, list[str]] | None = None,
    ) -> list[tuple[ContentItemRecord, bool]]:
        """Convert project raw posts and comments into cleaned content items."""

        materialized: list[tuple[ContentItemRecord, bool]] = []
        seen_posts: set[int] = set()
        for project_post in self.list_raw_project_posts(
            project.id,
            limit=limit,
            source_ids=source_scope.get("reddit_post", []) if source_scope is not None else None,
        ):
            if project_post.raw_post.id in seen_posts:
                continue
            seen_posts.add(project_post.raw_post.id)
            snapshot = project_post.project_post.filters_json.get("source_snapshot")
            text = combine_post_text(
                snapshot.get("title") if snapshot is not None else project_post.raw_post.title,
                snapshot.get("body") if snapshot is not None else project_post.raw_post.body,
            )
            materialized.append(
                self._materialize_one(
                    project=project,
                    run_id=run_id,
                    source_type="reddit_post",
                    source_id=project_post.raw_post.reddit_post_id,
                    source_table="reddit_posts_raw",
                    source_mode=_source_mode_from_raw_json(
                        project_post.raw_post.raw_json, project_post.project_post.filters_json
                    ),
                    text=text,
                )
            )
        seen_comments: set[int] = set()
        for project_comment in self.list_raw_project_comments(
            project.id,
            limit=limit,
            source_ids=source_scope.get("reddit_comment", []) if source_scope is not None else None,
        ):
            if project_comment.raw_comment.id in seen_comments:
                continue
            seen_comments.add(project_comment.raw_comment.id)
            snapshot = project_comment.project_comment.filters_json.get("source_snapshot")
            materialized.append(
                self._materialize_one(
                    project=project,
                    run_id=run_id,
                    source_type="reddit_comment",
                    source_id=project_comment.raw_comment.reddit_comment_id,
                    source_table="reddit_comments_raw",
                    source_mode=_source_mode_from_raw_json(
                        project_comment.raw_comment.raw_json,
                        project_comment.project_comment.filters_json,
                    ),
                    text=(
                        snapshot.get("body")
                        if snapshot is not None
                        else project_comment.raw_comment.body
                    )
                    or "",
                )
            )
        return materialized

    def _materialize_one(
        self,
        *,
        project: ResearchProjectRecord,
        run_id: int | None,
        source_type: str,
        source_id: str,
        source_table: str,
        source_mode: str,
        text: str,
    ) -> tuple[ContentItemRecord, bool]:
        cleaned = clean_reddit_text(text)
        language = detect_language(cleaned.cleaned_text)
        reasons = list(cleaned.reasons)
        if cleaned.evidence_eligible and not is_allowed_language(
            language, list(project.languages or [])
        ):
            reasons.append(_off_language_reason(language, list(project.languages or [])))
            cleaned = cleaned.model_copy(update={"reasons": reasons, "quality_score": 0.3})
        hard_rejected = any(
            reason.severity == ReasonSeverity.REJECT.value for reason in cleaned.reasons
        )
        final_status = REJECTED if hard_rejected else PENDING
        return self.upsert_content_item(
            project_db_id=project.id,
            run_id=run_id,
            source_type=source_type,
            source_id=source_id,
            source_table=source_table,
            source_mode=source_mode,
            text=text,
            cleaned=cleaned,
            language=language,
            final_status=final_status,
            llm_review_required=False,
        )

    def upsert_content_embedding(
        self,
        *,
        content_item: ContentItemRecord,
        embedding: EmbeddingResult,
        text_hash: str,
    ) -> tuple[ContentEmbeddingRecord, bool]:
        """Insert or update the active embedding row for a content item."""

        existing = self.session.scalar(
            select(ContentEmbeddingRecord).where(
                ContentEmbeddingRecord.content_item_id == content_item.id,
                ContentEmbeddingRecord.embedding_model == embedding.model,
            )
        )
        vector_payload = {
            "vector": embedding.vector,
            "provider": embedding.provider,
        }
        if existing is not None:
            existing.project_id = content_item.project_id
            existing.dimensions = embedding.dimensions
            existing.vector_json = vector_payload
            existing.text_hash = text_hash
            self.session.flush()
            return existing, False
        record = ContentEmbeddingRecord(
            content_item_id=content_item.id,
            project_id=content_item.project_id,
            embedding_model=embedding.model,
            dimensions=embedding.dimensions,
            vector_json=vector_payload,
            text_hash=text_hash,
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def update_relevance_routing(
        self,
        *,
        content_item: ContentItemRecord,
        final_status: str,
        relevance_score: float,
        ambiguity_score: float,
        llm_review_required: bool,
    ) -> ContentItemRecord:
        """Persist final relevance route fields on a content item."""

        content_item.final_status = final_status
        content_item.relevance_score = relevance_score
        content_item.ambiguity_score = ambiguity_score
        content_item.llm_review_required = llm_review_required
        self.session.flush()
        return content_item

    def record_relevance_decision(
        self,
        *,
        content_item: ContentItemRecord,
        run_id: int | None,
        decision: str,
        score: float,
        reason: str,
        output_json: dict,
    ) -> RelevanceDecisionRecord:
        """Insert or update the embedding relevance decision for a content item."""

        existing = self.session.scalar(
            select(RelevanceDecisionRecord).where(
                RelevanceDecisionRecord.content_item_id == content_item.id,
                RelevanceDecisionRecord.decision_type == EMBEDDING_DECISION,
            )
        )
        if existing is not None:
            existing.project_id = content_item.project_id
            existing.run_id = run_id
            existing.decision = decision
            existing.score = score
            existing.reason = reason
            existing.output_json = output_json
            self.session.flush()
            return existing
        record = RelevanceDecisionRecord(
            content_item_id=content_item.id,
            project_id=content_item.project_id,
            run_id=run_id,
            decision_type=EMBEDDING_DECISION,
            decision=decision,
            score=score,
            reason=reason,
            output_json=output_json,
        )
        self.session.add(record)
        self.session.flush()
        return record


def _off_language_reason(detected: str, configured: Sequence[str]) -> ProcessingReason:
    return build_reason(
        OFF_LANGUAGE,
        f"Detected language {detected!r} is outside configured project languages {list(configured)!r}.",
        ReasonSeverity.LOW_QUALITY.value,
    )


def _source_mode_from_raw_json(raw_json: dict | None, project_metadata: dict | None = None) -> str:
    acquisition_method = (
        (project_metadata or {}).get("acquisition_method")
        or (project_metadata or {}).get("source_mode")
        or (raw_json or {}).get("acquisition_method")
    )
    if acquisition_method in {
        "web_static",
        "web_browser",
        "web_json",
        "manual_web",
        "dom",
        "reddit_api",
    }:
        return str(acquisition_method)
    return "reddit_api"
