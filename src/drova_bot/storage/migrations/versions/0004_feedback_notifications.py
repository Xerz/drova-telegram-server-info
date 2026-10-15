"""Opt-in feedback baselines and recoverable Telegram message parts."""

import sqlalchemy as sa
from alembic import op

revision = "0004_feedback_notifications"
down_revision = "0003_platform_updates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_subscriptions",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("account_id", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("initialized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suspended", sa.String(32)),
        sa.Column("example_text", sa.Text()),
        sa.Column("last_poll_at", sa.Float()),
        sa.Column("last_success_at", sa.Float()),
    )
    op.create_table(
        "feedback_seen",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("account_id", sa.String(255), primary_key=True),
        sa.Column("session_id", sa.String(255), primary_key=True),
    )
    op.create_table(
        "feedback_parts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.String(255), nullable=False),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "chat_id", "account_id", "session_id", "part_number", name="uq_feedback_part"
        ),
    )
    op.create_index("ix_feedback_parts_chat_id", "feedback_parts", ["chat_id"])


def downgrade() -> None:
    for table in ("feedback_parts", "feedback_seen", "feedback_subscriptions"):
        op.drop_table(table)
