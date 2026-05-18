"""``attach()`` and ``end()`` - the load-bearing entry points.

Both keep their semantics frozen. Behavior changes here ripple to every
framework wrapper. See docs/design/session.md for the canonical spec.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

from oak_workspace import Workspace

from .configure import _effective_state_store, get_config
from .errors import SessionEnded, TraceSourceError, WorkspaceUnreachable
from .models import AttachedSession, Lease, SessionState
from .reconstruct import reconstruct_session

# state-store key for the "this session is over" tombstone
_ENDED_KEY = "oak:ended"
_WORKSPACE_KEY = "workspace"

ExitWorkspace = Literal["pause", "keep_alive", "terminate"]
OnWorkspaceLost = Literal["boot_fresh", "raise", "skip"]


async def _reconnect_workspace(handle: dict[str, Any]) -> Workspace:
    """Bridge to oak.workspace.reconnect.

    oak-workspace v0.1 does not yet ship a top-level ``reconnect()`` (Phase 1.3
    work). Until it does, we look the function up dynamically and raise a clear
    error if it is absent.
    """
    import oak_workspace as ws_module

    reconnect = getattr(ws_module, "reconnect", None)
    if reconnect is None:
        raise WorkspaceUnreachable(
            session_id="<unknown>",
            reason="oak_workspace.reconnect is not yet available in this version",
        )
    provider = handle.get("provider")
    handle_payload = handle.get("handle") or handle
    coro = reconnect(provider, handle_payload)
    if isinstance(coro, Awaitable):
        result: Workspace = await coro
        return result
    return coro  # type: ignore[no-any-return]


async def _safe_pause(workspace: Workspace) -> None:
    try:
        await workspace.pause()
    except Exception:
        # best-effort; do not raise from __aexit__
        pass


async def _safe_terminate(workspace: Workspace) -> None:
    try:
        await workspace.terminate()
    except Exception:
        pass


@asynccontextmanager
async def attach(
    session_id: str,
    *,
    workspace_factory: Callable[[], Awaitable[Workspace]] | None = None,
    on_workspace_lost: OnWorkspaceLost = "skip",
    wait_for_lease: bool | float = False,
    exit_workspace: ExitWorkspace = "pause",
) -> AsyncIterator[AttachedSession]:
    """Rehydrate a session and yield an ``AttachedSession``.

    See docs/design/session.md for the canonical 5-step semantics. Summary:

      1. Acquire lease (if configured)
      2. Reconnect workspace from state_store handle (or boot fresh via factory)
      3. Fetch + reconstruct messages from trace source
      4. Yield AttachedSession
      5. On exit: apply ``exit_workspace`` policy and release lease
    """
    config = get_config()
    store = _effective_state_store()

    # 0. Refuse re-attach to an ended session
    if await store.get(session_id, _ENDED_KEY) is not None:
        raise SessionEnded(session_id)

    # 1. Lease
    lease: Lease | None = None
    if config.lease is not None:
        lease = await config.lease.acquire(session_id, wait_for_lease=wait_for_lease)

    # 2. Workspace
    workspace: Workspace | None = None
    workspace_status: Literal["no_prior", "reattached", "reconnect_failed", "boot_fresh"]
    workspace_reconnect_error: str | None = None
    try:
        handle = await store.get(session_id, _WORKSPACE_KEY)
        if handle is not None:
            try:
                workspace = await _reconnect_workspace(handle)
                workspace_status = "reattached"
            except Exception as exc:
                workspace_reconnect_error = str(exc)
                if on_workspace_lost == "boot_fresh":
                    if workspace_factory is None:
                        raise WorkspaceUnreachable(
                            session_id,
                            "on_workspace_lost='boot_fresh' but no workspace_factory provided",
                        ) from exc
                    workspace = await workspace_factory()
                    workspace_status = "boot_fresh"
                elif on_workspace_lost == "raise":
                    raise WorkspaceUnreachable(session_id, str(exc)) from exc
                else:  # "skip"
                    workspace = None
                    workspace_status = "reconnect_failed"
        else:
            if workspace_factory is not None:
                workspace = await workspace_factory()
                workspace_status = "boot_fresh"
            else:
                workspace_status = "no_prior"

        # 3. Trace fetch + reconstruct
        state = SessionState()
        trace_status: Literal["loaded", "partial", "no_prior", "unavailable"]
        trace_error: str | None = None
        if config.trace is not None:
            try:
                spans = await config.trace.fetch_session_spans(session_id)
            except TraceSourceError as exc:
                trace_status = "unavailable"
                trace_error = str(exc)
                spans = []
            except Exception as exc:
                trace_status = "unavailable"
                trace_error = str(exc)
                spans = []
            else:
                if not spans:
                    trace_status = "no_prior"
                else:
                    trace_status = "loaded"
            if spans:
                reconstructor = config.reconstructor or reconstruct_session
                try:
                    state = reconstructor(spans)
                except Exception as exc:
                    trace_status = "partial"
                    trace_error = str(exc)
        else:
            trace_status = "no_prior"

        attached = AttachedSession(
            session_id=session_id,
            lease=lease,
            workspace=workspace,
            state=state,
            workspace_status=workspace_status,
            workspace_reconnect_error=workspace_reconnect_error,
            trace_status=trace_status,
            trace_error=trace_error,
        )

        # 4. Yield
        yield attached

    finally:
        # 5. Cleanup
        try:
            if workspace is not None:
                if exit_workspace == "pause":
                    await _safe_pause(workspace)
                elif exit_workspace == "terminate":
                    await _safe_terminate(workspace)
                # "keep_alive": no-op
        finally:
            if lease is not None and config.lease is not None:
                try:
                    await config.lease.release(session_id)
                except Exception:
                    pass


async def end(session_id: str) -> None:
    """Terminate the session: kill workspace, clear state, tombstone the session.

    Idempotent. Subsequent ``attach()`` raises ``SessionEnded``.
    """
    config = get_config()
    store = _effective_state_store()

    if await store.get(session_id, _ENDED_KEY) is not None:
        return  # already ended

    # Best-effort force-reclaim lease so end() always wins
    if config.lease is not None:
        try:
            await config.lease.acquire(session_id, force_reclaim=True)
        except Exception:
            pass

    handle = await store.get(session_id, _WORKSPACE_KEY)
    if handle is not None:
        try:
            workspace = await _reconnect_workspace(handle)
        except Exception:
            workspace = None
        if workspace is not None:
            await _safe_terminate(workspace)

    await store.delete_session(session_id)
    # Re-tombstone after the delete clears everything
    await store.put(session_id, _ENDED_KEY, {"ended": True})

    if config.lease is not None:
        try:
            await config.lease.release(session_id)
        except Exception:
            pass


__all__ = ["attach", "end"]
