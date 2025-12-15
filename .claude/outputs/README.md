# Subagent Outputs

This directory contains markdown outputs from subagents.

## Purpose

Subagents write their findings, analysis, and results to markdown files here instead of returning raw text. This ensures:

1. **Knowledge Persistence** - Files survive session boundaries
2. **Filterable Results** - Main agent reads only what's needed
3. **Consolidation Path** - Hierarchical knowledge agent can organize
4. **Audit Trail** - All work products are reviewable

## Structure

```
.claude/outputs/
├── README.md                 # This file
├── summaries/                # Consolidated topic summaries
├── hdf-analyst/              # HDF analysis outputs
├── geometry-parser/          # Geometry parsing outputs
├── usgs-integrator/          # USGS integration outputs
├── remote-executor/          # Remote execution outputs
└── {subagent-name}/          # Other subagent outputs
```

## File Naming Convention

**Pattern**: `{date}-{subagent}-{task-description}.md`

**Examples**:
- `2025-12-15-hdf-analyst-breach-results-investigation.md`
- `2025-12-15-geometry-parser-cross-section-audit.md`
- `2025-12-15-usgs-integrator-gauge-discovery-muncie.md`

## Lifecycle

1. **Active**: Current, relevant outputs (in this directory)
2. **Outdated**: Moved to `.old/` by hierarchical knowledge agent
3. **Recommend Delete**: Moved to `.old/recommend_to_delete/`
4. **Deleted**: By user only (never auto-deleted)

## See Also

- `.claude/rules/subagent-output-pattern.md` - Complete pattern documentation
- `.claude/agents/README.md` - Subagent guidelines
- `.claude/agents/hierarchical-knowledge-agent-skill-memory-curator.md` - Curation agent
