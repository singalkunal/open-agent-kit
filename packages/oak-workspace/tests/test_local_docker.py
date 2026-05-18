"""Contract suite against ``LocalDockerWorkspace`` (requires Docker daemon)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest

docker = pytest.importorskip("docker")

try:
    _client = docker.from_env()
    _client.ping()
    _DOCKER_AVAILABLE = True
except Exception:
    _DOCKER_AVAILABLE = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="docker daemon not reachable"),
]

from oak_workspace.local_docker import LocalDockerWorkspace  # noqa: E402

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
async def workspace() -> AsyncIterator[LocalDockerWorkspace]:
    ws = LocalDockerWorkspace(image="python:3.12-slim")
    try:
        await ws._ensure_container()
        yield ws
    finally:
        await ws.terminate()


@pytest.fixture
def workspace_factory() -> Callable[[], LocalDockerWorkspace]:
    return lambda: LocalDockerWorkspace(image="python:3.12-slim")


@pytest.fixture
def provider() -> str:
    return "local_docker"
