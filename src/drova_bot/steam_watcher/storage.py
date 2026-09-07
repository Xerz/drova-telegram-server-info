"""Watcher-only database. State changes and journal events share one transaction."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Float, Integer, String, Text, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from drova_bot.game_updates.models import EventPage, GameFeed, SteamEvent, SteamGame


class WatcherBase(DeclarativeBase):
    pass


class WatcherMeta(WatcherBase):
    __tablename__ = "watcher_meta"
    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(36))
    catalog_updated_at: Mapped[float | None] = mapped_column(Float)
    checked_at: Mapped[float | None] = mapped_column(Float)


class WatchedApp(WatcherBase):
    __tablename__ = "watched_apps"
    appid: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch: Mapped[str] = mapped_column(String(32), primary_key=True, default="public")
    title: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    buildid: Mapped[str | None] = mapped_column(String(64))
    last_success_at: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(64))


class WatcherEvent(WatcherBase):
    __tablename__ = "watcher_events"
    __table_args__ = {"sqlite_autoincrement": True}  # noqa: RUF012
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appid: Mapped[int] = mapped_column(Integer)
    branch: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    previous_buildid: Mapped[str] = mapped_column(String(64))
    buildid: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[float] = mapped_column(Float)


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

    async def replace_games(self, games: list[SteamGame], now: datetime) -> None:
        if not games:
            raise ValueError("empty_steam_catalog")
        async with self._lock, self.sessions.begin() as session:
            rows = {r.appid: r for r in (await session.scalars(select(WatchedApp))).all()}
            active = {g.appid for g in games}
            for existing in rows.values():
                if existing.appid not in active:
                    existing.active = False
            for game in games:
                row = rows.get(game.appid)
                if row is None:
                    session.add(WatchedApp(appid=game.appid, branch="public", title=game.title))
                else:
                    if not row.active:
                        row.buildid = None
                        row.last_success_at = None
                        row.error_code = None
                    row.active = True
                    row.title = game.title
            await session.execute(
                update(WatcherMeta)
                .where(WatcherMeta.id == 1)
                .values(catalog_updated_at=now.timestamp())
            )

    async def observe(self, appid: int, buildid: str, now: datetime) -> None:
        if not buildid.isascii() or not buildid.isdecimal() or int(buildid) <= 0:
            raise ValueError("invalid_buildid")
        async with self._lock, self.sessions.begin() as session:
            row = await session.get(WatchedApp, (appid, "public"))
            if row is None or not row.active:
                return
            if row.buildid is not None and row.buildid != buildid:
                session.add(
                    WatcherEvent(
                        appid=appid,
                        branch="public",
                        title=row.title,
                        previous_buildid=row.buildid,
                        buildid=buildid,
                        observed_at=now.timestamp(),
                    )
                )
            row.buildid = buildid
            row.last_success_at = now.timestamp()
            row.error_code = None

    async def record_error(self, appid: int, code: str) -> None:
        async with self._lock, self.sessions.begin() as session:
            await session.execute(
                update(WatchedApp).where(WatchedApp.appid == appid).values(error_code=code)
            )

    async def mark_checked(self, now: datetime) -> None:
        async with self._lock, self.sessions.begin() as session:
            await session.execute(
                update(WatcherMeta).where(WatcherMeta.id == 1).values(checked_at=now.timestamp())
            )

    async def games(self) -> GameFeed:
        async with self.sessions() as session:
            meta = await session.get(WatcherMeta, 1)
            assert meta is not None
            rows = (await session.scalars(select(WatchedApp).where(WatchedApp.active))).all()
            return GameFeed(
                games=sorted(
                    [
                        SteamGame(
                            appid=r.appid,
                            title=r.title,
                            buildid=r.buildid,
                            last_success_at=timestamp(r.last_success_at),
                            error_code=r.error_code,
                        )
                        for r in rows
                    ],
                    key=lambda g: (g.title.casefold(), g.appid),
                ),
                catalog_updated_at=timestamp(meta.catalog_updated_at),
                checked_at=timestamp(meta.checked_at),
            )

    async def events(self, cursor: str | None = None, limit: int = 500) -> EventPage:
        if not 1 <= limit <= 500:
            raise ValueError("invalid_limit")
        async with self.sessions() as session:
            meta = await session.get(WatcherMeta, 1)
            assert meta is not None
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
                maximum = await session.scalar(select(func.max(WatcherEvent.seq))) or 0
                if stream != meta.stream_id or position > maximum:
                    raise CursorConflict(f"{meta.stream_id}:0")
            rows = (
                await session.scalars(
                    select(WatcherEvent)
                    .where(WatcherEvent.seq > position)
                    .order_by(WatcherEvent.seq)
                    .limit(limit + 1)
                )
            ).all()
            events = [
                SteamEvent(
                    stream_id=meta.stream_id,
                    seq=r.seq,
                    appid=r.appid,
                    title=r.title,
                    previous_buildid=r.previous_buildid,
                    buildid=r.buildid,
                    observed_at=datetime.fromtimestamp(r.observed_at, UTC),
                )
                for r in rows[:limit]
            ]
            last = events[-1].seq if events else position
            return EventPage(
                events=events, next_cursor=f"{meta.stream_id}:{last}", has_more=len(rows) > limit
            )
