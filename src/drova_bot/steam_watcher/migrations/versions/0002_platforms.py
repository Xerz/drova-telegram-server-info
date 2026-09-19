"""Copy Steam baselines and journal into the versioned object schema."""

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0002_platforms"
down_revision = "0001_watcher"
branch_labels = None
depends_on = None


def upgrade() -> None:
    objects = op.create_table(
        "update_objects",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    journal = op.create_table(
        "update_journal",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "provider_status",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    conn = op.get_bind()
    stream = conn.execute(sa.text("SELECT stream_id FROM watcher_meta WHERE id=1")).scalar()
    for row in conn.execute(sa.text("SELECT * FROM watched_apps")).mappings():
        payload = {
            "id": f"steam:{row['appid']}",
            "appid": row["appid"],
            "provider": "steam",
            "external_id": str(row["appid"]),
            "title": row["title"],
            "buildid": row["buildid"],
            "news_url": f"https://store.steampowered.com/news/app/{row['appid']}",
            "error_code": row["error_code"],
            "last_success_at": datetime.fromtimestamp(row["last_success_at"], UTC).isoformat()
            if row["last_success_at"]
            else None,
        }
        conn.execute(
            objects.insert().values(
                id=payload["id"],
                provider="steam",
                active=row["active"],
                payload=json.dumps(payload),
            )
        )
    for row in conn.execute(sa.text("SELECT * FROM watcher_events ORDER BY seq")).mappings():
        payload = dict(row)
        payload.update(
            id=f"steam:{row['appid']}",
            provider="steam",
            external_id=str(row["appid"]),
            stream_id=stream,
            news_url=f"https://store.steampowered.com/news/app/{row['appid']}",
            observed_at=datetime.fromtimestamp(row["observed_at"], UTC).isoformat(),
        )
        conn.execute(journal.insert().values(seq=row["seq"], payload=json.dumps(payload)))


def downgrade() -> None:
    raise RuntimeError("Restore a coordinated pre-migration backup; journal downgrade is unsafe")
