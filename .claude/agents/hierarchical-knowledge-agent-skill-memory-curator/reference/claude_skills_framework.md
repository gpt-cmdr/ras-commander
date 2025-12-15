# Claude Skills Framework - Research Summary

**Source**: claude-code-guide agent research
**Date**: 2025-12-11
**Agent**: afc529a
**Reference**: https://claude.com/skills

## Executive Summary

Claude Skills are **prompt-based context modifiers** that extend Claude's capabilities through structured markdown with YAML frontmatter. Skills are **model-invoked** (Claude autonomously decides when to use them) and use **progressive disclosure** (metadata loaded at startup, full content only when skill activates).

**Key Insight**: Skills complement AGENTS.md files - AGENTS.md provides persistent project context, Skills provide discoverable workflows.

## How Skills Work

### Internal Mechanism

1. **Metadata Pre-loading**: At startup, only `name` and `description` from SKILL.md frontmatter loaded
2. **Skills List Injection**: `<available_skills>` section added to system prompt (15,000-character budget)
3. **Progressive Disclosure**: Full SKILL.md content read via Bash tool only when Claude selects the skill
4. **Two-Message Injection**:
   - Message 1 (visible): XML metadata showing skill activation
   - Message 2 (hidden): Complete skill prompt with `role: 'user'`, `isMeta: true`

**Token Efficiency**: Skills don't compete with AGENTS.md for system prompt space!

## Naming Best Practices

### Name Field (YAML Frontmatter)

**Format**: `lowercase-with-hyphens-only` (max 64 characters)
**Pattern**: Use **gerund form** (verb + -ing) for activity-based skills

**Good Examples for ras-commander**:
- `executing-hecras-plans` (gerund - covers plan execution)
- `analyzing-aorc-precipitation` (gerund - AORC workflows)
- `integrating-usgs-gauges` (gerund - USGS data integration)
- `parsing-hecras-geometry` (gerund - geometry file operations)
- `repairing-geometry-issues` (gerund - RasFixit workflows)

**Bad Examples**:
- `helper`, `utils`, `tools` (too vague)
- `hecras`, `data`, `files` (too generic)
- `HEC-RAS-Helper` (wrong case)
- `execute_plans` (underscores not allowed)

### Description Field

**Formula**: What it does + When to use it + Key trigger terms

**Excellent Example** (executing HEC-RAS plans):
```yaml
description: |
  Executes HEC-RAS plans using RasCmdr.compute_plan(), handles parallel
  execution across multiple plans, and manages destination folders. Use when
  running HEC-RAS simulations, computing plans, executing models, or setting
  up parallel computation workflows. Handles plan numbers (01-99), destination
  folder setup, geometry preprocessing, and core allocation.
```

**Key Elements**:
- Specificity (file extensions, API names, domain terms)
- Trigger phrases ("when running simulations", "when analyzing results")
- Concrete terms ("plan numbers (01-99)", "HDF files", "gauge data")
- Max 1024 characters

## Skills vs AGENTS.md: Complementary Roles

| Aspect | AGENTS.md | Skills |
|--------|-----------|--------|
| **Purpose** | Persistent project context | Discoverable workflows |
| **Loading** | Always loaded (hierarchical) | On-demand when selected |
| **Content** | API patterns, conventions, structure | Step-by-step processes |
| **Organization** | Reference documentation | Task-oriented workflows |
| **Token Cost** | System prompt space | Context window (when active) |
| **Best For** | "What exists", "How to code" | "How to accomplish task X" |

### Division of Responsibilities for ras-commander

**Keep in AGENTS.md**:
- Class hierarchies and module organization
- Coding style and conventions
- File structure and repository layout
- Quick reference for core APIs
- Environmental setup instructions

**Move to Skills**:
- Complete end-to-end workflows (AORC extraction, USGS integration)
- Multi-step validation loops (RasFixit geometry repair)
- Domain-specific operations with extensive reference data
- Workflows with conditional branching (steady vs unsteady analysis)

## Progressive Disclosure Architecture

**SKILL.md Body Target**: <500 lines (per official best practices)

**When Content Exceeds Target**:

```
executing-hecras-plans/
├── SKILL.md              # Overview + navigation (<500 lines)
├── reference/
│   ├── compute_plan.md   # Detailed API (load on-demand)
│   ├── parallel.md       # Parallel execution details
│   └── callbacks.md      # Real-time monitoring
├── examples/
│   ├── basic.md          # Simple examples
│   └── advanced.md       # Complex workflows
└── scripts/
    ├── validate_plan.py  # Utility (executed, not loaded!)
    └── setup_workers.py
```

**SKILL.md Navigation Pattern**:
```markdown
# Executing HEC-RAS Plans

## Quick Start
[50-line basic example]

## Detailed References
- **compute_plan() API**: See [reference/compute_plan.md](reference/compute_plan.md)
- **Parallel Execution**: See [reference/parallel.md](reference/parallel.md)
- **Real-Time Monitoring**: See [reference/callbacks.md](reference/callbacks.md)

## Examples
[Link to examples/ folder]

## Utility Scripts
[Link to scripts/ folder]
```

**Token Savings**: Reference files have **0 token cost until explicitly read** by Claude!

## Recommended Skill Suite for ras-commander

### Phase 1: Core Operations (3 skills)

**1. executing-hecras-plans**
- RasCmdr.compute_plan(), compute_parallel, compute_test_mode
- Destination folder management, core allocation
- Real-time monitoring with stream_callback
- **Trigger terms**: "run simulation", "execute plan", "compute parallel"

**2. extracting-hecras-results**
- HdfResultsPlan API for steady and unsteady results
- Conditional workflow (steady vs unsteady detection)
- Breach results, hydraulic tables, validation
- **Trigger terms**: "extract results", "HDF file", "water surface elevation", "time series"

**3. parsing-hecras-geometry**
- RasGeometry and RasStruct APIs
- Cross sections, storage areas, structures (bridges, culverts, weirs)
- Critical: 450-point limit, bank station interpolation
- **Trigger terms**: "geometry file", "cross section", "Manning's n", "bridge", "culvert"

### Phase 2: Advanced Features (3 skills)

**4. integrating-usgs-gauges**
- Complete USGS workflow: discovery → retrieval → matching → validation
- RasUsgsCore, GaugeMatcher, validation metrics
- Boundary condition and initial condition generation
- **Trigger terms**: "USGS", "gauge data", "observed flow", "model validation"

**5. analyzing-aorc-precipitation**
- AORC grid extraction, spatial interpolation
- Time series generation for HEC-RAS boundaries
- Quality control and visualization
- **Trigger terms**: "AORC", "precipitation", "rainfall", "meteorological"

**6. repairing-geometry-issues**
- RasFixit module workflows
- Validation loops: detect → backup → fix → verify → test
- Blocked obstruction fixes, elevation envelope algorithm
- **Trigger terms**: "geometry error", "blocked obstruction", "preprocessing failure"

### Phase 3: Specialized (2 skills)

**7. executing-remote-plans**
- Remote worker setup (PsExec, Docker, SSH)
- Distributed execution, queue management
- Critical: Session ID configuration, Group Policy
- **Trigger terms**: "remote execution", "distributed", "worker", "parallel across machines"

**8. reading-dss-boundary-data**
- RasDss API for HEC-DSS V6/V7 files
- Java bridge setup, lazy loading
- Boundary condition extraction and conversion
- **Trigger terms**: "DSS file", "boundary condition", "HMS output"

## Tool Permissions with `allowed-tools`

**Use Case**: Read-only geometry inspection

```yaml
---
name: inspecting-geometry-files
description: Reads and parses HEC-RAS geometry files without modifications...
allowed-tools: Read, Grep, Glob
---
```

**Effect**: While skill active, Claude can use Read/Grep/Glob without permission prompts, but cannot use Write/Edit/Bash.

**When to Use**:
- Read-only analysis skills
- Security-sensitive operations (limit destructive tools)
- Narrow scope workflows (data analysis only)

## Workflow Composition Patterns

### Pattern 1: Validation Loops (RasFixit)

```markdown
## Workflow

Copy this checklist:

Repair Progress:
- [ ] Step 1: Detect issues (detect_obstruction_overlaps)
- [ ] Step 2: Create backup (automatic timestamped backup)
- [ ] Step 3: Apply fixes (fix_blocked_obstructions)
- [ ] Step 4: Verify changes (review PNG outputs)
- [ ] Step 5: Test preprocessing (run RasCmdr)

[Detailed steps follow]
```

### Pattern 2: Conditional Workflows (HDF Results)

```markdown
## Determine Result Type

1. Check if HDF contains steady or unsteady results:
   ```python
   from ras_commander import HdfResultsPlan
   hdf = HdfResultsPlan("plan.p01.hdf")
   is_steady = hdf.is_steady_plan()
   ```

2. **For steady flow** → See [workflows/steady.md](workflows/steady.md)
3. **For unsteady flow** → See [workflows/unsteady.md](workflows/unsteady.md)
```

### Pattern 3: Script Automation (AORC)

```markdown
## AORC Precipitation Workflow

**Step 1: Generate AORC folder**
Run: `python scripts/generate_aorc_folder.py project_folder`

**Step 2: Extract time series**
Run: `python scripts/extract_timeseries.py project_folder --start 2017-08-25`

**Step 3: Visualize**
See [examples/visualization.md](examples/visualization.md)
```

**Advantage**: Scripts execute without loading into context (token-free!)

## Dependencies and Cross-Platform Compatibility

### Critical Dependencies (Must Pre-Install for API Usage)

**Skills should document dependencies in frontmatter**:
```yaml
---
name: integrating-usgs-gauges
description: Retrieves USGS gauge data using dataretrieval package...
---

# Requirements

Install the dataretrieval package:
```bash
pip install dataretrieval
```

Required for USGS NWIS access (lazy-loaded by ras-commander).
```

**Skills work across**:
- claude.ai (full support, can install packages)
- Claude Code CLI (full support)
- Anthropic API (**no network access** - dependencies must be pre-installed)

## Migration Strategy

### Phase 1: Create Skill Structure (Week 1-2)

```bash
mkdir -p .claude/skills/{executing-hecras-plans,extracting-hecras-results,parsing-hecras-geometry}
```

Create SKILL.md files with YAML frontmatter.

### Phase 2: Extract from AGENTS.md (Week 3-4)

**Identify workflow content** in current AGENTS.md files:
- Multi-step processes (more than "call this function")
- Conditional branching (if X then Y, else Z)
- Validation loops (repeat until success)
- Complete use-case demonstrations

**Move to Skills**, leaving API reference in AGENTS.md.

### Phase 3: Test Discovery (Week 5)

**Validation queries**:
- "How do I run a HEC-RAS simulation?" → Should trigger `executing-hecras-plans`
- "Extract water surface elevations from HDF" → Should trigger `extracting-hecras-results`
- "Read a geometry file and get cross sections" → Should trigger `parsing-hecras-geometry`
- "Get USGS gauge data for my model" → Should trigger `integrating-usgs-gauges`

### Phase 4: Optimize Progressive Disclosure (Week 6)

**For each skill**:
- Main SKILL.md: <500 lines
- Reference files: Detailed API (load on-demand)
- Examples: Complete workflows
- Scripts: Executable utilities (token-free)

## Key Takeaways

1. **Skills = Discoverable Workflows** (not API reference)
2. **Descriptions = Discovery** (invest time in clear, keyword-rich descriptions)
3. **Progressive Disclosure = Token Savings** (SKILL.md navigates, references load on-demand)
4. **Scripts = Token-Free Execution** (automate complex operations without context cost)
5. **Complementary to AGENTS.md** (Skills for workflows, AGENTS.md for persistent context)
6. **Gerund naming** - `executing-plans`, not `execute-plans` or `plan-executor`
7. **Third person descriptions** - "Executes plans", not "I execute plans"
8. **Test with all models** - Haiku needs more detail than Opus in descriptions

## Testing Framework

**Evaluation-Driven Development**:

```python
# test_skill_discovery.py
test_cases = [
    ("How do I run a HEC-RAS plan?", "executing-hecras-plans"),
    ("Extract unsteady results from HDF", "extracting-hecras-results"),
    ("Get USGS flow data", "integrating-usgs-gauges"),
    ("Fix geometry preprocessing error", "repairing-geometry-issues"),
]

for query, expected_skill in test_cases:
    selected_skill = claude.invoke(query, return_skill_name=True)
    assert selected_skill == expected_skill
```

---

**Bottom Line**: Skills framework enables **discoverable, composable workflows** with **progressive disclosure** for token optimization. Perfect fit for ras-commander's complex multi-step hydraulic modeling operations.
