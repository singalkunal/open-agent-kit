"""``callbacks=`` plumbing through ``build_session`` and ``attach``.

Verifies oak's wrapper forwards a user-supplied ``callbacks`` list verbatim to
upstream ``LocalConversation`` and that each callable fires on emitted events.

Skipped if upstream OpenHands SDK is not installed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("openhands.sdk", reason="openhands SDK not installed; skipping callbacks test")

from oak_session.models import AttachedSession, SessionState
from oak_session.openhands import build_session


class _FakeState:
    def __init__(self) -> None:
        self.execution_status = type("S", (), {"name": "FINISHED"})()
        self.events: list[object] = []


class _FakeLocalConversation:
    """Stand-in for upstream ``LocalConversation`` that fires registered callbacks."""

    last_instance: _FakeLocalConversation | None = None

    def __init__(
        self,
        *,
        agent: Any,
        callbacks: list[Callable[[Any], None]] | None = None,
        **kwargs: Any,
    ) -> None:
        self.agent = agent
        self.callbacks = callbacks
        self.kwargs = kwargs
        self.state = _FakeState()
        _FakeLocalConversation.last_instance = self

    def emit(self, event: Any) -> None:
        for cb in self.callbacks or []:
            cb(event)


def _make_attached() -> AttachedSession:
    return AttachedSession(
        session_id="sess-1",
        lease=None,
        workspace=None,
        state=SessionState(),
        workspace_status="no_prior",
        trace_status="no_prior",
    )


def test_build_session_forwards_callbacks_to_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    import openhands.sdk as oh_sdk

    monkeypatch.setattr(oh_sdk, "LocalConversation", _FakeLocalConversation)

    received: list[Any] = []

    def cb(event: Any) -> None:
        received.append(event)

    session = build_session(
        _make_attached(),
        agent=object(),
        initial_messages=[],
        callbacks=[cb],
    )

    fake = _FakeLocalConversation.last_instance
    assert fake is not None
    assert fake.callbacks is not None and len(fake.callbacks) == 1
    assert fake.callbacks[0] is cb

    sentinel = object()
    fake.emit(sentinel)
    assert received == [sentinel]

    # Wrapper still wires through normally.
    assert session.conv is fake


def test_build_session_omits_callbacks_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import openhands.sdk as oh_sdk

    monkeypatch.setattr(oh_sdk, "LocalConversation", _FakeLocalConversation)

    build_session(
        _make_attached(),
        agent=object(),
        initial_messages=[],
    )

    fake = _FakeLocalConversation.last_instance
    assert fake is not None
    # ``callbacks=None`` (default) must not be passed through - upstream defaults apply.
    assert "callbacks" not in fake.kwargs
    assert fake.callbacks is None


def test_build_session_passes_empty_callback_list(monkeypatch: pytest.MonkeyPatch) -> None:
    import openhands.sdk as oh_sdk

    monkeypatch.setattr(oh_sdk, "LocalConversation", _FakeLocalConversation)

    build_session(
        _make_attached(),
        agent=object(),
        initial_messages=[],
        callbacks=[],
    )

    fake = _FakeLocalConversation.last_instance
    assert fake is not None
    assert fake.callbacks == []
