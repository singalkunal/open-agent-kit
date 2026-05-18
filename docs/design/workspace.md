# `oak.workspace` design

`oak.workspace` is the sandbox-abstraction layer. It runs commands, moves files, and exposes lifecycle methods (pause, resume, terminate, reconnect) when a backend supports them. The reconnect capability is what makes cross-process resume work end-to-end with `oak.session`.

## Purpose

Production agents run model-chosen tools somewhere. Local subprocesses work for demos. Docker, E2B, Daytona, Modal, or any other sandbox provider works for real workloads. The agent loop should not change when the backend changes - and a process that picks up a paused session should be able to reconnect to the existing sandbox without losing filesystem state.

`LocalWorkspace` and `E2BWorkspace` are the v0.1 targets. Daytona / Modal / Vercel / Cloudflare adapters come from the community via entry-point discovery.

## Public API

```python
# oak/workspace/protocol.py
from __future__ import annotations
from datetime import timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable
from pydantic import BaseModel, Field

class CommandResult(BaseModel):
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timeout_occurred: bool

class FileOperationResult(BaseModel):
    success: bool
    source_path: str
    destination_path: str
    file_size: int | None = None
    error: str | None = None

class WorkspaceCapabilities(BaseModel):
    supports_reconnect: bool = False
    supports_snapshot: bool = False
    supports_gpu: bool = False
    supports_browser: bool = False
    supports_port_forward: bool = False
    native_idle_timeout: bool = False    # provider auto-pauses/terminates on idle config
    max_idle: timedelta | None = None
    max_lifetime: timedelta | None = None


@runtime_checkable
class Workspace(Protocol):
    """Sandbox protocol. All methods are async."""

    working_dir: str
    capabilities: WorkspaceCapabilities

    @property
    def handle(self) -> dict:
        """Serializable reconnect handle. Goes into oak.session's state_store
        AND into the workspace.boot OTel span attributes. MUST NOT contain
        secrets (auth is reapplied via provider client on reconnect)."""
        ...

    @property
    def underlying(self) -> object | None:
        """Provider's raw client / sandbox object, for escape-hatch access.
        Returns None for backends without an underlying client (e.g., LocalWorkspace)."""
        ...

    async def execute(
        self, command: str, *, cwd: str | Path | None = None, timeout: float = 30.0,
    ) -> CommandResult: ...

    async def upload(
        self, source: str | Path, destination: str | Path,
    ) -> FileOperationResult: ...

    async def download(
        self, source: str | Path, destination: str | Path,
    ) -> FileOperationResult: ...

    async def pause(self) -> None:
        """Pause the sandbox so it stops consuming compute but state is preserved.
        Idempotent. CapabilityUnsupported if supports_reconnect is False
        (a workspace that can't be reconnected to can't meaningfully pause)."""
        ...

    async def terminate(self) -> None:
        """Destroy the sandbox. State NOT preserved. After this, all other
        methods raise WorkspaceTerminated. Idempotent. Best-effort (swallows
        provider errors and logs them)."""
        ...

    async def snapshot(self) -> str:
        """Return snapshot ID. Raises CapabilityUnsupported if supports_snapshot is False."""
        ...

    async def restore(self, snapshot_id: str) -> None: ...

    async def __aenter__(self) -> "Workspace": ...
    async def __aexit__(self, *exc: object) -> None: ...
```

```python
# Module-level functions for creation and reconnect
async def create(
    provider: str,                       # "local" | "e2b" | community-registered
    **config: object,
) -> Workspace:
    """Boot a fresh workspace. config passes through to provider-specific kwargs:
        oak.workspace.create("e2b", api_key=..., region="us-east-1", timeout_ms=900000)
        oak.workspace.create("local", working_dir="/tmp/oak")
    The provider's native idle/TTL config (timeout_ms for E2B, etc.) is the
    primary lifetime mechanism - oak does NOT run a background timer.
    On boot, the implementation emits an OTel `workspace.boot` span with the
    handle in attributes (see Span attribute schema below)."""
    ...

async def reconnect(
    provider: str,
    handle: dict,
) -> Workspace:
    """Reattach to a paused/preserved sandbox by its handle.
    Raises WorkspaceUnreachable if reconnect fails (sandbox GC'd, etc.).
    On reconnect, emits an OTel `workspace.reconnect` span."""
    ...

def list_providers() -> list[str]:
    """List registered workspace providers (built-in + entry-point discovered)."""
    ...
```

```python
# oak_workspace/errors.py
class WorkspaceError(Exception):
    """Base class for all workspace errors."""

class CapabilityUnsupported(WorkspaceError):
    """Raised when a Protocol method is called against a backend whose capability flag is False."""
    def __init__(self, capability: str, backend: str | None = None):
        self.capability = capability
        self.backend = backend
        super().__init__(
            f"Backend{f' {backend!r}' if backend else ''} does not support {capability}"
        )

class WorkspaceTerminated(WorkspaceError):
    """Raised when any method is called on a workspace after terminate()."""

class WorkspaceUnreachable(WorkspaceError):
    """Raised when reconnect() fails (sandbox no longer exists at the provider).
    Carries `handle` and `reason` for diagnostics."""
    def __init__(self, handle: dict, reason: str):
        self.handle = handle
        self.reason = reason
        super().__init__(f"workspace unreachable: {reason} (handle={handle})")

class WorkspaceTimeout(WorkspaceError):
    """Raised when execute() exceeds its timeout."""
```

## Reconnect contract

Reconnect is THE feature that makes cross-process session resume work end-to-end. Without it, every process restart = lost filesystem state = re-bootstrap.

```python
# [USER] Day 1, Process A
ws = await oak.workspace.create("e2b", api_key=..., timeout_ms=900_000)
# [OAK] writes workspace.boot OTel span with ws.handle in attrs
# [USER] uses workspace; process A pauses on session exit
await ws.pause()
# [OAK] persisted ws.handle in state_store via oak.session

# [USER] Hours later, Process B (different process, possibly different host)
handle = state_store.get(session_id, "workspace")
ws = await oak.workspace.reconnect("e2b", handle)
# [PROVIDER] E2B SDK calls Sandbox.reconnect(sandbox_id); unpauses; filesystem intact
# [USER] continues
```

The handle is whatever the provider's SDK needs for `reconnect()`. For E2B it's `{"sandbox_id": "sb-x7f9k2"}`. For Modal it might be function lookup data. The Protocol does NOT prescribe the shape - each backend defines its own handle.

**The handle must be secret-free.** Auth is reapplied via the provider's already-configured client at reconnect time (E2B API key in env, etc.). Handle goes into both the state_store AND the OTel `workspace.boot` span attributes - neither is a safe place for credentials.

## Span attribute schema (long-term wire format promise)

When a workspace boots, the adapter emits an OTel span named `workspace.boot` with these attributes:

| Attribute | Type | Example |
|---|---|---|
| `workspace.provider` | str | `"e2b"` / `"local"` / `"daytona"` |
| `workspace.handle` | str (JSON-encoded dict) | `{"sandbox_id": "sb-x7f9k2"}` |
| `workspace.region` | str | `"us-east-1"` |
| `workspace.image` | str | `"python-3.12"` |
| `workspace.created_at` | str (ISO datetime) | `"2026-05-19T14:23:01Z"` |

A `workspace.reconnect` span is emitted similarly when reconnect succeeds.

This schema is a long-term promise per Principle #5 (stable wire formats). Tools downstream of oak's tracing can rely on it for forensic recovery (e.g., "the last known sandbox handle for session X" is reachable from the trace store as a fallback to the state store).

## Capability binding

| Method | Required capability | Raises if False |
|---|---|---|
| `pause()` / reconnect via state-store handle | `supports_reconnect` | `CapabilityUnsupported` |
| `snapshot()` / `restore()` | `supports_snapshot` | `CapabilityUnsupported` |
| `execute(timeout=...)` exceeding `max_lifetime` | n/a | `ValueError` at call time |

Backends without reconnect (e.g., a killed local Docker container is gone) set `supports_reconnect=False`. Callers branch on the flag.

## Provider-native lifetime config - no oak timer

oak does NOT run a background timer to pause/terminate idle workspaces. The provider's native idle config is the source of truth for "auto-pause/terminate on inactivity":

| Provider | Native idle config |
|---|---|
| E2B | `timeout_ms` on sandbox creation; auto-terminate after that idle period; pause can be explicit API call |
| Modal | Function timeouts on the underlying function |
| Daytona | Workspace TTL policies set at workspace creation |
| Vercel Sandbox | Lifetime config on creation |
| Cloudflare Sandbox | Hibernation policy on creation |
| Local | None - process runs until terminated explicitly |

`oak.workspace.create(provider, **config)` passes config through to the provider SDK. User configures the provider's native timeout; provider handles it. No oak watcher needed.

The `oak.session.attach()` exit handler additionally calls `workspace.pause()` on clean exit (default `exit_workspace="pause"`). Belt-and-suspenders: app-level pause on clean exit + provider native timeout on orphaned sessions.

## Backends

| Adapter | Capability flags | Shipped |
|---|---|---|
| `LocalWorkspace` | `supports_reconnect=False` (process death = gone), host filesystem | v0.1 |
| `E2BWorkspace` | `supports_reconnect=True`, `native_idle_timeout=True`, `max_idle=24h` | v0.1 via `[e2b]` extra |
| `DaytonaWorkspace` | `supports_reconnect=True`, `supports_snapshot=True` | community |
| `ModalWorkspace` | `supports_reconnect=True`, `supports_gpu=True` | community |
| `VercelSandboxWorkspace` | `supports_reconnect=True` | community |
| `CloudflareSandboxWorkspace` | `supports_reconnect=True` | community |
| `BrowserbaseWorkspace` | `supports_browser=True` | community |

Community backends register via entry points:

```toml
[project.entry-points."oak.workspaces"]
daytona = "oak_workspace_daytona:DaytonaWorkspace"
```

## Dependencies

```toml
[project]
name = "oak-workspace"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "anyio>=4.3",
    "opentelemetry-api>=1.27",
]

[project.optional-dependencies]
e2b = ["e2b>=1.0,<2.0"]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "mypy>=1.10", "ruff>=0.5"]
```

No cloud SDK is required for the local path.

## Quickstart

```python
import asyncio
import oak.workspace

async def main():
    # [USER] boot a workspace
    ws = await oak.workspace.create("local", working_dir="/tmp/oak-demo")
    
    # [USER] use it
    result = await ws.execute("python -c 'print(2 + 2)'")
    print(result.stdout)

    # [USER] cleanup
    await ws.terminate()

asyncio.run(main())
```

Swap to E2B by changing the provider string:

```python
ws = await oak.workspace.create(
    "e2b",
    api_key=os.environ["E2B_API_KEY"],
    region="us-east-1",
    timeout_ms=900_000,    # [PROVIDER] E2B's native 15-minute idle timeout
)
```

## Tests

- Contract tests for the `Workspace` Protocol (executable, file ops, capabilities, lifecycle, reconnect for backends that support it)
- LocalWorkspace tests are unit tests (no external deps)
- E2BWorkspace tests skip unless `E2B_API_KEY` is set

## Open risks

- Reconnect semantics differ subtly per provider (E2B's pause vs Modal's function-ID lookup vs Daytona's workspace state) - capability flags + per-backend tests bound the surface
- Span attribute schema changes are breaking; SemVer + deprecation window required
- Provider native idle config may evolve; bound by the capability flag `native_idle_timeout`
