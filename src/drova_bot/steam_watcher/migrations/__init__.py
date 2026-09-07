"""Independent packaged Alembic history for the Steam watcher."""

from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


def run_migrations(database_url: str) -> None:
    url = make_url(database_url)
    if url.database and url.database != ":memory:":
        Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(resources.files(__package__)))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
