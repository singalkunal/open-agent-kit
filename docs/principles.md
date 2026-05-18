# oak architectural principles

oak ships mechanism. You ship policy.

These nine rules keep the packages useful when users bring their own agent loop, backend choices, tenant model, and session model.

## 1. `session_id: str` is the only universal coupling

Every runtime primitive keys off a session ID string. There is no `OakSession`, `OakContext`, or required event envelope.

| Mechanism | Policy |
|---|---|
| `oak.session.attach(session_id)` | When to attach, when to end |
| `workspace.execute(command)` | Which workspace to use |
| `state_store.put(session_id, ...)` | What to persist |
| `trace_source.fetch_session_spans(session_id)` | Which backend to query |

If your app has parent sessions, child sessions, retries, or short-lived sub-sessions, generate the IDs you need. oak does not make you adopt its object model.

What is explicitly NOT in oak: conversation state, message taxonomy, agent loop, tool registry, prompt templating. Those belong to your framework and your product.

## 2. Small stable cores, explicit escape hatches

Each Protocol should stay small enough that backend authors can implement it without adopting oak internals. Each backend exposes capability flags. Wrappers expose `.underlying` / `.conv` / `.handle` for the raw vendor client.

Use oak for the portable path. Reach into the vendor SDK for the one call oak should not standardize.

Before adding another Protocol method, ask whether a capability flag, kwarg, or `.underlying` call solves the real case.

Today's escape hatches:

| Wrapper | Escape | What it exposes |
|---|---|---|
| `oak.session.openhands.OpenHandsSession` | `.conv` | upstream `LocalConversation` for direct calls |
| `oak.workspace.Workspace` | `.handle` + `.underlying` (where applicable) | provider's raw client / sandbox ID |
| `oak.session.AttachedSession` | `.state`, `.workspace`, `.lease`, `.extra` | direct access; oak doesn't gate them |

## 3. Hooks beat forks

Users should compose primitives and inject handlers at named boundaries. They should not need to subclass core classes or fork oak.

Hooks land only after a concrete use case fixes the signature. Pre-declared hooks age badly.

Current hook-shaped surfaces:

| Module | Surface |
|---|---|
| `oak.session.attach()` | `workspace_factory=` callable for fresh-boot; `on_workspace_lost=` policy |
| `oak.session.openhands.attach()` | `context_composer=` callback for full-customization context assembly; `session_class=` for subclass injection |

## 4. No god objects, no policy

There is no `OakAgent` or `OakRuntime`. No class owns "the agent." No class owns "the loop."

Convenience wrappers are suspect when they combine modules and choose policy. The per-framework `attach()` is convenience but stays opinionated only on assembly mechanics (message ordering, workspace wiring). It never decides domain logic (what to put in the system prompt, when a session is "done," which tools to bind).

## 5. Stable wire formats beat stable APIs

Python APIs can change under SemVer. Wire formats need stronger care.

Long-term promises include:

- OTel `gen_ai.*` semconv attribute names (the canonical span shape)
- `workspace.boot` span attribute schema (`workspace.handle`, `workspace.provider`, `workspace.region`, `workspace.image`)
- State store key namespace (`workspace`, `pending_action`, `oak:*` reserved prefix)
- Protocol method names

Changing one requires a deprecation window, a migration path when data is affected, and a clear release note.

## 6. Capability flags plus entry-point discovery

Adapters declare what they support.

```python
workspace.capabilities.supports_reconnect
workspace.capabilities.supports_snapshot
workspace.capabilities.supports_gpu
```

Callers branch on facts. A capability-gated method raises `CapabilityUnsupported` when the backend cannot do the work.

Community backends register through Python entry points. The core repo does not need every provider adapter.

```toml
[project.entry-points."oak.workspaces"]
daytona = "oak_workspace_daytona:DaytonaWorkspace"

[project.entry-points."oak.session.trace_sources"]
honeycomb = "oak_session_honeycomb:HoneycombTraceSource"

[project.entry-points."oak.session.state_stores"]
dynamodb = "oak_session_dynamodb:DynamoStateStore"
```

## 7. Contract tests are the safety net

Every package with a Protocol ships contract tests. A custom backend that passes them is oak-compatible.

The docstrings in the contract tests are part of the spec. Keep them concrete enough that backend authors know what behavior to match.

## 8. Multi-vendor coexistence is first-class

Multiple backends of the same kind can run in the same process. Two `Workspace` instances on different sandbox providers. Three `TraceSource` adapters across vendors. Per-agent, per-tenant, or per-call-site backend selection is config in user code.

```python
# [USER] - mix providers freely; both supported
ws_prod = oak.workspace.create("e2b", region="us-east-1")
ws_dev  = oak.workspace.create("local")
```

oak does NOT ship federation, fallback chains, or routing. Those compose above the Protocol in user code. If you need a `CompositeMemory` or `FallbackTraceSource`, write 30 lines of Python that wraps two oak backends - oak doesn't ship the composite.

This is the OpenRouter pitch applied to the agent runtime stack: switching costs drop to "swap the adapter argument" so teams actually evaluate alternatives.

## 9. Describe mechanism, not application

Modules are named for what they do, not for any one user's application of them.

| Bad framing | Good framing |
|---|---|
| "Multi-process session ownership" | "Exclusive ownership lease" |
| "Resume Staso SRE agent investigations" | "Rehydrate session-keyed state from any backend" |
| "Sandbox for the SRE agent" | "Sandbox abstraction with reconnect" |

The Staso SRE agent is one user. Others (research agents, code agents, long-running tasks, distributed debugging) apply the same primitives differently. Naming and docs always lead with what the primitive IS. Applications are examples, not definitions.

This is the discipline that keeps oak applicable beyond the initial dogfooder.

## Operating rules

Respond to issues quickly. Review PRs with context. Write changelogs that explain behavior changes. Document when oak is the wrong choice.

When a design choice is unclear, ask one question:

> Does this make oak more useful when the user personalizes it?
