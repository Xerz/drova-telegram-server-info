"""Atomic baselines, guarded credentials and durable delivery parts."""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drova_bot.domain.models import CatalogProduct, Station
from drova_bot.feedback_notifications.models import (
    DeliveryPart,
    FeedbackSettings,
    PollContext,
    StaleFeedbackContext,
)
from drova_bot.feedback_notifications.tables import (
    FeedbackPartRow,
    FeedbackSeenRow,
    FeedbackSubscriptionRow,
)
from drova_bot.storage.database import ChatProfileRow
from drova_bot.storage.encryption import TokenEncryptor
from drova_bot.storage.locks import chat_lock
from drova_bot.storage.repositories import ProductCacheRepository, StationCacheRepository


async def reset_feedback(session: AsyncSession, chat_id: int) -> None:
    for table in (FeedbackPartRow, FeedbackSeenRow, FeedbackSubscriptionRow):
        await session.execute(delete(table).where(table.chat_id == chat_id))


async def feedback_credentials_changed(
    session: AsyncSession, chat_id: int, account_id: str
) -> None:
    row = await session.get(FeedbackSubscriptionRow, chat_id)
    if row is None:
        return
    if row.account_id != account_id:
        await reset_feedback(session, chat_id)
    else:
        row.generation += 1
        if row.suspended == "auth":
            row.suspended = None


class FeedbackStore:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], encryptor: TokenEncryptor
    ) -> None:
        self.session_factory = session_factory
        self.encryptor = encryptor
        self._write_lock = asyncio.Lock()

    async def connected(self, chat_id: int) -> bool:
        async with self.session_factory() as session:
            row = await session.get(ChatProfileRow, chat_id)
            return bool(row and row.drova_user_id and row.encrypted_proxy_token)

    async def settings(self, chat_id: int) -> FeedbackSettings:
        async with self.session_factory() as session:
            row = await session.get(FeedbackSubscriptionRow, chat_id)
            return (
                FeedbackSettings(
                    row.enabled, row.initialized, row.generation, row.suspended, row.example_text
                )
                if row
                else FeedbackSettings()
            )

    async def set_enabled(self, chat_id: int, enabled: bool) -> FeedbackSettings:
        async with chat_lock(chat_id), self._write_lock, self.session_factory.begin() as session:
            profile = await session.get(ChatProfileRow, chat_id)
            if not profile or not profile.drova_user_id or not profile.encrypted_proxy_token:
                return FeedbackSettings()
            row = await session.get(FeedbackSubscriptionRow, chat_id)
            if row is None:
                row = FeedbackSubscriptionRow(
                    chat_id=chat_id,
                    account_id=profile.drova_user_id,
                    enabled=False,
                    initialized=False,
                    generation=0,
                )
                session.add(row)
            if row.enabled != enabled or (enabled and row.suspended):
                row.enabled, row.initialized, row.suspended = enabled, False, None
                row.generation += 1
                await session.execute(
                    delete(FeedbackPartRow).where(
                        FeedbackPartRow.chat_id == chat_id, FeedbackPartRow.status == "pending"
                    )
                )
        return await self.settings(chat_id)

    async def eligible_chats(self) -> list[int]:
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(FeedbackSubscriptionRow.chat_id)
                    .join(
                        ChatProfileRow,
                        ChatProfileRow.telegram_chat_id == FeedbackSubscriptionRow.chat_id,
                    )
                    .where(
                        FeedbackSubscriptionRow.enabled.is_(True),
                        FeedbackSubscriptionRow.suspended.is_(None),
                        ChatProfileRow.drova_user_id == FeedbackSubscriptionRow.account_id,
                        ChatProfileRow.encrypted_proxy_token.is_not(None),
                    )
                )
            )

    async def begin_poll(self, chat_id: int, now: datetime) -> PollContext | None:
        async with chat_lock(chat_id), self._write_lock, self.session_factory.begin() as session:
            row = await session.get(FeedbackSubscriptionRow, chat_id)
            profile = await session.get(ChatProfileRow, chat_id)
            if not row or not profile or not row.enabled or row.suspended:
                return None
            if not profile.encrypted_proxy_token or profile.drova_user_id != row.account_id:
                return None
            if row.last_poll_at is not None and now.timestamp() - row.last_poll_at < 60:
                return None
            row.last_poll_at = now.timestamp()
            return PollContext(
                chat_id,
                row.account_id,
                row.generation,
                profile.encrypted_proxy_token,
                profile.timezone,
            )

    @staticmethod
    async def _current(session: AsyncSession, ctx: PollContext) -> FeedbackSubscriptionRow | None:
        row = await session.get(FeedbackSubscriptionRow, ctx.chat_id)
        profile = await session.get(ChatProfileRow, ctx.chat_id)
        if (
            row
            and profile
            and row.enabled
            and not row.suspended
            and row.account_id == ctx.account_id
            and row.generation == ctx.generation
            and profile.drova_user_id == ctx.account_id
            and profile.encrypted_proxy_token == ctx.encrypted_token
        ):
            return row
        return None

    async def persist_token(self, ctx: PollContext, token: str) -> None:
        async with (
            chat_lock(ctx.chat_id),
            self._write_lock,
            self.session_factory.begin() as session,
        ):
            if await self._current(session, ctx) is None:
                raise StaleFeedbackContext()
            encrypted = self.encryptor.encrypt(token)
            await session.execute(
                update(ChatProfileRow)
                .where(
                    ChatProfileRow.telegram_chat_id == ctx.chat_id,
                    ChatProfileRow.drova_user_id == ctx.account_id,
                    ChatProfileRow.encrypted_proxy_token == ctx.encrypted_token,
                )
                .values(encrypted_proxy_token=encrypted)
            )
        ctx.encrypted_token = encrypted

    async def names(self, chat_id: int) -> tuple[dict[str, str], dict[str, str]]:
        async with self.session_factory() as session:
            return (
                await StationCacheRepository(session).station_names(chat_id),
                await ProductCacheRepository(session).title_map(),
            )

    async def cache_names(
        self, ctx: PollContext, stations: Sequence[Station], products: Sequence[CatalogProduct]
    ) -> None:
        async with (
            chat_lock(ctx.chat_id),
            self._write_lock,
            self.session_factory.begin() as session,
        ):
            if await self._current(session, ctx) is None:
                return
            if stations:
                await StationCacheRepository(session).replace_for_chat(ctx.chat_id, stations)
            if products:
                await ProductCacheRepository(session).upsert_catalog(products)

    async def ingest(
        self,
        ctx: PollContext,
        messages: Mapping[str, list[str]],
        example_text: str | None,
        now: datetime,
    ) -> int:
        async with (
            chat_lock(ctx.chat_id),
            self._write_lock,
            self.session_factory.begin() as session,
        ):
            row = await self._current(session, ctx)
            if row is None:
                return 0
            seen = set(
                await session.scalars(
                    select(FeedbackSeenRow.session_id).where(
                        FeedbackSeenRow.chat_id == ctx.chat_id,
                        FeedbackSeenRow.account_id == ctx.account_id,
                    )
                )
            )
            count = 0
            for session_id, parts in messages.items():
                if session_id in seen:
                    continue
                session.add(
                    FeedbackSeenRow(
                        chat_id=ctx.chat_id, account_id=ctx.account_id, session_id=session_id
                    )
                )
                if not row.initialized:
                    continue
                count += 1
                for index, text in enumerate(parts):
                    session.add(
                        FeedbackPartRow(
                            chat_id=ctx.chat_id,
                            account_id=ctx.account_id,
                            session_id=session_id,
                            part_number=index,
                            text=text,
                            status="pending",
                            attempts=0,
                            next_attempt_at=now.timestamp(),
                        )
                    )
            row.initialized = True
            row.last_success_at = now.timestamp()
            if example_text is not None:
                row.example_text = example_text
            return count

    async def pending(self, chat_id: int) -> list[DeliveryPart]:
        async with self.session_factory() as session:
            sub = await session.get(FeedbackSubscriptionRow, chat_id)
            profile = await session.get(ChatProfileRow, chat_id)
            if not sub or not profile or not sub.enabled or sub.suspended:
                return []
            if profile.drova_user_id != sub.account_id or not profile.encrypted_proxy_token:
                return []
            rows = await session.scalars(
                select(FeedbackPartRow)
                .where(
                    FeedbackPartRow.chat_id == chat_id,
                    FeedbackPartRow.account_id == sub.account_id,
                    FeedbackPartRow.status == "pending",
                )
                .order_by(FeedbackPartRow.id)
            )
            return [DeliveryPart(r.id, r.text, r.next_attempt_at, r.attempts) for r in rows]

    async def complete(self, part_id: int) -> None:
        async with self._write_lock, self.session_factory.begin() as session:
            await session.execute(
                update(FeedbackPartRow).where(FeedbackPartRow.id == part_id).values(status="sent")
            )

    async def retry(self, part_id: int, now: datetime, delay: float) -> None:
        async with self._write_lock, self.session_factory.begin() as session:
            await session.execute(
                update(FeedbackPartRow)
                .where(FeedbackPartRow.id == part_id)
                .values(
                    attempts=FeedbackPartRow.attempts + 1, next_attempt_at=now.timestamp() + delay
                )
            )

    async def suspend(self, chat_id: int, reason: str, ctx: PollContext | None = None) -> None:
        # Caller owns the chat lock during delivery; scanning uses a guarded generation.
        async with self._write_lock, self.session_factory.begin() as session:
            row = await session.get(FeedbackSubscriptionRow, chat_id)
            if ctx is not None and await self._current(session, ctx) is None:
                return
            if row:
                row.suspended = reason
                row.generation += 1
