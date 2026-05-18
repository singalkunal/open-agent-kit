"""Backend Protocols. User-pluggable; reference impls ship under
`oak_session.state_stores`, `oak_session.trace_sources`, and `oak_session._lease`.

Keep these small. Each method MUST stay implementable without adopting any oak
internals: only stdlib types and the dataclasses in `oak_session.models` cross
the boundary.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import GenAISpan, Lease


@runtime_checkable
class SessionStateStore(Protocol):
    """Durable backend for critical session state (workspace handles, pending actions).

    Documented key namespace (see docs/design/session.md):

      - ``workspace``       : ``{provider, handle, region, image, created_at}``
      - ``pending_action``  : ``{action_seq, action_kind, body, ...}``

    Reserved key prefix: ``oak:*``. User-application keys SHOULD use a non-``oak:`` prefix.

    Implementations MUST satisfy the contract suite at
    ``oak_session.tests.test_state_store_contract``.
    """

    async def put(self, session_id: str, key: str, value: dict[str, Any]) -> None: ...

    async def get(self, session_id: str, key: str) -> dict[str, Any] | None: ...

    async def delete_session(self, session_id: str) -> None: ...


@runtime_checkable
class TraceSource(Protocol):
    """Read-side adapter for a tracing backend.

    Returns OTel ``gen_ai.*``-shaped spans for a single session_id, in ascending
    start-time order. Implementations MUST auto-paginate internally; callers do
    not page.

    On backend failure (unreachable, unauthorized) implementations MUST raise
    ``oak_session.errors.TraceSourceError`` rather than returning ``[]``.
    """

    async def fetch_session_spans(self, session_id: str) -> list[GenAISpan]: ...


@runtime_checkable
class LeaseManager(Protocol):
    """Coordination backend that grants exclusive ownership of a session_id.

    Internal-by-default. Configured via ``oak.session.configure(lease=...)``;
    user code does not call ``acquire/renew/release`` directly under normal flow.

    Implementations MAY honour ``force_reclaim=True`` to override a live owner.
    They MUST honour ``wait_for_lease: bool | float`` per session.md.
    """

    async def acquire(
        self,
        session_id: str,
        *,
        wait_for_lease: bool | float = False,
        force_reclaim: bool = False,
    ) -> Lease: ...

    async def renew(self, session_id: str) -> None: ...

    async def release(self, session_id: str) -> None: ...


__all__ = ["LeaseManager", "SessionStateStore", "TraceSource"]
