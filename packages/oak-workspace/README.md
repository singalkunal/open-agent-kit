# oak-workspace

Sandbox abstraction for production agents. Wraps any sandbox provider behind one Protocol with capability flags + reconnect across process boundaries.

```python
# [USER]
import asyncio
import oak.workspace

async def main() -> None:
    ws = await oak.workspace.create("local", working_dir="/tmp/demo")    # [OAK]
    result = await ws.execute("echo hello")                              # [OAK]
    print(result.stdout)         # "hello\n"
    print(result.exit_code)      # 0
    await ws.terminate()                                                 # [OAK]

asyncio.run(main())
```

Same code runs against E2B by changing the provider string:

```python
# [USER]
ws = await oak.workspace.create(
    "e2b",
    api_key=os.environ["E2B_API_KEY"],
    region="us-east-1",
    timeout_ms=900_000,            # [PROVIDER] E2B's native 15-min idle timeout
)
```

## What this is

`oak.workspace` is one `Workspace` Protocol that wraps every sandbox provider (local subprocess + E2B today; Daytona, Modal, Vercel, Cloudflare, Runloop, Browserbase via community packages) behind a small async surface plus capability flags. Pick a backend per environment. Your agent code never changes.

The load-bearing addition for production: `Workspace.reconnect(handle)`. When a process restarts and a different process picks up a paused session, oak.session reads the workspace handle from the state store and calls `oak.workspace.reconnect()` — the E2B sandbox returns with filesystem state intact.

## Backends shipped in v0.1

| Backend | Extra | Requires | `supports_reconnect` |
|---|---|---|---|
| `LocalWorkspace` | none | nothing — runs anywhere Python runs | False (process death = gone) |
| `E2BWorkspace`   | `[e2b]` | `E2B_API_KEY` env var | True (E2B native `reconnect`) |

`LocalWorkspace` is **not a security boundary**. It is the zero-infra default so `oak demo` works on a fresh machine. For untrusted LLM-generated code, use `E2BWorkspace`.

Daytona / Modal / Vercel / Cloudflare / Runloop / Browserbase backends ship as community packages discovered via entry points.

## Capability flags

Every backend declares what it supports honestly:

```python
ws.capabilities.supports_reconnect      # True for E2B, False for Local
ws.capabilities.supports_snapshot       # False for v0.1 backends
ws.capabilities.supports_gpu            # False for v0.1 backends
ws.capabilities.native_idle_timeout     # True for E2B (timeout_ms config)
ws.capabilities.max_idle                # timedelta or None
```

Capability-dependent methods raise `CapabilityUnsupported` rather than silently no-op. No surprises in production.

## Reconnect contract

The `handle` property and `reconnect()` classmethod are how cross-process session resume works end-to-end:

```python
# [USER] Process A
ws_a = await oak.workspace.create("e2b", api_key=...)
handle = ws_a.handle              # [OAK] serializable dict; NO secrets
# ... oak.session persists handle in state store ...
await ws_a.pause()

# [USER] Process B (different host, hours later)
ws_b = await oak.workspace.reconnect("e2b", handle)
# [PROVIDER] E2B SDK reattaches; filesystem intact
```

See [`docs/design/workspace.md`](../../docs/design/workspace.md) for the full reconnect contract + span attribute schema.

## Provider-native lifetime config

oak does NOT run a background timer to pause/terminate idle workspaces. Pass the provider's native idle config at create time:

```python
# [USER]
ws = await oak.workspace.create("e2b", timeout_ms=900_000)   # E2B handles auto-terminate after 15min idle
```

Belt-and-suspenders: `oak.session.attach()` exit handler additionally pauses the workspace on clean exit. Together, app-level clean shutdown + provider auto-terminate cover both happy path and orphan-cleanup.

## Contract suite

Custom backends pass the same tests oak's own backends do:

```bash
pytest --pyargs oak.workspace.tests.contract --backend my_pkg:MyWorkspace
```

If green, your backend is oak-compliant. See [`docs/extending-oak.md`](../../docs/extending-oak.md) for the recipe.

## Errors

```python
from oak.workspace import (
    CapabilityUnsupported,   # missing capability
    WorkspaceTerminated,     # any call after terminate()
    WorkspaceUnreachable,    # reconnect() failed (sandbox no longer exists)
    WorkspaceTimeout,        # execute() exceeded timeout
    WorkspaceError,          # base class
)
```

## License

Apache-2.0.
