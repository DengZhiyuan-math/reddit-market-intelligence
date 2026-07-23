"""Add discovered URL search provenance.

Revision ID: 0002_discovered_urls
Revises: 0001_initial_pipeline_schema
Create Date: 2026-05-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.db.models import POSTGRES_JSON

revision: str = "0002_discovered_urls"
down_revision: str | None = "0001_initial_pipeline_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovered_urls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("research_projects.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("pipeline_runs.id"), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="discovered"),
        sa.Column("metadata_json", POSTGRES_JSON, nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "project_id",
            "provider",
            "normalized_url",
            name="uq_discovered_urls_project_provider_url",
        ),
    )
    op.create_index(
        "ix_discovered_urls_project_provider",
        "discovered_urls",
        ["project_id", "provider"],
    )


def downgrade() -> None:
    op.drop_index("ix_discovered_urls_project_provider", table_name="discovered_urls")
    op.drop_table("discovered_urls")
