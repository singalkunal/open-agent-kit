"""Process-level configuration for oak.session.

Stores the active backends + reconstructor + notice overrides in a singleton.
The singleton is mutable so tests and long-lived processes can reconfigure
between runs. ``attach()`` reads from this singleton at call time, not at
import time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import GenAISpan, SessionState
    from .protocols import LeaseManager, SessionStateStore, TraceSource

Reconstructor = Callable[[list["GenAISpan"]], "SessionState"]


@dataclass
class _Config:
    state_store: SessionStateStore | None = None
    trace: TraceSource | None = None
    lease: LeaseManager | None = None
    reconstructor: Reconstructor | None = None
    notice_text: dict[str, str] = field(default_factory=dict)


_config = _Config()


def configure(
    state_store: SessionStateStore | None = None,
    trace: TraceSource | None = None,
    lease: LeaseManager | None = None,
    *,
    reconstructor: Reconstructor | None = None,
    notice_text: dict[str, str] | None = None,
) -> None:
    """Wire process-level backends. Call once at startup.

    Passing ``None`` for a backend resets to the default behaviour:
      - ``state_store=None``  : an in-memory store is used implicitly.
      - ``trace=None``        : no history reconstruction; state stays empty.
      - ``lease=None``        : no ownership coordination (single-process mode).

    ``reconstructor`` overrides the default ``reconstruct_session`` callable.
    ``notice_text`` keys: ``workspace_reset``, ``continuation``, ``partial_history``.
    """
    _config.state_store = state_store
    _config.trace = trace
    _config.lease = lease
    _config.reconstructor = reconstructor
    if notice_text is not None:
        _config.notice_text = dict(notice_text)


def get_config() -> _Config:
    return _config


def _reset_for_tests() -> None:
    """Test-only hook. Restore defaults between tests."""
    global _config
    _config = _Config()


def _effective_state_store() -> SessionStateStore:
    """Return the configured state store or lazily create an in-memory default."""
    from .state_stores.in_memory import InMemoryStateStore

    if _config.state_store is None:
        store: Any = InMemoryStateStore()
        _config.state_store = store
    return _config.state_store


__all__ = ["configure", "get_config"]
