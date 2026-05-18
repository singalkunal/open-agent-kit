"""``LocalProcessWorkspace``: zero-infra reference backend.

Runs commands as subprocesses on the host filesystem. **NOT a security
boundary.** This exists so ``pipx run oak demo`` works on a fresh
machine with no Docker daemon and no cloud account. Users running
untrusted LLM-generated code in production should use
``LocalDockerWorkspace`` or ``E2BWorkspace``.

Capabilities:

* ``supports_reconnect = False`` - a killed local process is gone; the
  host filesystem survives but the workspace identity does not. This
  also means ``pause()`` raises ``CapabilityUnsupported`` (workspace.md
  binding: pause requires supports_reconnect).
* ``supports_snapshot = False`` - no copy-on-write fork primitive.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .errors import (
    CapabilityUnsupported,
    WorkspaceTerminated,
    WorkspaceTimeout,
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
    SPAN_TERMINATE,
    set_attribute,
    span,
)
from .types import CommandResult, FileOperationResult, WorkspaceCapabilities


class LocalProcessWorkspace:
    """Run commands as subprocesses on the host. Not a security boundary."""

    def __init__(
        self,
        working_dir: str | None = None,
        *,
        auto_terminate: bool = True,
        cleanup_on_terminate: bool = True,
    ) -> None:
        if working_dir is None:
            self._owns_workdir = True
            self.working_dir = tempfile.mkdtemp(prefix="oak-localproc-")
        else:
            self._owns_workdir = False
            Path(working_dir).mkdir(parents=True, exist_ok=True)
            self.working_dir = str(Path(working_dir).resolve())

        self.capabilities = WorkspaceCapabilities(
            supports_reconnect=False,
            supports_snapshot=False,
            native_idle_timeout=False,
        )
        self._auto_terminate = auto_terminate
        self._cleanup = cleanup_on_terminate
        self._terminated = False

    # ----------------------------------------------------------- properties

    @property
    def handle(self) -> dict[str, Any]:
        """Best-effort working-dir descriptor.

        Reconnect is unsupported for this backend (``supports_reconnect``
        is False), so the handle exists only for diagnostic / telemetry
        symmetry. Contains no secrets.
        """
        return {"working_dir": self.working_dir}

    @property
    def underlying(self) -> object | None:
        """``LocalProcessWorkspace`` has no underlying provider client."""
        return None

    # ------------------------------------------------------------------ core

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

        run_cwd = str(cwd) if cwd is not None else self.working_dir
        Path(run_cwd).mkdir(parents=True, exist_ok=True)

        with span(
            SPAN_EXECUTE_COMMAND,
            {
                ATTR_BACKEND: type(self).__name__,
                ATTR_COMMAND: command,
                ATTR_TIMEOUT_SECONDS: timeout,
            },
        ) as s:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=run_cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError as exc:
                # Kill the process tree best-effort.
                try:
                    proc.kill()
                except ProcessLookupError:  # pragma: no cover
                    pass
                with contextlib.suppress(Exception):
                    await proc.wait()
                raise WorkspaceTimeout(command=command, timeout=timeout) from exc

            exit_code = proc.returncode if proc.returncode is not None else -1
            set_attribute(s, ATTR_EXIT_CODE, exit_code)
            return CommandResult(
                command=command,
                exit_code=exit_code,
                stdout=stdout_b.decode("utf-8", errors="replace"),
                stderr=stderr_b.decode("utf-8", errors="replace"),
                timeout_occurred=False,
            )

    async def upload(
        self,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> FileOperationResult:
        self._check_alive()
        src = Path(source)
        dst = self._resolve_workspace_path(destination)
        with span(
            SPAN_FILE_UPLOAD,
            {ATTR_BACKEND: type(self).__name__, ATTR_DST_PATH: str(dst)},
        ) as s:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copyfile, str(src), str(dst))
                size = dst.stat().st_size
                set_attribute(s, ATTR_SIZE_BYTES, size)
                return FileOperationResult(
                    success=True,
                    source_path=str(src),
                    destination_path=str(dst),
                    file_size=size,
                )
            except Exception as exc:
                return FileOperationResult(
                    success=False,
                    source_path=str(src),
                    destination_path=str(dst),
                    error=str(exc),
                )

    async def download(
        self,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> FileOperationResult:
        self._check_alive()
        src = self._resolve_workspace_path(source)
        dst = Path(destination)
        with span(
            SPAN_FILE_DOWNLOAD,
            {ATTR_BACKEND: type(self).__name__, ATTR_DST_PATH: str(dst)},
        ) as s:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copyfile, str(src), str(dst))
                size = dst.stat().st_size
                set_attribute(s, ATTR_SIZE_BYTES, size)
                return FileOperationResult(
                    success=True,
                    source_path=str(src),
                    destination_path=str(dst),
                    file_size=size,
                )
            except Exception as exc:
                return FileOperationResult(
                    success=False,
                    source_path=str(src),
                    destination_path=str(dst),
                    error=str(exc),
                )

    # --------------------------------------------------------- capabilities

    async def snapshot(self) -> str:
        raise CapabilityUnsupported(
            capability="supports_snapshot", backend=type(self).__name__
        )

    async def restore(self, snapshot_id: str) -> None:
        raise CapabilityUnsupported(
            capability="supports_snapshot", backend=type(self).__name__
        )

    async def pause(self) -> None:
        # Per workspace.md, pause() requires supports_reconnect=True.
        # A killed local process is gone; pausing here would be a no-op
        # of nothing, so we surface the unsupported capability honestly.
        raise CapabilityUnsupported(
            capability="supports_reconnect", backend=type(self).__name__
        )

    async def resume(self) -> None:
        raise CapabilityUnsupported(
            capability="supports_reconnect", backend=type(self).__name__
        )

    @classmethod
    async def reconnect(cls, handle: dict[str, Any]) -> LocalProcessWorkspace:
        """Always raises - LocalProcessWorkspace declares supports_reconnect=False.

        The handle is preserved on the exception so callers can clean up
        their state store deterministically.
        """
        raise CapabilityUnsupported(
            capability="supports_reconnect", backend=cls.__name__
        )

    async def terminate(self) -> None:
        if self._terminated:
            return
        with span(SPAN_TERMINATE, {ATTR_BACKEND: type(self).__name__}):
            self._terminated = True
            if self._cleanup and self._owns_workdir:
                try:
                    await asyncio.to_thread(
                        shutil.rmtree, self.working_dir, True
                    )
                except Exception:  # pragma: no cover - best-effort
                    pass

    # ---------------------------------------------------------- async-ctx

    async def __aenter__(self) -> LocalProcessWorkspace:
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

    def _resolve_workspace_path(self, p: str | os.PathLike[str]) -> Path:
        path = Path(p)
        if path.is_absolute():
            return path
        return Path(self.working_dir) / path


__all__ = ["LocalProcessWorkspace"]
