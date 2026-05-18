from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from drova_bot.domain.formatters import normalize_session_limit
from drova_bot.storage import (
    ChatProfileRepository,
    ChatProfileRow,
    TokenEncryptor,
    create_database_engine,
    create_schema,
    make_session_factory,
)


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    db_path = tmp_path / "drova.sqlite3"
    async_engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_schema(async_engine)
    try:
        yield async_engine
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_schema_creates_required_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        tables = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
    assert {"chat_profiles", "station_cache", "product_cache", "export_jobs"} <= tables


@pytest.mark.asyncio
async def test_chat_profile_repository_encrypts_token_and_logs_out(engine: AsyncEngine) -> None:
    session_factory = make_session_factory(engine)
    encryptor = TokenEncryptor(TokenEncryptor.generate_key())

    async with session_factory() as session:
        repo = ChatProfileRepository(session, encryptor)
        profile = await repo.get_or_create(10001)
        assert profile.session_limit == 5
        assert profile.selected_station_id is None

        connected = await repo.connect_token(
            10001,
            drova_user_id="user-1",
            proxy_token="secret-token",
        )
        assert connected.drova_user_id == "user-1"
        assert connected.encrypted_proxy_token is not None
        assert b"secret-token" not in connected.encrypted_proxy_token
        assert await repo.decrypt_token(10001) == "secret-token"

        row = await session.get(ChatProfileRow, 10001)
        assert row is not None
        assert row.encrypted_proxy_token == connected.encrypted_proxy_token

        await repo.set_selected_station(10001, "station-1")
        await repo.set_session_limit(10001, 50)
        logged_out = await repo.logout(10001)
        assert logged_out.drova_user_id is None
        assert logged_out.encrypted_proxy_token is None
        assert logged_out.selected_station_id is None


def test_legacy_limit_normalization() -> None:
    assert normalize_session_limit(42) == 42
    assert normalize_session_limit(101) == 5
    assert normalize_session_limit("not-a-number") == 5
