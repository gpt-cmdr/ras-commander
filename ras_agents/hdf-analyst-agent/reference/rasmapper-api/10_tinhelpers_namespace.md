# RASMapper TIN Helpers Namespace Documentation

**Document Version:** 1.0
**Date:** 2025-12-09
**Namespace:** `RasMapperLib.TinHelpers`
**Purpose:** Triangulated Irregular Network (TIN) construction and interpolation support

---

## 1. Namespace Overview

The `RasMapperLib.TinHelpers` namespace provides low-level data structures for building and managing Triangulated Irregular Networks (TINs). These structures support Delaunay triangulation, spatial indexing, and barycentric interpolation for terrain and hydraulic results.

**Key Capabilities:**
- Triangle topology management (vertices, adjacency)
- Edge classification (breaklines, perimeter boundaries)
- Circumcircle computation for Delaunay triangulation
- Triangle insertion/deletion tracking
- Binary serialization for performance

**Primary Use Cases:**
- Terrain surface interpolation
- HEC-RAS result surface construction (WSE, velocity, depth)
- Cross-section profile generation
- Spatial queries and point-in-triangle tests

---

## 2. Class Hierarchy

```
RasMapperLib.TinHelpers
│
├── TriangleStruct (struct)           - Main triangle data structure
├── DevelopmentTriangle (class)       - Triangle with construction metadata
├── EdgeStruct (struct)               - Edge definition (2 points)
├── InsertionHoleEdge (struct)        - Edge during triangle insertion
├── InsertionHolePointTriangles (struct) - Point's adjacent triangles
└── TriangleFlags (enum)              - Triangle edge type flags

Supporting Classes (in RasMapperLib):
├── Tin (class)                       - TIN container and operations
├── TriangleShape (struct)            - Triangle geometry and interpolation
├── PointM (struct)                   - Point with X, Y, Z, M attributes
├── PlaneM (struct)                   - Plane equation coefficients
└── CircleM (struct)                  - Circle (circumcircle)
```

---

## 3. Core Data Structures

### 3.1 TriangleStruct

**Purpose:** Lightweight triangle representation with adjacency information.

**Key Properties:**
```csharp
public int p0, p1, p2;           // Vertex indices (counterclockwise)
public int at0, at1, at2;        // Adjacent triangle indices
public byte EdgeType;            // Edge classification flags
```

**Edge Indexing Convention:**
- Edge 0: p0 → p1 (adjacent triangle at0)
- Edge 1: p1 → p2 (adjacent triangle at1)
- Edge 2: p2 → p0 (adjacent triangle at2)

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `AssignPoints` | `(int pt0, int pt1, int pt2)` | Initialize triangle vertices |
| `GetEdge` | `(int pt0, int pt1) → int` | Find edge index from two points |
| `EdgePoint0/1` | `(int e012) → int` | Get edge endpoints |
| `ThirdPoint` | `(int p0, int p1) → int` | Get vertex opposite to edge |
| `PlaneCoefficients` | `(Tin TIN) → PlaneM` | Compute plane equation A·x + B·y + C·z + D = 0 |
| `IsEdge0/1/2Breakline` | `() → bool` | Check if edge is a breakline |
| `IsEdge0/1/2Perimeter` | `() → bool` | Check if edge is on perimeter |

**Binary Serialization:**
```csharp
static void Stream(BinaryWriter bw, IList<TriangleStruct> tris)
static TriangleStruct[] Stream(BinaryReader br)
```
- Serializes 7 integers per triangle: p0, p1, p2, at0, at1, at2, EdgeType
- Used for caching TIN structures to disk

---

### 3.2 DevelopmentTriangle

**Purpose:** Triangle used during incremental TIN construction (with deletion tracking).

**Key Properties:**
```csharp
public int p0, p1, p2;           // Vertex indices
public int at0, at1, at2;        // Adjacent triangles
private byte Flags;              // State flags (deleted, edge types)
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `ChangeAT` | `(int sourceVal, int destVal)` | Update adjacent triangle reference |
| `MarkDeleted` | `()` | Flag triangle as deleted (bit 6) |
| `IsDeleted` | `() → bool` | Check if triangle is deleted |
| `SetEdge` | `(int e012, bool isPerimeter)` | Mark edge as breakline or perimeter |
| `GetCWTriangle` | `(int aroundPointIdx, ref bool isEdgeBLorPerim) → int` | Clockwise adjacent triangle |
| `GetCCWTriangle` | `(int aroundPointIdx, ref bool isEdgeBLorPerim) → int` | Counter-clockwise adjacent |
| `CircumCircleCompute` | `(List<PointM> pts) → CircleM` | Compute circumcircle |

**Deletion Pattern:**
- Triangles are marked deleted but not removed from array
- Enables undo operations during construction
- Final TIN filters out deleted triangles

---

### 3.3 EdgeStruct

**Purpose:** Minimal edge representation (two point indices).

```csharp
public struct EdgeStruct
{
    public int p0;
    public int p1;

    public void AssignPts(int pt0, int pt1)
}
```

**Usage:** Edge list construction in `Tin.ComputeEdgesAndAdjacentTriangles()`

---

### 3.4 InsertionHoleEdge

**Purpose:** Edge on the boundary of a "hole" created during point insertion.

```csharp
public struct InsertionHoleEdge
{
    public int p0, p1;              // Edge endpoints
    public int outsideTriangle;     // Triangle outside the hole
    public int insideTriangle;      // Triangle inside the hole (to delete)
}
```

**Usage:** Delaunay triangulation maintains the convex hull of deleted triangles during point insertion.

---

### 3.5 InsertionHolePointTriangles

**Purpose:** Track left/right triangles adjacent to a point during insertion.

```csharp
public struct InsertionHolePointTriangles
{
    public int triangleLeft;
    public int triangleRight;
}
```

---

### 3.6 TriangleFlags (Enum)

**Purpose:** Bit flags for triangle edge classification.

```csharp
public enum TriangleFlags : byte
{
    E0Break = 1,         // Edge 0 is a breakline
    E1Break = 2,         // Edge 1 is a breakline
    E2Break = 4,         // Edge 2 is a breakline
    E0Perim = 8,         // Edge 0 is on perimeter
    E1Perim = 16,        // Edge 1 is on perimeter
    E2Perim = 32,        // Edge 2 is on perimeter
    Deleted = 64,        // Triangle is deleted
    AnyPerimOrBreak = 63 // Mask for any edge type
}
```

**Usage:**
- Breaklines enforce hard edges (no smoothing across)
- Perimeter edges define TIN boundary
- Flags stored in single byte for efficiency

---

## 4. Supporting Geometry Classes

### 4.1 TriangleShape

**Purpose:** Triangle geometry operations (interpolation, containment).

**Key Properties:**
```csharp
public PointM pt0, pt1, pt2;   // Triangle vertices
public double tolerance;       // Numerical tolerance (default 1e-6)
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `Contains` | `(double ptx, pty, ref λ0, λ1, λ2) → bool` | Point-in-triangle test |
| `InterpolationWeights` | `(double px, py, ref λ0, λ1, λ2)` | Barycentric coordinates |
| `ComputeZ` | `(double ptx, pty, ref double z) → bool` | Interpolate Z elevation |
| `ComputeM` | `(double ptx, pty, ref double m) → bool` | Interpolate M value |
| `ComputeZM` | `(double ptx, pty, ref z, ref m) → bool` | Interpolate both Z and M |

**Barycentric Interpolation Formula:**
```csharp
// Compute weights λ0, λ1, λ2 such that λ0 + λ1 + λ2 = 1
InterpolationWeights(px, py, ref λ0, ref λ1, ref λ2);

// Interpolate any attribute
Z = pt0.Z * λ0 + pt1.Z * λ1 + pt2.Z * λ2;
M = pt0.M * λ0 + pt1.M * λ1 + pt2.M * λ2;
```

**Containment Test:** Point is inside if all weights λ0, λ1, λ2 ∈ [0, 1] (with tolerance).

---

### 4.2 PlaneM

**Purpose:** Plane equation coefficients for 3D interpolation.

**Structure:**
```csharp
public struct PlaneM
{
    public double A, B, C, D;  // Z plane: Ax + By + Cz + D = 0
    public double E, F, G, H;  // M plane: Ex + Fy + Gm + H = 0
}
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `SetCoeffientsPtPtPt` | `(PointM pt0, pt1, pt2)` | Compute from 3 points |
| `Z` | `(double x, y) → double` | Evaluate Z at (x, y) |
| `M` | `(double x, y) → double` | Evaluate M at (x, y) |
| `dZ_dX` | `() → double` | Z gradient in X direction |
| `dM_dX` | `() → double` | M gradient in X direction |

**Plane Computation (Cross Product):**
```csharp
// From triangle vertices pt0, pt1, pt2
delta01 = pt0.Delta(pt1);  // pt1 - pt0
delta02 = pt0.Delta(pt2);  // pt2 - pt0

// Normal vector = delta01 × delta02
A = delta01.Y * delta02.Z - delta01.Z * delta02.Y;
B = delta01.Z * delta02.X - delta01.X * delta02.Z;
C = delta01.X * delta02.Y - delta01.Y * delta02.X;
D = -A*pt0.X - B*pt0.Y - C*pt0.Z;
```

---

### 4.3 CircleM

**Purpose:** Circle (typically circumcircle) for Delaunay triangulation.

**Structure:**
```csharp
public struct CircleM
{
    public double X, Y;  // Center coordinates
    public double R;     // Radius
}
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `Compute` | `(PointM A, B, C)` | Circumcircle through 3 points |
| `ContainsPoint` | `(PointM point) → bool` | Test if point inside circle |
| `Center` | `() → PointM` | Get center as PointM |

**Delaunay Property:** No triangle's circumcircle contains any other point.

---

## 5. TIN Construction

### 5.1 Tin Class Overview

**Inherits:** `MultiPoint` (stores PointM array)

**Key Properties:**
```csharp
public TriangleStruct[] Triangles;  // Triangle array
private EdgeStruct[] _edge;         // Edge list
private SpatialIndex<int> _triangleSpatialIndex;  // Spatial index
```

### 5.2 Building a TIN

**Constructor:**
```csharp
public Tin(PointMs points, TriangleStruct[] triangles)
```

**Adjacency Computation:**
```csharp
public void ComputeEdgesAndAdjacentTriangles()
```

**Process:**
1. For each triangle, enumerate 3 edges
2. Build edge lookup table (point → adjacent points)
3. When edge found twice, link adjacent triangles
4. Perimeter edges have adjacent triangle index = -1

**Edge List Construction:**
- Unique edges stored in `_edge` array
- Used for rendering and boundary queries

---

### 5.3 Spatial Indexing

**Method:**
```csharp
public void EnsureTriangleSpatialIndex()
```

**Structure:**
- Grid-based bins over TIN extent
- Each bin stores list of triangle indices
- Accelerates point-in-triangle queries

**Usage Pattern:**
```csharp
tin.EnsureTriangleSpatialIndex();
List<int> candidates = tin.GetTriangleSpatialIndex().GetElementsAtPoints(pts);
foreach (int triIdx in candidates)
{
    if (tin.TriangleShape(triIdx).ComputeZ(pt, ref z))
        break;  // Found containing triangle
}
```

---

## 6. TIN Interpolation

### 6.1 Point Elevation Sampling

**Method:**
```csharp
public void ComputePointElevations(IPoints points, float[] z, float[] m = null)
```

**Algorithm:**
1. Build spatial index for input points
2. For each bin:
   - Get candidate triangles from TIN spatial index
   - For each point-triangle pair:
     - Check if point in triangle MBR (fast reject)
     - Call `TriangleShape.ComputeZM()` for interpolation
3. Store results in output arrays

**Performance Optimization:**
- Dual spatial indexing (points and triangles)
- MBR pre-filtering before barycentric test
- Parallel processing support

---

### 6.2 Profile Generation

**Method:**
```csharp
public void ComputeProfiles(IList<Polyline> polylines,
                           Profile[] profilesZ,
                           double tolerance = 0.0,
                           Profile[] profilesM = null,
                           ProgressReporter reporter = null)
```

**Algorithm:**
1. For each polyline segment:
   - Find intersecting triangles via spatial index
   - Compute Z/M at segment endpoints (if inside triangles)
   - Find segment-triangle edge intersections
   - Interpolate Z/M at intersection points
2. Build station-elevation profile
3. Filter redundant points (Douglas-Peucker tolerance)

**Applications:**
- Cross-section elevation profiles
- Hydraulic structure profiles
- Breakline enforcement

---

### 6.3 Rasterization

**Method:**
```csharp
public bool Rasterize(RasterM raster, float[] values)
```

**Algorithm:**
1. For each raster cell:
   - Get cell center (x, y)
   - Query spatial index for candidate triangles
   - Test containment and interpolate Z
   - Write to values array
2. Return true if any cells populated

**Use Case:** Generate elevation TIFs from terrain TINs.

---

## 7. Python Implementation Notes

### 7.1 scipy.spatial Equivalents

**Triangle Construction:**
```python
from scipy.spatial import Delaunay

# Build Delaunay triangulation
points = np.array([[x0, y0], [x1, y1], ...])
tri = Delaunay(points)

# tri.simplices = triangle vertex indices (Nx3 array)
# tri.neighbors = adjacent triangle indices (Nx3 array)
# Equivalent to TriangleStruct arrays
```

**Point Location:**
```python
# Find containing triangle
tri_idx = tri.find_simplex([x, y])

# Barycentric coordinates
vertices = points[tri.simplices[tri_idx]]
b = barycentric_coords([x, y], vertices)  # Custom function
```

**Interpolation:**
```python
from scipy.interpolate import LinearNDInterpolator

# Build interpolator (uses Delaunay internally)
interp = LinearNDInterpolator(points, z_values)
z_interp = interp(x_grid, y_grid)
```

### 7.2 Custom Barycentric Implementation

**RASMapper Algorithm (from TriangleShape):**
```python
def barycentric_coords(px, py, pt0, pt1, pt2):
    """Compute barycentric coordinates (λ0, λ1, λ2)."""
    # Triangle vertices: pt0=(x0,y0), pt1=(x1,y1), pt2=(x2,y2)

    # Precompute terms (RASMapper algorithm)
    dy12 = pt1[1] - pt2[1]  # y1 - y2
    dx02 = pt0[0] - pt2[0]  # x0 - x2
    dx21 = pt2[0] - pt1[0]  # x2 - x1
    dy02 = pt0[1] - pt2[1]  # y0 - y2

    denom = dy12 * dx02 + dx21 * dy02

    dx = px - pt2[0]
    dy = py - pt2[1]

    λ0 = (dy12 * dx + dx21 * dy) / denom
    λ1 = (dx02 * dy - dy02 * dx) / denom
    λ2 = 1.0 - λ0 - λ1

    return λ0, λ1, λ2

def interpolate_z(px, py, tri_vertices, z_values):
    """Interpolate Z using barycentric coordinates."""
    λ0, λ1, λ2 = barycentric_coords(px, py, *tri_vertices)

    # Check containment (with tolerance)
    tol = 1e-6
    if all(-tol <= w <= 1.0 + tol for w in [λ0, λ1, λ2]):
        z = z_values[0] * λ0 + z_values[1] * λ1 + z_values[2] * λ2
        return z, True
    return None, False
```

### 7.3 Plane Equation Method

**Alternative to Barycentric (used in RASMapper for planar regression):**
```python
def fit_plane(pt0, pt1, pt2):
    """Compute plane coefficients A, B, C, D."""
    # Vectors from pt0 to pt1 and pt2
    v1 = np.array(pt1) - np.array(pt0)
    v2 = np.array(pt2) - np.array(pt0)

    # Normal vector = v1 × v2
    normal = np.cross(v1, v2)
    A, B, C = normal

    # D from point on plane
    D = -A*pt0[0] - B*pt0[1] - C*pt0[2]

    return A, B, C, D

def evaluate_plane(x, y, A, B, C, D):
    """Evaluate Z at (x, y) on plane."""
    if C == 0:
        return None  # Vertical plane
    z = (-D - A*x - B*y) / C
    return z
```

---

## 8. Automation Opportunities

### 8.1 Terrain Processing

**Use Case:** Generate terrain TINs from LiDAR/survey points.

**RASMapper Workflow:**
1. Read terrain points (PointM array with Z)
2. Build Delaunay triangulation (DevelopmentTriangle + CircleM)
3. Mark breaklines (set EdgeType flags)
4. Enforce breaklines (swap edges if needed)
5. Compute adjacency (`ComputeEdgesAndAdjacentTriangles`)
6. Build spatial index (`EnsureTriangleSpatialIndex`)
7. Rasterize to TIF

**Python Automation:**
```python
from scipy.spatial import Delaunay
import rasterio

# Build TIN
points = load_terrain_points()  # (N, 2) array
z = load_elevations()           # (N,) array
tri = Delaunay(points)

# Rasterize
x_grid, y_grid = create_grid(bounds, resolution)
z_grid = interpolate_to_grid(tri, points, z, x_grid, y_grid)

# Write TIF
with rasterio.open('terrain.tif', 'w', **profile) as dst:
    dst.write(z_grid, 1)
```

---

### 8.2 HEC-RAS Results Interpolation

**Use Case:** Convert mesh cell-center results to raster TIFs.

**Challenge:** HEC-RAS mesh is not Delaunay (structured quad cells).

**RASMapper Approach:**
1. Build face-vertex topology from HDF
2. Split quads into triangles (diagonal chosen by HEC-RAS)
3. Assign Z/M values to vertices (planar regression from faces)
4. Build TIN from vertices
5. Interpolate to raster grid

**Python Implementation (ras-commander):**
```python
from ras_commander import HdfMesh, HdfResultsMesh
from ras_commander.mapping import rasterize_sloped_wse

# Load mesh and results
geom_hdf = "BaldEagle.g09.hdf"
plan_hdf = "BaldEagle.p03.hdf"

cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
max_ws = HdfResultsMesh.get_mesh_max_ws(plan_hdf)

# Rasterize using sloped method (TIN-based)
wse_raster = rasterize_sloped_wse(
    cell_polygons=cell_polygons,
    cell_results=max_ws,
    terrain_raster=terrain,
    output_path="wse_max.tif"
)
```

**Key Difference:** HEC-RAS uses custom vertex WSE computation (not simple Delaunay).

---

### 8.3 Calling RASMapper Directly

**Opportunity:** Automate RASMapper TIN operations via .NET interop.

**Challenges:**
1. RASMapper.exe is not a COM server (no scripting interface)
2. RasMapperLib.dll requires RASMapper GUI context
3. No documented public API

**Feasible Approach:**
- Load RasMapperLib.dll in Python via pythonnet
- Construct Tin object manually
- Call interpolation methods

**Example (hypothetical):**
```python
import clr
clr.AddReference("RasMapperLib")
from RasMapperLib import Tin, PointMs, TriangleStruct

# Build TIN
points = PointMs()
for x, y, z in terrain_points:
    points.Add(PointM(x, y, z))

triangles = build_triangles(...)  # Array of TriangleStruct
tin = Tin(points, triangles)
tin.ComputeEdgesAndAdjacentTriangles()

# Interpolate
z_array = Array.CreateInstance(float, len(query_points))
tin.ComputePointElevations(query_points, z_array)
```

**Limitations:**
- Requires Windows + .NET Framework 4.8
- RasMapperLib dependencies (ESRI ArcObjects?)
- Not portable to Linux/cloud

---

## 9. Summary

### Key Takeaways

1. **TinHelpers provides low-level triangle topology:**
   - TriangleStruct: vertex indices + adjacency
   - DevelopmentTriangle: construction-time metadata
   - EdgeStruct: minimal edge representation

2. **Interpolation via barycentric coordinates:**
   - TriangleShape.InterpolationWeights() computes λ0, λ1, λ2
   - Z/M interpolated as weighted sum

3. **Spatial indexing critical for performance:**
   - Dual indexing (points + triangles)
   - MBR filtering before point-in-triangle tests

4. **Python equivalents exist:**
   - scipy.spatial.Delaunay for triangulation
   - Custom barycentric implementation needed
   - LinearNDInterpolator for simple cases

5. **RASMapper automation limited:**
   - No public API
   - pythonnet possible but not portable
   - Reverse-engineering algorithms for ras-commander better approach

### Recommended Implementation Strategy

**For ras-commander sloped interpolation:**
1. Extract mesh geometry from HDF (already working)
2. Compute vertex WSE using face regression (already working)
3. Build scipy Delaunay triangulation
4. Implement custom barycentric interpolation (match RASMapper algorithm)
5. Rasterize using Ben's Weights or barycentric (already validated)

**Status:** ✅ Implemented in v0.85.0+ using Ben's Weights algorithm.

---

## 10. References

**Decompiled Source Files:**
- `RasMapperLib.TinHelpers/TriangleStruct.cs`
- `RasMapperLib.TinHelpers/DevelopmentTriangle.cs`
- `RasMapperLib/Tin.cs`
- `RasMapperLib/TriangleShape.cs`
- `RasMapperLib/PlaneM.cs`
- `RasMapperLib/CircleM.cs`

**Related Documentation:**
- `01_rasmapper_architecture.md` - Overall RASMapper structure
- `03_mesh_interpolation.md` - Sloped interpolation algorithms
- `05_facepoint_vertex_topology.md` - Mesh topology details

**Python Libraries:**
- scipy.spatial.Delaunay - Delaunay triangulation
- scipy.interpolate.LinearNDInterpolator - TIN interpolation
- shapely.geometry.Polygon - Point-in-polygon tests

---

**End of Document**
