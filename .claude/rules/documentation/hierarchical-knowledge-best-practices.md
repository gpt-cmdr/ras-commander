# Hierarchical Knowledge - Best Practices

**Lesson Learned**: 2025-12-11 Phase 4 Refactoring

## The Anti-Pattern (What NOT to Do)

### ❌ Phase 4 Initial Implementation (Bloated)

Created ~30,000 lines of duplicated content:

```
.claude/agents/{name}/
├── SUBAGENT.md (300-800 lines with duplicated API)
└── reference/
    ├── api-patterns.md (400-600 lines - duplicates docstrings)
    ├── workflows.md (500-700 lines - duplicates CLAUDE.md)
    └── advanced.md (300-500 lines - duplicates AGENTS.md)

.claude/skills/{name}/
├── SKILL.md (500-800 lines with duplicated workflows)
├── reference/
│   ├── api.md (500-700 lines - duplicates CLAUDE.md)
│   └── advanced.md (400-600 lines - duplicates AGENTS.md)
└── examples/
    ├── basic.py (200-300 lines - duplicates notebooks)
    └── advanced.py (300-400 lines - duplicates notebooks)
```

**Problems**:
- Maintenance burden (update 5+ files for single change)
- Version drift (duplicates get out of sync)
- No single source of truth
- Hard to find authoritative documentation
- Wastes context loading time

## The Correct Pattern (Lightweight Navigators)

### ✅ Phase 4 Refactored (Efficient)

Created ~4,937 lines of primary source navigators:

```
.claude/agents/{name}/
└── SUBAGENT.md (200-400 lines - navigator ONLY)

.claude/skills/{name}/
└── SKILL.md (200-400 lines - navigator ONLY)
```

**Benefits**:
- Single source of truth
- No version drift
- Easy maintenance (update once)
- Faster loading (80% smaller)
- Clear authoritative sources

## Core Principles

### 1. Primary Source Navigation

**Subagents and skills are NAVIGATORS, not documentation repositories.**

**DO**:
- ✅ Point to existing primary sources
- ✅ Provide minimal orientation (200-400 lines total)
- ✅ Include quick reference patterns (copy-paste ready)
- ✅ Preserve critical warnings that MUST be visible
- ✅ Keep YAML trigger-rich for discovery

**DON'T**:
- ❌ Duplicate API documentation from code docstrings
- ❌ Duplicate workflows from CLAUDE.md files
- ❌ Duplicate examples from notebooks
- ❌ Create reference/ folders with authoritative content
- ❌ Exceed 400 lines without strong justification

### 2. Single Source of Truth

**Every piece of information has ONE authoritative location:**

| Content Type | Authoritative Location | Navigator Role |
|--------------|------------------------|----------------|
| Workflows | Subpackage CLAUDE.md | Point to CLAUDE.md sections |
| Implementation details | Subpackage AGENTS.md | Point to AGENTS.md sections |
| API reference | Code docstrings | Point to source files |
| Demonstrations | Example notebooks | Point to specific notebooks |
| Coding patterns | .claude/rules/ | Point to relevant rules |

### 3. Progressive Disclosure via References

**Hierarchy uses POINTERS instead of DUPLICATION:**

```
Root CLAUDE.md (strategic)
    ↓ references
Subpackage CLAUDE.md (tactical workflows) ← AUTHORITATIVE
    ↓ references
Subpackage AGENTS.md (technical details) ← AUTHORITATIVE
    ↓ referenced by
Subagent/Skill (lightweight navigator) ← POINTS TO ABOVE
```

### 4. Critical Warnings Exception

**Some content MUST be in navigators** (not buried in primary sources):

✅ **Include in navigators**:
- `session_id=2` requirement (remote execution) - critical configuration
- `0.02-unit gap` constant (geometry repair) - HEC-RAS requirement
- ReadTheDocs symlink stripping (documentation) - deployment blocker
- Fixed-width parsing patterns (geometry) - data corruption risk

**Rationale**: These are too critical to risk users missing them by not reading primary sources.

### 5. Legitimate reference/ Folder Exceptions

**TWO agents are permitted to have reference/ folders with substantial content:**

✅ **Exception 1: hierarchical-knowledge-agent-skill-memory-curator**
- **File**: `.claude/agents/hierarchical-knowledge-agent-skill-memory-curator.md` (468 lines + 104KB reference/)
- **Rationale**: Contains meta-knowledge about the hierarchical system itself
- **Reference content**: Implementation phases, governance rules, research synthesis, memory system architecture
- **Why justified**: Self-referential system - must contain organizational knowledge that doesn't belong elsewhere
- **Status**: Documented exception, no action needed

✅ **Exception 2: claude-code-guide**
- **File**: `.claude/agents/claude-code-guide.md` (331 lines + 46KB reference/)
- **Rationale**: Caches official Anthropic documentation to prevent repeated web fetches
- **Reference content**: Official docs from claude.com and code.claude.com (skills creation, memory system)
- **Why justified**: External authoritative source that should be cached locally for offline access
- **Status**: Documented exception, no action needed

**All other agents and skills MUST follow the lightweight navigator pattern (200-400 lines, no reference/ folders).**

## Template Structure

### Subagent/Skill YAML Frontmatter

```yaml
---
name: {subagent-name or skill-name}
model: sonnet  # or haiku for simpler tasks
tools: [Read, Grep, Glob, Edit, Bash]
working_directory: {path}  # agents only
description: |
  {Trigger-rich description with action verbs, class names, common phrases}

  Primary sources:
  - ras_commander/{subpackage}/CLAUDE.md - Complete workflows
  - ras_commander/{subpackage}/AGENTS.md - Implementation details
  - examples/{notebook}.ipynb - Working demonstrations
---
```

### Content Structure (200-400 lines TOTAL)

```markdown
# {Name}

## Primary Sources (Read These First)

**Complete Workflows**:
- `ras_commander/{subpackage}/CLAUDE.md` (XXX lines)
  - Lines XX-XX: {Workflow description}
  - Lines XX-XX: {Another workflow}

**Implementation Details**:
- `ras_commander/{subpackage}/AGENTS.md` (XXX lines)
  - Lines XX-XX: {Technical pattern}
  - Lines XX-XX: {Algorithm details}

**Working Examples**:
- `examples/{notebook}.ipynb` - {Description}

**API Reference**:
- Grep `ras_commander/{subpackage}/*.py` for method signatures
- Read docstrings for parameter details

## Quick Reference

[Minimal code patterns for common tasks - 50-100 lines]

## Common Workflows

[Brief workflow list with pointers to primary sources - 30-50 lines]

## Critical Warnings

[CRITICAL configuration/patterns that must be visible - 20-40 lines]

## Navigation Map

For complete details, always read the primary sources listed above.
```

## Real-World Examples

### Before Refactoring: usgs-integrator (❌ Bloated)

```
.claude/agents/usgs-integrator/
├── SUBAGENT.md (330 lines)
└── reference/
    ├── end-to-end.md (423 lines) - DUPLICATES usgs/CLAUDE.md
    ├── real-time.md (458 lines) - DUPLICATES usgs/CLAUDE.md
    └── validation.md (439 lines) - DUPLICATES usgs/CLAUDE.md

Total: 1,650 lines (84.5% duplication)
```

### After Refactoring: usgs-integrator (✅ Lightweight)

```
.claude/agents/usgs-integrator/
└── SUBAGENT.md (255 lines - navigator to usgs/CLAUDE.md)

Total: 255 lines (84.5% reduction, 0% duplication)
```

**SUBAGENT.md content**:
- YAML frontmatter (trigger-rich description)
- Primary sources section (points to usgs/CLAUDE.md lines XX-XX)
- Quick reference (14 modules, one-line descriptions)
- Common workflows (brief list with "See usgs/CLAUDE.md lines XX-XX")
- Navigation map (where to find complete details)

## Refactoring Checklist

When creating or updating agents/skills:

### Planning
- [ ] Identify all primary sources (CLAUDE.md, AGENTS.md, notebooks, code)
- [ ] List topics covered by each primary source
- [ ] Identify critical warnings that MUST be in navigator

### Writing Navigator
- [ ] YAML frontmatter with trigger-rich description
- [ ] Primary sources section with specific file/line references
- [ ] Quick reference patterns (copy-paste ready, no duplication)
- [ ] Critical warnings section (if applicable)
- [ ] Navigation map ("See X for complete Y")

### Cleanup
- [ ] Delete reference/ folder (if exists)
- [ ] Delete examples/ folder (if duplicates notebooks)
- [ ] Verify all primary source paths are correct
- [ ] Check line count (200-400 lines target)
- [ ] Test that navigator provides orientation without duplication

### Verification
- [ ] All "See X" links point to existing files
- [ ] Primary sources contain complete information
- [ ] No duplicated API docs, workflows, or examples
- [ ] Critical warnings are prominent
- [ ] File size within target range

## Metrics from Phase 4 Refactoring

### Subagents (7 total)
- **Before**: 12,891 lines (avg 1,842 lines/file)
- **After**: 2,141 lines (avg 306 lines/file)
- **Reduction**: 83.4% (10,750 lines removed)

### Skills (8 total)
- **Before**: 17,310 lines (avg 2,164 lines/file)
- **After**: 2,796 lines (avg 350 lines/file)
- **Reduction**: 83.8% (14,514 lines removed)

### Overall
- **Files deleted**: 60 (all reference/ and examples/ folders)
- **Lines removed**: 25,264 lines (83.6% reduction)
- **Duplication eliminated**: 100%
- **Maintenance locations**: Reduced from 75 files to 15 files

## Common Mistakes to Avoid

### Mistake 1: "Complete Reference" in Subagents

❌ **Wrong**: Creating comprehensive API documentation in subagent reference/ folder

```
.claude/agents/hdf-analyst/reference/api-patterns.md (389 lines)
- Complete API for 19 HDF classes
- Method signatures, parameters, return types
- Examples for each method
```

✅ **Right**: Point to authoritative sources

```
.claude/agents/hdf-analyst/SUBAGENT.md (278 lines)
Primary Sources:
- ras_commander/hdf/AGENTS.md (215 lines) - Complete class reference
- Grep "def " ras_commander/hdf/Hdf*.py - Method signatures
- Read docstrings for parameter details
```

### Mistake 2: "Complete Workflow" in Skills

❌ **Wrong**: Duplicating step-by-step workflows from CLAUDE.md

```
.claude/skills/integrating-usgs-gauges/reference/workflow.md (631 lines)
1. Spatial Discovery
   - Use UsgsGaugeSpatial.find_gauges_in_project()
   - Parameters: project_folder, buffer_miles
   - Returns: GeoDataFrame with gauge locations
   [... 600+ more lines duplicating usgs/CLAUDE.md]
```

✅ **Right**: Brief overview with pointer to complete workflow

```
.claude/skills/integrating-usgs-gauges/SKILL.md (282 lines)
Common Workflows:
1. Spatial Discovery → See usgs/CLAUDE.md lines 45-78
2. Data Retrieval → See usgs/CLAUDE.md lines 80-120
[... brief list, full details in CLAUDE.md]
```

### Mistake 3: "Duplicate Examples" in Skills

❌ **Wrong**: Creating example scripts that duplicate notebook content

```
.claude/skills/reading-dss-boundary-data/examples/read-catalog.py (120 lines)
# Complete workflow duplicating examples/22_dss_boundary_extraction.ipynb
from ras_commander import RasDss, RasExamples
path = RasExamples.extract_project("BaldEagleCrkMulti2D")
[... 100+ lines duplicating notebook]
```

✅ **Right**: Point to existing notebook

```
.claude/skills/reading-dss-boundary-data/SKILL.md (322 lines)
Working Examples:
- examples/22_dss_boundary_extraction.ipynb - Complete workflow with:
  - Project extraction
  - Catalog reading
  - Boundary extraction
  - Plotting and analysis
```

## Maintenance Guidelines

### When Primary Sources Change

**Scenario**: Update workflow in `ras_commander/usgs/CLAUDE.md`

✅ **With lightweight navigators**:
1. Update `ras_commander/usgs/CLAUDE.md` (1 file)
2. Navigator still points to CLAUDE.md
3. No additional updates needed

❌ **With duplicated content** (old approach):
1. Update `ras_commander/usgs/CLAUDE.md`
2. Update `.claude/agents/usgs-integrator/SUBAGENT.md`
3. Update `.claude/agents/usgs-integrator/reference/end-to-end.md`
4. Update `.claude/skills/integrating-usgs-gauges/SKILL.md`
5. Update `.claude/skills/integrating-usgs-gauges/reference/workflow.md`
6. Risk: Miss one location → version drift

### When Adding New Functionality

**New feature**: Add gauge catalog generation to `ras_commander/usgs/`

✅ **Update locations**:
1. Add code to `ras_commander/usgs/catalog.py` with docstrings
2. Add workflow section to `ras_commander/usgs/CLAUDE.md`
3. Add example notebook `examples/420_usgs_gauge_catalog.ipynb`
4. Update navigator: Add one line to usgs-integrator SUBAGENT.md pointing to new CLAUDE.md section

**Total**: 4 updates (all in primary sources + 1 line in navigator)

## Success Criteria

Your hierarchical knowledge structure is correctly implemented if:

- ✅ Each concept documented in exactly ONE authoritative location
- ✅ Subagents/skills are 200-400 lines (navigators, not documentation)
- ✅ No unauthorized reference/ folders (only 2 documented exceptions allowed - see section 5)
- ✅ No examples/ folders duplicating notebooks
- ✅ All "See X" links point to existing files
- ✅ Updates happen in ONE location (primary source)
- ✅ Critical warnings prominent in navigators
- ✅ File count minimal (17 navigators including 2 exceptions, not 75 duplicates)
- ✅ Exceptions documented with clear rationale (section 5)

## Agent Reference Data Locations

### ras_agents/ vs feature_dev_notes/

**Important Distinction**:

**ras_agents/** - Production-ready, tracked agent reference data:
- ✅ Tracked in git for version control
- ✅ Organized following hierarchical knowledge principles
- ✅ Production-ready for automated agent operation
- ✅ Agents can safely reference this location

**feature_dev_notes/** - Experimental, gitignored development space:
- ❌ Gitignored (not tracked)
- ❌ Unorganized experimentation
- ❌ Agents cannot reference this location
- ✅ Used for testing before formalizing in ras_agents/

**Migration Path**: When feature_dev_notes/ agents are ready, migrate to ras_agents/ following hierarchical knowledge principles.

**Example**: Decompilation Agent
- **Development**: `feature_dev_notes/Decompilation Agent/` (gitignored, local only)
- **Production**: `ras_agents/decompilation-agent/` (tracked, agents can reference)

## See Also

- `.claude/rules/documentation/mkdocs-config.md` - Documentation deployment
- `.claude/rules/documentation/notebook-standards.md` - Example notebook standards
- `planning_docs/PHASE_4_REFACTOR_SUMMARY.md` - Complete refactoring analysis
- Root `CLAUDE.md` - Strategic overview and hierarchical knowledge philosophy
- `ras_agents/README.md` - Production agent reference data structure
