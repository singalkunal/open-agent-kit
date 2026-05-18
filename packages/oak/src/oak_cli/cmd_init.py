"""``oak init <name>``: scaffold a starter project.

Uses ``string.Template`` substitution (stdlib only, no cookiecutter dep).

Template files use a ``.tmpl`` suffix so mypy/ruff don't try to parse
them as live Python/TOML. The suffix is stripped on render.
"""

from __future__ import annotations

import string
import sys
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TypedDict

from rich.console import Console


class _Entry(TypedDict):
    rel: str
    data: bytes


def _render_template(text: str, mapping: dict[str, str]) -> str:
    return string.Template(text).safe_substitute(mapping)


class _UnknownTemplate(Exception):
    pass


def _strip_tmpl(rel: str) -> str:
    return rel[: -len(".tmpl")] if rel.endswith(".tmpl") else rel


def _copy_template(template: str, dest: Path, mapping: dict[str, str]) -> int:
    pkg = f"oak_cli.templates.{template}"
    try:
        root = resources.files(pkg)
    except (ModuleNotFoundError, FileNotFoundError) as exc:
        raise _UnknownTemplate(template) from exc

    count = 0
    for entry in _walk(root):
        rel = _strip_tmpl(entry["rel"])
        # Skip the package marker so users don't get a stray __init__.py
        # at the project root.
        if rel == "__init__.py":
            continue
        out_path = dest / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        raw = entry["data"]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            out_path.write_bytes(raw)
        else:
            out_path.write_text(_render_template(text, mapping), encoding="utf-8")
        count += 1
    return count


def _walk(root: Traversable) -> list[_Entry]:
    """Walk a resources Traversable tree, returning relative paths + bytes."""
    out: list[_Entry] = []
    stack: list[tuple[Traversable, str]] = [(root, "")]
    while stack:
        node, prefix = stack.pop()
        for child in node.iterdir():
            name = child.name
            rel = f"{prefix}/{name}" if prefix else name
            if child.is_dir():
                stack.append((child, rel))
            else:
                out.append({"rel": rel, "data": child.read_bytes()})
    return out


def run_init(*, name: str, template: str) -> int:
    console = Console()
    dest = Path(name).resolve()
    if dest.exists():
        console.print(f"[red]error:[/] directory already exists: {dest}")
        return 1
    mapping = {
        "name": name,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }
    dest.mkdir(parents=True)
    try:
        count = _copy_template(template, dest, mapping)
    except _UnknownTemplate:
        console.print(f"[red]unknown template:[/] {template!r}")
        # Roll back the empty directory we just made.
        try:
            dest.rmdir()
        except OSError:
            pass
        return 2
    if count == 0:
        console.print(f"[red]template {template!r} is empty[/]")
        return 2

    console.print(f"[bold green]created[/] {dest} ({count} files)\n")
    console.print("Next steps:")
    console.print(f"  cd {name}")
    console.print("  uv sync")
    console.print("  uv run python agent.py")
    return 0
