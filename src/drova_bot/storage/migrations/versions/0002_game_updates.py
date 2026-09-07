"""Durable Steam subscriptions, feed cursor and digest delivery."""

import sqlalchemy as sa
from alembic import op

revision = "0002_game_updates"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "update_feed",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cursor", sa.String(100)),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.Float()),
    )
    op.create_table(
        "update_subscriptions",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "accepted_updates",
        sa.Column("stream_id", sa.String(36), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "pending_updates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("stream_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("job_id", sa.String(36)),
        sa.UniqueConstraint("chat_id", "stream_id", "seq", name="uq_pending_event"),
    )
    op.create_index("ix_pending_updates_chat_id", "pending_updates", ["chat_id"])
    op.create_index("ix_pending_updates_job_id", "pending_updates", ["job_id"])
    op.create_table(
        "update_digest_parts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.Float(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
    )
    op.create_index("ix_update_digest_parts_chat_id", "update_digest_parts", ["chat_id"])


def downgrade() -> None:
    for table in [
        "update_digest_parts",
        "pending_updates",
        "accepted_updates",
        "update_subscriptions",
        "update_feed",
    ]:
        op.drop_table(table)
