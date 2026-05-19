"""Snapshot + behaviour tests for ``oak setup``.

Snapshots live under ``tests/fixtures/setup/<combo>/``. To regenerate them
after a deliberate change to the manifest or templates, run::

    OAK_UPDATE_SNAPSHOTS=1 uv run pytest packages/oak/tests/test_setup.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
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
        name="e2b_inmem_redisseparate_staso",
        selection=SetupSelection(
            workspace="e2b",
            state_store="in_memory",
            lease="redis_separate",
            tracing="staso",
            framework="openhands",
            substitutions={
                "E2B_API_KEY_NAME": "E2B_API_KEY",
                "E2B_TIMEOUT_MS": "900000",
                "REDIS_LEASE_URL_NAME": "REDIS_LEASE_URL",
                "STASO_API_KEY_NAME": "STASO_API_KEY",
            },
        ),
    ),
    Combo(
        name="local_custom_custom_none",
        selection=SetupSelection(
            workspace="local",
            state_store="custom",
            lease="custom",
            tracing="none",
            framework="openhands",
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


_EXPECTED_SECTIONS = {
    "version",
    "workspace",
    "state_store",
    "lease",
    "tracing",
    "framework",
}


@pytest.mark.parametrize("combo", COMBOS, ids=lambda c: c.name)
def test_snapshot(combo: Combo) -> None:
    manifest = load_manifest()
    bundle = render_bundle(manifest, combo.selection)

    parsed = yaml.safe_load(bundle["oak.yaml"])
    assert isinstance(parsed, dict)
    assert parsed["version"] == 1
    assert _EXPECTED_SECTIONS.issubset(parsed.keys())

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
    result = runner.invoke(app, ["setup", "--non-interactive", "--output", str(out)])
    assert result.exit_code == 0, result.output
    for name in ("oak.yaml", "pyproject_snippet.toml", ".env.example"):
        assert (out / name).exists(), f"missing {name}"
    assert not (out / "docker-compose.yml").exists()
    assert not (out / "oak_setup.py").exists()
    spec = yaml.safe_load((out / "oak.yaml").read_text(encoding="utf-8"))
    assert spec["version"] == 1
    assert spec["state_store"]["kind"] == "in_memory"


def test_interactive_default_inputs(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "interactive"
    answers = "\n".join(["1", "1", "2", "1", "1", str(out)]) + "\n"
    result = runner.invoke(app, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    assert (out / "oak.yaml").exists()
    assert not (out / "docker-compose.yml").exists()
    assert not (out / "oak_setup.py").exists()


def test_redis_state_store_shared_lease_reuses_url_env(tmp_path: Path) -> None:
    """When state_store=redis is picked, the shared-lease option must reuse the same url_env."""
    runner = CliRunner()
    out = tmp_path / "redis_combo"
    answers = "\n".join(["1", "2", "", "1", "y", "1", "1", str(out)]) + "\n"
    result = runner.invoke(app, ["setup"], input=answers)
    assert result.exit_code == 0, result.output
    spec = yaml.safe_load((out / "oak.yaml").read_text(encoding="utf-8"))
    assert spec["state_store"]["kind"] == "redis"
    assert spec["lease"]["kind"] == "redis"
    assert spec["state_store"]["url_env"] == spec["lease"]["url_env"]


def test_help_prints_setup() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "interactive wizard" in result.output.lower()


def test_wizard_menu_excludes_loader_unsupported_backends() -> None:
    """The wizard must only offer backends the YAML loader can construct.

    Backends gated as NotImplementedError in configure_from_yaml (postgres
    state_store; langfuse / phoenix / logfire / otlp tracing) must not appear
    in the manifest or the *_ORDER tuples consumed by the prompts.
    """
    from oak_cli import cmd_setup

    manifest = load_manifest()
    assert "postgres" not in manifest.state_store
    for kind in ("langfuse", "phoenix", "logfire", "otlp"):
        assert kind not in manifest.tracing, f"{kind} leaked into tracing manifest"

    assert "postgres" not in cmd_setup.STATE_ORDER
    for kind in ("langfuse", "phoenix", "logfire", "otlp"):
        assert kind not in cmd_setup.TRACE_ORDER, f"{kind} leaked into TRACE_ORDER"
