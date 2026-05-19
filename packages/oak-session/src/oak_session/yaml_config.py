"""Declarative YAML config for oak.session.

``configure_from_yaml(path)`` reads an ``oak.yaml`` spec, resolves env vars by
name, constructs the chosen backend objects, and calls ``configure(...)``.

The spec is intentionally minimal and version-gated so future schema changes
are explicit (raise on unknown ``version``). Workspace selection lives in the
spec for documentation and downstream tooling, but is not applied here:
workspace instantiation happens per-request via ``oak.workspace.create(...)``.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .configure import configure

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from .protocols import LeaseManager, SessionStateStore, TraceSource


SUPPORTED_VERSION = 1


class OakConfigError(Exception):
    """Raised on malformed oak.yaml, missing env vars, or unknown ``kind`` values."""


def _require_section(data: dict[str, Any], key: str) -> dict[str, Any]:
    section = data.get(key)
    if not isinstance(section, dict):
        raise OakConfigError(f"oak.yaml: section '{key}' is required and must be a mapping")
    return section


def _require_kind(section: dict[str, Any], path: str) -> str:
    kind = section.get("kind")
    if not isinstance(kind, str) or not kind:
        raise OakConfigError(f"oak.yaml#{path}: 'kind' is required (string)")
    return kind


def _env(name: str, *, ref: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise OakConfigError(f"env var {name} referenced by oak.yaml#{ref} is not set")
    return value


def _resolve_factory(spec: str, *, ref: str) -> Any:
    if ":" not in spec:
        raise OakConfigError(f"oak.yaml#{ref}: factory '{spec}' must be 'package.module:callable'")
    module_name, _, attr = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise OakConfigError(
            f"oak.yaml#{ref}: cannot import module '{module_name}': {exc}"
        ) from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise OakConfigError(
            f"oak.yaml#{ref}: module '{module_name}' has no attribute '{attr}'"
        ) from exc


def _make_redis_client(url: str) -> Redis:
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        raise OakConfigError(
            "redis backend requires the [redis] extra: pip install oak-session[redis]"
        ) from exc
    return Redis.from_url(url)


def _build_state_store(
    section: dict[str, Any],
    *,
    redis_clients: dict[str, Redis],
) -> SessionStateStore | None:
    kind = _require_kind(section, "state_store")
    ref = "state_store"
    if kind == "in_memory":
        from .state_stores.in_memory import InMemoryStateStore

        return InMemoryStateStore()
    if kind == "redis":
        url_env = section.get("url_env")
        if not isinstance(url_env, str):
            raise OakConfigError(f"oak.yaml#{ref}: 'url_env' is required for kind=redis")
        url = _env(url_env, ref=f"{ref}.url_env")
        client = redis_clients.get(url_env)
        if client is None:
            client = _make_redis_client(url)
            redis_clients[url_env] = client
        from .state_stores.redis import RedisStateStore

        return RedisStateStore(client)
    if kind == "postgres":
        raise NotImplementedError(
            "postgres state_store via configure_from_yaml requires an async pool; "
            "construct PostgresStateStore manually and call oak.session.configure(...)"
        )
    if kind == "custom":
        factory_spec = section.get("factory")
        if not isinstance(factory_spec, str):
            raise OakConfigError(f"oak.yaml#{ref}: 'factory' is required for kind=custom")
        factory = _resolve_factory(factory_spec, ref=f"{ref}.factory")
        result: SessionStateStore = factory()
        return result
    raise OakConfigError(f"oak.yaml#{ref}: unknown kind '{kind}'")


def _build_lease(
    section: dict[str, Any],
    *,
    redis_clients: dict[str, Redis],
) -> LeaseManager | None:
    kind = _require_kind(section, "lease")
    ref = "lease"
    ttl_raw = section.get("ttl_seconds")
    ttl_kwargs: dict[str, Any] = {}
    if ttl_raw is not None:
        try:
            ttl_kwargs["ttl_seconds"] = float(ttl_raw)
        except (TypeError, ValueError) as exc:
            raise OakConfigError(f"oak.yaml#{ref}.ttl_seconds: must be numeric") from exc
    if kind == "none":
        return None
    if kind == "in_memory":
        from ._lease import InMemoryLease

        return InMemoryLease(**ttl_kwargs)
    if kind == "redis":
        url_env = section.get("url_env")
        if not isinstance(url_env, str):
            raise OakConfigError(f"oak.yaml#{ref}: 'url_env' is required for kind=redis")
        url = _env(url_env, ref=f"{ref}.url_env")
        client = redis_clients.get(url_env)
        if client is None:
            client = _make_redis_client(url)
            redis_clients[url_env] = client
        from ._lease import RedisLease

        return RedisLease(client, **ttl_kwargs)
    if kind == "custom":
        factory_spec = section.get("factory")
        if not isinstance(factory_spec, str):
            raise OakConfigError(f"oak.yaml#{ref}: 'factory' is required for kind=custom")
        factory = _resolve_factory(factory_spec, ref=f"{ref}.factory")
        result: LeaseManager = factory()
        return result
    raise OakConfigError(f"oak.yaml#{ref}: unknown kind '{kind}'")


def _build_trace(section: dict[str, Any]) -> TraceSource | None:
    kind = _require_kind(section, "tracing")
    ref = "tracing"
    if kind == "none":
        return None
    if kind == "staso":
        api_key_env = section.get("api_key_env")
        if not isinstance(api_key_env, str):
            raise OakConfigError(f"oak.yaml#{ref}: 'api_key_env' is required for kind=staso")
        api_key = _env(api_key_env, ref=f"{ref}.api_key_env")
        from .trace_sources.staso import StasoTraceSource

        return StasoTraceSource(api_key=api_key)
    if kind in {"langfuse", "phoenix", "logfire", "otlp"}:
        raise NotImplementedError(
            f"trace kind '{kind}' is not yet wired through configure_from_yaml; "
            "construct OTLPSpansTraceSource with your own query callable and call "
            "oak.session.configure(trace=...) directly"
        )
    raise OakConfigError(f"oak.yaml#{ref}: unknown kind '{kind}'")


def _validate_workspace(section: dict[str, Any]) -> None:
    """Workspace is informational here. Validate shape; resolve env eagerly."""
    kind = _require_kind(section, "workspace")
    if kind == "local":
        return
    if kind == "e2b":
        api_key_env = section.get("api_key_env")
        if not isinstance(api_key_env, str):
            raise OakConfigError("oak.yaml#workspace: 'api_key_env' is required for kind=e2b")
        _env(api_key_env, ref="workspace.api_key_env")
        return
    raise OakConfigError(f"oak.yaml#workspace: unknown kind '{kind}'")


def configure_from_yaml(path: str | Path) -> None:
    """Load an ``oak.yaml`` spec and apply it to ``oak.session.configure(...)``.

    Raises ``OakConfigError`` for malformed YAML, version mismatch, unknown
    ``kind`` values, or missing referenced env vars.
    """
    yaml_path = Path(path)
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OakConfigError(f"cannot read oak.yaml at {yaml_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise OakConfigError(f"oak.yaml parse error: {exc}") from exc

    if not isinstance(raw, dict):
        raise OakConfigError("oak.yaml: top-level document must be a mapping")

    version = raw.get("version")
    if version != SUPPORTED_VERSION:
        raise OakConfigError(
            f"oak.yaml: unsupported version {version!r}; expected {SUPPORTED_VERSION}"
        )

    workspace_section = _require_section(raw, "workspace")
    state_section = _require_section(raw, "state_store")
    lease_section = _require_section(raw, "lease")
    trace_section = _require_section(raw, "tracing")
    _require_section(raw, "framework")

    _validate_workspace(workspace_section)

    redis_clients: dict[str, Redis] = {}
    state_store = _build_state_store(state_section, redis_clients=redis_clients)
    lease = _build_lease(lease_section, redis_clients=redis_clients)
    trace = _build_trace(trace_section)

    configure(state_store=state_store, trace=trace, lease=lease)


__all__ = ["OakConfigError", "configure_from_yaml"]
