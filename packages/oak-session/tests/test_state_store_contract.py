"""Contract tests for the SessionStateStore Protocol.

These tests run against any backend; the default fixture exercises
``InMemoryStateStore``. A custom backend can satisfy oak compatibility by
making these 8 required tests pass.

Implements the spec at docs/contract_tests.md
(``oak.session.tests.contract.state_store``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from oak_session.protocols import SessionStateStore
from oak_session.state_stores.in_memory import InMemoryStateStore


@pytest_asyncio.fixture
async def store() -> AsyncIterator[SessionStateStore]:
    yield InMemoryStateStore()


@pytest.mark.contract
async def test_put_then_get_roundtrip(store: SessionStateStore) -> None:
    """put('sess-1', 'workspace', {'provider': 'e2b', 'handle': 'sb-x'}) → get returns the same dict."""
    payload = {"provider": "e2b", "handle": "sb-x"}
    await store.put("sess-1", "workspace", payload)
    assert await store.get("sess-1", "workspace") == payload


@pytest.mark.contract
async def test_get_missing_returns_none(store: SessionStateStore) -> None:
    """A fresh store returns None (not an exception) for a missing key."""
    assert await store.get("sess-1", "workspace") is None


@pytest.mark.contract
async def test_put_overwrites_existing(store: SessionStateStore) -> None:
    """Two puts on the same (session, key) keep the second value."""
    await store.put("sess-1", "workspace", {"v": 1})
    await store.put("sess-1", "workspace", {"v": 2})
    assert await store.get("sess-1", "workspace") == {"v": 2}


@pytest.mark.contract
async def test_multiple_keys_per_session(store: SessionStateStore) -> None:
    """Multiple keys per session are independently gettable; delete_session removes both."""
    await store.put("sess-1", "workspace", {"a": 1})
    await store.put("sess-1", "pending_action", {"b": 2})
    assert await store.get("sess-1", "workspace") == {"a": 1}
    assert await store.get("sess-1", "pending_action") == {"b": 2}
    await store.delete_session("sess-1")
    assert await store.get("sess-1", "workspace") is None
    assert await store.get("sess-1", "pending_action") is None


@pytest.mark.contract
async def test_session_isolation(store: SessionStateStore) -> None:
    """Two sessions' keys are independent; deleting one leaves the other intact."""
    await store.put("sess-1", "workspace", {"id": 1})
    await store.put("sess-2", "workspace", {"id": 2})
    await store.delete_session("sess-1")
    assert await store.get("sess-1", "workspace") is None
    assert await store.get("sess-2", "workspace") == {"id": 2}


@pytest.mark.contract
async def test_delete_session_clears_all_keys(store: SessionStateStore) -> None:
    """delete_session removes every key under that session."""
    await store.put("sess-1", "workspace", {"x": 1})
    await store.put("sess-1", "pending_action", {"y": 2})
    await store.delete_session("sess-1")
    assert await store.get("sess-1", "workspace") is None
    assert await store.get("sess-1", "pending_action") is None


@pytest.mark.contract
async def test_delete_missing_session_is_noop(store: SessionStateStore) -> None:
    """delete_session on a never-existed session does not raise."""
    await store.delete_session("never-existed")


@pytest.mark.contract
async def test_values_serializable(store: SessionStateStore) -> None:
    """Complex JSON-serializable values roundtrip losslessly."""
    payload = {
        "nested": {"deep": [1, 2, 3]},
        "ints": 42,
        "strs": "hello",
        "bools": True,
        "nulls": None,
        "list": [{"a": 1}, {"b": 2}],
    }
    await store.put("sess-1", "complex", payload)
    assert await store.get("sess-1", "complex") == payload


# --- defensive: mutating the returned dict does not affect stored state ----


async def test_returned_value_is_independent_copy() -> None:
    """Mutating a get() result does not affect a later get()."""
    store = InMemoryStateStore()
    await store.put("sess", "k", {"v": 1, "lst": [1, 2]})
    first = await store.get("sess", "k")
    assert first is not None
    first["v"] = 999
    first["lst"].append(99)
    second = await store.get("sess", "k")
    assert second == {"v": 1, "lst": [1, 2]}
