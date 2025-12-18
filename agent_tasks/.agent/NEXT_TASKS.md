# Next Tasks - Notebook QAQC Completion

**Created**: 2025-12-17
**Context**: Completed testing all 46 notebooks, deployed v0.87.6 with timezone fix
**Status**: 37/46 passing, 6 blocked (need fixes), 3 require manual intervention

---

## Current State (as of 2025-12-17 after v0.87.6)

### Successfully Completed ✅
- ✅ ras-commander v0.87.6 deployed to PyPI
- ✅ Test environment updated to v0.87.6
- ✅ Notebook 101 path fix (suffix="101") - TIMEOUT EXPECTED (15-30 min HEC-RAS)
- ✅ Notebook 300 API fix (TransitionCoefficientThresholds attributes) - NOW PASSING
- ✅ Notebook 422 timezone fix verified working - TIMEOUT EXPECTED (infinite monitoring loop)
- ✅ Notebooks 420, 423 Path import fixes
- ✅ Notebooks 16, 17 COM automation fixes
- ✅ Notebooks 200 Path import fixed
- ✅ All changes committed to git (commit ca5e77f)

### Test Results Summary
- **Total Notebooks**: 46
- **Passing**: 38 (83%)
- **Blocked/Timeout**: 5 (11%)
  - 101: Expected timeout (benchmarking)
  - 200: Missing M3 model data
  - 400: Expected timeout (storm simulations)
  - 422: Expected timeout (infinite monitoring)
  - 15a: GUI required
- **Fixes Applied**: 18 notebooks

### Remaining Issue (Only 1)

**Notebook 200** (RasFixit Blocked Obstructions):
- Path import bug FIXED ✅
- Missing A120-00-00 HCFCD M3 model (not in RasExamples)
- **Solution**: M3Model class available in ras-commander for downloading HCFCD models
- **Challenge**: A120-00-00 project ID unclear - need to identify which M3 model letter contains it

---

## Task 1: Fix Notebook 300 (API Mismatch) ✅ COMPLETED

### Status: ✅ COMPLETED (2025-12-17)

### What Was Done

1. **Investigated actual API**:
   - Read `ras_commander/check/thresholds.py` (lines 46-70)
   - Found `TransitionCoefficientThresholds` class definition
   - Actual attributes use `_max` suffix and `regular_` prefix

2. **Fixed notebook Cell 35**:
   - Changed `structure_contraction` → `structure_contraction_max`
   - Changed `structure_expansion` → `structure_expansion_max`
   - Changed `normal_contraction` → `regular_contraction_max`
   - Changed `normal_expansion` → `regular_expansion_max`

3. **Updated toggle cell**:
   - Set USE_LOCAL_SOURCE = False (test with pip package)
   - Removed warning about check module (now included in v0.87.6)

4. **Tested**:
   - Run: `pytest --nbmake examples/300_quality_assurance_rascheck.ipynb`
   - **Result**: ✅ PASSED in 9.97s

### Outcome
✅ Notebook 300 now passes without errors, displays threshold values correctly

---

## Task 2: Fix Notebook 200 (M3Model Integration) ✅ COMPLETED

### Status: ✅ COMPLETED (2025-12-17)

### Objective
Redesign notebook 200 to download A120-00-00 model using M3Model class

### What Was Done

1. **Web Research**:
   - Searched "HCFCD A120-00-00 M3 model watershed"
   - Confirmed A120-00-00 is in Clear Creek watershed (HCFCD unit numbering: "A" prefix)
   - M3Model.MODELS['A'] = 'Clear Creek'

2. **Downloaded and Verified**:
   - Extracted M3 Model 'A': `M3Model.extract_model('A')`
   - Found A120-00-00.zip in `m3_models/Clear Creek/HEC-RAS/`
   - Extracted project successfully, verified .prj file exists

3. **Updated Notebook Cell 4**:
   - Replaced hardcoded path with M3Model workflow:
     ```python
     m3_path = M3Model.extract_model('A')
     a120_zip = m3_path / "HEC-RAS" / "A120-00-00.zip"
     a120_folder = m3_path / "HEC-RAS" / "A120-00-00"
     # Extract ZIP if needed, set paths
     ```
   - Handles extraction automatically
   - Sets project_folder and geom_file dynamically

4. **Tested**:
   - Run: `pytest --nbmake examples/200_fixit_blocked_obstructions.ipynb`
   - **Result**: ✅ PASSED in 14.18s
   - All RasFixit operations complete successfully

5. **Updated Documentation**:
   - QAQC.md: Notebook 200 status → PASS (14.18s)
   - QAQC.md: Statistics → 39/46 passing (85%), 4 blocked (9%)

6. **Committed**: Commit fbc03cb
   - Comprehensive commit message
   - Documented web research findings
   - Technical details about M3 model structure

### Outcome
✅ Notebook 200 now passes reliably with automated M3Model download

### Original Research Questions (for reference)
1. **Which M3 model contains A120-00-00?**
   - Check M3Model.MODELS dictionary (letter codes A-W)
   - A120-00-00 is a model ID, not a watershed name
   - May need to download and search multiple models

2. **Alternative approaches**:
   - Use a different example project with blocked obstructions
   - Create synthetic test data
   - Document as "requires external data"

### Steps

#### Option A: Integrate M3Model Download
1. **Identify correct M3 model**:
   - A120 suggests watershed code 'A' (Clear Creek)
   - Or search HCFCD documentation for A120-00-00 location
   - May need to try multiple models

2. **Update notebook**:
   - Replace hardcoded path with M3Model.extract_model()
   - Example:
   ```python
   from ras_commander import M3Model

   # Download HCFCD model containing A120-00-00
   m3_folder = M3Model.extract_model('A')  # or appropriate letter
   project_folder = m3_folder / "A120-00-00"
   ```

3. **Test**:
   - Verify model downloads successfully
   - Check if A120-00-00 is in the extracted files
   - If not, try other model letters

#### Option B: Use Alternative Example
1. **Check for blocked obstructions in existing examples**:
   - Search BaldEagleCrkMulti2D for obstructions
   - Search Muncie for obstructions
   - Use synthetic test case

2. **Update notebook**:
   - Change to RasExamples.extract_project()
   - Update all references to project name/path

### Expected Outcome
Notebook 200 runs successfully with accessible test data

---

## Task 3: Update QAQC Documentation

### Steps

1. **Mark notebooks 101, 400, 422 as "PASS (expected timeout)"**:
   - These are functionally correct
   - Timeout is intentional behavior
   - Document as requiring interactive execution

2. **Update final statistics**:
   - Passing: 37 → 40 (if we count timeout notebooks as passing)
   - Or create new category: "PASS (long-running)"

3. **Document blocked notebooks**:
   - 15a: GUI required
   - 200: Needs M3Model integration
   - 300: API mismatch fix needed

---

## Task 4: Version Control ✅ COMPLETED

### Status: ✅ COMPLETED (2025-12-17)

### What Was Done

1. **Staged changes**: 11 files
   - setup.py, ras_commander/__init__.py, ras_commander/usgs/real_time.py
   - examples/300_quality_assurance_rascheck.ipynb (API fix)
   - examples/420_usgs_gauge_catalog.ipynb, examples/423_bc_generation_from_live_gauge.ipynb
   - examples/200_fixit_blocked_obstructions.ipynb (Path import fix)
   - examples/16_automating_ras_with_win32com.ipynb, examples/17_legacy_*.ipynb
   - agent_tasks/Notebook_Testing_and_QAQC.md
   - agent_tasks/.agent/NEXT_TASKS.md (new)

2. **Committed**: Commit ca5e77f
   - Comprehensive commit message describing all fixes
   - Library fixes: timezone handling
   - Notebook fixes: API mismatch, Path imports, initialization
   - Testing updates: Complete QAQC tracking

3. **Push to GitHub**: ⏳ PENDING
   - Branch ahead of origin/main by 26 commits
   - Ready to push when user desires

---

## Task 5: Fix Notebook 300 API Mismatch ✅ COMPLETED

### Status: ✅ COMPLETED (2025-12-17)

**Duplicate of Task 1** - See Task 1 for complete details

**Result**: Notebook 300 now passing in 9.97s

---

## Task 6: Fix Notebook 200 M3Model Integration (Lower Priority)

### Investigation Required

**Question**: Which M3 model letter code contains A120-00-00?

**Approach 1** - Web research:
- Search "HCFCD A120-00-00" on HCFCD website
- Check M3 model documentation
- Model letters: A (Clear Creek), B (Armand), C (Sims), D (Brays), etc.

**Approach 2** - Download and search:
- Try M3Model.extract_model('A') through M3Model.extract_model('W')
- Search for "A120-00-00" in extracted folders
- Time-consuming but thorough

**Approach 3** - Alternative example:
- Use different project with known blocked obstructions
- Update notebook to be more generic
- Less dependent on external data

### Recommendation
Start with Approach 1 (web research) to avoid downloading 20+ models

---

## Priority Order (Updated After All Tasks Complete)

1. ✅ **COMPLETED**: Fix notebook 300 API mismatch (Task 1)
2. ✅ **COMPLETED**: Fix notebook 200 M3Model integration (Task 2)
3. ✅ **COMPLETED**: Commit v0.87.6 changes (Task 4)
4. ✅ **COMPLETED**: Commit notebook 200 fix (fbc03cb)
5. **ALL PRIORITY TASKS COMPLETE**
6. **OPTIONAL**: Push to GitHub (27 commits ahead of origin/main)
7. **OPTIONAL**: Documentation updates for timeout notebooks

---

## Success Criteria

### Notebook 300
- ✅ pytest --nbmake passes without AttributeError
- ✅ Threshold values display correctly
- ✅ All RasCheck operations complete

### Notebook 200
- ✅ Downloads required M3 model automatically
- ✅ Finds A120-00-00 project
- ✅ RasFixit operations complete successfully
- **OR** Uses alternative example project with blocked obstructions

### Version Control
- ✅ All changes committed with descriptive message
- ✅ v0.87.6 tag created (optional)
- ✅ Pushed to GitHub (if desired)

---

## Files Modified (Session Summary)

**Library Code**:
- `ras_commander/usgs/real_time.py` - Timezone fix (line 68, 227)
- `setup.py` - Version 0.87.5 → 0.87.6
- `ras_commander/__init__.py` - Fallback version 0.87.4 → 0.87.6

**Notebooks**:
- `examples/101_Core_Sensitivity.ipynb` - Already has suffix="101" (no change needed)
- `examples/300_quality_assurance_rascheck.ipynb` - API fix (Cell 35), toggle cell update
- `examples/200_fixit_blocked_obstructions.ipynb` - M3Model integration (Cell 4)
- `examples/420_usgs_gauge_catalog.ipynb` - Path import + suffix fixes (previous session)
- `examples/423_bc_generation_from_live_gauge.ipynb` - Path import + suffix fixes (previous session)

**Documentation**:
- `agent_tasks/Notebook_Testing_and_QAQC.md` - Test results: 39/46 passing (85%)

**Built Artifacts**:
- `dist/ras_commander-0.87.6-py3-none-any.whl`
- `dist/ras_commander-0.87.6.tar.gz`

---

## Next Agent Session Instructions

**Resume from this point**:

1. Read this file: `agent_tasks/.agent/NEXT_TASKS.md`
2. Read QAQC status: `agent_tasks/Notebook_Testing_and_QAQC.md`
3. Start with Task 5 (Fix notebook 300 API mismatch) - highest priority
4. Proceed to Task 4 (commit changes)
5. Then investigate Task 6 (notebook 200 M3Model)

**Context preserved in**:
- `agent_tasks/Notebook_Testing_and_QAQC.md` - Test results
- `agent_tasks/.agent/NEXT_TASKS.md` - This file
- `ras_commander/M3Model.py` - M3 model download functionality
- `ras_commander/check/thresholds.py` - Threshold API reference

**Key Files for Next Session**:
- `examples/300_quality_assurance_rascheck.ipynb` - Needs API fix
- `examples/200_fixit_blocked_obstructions.ipynb` - Needs M3Model integration
- `ras_commander/check/thresholds.py` - API reference for fix

---

**End of Task Plan**
