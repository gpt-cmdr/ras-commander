# RAS Commander API Research

This directory contains research outputs from the `ras-commander-api-expert` subagent and its spawned subagents.

## Purpose

The ras-commander library is large and sprawling - it does NOT fit in a single context window. This directory serves as a coordination point for:

1. **Codebase explorations** - Search results from exploring `ras_commander/`
2. **Example findings** - Patterns extracted from `examples/*.ipynb`
3. **Documentation reviews** - Findings from docs and CLAUDE.md files
4. **Synthesized answers** - Final answers combining multiple sources
5. **Cached references** - Reusable dataframe/API documentation

## Structure

```
ras-commander-api-research/
├── README.md                           # This file
├── dataframe-reference/                # Cached dataframe documentation
│   ├── rasprj-dataframes.md            # RasPrj dataframe columns
│   ├── hdf-return-types.md             # HDF method return types
│   └── usgs-return-types.md            # USGS method return types
├── {date}-{topic}-exploration.md       # Codebase search results
├── {date}-{topic}-examples.md          # Notebook findings
├── {date}-{topic}-docs.md              # Documentation findings
└── {date}-{topic}-synthesis.md         # Final synthesized answer
```

## File Naming Convention

**Pattern**: `{YYYY-MM-DD}-{topic}-{type}.md`

**Types**:
- `exploration` - Raw codebase search results (from Haiku)
- `examples` - Notebook findings (from Haiku)
- `docs` - Documentation findings (from Haiku)
- `deep-analysis` - Complex analysis (from Sonnet)
- `synthesis` - Final answer (from API Expert)
- `reference` - Cached reference documentation

## Workflow

1. **API Expert receives question** from orchestrator
2. **Spawns Haiku subagents** to explore codebase, examples, docs in parallel
3. **Subagents write findings** to this directory
4. **API Expert reads findings** and synthesizes answer
5. **Synthesis written** to `{date}-{topic}-synthesis.md`
6. **File path returned** to orchestrator

## Lifecycle

**Active research**: Current explorations in root of this directory

**Completed research**: Can be moved to `.old/` by cleanup passes, but `dataframe-reference/` should be preserved as it's reusable.

## See Also

- `.claude/agents/ras-commander-api-expert.md` - Agent definition
- `ras_commander/AGENTS.md` - Library API overview
- `examples/AGENTS.md` - Notebook index
