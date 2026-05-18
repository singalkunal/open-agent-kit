"""Framework-neutral dataclasses for oak.session.

Pure data shapes. No backend-coupled fields. Mutable where the user is invited to
mutate (`AttachedSession.extra`, `SessionState.messages`); frozen where the value
must be append-only or carries identity (`Lease`, `Message`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from oak_workspace import Workspace

Role = Literal["system", "user", "assistant", "tool"]
WorkspaceStatus = Literal["no_prior", "reattached", "reconnect_failed", "boot_fresh"]
TraceStatus = Literal["loaded", "partial", "no_prior", "unavailable"]
TurnStatus = Literal["finished", "waiting_for_confirmation", "in_progress", "error"]


@dataclass
class Message:
    """A framework-agnostic typed message.

    Render to an SDK-specific shape via `oak.session.render.for_<framework>(messages)`.
    """

    role: Role
    content: str
    tool_call_id: str | None = None
    cache_breakpoint: bool = False


@dataclass
class ToolCall:
    """A historical tool invocation record reconstructed from spans."""

    tool_call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: str | None = None
    error: str | None = None


@dataclass
class PendingAction:
    """A pending action waiting on an approval gate.

    Populated by the per-framework wrapper when the agent stops at a confirmation
    boundary. Cleared on approve / reject.
    """

    action_seq: int
    action_kind: str
    body: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    """The framework-neutral rehydrated state for a session."""

    messages: list[Message] = field(default_factory=list)
    tool_history: list[ToolCall] = field(default_factory=list)
    pending_action: PendingAction | None = None


@dataclass(frozen=True)
class Lease:
    """An acquired ownership lease for a single session.

    Created and returned by a LeaseManager. Immutable from the caller's point of
    view; renewal updates internal expiry but does not mutate this object.
    """

    session_id: str
    owner: str
    generation: int
    acquired_at: float
    ttl_seconds: float


@dataclass
class GenAISpan:
    """A normalized span carrying OTel gen_ai.* and workspace.* attributes.

    TraceSource adapters convert vendor-specific span shapes into this form.
    """

    span_id: str
    name: str
    start_time_unix_nano: int
    end_time_unix_nano: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str | None = None


@dataclass
class TurnResult:
    """Outcome of one wrapper-driven agent turn.

    Wrappers return this from `run_turn`, `approve`, `reject`. Status mirrors the
    upstream execution state mapped to a stable oak-side enum.
    """

    status: TurnStatus
    messages: list[Message] = field(default_factory=list)
    pending_action: PendingAction | None = None
    error: str | None = None


@dataclass
class AttachedSession:
    """Result of `attach(session_id)`. Returned by the async context manager."""

    session_id: str
    lease: Lease | None
    workspace: Workspace | None
    state: SessionState
    workspace_status: WorkspaceStatus
    trace_status: TraceStatus
    workspace_reconnect_error: str | None = None
    trace_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "AttachedSession",
    "GenAISpan",
    "Lease",
    "Message",
    "PendingAction",
    "Role",
    "SessionState",
    "ToolCall",
    "TraceStatus",
    "TurnResult",
    "TurnStatus",
    "WorkspaceStatus",
]
