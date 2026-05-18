"""Reference TraceSource implementations. Vendor adapters are import-guarded.

Each vendor adapter does both directions of the relationship: ``install_emission()``
sets up the vendor's auto-instrument (e.g. ``patch_openai``); ``fetch_session_spans``
queries the backend. v0.1 ships the OTLP base + the Staso adapter; others are stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .otlp import OTLPSpansTraceSource

if TYPE_CHECKING:
    from .staso import StasoTraceSource


def __getattr__(name: str) -> Any:
    if name == "StasoTraceSource":
        from .staso import StasoTraceSource

        return StasoTraceSource
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["OTLPSpansTraceSource", "StasoTraceSource"]
