"""``oak protocols``: introspect installed oak Protocol surfaces.

Walks the v0.1 Protocol set across `oak_workspace` and `oak_session`,
prints methods + docstrings, and lists registered backends via
entry-point discovery.
"""

from __future__ import annotations

import importlib
import importlib.metadata as _md
import inspect
import json
import typing
from typing import Any

from rich.console import Console
from rich.table import Table

# Protocol name -> candidate import paths + entry-point group for backends.
_KNOWN_PROTOCOLS: dict[str, dict[str, Any]] = {
    "Workspace": {
        "modules": ["oak_workspace.protocol", "oak_workspace"],
        "entry_point_group": "oak.workspaces",
    },
    "SessionStateStore": {
        "modules": ["oak_session.protocols", "oak_session"],
        "entry_point_group": "oak.session.state_stores",
    },
    "TraceSource": {
        "modules": ["oak_session.protocols", "oak_session"],
        "entry_point_group": "oak.session.trace_sources",
    },
    "LeaseManager": {
        "modules": ["oak_session.protocols", "oak_session"],
        "entry_point_group": "oak.session.lease_managers",
    },
}


def _is_protocol(obj: Any) -> bool:
    if not inspect.isclass(obj):
        return False
    return bool(getattr(obj, "_is_protocol", False))


def _find_protocol(name: str) -> Any | None:
    spec = _KNOWN_PROTOCOLS.get(name)
    if spec is None:
        return None
    for path in spec["modules"]:
        try:
            mod = importlib.import_module(path)
        except ImportError:
            continue
        obj = getattr(mod, name, None)
        if obj is not None and _is_protocol(obj):
            return obj
    return None


def _discover_capability_flags(proto: Any) -> list[str]:
    if not hasattr(proto, "__annotations__"):
        return []
    try:
        hints = typing.get_type_hints(proto, include_extras=False)
    except Exception:
        hints = {}
    cap_attr = hints.get("capabilities")
    if cap_attr is None or not hasattr(cap_attr, "__annotations__"):
        return []
    return list(cap_attr.__annotations__)


def _methods(proto: Any) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for name, member in inspect.getmembers(proto):
        if name.startswith("_"):
            continue
        if not callable(member):
            continue
        try:
            sig = str(inspect.signature(member))
        except (TypeError, ValueError):
            sig = "(...)"
        doc = inspect.getdoc(member) or ""
        out.append((name, sig, doc))
    return out


def _protocol_payload(name: str, proto: Any) -> dict[str, Any]:
    return {
        "name": name,
        "module": getattr(proto, "__module__", "?"),
        "methods": [
            {"name": n, "signature": s, "doc": d} for (n, s, d) in _methods(proto)
        ],
        "capability_flags": _discover_capability_flags(proto),
    }


def _list_backends_for(name: str) -> dict[str, str]:
    spec = _KNOWN_PROTOCOLS.get(name)
    if spec is None:
        return {}
    group = spec.get("entry_point_group")
    if not group:
        return {}
    out: dict[str, str] = {}
    for ep in _md.entry_points(group=group):
        out[ep.name] = ep.value
    return out


def run_protocols(*, as_json: bool) -> int:
    console = Console()
    payload: dict[str, Any] = {"protocols": []}
    table = Table(title="oak protocols", show_header=True, header_style="bold")
    table.add_column("Protocol")
    table.add_column("Module")
    table.add_column("Methods")
    table.add_column("Backends")

    for name in _KNOWN_PROTOCOLS:
        proto = _find_protocol(name)
        backends = _list_backends_for(name)
        if proto is None:
            row: dict[str, Any] = {
                "name": name,
                "module": None,
                "methods": [],
                "capability_flags": [],
                "backends": backends,
            }
            payload["protocols"].append(row)
            if not as_json:
                table.add_row(name, "not installed", "-", ", ".join(backends) or "-")
            continue
        info = _protocol_payload(name, proto)
        info["backends"] = backends
        payload["protocols"].append(info)
        if not as_json:
            table.add_row(
                name,
                info["module"],
                ", ".join(m["name"] for m in info["methods"]) or "-",
                ", ".join(backends) or "-",
            )

    if as_json:
        console.print_json(json.dumps(payload))
    else:
        console.print(table)
    return 0


def run_protocols_show(*, name: str, as_json: bool) -> int:
    console = Console()
    proto = _find_protocol(name)
    if proto is None:
        console.print(f"[red]protocol not installed:[/] {name}")
        return 1
    info = _protocol_payload(name, proto)
    if as_json:
        console.print_json(json.dumps(info))
        return 0

    console.print(f"[bold]{info['name']}[/] [dim]({info['module']})[/]")
    if info["capability_flags"]:
        console.print("capabilities: " + ", ".join(info["capability_flags"]))
    for m in info["methods"]:
        console.print(f"\n[green]{m['name']}[/]{m['signature']}")
        if m["doc"]:
            for line in m["doc"].splitlines():
                console.print(f"  {line}")
    return 0


def run_protocols_backends(*, name: str, as_json: bool) -> int:
    console = Console()
    if name not in _KNOWN_PROTOCOLS:
        console.print(f"[red]unknown protocol:[/] {name}")
        return 1
    backends = _list_backends_for(name)
    group = _KNOWN_PROTOCOLS[name].get("entry_point_group", "")
    payload = {"protocol": name, "entry_point_group": group, "backends": backends}
    if as_json:
        console.print_json(json.dumps(payload))
        return 0
    console.print(f"[bold]{name}[/] backends [dim](group: {group})[/]")
    if not backends:
        console.print("  [dim]no backends registered[/]")
        return 0
    for ep_name, target in backends.items():
        console.print(f"  [green]{ep_name}[/]  ->  {target}")
    return 0
