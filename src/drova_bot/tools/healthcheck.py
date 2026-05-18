"""Runtime healthcheck without Drova or Telegram network access."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine import make_url

from drova_bot.config import Settings


class HealthcheckError(RuntimeError):
    pass


def check_health(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    _check_sqlite_path(settings.database_url)


def main() -> None:
    check_health()
    print("ok")


def _check_sqlite_path(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    parent = Path(url.database).expanduser().parent
    if not parent.exists():
        return
    if not parent.is_dir():
        raise HealthcheckError(f"database parent is not a directory: {parent}")
    if not os.access(parent, os.W_OK):
        raise HealthcheckError(f"database parent is not writable: {parent}")


if __name__ == "__main__":
    main()
