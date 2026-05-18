## Summary

One or two sentences on what this PR does and why.

## Type of change

- [ ] Bug fix
- [ ] Behavior change on an existing module
- [ ] New backend / framework adapter (Tier 1 plug)
- [ ] New behavior knob (Tier 2)
- [ ] New module (requires prior issue discussion - see CONTRIBUTING.md)
- [ ] Documentation
- [ ] Build / CI / hygiene

## Checklist

- [ ] `uv run pytest packages/` passes
- [ ] `uv run mypy --strict packages/oak-workspace/src/oak_workspace packages/oak-session/src/oak_session packages/oak/src/oak_cli` clean
- [ ] `uv run ruff check` clean
- [ ] Contract tests pass if a Protocol implementation was added or modified
- [ ] Docs updated (relevant `docs/` and package `README.md`)
- [ ] `CHANGELOG.md` entry added under `[Unreleased]`
- [ ] No emojis in code, comments, docstrings, or commit messages
- [ ] No AI-attribution lines in commit messages

## Related issues

Closes #...
Refs #...

## Notes for reviewers

Anything reviewers should pay particular attention to, design decisions worth flagging, etc.
