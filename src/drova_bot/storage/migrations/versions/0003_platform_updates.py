"""Upgrade persisted Steam identities without disturbing delivery state or cursors."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0003_platform_updates"
down_revision = "0002_game_updates"
branch_labels = None
depends_on = None


def identity(data: dict) -> dict:
    if data.get("appid") and not data.get("id"):
        data.update(
            id=f"steam:{data['appid']}",
            provider="steam",
            external_id=str(data["appid"]),
            news_url=f"https://store.steampowered.com/news/app/{data['appid']}",
        )
    return data


def upgrade() -> None:
    conn = op.get_bind()
    for name, keys in [
        ("accepted_updates", ["stream_id", "seq"]),
        ("pending_updates", ["id"]),
        ("update_feed", ["id"]),
        ("update_subscriptions", ["chat_id"]),
    ]:
        table = sa.table(name, *(sa.column(k) for k in keys), sa.column("payload"))
        for row in conn.execute(sa.select(table)).mappings():
            data = json.loads(row["payload"])
            if name == "update_subscriptions":
                data["selected"] = {
                    f"steam:{k}" if str(k).isdecimal() else k: v
                    for k, v in data.get("selected", {}).items()
                }
            elif name == "update_feed":
                data["games"] = [identity(g) for g in data.get("games", [])]
            else:
                identity(data)
            query = table.update()
            for k in keys:
                query = query.where(table.c[k] == row[k])
            conn.execute(query.values(payload=json.dumps(data)))


def downgrade() -> None:
    raise RuntimeError("Restore a coordinated pre-migration backup")
