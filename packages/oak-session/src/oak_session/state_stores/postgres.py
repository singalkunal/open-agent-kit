"""Postgres-backed SessionStateStore.

Import-guarded under the ``[postgres]`` extra. Expects a table created via
``RedisStateStore.create_table_sql()``; user owns migration.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncpg import Pool


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS oak_session_state (
    session_id TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, key)
);
"""


class PostgresStateStore:
    """Durable state store for teams already running Postgres.

    Pass an ``asyncpg.Pool``. Caller owns pool lifecycle.
    """

    def __init__(self, pool: Pool, *, table: str = "oak_session_state") -> None:
        try:
            import asyncpg  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised by missing extra
            raise ImportError(
                "PostgresStateStore requires the [postgres] extra: pip install oak-session[postgres]"
            ) from exc
        self._pool = pool
        self._table = table

    @staticmethod
    def create_table_sql(table: str = "oak_session_state") -> str:
        return CREATE_TABLE_SQL.replace("oak_session_state", table)

    async def put(self, session_id: str, key: str, value: dict[str, Any]) -> None:
        sql = (
            f"INSERT INTO {self._table} (session_id, key, value) VALUES ($1, $2, $3::jsonb) "
            f"ON CONFLICT (session_id, key) DO UPDATE SET value = EXCLUDED.value, "
            f"updated_at = NOW()"
        )
        async with self._pool.acquire() as conn:
            await conn.execute(sql, session_id, key, json.dumps(value))

    async def get(self, session_id: str, key: str) -> dict[str, Any] | None:
        sql = f"SELECT value FROM {self._table} WHERE session_id = $1 AND key = $2"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, session_id, key)
        if row is None:
            return None
        raw = row["value"]
        if isinstance(raw, str):
            decoded: Any = json.loads(raw)
        else:
            decoded = raw
        if not isinstance(decoded, dict):
            return None
        return decoded

    async def delete_session(self, session_id: str) -> None:
        sql = f"DELETE FROM {self._table} WHERE session_id = $1"
        async with self._pool.acquire() as conn:
            await conn.execute(sql, session_id)


__all__ = ["CREATE_TABLE_SQL", "PostgresStateStore"]
