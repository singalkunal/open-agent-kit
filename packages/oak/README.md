# oak

CLI and umbrella meta-package for oak. Lets users install the full v0.1 surface in one command.

```bash
pipx run oak demo                # zero-credentials end-to-end demo (<60s)
oak init myproj                  # scaffold a starter project
oak protocols                    # list installed Protocols + registered backends
oak protocols show Workspace     # methods + docstrings for one Protocol
oak version
```

### What `oak demo` does

Wires `oak.workspace.LocalWorkspace` + `oak.session.InMemoryStateStore` (no lease, no trace source) into a tiny scripted "agent" loop. No API keys, no Docker, no Redis required.

The "agent" is a deterministic stub (no LLM call) that exercises:
- `oak.workspace.create("local", ...)` + `execute()` + `terminate()`
- `oak.session.configure(state_store=InMemoryStateStore())`
- `async with oak.session.attach("demo_session") as attached:`
- `oak.session.end("demo_session")`

Proves the wiring; not the intelligence. Bring your own model.

### Install

```bash
# CLI + every sibling primitive at default versions
pip install 'oak[all]'

# CLI + just what the demo needs (no E2B, no Redis, no vendor extras)
pip install 'oak[demo]'

# Just the CLI itself
pip install oak

# Production-ish setup (OpenHands wrapper + E2B + Redis + Staso)
pip install 'oak[openhands,e2b,redis,staso]'
```

### Templates

`oak init <name>` renders the `starter` template by default. The starter is a small FastAPI app that wires:
- `oak.workspace.create("e2b", ...)` for the sandbox
- `oak.session.RedisStateStore` + `oak.session.RedisLease` for cross-process state + ownership
- `oak.session.openhands.attach()` for the per-request flow
- A trivial `Agent` with one tool (`echo`) so the demo is end-to-end runnable

Additional templates land only when the roadmap demand gate is met.

### License

Apache-2.0.
