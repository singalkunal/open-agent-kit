"""In-memory SessionStateStore. Default backend. Single-process only.

Values are deep-copied on put/get to defend against the user mutating the
returned dict and accidentally changing stored state.
"""

from __future__ import annotations

import copy
from typing import Any

import anyio


class InMemoryStateStore:
    """Process-local state store. Loses state on restart.

    Suitable for tests, dev, and single-process deployments. For multi-process, swap in
    ``RedisStateStore`` or ``PostgresStateStore``.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = anyio.Lock()

    async def put(self, session_id: str, key: str, value: dict[str, Any]) -> None:
        async with self._lock:
            self._data.setdefault(session_id, {})[key] = copy.deepcopy(value)

    async def get(self, session_id: str, key: str) -> dict[str, Any] | None:
        async with self._lock:
            session = self._data.get(session_id)
            if session is None:
                return None
            value = session.get(key)
            return copy.deepcopy(value) if value is not None else None

    async def delete_session(self, session_id: str) -> None:
        async with self._lock:
            self._data.pop(session_id, None)


__all__ = ["InMemoryStateStore"]
