"""The `Workspace` Protocol.

Eight async methods + ``handle`` / ``underlying`` properties + capabilities
+ lifecycle hooks. Implementations SHOULD honour the capability-flag ->
method binding declared in ``docs/design/workspace.md``: every capability-
dependent method checks its flag at the top of its body and raises
``CapabilityUnsupported`` if False.

``workspace.boot`` OTel span attribute schema (stable wire format,
SemVer + deprecation window required to change):

============================== ============================ ==========================================
Attribute                      Type                         Example
============================== ============================ ==========================================
``workspace.provider``         str                          ``"e2b"`` / ``"local"`` / ``"daytona"``
``workspace.handle``           str (JSON-encoded dict)      ``'{"sandbox_id": "sb-x7f9k2"}'``
``workspace.region``           str (optional)               ``"us-east-1"``
``workspace.image``            str (optional)               ``"python-3.12"``
``workspace.created_at``       str (ISO 8601 datetime)      ``"2026-05-19T14:23:01Z"``
============================== ============================ ==========================================

The same schema is reused on the ``workspace.reconnect`` span emitted by
``oak.workspace.reconnect()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .types import CommandResult, FileOperationResult, WorkspaceCapabilities


@runtime_checkable
class Workspace(Protocol):
    """Sandbox protocol. All methods are async. Sync wrappers ship separately."""

    working_dir: str
    capabilities: WorkspaceCapabilities

    @property
    def handle(self) -> dict[str, Any]:
        """Serializable reconnect handle.

        Goes into ``oak.session``'s state_store AND into the
        ``workspace.boot`` OTel span attributes. MUST NOT contain
        secrets (auth is reapplied via the provider's already-configured
        client at reconnect time).

        Values must be JSON-serializable primitives (str / int / bool /
        list / nested-dict). Backends without remote state (e.g.
        ``LocalProcessWorkspace``) may return a small descriptor like
        ``{"working_dir": "/tmp/oak"}`` or an empty dict.
        """
        ...

    @property
    def underlying(self) -> object | None:
        """Provider's raw client / sandbox object, for escape-hatch access.

        Returns ``None`` for backends without an underlying client
        (e.g. ``LocalProcessWorkspace``). Used by advanced callers that
        need provider-specific APIs not exposed by the Workspace
        Protocol - per principles.md, escape hatches are always
        present.
        """
        ...

    async def execute(
        self,
        command: str,
        *,
        cwd: str | Path | None = None,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Run `command` in the workspace.

        Returns a `CommandResult`. Non-zero exit codes are NOT raised.
        They are returned as data. Raises `WorkspaceTimeout` if the
        command exceeds `timeout` seconds. Raises `WorkspaceTerminated`
        if called after `terminate()`. Raises `ValueError` if `timeout`
        exceeds `capabilities.max_lifetime`.
        """
        ...

    async def upload(
        self,
        source: str | Path,
        destination: str | Path,
    ) -> FileOperationResult:
        """Copy a host file to the workspace."""
        ...

    async def download(
        self,
        source: str | Path,
        destination: str | Path,
    ) -> FileOperationResult:
        """Copy a file from the workspace to the host."""
        ...

    async def snapshot(self) -> str:
        """Return snapshot ID. Raises CapabilityUnsupported if capabilities.supports_snapshot is False."""
        ...

    async def restore(self, snapshot_id: str) -> None:
        """Restore from snapshot. Raises CapabilityUnsupported if capabilities.supports_snapshot is False.

        Post-condition: workspace state matches that captured by snapshot(). Idempotent.
        """
        ...

    async def pause(self) -> None:
        """Pause the sandbox so it stops consuming compute but state is preserved.

        Post-condition: subsequent execute() calls will block until resume().
        Idempotent: calling pause() on an already-paused workspace is a no-op.
        Raises CapabilityUnsupported if capabilities.supports_reconnect is False
        (a workspace that cannot be reconnected to cannot meaningfully pause -
        pausing a thing you cannot resume is a no-op of nothing).
        """
        ...

    async def resume(self) -> None:
        """Resume a paused sandbox. Post-condition: execute() works again, state from
        pre-pause is preserved. Idempotent: calling resume() on a running workspace
        is a no-op. Raises if the workspace was terminated (use create() instead).
        """
        ...

    async def terminate(self) -> None:
        """Destroy the sandbox unconditionally. State is NOT preserved. After terminate(),
        all other methods raise WorkspaceTerminated. Idempotent: calling terminate()
        on an already-terminated workspace is a no-op (does not raise). The implementation
        SHOULD be best-effort. Log and swallow exceptions from the underlying provider
        rather than propagating, since terminate() is most often called from cleanup paths
        where the caller can't usefully handle a failure.
        """
        ...

    @classmethod
    async def reconnect(cls, handle: dict[str, Any]) -> Workspace:
        """Re-attach to a paused / preserved sandbox by its serialized ``handle``.

        Symmetric with the ``handle`` property: a handle obtained from
        ``ws.handle`` and persisted to oak.session's state_store can be
        passed back here (possibly in a different process) to
        obtain a working Workspace pointed at the same sandbox.

        Raises ``CapabilityUnsupported`` (``capability='supports_reconnect'``)
        on backends whose capability flag is False.

        Raises ``WorkspaceUnreachable`` if the provider reports the
        sandbox no longer exists (GC'd, terminated, region down). The
        exception carries the original ``handle`` so callers can clear
        the stale state-store entry.
        """
        ...

    async def __aenter__(self) -> Workspace: ...

    async def __aexit__(self, *exc: object) -> None:
        """Implementations SHOULD call self.terminate() in __aexit__ unless the
        workspace was constructed with `auto_terminate=False`.
        """
        ...


__all__ = ["Workspace"]
