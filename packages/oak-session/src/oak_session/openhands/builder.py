"""Mid-level ``build_session(attached, agent, initial_messages, ...)``.

Caller assembles their own message list (using ``messages_from_session`` +
notice helpers as needed) and passes it in. Returns a ready ``OpenHandsSession``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..models import AttachedSession, Message
from .wrapper import OpenHandsSession


def _to_upstream_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Best-effort mapping to upstream OH's message dict shape.

    Upstream evolves; keep this minimal. Callers reaching for full upstream
    control should drop down via ``WorkspaceAdapter`` + raw ``LocalConversation``.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        entry: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        out.append(entry)
    return out


def build_session(
    attached: AttachedSession,
    *,
    agent: Any,
    initial_messages: list[Message],
    confirmation_policy: Any | None = None,
    callbacks: list[Callable[[Any], None]] | None = None,
    session_class: type[OpenHandsSession] = OpenHandsSession,
    **conversation_kwargs: Any,
) -> OpenHandsSession:
    """Construct an ``OpenHandsSession`` wired to the attached workspace.

    ``session_class`` is Tier 3 escape: pass a subclass for full custom behaviour.
    All extra ``**conversation_kwargs`` flow directly to ``LocalConversation``.

    ``callbacks`` is forwarded verbatim to upstream ``LocalConversation``. Each
    callable fires from the executor thread on every upstream ``Event``. Pass
    ``None`` (default) to defer to upstream defaults; pass ``[]`` to register
    no callbacks explicitly.
    """
    try:
        from openhands.sdk import LocalConversation
    except ImportError as exc:  # pragma: no cover - exercised by missing extra
        raise ImportError(
            "oak.session.openhands requires the [openhands] extra: "
            "pip install oak-session[openhands]"
        ) from exc

    from .workspace_adapter import WorkspaceAdapter

    kwargs: dict[str, Any] = dict(conversation_kwargs)
    if attached.workspace is not None and "workspace" not in kwargs:
        kwargs["workspace"] = WorkspaceAdapter(attached.workspace)
    if confirmation_policy is not None:
        kwargs.setdefault("confirmation_policy", confirmation_policy)
    if callbacks is not None:
        kwargs.setdefault("callbacks", callbacks)
    if initial_messages:
        kwargs.setdefault("initial_messages", _to_upstream_messages(initial_messages))

    conv = LocalConversation(agent=agent, **kwargs)
    return session_class(conv)


__all__ = ["build_session"]
