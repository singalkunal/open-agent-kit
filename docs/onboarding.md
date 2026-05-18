# Onboarding

Most readers start in the README. This file is for contributors who need the repo shape and release model.

## First run

```bash
uv sync
uv run pytest
pipx run oak demo
```

The demo uses local backends - `LocalWorkspace`, `InMemoryStateStore` - and prints a small interaction with no external credentials.

## Repo shape

```
packages/
  oak/                # umbrella CLI: demo, init, protocols, version
  oak-workspace/      # Workspace Protocol + Local + E2B backends
  oak-session/        # attach/end + state-store + trace-source + lease (internal)
                      # + per-framework: oak.session.openhands.*
docs/
  architecture.md
  principles.md
  contract_tests.md
  extending-oak.md
  design/
    workspace.md
    session.md
```

Each package owns its own README, source tree, tests, and optional extras.

## Package rule

Install only what you need.

```bash
pip install oak-workspace                      # just the sandbox abstraction
pip install oak-session                        # attach/end + state-store + trace-source + lease
pip install oak                                # CLI + meta extras

# Pluggable backends via extras
pip install "oak-workspace[e2b]"               # + E2BWorkspace
pip install "oak-session[redis,staso,openhands]"   # production-ish setup
```

The `oak` package gives the CLI. Focused packages stay usable on their own.

## Quick mental model

```python
# [USER] one-time process startup
oak.session.configure(
    state_store=oak.session.RedisStateStore(redis=redis_client),
    trace=oak.session.StasoTraceSource(api_key=os.environ["STASO_API_KEY"]),
    lease=oak.session.RedisLease(redis=redis_client),
)

# [USER] per-request
async def handle_turn(session_id: str, user_text: str):
    async with oak.session.openhands.attach(                       # [OAK] orchestrates
        session_id,
        agent=Agent(llm=llm, tools=tools, system_message=prompt),  # [USER + FRAMEWORK]
        system_prompt=prompt,                                       # [USER]
        workspace_factory=lambda: oak.workspace.create("e2b"),
        on_workspace_lost="boot_fresh",
    ) as session:
        result = await session.run_turn(user_text)                  # [OAK wrapper drives OH]
        if result.status == "waiting_for_confirmation":
            result = await (session.approve() if user_approves
                            else session.reject(reason))
        if result.status == "finished":
            await oak.session.end(session_id)
```

The agent loop is the framework's (OpenHands here). oak owns the runtime mechanism around it: workspace abstraction, session rehydration, cross-process ownership.

## Adding a backend or framework adapter

1. Pick the recipe in [`extending-oak.md`](extending-oak.md):
   - Workspace backend (new sandbox provider)
   - Trace-source adapter (new tracing backend's read API)
   - State-store backend (new persistence layer)
   - Per-framework session wrapper (new agent framework)
2. Implement the Protocol.
3. Set capability flags truthfully where applicable.
4. Run the contract suite.
5. Register through the package's entry-point group if the adapter should be auto-discoverable.

## Versioning

Packages version independently. The meta-package pins compatible ranges for users who install everything through `oak`.

Pre-1.0 minor releases may contain breaking API changes with a release note. Wire formats - OTel `gen_ai.*`, `workspace.boot` span attributes, state-store key namespace - get a deprecation window and migration guidance.

## Docs rule

Public docs explain shipped behavior. Each package's README describes what's installable today.
