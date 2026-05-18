"""Runs the workspace contract suite against ``LocalProcessWorkspace``.

Also asserts the local-specific binding promised in workspace.md:
``supports_reconnect=False`` plus ``pause()`` raising
``CapabilityUnsupported``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from oak_workspace import CapabilityUnsupported, LocalProcessWorkspace

# Re-export every contract test so pytest collects them in this file.
from .contract import (  # noqa: F401
    test_boot_emits_otel_span,
    test_capabilities_match_methods,
    test_cold_start_under_5s,
    test_concurrent_execute_isolated,
    test_execute_captures_stderr_independently,
    test_execute_nonzero_exit,
    test_execute_respects_timeout,
    test_execute_simple_command,
    test_handle_is_serializable,
    test_pause_unsupported_raises,
    test_reconnect_after_termination_raises,
    test_reconnect_roundtrip,
    test_snapshot_restore_roundtrip,
    test_snapshot_unsupported_raises,
    test_terminate_is_idempotent,
    test_upload_returns_file_size,
    test_upload_then_download_roundtrip,
    test_use_after_terminate_raises,
)


@pytest.fixture
async def workspace() -> AsyncIterator[LocalProcessWorkspace]:
    ws = LocalProcessWorkspace()
    try:
        yield ws
    finally:
        await ws.terminate()


@pytest.fixture
def workspace_factory() -> Callable[[], LocalProcessWorkspace]:
    return lambda: LocalProcessWorkspace()


@pytest.fixture
def provider() -> str:
    """Provider string used by reconnect / boot-span contract tests."""
    return "local"


# ---------------------------------------------------- local-specific asserts


async def test_local_does_not_support_reconnect() -> None:
    """LocalProcessWorkspace declares supports_reconnect=False per workspace.md."""
    ws = LocalProcessWorkspace()
    try:
        assert ws.capabilities.supports_reconnect is False
        assert ws.capabilities.native_idle_timeout is False
    finally:
        await ws.terminate()


async def test_local_pause_raises_capability_unsupported() -> None:
    """pause() on LocalProcessWorkspace must raise CapabilityUnsupported(supports_reconnect)."""
    ws = LocalProcessWorkspace()
    try:
        with pytest.raises(CapabilityUnsupported) as exc_info:
            await ws.pause()
        assert exc_info.value.capability == "supports_reconnect"
    finally:
        await ws.terminate()


async def test_local_reconnect_raises_capability_unsupported() -> None:
    """LocalProcessWorkspace.reconnect must raise CapabilityUnsupported(supports_reconnect)."""
    with pytest.raises(CapabilityUnsupported) as exc_info:
        await LocalProcessWorkspace.reconnect({"working_dir": "/tmp/x"})
    assert exc_info.value.capability == "supports_reconnect"


async def test_local_handle_contains_working_dir() -> None:
    """LocalProcessWorkspace.handle returns {"working_dir": ...} - no secrets."""
    ws = LocalProcessWorkspace()
    try:
        assert ws.handle == {"working_dir": ws.working_dir}
        assert ws.underlying is None
    finally:
        await ws.terminate()
