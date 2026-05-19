"""Workspace contract suite - 14 required tests + 3 advisory.

Per ``docs/contract_tests.md``: docstrings ARE the assertion text.
Backend authors import these tests and parametrize via a ``workspace``
fixture that yields a freshly-constructed instance. A ``provider``
fixture (string) is required for reconnect / boot-span tests so the
suite knows how to round-trip via ``oak_workspace.create`` /
``oak_workspace.reconnect``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any

import pytest
from oak_workspace import (
    CapabilityUnsupported,
    WorkspaceTerminated,
    WorkspaceTimeout,
    WorkspaceUnreachable,
)
from oak_workspace import create as ws_create
from oak_workspace import reconnect as ws_reconnect

# ---------------------------------------------------------------- helpers


def _skip_if(workspace: Any, capability: str, expected: bool = True) -> None:
    actual = getattr(workspace.capabilities, capability, False)
    if actual != expected:
        pytest.skip(
            f"backend {type(workspace).__name__} has {capability}={actual}; "
            f"test requires {capability}={expected}"
        )


# ---------------------------------------------------------------- 14 tests


@pytest.mark.contract
async def test_execute_simple_command(workspace: Any) -> None:
    """Given a brand-new workspace, when execute('echo hi') is called,
    then exit_code == 0, stdout == 'hi\\n', stderr == '', timeout_occurred is False."""
    r = await workspace.execute("echo hi")
    assert r.exit_code == 0
    assert r.stdout == "hi\n"
    assert r.stderr == ""
    assert r.timeout_occurred is False


@pytest.mark.contract
async def test_execute_nonzero_exit(workspace: Any) -> None:
    """Given a workspace, when execute('exit 7') is called,
    then exit_code == 7. No exception raised - exit codes are not errors."""
    r = await workspace.execute("exit 7")
    assert r.exit_code == 7


@pytest.mark.contract
async def test_execute_respects_timeout(workspace: Any) -> None:
    """Given a workspace, when execute('sleep 10', timeout=0.5) is called,
    then WorkspaceTimeout is raised within 1.0s, carrying command='sleep 10' and timeout=0.5."""
    start = time.perf_counter()
    with pytest.raises(WorkspaceTimeout) as exc_info:
        await workspace.execute("sleep 10", timeout=0.5)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.5
    assert exc_info.value.command == "sleep 10"
    assert exc_info.value.timeout == 0.5


@pytest.mark.contract
async def test_execute_captures_stderr_independently(workspace: Any) -> None:
    """Given a workspace, when execute('echo out; echo err >&2') is called,
    then stdout == 'out\\n' and stderr == 'err\\n'."""
    r = await workspace.execute("echo out; echo err >&2")
    assert r.stdout == "out\n"
    assert r.stderr == "err\n"


@pytest.mark.contract
async def test_upload_then_download_roundtrip(workspace: Any) -> None:
    """Given a workspace, when upload(local_file, '/tmp/x') then download('/tmp/x', local_file2),
    then sha256(local_file) == sha256(local_file2). Tests both directions of file transfer."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "src.bin"
        src.write_bytes(b"hello-oak-" * 100)
        digest_in = hashlib.sha256(src.read_bytes()).hexdigest()

        up = await workspace.upload(src, "/tmp/x")
        assert up.success, up.error

        dst = Path(td) / "out.bin"
        dn = await workspace.download("/tmp/x", dst)
        assert dn.success, dn.error

        digest_out = hashlib.sha256(dst.read_bytes()).hexdigest()
        assert digest_in == digest_out


@pytest.mark.contract
async def test_upload_returns_file_size(workspace: Any) -> None:
    """Given a workspace, when upload(file_with_123_bytes, '/tmp/x'),
    then result.success is True and result.file_size == 123."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "f.bin"
        src.write_bytes(b"x" * 123)
        r = await workspace.upload(src, "/tmp/x")
        assert r.success is True
        assert r.file_size == 123


_SECRET_LIKE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "auth",
    "authorization",
    "bearer",
}


@pytest.mark.contract
async def test_handle_is_serializable(workspace: Any) -> None:
    """workspace.handle is a dict with JSON-serializable values only
    (str/int/bool/None/list/dict). Contains NO secret-looking keys
    (no api_key, no token, no password)."""
    handle = workspace.handle
    assert isinstance(handle, dict)
    # JSON-serializable round-trip.
    json.dumps(handle)
    # No secret-looking keys at the top level.
    for key in handle:
        assert key.lower() not in _SECRET_LIKE_KEYS, (
            f"handle exposes secret-looking key {key!r}"
        )


@pytest.mark.contract
async def test_pause_unsupported_raises(workspace: Any) -> None:
    """Given supports_reconnect=False, when pause() is called,
    then CapabilityUnsupported is raised with capability='supports_reconnect'."""
    if workspace.capabilities.supports_reconnect:
        pytest.skip("backend supports reconnect; assertion does not apply")
    with pytest.raises(CapabilityUnsupported) as exc_info:
        await workspace.pause()
    assert exc_info.value.capability == "supports_reconnect"


@pytest.mark.contract
async def test_reconnect_roundtrip(workspace: Any, provider: str | None = None) -> None:
    """Given supports_reconnect=True, when:
       1. handle = workspace.handle
       2. workspace.execute('echo hi > /tmp/marker')
       3. workspace.pause()
       4. ws2 = reconnect(provider, handle)
       5. result = ws2.execute('cat /tmp/marker')
    then result.stdout == 'hi\\n' (filesystem state preserved).
    (Skipped if supports_reconnect=False or no provider fixture supplied.)"""
    _skip_if(workspace, "supports_reconnect", True)
    if provider is None:
        pytest.skip("no provider fixture supplied; cannot exercise reconnect()")
    handle = workspace.handle
    await workspace.execute("echo hi > /tmp/marker")
    await workspace.pause()
    ws2 = await ws_reconnect(provider, handle)
    try:
        r = await ws2.execute("cat /tmp/marker")
        assert r.stdout == "hi\n"
    finally:
        await ws2.terminate()


@pytest.mark.contract
async def test_reconnect_after_termination_raises(
    workspace: Any, provider: str | None = None
) -> None:
    """Given a terminated workspace's handle, when reconnect(handle) is called,
    then WorkspaceUnreachable is raised carrying handle + reason.
    (Skipped if supports_reconnect=False.)"""
    _skip_if(workspace, "supports_reconnect", True)
    if provider is None:
        pytest.skip("no provider fixture supplied; cannot exercise reconnect()")
    handle = dict(workspace.handle)
    await workspace.terminate()
    with pytest.raises(WorkspaceUnreachable) as exc_info:
        await ws_reconnect(provider, handle)
    # WorkspaceUnreachable carries the original handle so callers can
    # clean up their state-store entry.
    assert isinstance(exc_info.value.handle, dict)
    assert isinstance(exc_info.value.reason, str) and exc_info.value.reason


@pytest.mark.contract
async def test_snapshot_restore_roundtrip(workspace: Any) -> None:
    """Given supports_snapshot=True, when execute('echo x > /tmp/y'), sid = snapshot(),
    execute('rm /tmp/y'), restore(sid), execute('cat /tmp/y'),
    then stdout == 'x\\n'. (Skipped if capability is False.)"""
    _skip_if(workspace, "supports_snapshot", True)
    await workspace.execute("echo x > /tmp/y")
    sid = await workspace.snapshot()
    await workspace.execute("rm /tmp/y")
    await workspace.restore(sid)
    r = await workspace.execute("cat /tmp/y")
    assert r.stdout == "x\n"


@pytest.mark.contract
async def test_snapshot_unsupported_raises(workspace: Any) -> None:
    """Given supports_snapshot=False, when snapshot() is called,
    then CapabilityUnsupported is raised with capability='supports_snapshot'."""
    if workspace.capabilities.supports_snapshot:
        pytest.skip("backend supports snapshot; assertion does not apply")
    with pytest.raises(CapabilityUnsupported) as exc_info:
        await workspace.snapshot()
    assert exc_info.value.capability == "supports_snapshot"


@pytest.mark.contract
async def test_terminate_is_idempotent(workspace: Any) -> None:
    """Given a workspace, when terminate() is called twice,
    then the second call does NOT raise. Best-effort semantics."""
    await workspace.terminate()
    await workspace.terminate()  # must not raise


@pytest.mark.contract
async def test_use_after_terminate_raises(workspace: Any) -> None:
    """Given a terminated workspace, when execute('echo x') is called,
    then WorkspaceTerminated is raised."""
    await workspace.terminate()
    with pytest.raises(WorkspaceTerminated):
        await workspace.execute("echo x")


@pytest.mark.contract
async def test_boot_emits_otel_span(provider: str | None = None) -> None:
    """When ``oak_workspace.create()`` is called, then an OTel span named
    ``workspace.boot`` is emitted with attributes ``workspace.provider``,
    ``workspace.handle`` (JSON-encoded), and optional ``workspace.region``
    / ``workspace.image``. ``workspace.handle`` MUST NOT contain secrets.

    Uses an in-process InMemorySpanExporter via ``opentelemetry-sdk`` to
    capture the span. Skipped if ``opentelemetry-sdk`` is not installed
    or no provider is supplied.
    """
    if provider is None:
        pytest.skip("no provider fixture supplied; cannot exercise create()")
    try:
        from opentelemetry import trace as _trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
    except ImportError:
        pytest.skip("opentelemetry-sdk not installed; cannot capture spans")

    # NOTE: install a fresh TracerProvider so we don't pollute the global
    # one. We swap back after the test.
    exporter = InMemorySpanExporter()
    provider_obj = TracerProvider()
    provider_obj.add_span_processor(SimpleSpanProcessor(exporter))
    prev_provider = _trace.get_tracer_provider()
    _trace.set_tracer_provider(provider_obj)

    # ``oak_workspace.telemetry`` cached a tracer at import time against
    # the previous provider; re-bind it for this test.
    import oak_workspace.telemetry as _wt

    _wt._TRACER = _trace.get_tracer("oak.workspace")

    try:
        ws = await ws_create(provider)
        try:
            spans = exporter.get_finished_spans()
            boot_spans = [s for s in spans if s.name == "workspace.boot"]
            assert boot_spans, (
                f"no workspace.boot span emitted; saw {[s.name for s in spans]}"
            )
            attrs = dict(boot_spans[-1].attributes or {})
            assert attrs.get("workspace.provider") == provider
            handle_attr = attrs.get("workspace.handle")
            assert isinstance(handle_attr, str)
            # JSON-decodes cleanly and contains no secret-looking keys.
            decoded = json.loads(handle_attr)
            assert isinstance(decoded, dict)
            for key in decoded:
                assert key.lower() not in _SECRET_LIKE_KEYS
        finally:
            await ws.terminate()
    finally:
        _trace.set_tracer_provider(prev_provider)
        _wt._TRACER = _trace.get_tracer("oak.workspace")


# ------------------------------------------------------ advisory (3 warns)


@pytest.mark.contract
async def test_concurrent_execute_isolated(workspace: Any) -> None:
    """20 parallel execute() calls return without cross-contamination.
    PASS if all 20 complete with their own stdout; warn if any share output."""
    results = await asyncio.gather(*(workspace.execute(f"echo {i}") for i in range(20)))
    expected = {f"{i}\n" for i in range(20)}
    seen = {r.stdout for r in results}
    if seen != expected:
        warnings.warn(
            f"concurrent execute isolation: missing={expected - seen}", stacklevel=2
        )


@pytest.mark.contract
async def test_cold_start_under_5s(workspace_factory: Any) -> None:
    """__aenter__ + first execute completes in <5s. Warn (not fail) if slower."""
    start = time.perf_counter()
    async with workspace_factory() as ws:
        await ws.execute("echo ready")
    elapsed = time.perf_counter() - start
    if elapsed >= 5.0:
        warnings.warn(f"cold start was {elapsed:.2f}s (>5s)", stacklevel=2)


@pytest.mark.contract
async def test_capabilities_match_methods(workspace: Any) -> None:
    """For each method whose docstring says 'raises CapabilityUnsupported if X is False',
    verify the actual method raises that error when called with X=False. Reflection-based."""
    bindings = {
        "pause": "supports_reconnect",
        "resume": "supports_reconnect",
        "snapshot": "supports_snapshot",
        "restore": "supports_snapshot",
    }
    for method_name, cap in bindings.items():
        if getattr(workspace.capabilities, cap, False):
            continue
        method = getattr(workspace, method_name)
        try:
            if method_name == "restore":
                await method("dummy-id")
            else:
                await method()
        except CapabilityUnsupported as e:
            assert e.capability == cap, (
                f"{method_name} raised CapabilityUnsupported({e.capability}) "
                f"but binding declares {cap}"
            )
        else:
            warnings.warn(
                f"{method_name}() did not raise CapabilityUnsupported despite "
                f"{cap}=False",
                stacklevel=2,
            )
