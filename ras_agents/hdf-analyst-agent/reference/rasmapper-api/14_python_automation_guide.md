# Python Automation Guide for RASMapper

This guide provides practical approaches for automating RASMapper operations from Python, based on the decompiled source code analysis.

---

## Table of Contents

1. [Automation Strategies](#1-automation-strategies)
2. [RasProcess.exe Command-Line Interface](#2-rasprocessexe-command-line-interface)
3. [Direct .NET Interop via pythonnet](#3-direct-net-interop-via-pythonnet)
4. [Pure Python Implementations](#4-pure-python-implementations)
5. [Practical Examples](#5-practical-examples)
6. [Integration with ras-commander](#6-integration-with-ras-commander)

---

## 1. Automation Strategies

### Strategy Comparison

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **RasProcess.exe CLI** | Official, stable, no dependencies | Requires HEC-RAS install, subprocess overhead | Map export, preprocessing |
| **pythonnet (.NET)** | Full API access | Requires .NET runtime, complex setup | Advanced operations |
| **Pure Python** | No dependencies, full control | Development effort | Interpolation, analysis |
| **Hybrid** | Flexibility | Complexity | Production workflows |

### Recommended Approach

For **ras-commander**, use a hybrid strategy:

1. **RasProcess.exe** for geometry preprocessing and map export
2. **Pure Python** for interpolation and analysis (already implemented)
3. **HDF5 direct access** for results data (h5py)

---

## 2. RasProcess.exe Command-Line Interface

RASMapper includes a headless command processor at:
```
C:\Program Files\HEC\HEC-RAS\6.x\RasProcess.exe
```

### Command Syntax

```bash
# Direct command execution
RasProcess.exe -Command=<CommandName> -<Arg>=<Value> ...

# XML command file execution
RasProcess.exe -CommandFile=<path_to_command.xml>
```

### Available Commands

| Command | Purpose | Key Arguments |
|---------|---------|---------------|
| `StoreMap` | Export single result map | Result, MapType, ProfileName, OutputBaseFilename |
| `StoreAllMaps` | Batch export all maps | Result, MapTypes (list) |
| `GenerateMesh` | Create 2D mesh | PerimeterFilename, GeometryFilename, CellSize, Name |
| `CompleteGeometry` | Run geometry preprocessor | GeometryFilename |
| `CompletePreprocess` | Full preprocessing pipeline | ProjectFilename |
| `CreateGeometry` | Create new geometry file | GeometryFilename, ProjectFilename |
| `ComputePropertyTables` | Compute HTAB tables | GeometryFilename |
| `ExportGeometry` | Export geometry to format | GeometryFilename, OutputFilename, Format |
| `RemoveResults` | Delete result files | ResultFilename |

### Python Wrapper

```python
import subprocess
from pathlib import Path
from typing import Optional, List
import xml.etree.ElementTree as ET
import tempfile

class RasProcess:
    """Python wrapper for RasProcess.exe command execution."""

    def __init__(self, ras_version: str = "6.6"):
        """Initialize with HEC-RAS version."""
        self.exe_path = Path(f"C:/Program Files/HEC/HEC-RAS/{ras_version}/RasProcess.exe")
        if not self.exe_path.exists():
            raise FileNotFoundError(f"RasProcess.exe not found at {self.exe_path}")

    def _run_command(self, cmd_name: str, args: dict, timeout: int = 300) -> subprocess.CompletedProcess:
        """Execute a RasProcess command."""
        cmd = [str(self.exe_path), f"-Command={cmd_name}"]
        for key, value in args.items():
            if value is not None:
                cmd.append(f"-{key}={value}")

        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _run_xml_command(self, command_xml: ET.Element, timeout: int = 300) -> subprocess.CompletedProcess:
        """Execute a command from XML element."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            tree = ET.ElementTree(command_xml)
            tree.write(f.name, encoding='unicode')
            cmd = [str(self.exe_path), f"-CommandFile={f.name}"]
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def store_map(
        self,
        result_file: str,
        map_type: str,
        profile_name: str,
        output_file: Optional[str] = None,
        terrain: Optional[str] = None
    ) -> Path:
        """
        Export a result map to GeoTIFF.

        Args:
            result_file: Path to .p##.hdf file
            map_type: One of: depth, elevation, velocity, etc.
            profile_name: Profile name (e.g., "Max", time stamp)
            output_file: Optional output filename (auto-generated if None)
            terrain: Optional terrain file override

        Returns:
            Path to generated TIF file
        """
        args = {
            "Result": str(result_file),
            "MapType": map_type,
            "ProfileName": profile_name,
        }
        if output_file:
            args["OutputBaseFilename"] = str(output_file)
        if terrain:
            args["Terrain"] = str(terrain)

        result = self._run_command("StoreMap", args)
        if result.returncode != 0:
            raise RuntimeError(f"StoreMap failed: {result.stderr}")

        # Parse output filename from stdout if not specified
        if output_file:
            return Path(output_file)
        # Default naming convention
        return Path(result_file).with_suffix(f".{map_type}.tif")

    def generate_mesh(
        self,
        perimeter_shp: str,
        geometry_file: str,
        mesh_name: str,
        cell_size: float,
        min_face_ratio: float = -1
    ) -> None:
        """
        Generate a 2D mesh from perimeter shapefile.

        Args:
            perimeter_shp: Path to perimeter polygon shapefile
            geometry_file: Path to geometry file (.g##)
            mesh_name: Name for the 2D flow area
            cell_size: Target cell size in map units
            min_face_ratio: Minimum face length ratio (-1 for default)
        """
        args = {
            "PerimeterFilename": str(perimeter_shp),
            "GeometryFilename": str(geometry_file),
            "Name": mesh_name,
            "CellSize": str(cell_size),
        }
        if min_face_ratio > 0:
            args["MinFaceLengthRatio"] = str(min_face_ratio)

        result = self._run_command("GenerateMesh", args)
        if result.returncode != 0:
            raise RuntimeError(f"GenerateMesh failed: {result.stderr}")

    def complete_geometry(self, geometry_file: str) -> None:
        """
        Run geometry preprocessor (create .g##.hdf).

        Args:
            geometry_file: Path to geometry file (.g##)
        """
        args = {"GeometryFilename": str(geometry_file)}
        result = self._run_command("CompleteGeometry", args, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"CompleteGeometry failed: {result.stderr}")

    def complete_preprocess(self, project_file: str) -> None:
        """
        Run full preprocessing pipeline for project.

        Args:
            project_file: Path to project file (.prj)
        """
        args = {"ProjectFilename": str(project_file)}
        result = self._run_command("CompletePreprocess", args, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(f"CompletePreprocess failed: {result.stderr}")

    def batch_store_maps(
        self,
        result_file: str,
        map_types: List[str],
        profile_name: str,
        output_dir: Optional[str] = None
    ) -> List[Path]:
        """
        Export multiple map types in batch.

        Args:
            result_file: Path to .p##.hdf file
            map_types: List of map types to export
            profile_name: Profile name
            output_dir: Output directory (default: same as result)

        Returns:
            List of paths to generated TIF files
        """
        outputs = []
        for map_type in map_types:
            output = None
            if output_dir:
                output = Path(output_dir) / f"{Path(result_file).stem}.{map_type}.tif"
            outputs.append(self.store_map(result_file, map_type, profile_name, output))
        return outputs
```

### Usage Example

```python
# Initialize wrapper
rp = RasProcess("6.6")

# Export depth map
depth_tif = rp.store_map(
    result_file="Project.p01.hdf",
    map_type="depth",
    profile_name="Max"
)

# Generate mesh from shapefile
rp.generate_mesh(
    perimeter_shp="perimeter.shp",
    geometry_file="Project.g01",
    mesh_name="2D Flow Area",
    cell_size=50.0
)

# Run preprocessing
rp.complete_geometry("Project.g01")

# Batch export
tifs = rp.batch_store_maps(
    result_file="Project.p01.hdf",
    map_types=["depth", "elevation", "velocity"],
    profile_name="Max"
)
```

---

## 3. Direct .NET Interop via pythonnet

For advanced operations not exposed via CLI, use pythonnet to directly call RASMapper's .NET API.

### Setup

```bash
pip install pythonnet
```

### Basic Connection

```python
import clr
import sys

# Add RASMapper DLL path
ras_path = r"C:\Program Files\HEC\HEC-RAS\6.6"
sys.path.append(ras_path)

# Load assemblies
clr.AddReference("RasMapperLib")
clr.AddReference("H5Assist")
clr.AddReference("Geospatial")

# Import namespaces
from RasMapperLib import RASGeometry, RASResults, SharedData
from RasMapperLib.Mapping import MapTypes, RASResultsMap
from RasMapperLib.Scripting import StoreMapCommand, GenerateMeshCommand
```

### Direct API Calls

```python
# Load geometry
geometry = RASGeometry(r"C:\Project\Model.g01")

# Access mesh
mesh = geometry.D2FlowArea.Feature(0)  # MeshFV2D
print(f"Cells: {mesh.CellCount}, Faces: {mesh.FaceCount}")

# Load results
results = RASResults.TryIdentifyResultsFile(r"C:\Project\Model.p01.hdf")

# Create result map
result_map = RASResultsMap(results, MapTypes.Depth)
result_map.TrySetProfile("Max")
result_map.StoreMap()  # Exports TIF
```

### Accessing Mesh Topology

```python
from RasMapperLib.Mesh import Cell, Face, FacePoint

# Get cell topology
for i in range(mesh.NonVirtualCellCount):
    cell = mesh.Cell(i)
    print(f"Cell {i}: {cell.Faces.Count} faces")

    # Get face points (vertices)
    facepoints = mesh.CellFacePoints(i)
    for fp_idx in facepoints:
        fp = mesh.FacePoints[fp_idx]
        print(f"  Vertex: ({fp.Point.X}, {fp.Point.Y})")
```

### Caveats

1. **Thread Safety**: RASMapper is not thread-safe; use locks for parallel operations
2. **GUI Dependencies**: Some classes require WinForms initialization
3. **Memory Management**: Explicitly dispose of large objects
4. **Version Compatibility**: DLLs change between HEC-RAS versions

---

## 4. Pure Python Implementations

For maximum portability, implement algorithms in pure Python. Key implementations already in ras-commander:

### Ben's Weights (Implemented)

```python
def compute_bens_weights(pixel_xy, vertices):
    """
    Compute generalized barycentric weights for arbitrary polygon.

    Args:
        pixel_xy: (x, y) tuple for query point
        vertices: List of (x, y) vertex coordinates (CCW order)

    Returns:
        numpy array of weights, one per vertex
    """
    import numpy as np

    n = len(vertices)
    px, py = pixel_xy

    # Compute cross-products from pixel to each edge
    cross_products = np.zeros(n)
    for i in range(n):
        v1 = vertices[i]
        v2 = vertices[(i + 1) % n]
        # Cross product: (v1-p) x (v2-p)
        cross_products[i] = (v1[0] - px) * (v2[1] - py) - (v1[1] - py) * (v2[0] - px)

    # Handle zero cross-products (pixel on edge)
    cross_products[np.abs(cross_products) < 1e-10] = 1e-5

    # Compute raw weights
    weights = np.zeros(n)
    for i in range(n):
        # Product of all cross-products except adjacent edges
        prev_i = (i - 1) % n
        product = 1.0
        for j in range(n):
            if j != i and j != prev_i:
                product *= cross_products[j]

        # Additional cross-product factor
        v_prev = vertices[prev_i]
        v_curr = vertices[i]
        v_next = vertices[(i + 1) % n]
        tri_cross = (v_curr[0] - v_prev[0]) * (v_next[1] - v_prev[1]) - \
                    (v_curr[1] - v_prev[1]) * (v_next[0] - v_prev[0])

        weights[i] = product * tri_cross

    # Normalize
    weight_sum = np.sum(weights)
    if weight_sum != 0:
        weights /= weight_sum

    # Clamp negative weights (pixel outside convex hull)
    if np.any(weights < 0):
        weights[weights < 0] = 0
        weight_sum = np.sum(weights)
        if weight_sum > 0:
            weights /= weight_sum

    return weights
```

### Face WSE Computation (Implemented)

See `ras_commander/mapping/interpolation.py` for full implementation.

### Scanline Rasterization

```python
def rasterize_polygon_scanline(polygon_vertices, raster_transform, raster_shape, values):
    """
    Rasterize polygon with barycentric interpolation.

    Args:
        polygon_vertices: List of (x, y, z) vertices
        raster_transform: Affine transform (from rasterio)
        raster_shape: (rows, cols) output shape
        values: Value at each vertex to interpolate

    Returns:
        numpy array with interpolated values (NaN outside polygon)
    """
    import numpy as np
    from rasterio.transform import rowcol

    output = np.full(raster_shape, np.nan, dtype=np.float32)

    # Get bounding box in pixel coordinates
    xs = [v[0] for v in polygon_vertices]
    ys = [v[1] for v in polygon_vertices]

    min_row, min_col = rowcol(raster_transform, min(xs), max(ys))
    max_row, max_col = rowcol(raster_transform, max(xs), min(ys))

    # Clamp to raster bounds
    min_row = max(0, min_row)
    max_row = min(raster_shape[0], max_row + 1)
    min_col = max(0, min_col)
    max_col = min(raster_shape[1], max_col + 1)

    # Iterate over pixels in bounding box
    vertices_2d = [(v[0], v[1]) for v in polygon_vertices]

    for row in range(min_row, max_row):
        for col in range(min_col, max_col):
            # Get pixel center coordinates
            x, y = raster_transform * (col + 0.5, row + 0.5)

            # Compute weights
            weights = compute_bens_weights((x, y), vertices_2d)

            # Check if inside polygon (all weights non-negative)
            if np.all(weights >= 0) and np.sum(weights) > 0:
                # Interpolate value
                output[row, col] = np.sum(weights * values)

    return output
```

---

## 5. Practical Examples

### Example 1: Batch Map Export Workflow

```python
from pathlib import Path
from ras_commander import init_ras_project, ras

# Initialize project
project_path = Path("C:/Projects/DamBreak")
init_ras_project(project_path, "6.6")

# Get all plan HDFs
plan_hdfs = list(project_path.glob("*.p*.hdf"))

# Initialize RasProcess wrapper
rp = RasProcess("6.6")

# Export maps for each plan
for hdf in plan_hdfs:
    for map_type in ["depth", "elevation", "velocity"]:
        try:
            output = rp.store_map(
                result_file=str(hdf),
                map_type=map_type,
                profile_name="Max",
                output_file=str(project_path / "Maps" / f"{hdf.stem}.{map_type}.tif")
            )
            print(f"Exported: {output}")
        except Exception as e:
            print(f"Error exporting {hdf.name} {map_type}: {e}")
```

### Example 2: Mesh Generation Pipeline

```python
import geopandas as gpd
from shapely.geometry import Polygon

# Create perimeter from polygon
perimeter = gpd.GeoDataFrame({
    'geometry': [Polygon([
        (0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)
    ])]
}, crs="EPSG:26915")

# Save to shapefile
perimeter.to_file("perimeter.shp")

# Generate mesh
rp = RasProcess("6.6")
rp.generate_mesh(
    perimeter_shp="perimeter.shp",
    geometry_file="Project.g01",
    mesh_name="FloodPlain2D",
    cell_size=100.0
)

# Run preprocessing
rp.complete_geometry("Project.g01")
```

### Example 3: Compare Python vs RASMapper Output

```python
import numpy as np
import rasterio
from ras_commander import RasMap

# Generate map using ras-commander (Python)
python_output = RasMap.map_ras_results(
    plan_number="01",
    variables=["WSE"],
    terrain_path="Terrain/terrain.tif",
    interpolation_method="sloped"
)

# Export using RASMapper
rp = RasProcess("6.6")
rasmapper_tif = rp.store_map(
    result_file="Project.p01.hdf",
    map_type="elevation",
    profile_name="Max"
)

# Compare
with rasterio.open(python_output["WSE"]) as py_src:
    py_data = py_src.read(1)

with rasterio.open(rasmapper_tif) as rm_src:
    rm_data = rm_src.read(1)

# Compute difference statistics
valid = (py_data != py_src.nodata) & (rm_data != rm_src.nodata)
diff = py_data[valid] - rm_data[valid]

print(f"Mean diff: {np.mean(diff):.4f}")
print(f"Median |diff|: {np.median(np.abs(diff)):.4f}")
print(f"Max |diff|: {np.max(np.abs(diff)):.4f}")
print(f"RMSE: {np.sqrt(np.mean(diff**2)):.4f}")
```

---

## 6. Integration with ras-commander

### Proposed Module: `ras_commander.rasmapper`

```python
# ras_commander/rasmapper/__init__.py

from .rasprocess import RasProcess
from .map_export import export_maps, export_all_maps
from .preprocessing import complete_geometry, complete_preprocess
from .mesh_generation import generate_mesh

__all__ = [
    'RasProcess',
    'export_maps',
    'export_all_maps',
    'complete_geometry',
    'complete_preprocess',
    'generate_mesh'
]
```

### High-Level API

```python
# Future ras-commander API
from ras_commander import RasMapper

# Export maps (uses RasProcess.exe if available, falls back to Python)
RasMapper.export_maps(
    plan_number="01",
    map_types=["WSE", "Depth", "Velocity"],
    profile="Max",
    output_dir="Maps"
)

# Generate mesh
RasMapper.generate_mesh(
    geometry_number="01",
    perimeter_shapefile="perimeter.shp",
    mesh_name="Floodplain",
    cell_size=100
)

# Run preprocessing
RasMapper.preprocess(geometry_number="01")
```

---

## Summary

| Use Case | Recommended Approach |
|----------|---------------------|
| Map export (TIF) | RasProcess.exe `StoreMap` |
| Mesh generation | RasProcess.exe `GenerateMesh` |
| Geometry preprocessing | RasProcess.exe `CompleteGeometry` |
| Result interpolation | Pure Python (ras-commander) |
| Time series analysis | Pure Python (h5py + numpy) |
| Advanced mesh operations | pythonnet (if needed) |
| Mesh fixing/repair | pythonnet or pure Python port |

---

*Generated: 2025-12-09*
*Based on RASMapper decompilation analysis*
