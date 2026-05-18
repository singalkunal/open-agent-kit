"""``oak-workspace``: framework-neutral sandbox protocol.

Public re-exports. Backend modules are not imported eagerly so the
package loads without their optional dependencies (``docker``, ``e2b``).

Top-level helpers:

* :func:`create` -- boot a workspace via provider string dispatch
* :func:`reconnect` -- re-attach to a paused / preserved workspace
* :func:`list_providers` -- enumerate built-in + entry-point providers
"""

from __future__ import annotations

from .create import create, list_providers, reconnect
from .entry_points import get_backend, list_backends
from .errors import (
    CapabilityUnsupported,
    WorkspaceError,
    WorkspaceTerminated,
    WorkspaceTimeout,
    WorkspaceUnreachable,
)
from .local_process import LocalProcessWorkspace
from .protocol import Workspace
from .types import (
    CommandResult,
    ExecuteResult,
    FileOperationResult,
    WorkspaceCapabilities,
)

__all__ = [
    "CapabilityUnsupported",
    "CommandResult",
    "ExecuteResult",
    "FileOperationResult",
    "LocalProcessWorkspace",
    "Workspace",
    "WorkspaceCapabilities",
    "WorkspaceError",
    "WorkspaceTerminated",
    "WorkspaceTimeout",
    "WorkspaceUnreachable",
    "create",
    "get_backend",
    "list_backends",
    "list_providers",
    "reconnect",
]
