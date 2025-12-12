# ras_agents - Production Agent Reference Data

This directory contains production-ready agent configurations, reference materials, and workflows for specialized ras-commander agents.

## Purpose

`ras_agents/` is the **tracked, organized location** for production agent reference data. Unlike `feature_dev_notes/` (which is gitignored and used for experimentation), content here is:
- **Tracked in git** for version control
- **Organized** following hierarchical knowledge best practices
- **Production-ready** for automated agent operation
- **Documented** with clear navigation to primary sources

## Directory Structure

Each agent follows this pattern:

```
ras_agents/
├── README.md (this file)
├── {agent-name}/
│   ├── AGENT.md           # Agent navigator (200-400 lines)
│   ├── reference/         # Reference materials (if needed)
│   │   ├── README.md      # Reference organization
│   │   └── *.md           # Specific reference docs
│   └── workflows/         # Documented workflows
│       └── *.md
```

## Hierarchical Knowledge Principles

All agents follow these principles (see `.claude/rules/documentation/hierarchical-knowledge-best-practices.md`):

1. **Primary Source Navigation** - AGENT.md points to authoritative sources
2. **Single Source of Truth** - Each concept documented in ONE location
3. **Lightweight Navigators** - AGENT.md is 200-400 lines (navigates, doesn't duplicate)
4. **Progressive Disclosure** - Use pointers, not duplication

### Exceptions

**reference/ folders are acceptable when**:
1. Content cannot exist elsewhere (e.g., decompiled assembly findings)
2. Caching external documentation (e.g., API reference to avoid rate limits)
3. Meta-knowledge about the agent system itself

See hierarchical-knowledge-best-practices.md Section 5 for documented exceptions.

## Current Agents

### decompilation-agent
**Purpose**: Decompile .NET assemblies to understand HEC-RAS proprietary algorithms

**Use Cases**:
- Reverse-engineer RASMapper interpolation methods
- Extract HEC-RAS computation logic
- Create Python implementations of proprietary algorithms

**Reference**: See `decompilation-agent/AGENT.md`

## Relationship to Other Directories

### vs. .claude/subagents/
**.claude/subagents/** - General-purpose Claude Code subagents (HDF analyst, geometry parser, etc.)
**ras_agents/** - Specialized ras-commander domain agents (decompilation, model updating, etc.)

### vs. .claude/skills/
**.claude/skills/** - Reusable workflows (executing plans, parsing geometry, etc.)
**ras_agents/** - Complete agent configurations with domain-specific reference data

### vs. feature_dev_notes/
**feature_dev_notes/** - Gitignored experimentation and development space (unorganized)
**ras_agents/** - Production-ready, tracked agent reference data (organized)

**Migration Path**: When feature_dev_notes/ agents are ready for production, migrate to ras_agents/ following hierarchical knowledge principles.

### vs. ras_skills/
**ras_skills/** - Production domain skills (Phase 3+, future)
**ras_agents/** - Complete agent workflows and reference materials

## Adding New Agents

When adding a new agent:

1. **Create directory**: `ras_agents/{agent-name}/`
2. **Create AGENT.md** (200-400 lines):
   - YAML frontmatter with trigger-rich description
   - Primary sources section (point to authoritative docs)
   - Quick reference (minimal code patterns)
   - Common workflows (brief with pointers)
   - Critical warnings (if applicable)
3. **Add reference/ only if needed** (see exceptions above)
4. **Update this README** with agent description
5. **Follow hierarchical knowledge best practices**

## See Also

- `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` - Complete guidance
- `.claude/subagents/README.md` - General-purpose subagents
- `.claude/skills/README.md` - Reusable skills
- `feature_dev_notes/` - Experimentation space (gitignored)
