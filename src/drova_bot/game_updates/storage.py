"""Transactional bot-side event ingestion, subscriptions and durable digest parts."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4
from weakref import WeakValueDictionary

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drova_bot.game_updates.models import EventPage, GameFeed, SteamEvent, Subscription
from drova_bot.game_updates.renderers import MODES, digest_groups
from drova_bot.game_updates.tables import (
    AcceptedUpdateRow,
    DigestPartRow,
    PendingUpdateRow,
    UpdateFeedRow,
    UpdateSubscriptionRow,
)
from drova_bot.storage.database import ChatProfileRow

_CHAT_LOCKS: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


def chat_lock(chat_id: int) -> asyncio.Lock:
    lock = _CHAT_LOCKS.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _CHAT_LOCKS[chat_id] = lock
    return lock


async def reset_notifications(session: AsyncSession, chat_id: int) -> None:
    for table in (PendingUpdateRow, DigestPartRow, UpdateSubscriptionRow):
        await session.execute(delete(table).where(table.chat_id == chat_id))


class NotificationStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._lock = asyncio.Lock()

    @property
    def transaction_lock(self) -> asyncio.Lock:
        """Serialize logout's existing unit of work with ingestion's subscriber snapshot."""
        return self._lock

    async def profile(self, chat_id: int) -> ChatProfileRow | None:
        async with self.session_factory() as session:
            row = await session.get(ChatProfileRow, chat_id)
            return row if row and row.encrypted_proxy_token and row.drova_user_id else None

    async def settings(self, chat_id: int) -> Subscription:
        async with self.session_factory() as session:
            return await self._settings(session, chat_id)

    @staticmethod
    async def _settings(session: AsyncSession, chat_id: int) -> Subscription:
        row = await session.get(UpdateSubscriptionRow, chat_id)
        return Subscription.model_validate_json(row.payload) if row else Subscription()

    @staticmethod
    async def _save(session: AsyncSession, chat_id: int, value: Subscription) -> None:
        row = await session.get(UpdateSubscriptionRow, chat_id)
        if row is None:
            session.add(UpdateSubscriptionRow(chat_id=chat_id, payload=value.model_dump_json()))
        else:
            row.payload = value.model_dump_json()

    @staticmethod
    async def _clear_jobs(session: AsyncSession, chat_id: int) -> None:
        await session.execute(
            update(PendingUpdateRow).where(PendingUpdateRow.chat_id == chat_id).values(job_id=None)
        )
        await session.execute(
            delete(DigestPartRow).where(
                DigestPartRow.chat_id == chat_id, DigestPartRow.status == "pending"
            )
        )

    async def set_mode(self, chat_id: int, mode: str, now: datetime) -> None:
        if mode not in MODES:
            raise ValueError("invalid_subscription_mode")
        async with self._lock, self.session_factory.begin() as session:
            sub = await self._settings(session, chat_id)
            if sub.mode == mode and not sub.suspended:
                return
            sub = sub.model_copy(
                update={
                    "mode": mode,
                    "enabled_since": now.timestamp(),
                    "suspended": False,
                    "last_digest_hour": int(now.timestamp() // 3600),
                }
            )
            await self._clear_jobs(session, chat_id)
            await session.execute(
                delete(PendingUpdateRow).where(PendingUpdateRow.chat_id == chat_id)
            )
            await self._save(session, chat_id, sub)

    async def select(self, chat_id: int, appid: int, selected: bool, now: datetime) -> None:
        async with self._lock, self.session_factory.begin() as session:
            sub = await self._settings(session, chat_id)
            if selected == (appid in sub.selected):
                return
            if selected:
                sub.selected[appid] = now.timestamp()
            else:
                del sub.selected[appid]
                if sub.mode == "selected":
                    await self._clear_jobs(session, chat_id)
                    rows = (
                        await session.scalars(
                            select(PendingUpdateRow).where(PendingUpdateRow.chat_id == chat_id)
                        )
                    ).all()
                    for row in rows:
                        if SteamEvent.model_validate_json(row.payload).appid == appid:
                            await session.delete(row)
                    # Rebuild remaining unsent parts even if this hour was already prepared.
                    sub.last_digest_hour = min(
                        sub.last_digest_hour, int(now.timestamp() // 3600) - 1
                    )
            await self._save(session, chat_id, sub)

    async def search(self, chat_id: int, query: str) -> None:
        async with self._lock, self.session_factory.begin() as session:
            sub = await self._settings(session, chat_id)
            sub.search = query.strip()[:100]
            await self._save(session, chat_id, sub)

    async def suspend(self, chat_id: int) -> None:
        async with self._lock, self.session_factory.begin() as session:
            sub = await self._settings(session, chat_id)
            sub.suspended = True
            await self._save(session, chat_id, sub)

    async def reset(self, chat_id: int) -> None:
        async with self._lock, self.session_factory.begin() as session:
            await reset_notifications(session, chat_id)

    async def replace_feed(self, feed: GameFeed, now: datetime) -> None:
        async with self._lock, self.session_factory.begin() as session:
            row = await session.get(UpdateFeedRow, 1)
            if row is None:
                session.add(
                    UpdateFeedRow(id=1, payload=feed.model_dump_json(), fetched_at=now.timestamp())
                )
            else:
                row.payload, row.fetched_at = feed.model_dump_json(), now.timestamp()

    async def feed(self) -> tuple[GameFeed, float | None]:
        async with self.session_factory() as session:
            row = await session.get(UpdateFeedRow, 1)
            return (
                (GameFeed.model_validate_json(row.payload), row.fetched_at)
                if row
                else (GameFeed(games=[]), None)
            )

    async def cursor(self) -> str | None:
        async with self.session_factory() as session:
            row = await session.get(UpdateFeedRow, 1)
            return row.cursor if row else None

    async def reset_cursor(self, cursor: str) -> None:
        async with self._lock, self.session_factory.begin() as session:
            row = await session.get(UpdateFeedRow, 1)
            if row is None:
                session.add(UpdateFeedRow(id=1, cursor=cursor))
            else:
                row.cursor = cursor

    async def ingest(self, page: EventPage) -> None:
        stream, end = page.next_cursor.split(":")
        end_sequence = int(end)
        if page.events and (
            any(e.stream_id != stream for e in page.events)
            or any(a.seq >= b.seq for a, b in zip(page.events, page.events[1:], strict=False))
            or page.events[-1].seq != end_sequence
        ):
            raise ValueError("invalid_event_page")
        async with self._lock, self.session_factory.begin() as session:
            subscribers = (
                await session.scalars(
                    select(UpdateSubscriptionRow)
                    .join(
                        ChatProfileRow,
                        ChatProfileRow.telegram_chat_id == UpdateSubscriptionRow.chat_id,
                    )
                    .where(
                        ChatProfileRow.encrypted_proxy_token.is_not(None),
                        ChatProfileRow.drova_user_id.is_not(None),
                    )
                )
            ).all()
            settings = [
                (s.chat_id, Subscription.model_validate_json(s.payload)) for s in subscribers
            ]
            for event in page.events:
                if await session.get(AcceptedUpdateRow, (event.stream_id, event.seq)) is not None:
                    continue
                payload = event.model_dump_json()
                session.add(
                    AcceptedUpdateRow(stream_id=event.stream_id, seq=event.seq, payload=payload)
                )
                for chat_id, sub in settings:
                    if sub.accepts(event):
                        session.add(
                            PendingUpdateRow(
                                chat_id=chat_id,
                                stream_id=event.stream_id,
                                seq=event.seq,
                                payload=payload,
                            )
                        )
            feed = await session.get(UpdateFeedRow, 1)
            if feed is None:
                session.add(UpdateFeedRow(id=1, cursor=page.next_cursor))
            else:
                # A retried old page must not move the committed cursor backwards.
                old_stream, _, old_seq = (feed.cursor or ":0").partition(":")
                if old_stream != stream or int(old_seq) <= end_sequence:
                    feed.cursor = page.next_cursor
            await session.flush()

    async def pending(self, chat_id: int) -> list[SteamEvent]:
        async with self.session_factory() as session:
            rows = (
                await session.scalars(
                    select(PendingUpdateRow)
                    .where(PendingUpdateRow.chat_id == chat_id)
                    .order_by(PendingUpdateRow.id)
                )
            ).all()
            return [SteamEvent.model_validate_json(r.payload) for r in rows]

    async def chats(self) -> list[int]:
        async with self.session_factory() as session:
            return list((await session.scalars(select(UpdateSubscriptionRow.chat_id))).all())

    async def prepare(self, chat_id: int, now: datetime) -> list[DigestPartRow]:
        async with self._lock, self.session_factory.begin() as session:
            profile = await session.get(ChatProfileRow, chat_id)
            sub = await self._settings(session, chat_id)
            if not profile or not profile.encrypted_proxy_token or not profile.drova_user_id:
                await reset_notifications(session, chat_id)
                return []
            if sub.mode == "off" or sub.suspended:
                return []
            hour = int(now.timestamp() // 3600)
            if hour > sub.last_digest_hour:
                rows = (
                    await session.scalars(
                        select(PendingUpdateRow).where(
                            PendingUpdateRow.chat_id == chat_id, PendingUpdateRow.job_id.is_(None)
                        )
                    )
                ).all()
                eligible: list[tuple[PendingUpdateRow, SteamEvent]] = []
                for row in rows:
                    event = SteamEvent.model_validate_json(row.payload)
                    if not sub.accepts(event):
                        await session.delete(row)
                    elif event.observed_at.timestamp() < hour * 3600:
                        eligible.append((row, event))
                parts = digest_groups([e for _, e in eligible], profile.timezone)
                for number, (text, appids) in enumerate(parts):
                    job = DigestPartRow(
                        id=str(uuid4()),
                        chat_id=chat_id,
                        text=text,
                        created_at=now.timestamp(),
                        part_number=number,
                    )
                    session.add(job)
                    for row, event in eligible:
                        if event.appid in appids:
                            row.job_id = job.id
                sub.last_digest_hour = hour
                await self._save(session, chat_id, sub)
            await session.flush()
            return list(
                (
                    await session.scalars(
                        select(DigestPartRow)
                        .where(DigestPartRow.chat_id == chat_id, DigestPartRow.status == "pending")
                        .order_by(DigestPartRow.created_at, DigestPartRow.part_number)
                    )
                ).all()
            )

    async def complete(self, job_id: str) -> None:
        async with self._lock, self.session_factory.begin() as session:
            await session.execute(
                update(DigestPartRow).where(DigestPartRow.id == job_id).values(status="sent")
            )
            await session.execute(delete(PendingUpdateRow).where(PendingUpdateRow.job_id == job_id))

    async def retry(self, job_id: str, now: datetime, delay: float) -> None:
        async with self._lock, self.session_factory.begin() as session:
            await session.execute(
                update(DigestPartRow)
                .where(DigestPartRow.id == job_id)
                .values(
                    attempts=DigestPartRow.attempts + 1, next_attempt_at=now.timestamp() + delay
                )
            )
