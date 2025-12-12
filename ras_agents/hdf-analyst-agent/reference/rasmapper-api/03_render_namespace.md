# RasMapperLib.Render Namespace Documentation

**Purpose**: The `RasMapperLib.Render` namespace provides classes for rendering HEC-RAS results (water surface, velocity, depth, etc.) from computational mesh/geometry data onto raster grids for visualization.

**Location**: `RasMapperLib.Render/`

**Last Updated**: 2025-12-09

---

## Overview

The Render namespace handles the critical task of transforming HEC-RAS computation results into visual raster products. It bridges the gap between:
- **Input**: Mesh-based HDF5 results (cell/face/vertex data)
- **Output**: Georeferenced raster grids (GeoTIFF)

The namespace implements multiple interpolation methods (horizontal, sloped) and handles 1D cross-sections, 2D mesh areas, storage areas, and pipe networks.

---

## Class Hierarchy

### Base Class

```
Renderer (abstract base)
├─ WaterSurfaceRenderer
│  ├─ WaterSurfaceRenderer2DBridge
│  ├─ WaterSurfaceAddWSERenderer
│  └─ WaterSurfaceExtentRenderer
├─ DepthRenderer
├─ DepthExtentRenderer
├─ VelocityRenderer
│  └─ VelocityRenderer2DBridge
├─ DepthAndVelocityRenderer
│  ├─ DVRenderer (Depth × Velocity)
│  └─ DVSqRenderer (Depth × Velocity²)
├─ FlowRenderer
├─ VolumeRenderer
├─ ShearRenderer
├─ StreamPowerRenderer
├─ FractionInundatedRenderer
├─ HydraulicDepthRenderer
├─ CourantRenderer
├─ ArrivalTimeRenderer
├─ AuxillaryRenderer (generic variables)
├─ MCRenderer (Manning's Calibration)
├─ LaplaceRenderer
├─ MeshCellSizeRenderer
├─ WaterSurfaceRendererPipe
├─ VelocityRendererPipe
└─ CourantRendererPipe
```

**Design Pattern**: All renderers inherit from `Renderer` base class and use static `Compute()` methods for execution.

---

## Key Classes

### 1. Renderer (Base Class)

**Purpose**: Abstract base class providing common functionality for all renderers.

**Key Properties**:
```csharp
protected RASResults _result
protected RASGeometry _geometry
protected CacheCollection _cache
protected RASD2FlowArea _d2FlowArea
protected RASXSections _XS
protected RASXSIS _XSIS
protected string _hdfFilename
protected List<string> _d2FlowAreaNames
```

**Key Methods**:

```csharp
// Read HDF data for mapped mesh cells
protected float[][] ReadMappedMeshProfile(
    List<string> datasets,  // HDF dataset paths per mesh
    int profile,            // Profile/timestep index
    H5RowCache<float> cache,
    RASGeometryMapPoints mps
)

// Compute cell values using flat (horizontal) interpolation
protected void ComputeCellValuesFlat(
    FlatMeshMap flatArea,
    float[] cellInputValues,
    float[] output,
    float[] clipPixelDepths = null,
    float[] cellWaterSurfaces = null
)

// Compute from cell values with simple hydraulic connectivity
protected void ComputeFromCellValues_SimpleHydraulicConnectivity(
    SlopingMeshMap slopedArea,
    float[] cellInputValues,
    float[] cellWaterSurfaces,
    float[] output,
    float[] clipPixelDepths = null
)

// Compute from face point values (sloped rendering)
protected void ComputeFromFacepointValuesPixelParallelCellLocal(
    SlopingMeshMap slopedArea,
    float[][] facepointValues,  // Per-facepoint WSE/variable
    float[] output,
    float[] clipPixelDepths = null,
    float[] cellWaterSurfaces = null
)

// Get dataset names for water surface data
protected Names GetWaterSurfaceDatasetNames()

// Get dataset names for flow/velocity data
protected void GetFlowDatasetNames(
    ref Names flowNames,
    ref Names wsNames
)
```

**Responsibilities**:
- HDF5 data reading and caching
- Geometry mapping (mesh → raster pixels)
- Interpolation algorithms (flat, sloped)
- Hydraulic connectivity handling
- Progress reporting

---

### 2. WaterSurfaceRenderer

**Purpose**: Renders water surface elevation (WSE) for 1D, 2D, and storage areas.

**Key Methods**:

```csharp
public static void Compute(
    RASResults res,
    int profile,
    RASGeometryMapPoints mps,
    float[] terrain,
    ref float[] waterSurfaces,
    ref float[] outputTimes = null,
    CacheCollection cache = null,
    double wsDepthThreshold = 0.0
)

// Get function that computes WSE for any map points/terrain
public Func<RASGeometryMapPoints, float[], float[]> GetComputer(
    int profile,
    bool AllowNegativeValues,
    Func<float[]> GetReusableBuffer,
    Action<float[]> ReturnReusableBuffer
)

// Compute 1D cross-section water surfaces
public void ComputeWaterSurface1D(
    int profile,
    ref float[] outWSEL
)

// Compute storage area water surfaces
public void ComputeWaterSurfaceSA(
    int profile,
    ref float[] outWSEL
)
```

**Rendering Logic**:
1. Read WSE from HDF for 1D, 2D, SA
2. For 2D areas:
   - **Horizontal mode**: Use cell center WSE directly
   - **Sloped mode**: Compute face WSE → vertex WSE → interpolate to pixels
3. Apply depth threshold (default 0.001 ft)
4. Clip WSE < terrain + threshold to NODATA

**Special Handling**:
- `MinWSPlotTolerance = 0.001 ft` - threshold for shallow water
- `AllowNegativeValues` flag for backwater/surge scenarios

---

### 3. SlopingFactors

**Purpose**: Compute hydraulic connectivity and face/vertex values for sloped rendering.

**Key Methods**:

```csharp
// Compute face water surface factors
public static FaceValues[] ComputeSlopingWSFaceFactors(
    RASD2FlowArea d2FlowArea,
    float[] cellWaterSurface,
    MeshMap meshMap
)

// Compute facepoint water surface values
public static void ComputeSlopingWSFPValues(
    RASD2FlowArea d2FlowArea,
    MeshMap meshMap,
    float[] cellWaterSurface,
    ref FaceValues[] faceWS,
    ref float[][] facePointValues
)

// Compute facepoint values with hydraulic connectivity
public static void ComputeFacepointValues_SimpleHydraulicConnectivity(
    RASD2FlowArea d2FlowArea,
    SlopingMeshMap area,
    float[] cellWaterSurface,
    float[] cellVariable,
    ref float[][] facePointValues
)

// Compute facepoint values without hydraulic connectivity
public static void ComputeFacepointValues_NoHydraulicConnectivity(
    RASD2FlowArea d2FlowArea,
    SlopingMeshMap area,
    float[] cellVariable,
    ref float[] facePointValues
)
```

**FaceValues Structure**:
```csharp
struct FaceValues
{
    float ValueA;  // Value on cellA side of face
    float ValueB;  // Value on cellB side of face
    HydraulicConnection HydraulicConnection;
    bool IsHydraulicallyConnected { get; }
}
```

**Hydraulic Connectivity Types**:
- `None` - Cells not connected (levee/weir between)
- `Backfill` - Fill shallow cell to match deep neighbor
- `DownhillShallow` - Connected, shallow water
- `DownhillDeep` - Connected, deep water
- `LeveeTop` - Levee overtopping
- `LeveeShallow` - Levee with shallow water
- `LeveeDeep` - Levee with deep water

---

### 4. DepthRenderer

**Purpose**: Computes depth = WSE - terrain.

**Key Methods**:

```csharp
public static void Compute(
    RASResults res,
    int profile,
    RASGeometryMapPoints mps,
    float[] terrain,
    ref float[] depths,
    CacheCollection cache = null,
    bool allowNegativeDepths = false,
    double wsDepthThreshold = 0.0
)

public Func<RASGeometryMapPoints, float[], float[]> GetComputer(
    int profile,
    Func<float[]> GetReusableBuffer,
    Action<float[]> ReturnReusableBuffer,
    bool AllowNegativeDepths = false
)
```

**Implementation**:
```csharp
// Pseudo-code
WaterSurface = WaterSurfaceRenderer.Compute(...)
Depth[i] = WaterSurface[i] - terrain[i]

if (!AllowNegativeDepths && Depth[i] < 0)
    Depth[i] = NODATA
```

---

### 5. VelocityRenderer

**Purpose**: Renders velocity magnitude and direction (X/Y components).

**Key Methods**:

```csharp
public static void Compute(
    RASResults res,
    int profile,
    RASGeometryMapPoints mps,
    float[] terrain,
    ref float[] velocities,
    ref float[] vx,
    ref float[] vy,
    CacheCollection cache = null
)

// Returns: [vx, vy, magnitude, depths, null]
public Func<RASGeometryMapPoints, float[], float[][]> GetComputer(
    int profile,
    Func<float[]> GetReusableBuffer,
    Action<float[]> ReturnReusableBuffer
)
```

**2D Velocity Handling**:
- Reads face velocities from HDF
- Converts face-normal velocities to X/Y components
- For sloped rendering: interpolates facepoint velocities
- For horizontal rendering: uses cell-average velocity

**1D Velocity Computation**:
```csharp
// From cross-section subsection velocities
ComputeVelocityInternal1DFromVelocity(...)

// From flow and water surface
ComputeVelocityInternal1DFromFlow(...)
```

---

### 6. VolumeRenderer

**Purpose**: Computes water volume per pixel using volume-elevation curves.

**Key Methods**:

```csharp
public static void Compute(
    RASResults res,
    int profile,
    RASGeometryMapPoints mps,
    float[] terrain,
    ref float[] volumes,
    CacheCollection cache = null,
    double wsDepthThreshold = 0.0
)
```

**Implementation**:
1. Get WSE for each pixel
2. For 2D cells: Query cell volume-elevation table
3. For 1D XS: Compute flow area × channel length
4. For storage areas: Query SA volume-elevation curve

---

### 7. AuxillaryRenderer

**Purpose**: Renders generic variables from HDF (sediment, bed change, etc.).

**Key Methods**:

```csharp
public static void Compute(
    RASResultsMap map,
    Generic2DMapType genericMapType,
    int profile,
    RASGeometryMapPoints mps,
    float[] terrain,
    ref float[] values,
    ref float[] vx,
    ref float[] vy,
    CacheCollection cache = null
)
```

**Generic2DMapType** locations:
- `Location.Cell` - Cell-center values
- `Location.Face` - Face values (scalar or normal)
- `Location.SubCell` - Subcell/subgrid values
- `Location.SubFace` - Subface values

**Use Cases**:
- Sediment transport variables
- Bed change elevation
- Water quality parameters
- Custom output variables

---

### 8. Names Class

**Purpose**: Manages HDF dataset path names for different hydraulic elements.

**Properties**:
```csharp
public string Max1D          // 1D max dataset
public string Min1D          // 1D min dataset
public string Profile1D      // 1D time-series dataset
public List<string> Max2D    // 2D max datasets (per mesh)
public List<string> Profile2D // 2D time-series datasets
public string MaxSA          // Storage area max
public List<string> MaxPipeNetwork
```

**Methods**:
```csharp
public void Get1D(int pfIndex, ref string dataset, ref int row)
public void Get2D(int pfIndex, ref List<string> datasets, ref int row)
public void GetSA(int pfIndex, ref string dataset, ref int row)
public void Validate(string filename)  // Check datasets exist
```

---

## Render Modes

### 1. Horizontal (Flat) Rendering

**Configuration**: `SharedData.CellRenderMode = CellRenderMethod.Horizontal`

**Algorithm**:
1. Read cell-center values from HDF
2. For each pixel:
   - Find containing cell
   - Assign cell value directly (no interpolation)

**Use Cases**:
- Quick preview
- Cell-average properties
- Non-surface variables

**Advantages**: Fast, simple
**Disadvantages**: Blocky appearance, no slope

---

### 2. Sloped (Cell Corners) Rendering

**Configuration**: `SharedData.CellRenderMode = CellRenderMethod.Sloping`

**Algorithm**:
1. **Stage 1 - Compute Face WSE**:
   ```csharp
   faceWS = SlopingFactors.ComputeSlopingWSFaceFactors(...)
   ```
   - For each face: determine hydraulic connectivity
   - Compute WSE on both sides of face

2. **Stage 2 - Compute Vertex WSE**:
   ```csharp
   SlopingFactors.ComputeSlopingWSFPValues(...)
   ```
   - For each facepoint (vertex): compute planar regression
   - Use adjacent face WSE values
   - Stored in `facePointValues[][]`

3. **Stage 3 - Rasterize**:
   ```csharp
   ComputeFromFacepointValuesPixelParallelCellLocal(...)
   ```
   - For each pixel: find containing cell
   - Use Ben's Weights (barycentric coordinates)
   - Interpolate from vertex WSE values

**Use Cases**:
- Production-quality maps
- Water surface elevation
- Terrain-following variables

**Advantages**: Smooth, realistic slopes
**Disadvantages**: Slower, more complex

---

### 3. Depth-Weighted Faces Option

**Configuration**: `.rasmap` setting `<UseDepthWeightedFaces>true</UseDepthWeightedFaces>`

**Purpose**: Weight facepoint values by water depth to reduce artifacts.

**Implementation**: Applied during facepoint WSE computation.

---

### 4. Reduce Shallow to Horizontal

**Configuration**: `.rasmap` setting `<ReduceShallowToHorizontal>true</ReduceShallowToHorizontal>`

**Purpose**: Use horizontal rendering for shallow cells to avoid numerical issues.

**Threshold**: Typically `MinWSPlotTolerance = 0.001 ft`

---

## Color Ramps and Styling

### Color Ramp Application

**Location**: Handled by RASMapper GUI, not in Render namespace.

**Process**:
1. Renderer produces float[] raster values
2. GUI applies color ramp from `.rasmap` file
3. Result: RGB/RGBA image

**Example** `.rasmap` color ramp (WSE):
```xml
<ColorRamp>
  <RampMinValue>100.0</RampMinValue>
  <RampMaxValue>120.0</RampMaxValue>
  <Color1>0,0,255</Color1>      <!-- Blue (low) -->
  <Color2>0,255,0</Color2>      <!-- Green (mid) -->
  <Color3>255,0,0</Color3>      <!-- Red (high) -->
</ColorRamp>
```

**Transparency**: NODATA pixels rendered transparent.

---

## Python Implementation Notes

### Horizontal Interpolation (COMPLETED)

**Python equivalent**:
```python
from ras_commander import RasMap

outputs = RasMap.map_ras_results(
    plan_number="03",
    variables=["WSE", "Depth", "Velocity"],
    terrain_path="Terrain/Terrain.tif",
    interpolation_method="horizontal"
)
```

**Implementation**: `ras_commander/mapping/interpolation.py`

**Algorithm**:
1. Load mesh cell polygons
2. Create spatial index (R-tree)
3. For each pixel:
   - Query containing cell
   - Assign cell value

---

### Sloped Interpolation (IN PROGRESS)

**Target Python API**:
```python
outputs = RasMap.map_ras_results(
    plan_number="03",
    variables=["WSE"],
    terrain_path="Terrain/Terrain.tif",
    interpolation_method="sloped"  # Uses Ben's Weights
)
```

**Discovered Algorithm**: Ben's Weights (2025-12-09)
- Generalized barycentric coordinates for arbitrary polygons
- Located: `RASGeometryMapPoints.BensWeights()` in decompiled source

**Python Implementation**:
```python
def compute_bens_weights(pixel_xy, vertex_coords):
    """
    Compute generalized barycentric weights.

    Args:
        pixel_xy: (x, y) pixel center
        vertex_coords: [(x1,y1), (x2,y2), ...] cell vertices

    Returns:
        weights: [w1, w2, ...] normalized weights
    """
    # Cross-product weighting from pixel to face endpoints
    weights = []
    n = len(vertex_coords)
    for i in range(n):
        j = (i + 1) % n
        v1 = vertex_coords[i]
        v2 = vertex_coords[j]
        cross = cross_product_2d(
            (v1[0] - pixel_xy[0], v1[1] - pixel_xy[1]),
            (v2[0] - pixel_xy[0], v2[1] - pixel_xy[1])
        )
        weights.append(cross)

    # Normalize
    total = sum(weights)
    return [w / total for w in weights]

def interpolate_pixel_wse(pixel_xy, cell_polygon, vertex_wse):
    """
    Interpolate WSE at pixel using Ben's Weights.

    Args:
        pixel_xy: (x, y)
        cell_polygon: Shapely polygon
        vertex_wse: [wse1, wse2, ...] at vertices

    Returns:
        wse: Interpolated value
    """
    coords = list(cell_polygon.exterior.coords)[:-1]  # Remove duplicate
    weights = compute_bens_weights(pixel_xy, coords)
    return sum(w * wse for w, wse in zip(weights, vertex_wse))
```

**Validation Results** (Plan 15 - 1D-2D Refined Grid):
- Median |diff| = 0.0001 ft
- MAE = 0.0106 ft
- 90th percentile = 0.0097 ft

**See**: `findings/sloped_cell_corners.md` for full details

---

### Key Differences: .NET vs Python

| Aspect | .NET (RASMapper) | Python (ras-commander) |
|--------|------------------|------------------------|
| HDF Reading | H5Assist (custom) | h5py |
| Parallelization | `Parallel.SmartFor` | NumPy vectorization |
| Spatial Index | Built-in | Shapely + R-tree |
| Caching | `H5RowCache<float>` | Manual dict caching |
| Progress | `ProgressReporter` | tqdm |

---

## Automation Opportunities

### 1. Batch Raster Generation

**Use Case**: Generate rasters for all timesteps.

**Python Approach**:
```python
for profile in range(res.ProfileCount):
    outputs = RasMap.map_ras_results(
        plan_number="03",
        variables=["WSE", "Depth"],
        terrain_path=terrain,
        profile_index=profile,
        output_dir=f"results/timestep_{profile:04d}"
    )
```

**Direct RASMapper Call** (via COM):
```python
import win32com.client

ras = win32com.client.Dispatch("RAS65.HECRASController")
ras.Project_Open(project_file)
ras.Compute_CurrentPlan()

# Export via RASMapper (GUI automation - complex)
# Better: Use Python implementation above
```

---

### 2. Multi-Variable Maps

**Use Case**: WSE, Velocity, Depth in one pass.

**Python**:
```python
outputs = RasMap.map_ras_results(
    plan_number="03",
    variables=["WSE", "Velocity", "Depth"],
    terrain_path=terrain
)

wse_tif = outputs["WSE"]["path"]
vel_tif = outputs["Velocity"]["path"]
depth_tif = outputs["Depth"]["path"]
```

---

### 3. Custom Color Ramps

**Python with rasterio**:
```python
import rasterio
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

# Read float raster
with rasterio.open(wse_tif) as src:
    wse = src.read(1)

# Apply color ramp
cmap = LinearSegmentedColormap.from_list(
    "wse", ["blue", "green", "red"]
)
rgb = cmap((wse - wse.min()) / (wse.max() - wse.min()))

# Write RGB GeoTIFF
with rasterio.open(
    "wse_colored.tif", "w",
    driver="GTiff", count=3, dtype=np.uint8,
    width=wse.shape[1], height=wse.shape[0],
    transform=src.transform, crs=src.crs
) as dst:
    dst.write((rgb[:,:,:3] * 255).astype(np.uint8).transpose(2,0,1))
```

---

### 4. Difference Maps (Plan Comparison)

**Use Case**: Compare alternative scenarios.

**Python**:
```python
# Baseline
base = RasMap.map_ras_results(plan_number="01", variables=["WSE"])
base_wse = rasterio.open(base["WSE"]["path"]).read(1)

# Alternative
alt = RasMap.map_ras_results(plan_number="02", variables=["WSE"])
alt_wse = rasterio.open(alt["WSE"]["path"]).read(1)

# Difference
diff = alt_wse - base_wse
```

---

### 5. Time-Series Animation

**Use Case**: Create MP4 video of flooding.

**Python with ffmpeg**:
```python
import subprocess

for i in range(res.ProfileCount):
    outputs = RasMap.map_ras_results(
        plan_number="03", variables=["WSE"],
        profile_index=i,
        output_dir=f"frames/frame_{i:04d}.tif"
    )

# Create video
subprocess.run([
    "ffmpeg", "-framerate", "10",
    "-pattern_type", "glob", "-i", "frames/*.tif",
    "-c:v", "libx264", "flood_animation.mp4"
])
```

---

## Implementation Status (ras-commander)

| Feature | Status | Notes |
|---------|--------|-------|
| Horizontal WSE | ✅ Complete | Validated against RASMapper |
| Horizontal Depth | ✅ Complete | WSE - terrain |
| Horizontal Velocity | ✅ Complete | Face velocity interpolation |
| Sloped WSE (Ben's Weights) | ✅ Complete | 2025-12-09 validation |
| Sloped Depth | ✅ Complete | Uses sloped WSE |
| Sloped Velocity | ⚠️ Partial | 2D only, 1D needs work |
| Hydraulic Connectivity | ✅ Complete | Levee/weir handling |
| Depth-Weighted Faces | ❌ Not Implemented | Low priority |
| SubCell/SubFace | ❌ Not Implemented | Sediment transport |
| Color Ramps | ❌ Not Implemented | Use matplotlib/QGIS |
| Batch Processing | ✅ Complete | Loop over profiles |
| Multi-Variable | ✅ Complete | Single function call |

---

## Related Documentation

- `01_mesh_namespace.md` - Mesh topology (FacePoint, Face, Cell)
- `02_mapping_namespace.md` - Geometry mapping (RASGeometryMapPoints)
- `findings/horizontal_2d.md` - Horizontal rendering validation
- `findings/sloped_cell_corners.md` - Sloped rendering (Ben's Weights)

---

## References

**Source Files**:
- `RasMapperLib.Render/Renderer.cs` - Base renderer (4,100 lines)
- `RasMapperLib.Render/WaterSurfaceRenderer.cs` - WSE rendering (5,700 lines)
- `RasMapperLib.Render/VelocityRenderer.cs` - Velocity rendering (7,100 lines)
- `RasMapperLib.Render/SlopingFactors.cs` - Hydraulic connectivity (710 lines)

**Python Implementation**:
- `ras_commander/mapping/interpolation.py` - Horizontal/sloped algorithms
- `ras_commander/RasMap.py` - High-level API

**Validation**:
- `Test Data/BaldEagleCrkMulti2D - Horizontal/` - Ground truth (horizontal)
- `Test Data/BaldEagleCrkMulti2D - Sloped - Cell Corners/` - Ground truth (sloped)
