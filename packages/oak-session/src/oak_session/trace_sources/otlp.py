"""Base TraceSource for any OTLP-shaped backend (Jaeger, Tempo, ClickHouse).

Subclasses or instantiations supply a query callable that returns a list of raw
span dicts; this base normalizes them into ``GenAISpan`` and handles ordering.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..errors import TraceSourceError
from ..models import GenAISpan

SpanQuery = Callable[[str], Awaitable[list[dict[str, Any]]]]


def _normalize(span: dict[str, Any]) -> GenAISpan:
    """Best-effort normalization. Honours common OTLP JSON shapes."""
    attrs = span.get("attributes") or {}
    if isinstance(attrs, list):
        # OTLP wire form: [{"key": k, "value": {"stringValue": ...}}, ...]
        flat: dict[str, Any] = {}
        for item in attrs:
            if not isinstance(item, dict):
                continue
            k = item.get("key")
            v = item.get("value")
            if isinstance(v, dict):
                # take the first populated typed value
                for type_key in ("stringValue", "intValue", "boolValue", "doubleValue"):
                    if type_key in v:
                        flat[str(k)] = v[type_key]
                        break
                else:
                    flat[str(k)] = v
            else:
                flat[str(k)] = v
        attrs = flat
    return GenAISpan(
        span_id=str(span.get("span_id") or span.get("spanId") or ""),
        name=str(span.get("name", "")),
        start_time_unix_nano=int(span.get("start_time_unix_nano") or span.get("startTimeUnixNano") or 0),
        end_time_unix_nano=(
            int(span["end_time_unix_nano"]) if "end_time_unix_nano" in span else
            int(span["endTimeUnixNano"]) if "endTimeUnixNano" in span else None
        ),
        attributes=dict(attrs),
        events=list(span.get("events", []) or []),
        status=span.get("status"),
    )


class OTLPSpansTraceSource:
    """Adapter wrapping any user-supplied span-query callable.

    Example::

        async def query(session_id: str) -> list[dict]:
            return await my_jaeger_client.search(session_id=session_id)

        oak.session.configure(trace=OTLPSpansTraceSource(query=query))
    """

    def __init__(self, query: SpanQuery) -> None:
        self._query = query

    async def fetch_session_spans(self, session_id: str) -> list[GenAISpan]:
        try:
            raw = await self._query(session_id)
        except TraceSourceError:
            raise
        except Exception as exc:
            raise TraceSourceError(f"trace query failed: {exc}") from exc
        spans = [_normalize(s) for s in raw]
        spans.sort(key=lambda s: s.start_time_unix_nano)
        return spans


__all__ = ["OTLPSpansTraceSource", "SpanQuery"]
