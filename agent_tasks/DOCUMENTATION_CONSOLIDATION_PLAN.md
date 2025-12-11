# Documentation Consolidation Plan

**Created**: 2025-12-10
**Status**: Ready for Execution
**Scope**: Consolidate feature_dev_notes (13 folders), planning_docs (39 files), and tools (4 folders)

---

## Executive Summary

Analysis of ras-commander documentation reveals:
- **feature_dev_notes**: 13 folders with 60+ markdown docs, 30+ Python scripts, 3.1 GB test data
- **planning_docs**: 39 files (32+ precipitation investigation files) needing consolidation to ~10 active files
- **tools**: 4 projects including production GUI app, research scripts, and completed workflows

**Primary Issue**: Heavy redundancy in planning_docs (20+ precipitation files from single investigation), outdated content in feature_dev_notes (3 complete features still in research folder), scattered boundary analysis scripts.

**Goal**: Consolidate to clean structure, archive completed work, delete intermediate results, reduce cognitive load.

---

## Analysis Summary by Directory

### 1. feature_dev_notes/ (13 folders, 365 KB docs + 3.1 GB data)

**TIER 1: Complete & Integrated** (Archive candidates):
- ✅ **DSS** - Integrated into v0.82.0, 3.1 GB test data should be removed
- ✅ **HCFCD M3 Models** - Feature complete
- ✅ **formalizing_example_functions** - 64% complete, extract 9 pending items to roadmap

**TIER 2: Active Development** (Keep):
- ⏳ **RasMapper Interpolation** - 85% complete, validation ongoing
- ⏳ **cHECk-RAS** - Planning phase, 27K lines decompiled C#
- ⏳ **gauge_data_import** - Design complete, awaiting implementation
- ⏳ **National Water Model** - Research complete
- ⏳ **permutation_logic** - Documented, code in external project

**TIER 3: Investigate** (Unknown status):
- ❓ **floodway_analysis** - No documentation found
- ❓ **FEMA Frisel Agent** - No documentation found

**Issues**:
- Duplicate CLAUDE.md files across folders (consolidate to single root)
- 3.1 GB DSS test data still in folder (should be external/archived)
- Two folders lack documentation (floodway, FEMA)

---

### 2. planning_docs/ (39 files, 448 KB)

**Heavy Consolidation Needed - Precipitation Investigation** (32 files → 5 files):

**KEEP** (5 core files):
1. `PRECIPITATION_HDF_FORMAT_BREAKTHROUGH.md` (12 KB) - Key findings
2. `PRECIPITATION_FIX_CONSOLIDATED_SUMMARY.md` (8 KB) - Code fixes
3. `README_precipitation_investigation.md` (7 KB) - Index
4. `validate_precipitation_fix.py` (8 KB) - Active test
5. `DSS_SPATIAL_GRID_WRITING_RESEARCH.md` (35 KB) - Future work

**ARCHIVE** (15+ supporting analysis files):
- `precipitation_hdf_comparison.md`, `precipitation_hdf_format_from_decompilation.md`
- `PRECIPITATION_INVESTIGATION_FINAL_SUMMARY.md`, etc.
- All detailed analysis covered by BREAKTHROUGH document

**DELETE** (12+ intermediate/trivial files):
- `precipitation_comparison_full.txt` (30 KB raw output)
- `precipitation_comparison_output.txt`, `hdf_inspection_output.txt`
- `compare_hdf_files.py` (22 lines, trivial)
- `find_precipitation_data.py` (41 lines, trivial)
- `READTHEDOCS_NOTEBOOK_FIX.md` (superseded by _COMPLETE version)
- All `.txt` comparison outputs

**Other Files**:
- **MOVE**: `DECOMPILATION_REORGANIZATION_PLAN.md` → feature_dev_notes/
- **MOVE**: `example_projects.csv` → examples/
- **KEEP**: `DOCUMENTATION_REVISION_PLAN.md`, `HEC_COMMANDER_BLOG_EXTRACTION_PLAN.md`

**Net Result**: 39 files → 10-12 active files + archive folder

---

### 3. tools/ (4 folders + root files, ~3 MB)

**Production** (Keep):
- ✅ **1D Mannings to L-MC-R** - Git-tracked GUI application, production-ready

**Project Workflows** (Consolidate):
- ✅ **Model Updater - TP40 to Atlas 14** - Phase 5 complete, 20 task docs
  - ACTION: Archive task_docs/ to docs_old after final session
  - KEEP: Template models, working scripts as reference

**Utilities** (Clarify):
- ⏳ **DSS_Linker_Agent** - AGENTS.md documentation only
  - DECISION NEEDED: Move to feature_dev_notes or keep as utility?

**Research** (Archive):
- ~ **Boundary Analysis Scripts** (10 root-level files) - Tickfaw River research
  - ACTION: Organize into `Boundary_Analysis/` subfolder

**Cleanup**:
- ✗ **New folder** - Empty, delete

---

## Consolidation Actions

### Phase 1: Delete Intermediate Results (IMMEDIATE)

**planning_docs deletions** (12 files, ~62 KB):
```bash
# Raw comparison outputs
rm planning_docs/precipitation_comparison_full.txt
rm planning_docs/precipitation_comparison_output.txt
rm planning_docs/precipitation_structure_comparison.txt
rm planning_docs/hdf_inspection_output.txt
rm planning_docs/HDF_STRUCTURE_COMPARISON.txt

# Trivial scripts
rm planning_docs/compare_hdf_files.py
rm planning_docs/find_precipitation_data.py

# Superseded
rm planning_docs/READTHEDOCS_NOTEBOOK_FIX.md

# Duplicate comparison outputs
rm planning_docs/boundary_consistency_check.csv
rm planning_docs/boundary_summary_by_flow.csv
rm planning_docs/boundary_xsec_results.csv
rm planning_docs/proper_boundary_xsec_results.csv
```

**tools deletions** (1 folder):
```bash
rm -rf "tools/New folder"
```

**feature_dev_notes cleanup**:
```bash
# Remove 3.1 GB DSS test data (document location externally)
rm -rf feature_dev_notes/DSS/test_data/
```

**Total space freed**: ~3.2 GB

---

### Phase 2: Archive Completed Work (IMMEDIATE)

**Create archive structure**:
```bash
mkdir -p docs_old/completed_features
mkdir -p docs_old/precipitation_investigation
mkdir -p docs_old/model_updater_sessions
```

**Archive feature_dev_notes complete projects**:
```bash
# DSS feature (keep README as reference)
mv feature_dev_notes/DSS/ docs_old/completed_features/DSS/

# HCFCD M3 Models (feature complete)
mv feature_dev_notes/HCFCD_M3_Models/ docs_old/completed_features/HCFCD_M3_Models/

# Notebook analysis (extracted to roadmap)
mv feature_dev_notes/ex_notebook_updates/ docs_old/completed_features/ex_notebook_updates/
```

**Archive planning_docs precipitation supporting files**:
```bash
# Move 15+ supporting analysis files
mv planning_docs/precipitation_hdf_comparison.md docs_old/precipitation_investigation/
mv planning_docs/precipitation_hdf_format_from_decompilation.md docs_old/precipitation_investigation/
mv planning_docs/PRECIPITATION_INVESTIGATION_FINAL_SUMMARY.md docs_old/precipitation_investigation/
mv planning_docs/PRECIPITATION_IMPORT_FINDINGS.md docs_old/precipitation_investigation/
mv planning_docs/PRECIPITATION_FORMAT_ISSUES_FOUND.md docs_old/precipitation_investigation/
mv planning_docs/PRECIPITATION_HDF_ANALYSIS.md docs_old/precipitation_investigation/
mv planning_docs/precipitation_timestamp_analysis.md docs_old/precipitation_investigation/
mv planning_docs/precipitation_raster_attributes.md docs_old/precipitation_investigation/
mv planning_docs/precipitation_fixes_summary.md docs_old/precipitation_investigation/
mv planning_docs/PRECIPITATION_EXTENT_INVESTIGATION.md docs_old/precipitation_investigation/
mv planning_docs/HDF_COMPARISON_REPORT.md docs_old/precipitation_investigation/

# Archive supporting Python scripts
mv planning_docs/compare_precipitation_groups.py docs_old/precipitation_investigation/
mv planning_docs/compare_precipitation_implementation.py docs_old/precipitation_investigation/
mv planning_docs/analyze_netcdf_files.py docs_old/precipitation_investigation/
mv planning_docs/inspect_netcdf_detailed.py docs_old/precipitation_investigation/
mv planning_docs/inspect_precipitation_hdf.py docs_old/precipitation_investigation/
mv planning_docs/inspect_gdal_precipitation.py docs_old/precipitation_investigation/
mv planning_docs/check_empty_meteorology_groups.py docs_old/precipitation_investigation/
mv planning_docs/check_meteorology_attributes.py docs_old/precipitation_investigation/
mv planning_docs/find_gdal_precipitation.py docs_old/precipitation_investigation/
```

**Archive completed ReadTheDocs fix**:
```bash
mv planning_docs/READTHEDOCS_NOTEBOOK_FIX_COMPLETE.md docs_old/
```

---

### Phase 3: Reorganize Active Content (SHORT-TERM)

**Organize boundary analysis scripts**:
```bash
mkdir tools/Boundary_Analysis
mv tools/boundary_*.* tools/Boundary_Analysis/
mv tools/*_boundary*.py tools/Boundary_Analysis/
mv tools/check_crs.py tools/Boundary_Analysis/
mv tools/debug_boundaries.py tools/Boundary_Analysis/
mv tools/proper_boundary*.* tools/Boundary_Analysis/
```

**Move misplaced files**:
```bash
# Move to appropriate locations
mv planning_docs/DECOMPILATION_REORGANIZATION_PLAN.md feature_dev_notes/Decompilation_Agent/
mv planning_docs/example_projects.csv examples/
```

**Create index files**:
```bash
# Create README for planning_docs
# Create README for feature_dev_notes consolidation status
```

---

### Phase 4: Consolidate Documentation (MEDIUM-TERM)

**CLAUDE.md consolidation**:
- Multiple CLAUDE.md files exist in: cHECk-RAS, DSS, RasMapper, NWM, Decompilation Agent, gauge_data_import
- ACTION: Extract common guidance to `feature_dev_notes/CLAUDE.md` (root)
- Keep project-specific sections in subfolders

**Status tracking standardization**:
- Files use: README.md, FINAL_STATUS.md, SUCCESS.md, INTEGRATION_COMPLETE.md, MASTER_STATUS.md
- ACTION: Standardize on single STATUS.md format per project

---

## Recommended Final Structure

```
ras-commander/
├── feature_dev_notes/
│   ├── README.md (index of all projects)
│   ├── CLAUDE.md (consolidated guidance)
│   │
│   ├── ACTIVE/
│   │   ├── RasMapper_Interpolation/
│   │   ├── cHECk_RAS/
│   │   └── permutation_logic/
│   │
│   ├── PLANNING/
│   │   ├── gauge_data_import/
│   │   ├── National_Water_Model/
│   │   └── formalizing_example_functions/
│   │
│   └── TOOLKITS/
│       └── Decompilation_Agent/
│
├── planning_docs/
│   ├── README.md (index)
│   ├── ACTIVE/
│   │   ├── DSS_SPATIAL_GRID_WRITING_RESEARCH.md
│   │   ├── DOCUMENTATION_REVISION_PLAN.md
│   │   └── validate_precipitation_fix.py
│   │
│   └── COMPLETED/
│       ├── PRECIPITATION_HDF_FORMAT_BREAKTHROUGH.md
│       ├── PRECIPITATION_FIX_CONSOLIDATED_SUMMARY.md
│       └── README_precipitation_investigation.md
│
├── tools/
│   ├── 1D_Mannings_to_L-MC-R/ (production)
│   ├── Model_Updater_TP40_Atlas14/ (reference)
│   ├── DSS_Linker_Agent/ (utility)
│   └── Boundary_Analysis/ (research)
│
└── docs_old/
    ├── completed_features/
    │   ├── DSS/
    │   ├── HCFCD_M3_Models/
    │   └── ex_notebook_updates/
    ├── precipitation_investigation/ (20+ supporting files)
    ├── model_updater_sessions/ (future: task_docs archive)
    └── READTHEDOCS_NOTEBOOK_FIX_COMPLETE.md
```

---

## Execution Summary

### Files to DELETE (13 files, ~3.2 GB):
- 5 raw comparison .txt files
- 2 trivial Python scripts
- 1 superseded markdown
- 4 CSV boundary analysis outputs
- 1 empty "New folder"
- 3.1 GB DSS test data

### Files to ARCHIVE (30+ files):
- 3 complete feature folders (DSS, HCFCD, ex_notebook_updates)
- 20+ precipitation supporting analysis files
- 1 ReadTheDocs fix (complete)

### Files to KEEP in planning_docs (10 files):
- 5 precipitation core files
- 2 active planning docs (DSS, Documentation)
- 2 reference docs (blog extraction, HEC Commander)
- 1 test plan (verify completion)

### Files to REORGANIZE (15+ files):
- 10 boundary analysis scripts → tools/Boundary_Analysis/
- 2 planning docs → feature_dev_notes/
- 1 CSV → examples/

**Net Result**:
- planning_docs: 39 files → 10 active files
- feature_dev_notes: 13 folders → 7 active folders (6 archived)
- tools: Root clutter → organized subfolders
- ~3.2 GB disk space freed

---

## Verification Checklist

After execution:
- [ ] All intermediate .txt outputs deleted
- [ ] Trivial scripts (<50 lines) deleted
- [ ] DSS 3.1 GB test data removed (location documented)
- [ ] Completed features moved to docs_old/
- [ ] Precipitation supporting files (20+) archived
- [ ] Boundary analysis scripts organized into subfolder
- [ ] planning_docs reduced to ~10 active files
- [ ] Index READMEs created for navigation
- [ ] .gitignore updated if needed

---

## Next Steps

**After Execution**:
1. Investigate floodway_analysis and FEMA_Frisel_Agent (unknown status)
2. Decide DSS_Linker_Agent location (tools vs feature_dev_notes)
3. Archive Model Updater task_docs after next session
4. Create feature_dev_notes/CLAUDE.md (consolidated)
5. Update repository root README with documentation organization

**Status**: Ready to execute Phase 1-2 immediately
