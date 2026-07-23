"""Add source mode provenance columns.

Revision ID: 0004_source_mode_provenance
Revises: 0003_web_fallback_fetches
Create Date: 2026-05-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_source_mode_provenance"
down_revision: str | None = "0003_web_fallback_fetches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("source_mode", sa.String(length=64), nullable=False, server_default="reddit_api"),
    )
    op.add_column(
        "market_signals",
        sa.Column("source_mode", sa.String(length=64), nullable=False, server_default="reddit_api"),
    )


def downgrade() -> None:
    op.drop_column("market_signals", "source_mode")
    op.drop_column("content_items", "source_mode")
