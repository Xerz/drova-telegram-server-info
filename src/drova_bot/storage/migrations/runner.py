"""Programmatic Alembic migration runner."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


def run_migrations(database_url: str) -> None:
    """Upgrade the configured database to the latest packaged migration."""
    _ensure_sqlite_parent(database_url)
    config = Config()
    script_location = resources.files("drova_bot.storage.migrations")
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
