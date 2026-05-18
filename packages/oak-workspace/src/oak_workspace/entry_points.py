"""Entry-point discovery for community-contributed backends.

Third parties publishing `oak-workspace-mycloud` register their class
under the `oak.workspaces` group; `get_backend("mycloud")` then loads it
without import gymnastics. Per principles.md §6.
"""

from __future__ import annotations

import importlib.metadata as _md
from typing import Any

_GROUP = "oak.workspaces"


def list_backends() -> dict[str, str]:
    """Return `{name: 'module:attr'}` for every registered backend."""
    out: dict[str, str] = {}
    for ep in _md.entry_points(group=_GROUP):
        out[ep.name] = ep.value
    return out


def get_backend(name: str) -> Any:
    """Resolve a registered backend by name.

    Raises `KeyError` if `name` is not registered. Loads the class
    lazily so importing this module never imports e.g. the docker SDK.
    """
    for ep in _md.entry_points(group=_GROUP):
        if ep.name == name:
            return ep.load()
    raise KeyError(f"no backend named {name!r} registered under {_GROUP!r}")


__all__ = ["get_backend", "list_backends"]
