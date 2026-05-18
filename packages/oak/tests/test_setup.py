"""Snapshot + behaviour tests for ``oak setup``.

Snapshots live under ``tests/fixtures/setup/<combo>/``. To regenerate them
after a deliberate change to the manifest or templates, run::

    OAK_UPDATE_SNAPSHOTS=1 uv run pytest packages/oak/tests/test_setup.py

Or pass ``--update-snapshots`` (we wire it as a CLI flag below).
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from oak_cli.main import app
from oak_cli.setup_manifest import (
    SetupSelection,
    load_manifest,
    render_bundle,
)
from typer.testing import CliRunner

FIXTURES = Path(__file__).parent / "fixtures" / "setup"


def _should_update() -> bool:
    return os.environ.get("OAK_UPDATE_SNAPSHOTS") == "1"


@dataclass(frozen=True)
class Combo:
    name: str
    selection: SetupSelection


COMBOS: list[Combo] = [
    Combo(
        name="local_inmem_none_console",
        selection=SetupSelection(
            workspace="local",
            state_store="in_memory",
            lease="none",
            tracing="none",
            framework="openhands",
        ),
    ),
    Combo(
        name="e2b_redis_redisshared_staso",
        selection=SetupSelection(
            workspace="e2b",
            state_store="redis",
            lease="redis_shared",
            tracing="staso",
            framework="openhands",
            substitutions={
                "E2B_API_KEY_NAME": "E2B_API_KEY",
                "E2B_TIMEOUT_MS": "900000",
                "REDIS_URL_NAME": "REDIS_URL",
                "STASO_API_KEY_NAME": "STASO_API_KEY",
            },
        ),
    ),
    Combo(
        name="e2b_postgres_redisseparate_langfuse",
        selection=SetupSelection(
            workspace="e2b",
            state_store="postgres",
            lease="redis_separate",
            tracing="langfuse",
            framework="openhands",
            substitutions={
                "E2B_API_KEY_NAME": "E2B_API_KEY",
                "E2B_TIMEOUT_MS": "900000",
                "PG_URL_NAME": "DATABASE_URL",
                "REDIS_LEASE_URL_NAME": "REDIS_LEASE_URL",
                "LANGFUSE_API_KEY_NAME": "LANGFUSE_PUBLIC_KEY",
            },
        ),
    ),
    Combo(
        name="local_inmem_inmem_console",
        selection=SetupSelection(
            workspace="local",
            state_store="in_memory",
            lease="in_memory",
            tracing="none",
            framework="openhands",
        ),
    ),
]


@pytest.mark.parametrize("combo", COMBOS, ids=lambda c: c.name)
def test_snapshot(combo: Combo) -> None:
    manifest = load_manifest()
    bundle = render_bundle(manifest, combo.selection)
    # Generated python must always parse.
    ast.parse(bundle["oak_setup.py"])

    fixture_dir = FIXTURES / combo.name
    if _should_update() or not fixture_dir.exists():
        fixture_dir.mkdir(parents=True, exist_ok=True)
        for name, content in bundle.items():
            (fixture_dir / name).write_text(content, encoding="utf-8")
        if not _should_update():
            pytest.skip(f"created fresh fixture for {combo.name}")
        return

    expected_files = {p.name for p in fixture_dir.iterdir() if p.is_file()}
    assert expected_files == set(bundle.keys()), (
        f"file set diverged: expected={expected_files} got={set(bundle.keys())}"
    )
    for name, content in bundle.items():
        expected = (fixture_dir / name).read_text(encoding="utf-8")
        assert content == expected, f"{name} content drift for {combo.name}"


def test_non_interactive_smoke(tmp_path: Path) -> None:
    """`oak setup --non-interactive -o <dir>` runs end-to-end with no prompts."""
    runner = CliRunner()
    out = tmp_path / "bundle"
    result = runner.invoke(
        app, ["setup", "--non-interactive", "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    for name in ("oak_setup.py", "pyproject_snippet.toml", ".env.example"):
        assert (out / name).exists(), f"missing {name}"
    # docker-compose must NOT be emitted for the all-in-memory default.
    assert not (out / "docker-compose.yml").exists()
    ast.parse((out / "oak_setup.py").read_text(encoding="utf-8"))


def test_interactive_default_inputs(tmp_path: Path) -> None:
    """Walk the prompts with explicit picks for the zero-credentials combo.

    workspace=1 (local), state_store=1 (in_memory), lease=2 (in_memory),
    tracing=1 (none), framework=1 (openhands).
    """
    runner = CliRunner()
    out = tmp_path / "interactive"
    answers = "\n".join(["1", "1", "2", "1", "1", str(out)]) + "\n"
    result = runner.invoke(app, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    assert (out / "oak_setup.py").exists()
    assert not (out / "docker-compose.yml").exists()


def test_redis_state_store_offers_shared_lease(tmp_path: Path) -> None:
    """When state_store=redis is picked, the lease menu must offer 'shared'."""
    runner = CliRunner()
    out = tmp_path / "redis_combo"
    # picks: workspace=1 (local), state_store=2 (redis), env=default,
    # lease=1 (redis_shared), reuse=y, tracing=1 (none), framework=1, dir.
    answers = "\n".join(
        ["1", "2", "", "1", "y", "1", "1", str(out)]
    ) + "\n"
    result = runner.invoke(app, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    text = (out / "oak_setup.py").read_text(encoding="utf-8")
    # Only one Redis client should be wired (shared mode).
    assert "RedisLease(redis_client)" in text
    assert "lease_redis" not in text


def test_help_prints_setup() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "interactive wizard" in result.output.lower()
