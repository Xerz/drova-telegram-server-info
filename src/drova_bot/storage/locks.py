"""Shared per-chat locks for settings, credential changes and notification delivery."""

import asyncio
from weakref import WeakValueDictionary

_CHAT_LOCKS: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


def chat_lock(chat_id: int) -> asyncio.Lock:
    lock = _CHAT_LOCKS.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _CHAT_LOCKS[chat_id] = lock
    return lock
