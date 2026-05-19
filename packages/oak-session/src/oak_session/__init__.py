"""oak.session - session rehydration, lease coordination, per-framework wrappers.

Load-bearing module. See docs/design/session.md for the canonical spec.

Public surface:

    oak.session.configure(state_store, trace, lease)
    async with oak.session.attach(session_id, ...) as attached: ...
    await oak.session.end(session_id)

Reference backends:

    InMemoryStateStore                            (default)
    RedisStateStore        [redis]
    PostgresStateStore     [postgres]
    OTLPSpansTraceSource                          (base class)
    StasoTraceSource       [staso]                (stub until SDK ships)
    InMemoryLease                                 (default)
    RedisLease             [redis]

Per-framework wrappers:

    oak.session.openhands.attach / build_session / OpenHandsSession / WorkspaceAdapter

Lazy submodules - vendor-extra adapters are not imported at package load.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._lease import InMemoryLease
from .attach import attach, end
from .configure import configure
from .context import (
    continuation_prelude,
    messages_from_session,
    partial_history_notice,
    render,
    workspace_reset_notice,
)
from .errors import (
    LeaseHeld,
    SessionEnded,
    SessionError,
    TraceSourceError,
    WorkspaceUnreachable,
)
from .models import (
    AttachedSession,
    GenAISpan,
    Lease,
    Message,
    PendingAction,
    SessionState,
    ToolCall,
    TurnResult,
)
from .protocols import LeaseManager, SessionStateStore, TraceSource
from .reconstruct import reconstruct_session
from .state_stores.in_memory import InMemoryStateStore
from .trace_sources.otlp import OTLPSpansTraceSource
from .yaml_config import OakConfigError, configure_from_yaml

if TYPE_CHECKING:
    from . import openhands as openhands
    from ._lease import RedisLease
    from .state_stores.postgres import PostgresStateStore
    from .state_stores.redis import RedisStateStore
    from .trace_sources.staso import StasoTraceSource


_LAZY: dict[str, tuple[str, str]] = {
    "RedisStateStore": ("oak_session.state_stores.redis", "RedisStateStore"),
    "PostgresStateStore": ("oak_session.state_stores.postgres", "PostgresStateStore"),
    "RedisLease": ("oak_session._lease", "RedisLease"),
    "StasoTraceSource": ("oak_session.trace_sources.staso", "StasoTraceSource"),
    "openhands": ("oak_session.openhands", ""),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        import importlib

        module_name, attr = _LAZY[name]
        module = importlib.import_module(module_name)
        return module if not attr else getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AttachedSession",
    "GenAISpan",
    "InMemoryLease",
    "InMemoryStateStore",
    "Lease",
    "LeaseHeld",
    "LeaseManager",
    "Message",
    "OTLPSpansTraceSource",
    "OakConfigError",
    "PendingAction",
    "PostgresStateStore",
    "RedisLease",
    "RedisStateStore",
    "SessionEnded",
    "SessionError",
    "SessionState",
    "SessionStateStore",
    "StasoTraceSource",
    "ToolCall",
    "TraceSource",
    "TraceSourceError",
    "TurnResult",
    "WorkspaceUnreachable",
    "attach",
    "configure",
    "configure_from_yaml",
    "continuation_prelude",
    "end",
    "messages_from_session",
    "openhands",
    "partial_history_notice",
    "reconstruct_session",
    "render",
    "workspace_reset_notice",
]
