import json
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from drova_bot.storage.encryption import TokenEncryptor

STREAM = "00000000-0000-0000-0000-000000000001"


def migrate(path: Path, package: str, revision: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path("src/drova_bot") / package / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
    command.upgrade(cfg, revision)


def test_real_watcher_migration_preserves_baseline_sequence_and_stream(tmp_path: Path) -> None:
    path = tmp_path / "watcher.db"
    migrate(path, "steam_watcher", "0001_watcher")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO watcher_meta VALUES (1,?,100,101)", (STREAM,))
        db.execute("INSERT INTO watched_apps VALUES (730,'public','CS2',1,'2',101,NULL)")
        db.execute("INSERT INTO watcher_events VALUES (41,730,'public','CS2','1','2',101)")
    migrate(path, "steam_watcher", "head")
    migrate(path, "steam_watcher", "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT stream_id FROM watcher_meta").fetchone()[0] == STREAM
        state = json.loads(db.execute("SELECT payload FROM update_objects").fetchone()[0])
        assert state["id"] == "steam:730" and state["buildid"] == "2"
        seq, payload = db.execute("SELECT seq,payload FROM update_journal").fetchone()
        assert seq == 41 and json.loads(payload)["seq"] == 41
        db.execute("INSERT INTO update_journal (payload) VALUES ('{}')")
        assert db.execute("SELECT max(seq) FROM update_journal").fetchone()[0] == 42


def test_bot_migration_preserves_profile_cursor_pending_sent_parts(tmp_path: Path) -> None:
    path = tmp_path / "bot.db"
    migrate(path, "storage", "0002_game_updates")
    crypt = TokenEncryptor(TokenEncryptor.generate_key())
    encrypted = crypt.encrypt("test-only-token")
    event = {
        "stream_id": STREAM,
        "seq": 41,
        "appid": 730,
        "title": "CS2",
        "previous_buildid": "1",
        "buildid": "2",
        "observed_at": "2026-09-19T00:00:00Z",
    }
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO chat_profiles (telegram_chat_id,drova_user_id,encrypted_proxy_token,"
            "session_limit,timezone,created_at,updated_at) "
            "VALUES (1,'owner',?,5,'UTC',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (encrypted,),
        )
        db.execute(
            "INSERT INTO update_feed VALUES (1,?,?,100)",
            (f"{STREAM}:41", json.dumps({"games": [{"appid": 730, "title": "CS2"}]})),
        )
        db.execute(
            "INSERT INTO update_subscriptions VALUES (1,?)",
            (json.dumps({"mode": "all", "enabled_since": 1, "selected": {"730": 2}}),),
        )
        db.execute("INSERT INTO accepted_updates VALUES (?,?,?)", (STREAM, 41, json.dumps(event)))
        db.execute(
            "INSERT INTO pending_updates VALUES (1,1,?,41,?,?)",
            (STREAM, json.dumps(event), "pending"),
        )
        for status in ["pending", "sent"]:
            db.execute(
                "INSERT INTO update_digest_parts VALUES (?,1,?,?,0,0,100,0)",
                (status, "immutable text", status),
            )
    migrate(path, "storage", "head")
    migrate(path, "storage", "head")
    with sqlite3.connect(path) as db:
        assert (
            crypt.decrypt(
                db.execute("SELECT encrypted_proxy_token FROM chat_profiles").fetchone()[0]
            )
            == "test-only-token"
        )
        assert db.execute("SELECT cursor FROM update_feed").fetchone()[0] == f"{STREAM}:41"
        sub = json.loads(db.execute("SELECT payload FROM update_subscriptions").fetchone()[0])
        assert sub["mode"] == "all" and sub["selected"] == {"steam:730": 2}
        assert (
            json.loads(db.execute("SELECT payload FROM pending_updates").fetchone()[0])["id"]
            == "steam:730"
        )
        assert db.execute("SELECT job_id FROM pending_updates").fetchone()[0] == "pending"
        assert (
            db.execute(
                "SELECT count(*) FROM update_digest_parts WHERE text=?", ("immutable text",)
            ).fetchone()[0]
            == 2
        )
