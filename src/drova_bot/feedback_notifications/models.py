"""Small feedback DTOs; no raw API payloads are persisted."""

from dataclasses import dataclass


class StaleFeedbackContext(Exception):
    """A scan no longer belongs to the active account/subscription/credentials."""


@dataclass(frozen=True, slots=True)
class FeedbackSettings:
    enabled: bool = False
    initialized: bool = False
    generation: int = 0
    suspended: str | None = None
    example_text: str | None = None


@dataclass(slots=True)
class PollContext:
    chat_id: int
    account_id: str
    generation: int
    encrypted_token: bytes
    timezone: str


@dataclass(frozen=True, slots=True)
class ClientUsage:
    total_seconds: int
    station_seconds: int
    incomplete: bool


@dataclass(frozen=True, slots=True)
class DeliveryPart:
    id: int
    text: str
    next_attempt_at: float
    attempts: int


def has_feedback(score: int | None, comment: str | None) -> bool:
    return (type(score) is int and 1 <= score <= 5) or bool(comment and comment.strip())
