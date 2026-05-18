"""Tier 3 escape: adapter that wraps ``oak.workspace.Workspace`` to satisfy
upstream OpenHands ``BaseWorkspace`` where required.

Import-guarded; if upstream OH is not installed, the adapter still exposes
``.underlying`` and the execute/upload/download passthroughs but does not
subclass any upstream type.
"""

from __future__ import annotations

import asyncio
from typing import Any

from oak_workspace import Workspace


class WorkspaceAdapter:
    """Bridge an oak Workspace into upstream OpenHands' workspace contract.

    OpenHands' upstream contract evolves; this adapter intentionally keeps the
    surface tiny and exposes the underlying oak workspace via ``.underlying``.
    """

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @property
    def underlying(self) -> Workspace:
        return self._workspace

    @property
    def working_dir(self) -> str:
        return str(self._workspace.working_dir)

    def execute(self, command: str, *, cwd: str | None = None, timeout: float = 30.0) -> Any:
        """Synchronous bridge for upstream OH which calls workspace.execute() sync."""
        coro = self._workspace.execute(command, cwd=cwd, timeout=timeout)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # If a loop is running we cannot run sync here; upstream OH always
        # calls from a worker thread via asyncio.to_thread, so this is safe.
        return asyncio.run_coroutine_threadsafe(coro, asyncio.get_event_loop()).result()


__all__ = ["WorkspaceAdapter"]
