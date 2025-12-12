# RASMapper Sloped Interpolation Algorithm

## Discovery Summary

**Date**: 2025-12-09
**Method**: .NET Decompilation using ILSpy
**Source**: `RasMapperLib.dll` → `RASGeometryMapPoints` class
**Key Method**: `BensWeights()` (line 2895)

---

## Algorithm Overview

RASMapper uses a custom **polygon-based generalized barycentric coordinate** interpolation method (called "Ben's Weights") to compute vertex water surface elevations from cell/face values.

### High-Level Workflow

```
1. For each grid pixel (raster cell):
   a. Find which mesh cell contains the pixel center
   b. Compute interpolation weights from mesh facepoints → pixel
   c. Apply weights to facepoint WSE values
   d. Store interpolated WSE at pixel

2. Rasterize pixels to GeoTIFF using GDAL
```

---

## The "Ben's Weights" Algorithm

### Mathematical Foundation

This is a **generalized barycentric coordinate system** for arbitrary convex polygons, similar to Wachspress coordinates or mean value coordinates.

For a point `p` inside a cell with `n` faces:
- Each face contributes a weight based on:
  1. **Cross products** from adjacent facepoints (measures "angular contribution")
  2. **Product of distances** to other faces (normalizes contribution)

### Algorithm Steps (from decompiled code)

#### Step 1: Compute Cross Products

For each face `j` in the cell (lines 2914-2946):

```csharp
// For face j, get the three key facepoints:
// - point2: Previous facepoint on previous face (CCW)
// - point3: Shared facepoint between faces j-1 and j
// - point4: Next facepoint on face j

Point2Double point2 = mesh.FacePoints[fPPrev].Point;
Point2Double point3 = mesh.FacePoints[fPNext].Point;
Point2Double point4 = mesh.FacePoints[fPNext2].Point;

// Compute cross product term (triangle area contribution)
// This measures the "angular span" of face j as seen from point p
array[j] = num7 * Vector.CrossProduct(point3, point4, point2);
```

Where `num7` is the **product of cross products from all OTHER faces**:
```csharp
double num7 = 1.0;
for (int k = 0; k <= num - 1; k++)
{
    if (k != j && k != j-1)  // Exclude current and previous face
    {
        num7 *= pixelXProducts[k];
    }
}
```

`pixelXProducts[k]` = cross product from pixel `p` to face `k` endpoints (computed in `GetPixelXProducts()`)

#### Step 2: Normalize to Weights

```csharp
// Sum of all contributions
double num3 = Sum(array[j] for all j);

// Normalize to get weights (sum = 1.0)
fpWeights[j] = (float)(array[j] / num3);
```

#### Step 3: Handle Points Outside Cell (Negative Weights)

If point `p` is outside the cell, some weights will be negative:

```csharp
if (flag)  // Any negative weights detected
{
    // Clamp negative weights to zero
    for (int m = 0; m <= num-1; m++)
    {
        if (fpWeights[m] < 0f)
            fpWeights[m] = 0f;
    }

    // Re-normalize to sum = 1.0
    float sum = Sum(fpWeights);
    for (int n = 0; n <= num-1; n++)
    {
        fpWeights[n] /= sum;
    }
}
```

This handles **perimeter cells** where grid pixels extend beyond the mesh boundary.

---

## Data Structures

### SlopingCellPoint

```csharp
public struct SlopingCellPoint
{
    public int Index;                 // Grid pixel index in flattened raster
    public float[] FPPrevWeights;     // Interpolation weights [n_faces]
    public float[] VelocityWeights;   // Velocity interpolation weights [n_faces*2]
}
```

### Interpolation Weights

**FPPrevWeights** (length = n_faces):
- `fpWeights[j]` = contribution from face `j`'s facepoint to pixel WSE
- Sum of all weights = 1.0 (normalized)
- Computed using `BensWeights()` algorithm

**VelocityWeights** (length = n_faces * 2):
- More complex: includes face-center contributions
- Uses `Donate()` method to distribute weights between faces and face-centers
- First `n_faces` elements: face contributions
- Last `n_faces` elements: face-center contributions

---

## Velocity Interpolation: The "Donate" Method

After computing face weights, velocity weights are adjusted using a "donation" scheme (lines 2988-3039):

```csharp
private void Donate(float[] fpWeights, float[] velocityWeights, PixelComputeBuffer buf)
{
    // For each face i:
    for (int i = 0; i <= count-1; i++)
    {
        int prev = (i - 1 + count) % count;  // Previous face (CCW)
        int next = (i + 1) % count;           // Next face (CW)

        float w_i = fpWeights[i];
        float w_prev = fpWeights[prev];
        float w_next = fpWeights[next];

        // How much can face i donate to its neighbors?
        float canGiveCCW = w_i * w_next / (w_prev + w_next);
        float canGiveCW  = w_i * w_prev / (w_prev + w_next);

        buf.CCWCanGive[i] = canGiveCCW;
        buf.CWCanGive[i] = canGiveCW;
    }

    // Transfer weights from faces to face-centers
    for (int j = 0; j <= count-1; j++)
    {
        int next = (j + 1) % count;

        // How much can be transferred from faces j and next to their shared center?
        float transfer = Min(buf.CCWCanGive[j], buf.CWCanGive[next]);

        // Reduce face weights
        velocityWeights[j] -= transfer;
        velocityWeights[next] -= transfer;

        // Add to face-center weight
        velocityWeights[count + j] = transfer * 2.0;
    }
}
```

**Purpose**: Redistribute weights to account for velocity being stored at **face centers**, not facepoints.

---

## Bilinear Interpolation (1D Cross-Sections)

For 1D elements with rectangular cross-sections (lines 2878-2892):

```csharp
// Four-corner bilinear interpolation
fPPrevWeights[corner[0]] = (1 - u) * (1 - v);  // Bottom-left
fPPrevWeights[corner[1]] = (1 - u) * v;        // Top-left
fPPrevWeights[corner[2]] = u * v;              // Top-right
fPPrevWeights[corner[3]] = u * (1 - v);        // Bottom-right
```

Where `u` and `v` are normalized coordinates (0-1) within the rectangular cell.

---

## Implementation in ras-commander

### Proposed Python Implementation

```python
def compute_sloped_wse(
    cell_polygons: gpd.GeoDataFrame,  # From HdfMesh.get_mesh_cell_polygons()
    cell_wse: gpd.GeoDataFrame,       # From HdfResultsMesh.get_mesh_max_ws()
    terrain_transform: rasterio.Affine,
    terrain_shape: Tuple[int, int]
) -> np.ndarray:
    """
    Compute sloped water surface elevation raster using Ben's Weights algorithm.

    Returns:
        wse_raster: np.ndarray of shape terrain_shape with interpolated WSE
    """

    # Initialize output raster
    wse_raster = np.full(terrain_shape, np.nan, dtype=np.float32)

    # Spatial index for fast cell lookup
    cell_spatial_index = cell_polygons.sindex

    # For each pixel in raster
    for row in range(terrain_shape[0]):
        for col in range(terrain_shape[1]):
            # Get pixel center coordinates
            x, y = rasterio.transform.xy(terrain_transform, row, col)
            point = Point(x, y)

            # Find containing cell
            possible_cells = list(cell_spatial_index.intersection((x, y, x, y)))
            for cell_idx in possible_cells:
                cell_geom = cell_polygons.iloc[cell_idx].geometry

                if cell_geom.contains(point):
                    # Compute Ben's Weights
                    face_wse = get_face_wse(cell_idx, cell_wse)
                    face_coords = get_face_coordinates(cell_idx, cell_polygons)

                    weights = compute_bens_weights(point, face_coords)

                    # Interpolate WSE
                    wse_raster[row, col] = np.dot(weights, face_wse)
                    break

    return wse_raster


def compute_bens_weights(
    point: Point,
    face_coords: List[Tuple[float, float]]
) -> np.ndarray:
    """
    Compute Ben's Weights for a point inside a polygon.

    Args:
        point: Query point (pixel center)
        face_coords: List of (x, y) coordinates of facepoints (CCW order)

    Returns:
        weights: np.ndarray of shape (n_faces,) summing to 1.0
    """
    n = len(face_coords)
    px, py = point.x, point.y

    # Step 1: Compute cross products from point to each face
    xproducts = []
    for i in range(n):
        j = (i + 1) % n
        x1, y1 = face_coords[i]
        x2, y2 = face_coords[j]

        # Cross product: (p->face_i) × (p->face_j)
        xprod = (x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)
        xproducts.append(max(xprod, 1e-5))  # Avoid division by zero

    # Step 2: Compute weights using product of OTHER cross products
    raw_weights = []
    for i in range(n):
        prev = (i - 1) % n

        # Product of all cross products EXCEPT i and prev
        product = 1.0
        for k in range(n):
            if k != i and k != prev:
                product *= xproducts[k]

        # Get triangle formed by three facepoints
        i_prev = (i - 1) % n
        i_next = (i + 1) % n
        p_prev = face_coords[i_prev]
        p_curr = face_coords[i]
        p_next = face_coords[i_next]

        # Cross product of triangle
        triangle_area = (
            (p_curr[0] - p_prev[0]) * (p_next[1] - p_prev[1]) -
            (p_next[0] - p_prev[0]) * (p_curr[1] - p_prev[1])
        )

        raw_weights.append(product * triangle_area)

    # Step 3: Normalize
    raw_weights = np.array(raw_weights)
    total = raw_weights.sum()

    if total == 0:
        # Fallback: equal weights
        return np.ones(n) / n

    weights = raw_weights / total

    # Step 4: Handle negative weights (point outside polygon)
    if np.any(weights < 0):
        weights = np.maximum(weights, 0)
        weights /= weights.sum()

    return weights
```

### Integration with RasMap

Add new method to `ras_commander/RasMap.py`:

```python
@staticmethod
def map_ras_results_sloped(
    plan_number: str,
    variables: List[str],
    terrain_path: Path,
    output_dir: Path = None,
    depth_weighted_faces: bool = False,
    shallow_reduces_to_horizontal: bool = True,
    shallow_threshold_ft: float = 0.5,
    ras_object: RasPrj = None
) -> Dict[str, Path]:
    """
    Generate sloped water surface rasters using cell corner interpolation.

    This implements RASMapper's "Sloped (Cell Corners)" rendering mode using
    the Ben's Weights algorithm (generalized barycentric coordinates).

    Args:
        plan_number: Plan number (e.g., "01", "15")
        variables: List of variables ["WSE", "Depth", "Velocity"]
        terrain_path: Path to terrain raster (for resolution and extent)
        output_dir: Output directory for rasters
        depth_weighted_faces: Use depth-weighted face velocities (Precip Mode)
        shallow_reduces_to_horizontal: Shallow water uses flat interpolation
        shallow_threshold_ft: Depth threshold for shallow water (default 0.5 ft)
        ras_object: RasPrj instance (uses global ras if None)

    Returns:
        Dictionary mapping variable names to output raster paths
    """
```

---

## Key Insights

1. **Not standard barycentric coordinates**: Uses a custom generalized method for arbitrary polygons
2. **Cross product weighting**: Weights based on "angular contribution" of each face
3. **Handles non-convex cases**: Negative weight clamping for perimeter pixels
4. **Velocity requires redistribution**: Face-center values need special handling via `Donate()`
5. **Shallow water optimization**: Falls back to horizontal mode for thin water (performance)

---

## Testing Strategy

1. **Extract test data**:
   - Use "Sloped - Cell Corners" project from Test Data
   - Get mesh geometry, cell WSE, face coordinates from HDF
   - Load RASMapper ground truth raster

2. **Implement algorithm**:
   - Start with simple convex cells (triangles, quads)
   - Test weight computation for known geometries
   - Validate weight sum = 1.0

3. **Compare outputs**:
   - Compute RMSE vs RASMapper raster
   - Target: RMSE < 0.01 ft (similar to horizontal mode)
   - Check edge cases: perimeter, concave cells, dry cells

4. **Performance optimization**:
   - Use spatial indexing (rtree) for cell lookup
   - Vectorize weight computation where possible
   - Consider Cython for hot loops

---

## References

### Decompiled Source Files
- `RasMapperLib.RASGeometryMapPoints.decompiled.cs` (lines 2895-3039)
- `RasMapperLib.Mapping.SlopingCellPoint.decompiled.cs`
- `RasMapperLib.InterpolatedLayer.decompiled.cs`

### Mathematical Background
- **Generalized Barycentric Coordinates**: Wachspress (1975), Mean Value Coordinates (Floater 2003)
- **GDAL Linear Interpolation**: Delaunay triangulation + barycentric interpolation
- **Cross Product Method**: Custom HEC-RAS implementation (likely by Ben Pratt, HEC developer)

### ras-commander APIs
- `HdfMesh.get_mesh_cell_polygons()` - Cell geometry
- `HdfMesh.get_mesh_cell_faces()` - Face connectivity
- `HdfResultsMesh.get_mesh_max_ws()` - Water surface elevations
- `RasMap.map_ras_results()` - Horizontal mode (already implemented)

---

**Document Status**: Algorithm fully understood from decompilation
**Next Step**: Implement in Python and validate against RASMapper output
**Estimated Complexity**: Medium (100-200 lines of core logic)
**Expected Accuracy**: RMSE < 0.01 ft (matching horizontal mode validation)
