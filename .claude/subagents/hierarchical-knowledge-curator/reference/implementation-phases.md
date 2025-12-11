# Implementation Phases - Hierarchical Knowledge Approach

**Source**: MASTER_IMPLEMENTATION_PLAN.md (condensed)
**Version**: 1.0
**Date**: 2025-12-11

## Overview

5-phase approach to migrate ras-commander to hierarchical knowledge architecture:
- **Timeline**: 6 weeks, ~40-50 hours effort
- **Status**: Phase 1 COMPLETE ✅
- **Goal**: Pure Claude framework with progressive disclosure

## Phase 1: Foundation (Week 1) ✅ COMPLETE

**Status**: Completed 2025-12-11 (commit 573a62d)

### Achievements

1. ✅ Created .claude/ directory structure
   - .claude/rules/ (python/, hec-ras/, testing/, documentation/)
   - .claude/skills/ (library workflows)
   - .claude/subagents/ (specialist definitions)

2. ✅ Renamed ras_agents → ras_skills
   - Updated all documentation references
   - Aligned with Claude Skills terminology
   - No large files tracked in git

3. ✅ Updated .gitignore
   - Excluded 22GB+ development folders
   - Allowed framework structure
   - Protected repository from bloat

4. ✅ Established ras_skills/
   - README.md with guidelines
   - CLAUDE.md for context
   - Production-ready skills location

### Metrics

- Branch: `feature/hierarchical-knowledge`
- Files changed: 20
- Lines added: +3,266
- Lines removed: -934
- Large files excluded: Model Updater (22GB), 1D Mannings (11MB)

## Phase 2: Content Migration (Week 2-3) 🔄 IN PROGRESS

**Goal**: Reduce root CLAUDE.md from 607 lines → <200 lines (67% reduction)

### Tasks

#### 2.1: Extract Python Patterns to .claude/rules/python/

Create modular rules files:

**static-classes.md** (Extract lines 304-330 from root CLAUDE.md):
- RasCmdr, HdfBase pattern explanation
- Why no instantiation required
- @log_call decorator usage
- Example: `RasCmdr.compute_plan()` not `RasCmdr().compute_plan()`

**decorators.md**:
- @log_call decorator
- @standardize_input decorator
- Custom decorator patterns
- Logging integration

**path-handling.md**:
- pathlib.Path patterns
- Windows compatibility
- Support for both Path and string inputs

**error-handling.md**:
- LoggingConfig usage
- Exception patterns
- Log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Rotating file logs

**naming-conventions.md**:
- snake_case functions/variables
- PascalCase classes
- UPPER_CASE constants
- Approved abbreviations: ras, prj, geom, num, BC, IC, TW

**import-patterns.md**:
- Flexibility pattern for dev vs installed package
- try/except ImportError with sys.path.append()

#### 2.2: Extract HEC-RAS Knowledge to .claude/rules/hec-ras/

**execution.md**:
- RasCmdr.compute_plan() parameters
- Parallel execution: compute_parallel()
- Test mode: compute_test_mode()
- stream_callback for real-time monitoring

**geometry.md**:
- Fixed-width parsing patterns
- Bank station interpolation
- 450-point limit enforcement
- RasGeometry and RasStruct APIs

**hdf-files.md**:
- HdfResultsPlan API
- Steady vs unsteady detection
- is_steady_plan() pattern
- Result extraction workflows

**dss-files.md**:
- RasDss API for HEC-DSS V6/V7
- Java bridge (pyjnius lazy loading)
- Boundary condition extraction
- get_catalog(), read_timeseries()

**remote.md**:
- Critical: Session ID=2 (not system_account)
- Group Policy requirements
- Registry: LocalAccountTokenFilterPolicy=1
- Remote Registry service must run
- PsExec, Docker, SSH worker patterns

**usgs.md**:
- RasUsgsCore data retrieval
- GaugeMatcher spatial matching
- Validation metrics (NSE, KGE)
- Real-time monitoring workflows

**precipitation.md**:
- AORC grid extraction
- Atlas 14 integration
- StormGenerator patterns
- Time series for HEC-RAS boundaries

#### 2.3: Extract Testing Patterns to .claude/rules/testing/

**tdd-approach.md**:
- Test with real HEC-RAS example projects
- NOT unit tests or mocks
- RasExamples.extract_project() workflows
- Example projects serve as functional tests

**example-projects.md**:
- RasExamples class usage
- Extraction to temporary folders
- List projects by category
- Validation with actual HEC-RAS runs

#### 2.4: Extract Documentation Standards to .claude/rules/documentation/

**mkdocs-config.md**:
- Notebook integration patterns
- ReadTheDocs: Use `cp`, NOT `ln -s` (symlinks stripped!)
- GitHub Pages: Symlinks OK
- validation.links.unrecognized_links: info

**notebook-standards.md**:
- H1 title required in first cell
- mkdocs-jupyter configuration
- ignore_h1_titles: true pattern
- execute: false (don't run notebooks during build)

#### 2.5: Condense Root CLAUDE.md

**Keep (strategic content)**:
- Project overview (what is ras-commander)
- Architecture principles
- Model selection guide (Opus/Sonnet/Haiku)
- Subagent delegation decision tree
- Navigation guide (folder → context mapping)
- Repository structure overview

**Remove (extracted to .claude/rules/)**:
- Detailed Python patterns → python/
- HEC-RAS domain knowledge → hec-ras/
- Testing approaches → testing/
- Documentation standards → documentation/
- Agent coordination (duplicates agent_tasks/README.md)

**Target**: <200 lines (~10KB)

### Success Criteria

- [ ] Root CLAUDE.md <200 lines
- [ ] 20+ rules files created in .claude/rules/
- [ ] No duplicated content
- [ ] All critical knowledge preserved
- [ ] Context inheritance verified

## Phase 3: Create Missing CLAUDE.md Files (Week 3-4)

**Goal**: Provide tactical context for subpackages missing documentation

### Files to Create

#### ras_commander/CLAUDE.md
**Current**: AGENTS.md exists (70 lines)
**Action**: Convert AGENTS.md → CLAUDE.md, expand to ~150 lines

**Content**:
- Library organization overview
- Common patterns (init → compute → extract)
- Module relationships
- Import conventions

#### ras_commander/usgs/CLAUDE.md
**Current**: No documentation (14 modules!)
**Size Target**: ~150 lines

**Content**:
- USGS workflow overview
- RasUsgsCore, GaugeMatcher, UsgsGaugeSpatial
- Real-time monitoring patterns
- Validation metrics usage
- dataretrieval dependency (lazy loaded)

#### ras_commander/check/CLAUDE.md
**Current**: No documentation (4 modules)
**Size Target**: ~100 lines

**Content**:
- RasCheck quality assurance framework
- Validation patterns
- Integration with RasFixit
- Quality metrics

#### ras_commander/precip/CLAUDE.md
**Current**: No documentation (2 modules)
**Size Target**: ~100 lines

**Content**:
- AORC precipitation workflows
- Atlas 14 integration
- StormGenerator patterns
- HEC-RAS boundary condition generation

#### ras_commander/mapping/CLAUDE.md
**Current**: No documentation (3 modules)
**Size Target**: ~100 lines

**Content**:
- RASMapper automation
- RasMap configuration parsing
- Programmatic result mapping
- Map layer creation

#### feature_dev_notes/CLAUDE.md
**Current**: No documentation
**Size Target**: ~150 lines

**Content**:
- Purpose of feature_dev_notes/
- Organization by feature area
- Development workflow
- When to move to production
- Relationship to planning_docs/ (deprecated)

### Conversion Pattern

For existing AGENTS.md → CLAUDE.md:

1. Read existing AGENTS.md
2. Extract key content
3. Remove AGENTS.md terminology
4. Add Claude framework context
5. Ensure <150 lines
6. Add deprecation notice to old AGENTS.md
7. Commit both (keep AGENTS.md for 1 release cycle)

## Phase 4: Create Subagents & Skills (Week 4-5)

### 4.1: Define Specialist Subagents

Create 7 subagent definitions in .claude/subagents/:

1. **hdf-analyst** - HEC-RAS HDF file operations
2. **geometry-parser** - Geometry file parsing and modification
3. **remote-executor** - Distributed execution coordination
4. **usgs-integrator** - USGS gauge data workflows
5. **precipitation-specialist** - AORC and Atlas 14
6. **quality-assurance** - RasFixit and RasCheck
7. **documentation-generator** - Example notebooks and API docs

Each subagent:
- Model: sonnet (for specialists), haiku (for simple tasks)
- Tools: Minimal necessary set
- Skills: Relevant library skills
- Working directory: Specific subpackage
- Trigger-rich description

### 4.2: Create Library Workflow Skills

Create 8 skills in .claude/skills/:

**Phase 1** (Core operations):
1. executing-hecras-plans
2. extracting-hecras-results
3. parsing-hecras-geometry

**Phase 2** (Advanced features):
4. integrating-usgs-gauges
5. analyzing-aorc-precipitation
6. repairing-geometry-issues

**Phase 3** (Specialized):
7. executing-remote-plans
8. reading-dss-boundary-data

Each skill:
- SKILL.md with YAML frontmatter
- Progressive disclosure (<500 lines main, details in reference/)
- Gerund naming convention
- Trigger-rich description
- Examples and scripts

## Phase 5: Testing & Validation (Week 6)

### 5.1: Hierarchical Context Loading Tests

```python
# Test context inheritance
def test_context_inheritance():
    # Test subagent in ras_commander/hdf/ inherits:
    # 1. Root CLAUDE.md
    # 2. ras_commander/CLAUDE.md
    # 3. ras_commander/hdf/CLAUDE.md
    # 4. .claude/rules/hec-ras/hdf-files.md
    pass
```

### 5.2: Skill Discovery Tests

```python
# Test skill activation with natural language
test_cases = [
    ("How do I run a HEC-RAS plan?", "executing-hecras-plans"),
    ("Extract water surface elevations", "extracting-hecras-results"),
    ("Get USGS gauge data", "integrating-usgs-gauges"),
    ("Fix geometry error", "repairing-geometry-issues"),
]
```

### 5.3: Subagent Delegation Tests

```python
# Test main agent delegates correctly
test_cases = [
    ("Analyze this HDF file", "hdf-analyst"),
    ("Parse geometry file", "geometry-parser"),
    ("Setup remote workers", "remote-executor"),
]
```

### 5.4: Duplication Audit

```bash
# Check for duplicated content
./scripts/check_duplication.sh

# Verify no circular references
./scripts/check_circular_refs.sh

# Validate file sizes
./scripts/check_file_sizes.sh
```

### 5.5: Integration Testing

1. Complete end-to-end workflow with subagents
2. Skill discovery and activation
3. Context inheritance verification
4. Performance profiling (context loading time)

## Success Metrics Summary

| Metric | Before | After | Target Met? |
|--------|--------|-------|-------------|
| Root CLAUDE.md size | 607 lines | <200 lines | Phase 2 |
| Context duplication | 3+ instances | 0 | Phase 2-3 |
| Subagents defined | 0 | 7 | Phase 4 |
| Library skills created | 0 | 8 | Phase 4 |
| Missing CLAUDE.md | 6 subpackages | 0 | Phase 3 |
| Documentation health | Good foundation | Excellent | Phase 5 |

## Rollback Plan

If issues found:

1. **Phase 2-3**: Restore root CLAUDE.md from git
2. **Phase 4**: Remove subagent/skill definitions
3. **Phase 5**: Revert to previous architecture

Git branch isolation provides safety net.

## Next Steps

**Immediate** (Phase 2):
1. Start extracting Python patterns to .claude/rules/python/
2. Create first rules file: static-classes.md
3. Test context loading
4. Continue extracting HEC-RAS knowledge

**This Week**:
- Complete Phase 2 content migration
- Begin Phase 3 (missing CLAUDE.md files)

**Next Week**:
- Finish Phase 3
- Start Phase 4 (subagents & skills)

---

**Reference**: See `feature_dev_notes/Hierarchical_Knowledge_Approach/MASTER_IMPLEMENTATION_PLAN.md` for complete details
