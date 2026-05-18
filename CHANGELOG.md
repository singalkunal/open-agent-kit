# Changelog

All notable changes to oak are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Packages version independently; entries are grouped per release.

## [Unreleased]

## [0.1.0] - first public release

### Added

- **`oak.workspace`** - sandbox abstraction with cross-process reconnect support.
  - `Workspace` Protocol with `execute`, `upload`, `download`, `pause`, `terminate`, `reconnect`, `handle`, `underlying`
  - Capability flags: `supports_reconnect`, `supports_snapshot`, `supports_gpu`, `native_idle_timeout`, `max_idle`
  - Reference backends: `LocalWorkspace` (subprocess), `E2BWorkspace` (via `[e2b]` extra)
  - Module-level `create(provider, **config)` and `reconnect(provider, handle)` with entry-point discovery
  - OTel `workspace.boot` / `workspace.reconnect` span emission with documented attribute schema (`workspace.provider`, `workspace.handle`, `workspace.region`, `workspace.image`)
- **`oak.session`** - session rehydration + per-framework wrappers.
  - `attach(session_id, ...)` async context manager - acquires lease, reconnects workspace, rehydrates state from trace source
  - `end(session_id)` - terminates workspace, clears state, releases lease
  - `configure(state_store, trace, lease)` - process-level setup
  - `AttachedSession` dataclass with diagnostic statuses (`workspace_status`, `trace_status`)
  - Three pluggable Protocols: `SessionStateStore`, `TraceSource`, `LeaseManager` (lease internal-by-default)
  - Reference state stores: `InMemoryStateStore`, `RedisStateStore` (via `[redis]`), `PostgresStateStore` (via `[postgres]`)
  - Reference trace sources: `StasoTraceSource` (via `[staso]`), `LangfuseTraceSource` (via `[langfuse]`), `PhoenixTraceSource` (via `[phoenix]`), `LogfireTraceSource` (via `[logfire]`), `OTLPSpansTraceSource` base class
  - Reference lease impls: `InMemoryLease`, `RedisLease`
  - Context helpers: `Message`, `messages_from_session`, `workspace_reset_notice`, `continuation_prelude`, `partial_history_notice`, `render.for_anthropic`, `render.for_openai`, `render.for_langgraph`
  - `reconstruct_session(spans)` pure function from OTel `gen_ai.*` spans
  - Per-framework wrapper: `oak.session.openhands` - `attach` (high-level), `build_session` (mid-level), `OpenHandsSession` class (composition over inheritance with `.conv` member), `WorkspaceAdapter` (Tier 3 escape)
- **`oak`** - umbrella CLI: `demo` (zero-credentials end-to-end), `init` (starter template), `protocols` (introspect installed Protocols + backends), `version`

### Three-tier pluggability (uniform across modules)

- Tier 1 - Backend plug (Protocol + reference impls + entry-point discovery)
- Tier 2 - Behavior knob (kwarg / config parameter)
- Tier 3 - Full customization (subclass / callback / escape hatch - `session.conv`, `attached.workspace`, `workspace.underlying` always exposed)

### Two new principles encoded

- **Principle 8 - Multi-vendor coexistence is first-class.** Multiple backends of the same kind run in the same process by intent. Routing is user policy. Oak does not ship federation, fallback chains, or routing.
- **Principle 9 - Describe mechanism, not application.** Modules named for what they DO, not for any one user's application of them.

### Breaking changes from pre-1.0 designs

This is the first public release. Earlier internal designs (referenced in some pre-release documentation) shipped a 10-module surface; v0.1 consolidates to **2 public sub-modules + CLI**. The following items are deliberately not shipped:

| Earlier item | Status in v0.1 | What to use instead |
|---|---|---|
| `oak-archive` (JSONL session log) | Cut | OTel `gen_ai.*` spans are the append-only event log via your tracing backend |
| `oak-storage` (durable bytes Protocol) | Cut | Use cloud SDKs directly (`boto3`, `google-cloud-storage`, `obstore`); workspace file I/O uses `Workspace.upload()` / `Workspace.download()` |
| `oak-dev` (local inspector) | Cut | Use your tracing backend's UI (Jaeger, Tempo, Langfuse, Phoenix, Honeycomb) |
| `oak-telemetry` (separate module) | Folded | Per-vendor adapters inside `oak.session.TraceSource` handle both emission setup and query in one adapter |
| `oak-lifetime` (background reconciler) | Cut | Provider-native idle config (e.g., E2B `timeout_ms` on creation) + `oak.session.attach()` exit-handler pause |
| `oak-lease` (top-level module) | Folded | Internal to `oak.session`; configure via `oak.session.configure(lease=...)`; pluggable via `LeaseManager` Protocol |
| `oak-pool` (per-session FIFO) | Cut | WebSocket handlers serialize naturally per session; `asyncio.Queue` is stdlib |
| `oak-dispatch` (durable post-turn) | Cut | Use `streaq`, `arq`, Celery, Inngest, or Temporal for durable post-turn work |
| `oak-middleware` (HarnessMiddleware) | Cut | SDK auto-patching (`patch_*()` from Staso SDK, OpenLLMetry, Logfire, Phoenix) already covers tracing/cost/audit |
| `openhands-agent-sdk-ext` fork | Dropped | Functionality reabsorbed into `oak.session.openhands` as composition-based wrappers over upstream OpenHands classes. `AsyncLocalConversation` no longer exists; use `oak.session.openhands.OpenHandsSession` (composes upstream `LocalConversation` as `.conv` member) |
| `oak-memory` | Cut | Use the memory engine SDK directly (Mem0, Letta, Zep) |
| `oak-tenant` (rate limits + cost caps) | Cut | Use `slowapi`, `fastapi-limiter`, or your own rate limiter |
| Agent loop / `OakAgent` god object | Never | Pick an existing loop: OpenHands, Claude Agent SDK, OpenAI Agents SDK, LangGraph, Mastra, CrewAI |

### Compatibility

- Python 3.11, 3.12
- OS: Linux, macOS (Windows: untested in CI)

---

[Unreleased]: https://github.com/<org>/open-agent-kit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/<org>/open-agent-kit/releases/tag/v0.1.0
