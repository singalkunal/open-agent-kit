# oak-session

Session rehydration, lease coordination, and per-framework wrappers for oak.

oak.session is the load-bearing module. It handles:

- **Cross-process resume** — close a session, come back hours later (possibly on a
  different process), continue where you left off.
- **Single-ownership coordination** — only one process processes a given session at
  a time, even under WebSocket reconnects and load-balancer rerouting.
- **Per-framework wrappers** — the same primitive works whether the agent loop
  is OpenHands, Claude Agent SDK, OpenAI Agents SDK, or LangGraph.

See `docs/design/session.md` in the monorepo for the full spec.

## Install

```bash
pip install oak-session                    # core
pip install oak-session[redis]             # RedisStateStore + RedisLease
pip install oak-session[postgres]          # PostgresStateStore
pip install oak-session[staso]             # StasoTraceSource (stub until SDK ships)
pip install oak-session[openhands]         # oak.session.openhands wrappers
```

## Quickstart (OpenHands)

```python
# [USER] one-time setup at process startup
oak.session.configure(
    state_store=oak.session.RedisStateStore(redis=redis_client),
    trace=oak.session.OTLPSpansTraceSource(query=my_jaeger_query),
    lease=oak.session.RedisLease(redis=redis_client),
)

# [USER] per-request handler
async def handle_user_message(session_id: str, user_text: str):
    async with oak.session.openhands.attach(             # [OAK]
        session_id,
        agent=Agent(                                     # [USER + FRAMEWORK]
            llm=llm,
            tools=tools,
            system_message="<your system prompt>",
        ),
        system_prompt="<your system prompt>",         # [USER]
        workspace_factory=lambda: oak.workspace.create("e2b"),
        on_workspace_lost="boot_fresh",
        callbacks=[my_event_translator],                 # [USER] sync per-Event hooks; forwarded to upstream LocalConversation
    ) as session:
        # [OAK wrapper] drives upstream LocalConversation non-blocking
        result = await session.run_turn(user_text)

        if result.status == "waiting_for_confirmation":
            # [USER] product-side UI loop for approval
            if await get_user_decision():
                result = await session.approve()
            else:
                result = await session.reject("user declined")

        is_done = result.status == "finished"

    if is_done:
        await oak.session.end(session_id)                # [OAK]
```

## Three storage shapes

| Shape | Backend Protocol | What lives here | Backends |
|---|---|---|---|
| Append-only history | `TraceSource` | LLM messages, tool calls, `workspace.boot` spans | Staso / Langfuse / Phoenix / Logfire / OTLP |
| Critical key-value | `SessionStateStore` | Workspace handle, pending action state | InMemory / Redis / Postgres / custom |
| Mutable ownership lease | `LeaseManager` | Which process owns this session right now | InMemory / Redis / custom |

Each shape, the right backend, the right semantics.

## Three-tier pluggability

Every public surface exposes three extension tiers:

| Tier | Mechanism | Use case |
|---|---|---|
| **1 — Backend plug** | Protocol + reference impls + entry-point discovery | Swap Redis ↔ Postgres state store, E2B ↔ Daytona workspace |
| **2 — Behavior knob** | kwarg / config parameter | Tune defaults (`on_workspace_lost`, `exit_workspace`, `include_notices`) |
| **3 — Full custom** | Subclass / callback / escape hatch | `session_class=`, `context_composer=`, direct `attached.workspace` access |

## Ownership markers

Docs and examples use ownership markers so the boundary between user code,
framework code, and oak code stays explicit:

- **[USER]** — your code
- **[OAK]** — oak's mechanism
- **[FRAMEWORK]** — upstream agent framework (OpenHands, Claude Agent SDK, ...)

## License

Apache-2.0
