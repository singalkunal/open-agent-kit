"""Internal lease implementations.

Lease coordination is a private concern; user code does not import from this
module directly. Configure via ``oak.session.configure(lease=...)`` instead.
"""

from __future__ import annotations

import os
import socket
import time
import uuid
from typing import TYPE_CHECKING, Any

import anyio

from .errors import LeaseHeld
from .models import Lease

if TYPE_CHECKING:
    from redis.asyncio import Redis


DEFAULT_TTL_SECONDS = 30.0
_POLL_INTERVAL = 0.05


def _make_owner() -> str:
    """Stable-per-process owner identifier. Used to identify the lease holder."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class InMemoryLease:
    """Process-local lease coordinator. Single-process only.

    Each call to ``InMemoryLease()`` creates a separate logical owner. Multi-process
    coordination requires ``RedisLease``.
    """

    def __init__(self, *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._owner = _make_owner()
        # session_id -> (owner, generation, expires_at, ttl)
        self._state: dict[str, tuple[str, int, float, float]] = {}
        # monotonically increasing generation counter across acquire cycles
        self._generations: dict[str, int] = {}
        self._lock = anyio.Lock()

    @property
    def owner_id(self) -> str:
        return self._owner

    async def acquire(
        self,
        session_id: str,
        *,
        wait_for_lease: bool | float = False,
        force_reclaim: bool = False,
    ) -> Lease:
        deadline: float | None = None
        if wait_for_lease is True:
            deadline = None  # wait indefinitely
            waiting = True
        elif isinstance(wait_for_lease, int | float) and wait_for_lease:
            deadline = time.monotonic() + float(wait_for_lease)
            waiting = True
        else:
            waiting = False

        while True:
            async with self._lock:
                existing = self._state.get(session_id)
                now = time.monotonic()
                alive = existing is not None and existing[2] > now
                # take the slot if free / dead / forced / owned-by-us
                if (
                    existing is None
                    or not alive
                    or force_reclaim
                    or existing[0] == self._owner
                ):
                    generation = self._generations.get(session_id, 0) + 1
                    self._generations[session_id] = generation
                    acquired = time.time()
                    expires = time.monotonic() + self._ttl
                    self._state[session_id] = (self._owner, generation, expires, self._ttl)
                    return Lease(
                        session_id=session_id,
                        owner=self._owner,
                        generation=generation,
                        acquired_at=acquired,
                        ttl_seconds=self._ttl,
                    )
                held_owner = existing[0]

            if not waiting:
                raise LeaseHeld(session_id, owner=held_owner)
            if deadline is not None and time.monotonic() >= deadline:
                raise LeaseHeld(session_id, owner=held_owner)
            await anyio.sleep(_POLL_INTERVAL)

    async def renew(self, session_id: str) -> None:
        async with self._lock:
            existing = self._state.get(session_id)
            if existing is None or existing[0] != self._owner:
                raise LeaseHeld(session_id, owner=existing[0] if existing else None)
            owner, generation, _expires, ttl = existing
            self._state[session_id] = (
                owner,
                generation,
                time.monotonic() + ttl,
                ttl,
            )

    async def release(self, session_id: str) -> None:
        async with self._lock:
            existing = self._state.get(session_id)
            if existing is None:
                return
            if existing[0] == self._owner:
                self._state.pop(session_id, None)
            # else: not ours; no-op (idempotent, defensive)


_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

_RENEW_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
else
    return 0
end
"""


def _lease_key(session_id: str) -> str:
    return f"oak:session:lease:{session_id}"


def _gen_key(session_id: str) -> str:
    return f"oak:session:lease:{session_id}:gen"


class RedisLease:
    """Redis-backed CAS lease. Production multi-process coordinator.

    Uses ``SET NX PX`` for atomic acquire and Lua scripts for owner-verified
    release / renew. Generation counter is a separate ``INCR`` key.
    """

    def __init__(self, redis: Redis, *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        try:
            import redis as _redis  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised by missing extra
            raise ImportError(
                "RedisLease requires the [redis] extra: pip install oak-session[redis]"
            ) from exc
        self._redis = redis
        self._ttl = ttl_seconds
        self._owner = _make_owner()

    @property
    def owner_id(self) -> str:
        return self._owner

    async def _try_set(self, session_id: str) -> bool:
        ok: Any = await self._redis.set(
            _lease_key(session_id),
            self._owner,
            nx=True,
            px=int(self._ttl * 1000),
        )
        return bool(ok)

    async def _current_owner(self, session_id: str) -> str | None:
        val = await self._redis.get(_lease_key(session_id))
        if val is None:
            return None
        if isinstance(val, bytes):
            return val.decode("utf-8")
        return str(val)

    async def acquire(
        self,
        session_id: str,
        *,
        wait_for_lease: bool | float = False,
        force_reclaim: bool = False,
    ) -> Lease:
        deadline: float | None = None
        if wait_for_lease is True:
            waiting = True
        elif isinstance(wait_for_lease, int | float) and wait_for_lease:
            waiting = True
            deadline = time.monotonic() + float(wait_for_lease)
        else:
            waiting = False

        while True:
            acquired = await self._try_set(session_id)
            if not acquired and force_reclaim:
                await self._redis.set(
                    _lease_key(session_id),
                    self._owner,
                    px=int(self._ttl * 1000),
                )
                acquired = True
            if acquired:
                gen: Any = await self._redis.incr(_gen_key(session_id))
                return Lease(
                    session_id=session_id,
                    owner=self._owner,
                    generation=int(gen),
                    acquired_at=time.time(),
                    ttl_seconds=self._ttl,
                )
            owner = await self._current_owner(session_id)
            if not waiting:
                raise LeaseHeld(session_id, owner=owner)
            if deadline is not None and time.monotonic() >= deadline:
                raise LeaseHeld(session_id, owner=owner)
            await anyio.sleep(_POLL_INTERVAL)

    async def renew(self, session_id: str) -> None:
        eval_call: Any = self._redis.eval(
            _RENEW_LUA, 1, _lease_key(session_id), self._owner, str(int(self._ttl * 1000))
        )
        result: Any = await eval_call
        if not result:
            owner = await self._current_owner(session_id)
            raise LeaseHeld(session_id, owner=owner)

    async def release(self, session_id: str) -> None:
        eval_call: Any = self._redis.eval(
            _RELEASE_LUA, 1, _lease_key(session_id), self._owner
        )
        await eval_call


__all__ = ["DEFAULT_TTL_SECONDS", "InMemoryLease", "RedisLease"]
