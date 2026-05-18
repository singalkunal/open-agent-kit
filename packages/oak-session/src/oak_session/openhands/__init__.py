"""OpenHands per-framework wrappers.

Public API mirrors the three-level shape declared in docs/design/session.md:

  - ``attach()``        : high-level one-call assembly + session bring-up
  - ``build_session()`` : mid-level assembly (caller controls message list)
  - ``OpenHandsSession``: composition wrapper around upstream ``LocalConversation``
  - ``WorkspaceAdapter``: Tier 3 escape - direct upstream use bypassing oak helpers
"""

from __future__ import annotations

from .attach import attach
from .builder import build_session
from .workspace_adapter import WorkspaceAdapter
from .wrapper import OpenHandsSession

__all__ = ["OpenHandsSession", "WorkspaceAdapter", "attach", "build_session"]
