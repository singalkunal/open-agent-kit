"""High-level ``oak.session.openhands.attach()``.

One call: rehydrates via ``oak.session.attach``, assembles the message list,
and yields a ready ``OpenHandsSession``. Opinionated only on assembly
mechanics (ordering: system_prompt -> notices -> prior history); never on
domain logic (system prompt content, tool bindings, "done" semantics).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

from oak_workspace import Workspace

from ..attach import attach as core_attach
from ..context import (
    continuation_prelude,
    messages_from_session,
    partial_history_notice,
    workspace_reset_notice,
)
from ..models import AttachedSession, Message
from .builder import build_session
from .wrapper import OpenHandsSession

ContextComposer = Callable[[AttachedSession], list[Message]]


def _default_compose(
    attached: AttachedSession,
    *,
    system_prompt: str | None,
    include_notices: bool,
) -> list[Message]:
    messages: list[Message] = []
    if system_prompt:
        messages.append(Message(role="system", content=system_prompt))
    if include_notices:
        for notice_fn in (workspace_reset_notice, partial_history_notice, continuation_prelude):
            text = notice_fn(attached)
            if text:
                messages.append(Message(role="system", content=text))
    messages.extend(messages_from_session(attached))
    return messages


@asynccontextmanager
async def attach(
    session_id: str,
    *,
    agent: Any,
    system_prompt: str | None = None,
    workspace_factory: Callable[[], Awaitable[Workspace]] | None = None,
    on_workspace_lost: Literal["boot_fresh", "raise", "skip"] = "skip",
    exit_workspace: Literal["pause", "keep_alive", "terminate"] = "pause",
    wait_for_lease: bool | float = False,
    include_notices: bool = True,
    context_composer: ContextComposer | None = None,
    session_class: type[OpenHandsSession] = OpenHandsSession,
    confirmation_policy: Any | None = None,
    callbacks: list[Callable[[Any], None]] | None = None,
    **conversation_kwargs: Any,
) -> AsyncIterator[OpenHandsSession]:
    """Attach to a session and yield a ready ``OpenHandsSession``.

    Tier 1 - backend plug: configured via ``oak.session.configure``.
    Tier 2 - behaviour knobs: ``on_workspace_lost``, ``exit_workspace``,
             ``include_notices``, ``confirmation_policy``, ``callbacks``.
    Tier 3 - full custom: ``context_composer=`` and ``session_class=``.

    ``callbacks`` is forwarded verbatim to upstream ``LocalConversation``; each
    sync callable fires from the executor thread on every upstream ``Event``.
    """
    async with core_attach(
        session_id,
        workspace_factory=workspace_factory,
        on_workspace_lost=on_workspace_lost,
        wait_for_lease=wait_for_lease,
        exit_workspace=exit_workspace,
    ) as attached:
        if context_composer is not None:
            messages = context_composer(attached)
        else:
            messages = _default_compose(
                attached,
                system_prompt=system_prompt,
                include_notices=include_notices,
            )

        session = build_session(
            attached,
            agent=agent,
            initial_messages=messages,
            confirmation_policy=confirmation_policy,
            callbacks=callbacks,
            session_class=session_class,
            **conversation_kwargs,
        )
        yield session


__all__ = ["attach"]
