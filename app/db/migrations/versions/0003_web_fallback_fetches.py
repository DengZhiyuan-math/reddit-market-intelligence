"""Add web fallback fetch provenance.

Revision ID: 0003_web_fallback_fetches
Revises: 0002_discovered_urls
Create Date: 2026-05-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.db.models import POSTGRES_JSON

revision: str = "0003_web_fallback_fetches"
down_revision: str | None = "0002_discovered_urls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_fallback_fetches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("research_projects.id"), nullable=False),
        sa.Column("discovered_url_id", sa.Integer(), sa.ForeignKey("discovered_urls.id")),
        sa.Column("acquisition_method", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("content_available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("risk_flags", POSTGRES_JSON, nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("metadata_json", POSTGRES_JSON, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("web_fallback_fetches")
