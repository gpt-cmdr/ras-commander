# HDF Structure Reference

Detailed reference for HEC-RAS HDF5 file structure.

## File Types

| File | Description |
|------|-------------|
| `.p##.hdf` | Plan results (unsteady/steady output) |
| `.g##.hdf` | Preprocessed geometry (hydraulic tables) |
| `Terrain.hdf` | Terrain data |
| `*.tif.hdf` | Raster data (land cover, soil, etc.) |
| `Land Cover.*.hdf` | Land cover classification data |
| `Soils.*.hdf` | Soil classification data |

## Data Provenance: Plain Text vs HDF Primary

!!! warning "Critical Concept for Automation"
    Understanding where HEC-RAS stores **authoritative data** is essential before attempting any programmatic modifications.

### The Two Data Sources

HEC-RAS maintains data in two locations with different roles:

| Storage Type | File Types | Authoritative? | Direct Edit Safe? |
|--------------|------------|----------------|-------------------|
| Plain Text | `.prj`, `.p##`, `.g##`, `.f##`, `.u##` | Yes (usually) | Yes |
| HDF | `.hdf` (various types) | Sometimes | With extreme caution |

### Plain Text as Primary (HDF is Derived)

For most model components, **plain text files are the authoritative source**. HDF contains copies that are regenerated when you run the geometry preprocessor or execute plans:

| Data Category | Plain Text Source | HDF Location | Regeneration Trigger |
|---------------|-------------------|--------------|---------------------|
| Cross Sections | `.g##` (Sta/Elev, Mann n) | `/Geometry/Cross Sections/` | Geometry preprocessor |
| 2D Flow Area Perimeter | `.g##` | `/Geometry/2D Flow Areas/` | Geometry preprocessor |
| Storage Areas | `.g##` | `/Geometry/Storage Areas/` | Geometry preprocessor |
| SA/2D Connections | `.g##` (weir profiles, gates) | `/Geometry/Structures/` | Geometry preprocessor |
| Lateral Structures | `.g##` | `/Geometry/Structures/` | Geometry preprocessor |
| Inline Weirs | `.g##` | `/Geometry/Structures/` | Geometry preprocessor |
| Bridges/Culverts | `.g##` | `/Geometry/Structures/` | Geometry preprocessor |
| Plan Settings | `.p##` | `/Plan Data/` | Plan execution |
| Boundary Conditions | `.u##` | `/Event Conditions/` | Plan execution |
| Steady Flow Data | `.f##` | (included in results) | Plan execution |

**Rule**: For these data types, edit the plain text file, then let HEC-RAS regenerate the HDF.

### HDF as Primary (No Plain Text Equivalent)

These data types are **only stored in HDF** - there is no plain text representation:

| Data Category | HDF File Type | HDF Location | Why HDF-Only |
|---------------|---------------|--------------|--------------|
| **Gridded Precipitation** | `.p##.hdf` | `/Event Conditions/Meteorology/` | Raster/gridded data too large for text |
| **Gridded Land Cover** | `Land Cover.*.hdf` | `//Raster Map`, `//Variables` | Raster classification + attribute table |
| **Gridded Soils** | `Soils.*.hdf` | `//Raster Map`, `//Variables` | Raster classification + attribute table |
| **Infiltration Base Overrides** | `.g##.hdf` | `/Geometry/Infiltration/Base Overrides` | Calibration region table |
| **Pipe Networks** | `.g##.hdf` | `/Geometry/Pipe Networks/` | Complex 3D pipe network |
| **Terrain Data** | `Terrain.hdf` | `//Elevation` | Native raster format |
| **Computed Results** | `.p##.hdf` | `/Results/` | Time series output |
| **Computed Mesh Geometry** | `.g##.hdf` | `/Geometry/2D Flow Areas/*/Cells` | Generated from perimeter |
| **Hydraulic Tables (HTAB)** | `.g##.hdf` | `/Geometry/Cross Sections/Property Tables/` | Computed cross section properties |

**Rule**: For these data types, direct HDF editing is required - but with extreme care to match HEC-RAS's exact expectations. See the [HDF Writing Guide](hdf-writing-guide.md).

### Hybrid Cases

Some data exists in both locations with different information:

| Data | Plain Text Contains | HDF Contains |
|------|---------------------|--------------|
| **2D Flow Areas** | Perimeter polygon, parameters | Full computed mesh (cells, faces, property tables) |
| **Cross Sections** | Station-elevation points, roughness | Property tables (HTAB), indexed geometry |
| **Structures** | Weir profiles, gate parameters | Indexed/processed versions |

For hybrids, the plain text holds the **input definition** while HDF holds **computed/processed versions**.

### Practical Implications

**For most automation tasks:**

1. **Modify the plain text** file (`.g##`, `.p##`, `.u##`)
2. **Run geometry preprocessor** if you changed geometry
3. **Run the plan** to regenerate results HDF

**For HDF-only data (gridded data, infiltration overrides):**

1. **Create reference files** by doing the workflow manually in HEC-RAS
2. **Analyze HDF structure** using HDFView or h5py
3. **Match structure exactly** (dtype, compression, chunks, fill values)
4. **Validate** by opening in HEC-RAS and running simulation

See the [HDF Writing Guide](hdf-writing-guide.md) for detailed instructions on safe HDF modification.

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
