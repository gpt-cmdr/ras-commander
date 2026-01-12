# Notebook-to-Agent/Skill Conversion Pattern

**Context**: Converting example notebooks into reusable agents and skills
**Priority**: Medium - Helps with agent/skill development
**Auto-loads**: When creating new agents or skills
**Discovered**: 2026-01-08 (HEC-RAS Operations System implementation)

---

## Overview

Example notebooks in `examples/` are excellent sources for creating agents and skills. This document provides the pattern for extracting workflows from notebooks into the hierarchical knowledge system.

## Core Principle

**Notebooks are PRIMARY SOURCES, not duplication targets.**

Agents and skills should NAVIGATE TO notebooks, not copy from them.

---

## Conversion Decision Tree

### When to Create an Agent

Create an agent when the notebook demonstrates:
- ✅ Complex multi-step analysis requiring domain expertise
- ✅ Data extraction and interpretation patterns
- ✅ Specialized knowledge in a subdomain
- ✅ Workflows requiring multiple tool calls

**Examples**:
- `400_1d_hdf_data_extraction.ipynb` → `hdf-analyst` agent
- `201_1d_plaintext_geometry.ipynb` → `geometry-parser` agent
- `101_project_initialization.ipynb` → `hecras-project-inspector` agent

### When to Create a Skill

Create a skill when the notebook demonstrates:
- ✅ Repeatable workflow users frequently need
- ✅ API usage patterns with common parameters
- ✅ Clear happy path with variations
- ✅ End-to-end process (setup → execute → validate)

**Examples**:
- `110_single_plan_execution.ipynb` → `executing-hecras-plans` skill
- `500_remote_execution_psexec.ipynb` → `executing-remote-plans` skill
- `310_dss_boundary_extraction.ipynb` → `reading-dss-boundary-data` skill

---

## The Conversion Pattern

### Step 1: Identify the Workflow

**Read the notebook** and extract:
1. **What problem it solves** (Quick Start summary)
2. **Key API methods used** (Quick Reference)
3. **Common variations** (Common Patterns)
4. **Prerequisites** (Setup requirements)
5. **Failure modes** (Troubleshooting)

### Step 2: Create the Navigator

**Agent/Skill Structure**:
```yaml
---
name: skill-name
description: |
  [Trigger-rich description extracted from notebook introduction]
---

# Skill/Agent Name

## Primary Sources

**Complete workflow**: `examples/XXX_notebook_name.ipynb`
- Cells 1-5: Setup and initialization
- Cells 6-10: Core execution
- Cells 11-15: Results extraction

**API reference**: Grep `ras_commander/{module}/*.py`

## Quick Start

[Minimal code from notebook - 30-50 lines max]

## Common Patterns

1. **Pattern Name** - See notebook cells XX-XX
2. **Pattern Name** - See notebook cells XX-XX

## Troubleshooting

- Issue → See notebook cells XX-XX for solution
```

### Step 3: What NOT to Convert

**❌ Don't duplicate**:
- Detailed explanations (keep in notebook)
- Complete code examples (reference notebook cells)
- Output examples (notebook shows them)
- Setup instructions (reference notebook)

**✅ DO provide**:
- Quick reference code (copy-paste ready)
- Navigation to notebook sections
- Key API method signatures
- Critical warnings not obvious in notebook

---

## Example: executing-hecras-plans Skill

### Source Notebook

`examples/110_single_plan_execution.ipynb` demonstrates:
- Basic compute_plan() usage
- Parameter variations (dest_folder, num_cores)
- Monitoring with callbacks
- Error handling

### Skill Content (What to Include)

**Quick Start** (from notebook cells 3-5):
```python
from ras_commander import init_ras_project, RasCmdr

init_ras_project("/path/to/project", "6.5")
RasCmdr.compute_plan("01")
```

**Navigation** (not duplication):
```markdown
## Complete Workflow

See `examples/110_single_plan_execution.ipynb`:
- Cells 1-2: Setup
- Cells 3-5: Basic execution
- Cells 6-8: Advanced parameters
- Cells 9-12: Monitoring with callbacks
```

**Quick Reference** (extracted patterns):
```python
# Common parameter combinations
RasCmdr.compute_plan("01", dest_folder="/output", num_cores=4)
RasCmdr.compute_plan("01", stream_callback=ConsoleCallback())
```

---

## Multiple Notebooks to One Skill

### Pattern: Consolidate Related Workflows

**Notebooks**:
- `110_single_plan_execution.ipynb`
- `113_parallel_execution.ipynb`
- `112_sequential_plan_execution.ipynb`

**One Skill**: `executing-hecras-plans`

**Structure**:
```markdown
## Primary Sources

**Single plan execution**: `examples/110_single_plan_execution.ipynb`
**Parallel execution**: `examples/113_parallel_execution.ipynb`
**Sequential test mode**: `examples/112_sequential_plan_execution.ipynb`

## Quick Start

### Single Plan
[Pattern from 110]

### Parallel
[Pattern from 113]

### Sequential Test
[Pattern from 112]
```

---

## Agent Output Schema Design

### Extract from Notebook Analysis Cells

Notebooks often have summary/analysis cells at the end. Extract the output format:

**Notebook Cell**:
```python
# Summary statistics
print(f"Max WSE: {wse.max():.2f}")
print(f"Min WSE: {wse.min():.2f}")
print(f"Execution time: {duration:.1f} seconds")
```

**Agent Output Schema**:
```markdown
## Results Summary

- Max WSE: X.XX ft
- Min WSE: X.XX ft
- Execution time: X.X seconds
```

### Structured Reports for Orchestrators

Agents should produce **structured markdown** that orchestrators can parse:

```markdown
# {Report Type}: {Subject}

## Summary
[2-3 sentence executive summary]

## {Section 1}
| Key | Value | Status |
|-----|-------|--------|

## Recommendations
- [Actionable items]
```

---

## Anti-Patterns

### ❌ Duplicating Notebook Content

**Wrong**:
```markdown
# executing-plans skill

## Complete Tutorial

[Copies all notebook cells and explanations]
```

**Right**:
```markdown
# executing-plans skill

## Primary Sources

See `examples/110_single_plan_execution.ipynb` for complete tutorial.

## Quick Start
[Minimal code only]
```

### ❌ Creating Examples/ Folder in Skill

**Wrong**:
```
.claude/skills/executing-plans/
├── SKILL.md
└── examples/
    └── basic.py  # Duplicates examples/110_...
```

**Right**:
```
.claude/skills/executing-plans/
└── SKILL.md  # References examples/110_...
```

### ❌ Missing Notebook References

**Wrong**:
```markdown
# Skill with code but no source attribution
```

**Right**:
```markdown
# Skill

## Primary Sources

**Complete workflow**: `examples/110_single_plan_execution.ipynb`
**Advanced patterns**: `examples/113_parallel_execution.ipynb`
```

---

## Quality Checklist

When converting notebooks to agents/skills:

- [ ] Identified primary source notebook(s)
- [ ] Extracted minimal Quick Start (30-50 lines)
- [ ] Created navigation to notebook sections (not duplication)
- [ ] Defined output schema (if agent)
- [ ] Documented trigger keywords
- [ ] Added troubleshooting references
- [ ] File size 200-400 lines (navigator, not tutorial)
- [ ] No examples/ folder created
- [ ] No reference/ folder created (except documented exceptions)

---

## Implementation Template

```yaml
---
name: {skill-name}
description: |
  {What notebook demonstrates} ...triggers: {keywords from notebook}
---

# {Skill/Agent Name}

## Primary Sources

**Complete workflow**: `examples/{number}_{name}.ipynb`
- [Brief description of what notebook covers]

## Quick Start

[Minimal code from notebook - 30-50 lines]

## Common Patterns

1. **Pattern Name** - See notebook cells XX-XX
2. **Pattern Name** - See notebook cells XX-XX

## Troubleshooting

See `examples/{notebook}.ipynb` cells XX-XX for common issues.

## See Also

- Other related notebooks
- Relevant CLAUDE.md files
- Related agents/skills
```

---

## See Also

- **Notebook Standards**: `.claude/rules/documentation/notebook-standards.md`
- **Hierarchical Knowledge**: `.claude/rules/documentation/hierarchical-knowledge-best-practices.md`
- **Agent README**: `.claude/agents/README.md`
- **Skills README**: `.claude/skills/README.md`
- **Implementation Example**: HEC-RAS Operations System (this task)

---

**Key Takeaway**: Notebooks are PRIMARY SOURCES. Agents and skills NAVIGATE TO them, providing minimal Quick Start patterns and references to notebook sections. Never duplicate tutorial content.
