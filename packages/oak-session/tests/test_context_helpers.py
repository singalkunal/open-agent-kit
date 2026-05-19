"""Context helper + renderer tests."""

from __future__ import annotations

from oak_session import (
    AttachedSession,
    Message,
    SessionState,
    configure,
    continuation_prelude,
    messages_from_session,
    partial_history_notice,
    render,
    workspace_reset_notice,
)


def _attached(
    *,
    messages: list[Message] | None = None,
    workspace_status: str = "no_prior",
    workspace_reconnect_error: str | None = None,
    trace_status: str = "no_prior",
) -> AttachedSession:
    return AttachedSession(
        session_id="s",
        lease=None,
        workspace=None,
        state=SessionState(messages=messages or []),
        workspace_status=workspace_status,  # type: ignore[arg-type]
        trace_status=trace_status,  # type: ignore[arg-type]
        workspace_reconnect_error=workspace_reconnect_error,
    )


def test_messages_from_session_returns_copy() -> None:
    msgs = [Message(role="user", content="hi")]
    attached = _attached(messages=msgs)
    out = messages_from_session(attached)
    assert out == msgs
    out.append(Message(role="user", content="extra"))
    assert len(attached.state.messages) == 1


def test_workspace_reset_notice_only_when_reset_happened() -> None:
    fresh = _attached()
    assert workspace_reset_notice(fresh) is None
    rebooted = _attached(workspace_status="boot_fresh", workspace_reconnect_error="sandbox gc'd")
    notice = workspace_reset_notice(rebooted)
    assert notice is not None and "fresh sandbox" in notice


def test_continuation_prelude_emits_only_with_prior_history() -> None:
    assert continuation_prelude(_attached()) is None
    with_history = _attached(messages=[Message(role="user", content="prev")])
    assert continuation_prelude(with_history) is not None


def test_partial_history_notice_only_for_partial_status() -> None:
    assert partial_history_notice(_attached()) is None
    partial = _attached(trace_status="partial")
    assert partial_history_notice(partial) is not None


def test_notice_overrides_via_configure() -> None:
    configure(notice_text={"workspace_reset": "custom reset text"})
    rebooted = _attached(workspace_status="boot_fresh", workspace_reconnect_error="x")
    assert workspace_reset_notice(rebooted) == "custom reset text"


def test_render_for_anthropic_drops_system_and_wraps_tool() -> None:
    msgs = [
        Message(role="system", content="be helpful"),
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
        Message(role="tool", content="result text", tool_call_id="call-1"),
    ]
    out = render.for_anthropic(msgs)
    assert all(m["role"] != "system" for m in out)
    assert out[0] == {"role": "user", "content": "hi"}
    assert out[-1]["role"] == "user"
    assert out[-1]["content"][0]["type"] == "tool_result"
    assert out[-1]["content"][0]["tool_use_id"] == "call-1"


def test_render_for_openai_preserves_roles_and_tool_call_id() -> None:
    msgs = [
        Message(role="system", content="be helpful"),
        Message(role="tool", content="result", tool_call_id="call-1"),
    ]
    out = render.for_openai(msgs)
    assert out[0]["role"] == "system"
    assert out[1]["tool_call_id"] == "call-1"


def test_render_for_langgraph_wraps_in_messages_dict() -> None:
    msgs = [Message(role="user", content="hi")]
    out = render.for_langgraph(msgs)
    assert "messages" in out
    assert out["messages"][0]["type"] == "user"
