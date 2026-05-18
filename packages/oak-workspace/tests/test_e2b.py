"""Contract suite against ``E2BWorkspace`` (requires E2B_API_KEY)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable

import pytest

pytest.importorskip("e2b_code_interpreter")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "E2B_API_KEY" not in os.environ, reason="E2B_API_KEY not set"
    ),
]

from oak_workspace.e2b import E2BWorkspace  # noqa: E402

from .contract import (  # noqa: E402, F401
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
async def workspace() -> AsyncIterator[E2BWorkspace]:
    ws = E2BWorkspace()
    try:
        await ws._ensure_sandbox()
        yield ws
    finally:
        await ws.terminate()


@pytest.fixture
def workspace_factory() -> Callable[[], E2BWorkspace]:
    return lambda: E2BWorkspace()


@pytest.fixture
def provider() -> str:
    return "e2b"
