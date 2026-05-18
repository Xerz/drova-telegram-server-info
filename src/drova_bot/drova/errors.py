"""Typed errors raised by Drova integration and application services."""

from __future__ import annotations


class DrovaError(Exception):
    """Base class for user-safe Drova failures."""


class UserNotConnected(DrovaError):
    """The current chat has no saved Drova token."""


class InvalidUserInput(DrovaError):
    """A command argument or callback payload is invalid."""


class DrovaUnauthorized(DrovaError):
    """The token is invalid and renewal did not recover the request."""


class DrovaUnavailable(DrovaError):
    """Drova is unavailable, timed out, or returned malformed data."""


class DrovaPermissionDenied(DrovaError):
    """Drova rejected the operation for permission reasons."""


class TelegramDeliveryFailed(DrovaError):
    """Telegram send/edit failed after fallback."""


class ExportTooLarge(DrovaError):
    """Export exceeds configured limits."""

