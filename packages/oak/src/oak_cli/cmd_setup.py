"""``oak setup``: interactive wizard that generates a backend wiring bundle.

Asks five questions (workspace, state store, lease, tracing, framework),
substitutes the user's picks into ``oak_setup.py``, ``pyproject_snippet.toml``,
``.env.example`` and (when relevant) ``docker-compose.yml``. The CLI uses
typer's built-in ``prompt`` / ``confirm`` to avoid adding a new dep.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import typer
from rich.console import Console

from .setup_manifest import (
    BackendOption,
    Manifest,
    SetupSelection,
    load_manifest,
)
from .setup_manifest.manifest import write_bundle

WORKSPACE_ORDER = ("local", "e2b")
STATE_ORDER = ("in_memory", "redis", "postgres", "custom")
TRACE_ORDER = ("none", "staso", "langfuse", "phoenix", "logfire", "otlp")
FRAMEWORK_ORDER = ("openhands",)


def _print_menu(
    console: Console,
    title: str,
    options: Sequence[tuple[str, BackendOption]],
) -> None:
    console.print(f"\n[bold]{title}[/]")
    for idx, (_key, opt) in enumerate(options, start=1):
        console.print(f"  {idx}. {opt.label}")


def _pick(
    console: Console,
    title: str,
    group: dict[str, BackendOption],
    order: Sequence[str],
    default: int = 1,
) -> str:
    pairs = [(k, group[k]) for k in order if k in group]
    _print_menu(console, title, pairs)
    while True:
        raw = typer.prompt(f"choose 1-{len(pairs)}", default=str(default))
        try:
            idx = int(raw)
        except ValueError:
            console.print("[red]enter a number[/]")
            continue
        if 1 <= idx <= len(pairs):
            return pairs[idx - 1][0]
        console.print(f"[red]out of range; pick 1-{len(pairs)}[/]")


def _prompt_workspace(
    console: Console, manifest: Manifest, subs: dict[str, str]
) -> str:
    key = _pick(console, "Workspace provider", manifest.workspace, WORKSPACE_ORDER)
    if key == "e2b":
        subs["E2B_API_KEY_NAME"] = typer.prompt(
            "  env var name for E2B API key", default="E2B_API_KEY"
        )
        timeout_s = typer.prompt(
            "  E2B idle timeout (seconds)", default="900"
        )
        try:
            subs["E2B_TIMEOUT_MS"] = str(int(timeout_s) * 1000)
        except ValueError:
            subs["E2B_TIMEOUT_MS"] = "900000"
    return key


def _prompt_state_store(
    console: Console, manifest: Manifest, subs: dict[str, str]
) -> str:
    key = _pick(console, "State store", manifest.state_store, STATE_ORDER)
    if key == "redis":
        subs["REDIS_URL_NAME"] = typer.prompt(
            "  env var name for Redis connection", default="REDIS_URL"
        )
    elif key == "postgres":
        subs["PG_URL_NAME"] = typer.prompt(
            "  env var name for Postgres connection", default="DATABASE_URL"
        )
    return key


def _prompt_lease(
    console: Console,
    manifest: Manifest,
    state_store: str,
    subs: dict[str, str],
) -> str:
    pairs: list[tuple[str, BackendOption]] = []
    if state_store == "redis":
        pairs.append(("redis_shared", manifest.lease["redis_shared"]))
        pairs.append(("redis_separate", manifest.lease["redis_separate"]))
    else:
        pairs.append(("redis_separate", manifest.lease["redis_separate"]))
    pairs.append(("in_memory", manifest.lease["in_memory"]))
    pairs.append(("none", manifest.lease["none"]))
    pairs.append(("custom", manifest.lease["custom"]))

    _print_menu(console, "Lease coordinator", pairs)
    while True:
        raw = typer.prompt(f"choose 1-{len(pairs)}", default="1")
        try:
            idx = int(raw)
        except ValueError:
            console.print("[red]enter a number[/]")
            continue
        if 1 <= idx <= len(pairs):
            key = pairs[idx - 1][0]
            break
        console.print(f"[red]out of range; pick 1-{len(pairs)}[/]")

    if key == "redis_shared" and state_store == "redis":
        reuse = typer.confirm(
            "  reuse the same Redis client as the state store?", default=True
        )
        if not reuse:
            key = "redis_separate"
    if key == "redis_separate":
        subs["REDIS_LEASE_URL_NAME"] = typer.prompt(
            "  env var name for lease Redis", default="REDIS_LEASE_URL"
        )
    if key == "in_memory":
        console.print(
            "  [yellow]WARNING:[/] InMemoryLease is single-process only. "
            "Multiple workers will not coordinate."
        )
    if key == "none":
        console.print(
            "  [yellow]WARNING:[/] no lease configured. Concurrent attach() "
            "across processes can race on the same session id."
        )
    return key


def _prompt_tracing(
    console: Console, manifest: Manifest, subs: dict[str, str]
) -> str:
    key = _pick(console, "Tracing backend", manifest.tracing, TRACE_ORDER)
    env_name_map = {
        "staso": ("STASO_API_KEY_NAME", "STASO_API_KEY"),
        "langfuse": ("LANGFUSE_API_KEY_NAME", "LANGFUSE_PUBLIC_KEY"),
        "phoenix": ("PHOENIX_API_KEY_NAME", "PHOENIX_API_KEY"),
        "logfire": ("LOGFIRE_API_KEY_NAME", "LOGFIRE_TOKEN"),
    }
    if key in env_name_map:
        sub_key, default_name = env_name_map[key]
        subs[sub_key] = typer.prompt(
            f"  env var name for {key} API key", default=default_name
        )
    return key


def _prompt_framework(
    console: Console, manifest: Manifest
) -> str:
    return _pick(console, "Agent framework", manifest.framework, FRAMEWORK_ORDER)


def _print_summary(
    console: Console, written: list[Path], dest: Path
) -> None:
    console.print("")
    for path in written:
        console.print(f"[green][OK][/] wrote {path}")
    console.print("\n[bold]Next steps:[/]")
    console.print(f"  1. Copy {dest}/oak_setup.py into your project")
    console.print(
        "  2. Add the pyproject snippet to your pyproject.toml and run `uv sync`"
    )
    console.print("  3. Fill in .env from .env.example")
    if (dest / "docker-compose.yml").exists():
        console.print(
            "  4. `docker compose up -d` for local Redis/Postgres "
            "(skip if you have them elsewhere)"
        )


def run_setup(
    *, output_dir: str | None = None, non_interactive: bool = False
) -> int:
    """Run the interactive wizard.

    When ``non_interactive`` is set we never prompt and just return the
    all-defaults selection. Used by the smoke test entrypoint.
    """
    console = Console()
    manifest = load_manifest()

    if non_interactive:
        sel = SetupSelection(
            workspace="local",
            state_store="in_memory",
            lease="in_memory",
            tracing="none",
            framework="openhands",
        )
    else:
        console.print(
            "[bold]oak setup[/] - interactive wiring for "
            "oak.workspace + oak.session\n"
        )
        subs: dict[str, str] = {}
        workspace = _prompt_workspace(console, manifest, subs)
        state_store = _prompt_state_store(console, manifest, subs)
        lease = _prompt_lease(console, manifest, state_store, subs)
        tracing = _prompt_tracing(console, manifest, subs)
        framework = _prompt_framework(console, manifest)
        sel = SetupSelection(
            workspace=workspace,
            state_store=state_store,
            lease=lease,
            tracing=tracing,
            framework=framework,
            substitutions=subs,
        )

    if output_dir is None:
        output_dir = typer.prompt("\noutput directory", default="./oak-setup")

    dest = Path(output_dir).resolve()
    if dest.exists() and any(dest.iterdir()):
        if not typer.confirm(
            f"directory {dest} exists and is not empty; overwrite files?",
            default=False,
        ):
            console.print("[red]aborted[/]")
            return 1

    from .setup_manifest.manifest import render_bundle

    bundle = render_bundle(manifest, sel)
    written = write_bundle(bundle, dest)
    _print_summary(console, written, dest)
    return 0


__all__ = ["run_setup"]
