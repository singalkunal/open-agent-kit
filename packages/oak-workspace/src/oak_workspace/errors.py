"""Error classes for the Workspace protocol.

Per workspace.md, the following error classes are exposed:

* ``WorkspaceError``        : base class
* ``CapabilityUnsupported`` : protocol method called against a backend
                              whose capability flag is False
* ``WorkspaceTerminated``   : any method called on a terminated workspace
* ``WorkspaceTimeout``      : ``execute()`` exceeded its timeout
* ``WorkspaceUnreachable``  : ``reconnect()`` failed (sandbox GC'd or
                              otherwise no longer reachable at the
                              provider). Carries the ``handle`` and a
                              human-readable ``reason``.

Capability-dependent methods MUST raise ``CapabilityUnsupported(capability=...,
backend=type(self).__name__)`` rather than silently no-op. No silent fallbacks.
"""

from __future__ import annotations


class WorkspaceError(Exception):
    """Base class for all workspace errors."""


class CapabilityUnsupported(WorkspaceError):
    """Raised when a Protocol method is called against a backend whose capability flag is False.

    Carries the capability name so callers can branch:

        try:
            sid = await workspace.snapshot()
        except CapabilityUnsupported as e:
            assert e.capability == "supports_snapshot"
    """

    def __init__(self, capability: str, backend: str | None = None) -> None:
        self.capability = capability
        self.backend = backend
        super().__init__(
            f"Backend{f' {backend!r}' if backend else ''} does not support {capability}"
        )


class WorkspaceTerminated(WorkspaceError):
    """Raised when any method is called on a workspace after `terminate()`."""


class WorkspaceTimeout(WorkspaceError):
    """Raised when `execute()` exceeds its timeout. Carries `command` and `timeout`."""

    def __init__(self, command: str, timeout: float) -> None:
        self.command = command
        self.timeout = timeout
        super().__init__(f"command timed out after {timeout}s: {command!r}")


class WorkspaceUnreachable(WorkspaceError):
    """Raised when ``reconnect()`` fails - the sandbox no longer exists at the provider.

    Carries the original ``handle`` (so callers can log / diagnose / delete
    the stale state-store entry) and a human-readable ``reason`` string
    summarising what the provider SDK reported.
    """

    def __init__(self, handle: dict[str, object], reason: str) -> None:
        self.handle = handle
        self.reason = reason
        super().__init__(f"workspace unreachable: {reason} (handle={handle})")


__all__ = [
    "CapabilityUnsupported",
    "WorkspaceError",
    "WorkspaceTerminated",
    "WorkspaceTimeout",
    "WorkspaceUnreachable",
]
