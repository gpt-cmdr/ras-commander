# Skills - Library Workflow Skills

This directory contains **library workflow skills** - how to use ras-commander for common tasks.

## Skills vs ras_skills/

| Type | Location | Purpose | Example |
|------|----------|---------|---------|
| **Library Skills** | `.claude/skills/` | How to use ras-commander APIs | `executing-hecras-plans` |
| **Domain Skills** | `ras_skills/` | Production automation capabilities | `dss-linker`, `historical-flood-reconstruction` |

Both use Claude Skills framework - the distinction is **scope and distribution**.

## Recommended Library Skills (Phase 3)

### Phase 1: Core Operations
1. **executing-hecras-plans** - RasCmdr.compute_plan(), parallel execution, callbacks
2. **extracting-hecras-results** - HdfResultsPlan API, steady vs unsteady workflows
3. **parsing-hecras-geometry** - RasGeometry, RasStruct, fixed-width parsing

### Phase 2: Advanced Features
4. **integrating-usgs-gauges** - Complete USGS workflow (discovery → validation)
5. **analyzing-aorc-precipitation** - AORC grid extraction, time series generation
6. **repairing-geometry-issues** - RasFixit validation loops

### Phase 3: Specialized
7. **executing-remote-plans** - PsExec, Docker, SSH worker setup
8. **reading-dss-boundary-data** - RasDss API, HEC-DSS V6/V7 files

## Skill Structure

Each skill folder contains:
```
executing-hecras-plans/
├── SKILL.md              # Main instructions with YAML frontmatter
├── reference/
│   ├── compute_plan.md   # Detailed API docs (load on-demand)
│   ├── parallel.md       # Parallel execution details
│   └── callbacks.md      # Real-time monitoring
├── examples/
│   ├── basic.md          # Simple examples
│   └── advanced.md       # Complex workflows
└── scripts/
    ├── validate_plan.py  # Utility scripts (token-free execution!)
    └── setup_workers.py
```

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
