# RAS-Commander Development Backlog

## High Priority

### Core Architecture & DataFrame Discipline

- [x] **arch-breaking-001** Remove [Computed] Folder Default Behavior ✅ COMPLETED (2026-01-08)
  - **BREAKING CHANGE** implemented in v0.88.1
  - **SCOPE**: `RasCmdr.compute_parallel()` and `compute_test_mode()` (local execution)
  - **Changes Made**:
    - `compute_parallel()`: Consolidates results directly to original folder (no [Computed] folder created when dest_folder=None)
    - `compute_test_mode()`: Copies HDF files back to original folder after execution, removes [Test] folder
    - Documentation updated in `.claude/rules/python/dataframe-first-principle.md`
    - Bug 3 marked as FIXED in `.claude/rules/documentation/precipitation-notebook-debugging-patterns.md`
  - **Result**: plan_df automatically has correct HDF paths after execution - no re-initialization needed
  - **Notebooks**: Old workaround code still works (falls back to original folder when [Computed] not found) - can be cleaned up incrementally

- [ ] **arch-df-001** DataFrame Update Audit (2026-01-07)
  - Review ALL compute_* functions (compute_plan, compute_parallel, compute_test_mode, compute_parallel_remote)
  - Ensure plan_df is refreshed after execution
  - Fix inconsistency: compute_parallel creates [Computed] folder but updates plan_df for original folder
  - Add logic to return final execution folder path so notebooks can re-initialize correctly
  - Document when DataFrame refresh is needed vs automatic
  - **Priority**: CRITICAL - affects reliability of all automation workflows
  - **Effort**: 4-6 hours
  - **See**: `.claude/rules/python/dataframe-first-principle.md`

- [ ] **arch-df-002** Enhanced geom_df Metadata Columns (2026-01-07)
  - Add geometry type detection columns to geom_df:
    - `has_1d_xs` (bool) - Contains 1D cross sections
    - `has_2d_mesh` (bool) - Contains 2D mesh
    - `num_cross_sections` (int) - Count of 1D cross sections
    - `num_inline_structures` (int) - Bridges, culverts, gates, weirs in main channel
    - `num_lateral_structures` (int) - Lateral structures
    - `num_bridges` (int) - Bridge count
    - `num_culverts` (int) - Culvert count
    - `num_gates` (int) - Gate count
    - `num_weirs` (int) - Weir count
    - `num_sa_2d_connections` (int) - Storage Area to 2D connections
    - `mesh_cell_count` (int) - Total 2D mesh cells
    - `mesh_area_names` (list[str]) - Names of 2D flow areas
  - Parse from geometry HDF (.g##.hdf) if available, else parse plain text
  - Provides project overview at a glance for users/agents
  - **Priority**: HIGH - significantly improves usability
  - **Effort**: 8-12 hours
  - **See**: `ras_commander/geom/AGENTS.md`, `ras_commander/hdf/HdfMesh.py`

### Precipitation Workflows

- [x] **gridded-precip-001** Create Gridded Atlas 14 Storm Notebook (2026-01-03)
  - Created `examples/722_gridded_precipitation_atlas14.ipynb`
  - Uses `BaldEagleCrkMulti2D` project with 2D mesh analysis
  - Demonstrates all HMS methods (Atlas14Storm, FrequencyStorm, ScsTypeStorm)
  - Includes spatial variance assessment with Atlas14Variance
  - Documents future conversion function workflow (placeholder)

- [ ] **gridded-precip-002** Implement Hydrograph to Gridded Precipitation Conversion
  - Function: `convert_hydrograph_to_gridded(hyeto, mesh_cells, spatial_pattern)`
  - Function: `convert_gridded_to_hydrograph(gridded_precip, reduction_method)`
  - Allow comparison of uniform vs distributed precipitation impacts
  - **Dependencies**: gridded-precip-001
  - **Effort**: 6-8 hours

- [ ] **gridded-precip-003** Implement Gridded to Hydrograph Conversion
  - Extract spatial average from gridded precipitation
  - Multiple reduction methods (mean, max, area-weighted)
  - Validate depth conservation
  - **Dependencies**: gridded-precip-002
  - **Effort**: 4-6 hours

## Medium Priority

### DataFrame Discipline & Knowledge Systems

- [ ] **arch-df-003** Example Notebook DataFrame Audit (2026-01-07)
  - Audit ALL example notebooks for anti-patterns:
    - Glob patterns for finding HDF files
    - Manual path construction
    - Missing DataFrame refresh after execution
  - Replace with plan_df/geom_df lookups (authoritative source)
  - Add notebook cells demonstrating DataFrame best practices
  - Ensure optimal behavior is demonstrated in all examples
  - **Priority**: MEDIUM - improves documentation quality
  - **Effort**: 6-8 hours
  - **See**: `.claude/rules/python/dataframe-first-principle.md`

- [ ] **arch-df-004** DataFrame Navigator Agent/Skill (2026-01-07)
  - Create agent or skill: `/dataframe-guide` or `dataframe-navigator` subagent
  - Provides quick reference for finding data in ras-commander DataFrames
  - Answers queries like:
    - "Where are HDF files?" → `ras.plan_df['HDF_Results_Path']`
    - "How do I find geometry file?" → `ras.geom_df.loc[geom_num, 'file_path']`
    - "What plans are available?" → `ras.plan_df[['plan_number', 'Plan Title']]`
    - "Which geometries have 2D meshes?" → `ras.geom_df[ras.geom_df['has_2d_mesh']]` (after arch-df-002)
  - Includes guidance on when to refresh DataFrames
  - References all DataFrame columns and their meanings
  - **Priority**: MEDIUM - helps users/agents navigate library
  - **Effort**: 4-6 hours
  - **Dependencies**: arch-df-002 (enhanced geom_df)

### Documentation

- [ ] **docs-001** Update Examples README with New Notebook Organization
  - Document 720 (methods), 721 (hydrograph BC), 722 (gridded precip), 725 (spatial variance)
  - Archive references to old 720-724 notebooks
  - **Dependencies**: None
  - **Effort**: 1 hour

### Testing

- [ ] **test-001** Create Integration Test for All Precipitation Methods
  - Test file: `tests/test_precipitation_complete.py`
  - Verify all 4 HMS methods import and generate
  - Test depth conservation for each method
  - **Dependencies**: None
  - **Effort**: 2-3 hours

## Low Priority

### Enhancements

- [ ] **precip-enhance-001** Add DSS Direct Write to Workflow Notebook
  - Write hyetographs directly to DSS files
  - Use RasDss.write_timeseries()
  - Demonstrate boundary condition setup
  - **Dependencies**: None
  - **Effort**: 2-3 hours

- [ ] **precip-enhance-002** Add Parallel Execution Mode
  - Use RasCmdr.compute_parallel() instead of sequential
  - Speed up bulk execution for large storm suites
  - **Dependencies**: None
  - **Effort**: 2-3 hours

## Completed

- [x] **precip-001** Integrate FrequencyStorm from hms-commander (2026-01-03)
- [x] **precip-002** Implement SCS Type Distributions (I, IA, II, III) (2026-01-03)
- [x] **precip-003** Implement Multi-Duration Atlas 14 (6h, 12h, 24h, 96h) (2026-01-03)
- [x] **precip-004** Create Comprehensive Method Comparison Notebook (720) (2026-01-03)
- [x] **precip-005** Create Comprehensive Workflow Notebook (721) (2026-01-03)
- [x] **precip-006** Update Documentation with TP-40 Terminology (2026-01-03)
- [x] **gridded-precip-001** Create Gridded Atlas 14 Storm Notebook (2026-01-03)

---

## Critical Knowledge Captured (2026-01-07 Session)

**DataFrame-First Principle**: All file path resolution and metadata queries should use ras-commander DataFrames as the single source of truth. Never use glob patterns or manual path construction. After execution, plan_df is automatically refreshed and HDF files are in the original project folder.

**[Computed] Folder Anti-Pattern - FIXED (2026-01-08)**: The default behavior of creating separate [Computed] folders in `compute_parallel()` was identified as a design mistake. **This has been fixed in v0.88.1** - both `compute_parallel()` and `compute_test_mode()` now consolidate HDF results back to the original project folder. No re-initialization needed.

**Documented in**:
- `.claude/rules/python/dataframe-first-principle.md` (NEW - comprehensive guidance)
- Updated `.claude/rules/documentation/precipitation-notebook-debugging-patterns.md` (already had partial guidance)

**Roadmap Items Added**:
- arch-df-001: DataFrame Update Audit (HIGH priority)
- arch-df-002: Enhanced geom_df Metadata (HIGH priority)
- arch-df-003: Example Notebook DataFrame Audit (MEDIUM priority)
- arch-df-004: DataFrame Navigator Agent/Skill (MEDIUM priority)

---

**Last Updated**: 2026-01-08
