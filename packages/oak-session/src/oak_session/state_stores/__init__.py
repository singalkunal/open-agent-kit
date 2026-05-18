"""Reference SessionStateStore implementations.

Lazy re-exports so that importing this package does not pull in `redis` or
`asyncpg` unless the user has installed the corresponding extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .in_memory import InMemoryStateStore

if TYPE_CHECKING:
    from .postgres import PostgresStateStore
    from .redis import RedisStateStore


def __getattr__(name: str) -> Any:
    if name == "RedisStateStore":
        from .redis import RedisStateStore

        return RedisStateStore
    if name == "PostgresStateStore":
        from .postgres import PostgresStateStore

        return PostgresStateStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["InMemoryStateStore", "PostgresStateStore", "RedisStateStore"]
