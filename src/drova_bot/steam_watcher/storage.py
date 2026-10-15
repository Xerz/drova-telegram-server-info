"""Atomic, append-only observations shared by independent provider loops."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Float, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from drova_bot.game_updates.models import (
    EventPage,
    GameFeed,
    ProviderStatus,
    UpdateEvent,
    UpdateObject,
    object_id,
)


class WatcherBase(DeclarativeBase):
    pass


class WatcherMeta(WatcherBase):
    __tablename__ = "watcher_meta"
    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(36))
    catalog_updated_at: Mapped[float | None] = mapped_column(Float)
    checked_at: Mapped[float | None] = mapped_column(Float)


class ObjectRow(WatcherBase):
    __tablename__ = "update_objects"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[str] = mapped_column(Text)


class JournalRow(WatcherBase):
    __tablename__ = "update_journal"
    __table_args__ = {"sqlite_autoincrement": True}  # noqa: RUF012
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payload: Mapped[str] = mapped_column(Text)


class StatusRow(WatcherBase):
    __tablename__ = "provider_status"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class CursorConflict(Exception):
    def __init__(self, next_cursor: str) -> None:
        self.next_cursor = next_cursor
        super().__init__("watcher_stream_reset")


def timestamp(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value is not None else None


class WatcherStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_async_engine(database_url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        from drova_bot.steam_watcher.migrations import run_migrations

        await asyncio.to_thread(run_migrations, self.database_url)
        async with self.sessions.begin() as session:
            if await session.get(WatcherMeta, 1) is None:
                session.add(WatcherMeta(id=1, stream_id=str(uuid4())))

    async def close(self) -> None:
        await self.engine.dispose()

    async def replace_games(self, games: list[UpdateObject], now: datetime) -> None:
        if not games:
            raise ValueError("empty_steam_catalog")
        await self.replace_objects(games, now, provider="steam")

    async def replace_objects(
        self,
        objects: list[UpdateObject],
        now: datetime,
        *,
        provider: str | None = None,
        unmapped: dict[str, int] | None = None,
    ) -> None:
        async with self._lock, self.sessions.begin() as session:
            query = select(ObjectRow)
            if provider:
                query = query.where(ObjectRow.provider == provider)
            rows = {r.id: r for r in (await session.scalars(query)).all()}
            active = {o.id for o in objects}
            for existing in rows.values():
                if existing.id not in active:
                    existing.active = False
            for obj in objects:
                row = rows.get(obj.id)
                if row is None:
                    session.add(
                        ObjectRow(
                            id=obj.id,
                            provider=obj.provider,
                            active=True,
                            payload=obj.model_dump_json(),
                        )
                    )
                else:
                    if row.active:
                        old = UpdateObject.model_validate_json(row.payload)
                        obj = obj.model_copy(
                            update={
                                k: getattr(old, k)
                                for k in ("buildid", "version", "last_success_at", "error_code")
                            }
                        )
                    row.active = True
                    row.payload = obj.model_dump_json()
            meta = await session.get(WatcherMeta, 1)
            assert meta
            meta.catalog_updated_at = now.timestamp()
            for name, count in (unmapped or {}).items():
                row_status = await session.get(StatusRow, name)
                status = (
                    ProviderStatus.model_validate_json(row_status.payload)
                    if row_status
                    else ProviderStatus()
                )
                status.unmapped = count
                if row_status:
                    row_status.payload = status.model_dump_json()
                else:
                    session.add(StatusRow(id=name, payload=status.model_dump_json()))

    async def observe(
        self, ident: str | int, buildid: str, now: datetime, *, version: str | None = None
    ) -> None:
        ident = object_id(ident)
        if (
            not buildid
            or len(buildid) > 256
            or (
                ident.startswith("steam:")
                and (not buildid.isascii() or not buildid.isdecimal() or int(buildid) <= 0)
            )
        ):
            raise ValueError("invalid_buildid")
        async with self._lock, self.sessions.begin() as session:
            row = await session.get(ObjectRow, ident)
            if row is None or not row.active:
                return
            obj = UpdateObject.model_validate_json(row.payload)
            if obj.buildid is not None and obj.buildid != buildid:
                meta = await session.get(WatcherMeta, 1)
                assert meta
                event_data = obj.model_dump()
                event_data.update(
                    stream_id=meta.stream_id,
                    seq=1,
                    previous_buildid=obj.buildid,
                    buildid=buildid,
                    version=version,
                    observed_at=now,
                    branch=obj.channel,
                )
                event = UpdateEvent.model_validate(event_data)
                journal = JournalRow(payload="{}")
                session.add(journal)
                await session.flush()
                event.seq = journal.seq
                journal.payload = event.model_dump_json()
            obj.buildid, obj.version, obj.last_success_at, obj.error_code = (
                buildid,
                version,
                now,
                None,
            )
            row.payload = obj.model_dump_json()

    async def record_error(self, ident: str | int, code: str) -> None:
        async with self._lock, self.sessions.begin() as session:
            row = await session.get(ObjectRow, object_id(ident))
            if row and row.active:
                obj = UpdateObject.model_validate_json(row.payload)
                obj.error_code = code
                row.payload = obj.model_dump_json()

    async def mark_checked(
        self, now: datetime, provider: str = "steam", error_code: str | None = None
    ) -> None:
        async with self._lock, self.sessions.begin() as session:
            meta = await session.get(WatcherMeta, 1)
            assert meta
            meta.checked_at = now.timestamp()
            row = await session.get(StatusRow, provider)
            status = ProviderStatus.model_validate_json(row.payload) if row else ProviderStatus()
            status.checked_at, status.error_code = now, error_code
            if row:
                row.payload = status.model_dump_json()
            else:
                session.add(StatusRow(id=provider, payload=status.model_dump_json()))

    async def games(self) -> GameFeed:
        async with self.sessions() as session:
            meta = await session.get(WatcherMeta, 1)
            assert meta
            objects = [
                UpdateObject.model_validate_json(r.payload)
                for r in (await session.scalars(select(ObjectRow).where(ObjectRow.active))).all()
            ]
            statuses = {
                r.id: ProviderStatus.model_validate_json(r.payload)
                for r in (await session.scalars(select(StatusRow))).all()
            }
            for obj in objects:
                status = statuses.setdefault(obj.provider, ProviderStatus())
                if obj.coverage == "full":
                    status.total += 1
                    status.covered += int(obj.buildid is not None and obj.error_code is None)
            return GameFeed(
                games=sorted(
                    [o for o in objects if o.kind == "game"],
                    key=lambda o: (o.title.casefold(), o.id),
                ),
                objects=objects,
                providers=statuses,
                catalog_updated_at=timestamp(meta.catalog_updated_at),
                checked_at=timestamp(meta.checked_at),
            )

    async def events(self, cursor: str | None = None, limit: int = 500) -> EventPage:
        if not 1 <= limit <= 500:
            raise ValueError("invalid_limit")
        async with self.sessions() as session:
            meta = await session.get(WatcherMeta, 1)
            assert meta
            position = 0
            if cursor is not None:
                try:
                    stream, number = cursor.split(":")
                    UUID(stream)
                    if not number.isascii() or not number.isdecimal():
                        raise ValueError("invalid_cursor")
                    position = int(number)
                except (ValueError, AttributeError) as exc:
                    raise ValueError("invalid_cursor") from exc
                maximum = await session.scalar(select(func.max(JournalRow.seq))) or 0
                if stream != meta.stream_id or position > maximum:
                    raise CursorConflict(f"{meta.stream_id}:0")
            rows = (
                await session.scalars(
                    select(JournalRow)
                    .where(JournalRow.seq > position)
                    .order_by(JournalRow.seq)
                    .limit(limit + 1)
                )
            ).all()
            events = [UpdateEvent.model_validate_json(r.payload) for r in rows[:limit]]
            last = events[-1].seq if events else position
            return EventPage(
                events=events, next_cursor=f"{meta.stream_id}:{last}", has_more=len(rows) > limit
            )
