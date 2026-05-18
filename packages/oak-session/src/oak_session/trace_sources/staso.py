"""Staso TraceSource adapter.

Stub under the ``[staso]`` extra. Wraps the Staso SDK once its query endpoints
ship (see open risk in docs/design/session.md).
"""

from __future__ import annotations

from typing import Any

from ..errors import TraceSourceError
from ..models import GenAISpan


class StasoTraceSource:
    """Adapter for Staso. Requires the Staso SDK installed via the ``[staso]`` extra.

    ``install_emission()`` calls the Staso SDK's auto-instrument once it exists.
    Until then, both methods raise informatively.
    """

    def __init__(self, *, api_key: str | None = None, client: Any | None = None) -> None:
        try:
            import staso  # noqa: F401  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised by missing extra
            raise ImportError(
                "StasoTraceSource requires the [staso] extra: pip install oak-session[staso]"
            ) from exc
        self._api_key = api_key
        self._client = client

    def install_emission(self) -> None:
        """Install the Staso SDK auto-instrument. No-op until SDK exposes patch_*.

        Once Staso ships patch entrypoints, this MUST call them and short-circuit
        on already-installed.
        """
        raise NotImplementedError(
            "StasoTraceSource.install_emission requires Staso SDK patch_* hooks"
        )

    async def fetch_session_spans(self, session_id: str) -> list[GenAISpan]:
        raise TraceSourceError(
            "StasoTraceSource.fetch_session_spans is stubbed; "
            "implement once the Staso SDK query endpoints are available"
        )


__all__ = ["StasoTraceSource"]
