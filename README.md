# open-agent-kit (`oak`)

**Production runtime toolkit for agents.** Closes the gap between packaging an agent and shipping it. Apache-2.

## What it's for

### Sandbox

- **Pluggable workspace.** Local, E2B, Daytona, Modal, Docker behind one interface.
- **Sticky per session.** Survives turns, pauses, and server restarts.
- **Cross-server reconnect via handle.** Any server in the cluster wakes the same sandbox.

### Session

- **Single owner per session.** Pluggable lease (Redis, in-memory, custom) with TTL stops two servers from racing.
- **Resumable.** Conversation history rebuilt from your tracing backend on reconnect. No duplicate store.

### Framework integration

- **Per-framework wrapper.** Wraps your framework's native session object (OpenHands first). Upstream API stays directly reachable.
- **Non-blocking async bridge.** The framework's sync loop runs on a worker thread. Your event loop stays free.

### Pluggable backends

- **State store.** Redis, Postgres, in-memory, custom.
- **Tracing backend.** Staso, Langfuse, Phoenix, Logfire, any OTLP.

### Across the board

- **Capability flags per backend.** `supports_reconnect`, `supports_snapshot`, etc. Callers branch on facts.
- **Escape hatches everywhere.** `session.conv`, `workspace.underlying`, `attached.workspace` always reachable.

oak is the OSS counterpart to AWS Bedrock AgentCore: same shape, no cloud lock-in.

## Try it now

```bash
pip install oak                  # core (workspace + session, no extras)
oak demo                         # zero-credential agent loop, ~5 seconds
```

`oak demo` wires a local sandbox + in-memory state store + a stub agent end-to-end so you can see what `oak.workspace.create` and `oak.session.attach` actually do. No API keys, no Docker, no Redis.

## Generate a setup bundle

When you're ready to wire oak into a real backend:

```bash
oak setup                        # interactive wizard; pick backends, get a setup bundle
```

The wizard asks for your sandbox provider (Local / E2B), state store (in-memory / Redis / Postgres / custom), lease backend (Redis / in-memory / none / custom), tracing backend (Staso / Langfuse / Phoenix / Logfire / OTLP / console), and framework wrapper (OpenHands). Outputs four files into a directory:

- `oak_setup.py` - imports + `oak.session.configure(...)` + a sample request handler using `oak.session.openhands.attach(...)`
- `pyproject_snippet.toml` - dependencies and extras to paste into your project
- `.env.example` - the env vars the picked backends need
- `docker-compose.yml` - only when Redis or Postgres is picked, for local dev

Paste `oak_setup.py` into your FastAPI lifespan, merge the pyproject snippet, fill in `.env`, `docker compose up -d`, done.

## Realistic usage

```python
# [USER] one-time process startup
oak.session.configure(
    state_store=oak.session.RedisStateStore(redis=redis_client),     # [USER picks backend]
    trace=oak.session.StasoTraceSource(api_key=...),                  # [USER picks backend]
    lease=oak.session.RedisLease(redis=redis_client),                 # [USER picks backend]
)

# [USER] per-request handler - works for first turn AND for resume hours later
async def handle_user_message(session_id: str, user_text: str):
    async with oak.session.openhands.attach(                          # [OAK] orchestrates
        session_id,
        agent=Agent(llm=llm, tools=tools, system_message=my_prompt),  # [USER + FRAMEWORK]
        system_prompt=my_prompt,                                       # [USER]
        workspace_factory=lambda: oak.workspace.create("e2b"),
        on_workspace_lost="boot_fresh",
    ) as session:
        result = await session.run_turn(user_text)                    # [OAK wrapper drives FRAMEWORK]

        if result.status == "waiting_for_confirmation":
            if await user_approved():                                  # [USER] product UI
                result = await session.approve()
            else:
                result = await session.reject("user declined")

        if result.status == "finished":
            await oak.session.end(session_id)
```

The `attach` call does the work: claims the lease, reconnects (or boots) the sandbox, reads prior conversation spans from your tracing backend, and hands back a ready session. On exit, it pauses the sandbox and releases the lease. See [`docs/architecture.md`](docs/architecture.md) for the full lifecycle.

## Install

```bash
pip install oak                                  # CLI + workspace + session, no extras
pip install "oak[e2b,redis,staso,openhands]"     # production-ish: real sandbox, state store, tracing, framework
```

Optional extras:

- **Workspace providers:** `[e2b]`. Community adapters install separately (`oak-workspace-daytona`, etc.).
- **State store:** `[redis]`, `[postgres]`.
- **Tracing backend:** `[staso]`, `[langfuse]`, `[phoenix]`, `[logfire]`.
- **Agent framework:** `[openhands]`. Others install separately as adapters appear.

## What ships in v0.1

| Module | What it does |
|---|---|
| `oak.workspace` | Sandbox abstraction with `reconnect()`. Reference backends: local subprocess, E2B. Community backends register via Python entry points. |
| `oak.session` | `attach(session_id)` / `end(session_id)` flow, plus per-framework wrappers (currently `oak.session.openhands`). Pluggable state store, tracing backend, lease. |
| `oak` (CLI) | `demo`, `init`, `protocols`, `version`. |

## What oak is NOT

| Not this | Use this instead |
|---|---|
| An agent framework | OpenHands · Claude Agent SDK · OpenAI Agents SDK · LangGraph · Mastra · CrewAI |
| An LLM router | LiteLLM · Portkey · OpenRouter |
| A sandbox runtime | E2B · Daytona · Modal · Docker - oak wraps them |
| A memory store | Mem0 · Letta · Zep · SQLite |
| A tracing platform | Staso · Langfuse · Phoenix · Logfire · Datadog - oak reads from them |
| A prompt-engineering library | LangChain Prompts · Mirascope · DSPy |
| A durable execution engine | Inngest · Temporal · streaq |
| Observability dashboards | Use your tracing platform's UI |
| Eval / guard / firewall | A platform (Staso, etc.) - oak is the runtime layer underneath |

## Glossary

| Term | Meaning in oak |
|---|---|
| **session** | A unit of agent runtime work keyed by a string `session_id`. Your app owns the metadata (created_at, user_id, etc.); oak only handles the runtime mechanics. |
| **workspace** | A sandbox where agent-chosen code runs. One per session. Pluggable backend (Local, E2B, ...). |
| **handle** | A small serializable ID for a paused workspace. Stored so a different server can call `reconnect()` to wake it. Secret-free. |
| **reconnect** | Wake a paused workspace using its handle. Filesystem state survives; in-flight processes do not. |
| **attach** | `oak.session.attach(session_id)` - context manager that claims the lease, reconnects the workspace, reads conversation history from your tracing backend, and returns the assembled session. |
| **end** | `oak.session.end(session_id)` - terminate the workspace, clear stored state, release the lease. Idempotent. |
| **state store** | A small key-value store oak uses for critical handles (workspace ID, pending approval). Reference: in-memory, Redis, Postgres. |
| **trace source** | An adapter that queries your tracing backend for the spans of a given session. Reference: Staso, Langfuse, Phoenix, Logfire, OTLP base. |
| **lease** | Internal-by-default ownership claim - only one process holds a given `session_id` at a time. CAS + TTL + renewal. Configure with `oak.session.configure(lease=...)`. |
| **framework wrapper** | A per-framework adapter at `oak.session.<framework>`. Wraps the framework's native session object (composition, not subclassing) and adds async-bridged `run_turn` / `approve` / `reject`. |
| **`AttachedSession`** | Dataclass returned by `attach()`. Fields: `lease`, `workspace`, `state`, plus diagnostic statuses (`workspace_status`, `trace_status`). |
| **`TurnResult`** | Returned by `session.run_turn()`. `status` is `finished` / `waiting_for_confirmation` / `stuck` / `error` / `running`. |
| **capability flag** | Boolean on a backend declaring what it supports (`supports_reconnect`, `supports_snapshot`, ...). Callers branch on facts; methods gated by a False flag raise `CapabilityUnsupported`. |
| **escape hatch** | The framework's or provider's native object, always accessible - `session.conv`, `attached.workspace`, `workspace.underlying`. |

## Docs

- [`docs/architecture.md`](docs/architecture.md) - full lifecycle, why each piece exists
- [`docs/principles.md`](docs/principles.md) - the nine rules
- [`docs/design/workspace.md`](docs/design/workspace.md) - sandbox abstraction + reconnect contract
- [`docs/design/session.md`](docs/design/session.md) - `attach`/`end`, state store, trace source, per-framework wrappers
- [`docs/extending-oak.md`](docs/extending-oak.md) - recipes for adding backends and framework adapters
- [`docs/contract_tests.md`](docs/contract_tests.md) - what a backend has to satisfy to be oak-compatible

## Repo layout

```
packages/
  oak-workspace/      Workspace abstraction + Local + E2B
  oak-session/        attach/end + state-store + trace-source + lease (internal)
                      + per-framework wrappers (oak.session.openhands.*)
  oak/                CLI: demo, init, protocols, version
docs/
  architecture.md   principles.md   contract_tests.md   extending-oak.md   onboarding.md
  design/
    workspace.md    session.md
```

## Status

v0.1: `oak.workspace`, `oak.session` (with reference state-store, tracing, and lease backends and the `openhands` framework wrapper), and the umbrella CLI. Contract tests cover every Protocol.

## License

Apache-2.
