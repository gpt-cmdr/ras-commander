# Hierarchical Knowledge Curator - Reference Documentation

This directory contains detailed reference documentation for the Hierarchical Knowledge Curator subagent. Files here are **loaded on-demand** (0 token cost until explicitly read).

## Contents

### Core References

**current_state_analysis.md** - Repository inventory and health assessment
- 31 documentation files analyzed
- Size distribution and hierarchy structure
- Problem areas identified
- Baseline established: ras-commander has good foundation

**claude_memory_system.md** - Claude Code memory features research
- 4-level hierarchical loading mechanism
- On-demand nested context inheritance
- Modular rules directory patterns
- Path-specific YAML frontmatter
- File import syntax (@imports)

**claude_skills_framework.md** - Skills best practices and patterns
- Progressive disclosure architecture
- Gerund naming convention
- Description optimization for discovery
- Metadata-first loading (name + description only)
- Skills vs CLAUDE.md complementary roles
- Reference files = token-free until read

### Implementation Guides

**implementation-phases.md** - 5-phase implementation roadmap
- Phase 1: Foundation ✅ COMPLETE
- Phase 2: Content migration (root → rules) 🔄 IN PROGRESS
- Phase 3: Create missing CLAUDE.md files
- Phase 4: Define subagents and skills
- Phase 5: Testing and validation

**governance-rules.md** - Decision framework for knowledge organization
- File size governance (60KB warning, 75KB hard limit)
- Content assignment rules (when to create/split/consolidate)
- Hierarchy governance (5-level structure)
- Skills governance (naming, descriptions, locations)
- Subagent governance (model selection, tool permissions)
- Deprecation timeline (AGENTS.md → CLAUDE.md)
- Quality assurance checklist

**research-synthesis.md** - Consolidated findings from 5 research agents
- Agent 1 (ae512db): Inventory and health scan
- Agent 2 (aba6c33): Memory system research
- Agent 3 (afc529a): Skills framework
- Agent 4 (a5b19ed): Librarian agent design
- Agent 5 (a810522): Hierarchy architecture
- Convergent recommendations (100% agreement)
- Success metrics and confidence levels

## How to Use

### As Main Orchestrator

When delegating to hierarchical-knowledge-curator subagent:

```
"Review the current state analysis and identify next priority tasks"
→ Subagent reads reference/current_state_analysis.md

"What are the governance rules for creating a new skill?"
→ Subagent reads reference/governance-rules.md

"Summarize Phase 2 implementation tasks"
→ Subagent reads reference/implementation-phases.md
```

### As Curator Subagent

When working on knowledge organization:

1. **Before creating new documentation**: Read governance-rules.md
2. **When refactoring CLAUDE.md**: Read implementation-phases.md
3. **When creating skills**: Read claude_skills_framework.md
4. **When defining subagents**: Read research-synthesis.md
5. **For health checks**: Read current_state_analysis.md

## Progressive Disclosure Benefits

**Token Efficiency**:
- Main subagent definition: ~10KB (always loaded)
- Reference files: 0 tokens until explicitly read
- Total reference size: ~50KB available on-demand

**Example Savings**:
- Without progressive disclosure: 60KB always loaded
- With progressive disclosure: 10KB default, +50KB optional
- Efficiency gain: 6x reduction in baseline context

## File Size Summary

| File | Lines | Size | Load Mode |
|------|-------|------|-----------|
| ../hierarchical-knowledge-curator.md | ~600 | ~30KB | Always (subagent active) |
| current_state_analysis.md | ~200 | ~10KB | On-demand |
| claude_memory_system.md | ~350 | ~15KB | On-demand |
| claude_skills_framework.md | ~350 | ~15KB | On-demand |
| implementation-phases.md | ~400 | ~18KB | On-demand |
| governance-rules.md | ~450 | ~20KB | On-demand |
| research-synthesis.md | ~450 | ~20KB | On-demand |
| **TOTAL** | **~2,800** | **~128KB** | 30KB default |

## Relationship to feature_dev_notes/

**Original Research** (preserved in feature_dev_notes/):
- MASTER_IMPLEMENTATION_PLAN.md (110KB, complete details)
- ARCHITECTURE_CLARITY.md (mental model diagrams)
- AGENT_RESEARCH_INDEX.md (agent navigation)
- Full agent outputs via TaskOutput

**Consolidated for Curator** (this directory):
- Essential guidance extracted
- Optimized for on-demand loading
- Organized by use case
- Progressive disclosure enabled

**When to use which**:
- Curator references: Day-to-day guidance and decisions
- feature_dev_notes: Historical context and complete research details

## Update Cycle

**Frequency**: As needed during implementation phases

**Trigger for updates**:
- Phase completion (update implementation-phases.md)
- New governance decisions (update governance-rules.md)
- Repository health changes (update current_state_analysis.md)
- Framework evolution (update claude_*.md files)

**Version tracking**: Include date in file headers

---

**Status**: Complete reference library for hierarchical knowledge curator
**Last Updated**: 2025-12-11
**Version**: 1.0
