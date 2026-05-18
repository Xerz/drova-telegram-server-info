"""Repository implementations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from drova_bot.domain.formatters import normalize_session_limit
from drova_bot.domain.models import DEFAULT_TIMEZONE, ChatProfile
from drova_bot.storage.database import ChatProfileRow
from drova_bot.storage.encryption import TokenEncryptor


class ChatProfileRepository:
    def __init__(self, session: AsyncSession, encryptor: TokenEncryptor | None = None) -> None:
        self._session = session
        self._encryptor = encryptor

    async def get(self, telegram_chat_id: int) -> ChatProfile | None:
        row = await self._session.get(ChatProfileRow, telegram_chat_id)
        if row is None:
            return None
        return self._to_domain(row)

    async def get_or_create(self, telegram_chat_id: int) -> ChatProfile:
        row = await self._session.get(ChatProfileRow, telegram_chat_id)
        if row is None:
            row = ChatProfileRow(
                telegram_chat_id=telegram_chat_id,
                session_limit=normalize_session_limit(None),
                timezone=DEFAULT_TIMEZONE,
            )
            self._session.add(row)
            await self._session.flush()
        return self._to_domain(row)

    async def connect_token(
        self,
        telegram_chat_id: int,
        *,
        drova_user_id: str,
        proxy_token: str,
    ) -> ChatProfile:
        row = await self._get_or_create_row(telegram_chat_id)
        row.drova_user_id = drova_user_id
        row.encrypted_proxy_token = self._encrypt(proxy_token)
        await self._session.flush()
        return self._to_domain(row)

    async def update_token(self, telegram_chat_id: int, proxy_token: str) -> None:
        row = await self._get_or_create_row(telegram_chat_id)
        row.encrypted_proxy_token = self._encrypt(proxy_token)
        await self._session.flush()

    async def set_selected_station(
        self,
        telegram_chat_id: int,
        station_id: str | None,
    ) -> ChatProfile:
        row = await self._get_or_create_row(telegram_chat_id)
        row.selected_station_id = station_id
        await self._session.flush()
        return self._to_domain(row)

    async def set_session_limit(self, telegram_chat_id: int, limit: int) -> ChatProfile:
        row = await self._get_or_create_row(telegram_chat_id)
        row.session_limit = normalize_session_limit(limit)
        await self._session.flush()
        return self._to_domain(row)

    async def logout(self, telegram_chat_id: int) -> ChatProfile:
        row = await self._get_or_create_row(telegram_chat_id)
        row.drova_user_id = None
        row.encrypted_proxy_token = None
        row.selected_station_id = None
        await self._session.flush()
        return self._to_domain(row)

    async def decrypt_token(self, telegram_chat_id: int) -> str | None:
        if self._encryptor is None:
            raise RuntimeError("TokenEncryptor is required to decrypt tokens")
        row = await self._session.get(ChatProfileRow, telegram_chat_id)
        if row is None or row.encrypted_proxy_token is None:
            return None
        return self._encryptor.decrypt(row.encrypted_proxy_token)

    async def _get_or_create_row(self, telegram_chat_id: int) -> ChatProfileRow:
        row = await self._session.get(ChatProfileRow, telegram_chat_id)
        if row is None:
            row = ChatProfileRow(
                telegram_chat_id=telegram_chat_id,
                session_limit=normalize_session_limit(None),
                timezone=DEFAULT_TIMEZONE,
            )
            self._session.add(row)
            await self._session.flush()
        return row

    def _encrypt(self, token: str) -> bytes:
        if self._encryptor is None:
            raise RuntimeError("TokenEncryptor is required to store tokens")
        return self._encryptor.encrypt(token)

    @staticmethod
    def _to_domain(row: ChatProfileRow) -> ChatProfile:
        return ChatProfile(
            telegram_chat_id=row.telegram_chat_id,
            drova_user_id=row.drova_user_id,
            encrypted_proxy_token=row.encrypted_proxy_token,
            selected_station_id=row.selected_station_id,
            session_limit=row.session_limit,
            timezone=row.timezone,
        )
