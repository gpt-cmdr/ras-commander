---
description: Standard pattern for creating thin-wrapper AGENTS.md files that bridge Claude Code .claude/ infrastructure with Codex and other agents
paths:
  - "AGENTS.md"
  - "**/AGENTS.md"
---

# AGENTS.md Bridge Standard

## Purpose

- `AGENTS.md` is the compatibility layer for non-Claude agents such as Codex, Gemini CLI, and similar tools.
- Canonical repository guidance stays in `CLAUDE.md` and the canonical agent framework stays under `.claude/`.
- Use `AGENTS.md` to help other agents discover the Claude-managed framework quickly, not to create a second framework.

## Standard Thin-Wrapper Structure

1. Start with a one-line purpose statement.
2. Point to `CLAUDE.md` as the canonical top-level instruction file.
3. Point to `.claude/MANIFEST.md` as the component registry when it exists.
4. List the key framework paths: `.claude/rules/`, `.claude/agents/`, `.claude/skills/`, `.claude/commands/`.
5. Add a short project-specific quick-start: environment setup, key entry points, working directory conventions.
6. Include a `Cross-Loading Contract` that says: read `AGENTS.md`, then `CLAUDE.md`, then `MANIFEST.md`, then only the relevant `.claude/` files.

## What Not To Put In AGENTS.md

- Do not duplicate `.claude/rules/` content.
- Do not create tool-specific parallel frameworks such as separate Codex-only instruction hierarchies unless explicitly requested.
- Do not turn `AGENTS.md` into a long tutorial or operations manual.
- Do not maintain competing top-level instructions that can drift away from `CLAUDE.md`.

## Subdirectory AGENTS.md Files

- Subdirectory `AGENTS.md` files should also be thin wrappers.
- They should point to the nearest relevant `CLAUDE.md` file for that subtree.
- They may add only local entry points, local workflows, or local directory conventions that a sub-agent needs immediately.

## Worktree Pattern

- Git worktrees inherit the parent repository `AGENTS.md` by default.
- A worktree may add a small local wrapper if it needs branch-specific paths, outputs, or temporary context.
- Worktree wrappers should still point back to the parent `CLAUDE.md` and `.claude/` sources rather than copying framework content.

## When To Create AGENTS.md

- Any project with active Claude Code sessions should also have `AGENTS.md`.
- Add it when bootstrapping `.claude/` in a new repository.
- Add it when creating a Claude-managed analysis workspace or sub-workspace that non-Claude agents will also enter.

## Template: Thin-Wrapper AGENTS.md for CLB Projects

```markdown
## Template: Thin-Wrapper AGENTS.md for CLB Projects

---
**Purpose**: Thin compatibility wrapper - canonical guidance lives in `CLAUDE.md` and `.claude/`.

**Read First**
- `CLAUDE.md` - canonical top-level instructions
- `.claude/MANIFEST.md` - component registry (rules, agents, skills, commands)

**Claude Infrastructure** (load only what's relevant to current task)
- `.claude/rules/` - auto-loaded topic rules
- `.claude/agents/` - specialist subagent definitions
- `.claude/skills/` - domain workflow skills
- `.claude/commands/` - slash command definitions

**[Project-Specific Quick Start]**
- [Environment setup]
- [Key entry points]
- [Working directory conventions]

**Cross-Loading Contract**
1. Read this AGENTS.md
2. Read CLAUDE.md
3. Consult .claude/MANIFEST.md for component discovery
4. Load only relevant .claude/ files for the current task
---
```

## Maintenance Rules

- Keep new project `AGENTS.md` files short; thin wrappers should usually stay under 100 lines.
- If a project does not yet have `.claude/MANIFEST.md`, point to the existing `.claude/` paths directly and say so explicitly.
- When framework paths change, update `AGENTS.md` pointers instead of copying content into the wrapper.
- The compatibility contract is stable: `AGENTS.md` redirects, `CLAUDE.md` instructs, `.claude/` provides the detailed components.
