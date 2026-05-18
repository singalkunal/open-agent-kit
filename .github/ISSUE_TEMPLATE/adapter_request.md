---
name: Adapter request
about: I want oak to support a new vendor (sandbox / tracing / state store / framework)
title: ''
labels: adapter
assignees: ''
---

## Which adapter?

- [ ] Workspace backend (new sandbox provider - Daytona, Modal, Vercel, Cloudflare, Runloop, Browserbase, custom)
- [ ] Trace-source adapter (new tracing backend's read API - Honeycomb, Datadog, custom OTLP store)
- [ ] State-store backend (new persistence layer - DynamoDB, MongoDB, your DB)
- [ ] Per-framework session wrapper (new agent framework - Claude Agent SDK, OpenAI Agents SDK, LangGraph, Mastra, CrewAI, custom)

## Vendor / framework

Name + link to docs.

## Production use case

Are you running this vendor / framework in production today? At what scale?

oak's demand-led principle: adapters that ship to core need at least one production use case. Speculative adapters belong in community packages first.

## Willing to contribute?

- [ ] I can implement the adapter (best path - fastest to ship)
- [ ] I can co-author with a maintainer
- [ ] I need someone else to implement it (slowest; only happens when multiple users converge on the same vendor)

## Willing to maintain?

Adapters need ongoing care as upstream vendor APIs evolve. Are you willing to be the maintainer for this adapter for at least 6 months after it ships?

- [ ] Yes, I will maintain
- [ ] I can find a co-maintainer
- [ ] No

## What existing tool falls short

If users today reach this vendor via another tool, what is broken about that path? Why do they need an oak-native adapter?

## Additional context

Links to relevant vendor SDK docs, similar adapters in other ecosystems, etc.
