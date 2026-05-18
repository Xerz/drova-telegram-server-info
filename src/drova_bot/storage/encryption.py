"""Token encryption helpers."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptor:
    """Fernet-backed encryption for Drova proxy tokens at rest."""

    def __init__(self, secret_key: str) -> None:
        self._fernet = Fernet(secret_key.encode("ascii"))

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("ascii")

    def encrypt(self, token: str) -> bytes:
        return self._fernet.encrypt(token.encode("utf-8"))

    def decrypt(self, payload: bytes) -> str:
        try:
            return self._fernet.decrypt(payload).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("stored token cannot be decrypted") from exc

