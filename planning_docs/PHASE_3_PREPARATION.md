# Phase 3 Preparation - Subpackage CLAUDE.md Files

**Created**: 2025-12-11
**Purpose**: Prepare context for Phase 3 implementation before conversation compacts
**Branch**: feature/hierarchical-knowledge

---

## Current Status Summary

### ✅ COMPLETED
- **Phase 1**: Foundation (directory structure, ras_skills migration) - Commit 573a62d
- **Phase 2**: Content migration (11 rules files, root CLAUDE.md condensed) - Commits 2f36b7a, cf50712
- **LLM Forward Integration**: Phases 1-3 complete - Commit dd0285c

### 🎯 NEXT: Phase 3 - Create Missing CLAUDE.md Files

**Goal**: Provide tactical context for subpackages through hierarchical CLAUDE.md files

**Timeline**: Week 3-4 of 6-week implementation

**Success Criteria**:
- [ ] 5 new CLAUDE.md files created in subpackages
- [ ] Existing AGENTS.md files reviewed for conversion
- [ ] All subpackages have local context
- [ ] Hierarchical loading verified

---

## Phase 3 File Creation Tasks

### Priority 1: Core Library Context

#### 1. ras_commander/CLAUDE.md
**Current State**: AGENTS.md exists (70 lines)
**Action**: Convert AGENTS.md → CLAUDE.md, expand to ~150 lines
**Target**: 150 lines

**Content Structure**:
```markdown
# ras_commander Library Context

## Module Organization

Core modules in this package:
- RasPrj (RasPrj.py) - Project initialization and management
- RasCmdr (RasCmdr.py) - Plan execution (single/parallel/remote)
- RasControl (RasControl.py) - Legacy HEC-RAS 3.x-4.x COM interface
- RasPlan (RasPlan.py) - Plan file operations
- RasMap (RasMap.py) - RASMapper configuration

Subpackages:
- hdf/ - HDF data access (14 modules)
- geom/ - Geometry parsing (10 modules)
- remote/ - Distributed execution (12 modules)
- usgs/ - USGS gauge integration (14 modules)
- check/ - Quality assurance (5 modules)
- precip/ - Precipitation workflows (3 modules)
- mapping/ - RASMapper automation (3 modules)
- dss/ - DSS file operations (3 modules)
- fixit/ - Geometry repair (6 modules)

## Common Workflow Pattern

init_ras_project() → compute_plan() → extract_results()

## Static Class Pattern

Most classes (RasCmdr, HdfBase, RasGeometry, etc.) use static methods.
DO NOT instantiate. Call methods directly.

## Input Normalization

@standardize_input decorator accepts:
- h5py.File object
- Path object
- String path
- Plan/geom number ("01", "p01")

## See Also

- Root CLAUDE.md for strategic overview
- Subpackage AGENTS.md for specialized guidance
- .claude/rules/ for coding patterns
```

**Existing Content to Preserve** (from current AGENTS.md):
- Module layout (RasPrj, RasCmdr, RasControl, RasMap, Hdf*)
- Static namespace pattern
- Plan number conventions ("01" format)
- Input normalization with @standardize_input
- Common recipes (init/compute, 2D mesh, 1D cross sections, pipes/pumps, legacy)
- Performance guidance (num_cores, compute_parallel)

**New Content to Add**:
- Subpackage relationship map
- Workflow progression (project → execution → results)
- When to use which module
- Cross-references to .claude/rules/ files

---

### Priority 2: USGS Integration (Largest Subpackage)

#### 2. ras_commander/usgs/CLAUDE.md
**Current State**: No documentation
**Modules**: 14 files (core.py, spatial.py, real_time.py, catalog.py, etc.)
**Target**: 150 lines

**Content Structure**:
```markdown
# USGS Gauge Data Integration

## Module Overview

14 modules organized by workflow stage:

**Data Retrieval** (core.py):
- RasUsgsCore.retrieve_flow_data()
- RasUsgsCore.retrieve_stage_data()
- RasUsgsCore.get_gauge_metadata()

**Spatial Queries** (spatial.py):
- UsgsGaugeSpatial.find_gauges_in_project()
- UsgsGaugeSpatial.get_project_gauges_with_data()

**Gauge Matching** (gauge_matching.py):
- GaugeMatcher.match_gauge_to_cross_section()
- GaugeMatcher.match_gauge_to_2d_area()
- GaugeMatcher.auto_match_gauges()

**Time Series Processing** (time_series.py):
- RasUsgsTimeSeries.resample_to_hecras_interval()
- RasUsgsTimeSeries.check_data_gaps()
- RasUsgsTimeSeries.align_timeseries()

**Boundary Conditions** (boundary_generation.py):
- RasUsgsBoundaryGeneration.generate_flow_hydrograph_table()
- RasUsgsBoundaryGeneration.generate_stage_hydrograph_table()
- RasUsgsBoundaryGeneration.update_boundary_hydrograph()

**Initial Conditions** (initial_conditions.py):
- InitialConditions.create_ic_line()
- InitialConditions.get_ic_value_from_usgs()

**Real-Time Monitoring** (real_time.py):
- RasUsgsRealTime.get_latest_value()
- RasUsgsRealTime.get_recent_data()
- RasUsgsRealTime.monitor_gauge()

**Catalog Generation** (catalog.py):
- generate_gauge_catalog()
- load_gauge_catalog()

**Validation** (metrics.py, visualization.py):
- nash_sutcliffe_efficiency()
- kling_gupta_efficiency()
- plot_timeseries_comparison()

## Complete Workflow

1. Spatial query → find gauges in project bounds
2. Data retrieval → get historical flow/stage data
3. Gauge matching → associate with HEC-RAS features
4. Time series processing → resample to HEC-RAS intervals
5. Boundary generation → create .u## file hydrographs
6. Validation → compare modeled vs observed

## Lazy Loading

dataretrieval dependency is lazy-loaded. Methods check on first use.

## See Also

- examples/29_usgs_gauge_data_integration.ipynb
- examples/30_usgs_real_time_monitoring.ipynb
- examples/32_model_validation_with_usgs.ipynb
```

**Key Points**:
- 14 modules make this the largest specialized subpackage
- Complete end-to-end workflow from discovery to validation
- Real-time monitoring capabilities (NEW in v0.87.0+)
- Catalog generation (NEW in v0.89.0+)
- Lazy loading of dataretrieval dependency

---

### Priority 3: Quality Assurance

#### 3. ras_commander/check/CLAUDE.md
**Current State**: No documentation
**Modules**: 5 files (RasCheck.py, messages.py, report.py, thresholds.py)
**Target**: 100 lines

**Content Structure**:
```markdown
# RasCheck - Quality Assurance Module

## Purpose

Automated quality assurance checks for HEC-RAS models following FEMA/USACE standards.

## Modules

**RasCheck.py** (448 KB, main module):
- NT Check (Manning's n values)
- XS Check (Cross section spacing, station ordering)
- Structure Check (Bridge/culvert geometry)
- Floodway Check (Floodway encroachment)
- Profiles Check (Profile validation)

**messages.py** (106 KB):
- Validation message templates
- Error codes and descriptions

**report.py** (23 KB):
- Check result compilation
- Report generation

**thresholds.py** (18 KB):
- Configurable QA thresholds
- Standard vs custom limits

## Usage Pattern

from ras_commander.check import RasCheck

# Run all checks
results = RasCheck.run_all_checks("project_folder")

# Run specific check
nt_results = RasCheck.nt_check("project_folder")

## Integration with RasFixit

check/ identifies issues → fixit/ repairs them

## See Also

- examples/28_quality_assurance_rascheck.ipynb
- ras_commander/fixit/ for automated repairs
```

---

### Priority 4: Precipitation Workflows

#### 4. ras_commander/precip/CLAUDE.md
**Current State**: No documentation
**Modules**: 3 files (PrecipAorc.py, StormGenerator.py, __init__.py)
**Target**: 100 lines

**Content Structure**:
```markdown
# Precipitation Workflows

## Purpose

AORC (Analysis of Record for Calibration) and Atlas 14 precipitation integration for HEC-RAS.

## Modules

**PrecipAorc.py** (38 KB):
- AORC data retrieval
- Temporal aggregation
- Spatial averaging over watersheds

**StormGenerator.py** (27 KB):
- Atlas 14 design storm generation
- AEP (Annual Exceedance Probability) events
- Duration-frequency analysis

## AORC Workflow

1. Define watershed boundary (shapefile or HUC)
2. Retrieve AORC precipitation time series
3. Aggregate to HEC-RAS intervals
4. Generate DSS input files

## Atlas 14 Workflow

1. Specify location (lat/lon or station)
2. Select AEP (e.g., 1%, 0.2%, 0.1%)
3. Generate design storm hyetograph
4. Export to HEC-HMS or HEC-RAS format

## See Also

- examples/24_aorc_precipitation.ipynb
- examples/103_Running_AEP_Events_from_Atlas_14.ipynb
- examples/104_Atlas14_AEP_Multi_Project.ipynb
```

---

### Priority 5: RASMapper Automation

#### 5. ras_commander/mapping/CLAUDE.md
**Current State**: No documentation
**Modules**: 3 files (rasterization.py, sloped_interpolation.py, __init__.py)
**Target**: 100 lines

**Content Structure**:
```markdown
# RASMapper Automation

## Purpose

Programmatic result mapping and raster export automation.

## Modules

**rasterization.py** (22 KB):
- Convert HEC-RAS results to rasters
- Depth grids, velocity grids, WSE grids

**sloped_interpolation.py** (28 KB):
- Floodplain interpolation algorithms
- Sloped vs flat water surface methods

## Workflows

**Programmatic Result Mapping**:
- Generate rasters without RAS Mapper GUI
- Batch export multiple variables
- Custom resolution and extent

**Stored Map Generation**:
- Automate RAS Mapper stored map workflow
- Export to GeoTIFF, shapefile

## See Also

- examples/25_programmatic_result_mapping.ipynb
- examples/26_rasprocess_stored_maps.ipynb
- examples/21_rasmap_raster_exports.ipynb
- RasMap class in ras_commander/RasMap.py
```

---

## Existing AGENTS.md Files (Conversion Candidates)

These subpackages already have AGENTS.md files. Review for potential conversion to CLAUDE.md:

### ras_commander/hdf/AGENTS.md
- **Size**: Unknown
- **Content**: HDF module guidance
- **Action**: Read and evaluate if conversion needed or if coexistence is OK

### ras_commander/geom/AGENTS.md
- **Size**: Unknown
- **Content**: Geometry parsing guidance
- **Action**: Read and evaluate

### ras_commander/dss/AGENTS.md
- **Size**: Unknown
- **Content**: DSS file operations
- **Action**: Read and evaluate

### ras_commander/fixit/AGENTS.md
- **Size**: Unknown
- **Content**: RasFixit module guidance
- **Action**: Read and evaluate

### ras_commander/remote/AGENTS.md
- **Size**: Known (extensive, ~200 lines)
- **Content**: Distributed execution, worker types, critical configuration
- **Action**: Keep as AGENTS.md OR convert with extensive expansion

---

## Conversion Pattern (AGENTS.md → CLAUDE.md)

When converting existing AGENTS.md files:

1. **Read** existing AGENTS.md
2. **Extract** key content (module organization, workflows, patterns)
3. **Remove** AGENTS.md-specific terminology
4. **Add** Claude framework context:
   - Link to parent CLAUDE.md
   - Cross-reference to .claude/rules/ where relevant
   - Progressive disclosure (overview here, details in code)
5. **Ensure** <150 lines (concise, focused)
6. **Add** deprecation notice to old AGENTS.md:
   ```markdown
   **Note**: This AGENTS.md will be deprecated in v0.91.0.
   See CLAUDE.md for Claude Code guidance.
   ```
7. **Commit** both files (keep AGENTS.md for 1 release cycle)

---

## Implementation Order (Recommended)

### Week 3 (Days 1-3)
1. ✅ Create ras_commander/CLAUDE.md (convert from AGENTS.md)
2. ✅ Create ras_commander/usgs/CLAUDE.md (largest, most complex)

### Week 3 (Days 4-5)
3. ✅ Create ras_commander/check/CLAUDE.md
4. ✅ Create ras_commander/precip/CLAUDE.md

### Week 4 (Days 1-2)
5. ✅ Create ras_commander/mapping/CLAUDE.md
6. ✅ Review existing AGENTS.md files (hdf/, geom/, dss/, fixit/, remote/)
7. ✅ Decide: Convert or coexist?

### Week 4 (Days 3-5)
8. Test hierarchical loading
9. Verify context inheritance
10. Update integration plan with findings

---

## Key Module Counts (for sizing guidance)

| Subpackage | Module Count | AGENTS.md Exists? | Priority |
|------------|--------------|-------------------|----------|
| usgs/      | 14           | No                | HIGH     |
| remote/    | 12           | Yes               | Review   |
| hdf/       | 14+          | Yes               | Review   |
| geom/      | 10           | Yes               | Review   |
| fixit/     | 6            | Yes               | Review   |
| check/     | 5            | No                | MEDIUM   |
| dss/       | 3            | Yes               | Review   |
| precip/    | 3            | No                | MEDIUM   |
| mapping/   | 3            | No                | LOW      |

---

## Testing Checklist

After Phase 3 completion:

- [ ] All new CLAUDE.md files created (5 files)
- [ ] Hierarchical loading verified (Claude Code reads parent + subpackage)
- [ ] No duplicated content between root and subpackage
- [ ] Cross-references work (links to .claude/rules/ resolve)
- [ ] File sizes appropriate (<150 lines for tactical context)
- [ ] Existing AGENTS.md files reviewed
- [ ] Conversion decisions documented

---

## Success Metrics

**Quantitative**:
- 5 new CLAUDE.md files created
- <150 lines per file (tactical, not reference)
- All 9 subpackages have local context

**Qualitative**:
- Claude Code finds relevant context when working in subpackages
- Progressive disclosure working (overview in CLAUDE.md, details in code)
- No confusion between AGENTS.md and CLAUDE.md purposes
- Engineers can navigate hierarchically (root → subpackage → module)

---

## Next Session Preparation

**Files to read first**:
1. This file (PHASE_3_PREPARATION.md)
2. ras_commander/AGENTS.md (conversion template)
3. ras_commander/usgs/__init__.py (understand module organization)

**Tools needed**:
- Read (for reviewing existing AGENTS.md files)
- Write (for creating new CLAUDE.md files)
- Edit (for adding deprecation notices)
- Grep (for finding cross-references)

**Estimated effort**:
- ras_commander/CLAUDE.md: 30 minutes (conversion)
- usgs/CLAUDE.md: 45 minutes (largest)
- check/CLAUDE.md: 30 minutes
- precip/CLAUDE.md: 30 minutes
- mapping/CLAUDE.md: 30 minutes
- Review existing: 1 hour (6 files)

**Total**: ~4 hours for Phase 3

---

## Handoff Notes

This document preserves:
1. Current phase status (Phase 2 complete, Phase 3 ready)
2. Detailed content structure for each new CLAUDE.md file
3. Conversion pattern for existing AGENTS.md files
4. Implementation order and timeline
5. Success criteria and testing checklist

When resuming, start with ras_commander/CLAUDE.md conversion as it provides the template pattern for the others.

**Branch**: feature/hierarchical-knowledge
**Latest Commit**: dd0285c (LLM Forward integration)
**Ready for**: Phase 3 implementation
