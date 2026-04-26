---
description: Standard pattern for maintaining AGENTS.md as the canonical shared contract and CLAUDE.md as a Claude-only loader
paths:
  - "AGENTS.md"
  - "**/AGENTS.md"
  - "CLAUDE.md"
  - "**/CLAUDE.md"
---

# Multi-Harness Instruction Standard

## Core Rule

- `AGENTS.md` is the canonical shared instruction file for this repository.
- `CLAUDE.md` exists because Claude Code discovers that filename natively.
- The required duplication is loader duplication, not content duplication.

## Required Structure

### `AGENTS.md`

- Put shared rules here.
- Keep the file scoped to the directory it lives in.
- Let parent and child `AGENTS.md` files form the instruction hierarchy.

### `CLAUDE.md`

- Import the sibling `AGENTS.md`.
- Add only Claude-specific notes that Codex does not need.
- Do not rebuild a second full instruction system in `CLAUDE.md`.

## Shared Vs Claude-Only Content

Put content in `AGENTS.md` when:

- Claude and Codex both need it
- it describes repo norms, coding patterns, or directory-local behavior
- it should remain true even if `.claude/` is reorganized

Put content in `.claude/` when:

- it is Claude preload behavior
- it is a Claude-native agent definition
- it is a Claude-native command or registry

## `.claude/rules/`

- `.claude/rules/` is a Claude accelerator layer, not the canonical shared source of truth.
- If a rule matters to Codex too, move it into the `AGENTS.md` hierarchy and keep any `.claude/rules/` copy short and clearly Claude-specific.

## `.claude/MANIFEST.md`

- Treat `.claude/MANIFEST.md` as the Claude component registry.
- Do not tell other harnesses that `.claude/MANIFEST.md` is the canonical repository contract.

## Subdirectory Pattern

- Subdirectory `AGENTS.md` files should be real local contracts, not wrapper redirects.
- Subdirectory `CLAUDE.md` files should import the local `AGENTS.md` and stay small.

## Worktrees

- Worktrees should inherit the same shared instruction graph.
- Do not create a worktree-only instruction hierarchy unless the branch truly needs temporary, local-only context.

## Codex Skills

- Do not create a copied `.agents/skills/` mirror just to satisfy Codex discovery.
- Use `scripts/agent_framework/sync_codex_skill_bridge.py` for Codex skill exposure.
- The bridge must be fail-closed. Shared `.claude/skills/` entries are exposed only when explicitly marked `shared_corpus: true`, `harness_scope: shared`, and approved by source/review metadata.
- Codex-native adapter skills live outside `.claude/` in `.agents/native-skills/`; they require `shared_corpus: false`, `harness_scope: codex_only`, and the same approved source/review metadata before the bridge exposes them.
- Do not bridge third-party skill or plugin sources unless they have been security-audited and re-implemented in this repository.

## Template

```markdown
# Directory Contract

This file is the canonical local instruction file for this directory.

- Parent guidance still applies.
- Shared directory rules live here.
```

```markdown
@AGENTS.md

## Claude Adapter Notes

- Claude-specific preload notes only.
```
