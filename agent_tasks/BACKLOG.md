# RAS-Commander Development Backlog

## High Priority

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

**Last Updated**: 2026-01-03
