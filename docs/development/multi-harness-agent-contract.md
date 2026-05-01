# Multi-Harness Agent Contract

This document records the accepted design for supporting Claude Code and Codex in the same repository without drifting into parallel instruction systems.

## Status

- Accepted on 2026-04-25.
- This document is the architectural record for the migration away from a Claude-first compatibility-wrapper model.

## Decision

The repository uses one shared instruction graph with harness-native entry points:

- `AGENTS.md` hierarchy = canonical shared contract
- `CLAUDE.md` hierarchy = Claude loaders and Claude-only notes
- `.claude/rules/` = Claude preload accelerators only
- `.claude/agents/` = Claude-native delegation roles
- `.claude/MANIFEST.md` = Claude component registry
- `.agents/native-skills/` = Codex-native adapter skill sources
- `.codex/` = Codex-native hook configuration only
- `scripts/agent_hooks/` = shared hook implementation

## Why

Claude Code and Codex have different default discovery behavior:

- Codex automatically reads `AGENTS.md` files.
- Claude Code automatically reads `CLAUDE.md` files and `.claude/` infrastructure.

Trying to make both harnesses share one loader filename does not work. The only durable shared layer is the `AGENTS.md` hierarchy. The only duplication we accept is loader-level duplication such as `CLAUDE.md` importing `AGENTS.md`.

## Design Principles

1. Shared rules live in `AGENTS.md` files, not only in `.claude/rules/`.
2. `CLAUDE.md` files stay small and import the matching `AGENTS.md`.
3. `.claude/rules/` can preload or accelerate Claude behavior, but they do not own shared policy.
4. `.claude/agents/` can stay Claude-native, but they should point back to shared instructions instead of becoming a second knowledge base.
5. No copied instruction trees for Codex.

## File Responsibilities

### Shared Contract

- `AGENTS.md`
- `ras_commander/AGENTS.md`
- `examples/AGENTS.md`
- other subtree `AGENTS.md` files as needed

These files contain the durable shared instructions that both Claude and Codex must follow.

### Claude Adapters

- `CLAUDE.md`
- subtree `CLAUDE.md` files
- `.claude/rules/`
- `.claude/agents/`
- `.claude/commands/`
- `.claude/MANIFEST.md`

These files exist because Claude has native discovery behavior that Codex does not share.

## Explicit Boundaries

### `AGENTS.md`

- Canonical shared source of truth
- Safe place for rules that both Claude and Codex need
- Can be hierarchical and directory-scoped

### `CLAUDE.md`

- Must import the sibling `AGENTS.md`
- May add only Claude-specific notes
- Must not repeat full workflow documentation that also belongs to Codex

### `.claude/rules/`

- Claude auto-load helpers
- Good for path-scoped preload behavior
- Not acceptable as the only home of shared rules

### `.claude/MANIFEST.md`

- Inventory of Claude-native components
- Useful for discovery
- Not the shared source of truth

### Hooks

Hooks are the one place where both harnesses need native config files:

- Claude Code reads project hooks from `.claude/settings.json`.
- Codex reads project hooks from `.codex/hooks.json`, with `.codex/config.toml`
  enabling hook support for the project.

To avoid drift, these files should stay as thin adapters. Shared hook behavior
belongs in `scripts/agent_hooks/`, where it can be implemented once in
cross-platform Python and called by both harnesses.

Hook adapters assume `python` and `git` are available on `PATH`; they avoid
Bash-only or PowerShell-only policy logic.

Initial hook policy:

- inject a short session-start reminder that `AGENTS.md` is the shared contract
- block direct edits to generated `.agents/skills/` bridge entries
- block obviously destructive recursive deletion and hard reset commands

Hooks are guardrails, not a security boundary. Durable policy still belongs in
`AGENTS.md`, code review, and explicit validation.

## Codex Skill Exposure

Codex skill auto-discovery is provided through a generated local bridge.

Reason:

- The current `.claude/skills/` corpus still includes provider-specific orchestration skills.
- The repository is running on Windows with `core.symlinks=false`, so a tracked no-copy mirror into `.agents/skills/` is not safe.
- Generated symlinks or Windows junctions avoid tracked duplicate skill content.

Implication:

- Codex uses the `AGENTS.md` hierarchy immediately.
- Codex can use native skill discovery after running `python scripts/agent_framework/sync_codex_skill_bridge.py`.
- `.agents/skills/*` entries are generated and ignored by git.
- Shared skill sources remain `.claude/skills/`.
- Codex-native provider handoff sources live in `.agents/native-skills/`.
- The bridge is fail-closed: shared skills must be explicitly marked `shared_corpus: true` and `harness_scope: shared`.
- The bridge must also require accepted source and review metadata before exposing a skill to Codex.

### Codex-Native Adapter Skills

Some workflows are not shared domain skills but are still first-class Codex
adapter capabilities. The initial example is `dev_invoke_claude-code`, which
lets Codex invoke Claude Code as an independent read-only QAQC reviewer.

These skills live in `.agents/native-skills/` and are exposed through generated
links in `.agents/skills/`. They must be explicitly marked:

```yaml
shared_corpus: false
harness_scope: codex_only
source_owner: gpt-cmdr
security_review: internal
```

Codex-native adapter skills are allowed because they do not duplicate shared
repo policy. They only describe how Codex should call another supported harness.

## Recommended Tool Policy

Recommended agent tooling must stay specific and first-party or strongly maintained:

- Claude Code is supported through `CLAUDE.md`, `.claude/agents/`, `.claude/skills/`, `.claude/rules/`, and `.claude/commands/`.
- Codex is supported through the `AGENTS.md` hierarchy and the generated `.agents/skills/` bridge.
- Cross-harness QAQC is supported in both directions: Claude can invoke Codex through a Claude-native adapter, and Codex can invoke Claude Code through a Codex-native adapter.
- Codex Browser Use may be recommended for local browser inspection of generated docs or future UI surfaces when it is available in the user's Codex environment.
- GitHub's official CLI or MCP tooling may be recommended for repository issues, pull requests, and release work.

Do not add generic recommendation lists. Do not recommend Gemini, Context7, or a second copied agent-framework tree as part of this repository's standard setup.

## External Tool And Plugin Supply Chain

Agent-facing external tools, plugins, and skills must follow the repository owner's supply-chain policy:

- Prefer components written and maintained by `gpt-cmdr` in this repository or sibling `gpt-cmdr` repositories.
- Official Anthropic or OpenAI repositories are acceptable upstream sources for harness-native plugins, skills, or examples.
- Third-party external plugins or skills from outside `gpt-cmdr`, Anthropic, or OpenAI must be treated as untrusted until reviewed.
- If a third-party component is useful, thoroughly security-audit it and re-implement the needed behavior inside this repository rather than linking to it as an external plugin or skill dependency.
- Do not add repo-standard guidance that asks agents to install opaque third-party agent plugins, skills, MCP servers, or command wrappers.

## Skill Classification Metadata

During the migration, provider-orchestration skills should be marked in frontmatter:

```yaml
shared_corpus: false
harness_scope: claude_only
```

Shared skills must be explicitly allowlisted:

```yaml
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
```

Meaning:

- shared skill exposure must exclude any skill that is not explicitly marked `shared_corpus: true`
- `harness_scope: shared` is required for Codex bridge exposure
- `harness_scope: claude_only` indicates the skill exists to orchestrate Claude-native behavior or Claude-triggered provider delegation
- `harness_scope: codex_only` indicates the skill exists to orchestrate Codex-native behavior or Codex-triggered provider delegation
- absence of these fields means the skill is not eligible for bridge exposure
- accepted `source_owner` values are `gpt-cmdr`, `anthropic`, and `openai`
- accepted `security_review` values are `internal`, `official-upstream`, and `audited-reimplemented`

## Migration Rules

During the transition:

1. Remove any statement that says `AGENTS.md` is only a compatibility shim.
2. Remove any statement that says `CLAUDE.md` is the canonical shared source of truth.
3. Keep `.claude` as Claude-native infrastructure, not the shared contract.
4. Prefer adding new local `AGENTS.md` files in active subtrees instead of stuffing more shared guidance into `.claude/rules/`.

## Invariants

The repository should continue to satisfy these rules:

- A Codex session can follow the repo correctly by reading `AGENTS.md` files only.
- A Claude session can follow the repo correctly by reading `CLAUDE.md`, which imports the same `AGENTS.md` content.
- No shared rule exists only in `.claude/rules/`.
- No new copied instruction hierarchy is introduced for a second harness.
- Shared architectural changes update this record.

## Related Files

- [AGENTS.md](https://github.com/gpt-cmdr/ras-commander/blob/main/AGENTS.md)
- [CLAUDE.md](https://github.com/gpt-cmdr/ras-commander/blob/main/CLAUDE.md)
- [agent_tasks/2026-04-25_multi_harness_agent_framework_migration_plan.md](https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/2026-04-25_multi_harness_agent_framework_migration_plan.md)


