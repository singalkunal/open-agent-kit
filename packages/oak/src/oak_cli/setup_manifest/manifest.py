"""Dataclasses for the setup manifest + bundle renderer.

The manifest is a plain JSON file; this module loads it, validates shape, and
renders the four output files (oak_setup.py, pyproject_snippet.toml,
.env.example, docker-compose.yml) for a given ``SetupSelection``.
"""

from __future__ import annotations

import json
import string
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EnvVar:
    name: str
    description: str
    example: str = ""


@dataclass(frozen=True)
class BackendOption:
    key: str
    label: str
    extras: tuple[str, ...]
    env: tuple[EnvVar, ...]
    imports: tuple[str, ...]
    config_snippet: str = ""
    attach_call: str = ""


@dataclass(frozen=True)
class Manifest:
    workspace: dict[str, BackendOption]
    state_store: dict[str, BackendOption]
    lease: dict[str, BackendOption]
    tracing: dict[str, BackendOption]
    framework: dict[str, BackendOption]


@dataclass
class SetupSelection:
    """The user's picks plus any prompt-time substitutions."""

    workspace: str
    state_store: str
    lease: str
    tracing: str
    framework: str
    # ``substitutions`` holds string.Template values harvested at prompt time
    # (e.g. {"E2B_API_KEY_NAME": "E2B_API_KEY", "E2B_TIMEOUT_MS": "900000"}).
    substitutions: dict[str, str] = field(default_factory=dict)


def _parse_option(key: str, raw: dict[str, Any]) -> BackendOption:
    env_raw = raw.get("env", []) or []
    env: list[EnvVar] = []
    for item in env_raw:
        env.append(
            EnvVar(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                example=str(item.get("example", "")),
            )
        )
    return BackendOption(
        key=key,
        label=str(raw.get("label", key)),
        extras=tuple(raw.get("extras", []) or []),
        env=tuple(env),
        imports=tuple(raw.get("imports", []) or []),
        config_snippet=str(raw.get("config_snippet", "")),
        attach_call=str(raw.get("attach_call", "")),
    )


def _parse_group(raw: dict[str, Any]) -> dict[str, BackendOption]:
    return {k: _parse_option(k, v) for k, v in raw.items()}


def load_manifest() -> Manifest:
    """Load the bundled ``manifest.json``."""
    data = resources.files("oak_cli.setup_manifest").joinpath("manifest.json").read_bytes()
    raw: dict[str, Any] = json.loads(data.decode("utf-8"))
    return Manifest(
        workspace=_parse_group(raw["workspace"]),
        state_store=_parse_group(raw["state_store"]),
        lease=_parse_group(raw["lease"]),
        tracing=_parse_group(raw["tracing"]),
        framework=_parse_group(raw["framework"]),
    )


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

_TEMPLATE_PKG = "oak_cli.setup_manifest.templates"


def _load_template(name: str) -> str:
    return (
        resources.files(_TEMPLATE_PKG)
        .joinpath(name)
        .read_bytes()
        .decode("utf-8")
    )


def _sub(text: str, mapping: dict[str, str]) -> str:
    return string.Template(text).safe_substitute(mapping)


def _selected_options(
    manifest: Manifest, sel: SetupSelection
) -> list[BackendOption]:
    return [
        manifest.workspace[sel.workspace],
        manifest.state_store[sel.state_store],
        manifest.lease[sel.lease],
        manifest.tracing[sel.tracing],
        manifest.framework[sel.framework],
    ]


def _gather_imports(opts: list[BackendOption]) -> list[str]:
    """Dedupe imports preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for opt in opts:
        for imp in opt.imports:
            if imp not in seen:
                seen.add(imp)
                out.append(imp)
    return out


def _gather_extras(opts: list[BackendOption]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for opt in opts:
        for extra in opt.extras:
            if extra not in seen:
                seen.add(extra)
                out.append(extra)
    return out


def _gather_env(opts: list[BackendOption], mapping: dict[str, str]) -> list[EnvVar]:
    seen: set[str] = set()
    out: list[EnvVar] = []
    for opt in opts:
        for var in opt.env:
            name = _sub(var.name, mapping)
            if name in seen or not name:
                continue
            seen.add(name)
            out.append(
                EnvVar(
                    name=name,
                    description=_sub(var.description, mapping),
                    example=_sub(var.example, mapping),
                )
            )
    return out


def _reindent(text: str, n: int) -> str:
    """Place a multi-line snippet at column ``n`` while preserving relative indent.

    Snippets in the manifest are authored with the assumption that line 1 lives
    at column 0 (the template provides the leading whitespace via its own
    indentation). Subsequent lines may carry their own *relative* indentation
    (e.g. nested ``def`` bodies). We dedent against the minimum non-empty
    leading-space of lines 2+, then re-indent every continuation line by ``n``.
    """
    lines = text.split("\n")
    if len(lines) <= 1:
        return text
    pad = " " * n
    # Find the minimum leading whitespace of the continuation lines so we can
    # treat that as the "base" of the snippet and rebase to column n.
    cont = lines[1:]
    indents = [
        len(ln) - len(ln.lstrip())
        for ln in cont
        if ln.strip()
    ]
    base = min(indents) if indents else 0
    out = [lines[0]]
    for ln in cont:
        if not ln.strip():
            out.append("")
        else:
            out.append(pad + ln[base:])
    return "\n".join(out)


def _render_oak_setup(
    manifest: Manifest, sel: SetupSelection
) -> str:
    opts = _selected_options(manifest, sel)
    workspace_opt, state_opt, lease_opt, trace_opt, fw_opt = opts

    imports = _gather_imports(opts)
    # Ensure stdlib essentials are present.
    for must in ("import asyncio", "import os"):
        if must not in imports:
            imports.insert(0, must)
    # Sort: stdlib first, then third-party, then oak. Simple heuristic.
    stdlib = sorted(i for i in imports if i.split()[1] in {"asyncio", "os"})
    others = [i for i in imports if i not in stdlib]
    imports_block = "\n".join(stdlib + sorted(others))

    sub = sel.substitutions
    workspace_line = _sub(workspace_opt.config_snippet, sub)
    state_line = _sub(state_opt.config_snippet, sub)
    lease_line = _sub(lease_opt.config_snippet, sub)
    trace_line = _sub(trace_opt.config_snippet, sub)

    template = _load_template("oak_setup.py.tmpl")
    return _sub(
        template,
        {
            "IMPORTS": imports_block,
            "WORKSPACE_LINE": _reindent(workspace_line, 4),
            "STATE_LINE": _reindent(state_line, 4),
            "LEASE_LINE": _reindent(lease_line, 4),
            "TRACE_LINE": _reindent(trace_line, 4),
            "ATTACH_CALL": fw_opt.attach_call or "oak.session.attach",
            "FRAMEWORK_LABEL": fw_opt.label,
            "WORKSPACE_LABEL": workspace_opt.label,
            "STATE_LABEL": state_opt.label,
            "LEASE_LABEL": lease_opt.label,
            "TRACE_LABEL": trace_opt.label,
        },
    )


def _render_pyproject_snippet(
    manifest: Manifest, sel: SetupSelection
) -> str:
    opts = _selected_options(manifest, sel)
    extras = _gather_extras(opts)
    # Always include the base packages even if no extras pulled them in.
    base = ["oak-workspace", "oak-session"]
    deps: list[str] = []
    for item in base + extras:
        if item not in deps:
            deps.append(item)
    deps_block = ",\n    ".join(f'"{d}"' for d in deps)
    template = _load_template("pyproject_snippet.toml.tmpl")
    return _sub(template, {"DEPS_BLOCK": deps_block})


def _render_env_example(
    manifest: Manifest, sel: SetupSelection
) -> str:
    opts = _selected_options(manifest, sel)
    env_vars = _gather_env(opts, sel.substitutions)
    if not env_vars:
        return (
            "# No external services were selected; this file is intentionally\n"
            "# empty. Delete it or keep it as a placeholder.\n"
        )
    lines: list[str] = []
    for var in env_vars:
        lines.append(f"# {var.description}")
        lines.append(f"{var.name}={var.example}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_docker_compose(
    manifest: Manifest, sel: SetupSelection
) -> str | None:
    services: list[str] = []
    if sel.state_store == "redis" or sel.lease in {"redis_shared", "redis_separate"}:
        services.append(
            "  redis:\n"
            "    image: redis:7-alpine\n"
            "    ports: [\"6379:6379\"]"
        )
    if sel.state_store == "postgres":
        services.append(
            "  postgres:\n"
            "    image: postgres:16-alpine\n"
            "    environment:\n"
            "      POSTGRES_USER: oak\n"
            "      POSTGRES_PASSWORD: oak\n"
            "      POSTGRES_DB: oak\n"
            "    ports: [\"5432:5432\"]"
        )
    if not services:
        return None
    template = _load_template("docker-compose.yml.tmpl")
    return _sub(template, {"SERVICES": "\n".join(services)})


def render_bundle(
    manifest: Manifest, sel: SetupSelection
) -> dict[str, str]:
    """Return a dict of {relative_filename: content}.

    The docker-compose file is omitted entirely when no service is needed.
    """
    bundle: dict[str, str] = {
        "oak_setup.py": _render_oak_setup(manifest, sel),
        "pyproject_snippet.toml": _render_pyproject_snippet(manifest, sel),
        ".env.example": _render_env_example(manifest, sel),
    }
    compose = _render_docker_compose(manifest, sel)
    if compose is not None:
        bundle["docker-compose.yml"] = compose
    return bundle


def write_bundle(bundle: dict[str, str], dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for rel, content in bundle.items():
        path = dest / rel
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


__all__ = [
    "BackendOption",
    "EnvVar",
    "Manifest",
    "SetupSelection",
    "load_manifest",
    "render_bundle",
    "write_bundle",
]
