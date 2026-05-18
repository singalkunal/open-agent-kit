"""Result + capability types for the Workspace protocol.

These are plain dataclasses to avoid a hard pydantic dependency in the
core package. Backends that ship pydantic models can pass dicts that
match the dataclass shape or instantiate these types directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass
class CommandResult:
    """Result of a single `execute()` call.

    `exit_code` is the integer exit status of the command. Non-zero is
    NOT raised as an exception. Exit codes are data, not errors.
    `timeout_occurred` is True only when the command was killed by the
    timeout enforcer. When True, callers receive the partial stdout/stderr
    captured before the kill, and the underlying impl raises
    `WorkspaceTimeout` instead of returning this result.
    """

    command: str
    exit_code: int
    stdout: str
    stderr: str
    timeout_occurred: bool = False


@dataclass
class FileOperationResult:
    """Result of `upload()` or `download()`.

    `file_size` is the size in bytes of the source file on success.
    `error` is populated only when `success is False`.
    """

    success: bool
    source_path: str
    destination_path: str
    file_size: int | None = None
    error: str | None = None


# Compatibility alias for the spec name in workspace.md.
ExecuteResult = CommandResult


@dataclass
class WorkspaceCapabilities:
    """Honest declaration of what a backend supports.

    Per principles.md §6, every adapter declares these explicitly so
    callers branch on reality rather than encountering runtime
    `NotImplementedError`s.

    Flags:

    * ``supports_reconnect`` - backend exposes a serializable ``handle``
      and a ``reconnect()`` classmethod that can re-attach to a paused /
      preserved sandbox from a different process. Backends that set this
      to False also do not meaningfully support ``pause()`` (pausing a
      thing you cannot reconnect to is a no-op of nothing).
    * ``native_idle_timeout`` - the provider has its own idle-timeout
      configuration (e.g. E2B's ``timeout_ms``) and ``create()`` passes
      that config through. oak does NOT run a background reconciler;
      this flag tells callers the provider will auto-pause / auto-
      terminate on its own.

    Legacy flag (kept for backward-compat during the v0.1 transition):

    * ``supports_persistence`` mirrors ``supports_reconnect`` and is the
      name still used by the LocalDocker adapter and a handful of
      contract tests written before the rename. New code should read
      ``supports_reconnect``.
    """

    supports_snapshot: bool = False
    supports_gpu: bool = False
    supports_reconnect: bool = False
    supports_persistence: bool = False  # legacy alias for supports_reconnect
    native_idle_timeout: bool = False
    supports_browser: bool = False
    supports_port_forward: bool = False
    max_idle: timedelta | None = None
    max_lifetime: timedelta | None = None

    def __post_init__(self) -> None:
        # Keep the legacy `supports_persistence` flag in lockstep with
        # the canonical `supports_reconnect` flag so older call sites
        # continue to read True/False consistently with new ones.
        if self.supports_reconnect and not self.supports_persistence:
            self.supports_persistence = True
        elif self.supports_persistence and not self.supports_reconnect:
            self.supports_reconnect = True


__all__ = [
    "CommandResult",
    "ExecuteResult",
    "FileOperationResult",
    "WorkspaceCapabilities",
]
