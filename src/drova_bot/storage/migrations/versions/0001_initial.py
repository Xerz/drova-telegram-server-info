"""Initial V2 storage schema."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_profiles",
        sa.Column("telegram_chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("drova_user_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_proxy_token", sa.LargeBinary(), nullable=True),
        sa.Column("selected_station_id", sa.String(length=255), nullable=True),
        sa.Column("session_limit", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "session_limit >= 1 AND session_limit <= 100",
            name="ck_session_limit_range",
        ),
    )
    op.create_table(
        "product_cache",
        sa.Column("product_id", sa.String(length=255), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "station_cache",
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("station_id", sa.String(length=255), nullable=False),
        sa.Column("station_name", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["telegram_chat_id"],
            ["chat_profiles.telegram_chat_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("telegram_chat_id", "station_id"),
        sa.UniqueConstraint("telegram_chat_id", "station_id", name="uq_station_cache_chat_station"),
    )
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_export_jobs_telegram_chat_id", "export_jobs", ["telegram_chat_id"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_telegram_chat_id", table_name="export_jobs")
    op.drop_table("export_jobs")
    op.drop_table("station_cache")
    op.drop_table("product_cache")
    op.drop_table("chat_profiles")

