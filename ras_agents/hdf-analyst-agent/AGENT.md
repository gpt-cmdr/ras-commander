# HDF Analyst Agent

**Purpose**: Production-ready reference documentation for HDF file analysis, RASMapper interpolation algorithms, and water surface rasterization.

**Domain**: HDF data extraction, mesh interpolation, water surface rendering

**Status**: Production (migrated from feature_dev_notes with security verification)

---

## ⚠️ IMPORTANT DISCLAIMER - Clean-Room Implementation

All algorithm implementations in ras-commander are **clean-room Python code**, NOT derived from decompiled source.

**Research Methodology:**
- Reverse-engineered RASMapper behavior through decompilation analysis
- Documented algorithms as behavioral specifications
- Implemented independently in Python
- Validated through black-box testing (pixel-perfect match)

**Legal Status:**
- HEC-RAS is public domain U.S. government software
- Decompilation for interoperability is legally permissible
- Python implementation is independent work, not copied code
- Decompiled source used only as reference (not migrated to tracked repository)

**Ethics:**
- Clean-room implementation documented here
- No proprietary .NET code redistributed
- Algorithms described, not copied
- Attribution to USACE/HEC-RAS maintained

---

## Primary Sources

**Production Implementation**:
- `ras_commander/RasMap.py` - RASMapper interpolation and stored map processing
  - `interpolate_mesh_to_raster()` - Main interpolation function
  - Horizontal mode: Constant WSE per cell
  - Sloped mode: Ben's Weights 3-stage algorithm
- `ras_commander/hdf/HdfMesh.py` - Mesh geometry extraction
- `ras_commander/hdf/HdfResultsMesh.py` - Mesh result time series

**Algorithm Specifications** (this directory):
- `reference/algorithms/rasmapper-interpolation-reference.md` - Complete algorithm reference
- `reference/algorithms/bens-weights-discovery.md` - Key discovery ("THE_ANSWER")
- `reference/algorithms/sloped-interpolation.md` - Sloped algorithm validated
- `reference/algorithms/horizontal-interpolation.md` - Horizontal algorithm
- `reference/algorithms/vertex-wse-calculation.md` - Vertex WSE formula
- `reference/algorithms/interpolation-analysis.md` - Validation analysis
- `reference/algorithms/horizontal-clipping.md` - Clipping investigation
- `reference/algorithms/sloped-algorithm-spec.md` - Full specification

**RASMapper Python API Documentation**:
- `reference/rasmapper-api/` - Complete RASMapper Python automation docs (16 files)
  - 00_INDEX.md through 16_rasprocess_cli_reference.md
  - Mesh, mapping, render, terrain, structures namespaces
  - Python automation guide and CLI reference

**Research Documentation**:
- `reference/research-overview.md` - Complete research summary
- `reference/decompilation-report.md` - Technical and legal analysis
- `reference/index.md` - Content navigation

**Working Examples**:
- `examples/25_programmatic_result_mapping.ipynb` - Complete mapping workflow
- `examples/26_rasprocess_stored_maps.ipynb` - RASProcess automation

**Decompilation Methodology**:
- `ras_agents/decompilation-agent/AGENT.md` - Decompilation approach
- `ras_agents/decompilation-agent/reference/DECOMPILATION_GUIDE.md` - ILSpy usage

---

## Quick Reference

### Interpolate Water Surface to Raster

```python
from ras_commander import init_ras_project, RasMap

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Interpolate using horizontal method (constant WSE per cell)
raster = RasMap.interpolate_mesh_to_raster(
    plan_number="01",
    time_index=-1,  # Final time step
    mode="horizontal",
    output_file="wse.tif"
)

# Interpolate using sloped method (Ben's Weights)
raster = RasMap.interpolate_mesh_to_raster(
    plan_number="01",
    time_index=-1,
    mode="sloped",  # Smooth gradient across cells
    output_file="wse_sloped.tif"
)
```

### Access Mesh Geometry

```python
from ras_commander.hdf import HdfMesh

# Get cell polygons
cells = HdfMesh.get_mesh_cell_polygons("01")  # GeoDataFrame

# Get vertex coordinates
vertices = HdfMesh.get_mesh_face_points("01")  # (x, y) array

# Get cell connectivity
faces = HdfMesh.get_mesh_faces("01")  # Cell-face mapping
```

### Extract Mesh Results

```python
from ras_commander.hdf import HdfResultsMesh

# Get WSE time series for all cells
wse_series = HdfResultsMesh.get_mesh_timeseries(
    "01",
    variables=["Water Surface"],
    time_window=(0, -1)  # All time steps
)

# Get maximum WSE per cell
max_wse = HdfResultsMesh.get_mesh_summary(
    "01",
    variable="Maximum Water Surface"
)
```

---

## Interpolation Algorithms

### Horizontal Mode (Constant WSE)

**Description:**
- Each cell has single water surface elevation
- All pixels within cell receive same WSE value
- Clipping: Only assign depth where terrain < WSE

**Use When:**
- Fast rasterization needed
- Cell-averaged results acceptable
- Flat terrain or low-resolution meshes

**Performance:** Fast (simple polygon rasterization)

### Sloped Mode (Ben's Weights)

**Description:**
- 3-stage process creates smooth gradients across cells
- Stage 1: Compute face WSE using hydraulic connectivity
- Stage 2: Compute vertex WSE via planar regression
- Stage 3: Rasterize using generalized barycentric coordinates

**Use When:**
- High-quality visualization needed
- Variable terrain within cells
- Smooth water surface gradients desired

**Performance:** Slower (3-stage computation)

**Validation:** Pixel-perfect match with RASMapper (< 0.001 ft error)

**See**: `reference/algorithms/sloped-interpolation.md` for complete 3-stage algorithm.

### Ben's Weights Discovery

**Key Formula** (simplified approximation):
```python
# For 4-cell interior vertices (94% of vertices):
vertex_wse = 0.72 * mean(adjacent_cell_wse) + 0.28 * max(adjacent_cell_wse)

# For 2-3 cell boundary vertices:
vertex_wse = mean(adjacent_cell_wse)
```

**RMSE:** 0.019 ft at vertices (simpler than full planar regression)

**See**: `reference/algorithms/bens-weights-discovery.md` for discovery narrative ("THE_ANSWER").

---

## RASMapper Python API

**Automation Capabilities:**
- Create stored maps via Python API
- Trigger RASProcess CLI for batch processing
- Filter and export raster results
- Automate map generation workflows

**Key Namespaces:**
- `Mesh` - Mesh geometry access
- `Mapping` - Map layer configuration
- `Render` - Rendering operations
- `Terrain` - Terrain data
- `Structures` - Structure visualization

**See**: `reference/rasmapper-api/` for complete API documentation (16 files).

---

## HDF Structure Insights

### Mesh Geometry HDF Structure

**Key Datasets** (`Geometry/2D Flow Areas/{area}/`):
- `Cells Center Coordinate` - Cell centroids (x, y)
- `Cells Minimum Elevation` - Terrain minimum per cell
- `FacePoints Coordinate` - Vertex coordinates
- `Faces FacePoint Indexes` - Face connectivity
- `Faces Cell Indexes` - Face to cell mapping
- `Faces Minimum Elevation` - Terrain minimum along face

**Discovery:** Vertex WSE computed on-the-fly from cell values, NOT pre-computed in HDF.

### Plan Results HDF Structure

**Key Datasets** (`Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{area}/`):
- `Water Surface` - Cell WSE time series [cells × timesteps]
- `Face Velocity` - Face velocity (optional)
- `Cell Volume` - Cell volume time series

**Maximum Results** (`Results/Unsteady/Summary Output/2D Flow Areas/{area}/`):
- `Maximum Water Surface` - Max WSE per cell
- `Time of Maximum Water Surface` - Time index of maximum

**Discovery:** Only cell-centered values stored. All face/vertex values derived.

---

## Common Workflows

### 1. Programmatic Result Mapping

**Goal**: Create WSE raster without RASMapper GUI

```python
from ras_commander import init_ras_project, RasMap

init_ras_project("/path/to/project", "6.5")

# Generate raster using sloped interpolation
RasMap.interpolate_mesh_to_raster(
    plan_number="01",
    time_index=-1,
    mode="sloped",
    output_file="max_wse.tif",
    resolution=10.0  # 10 ft pixel size
)
```

**See**: `examples/25_programmatic_result_mapping.ipynb` for complete workflow.

### 2. RASProcess Stored Maps Automation

**Goal**: Batch-generate stored maps using RASProcess CLI

```python
from ras_commander import RasMap

# Trigger RASProcess to create all stored maps
RasMap.generate_stored_maps(
    project_file="/path/to/project.prj",
    rasmap_file="/path/to/project.rasmap"
)
```

**See**: `examples/26_rasprocess_stored_maps.ipynb` and `reference/rasmapper-api/16_rasprocess_cli_reference.md`.

### 3. Compare Interpolation Methods

**Goal**: Validate interpolation accuracy

```python
# Generate both horizontal and sloped
horizontal_raster = RasMap.interpolate_mesh_to_raster(..., mode="horizontal")
sloped_raster = RasMap.interpolate_mesh_to_raster(..., mode="sloped")

# Compute difference
import rasterio
with rasterio.open("horizontal.tif") as h, rasterio.open("sloped.tif") as s:
    diff = s.read(1) - h.read(1)
    print(f"Mean difference: {diff[diff != 0].mean():.4f} ft")
```

**See**: `reference/algorithms/interpolation-analysis.md` for validation methodology.

---

## Navigation Map

**Need interpolation algorithm details?**
→ `reference/algorithms/rasmapper-interpolation-reference.md` (complete spec)
→ `reference/algorithms/bens-weights-discovery.md` (key discovery narrative)

**Need implementation code?**
→ `ras_commander/RasMap.py` (production Python code)

**Need RASMapper automation?**
→ `reference/rasmapper-api/14_python_automation_guide.md`
→ `reference/rasmapper-api/16_rasprocess_cli_reference.md`

**Need HDF structure reference?**
→ `ras_commander/hdf/AGENTS.md` (complete HDF module guide)

**Need working example?**
→ `examples/25_programmatic_result_mapping.ipynb`

**Need decompilation methodology?**
→ `ras_agents/decompilation-agent/` (ILSpy usage and ethics)

---

## Migration Notes

**Source**: `feature_dev_notes/RasMapper Interpolation/` (gitignored, 5.7GB total)

**Migrated**: 2025-12-12

**Content**: 28 markdown files (~255KB) - algorithm specs and RASMapper API docs

**Excluded**:
- ❌ Decompiled C# source (947 files, ~50MB) - Copyright/ethical concerns
- ❌ Test data (5.7GB HEC-RAS projects) - Size constraints
- ❌ Python scripts with hard-coded paths (40 files) - Machine-specific

**Security Verification**: PASSED ✅
- Zero .cs files (no decompiled source)
- Zero .dll or .exe files (no binaries)
- Zero hard-coded paths (C:\GH, D:\)
- Only markdown documentation files

**Clean-Room Status**: ✅
- Algorithm descriptions, not copied code
- Independent Python implementation in ras-commander
- Validated through behavioral testing
- Ethical decompilation practices documented

**Original Content**: Available in gitignored `feature_dev_notes/` for development reference (not accessible to automated agents).

---

**Last Updated**: 2025-12-12
**Status**: Production Ready ✅
**Security**: Audited and Verified ✅
**Legal**: Clean-Room Implementation ✅
**Coverage**: 2 interpolation modes (horizontal, sloped) fully documented ✅
