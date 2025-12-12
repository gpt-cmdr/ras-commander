# RASMapper Sloped Interpolation - Complete Algorithm Reference

**Source**: Decompiled `RasMapperLib.dll` from HEC-RAS 6.6
**Date**: 2025-12-09
**Purpose**: Permanent reference for recreating RASMapper's water surface rasterization

---

## Table of Contents

1. [Algorithm Overview](#algorithm-overview)
2. [Data Structures](#data-structures)
3. [Stage 1: Face WSE Computation](#stage-1-face-wse-computation)
4. [Stage 2: Vertex WSE Computation](#stage-2-vertex-wse-computation)
5. [Stage 3: Cell Triangulation and Rasterization](#stage-3-cell-triangulation-and-rasterization)
6. [Configuration Options](#configuration-options)
7. [Complete Code References](#complete-code-references)

---

## Algorithm Overview

RASMapper's "Sloped (Cell Corners)" mode computes water surface elevations through three stages:

```
┌─────────────────────────────────────────────────────────────────┐
│                    CELL WSE VALUES (from HDF)                   │
│                    [One value per mesh cell]                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              STAGE 1: FACE WSE COMPUTATION                      │
│                                                                 │
│  For each face between two cells:                               │
│  - Check hydraulic connectivity                                 │
│  - Apply terrain slope corrections                              │
│  - Determine connection type (Backfill, Deep, Shallow, etc.)    │
│  - Output: FaceValues (ValueA, ValueB, ConnectionType)          │
│                                                                 │
│  Method: MeshFV2D.ComputeFaceWSsNew()                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              STAGE 2: VERTEX WSE COMPUTATION                    │
│                                                                 │
│  For each vertex (facepoint):                                   │
│  - Collect WSE values from adjacent faces                       │
│  - Get face application points (midside or centroid)            │
│  - Fit plane using PlanarRegressionZ                           │
│  - Evaluate plane at vertex location                            │
│  - Output: Vertex WSE value                                     │
│                                                                 │
│  Method: MeshFV2D.ComputeFacePointWSs()                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              STAGE 3: TRIANGULATION & RASTERIZATION             │
│                                                                 │
│  For each cell:                                                 │
│  - Create triangles from cell center + vertices (+ face mids)   │
│  - For each triangle:                                           │
│    - Define plane through 3 points with WSE values              │
│    - Rasterize pixels within triangle                           │
│    - Interpolate WSE using PlaneM coefficients                  │
│                                                                 │
│  Method: RasterizeTriangles.ComputeCells()                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OUTPUT RASTER (GeoTIFF)                      │
│                    [WSE value per pixel]                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Structures

### Cell
```csharp
struct Cell {
    Point2D Point;           // Cell center coordinates
    float MinimumElevation;  // Minimum terrain elevation in cell
    List<int> Faces;         // Indices of adjacent faces
}
```

### Face
```csharp
struct Face {
    int cellA;               // Index of cell on side A
    int cellB;               // Index of cell on side B (-1 if perimeter)
    int fpA;                 // FacePoint index at start
    int fpB;                 // FacePoint index at end
    float MinimumElevation;  // Minimum terrain elevation along face
}
```

### FacePoint (Vertex)
```csharp
struct FacePoint {
    Point2Double Point;      // Vertex coordinates
    List<int> Faces;         // Indices of faces meeting at this vertex
}
```

### FaceValues
```csharp
struct FaceValues {
    float ValueA;            // WSE value for cell A side
    float ValueB;            // WSE value for cell B side
    HydraulicConnection HydraulicConnection;  // Connection type

    bool IsHydraulicallyConnected => HydraulicConnection != None;
}

enum HydraulicConnection {
    None,                    // No hydraulic connection
    Backfill,               // Water flowing uphill
    Levee,                  // Levee/weir condition
    DownhillDeep,           // Deep flow (depth >= 2 * terrain gradient)
    DownhillShallow,        // Shallow flow (depth < terrain gradient)
    DownhillIntermediate    // Intermediate flow
}
```

### FaceMidside
```csharp
struct FaceMidside {
    Point2Double Point;      // Midside point coordinates
    int SegmentIndex;        // Index of segment on face polyline
}
```

---

## Stage 1: Face WSE Computation

### Method: `MeshFV2D.ComputeFaceWSsNew()`
**Source**: `MeshFV2D.cs` lines 9331-9447

### Algorithm (Pseudocode)

```python
def compute_face_wse(face_idx, cell_wse_a, cell_wse_b):
    """
    Compute face WSE values with hydraulic connectivity.

    Returns FaceValues with ValueA, ValueB, and HydraulicConnection type.
    """
    face = faces[face_idx]
    cell_a, cell_b = face.cellA, face.cellB

    cell_a_min_elev = cells[cell_a].MinimumElevation
    cell_b_min_elev = cells[cell_b].MinimumElevation
    face_min_elev = face.MinimumElevation

    MIN_WS_PLOT_TOLERANCE = 0.001  # From RASResults
    NODATA = -9999.0

    # ═══════════════════════════════════════════════════════════════
    # CHECK 1: Dry cells or perimeter face
    # ═══════════════════════════════════════════════════════════════
    is_dry_a = cell_wse_a <= cell_a_min_elev + MIN_WS_PLOT_TOLERANCE
    is_dry_b = cell_wse_b <= cell_b_min_elev + MIN_WS_PLOT_TOLERANCE
    is_perimeter = (cell_a < 0) or (cell_b < 0) or face_is_perimeter(face_idx)

    if is_dry_a or is_dry_b or is_perimeter:
        return FaceValues(
            value_a = NODATA if (is_dry_a or cell_is_virtual(cell_a)) else cell_wse_a,
            value_b = NODATA if (is_dry_b or cell_is_virtual(cell_b)) else cell_wse_b,
            hydraulic_connection = "None"
        )

    # ═══════════════════════════════════════════════════════════════
    # CHECK 2: Both cells below face minimum elevation
    # ═══════════════════════════════════════════════════════════════
    if cell_wse_a <= face_min_elev and cell_wse_b <= face_min_elev:
        return FaceValues(
            value_a = cell_wse_a,
            value_b = cell_wse_b,
            hydraulic_connection = "None"
        )

    # ═══════════════════════════════════════════════════════════════
    # DETERMINE HIGH/LOW CELLS
    # ═══════════════════════════════════════════════════════════════
    if cell_wse_a > cell_wse_b:
        high_cell = cell_a
        max_wse = cell_wse_a
        low_wse = cell_wse_b
        high_cell_min_elev = cell_a_min_elev
    else:
        high_cell = cell_b
        max_wse = cell_wse_b
        low_wse = cell_wse_a
        high_cell_min_elev = cell_b_min_elev

    # Terrain gradient between cells
    terrain_gradient = abs(cell_b_min_elev - cell_a_min_elev)

    # Depth in high cell
    depth = max_wse - high_cell_min_elev

    # ═══════════════════════════════════════════════════════════════
    # CRITICAL FLOW CAP CHECK
    # ═══════════════════════════════════════════════════════════════
    avg_wse = (cell_wse_a + cell_wse_b) / 2
    crit_wse = (max_wse - face_min_elev) * (2/3) + face_min_elev
    was_crit_cap_used = avg_wse <= crit_wse

    # ═══════════════════════════════════════════════════════════════
    # CHECK 3: Backfill (water flowing uphill)
    # ═══════════════════════════════════════════════════════════════
    wse_gradient = cell_wse_b - cell_wse_a
    terrain_diff = cell_b_min_elev - cell_a_min_elev
    is_backfill = (wse_gradient * terrain_diff <= 0) and (terrain_gradient > 0)

    # ═══════════════════════════════════════════════════════════════
    # CHECK 4: Levee condition
    # ═══════════════════════════════════════════════════════════════
    depth_above_face = max_wse - face_min_elev
    is_levee = (was_crit_cap_used and
                depth_above_face > 0 and
                depth / depth_above_face > 2)

    if is_levee:
        if high_cell == cell_a:
            return FaceValues(max_wse, cell_wse_b, "Levee")
        else:
            return FaceValues(cell_wse_a, max_wse, "Levee")

    if is_backfill:
        return FaceValues(max_wse, max_wse, "Backfill")

    # ═══════════════════════════════════════════════════════════════
    # CHECK 5: Downhill Deep (depth >= 2 * terrain gradient)
    # ═══════════════════════════════════════════════════════════════
    if terrain_gradient > 0 and depth >= 2 * terrain_gradient:
        return FaceValues(max_wse, max_wse, "DownhillDeep")

    # ═══════════════════════════════════════════════════════════════
    # CASE 6: Downhill Shallow/Intermediate
    # ═══════════════════════════════════════════════════════════════
    if terrain_gradient > 0:
        num5 = max(face_min_elev, low_wse)
        num6 = num5 - high_cell_min_elev

        # Quadratic interpolation formula
        face_wse = num5 + (depth**2 - num6**2) / (2 * terrain_gradient)

        if depth > terrain_gradient:
            # Intermediate: blend toward max_wse
            face_wse = ((2 * terrain_gradient - depth) * face_wse +
                       (depth - terrain_gradient) * max_wse) / terrain_gradient
            return FaceValues(face_wse, face_wse, "DownhillIntermediate")
        else:
            return FaceValues(face_wse, face_wse, "DownhillShallow")

    # ═══════════════════════════════════════════════════════════════
    # DEFAULT: No connection, use cell values directly
    # ═══════════════════════════════════════════════════════════════
    return FaceValues(cell_wse_a, cell_wse_b, "None")
```

---

## Stage 2: Vertex WSE Computation

### Method: `MeshFV2D.ComputeFacePointWSs()`
**Source**: `MeshFV2D.cs` lines 9483-9571

### PlanarRegressionZ Class
**Source**: `PlanarRegressionZ.cs`

```python
class PlanarRegressionZ:
    """
    Least-squares planar regression for computing Z at a base point.

    Fits plane Z = ax + by + c through points, evaluates at base (returns c).
    """

    def __init__(self, base_x: float, base_y: float):
        self.base_x = base_x
        self.base_y = base_y
        self.sum_x2 = 0.0
        self.sum_x = 0.0
        self.sum_y2 = 0.0
        self.sum_y = 0.0
        self.sum_z = 0.0
        self.sum_xy = 0.0
        self.sum_yz = 0.0
        self.sum_xz = 0.0
        self.n = 0

    def add(self, x: float, y: float, z: float):
        """Add a point to the regression."""
        dx = x - self.base_x
        dy = y - self.base_y

        self.sum_x2 += dx * dx
        self.sum_x += dx
        self.sum_y2 += dy * dy
        self.sum_y += dy
        self.sum_z += z
        self.sum_xy += dx * dy
        self.sum_yz += dy * z
        self.sum_xz += dx * z
        self.n += 1

    def solve_z(self) -> float:
        """Solve for Z at the base point."""
        if self.n == 1:
            return self.sum_z
        if self.n == 2:
            return self.sum_z / 2

        # Determinant of normal equations matrix
        det = (self.sum_x2 * (self.sum_y2 * self.n - self.sum_y * self.sum_y) -
               self.sum_xy * (self.sum_xy * self.n - self.sum_y * self.sum_x) +
               self.sum_x * (self.sum_xy * self.sum_y - self.sum_y2 * self.sum_x))

        if det == 0:
            return self.sum_z / self.n  # Fallback to average

        # Solve for Z at base point (where dx=0, dy=0)
        z = (self.sum_x2 * (self.sum_y2 * self.sum_z - self.sum_yz * self.sum_y) -
             self.sum_xy * (self.sum_xy * self.sum_z - self.sum_yz * self.sum_x) +
             self.sum_xz * (self.sum_xy * self.sum_y - self.sum_y2 * self.sum_x)) / det

        return z
```

### Face Application Point
**Source**: `RASD2FlowArea.GetFaceLocationFunc()` (line 6562)

```python
def get_face_application_point(face_idx: int) -> Tuple[float, float]:
    """
    Get the point where face WSE is "applied" for planar regression.

    Two options based on RASResults.UseFaceCentroidAdjustment:
    1. Face Centroid (if enabled and cached)
    2. Face Midside (intersection of cell-center line with face, or midpoint)
    """
    if USE_FACE_CENTROID_ADJUSTMENT:
        return mesh.face_centroid_point(face_idx)
    else:
        return mesh.get_face_midside(face_idx).point
```

### Face Midside Calculation
**Source**: `MeshFV2D.EnsureFaceMidsideCached()` (line 9574)

```python
def get_face_midside(face_idx: int) -> Point:
    """
    Calculate face midside point.

    For internal faces: intersection of line(cellA_center, cellB_center) with face
    For perimeter faces: face midpoint
    """
    face = faces[face_idx]
    face_polyline = get_face_polyline(face_idx)

    if face.cellA >= 0 and face.cellB >= 0:
        # Internal face: intersect cell-center line with face
        cell_a_center = cells[face.cellA].Point
        cell_b_center = cells[face.cellB].Point
        segment = Segment(cell_a_center, cell_b_center)

        intersection = face_polyline.get_line_intersection(segment)
        if intersection is not None:
            return intersection.point

    # Fallback: face midpoint
    return face_polyline.midpoint()
```

### Vertex WSE Algorithm

```python
def compute_facepoint_wse(fp_idx: int, face_wse_values: List[FaceValues],
                          get_face_application_point: Callable) -> List[float]:
    """
    Compute vertex WSE using planar regression.

    Returns list of WSE values, one per adjacent face (for hydraulic connectivity).
    """
    facepoint = facepoints[fp_idx]
    adjacent_faces = facepoint.Faces
    result = [NODATA] * len(adjacent_faces)

    # Check if all faces are dry
    all_dry = True
    for face_idx in adjacent_faces:
        fv = face_wse_values[face_idx]
        if fv.value_a != NODATA or fv.value_b != NODATA:
            all_dry = False
            break

    if all_dry:
        return result

    # ═══════════════════════════════════════════════════════════════
    # HYDRAULIC CONNECTIVITY GROUPING
    # ═══════════════════════════════════════════════════════════════
    # Faces around a vertex are grouped by hydraulic connectivity.
    # Each connected group gets its own planar regression.

    processed = [False] * len(adjacent_faces)

    for start_idx in range(len(adjacent_faces)):
        if processed[start_idx]:
            continue

        # Find extent of hydraulically connected faces
        # (traverse CCW until hitting non-connected face or returning to start)

        regression = PlanarRegressionZ(facepoint.Point.x, facepoint.Point.y)

        # Collect face WSE values for this connected group
        current_idx = start_idx
        group_indices = []

        while True:
            face_idx = adjacent_faces[current_idx]
            fv = face_wse_values[face_idx]

            # Get appropriate value based on face orientation
            face = faces[face_idx]
            if face.fpA == fp_idx:
                face_wse = fv.value_a
            else:
                face_wse = fv.value_b

            if face_wse != NODATA:
                app_point = get_face_application_point(face_idx)
                regression.add(app_point.x, app_point.y, face_wse)

            group_indices.append(current_idx)
            processed[current_idx] = True

            # Move to next face CCW
            next_idx = (current_idx + 1) % len(adjacent_faces)

            # Stop if not hydraulically connected or back to start
            if (not fv.is_hydraulically_connected or
                next_idx == start_idx or
                processed[next_idx]):
                break

            current_idx = next_idx

        # Solve regression for this group
        if regression.count() > 0:
            vertex_wse = regression.solve_z()
            for idx in group_indices:
                result[idx] = vertex_wse

    return result
```

---

## Stage 3: Cell Triangulation and Rasterization

### Method: `RasterizeTriangles.ComputeCells()`
**Source**: `RasterizeTriangles.cs`

### PlaneM (Plane with M-value)
Used for linear interpolation within triangles:

```python
class PlaneM:
    """Plane defined by 3 points, for interpolating Z and M values."""

    def set_coefficients_pt_pt_pt(self, p0, p1, p2):
        """Define plane through 3 points."""
        # Each point has (x, y, z, m) where z=WSE, m=optional second value
        # Computes plane coefficients for Z = ax + by + c
        pass

    def dz_dx(self) -> float:
        """Partial derivative dZ/dX."""
        pass

    def z(self, x: float, y: float) -> float:
        """Evaluate Z at point (x, y)."""
        pass
```

### Triangle Rasterization Algorithm

```python
def rasterize_triangles(p0, p1, p2, raster, fill_cell_action):
    """
    Rasterize a triangle to a grid.

    p0, p1, p2: Triangle vertices with (x, y, z, m) values
    raster: Target raster grid
    fill_cell_action: Callback(cell_idx, z_value, m_value)
    """
    # Quick bounds check
    if (all x < raster.min_x or all x > raster.max_x or
        all y < raster.min_y or all y > raster.max_y):
        return

    # Define plane through triangle
    plane = PlaneM()
    plane.set_coefficients_pt_pt_pt(p0, p1, p2)

    # Pre-compute Z gradient for row traversal
    dz_dx = plane.dz_dx() * raster.cell_size

    # Sort points by Y coordinate (p0=top, p2=bottom)
    p0, p1, p2 = sort_by_y(p0, p1, p2)

    if p0.y == p2.y:
        return  # Degenerate triangle

    # Compute row range
    top_row = raster.row(p2.y)  # Note: row 0 is at max_y
    bottom_row = raster.row(p0.y)

    # Edge slopes
    slope_02 = (p2.x - p0.x) / (p2.y - p0.y)  # Long edge
    slope_12 = (p2.x - p1.x) / (p2.y - p1.y)  # Top short edge
    slope_01 = (p1.x - p0.x) / (p1.y - p0.y)  # Bottom short edge

    # Initial X positions at top row
    y = raster.cell_center_y(top_row)
    x_long = p2.x + slope_02 * (y - p2.y)
    x_short_top = p2.x + slope_12 * (y - p2.y)
    x_short_bottom = p1.x + slope_01 * (y - p1.y)

    # Rasterize row by row
    for row in range(top_row, bottom_row + 1):
        # Determine X range for this row
        x_left = x_long
        x_right = x_short_top if y > p1.y else x_short_bottom

        if x_left > x_right:
            x_left, x_right = x_right, x_left

        # Column range
        col_left = raster.col(x_left)
        col_right = raster.col(x_right)

        # Clamp to raster bounds
        col_left = max(0, col_left)
        col_right = min(raster.cols - 1, col_right)

        # Fill cells in this row
        x = raster.cell_center_x(col_left)
        z = plane.z(x, y)

        for col in range(col_left, col_right + 1):
            cell_idx = row * raster.cols + col
            fill_cell_action(cell_idx, z, 0)  # m=0 for WSE-only
            z += dz_dx

        # Move to next row
        y -= raster.cell_size
        x_long -= slope_02 * raster.cell_size
        x_short_top -= slope_12 * raster.cell_size
        x_short_bottom -= slope_01 * raster.cell_size
```

### Cell Triangulation Pattern

For "Sloped (Cell Corners)" mode, each cell is divided into triangles:

```
   FP0 ─────── Face0 ─────── FP1
    │ \                     / │
    │   \                 /   │
    │     \    Cell     /     │
  Face3    \  Center  /    Face1
    │       \   ●   /       │
    │         \   /         │
    │           X           │
   FP3 ─────── Face2 ─────── FP2

Triangles (for 4-sided cell):
1. (CellCenter, FP0, FP1)
2. (CellCenter, FP1, FP2)
3. (CellCenter, FP2, FP3)
4. (CellCenter, FP3, FP0)
```

For "Sloped (Cell Corners + Face Centers)" mode, face midpoints are also included:

```
   FP0 ── FM0 ── FP1
    │ \   │   / │
    │   \ │ /   │
   FM3 ── ● ── FM1
    │   / │ \   │
    │ /   │   \ │
   FP3 ── FM2 ── FP2

Triangles (8 per cell):
1. (CellCenter, FP0, FM0)
2. (CellCenter, FM0, FP1)
... etc
```

---

## Configuration Options

### Render Modes
**Source**: `SharedData.CellRenderMethod` and `.rasmap` XML

| Mode | XML Value | Description |
|------|-----------|-------------|
| Horizontal | `horizontal` | Constant WSE per cell |
| Sloped (Cell Corners) | `sloping` | Interpolate using 4 corners |
| Sloped (Cell Corners + Face Centers) | `slopingPretty` | 8-point interpolation |

### Options in `.rasmap` File

```xml
<Layer Name="WSE">
  <RenderMode>slopingPretty</RenderMode>
  <UseDepthWeightedFaces>true</UseDepthWeightedFaces>
  <ReduceShallowToHorizontal>true</ReduceShallowToHorizontal>
</Layer>
```

| Option | Effect |
|--------|--------|
| `UseDepthWeightedFaces` | Weight face contributions by depth |
| `ReduceShallowToHorizontal` | Use horizontal mode for shallow cells |

### Face WSE Mode
**Source**: `SharedData.FaceWSMode`

| Mode | Method |
|------|--------|
| `Adjusted` | `ComputeFaceWSsNew()` - Full hydraulic algorithm |
| `BENPrev` | `ComputeFaceWSsBENPrev()` - Older algorithm |

---

## Complete Code References

### Key Source Files (Decompiled)

| File | Location | Purpose |
|------|----------|---------|
| `MeshFV2D.cs` | `RasMapperLib/` | Core mesh operations, face/vertex WSE |
| `PlanarRegressionZ.cs` | `RasMapperLib/` | Planar regression class |
| `SlopingFactors.cs` | `RasMapperLib.Render/` | Orchestration of sloped calculations |
| `RasterizeTriangles.cs` | `RasMapperLib/` | Triangle rasterization |
| `RASD2FlowArea.cs` | `RasMapperLib/` | Face location functions |
| `WaterSurfaceRenderer.cs` | `RasMapperLib.Render/` | Main rendering pipeline |
| `FaceValues.cs` | `RasMapperLib.Mesh/` | Face WSE structure |
| `FacePoint.cs` | `RasMapperLib.Mesh/` | Vertex structure |

### Line Number References

| Method | File | Lines |
|--------|------|-------|
| `ComputeFaceWSsNew` | MeshFV2D.cs | 9331-9447 |
| `ComputeFacePointWSs` | MeshFV2D.cs | 9483-9571 |
| `EnsureFaceMidsideCached` | MeshFV2D.cs | 9574-9609 |
| `GetFaceLocationFunc` | RASD2FlowArea.cs | 6562-6572 |
| `PlanarRegressionZ.SolveZ` | PlanarRegressionZ.cs | 151-167 |
| `RasterizeTriangles.ComputeCells` | RasterizeTriangles.cs | 15-121 |

---

## Validation Approach

### Ground Truth Data

Project: `BaldEagleCrkMulti2D - Sloped - Cell Corners`
- Located in `Test Data/`
- Contains RASMapper-exported TIFs for comparison
- Multiple plans with different hydraulic conditions

### Comparison Metrics

| Metric | Target |
|--------|--------|
| RMSE | < 0.01 ft |
| MAE | < 0.01 ft |
| Max Absolute Error | < 0.1 ft |
| Pixel Count Match | > 99% |

### Test Procedure

1. Load mesh geometry from `.g##.hdf`
2. Load cell WSE from `.p##.hdf`
3. Load terrain elevations from terrain TIF
4. Compute face and vertex WSE using algorithm
5. Triangulate and rasterize
6. Compare pixel-by-pixel with RASMapper output
7. Report statistics

---

## Implementation Notes

### Critical Details

1. **NODATA Value**: Use -9999.0 consistently
2. **Floating Point**: Use float32 for consistency with HDF
3. **Coordinate System**: Match terrain raster CRS
4. **Cell Size**: Match output to terrain raster cell size
5. **Edge Handling**: Perimeter faces have cellA or cellB = -1

### Common Pitfalls

1. **Wrong face orientation**: Check fpA vs fpB for correct WSE value
2. **Missing terrain data**: Face/cell minimum elevations come from preprocessed geometry
3. **Hydraulic connectivity**: Don't ignore the connection type
4. **Face midside vs midpoint**: Use intersection method for internal faces

---

*Document generated from decompiled RasMapperLib.dll analysis*
*Last updated: 2025-12-09*
