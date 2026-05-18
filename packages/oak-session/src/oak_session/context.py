"""Stateless context helpers: message extraction, status notices, and
framework-shape rendering.

These functions don't compete with prompt frameworks (LangChain, Mirascope,
DSPy). Bring your system prompt as a string; oak handles session-aware notices
and shape rendering only.
"""

from __future__ import annotations

from typing import Any

from .configure import get_config
from .models import AttachedSession, Message

_DEFAULT_NOTICES = {
    "workspace_reset": (
        "Note: the prior workspace was unreachable and has been replaced with a "
        "fresh sandbox. Files and state from the previous session are not "
        "available."
    ),
    "continuation": (
        "You are resuming an existing session. Prior conversation and tool "
        "history follow. Continue from where the assistant left off."
    ),
    "partial_history": (
        "Note: the tracing backend returned only partial history for this "
        "session. Some prior turns may be missing."
    ),
}


def _notice(key: str) -> str:
    overrides = get_config().notice_text
    return overrides.get(key, _DEFAULT_NOTICES[key])


def messages_from_session(attached: AttachedSession) -> list[Message]:
    """Return the rehydrated prior messages for inclusion in a fresh prompt."""
    return list(attached.state.messages)


def workspace_reset_notice(attached: AttachedSession) -> str | None:
    """Notice string if the workspace was re-booted because reconnect failed.

    Returns None when no notice is warranted. Caller decides whether to inject
    as a system message.
    """
    if attached.workspace_status in ("reconnect_failed", "boot_fresh") and (
        attached.workspace_reconnect_error is not None
    ):
        return _notice("workspace_reset")
    return None


def continuation_prelude(attached: AttachedSession) -> str | None:
    """Notice string if any prior history was rehydrated. None for fresh sessions."""
    if attached.state.messages:
        return _notice("continuation")
    return None


def partial_history_notice(attached: AttachedSession) -> str | None:
    """Notice string if the trace fetch returned a partial result."""
    if attached.trace_status == "partial":
        return _notice("partial_history")
    return None


# ----- framework-shape rendering -------------------------------------------


class _Render:
    """Namespace exposing ``oak.session.render.for_*`` helpers.

    These functions are pure shape adapters: oak ``Message`` -> the dict shape
    each SDK expects. They never call into the SDK.
    """

    @staticmethod
    def for_anthropic(messages: list[Message]) -> list[dict[str, Any]]:
        """Render to anthropic.types.MessageParam-compatible dicts.

        Anthropic accepts ``role`` in {user, assistant} only; ``system`` is
        threaded via the ``system`` top-level parameter - pass those separately.
        Tool messages are emitted as user messages carrying a ``tool_result``
        content block.
        """
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "",
                                "content": m.content,
                            }
                        ],
                    }
                )
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    @staticmethod
    def for_openai(messages: list[Message]) -> list[dict[str, Any]]:
        """Render to openai.types.chat.ChatCompletionMessageParam-compatible dicts."""
        out: list[dict[str, Any]] = []
        for m in messages:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == "tool" and m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            out.append(entry)
        return out

    @staticmethod
    def for_langgraph(messages: list[Message]) -> dict[str, Any]:
        """Render to a LangGraph-style state dict: ``{"messages": [...]}``."""
        rendered: list[dict[str, Any]] = []
        for m in messages:
            entry: dict[str, Any] = {"type": m.role, "content": m.content}
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            rendered.append(entry)
        return {"messages": rendered}


render = _Render()


__all__ = [
    "continuation_prelude",
    "messages_from_session",
    "partial_history_notice",
    "render",
    "workspace_reset_notice",
]
