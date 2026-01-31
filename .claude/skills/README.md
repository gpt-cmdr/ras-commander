# Skills - Library Workflow Skills

This directory contains **library workflow skills** - how to use ras-commander for common tasks.

## Naming Convention

**Pattern**: `category_verb_modifier` or `category_verb-compound_modifier`

- **Underscore (`_`)**: separates segments (category, verb, modifier)
- **Hyphen (`-`)**: joins compound words within a segment
- **Verb alignment**: Matches ras-commander API verbs (compute, extract, parse, organize, etc.)

**Categories**:

| Prefix | Domain |
|--------|--------|
| `hecras` | HEC-RAS model operations |
| `precip` | Precipitation data |
| `usgs` | USGS gauge integration |
| `ebfe` | eBFE/BLE FEMA models |
| `dss` | HEC-DSS file operations |
| `dev` | Development tooling |
| `qa` | Quality assurance |

## Skills vs ras_skills/

| Type | Location | Purpose | Example |
|------|----------|---------|---------|
| **Library Skills** | `.claude/skills/` | How to use ras-commander APIs | `hecras_compute_plans` |
| **Domain Skills** | `ras_skills/` | Production automation capabilities | `dss-linker`, `historical-flood-reconstruction` |

Both use Claude Skills framework - the distinction is **scope and distribution**.

## Implemented Library Skills

### HEC-RAS Execution (`hecras_compute_*`, `hecras_plan_*`)
- **hecras_compute_plans** - RasCmdr.compute_plan(), parallel execution, callbacks, mode selection
- **hecras_compute_remote** - PsExec, Docker, SSH worker setup, distributed execution
- **hecras_compute_rascontrol** - RasControl COM interface for legacy HEC-RAS 3.x-5.x
- **hecras_plan_execution** - Decision support for execution strategy, mode selection

### HEC-RAS Results & Parsing (`hecras_extract_*`, `hecras_parse_*`)
- **hecras_extract_results** - HdfResultsPlan API, steady vs unsteady workflows
- **hecras_parse_compute-messages** - HEC-RAS compute message diagnostics, error classification
- **hecras_parse_geometry** - RasGeometry, RasStruct, fixed-width parsing

### HEC-RAS GUI (`hecras_explore_*`)
- **hecras_explore_gui** - HEC-RAS GUI exploration and documentation

### DSS Operations (`dss_*`)
- **dss_read_boundary-data** - RasDss API, HEC-DSS V6/V7 files

### Data Integration (`usgs_*`, `precip_*`)
- **usgs_integrate_gauges** - Complete USGS workflow (discovery -> validation)
- **precip_analyze_aorc** - AORC grid extraction, time series generation
- **precip_analyze_atlas14-variance** - Atlas 14 precipitation spatial analysis

### eBFE/BLE Models (`ebfe_*`)
- **ebfe_organize_models** - FEMA eBFE/BLE model organization
- **ebfe_validate_models** - Validate organized eBFE models

### Quality Assurance (`qa_*`)
- **qa_repair_geometry** - RasFixit validation loops, geometry repair
- **qa_review_triple-model** - Multi-LLM code review (Opus, Gemini, Codex)

### Development Tools (`dev_*`)
- **dev_manage_git-worktrees** - Git worktree management for feature isolation

### CLI Invocation Skills (`dev_invoke_*`)
- **dev_invoke_codex-cli** - Delegate implementation tasks to Codex CLI (gpt-5.2-codex) via markdown file handoff
- **dev_invoke_gemini-cli** - Delegate QAQC/review tasks to Gemini CLI (gemini-3-pro-preview) via markdown file handoff
- **dev_invoke_kimi-cli** - Delegate testing/QA tasks to Opencode CLI with Kimi K2.5 via markdown file handoff

## Skill Structure

**CRITICAL: Each skill folder contains ONLY `SKILL.md`**

```
.claude/skills/
├── hecras_compute_plans/
│   └── SKILL.md                    # ONLY file (200-400 lines)
├── usgs_integrate_gauges/
│   └── SKILL.md                    # ONLY file
└── precip_analyze_aorc/
    └── SKILL.md                    # ONLY file
```

**Prohibited in skill folders**:
- NO `README.md` (duplicates SKILL.md)
- NO `reference/` folders (skills are navigators, not docs)
- NO `examples/` folders (examples belong in `examples/` root)
- NO `scripts/` folders (utilities belong in `ras_commander/` or `tools/`)
- NO task artifacts (COMPLETION_SUMMARY.md, REFACTORING_NOTES.txt)

**Rationale**: Skills are **lightweight navigators** that point to primary sources:
- Workflows -> `ras_commander/{module}/CLAUDE.md`
- API reference -> Code docstrings
- Examples -> `examples/*.ipynb` notebooks

**File size target**: 200-400 lines per SKILL.md

## Creating Library Skills

1. **Identify workflow**: Multi-step process users frequently need
2. **Choose name**: `category_verb_modifier` matching API verbs
3. **Create folder**: `.claude/skills/{name}/`
4. **Write SKILL.md**:
   ```yaml
   ---
   name: hecras_compute_plans
   description: |
     Executes HEC-RAS plans using RasCmdr.compute_plan(), handles parallel
     execution across multiple plans, and manages destination folders. Use when
     running HEC-RAS simulations, computing plans, executing models, or setting
     up parallel computation workflows.
   ---

   # Computing HEC-RAS Plans

   ## Quick Start
   [50-line basic example]

   ## Detailed References
   - **compute_plan() API**: See ras_commander/CLAUDE.md
   ```

5. **Test discovery**: Verify skill activates with natural language queries

## Key Principles

### Progressive Disclosure
- **Metadata loads first**: ~100 tokens (name + description)
- **Full content when relevant**: <5k tokens (SKILL.md)

### Discovery Optimization
Write descriptions that include:
- **What it does**: "Executes HEC-RAS plans..."
- **When to use**: "...when running simulations, computing plans..."
- **Trigger terms**: "HEC-RAS", "compute", "parallel", "execute model"

## Guidelines

- **One workflow per skill**: Don't combine unrelated operations
- **Clear trigger terms**: Help Claude discover the skill
- **Minimal main file**: Keep SKILL.md concise, link to details
- **Test with real projects**: Validate workflows with actual HEC-RAS models

## See Also

- [Claude Skills Framework Research](../../feature_dev_notes/Hierarchical_Knowledge_Approach/research/claude_skills_framework.md)
- [Domain Skills](../../ras_skills/) - Production automation
- Root CLAUDE.md for repository patterns
