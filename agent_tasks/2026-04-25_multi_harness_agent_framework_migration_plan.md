# Multi-Harness Agent Framework Migration Plan

Date: 2026-04-25

## Goal

Migrate `ras-commander` from a Claude-first instruction model to a shared `AGENTS.md` contract that works cleanly for both Claude Code and Codex, without maintaining duplicated instruction trees.

## Accepted Architecture

- `AGENTS.md` hierarchy is the canonical shared contract.
- `CLAUDE.md` files become thin loaders importing the matching `AGENTS.md`.
- `.claude/rules/` remains Claude-specific preload guidance only.
- `.claude/agents/` remains Claude-native.
- `.claude/MANIFEST.md` remains a Claude registry, not the shared source of truth.
- Codex skill auto-discovery is exposed through a generated local bridge after provider-specific orchestration skills are marked out of the shared corpus and shared-domain skills are explicitly allowlisted.
- Codex-native adapter skills live in `.agents/native-skills/` and are exposed through the same generated bridge. The first adapter is `dev_invoke_claude-code` for read-only Claude Code QAQC reviews.
- Cross-harness hooks use native project config files (`.claude/settings.json` and `.codex/hooks.json`) as thin adapters that call shared Python logic under `scripts/agent_hooks/`.
- Recommended tool guidance is limited to Claude Code, Codex, Codex Browser Use for browser inspection, and official GitHub tooling for issue/PR work.
- External agent-facing tools, plugins, and skills should be written by `gpt-cmdr` or sourced from official Anthropic/OpenAI repositories. Third-party components from outside those sources must be audited and re-implemented here rather than linked as plugin or skill dependencies.

See [docs/development/multi-harness-agent-contract.md](../docs/development/multi-harness-agent-contract.md).

## Inventory Snapshot

Current `.claude/` inventory at migration start:

- 35 Claude agent definitions
- 24 skill directories
- 9 command definitions
- 40 rule files

Key structural issue:

- Root and subtree `AGENTS.md` files currently describe themselves as compatibility wrappers and redirect agents to `CLAUDE.md`.

## Risks To Remove

1. Contradictory loader behavior between Claude and Codex
2. Shared rules living only in `.claude/rules/`
3. Provider-specific orchestration skills inside what should become a shared skill corpus
4. Drift between repo-visible design intent and Claude-internal implementation docs

## Workstreams

### 1. Establish The Durable Record

- [x] Add a formal design record for the shared multi-harness contract
- [x] Add this implementation plan
- [x] Add migration note in developer docs
- [x] Record the explicit recommended-tool policy and exclusions
- [x] Record the external agent-tool supply-chain policy

### 2. Replace Wrapper-Style Root Instructions

- [x] Rewrite root `AGENTS.md` as canonical shared instructions
- [x] Reduce root `CLAUDE.md` to a loader plus Claude-only notes

### 3. Replace Wrapper-Style Subtree Instructions

- [x] Rewrite `ras_commander/AGENTS.md`
- [x] Rewrite `examples/AGENTS.md`
- [x] Rewrite subpackage `AGENTS.md` files for `hdf`, `geom`, `remote`, `dss`, `usgs`, `check`, `fixit`, `precip`, and `gui`
- [x] Reduce all matching subtree `CLAUDE.md` files to loaders

### 4. Add Missing Local Contracts For Common Workdirs

- [x] Add `docs/AGENTS.md`
- [x] Add `tests/AGENTS.md`

### 5. Update Claude-Native Documentation

- [x] Rewrite `.claude/rules/agents-md-bridge.md` to the new contract
- [x] Add migration note to Claude-first best-practice docs
- [x] Update `.claude/README.md` and `.claude/MANIFEST.md` headers so they stop claiming shared canonicality

### 6. Rationalize Shared Skills

- [x] Mark current provider-orchestration skills with `shared_corpus: false` and `harness_scope: claude_only`
- [x] Mark shared-domain skills with explicit bridge allowlist metadata
- [x] Decide which existing `.claude/skills/` entries are currently eligible shared-domain skills
- [x] Introduce a generated no-duplication Codex skill bridge for the shared subset
- [x] Add Codex-native Claude Code QAQC handoff support without creating a copied skill tree
- [x] Add cross-platform hook adapters for Claude Code and Codex backed by shared Python hook logic
- [x] Tighten individual shared-domain skills so they point to `AGENTS.md` instead of old `CLAUDE.md` primary sources

### 7. Validate

- [x] Run `mkdocs build --strict`
- [x] Search for remaining wrapper language that contradicts the new contract
- [x] Review for stale references that still say `CLAUDE.md` is the shared source of truth

## Current Implementation Slice

This worktree implements the instruction-layer migration first:

- shared `AGENTS.md` hierarchy
- loader-style `CLAUDE.md`
- architectural record
- documentation updates

It introduces repo-native Codex skill auto-discovery through generated `.agents/skills/` symlinks or Windows junctions. The generated bridge is ignored by git and filters out Claude-only provider orchestration skills. Shared-domain skills have also been updated to avoid treating `CLAUDE.md` files as primary shared sources.

## Exit Criteria

The migration is complete when all of the following are true:

1. No active `AGENTS.md` file in the repo describes itself as a compatibility wrapper.
2. Shared rules needed by Claude and Codex live in the `AGENTS.md` hierarchy.
3. `CLAUDE.md` files are loader-sized and Claude-specific.
4. Claude-specific docs stop claiming `.claude/` is the shared canonical source.
5. Any future Codex skill exposure path is implemented without copied instruction trees.


