---
name: Feature request
about: Propose new behavior on an existing oak module
title: ''
labels: enhancement
assignees: ''
---

## Use case

What production problem are you trying to solve? Be specific. "I want my agent to do X but oak makes me do Y because Z."

## What existing solution falls short

What did you try first? Why did it not work?

- Did you try the relevant Tier 2 behavior knob (kwarg / config parameter)?
- Did you try the Tier 3 escape hatch (subclass / callback / direct access to underlying)?
- If you used a workaround, what did it look like?

## Proposed change

What should oak do differently? Be concrete:

- Which module? (oak.workspace / oak.session / CLI)
- What surface changes? (new method, new kwarg, new behavior on existing method)
- How does it interact with the three-tier pluggability model? Is this a Tier 1 (backend), Tier 2 (knob), or Tier 3 (escape hatch) change?

## Is this a backend (Protocol-pluggable) or a new module (demand-gated)?

oak adds new top-level modules only when at least two real users hit the same pain AND no existing OSS tool covers the gap. See [`docs/roadmap_demand_led.md`](../../docs/roadmap_demand_led.md).

- [ ] This is a behavior change to an existing module (low bar)
- [ ] This adds a backend / framework adapter (low bar; can ship as a community package)
- [ ] This proposes a new module (must clear the demand gate)

## Additional context

Links to similar features in other libraries, related issues, examples, etc.
