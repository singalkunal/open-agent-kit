# `oak.session` design

The module that handles a session's lifecycle: bring it back to life on demand, hand it back ready to use, clean it up when done.

## The problem this solves

A session in production isn't bound to a single server. A user can close their browser and reconnect from a different device hours later, possibly to a different server in your cluster. Whichever server picks up the WebSocket needs to:

- Wake up the sandbox the session was using.
- Recover the conversation history.
- Make sure no other server is also trying to run this session right now.

Without a library, every team writes the same three pieces of code, badly, every time. `oak.session` is those three pieces, written once, behind one call: `attach()`.

The cleanup counterpart is `end()` - terminate the sandbox, clear stored state, release the ownership claim.

## Where state lives

Three kinds of state, three different storage shapes. They don't overlap:

| Kind of state | Backend | Why this shape |
|---|---|---|
| Conversation history (all messages, tool calls, results) | Your tracing backend, queried via a `TraceSource` adapter - Staso, Langfuse, Phoenix, Logfire, OTLP base | You're already storing these spans for observability. Storing them twice would be wasteful and drift-prone. |
| Critical handles (sandbox ID, pending approval) | `SessionStateStore` - Redis / Postgres / in-memory / custom | Tracing data can be sampled or dropped; these few keys must be reliably retrievable. |
| Who owns the session right now | `LeaseManager` (internal to `oak.session`) - Redis CAS or in-memory | Mutable; TTL means a crashed server's claim eventually expires; CAS means two servers can't both claim it. |

Each backend is pluggable. You wire them once at startup; the rest of oak reads from this registry.

## Public surface

```python
# Process-level setup (called once at startup)
oak.session.configure(
    state_store: SessionStateStore | None = None,    # default: InMemoryStateStore
    trace: TraceSource | None = None,                # default: None (no history reconstruction)
    lease: LeaseManager | None = None,               # default: None (no ownership coordination)
)

# Per-session lifecycle
async with oak.session.attach(
    session_id: str,
    *,
    workspace_factory: Callable[[], Awaitable[Workspace]] | None = None,
    on_workspace_lost: Literal["boot_fresh", "raise", "skip"] = "skip",
    wait_for_lease: bool | float = False,
    exit_workspace: Literal["pause", "keep_alive", "terminate"] = "pause",
) as attached: ...
# attached: AttachedSession

await oak.session.end(session_id: str) -> None
```

### `AttachedSession`

```python
@dataclass
class AttachedSession:
    session_id: str
    lease: Lease | None              # None if no lease configured
    workspace: Workspace | None       # None if no prior or reconnect failed (and on_workspace_lost="skip")
    state: SessionState

    # Diagnostics - caller can branch on these
    workspace_status: Literal["no_prior", "reattached", "reconnect_failed", "boot_fresh"]
    workspace_reconnect_error: str | None
    trace_status: Literal["loaded", "partial", "no_prior", "unavailable"]
    trace_error: str | None

    # User-stuffable opaque metadata
    extra: dict[str, Any]
```

### `SessionState`

```python
@dataclass
class SessionState:
    messages: list[Message]                  # prior LLM conversation, in order
    tool_history: list[ToolCall]             # prior tool invocations + results
    pending_action: PendingAction | None     # if agent stopped at approval gate

@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    cache_breakpoint: bool = False           # marks KV-cache stable-prefix boundary
```

## `attach()` semantics

```
[OAK] attach(session_id) does, in order:

  1. Acquire lease (if lease configured)
     ├─ If lease held by live owner: behavior per wait_for_lease
     │  ├─ wait_for_lease=False (default) → raise LeaseHeld
     │  └─ wait_for_lease=N → wait up to N seconds; raise LeaseHeld on timeout
     └─ If lease held by dead owner: reclaim with generation += 1

  2. Read workspace handle from state_store (if configured)
     ├─ If handle exists:
     │  └─ Call oak.workspace.reconnect(provider, handle)
     │     ├─ Success → attached.workspace, workspace_status="reattached"
     │     └─ Reconnect fails (sandbox GC'd, etc.):
     │        ├─ on_workspace_lost="boot_fresh" → call workspace_factory()
     │        │    workspace_status="boot_fresh", workspace_reconnect_error=<reason>
     │        ├─ on_workspace_lost="raise"      → raise WorkspaceUnreachable
     │        └─ on_workspace_lost="skip"       → attached.workspace=None, status="reconnect_failed"
     └─ If no handle:
        ├─ workspace_factory provided → call it; workspace_status="boot_fresh"
        └─ no factory                  → attached.workspace=None, status="no_prior"

  3. Fetch spans from trace_source (if configured)
     ├─ Success → reconstruct_session(spans); attached.state populated, trace_status="loaded"
     ├─ Partial (backend still indexing) → trace_status="partial", state has what's available
     ├─ No prior spans (genuinely new session) → trace_status="no_prior", state empty
     └─ Backend error → trace_status="unavailable", trace_error=<reason>, state empty

  4. Yield AttachedSession to the with block

  5. On __aexit__:
     ├─ If exit_workspace="pause" (default)     → workspace.pause()
     ├─ If exit_workspace="terminate"           → workspace.terminate()
     ├─ If exit_workspace="keep_alive"          → no-op
     └─ Release lease (if held)
```

## `end()` semantics

```
[OAK] end(session_id) does:
  1. Acquire lease (force-reclaim allowed if necessary)
  2. Read workspace handle from state_store
  3. Reconnect workspace (best-effort; ignore if already gone) and call .terminate()
  4. state_store.delete_session(session_id)
  5. Release lease
  6. Subsequent attach() raises SessionEnded
```

`end()` is idempotent. Calling it on an already-ended session is a no-op.

## Backend Protocols

### `SessionStateStore`

```python
class SessionStateStore(Protocol):
    """User-pluggable durable backend for critical session state.
    oak puts/gets handles here; user owns the backend choice.
    """
    async def put(self, session_id: str, key: str, value: dict) -> None: ...
    async def get(self, session_id: str, key: str) -> dict | None: ...
    async def delete_session(self, session_id: str) -> None: ...
```

Documented key namespace:

| Key | Value shape | When oak writes / reads |
|---|---|---|
| `workspace` | `{provider, handle, region, image, created_at}` | Write after workspace boot; read on `attach()` for reconnect |
| `pending_action` | `{action_seq, action_kind, body, ...}` | Write when an approval gate fires; clear on approve/reject |

Reserved key prefix: `oak:*`. User-application keys are encouraged to use a non-`oak:` prefix.

Reference impls (oak ships):
- `InMemoryStateStore` - default; single-process dev/tests
- `RedisStateStore` - `[redis]` extra; production multi-process
- `PostgresStateStore` - `[postgres]` extra; already-on-PG teams

User adds custom backends by implementing the Protocol; community packages register via entry points.

### `TraceSource`

```python
class TraceSource(Protocol):
    """User-pluggable read-side adapter for a tracing backend.
    Returns OTel `gen_ai.*`-shaped spans for a session_id.
    """
    async def fetch_session_spans(self, session_id: str) -> list[GenAISpan]: ...
```

Reference impls (oak ships):
- `StasoTraceSource` - `[staso]` extra (wraps Staso's query SDK)
- `LangfuseTraceSource` - `[langfuse]` extra (wraps `langfuse-python`)
- `PhoenixTraceSource` - `[phoenix]` extra (wraps `arize-phoenix-client`)
- `LogfireTraceSource` - `[logfire]` extra (wraps Logfire SDK)
- `OTLPSpansTraceSource` - base class; user provides query callable for Jaeger / Tempo / ClickHouse / etc.

Per-vendor adapters do **both directions** of the vendor relationship. A vendor adapter typically also has an `install_emission()` method that calls the vendor's auto-patch (e.g., `patch_openai`, `patch_anthropic`). Setup pattern:

```python
# [USER]
staso = oak.session.StasoTraceSource(api_key=os.environ["STASO_API_KEY"])
staso.install_emission()                      # calls Staso SDK's patch_* under the hood

oak.session.configure(
    state_store=oak.session.RedisStateStore(redis=redis_client),
    trace=staso,
    lease=oak.session.RedisLease(redis=redis_client),
)
```

If a user prefers OpenLLMetry or hand-rolled OTel emission, they wire emission themselves and pass a TraceSource that only does the read side.

### `LeaseManager` (internal-by-default)

```python
class LeaseManager(Protocol):
    async def acquire(self, key: str) -> Lease: ...
    async def renew(self, key: str) -> None: ...
    async def release(self, key: str) -> None: ...
```

Lives inside `oak.session._lease` (private). Configurable via `oak.session.configure(lease=...)`. Default: `None` (no coordination - fine for single-process).

Reference impls:
- `InMemoryLease` - default if user enables but doesn't pick a backend
- `RedisLease` - `[redis]` extra; production multi-process

## Context helpers (stateless functions)

```python
# Extract prior conversation from rehydrated session
oak.session.messages_from_session(attached) -> list[Message]

# Notice generators - return string or None based on session status
oak.session.workspace_reset_notice(attached) -> str | None      # if workspace_status == "reconnect_failed"
oak.session.continuation_prelude(attached) -> str | None        # if there's prior history
oak.session.partial_history_notice(attached) -> str | None      # if trace_status == "partial"

# Framework-shape rendering
oak.session.render.for_anthropic(messages) -> list[MessageParam]
oak.session.render.for_openai(messages) -> list[ChatCompletionMessageParam]
oak.session.render.for_langgraph(messages) -> dict
```

These don't compete with LangChain Prompts, Mirascope, or DSPy. Bring your system prompt as a string; oak's helpers handle the session-aware notice generation and message-list rendering.

## Per-framework wrappers

Each framework gets a sub-namespace with the same three-level shape:

```
oak.session.<framework>/
  attach(session_id, agent, system_prompt, ...)  # high-level: one call, opinionated assembly
  build_session(attached, agent, initial_messages, ...)  # mid-level: assemble messages yourself
  <Framework>Session                              # wrapper class (composition over upstream type)
  WorkspaceAdapter                                # for Tier 3 escape (direct upstream usage)
```

v0.1 ships **OpenHands** first (Staso dogfoods it). Others land as adapter packages with the same shape.

### `oak.session.openhands` (v0.1)

#### High-level - `attach()`

```python
# [USER]
async with oak.session.openhands.attach(
    session_id,
    agent=Agent(llm=llm, tools=tools, system_message=staso_sre_prompt),  # [USER + FRAMEWORK]
    system_prompt=staso_sre_prompt,                                       # [USER]
    workspace_factory=lambda: oak.workspace.create("e2b", api_key=...),
    on_workspace_lost="boot_fresh",
    confirmation_policy=AlwaysConfirm(),                                  # [FRAMEWORK] passthrough
    callbacks=[my_event_adapter],                                         # [USER] per-Event sync hooks; forwarded to LocalConversation(callbacks=...)
) as session:
    # [OAK] returned: ready OpenHandsSession with workspace + prior messages seeded
    result = await session.run_turn(user_text)        # [OAK wrapper]
    if result.status == "waiting_for_confirmation":
        result = await session.approve()              # [OAK wrapper]
    is_done = result.status == "finished"

# On exit: [OAK] pauses workspace + releases lease

if is_done:
    await oak.session.end(session_id)
```

Internally, `openhands.attach`:
1. Calls `oak.session.attach(session_id, ...)` to get `AttachedSession`
2. Assembles message list: `system_prompt` + notices (if applicable) + prior messages
3. Calls `build_session(attached, agent=agent, initial_messages=messages, ...)`
4. Yields the `OpenHandsSession` wrapper

#### Mid-level - `build_session()`

```python
# [USER] - custom message assembly
async with oak.session.attach(session_id, workspace_factory=...) as attached:
    messages = [oak.session.Message("system", my_prompt)]                       # [USER]
    if notice := oak.session.workspace_reset_notice(attached):                   # [OAK helper]
        messages.append(oak.session.Message("system", notice))
    messages.extend(my_memory_recall_blocks(attached))                           # [USER]
    messages.extend(oak.session.messages_from_session(attached))                 # [OAK helper]

    session = oak.session.openhands.build_session(                               # [OAK]
        attached,
        agent=Agent(...),
        initial_messages=messages,
        callbacks=[my_event_adapter],                                            # [USER] forwarded to LocalConversation(callbacks=...)
    )
    result = await session.run_turn(text)
```

#### Wrapper class - `OpenHandsSession`

Composition over inheritance. Holds upstream `LocalConversation` as `.conv`; provides async methods and result extraction; exposes upstream for escape-hatch access.

```python
class OpenHandsSession:
    def __init__(self, conv: LocalConversation):
        self.conv = conv                # [FRAMEWORK] underlying upstream OH, always accessible

    async def run_turn(self, text: str) -> TurnResult:
        """[OAK] sends user message, drives one turn non-blocking."""
        self.conv.send_message(text)
        await asyncio.to_thread(self.conv.run)
        return self._result()

    async def approve(self) -> TurnResult:
        """[OAK] continue after WAITING_FOR_CONFIRMATION."""
        await asyncio.to_thread(self.conv.run)
        return self._result()

    async def reject(self, reason: str) -> TurnResult:
        """[OAK] reject pending actions; agent replans."""
        self.conv.reject_pending_actions(reason)
        await asyncio.to_thread(self.conv.run)
        return self._result()

    @property
    def execution_status(self): return self.conv.state.execution_status
    @property
    def pending_actions(self): return ConversationState.get_unmatched_actions(self.conv.state.events)
```

**Why composition over inheritance.** The old fork's `AsyncLocalConversation` extended `LocalConversation`. That couples to upstream's internal class hierarchy. Composition (`.conv` member) only depends on upstream's public method signatures, which evolve more carefully.

#### Low-level - direct upstream usage (Tier 3 escape)

```python
# [USER] full control; oak provides only the workspace adapter
async with oak.session.attach(session_id, workspace_factory=...) as attached:
    conv = LocalConversation(                                                    # [FRAMEWORK direct]
        agent=...,
        workspace=oak.session.openhands.WorkspaceAdapter(attached.workspace),    # [OAK adapter]
    )
    conv.send_message(text)
    await asyncio.to_thread(conv.run)
```

## Three-tier pluggability - applied

| Concern | Tier 1 (backend plug) | Tier 2 (behavior knob) | Tier 3 (full custom) |
|---|---|---|---|
| State persistence | `state_store: SessionStateStore` | - | direct `state_store.put/get` outside attach |
| History source | `trace: TraceSource` | - | mutate `attached.state.messages` directly |
| Cross-process ownership | `lease: LeaseManager \| None` | `wait_for_lease: bool\|float` | direct `attached.lease` access |
| Workspace lifecycle | `workspace_factory: Callable` | `on_workspace_lost`, `exit_workspace` | direct `attached.workspace` mutation |
| Context composition | - | `system_prompt`, `include_notices` (in per-framework `attach`) | `context_composer: Callable[[AttachedSession], list[Message]]` |
| Session wrapper | - | - | `session_class: Type[OpenHandsSession]` subclass injection |
| Per-Event hooks | - | `callbacks: list[Callable[[Event], None]]` (forwarded to `LocalConversation`) | direct `conv.callbacks.append(...)` on `session.conv` |
| Reconstruction | `reconstructor: Callable` (advanced) | - | pass `attached.state` to user's own logic |
| Notice text | `oak.session.configure(notice_text={"workspace_reset": "your text"})` | - | don't call oak's helpers; write your own |

## Error handling matrix

| Failure | Severity | Default behavior | Override |
|---|---|---|---|
| Workspace GC'd by provider TTL (reconnect fails) | Soft | `on_workspace_lost="skip"` → `attached.workspace = None` | `on_workspace_lost="boot_fresh"` to auto-boot via factory; `"raise"` to fail loud |
| No prior workspace (first-time session) | Expected | `attached.workspace = None`, status="no_prior" | provide `workspace_factory` to boot fresh |
| Trace backend down | Soft | `attached.state.messages = []`, `trace_status="unavailable"` | caller checks status; raises HTTP 503 or proceeds with empty history |
| Trace partial (still indexing) | Soft | `attached.state.messages = [available]`, `trace_status="partial"` | caller decides |
| State store down | Soft | proceed as `no_prior` | log warning; user handles |
| Lease held by live owner | Hard (default) | raise `LeaseHeld` | `wait_for_lease=N` to wait; `force_reclaim=True` to override |
| Session already ended | Hard | raise `SessionEnded` | - (not overridable) |
| Workspace reconnect raises | Soft | per `on_workspace_lost` | as above |

Every status field is observable. No silent surprises.

## Quickstart

```python
# [USER] one-time setup at process startup
oak.session.configure(
    state_store=oak.session.RedisStateStore(redis=redis_client),
    trace=oak.session.StasoTraceSource(api_key=os.environ["STASO_API_KEY"]),
    lease=oak.session.RedisLease(redis=redis_client),
)

# [USER] per-request handler
async def handle_user_message(session_id: str, user_text: str):
    async with oak.session.openhands.attach(
        session_id,
        agent=Agent(                                                # [USER + FRAMEWORK]
            llm=llm,
            tools=tools,
            system_message="<your system prompt>",
        ),
        system_prompt="<your system prompt>",                    # [USER]
        workspace_factory=lambda: oak.workspace.create("e2b"),
        on_workspace_lost="boot_fresh",
    ) as session:
        # [OAK wrapper] drives upstream LocalConversation non-blocking under the hood
        result = await session.run_turn(user_text)

        if result.status == "waiting_for_confirmation":
            # [USER] product UI loop for approval
            if await get_user_decision():
                result = await session.approve()
            else:
                result = await session.reject("user declined")

        is_done = result.status == "finished"

    if is_done:
        await oak.session.end(session_id)
```

## Dependencies

```toml
[project]
name = "oak-session"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "anyio>=4.3",
    "oak-workspace>=0.1.0",
    "opentelemetry-api>=1.27",
]

[project.optional-dependencies]
redis = ["redis>=5.0"]
postgres = ["asyncpg>=0.29"]
staso = ["staso>=X.Y"]
langfuse = ["langfuse>=2.0"]
phoenix = ["arize-phoenix-client>=1.0"]
logfire = ["logfire>=2.0"]
openhands = ["openhands-sdk>=1.0"]
all = ["oak-session[redis,postgres,staso,langfuse,phoenix,logfire,openhands]"]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "mypy>=1.10", "ruff>=0.5"]
```

## Tests

- Contract tests for each Protocol (state_store, trace_source, lease) - runnable against any user-supplied backend
- Reference-impl unit tests for InMemory backends (no external deps)
- Integration tests for Redis backend (skip unless `REDIS_URL` is set)
- Per-framework wrapper tests (skip unless framework SDK is installed)

## Open risks

- **OpenHands API surface evolution** - composition reduces brittleness but doesn't eliminate it; CI runs against OH latest weekly
- **OTel `gen_ai.*` semconv evolution** - semconv is in active development; oak pins a snapshot and ships migration helpers when major changes land
- **Staso SDK query endpoint dependency** - `StasoTraceSource` requires the Staso SDK to grow query methods; documented as a dependency, not blocking other adapters
