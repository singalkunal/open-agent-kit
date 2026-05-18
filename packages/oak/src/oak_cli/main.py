"""Typer entrypoint for the oak CLI.

Subcommands are kept thin; logic lives in cmd_*.py modules.
"""

from __future__ import annotations

import typer

from . import __version__
from .cmd_demo import run_demo
from .cmd_init import run_init
from .cmd_protocols import (
    run_protocols,
    run_protocols_backends,
    run_protocols_show,
)
from .cmd_setup import run_setup

app = typer.Typer(
    name="oak",
    help="oak: production runtime toolkit for agents.",
    no_args_is_help=True,
    add_completion=False,
)

protocols_app = typer.Typer(
    name="protocols",
    help="Introspect installed oak Protocol surfaces.",
    no_args_is_help=False,
    invoke_without_command=True,
)
app.add_typer(protocols_app)


@app.command("version")
def version() -> None:
    """Print the oak CLI version."""
    typer.echo(__version__)


@app.command("demo")
def demo(
    session_id: str = typer.Option(
        "demo_sess",
        "--session-id",
        "-s",
        help="Session id to attach to.",
    ),
) -> None:
    """Run a zero-credentials end-to-end wiring demo (<10s)."""
    code = run_demo(session_id=session_id)
    raise typer.Exit(code=code)


@app.command("setup")
def setup(
    output_dir: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory for the generated bundle (skips the prompt).",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Skip prompts and emit the zero-credentials default bundle.",
    ),
) -> None:
    """Interactive wizard that generates an oak wiring bundle for your backend."""
    code = run_setup(output_dir=output_dir, non_interactive=non_interactive)
    raise typer.Exit(code=code)


@app.command("init")
def init(
    name: str = typer.Argument(..., help="Project name / output directory."),
    template: str = typer.Option(
        "starter",
        "--template",
        "-t",
        help="Template to render (starter is the only template in v0.1).",
    ),
) -> None:
    """Generate a starter project under ./<name>/."""
    code = run_init(name=name, template=template)
    raise typer.Exit(code=code)


@protocols_app.callback()
def protocols_callback(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Print the live Protocol surface across installed oak_* packages."""
    if ctx.invoked_subcommand is None:
        code = run_protocols(as_json=as_json)
        raise typer.Exit(code=code)


@protocols_app.command("show")
def protocols_show(
    name: str = typer.Argument(..., help="Protocol name, e.g. Workspace."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Print one Protocol's methods and docstrings."""
    code = run_protocols_show(name=name, as_json=as_json)
    raise typer.Exit(code=code)


@protocols_app.command("backends")
def protocols_backends(
    name: str = typer.Argument(..., help="Protocol name, e.g. Workspace."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List installed backends for one Protocol (entry-point discovery)."""
    code = run_protocols_backends(name=name, as_json=as_json)
    raise typer.Exit(code=code)


if __name__ == "__main__":  # pragma: no cover
    app()
