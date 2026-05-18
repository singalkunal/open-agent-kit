"""OTel span helpers for `oak-workspace`.

Attribute names are the forever wire format declared in
`docs/plan/dev_experience.md` §3. Renames go through a 2-minor-version
deprecation window per principles.md §5.

OTel is an optional dependency. When `opentelemetry-api` is not installed
the helpers turn into no-ops so the workspace package remains zero-dep.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

try:  # pragma: no cover - import guard
    from opentelemetry import trace as _otel_trace

    _TRACER: Any = _otel_trace.get_tracer("oak.workspace")
except Exception:  # pragma: no cover - opentelemetry not installed
    _TRACER = None


# Forever wire-format attribute keys. Do NOT rename without a deprecation
# window. New attributes can be added freely.
ATTR_SESSION_ID = "oak.session_id"
ATTR_TENANT_ID = "oak.tenant_id"
ATTR_MODULE = "oak.module"
ATTR_VERSION = "oak.version"

ATTR_BACKEND = "oak.workspace.backend"
ATTR_COMMAND = "oak.workspace.command"
ATTR_EXIT_CODE = "oak.workspace.exit_code"
ATTR_TIMEOUT_SECONDS = "oak.workspace.timeout_seconds"
ATTR_DURATION_MS = "oak.workspace.duration_ms"
ATTR_DST_PATH = "oak.workspace.dst_path"
ATTR_SIZE_BYTES = "oak.workspace.size_bytes"
ATTR_SNAPSHOT_ID = "oak.workspace.snapshot_id"

# Long-term wire format for boot / reconnect spans. Per workspace.md
# "Span attribute schema" section, these attribute names are a stable
# promise - downstream tools (trace stores, forensic recovery tools)
# rely on them. Rename requires SemVer + deprecation window per
# principles.md §5.
ATTR_WS_PROVIDER = "workspace.provider"
ATTR_WS_HANDLE = "workspace.handle"
ATTR_WS_REGION = "workspace.region"
ATTR_WS_IMAGE = "workspace.image"
ATTR_WS_CREATED_AT = "workspace.created_at"

SPAN_EXECUTE_COMMAND = "oak.workspace.execute_command"
SPAN_FILE_UPLOAD = "oak.workspace.file_upload"
SPAN_FILE_DOWNLOAD = "oak.workspace.file_download"
SPAN_SNAPSHOT = "oak.workspace.snapshot"
SPAN_RESTORE = "oak.workspace.restore"
SPAN_PAUSE = "oak.workspace.pause"
SPAN_RESUME = "oak.workspace.resume"
SPAN_TERMINATE = "oak.workspace.terminate"
SPAN_BOOT = "workspace.boot"
SPAN_RECONNECT = "workspace.reconnect"


@contextlib.contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Start a span; no-op when OTel is not installed."""
    if _TRACER is None:
        yield None
        return
    with _TRACER.start_as_current_span(name) as s:
        if attributes:
            for k, v in attributes.items():
                if v is None:
                    continue
                s.set_attribute(k, v)
        yield s


def set_attribute(span_obj: Any, key: str, value: Any) -> None:
    """Set an attribute on a span if OTel is active; ignore otherwise."""
    if span_obj is None or value is None:
        return
    try:
        span_obj.set_attribute(key, value)
    except Exception:  # pragma: no cover - never break runtime on telemetry
        pass


__all__ = [
    "ATTR_BACKEND",
    "ATTR_COMMAND",
    "ATTR_DST_PATH",
    "ATTR_DURATION_MS",
    "ATTR_EXIT_CODE",
    "ATTR_MODULE",
    "ATTR_SESSION_ID",
    "ATTR_SIZE_BYTES",
    "ATTR_SNAPSHOT_ID",
    "ATTR_TENANT_ID",
    "ATTR_TIMEOUT_SECONDS",
    "ATTR_VERSION",
    "ATTR_WS_CREATED_AT",
    "ATTR_WS_HANDLE",
    "ATTR_WS_IMAGE",
    "ATTR_WS_PROVIDER",
    "ATTR_WS_REGION",
    "SPAN_BOOT",
    "SPAN_EXECUTE_COMMAND",
    "SPAN_FILE_DOWNLOAD",
    "SPAN_FILE_UPLOAD",
    "SPAN_PAUSE",
    "SPAN_RECONNECT",
    "SPAN_RESTORE",
    "SPAN_RESUME",
    "SPAN_SNAPSHOT",
    "SPAN_TERMINATE",
    "set_attribute",
    "span",
]
