"""Verifies the framework shim template renders to syntactically valid Python."""

from __future__ import annotations

import ast
import string
from pathlib import Path


def test_framework_shim_template_renders_valid_python() -> None:
    tmpl_path = (
        Path(__file__).parent.parent
        / "src"
        / "oak_workspace"
        / "templates"
        / "framework_shim.py.tmpl"
    )
    raw = tmpl_path.read_text()
    rendered = string.Template(raw).substitute(
        framework_name="Demo",
        framework_base_import="class _StubBase:\n    pass",
        framework_base_class="_StubBase",
        oak_backend_import="from oak_workspace import LocalProcessWorkspace",
        oak_backend_class="LocalProcessWorkspace",
    )
    # Must parse as valid Python.
    ast.parse(rendered)
