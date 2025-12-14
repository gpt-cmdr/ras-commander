# Floodplain Mapping Notebook Consolidation Plan

**Created**: 2025-12-12
**Status**: Ready for Implementation
**Related Backlog Item**: nb-004 (full notebook reorganization - deferred)

---

## Executive Summary

Consolidate 4 overlapping/broken floodplain mapping notebooks into 3 methodology-focused notebooks (15_a, 15_b, 15_c) with minimal renumbering. Add .rasmap version compatibility automation to fix 5.0.7→6.x upgrade issues that currently cause GUI automation failures.

---

## Current Problem

### Existing Notebooks (Broken/Overlapping)

1. **`15_stored_map_generation  --- GUI Automation fails - no maps in rasmapper   .ipynb`**
   - Status: BROKEN - GUI automation fails
   - Issue: Requires manual .rasmap upgrade for 5.0.7→6.x projects
   - Method: `RasMap.postprocess_stored_maps()` with GUI automation

2. **`21_rasmap_raster_exports_does not work - no maps in rasmapper - old version complication.ipynb`**
   - Status: FILE DOESN'T EXIST (deleted previously)
   - Was another broken GUI automation attempt

3. **`25_programmatic_result_mapping    --- GUI Automation fails - no maps in rasmapper.ipynb`**
   - Status: BROKEN - marked as failing in filename
   - Method: `RasMap.map_ras_results()` (Python-GIS approach)
   - Actually works but labeled as broken

4. **`26_rasprocess_stored_maps.ipynb`**
   - Status: FULLY FUNCTIONAL
   - Method: `RasProcess.store_maps()` CLI approach
   - Will be used as basis for 15_b

### Root Cause: .rasmap Version Incompatibility

When HEC-RAS 5.0.7 projects are opened in HEC-RAS 6.x:
- The `.rasmap` file is in old 5.0.7 XML format
- RASMapper needs to update it to 6.x format (creates `<Results>` section)
- Without this update, stored map generation fails
- Current notebooks require **manual** opening of RASMapper to trigger upgrade

---

## Solution: 3 Distinct Methodology Notebooks

### Naming Convention (Minimal Renumbering)
- `15_a_floodplain_mapping_gui.ipynb` - RASMapper GUI Automation
- `15_b_floodplain_mapping_rasprocess.ipynb` - RasProcess CLI
- `15_c_floodplain_mapping_python_gis.ipynb` - Python-GIS Method

### Method Positioning

Per user requirements:

| Method | Windows Performance | Cloud Compatible | Feature Complete | Recommendation |
|--------|---------------------|------------------|------------------|----------------|
| **15_a GUI** | Clunky, fragile | No (requires GUI) | Yes | Least recommended, but shows process visually |
| **15_b RasProcess** | **Fastest, optimal** | No (Windows only) | Yes (all variables) | **Most recommended for Windows** |
| **15_c Python-GIS** | Acceptable | **Yes** | **2D only** | Cloud processing, limited scope |

---

## Implementation Details

### 1. Add .rasmap Compatibility Function

**File**: `ras_commander/RasMap.py`

**New Function** (~50-80 lines):

```python
@staticmethod
@log_call
def ensure_rasmap_compatible(ras_object=None, auto_upgrade=True):
    """
    Ensure .rasmap file is compatible with current HEC-RAS version.

    For 5.0.7 projects in HEC-RAS 6.x, opens RASMapper via COM/GUI
    automation to trigger automatic .rasmap upgrade.

    Args:
        ras_object: RasPrj object (default: global ras)
        auto_upgrade: If True, attempt automatic upgrade via COM

    Returns:
        dict: {
            'status': 'ready'|'upgraded'|'manual_needed',
            'message': str,
            'version': str
        }

    Technical Approach:
    1. Parse .rasmap XML to detect version
       - Look for XML schema version attribute
       - Check for presence of <Results> section

    2. If old version detected and auto_upgrade=True:
       - Open HEC-RAS.exe with project path
       - Use win32com.client or win32gui to:
         * Click "GIS Tools" > "RAS Mapper" menu
         * Wait for RASMapper window to open
         * Allow .rasmap update dialog (auto-accepts)
         * Close RASMapper window
         * Close HEC-RAS window

    3. Verify upgrade succeeded by re-parsing .rasmap

    4. Return status for user feedback

    Edge Cases:
    - .rasmap doesn't exist → create minimal valid file
    - HEC-RAS won't open → return 'manual_needed'
    - Upgrade dialog doesn't appear → already upgraded
    - COM automation fails → fallback to manual instructions
    """
    # Implementation here
```

**Integration Points**:
- Called at start of `postprocess_stored_maps()` (15_a)
- Called at start of RasProcess workflow (15_b)
- Optional/skipped for Python-GIS (15_c doesn't use .rasmap)

**File**: `ras_commander/RasGuiAutomation.py`

**Potential Addition**: RASMapper-specific automation helper if win32com pattern doesn't work

```python
@staticmethod
def open_rasmapper_for_upgrade(ras_object=None):
    """
    Open RASMapper to trigger .rasmap file upgrade.

    Uses existing GUI automation patterns from open_and_compute()
    but specifically targets RASMapper menu item.
    """
    # Similar to existing GUI automation
    # Use menu ID discovery for "GIS Tools" > "RAS Mapper"
    # Wait for RASMapper window, then close
```

---

### 2. Update Existing postprocess_stored_maps()

**File**: `ras_commander/RasMap.py`

**Modification** (lines ~320-563):

```python
@staticmethod
@log_call
def postprocess_stored_maps(...):
    """
    [Existing docstring]

    Note: Automatically calls ensure_rasmap_compatible() to handle
    5.0.7→6.x .rasmap upgrades before proceeding.
    """

    # NEW: Add .rasmap compatibility check at beginning
    compat_result = RasMap.ensure_rasmap_compatible(
        ras_object=ras_obj,
        auto_upgrade=True
    )

    if compat_result['status'] == 'manual_needed':
        logger.warning(
            "Unable to automatically upgrade .rasmap file. "
            "Please open project in HEC-RAS and access RASMapper manually."
        )
        # Optionally: return False or raise exception

    # EXISTING: Rest of function as-is
    # - Backup plan files
    # - Modify .rasmap XML
    # - Call RasGuiAutomation.open_and_compute()
    # - Restore files
    ...
```

---

### 3. Create Three New Notebooks

#### Notebook 15_a: GUI Automation Approach

**File**: `examples/15_a_floodplain_mapping_gui.ipynb`

**H1 Title**: "Floodplain Mapping via RASMapper GUI Automation"

**Content Structure**:

1. **Overview** (Markdown)
   - When to use: Want to see visual feedback, verify maps in RASMapper
   - Limitations: Requires Windows, GUI automation can be fragile
   - Positioning: "Least recommended, but provides visibility"

2. **Prerequisites** (Markdown)
   - HEC-RAS 6.x installed
   - Windows environment
   - win32gui, win32com libraries

3. **Project Setup** (Code)
   ```python
   from ras_commander import RasExamples, init_ras_project, RasMap

   project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")
   init_ras_project(project_path, "6.6")
   ```

4. **Pre-step: .rasmap Compatibility Check** (Code + Explanation)
   ```python
   # Automatically upgrade .rasmap if needed
   result = RasMap.ensure_rasmap_compatible(auto_upgrade=True)
   print(f"Status: {result['status']}")
   print(f"Message: {result['message']}")
   ```

5. **Generate Stored Maps via GUI** (Code)
   ```python
   # Get terrain names
   terrains = RasMap.get_terrain_names(rasmap_path)

   # Generate maps with GUI automation
   success = RasMap.postprocess_stored_maps(
       plan_number="06",
       specify_terrain=terrains[0],
       layers=['Depth', 'WSE', 'Velocity']
   )
   ```

6. **Visualization** (Code)
   ```python
   # Load and display generated rasters
   import rasterio
   from rasterio.plot import show
   import matplotlib.pyplot as plt

   # Plot depth map
   depth_path = RasMap.get_results_raster("06", "Depth (Max)")
   with rasterio.open(depth_path) as src:
       show(src, title="Maximum Depth")
   ```

7. **Technical Explanation** (Markdown + Code)
   - **GUI Automation Process**:
     - Opens HEC-RAS.exe via subprocess
     - Uses win32gui to find main window
     - Clicks "Run > Unsteady Flow Analysis" menu (ID 47)
     - Finds and clicks "Compute" button
     - Waits for completion
     - Closes HEC-RAS

   - **Why Fragile**:
     - Window must be fully loaded before menu clicks
     - Dialog boxes can interrupt flow
     - HEC-RAS version changes affect menu IDs
     - Non-deterministic timing issues

8. **Troubleshooting** (Markdown)
   - .rasmap upgrade fails → Manual steps
   - GUI automation hangs → Kill process, retry
   - No maps generated → Check HEC-RAS error messages

9. **Decision Matrix** (Markdown)
   - When to use GUI vs RasProcess vs Python-GIS

#### Notebook 15_b: RasProcess CLI Approach

**File**: `examples/15_b_floodplain_mapping_rasprocess.ipynb`

**H1 Title**: "Floodplain Mapping via RasProcess CLI (Recommended for Windows)"

**Content Structure**:

1. **Overview** (Markdown)
   - **Fastest method for Windows hosts**
   - Native HEC-RAS rendering without GUI interaction
   - Supports all variables: WSE, Depth, Velocity, Froude, Shear, D*V, D*V²
   - Time-series support for specific timestamps

2. **Prerequisites** (Markdown)
   - HEC-RAS 6.x (provides RasProcess.exe)
   - Windows environment
   - rasterio (optional, for georeferencing fixes)

3. **Project Setup** (Code)
   ```python
   from ras_commander import RasExamples, init_ras_project, RasProcess

   project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")
   init_ras_project(project_path, "6.6")

   # Ensure plan is computed
   RasCmdr.compute_plan("06", skip_existing=True)
   ```

4. **Pre-step: .rasmap Compatibility** (Code)
   ```python
   # Check .rasmap compatibility
   result = RasMap.ensure_rasmap_compatible(auto_upgrade=True)
   ```

5. **Generate Individual Maps** (Code)
   ```python
   # Generate WSE, Depth, Velocity for Max profile
   results = RasProcess.store_maps(
       plan_number="06",
       profile="Max",
       wse=True,
       depth=True,
       velocity=True,
       fix_georef=True,
       ras_version="6.6"
   )

   for map_type, files in results.items():
       print(f"{map_type}: {files[0]}")
   ```

6. **Additional Variables** (Code)
   ```python
   # Froude, Shear Stress, D*V hazard metrics
   results_extra = RasProcess.store_maps(
       plan_number="06",
       profile="Max",
       froude=True,
       shear_stress=True,
       depth_x_velocity=True,
       depth_x_velocity_sq=True,
       fix_georef=True
   )
   ```

7. **Time-Series Maps** (Code)
   ```python
   # Get available timestamps
   timestamps = RasProcess.get_plan_timestamps("06")

   # Generate map for specific time
   results_ts = RasProcess.store_maps(
       plan_number="06",
       profile=timestamps[100],  # Specific timestamp
       wse=True
   )
   ```

8. **Batch Processing** (Code)
   ```python
   # Process all plans at once
   all_results = RasProcess.store_all_maps(
       profile="Max",
       wse=True,
       depth=True,
       velocity=True,
       fix_georef=True
   )
   ```

9. **Visualization** (Code)
   ```python
   # Plot generated rasters
   import rasterio
   import matplotlib.pyplot as plt

   with rasterio.open(results['wse'][0]) as src:
       plt.imshow(src.read(1), cmap='terrain')
       plt.title("Maximum WSE - RasProcess")
       plt.colorbar()
   ```

10. **Technical Explanation** (Markdown + Code)
    - **RasProcess.exe CLI Tool**:
      - Undocumented but stable HEC-RAS utility
      - Bundled with HEC-RAS 6.x installation
      - XML-based command interface

    - **Command Structure**:
      ```bash
      RasProcess.exe -Command=StoreAllMaps \
                     -RasMapFilename=project.rasmap \
                     -ResultFilename=project.p01.hdf
      ```

    - **Workflow**:
      1. Modify .rasmap XML to add stored map definitions
      2. Execute RasProcess.exe subprocess
      3. Parse output to find generated .tif files
      4. Optionally fix georeferencing (CRS metadata)
      5. Restore original .rasmap file

    - **Why Fastest**:
      - Direct HEC-RAS rasterization engine
      - No GUI overhead
      - Optimized native code
      - Parallel processing within HEC-RAS

11. **Performance Comparison** (Markdown)
    - Benchmark results vs GUI vs Python-GIS
    - Expected timing for various project sizes

#### Notebook 15_c: Python-GIS Approach

**File**: `examples/15_c_floodplain_mapping_python_gis.ipynb`

**H1 Title**: "Floodplain Mapping via Python-GIS (Cloud-Compatible, 2D Only)"

**Content Structure**:

1. **Overview** (Markdown)
   - Pure Python implementation (no HEC-RAS dependencies)
   - Cloud/Docker/headless compatible
   - **Limitation: 2D mesh areas only** (not 1D cross sections)
   - 99.93% pixel-level accuracy vs RASMapper
   - Horizontal interpolation validated, sloped not yet implemented

2. **Prerequisites** (Markdown)
   - geopandas, rasterio, h5py (standard data science stack)
   - No HEC-RAS installation needed
   - Works on Linux, Mac, Windows

3. **Project Setup** (Code)
   ```python
   from ras_commander import RasExamples, init_ras_project, RasMap

   project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")
   init_ras_project(project_path, "6.6")

   # Compute plan (requires HEC-RAS, but only once)
   RasCmdr.compute_plan("06", skip_existing=True)
   ```

4. **Generate Rasters Programmatically** (Code)
   ```python
   # Pure Python rasterization from HDF
   outputs = RasMap.map_ras_results(
       plan_number="06",
       variables=["WSE", "Depth", "Velocity"],
       terrain_path="Terrain/Terrain50.tif",
       output_dir="python_gis_outputs",
       interpolation_method="horizontal"
   )

   for var, path in outputs.items():
       print(f"{var}: {path}")
   ```

5. **Batch Processing** (Code)
   ```python
   # Process multiple plans
   for plan_num in ["01", "06"]:
       outputs = RasMap.map_ras_results(
           plan_number=plan_num,
           variables=["WSE"],
           output_dir=f"outputs/plan_{plan_num}"
       )
   ```

6. **Visualization** (Code)
   ```python
   import rasterio
   import matplotlib.pyplot as plt
   import numpy as np

   with rasterio.open(outputs["WSE"]) as src:
       data = src.read(1, masked=True)
       plt.imshow(data, cmap='terrain')
       plt.title("Maximum WSE - Python-GIS")
       plt.colorbar(label='Elevation (ft)')
   ```

7. **Technical Explanation: Mesh Rasterization** (Markdown + Code)

   **Algorithm Overview**:

   1. **Extract Mesh Geometry** (from geometry HDF):
      ```python
      # Get mesh cell polygons
      mesh_gdf = HdfMesh.get_mesh_cell_polygons(geom_hdf_path)
      # Returns: GeoDataFrame with Polygon geometries
      ```

   2. **Extract Results** (from plan HDF):
      ```python
      # Get maximum water surface elevation per cell
      wse_max = HdfResultsMesh.get_mesh_max_ws(plan_hdf_path)
      # Returns: Array matching mesh cell order
      ```

   3. **Horizontal Interpolation**:
      - Each mesh cell gets **constant WSE value**
      - No variation within cell boundaries
      - Matches RASMapper "Horizontal" rendering mode

      ```python
      # Create (geometry, value) pairs
      shapes = [
          (geom, float(val))
          for geom, val in zip(mesh_gdf.geometry, wse_values)
          if not np.isnan(val)
      ]

      # Rasterize to grid
      raster_data = rasterio.rasterize(
          shapes=shapes,
          out_shape=(height, width),
          transform=grid_transform,
          fill=np.nan,
          dtype='float32',
          all_touched=False  # Exact cell boundaries
      )
      ```

   4. **Wet Cell Filtering**:
      - Only cells with depth > 0 are rasterized
      - Matches RASMapper behavior
      - Prevents "dry cell" artifacts

   5. **Depth Calculation**:
      ```python
      # WSE - Terrain = Depth
      depth_raster = wse_raster - terrain_raster
      depth_raster[depth_raster <= 0] = np.nan
      ```

   6. **Velocity Aggregation**:
      - Extract max face velocity per cell
      - Average face velocities to get cell velocity
      - Formula: `cell_velocity = max(face_velocities)`

8. **Validation Against RASMapper** (Markdown + Code)
   ```python
   # Compare with RASMapper output
   rasmap_wse = rasterio.open("RASMapper_WSE.tif").read(1)
   python_wse = rasterio.open(outputs["WSE"]).read(1)

   # Calculate RMSE
   valid = ~np.isnan(rasmap_wse) & ~np.isnan(python_wse)
   rmse = np.sqrt(np.mean((rasmap_wse[valid] - python_wse[valid])**2))

   print(f"RMSE: {rmse:.6f}")  # Expected: 0.000000
   print(f"Pixel match: {valid.sum() / np.isfinite(rasmap_wse).sum():.2%}")
   # Expected: 99.93%
   ```

   **Validation Results**:
   - Pixel count accuracy: **99.93%** (1,058 edge pixels difference)
   - Value accuracy (RMSE): **0.000000** (exact match where both valid)
   - Edge pixels differ due to anti-aliasing in RASMapper

9. **Limitations** (Markdown)
   - **2D Mesh Only**: Does not support 1D cross section results
   - **Horizontal Interpolation Only**: Sloped mode raises NotImplementedError
   - **No Time-Series GUI**: Must manually specify time indices
   - **Memory Usage**: Large meshes (1M+ cells) may require chunking

10. **When to Use This Approach** (Markdown)
    - ✅ Cloud/headless environments (Docker, AWS, Azure)
    - ✅ Reproducible workflows (no GUI variability)
    - ✅ Integration with Python analysis pipelines
    - ✅ 2D mesh projects only
    - ❌ Mixed 1D/2D projects
    - ❌ Need for additional variables (Froude, D*V)
    - ❌ Want native HEC-RAS rendering

11. **Future Enhancements** (Markdown)
    - Sloped interpolation (cell corner elevations)
    - 1D cross section support
    - Additional variables (Froude, shear stress)
    - Performance optimization (parallel chunking)

---

### 4. Delete Old Broken Notebooks

**Files to Delete**:
```bash
git rm "examples/15_stored_map_generation  --- GUI Automation fails - no maps in rasmapper   .ipynb"
git rm "examples/25_programmatic_result_mapping    --- GUI Automation fails - no maps in rasmapper.ipynb"
```

**Note**: `21_rasmap_raster_exports...` already doesn't exist

---

### 5. Update Documentation References

#### File: `examples/AGENTS.md`

**Current Section** (find and replace):
```markdown
## Floodplain Mapping

- `15_stored_map_generation.ipynb` - Generate stored maps (BROKEN)
- `25_programmatic_result_mapping.ipynb` - Python GIS approach (BROKEN)
- `26_rasprocess_stored_maps.ipynb` - RasProcess CLI approach
```

**New Section**:
```markdown
## Floodplain Mapping

Three distinct approaches for generating flood inundation rasters:

- **`15_a_floodplain_mapping_gui.ipynb`** - RASMapper GUI Automation
  - Uses: `RasMap.postprocess_stored_maps()` with GUI automation
  - Pros: Visual feedback, verify in RASMapper
  - Cons: Fragile, Windows-only, requires GUI
  - Recommendation: **Least recommended** (clunky)

- **`15_b_floodplain_mapping_rasprocess.ipynb`** - RasProcess CLI ⭐
  - Uses: `RasProcess.store_maps()` CLI tool
  - Pros: **Fastest**, native HEC-RAS rendering, all variables
  - Cons: Windows-only
  - Recommendation: **Most optimal for Windows**

- **`15_c_floodplain_mapping_python_gis.ipynb`** - Python-GIS Method
  - Uses: `RasMap.map_ras_results()` mesh rasterization
  - Pros: Cloud-compatible, pure Python, 99.93% accurate
  - Cons: **2D mesh only**, limited variables
  - Recommendation: Cloud/headless environments

**Decision Matrix**:
- Windows batch processing → Use 15_b (RasProcess)
- Cloud/Docker environment → Use 15_c (Python-GIS, if 2D only)
- Need visual verification → Use 15_a (GUI)
```

#### Search for References in Skills/Subagents

**Command**:
```bash
rg "15_stored_map|25_programmatic|26_rasprocess" .claude/skills/ .claude/subagents/
```

**Update any references** to point to new 15_a, 15_b, 15_c notebooks.

---

## Testing Checklist

Before committing, verify:

- [ ] `ensure_rasmap_compatible()` function works with 5.0.7 project
- [ ] `ensure_rasmap_compatible()` handles already-upgraded 6.x projects
- [ ] Notebook 15_a executes without errors (BaldEagleCrkMulti2D)
- [ ] Notebook 15_b executes without errors
- [ ] Notebook 15_c executes without errors
- [ ] All three notebooks generate valid GeoTIFF outputs
- [ ] Visualizations render correctly in all three notebooks
- [ ] Technical explanations are accurate and detailed
- [ ] AGENTS.md updated correctly
- [ ] No broken references in skills/subagents
- [ ] Old notebooks (15, 25) successfully deleted

**Test Command**:
```bash
pytest --nbmake examples/15_a_floodplain_mapping_gui.ipynb
pytest --nbmake examples/15_b_floodplain_mapping_rasprocess.ipynb
pytest --nbmake examples/15_c_floodplain_mapping_python_gis.ipynb
```

---

## Commit Strategy

```bash
# Stage new library code
git add ras_commander/RasMap.py
git add ras_commander/RasGuiAutomation.py  # if modified

# Stage new notebooks
git add examples/15_a_floodplain_mapping_gui.ipynb
git add examples/15_b_floodplain_mapping_rasprocess.ipynb
git add examples/15_c_floodplain_mapping_python_gis.ipynb

# Stage deletions
git rm "examples/15_stored_map_generation  --- GUI Automation fails - no maps in rasmapper   .ipynb"
git rm "examples/25_programmatic_result_mapping    --- GUI Automation fails - no maps in rasmapper.ipynb"

# Stage documentation updates
git add examples/AGENTS.md
git add .claude/skills/  # if references updated
git add .claude/subagents/  # if references updated

# Commit
git commit -m "Consolidate floodplain mapping notebooks (4→3)

- Add RasMap.ensure_rasmap_compatible() for 5.0.7→6.x .rasmap upgrades
- Create 15_a (GUI), 15_b (RasProcess), 15_c (Python-GIS) notebooks
- Delete broken notebooks (15, 25)
- Update AGENTS.md with decision matrix
- All three approaches include technical explanations (LLM Forward)

Resolves GUI automation failures due to .rasmap version incompatibility."
```

---

## Timeline Estimate

| Task | Duration | Details |
|------|----------|---------|
| Add `ensure_rasmap_compatible()` | 3 hours | XML parsing, COM automation, testing |
| Update `postprocess_stored_maps()` | 1 hour | Integration, error handling |
| Create notebook 15_a | 3 hours | GUI approach, troubleshooting section |
| Create notebook 15_b | 2 hours | Based on existing 26, add pre-step |
| Create notebook 15_c | 3 hours | Python-GIS, validation section |
| Testing all 3 notebooks | 2 hours | Run with BaldEagleCrkMulti2D |
| Update documentation | 1 hour | AGENTS.md, skills/subagents |
| Refinement | 1 hour | Polish, verify references |
| **TOTAL** | **16 hours** | **~2 working days** |

---

## Critical Implementation Notes

### .rasmap XML Version Detection

**Location**: Look for these XML patterns in .rasmap file:

```xml
<!-- Old 5.0.7 format -->
<RASMapper>
  <Version>5.0.7</Version>
  <!-- Missing <Results> section -->
</RASMapper>

<!-- New 6.x format -->
<RASMapper>
  <Version>6.6</Version>
  <Results>
    <Layer ... />  <!-- Results layers present -->
  </Results>
</RASMapper>
```

**Detection Logic**:
```python
import xml.etree.ElementTree as ET

tree = ET.parse(rasmap_path)
root = tree.getroot()
version = root.find("Version").text  # "5.0.7" or "6.6"
results = root.find("Results")  # None if old format

needs_upgrade = (
    version.startswith("5.") and
    results is None
)
```

### COM Automation Fallback

If win32com automation doesn't work reliably, use direct win32gui approach from notebook 15 cell 16 (which already has working code for opening RASMapper):

```python
# Find HEC-RAS window
hwnd = win32gui.FindWindow(None, "HEC-RAS 6.6")

# Get menu bar
menu_bar = win32gui.GetMenu(hwnd)

# Find "GIS Tools" menu ID (enumerate all menus)
# Find "RAS Mapper" submenu ID
# Click menu item

# Wait for RASMapper window
rasmapper_hwnd = win32gui.FindWindow(None, "RAS Mapper")

# Close RASMapper
win32gui.PostMessage(rasmapper_hwnd, win32con.WM_CLOSE, 0, 0)
```

This code pattern already exists in the current broken notebook 15 and can be extracted.

---

## Success Criteria

✅ **All three notebooks execute successfully** with BaldEagleCrkMulti2D example
✅ **Technical explanations included** (mesh rasterization, GUI automation, CLI process)
✅ **.rasmap upgrade automation works** for 5.0.7→6.x projects
✅ **Clear decision matrix** showing when to use each method
✅ **Documentation updated** (AGENTS.md, skills, subagents)
✅ **Zero broken references** across codebase
✅ **Old broken notebooks deleted** (15, 25)

---

## Future Work (Deferred to nb-004)

**Full Notebook Reorganization** - Tracked in backlog:
- Systematic renumbering into logical categories
- Recursive reference checking across entire codebase
- Create missing notebooks (Atlas 14, structure results, etc.)
- Complete AGENTS.md rewrite

**Estimated**: 28 hours (~3-4 days) after this consolidation completes

---

## Related Documentation

- **Plan File**: `C:\Users\billk_clb\.claude\plans\rippling-foraging-rainbow.md`
- **Backlog Item**: `agent_tasks/.agent/BACKLOG.md` (nb-004)
- **LLM Forward Principles**: Root CLAUDE.md
- **Notebook Standards**: `.claude/rules/documentation/notebook-standards.md`
- **Hierarchical Knowledge**: `.claude/rules/documentation/hierarchical-knowledge-best-practices.md`

---

**End of Plan Document**
