# Skills - Library Workflow Skills

This directory contains **library workflow skills** - how to use ras-commander for common tasks.

## Skills vs ras_skills/

| Type | Location | Purpose | Example |
|------|----------|---------|---------|
| **Library Skills** | `.claude/skills/` | How to use ras-commander APIs | `executing-hecras-plans` |
| **Domain Skills** | `ras_skills/` | Production automation capabilities | `dss-linker`, `historical-flood-reconstruction` |

Both use Claude Skills framework - the distinction is **scope and distribution**.

## Implemented Library Skills

### Execution Skills
- **executing-hecras-plans** - RasCmdr.compute_plan(), parallel execution, callbacks, mode selection
- **executing-remote-plans** - PsExec, Docker, SSH worker setup, distributed execution
- **executing-hecras-rascontrol** - RasControl COM interface for legacy HEC-RAS 3.x-5.x
- **planning-hecras-execution** - Decision support for execution strategy, mode selection

### Results & Analysis Skills
- **extracting-hecras-results** - HdfResultsPlan API, steady vs unsteady workflows
- **parsing-compute-messages** - HEC-RAS compute message diagnostics, error classification

### File Operations Skills
- **parsing-hecras-geometry** - RasGeometry, RasStruct, fixed-width parsing
- **reading-dss-boundary-data** - RasDss API, HEC-DSS V6/V7 files
- **repairing-geometry-issues** - RasFixit validation loops

### Data Integration Skills
- **integrating-usgs-gauges** - Complete USGS workflow (discovery → validation)
- **analyzing-aorc-precipitation** - AORC grid extraction, time series generation
- **atlas14-spatial-variance** - Atlas 14 precipitation spatial analysis

### Specialized Skills
- **organizing-ebfe-models** - FEMA eBFE/BLE model organization
- **ebfe-validator** - Validate organized eBFE models
- **exploring-hecras-gui** - HEC-RAS GUI exploration and documentation
- **using-git-worktrees** - Git worktree management for feature isolation

### CLI Subagent Skills
- **invoking-codex-cli** - Delegate implementation tasks to Codex CLI (gpt-5.2-codex) via markdown file handoff
- **invoking-gemini-cli** - Delegate QAQC/review tasks to Gemini CLI (gemini-3-pro-preview) via markdown file handoff

## Skill Structure

**CRITICAL: Each skill folder contains ONLY `SKILL.md`**

```
.claude/skills/
├── executing-hecras-plans/
│   └── SKILL.md                    # ONLY file (200-400 lines)
├── integrating-usgs-gauges/
│   └── SKILL.md                    # ONLY file
└── analyzing-aorc-precipitation/
    └── SKILL.md                    # ONLY file
```

**Prohibited in skill folders**:
- ❌ NO `README.md` (duplicates SKILL.md)
- ❌ NO `reference/` folders (skills are navigators, not docs)
- ❌ NO `examples/` folders (examples belong in `examples/` root)
- ❌ NO `scripts/` folders (utilities belong in `ras_commander/` or `tools/`)
- ❌ NO task artifacts (COMPLETION_SUMMARY.md, REFACTORING_NOTES.txt)

**Rationale**: Skills are **lightweight navigators** that point to primary sources:
- Workflows → `ras_commander/{module}/CLAUDE.md`
- API reference → Code docstrings
- Examples → `examples/*.ipynb` notebooks

**File size target**: 200-400 lines per SKILL.md

## Creating Library Skills

1. **Identify workflow**: Multi-step process users frequently need
2. **Create folder**: Use gerund naming (`executing-plans`, not `plan-executor`)
3. **Write SKILL.md**:
   ```yaml
   ---
   name: executing-hecras-plans
   description: |
     Executes HEC-RAS plans using RasCmdr.compute_plan(), handles parallel
     execution across multiple plans, and manages destination folders. Use when
     running HEC-RAS simulations, computing plans, executing models, or setting
     up parallel computation workflows.
   ---

   # Executing HEC-RAS Plans

   ## Quick Start
   [50-line basic example]

   ## Detailed References
   - **compute_plan() API**: See [reference/compute_plan.md](reference/compute_plan.md)
   - **Parallel Execution**: See [reference/parallel.md](reference/parallel.md)
   ```

4. **Add progressive disclosure**: Main SKILL.md < 500 lines, details in reference/
5. **Test discovery**: Verify skill activates with natural language queries

## Key Principles

### Progressive Disclosure
- **Metadata loads first**: ~100 tokens (name + description)
- **Full content when relevant**: <5k tokens (SKILL.md)
- **Reference files on-demand**: 0 tokens until explicitly read

### Discovery Optimization
Write descriptions that include:
- **What it does**: "Executes HEC-RAS plans..."
- **When to use**: "...when running simulations, computing plans..."
- **Trigger terms**: "HEC-RAS", "compute", "parallel", "execute model"

### Content Organization
- **SKILL.md**: Navigation and overview
- **reference/**: Detailed API and patterns
- **examples/**: Complete working demonstrations
- **scripts/**: Executable utilities (run without loading into context!)

## Guidelines

- **One workflow per skill**: Don't combine unrelated operations
- **Clear trigger terms**: Help Claude discover the skill
- **Minimal main file**: Keep SKILL.md concise, link to details
- **Test with real projects**: Validate workflows with actual HEC-RAS models

## See Also

- [Claude Skills Framework Research](../../feature_dev_notes/Hierarchical_Knowledge_Approach/research/claude_skills_framework.md)
- [Domain Skills](../../ras_skills/) - Production automation
- Root CLAUDE.md for repository patterns
