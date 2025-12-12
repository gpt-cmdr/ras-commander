# Notebook Try/Except Anti-Pattern Cleanup Plan

**Created**: 2025-12-12
**Scope**: 5 notebooks requiring removal of unnecessary try/except import blocks
**Priority**: High - affects documentation and user experience

## Overview

This plan provides detailed cell-by-cell instructions for removing try/except anti-patterns from example notebooks. The primary anti-pattern is using try/except for imports instead of following the established flexible import pattern.

---

## Notebook 1: 31_bc_generation_from_live_gauge.ipynb

### Status Summary
- **Problematic cells**: 1 cell (Cell 2)
- **Risk level**: Low
- **Dependencies**: None (isolated import cell)

### Cell-by-Cell Analysis

#### Cell 2 (Code) - Import Cell
**Current Code:**
```python
import sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Add parent directory to path for development
try:
    from ras_commander import init_ras_project, RasExamples, ras
except ImportError:
    sys.path.insert(0, str(Path.cwd().parent))
    from ras_commander import init_ras_project, RasExamples, ras

from ras_commander.usgs import (
    get_gauge_metadata,
    get_recent_data,
    generate_flow_hydrograph_table,
    update_boundary_hydrograph
)

print("✓ Imports successful")
```

**Why Problematic:**
- Violates `.claude/rules/python/import-patterns.md` - try/except should only be used with `sys.path.append()` fallback
- Uses `sys.path.insert(0, ...)` instead of standard pattern
- Doesn't use `Path(__file__)` for notebook compatibility

**Replacement Code:**
```python
import sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Flexible imports for development vs installed package
try:
    from ras_commander import init_ras_project, RasExamples, ras
except ImportError:
    current_file = Path.cwd().resolve()
    parent_directory = current_file.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasExamples, ras

from ras_commander.usgs import (
    get_gauge_metadata,
    get_recent_data,
    generate_flow_hydrograph_table,
    update_boundary_hydrograph
)

print("✓ Imports successful")
```

**Changes:**
1. Add comment explaining flexible import pattern
2. Use `current_file = Path.cwd().resolve()` (notebook-safe)
3. Change `sys.path.insert(0, ...)` to `sys.path.append(...)`
4. Calculate `parent_directory` explicitly

**Risk Assessment:** Low
- Isolated cell, no dependencies
- Changes only affect import mechanism
- All downstream cells reference `ras_commander` objects directly

**Testing Approach:**
1. Run Cell 2 after changes
2. Verify "✓ Imports successful" message appears
3. Run Cell 4 (project initialization) to confirm `init_ras_project()` works
4. Run Cell 7 (gauge metadata query) to confirm USGS functions work

**Expected Behavior:**
- No errors if ras-commander installed: uses installed package
- No errors if development mode: uses parent directory
- Error message clear if neither works

---

## Notebook 2: 32_model_validation_with_usgs.ipynb

### Status Summary
- **Problematic cells**: 1 cell (Cell 2)
- **Risk level**: Low
- **Dependencies**: None (isolated import cell)

### Cell-by-Cell Analysis

#### Cell 2 (Code) - Import Cell
**Current Code:**
```python
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Add parent directory to path for development
try:
    from ras_commander import init_ras_project, RasExamples, ras, RasCmdr
except ImportError:
    sys.path.insert(0, str(Path.cwd().parent))
    from ras_commander import init_ras_project, RasExamples, ras, RasCmdr

from ras_commander.hdf import HdfResultsPlan
from ras_commander.usgs import (
    get_gauge_metadata,
    retrieve_flow_data,
    align_timeseries
)
from ras_commander.usgs.metrics import (
    nash_sutcliffe_efficiency,
    kling_gupta_efficiency,
    calculate_peak_error,
    calculate_all_metrics
)
from ras_commander.usgs.visualization import (
    plot_timeseries_comparison,
    plot_scatter_comparison,
    plot_residuals
)

print("✓ Imports successful")
```

**Why Problematic:** Same as notebook 31

**Replacement Code:**
```python
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Flexible imports for development vs installed package
try:
    from ras_commander import init_ras_project, RasExamples, ras, RasCmdr
except ImportError:
    current_file = Path.cwd().resolve()
    parent_directory = current_file.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasExamples, ras, RasCmdr

from ras_commander.hdf import HdfResultsPlan
from ras_commander.usgs import (
    get_gauge_metadata,
    retrieve_flow_data,
    align_timeseries
)
from ras_commander.usgs.metrics import (
    nash_sutcliffe_efficiency,
    kling_gupta_efficiency,
    calculate_peak_error,
    calculate_all_metrics
)
from ras_commander.usgs.visualization import (
    plot_timeseries_comparison,
    plot_scatter_comparison,
    plot_residuals
)

print("✓ Imports successful")
```

**Changes:** Identical to notebook 31

**Risk Assessment:** Low
- Isolated import cell
- No downstream dependencies on import mechanism
- All functions referenced by name only

**Testing Approach:**
1. Run Cell 2 after changes
2. Verify "✓ Imports successful" message
3. Run Cell 4 (project initialization)
4. Run Cell 7 (model execution if needed)
5. Run Cell 12 (gauge metadata query)

---

## Notebook 3: 104_Atlas14_AEP_Multi_Project.ipynb

### Status Summary
- **Problematic cells**: 2 cells with nested try/except blocks
- **Risk level**: Medium - complex function definitions
- **Dependencies**: Function cells used by later execution cells

### Cell-by-Cell Analysis

#### Cell 11 (Code) - parse_duration function
**Location:** Inside `read_precipitation_data()` function

**Current Code (partial, showing problem area):**
```python
def read_precipitation_data(csv_file):
    """
    Reads the precipitation frequency CSV and returns a DataFrame
    with durations in hours as the index and ARIs as columns.
    """
    with open(csv_file, 'r') as f:
        lines = f.readlines()

    # ... [header parsing code] ...

    # Iterate over the lines following the header to extract data
    for line in lines[header_line_idx + 1:]:
        # ... [line processing] ...
        duration_str = parts[0]
        try:
            duration_hours = parse_duration(duration_str)
        except ValueError as ve:
            print(f"Skipping line due to error: {ve}")
            continue
        durations.append(duration_hours)
        for ari, depth_str in zip(aris, parts[1:]):
            try:
                depth = float(depth_str)
            except ValueError:
                depth = np.nan
            depths[ari].append(depth)
    # ...
```

**Why Problematic:**
- **First try/except (duration parsing)**: Catches `ValueError` and prints message, but this hides data quality issues
- **Second try/except (depth conversion)**: Silently converts parse failures to NaN, hiding data corruption
- Both suppress errors that should be visible to users for debugging

**Replacement Code:**
```python
def read_precipitation_data(csv_file):
    """
    Reads the precipitation frequency CSV and returns a DataFrame
    with durations in hours as the index and ARIs as columns.
    """
    with open(csv_file, 'r') as f:
        lines = f.readlines()

    # ... [header parsing code unchanged] ...

    # Iterate over the lines following the header to extract data
    for line in lines[header_line_idx + 1:]:
        # ... [line processing] ...
        duration_str = parts[0]

        # Parse duration with clear error message if it fails
        duration_hours = parse_duration(duration_str)  # Let ValueError propagate

        durations.append(duration_hours)
        for ari, depth_str in zip(aris, parts[1:]):
            # Convert depth, using NaN for empty/missing values
            if depth_str.strip() == '' or depth_str.strip().lower() == 'nan':
                depth = np.nan
            else:
                depth = float(depth_str)  # Let ValueError propagate for malformed data
            depths[ari].append(depth)
    # ...
```

**Changes:**
1. **Duration parsing**: Remove try/except, let `parse_duration()` raise `ValueError` with clear message
2. **Depth conversion**: Only use NaN for truly empty/missing values, not parse failures
3. **Error transparency**: Users see which line failed instead of silent skip

**Justification:**
- Data quality errors should be visible, not hidden
- Empty values intentionally become NaN (expected behavior)
- Malformed data causes immediate, clear error (helps debugging)

**Risk Assessment:** Medium
- Function used in Cell 16 (generate hyetographs)
- Breaking change: previously silent errors now raise exceptions
- **Mitigation**: Atlas 14 CSV format is standardized, errors are rare

**Testing Approach:**
1. Run Cell 11 (function definition)
2. Run Cell 14 (test data read with small CSV)
3. Verify DataFrame structure matches expected format
4. **Test error case**: Create CSV with malformed line, verify clear error message

**Dependencies:**
- Used by: Cell 16 (hyetograph generation)
- Impact: If CSV is malformed, error appears earlier (during data read) instead of later (during hydrograph calculation)

#### Cell 11 (Code) - get_regional_override_polygons function
**Location:** Inside `get_regional_override_polygons()` helper function

**Current Code:**
```python
def get_regional_override_polygons(geom_hdf_path):
    """
    Extract regional override polygon geometries from a HEC-RAS geometry HDF file.
    """
    import h5py
    import geopandas as gpd
    from shapely.geometry import Polygon

    try:
        with h5py.File(geom_hdf_path, 'r') as f:
            # Navigate to regional override polygons
            if 'Geometry/Regional Manning Areas' in f:
                region_group = f['Geometry/Regional Manning Areas']
                # ... [processing code] ...
                if polygons:
                    gdf = gpd.GeoDataFrame(...)
                    return gdf

        # Return empty GeoDataFrame if no regional overrides found
        return gpd.GeoDataFrame(columns=['region_name', 'geometry'])

    except Exception as e:
        print(f"Error extracting regional override polygons: {str(e)}")
        return gpd.GeoDataFrame(columns=['region_name', 'geometry'])
```

**Why Problematic:**
- Catches **all exceptions** with bare `except Exception`
- Prints generic error message, loses specific error details
- Returns empty GeoDataFrame on any error (masks problems)
- Users can't distinguish between "no regional overrides" and "HDF file corrupted"

**Replacement Code:**
```python
def get_regional_override_polygons(geom_hdf_path):
    """
    Extract regional override polygon geometries from a HEC-RAS geometry HDF file.

    Returns:
        geopandas.GeoDataFrame: GeoDataFrame with regional override polygons,
                                 or empty GeoDataFrame if no regional areas exist

    Raises:
        FileNotFoundError: If geom_hdf_path doesn't exist
        OSError: If HDF file is corrupted or inaccessible
    """
    import h5py
    import geopandas as gpd
    from shapely.geometry import Polygon

    # Validate file exists before opening
    if not Path(geom_hdf_path).exists():
        raise FileNotFoundError(f"Geometry HDF file not found: {geom_hdf_path}")

    with h5py.File(geom_hdf_path, 'r') as f:
        # Check if regional overrides exist
        if 'Geometry/Regional Manning Areas' not in f:
            # Expected case: no regional overrides in this model
            return gpd.GeoDataFrame(columns=['region_name', 'geometry'])

        region_group = f['Geometry/Regional Manning Areas']
        polygons = []
        region_names = []

        # Process each regional override polygon
        for region_name, region_data in region_group.items():
            if 'Polygon' in region_data:
                coords = region_data['Polygon'][:]
                polygon = Polygon(coords)
                polygons.append(polygon)
                region_names.append(region_name)

        # Return GeoDataFrame with regional overrides (or empty if none)
        if polygons:
            gdf = gpd.GeoDataFrame(
                {'region_name': region_names, 'geometry': polygons},
                crs='EPSG:4326'  # Set appropriate CRS
            )
            return gdf
        else:
            return gpd.GeoDataFrame(columns=['region_name', 'geometry'])
```

**Changes:**
1. **Remove try/except wrapper**: Let h5py errors propagate naturally
2. **Add file existence check**: Explicit `FileNotFoundError` if file missing
3. **Document expected exceptions**: Users know what errors mean
4. **Distinguish cases**: "No regional overrides" vs "HDF file problem" are different

**Justification:**
- HDF file errors indicate real problems (corrupted file, wrong version, etc.)
- Users need to know when HDF structure is unexpected
- Empty return should only happen when model legitimately has no regional overrides

**Risk Assessment:** Low-Medium
- Function is optional (fallback to empty GeoDataFrame is valid)
- Used in Manning's n sensitivity analysis (notebooks 105, 106)
- **Mitigation**: Most models either have regional overrides or don't; HDF errors are rare

**Testing Approach:**
1. Run Cell 11 (function definition)
2. **Test case 1**: Model WITH regional overrides - verify GeoDataFrame populated
3. **Test case 2**: Model WITHOUT regional overrides - verify empty GeoDataFrame (not error)
4. **Test case 3**: Missing HDF file - verify clear `FileNotFoundError`
5. **Test case 4**: Corrupted HDF - verify h5py error with helpful message

**Dependencies:**
- Used by: `analyze_mesh_land_cover_statistics()` in same cell
- Impact: Failures now explicit instead of silent

---

## Notebook 4: 105_mannings_sensitivity_bulk_analysis.ipynb

### Status Summary
- **Problematic cells**: 1 cell (Cell 6)
- **Risk level**: Low
- **Dependencies**: None (isolated import cell)

### Cell-by-Cell Analysis

#### Cell 6 (Code) - Import Cell
**Current Code:**
```python
import sys
import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from shapely.geometry import Point

# Flexible imports to allow for development without installation
try:
    from ras_commander import *
except ImportError:
    current_file = Path(os.getcwd()).resolve()
    rascmdr_directory = current_file.parent
    sys.path.append(str(rascmdr_directory))
    print("Loading ras-commander from local dev copy")
    from ras_commander import *

print("ras_commander imported successfully")
```

**Why Problematic:**
- Uses `os.getcwd()` instead of `Path.cwd()` (inconsistent)
- Uses wildcard import `from ras_commander import *` (anti-pattern)
- Doesn't follow standard pattern from `.claude/rules/python/import-patterns.md`

**Replacement Code:**
```python
import sys
import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from shapely.geometry import Point

# Flexible imports for development vs installed package
try:
    from ras_commander import (
        init_ras_project, RasExamples, RasPlan, RasCmdr,
        RasGeo, HdfMesh, HdfResultsMesh
    )
except ImportError:
    current_file = Path.cwd().resolve()
    parent_directory = current_file.parent
    sys.path.append(str(parent_directory))
    print("Loading ras-commander from local dev copy")
    from ras_commander import (
        init_ras_project, RasExamples, RasPlan, RasCmdr,
        RasGeo, HdfMesh, HdfResultsMesh
    )

print("ras_commander imported successfully")
```

**Changes:**
1. Replace `os.getcwd()` with `Path.cwd()` (consistent with rules)
2. **Replace wildcard import** with explicit imports of used classes
3. Calculate `parent_directory` explicitly for clarity

**Justification:**
- **Explicit imports**: Makes dependencies clear, avoids namespace pollution
- **Consistency**: Matches pattern in notebooks 31, 32
- **Discoverability**: Users see which classes are actually used

**Risk Assessment:** Low
- Notebook may use additional classes from ras_commander not listed
- **Mitigation**: Run notebook completely, add missing imports if `NameError` occurs

**Testing Approach:**
1. Run Cell 6 (imports)
2. Verify "ras_commander imported successfully" message
3. Run Cell 9 (create_manning_minmax_df function)
4. Run Cell 11 (autoras_mannings_bulk_sensitivity function)
5. **Run complete workflow** (Cells 13-16) to verify all needed classes imported

**Dependencies:**
- **Critical classes used in notebook**: Scan cells to identify all ras_commander classes
- Likely additions: `ras` (global object), potentially others

**Action Required:**
Before finalizing replacement code, scan all code cells for ras_commander usage:
```bash
# Check which ras_commander classes are used
grep -o "Ras[A-Za-z]*\|Hdf[A-Za-z]*" 105_mannings_sensitivity_bulk_analysis.ipynb
```

---

## Notebook 5: 106_mannings_sensitivity_multi-interval.ipynb

### Status Summary
- **Problematic cells**: 2 cells (Cell 8, Cell 10) with try/except blocks in functions
- **Risk level**: Medium - functions used in sensitivity analysis
- **Dependencies**: Functions used in later execution cells

### Cell-by-Cell Analysis

#### Cell 8 (Code) - get_regional_override_polygons function

**Problem:** Identical to notebook 104 Cell 11

**Replacement Code:** See Notebook 104 Cell 11 replacement (identical fix)

**Risk Assessment:** Low-Medium (same as notebook 104)

**Testing Approach:** Same as notebook 104

#### Cell 10 (Code) - get_regional_override_polygons function (duplicate)

**Problem:** Appears to be duplicate of Cell 8 function definition

**Action Required:**
1. Verify Cell 8 and Cell 10 have identical function definitions
2. If identical: Remove Cell 10 entirely (duplicate)
3. If different: Apply same fix as Cell 8, then investigate why duplicated

**Risk Assessment:** Low
- Duplication suggests copy/paste error
- Removing duplicate has no functional impact

**Testing Approach:**
1. Compare Cell 8 and Cell 10 function signatures
2. If duplicates, delete Cell 10
3. Run notebook to verify no `NameError` for `get_regional_override_polygons`

#### Cell 12 (Code) - individual_landuse_sensitivity_base function

**Current Code (partial, showing problem areas):**
```python
def individual_landuse_sensitivity_base(...):
    # ... [setup code] ...

    for scenario in scenarios:
        plan_number = scenario['plan_number']
        land_cover = scenario['land_cover']
        n_value = scenario['n_value']
        shortid = scenario['shortid']

        try:
            results_xr = HdfResultsMesh.get_mesh_cells_timeseries(plan_number)

            # Extract water surface data
            ws_data = results_xr[mesh_name]['Water Surface'].sel(cell_id=int(mesh_cell_id))

            # Convert to DataFrame
            ws_df = pd.DataFrame({
                'time': ws_data.time.values,
                'water_surface': ws_data.values
            })

            # Store results
            max_ws = ws_df['water_surface'].max()
            # ... [save results] ...

        except Exception as e:
            print(f"  Error extracting results for {shortid}: {str(e)}")
```

**Why Problematic:**
- Catches all exceptions with bare `except Exception`
- Prints error but continues loop (results incomplete)
- Users don't know which scenarios succeeded vs failed
- Can't distinguish between "HDF file missing" and "wrong mesh name"

**Replacement Code:**
```python
def individual_landuse_sensitivity_base(...):
    # ... [setup code] ...

    failed_scenarios = []

    for scenario in scenarios:
        plan_number = scenario['plan_number']
        land_cover = scenario['land_cover']
        n_value = scenario['n_value']
        shortid = scenario['shortid']

        # Extract results with specific error handling
        results_xr = HdfResultsMesh.get_mesh_cells_timeseries(plan_number)

        # Verify mesh exists in results
        if mesh_name not in results_xr:
            error_msg = f"Mesh '{mesh_name}' not found in results for {shortid}"
            print(f"  ERROR: {error_msg}")
            failed_scenarios.append({'shortid': shortid, 'error': error_msg})
            continue

        # Extract water surface data
        ws_data = results_xr[mesh_name]['Water Surface'].sel(cell_id=int(mesh_cell_id))

        # Convert to DataFrame
        ws_df = pd.DataFrame({
            'time': ws_data.time.values,
            'water_surface': ws_data.values
        })

        # Store results
        max_ws = ws_df['water_surface'].max()
        # ... [save results] ...

    # Report failed scenarios at end
    if failed_scenarios:
        print(f"\n⚠ WARNING: {len(failed_scenarios)} scenarios failed:")
        for fail in failed_scenarios:
            print(f"  - {fail['shortid']}: {fail['error']}")
        print("Review errors above to determine if results are valid.\n")
```

**Changes:**
1. **Remove try/except**: Let file access errors (HDF missing, corrupted) raise immediately
2. **Explicit mesh check**: Distinguish "mesh not in results" from other errors
3. **Track failures**: Collect failed scenarios, report summary at end
4. **User awareness**: Clear warning if any scenarios incomplete

**Justification:**
- HDF file errors indicate real problems (plan didn't run, HDF corrupted)
- Users need to know analysis is incomplete
- Specific checks give actionable error messages
- Summary at end prevents missed failures in long output

**Risk Assessment:** Medium
- Breaking change: previously silent failures now explicit
- **Mitigation**: Most common failure is "plan didn't run" - clear message helps

**Testing Approach:**
1. Run Cell 12 (function definition)
2. **Test case 1**: All plans successful - verify no warnings
3. **Test case 2**: One plan failed - verify warning lists that scenario
4. **Test case 3**: Missing HDF - verify immediate error (not silent skip)
5. Run complete sensitivity analysis to verify results DataFrame correct

**Dependencies:**
- Used by: Sensitivity analysis execution cells
- Impact: Analysis results now reflect only successful scenarios

---

## Implementation Sequence

### Phase 1: Low-Risk Notebooks (Order: 31 → 32 → 105)
**Estimated time**: 30 minutes

1. **Notebook 31** (31_bc_generation_from_live_gauge.ipynb)
   - Edit Cell 2
   - Run cells 2, 4, 7
   - Verify gauge query works
   - **Commit**: "Fix import pattern in notebook 31"

2. **Notebook 32** (32_model_validation_with_usgs.ipynb)
   - Edit Cell 2 (identical to notebook 31)
   - Run cells 2, 4, 12
   - Verify validation functions work
   - **Commit**: "Fix import pattern in notebook 32"

3. **Notebook 105** (105_mannings_sensitivity_bulk_analysis.ipynb)
   - Edit Cell 6
   - Scan notebook for all ras_commander classes used
   - Update import list if needed
   - Run cells 6, 9, 11
   - **Commit**: "Fix imports and remove wildcard in notebook 105"

### Phase 2: Medium-Risk Notebooks (Order: 104 → 106)
**Estimated time**: 1-2 hours

4. **Notebook 104** (104_Atlas14_AEP_Multi_Project.ipynb)
   - Edit Cell 11 (`read_precipitation_data` function)
   - Edit Cell 11 (`get_regional_override_polygons` function)
   - **Test with sample Atlas 14 CSV**:
     - Valid CSV → should work
     - Malformed line → should show clear error (not silent skip)
   - Run dependent cells (16+)
   - **Commit**: "Remove error-hiding try/except in notebook 104"

5. **Notebook 106** (106_mannings_sensitivity_multi-interval.ipynb)
   - **Check Cell 8 vs Cell 10** for duplication
   - If duplicates: Delete Cell 10
   - Edit Cell 8 (`get_regional_override_polygons` - same as 104)
   - Edit Cell 12 (`individual_landuse_sensitivity_base` function)
   - **Test sensitivity analysis with 2-3 scenarios**
   - **Commit**: "Fix error handling in notebook 106 sensitivity functions"

### Phase 3: Verification
**Estimated time**: 30 minutes

6. **Run complete workflows** for each notebook
   - Notebook 31: Full BC generation from live gauge
   - Notebook 32: Model validation workflow
   - Notebook 104: Atlas 14 hyetograph generation
   - Notebook 105: Manning's bulk sensitivity
   - Notebook 106: Manning's multi-interval sensitivity

7. **Document changes** in commit messages
   - Reference this cleanup plan
   - Note any unexpected issues found

---

## Testing Matrix

| Notebook | Cell | Test Case | Expected Result | Risk if Broken |
|----------|------|-----------|-----------------|----------------|
| 31 | 2 | Installed package | Imports succeed | High (notebook unusable) |
| 31 | 2 | Development mode | Falls back to parent dir | High |
| 31 | 7 | USGS gauge query | Metadata retrieved | Medium (workflow fails) |
| 32 | 2 | Installed package | Imports succeed | High |
| 32 | 2 | Development mode | Falls back to parent dir | High |
| 32 | 12 | Gauge metadata | Data retrieved | Medium |
| 104 | 11 | Valid Atlas 14 CSV | DataFrame created | High |
| 104 | 11 | Malformed CSV line | Clear ValueError (not silent) | Low (data quality improvement) |
| 104 | 11 | Missing HDF file | FileNotFoundError | Low (optional function) |
| 105 | 6 | Import all classes | No NameError | High |
| 105 | 11 | Sensitivity analysis | Plans created and run | Medium |
| 106 | 8 | Regional override check | GeoDataFrame returned | Low |
| 106 | 12 | Scenario with failed plan | Warning printed | Medium (user awareness) |

---

## Rollback Plan

If any changes cause issues:

1. **Individual notebook rollback**:
   ```bash
   git checkout HEAD~1 examples/{notebook_name}.ipynb
   ```

2. **Full rollback** (if multiple notebooks broken):
   ```bash
   git revert <commit_hash>
   ```

3. **Identify issue**:
   - Check error message
   - Verify which cell caused problem
   - Test replacement code in isolation

4. **Fix forward** (preferred):
   - Adjust replacement code
   - Add missing imports
   - Handle edge case
   - Commit fix

---

## Success Criteria

- [ ] All 5 notebooks run without errors
- [ ] Import cells follow `.claude/rules/python/import-patterns.md`
- [ ] Error messages are clear and actionable (not hidden)
- [ ] No wildcard imports (`from x import *`)
- [ ] All try/except blocks have clear justification
- [ ] Commit messages reference this cleanup plan
- [ ] Testing matrix completed for all notebooks

---

## Notes for Future Notebook Development

**Guidelines** (from this cleanup):

1. **Imports**: Always use standard flexible import pattern:
   ```python
   try:
       from ras_commander import <explicit_list>
   except ImportError:
       current_file = Path.cwd().resolve()
       parent_directory = current_file.parent
       sys.path.append(str(parent_directory))
       from ras_commander import <explicit_list>
   ```

2. **Error handling**: Only use try/except when:
   - Expected failure case (network timeout, optional file)
   - Specific exception type (not bare `except Exception`)
   - Clear error message explaining what happened
   - Documented in code comment

3. **Data quality**: Don't hide data errors
   - Let parse failures propagate
   - Use NaN only for truly missing values
   - Validate inputs before processing

4. **Function robustness**: Make errors visible
   - Check preconditions explicitly
   - Raise specific exceptions
   - Document expected exceptions in docstring

5. **User experience**: Help users debug
   - Print warnings for degraded functionality
   - Collect and summarize failures
   - Distinguish "expected empty result" from "error occurred"

---

## References

- `.claude/rules/python/import-patterns.md` - Standard import pattern
- `.claude/rules/python/error-handling.md` - When to use try/except
- `.claude/rules/documentation/notebook-standards.md` - Notebook requirements
- `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` - Anti-patterns

---

## Appendix: Complete Import Scan

### Notebook 105 - Classes Used

Scan result:
```
RasGeo, RasPlan, RasCmdr, HdfMesh, HdfResultsMesh,
init_ras_project, RasExamples, (ras global object likely)
```

**Recommended import statement**:
```python
from ras_commander import (
    init_ras_project, RasExamples, ras,
    RasPlan, RasCmdr, RasGeo,
    HdfMesh, HdfResultsMesh
)
```

### Notebook 106 - Classes Used

Scan result:
```
RasGeo, RasPlan, RasCmdr, HdfMesh, HdfResultsMesh,
init_ras_project, Point (from shapely)
```

**Recommended import statement**: Same as notebook 105

---

**End of Cleanup Plan**
