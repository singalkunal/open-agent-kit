"""Module-level ``create()`` / ``reconnect()`` / ``list_providers()``.

The provider-string -> backend-class dispatch table. Built-in
providers (``local``, ``e2b``) are registered statically; community
providers are discovered via the ``oak.workspaces`` entry-point group.

On boot, ``create()`` emits a ``workspace.boot`` OTel span with the
attribute schema declared in ``docs/design/workspace.md`` (and mirrored
in ``protocol.py``'s docstring). ``reconnect()`` emits ``workspace.reconnect``
with the same schema.
"""

from __future__ import annotations

import datetime as _dt
import importlib.metadata as _md
import json
from typing import Any, Protocol, cast

from .errors import WorkspaceUnreachable
from .telemetry import (
    ATTR_WS_CREATED_AT,
    ATTR_WS_HANDLE,
    ATTR_WS_IMAGE,
    ATTR_WS_PROVIDER,
    ATTR_WS_REGION,
    SPAN_BOOT,
    SPAN_RECONNECT,
    set_attribute,
    span,
)

_ENTRY_POINT_GROUP = "oak.workspaces"


class _WorkspaceLike(Protocol):
    """Structural typing for the Workspace surface that ``create()`` /
    ``reconnect()`` need to interact with. Mirrors ``Workspace`` but lives
    here to avoid a circular import.
    """

    @property
    def handle(self) -> dict[str, Any]: ...

    async def __aenter__(self) -> _WorkspaceLike: ...

    async def __aexit__(self, *exc: object) -> None: ...


def _builtin_providers() -> dict[str, str]:
    # Resolved lazily so importing this module never imports e.g. the
    # e2b SDK. Values are ``"module:attr"`` strings - same shape as
    # entry-point ``value`` so the resolver path is uniform.
    return {
        "local": "oak_workspace.local_process:LocalProcessWorkspace",
        "local_process": "oak_workspace.local_process:LocalProcessWorkspace",
        "local_docker": "oak_workspace.local_docker:LocalDockerWorkspace",
        "e2b": "oak_workspace.e2b:E2BWorkspace",
    }


def list_providers() -> list[str]:
    """List all registered workspace providers (built-in + entry-point).

    Returns provider names sorted alphabetically. The same name may
    appear in both built-in and entry-point dicts; we deduplicate.
    """
    names: set[str] = set(_builtin_providers())
    for ep in _md.entry_points(group=_ENTRY_POINT_GROUP):
        names.add(ep.name)
    return sorted(names)


def _resolve_provider(provider: str) -> type[Any]:
    """Resolve ``provider`` name to a backend class.

    Entry-point registrations win over built-ins so users can override.
    """
    for ep in _md.entry_points(group=_ENTRY_POINT_GROUP):
        if ep.name == provider:
            return cast(type[Any], ep.load())
    builtins = _builtin_providers()
    if provider in builtins:
        module_path, _, attr = builtins[provider].partition(":")
        mod = __import__(module_path, fromlist=[attr])
        return cast(type[Any], getattr(mod, attr))
    raise KeyError(
        f"unknown workspace provider {provider!r}; known providers: {list_providers()}"
    )


def _encode_handle(handle: dict[str, Any]) -> str:
    """JSON-encode the handle for OTel attribute emission.

    Per workspace.md the ``workspace.handle`` attribute is a JSON string.
    We sort keys for deterministic-looking traces. ``default=str`` is a
    permissive fallback for non-JSON-native types (e.g. UUID, datetime).
    """
    try:
        return json.dumps(handle, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return json.dumps({"_unserializable": True})


def _emit_boot_span(
    provider: str,
    workspace: _WorkspaceLike,
    *,
    span_name: str = SPAN_BOOT,
) -> None:
    """Best-effort OTel emission. No-op when opentelemetry-api is absent."""
    handle = workspace.handle
    attrs: dict[str, Any] = {
        ATTR_WS_PROVIDER: provider,
        ATTR_WS_HANDLE: _encode_handle(handle),
        ATTR_WS_CREATED_AT: _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    region = handle.get("region") if isinstance(handle, dict) else None
    if isinstance(region, str):
        attrs[ATTR_WS_REGION] = region
    image = (
        handle.get("image") or handle.get("template")
        if isinstance(handle, dict)
        else None
    )
    if isinstance(image, str):
        attrs[ATTR_WS_IMAGE] = image
    with span(span_name, attrs) as s:
        # set_attribute is a no-op when OTel is not installed; we
        # already passed attrs into span() but call it again as a
        # belt-and-suspenders for backends that mutate handle after
        # boot but before the span closes.
        for k, v in attrs.items():
            set_attribute(s, k, v)


async def create(provider: str, **config: Any) -> _WorkspaceLike:
    """Boot a fresh workspace via ``provider`` string dispatch.

    ``config`` passes through to the backend's constructor. The
    provider's native idle / TTL config (e.g. E2B ``timeout_ms``) is the
    primary lifetime mechanism; oak does NOT run a background timer.

    Emits a ``workspace.boot`` OTel span with the attribute schema
    declared in ``docs/design/workspace.md``.
    """
    cls = _resolve_provider(provider)
    instance: Any = cls(**config)
    # Materialise any lazy underlying client (E2B sandbox, Docker
    # container) so the handle is populated when we emit the boot span.
    ensure = getattr(instance, "_ensure_sandbox", None) or getattr(
        instance, "_ensure_container", None
    )
    if ensure is not None:
        await ensure()
    _emit_boot_span(provider, cast(_WorkspaceLike, instance))
    return cast(_WorkspaceLike, instance)


async def reconnect(provider: str, handle: dict[str, Any]) -> _WorkspaceLike:
    """Reattach to a paused / preserved workspace via ``provider`` + ``handle``.

    Raises ``WorkspaceUnreachable`` if the provider reports the sandbox
    no longer exists. Emits a ``workspace.reconnect`` OTel span on
    success.
    """
    cls = _resolve_provider(provider)
    reconnect_fn = getattr(cls, "reconnect", None)
    if reconnect_fn is None:
        raise WorkspaceUnreachable(
            handle=handle,
            reason=f"backend {cls.__name__!r} does not implement reconnect()",
        )
    instance: Any = await reconnect_fn(handle)
    _emit_boot_span(provider, cast(_WorkspaceLike, instance), span_name=SPAN_RECONNECT)
    return cast(_WorkspaceLike, instance)


__all__ = ["create", "list_providers", "reconnect"]
