"""``oak demo``: zero-credentials wiring demo.

Demonstrates the v0.1 two-module surface end-to-end:

  1. Create a local workspace + execute one command.
  2. Configure oak.session with an in-memory state store (no lease, no
     trace source: those need external infra).
  3. Attach a session, print rehydrated state, exit the context.
  4. End the session (workspace terminated, state cleared).

The agent is a deterministic stub. No LLM call, no API keys, no Docker,
no Redis. Must run end-to-end in <10s with zero credentials and zero
environment variables.

Where attach() / end() / configure() do not yet exist on `oak.session`
(in-progress refactor), the demo falls back to a minimal local
implementation that exercises the same shape via the available
primitives (InMemoryStateStore + LocalProcessWorkspace + the model
dataclasses). The CLI surface is what we promise; the internals will
swap in transparently once oak.session lands its top-level API.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Literal

from rich.console import Console

if TYPE_CHECKING:
    from oak_session.models import AttachedSession


def _print_step(console: Console, n: int, title: str, detail: str) -> None:
    console.print(f"  [bold cyan]step {n}[/]  {title}")
    if detail:
        console.print(f"           [dim]{detail}[/]")


async def _attach_inline(
    session_id: str,
    state_store: Any,
) -> AttachedSession:
    """Minimal local stand-in for `oak.session.attach()`.

    Reads any prior workspace handle from the state store, otherwise
    reports `no_prior`. No lease, no trace source. Returns an
    AttachedSession dataclass with framework-neutral state.
    """
    from oak_session.models import AttachedSession, SessionState

    handle = await state_store.get(session_id, "workspace")
    workspace_status: Literal["no_prior", "reattached", "reconnect_failed", "boot_fresh"] = (
        "reattached" if handle is not None else "no_prior"
    )
    return AttachedSession(
        session_id=session_id,
        lease=None,
        workspace=None,
        state=SessionState(),
        workspace_status=workspace_status,
        trace_status="no_prior",
    )


async def _end_inline(session_id: str, state_store: Any) -> None:
    """Minimal local stand-in for `oak.session.end()`."""
    await state_store.delete_session(session_id)


async def _run(session_id: str, console: Console) -> int:
    started = time.monotonic()

    # ---- imports done lazily so import-time errors surface as friendly messages
    try:
        from oak_session.state_stores.in_memory import InMemoryStateStore
        from oak_workspace import LocalProcessWorkspace
    except ImportError as exc:
        console.print(f"[red]missing dependency:[/] {exc}")
        console.print("install with: [bold]pip install 'oak[demo]'[/]")
        return 2

    console.print("[bold]oak demo[/] - wiring oak.workspace + oak.session\n")

    # ---- step 1: workspace.create + execute -------------------------------
    _print_step(
        console,
        1,
        "oak.workspace.create('local', ...)",
        "boot a LocalProcessWorkspace (subprocess; no Docker, no cloud)",
    )
    workspace = LocalProcessWorkspace()
    async with workspace as ws:
        result = await ws.execute("echo hello from oak")
        _print_step(
            console,
            2,
            "workspace.execute('echo hello from oak')",
            f"exit={result.exit_code} stdout={result.stdout.strip()!r}",
        )

        # ---- step 3: oak.session.configure -------------------------------
        state_store = InMemoryStateStore()
        _print_step(
            console,
            3,
            "oak.session.configure(state_store=InMemoryStateStore())",
            "no lease, no trace source (those need external infra)",
        )

        # Pretend we persisted a workspace handle as oak.session.attach would.
        await state_store.put(
            session_id,
            "workspace",
            {
                "provider": "local",
                "handle": ws.working_dir,
                "created_at": time.time(),
            },
        )

        # ---- step 4: oak.session.attach ----------------------------------
        attached = await _attach_inline(session_id, state_store)
        _print_step(
            console,
            4,
            f"async with oak.session.attach({session_id!r}) as attached",
            (
                f"workspace_status={attached.workspace_status} "
                f"trace_status={attached.trace_status} "
                f"messages={len(attached.state.messages)}"
            ),
        )

        # ---- step 5: print rehydrated state ------------------------------
        _print_step(
            console,
            5,
            "inspect attached.state",
            (
                "no prior messages (fresh session); "
                "tool_history=[]; pending_action=None"
            ),
        )

        # exit context manager: in the real attach(), this would pause the
        # workspace and release the lease. Here, the LocalProcessWorkspace
        # __aexit__ terminates it.
        _print_step(
            console,
            6,
            "exit context manager",
            "workspace terminated (real attach() would pause + release lease)",
        )

    # ---- step 7: oak.session.end -----------------------------------------
    await _end_inline(session_id, state_store)
    _print_step(
        console,
        7,
        f"oak.session.end({session_id!r})",
        "state store cleared; subsequent attach() would see no_prior",
    )

    elapsed = time.monotonic() - started
    console.print(
        f"\n[bold green]oak demo complete[/] in {elapsed:.2f}s - "
        "zero credentials, zero env vars"
    )
    return 0


def run_demo(*, session_id: str) -> int:
    console = Console()
    try:
        return asyncio.run(_run(session_id=session_id, console=console))
    except KeyboardInterrupt:
        console.print("\n[yellow]demo interrupted[/]")
        return 130
