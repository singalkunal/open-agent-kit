"""Shared fixtures for oak.session tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from oak_session import configure
from oak_session.configure import _reset_for_tests
from oak_session.state_stores.in_memory import InMemoryStateStore


@pytest_asyncio.fixture(autouse=True)
async def _reset_config() -> AsyncIterator[None]:
    """Reset process-level configure() between tests."""
    _reset_for_tests()
    yield
    _reset_for_tests()


@pytest_asyncio.fixture
async def in_memory_store() -> InMemoryStateStore:
    store = InMemoryStateStore()
    configure(state_store=store)
    return store
