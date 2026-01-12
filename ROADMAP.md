# ras-commander Feature Roadmap

This document tracks planned features and enhancements for ras-commander.

## Analysis Features

### 1D Benefit Areas Analysis

**Status**: Planned

**Description**: Extend benefit area analysis to 1D cross section models.

**Current State**:
- ✅ 2D mesh benefit areas implemented (`HdfBenefitAreas.identify_benefit_areas()`)
- ❌ 1D cross section benefit areas not yet implemented

**Proposed API**:
```python
HdfBenefitAreas.identify_benefit_areas_1d(
    existing_hdf_path: Union[str, Path],
    proposed_hdf_path: Union[str, Path],
    min_delta: float = 0.1,
    interpolation_method: str = "linear",  # How to create polygons from XS lines
    ras_object: Optional[Any] = None
) -> Dict[str, gpd.GeoDataFrame]
```

**Returns**: Dictionary with GeoDataFrames:
- `benefit_reaches`: River reaches with net WSE reduction
- `rise_reaches`: River reaches with net WSE increase
- `existing_xs_profiles`: Cross section water surface profiles (existing)
- `proposed_xs_profiles`: Cross section water surface profiles (proposed)
- `difference_xs_profiles`: WSE differences at each cross section

**Technical Approach**:

1. **Extract XS Water Surfaces**:
   - Use `HdfResultsXsec.get_xs_timeseries()` for max WSE at each cross section
   - Match cross sections by river/reach/station

2. **Compare WSE at Cross Sections**:
   - Compute difference: `proposed_wse - existing_wse` (same sign convention as 2D)
   - Filter by `min_delta` threshold
   - Classify as benefit (negative) or rise (positive)

3. **Create Benefit Polygons** (Challenge):
   - **Option A**: Thiessen polygons around cross sections
   - **Option B**: River corridor buffer with interpolation
   - **Option C**: Interpolate between XS, create polygons from banks
   - **Option D**: Use storage area polygons if available

4. **Aggregate by Reach**:
   - Group contiguous cross sections showing benefit/rise
   - Calculate reach-level statistics (avg reduction, length affected)

**Use Cases**:
- Levee projects (1D riverine models)
- Channel improvement analysis
- Bridge/culvert impact assessment
- Floodplain mapping updates

**Challenges**:
1. **Polygon creation**: 1D cross sections are lines, not areas
   - Need interpolation method to create 2D polygons
   - Floodplain boundary definition (bank stations? terrain?)
2. **Spatial resolution**: Coarser than 2D (XS spacing typically 100s of feet)
3. **Mixed 1D/2D models**: How to handle combined models?

**Priority**: Medium - 1D models are common, but 2D is current focus

**Dependencies**:
- `HdfResultsXsec` (already exists)
- `HdfXsec.get_xs_geometry()` for XS locations
- Polygon interpolation method (new)

**Estimated Scope**: Medium (200-400 lines)

**References**:
- 2D implementation: `ras_commander/hdf/HdfBenefitAreas.py`
- XS results: `ras_commander/hdf/HdfResultsXsec.py`
- XS geometry: `ras_commander/hdf/HdfXsec.py`

---

## Precipitation & Rain-on-Grid Features

### Atlas 14 Gridded AEP Events for HEC-RAS

**Status**: Planned

**Description**: Direct Atlas 14 gridded precipitation (AEP design storms) to
HEC-RAS gridded precipitation boundaries using the same NetCDF/GDAL pathway as
AORC. This replaces the incorrect hyetograph <-> gridded conversion placeholders.

**Current State**:
- Atlas14Grid provides depth grids (NetCDF lat/lon, pf_###_hr, inches) for
  duration/return period, but no time-series export for HEC-RAS.
- PrecipAorc.download + RasUnsteady.set_gridded_precipitation works for gridded
  time-series data (NetCDF time/x/y, EPSG:5070).
- No direct Atlas 14 gridded export path for HEC-RAS design storms.

**Planned Approach**:
1. Extract Atlas 14 depth grids for project extent and chosen AEP/duration.
2. Apply a temporal distribution (Atlas14Storm or FrequencyStorm) to build a
   time series per grid cell.
3. Write NetCDF in the same structural format as AORC output:
   - dims: time, y, x
   - variable: APCP_surface (mm)
   - CRS: EPSG:5070 (SHG), 2000 m grid
4. Configure unsteady files via RasUnsteady.set_gridded_precipitation and run.

**Not Planned (remove placeholders)**:
- convert_hydrograph_to_gridded(...)
- convert_gridded_to_hydrograph(...)

---

## Validation & Boundary Condition Features

### Automated Lateral BC Creation from USGS Gauge Locations

**Priority**: Medium-High
**Status**: Planned
**Motivating Use Case**: Notebook 915 - Bald Eagle Creek multi-gauge validation
**Target Module**: `ras_commander/geom/RasGeometry2D.py` (new)

#### Problem Statement

Current validation workflows require manual geometry editing to add lateral inflow boundaries at tributary confluences where USGS gauges are located. This is time-consuming and error-prone, especially when setting up multi-gauge validation networks with 4+ lateral inflows.

**Example**: Bald Eagle Creek validation requires adding:
- Spring Creek inflow BC (USGS 01547100, 142 sq mi drainage area)
- Marsh Creek inflow BC (USGS 01547700, 44 sq mi)
- Beech Creek inflow BC (USGS 01547980, 170 sq mi)
- Fishing Creek inflow BC (USGS 01548079, 180 sq mi)

Currently requires: Manual HEC-RAS GUI operations or complex geometry file text editing.

#### Proposed Solution

**Function**: `RasGeometry2D.create_lateral_bc_from_gauge()`

**Purpose**: Automatically create SA/2D Area Conn boundary conditions from USGS gauge coordinates by analyzing mesh cell face topology and generating valid connection linestrings.

**High-Level Algorithm**:

1. **Find nearest external mesh cell faces to gauge location** (default: 20 faces, configurable)
2. **Combine face linestrings** into continuous boundary line
3. **Offset linestring** away from mesh interior (default: 50 ft, configurable)
4. **Trim linestring ends** by percentage to avoid corners (default: 7.5%, configurable 5-10%)
5. **Add SA/2D Area Conn** to geometry file with proper fixed-width format
6. **Add BC reference** to unsteady file (optional)
7. **Validate geometry** - ensure no mesh intersections, valid connection cells

#### Proposed API

```python
from ras_commander.geom import RasGeometry2D

bc_info = RasGeometry2D.create_lateral_bc_from_gauge(
    geom_file: Union[str, Path],           # Geometry file path (.g##)
    gauge_id: str,                         # USGS site number (e.g., "01547100")
    gauge_lat: float,                      # Gauge latitude (decimal degrees)
    gauge_lon: float,                      # Gauge longitude (decimal degrees)
    num_faces: int = 20,                   # Number of mesh faces to include
    offset_distance: float = 50.0,         # Offset from mesh (ft/m, match geom units)
    trim_percent: float = 7.5,             # Trim from each end (%, range 5-10%)
    bc_name: Optional[str] = None,         # BC name (default: gauge station name)
    add_to_unsteady: bool = False,         # Also create BC in unsteady file
    unsteady_file: Optional[Path] = None,  # Unsteady file path (required if add_to_unsteady=True)
    validate_geometry: bool = True,        # Run geometry validation checks
    ras_object: Optional[Any] = None       # RasPrj object for multi-project scenarios
) -> Dict[str, Any]
```

**Returns**:
```python
{
    'bc_name': str,                    # Created BC name
    'sa_conn_line': int,               # Line number in geometry file where BC was added
    'num_faces_used': int,             # Actual number of faces included in BC
    'bc_length_ft': float,             # Total BC linestring length
    'offset_applied_ft': float,        # Actual offset distance applied
    'trim_applied_pct': float,         # Actual trim percentage applied
    'gauge_distance_ft': float,        # Distance from gauge to BC line centroid
    'geometry_valid': bool,            # True if passes HEC-RAS validation checks
    'warnings': List[str],             # Any geometry warnings or concerns
    'bc_coordinates': List[Tuple]      # Actual BC linestring coordinates (for verification)
}
```

#### Implementation Phases

**Phase 1: Mesh Face Spatial Query** (Foundation)
```python
# New methods in HdfMesh
HdfMesh.get_external_faces(geom_hdf) -> GeoDataFrame
HdfMesh.find_nearest_faces(geom_hdf, point, num_faces=20) -> GeoDataFrame
HdfMesh.get_face_linestrings(geom_hdf, face_ids) -> List[LineString]
```

**Phase 2: Linestring Processing** (Geometry Operations)
```python
# Internal helper functions
_combine_face_linestrings(faces: List[LineString]) -> LineString
_offset_linestring_from_mesh(line: LineString, mesh_polygon: Polygon, distance: float) -> LineString
_trim_linestring_ends(line: LineString, trim_percent: float) -> LineString
_validate_bc_linestring(line: LineString, mesh_areas: GeoDataFrame) -> Tuple[bool, List[str]]
```

**Phase 3: Geometry File Editing** (HEC-RAS Format)
```python
# Geometry file operations
_add_sa_2d_conn(geom_file: Path, bc_linestring: LineString, bc_name: str, ...) -> int
_format_sa_2d_conn_entry(coords: List[Tuple], bc_name: str) -> str
_validate_geometry_file(geom_file: Path) -> Tuple[bool, List[str]]
```

**Phase 4: Unsteady File Integration** (Optional)
```python
# Unsteady file operations
_add_bc_reference(unsteady_file: Path, bc_name: str, bc_type: str) -> None
_create_placeholder_hydrograph(num_values: int, initial_flow: float) -> str
```

**Phase 5: Validation & Testing**
- Unit tests with synthetic geometries
- Integration tests with RasExamples projects
- GUI verification (open in HEC-RAS, check for errors)
- Example notebook: `920_automated_bc_creation.ipynb`

**Phase 6: Documentation**
- Add to `.claude/rules/hec-ras/geometry.md`
- Update `ras_commander/geom/CLAUDE.md`
- Create workflow guide in USGS validation documentation

#### Dependencies

**Required Packages**:
- `geopandas` - Spatial operations and GeoDataFrame handling
- `shapely` - Linestring manipulation, offset, trimming
- `scipy` - Spatial indexing (KDTree for nearest neighbor search)
- `numpy` - Array operations

**Leverages Existing Modules**:
- `HdfMesh` - Extract 2D mesh cell face geometry
- `RasGeometry` - Geometry file fixed-width format parsing/writing
- `RasUnsteady` - Unsteady file BC reference management
- `RasUsgsCore` - Gauge metadata retrieval (lat/lon, station name)

#### Testing Strategy

**RasExamples Projects with 2D Meshes**:
1. BaldEagleCrkMulti2D - Multiple potential lateral inflows, real USGS gauges
2. BaldEagleDamBrk - Dam breach with 2D mesh
3. Any other examples with 2D flow areas

**Test Scenarios**:
| Test Case | Configuration | Expected Behavior |
|-----------|---------------|-------------------|
| Single lateral inflow | 1 gauge, 20 faces | Creates valid SA/2D Area Conn |
| Multiple laterals | 4 gauges, 20 faces each | Creates 4 independent BCs |
| Gauge very close | <100 ft from mesh | Uses available faces, may reduce num_faces |
| Gauge far from mesh | >1000 ft | Uses nearest available faces, warns of distance |
| Corner location | Gauge near mesh corner | Trims aggressively to avoid sharp angles |
| Small mesh | <100 cells total | Adapts num_faces to available perimeter |

**Validation Checks** (automated in function):
- ✅ BC linestring doesn't intersect mesh interior
- ✅ BC line is continuous (no gaps)
- ✅ Connection cells are actual perimeter cells
- ✅ Geometry file format compliance (fixed-width)
- ✅ BC appears in RASMapper without errors
- ✅ Model runs without geometry warnings

#### Example Usage

```python
from ras_commander import RasExamples, init_ras_project
from ras_commander.geom import RasGeometry2D
from ras_commander.usgs import get_gauge_metadata, retrieve_flow_data
from ras_commander.usgs.boundary_generation import BoundaryGenerator

# 1. Setup project
project = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="multi_bc")
ras = init_ras_project(project, "6.6")

# 2. Get gauge metadata for lateral inflow (Spring Creek)
gauge_meta = get_gauge_metadata("01547100")

# 3. Automatically create BC from gauge location
bc_result = RasGeometry2D.create_lateral_bc_from_gauge(
    geom_file=project / "BaldEagleDamBrk.g09",
    gauge_id="01547100",
    gauge_lat=gauge_meta['latitude'],
    gauge_lon=gauge_meta['longitude'],
    num_faces=20,           # Use 20 nearest mesh cell faces
    offset_distance=50.0,   # Offset 50 ft from mesh
    trim_percent=7.5,       # Trim 7.5% from each end
    bc_name="Spring Creek Inflow",
    validate_geometry=True,
    ras_object=ras
)

print(f"✓ Created BC: {bc_result['bc_name']}")
print(f"  BC length: {bc_result['bc_length_ft']:.1f} ft")
print(f"  Faces used: {bc_result['num_faces_used']}")
print(f"  Validation: {'PASS' if bc_result['geometry_valid'] else 'FAIL'}")

# 4. Add flow hydrograph to unsteady file (if BC was created successfully)
if bc_result['geometry_valid']:
    # Retrieve USGS flow data
    flow_data = retrieve_flow_data("01547100", "2020-12-22", "2020-12-27")

    # Generate flow table
    flow_table = BoundaryGenerator.generate_flow_hydrograph_table(
        flow_values=flow_data['value'].values,
        interval='1HOUR'
    )

    # Add to unsteady file
    # (requires new method or manual insertion)

# 5. Verify in HEC-RAS GUI
print("\nOpen project in HEC-RAS to verify:")
print("  - New BC appears in RASMapper")
print("  - Geometry file loads without errors")
print("  - BC linestring is positioned correctly at Spring Creek confluence")

# 6. Batch creation for multiple lateral inflows
gauges = {
    "01547100": "Spring Creek",
    "01547700": "Marsh Creek",
    "01547980": "Beech Creek",
    "01548079": "Fishing Creek"
}

for gauge_id, creek_name in gauges.items():
    meta = get_gauge_metadata(gauge_id)
    result = RasGeometry2D.create_lateral_bc_from_gauge(
        geom_file=project / "BaldEagleDamBrk.g09",
        gauge_id=gauge_id,
        gauge_lat=meta['latitude'],
        gauge_lon=meta['longitude'],
        bc_name=f"{creek_name} Inflow",
        ras_object=ras
    )
    print(f"✓ {creek_name}: {result['bc_length_ft']:.0f} ft BC created")
```

#### Technical Challenges

**Challenge 1: Face Ordering and Continuity**
- Mesh cell faces may not be in spatial/topological order
- Need to sort faces to create continuous linestring
- Use centerline direction or confluence orientation to order
- Handle cases where faces aren't contiguous

**Challenge 2: Offset Direction Determination**
- Must offset "away" from mesh interior (outward normal direction)
- Calculate average normal vector for selected faces
- Handle concave sections where offset direction may vary
- Ensure offset doesn't create self-intersections

**Challenge 3: Geometry File Format Compliance**
- SA/2D Area Conn has specific HEC-RAS fixed-width text format
- Must preserve all existing geometry without corruption
- Careful line insertion at correct positions
- Maintain proper section ordering (2D Flow Areas, then connections)

**Challenge 4: HEC-RAS Validation Requirements**
- BC linestring must be completely external to mesh
- Connection cells must be actual perimeter cells (not interior)
- Linestring must be continuous without gaps
- Must not create invalid topology (self-intersections, degenerate segments)

**Challenge 5: CRS and Units Handling**
- Gauge coordinates in WGS84 (lat/lon)
- Mesh geometry in project CRS (various - State Plane, UTM, etc.)
- Offset distance must match geometry units (feet vs meters)
- Proper CRS transformation throughout

#### Success Criteria

- ✅ Creates valid SA/2D Area Conn from gauge lat/lon in <10 seconds
- ✅ BC geometry passes HEC-RAS validation (opens in GUI without errors)
- ✅ BC linestring appears correctly positioned in RASMapper
- ✅ Model computes without geometry errors
- ✅ Flow hydrograph can be successfully applied to created BC
- ✅ Tested on 3+ different 2D mesh geometries with varying cell sizes
- ✅ Handles edge cases (gauge at corners, far from mesh, small meshes)

#### Integration with USGS Validation Workflow

Once implemented, this feature will enable:

```python
# Automated setup of multi-gauge validation network
from ras_commander.geom import RasGeometry2D
from ras_commander.usgs import get_gauge_metadata, retrieve_flow_data

# Define validation network
lateral_gauges = {
    "01547100": "Spring Creek",
    "01547700": "Marsh Creek"
}

# Automatically create BCs for all lateral inflows
for gauge_id, name in lateral_gauges.items():
    # Get gauge location
    meta = get_gauge_metadata(gauge_id)

    # Create BC at mesh perimeter near gauge
    result = RasGeometry2D.create_lateral_bc_from_gauge(
        geom_file="model.g09",
        gauge_id=gauge_id,
        gauge_lat=meta['latitude'],
        gauge_lon=meta['longitude'],
        bc_name=f"{name} Inflow",
        num_faces=20,
        offset_distance=50.0,
        trim_percent=7.5
    )

    # Retrieve and apply USGS flow data
    flow = retrieve_flow_data(gauge_id, start_date, end_date)
    # ... apply to BC in unsteady file
```

**Result**: Multi-gauge validation network set up in minutes instead of hours.

#### Related Features to Develop

1. **Batch BC creation** - Process multiple gauges in one call
2. **BC removal** - Clean up test BCs without manual editing
3. **BC visualization** - Plot all BCs on mesh with gauge locations
4. **Automated BC-to-gauge matching** - Find best BC location given mesh topology
5. **Conflict detection** - Warn if BCs are too close or overlap

#### Estimated Development Scope

- **New code**: 400-600 lines
- **Testing**: 200-300 lines
- **Documentation**: 150-250 lines
- **Example notebook**: 100-150 lines
- **Development time**: 2-3 weeks with testing and documentation

#### Priority Justification

**Medium-High Priority** because:
- Enables professional multi-gauge validation workflows
- Significantly reduces model setup time (hours → minutes)
- Improves validation quality (more BCs = better drainage coverage)
- Differentiator feature (not available in other HEC-RAS automation tools)
- Directly supports ras-commander's LLM Forward validation philosophy

**Not High Priority** because:
- Current manual workflow is functional (just slow)
- Only needed for complex validation scenarios
- Requires significant development and testing effort

---

## Bug Fixes

### Path.resolve() Converts Mapped Drives to UNC Paths on Windows

**Priority**: High
**Status**: ✅ Implemented
**Discovered**: 2026-01-08 (South Belt HEC-RAS 4.1 to 6.6 upgrade)
**Implemented**: 2026-01-08

#### Problem Statement

On Windows systems with mapped network drives (e.g., `H:\` mapped to `\\192.168.x.x\share`), Python's `Path.resolve()` converts the drive letter path to its underlying UNC path. HEC-RAS **cannot read from UNC paths** - it requires drive letter paths.

**Error Observed**:
```
Error loading project data from file:
"\\192.168.3.10\CLB-Engineering\25-001 HCFCD Benefits\...\A100_00_00.prj"
```

**Expected Path**: `H:\25-001 HCFCD Benefits\...\A100_00_00.prj`

#### Affected Code Locations

1. **`ras_commander/RasPrj.py` line 151**: `self.prj_path = self.prj_path.resolve()`
2. **`ras_commander/RasPrj.py` line 1484**: `project_path = Path(project_path).resolve()`

Any other location using `Path.resolve()` on user-provided paths is potentially affected.

#### Current Workaround

A monkey-patch can be applied before importing ras-commander:

```python
from pathlib import Path
import os

_original_resolve = Path.resolve

def _patched_resolve(self, strict=False):
    resolved = _original_resolve(self, strict)
    original_str = str(self)
    # If original started with drive letter but resolved became UNC, keep original
    if (len(original_str) >= 2 and original_str[1] == ':' and
        str(resolved).startswith('\\\\')):
        return self if self.is_absolute() else Path(os.path.abspath(str(self)))
    return resolved

Path.resolve = _patched_resolve

# Now import ras-commander
from ras_commander import init_ras_project
```

#### Proposed Solution

**Option A: Replace `resolve()` with `absolute()`** (Simplest)
- `Path.absolute()` does NOT convert to UNC paths
- May not canonicalize symlinks, but that's rarely needed for HEC-RAS

```python
# Before
self.prj_path = self.prj_path.resolve()

# After
self.prj_path = self.prj_path.absolute()
```

**Option B: Custom `safe_resolve()` helper function**

```python
def safe_resolve(path: Path) -> Path:
    """Resolve path while preserving Windows drive letters.

    On Windows with mapped network drives, Path.resolve() converts
    drive letters (H:\) to UNC paths (\\server\share). HEC-RAS cannot
    read from UNC paths, so we preserve the drive letter format.
    """
    if os.name != 'nt':
        return path.resolve()

    original_str = str(path)
    resolved = path.resolve()

    # If original had drive letter but resolved is UNC, use absolute() instead
    if (len(original_str) >= 2 and original_str[1] == ':' and
        str(resolved).startswith('\\\\')):
        return path.absolute()

    return resolved
```

**Option C: Check for UNC and warn/error**

```python
resolved = path.resolve()
if str(resolved).startswith('\\\\'):
    warnings.warn(
        f"Path resolved to UNC format ({resolved}), which HEC-RAS cannot read. "
        f"Use a mapped drive letter instead.",
        UserWarning
    )
```

#### Testing Strategy

1. Test on local drive (C:\) - should work unchanged
2. Test on mapped network drive (H:\ -> \\server\share) - should preserve H:\
3. Test on direct UNC path (\\server\share) - should work (already UNC)
4. Test on Linux/Mac - should use standard resolve()

#### Files to Modify

- `ras_commander/RasPrj.py` - Primary locations
- `ras_commander/utils/path_utils.py` - Create helper if Option B chosen
- Any other files using `Path.resolve()` on user paths

#### Estimated Scope

- **Code changes**: 10-30 lines
- **Testing**: 50-100 lines
- **Documentation**: Update CLAUDE.md with note about network drives

#### Related Issues

- HEC-RAS COM interface also has path sensitivity
- May affect `shutil.copytree()` if destination path gets resolved
- RASMapper file paths in `.rasmap` files may also be affected

#### Implementation (2026-01-08)

**Solution Implemented: Option B - `safe_resolve()` helper function**

Added `RasUtils.safe_resolve(path)` that:
- Uses standard `resolve()` on local drives and non-Windows
- Falls back to `absolute()` when UNC path detected (preserves drive letter)
- Logs debug message when fallback occurs

**Files Modified**:
- `ras_commander/RasUtils.py` - Added `safe_resolve()` function
- `ras_commander/RasPrj.py` - Updated 5 `.resolve()` calls
- `ras_commander/RasMap.py` - Updated 4 `.resolve()` calls
- `ras_commander/dss/RasDss.py` - Updated 3 `.resolve()` calls
- `.claude/rules/python/path-handling.md` - Added documentation
- `tests/test_safe_resolve.py` - Added unit tests (13 tests)

**Usage**:
```python
from ras_commander.RasUtils import RasUtils

# Instead of: path.resolve()
# Use: RasUtils.safe_resolve(path)
resolved = RasUtils.safe_resolve(Path("H:/Projects/Model.prj"))
```

---

## Future Enhancements

(Additional features can be added here as they are identified)
