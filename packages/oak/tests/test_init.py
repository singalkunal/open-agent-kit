from __future__ import annotations

import ast
from pathlib import Path

from oak_cli.main import app
from typer.testing import CliRunner


def test_init_starter_renders_files(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "myproj"
    result = runner.invoke(app, ["init", str(project), "--template", "starter"])
    assert result.exit_code == 0, result.output

    for name in ("pyproject.toml", "agent.py", "README.md"):
        assert (project / name).exists(), f"missing {name}"

    # agent.py must parse as valid Python after template substitution.
    src = (project / "agent.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert "${name}" not in src, "template variables were not substituted"
    assert "myproj" in src


def test_init_rejects_existing_dir(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "exists"
    project.mkdir()
    result = runner.invoke(app, ["init", str(project)])
    assert result.exit_code != 0


def test_init_unknown_template(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(tmp_path / "x"), "--template", "nope"])
    assert result.exit_code != 0
