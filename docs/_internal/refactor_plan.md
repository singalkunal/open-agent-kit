# oak - final v0.1 refactor plan

The canonical plan after the design session that produced this redesign. Supersedes prior versions of this file and obsoletes most other design docs (deletion list below).

## Mission

> **oak is the production runtime toolkit for agents. Reconnect-capable sandbox abstraction, cross-process session rehydration, and per-framework session wrappers. Framework-neutral, multi-vendor, escape-hatched everywhere.**

The OpenRouter pitch applied to the agent runtime stack: make the cost of swapping any infrastructure choice (sandbox, tracing backend, state backend, memory engine, agent framework) drop from days to minutes.

## Tagline

**"Production runtime toolkit for agents."**

"Runtime" scopes oak away from build-time tools (prompt engineering, eval), test-time tools (simulation, regression), and observability *platforms* (Staso / Langfuse / Phoenix). oak is the layer where agents actually execute - the OSS counterpart to AWS Bedrock AgentCore.

The earlier "runtime primitives for autonomous agents" framing is dropped from public surfaces. "Primitives" stays only as internal technical vocabulary.

## Final v0.1 module list

```
oak.workspace                    sandbox abstraction (multi-provider, reconnect-capable)
oak.session                      session rehydration + per-framework wrappers
oak                              CLI: demo, init, protocols, version
```

**Two public sub-modules + CLI.** Everything else either cut, deferred, or folded into these two.

### What lives inside `oak.workspace`

```
oak.workspace
  Workspace                       Protocol - execute / pause / terminate / reconnect / handle / capabilities
  WorkspaceCapabilities           supports_reconnect, supports_snapshot, supports_gpu, max_idle
  create(provider, **config)      provider="local" | "e2b" | ... (string dispatch)
  reconnect(provider, handle)     reconnect to a paused/preserved sandbox
  LocalWorkspace                  subprocess-based, no isolation
  E2BWorkspace                    E2B sandbox (via [e2b] extra)
  errors                          WorkspaceError, CapabilityUnsupported, WorkspaceTerminated, WorkspaceTimeout
```

Provider-native lifetime config (idle timeout, max lifetime) passes through to the underlying SDK at create time. No oak-side background timer or reconciler. No separate `oak.lifetime` module.

### What lives inside `oak.session`

```
oak.session
  ── core (framework-neutral) ──────────────────────────────────────
  configure(state_store, trace, lease)       process-level setup
  attach(session_id, ...)                     async context - rehydrate + acquire lease
  end(session_id)                             terminate workspace + clear state
  AttachedSession                             dataclass: lease, workspace, state, statuses
  SessionState                                dataclass: messages, tool_history, pending_action
  Message                                     framework-agnostic typed message
  
  ── pluggable backends (Protocols) ───────────────────────────────
  SessionStateStore                           put / get / delete_session
  TraceSource                                 fetch_session_spans
  LeaseManager                                acquire / renew / release  (internal-by-default)
  
  ── reference backends ───────────────────────────────────────────
  InMemoryStateStore, RedisStateStore         [redis] extra
  PostgresStateStore                          [postgres] extra
  StasoTraceSource, LangfuseTraceSource       per-vendor [staso] [langfuse] extras
  PhoenixTraceSource, LogfireTraceSource      per-vendor extras
  OTLPSpansTraceSource                        base class; user provides query callable
  InMemoryLease, RedisLease                   internal default + [redis] extra
  
  ── context helpers (stateless functions) ────────────────────────
  messages_from_session(attached)             extract prior messages
  workspace_reset_notice(attached)            notice string or None
  continuation_prelude(attached)              notice string or None
  partial_history_notice(attached)            notice string or None
  render.for_anthropic(messages)              framework-shape rendering
  render.for_openai(messages)
  render.for_langgraph(messages)
  
  ── per-framework attach + wrapper classes ───────────────────────
  openhands.attach(session_id, agent, system_prompt, ...)
                                              high-level: one call returns ready OpenHandsSession
  openhands.build_session(attached, agent, initial_messages, ...)
                                              mid-level: assemble messages yourself
  openhands.OpenHandsSession                  wrapper class (composes upstream LocalConversation)
  openhands.WorkspaceAdapter                  for direct upstream usage (Tier 3 escape)
  
  # same shape across frameworks as they're added:
  # claude.attach / claude.ClaudeAgentSession
  # openai.attach / openai.OpenAIAgentSession
  # langgraph.attach / langgraph.LangGraphSession
```

Lease lives **inside** `oak.session` as internal plumbing (`_lease.py`). Configured via `oak.session.configure(lease=...)`; nullable. Not a public top-level module.

Trace source adapters do **both directions** of the vendor relationship: emission setup (calls vendor's auto-instrument like `patch_openai`) AND span querying. One adapter per vendor. No separate `oak.telemetry` module.

## What's cut, deferred, or absorbed

| Earlier item | Final disposition |
|---|---|
| `oak-storage` | **Cut.** No consumer. Workspace.fs bridge is speculative; archive is cut. |
| `oak-archive` (JSONL session log) | **Cut.** OTel spans ARE the append-only event log via the user's chosen tracing backend. |
| `oak-dev` (inspector) | **Cut.** Duplicates mature OTel UIs (Jaeger / Tempo / Langfuse / Phoenix). |
| `oak-telemetry` (separate module) | **Absorbed into `oak.session` trace-source adapters.** Per-vendor adapter handles both emission setup and query. No standalone module. |
| `oak-lifetime` (background reconciler) | **Cut.** Provider's native idle-timeout config (e.g., E2B `timeoutMs`) + `oak.session.attach()` exit-handler pause covers it. No oak-side timer. |
| `oak-lease` (separate module) | **Absorbed into `oak.session` as internal plumbing.** Configurable via `oak.session.configure(lease=...)`. |
| `oak-pool` (per-session FIFO) | **Cut.** WebSocket handlers serialize naturally per session; cross-trigger case is speculative. |
| `oak-dispatch` (durable post-turn) | **Cut.** With archive gone, no v1 use case. `asyncio.create_task` covers local needs; streaq/Celery for durable. |
| `oak-tenant` (rate limits + cost caps) | **Deferred with design doc.** Real V2 concern; ships when a second user beyond initial cohort asks. |
| `oak-memory` | **Deferred with design doc.** No concrete v1 user demand independent of dogfooding. Lands when a real user pulls it. |
| `oak-middleware` (HarnessMiddleware) | **Cut.** SDK auto-patching (Staso SDK, Logfire, Phoenix, OpenLLMetry) covers tracing/cost/audit per-vendor. PydanticAI shipped a Hooks-API equivalent but the use cases don't currently warrant oak owning this. |
| `openhands-agent-sdk-ext` fork | **Dropped.** Functionality reabsorbed into `oak.session.openhands` as composition-based wrappers (not subclasses) over upstream OH classes. The fork repo ceases to exist. |
| `oak-tool-plane` (multi-projection tool registry) | **Not in scope.** Staso-internal product code per v_20.3 §2.6. Extract to OSS later if it proves general. |
| Agent loop / god object / `OakAgent` | **Never.** Five mature loops exist (OH, Claude Agent SDK, OpenAI Agents SDK, LangGraph, Mastra). |

## Three-tier pluggability model - applied uniformly

Every public oak object exposes three extension tiers:

| Tier | Mechanism | Use case |
|---|---|---|
| **1 - Backend plug** | Protocol + reference impls + entry-point discovery | Swap implementations (Redis ↔ Postgres state store, E2B ↔ Daytona workspace, etc.) |
| **2 - Behavior knob** | kwarg / config parameter | Tune defaults (on_workspace_lost policy, exit_workspace action, include_notices, lease TTL) |
| **3 - Full customization** | Subclass / callback / escape hatch | Override entirely; `session.conv` / `attached.workspace` always exposed for direct upstream access |

**Anti-patterns explicitly avoided:**

- Pre-shipping speculative hooks "just in case" - hooks land when a concrete use case fixes the signature
- Magic defaults - every knob surfaces explicitly in the signature; nothing hidden
- Hiding upstream - escape hatches always present (`session.conv`, `attached.state`, `workspace.underlying`)
- Forks - composition over inheritance; subclass injection (`session_class=`) for user-side customization without separate packages

## Multi-vendor coexistence as a first-class principle

Multiple backends of the same kind can run in the same process. Two `Workspace` instances on different sandbox providers. Three `TraceSource` adapters writing/reading from different vendors. Per-agent or per-tenant backend selection is a config decision in user code, not a fork-the-architecture decision.

Oak does NOT ship federation, fallback chains, or routing - those compose above the Protocol in user code. Oak ships the primitives; the user composes the policy.

## Order of operations

### Phase 1 - code refactor

1. Delete `oak-storage`, `oak-archive`, `oak-dev`, `oak-lease` (top-level package - folds into `oak.session`)
2. Build `oak.session` as a single package:
   - Core: `configure()`, `attach()`, `end()`, `AttachedSession`, `SessionState`, `Message`
   - Internal: `_lease.py` (was `oak-lease`)
   - Protocols: `SessionStateStore`, `TraceSource`
   - Reference backends: `InMemoryStateStore`, `RedisStateStore[redis]`, `PostgresStateStore[postgres]`
   - Trace-source adapters: `StasoTraceSource[staso]`, `LangfuseTraceSource[langfuse]`, `PhoenixTraceSource[phoenix]`, `LogfireTraceSource[logfire]`, `OTLPSpansTraceSource` base
   - Context helpers: `messages_from_session`, `*_notice`, `render.for_*`
   - Per-framework: `openhands.{attach, build_session, OpenHandsSession, WorkspaceAdapter}` first; others as community/follow-up
3. Update `oak.workspace`:
   - Add `Workspace.reconnect()` classmethod + `handle` property
   - Add `supports_reconnect` capability flag
   - Document `workspace.boot` OTel span attribute convention (provider, handle, region, image)
   - Remove `LifetimeWorkspaceAdapter` (was carrying the cut `oak-lifetime` shape)
4. Update `oak` CLI:
   - Drop `dev` subcommand
   - Simplify `demo` to use new attach/end shape
   - `protocols` reflects new module layout
5. Update every remaining package's `pyproject.toml`

### Phase 2 - docs refresh

1. Update `docs/principles.md`:
   - Add: **"Multi-vendor coexistence is first-class"** (multiple backends of the same kind in one process; routing is user policy)
   - Add: **"Describe mechanism, not application"** (modules named for what they do, not for one user's use of them)
   - Existing 7 principles stay
2. Rewrite `docs/architecture.md`:
   - Module map: 2 public sub-modules (workspace, session) + CLI
   - Layered stack diagram
   - "When NOT to use oak" section
3. Delete obsolete design docs (see list below)
4. Write `docs/design/session.md` - load-bearing module's design doc (attach/end, state store, trace source, lease internals, context helpers, per-framework wrappers, three-tier pluggability)
5. Update `docs/design/workspace.md` - reconnect contract, capability flags, provider-native lifetime config
6. Refresh `docs/roadmap_demand_led.md` - current deferred list (memory, tenant, pool, dispatch, middleware)
7. Refresh `docs/extending-oak.md` - recipes per the new shape: state-store backend, trace-source adapter, workspace provider, framework adapter

### Phase 3 - README + onboarding

1. Rewrite `README.md`:
   - Tagline: "Production toolkit for agents"
   - Code-first opener showing `oak.session.openhands.attach()` flow with ownership markers
   - 2-module surface table
   - "What oak is / is not"
   - Cut/deferred list (so readers don't ask "where's archive / lifetime / memory")
2. Update CLI starter template
3. Add `docs/configuration.md` covering the three-layer config approach (env vars → programmatic → eventual YAML)

### Phase 4 - OSS hygiene

1. Add CONTRIBUTING.md, CODE_OF_CONDUCT.md, CHANGELOG.md, SECURITY.md
2. Add GitHub issue / PR templates
3. Add CI workflow (lint + mypy strict + pytest)
4. Configure branch protection

### Phase 5 - release prep

1. Bump versions to 0.1.0
2. Verify PyPI names available
3. Dry-run wheel build
4. Tag v0.1.0
5. Publish to PyPI

## Files to delete (Phase 2)

```
docs/design/storage_and_archive.md            (cut: archive + storage gone)
docs/design/dispatch_and_pool.md              (cut: dispatch + pool deferred indefinitely)
docs/design/tenant.md                         (deferred; design moves to roadmap if needed)
docs/design/telemetry.md                      (absorbed into session trace-source adapters)
docs/design/lifecycle_and_lease.md            (lifetime cut; lease internal to session)
docs/design/memory.md                         (move to docs/_internal/deferred/memory.md)
docs/dev_experience.md                        (oak-dev cut)
packages/oak-storage/                         (whole package)
packages/oak-archive/                         (whole package)
packages/oak-dev/                             (whole package)
packages/oak-lease/                           (folds into oak-session)
packages/oak-memory/                          (deferred)
```

## Estimated effort

| Phase | Estimate (single focused engineer) |
|---|---|
| Phase 1 - code | 2-3 days |
| Phase 2 - design docs | 1 day |
| Phase 3 - README + onboarding | 0.5 day |
| Phase 4 - OSS hygiene | 0.5 day |
| Phase 5 - release prep | 0.5 day |
| **Total** | **~5 days** |

Smaller than prior estimates because the module surface shrank significantly (10 modules → 2 + CLI).

## Risk register

| Risk | Mitigation |
|---|---|
| Provider native lifetime config doesn't cover all idle-pause cases | `oak.session.attach()` exit handler pauses explicitly as backstop; document the layering. |
| Trace backend may drop critical info (workspace handle) | State store holds critical handles; trace store holds append-only history only. Two storage shapes for two concerns. |
| Renamed concepts (no fork, no telemetry module, no lifetime) confuse early adopters | CHANGELOG explicitly lists each change with migration note. |
| Staso SDK doesn't yet expose query endpoints needed for `StasoTraceSource` | Document the 3 needed endpoints; hand-write in Staso SDK as parallel work. |
| OpenHands API changes break `oak.session.openhands` wrapper | Composition (not inheritance) reduces brittleness; CI runs against OH latest weekly. |

## What this redesign explicitly does NOT do

- No rebrand. Name stays `oak` / `open-agent-kit`.
- No license change. Apache-2 stays.
- No agent loop, no god objects, no convenience wrappers that hide policy.
- No vendor competition with mature observability tools - oak reads from them, doesn't replace them.
- No standalone `oak-telemetry` module - vendor SDKs + OpenLLMetry already cover one-line emission setup; oak doesn't reinvent.

## When this plan is "done"

A new developer:
- Lands on the GitHub page
- Reads the README in 90 seconds
- Understands what oak is, what it ships (2 modules + CLI), and who it's for
- Runs `pipx run oak demo` and sees a working agent + workspace + session attach
- Reads `docs/architecture.md` in 5 minutes and understands the 2-module model
- Reads `docs/extending-oak.md` and knows how to add a state-store backend, trace-source adapter, workspace provider, or framework adapter
- Reads `docs/design/session.md` and understands attach/end semantics, the three-tier pluggability model, and how the per-framework wrappers compose

That's the bar. Until then, the project isn't shippable as "loved OSS."

---

Generated 2026-05-19. Final consolidation after multi-session redesign converging on:
- The Staso SRE agent's actual requirements (not the premature scaffolding currently shipped)
- The convergent gaps real production-agent builders hit
- The traces-as-append-only-history + state-store-for-critical-handles + lease-for-ownership three-shape model
- Composition over inheritance for all framework integration
- Three-tier pluggability uniformly applied
