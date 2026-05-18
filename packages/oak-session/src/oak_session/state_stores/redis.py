"""Redis-backed SessionStateStore.

Import-guarded under the ``[redis]`` extra. Values are JSON-encoded under
``oak:session:<session_id>:<key>``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis

_KEY_PREFIX = "oak:session"
_INDEX_PREFIX = "oak:session:index"


def _key(session_id: str, key: str) -> str:
    return f"{_KEY_PREFIX}:{session_id}:{key}"


def _index_key(session_id: str) -> str:
    return f"{_INDEX_PREFIX}:{session_id}"


class RedisStateStore:
    """Production-grade durable state store. Multi-process safe.

    Pass an already-constructed ``redis.asyncio.Redis`` client. The store does
    not own the client's lifecycle (do not call ``aclose()``).
    """

    def __init__(self, redis: Redis) -> None:
        try:
            import redis as _redis  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised by missing extra
            raise ImportError(
                "RedisStateStore requires the [redis] extra: pip install oak-session[redis]"
            ) from exc
        self._redis = redis

    async def put(self, session_id: str, key: str, value: dict[str, Any]) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(_key(session_id, key), json.dumps(value))
            pipe.sadd(_index_key(session_id), key)
            await pipe.execute()

    async def get(self, session_id: str, key: str) -> dict[str, Any] | None:
        raw = await self._redis.get(_key(session_id, key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        decoded: Any = json.loads(raw)
        if not isinstance(decoded, dict):
            return None
        return decoded

    async def delete_session(self, session_id: str) -> None:
        smembers_call: Any = self._redis.smembers(_index_key(session_id))
        members: Any = await smembers_call
        keys = [_key(session_id, m.decode("utf-8") if isinstance(m, bytes) else m) for m in members]
        async with self._redis.pipeline(transaction=True) as pipe:
            if keys:
                pipe.delete(*keys)
            pipe.delete(_index_key(session_id))
            await pipe.execute()


__all__ = ["RedisStateStore"]
