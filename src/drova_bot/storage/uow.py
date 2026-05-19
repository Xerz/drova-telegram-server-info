"""Storage unit-of-work helpers."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drova_bot.storage.encryption import TokenEncryptor
from drova_bot.storage.repositories import (
    ChatProfileRepository,
    ExportJobRepository,
    ProductCacheRepository,
    StationCacheRepository,
)


class StorageUnitOfWork:
    """Small async unit of work that groups repositories around one session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        encryptor: TokenEncryptor,
    ) -> None:
        self._session_factory = session_factory
        self._encryptor = encryptor
        self.session: AsyncSession | None = None
        self.chat_profiles: ChatProfileRepository
        self.station_cache: StationCacheRepository
        self.product_cache: ProductCacheRepository
        self.export_jobs: ExportJobRepository

    async def __aenter__(self) -> StorageUnitOfWork:
        self.session = self._session_factory()
        self.chat_profiles = ChatProfileRepository(self.session, self._encryptor)
        self.station_cache = StationCacheRepository(self.session)
        self.product_cache = ProductCacheRepository(self.session)
        self.export_jobs = ExportJobRepository(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.session is None:
            return
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()


class StorageUnitOfWorkFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        encryptor: TokenEncryptor,
    ) -> None:
        self._session_factory = session_factory
        self._encryptor = encryptor

    def __call__(self) -> StorageUnitOfWork:
        return StorageUnitOfWork(self._session_factory, self._encryptor)
