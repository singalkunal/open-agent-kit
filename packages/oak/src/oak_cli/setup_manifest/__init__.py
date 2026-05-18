"""Manifest + template loaders for ``oak setup``.

The manifest is data-driven (manifest.json) so adding a new backend is a JSON
edit, not a code change.
"""

from __future__ import annotations

from .manifest import (
    BackendOption,
    Manifest,
    SetupSelection,
    load_manifest,
    render_bundle,
)

__all__ = [
    "BackendOption",
    "Manifest",
    "SetupSelection",
    "load_manifest",
    "render_bundle",
]
