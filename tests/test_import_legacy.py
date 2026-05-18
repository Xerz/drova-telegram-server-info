from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from drova_bot.config import Settings
from drova_bot.storage import (
    ChatProfileRepository,
    StationCacheRepository,
    StorageUnitOfWorkFactory,
    TokenEncryptor,
    create_database_engine,
    create_schema,
    make_session_factory,
)
from drova_bot.tools import import_legacy
from drova_bot.tools.import_legacy import import_legacy_payload


def test_import_legacy_payload_imports_profiles_tokens_and_station_cache(tmp_path: Path) -> None:
    encryptor = TokenEncryptor(TokenEncryptor.generate_key())
    engine, uow_factory = _make_uow(tmp_path, encryptor)
    payload = {
        "authTokens": {"10001": "secret-token"},
        "userIDs": {"10001": "user-1"},
        "limits": {"10001": "25"},
        "selectedStations": {"10001": "station-1"},
        "stationNames": {
            "10001": {
                "station-1": "Station One",
                "station-2": "Station Two",
            }
        },
    }

    try:
        result = import_legacy_payload(payload, uow_factory)
        profile, token, station_names = asyncio.run(_read_chat(engine, encryptor, 10001))
    finally:
        asyncio.run(engine.dispose())

    assert result.imported_profiles == 1
    assert result.imported_station_names == 2
    assert result.skipped_chats == 0
    assert result.normalized_limits == 0
    assert profile is not None
    assert profile.drova_user_id == "user-1"
    assert profile.session_limit == 25
    assert profile.selected_station_id == "station-1"
    assert profile.encrypted_proxy_token is not None
    assert b"secret-token" not in profile.encrypted_proxy_token
    assert token == "secret-token"
    assert station_names == {"station-1": "Station One", "station-2": "Station Two"}


def test_import_legacy_payload_skips_bad_records_and_normalizes_limits(tmp_path: Path) -> None:
    encryptor = TokenEncryptor(TokenEncryptor.generate_key())
    engine, uow_factory = _make_uow(tmp_path, encryptor)
    payload = {
        "authTokens": {
            "bad-chat": "bad-token",
            "10002": "secret-token",
            "10003": "incomplete-token",
        },
        "userIDs": {"10002": "user-2"},
        "limits": {"10002": "101", "10004": "10"},
        "selectedStations": {"10002": "unknown-station", "10003": "station-a"},
        "stationNames": {"station-a": "Alpha"},
    }

    try:
        result = import_legacy_payload(payload, uow_factory)
        profile, token, station_names = asyncio.run(_read_chat(engine, encryptor, 10002))
        skipped_profile, _, _ = asyncio.run(_read_chat(engine, encryptor, 10003))
    finally:
        asyncio.run(engine.dispose())

    assert result.imported_profiles == 1
    assert result.imported_station_names == 1
    assert result.skipped_chats == 3
    assert result.normalized_limits == 1
    assert profile is not None
    assert profile.session_limit == 5
    assert profile.selected_station_id is None
    assert token == "secret-token"
    assert station_names == {"station-a": "Alpha"}
    assert skipped_profile is None


def test_import_legacy_payload_reimport_updates_existing_rows(tmp_path: Path) -> None:
    encryptor = TokenEncryptor(TokenEncryptor.generate_key())
    engine, uow_factory = _make_uow(tmp_path, encryptor)
    first_payload = {
        "authTokens": {"10001": "first-token"},
        "userIDs": {"10001": "user-1"},
        "limits": {"10001": "5"},
        "selectedStations": {"10001": "station-1"},
        "stationNames": {"10001": {"station-1": "One"}},
    }
    second_payload = {
        "authTokens": {"10001": "second-token"},
        "userIDs": {"10001": "user-2"},
        "limits": {"10001": "7"},
        "selectedStations": {"10001": "all"},
        "stationNames": {"10001": {"station-2": "Two"}},
    }

    try:
        import_legacy_payload(first_payload, uow_factory)
        result = import_legacy_payload(second_payload, uow_factory)
        profile, token, station_names = asyncio.run(_read_chat(engine, encryptor, 10001))
    finally:
        asyncio.run(engine.dispose())

    assert result.imported_profiles == 1
    assert profile is not None
    assert profile.drova_user_id == "user-2"
    assert profile.session_limit == 7
    assert profile.selected_station_id is None
    assert token == "second-token"
    assert station_names == {"station-2": "Two"}


def test_import_legacy_cli_imports_temp_json_without_leaking_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "drova.sqlite3"
    key = TokenEncryptor.generate_key()
    legacy_path = tmp_path / "persistentData.json"
    legacy_path.write_text(
        json.dumps(
            {
                "authTokens": {"10001": "secret-token"},
                "userIDs": {"10001": "user-1"},
                "stationNames": {"station-1": "Station One"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        import_legacy,
        "Settings",
        lambda: _settings(bot_secret_key=key, database_url=f"sqlite+aiosqlite:///{db_path}"),
    )

    exit_code = import_legacy.main([str(legacy_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "profiles=1" in captured.out
    assert "secret-token" not in captured.out
    assert "secret-token" not in captured.err
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        profile, token, station_names = asyncio.run(
            _read_chat(engine, TokenEncryptor(key), 10001)
        )
    finally:
        asyncio.run(engine.dispose())
    assert profile is not None
    assert token == "secret-token"
    assert station_names == {"station-1": "Station One"}


def test_import_legacy_cli_rejects_missing_or_invalid_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_path = tmp_path / "missing.json"
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")

    assert import_legacy.main([str(missing_path)]) == 1
    assert import_legacy.main([str(invalid_path)]) == 1
    captured = capsys.readouterr()

    assert "Cannot read legacy payload" in captured.err


def test_import_legacy_cli_requires_secret_before_migrations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_path = tmp_path / "persistentData.json"
    legacy_path.write_text(json.dumps({"authTokens": {"10001": "secret-token"}}), encoding="utf-8")
    migrations_called = False

    def fake_run_migrations(database_url: str) -> None:
        nonlocal migrations_called
        migrations_called = True

    monkeypatch.setattr(
        import_legacy,
        "Settings",
        lambda: _settings(bot_secret_key=None, database_url="sqlite+aiosqlite:///:memory:"),
    )
    monkeypatch.setattr(import_legacy, "run_migrations", fake_run_migrations)

    assert import_legacy.main([str(legacy_path)]) == 1
    captured = capsys.readouterr()

    assert not migrations_called
    assert "BOT_SECRET_KEY" in captured.err
    assert "secret-token" not in captured.err


def _make_uow(
    tmp_path: Path,
    encryptor: TokenEncryptor,
) -> tuple[Any, StorageUnitOfWorkFactory]:
    db_path = tmp_path / "drova.sqlite3"
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    asyncio.run(create_schema(engine))
    return engine, StorageUnitOfWorkFactory(make_session_factory(engine), encryptor)


async def _read_chat(
    engine: Any,
    encryptor: TokenEncryptor,
    chat_id: int,
) -> tuple[Any, str | None, dict[str, str]]:
    session_factory = make_session_factory(engine)
    async with session_factory() as session:
        profile_repo = ChatProfileRepository(session, encryptor)
        station_repo = StationCacheRepository(session)
        profile = await profile_repo.get(chat_id)
        token = await profile_repo.decrypt_token(chat_id) if profile is not None else None
        station_names = await station_repo.station_names(chat_id)
        return profile, token, station_names


def _settings(**values: object) -> Settings:
    return Settings.model_validate(values)
