"""Tests for ``oak.session.configure_from_yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from oak_session import (
    InMemoryLease,
    InMemoryStateStore,
    OakConfigError,
    configure_from_yaml,
)
from oak_session.configure import get_config


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "oak.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_minimum_shape_yaml_configures_in_memory_defaults(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: local
state_store:
  kind: in_memory
lease:
  kind: none
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    configure_from_yaml(path)

    cfg = get_config()
    assert isinstance(cfg.state_store, InMemoryStateStore)
    assert cfg.lease is None
    assert cfg.trace is None


def test_full_shape_yaml_constructs_redis_and_staso(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("redis")
    pytest.importorskip("staso")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test")
    monkeypatch.setenv("STASO_API_KEY", "staso-test")

    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: e2b
  api_key_env: E2B_API_KEY
  idle_timeout_ms: 900000
state_store:
  kind: redis
  url_env: REDIS_URL
lease:
  kind: redis
  url_env: REDIS_URL
  ttl_seconds: 30
tracing:
  kind: staso
  api_key_env: STASO_API_KEY
framework:
  kind: openhands
""",
    )

    configure_from_yaml(path)

    cfg = get_config()
    assert cfg.state_store is not None
    assert cfg.lease is not None
    assert cfg.trace is not None


def test_version_mismatch_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
version: 2
workspace:
  kind: local
state_store:
  kind: in_memory
lease:
  kind: none
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    with pytest.raises(OakConfigError, match="unsupported version"):
        configure_from_yaml(path)


def test_missing_env_var_raises_with_helpful_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: local
state_store:
  kind: redis
  url_env: REDIS_URL
lease:
  kind: none
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    with pytest.raises(OakConfigError) as excinfo:
        configure_from_yaml(path)
    msg = str(excinfo.value)
    assert "REDIS_URL" in msg
    assert "state_store.url_env" in msg


def test_unknown_kind_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: local
state_store:
  kind: martian
lease:
  kind: none
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    with pytest.raises(OakConfigError, match="unknown kind 'martian'"):
        configure_from_yaml(path)


def test_shared_redis_client_reused_across_state_store_and_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    seen: list[str] = []

    from redis.asyncio import Redis

    real_from_url = Redis.from_url

    def spy_from_url(url: str, *args: Any, **kwargs: Any) -> Any:
        seen.append(url)
        return real_from_url(url, *args, **kwargs)

    monkeypatch.setattr(Redis, "from_url", spy_from_url)

    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: local
state_store:
  kind: redis
  url_env: REDIS_URL
lease:
  kind: redis
  url_env: REDIS_URL
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    configure_from_yaml(path)

    assert len(seen) == 1, f"expected single shared client, got {seen}"


def test_separate_redis_envs_create_two_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("REDIS_LEASE_URL", "redis://localhost:6379/1")

    seen: list[str] = []
    from redis.asyncio import Redis

    real_from_url = Redis.from_url

    def spy_from_url(url: str, *args: Any, **kwargs: Any) -> Any:
        seen.append(url)
        return real_from_url(url, *args, **kwargs)

    monkeypatch.setattr(Redis, "from_url", spy_from_url)

    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: local
state_store:
  kind: redis
  url_env: REDIS_URL
lease:
  kind: redis
  url_env: REDIS_LEASE_URL
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    configure_from_yaml(path)

    assert len(seen) == 2


def test_custom_factory_imports_and_instantiates(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: local
state_store:
  kind: custom
  factory: oak_session.state_stores.in_memory:InMemoryStateStore
lease:
  kind: custom
  factory: oak_session._lease:InMemoryLease
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    configure_from_yaml(path)

    cfg = get_config()
    assert isinstance(cfg.state_store, InMemoryStateStore)
    assert isinstance(cfg.lease, InMemoryLease)


def test_custom_factory_bad_path_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: local
state_store:
  kind: custom
  factory: no_such_module:nope
lease:
  kind: none
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    with pytest.raises(OakConfigError, match="cannot import module"):
        configure_from_yaml(path)


def test_missing_section_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: local
state_store:
  kind: in_memory
lease:
  kind: none
framework:
  kind: openhands
""",
    )

    with pytest.raises(OakConfigError, match="section 'tracing'"):
        configure_from_yaml(path)


def test_workspace_e2b_missing_env_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    path = _write(
        tmp_path,
        """
version: 1
workspace:
  kind: e2b
  api_key_env: E2B_API_KEY
state_store:
  kind: in_memory
lease:
  kind: none
tracing:
  kind: none
framework:
  kind: openhands
""",
    )

    with pytest.raises(OakConfigError, match="E2B_API_KEY"):
        configure_from_yaml(path)
