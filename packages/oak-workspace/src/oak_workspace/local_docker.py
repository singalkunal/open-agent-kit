"""`LocalDockerWorkspace`: Step 2 quickstart upgrade.

Spawns a long-running container and shells in via `docker exec`. Uploads
and downloads use the docker SDK's `put_archive`/`get_archive` tar API
so we never depend on the host having `docker cp` on PATH.

Requires the `[docker]` extra: `pip install oak-workspace[docker]`.
"""

from __future__ import annotations

import asyncio
import io
import os
import tarfile
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
    SPAN_PAUSE,
    SPAN_RESUME,
    SPAN_TERMINATE,
    set_attribute,
    span,
)
from .types import CommandResult, FileOperationResult, WorkspaceCapabilities


class LocalDockerWorkspace:
    """Docker-backed workspace. Real isolation via container, no cloud account."""

    def __init__(
        self,
        image: str = "python:3.12-slim",
        *,
        working_dir: str = "/work",
        command: list[str] | None = None,
        auto_terminate: bool = True,
        client: Any = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.image = image
        self.working_dir = working_dir
        self._command = command or ["sleep", "infinity"]
        self._auto_terminate = auto_terminate
        self._environment = environment or {}

        self.capabilities = WorkspaceCapabilities(
            supports_reconnect=True,
            supports_snapshot=False,
        )
        self._terminated = False
        self._client = client
        self._container: Any = None

    # ----------------------------------------------------------- properties

    @property
    def handle(self) -> dict[str, Any]:
        """Reconnect handle: container id + image (no secrets)."""
        out: dict[str, Any] = {"image": self.image}
        if self._container is not None:
            cid = getattr(self._container, "id", None)
            if cid is not None:
                out["container_id"] = cid
        return out

    @property
    def underlying(self) -> object | None:
        """The raw docker-py ``Container`` instance (or ``None`` pre-boot)."""
        c: object | None = self._container
        return c

    @classmethod
    async def reconnect(cls, handle: dict[str, Any]) -> LocalDockerWorkspace:
        """Re-attach to a running docker container by ``container_id``."""
        # Local-import to keep the package importable without docker.
        from .errors import WorkspaceUnreachable

        container_id = handle.get("container_id")
        if not isinstance(container_id, str) or not container_id:
            raise WorkspaceUnreachable(
                handle=handle,
                reason="handle missing 'container_id' field",
            )
        try:
            import docker
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "LocalDockerWorkspace requires the [docker] extra"
            ) from exc
        try:
            client = docker.from_env()
            container = await asyncio.to_thread(
                client.containers.get, container_id
            )
        except Exception as exc:  # noqa: BLE001 - docker errors vary
            raise WorkspaceUnreachable(
                handle=handle,
                reason=f"{type(exc).__name__}: {exc}",
            ) from exc
        image = handle.get("image") or "python:3.12-slim"
        ws = cls(image=image if isinstance(image, str) else "python:3.12-slim")
        ws._client = client
        ws._container = container
        return ws

    # ----------------------------------------------------------- lifecycle

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import docker
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "LocalDockerWorkspace requires the [docker] extra: "
                "pip install oak-workspace[docker]"
            ) from exc
        self._client = docker.from_env()
        return self._client

    async def _ensure_container(self) -> Any:
        if self._container is not None:
            return self._container
        client = self._ensure_client()
        self._container = await asyncio.to_thread(
            client.containers.run,
            self.image,
            self._command,
            detach=True,
            working_dir=self.working_dir,
            environment=self._environment,
            tty=False,
            remove=False,
        )
        # Create working_dir inside the container.
        await asyncio.to_thread(
            self._container.exec_run, ["mkdir", "-p", self.working_dir]
        )
        return self._container

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
        container = await self._ensure_container()
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
                    asyncio.to_thread(
                        container.exec_run,
                        ["sh", "-c", command],
                        workdir=workdir,
                        demux=True,
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                raise WorkspaceTimeout(command=command, timeout=timeout) from exc

            exit_code = int(getattr(result, "exit_code", 0) or 0)
            out_b, err_b = result.output if isinstance(result.output, tuple) else (
                result.output,
                b"",
            )
            stdout = (out_b or b"").decode("utf-8", errors="replace")
            stderr = (err_b or b"").decode("utf-8", errors="replace")
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
        container = await self._ensure_container()
        src = Path(source)
        dst = Path(destination)
        with span(
            SPAN_FILE_UPLOAD,
            {ATTR_BACKEND: type(self).__name__, ATTR_DST_PATH: str(dst)},
        ) as s:
            try:
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    tar.add(str(src), arcname=dst.name)
                buf.seek(0)
                await asyncio.to_thread(
                    container.put_archive, str(dst.parent), buf.read()
                )
                size = src.stat().st_size
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
        container = await self._ensure_container()
        src = Path(source)
        dst = Path(destination)
        with span(
            SPAN_FILE_DOWNLOAD,
            {ATTR_BACKEND: type(self).__name__, ATTR_DST_PATH: str(dst)},
        ) as s:
            try:
                stream, _stat = await asyncio.to_thread(
                    container.get_archive, str(src)
                )
                buf = io.BytesIO(b"".join(stream))
                buf.seek(0)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with tarfile.open(fileobj=buf, mode="r") as tar:
                    member = tar.getmember(src.name)
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        raise RuntimeError(f"cannot read {src} from container tar")
                    data = extracted.read()
                dst.write_bytes(data)
                size = len(data)
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
        container = await self._ensure_container()
        with span(SPAN_PAUSE, {ATTR_BACKEND: type(self).__name__}):
            try:
                await asyncio.to_thread(container.pause)
            except Exception:  # pragma: no cover
                pass

    async def resume(self) -> None:
        if not self.capabilities.supports_reconnect:
            raise CapabilityUnsupported(
                capability="supports_reconnect", backend=type(self).__name__
            )
        self._check_alive()
        container = await self._ensure_container()
        with span(SPAN_RESUME, {ATTR_BACKEND: type(self).__name__}):
            try:
                await asyncio.to_thread(container.unpause)
            except Exception:  # pragma: no cover
                pass

    async def terminate(self) -> None:
        if self._terminated:
            return
        self._terminated = True
        with span(SPAN_TERMINATE, {ATTR_BACKEND: type(self).__name__}):
            container = self._container
            if container is not None:
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except Exception:  # pragma: no cover - best-effort
                    pass

    # ---------------------------------------------------------- async-ctx

    async def __aenter__(self) -> LocalDockerWorkspace:
        await self._ensure_container()
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


__all__ = ["LocalDockerWorkspace"]
