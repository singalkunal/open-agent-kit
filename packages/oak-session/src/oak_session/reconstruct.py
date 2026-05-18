"""Pure reconstruction: spans → SessionState.

No I/O, no globals, no logging. Takes a span list (already sorted by start_time)
and returns the framework-neutral SessionState. Replaceable via
``oak.session.configure(reconstructor=...)``.

Span semantic convention follows OTel ``gen_ai.*`` and oak's ``workspace.*``:

  - ``gen_ai.input.messages``  : list of input messages for an LLM call
  - ``gen_ai.output.messages`` : list of output messages from an LLM call
  - ``gen_ai.tool.call.id``    : tool call identifier
  - ``gen_ai.tool.name``       : tool name
  - ``gen_ai.tool.arguments``  : tool arguments (JSON)
  - ``gen_ai.tool.result``     : tool result (string)
  - ``oak.pending_action``     : carries a serialized PendingAction body
"""

from __future__ import annotations

import json
from typing import Any

from .models import Message, PendingAction, Role, SessionState, ToolCall

_VALID_ROLES: set[str] = {"system", "user", "assistant", "tool"}


def _coerce_messages(payload: Any) -> list[Message]:
    """Best-effort coerce span attribute payload to a list[Message].

    Accepts: a list of dicts, a JSON-encoded string, or a single dict.
    Skips entries with no recognized role.
    """
    if payload is None:
        return []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []
    out: list[Message] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if role not in _VALID_ROLES:
            continue
        content = entry.get("content")
        if content is None:
            continue
        if not isinstance(content, str):
            content = json.dumps(content, default=str)
        out.append(
            Message(
                role=role,
                content=content,
                tool_call_id=entry.get("tool_call_id"),
                cache_breakpoint=bool(entry.get("cache_breakpoint", False)),
            )
        )
    return out


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def reconstruct_session(spans: list[Any]) -> SessionState:
    """Reconstruct framework-neutral SessionState from an ordered span list.

    Tolerant by design: missing or malformed attributes do not raise, they
    are silently skipped. Callers observe rehydration completeness via
    ``trace_status`` on the AttachedSession.
    """
    messages: list[Message] = []
    tool_history: list[ToolCall] = []
    pending: PendingAction | None = None
    seen_message_keys: set[tuple[Role, str]] = set()

    for span in spans:
        attrs = getattr(span, "attributes", None) or {}

        for key in ("gen_ai.input.messages", "gen_ai.prompt"):
            if key in attrs:
                for msg in _coerce_messages(attrs[key]):
                    sig = (msg.role, msg.content)
                    if sig in seen_message_keys:
                        continue
                    seen_message_keys.add(sig)
                    messages.append(msg)

        for key in ("gen_ai.output.messages", "gen_ai.completion"):
            if key in attrs:
                for msg in _coerce_messages(attrs[key]):
                    sig = (msg.role, msg.content)
                    if sig in seen_message_keys:
                        continue
                    seen_message_keys.add(sig)
                    messages.append(msg)

        if "gen_ai.tool.name" in attrs or "gen_ai.tool.call.id" in attrs:
            tool_history.append(
                ToolCall(
                    tool_call_id=str(attrs.get("gen_ai.tool.call.id", "")),
                    name=str(attrs.get("gen_ai.tool.name", "")),
                    arguments=(
                        _decode(attrs.get("gen_ai.tool.arguments", {})) or {}
                        if isinstance(_decode(attrs.get("gen_ai.tool.arguments", {})), dict)
                        else {}
                    ),
                    result=(
                        str(attrs["gen_ai.tool.result"])
                        if "gen_ai.tool.result" in attrs
                        else None
                    ),
                    error=(
                        str(attrs["gen_ai.tool.error"])
                        if "gen_ai.tool.error" in attrs
                        else None
                    ),
                )
            )

        if "oak.pending_action" in attrs:
            body = _decode(attrs["oak.pending_action"])
            if isinstance(body, dict):
                try:
                    pending = PendingAction(
                        action_seq=int(body.get("action_seq", 0)),
                        action_kind=str(body.get("action_kind", "")),
                        body=dict(body.get("body", {})),
                    )
                except (TypeError, ValueError):
                    pending = None

    return SessionState(messages=messages, tool_history=tool_history, pending_action=pending)


__all__ = ["reconstruct_session"]
