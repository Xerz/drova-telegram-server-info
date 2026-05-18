"""SQLAlchemy async database models and helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from drova_bot.domain.models import DEFAULT_SESSION_LIMIT, DEFAULT_TIMEZONE


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    pass


class ChatProfileRow(Base):
    __tablename__ = "chat_profiles"
    __table_args__ = (
        CheckConstraint(
            "session_limit >= 1 AND session_limit <= 100",
            name="ck_session_limit_range",
        ),
    )

    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    drova_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_proxy_token: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    selected_station_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_SESSION_LIMIT,
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_TIMEZONE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class StationCacheRow(Base):
    __tablename__ = "station_cache"
    __table_args__ = (
        UniqueConstraint("telegram_chat_id", "station_id", name="uq_station_cache_chat_station"),
    )

    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_profiles.telegram_chat_id", ondelete="CASCADE"),
        primary_key=True,
    )
    station_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    station_name: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class ProductCacheRow(Base):
    __tablename__ = "product_cache"

    product_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class ExportJobRow(Base):
    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


def create_database_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(database_url, echo=echo)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
