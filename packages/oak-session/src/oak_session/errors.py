"""Error types raised by oak.session."""

from __future__ import annotations


class SessionError(Exception):
    """Base error for oak.session."""


class SessionEnded(SessionError):
    """Raised by attach() when the session has been ended via end().

    Not overridable. Callers must observe end() as terminal.
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session {session_id!r} has been ended")
        self.session_id = session_id


class LeaseHeld(SessionError):
    """Raised by the lease manager when another live owner holds the lease."""

    def __init__(self, session_id: str, owner: str | None = None) -> None:
        msg = f"lease for {session_id!r} held by another owner"
        if owner:
            msg = f"{msg} ({owner})"
        super().__init__(msg)
        self.session_id = session_id
        self.owner = owner


class WorkspaceUnreachable(SessionError):
    """Raised when a prior workspace handle cannot be reconnected and policy requires raising."""

    def __init__(self, session_id: str, reason: str) -> None:
        super().__init__(f"workspace for {session_id!r} unreachable: {reason}")
        self.session_id = session_id
        self.reason = reason


class TraceSourceError(SessionError):
    """Raised by a TraceSource when the backend is unreachable or returns an error.

    Adapters MUST NOT silently swallow backend errors. Raise this (or a documented
    subclass) so attach() can surface the failure as trace_status='unavailable'.
    """
