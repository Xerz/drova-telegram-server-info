"""Initial watcher metadata and append-only journal."""

import sqlalchemy as sa
from alembic import op

revision = "0001_watcher"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watcher_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.String(36), nullable=False),
        sa.Column("catalog_updated_at", sa.Float()),
        sa.Column("checked_at", sa.Float()),
    )
    op.create_table(
        "watched_apps",
        sa.Column("appid", sa.Integer(), primary_key=True),
        sa.Column("branch", sa.String(32), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("buildid", sa.String(64)),
        sa.Column("last_success_at", sa.Float()),
        sa.Column("error_code", sa.String(64)),
    )
    op.create_table(
        "watcher_events",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("appid", sa.Integer(), nullable=False),
        sa.Column("branch", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("previous_buildid", sa.String(64), nullable=False),
        sa.Column("buildid", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.Float(), nullable=False),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    op.drop_table("watcher_events")
    op.drop_table("watched_apps")
    op.drop_table("watcher_meta")
