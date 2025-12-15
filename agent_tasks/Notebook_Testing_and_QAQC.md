# Notebook Testing and QAQC Plan

**Purpose**: Systematic testing of all example notebooks using notebook-runner subagent
**Environment**: `rascmdr_piptest` (pip-installed package, no local sideload)
**Execution**: One notebook at a time, sequentially
**Created**: 2025-12-15

---

## Testing Methodology

### Environment Configuration
- **Conda Environment**: `rascmdr_piptest`
- **Package Source**: Published pip package (`pip install ras-commander`)
- **Toggle Cell Setting**: `USE_LOCAL_SOURCE = False` (CRITICAL)
- **Python Version**: 3.13
- **HEC-RAS Version**: 6.6 (when execution required)

### Execution Approach
1. **Sequential Testing**: One notebook at a time to avoid resource conflicts
2. **Clean Execution**: Restart kernel before each notebook run
3. **Timing Capture**: Record execution time for each notebook
4. **Output Review**: notebook-runner subagent performs QAQC review
5. **Issue Logging**: Document any errors, warnings, or anomalies

### Success Criteria
- ✅ **PASS**: Notebook completes without errors, outputs are valid
- ⚠️ **WARNING**: Notebook completes but has minor issues (warnings, deprecated features)
- ❌ **FAIL**: Notebook fails to complete or produces invalid outputs
- ⏸️ **SKIP**: Notebook requires resources not available (remote workers, specific data)

---

## Notebook Test Tracking

### Category 1: Core / Getting Started (Notebooks 00-09)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 1 | `00_Using_RasExamples.ipynb` | ✅ PASS | ~1 sec | All 14 cells executed, no errors. Verified pip package 0.87.4 loads correctly. [Details](.claude/outputs/notebook-runner/2025-12-15-00_Using_RasExamples-test.md) |
| 2 | `01_project_initialization.ipynb` | ✅ PASS | ~13 sec | 15/15 cells executed. Tested project extraction, initialization, multi-project mode, RASMapper parsing. [Details](.claude/outputs/notebook-runner/2025-12-15-01_project_initialization-test.md) |
| 3 | `02_plan_and_geometry_operations.ipynb` | ✅ PASS (after fix) | ~9 sec | Cell 23: Path import FIXED and verified. Fix confirmed through static and dynamic testing. ALSO NOTE: Using `example_projects_02_...` instead of suffix param (requires revision). [Details](../working/notebook_runs/2025-12-15-02_plan_and_geometry_operations-RETEST.md) |
| 4 | `03_unsteady_flow_operations.ipynb` | ✅ PASS | Fast (data parsing only) | 40 cells executed, 0 errors. Demonstrates unsteady flow initialization, boundary conditions, time series extraction. [Details](.claude/outputs/notebook-runner/2025-12-15-03_unsteady_flow_operations-test.md) |
| 5 | `04_multiple_project_operations.ipynb` | ✅ PASS (after 4 fixes) | ~2 min | 26 cells executed, 0 errors. FIXES: (1) suffix="04" parameter, (2) cell ordering (paths moved Cell 2→Cell 5), (3) RasExamples static call, (4) f-string syntax. [Analysis](.claude/outputs/notebook-runner/2025-12-15-04_cell_ordering_fix.md) [Retest](.claude/outputs/notebook-runner/2025-12-15-04_multiple_project_operations-RETEST.md) |
| 6 | `05_single_plan_execution.ipynb` | ✅ PASS | ~10-15 min | 11 cells executed, 0 errors. Demonstrates RasCmdr.compute_plan() with parameter control. HDF output validated (BaldEagle.p01.hdf, 7.5 MB). [Details](.claude/outputs/notebook-runner/2025-12-15-05_single_plan_execution-test.md) |
| 7 | `06_executing_plan_sets.ipynb` | ✅ PASS | ~3 sec | 13 cells, 0 errors. Parallel plan set execution with RasCmdr.compute_parallel(). [Details](.claude/outputs/notebook-runner/2025-12-15-06_executing_plan_sets-test.md) |
| 8 | `07_sequential_plan_execution.ipynb` | ✅ PASS (after fix) | ~3.5 min | FIXED: Inserted extraction code cell (Cell 3) with `RasExamples.extract_project("Balde Eagle Creek", suffix="07")`. 18 cells executed, 0 errors. Sequential execution validated (2 complete runs, 4 plans total). [Details](.claude/outputs/notebook-runner/2025-12-15-07_sequential_plan_execution-RETEST.md) |
| 9 | `08_parallel_execution.ipynb` | ⏳ PENDING | - | Parallel local execution |
| 10 | `09_plan_parameter_operations.ipynb` | ⏳ PENDING | - | Plan parameter modification |

### Category 2: HDF Data Extraction (Notebooks 10-19)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 11 | `10_1d_hdf_data_extraction.ipynb` | ⏳ PENDING | - | 1D cross section results |
| 12 | `11_2d_hdf_data_extraction.ipynb` | ⏳ PENDING | - | 2D mesh results |
| 13 | `12_2d_hdf_data_extraction pipes and pumps.ipynb` | ⏳ PENDING | - | Pipes and pumps (HEC-RAS 6.6+) |
| 14 | `13_2d_detail_face_data_extraction.ipynb` | ⏳ PENDING | - | 2D detailed face data |
| 15 | `14_fluvial_pluvial_delineation.ipynb` | ⏳ PENDING | - | Fluvial vs pluvial analysis |
| 16 | `18_breach_results_extraction.ipynb` | ⏳ PENDING | - | Dam breach results |
| 17 | `19_steady_flow_analysis.ipynb` | ⏳ PENDING | - | Steady flow analysis |

### Category 3: Mapping (Notebooks 15 series)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 18 | `15_a_floodplain_mapping_gui.ipynb` | ⏳ PENDING | - | GUI-based mapping |
| 19 | `15_b_floodplain_mapping_rasprocess.ipynb` | ⏳ PENDING | - | RasProcess mapping |
| 20 | `15_c_floodplain_mapping_python_gis.ipynb` | ⏳ PENDING | - | Python GIS mapping |
| 21 | `15_stored_map_generation.ipynb` | ⏳ PENDING | - | Stored map generation |
| 22 | `26_rasprocess_stored_maps.ipynb` | ⏳ PENDING | - | RasProcess stored maps |

### Category 4: Advanced Features (Notebooks 20-33)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 23 | `20_plaintext_geometry_operations.ipynb` | ⏳ PENDING | - | Plain text geometry parsing |
| 24 | `21_dss_boundary_extraction.ipynb` | ⏳ PENDING | - | DSS boundary data (duplicate?) |
| 25 | `22_dss_boundary_extraction.ipynb` | ⏳ PENDING | - | DSS boundary data (duplicate?) |
| 26 | `22_remote_execution_psexec.ipynb` | ⏳ PENDING | - | Remote execution (may skip) |
| 27 | `23_remote_execution_psexec.ipynb` | ⏳ PENDING | - | Remote execution (duplicate?) |
| 28 | `24_1d_boundary_condition_visualization.ipynb` | ⏳ PENDING | - | 1D BC visualization |
| 29 | `24_aorc_precipitation.ipynb` | ⏳ PENDING | - | AORC precipitation |
| 30 | `27_fixit_blocked_obstructions.ipynb` | ⏳ PENDING | - | RasFixit geometry repair |
| 31 | `28_quality_assurance_rascheck.ipynb` | ⏳ PENDING | - | RasCheck QA framework |
| 32 | `29_usgs_gauge_data_integration.ipynb` | ⏳ PENDING | - | USGS gauge integration |
| 33 | `30_usgs_real_time_monitoring.ipynb` | ⏳ PENDING | - | USGS real-time monitoring |
| 34 | `31_bc_generation_from_live_gauge.ipynb` | ⏳ PENDING | - | BC generation from USGS |
| 35 | `31_bc_generation_from_live_gauge_executed.ipynb` | ⏳ PENDING | - | BC generation (executed version) |
| 36 | `32_model_validation_with_usgs.ipynb` | ⏳ PENDING | - | Model validation with USGS |
| 37 | `33_gauge_catalog_generation.ipynb` | ⏳ PENDING | - | Gauge catalog generation |

### Category 5: Sensitivity Analysis (100 series)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 38 | `101_Core_Sensitivity.ipynb` | ⏳ PENDING | - | CPU core sensitivity analysis |
| 39 | `102_benchmarking_versions_6.1_to_6.6.ipynb` | ⏳ PENDING | - | Version benchmarking |
| 40 | `103_Running_AEP_Events_from_Atlas_14.ipynb` | ⏳ PENDING | - | Atlas 14 AEP events |
| 41 | `103b_Atlas14_Caching_Demo.ipynb` | ⏳ PENDING | - | Atlas 14 caching |
| 42 | `104_Atlas14_AEP_Multi_Project.ipynb` | ⏳ PENDING | - | Atlas 14 multi-project |
| 43 | `105_mannings_sensitivity_bulk_analysis.ipynb` | ⏳ PENDING | - | Manning's n bulk sensitivity |
| 44 | `106_mannings_sensitivity_multi-interval.ipynb` | ⏳ PENDING | - | Manning's n multi-interval |

### Category 6: Quality Assurance (200-300 series)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 45 | `200_fixit_blocked_obstructions.ipynb` | ⏳ PENDING | - | RasFixit blocked obstructions |
| 46 | `300_quality_assurance_rascheck.ipynb` | ⏳ PENDING | - | RasCheck QA (duplicate?) |

### Category 7: Precipitation (400 series)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 47 | `400_aorc_precipitation_catalog.ipynb` | ⏳ PENDING | - | AORC precipitation catalog |

### Category 8: USGS Integration (420 series)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 48 | `420_usgs_gauge_catalog.ipynb` | ⏳ PENDING | - | USGS gauge catalog |
| 49 | `421_usgs_gauge_data_integration.ipynb` | ⏳ PENDING | - | USGS gauge integration |
| 50 | `422_usgs_real_time_monitoring.ipynb` | ⏳ PENDING | - | USGS real-time monitoring |
| 51 | `423_bc_generation_from_live_gauge.ipynb` | ⏳ PENDING | - | BC generation from gauge |
| 52 | `424_model_validation_with_usgs.ipynb` | ⏳ PENDING | - | Model validation with USGS |

### Category 9: Legacy/COM Interface (16-17)

| # | Notebook | QAQC Status | Execution Time | Notes |
|---|----------|-------------|----------------|-------|
| 53 | `16_automating_ras_with_win32com.ipynb` | ⏳ PENDING | - | Legacy COM interface |
| 54 | `17_extracting_profiles_with_hecrascontroller and RasControl.ipynb` | ⏳ PENDING | - | HEC-RAS Controller API |

---

## Test Execution Instructions

### For Orchestrator

**Delegation Pattern**:
```python
Task(
    subagent_type="notebook-runner",
    model="haiku",  # Fast execution
    prompt="""
    Test notebook: examples/{notebook_name}.ipynb

    Requirements:
    - Environment: rascmdr_piptest (conda activate rascmdr_piptest)
    - Toggle cell: USE_LOCAL_SOURCE = False (CRITICAL)
    - Execute: jupyter nbconvert --to notebook --execute --inplace {notebook_name}.ipynb
    - Capture: Execution time, error status, output validity

    Context files:
    - agent_tasks/Notebook_Testing_and_QAQC.md (this file)

    Task:
    1. Activate rascmdr_piptest environment
    2. Navigate to examples/ directory
    3. Verify toggle cell is set to False
    4. Execute notebook
    5. Review outputs for errors/warnings
    6. Record timing and status

    Write findings to: .claude/outputs/notebook-runner/{date}-{notebook_name}-test.md
    Update: agent_tasks/Notebook_Testing_and_QAQC.md with status

    Return: File path to findings and summary status
    """
)
```

### For notebook-runner Subagent

**Pre-execution Checklist**:
1. ✅ Conda environment `rascmdr_piptest` activated
2. ✅ Current directory is `examples/`
3. ✅ Notebook toggle cell verified: `USE_LOCAL_SOURCE = False`
4. ✅ HEC-RAS 6.6 available (if execution required)
5. ✅ No other notebooks running (avoid resource conflicts)

**Execution Command**:
```bash
conda activate rascmdr_piptest
cd C:\GH\ras-commander\examples
jupyter nbconvert --to notebook --execute --inplace {notebook_name}.ipynb --ExecutePreprocessor.timeout=3600
```

**Post-execution Review**:
1. Check for execution errors in notebook outputs
2. Validate expected outputs exist (plots, dataframes, files)
3. Review any warnings or deprecation messages
4. Capture execution time from nbconvert output
5. Update this tracking document with status

**Status Update Format**:
Replace `⏳ PENDING` with:
- `✅ PASS` - Clean execution, valid outputs
- `⚠️ WARNING` - Completes with warnings (document in Notes)
- `❌ FAIL` - Execution error (document in Notes)
- `⏸️ SKIP` - Cannot test (missing resources, document reason)

---

## Identified Issues

### Pattern Issue: Inconsistent Example Project Folder Naming

**CRITICAL PATTERN BUG** found across multiple notebooks:

**Problem**: Notebooks are creating custom-named folders like `example_projects_02_plan_and_geometry_operations/` instead of using the standardized `suffix` parameter in `RasExamples.extract_project()`.

**Incorrect Pattern** (found in notebooks 02, 04, and likely others):
```python
# ❌ WRONG - creates custom folder names
RasExamples.extract_project("Muncie", output_path="example_projects_02_plan_and_geometry_operations")
```

**Correct Pattern** (using suffix parameter):
```python
# ✅ CORRECT - uses suffix parameter
RasExamples.extract_project("Muncie", suffix="02")
# Results in: example_projects/Muncie-02/
```

**Affected Notebooks** (confirmed so far):
- `02_plan_and_geometry_operations.ipynb` - uses `example_projects_02_plan_and_geometry_operations/`
- `04_multiple_project_operations.ipynb` - uses `example_projects_04_multiple_project_operations/`

**Impact**:
- Inconsistent folder structure across notebooks
- Defeats purpose of suffix parameter feature
- Makes cleanup harder (multiple top-level folders)
- Not following library best practices

**Fix Required**: Update all notebooks to use `suffix` parameter instead of custom `output_path`.

### Known Duplicates
- `21_dss_boundary_extraction.ipynb` and `22_dss_boundary_extraction.ipynb` (investigate)
- `22_remote_execution_psexec.ipynb` and `23_remote_execution_psexec.ipynb` (investigate)
- `28_quality_assurance_rascheck.ipynb` and `300_quality_assurance_rascheck.ipynb` (investigate)
- `29_usgs_gauge_data_integration.ipynb` and `421_usgs_gauge_data_integration.ipynb` (investigate)
- `31_bc_generation_from_live_gauge.ipynb` and `31_bc_generation_from_live_gauge_executed.ipynb` (variants?)

### Notebooks Likely to be Skipped
- Remote execution notebooks (require remote workers configured)
- Notebooks requiring external API keys or credentials
- Notebooks requiring large datasets not in examples

---

## Progress Summary

**Total Notebooks**: 54
**Tested**: 8
**Passed**: 8
**Warnings**: 0
**Failed**: 0
**Skipped**: 0

**Estimated Total Time**: TBD (will calculate after first 10 notebooks)
**Completion**: 14.8% (8/54)
**Average Time per Notebook**: ~6.5 sec (excluding compute-heavy notebooks like 05 which took 10-15 min)

---

## Session Log

### Session 1: 2025-12-15
- **Orchestrator**: Created testing plan and tracking document
- **Next**: Begin sequential testing starting with Category 1 (Core notebooks)

---

## Notes

- **Toggle Cell Critical**: All notebooks MUST have `USE_LOCAL_SOURCE = False` for pip package testing
- **Resource Management**: Some notebooks may create large files (clean up between tests)
- **HEC-RAS Dependency**: Notebooks 05-09 require HEC-RAS 6.6 installed and functional
- **Internet Dependency**: USGS and AORC notebooks require internet connectivity
- **Execution Time**: Long-running notebooks (100 series) may take hours - plan accordingly

---

**Last Updated**: 2025-12-15 (Plan created, testing not yet started)
