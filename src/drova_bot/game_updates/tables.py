"""Notification tables in the bot database (never mounted into the watcher)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from drova_bot.storage.database import Base


class UpdateFeedRow(Base):
    __tablename__ = "update_feed"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cursor: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[str] = mapped_column(Text, default='{"games":[]}')
    fetched_at: Mapped[float | None] = mapped_column(Float)


class UpdateSubscriptionRow(Base):
    __tablename__ = "update_subscriptions"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class AcceptedUpdateRow(Base):
    __tablename__ = "accepted_updates"
    stream_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class PendingUpdateRow(Base):
    __tablename__ = "pending_updates"
    __table_args__ = (UniqueConstraint("chat_id", "stream_id", "seq", name="uq_pending_event"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    stream_id: Mapped[str] = mapped_column(String(36))
    seq: Mapped[int] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(String(36), index=True)


class DigestPartRow(Base):
    __tablename__ = "update_digest_parts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[float] = mapped_column(Float)
    part_number: Mapped[int] = mapped_column(Integer)
