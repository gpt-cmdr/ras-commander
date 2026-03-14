# .claude/ - Claude Framework Configuration

This directory contains Claude Code's memory, skills, agents, and rules configuration.

## Structure

- **`MANIFEST.md`** - Central registry mapping all components by domain (read this for cross-references)
- **`rules/`** - Topic-specific guidance (auto-loaded by Claude based on working directory)
- **`skills/`** - Library workflow skills (discovered dynamically by trigger keywords)
- **`agents/`** - Specialist agent definitions (delegated to by orchestrator)
- **`commands/`** - Slash commands for common workflows

## Voice Convention

All documentation in this directory uses **imperative agent-instructable voice**:
- Write "When the user asks X, use Y" not "This module provides Y"
- Write "Use `RasCmdr.compute_plan()`" not "The RasCmdr class provides compute_plan()"
- Write "Read this file when..." not "This file contains..."

## Cross-References Convention

Every skill, agent, rule, and command includes a `## Cross-References` section mapping related components across directories. Use `.claude/MANIFEST.md` as the source of truth for all relationships.

## How It Works

### Hierarchical Context Loading

Claude Code automatically loads context based on working directory:

```
When working in: ras_commander/remote/

Automatic context loading:
1. /CLAUDE.md (root - strategic vision)
2. /ras_commander/CLAUDE.md (library - tactical patterns)
3. /ras_commander/remote/CLAUDE.md (subpackage - implementation details)
4. /.claude/rules/** (all relevant rules files, scoped by paths: frontmatter)
```

### Rules (Auto-Loaded)

Rules in `.claude/rules/` auto-load when relevant. Organized by topic:

- **`python/`** - Language patterns (static classes, decorators, error handling)
- **`hec-ras/`** - Domain knowledge (execution, geometry, HDF, remote, USGS, DSS, precipitation)
- **`testing/`** - Testing approaches (TDD with real HEC-RAS examples, never mocks)
- **`documentation/`** - Documentation standards (MkDocs, notebooks, hierarchical knowledge)
- **`validation/`** - Validation patterns and severity levels
- **`workflow/`** - Primitive extraction workflow

### Skills (Dynamic Discovery)

Skills in `.claude/skills/` are discovered by trigger keywords in YAML descriptions. Each skill folder contains only `SKILL.md` (200-400 lines, lightweight navigator to primary sources).

### Agents (Explicit Delegation)

Agent definitions in `.claude/agents/` specify specialist agents. The orchestrator delegates to them based on domain. Read `.claude/agents/README.md` for the delegation decision tree.

### Commands (User-Triggered)

Commands in `.claude/commands/` are slash commands users invoke directly (e.g., `/test-notebook`, `/agent-taskclose`).

## Content Guidelines

| Level | Purpose | Size Target | Auto-Loaded? |
|-------|---------|-------------|--------------|
| Root CLAUDE.md | Strategic vision | < 200 lines | Always |
| Subpackage CLAUDE.md | Tactical patterns | < 150 lines | When in directory |
| .claude/rules/*.md | Guidance procedures | 50-200 lines | By path relevance |
| .claude/skills/*/SKILL.md | Workflow navigation | 200-400 lines | When discovered |
| .claude/agents/*.md | Agent definitions | 200-400 lines | When delegated |

## Cross-References

**Key index files**:
- `.claude/MANIFEST.md` -- Central registry of all components by domain
- `.claude/agents/README.md` -- Agent registry, model assignments, delegation tree
- `.claude/skills/README.md` -- Skill catalog and naming conventions
- `.claude/rules/README.md` -- Rule organization and path scoping
