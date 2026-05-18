"""attach() + end() basic lifecycle tests against InMemory backends."""

from __future__ import annotations

import pytest
from oak_session import (
    InMemoryLease,
    LeaseHeld,
    SessionEnded,
    attach,
    configure,
    end,
)
from oak_session.state_stores.in_memory import InMemoryStateStore


async def test_attach_fresh_session_no_prior() -> None:
    configure(state_store=InMemoryStateStore())
    async with attach("sess-1") as attached:
        assert attached.session_id == "sess-1"
        assert attached.workspace is None
        assert attached.workspace_status == "no_prior"
        assert attached.trace_status == "no_prior"
        assert attached.state.messages == []
        assert attached.lease is None


async def test_attach_with_lease_acquires_and_releases() -> None:
    lease = InMemoryLease()
    configure(state_store=InMemoryStateStore(), lease=lease)
    async with attach("sess-2") as attached:
        assert attached.lease is not None
        assert attached.lease.session_id == "sess-2"
        assert attached.lease.generation == 1
    # After exit, lease should be released; second attach should re-acquire.
    async with attach("sess-2") as attached2:
        assert attached2.lease is not None
        assert attached2.lease.generation == 2


async def test_attach_raises_lease_held_for_concurrent_owner() -> None:
    lease_a = InMemoryLease()
    lease_b = InMemoryLease()
    # Both share the underlying state because we'll point process config at A
    configure(state_store=InMemoryStateStore(), lease=lease_a)
    await lease_a.acquire("sess-x")

    # Simulate a separate process by reconfiguring with B and sharing state.
    # We have to share lease_a's _state for the test to be meaningful.
    lease_b._state = lease_a._state
    lease_b._generations = lease_a._generations

    configure(state_store=InMemoryStateStore(), lease=lease_b)
    with pytest.raises(LeaseHeld):
        async with attach("sess-x"):
            pass


async def test_end_then_attach_raises_session_ended() -> None:
    configure(state_store=InMemoryStateStore())
    async with attach("sess-3"):
        pass
    await end("sess-3")
    with pytest.raises(SessionEnded):
        async with attach("sess-3"):
            pass


async def test_end_is_idempotent() -> None:
    configure(state_store=InMemoryStateStore())
    await end("never-existed")  # no-op
    await end("never-existed")  # still no-op


async def test_attach_workspace_factory_used_when_no_prior() -> None:
    configure(state_store=InMemoryStateStore())

    class FakeWorkspace:
        working_dir = "/tmp"
        capabilities = None

        async def pause(self) -> None:
            pass

        async def terminate(self) -> None:
            pass

    async def factory() -> FakeWorkspace:
        return FakeWorkspace()

    async with attach(
        "sess-4",
        workspace_factory=factory,  # type: ignore[arg-type]
    ) as attached:
        assert attached.workspace_status == "boot_fresh"
        assert isinstance(attached.workspace, FakeWorkspace)
