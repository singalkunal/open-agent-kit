"""Pure unit tests for reconstruct_session()."""

from __future__ import annotations

import json

from oak_session import GenAISpan, reconstruct_session


def _span(name: str, ts: int, **attrs: object) -> GenAISpan:
    return GenAISpan(
        span_id=f"sp-{ts}",
        name=name,
        start_time_unix_nano=ts,
        attributes=dict(attrs),
    )


def test_reconstruct_empty_returns_empty_state() -> None:
    state = reconstruct_session([])
    assert state.messages == []
    assert state.tool_history == []
    assert state.pending_action is None


def test_reconstruct_messages_from_input_and_output() -> None:
    spans = [
        _span(
            "gen_ai.chat.openai",
            1,
            **{
                "gen_ai.input.messages": [
                    {"role": "system", "content": "you are a helper"},
                    {"role": "user", "content": "hi"},
                ],
                "gen_ai.output.messages": [
                    {"role": "assistant", "content": "hello"},
                ],
            },
        )
    ]
    state = reconstruct_session(spans)
    roles = [m.role for m in state.messages]
    assert roles == ["system", "user", "assistant"]
    assert state.messages[-1].content == "hello"


def test_reconstruct_dedupes_messages_across_spans() -> None:
    spans = [
        _span(
            "first",
            1,
            **{
                "gen_ai.input.messages": [{"role": "user", "content": "ping"}],
            },
        ),
        _span(
            "second",
            2,
            **{
                "gen_ai.input.messages": [{"role": "user", "content": "ping"}],
                "gen_ai.output.messages": [{"role": "assistant", "content": "pong"}],
            },
        ),
    ]
    state = reconstruct_session(spans)
    assert [m.content for m in state.messages] == ["ping", "pong"]


def test_reconstruct_collects_tool_calls() -> None:
    spans = [
        _span(
            "tool",
            10,
            **{
                "gen_ai.tool.call.id": "call-1",
                "gen_ai.tool.name": "search",
                "gen_ai.tool.arguments": json.dumps({"q": "x"}),
                "gen_ai.tool.result": "found",
            },
        )
    ]
    state = reconstruct_session(spans)
    assert len(state.tool_history) == 1
    tc = state.tool_history[0]
    assert tc.name == "search"
    assert tc.arguments == {"q": "x"}
    assert tc.result == "found"


def test_reconstruct_recovers_pending_action() -> None:
    spans = [
        _span(
            "approval",
            20,
            **{
                "oak.pending_action": json.dumps(
                    {"action_seq": 7, "action_kind": "shell.exec", "body": {"cmd": "rm -rf"}}
                ),
            },
        )
    ]
    state = reconstruct_session(spans)
    assert state.pending_action is not None
    assert state.pending_action.action_seq == 7
    assert state.pending_action.action_kind == "shell.exec"
    assert state.pending_action.body == {"cmd": "rm -rf"}


def test_reconstruct_tolerates_malformed_messages() -> None:
    spans = [
        _span(
            "bad",
            1,
            **{"gen_ai.input.messages": "not json at all"},
        )
    ]
    state = reconstruct_session(spans)
    assert state.messages == []
