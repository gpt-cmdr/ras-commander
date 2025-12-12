# RASMapper Mapping Namespace Documentation

**Decompiled from:** RasMapperLib.dll (RasMapperLib.Mapping namespace)
**Purpose:** Result mapping and rasterization algorithms for HEC-RAS output visualization

---

## Table of Contents

1. [Namespace Overview](#namespace-overview)
2. [Class Hierarchy](#class-hierarchy)
3. [Key Classes](#key-classes)
4. [Map Output Types](#map-output-types)
5. [Rasterization Algorithms](#rasterization-algorithms)
6. [Interpolation Methods](#interpolation-methods)
7. [Python Implementation Notes](#python-implementation-notes)
8. [Automation Opportunities](#automation-opportunities)

---

## Namespace Overview

The `RasMapperLib.Mapping` namespace handles the transformation of HEC-RAS hydraulic results into visualizable map products (rasters, vectors, points). It provides:

- **Map type definitions** (WSE, Depth, Velocity, etc.)
- **Interpolation algorithms** (horizontal flat, sloped cell corners)
- **Cell-to-pixel mapping** structures
- **Output mode configurations** (dynamic vs. stored, surface vs. point)
- **Geometry data structures** (rivers, reaches, cross-sections, 2D meshes, pipe networks)

This namespace is central to understanding how RASMapper generates the TIF files that we're trying to replicate in Python.

---

## Class Hierarchy

```
Mapping Classes:
├── MapTypes (base class)
│   ├── Generic2DMapType (extends MapTypes)
│   └── Generic2DMapTypeTemplate (factory for Generic2DMapType)
│
├── MeshMap (abstract base)
│   ├── FlatMeshMap (horizontal interpolation)
│   └── SlopingMeshMap (sloped interpolation)
│
├── CellMap structures:
│   ├── FlatCellMap (cell → pixel indices)
│   ├── SlopingCellMap (cell → SlopingCellPoint[])
│   ├── Sloping1DCellMap (1D sloped)
│   └── SAMap (storage area map)
│
├── Point structures:
│   ├── SlopingCellPoint (pixel with barycentric weights)
│   ├── Sloping1DCellPoint (1D pixel interpolation)
│   └── XSISMapPoint (cross-section interpolated station)
│
├── RiverMap (geometry model)
│   ├── River, Reach, CrossSection (1D elements)
│   ├── Mesh (2D flow area)
│   ├── PipeNetwork, PipeLink, PipeNode (pipe networks)
│   └── ConnectionElement, Junction, D2Connection
│
├── Generic2DMapParameters (HDF dataset metadata)
├── OutputModes (dynamic vs stored rendering)
└── StoredMapStatus (map file state tracking)
```

---

## Key Classes

### 1. MapTypes (Core Map Type Definitions)

**Purpose:** Defines all available hydraulic map types with metadata, units, color scales, and validation rules.

**Key Static Instances:**
```csharp
public static readonly MapTypes Depth
public static readonly MapTypes Elevation (WSE)
public static readonly MapTypes Velocity
public static readonly MapTypes Flow
public static readonly MapTypes Courant
public static readonly MapTypes Froude
public static readonly MapTypes ShearStress
public static readonly MapTypes StreamPower
public static readonly MapTypes ArrivalTime
public static readonly MapTypes Duration
public static readonly MapTypes DepthTimesVelocity  // Hazard
public static readonly MapTypes DepthTimesVelocitySquared
public static readonly MapTypes ManningsN
public static readonly MapTypes PipeElevation
public static readonly MapTypes PipeVelocity
// ... 43 total types
```

**Key Properties:**
```csharp
string XMLName              // Identifier in .rasmap XML
string Description          // Display name
string DefaultLayerName     // Layer name in GUI
UnitType MapUnitType        // Length, Speed, Time, Pressure, etc.
bool CanAnimate             // Supports time series?
bool SupportsStaticMinMaxProfile   // Max/Min across all timesteps
bool SupportsDynamicMinMaxProfile  // Max/Min within time window
bool NeedsDepthThreshold    // Requires depth cutoff (e.g., Arrival Time)
bool ValidIn1DAreas
bool ValidIn2DAreas
bool ValidInStorageAreas
bool ValidInPipeNetworks
ColorScale DefaultColorScale
double[] DefaultValues      // Color ramp breakpoints
bool DefaultUseDatasetMinMax  // Auto-scale to data range
```

**Key Methods:**
```csharp
static MapTypes LoadFromXMLName(string name)
static MapTypes LoadFromXML(XmlNode node)
static MapTypes LoadFromDescription(string desc)
void XMLSave(XmlElement node)
```

**Automation Value:** Provides complete list of supported map types and their configurations. Python code can enumerate available variables and match them to HDF datasets.

---

### 2. Generic2DMapType (Custom 2D Map Types)

**Purpose:** Represents user-defined or generic 2D-only datasets from HDF files (e.g., sediment transport, bed change).

**Key Properties:**
```csharp
string HDF5Dataset          // HDF path component (e.g., "Bed Change")
string VirtualHDF5Dataset   // Optional virtual dataset for computed values
string OutputBlock          // "Base Output", "Sediment Bed", etc.
OutputBlockLocation OutputBlockLoc  // UnsteadyTimeSeries, SummaryOutput, Geometry
string Units
Action<float[], float[]> AdditionalProcessing  // Optional post-processing
```

**Key Static Map Types:**
```csharp
Generic2DMapType VariableDepth          // Depth with bed change
Generic2DMapType CellBedChange
Generic2DMapType CellBedElevation
Generic2DMapType SubcellBedChange
Generic2DMapType SubcellBedElevation
Generic2DMapType HydraulicBedElevation
Generic2DMapType CellMaximumWaterSurfaceError
Generic2DMapType CumulativeIterations
```

**Automation Value:** Shows how RASMapper discovers and handles arbitrary HDF datasets beyond standard output variables.

---

### 3. Generic2DMapParameters (HDF Metadata Parser)

**Purpose:** Parses HDF dataset attributes to determine how to map results.

**Key Properties:**
```csharp
string Group                // HDF group name
string Name                 // Dataset display name
string Units
Location Location           // Cell, Face, SubCell, SubFace
Coverage Coverage           // Average, Wet, Dry
Orientation Orientation     // Scalar, Normal
bool CanPlot
bool CanInterpolate
int Index                   // Multi-index datasets (e.g., grain size classes)
float Max, Min              // Dataset range
bool HasMinMax
```

**Key Static Methods:**
```csharp
static Dictionary<string, List<Generic2DMapParameters>>
    AvailableGenericDatasets(H5Reader hr, string outputBlockName, string d2FlowAreaName)

static bool Parse(H5Reader hr, string datasetFullPath,
                  OutputBlockLocation outputBlockLoc,
                  ref Generic2DMapParameters mapParams)
```

**HDF Attribute Mapping:**
- `"Location"` → Cell, Face, SubCell, SubFace
- `"Coverage"` → Average, Wet, Dry
- `"Orientation"` → Scalar, Normal
- `"Group"` → Display grouping
- `"Name"` → Display name
- `"Units"` → Unit string
- `"Can Plot"` → Boolean
- `"Can Interpolate"` → Boolean
- `"Maximum Value of Data Set"`, `"Minimum Value of Data Set"` → Data range

**Automation Value:** Shows exact HDF attribute names and parsing logic for discovering datasets dynamically.

---

### 4. OutputModes (Rendering Mode Configuration)

**Purpose:** Defines how maps are computed and stored.

**Static Instances:**
```csharp
OutputModes.DynamicSurface          // On-the-fly rasterization
OutputModes.DynamicPoint            // On-the-fly point extraction
OutputModes.StoredDefaultTerrain    // Pre-computed with current terrain
OutputModes.StoredSpecifiedTerrain  // Pre-computed with alternate terrain
OutputModes.StoredPoint             // Pre-computed point results
OutputModes.StoredPolygonSpecifiedDepth  // Depth contour polygons
OutputModes.StoredPolygonBands      // Multi-depth contour bands
```

**Key Properties:**
```csharp
bool IsDynamic              // Computed on-demand vs. pre-stored
bool IsStored               // Inverse of IsDynamic
bool IsVector               // Vector output (points/polygons)
bool IsRaster               // Raster output (TIF)
bool UseAlternateTerrain    // Use specified terrain vs. default
```

**Automation Value:** Identifies that RASMapper supports both dynamic (real-time) and stored (pre-computed) modes. Stored modes produce TIF files on disk.

---

### 5. MeshMap Hierarchy (Cell-to-Pixel Mapping)

#### 5.1 MeshMap (Abstract Base)

**Purpose:** Base class for mapping mesh cells to raster pixels.

**Key Properties:**
```csharp
int MeshIndex               // Which 2D flow area
List<int> UniqueFaces       // Face IDs used in mapping
List<int> UniqueFacePoints  // Facepoint IDs used
```

**Abstract Method:**
```csharp
abstract List<int> UniqueCells()
```

#### 5.2 FlatMeshMap (Horizontal Interpolation)

**Purpose:** Maps cells to pixels using **horizontal (flat)** interpolation.

**Key Properties:**
```csharp
List<FlatCellMap> Cells     // One per cell that intersects raster
```

**Structure:**
```csharp
class FlatCellMap {
    int Index;                  // Cell ID
    List<int> MapPoints;        // Pixel indices covered by this cell
}
```

**Algorithm Implication:** Each pixel is assigned to one cell (point-in-polygon test). All pixels in a cell get the same value (cell center result).

#### 5.3 SlopingMeshMap (Sloped Interpolation)

**Purpose:** Maps cells to pixels using **sloped (cell corners)** interpolation.

**Key Properties:**
```csharp
List<SlopingCellMap> Cells  // One per cell
```

**Structure:**
```csharp
class SlopingCellMap {
    int Index;                          // Cell ID
    List<SlopingCellPoint> MapPoints;   // Pixels with barycentric weights
}

struct SlopingCellPoint {
    int Index;                  // Pixel index
    float[] FPPrevWeights;      // Weights for facepoint WSE interpolation
    float[] VelocityWeights;    // Separate weights for velocity (flow/subcell)
}
```

**Algorithm Implication:**
- Each pixel stores **barycentric weights** for interpolation
- `FPPrevWeights[]` length = number of facepoints (cell vertices)
- Pixel value = weighted sum of vertex values
- Separate velocity weights support flow-based weighting

**Key Method:**
```csharp
Vector2D ComputeVelocity(Vector2D[] fLocalValues, Vector2D[] fpLocalValues)
```
Computes velocity at pixel using weights for both face velocities and facepoint velocities.

---

### 6. 1D Mapping Classes (Cross-Section Interpolation)

#### 6.1 Sloping1DMeshMap

**Purpose:** Maps 1D cross-sections to pixels with sloped interpolation.

```csharp
class Sloping1DMeshMap {
    int MeshIndex;
    List<Sloping1DCellMap> Cells;
}

class Sloping1DCellMap {
    int Index;                              // XS cell ID
    List<Sloping1DCellPoint> MapPoints;
}

class Sloping1DCellPoint {
    int Index;              // Pixel index
    double FractionAlong;   // Position along XS (0-1)
    int USFace;             // Upstream face ID
    int DSFace;             // Downstream face ID
    double NodeFraction;    // Fraction along node for interpolation
}
```

**Algorithm Implication:** 1D results interpolate between upstream/downstream cross-sections using fractional distances.

---

### 7. Storage Area and Cross-Section Maps

```csharp
class SAMap {
    int ID;                     // Storage area ID
    List<int> MapPoints;        // Pixel indices
}

class MappedXSIS {
    int ID;                     // XS ID
    List<XSISMapPoint> MapPoints;
}

class XSISMapPoint {
    int Index;          // Pixel index
    float Z;            // Elevation
    float M;            // Mannings n (or other attribute)
    float StreamNX;     // Stream normal X component
    float StreamNY;     // Stream normal Y component
}
```

**Purpose:** Maps storage areas and cross-section interpolated stations to raster pixels.

---

### 8. RiverMap (Geometry Data Model)

**Purpose:** Object model for 1D/2D/Pipe geometry (mirrors HDF Geometry structure).

**Key Components:**

#### Rivers and Reaches
```csharp
class River {
    string Name;
    List<Reach> Reaches;
    double Length;
    Polyline CombinedPolyline;
    double[] CumulativeSegLengths;

    List<Reach> GetReachesUpstreamToDownstream()
    List<Reach> GetReachesDownstreamToUpstream()
    List<CrossSection> GetCrossSections()
}

class Reach {
    River River;
    string Name;
    int ID;
    double Length;
    int SegmentCount;
    List<CrossSection> CrossSections;
    ConnectionElement UpstreamConnection;
    ConnectionElement DownstreamConnection;
}

class CrossSection {
    Reach Reach;
    string Name;
    int ID;
    double RiverStationUser;
    double RiverStationComputed_WithRMM;
    bool IsInterpolated;
    double DistanceFromTopOfReach;
    float LeftBankStation;
    float RightBankStation;
    float ChannelLength;
}
```

#### 2D Flow Areas
```csharp
class Mesh {
    string Name;
    int ID;
    int CellCount;
    int NonVirtualCellCount;
    int FaceCount;
    int FacePointCount;
    double CellAverageSize;
    PropertyTablesState PropertyTablesState;
}
```

#### Pipe Networks
```csharp
class PipeNetwork {
    string Name;
    int ID;
    HashSet<int> Nodes;
    HashSet<int> Links;
    Dictionary<int, HashSet<int>> LinkToCellIds;
    Dictionary<int, HashSet<int>> NodeToCellIds;
}

class PipeLink {
    string Name;
    int ID;
    double ConnectedLength;
    PipeNode USNode;
    PipeNode DSNode;
    PipeNetwork Network;
}

class PipeNode {
    string Name;
    int ID;
    List<PipeLink> FlowInLinks;
    List<PipeLink> FlowOutLinks;
    List<PipeNetwork> Networks;
}
```

**Key Methods:**
```csharp
River GetRiver(string rivName)
Reach GetReach(string riverName, string reachName)
CrossSection GetCrossSection(int xsId)
List<CrossSection> GetCrossSectionsOnReach(string riverName, string rchName)
Mesh Get2DArea(string d2Name)
PipeNetwork GetPipeNetwork(string networkName)
```

**Automation Value:** Shows how RASMapper organizes geometry internally. Can be used to navigate HDF geometry structure.

---

### 9. StoredMapStatus (Map File State Tracking)

**Purpose:** Tracks whether stored map files are current or need recomputation.

**Static Instances:**
```csharp
StoredMapStatus.NotCreatedYet
StoredMapStatus.ResultsDontExist
StoredMapStatus.TerrainNotFound
StoredMapStatus.FilesOutOfDate
StoredMapStatus.FilesUpToDate
StoredMapStatus.DifferentParameters
StoredMapStatus.NotApplicable
```

**Key Properties:**
```csharp
string Description
string LongDescription
bool AllowRecompute
```

**Automation Value:** Indicates RASMapper caches map files and validates freshness. Useful for understanding when TIFs are regenerated.

---

## Map Output Types

### Standard Output Variables

| Map Type | XML Name | Units | Valid Areas | Notes |
|----------|----------|-------|-------------|-------|
| **Depth** | `depth` | Length | 1D, 2D, SA | Flood inundation depth |
| **WSE** | `elevation` | Length | 1D, 2D, SA | Water surface elevation |
| **Velocity** | `velocity` | Speed | 1D, 2D | Flow velocity magnitude |
| **Flow** | `flow` | VolumetricFlow | 1D only | Total discharge |
| **Courant** | `courant` | Unitless | 1D, 2D | CFL stability metric |
| **Froude** | `froude` | Unitless | 1D, 2D | Froude number |
| **Shear Stress** | `Shear` | ShearStress | 1D, 2D | Bed shear |
| **Stream Power** | `stream power` | PoundsPerLengthTime | 1D, 2D | Erosive power |
| **Arrival Time** | `arrival time` | Time | 1D, 2D, SA | Time to depth threshold |
| **Duration** | `duration` | Time | 1D, 2D, SA | Inundation duration |
| **D × V** | `depth and velocity` | LengthTimesSpeed | 1D, 2D | Hazard metric |
| **D × V²** | `depth and velocity squared` | LengthTimesSpeedSquared | 1D, 2D | Hazard metric |
| **Energy (Depth)** | `energy_depth` | Length | 1D, 2D, SA | Total energy head |
| **Energy (Elev)** | `energy_elevation` | Length | 1D, 2D, SA | Energy grade line |

### 2D-Specific Variables

| Map Type | XML Name | Valid Areas | Notes |
|----------|----------|-------------|-------|
| **Courant (Residence Time)** | `residenceTime` | 2D | Cell volume turnover |
| **Laplacian U** | `laplacianU` | 2D | Velocity gradient |
| **Laplacian V** | `laplacianV` | 2D | Velocity gradient |
| **Variable Depth** | `variable depth` | 2D | Depth accounting for bed change |
| **Bed Change** | `Bed Change` | 2D | Sediment bed elevation change |
| **Bed Elevation** | `Bed Elevation` | 2D | Current bed elevation |
| **Cell WSE Error** | `Maximum Water Surface Error` | 2D | Convergence metric |
| **Cumulative Iterations** | `Cumulative Max Iterations` | 2D | Solver iterations |

### Pipe Network Variables

| Map Type | XML Name | Notes |
|----------|----------|-------|
| **Pipe WSE** | `pipeelevation` | Water surface in pipe |
| **Pipe Depth** | `pipedepth` | Flow depth in pipe |
| **Pipe % Full** | `pipepercentfull` | Percent of pipe capacity |
| **Pipe Velocity** | `pipevelocity` | Flow velocity |
| **Pipe Invert** | `pipeinvert` | Invert elevation |

### Unit Types

```csharp
enum UnitType {
    Length,
    Speed,
    LengthTimesSpeed,           // D × V
    LengthTimesSpeedSquared,    // D × V²
    PoundsPerArea,
    Area,
    Pressure,
    PressureScientific,
    ShearStress,
    WaveForcing,
    PoundsPerLengthTime,        // Stream Power
    VolumetricFlow,
    Time,
    Percent,
    Concentration,
    Unitless
}
```

---

## Rasterization Algorithms

### Two Primary Methods

RASMapper supports two interpolation methods for 2D areas:

1. **Horizontal (Flat)** - Cell-based constant values
2. **Sloped (Cell Corners)** - Barycentric vertex interpolation

**Controlled by .rasmap settings:**
```xml
<RenderMode>horizontal</RenderMode>           <!-- or "slopingPretty" -->
<UseDepthWeightedFaces>false</UseDepthWeightedFaces>
<ReduceShallowToHorizontal>false</ReduceShallowToHorizontal>
```

### Algorithm Selection Logic

```
IF RenderMode == "horizontal":
    Use FlatMeshMap
    → Each pixel = cell center value

ELSE IF RenderMode == "slopingPretty":
    Use SlopingMeshMap
    → Each pixel = barycentric interpolation of vertex values

    IF UseDepthWeightedFaces:
        → Vertex values computed using hydraulic connectivity rules

    IF ReduceShallowToHorizontal:
        → Shallow cells revert to horizontal method
```

---

## Interpolation Methods

### 1. Horizontal (Flat) Method

**Data Structure:** `FlatMeshMap`

**Algorithm:**
1. For each raster pixel:
   - Determine which cell polygon contains the pixel center
   - Assign pixel value = cell center result value
2. All pixels in the same cell get identical values
3. Sharp discontinuities at cell boundaries

**Pros:**
- Simple, fast
- Exact match to cell-average HDF data
- No risk of extrapolation

**Cons:**
- Blocky appearance
- Ignores terrain slope within cells

**Python Implementation:**
```python
# Pseudo-code
for pixel in raster:
    cell_id = find_containing_cell(pixel.x, pixel.y, cell_polygons)
    pixel.value = cell_results[cell_id]
```

**Status:** ✅ **VALIDATED** - Implemented in `ras_commander.RasMap.map_ras_results()` with `interpolation_method="horizontal"`

---

### 2. Sloped (Cell Corners) Method

**Data Structure:** `SlopingMeshMap` with `SlopingCellPoint`

**Algorithm Overview:**

#### Stage 1: Compute Vertex WSE
1. For each cell, compute WSE at each facepoint (vertex)
2. Uses hydraulic connectivity rules:
   - If vertex is wet: Use terrain + depth
   - If vertex is dry: Use terrain elevation
   - Handles backfilling, levees, terrain gradients

#### Stage 2: Rasterize with Barycentric Interpolation
1. For each pixel in cell:
   - Compute barycentric weights for cell vertices
   - Pixel WSE = Σ(weight[i] × vertex_WSE[i])

**Key Data Structure:**
```csharp
SlopingCellPoint {
    int Index;              // Pixel linear index
    float[] FPPrevWeights;  // [v0_weight, v1_weight, ..., vN_weight]
}
```

**Barycentric Weight Computation:**
- Uses **Ben's Weights** (generalized barycentric coordinates)
- Located in decompiled code: `RASGeometryMapPoints.BensWeights()`
- Supports arbitrary polygon shapes (not just triangles)

**Depth-Weighted Faces:**
- When `UseDepthWeightedFaces = true`
- Modifies vertex WSE based on adjacent cell depths
- Implements hydraulic connectivity constraints

**Shallow Cell Handling:**
- When `ReduceShallowToHorizontal = true`
- Cells with depth < 0.001 ft revert to horizontal method

**Pros:**
- Smooth, realistic appearance
- Respects terrain slope
- Better for visualization

**Cons:**
- More complex
- Can introduce interpolation artifacts
- Vertices at boundaries may extrapolate

**Python Implementation Status:** ✅ **IMPLEMENTED** (2025-12-09)

**Validation Results (Plan 15 - 1D-2D Refined Grid):**
- Median |diff| = 0.0001 ft
- MAE = 0.0106 ft
- 90th percentile = 0.0097 ft
- Essentially perfect agreement with RASMapper

**Key Functions:**
```python
from ras_commander.mapping import (
    compute_bens_weights,      # Barycentric coordinates
    interpolate_pixel_wse,     # Per-pixel interpolation
    rasterize_sloped_wse,      # Full grid rasterization
    compute_face_wse,          # Hydraulic connectivity
    compute_vertex_wse,        # Planar regression
)
```

---

## Python Implementation Notes

### Current Status (as of 2025-12-09)

#### ✅ Completed:

1. **Horizontal Interpolation** (`RasMap.map_ras_results(interpolation_method="horizontal")`)
   - Point-in-polygon cell assignment
   - Validated against RASMapper TIFs

2. **Sloped Interpolation** (`RasMap.map_ras_results(interpolation_method="sloped")`)
   - Ben's Weights barycentric interpolation
   - Face WSE computation with hydraulic connectivity
   - Vertex WSE via planar regression
   - Validated with median error = 0.0001 ft

#### Implementation Details:

**Horizontal Method:**
```python
from ras_commander import RasMap

outputs = RasMap.map_ras_results(
    plan_number="03",
    variables=["WSE", "Depth"],
    terrain_path="Terrain/Terrain.tif",
    interpolation_method="horizontal"
)
```

**Sloped Method:**
```python
outputs = RasMap.map_ras_results(
    plan_number="03",
    variables=["WSE", "Depth"],
    terrain_path="Terrain/Terrain.tif",
    interpolation_method="sloped"
)
```

**Core Algorithm:**
```python
# Stage 1: Compute vertex WSE
face_wse = compute_face_wse(cell_wse, cell_faces, terrain, ...)
vertex_wse = compute_vertex_wse(face_wse, cell_points, facepoint_cell_map)

# Stage 2: Rasterize with Ben's Weights
wse_raster = rasterize_sloped_wse(
    cell_polygons,
    vertex_wse,
    raster_transform,
    method='bens_weights'
)
```

### Required Python Libraries

```python
import rasterio          # Raster I/O
import geopandas as gpd  # Geometry handling
import numpy as np       # Numerical operations
import scipy.spatial     # Spatial algorithms (optional)
from shapely.geometry import Point, Polygon

# ras-commander native:
from ras_commander import HdfMesh, HdfResultsMesh, RasMap
from ras_commander.mapping import compute_bens_weights, interpolate_pixel_wse
```

### Key Algorithms to Replicate

1. **Ben's Weights (Generalized Barycentric Coordinates)**
   - Input: Pixel (x, y), Cell polygon vertices
   - Output: Weight array [w0, w1, ..., wN] where Σw = 1
   - Algorithm: Cross-product weighting from pixel to polygon edges
   - Location in decompiled code: `RASGeometryMapPoints.BensWeights()`

2. **Hydraulic Connectivity (Face WSE Computation)**
   - Rules: Backfill dry vertices, respect levees, honor terrain gradients
   - See: `01_rasmapper_geometry_structure.md` for face connectivity

3. **Vertex WSE Regression**
   - Fit plane through adjacent face WSE values
   - Uses least-squares planar regression

### Known Gaps

1. **29% vertex coverage gap**
   - Vertices at mesh boundaries point to exterior (NODATA) faces
   - Shallow cells (< 0.001 ft depth) treated as dry

2. **Large outliers at 1D-2D connections**
   - Max diff = 40 ft in validation
   - Different handling of hydraulic connectivity edge cases

3. **8% cell polygon failures**
   - 1,193 cells fail with < 3 facepoints
   - May be 1D structures or mesh artifacts

---

## Automation Opportunities

### 1. Batch TIF Export

**RASMapper Approach:** User manually selects map types, profiles, and clicks "Compute Stored Maps"

**Python Automation:**
```python
from ras_commander import RasMap

# Export all variables for all timesteps
variables = ["WSE", "Depth", "Velocity"]
for plan in ["01", "02", "03"]:
    outputs = RasMap.map_ras_results(
        plan_number=plan,
        variables=variables,
        terrain_path="Terrain.tif",
        output_dir=f"maps/plan_{plan}"
    )
```

**Benefits:**
- Batch process multiple plans/variables
- Scriptable, repeatable
- No GUI required

---

### 2. Custom Color Ramps

**RASMapper Approach:** Limited color scales in GUI

**Python Automation:**
```python
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

# Custom FEMA-style depth colormap
fema_colors = ['#00FF00', '#FFFF00', '#FFA500', '#FF0000', '#8B0000']
cmap = ListedColormap(fema_colors)

# Apply to raster
plt.imsave('depth_fema.tif', depth_array, cmap=cmap, vmin=0, vmax=10)
```

---

### 3. Difference Maps (Model Comparison)

**Use Case:** Compare baseline vs. alternative scenarios

**Python Automation:**
```python
baseline = rasterio.open('baseline_wse.tif').read(1)
proposed = rasterio.open('proposed_wse.tif').read(1)

diff = proposed - baseline

# Export difference raster
with rasterio.open('wse_difference.tif', 'w', ...) as dst:
    dst.write(diff, 1)
```

**Benefits:**
- RASMapper has no built-in difference map tool
- Python provides full control over raster math

---

### 4. Multi-Plan Animation

**Use Case:** Create GIF/MP4 of WSE evolution across multiple breach scenarios

**Python Automation:**
```python
import imageio

frames = []
for plan in breach_plans:
    wse = RasMap.map_ras_results(plan, ["WSE"], ...)
    frames.append(wse['WSE'])

imageio.mimsave('breach_animation.gif', frames, fps=2)
```

---

### 5. Calling RASMapper Directly (COM Automation)

**Potential:** RASMapper may expose COM interface for automation

**Investigation Needed:**
- Check if `RasMapperLib.dll` is COM-visible
- Look for type library (TLB) or COM registration
- Decompiled code shows `[ComVisible(false)]` on many classes → **Not exposed**

**Alternative:** Use Python `subprocess` to call RASMapper.exe with command-line args (if supported)

```python
import subprocess

subprocess.run([
    "RASMapper.exe",
    "-project", "MyProject.prj",
    "-export", "WSE",
    "-plan", "01",
    "-terrain", "Terrain.tif",
    "-output", "output.tif"
])
```

**Status:** Unknown if RASMapper supports CLI. Would need testing.

---

### 6. Custom Interpolation Methods

**Use Case:** Implement custom spatial interpolation (e.g., IDW, kriging)

**Python Automation:**
```python
from scipy.interpolate import griddata

# Extract cell center points and values
points = np.array([[cell.x, cell.y] for cell in cells])
values = max_wse['value'].values

# Interpolate to raster grid
grid_x, grid_y = np.meshgrid(raster_x, raster_y)
wse_idw = griddata(points, values, (grid_x, grid_y), method='cubic')
```

**Benefits:**
- Go beyond RASMapper's horizontal/sloped options
- Implement custom hazard mapping algorithms

---

### 7. Integration with GIS Workflows

**Use Case:** Automated damage assessment, population exposure analysis

**Python Automation:**
```python
import geopandas as gpd

# Load building footprints
buildings = gpd.read_file('buildings.shp')

# Sample depth raster at building locations
from rasterstats import point_query
depths = point_query(buildings.geometry, 'depth.tif')

# Filter flooded buildings
flooded = buildings[depths > 0.5]

# Export for damage assessment
flooded.to_file('flooded_buildings.shp')
```

**Benefits:**
- RASMapper has limited GIS integration
- Python enables full spatial analysis workflows

---

## Summary

The `RasMapperLib.Mapping` namespace provides a comprehensive framework for converting HEC-RAS results into map products. Key takeaways:

1. **Map Types:** 43+ predefined types covering standard hydraulic variables
2. **Interpolation:** Two methods (horizontal, sloped) with barycentric weighting
3. **Output Modes:** Dynamic (on-the-fly) vs. Stored (pre-computed TIFs)
4. **Data Structures:** Cell/vertex mapping with weights for interpolation
5. **Geometry Model:** Complete object model for 1D/2D/Pipe networks

**Python Implementation Status:**
- ✅ Horizontal interpolation validated
- ✅ Sloped interpolation implemented and validated (Ben's Weights)
- ✅ Face WSE and vertex WSE computation complete
- ⚠️ Known gaps at boundaries and shallow cells

**Automation Opportunities:**
- Batch TIF export
- Custom color ramps
- Difference maps
- Multi-plan animations
- GIS workflow integration
- Custom interpolation algorithms

**Next Steps:**
1. Resolve 29% coverage gap (boundary vertex handling)
2. Investigate 1D-2D connection outliers
3. Implement velocity interpolation with flow weighting
4. Add support for arrival time, duration metrics
5. Explore COM automation or CLI interface for RASMapper.exe

---

## References

- **Decompiled Source:** `RasMapperLib.dll` → `RasMapperLib.Mapping` namespace
- **Ben's Weights Algorithm:** `RASGeometryMapPoints.BensWeights()` (see namespace 01)
- **HDF Structure:** See `01_rasmapper_geometry_structure.md`
- **Python Implementation:** `ras_commander/mapping/` module
- **Validation Report:** `findings/sloped_cell_corners.md`
