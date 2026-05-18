"""OpenHands wrapper smoke test.

Skipped if upstream OpenHands SDK is not installed. The wrapper composes over
``LocalConversation`` so we mock the upstream object: the wrapper must work
against any duck-typed conversation.
"""

from __future__ import annotations

import pytest

openhands = pytest.importorskip(
    "openhands.sdk", reason="openhands SDK not installed; skipping wrapper test"
)

from oak_session.openhands import OpenHandsSession  # noqa: E402


class _FakeStatus:
    name = "FINISHED"


class _FakeState:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.execution_status = _FakeStatus()


class _FakeConv:
    def __init__(self) -> None:
        self.state = _FakeState()
        self.sent: list[str] = []
        self.runs = 0
        self.rejected: list[str] = []

    def send_message(self, text: str) -> None:
        self.sent.append(text)

    def run(self) -> None:
        self.runs += 1

    def reject_pending_actions(self, reason: str) -> None:
        self.rejected.append(reason)


async def test_run_turn_invokes_send_and_run() -> None:
    conv = _FakeConv()
    session = OpenHandsSession(conv)
    result = await session.run_turn("hello")
    assert conv.sent == ["hello"]
    assert conv.runs == 1
    assert result.status == "finished"


async def test_approve_runs_without_send() -> None:
    conv = _FakeConv()
    session = OpenHandsSession(conv)
    await session.approve()
    assert conv.sent == []
    assert conv.runs == 1


async def test_reject_records_reason_then_runs() -> None:
    conv = _FakeConv()
    session = OpenHandsSession(conv)
    await session.reject("user changed mind")
    assert conv.rejected == ["user changed mind"]
    assert conv.runs == 1


def test_underlying_alias_points_to_conv() -> None:
    conv = _FakeConv()
    session = OpenHandsSession(conv)
    assert session.conv is conv
    assert session.underlying is conv
