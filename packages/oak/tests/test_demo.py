from __future__ import annotations

from oak_cli.main import app
from typer.testing import CliRunner


def test_demo_exits_zero() -> None:
    """Smoke test: `oak demo` runs end-to-end with zero credentials."""
    runner = CliRunner()
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0, result.output
    assert "oak demo complete" in result.output


def test_demo_with_custom_session_id() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--session-id", "test_sess_xyz"])
    assert result.exit_code == 0, result.output
    assert "test_sess_xyz" in result.output


def test_demo_exercises_real_modules() -> None:
    """Demo must import the real sibling packages, not a stub.

    Asserts the public re-exports the demo depends on still exist.
    """
    from oak_session.state_stores.in_memory import InMemoryStateStore
    from oak_workspace import LocalProcessWorkspace

    assert InMemoryStateStore is not None
    assert LocalProcessWorkspace is not None
