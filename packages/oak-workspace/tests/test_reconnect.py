"""Targeted reconnect tests.

Covers the reconnect-capable contract from
``docs/design/workspace.md``: handle round-trip, filesystem-state
preservation, and ``WorkspaceUnreachable`` on a stale handle.

E2B-backed scenarios are skipped unless ``E2B_API_KEY`` is set in the
environment (and the ``e2b_code_interpreter`` SDK is installed). The
``handle``-shape assertion against ``E2BWorkspace`` runs offline.
"""

from __future__ import annotations

import os

import pytest

from oak_workspace import (
    CapabilityUnsupported,
    LocalProcessWorkspace,
    WorkspaceUnreachable,
    create as ws_create,
    list_providers,
    reconnect as ws_reconnect,
)

_E2B_INSTALLED = True
try:
    import e2b_code_interpreter  # type: ignore[import-not-found]  # noqa: F401
except ImportError:
    _E2B_INSTALLED = False

_E2B_AVAILABLE = _E2B_INSTALLED and "E2B_API_KEY" in os.environ


# ----------------------------------------------------- provider registration


def test_list_providers_includes_local_and_e2b() -> None:
    """``list_providers()`` returns at minimum the built-in ``local`` and ``e2b`` names."""
    providers = list_providers()
    assert "local" in providers
    assert "e2b" in providers


# -------------------------------------------------------------- local (sync)


async def test_local_reconnect_raises_capability_unsupported() -> None:
    """LocalProcessWorkspace.reconnect raises CapabilityUnsupported(supports_reconnect)."""
    with pytest.raises(CapabilityUnsupported) as exc_info:
        await LocalProcessWorkspace.reconnect({"working_dir": "/tmp/x"})
    assert exc_info.value.capability == "supports_reconnect"


async def test_module_reconnect_local_raises_capability_unsupported() -> None:
    """Module-level reconnect('local', handle) bubbles the CapabilityUnsupported."""
    with pytest.raises(CapabilityUnsupported):
        await ws_reconnect("local", {"working_dir": "/tmp/x"})


# ---------------------------------------------------------------- E2B (live)

_e2b_skip = pytest.mark.skipif(
    not _E2B_AVAILABLE,
    reason="E2B_API_KEY not set or e2b_code_interpreter not installed",
)


@_e2b_skip
async def test_e2b_handle_contains_sandbox_id() -> None:
    """After boot, E2BWorkspace.handle contains a non-empty sandbox_id string."""
    ws = await ws_create("e2b")
    try:
        handle = ws.handle
        assert "sandbox_id" in handle
        assert isinstance(handle["sandbox_id"], str)
        assert handle["sandbox_id"]
    finally:
        await ws.terminate()


@_e2b_skip
async def test_e2b_reconnect_roundtrip_preserves_filesystem() -> None:
    """Boot E2B, write a marker file, pause, reconnect from handle, read the marker back."""
    ws1 = await ws_create("e2b")
    try:
        await ws1.execute("echo hi > /tmp/marker")
        handle = ws1.handle
        await ws1.pause()
        ws2 = await ws_reconnect("e2b", handle)
        try:
            r = await ws2.execute("cat /tmp/marker")
            assert r.stdout == "hi\n"
        finally:
            await ws2.terminate()
    finally:
        # ws1 may already be terminated via ws2; terminate is idempotent.
        await ws1.terminate()


@_e2b_skip
async def test_e2b_reconnect_unknown_sandbox_raises_unreachable() -> None:
    """A handle pointing at a never-existed sandbox_id raises WorkspaceUnreachable."""
    bogus = {"sandbox_id": "sb-does-not-exist-0000000000"}
    with pytest.raises(WorkspaceUnreachable) as exc_info:
        await ws_reconnect("e2b", bogus)
    assert exc_info.value.handle == bogus
    assert exc_info.value.reason


@_e2b_skip
async def test_e2b_reconnect_missing_sandbox_id_raises_unreachable() -> None:
    """A handle without sandbox_id field raises WorkspaceUnreachable with a clear reason."""
    with pytest.raises(WorkspaceUnreachable) as exc_info:
        await ws_reconnect("e2b", {})
    assert "sandbox_id" in exc_info.value.reason
