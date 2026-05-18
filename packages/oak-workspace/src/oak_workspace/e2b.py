"""``E2BWorkspace``: production cloud sandbox via the E2B Code Interpreter SDK.

Wraps ``e2b_code_interpreter.AsyncSandbox``. Requires ``E2B_API_KEY`` env
var or an explicit ``api_key=`` constructor arg. Install with the
``[e2b]`` extra: ``pip install oak-workspace[e2b]``.

Capabilities (v0.1):

* ``supports_reconnect = True``    - E2B's ``Sandbox.connect(sandbox_id)``
  re-attaches to a paused / preserved sandbox. The reconnect handle is
  ``{"sandbox_id": ..., "region": ...}`` (secret-free; auth is reapplied
  via the E2B SDK's ambient API-key configuration).
* ``native_idle_timeout = True``   - E2B's ``timeout_ms`` on
  ``Sandbox.create`` is the source-of-truth idle timeout. oak does NOT
  run a background reconciler.
* ``max_idle = 24h``               - declared upper bound on E2B side.
* ``supports_snapshot = False``    - E2B has no fork-from-snapshot id yet.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from .errors import (
    CapabilityUnsupported,
    WorkspaceTerminated,
    WorkspaceTimeout,
    WorkspaceUnreachable,
)
from .telemetry import (
    ATTR_BACKEND,
    ATTR_COMMAND,
    ATTR_DST_PATH,
    ATTR_EXIT_CODE,
    ATTR_SIZE_BYTES,
    ATTR_TIMEOUT_SECONDS,
    SPAN_EXECUTE_COMMAND,
    SPAN_FILE_DOWNLOAD,
    SPAN_FILE_UPLOAD,
    SPAN_PAUSE,
    SPAN_RESUME,
    SPAN_TERMINATE,
    set_attribute,
    span,
)
from .types import CommandResult, FileOperationResult, WorkspaceCapabilities

_E2B_MAX_IDLE = timedelta(hours=24)


class E2BWorkspace:
    """Async sandbox backed by E2B's hosted code interpreter."""

    def __init__(
        self,
        *,
        template: str | None = None,
        api_key: str | None = None,
        working_dir: str = "/home/user",
        region: str | None = None,
        timeout_ms: int | None = None,
        auto_terminate: bool = True,
        sandbox: Any = None,
    ) -> None:
        self.working_dir = working_dir
        self.capabilities = WorkspaceCapabilities(
            supports_reconnect=True,
            native_idle_timeout=True,
            supports_snapshot=False,
            max_idle=_E2B_MAX_IDLE,
        )
        self._api_key = api_key or os.environ.get("E2B_API_KEY")
        self._template = template
        self._region = region
        self._timeout_ms = timeout_ms
        self._auto_terminate = auto_terminate
        self._terminated = False
        self._sandbox: Any = sandbox

    # ----------------------------------------------------------- properties

    @property
    def handle(self) -> dict[str, Any]:
        """Serializable reconnect handle.

        Contains ``sandbox_id`` (the E2B identity) plus optional
        ``region`` / ``template`` descriptors. Contains NO secrets -
        the API key is reapplied via the E2B SDK's ambient configuration
        at reconnect time.

        Returns an empty dict if the sandbox has not yet been
        materialised (i.e. ``_ensure_sandbox`` was not awaited).
        """
        out: dict[str, Any] = {}
        sb = self._sandbox
        if sb is not None:
            sid = getattr(sb, "sandbox_id", None)
            if sid is not None:
                out["sandbox_id"] = sid
        if self._region is not None:
            out["region"] = self._region
        if self._template is not None:
            out["template"] = self._template
        return out

    @property
    def underlying(self) -> object | None:
        """The raw ``AsyncSandbox`` instance (or ``None`` pre-boot)."""
        sb: object | None = self._sandbox
        return sb

    async def _ensure_sandbox(self) -> Any:
        if self._sandbox is not None:
            return self._sandbox
        try:
            from e2b_code_interpreter import AsyncSandbox
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "E2BWorkspace requires the [e2b] extra: "
                "pip install oak-workspace[e2b]"
            ) from exc
        kwargs: dict[str, Any] = {}
        if self._api_key is not None:
            kwargs["api_key"] = self._api_key
        if self._template is not None:
            kwargs["template"] = self._template
        if self._timeout_ms is not None:
            # E2B SDK's native idle timeout. oak does not run a
            # background reconciler; the provider handles auto-terminate
            # via this value (capabilities.native_idle_timeout = True).
            kwargs["timeout_ms"] = self._timeout_ms
        self._sandbox = await AsyncSandbox.create(**kwargs)
        return self._sandbox

    # ------------------------------------------------------------ core API

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float = 30.0,
    ) -> CommandResult:
        self._check_alive()
        if (
            self.capabilities.max_lifetime is not None
            and timeout > self.capabilities.max_lifetime.total_seconds()
        ):
            raise ValueError(
                f"timeout={timeout}s exceeds capabilities.max_lifetime"
            )
        sb = await self._ensure_sandbox()
        workdir = str(cwd) if cwd is not None else self.working_dir
        with span(
            SPAN_EXECUTE_COMMAND,
            {
                ATTR_BACKEND: type(self).__name__,
                ATTR_COMMAND: command,
                ATTR_TIMEOUT_SECONDS: timeout,
            },
        ) as s:
            try:
                result = await asyncio.wait_for(
                    sb.commands.run(command, cwd=workdir),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                raise WorkspaceTimeout(command=command, timeout=timeout) from exc

            exit_code = int(getattr(result, "exit_code", 0) or 0)
            stdout = getattr(result, "stdout", "") or ""
            stderr = getattr(result, "stderr", "") or ""
            set_attribute(s, ATTR_EXIT_CODE, exit_code)
            return CommandResult(
                command=command,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                timeout_occurred=False,
            )

    async def upload(
        self,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> FileOperationResult:
        self._check_alive()
        sb = await self._ensure_sandbox()
        src = Path(source)
        dst = str(destination)
        with span(
            SPAN_FILE_UPLOAD,
            {ATTR_BACKEND: type(self).__name__, ATTR_DST_PATH: dst},
        ) as s:
            try:
                data = await asyncio.to_thread(src.read_bytes)
                await sb.files.write(dst, data)
                size = len(data)
                set_attribute(s, ATTR_SIZE_BYTES, size)
                return FileOperationResult(
                    success=True,
                    source_path=str(src),
                    destination_path=dst,
                    file_size=size,
                )
            except Exception as exc:
                return FileOperationResult(
                    success=False,
                    source_path=str(src),
                    destination_path=dst,
                    error=str(exc),
                )

    async def download(
        self,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> FileOperationResult:
        self._check_alive()
        sb = await self._ensure_sandbox()
        src = str(source)
        dst = Path(destination)
        with span(
            SPAN_FILE_DOWNLOAD,
            {ATTR_BACKEND: type(self).__name__, ATTR_DST_PATH: str(dst)},
        ) as s:
            try:
                data = await sb.files.read(src, format="bytes")
                if isinstance(data, str):
                    data = data.encode("utf-8")
                dst.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(dst.write_bytes, data)
                size = len(data)
                set_attribute(s, ATTR_SIZE_BYTES, size)
                return FileOperationResult(
                    success=True,
                    source_path=src,
                    destination_path=str(dst),
                    file_size=size,
                )
            except Exception as exc:
                return FileOperationResult(
                    success=False,
                    source_path=src,
                    destination_path=str(dst),
                    error=str(exc),
                )

    # --------------------------------------------------------- capabilities

    async def snapshot(self) -> str:
        # TODO(human-decision): revisit when E2B ships fork-from-snapshot.
        if not self.capabilities.supports_snapshot:
            raise CapabilityUnsupported(
                capability="supports_snapshot", backend=type(self).__name__
            )
        raise NotImplementedError  # pragma: no cover

    async def restore(self, snapshot_id: str) -> None:
        if not self.capabilities.supports_snapshot:
            raise CapabilityUnsupported(
                capability="supports_snapshot", backend=type(self).__name__
            )
        raise NotImplementedError  # pragma: no cover

    async def pause(self) -> None:
        if not self.capabilities.supports_reconnect:
            raise CapabilityUnsupported(
                capability="supports_reconnect", backend=type(self).__name__
            )
        self._check_alive()
        sb = await self._ensure_sandbox()
        with span(SPAN_PAUSE, {ATTR_BACKEND: type(self).__name__}):
            try:
                await sb.pause()
            except Exception:  # pragma: no cover - best-effort
                pass

    async def resume(self) -> None:
        if not self.capabilities.supports_reconnect:
            raise CapabilityUnsupported(
                capability="supports_reconnect", backend=type(self).__name__
            )
        self._check_alive()
        sb = await self._ensure_sandbox()
        with span(SPAN_RESUME, {ATTR_BACKEND: type(self).__name__}):
            try:
                await sb.resume()
            except Exception:  # pragma: no cover - best-effort
                pass

    @classmethod
    async def reconnect(cls, handle: dict[str, Any]) -> E2BWorkspace:
        """Re-attach to an existing E2B sandbox by ``sandbox_id``.

        Uses the E2B SDK's ``AsyncSandbox.connect`` (or ``reconnect``)
        classmethod - whichever the installed SDK version exposes.
        Falls back through a small list of candidate method names so we
        survive minor SDK rev bumps.

        Raises ``WorkspaceUnreachable`` if the provider reports the
        sandbox no longer exists. Auth is taken from ``E2B_API_KEY``
        env var (the handle is secret-free).
        """
        sandbox_id = handle.get("sandbox_id")
        if not isinstance(sandbox_id, str) or not sandbox_id:
            raise WorkspaceUnreachable(
                handle=handle,
                reason="handle missing 'sandbox_id' field",
            )
        try:
            from e2b_code_interpreter import AsyncSandbox
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "E2BWorkspace requires the [e2b] extra: "
                "pip install oak-workspace[e2b]"
            ) from exc

        # E2B has renamed this method between SDK versions. Try the
        # known candidates in order so we keep working across rev bumps.
        connect_fn = (
            getattr(AsyncSandbox, "connect", None)
            or getattr(AsyncSandbox, "reconnect", None)
            or getattr(AsyncSandbox, "resume", None)
        )
        if connect_fn is None:
            raise WorkspaceUnreachable(
                handle=handle,
                reason=(
                    "installed e2b SDK exposes none of "
                    "AsyncSandbox.connect / .reconnect / .resume"
                ),
            )

        try:
            sb = await connect_fn(sandbox_id)
        except Exception as exc:  # noqa: BLE001 - SDK exceptions vary
            raise WorkspaceUnreachable(
                handle=handle,
                reason=f"{type(exc).__name__}: {exc}",
            ) from exc

        region = handle.get("region")
        template = handle.get("template")
        ws = cls(
            template=template if isinstance(template, str) else None,
            region=region if isinstance(region, str) else None,
            sandbox=sb,
        )
        return ws

    async def terminate(self) -> None:
        if self._terminated:
            return
        self._terminated = True
        with span(SPAN_TERMINATE, {ATTR_BACKEND: type(self).__name__}):
            sb = self._sandbox
            if sb is not None:
                try:
                    await sb.kill()
                except Exception:  # pragma: no cover - best-effort
                    pass

    # ---------------------------------------------------------- async-ctx

    async def __aenter__(self) -> E2BWorkspace:
        await self._ensure_sandbox()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._auto_terminate:
            await self.terminate()

    # --------------------------------------------------------------- utils

    def _check_alive(self) -> None:
        if self._terminated:
            raise WorkspaceTerminated(
                f"{type(self).__name__} has been terminated"
            )


__all__ = ["E2BWorkspace"]
