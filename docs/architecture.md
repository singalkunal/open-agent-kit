# oak architecture

oak closes the gap between **packaging an agent** (system prompt + tools + framework loop) and **shipping it to production** (multi-user, multi-server, resumable, non-blocking). Everything in this doc is in service of that one gap.

### A typical production-agent flow

Your product starts an agent for a user. The agent runs for minutes - calling models, running tool calls in a sandbox (shell commands, file edits, code), reading data, calling external APIs. Your client (web app, CLI, mobile app, embedded tool - whatever you ship) streams progress back. The user can stop the agent, approve actions it proposes, or step away.

When the client disconnects, the session pauses. Later - minutes, hours, days - the user reconnects from the same client or a different one. The new connection may land on a different server in your cluster. They pick up exactly where they left off: same conversation, same files in the sandbox, same pending state.

Other users are doing the same thing concurrently. Multiple servers each handle multiple sessions. No two servers ever process the same session at the same time.

That's the flow. oak sits between your product code and the boring runtime parts of it. It doesn't dictate the client (browser, CLI, native app - your choice) or the transport (WebSocket, SSE, long-poll, HTTP polling - your choice). It handles what happens on the server side, between the framework's agent loop and your infrastructure.

### Why this needs a library

Five problems sit between you and that flow:

1. **Cross-server sandbox reconnect.** When a different server picks up the connection, it needs to wake the same sandbox the previous server was using. Filesystem state has to survive; in-flight processes won't.
2. **Single-owner coordination across servers.** Without it, two servers race on the same session - client reconnects across a load balancer make this trivially reproducible.
3. **Rebuilding the conversation from somewhere.** The new server needs the prior message history. It must come from somewhere both servers can read.
4. **Bridging async to sync.** Most agent frameworks ship synchronous `Conversation.run()`. Calling it naively from an async server freezes the event loop and your live stream stalls.
5. **Not locking into one provider.** Sandbox SDKs (E2B, Daytona, Modal) all differ. Tracing backends (Langfuse, Phoenix, Staso) all differ. State stores all differ. Picking one shouldn't mean rewriting when you want to swap.

What's available today, and why each one is incomplete:

| Tool category | What it gives you | What it doesn't |
|---|---|---|
| Agent frameworks (OpenHands, Claude Agent SDK, OpenAI Agents SDK, LangGraph, Mastra, smolagents) | The agent loop, tool execution, optional approval gates | Assume single-process runtime. No cross-server reconnect, no distributed lease, no async wrapping. OpenHands' `agent-server` ships a `FileLock` for ownership - useless across servers. |
| Sandbox SDKs (E2B, Daytona, Modal, ...) | Provider-specific create/exec/pause/reconnect | Each is a different API. Swap a provider = rewrite. |
| Tracing platforms (Langfuse, Phoenix, Staso, Logfire) | Emit spans for every LLM and tool call | Don't help you read spans back to reconstruct conversation history. |
| Durable execution (Inngest, Temporal, streaq) | Workflow orchestration with retry/restart guarantees | Built for workflows; not the right shape for an agent session that streams events live to a connected client. |
| LangGraph Checkpointer | Persists graph state across restarts | LangGraph-only. Locks you out of every other framework. |
| OpenAI Threads API | Server-side conversation state | OpenAI-only. Doesn't help if you're not on OpenAI. |
| AWS Bedrock AgentCore | All of the above, in one managed service | Proprietary, AWS-only, cloud-locked. |

The gap nobody fills in OSS: a framework-neutral, multi-vendor runtime layer for cross-server agent sessions. oak is exactly that.

### Who oak is for (and who it isn't)

Position your product on two axes - **where the agent runs** and **how long a single session lives**.

```
                            LONG-RUNNING / multi-turn
                                       ↑
                                       │
        (rare edge case)               │   ← OAK'S TARGET
        Long-running agents that run   │     Autonomous server-side agents.
        on the user's machine: local   │     One session lives minutes to days,
        Claude Code, local CLI agents. │     spans many turns, may pause and
        oak doesn't help much; you     │     resume across server restarts.
        own the whole runtime.         │     Examples: SRE / heal agents,
                                       │     async code agents, research
                                       │     agents, long-running task
                                       │     workers. (Devin / Manus /
                                       │     OpenHands-deployed shape.)
                                       │
            ───────────────────────────┼─────────────────────────────→
            USER DEVICE                │                     SERVER INFRA
                                       │
        IDE co-pilots and inline       │   Short server-side calls
        autocomplete:                  │   - one-shot tool execution
        - Cursor                       │   - classification / embedding jobs
        - GitHub Copilot               │   - Lambda-style serverless agents
        - Continue.dev                 │   - synchronous request → reply
        - Aider in interactive mode    │
                                       │   oak is overkill here; the provider
        oak isn't for this. The agent  │   SDK + a function handler is fine.
        runs on the user's machine     │   No session resume, no lease,
        and the lifecycle fits inside  │   no async bridging needed.
        one editor invocation.         │
                                       ↓
                            SHORT / single-turn
```

Only the **top-right** quadrant has all of: a sandbox to run code, a session that outlives one request, multiple servers possibly handling the same session over time, and a connected client streaming events. That's where the runtime concerns from the previous section all bite at once, and that's where oak earns its place.

If your product is in any other quadrant, oak's primitives still work, but most of them are over-engineered for what you need.

### The stack

```
┌──────────────────────────────────────────────────────────────────┐
│  YOUR PRODUCT                                                     │
│  routes · client transport · auth · tools · prompts · UI          │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  AGENT FRAMEWORK  /  AGENT HARNESS                (you pick one)  │
│                                                                   │
│  The loop:  model call → tool call → observation → repeat        │
│  Tools, prompts, confirmation policy, message store - all here.  │
│                                                                   │
│  options: OpenHands · Claude Agent SDK · OpenAI Agents SDK ·      │
│           LangGraph · Mastra · CrewAI · smolagents                │
│                                                                   │
│  >>> oak does NOT modify, subclass, or fork this layer.           │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
╔══════════════════════════════════════════════════════════════════╗
║  OAK                                                              ║
║                                                                   ║
║   oak.workspace      sandbox abstraction with reconnect           ║
║   oak.session        attach/end + per-framework wrappers          ║
║                      (wraps the framework's session object;       ║
║                       framework loop runs unchanged inside it)    ║
║   oak (CLI)          demo · init · protocols · version            ║
║                                                                   ║
║   framework-neutral · multi-vendor · escape hatches everywhere    ║
╚══════════════════════════════════════════════════════════════════╝
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  PROVIDERS                                        (you pick each) │
│  Sandbox:  E2B · Daytona · Modal · Docker · local                 │
│  State:    Redis · Postgres · in-memory · DynamoDB · your DB      │
│  Tracing:  Staso · Langfuse · Phoenix · Logfire · any OTLP        │
└──────────────────────────────────────────────────────────────────┘
```

Each layer talks down to the one below. Lower layers never reach up. The framework runs the agent's logic; oak handles the runtime concerns around it; providers store the bytes.

### Where the harness lives (and what oak does to it)

oak doesn't replace, subclass, or fork the agent harness. It **wraps** the framework's native session object by composition - the framework loop is untouched inside.

```
  oak.session.openhands.OpenHandsSession   ← thin async-safe wrapper (oak owns this)
  ┌────────────────────────────────────────────────────────────────┐
  │  .conv  →  LocalConversation                                   │
  │           ┌──────────────────────────────────────────────────┐ │
  │           │  AGENT HARNESS  (framework code; oak ≠ touches)  │ │
  │           │                                                  │ │
  │           │   model call → tool call → observation → repeat │ │
  │           │   tools, prompts, confirmation policy, history  │ │
  │           └──────────────────────────────────────────────────┘ │
  │                                                                │
  │  async run_turn()  =  await asyncio.to_thread(self.conv.run)  │
  │  async approve()   =  await asyncio.to_thread(self.conv.run)  │
  │  async reject()    =  self.conv.reject_pending_actions(...)   │
  │                       + await asyncio.to_thread(self.conv.run)│
  └────────────────────────────────────────────────────────────────┘
       ▲
       │  The upstream object stays directly reachable as `session.conv`.
       │  Any framework API oak hasn't wrapped, you call on `.conv`.
```

What oak adds *around* the harness (none of which lives inside the harness itself):

- **Lease.** Claim ownership of `session_id` before the harness runs; release on exit.
- **Workspace lifecycle.** Boot / reconnect the sandbox the harness will run code in; pause it on exit.
- **Async bridge.** Frameworks ship synchronous `Conversation.run()`. oak runs it on a worker thread so your event loop keeps streaming.
- **Trace replay.** Read prior turns from your tracing backend and hand them to the framework as initial messages.

Result: you can swap the framework (OpenHands → Claude Agent SDK → smolagents) without rewriting oak; you can swap oak without rewriting the framework code; and when oak's wrapper doesn't expose an upstream feature, you reach in via `.conv` and use it directly.

### Sandbox patterns

Production agents use sandboxes in several distinct patterns. oak targets one of them.

| # | Pattern | What it is | oak's stance |
|---|---|---|---|
| 1 | Ephemeral per-call | Boot, execute one command, tear down. No state across calls. | Works (skip `reconnect()`). Often overkill - the provider SDK directly is fine. |
| 2 | Ephemeral per-session | Boot at session start, hold across turns, tear down at session end. No survival across restarts. | Works (`exit_workspace="terminate"`). Useful for multi-provider portability without resume. |
| 3 | **Persistent / sticky per-session** | Sandbox survives across turns AND pauses, restarts, server changes. Reconnect from any server. | **oak's primary target.** The `attach` / `pause` / `reconnect` / `end` flow exists for this. |
| 4 | Shared / pooled | Pool of warm sandboxes shared across sessions; grab one per request. | Compose above `oak.workspace` - a pool manager + slot lease sits next to it; session model unchanged. |
| 5 | Per-tenant / per-org persistent | One sandbox per tenant, shared across that tenant's sessions, lives indefinitely. | Decouple sandbox lifetime from `session_id` in user code; oak's primitives don't enforce a 1:1 mapping. |
| 6 | Forked from snapshot | Snapshot a base environment; fork to a child sandbox per session. | `Workspace.snapshot()` / `restore()` live in the Protocol behind a capability flag; usable wherever a backend implements them. |

If your product uses pattern 1 or 2, oak's workspace abstraction still gets you multi-provider portability - just don't store handles and don't call `reconnect()`. Patterns 4, 5, 6 compose above the Protocol; oak's Protocols are small enough that supporting new patterns means adding Protocols or methods, not rewriting the core.

#### Timeline view (1 vs 2 vs 3)

Time runs left to right. Each `[box]` is a sandbox state. Server changes are explicit.

```
Pattern 1 - ephemeral per-call
  [boot ─ exec ─ kill]   [boot ─ exec ─ kill]   [boot ─ exec ─ kill]   ...
   (one cycle per command; no state survives between calls)

Pattern 2 - ephemeral per-session
  [boot ─ exec ─ exec ─ exec ─ exec ─ kill]
   (one cycle per session; dies when the session ends OR the server dies)
   ──── one server, start to finish ────

Pattern 3 - persistent per-session (oak's target)
  [boot ─ exec ─ exec ─ pause]  · · · idle · · ·  [reconnect ─ exec ─ exec ─ end]
   ─── server A ───              (no compute,      ─── server B (different) ───
                                  sandbox preserved
                                  by provider)
```

Pattern 3's distinguishing trait: the sandbox **persists across both time and server changes**. That's what `oak.workspace.reconnect(provider, handle)` makes possible, and what every other piece of `oak.session` exists to support.

The rest of this doc describes pattern 3.

### What oak handles in that flow

- **The same sandbox across the session.** `oak.workspace.create(provider, ...)` and `oak.workspace.reconnect(provider, handle)` work across local, E2B, Daytona, Modal, Docker. One interface; the agent keeps its filesystem across turns, pauses, and server restarts.
- **A small handle that travels with the session.** Serializable dict, no secrets, retrievable from any server so any process can wake the sandbox.
- **One call to resume.** `oak.session.openhands.attach(session_id, ...)` claims the lease, reconnects the sandbox, replays history from your tracer, returns a ready session.
- **One owner per session at a time.** Pluggable lease (Redis, in-memory, custom) with TTL. Only one server processes a session at a time; dead owners expire automatically.
- **An async-safe wrapper around sync loops.** Framework's `Conversation.run()` runs in a worker thread; your event loop keeps streaming.

### What you keep building

- **Product code.** Routes, auth, UI, client transport (WebSocket, SSE, long-poll, your choice).
- **System prompt and tools.** oak doesn't ship either.
- **Framework choice.** oak wraps it; it doesn't replace it.
- **Tracing backend.** oak reads spans from whichever you picked.
- **Sandbox provider account.** oak drives the SDK; you bring the credentials.
- **State store.** Three-method interface. Pick Redis, Postgres, in-memory, or write your own.
- **Your infra.** oak doesn't provision Redis, Postgres, or sandbox runtimes for you. Run them however you prefer - local containers, k8s, managed cloud, whatever fits.

### Walkthrough - one session's life

Six steps. oak shows up from step 2 onwards.

**1. Created.** Your app inserts a session row, returns the `session_id`. No oak involvement.

**2. First turn.** Your handler calls `oak.session.openhands.attach(session_id, ...)`. oak claims the lease, calls your `workspace_factory()` to boot a fresh sandbox, finds no prior history (this is a new session), returns a session object. You call `session.run_turn(text)`. The framework drives the agent loop in a worker thread. Your tracing SDK emits spans for every model and tool call. Your handler streams those events to whichever transport you've wired to your client. The user watches the agent work.

**3. Subsequent turns.** Same flow. Lease is already yours. Sandbox is already running. The conversation grows in your tracing backend (no oak-side duplication).

**4. Paused.** The client disconnects; the `async with` block exits. oak pauses the sandbox, writes the sandbox handle to your state store, releases the lease.

**5. Resumed.** Later (minutes, hours, days). A client reconnects, possibly via a different transport, possibly to a different server. Your handler calls `attach` again. oak claims the lease (the prior server's claim has expired via TTL), reads the saved handle from the state store, calls the provider's reconnect API to wake the sandbox (filesystem intact), fetches the prior spans from your tracing backend, reconstructs the message history. Returns a ready session. The agent continues.

**6. Ended.** Your code calls `oak.session.end(session_id)` when the work is done (final response, user clicked End, hard TTL cron). oak terminates the sandbox, clears state, releases the lease.

### Where state actually lives

For resume to work, three things must be retrievable by any server in your cluster at any moment. Each kind of state needs a different shape of storage:

| State | Where it lives | Why this shape |
|---|---|---|
| Sandbox handle (small, must always be there) | A key-value store: Redis, Postgres, in-memory for dev | Tracing data is sampled and sometimes dropped; the handle cannot be. Key-value is the right primitive. |
| Conversation history (large, append-only) | Your tracing backend, queried via an adapter | You already emit these spans for observability. Storing them twice would drift. |
| Who owns the session right now (mutable) | A short-lived claim in Redis with TTL + compare-and-set | Mutable; needs strict mutual exclusion; dead servers must release automatically. |

Each is pluggable. Swap any of them - Redis to DynamoDB, Staso to Langfuse, E2B to Daytona - and the agent code doesn't change.

### Customization, in three weights

| Weight | Mechanism | When to use |
|---|---|---|
| Light | `attach` kwargs (`on_workspace_lost`, `wait_for_lease`, `exit_workspace`) | Tuning behavior per session without writing code. |
| Medium | Swap a backend. `Workspace` is six methods, `SessionStateStore` three, `TraceSource` one. Pass to `oak.session.configure()` or register via entry points. | Adding a provider, store, or tracing backend oak doesn't ship. |
| Heavy | Escape hatch. `session.conv`, `workspace.underlying`, `attached.workspace` expose the native object. | Calling provider-specific APIs, or wrapping oak primitives for exotic patterns (fallback chains, federation, multi-tenant routing). |

### When oak isn't the right fit

A one-shot script with no resume, no live streaming, single-process - just construct your agent and run it. You want an agent framework - oak isn't one; pick OpenHands or similar. You want a hosted runtime - that's AWS Bedrock AgentCore. You want prompt templating - LangChain Prompts, Mirascope, DSPy. You want one library that bundles observability + evals + guards - that's a platform (Staso, Langfuse), not oak.

### Vocabulary

In the [README glossary](../README.md#glossary). Anything else is your framework's or provider's vocabulary.
