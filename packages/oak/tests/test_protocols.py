from __future__ import annotations

import json

from oak_cli.main import app
from typer.testing import CliRunner


def test_protocols_lists_v01_protocols() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["protocols"])
    assert result.exit_code == 0, result.output
    for name in ("Workspace", "SessionStateStore", "TraceSource", "LeaseManager"):
        assert name in result.output, f"protocol {name} not listed: {result.output}"


def test_protocols_json_mode_is_valid_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["protocols", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert "protocols" in parsed
    names = {p["name"] for p in parsed["protocols"]}
    assert {"Workspace", "SessionStateStore", "TraceSource", "LeaseManager"} <= names


def test_protocols_show_workspace() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["protocols", "show", "Workspace"])
    assert result.exit_code == 0, result.output
    assert "execute" in result.output


def test_protocols_backends_workspace() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["protocols", "backends", "Workspace"])
    assert result.exit_code == 0, result.output
    assert "Workspace" in result.output


def test_version_subcommand() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_no_dev_subcommand() -> None:
    """dev subcommand has been removed; oak-dev is cut."""
    runner = CliRunner()
    result = runner.invoke(app, ["dev"])
    assert result.exit_code != 0
