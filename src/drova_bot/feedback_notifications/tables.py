"""Durable feedback state in the bot database."""

from sqlalchemy import BigInteger, Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from drova_bot.storage.database import Base


class FeedbackSubscriptionRow(Base):
    __tablename__ = "feedback_subscriptions"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    initialized: Mapped[bool] = mapped_column(Boolean, default=False)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    suspended: Mapped[str | None] = mapped_column(String(32), nullable=True)
    example_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_poll_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_success_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class FeedbackSeenRow(Base):
    __tablename__ = "feedback_seen"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)


class FeedbackPartRow(Base):
    __tablename__ = "feedback_parts"
    __table_args__ = (
        UniqueConstraint(
            "chat_id", "account_id", "session_id", "part_number", name="uq_feedback_part"
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    account_id: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str] = mapped_column(String(255))
    part_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[float] = mapped_column(Float)
