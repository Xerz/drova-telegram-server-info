"""One-time import from legacy ``persistentData.json`` into V2 storage."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drova_bot.config import Settings
from drova_bot.domain.formatters import normalize_session_limit
from drova_bot.domain.models import (
    DEFAULT_SESSION_LIMIT,
    MAX_SESSION_LIMIT,
    MIN_SESSION_LIMIT,
    Station,
)
from drova_bot.storage import (
    StorageUnitOfWork,
    StorageUnitOfWorkFactory,
    TokenEncryptor,
    create_database_engine,
    make_session_factory,
    run_migrations,
)

UnitOfWorkFactory = Callable[[], StorageUnitOfWork]


@dataclass(frozen=True, slots=True)
class ImportLegacyResult:
    imported_profiles: int
    imported_station_names: int
    skipped_chats: int
    normalized_limits: int


@dataclass(frozen=True, slots=True)
class _LegacyRecord:
    chat_id: int
    token: str
    user_id: str
    limit: int
    selected_station_id: str | None
    station_names: dict[str, str]
    limit_normalized: bool


def import_legacy_payload(
    payload: Mapping[str, object],
    uow_factory: UnitOfWorkFactory,
) -> ImportLegacyResult:
    """Import a parsed legacy payload into storage and return safe counters."""
    return asyncio.run(_import_legacy_payload(payload, uow_factory))


async def _import_legacy_payload(
    payload: Mapping[str, object],
    uow_factory: UnitOfWorkFactory,
) -> ImportLegacyResult:
    legacy = _LegacyPayload(payload)
    imported_profiles = 0
    imported_station_names = 0
    skipped_chats = 0
    normalized_limits = 0

    async with uow_factory() as uow:
        for raw_chat_id in sorted(legacy.chat_keys()):
            record = legacy.record_for(raw_chat_id)
            if record is None:
                skipped_chats += 1
                continue

            await uow.chat_profiles.connect_token(
                record.chat_id,
                drova_user_id=record.user_id,
                proxy_token=record.token,
            )
            await uow.chat_profiles.set_session_limit(record.chat_id, record.limit)
            await uow.station_cache.replace_for_chat(
                record.chat_id,
                _stations_from_names(record.station_names),
            )
            await uow.chat_profiles.set_selected_station(
                record.chat_id,
                record.selected_station_id,
            )
            imported_profiles += 1
            imported_station_names += len(record.station_names)
            if record.limit_normalized:
                normalized_limits += 1

    return ImportLegacyResult(
        imported_profiles=imported_profiles,
        imported_station_names=imported_station_names,
        skipped_chats=skipped_chats,
        normalized_limits=normalized_limits,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Usage: python -m drova_bot.tools.import_legacy persistentData.json", file=sys.stderr)
        return 2

    legacy_path = Path(args[0])
    try:
        payload = _load_payload(legacy_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Cannot read legacy payload: {type(exc).__name__}", file=sys.stderr)
        return 1

    settings = Settings()
    if not settings.bot_secret_key:
        print("Missing required runtime environment: BOT_SECRET_KEY", file=sys.stderr)
        return 1

    try:
        run_migrations(settings.database_url)
        engine = create_database_engine(settings.database_url)
        try:
            session_factory = make_session_factory(engine)
            encryptor = TokenEncryptor(settings.bot_secret_key)
            result = import_legacy_payload(
                payload,
                StorageUnitOfWorkFactory(session_factory, encryptor),
            )
        finally:
            asyncio.run(engine.dispose())
    except Exception as exc:
        print(f"Legacy import failed: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(
        "Legacy import complete: "
        f"profiles={result.imported_profiles}, "
        f"station_names={result.imported_station_names}, "
        f"skipped_chats={result.skipped_chats}, "
        f"normalized_limits={result.normalized_limits}"
    )
    return 0


class _LegacyPayload:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.auth_tokens = _mapping(payload.get("authTokens"))
        self.user_ids = _mapping(payload.get("userIDs"))
        self.limits = _mapping(payload.get("limits"))
        self.selected_stations = _mapping(payload.get("selectedStations"))
        self.station_names = _mapping(payload.get("stationNames"))

    def chat_keys(self) -> set[str]:
        keys = set(self.auth_tokens) | set(self.user_ids) | set(self.limits) | set(
            self.selected_stations
        )
        if _station_names_are_per_chat(self.station_names):
            keys |= set(self.station_names)
        return keys

    def record_for(self, raw_chat_id: str) -> _LegacyRecord | None:
        chat_id = _parse_chat_id(raw_chat_id)
        if chat_id is None:
            return None

        token = _string_value(_lookup(self.auth_tokens, raw_chat_id, chat_id))
        user_id = _string_value(_lookup(self.user_ids, raw_chat_id, chat_id))
        if token is None or user_id is None:
            return None

        raw_limit = _lookup(self.limits, raw_chat_id, chat_id)
        limit = normalize_session_limit(_limit_input(raw_limit))
        station_names = _station_names_for_chat(self.station_names, raw_chat_id, chat_id)
        selected_station_id = _selected_station_id(
            _lookup(self.selected_stations, raw_chat_id, chat_id),
            station_names,
        )
        return _LegacyRecord(
            chat_id=chat_id,
            token=token,
            user_id=user_id,
            limit=limit,
            selected_station_id=selected_station_id,
            station_names=station_names,
            limit_normalized=_limit_was_normalized(raw_limit, limit),
        )


def _load_payload(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("legacy payload root must be an object")
    return payload


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _parse_chat_id(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _lookup(mapping: Mapping[str, object], raw_chat_id: str, chat_id: int) -> object | None:
    if raw_chat_id in mapping:
        return mapping[raw_chat_id]
    return mapping.get(str(chat_id))


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _station_names_are_per_chat(station_names: Mapping[str, object]) -> bool:
    return any(isinstance(value, Mapping) for value in station_names.values())


def _station_names_for_chat(
    station_names: Mapping[str, object],
    raw_chat_id: str,
    chat_id: int,
) -> dict[str, str]:
    per_chat = _lookup(station_names, raw_chat_id, chat_id)
    if isinstance(per_chat, Mapping):
        return _station_name_map(per_chat)
    if _station_names_are_per_chat(station_names):
        return {}
    return _station_name_map(station_names)


def _station_name_map(value: Mapping[Any, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for station_id, station_name in value.items():
        station_id_text = str(station_id).strip()
        station_name_text = _string_value(station_name)
        if station_id_text and station_name_text is not None:
            result[station_id_text] = station_name_text
    return result


def _selected_station_id(value: object, station_names: Mapping[str, str]) -> str | None:
    selected = _string_value(value)
    if selected is None or selected.lower() == "all":
        return None
    if selected not in station_names:
        return None
    return selected


def _stations_from_names(station_names: Mapping[str, str]) -> list[Station]:
    return [
        Station(uuid=station_id, name=name, state="", published=True)
        for station_id, name in station_names.items()
    ]


def _limit_was_normalized(raw_limit: object, limit: int) -> bool:
    if raw_limit is None:
        return False
    try:
        parsed = int(str(raw_limit).strip())
    except (TypeError, ValueError):
        return True
    return parsed != limit or not MIN_SESSION_LIMIT <= parsed <= MAX_SESSION_LIMIT


def _limit_input(raw_limit: object) -> int | str | None:
    if type(raw_limit) is int or isinstance(raw_limit, str):
        return raw_limit
    return None


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_SESSION_LIMIT",
    "ImportLegacyResult",
    "import_legacy_payload",
    "main",
    "normalize_session_limit",
]
