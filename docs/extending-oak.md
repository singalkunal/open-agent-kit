# Extending oak

Four extension paths in oak v0.1:

1. **Workspace backend** - add a sandbox provider (Daytona, Modal, Vercel, your own)
2. **Trace-source adapter** - adapt a tracing backend's query API (Honeycomb, Datadog, custom OTLP store)
3. **State-store backend** - wire `SessionStateStore` to a new persistence layer (DynamoDB, MongoDB, your DB)
4. **Per-framework session wrapper** - bridge oak to a new agent framework (Claude Agent SDK, OpenAI Agents SDK, LangGraph, etc.)

All four follow the same shape: implement a small Protocol, pass contract tests, register via entry points if you want auto-discovery.

---

### Recipe A - Workspace backend

Add a new sandbox provider.

#### Steps

1. **Read the Protocol.** Find `oak.workspace.Workspace` in `oak_workspace/protocol.py`. The docstrings spell out method semantics, errors, idempotency, and reconnect contract.

2. **Implement it.** Subclass the Protocol or match the shape (Protocols are structural). Wrap the provider's SDK calls. Set capability flags honestly:
   - `supports_reconnect=True` if the provider has a "reattach to existing sandbox" API
   - `supports_snapshot=True` if it ships filesystem snapshots
   - `native_idle_timeout=True` if the provider auto-pauses/terminates on idle config

3. **Implement `handle` + `reconnect()`.** This is the load-bearing addition for cross-process resume. `handle` returns a serializable dict (no secrets); `reconnect(handle)` reattaches.

4. **Emit the boot span.** On successful create / reconnect, emit OTel `workspace.boot` / `workspace.reconnect` with attributes per the design doc:
   ```python
   span.set_attributes({
       "workspace.provider": "daytona",
       "workspace.handle": json.dumps(self.handle),
       "workspace.region": region,
       "workspace.image": image,
   })
   ```

5. **Run the contract suite.**
   ```bash
   pip install oak-workspace[test]
   python -m pytest oak_workspace.tests.contract --backend oak_workspace_daytona:DaytonaWorkspace
   ```

6. **Register via entry points** so `oak.workspace.create("daytona", ...)` picks it up:
   ```toml
   [project.entry-points."oak.workspaces"]
   daytona = "oak_workspace_daytona:DaytonaWorkspace"
   ```

#### Reference impl to copy from

- `oak_workspace/local.py` (~150 LOC) - minimal subprocess-based backend
- `oak_workspace/e2b.py` (~300 LOC) - full reconnect + capability flags + provider-native timeout

---

### Recipe B - Trace-source adapter

Adapt a tracing backend's query API so `oak.session` can resume a session's history from it.

#### Steps

1. **Read the Protocol.**
   ```python
   class TraceSource(Protocol):
       async def fetch_session_spans(self, session_id: str) -> list[GenAISpan]: ...
   ```

2. **Implement it.** Wrap the vendor's query SDK; translate the vendor's span shape into oak's `GenAISpan` (OTel `gen_ai.*` aligned).

   ```python
   class HoneycombTraceSource:
       def __init__(self, client: HoneycombClient, dataset: str):
           self._client = client
           self._dataset = dataset

       async def fetch_session_spans(self, session_id: str) -> list[GenAISpan]:
           result = await self._client.query(
               dataset=self._dataset,
               filters=[{"column": "session_id", "op": "=", "value": session_id}],
               order_by="start_time",
           )
           return [self._to_genai_span(row) for row in result.rows]

       @staticmethod
       def _to_genai_span(row) -> GenAISpan:
           # Translate vendor's row → oak's GenAISpan
           ...
   ```

3. **(Optional) Add an `install_emission()` method** if the same vendor offers auto-instrumentation. Lets users wire both directions through one adapter:
   ```python
   def install_emission(self):
       """Set up OTel emission to this backend."""
       # vendor-specific emission setup
   ```

4. **Run the contract suite** with a fixture span dataset.

5. **Register via entry points.**
   ```toml
   [project.entry-points."oak.session.trace_sources"]
   honeycomb = "oak_session_honeycomb:HoneycombTraceSource"
   ```

#### Reference impls to copy from

- `oak_session/_trace_sources/staso.py` - full bidirectional (emission + query) adapter
- `oak_session/_trace_sources/langfuse.py` - wraps `langfuse-python` query API
- `oak_session/_trace_sources/otlp.py` - base class for OTLP-collector setups where you provide a query callable

---

### Recipe C - State-store backend

Wire `SessionStateStore` to a new persistence layer (DynamoDB, MongoDB, your existing app DB).

#### Steps

1. **Read the Protocol.**
   ```python
   class SessionStateStore(Protocol):
       async def put(self, session_id: str, key: str, value: dict) -> None: ...
       async def get(self, session_id: str, key: str) -> dict | None: ...
       async def delete_session(self, session_id: str) -> None: ...
   ```

2. **Implement it.** Three methods. Key namespace documented at `oak.session` design (reserved `oak:*` prefix; user keys should avoid that prefix).

3. **Run the contract suite.**
   ```bash
   python -m pytest oak_session.tests.contract.state_store --backend my_pkg:DynamoStateStore
   ```

4. **Register via entry points** if you want string-based dispatch:
   ```toml
   [project.entry-points."oak.session.state_stores"]
   dynamodb = "oak_session_dynamodb:DynamoStateStore"
   ```

#### Reference impls to copy from

- `oak_session/_state_stores/in_memory.py` (~50 LOC) - simplest
- `oak_session/_state_stores/redis.py` (~120 LOC) - production reference
- `oak_session/_state_stores/postgres.py` (~150 LOC) - alternative production backend

---

### Recipe D - Per-framework session wrapper

Add a new agent framework to `oak.session.<framework>`.

This is the largest of the four recipes because each framework has its own primitives (agent loop API, message shape, approval mechanism). But the pattern is uniform.

#### Steps

1. **Pick the namespace.** New sub-module: `oak.session.<framework>` (e.g., `oak.session.claude` for Claude Agent SDK).

2. **Define a session wrapper class** using **composition over inheritance**. Hold the framework's native session/conversation object as a member; provide your own async methods; expose the underlying object via `.underlying` (or framework-natural name) for escape-hatch access.

   ```python
   class ClaudeAgentSession:
       def __init__(self, runner: ClaudeRunner):
           self.runner = runner    # underlying framework object, always accessible

       async def run_turn(self, text: str) -> TurnResult:
           # Drive the framework's turn; handle approval gates if applicable
           ...

       async def approve(self) -> TurnResult: ...
       async def reject(self, reason: str) -> TurnResult: ...
   ```

3. **Define `build_session(attached, ...)`** - the mid-level constructor that takes an `AttachedSession` from `oak.session.attach()`, wires the workspace adapter, seeds initial messages, and returns a `<Framework>Session` wrapper.

4. **Define `attach(session_id, ...)`** - the high-level one-call API that wraps `oak.session.attach()` + assembles context (system_prompt + notices + prior messages) + calls `build_session()`. Most users live here.

5. **Define a `WorkspaceAdapter`** if the framework needs its workspace objects to satisfy a framework-specific type/Protocol. The adapter wraps `oak.workspace.Workspace`.

6. **Document the three tiers** in the package README:
   - High-level: `oak.session.<framework>.attach(...)` - one call
   - Mid-level: `build_session(attached, ...)` + manual context assembly
   - Low-level: `oak.session.attach(...)` + direct upstream framework usage with the workspace adapter

7. **Tests:** integration tests that boot a workspace, drive a turn, hit an approval gate (if applicable), and verify the framework's native run loop completes.

8. **Register via entry points** if you want oak's CLI introspection to list it:
   ```toml
   [project.entry-points."oak.session.frameworks"]
   claude = "oak_session_claude:claude_framework_metadata"
   ```

#### Reference impl to copy from

- `oak.session.openhands` (~250 LOC across `attach`, `build_session`, `OpenHandsSession`, `WorkspaceAdapter`) - the v0.1 reference

#### Key design rule - composition, never inheritance

The old `openhands-agent-sdk-ext` fork's `AsyncLocalConversation` subclassed upstream `LocalConversation`. That coupled the fork to upstream's internal class hierarchy and required maintaining a separate package.

oak's `OpenHandsSession` **holds** upstream `LocalConversation` as `.conv` member. Lives inside oak. Same value, robust to upstream changes.

Apply the same rule to any new framework adapter: hold the framework's native session/conversation as a member; never subclass it.

---

### What oak should provide (contract)

| Promise | Where it's enforced |
|---|---|
| Every Protocol has a docstring spelling out semantics | `oak_<module>/protocol.py` |
| Every module ships a contract test suite | `oak_<module>/tests/contract.py` |
| Capability flags signal honest backend limitations | Documented in each backend's README |
| Breaking changes to Protocols bump major version | SemVer per-module |
| Entry-point discovery works for community backends | `oak protocols` CLI lists installed adapters |

If any of these are missing for a shipped module, file an issue.

---

### When NOT to extend oak

- Your "new backend" is actually a thin wrapper around an existing one with one extra option. File a PR adding the option to the existing backend instead.
- Your "new framework" is a custom loop you wrote in-house. You may not need an adapter at all - duck-type and use `oak.session.attach()` directly + the workspace adapter.
- Your extension contains your product's domain types (event taxonomy, prompt assembly, tool registry). That belongs in your product code, not in an oak extension.
- Your extension would compete with mature tooling. If you want to ship a prompt templater on top of oak: don't. Use LangChain Prompts / Mirascope / DSPy. oak's context helpers are session-aware glue only.
