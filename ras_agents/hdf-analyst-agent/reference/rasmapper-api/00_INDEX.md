# RASMapper Decompiled Code Documentation

This documentation provides a comprehensive analysis of RASMapper's decompiled source code (RasMapperLib.dll) for the purposes of:

1. **Building parallel Python functionality** - Replicating RASMapper algorithms in Python for the ras-commander library
2. **Direct automation** - Calling RASMapper functionality programmatically for HEC-RAS project automation

## Source Information

- **Library**: RasMapperLib.dll (decompiled)
- **Version**: HEC-RAS 6.x
- **Original Language**: VB.NET (compiled to .NET IL)
- **Total Files**: 936 C# source files
- **Decompilation Tool**: ILSpy/dnSpy

---

## Table of Contents

### Core Namespaces

| # | Document | Namespace | Description |
|---|----------|-----------|-------------|
| 01 | [Mesh Namespace](01_mesh_namespace.md) | `RasMapperLib.Mesh` | Core mesh data structures: Cell, Face, FacePoint, Vector2D |
| 02 | [Mapping Namespace](02_mapping_namespace.md) | `RasMapperLib.Mapping` | Result mapping, rasterization, map types (WSE, Depth, Velocity) |
| 03 | [Render Namespace](03_render_namespace.md) | `RasMapperLib.Render` | Rendering modes, color ramps, visualization |
| 04 | [Terrain Namespace](04_terrain_namespace.md) | `RasMapperLib.Terrain` | Terrain processing, raster operations |
| 05 | [Structures Namespace](05_structures_namespace.md) | `RasMapperLib.Structures` | Hydraulic structures (bridges, culverts, weirs) |
| 06 | [EditLayers Namespace](06_editlayers_namespace.md) | `RasMapperLib.EditLayers` | Layer editing, mesh modification operations |
| 07 | [Core Geometry](07_core_geometry.md) | `RasMapperLib` | Point, Polygon, Polyline, TIN, Barycentric coordinates |
| 08 | [Scripting Namespace](08_scripting_namespace.md) | `RasMapperLib.Scripting` | **Command-based automation API** |
| 09 | [Utilities Namespace](09_utilities_namespace.md) | `RasMapperLib.Utilities` | Helper functions, file I/O |
| 10 | [TinHelpers Namespace](10_tinhelpers_namespace.md) | `RasMapperLib.TinHelpers` | TIN construction and interpolation |
| 11 | [ArrivalTime Namespace](11_arrivaltime_namespace.md) | `RasMapperLib.ArrivalTime` | Flood arrival time calculations |
| 12 | [Functional Namespace](12_functional_namespace.md) | `RasMapperLib.Functional` | Functional programming utilities |
| 13 | [RASGeometryMapPoints](13_rasgeometrymappoints.md) | `RasMapperLib` | **Critical interpolation algorithms (Ben's Weights)** |

### Guides

| Document | Description |
|----------|-------------|
| [Python Automation Guide](14_python_automation_guide.md) | How to call RASMapper from Python |
| [Filter Features](15_filter_features.md) | Attribute filtering and polygon simplification algorithms |
| [**RasProcess.exe CLI Reference**](16_rasprocess_cli_reference.md) | **Complete CLI documentation (UNDOCUMENTED)** |
| [Algorithm Reference](17_algorithm_reference.md) | Key algorithms with Python implementations |

---

## Quick Reference: Automation Options

### Option A: Direct Command Execution via RasProcess.exe

RASMapper exposes a command-line interface through `RasProcess.exe`:

```bash
# Command-line syntax
RasProcess.exe -Command=<CommandName> -<Arg1>=<Value1> -<Arg2>=<Value2>

# Or via XML command file
RasProcess.exe -CommandFile=<path_to_command.xml>
```

**Available Commands** (from `RasMapperLib.Scripting` namespace):

| Command | Purpose |
|---------|---------|
| `StoreMap` | Generate and export result maps (WSE, Depth, Velocity, etc.) |
| `StoreAllMaps` | Batch export all result maps |
| `GenerateMesh` | Create 2D mesh from perimeter shapefile |
| `CreateGeometry` | Create new geometry file |
| `CompleteGeometry` | Finalize geometry with preprocessor |
| `CompletePreprocess` | Run geometry preprocessing |
| `ComputePropertyTables` | Compute hydraulic property tables |
| `ExportGeometry` | Export geometry to various formats |
| `LoadSaveGeometry` | Load and save geometry files |
| `SetGeometryAssociation` | Set terrain/land cover associations |
| `RemoveResults` | Remove result files |
| `LaunchRasMapper` | Launch RASMapper GUI |
| `GeneratePostProcess` | Generate post-processing outputs |
| `CompleteEvent` | Complete event processing |
| `DownloadFiles` | Download web resources |
| `MergePolygon` | Merge polygon features |
| `DiffH5` | Compare HDF5 files |

### Option B: Python via pythonnet/clr

```python
import clr
clr.AddReference("RasMapperLib")
from RasMapperLib.Scripting import StoreMapCommand

# Create and execute command
cmd = StoreMapCommand()
cmd.Result = "path/to/plan.hdf"
cmd.MapType = MapTypes.Depth
cmd.ProfileName = "Max"
cmd.Execute()
```

### Option C: Replicate Algorithms in Pure Python

Use ras-commander's `RasMap` module which implements:
- Horizontal interpolation (validated)
- Sloped interpolation with Ben's Weights (validated)

```python
from ras_commander import RasMap

outputs = RasMap.map_ras_results(
    plan_number="01",
    variables=["WSE", "Depth", "Velocity"],
    terrain_path="Terrain/terrain.tif",
    interpolation_method="sloped"  # Uses Ben's Weights
)
```

---

## Key Algorithms

### Ben's Weights (Generalized Barycentric Coordinates)

**Location**: `RASGeometryMapPoints.BensWeights()` (line ~2895)

Used for interpolating values within arbitrary polygonal mesh cells. The algorithm:

1. Computes cross-products from pixel location to each face edge
2. Calculates weights using product of all other cross-products
3. Normalizes weights to sum to 1.0
4. Handles negative weights (pixel outside cell) by clamping

**Python Implementation**: See `ras_commander/mapping/interpolation.py`

### Face WSE Computation

**Location**: `RASGeometryMapPoints.ComputeFacePointWaterSurfaces()`

Determines water surface elevation at cell vertices using:
- Backfill rules (from downhill cells)
- Levee/weir handling
- Depth-weighted averaging
- Terrain gradient consideration

### Rasterization

**Location**: `RasterizeTriangles.cs`, `RasterizeSegment.cs`

Converts mesh results to raster format:
- Triangle rasterization with barycentric interpolation
- Scanline algorithms for polygon filling
- Edge handling and anti-aliasing

### Polygon Simplification

**Location**: `Polygon.cs` (FilterXY, FilterXYIterative, FilterByArea methods)

Three polygon simplification algorithms:
- **Douglas-Peucker-Ramer (by tolerance)** - Remove vertices within tolerance distance
- **Douglas-Peucker-Ramer (by point count)** - Iterative binary search to target vertex count
- **Minimum Area Reduction** - Visvalingam-Whyatt algorithm, removes smallest-area vertices

**Python Implementation**: See [Filter Features](15_filter_features.md)

---

## Namespace File Counts

| Namespace | File Count | Key Classes |
|-----------|------------|-------------|
| `RasMapperLib` (root) | ~400 | RASGeometry, RASGeometryMapPoints, Layer |
| `RasMapperLib.Mesh` | 15 | Cell, Face, FacePoint, MeshStatus |
| `RasMapperLib.Mapping` | ~30 | MapTypes, RASResultsMap, OutputModes |
| `RasMapperLib.Render` | ~20 | RenderMode, ColorScale |
| `RasMapperLib.Terrain` | ~15 | TerrainLayer, TerrainTile |
| `RasMapperLib.Structures` | ~25 | Bridge, Culvert, Weir, Levee |
| `RasMapperLib.EditLayers` | ~50 | FeatureEditor, EditOperation |
| `RasMapperLib.Scripting` | 22 | Command, StoreMapCommand, GenerateMeshCommand |
| `RasMapperLib.Utilities` | ~20 | FileHelpers, PathUtilities |
| `RasMapperLib.TinHelpers` | ~10 | TinBuilder, TinInterpolator |
| `RasMapperLib.ArrivalTime` | ~5 | ArrivalTimeCalculator |
| `RasMapperLib.Functional` | ~5 | FunctionalExtensions |

---

## Dependencies

RASMapper depends on these external libraries:

- **H5Assist** - HDF5 file access
- **Geospatial.GDALAssist** - GDAL/OGR operations
- **TiffAssist** - GeoTIFF reading/writing
- **Utility** - General utilities, progress reporting
- **Microsoft.VisualBasic** - VB.NET runtime support

---

## Usage Notes

### For Python Developers

1. **Prefer pure Python implementations** when possible (ras-commander's `RasMap` module)
2. **Use RasProcess.exe** for operations that are difficult to replicate (mesh generation, preprocessing)
3. **pythonnet** requires .NET Framework/Mono and adds complexity

### For Direct .NET Integration

1. Reference `RasMapperLib.dll` from HEC-RAS installation
2. Also reference dependent DLLs (H5Assist, Geospatial, etc.)
3. Use `RasMapperLib.Scripting.Command` subclasses for automation

### Key Findings for Automation

1. **StoreMapCommand** is the primary way to export result maps programmatically
2. **GenerateMeshCommand** can create meshes from shapefiles without GUI
3. **CompletePreprocess** runs geometry preprocessing headlessly
4. All commands can be serialized to XML for batch processing

---

## Document Status

| Document | Status |
|----------|--------|
| 00_INDEX.md | Complete |
| 01-13 | Complete (namespace documentation) |
| 14_python_automation_guide.md | Complete |
| 15_filter_features.md | Complete |
| 16_rasprocess_cli_reference.md | **Complete** (NEW - undocumented CLI) |
| 17_algorithm_reference.md | Pending |

---

*Generated: 2025-12-09*
*Source: RasMapperLib.dll decompilation*
