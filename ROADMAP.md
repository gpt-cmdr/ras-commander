# ras-commander Roadmap

**Last Updated**: 2026-04-12

This document tracks forward-looking work for ras-commander.
Execution-level task tracking lives in `agent_tasks/.agent/BACKLOG.md`.
Use this file for roadmap direction, not for stale feature requests that are
already implemented.

## Roadmap Snapshot

### Recently Landed and Removed from Future Roadmap

- UNC mapped-drive path preservation via `RasUtils.safe_resolve()`
  - Implemented on 2026-01-08
- Storage area polygon extraction from plain text and HDF
  - Commit: `fdf7dd0f`
- Backup-based safe deletion for `RasPlan.delete_*()` workflows
  - Commit: `35a7979d`

### Current Roadmap Tiers

1. **Near-term integration and stabilization**
   - Reconcile diverged branches and remove documentation/index drift
2. **Medium-term productization**
   - Clarify DataFrame-first execution behavior, strengthen docs, add tests
3. **Long-horizon feature development**
   - Build new capabilities not yet implemented anywhere in the repo

## Near-Term Integration and Stabilization

### 1. Calibration Branch Reconciliation

**Status**: Active  
**Branch**: `feat/ras-calibrate`

**Why this is first**:
- The branch is 5 commits ahead and 4 commits behind local `main` as of
  2026-04-12.
- `main` contains calibration-adjacent and eBFE/documentation changes that the
  branch does not have.
- The branch also carries notebooks and integration notes that should not be
  lost.

**Open work**:
- Rebase or replay `feat/ras-calibrate` onto current `main`
- Re-run notebooks `220` and `221`
- Resolve the `RasCalibrate` redesign vs revert split cleanly
- Confirm `depth_datum` behavior and `force_geompre` propagation
- Freeze the intended merge scope in `INTEGRATION.md`

**Exit criteria**:
- Branch is based on current `main`
- Notebook-backed validation passes
- Merge scope is explicit
- User-facing docs are aligned with the kept API

### 2. Monte Carlo Branch Integration

**Status**: Implemented on branch, not merged  
**Branch**: `feat/ras-montecarlo`

**Existing branch artifacts**:
- `d40032c9` - initial `RasMonteCarlo`
- `f052bb1d` - redesigned general-purpose uncertainty analysis
- `3b11f22e` - notebook `116_monte_carlo_uncertainty.ipynb`

**Open work**:
- Rebase/replay onto current `main`
- Verify `from ras_commander import RasMonteCarlo`
- Run notebook `116` against a real HEC-RAS project
- Capture merge-gate evidence before merge

**Exit criteria**:
- Branch imports cleanly on current `main`
- Notebook `116` runs end-to-end
- Merge evidence is archived

### 3. Floodway Branch Integration

**Status**: Implemented on branch, not merged  
**Branch**: `feat/floodway-analysis`

**Existing branch artifacts**:
- `db992a43` - Phase 1 floodway compliance checking
- `1a2394ae` - parametric surcharge limit + notebook
  `432_floodway_compliance_analysis.ipynb`

**Open work**:
- Rebase/replay onto current `main`
- Verify `RasFloodway` export/import behavior on the rebased branch
- Run notebook `432` with real HDF inputs
- Capture merge-gate evidence before merge

**Exit criteria**:
- Branch rebases cleanly
- Notebook `432` is verified on current code
- Merge evidence is archived

### 4. Documentation and Knowledge Index Sync

**Status**: Active

**Why it matters**:
- Agents and users are now more likely to be misdirected by stale docs than by
  unknown code.
- The docs site, `.claude` index layer, and root guidance files no longer
  match the live repository.

**Open work**:
- Sync `docs/notebooks/` and `mkdocs.yml` to the actual `examples/*.ipynb`
  inventory
- Remove generated docs for notebooks that no longer exist
- Fix root `AGENTS.md` references to missing top-level documents
- Update `.claude/skills/README.md`, `.claude/rules/README.md`, and
  `.claude/MANIFEST.md` to match the live skills/rules inventory
- Finish stale branch cleanup after the wine-fix merge

**Exit criteria**:
- Notebook docs and nav reflect only live notebooks
- `.claude` README/manifest indexes match the actual tree
- Root guidance points only to live files
- Merged/obsolete branches are cleaned up

## Medium-Term Productization

### 1. DataFrame-First Execution Clarity

**Status**: Planned

The next architecture pass should make execution behavior easier to reason
about and easier to teach.

**Open work**:
- Audit `compute_plan`, `compute_parallel`, `compute_test_mode`, and
  `compute_parallel_remote`
- Document when `plan_df` and `results_df` refresh automatically vs when the
  caller must refresh or re-query
- Confirm there is no remaining folder-path drift after the `[Computed]`
  default removal and the 2026-04-10 alias/geompre fixes
- Audit example notebooks for glob/path anti-patterns

**Potential follow-on**:
- Add a DataFrame navigator agent or skill for answering:
  - where HDF results live
  - how geometry and boundary metadata are exposed
  - what the major DataFrames/GeoDataFrames contain

### 2. eBFE Public Catalog Documentation

**Status**: Planned

The repo now has enough research to document the public BLE/eBFE discovery
path, but the knowledge is not yet packaged for normal users.

**Open work**:
- Turn `.claude/outputs/calibration-research/2026-04-10-ble-s3-research.md`
  into user-facing docs
- Align `.claude/skills/ebfe_crawl_s3-catalog/SKILL.md` with the validated
  discovery workflow
- Add a discoverability section to `docs/ebfe_models.md`
- Clarify how study enumeration works when bucket listing is unavailable

### 3. Test and Notebook Hardening

**Status**: Planned

**Open work**:
- Add an integration test covering all four HMS-derived precipitation methods
- Add DSS direct-write coverage in the precipitation workflow docs/notebooks
- Add parallel execution examples where that improves real workflows

## Long-Horizon Feature Development

These items are still genuine roadmap work. They are not implemented on the
current branch or on known feature branches.

### 1. 1D Benefit Areas Analysis

**Status**: Proposed  
**Priority**: Medium

**Goal**:
Extend benefit-area analysis to 1D cross-section models, not just 2D mesh
results.

**Current state**:
- 2D mesh benefit areas already exist via
  `HdfBenefitAreas.identify_benefit_areas()`
- 1D cross-section benefit areas do not yet exist

**Likely API direction**:

```python
HdfBenefitAreas.identify_benefit_areas_1d(
    existing_hdf_path,
    proposed_hdf_path,
    min_delta=0.1,
    interpolation_method="linear",
    ras_object=None,
)
```

**Key design problems**:
- Converting line-based cross sections into reviewable polygons
- Aggregating contiguous reaches into benefit/rise segments
- Handling mixed 1D/2D projects without confusing the sign conventions

**Dependencies**:
- `HdfResultsXsec`
- `HdfXsec`
- A clear interpolation/polygonization strategy

**Success criteria**:
- Reach-level benefit/rise outputs are reviewable in GIS
- Sign convention matches the existing 2D benefit-area workflow
- Mixed-model behavior is explicit and documented

### 2. Atlas 14 Gridded AEP Events for HEC-RAS

**Status**: Proposed  
**Priority**: Medium

**Goal**:
Create a direct gridded Atlas 14 design-storm path for HEC-RAS using the same
kind of NetCDF workflow that already exists for AORC.

**Current state**:
- Atlas 14 depth-grid extraction exists
- AORC gridded precipitation workflows exist
- No direct Atlas 14 gridded export path exists for HEC-RAS design storms

**Planned approach**:
1. Extract Atlas 14 depth grids for the project extent
2. Apply a temporal distribution such as `Atlas14Storm` or `FrequencyStorm`
3. Write NetCDF in a HEC-RAS-compatible gridded precipitation structure
4. Configure the unsteady boundary via `RasUnsteady.set_gridded_precipitation`

**Explicit non-goals**:
- Do not revive placeholder hydrograph-to-gridded conversion helpers
- Keep this as a direct gridded-design-storm workflow

**Success criteria**:
- End-to-end notebook-backed demonstration with a real model
- Output structure matches the proven AORC pathway
- Documentation clearly distinguishes hyetograph vs gridded workflows

### 3. Automated Lateral BC Creation from USGS Gauge Locations

**Status**: Proposed  
**Priority**: Medium-High

**Goal**:
Automate creation of SA/2D lateral boundary conditions near tributary gauges
for multi-gauge validation workflows.

**Motivating use case**:
- Notebook `915` style validation setups with several tributary inflows
- Reduce manual HEC-RAS geometry editing for lateral inflow creation

**Likely API direction**:

```python
RasGeometry2D.create_lateral_bc_from_gauge(
    geom_file,
    gauge_id,
    gauge_lat,
    gauge_lon,
    num_faces=20,
    offset_distance=50.0,
    trim_percent=7.5,
    bc_name=None,
    add_to_unsteady=False,
    unsteady_file=None,
    validate_geometry=True,
    ras_object=None,
)
```

**Implementation phases**:
1. Extract and query external mesh faces
2. Convert candidate faces into a continuous boundary line
3. Offset and trim the line safely
4. Write the geometry-file SA/2D connection entry
5. Optionally wire the boundary into the unsteady file
6. Validate in GUI and notebook workflows

**Key technical challenges**:
- Ordering faces into a continuous line
- Determining the correct outward offset direction
- Preserving HEC-RAS fixed-width geometry formatting
- Ensuring the generated connection is valid and external to the mesh
- Handling CRS/unit conversions correctly

**Success criteria**:
- A valid SA/2D connection can be created from gauge coordinates quickly
- The result loads in HEC-RAS without geometry errors
- Multi-gauge validation setup becomes minutes instead of hours

## Roadmap Hygiene Rules

- If work is already implemented, remove it from the future roadmap and record
  it in `agent_tasks/.agent/PROGRESS.md` instead.
- If work exists only on a branch, classify it as integration/verification
  work, not as greenfield feature work.
- Keep `ROADMAP.md` aligned with `agent_tasks/.agent/BACKLOG.md`; the roadmap
  should summarize direction, while the backlog should track execution detail.
