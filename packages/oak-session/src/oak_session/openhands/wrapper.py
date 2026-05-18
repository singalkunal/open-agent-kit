"""``OpenHandsSession`` - composition wrapper around upstream ``LocalConversation``.

Composition over inheritance. We hold ``.conv`` and expose it directly for any
caller that needs to drop down to upstream APIs. Methods run upstream's sync
``conv.run()`` in a thread so the wrapper stays async.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..models import Message, PendingAction, TurnResult, TurnStatus


def _map_status(status: Any) -> TurnStatus:
    """Best-effort map upstream execution_status to oak's stable TurnStatus."""
    name = getattr(status, "name", None) or str(status)
    name = name.upper()
    if name in {"FINISHED", "COMPLETED", "DONE"}:
        return "finished"
    if name in {"WAITING_FOR_CONFIRMATION", "AWAITING_CONFIRMATION", "AWAITING_USER"}:
        return "waiting_for_confirmation"
    if name in {"ERROR", "FAILED"}:
        return "error"
    return "in_progress"


def _extract_messages(conv: Any) -> list[Message]:
    """Best-effort extract messages from upstream conversation state. Optional."""
    out: list[Message] = []
    events = getattr(getattr(conv, "state", None), "events", None) or []
    for event in events:
        role = getattr(event, "role", None)
        content = getattr(event, "content", None) or getattr(event, "text", None)
        if not role or not content:
            continue
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        out.append(Message(role=role, content=str(content)))
    return out


def _extract_pending(conv: Any) -> PendingAction | None:
    """Best-effort extract pending actions from upstream state."""
    try:
        from openhands.sdk.conversation.state import (
            ConversationState,
        )
    except ImportError:
        return None
    actions = ConversationState.get_unmatched_actions(conv.state.events)
    if not actions:
        return None
    first = actions[0]
    return PendingAction(
        action_seq=int(getattr(first, "seq", 0)),
        action_kind=str(getattr(first, "kind", first.__class__.__name__)),
        body=getattr(first, "body", {}) or {},
    )


class OpenHandsSession:
    """Async wrapper around upstream ``openhands.sdk.LocalConversation``.

    Composition only: this class never subclasses upstream. ``.conv`` is always
    accessible so callers can drop down to upstream APIs at any time.
    """

    def __init__(self, conv: Any) -> None:
        self.conv = conv

    @property
    def underlying(self) -> Any:
        """Alias for ``.conv`` to match the project convention (.underlying everywhere)."""
        return self.conv

    @property
    def execution_status(self) -> Any:
        return self.conv.state.execution_status

    @property
    def pending_actions(self) -> Any:
        try:
            from openhands.sdk.conversation.state import (
                ConversationState,
            )
        except ImportError:
            return []
        return ConversationState.get_unmatched_actions(self.conv.state.events)

    def _result(self) -> TurnResult:
        return TurnResult(
            status=_map_status(self.conv.state.execution_status),
            messages=_extract_messages(self.conv),
            pending_action=_extract_pending(self.conv),
        )

    async def run_turn(self, text: str) -> TurnResult:
        """Send a user message and drive one turn. Returns the resulting TurnResult."""
        self.conv.send_message(text)
        await asyncio.to_thread(self.conv.run)
        return self._result()

    async def approve(self) -> TurnResult:
        """Continue execution after a WAITING_FOR_CONFIRMATION pause."""
        await asyncio.to_thread(self.conv.run)
        return self._result()

    async def reject(self, reason: str) -> TurnResult:
        """Reject pending actions; agent replans."""
        self.conv.reject_pending_actions(reason)
        await asyncio.to_thread(self.conv.run)
        return self._result()


__all__ = ["OpenHandsSession"]
