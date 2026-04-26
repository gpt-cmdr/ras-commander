---
description: AGENTS-first hierarchy and lightweight navigator pattern for repository agent knowledge
paths:
  - ".claude/agents/**"
  - ".claude/skills/**"
  - ".claude/rules/**"
  - "AGENTS.md"
  - "**/AGENTS.md"
  - "CLAUDE.md"
  - "**/CLAUDE.md"
---

# Hierarchical Knowledge Best Practices

## Current Architecture

This repository uses an AGENTS-first multi-harness instruction graph.

- `AGENTS.md` files are the canonical shared contracts.
- `CLAUDE.md` files are Claude loaders and Claude-only notes.
- `.claude/rules/` files are Claude preload accelerators.
- `.claude/agents/` files are Claude-native delegation roles.
- `.claude/skills/` files are workflow navigators.

Use `docs/development/multi-harness-agent-contract.md` as the durable architectural record when changing this system.

## Single Source Of Truth

Keep each concept in exactly one durable place:

| Concept | Durable Home |
|---------|--------------|
| Shared repository policy | nearest applicable `AGENTS.md` |
| Shared package-local coding rules | package or subpackage `AGENTS.md` |
| Claude-only preload behavior | `.claude/rules/` |
| Claude-only delegation behavior | `.claude/agents/` |
| Workflow trigger and navigation | `.claude/skills/*/SKILL.md` |
| Runnable examples | `examples/*.ipynb` or focused scripts |
| API signatures and exact parameters | source code and docstrings |

Do not make `.claude/rules/`, `.claude/agents/`, or `.claude/skills/` the only home of a rule that Codex must also follow.

## Lightweight Navigator Pattern

Claude-native agents and skills should be lightweight navigators.

They should:

- state when to use the workflow or agent
- point to the relevant `AGENTS.md`, source files, notebooks, and narrowly relevant rules
- keep critical warnings local when missing them would be dangerous
- avoid copied workflow bodies that will diverge

They should not:

- call `CLAUDE.md` the shared source of truth
- cite brittle line-number ranges in `AGENTS.md` files
- maintain separate API references
- copy long workflows from notebooks or source modules
- create hidden reference folders for content that belongs in shared contracts or source docs

## Updating Shared Guidance

When shared behavior changes:

1. Update the nearest relevant `AGENTS.md`.
2. Keep the matching `CLAUDE.md` as a loader.
3. Update Claude rules, agents, or skills only when Claude needs a preload, role, trigger, or workflow navigator.
4. Update `docs/development/multi-harness-agent-contract.md` when the architecture itself changes.

When a workflow changes:

1. Update source code and docstrings.
2. Update runnable examples if behavior changed.
3. Update the relevant `AGENTS.md` if the workflow changes shared agent behavior.
4. Update skills and subagents only with routing text or critical warnings.

## Codex Skill Exposure

Do not copy `.claude/skills/` into `.agents/skills/`.

Use `scripts/agent_framework/sync_codex_skill_bridge.py` to generate the local bridge. A skill is eligible only when its frontmatter explicitly declares:

```yaml
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
```

Third-party skills or plugins must be security-audited and re-implemented in this repository before becoming part of the standard workflow.

## Review Checklist

Before accepting agent-infrastructure changes, verify:

- no active `AGENTS.md` file describes itself as a compatibility wrapper
- no shared rule exists only in `.claude/rules/`
- `CLAUDE.md` files remain loader-sized
- skills exposed through `.agents/skills/` are explicitly allowlisted
- public docs do not recommend generic harness/plugin lists
- generated files are not required for a clean docs build unless generation is part of the build process
