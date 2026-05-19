"""Dataclasses for the setup manifest + bundle renderer.

The manifest is a plain JSON file; this module loads it, validates shape, and
renders the output bundle (``oak.yaml``, ``pyproject_snippet.toml``,
``.env.example``) for a given ``SetupSelection``.

The wizard emits a declarative spec; the user's app loads it via
``oak.session.configure_from_yaml("oak.yaml")``. The wizard does not emit
Python wiring or docker-compose: provisioning infra is the user's job.
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


_TEMPLATE_PKG = "oak_cli.setup_manifest.templates"


def _load_template(name: str) -> str:
    return resources.files(_TEMPLATE_PKG).joinpath(name).read_bytes().decode("utf-8")


def _sub(text: str, mapping: dict[str, str]) -> str:
    return string.Template(text).safe_substitute(mapping)


def _selected_options(manifest: Manifest, sel: SetupSelection) -> list[BackendOption]:
    return [
        manifest.workspace[sel.workspace],
        manifest.state_store[sel.state_store],
        manifest.lease[sel.lease],
        manifest.tracing[sel.tracing],
        manifest.framework[sel.framework],
    ]


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


def _indent_block(lines: list[str], n: int = 2) -> str:
    pad = " " * n
    return "\n".join(pad + ln if ln else "" for ln in lines)


def _workspace_block(sel: SetupSelection) -> str:
    sub = sel.substitutions
    if sel.workspace == "local":
        return _indent_block(["kind: local"])
    if sel.workspace == "e2b":
        api_key = sub.get("E2B_API_KEY_NAME", "E2B_API_KEY")
        timeout = sub.get("E2B_TIMEOUT_MS", "900000")
        return _indent_block(
            [
                "kind: e2b",
                f"api_key_env: {api_key}",
                f"idle_timeout_ms: {timeout}",
            ]
        )
    raise ValueError(f"unknown workspace selection: {sel.workspace}")


def _state_store_block(sel: SetupSelection) -> str:
    sub = sel.substitutions
    if sel.state_store == "in_memory":
        return _indent_block(["kind: in_memory"])
    if sel.state_store == "redis":
        url_env = sub.get("REDIS_URL_NAME", "REDIS_URL")
        return _indent_block(["kind: redis", f"url_env: {url_env}"])
    if sel.state_store == "custom":
        return _indent_block(
            [
                "kind: custom",
                "# Point at your callable that returns a SessionStateStore.",
                "factory: my_package.module:make_state_store",
            ]
        )
    raise ValueError(f"unknown state_store selection: {sel.state_store}")


def _lease_block(sel: SetupSelection) -> str:
    sub = sel.substitutions
    if sel.lease == "redis_shared":
        url_env = sub.get("REDIS_URL_NAME", "REDIS_URL")
        return _indent_block(
            [
                "kind: redis",
                f"url_env: {url_env}",
                "ttl_seconds: 30",
            ]
        )
    if sel.lease == "redis_separate":
        url_env = sub.get("REDIS_LEASE_URL_NAME", "REDIS_LEASE_URL")
        return _indent_block(
            [
                "kind: redis",
                f"url_env: {url_env}",
                "ttl_seconds: 30",
            ]
        )
    if sel.lease == "in_memory":
        return _indent_block(
            [
                "# Single-process only. Multiple workers will not coordinate.",
                "kind: in_memory",
                "ttl_seconds: 30",
            ]
        )
    if sel.lease == "none":
        return _indent_block(
            [
                "# No coordination. Concurrent attach() across processes can race.",
                "kind: none",
            ]
        )
    if sel.lease == "custom":
        return _indent_block(
            [
                "kind: custom",
                "factory: my_package.module:make_lease",
            ]
        )
    raise ValueError(f"unknown lease selection: {sel.lease}")


def _tracing_block(sel: SetupSelection) -> str:
    sub = sel.substitutions
    if sel.tracing == "none":
        return _indent_block(["kind: none"])
    if sel.tracing == "staso":
        api_key = sub.get("STASO_API_KEY_NAME", "STASO_API_KEY")
        return _indent_block(
            [
                "kind: staso",
                f"api_key_env: {api_key}",
            ]
        )
    raise ValueError(f"unknown tracing selection: {sel.tracing}")


def _framework_block(sel: SetupSelection) -> str:
    return _indent_block([f"kind: {sel.framework}"])


def _render_oak_yaml(manifest: Manifest, sel: SetupSelection) -> str:
    template = _load_template("oak.yaml.tmpl")
    return _sub(
        template,
        {
            "WORKSPACE_BLOCK": _workspace_block(sel),
            "STATE_BLOCK": _state_store_block(sel),
            "LEASE_BLOCK": _lease_block(sel),
            "TRACE_BLOCK": _tracing_block(sel),
            "FRAMEWORK_BLOCK": _framework_block(sel),
        },
    )


def _render_pyproject_snippet(manifest: Manifest, sel: SetupSelection) -> str:
    opts = _selected_options(manifest, sel)
    extras = _gather_extras(opts)
    base = ["oak-workspace", "oak-session"]
    deps: list[str] = []
    for item in base + extras:
        if item not in deps:
            deps.append(item)
    deps_block = ",\n    ".join(f'"{d}"' for d in deps)
    template = _load_template("pyproject_snippet.toml.tmpl")
    return _sub(template, {"DEPS_BLOCK": deps_block})


def _render_env_example(manifest: Manifest, sel: SetupSelection) -> str:
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


def render_bundle(manifest: Manifest, sel: SetupSelection) -> dict[str, str]:
    """Return a dict of {relative_filename: content}.

    Bundle is fixed at three files: the declarative spec, a pyproject snippet,
    and a .env.example. Infra provisioning (Redis, Postgres) is the user's job.
    """
    return {
        "oak.yaml": _render_oak_yaml(manifest, sel),
        "pyproject_snippet.toml": _render_pyproject_snippet(manifest, sel),
        ".env.example": _render_env_example(manifest, sel),
    }


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
