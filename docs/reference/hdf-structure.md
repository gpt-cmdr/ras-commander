# HDF Structure Reference

Detailed reference for HEC-RAS HDF5 file structure.

## File Types

| File | Description |
|------|-------------|
| `.p##.hdf` | Plan results (unsteady/steady output) |
| `.g##.hdf` | Preprocessed geometry (hydraulic tables) |
| `Terrain.hdf` | Terrain data |
| `*.tif.hdf` | Raster data (land cover, soil, etc.) |

## Plan Results Structure

```
/
├── Event Conditions/
│   └── Meteorology/
├── Geometry/
│   ├── 2D Flow Areas/
│   │   └── {area_name}/
│   │       ├── Attributes
│   │       ├── Cells Center Coordinate
│   │       ├── Cells Face Point Indexes
│   │       ├── Cells Minimum Elevation
│   │       └── Perimeter/
│   ├── Cross Sections/
│   │   └── Attributes
│   ├── Structures/
│   └── Boundary Conditions/
├── Plan Data/
│   ├── Plan Information
│   └── Plan Parameters
└── Results/
    ├── Summary/
    │   ├── Compute Messages (text)
    │   └── Volume Accounting/
    └── Unsteady/
        └── Output/
            ├── Output Blocks/
            │   └── Base Output/
            │       ├── Summary Output/
            │       │   └── 2D Flow Areas/
            │       │       └── {area_name}/
            │       │           ├── Maximum Water Surface
            │       │           ├── Maximum Water Surface Time
            │       │           └── Maximum Face Velocity
            │       └── Unsteady Time Series/
            │           ├── 2D Flow Areas/
            │           │   └── {area_name}/
            │           │       ├── Water Surface
            │           │       ├── Face Velocity
            │           │       └── Cell Cumulative Precipitation
            │           └── Cross Sections/
            │               └── {river}_{reach}/
            │                   ├── Flow
            │                   └── Water Surface
            └── Geometry Info/
```

## Key Datasets

### 2D Mesh Geometry

| Path | Shape | Description |
|------|-------|-------------|
| `Cells Center Coordinate` | (n_cells, 2) | Cell center X,Y |
| `Cells Face Point Indexes` | (n_cells, max_faces) | Face indices per cell |
| `Cells Minimum Elevation` | (n_cells,) | Cell minimum elevation |
| `Face Points Coordinate` | (n_points, 2) | Face point X,Y |
| `Faces FacePoint Indexes` | (n_faces, 2) | Point indices per face |
| `Faces Cell Indexes` | (n_faces, 2) | Cell indices per face |

### 2D Mesh Results

| Path | Shape | Description |
|------|-------|-------------|
| `Water Surface` | (n_times, n_cells) | WSE time series |
| `Face Velocity` | (n_times, n_faces) | Face velocity time series |
| `Depth` | (n_times, n_cells) | Depth time series |
| `Maximum Water Surface` | (n_cells,) | Max WSE |
| `Maximum Water Surface Time` | (n_cells,) | Time of max WSE |
| `Maximum Face Velocity` | (n_faces,) | Max face velocity |

### Cross Section Results

| Path | Shape | Description |
|------|-------|-------------|
| `Flow` | (n_times, n_xs) | Flow time series |
| `Water Surface` | (n_times, n_xs) | WSE time series |
| `Velocity Channel` | (n_times, n_xs) | Channel velocity |
| `Velocity Total` | (n_times, n_xs) | Total velocity |

### Time Reference

| Dataset | Description |
|---------|-------------|
| `Unsteady Time Series/Time Date Stamp` | String timestamps |
| `Unsteady Time Series/Time` | Numeric time (hours from start) |

## Attributes

### Plan Information

| Attribute | Description |
|-----------|-------------|
| `Plan Name` | Plan title |
| `Short Identifier` | Plan short ID |
| `Simulation Start Time` | Start datetime string |
| `Simulation End Time` | End datetime string |
| `Computation Time Step` | Timestep string |

### 2D Flow Area

| Attribute | Description |
|-----------|-------------|
| `Name` | Flow area name |
| `Cell Count` | Number of cells |
| `Face Count` | Number of faces |
| `Projection` | Coordinate system WKT |

## Data Types

| HEC-RAS Type | HDF Type | Python Type |
|--------------|----------|-------------|
| Float | `H5T_IEEE_F32LE` | `numpy.float32` |
| Double | `H5T_IEEE_F64LE` | `numpy.float64` |
| Integer | `H5T_STD_I32LE` | `numpy.int32` |
| String | `H5T_STRING` | `str` |
| DateTime | `H5T_STRING` | Parse with `parse_ras_datetime()` |

## Accessing with h5py

```python
import h5py
import numpy as np

with h5py.File("project.p01.hdf", "r") as hdf:
    # List groups
    print(list(hdf.keys()))

    # Read dataset
    wse = hdf["/Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/Flow Area/Maximum Water Surface"][:]

    # Read attribute
    plan_name = hdf["/Plan Data/Plan Information"].attrs["Plan Name"]

    # Navigate structure
    def print_structure(name, obj):
        print(name)
    hdf.visititems(print_structure)
```

## Steady vs Unsteady

### Unsteady Results

```
/Results/Unsteady/Output/Output Blocks/Base Output/
├── Summary Output/
│   └── 2D Flow Areas/{area}/
│       ├── Maximum Water Surface
│       └── Maximum Water Surface Time
└── Unsteady Time Series/
    └── 2D Flow Areas/{area}/
        └── Water Surface  # (n_times, n_cells)
```

### Steady Results

```
/Results/Steady/Output/
└── Geometry/
    └── Cross Sections/
        └── {river}_{reach}/
            └── Water Surface  # (n_profiles, n_xs)
```

## Compression

HEC-RAS uses GZIP compression for large datasets. h5py handles this transparently.

## Chunk Size

Large time series are typically chunked along the time axis for efficient access:

```python
with h5py.File("project.p01.hdf", "r") as hdf:
    ds = hdf["/Results/Unsteady/.../Water Surface"]
    print(f"Shape: {ds.shape}")
    print(f"Chunks: {ds.chunks}")
    # Typical: chunks=(1, n_cells) for time-efficient access
```

## Complete Path Reference

### Geometry HDF Paths (.g##.hdf)

| Data Category | HDF Path | ras-commander Method |
|---------------|----------|---------------------|
| **2D Mesh Cells** | `/Geometry/2D Flow Areas/{name}/Cells Center Coordinate` | `HdfMesh.get_mesh_cell_points()` |
| **2D Mesh Polygons** | `/Geometry/2D Flow Areas/{name}/Cells Face Point Indexes` | `HdfMesh.get_mesh_cell_polygons()` |
| **2D Mesh Faces** | `/Geometry/2D Flow Areas/{name}/Faces FacePoint Indexes` | `HdfMesh.get_mesh_faces()` |
| **Cell Elevations** | `/Geometry/2D Flow Areas/{name}/Cells Minimum Elevation` | `HdfMesh.get_mesh_cell_min_elevations()` |
| **Perimeter** | `/Geometry/2D Flow Areas/{name}/Perimeter/` | `HdfMesh.get_mesh_perimeter()` |
| **Cross Section XY** | `/Geometry/Cross Sections/Polyline Info` | `HdfXsec.get_cross_section_coords()` |
| **River Centerline** | `/Geometry/River Centerlines/Polyline Info` | `HdfXsec.get_river_centerlines()` |
| **Bank Lines** | `/Geometry/Bank Lines/Polyline Info` | `HdfXsec.get_bank_lines()` |
| **Structures** | `/Geometry/Structures/` | `HdfStruc.get_structures()` |
| **Pipe Conduits** | `/Geometry/Pipe Networks/Conduits/` | `HdfPipe.get_pipe_conduits()` |
| **Pipe Nodes** | `/Geometry/Pipe Networks/Nodes/` | `HdfPipe.get_pipe_nodes()` |
| **Pump Stations** | `/Geometry/Pump Stations/` | `HdfPump.get_pump_stations()` |
| **Hydraulic Tables** | `/Geometry/Cross Sections/Property Tables/` | `HdfHydraulicTables.get_xs_htab()` |

### Plan Results HDF Paths (.p##.hdf)

| Data Category | HDF Path | ras-commander Method |
|---------------|----------|---------------------|
| **Plan Info** | `/Plan Data/Plan Information` | `HdfPlan.get_plan_info_attrs()` |
| **Simulation Times** | `/Plan Data/Plan Parameters` | `HdfPlan.get_simulation_start_time()` |
| **Compute Messages** | `/Results/Summary/Compute Messages (text)` | `HdfResultsPlan.get_compute_messages()` |
| **Volume Accounting** | `/Results/Summary/Volume Accounting/` | `HdfResultsPlan.get_volume_accounting()` |
| **Runtime Data** | `/Results/Summary/Run Time Window/` | `HdfResultsPlan.get_runtime_data()` |
| **2D Max WSE** | `/Results/Unsteady/.../Summary Output/2D Flow Areas/{name}/Maximum Water Surface` | `HdfResultsMesh.get_mesh_max_ws()` |
| **2D Max Depth** | `/Results/Unsteady/.../Summary Output/2D Flow Areas/{name}/Maximum Depth` | `HdfResultsMesh.get_mesh_max_depth()` |
| **2D Max Velocity** | `/Results/Unsteady/.../Summary Output/2D Flow Areas/{name}/Maximum Face Velocity` | `HdfResultsMesh.get_mesh_max_face_velocity()` |
| **2D WSE Timeseries** | `/Results/Unsteady/.../Unsteady Time Series/2D Flow Areas/{name}/Water Surface` | `HdfResultsMesh.get_mesh_timeseries()` |
| **1D WSE Timeseries** | `/Results/Unsteady/.../Cross Sections/{river}_{reach}/Water Surface` | `HdfResultsXsec.get_xsec_timeseries()` |
| **1D Flow Timeseries** | `/Results/Unsteady/.../Cross Sections/{river}_{reach}/Flow` | `HdfResultsXsec.get_xsec_timeseries()` |
| **Timestamps** | `/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp` | `HdfBase.get_unsteady_timestamps()` |
| **Steady Profiles** | `/Results/Steady/Output/Geometry/Cross Sections/{river}_{reach}/Water Surface` | `HdfResultsPlan.get_steady_wse()` |
| **Steady Profile Names** | `/Results/Steady/Output/Geometry/Cross Sections/Output Profiles/` | `HdfResultsPlan.get_steady_profile_names()` |
| **Breach Data** | `/Results/Unsteady/.../Breach/` | `HdfResultsBreach.get_breach_timeseries()` |

### Common Query Examples

```python
import h5py
from pathlib import Path

hdf_path = Path("project.p01.hdf")

with h5py.File(hdf_path, 'r') as hdf:
    # Get all 2D flow area names
    areas = list(hdf['Geometry/2D Flow Areas'].keys())

    # Get max WSE for first area
    max_wse = hdf[f'Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/{areas[0]}/Maximum Water Surface'][:]

    # Get timestamps
    timestamps = hdf['Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp'][:]

    # Get plan name attribute
    plan_name = hdf['Plan Data/Plan Information'].attrs['Plan Name'].decode()
```

### Path Abbreviations

The full unsteady results path is verbose. Here's the structure:

```
/Results/Unsteady/Output/Output Blocks/Base Output/
├── Summary Output/           # Maximum values
│   └── 2D Flow Areas/{name}/
├── Unsteady Time Series/     # Time series data
│   ├── 2D Flow Areas/{name}/
│   └── Cross Sections/{river}_{reach}/
└── Geometry Info/            # Spatial metadata
```

## See Also

- [HDF Data Extraction](../user-guide/hdf-data-extraction.md) - Using Hdf* classes
- [HDF5 Documentation](https://www.hdfgroup.org/solutions/hdf5/)
- [h5py Documentation](https://docs.h5py.org/)
