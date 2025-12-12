# RASGeometryMapPoints Class Documentation

**Purpose**: Core class responsible for mapping raster pixels or points to HEC-RAS geometry elements and computing interpolation weights using Ben's Weights algorithm (generalized barycentric coordinates).

**Namespace**: `RasMapperLib`

**Source**: Decompiled from `RasMapperLib.dll`

---

## Table of Contents

1. [Class Overview](#class-overview)
2. [Key Data Structures](#key-data-structures)
3. [Public Methods](#public-methods)
4. [Ben's Weights Algorithm](#bens-weights-algorithm)
5. [Face WSE Computation](#face-wse-computation)
6. [Interpolation Methods](#interpolation-methods)
7. [Rasterization Methods](#rasterization-methods)
8. [Python Implementation Guide](#python-implementation-guide)

---

## Class Overview

### Purpose

`RASGeometryMapPoints` is the central class for RASMapper's water surface interpolation system. It:

1. **Rasterizes** HEC-RAS geometry features (2D flow areas, storage areas, cross-sections) onto a target raster
2. **Maps** each pixel to its containing mesh cell(s)
3. **Computes** generalized barycentric coordinates (Ben's Weights) for interpolation
4. **Manages** multiple render modes (horizontal, sloped, sloped with cell corners)

### Class Hierarchy

```
RASGeometryMapPoints : ISizeKnown
```

### Key Fields

```csharp
// Geometry references
private RASGeometry _geometry;
private RASD2FlowArea _D2;              // 2D flow areas
private RASStorageArea _SA;             // Storage areas
private BlockedObstructionLayer _BO;     // Blocked obstructions
private RASXSInterpolationSurface _XSIS; // Cross-section interpolation surfaces
private RASPipeNetworks _PN;             // Pipe networks

// Query state
private QueryType _queryType;            // None, Raster, or Points
private RasterM _raster;                 // Target raster grid
private int _pointCount;                 // Number of points being mapped
private BitArray _mappedPixels;          // Tracks which pixels have been mapped

// Mapped results
public List<MappedXSIS> MappedXSISs;     // Cross-section mappings
public List<SAMap> MappedSAs;            // Storage area mappings
public List<SAMap> MappedBOs;            // Blocked obstruction mappings
private List<FlatMeshMap> _flatAreas;    // Horizontal interpolation cells
private List<SlopingMeshMap> _slopingAreas; // Sloped interpolation cells
private List<Sloping1DMeshMap> _slopingAreas1DMesh; // 1D sloped cells

// Performance optimization
private List<SlopingCellPoint> _reusableSquarePixels; // Reusable weights for square cells
private int _reusablePixelsInUse;
private bool _canTranslate;              // Can reuse previous raster computation
private Dictionary<int, SlopingCellMap>[] _translatableCells;
```

---

## Key Data Structures

### PixelComputeBuffer

Internal buffer for Ben's Weights computation to avoid repeated allocations.

```csharp
private struct PixelComputeBuffer
{
    public float[] CWCanGive;    // Clockwise donation capacity
    public float[] CCWCanGive;   // Counter-clockwise donation capacity
    public float[] XProducts;    // Cross products for each face
    public int Count;            // Number of facepoints

    public void Resize(int nFacepoints)
    {
        CWCanGive = new float[nFacepoints];
        CCWCanGive = new float[nFacepoints];
        XProducts = new float[nFacepoints];
        Count = nFacepoints;
    }
}
```

### Sloping1DCellInputs

Data structure for 1D sloped cell interpolation (pipes, channels).

```csharp
public struct Sloping1DCellInputs
{
    public int USFace;           // Upstream face index
    public int DSFace;           // Downstream face index
    public double Fraction;      // Position fraction between faces
    public double NodeFraction;  // Node position fraction
}
```

### QueryType Enum

```csharp
private enum QueryType
{
    None,
    Raster,  // Rasterizing to a grid
    Points   // Querying specific points
}
```

---

## Public Methods

### Constructor

```csharp
public RASGeometryMapPoints(RASGeometry geometry)
```

**Purpose**: Initialize the map points object with HEC-RAS geometry.

**Parameters**:
- `geometry`: The RASGeometry object containing all geometry features

**Initializes**:
- Empty lists for all mapped feature types
- Geometry feature references (_D2, _SA, _BO, _XSIS, _PN)
- Tolerance from geometry settings
- Query type to None

---

### ComputeForRaster

```csharp
public void ComputeForRaster(RasterM raster)
```

**Purpose**: Main entry point for rasterizing HEC-RAS geometry onto a target grid.

**Parameters**:
- `raster`: Target raster grid (defines extent, resolution, cell size)

**Algorithm**:

1. **Check for Raster Reuse**:
   - If same cell size/dimensions and overlapping, attempt to translate previous computation
   - Compute `_indexSlide` for pixel index translation
   - Identify `_translatableCells` that remain valid

2. **Clear Previous Results**:
   - Clear all mapped feature lists (MappedXSISs, MappedSAs, etc.)

3. **Rasterize Features** (if overlapping):
   - 2D Flow Areas: `Rasterize2DFlowAreasWithSpatialIndex()`
   - Storage Areas: `RasterizeStorageAreas()`
   - Blocked Obstructions: `RasterizeBlockedObstructions()`
   - Cross-Section Surfaces: `RasterizeCrossSectionRegions()`
   - Pipe Networks: `RasterizePipeNetworkWithSpatialIndex()`

4. **Create BitArray Mask**:
   - Tracks which pixels have been mapped to avoid double-counting

**Python Implementation Notes**:
```python
def compute_for_raster(self, raster):
    """Map HEC-RAS geometry to raster grid."""
    self.query_type = QueryType.RASTER
    self.raster = raster
    self.clear_stored_lists()

    # Create pixel mask
    mask = np.zeros(raster.rows * raster.cols, dtype=bool)

    # Rasterize each feature type
    if raster.overlaps(self.d2_extent):
        self.rasterize_2d_flow_areas(mask)
    if raster.overlaps(self.sa_extent):
        self.rasterize_storage_areas(mask)
    # ... etc
```

---

### ComputeFor1D

```csharp
public void ComputeFor1D(RasterM raster)
```

**Purpose**: Compute mapping for 1D cross-section interpolation surfaces only.

**Parameters**:
- `raster`: Target raster grid

**Algorithm**:
- Only rasterizes XSIS (cross-section interpolation surfaces)
- Used when 2D mesh data is not needed
- Creates `_mappedPixels` BitArray for tracking

---

### ComputeForPoints

```csharp
public void ComputeForPoints(IPoints points, bool reportTime = false,
                             ProgressReporter reporter = null)
```

**Purpose**: Map specific point locations to geometry features (for profiles, cross-sections).

**Parameters**:
- `points`: Collection of PointM objects to map
- `reportTime`: Whether to report timing information
- `reporter`: Progress reporter for UI feedback

**Algorithm**:

1. **Initialize Query**:
   - Set `_queryType = QueryType.Points`
   - Clear previous results

2. **Create Spatial Index**:
   - Build DistinctSpatialIndex for efficient point queries

3. **Map Points to Features**:
   - XSIS regions: `ComputeXSISPoints()`
   - 2D cells (flat): `Compute2DPointsFlat()`
   - Storage areas: `ComputeSAPoints()`
   - Blocked obstructions: `ComputeBOPoints()`
   - 2D cells (sloped): `Compute2DPointsSloped()`

4. **Convert to Sloped**:
   - Call `ConvertFlatToSloped()` to compute Ben's Weights

---

### ComputeForLine

```csharp
public void ComputeForLine(Polyline pline, ref List<PointOnPolyline> intersections,
                           double maxSegmentLen = double.NaN)
```

**Purpose**: Compute geometry intersections along a polyline (for cross-section profiles).

**Parameters**:
- `pline`: Polyline to sample
- `intersections`: Output list of intersection points
- `maxSegmentLen`: Maximum segment length for subsampling

**Algorithm**:

1. **Find Intersections**:
   - Call `ComputeGeometryIntersections()`
   - Intersects polyline with mesh faces, perimeters

2. **Subsample** (if maxSegmentLen specified):
   - Call `SubsampleIntersections()` to add intermediate points

3. **Compute Weights**:
   - Call `ComputeForPoints()` on intersection points

---

## Ben's Weights Algorithm

### Overview

**Ben's Weights** is a generalized barycentric coordinate system for arbitrary convex polygons. It extends traditional barycentric coordinates (used for triangles) to work with mesh cells of any number of sides (3, 4, 5, 6, etc.).

### Mathematical Formula

For a polygon with `n` vertices and a point `p` inside:

```
w_i = (product of cross products excluding adjacent faces) / (sum of all products)
```

Where:
- `w_i` is the weight for vertex `i`
- Cross products are computed from `p` to polygon edges
- Adjacent faces are excluded from the product for each vertex

### Implementation

#### BensWeights Method

```csharp
private void BensWeights(PointM point, MeshFV2D mesh, int cIdx,
                         float areaTolerance, PixelComputeBuffer buf,
                         ref float[] fpWeights, ref float[] velocityWeights)
```

**Purpose**: Compute generalized barycentric coordinates for a point within a mesh cell.

**Parameters**:
- `point`: The query point (pixel center)
- `mesh`: The 2D mesh containing the cell
- `cIdx`: Cell index
- `areaTolerance`: Tolerance for area calculations
- `buf`: Reusable computation buffer
- `fpWeights`: Output facepoint weights (for WSE interpolation)
- `velocityWeights`: Output velocity weights (includes face contributions)

**Algorithm**:

```csharp
// Step 1: Get cross products from point to each face
Cell cell = mesh.Cell(cIdx);
int nFaces = cell.Faces.Count;
float[] pixelXProducts = GetPixelXProducts(mesh, cIdx, point, buf);

// Step 2: Ensure no zero cross products (add small epsilon)
for (int i = 0; i < pixelXProducts.Length; i++)
{
    if (pixelXProducts[i] == 0f)
        pixelXProducts[i] = 1e-5f;
}

// Step 3: Compute weight for each facepoint
double[] weights = new double[nFaces];
double sumWeights = 0.0;

for (int j = 0; j < nFaces; j++)
{
    int curr = j;
    int prev = (j - 1 + nFaces) % nFaces;

    // Product of all cross products EXCEPT adjacent faces
    double product = 1.0;
    for (int k = 0; k < nFaces; k++)
    {
        if (k != curr && k != prev)
            product *= pixelXProducts[k];
    }

    // Get facepoint coordinates for cross product computation
    int faceIdx = cell.Faces[curr];
    int prevFaceIdx = cell.Faces[prev];

    int fp_prev = mesh.Faces[prevFaceIdx].GetFPPrev(cIdx);
    int fp_next = mesh.Faces[prevFaceIdx].GetFPNext(cIdx);
    int fp_next2 = mesh.Faces[faceIdx].GetFPNext(cIdx);

    Point2Double p1 = mesh.FacePoints[fp_prev].Point;
    Point2Double p2 = mesh.FacePoints[fp_next].Point;
    Point2Double p3 = mesh.FacePoints[fp_next2].Point;

    // Final weight calculation
    weights[j] = product * Vector.CrossProduct(p2, p3, p1);
    sumWeights += weights[j];
}

// Step 4: Normalize weights
fpWeights = new float[nFaces];
bool hasNegative = false;

for (int i = 0; i < nFaces; i++)
{
    fpWeights[i] = (float)(weights[i] / sumWeights);
    if (fpWeights[i] < 0f)
        hasNegative = true;
}

// Step 5: Handle negative weights (point near edge/outside)
if (hasNegative)
{
    float sum = 0f;
    for (int i = 0; i < nFaces; i++)
    {
        if (fpWeights[i] < 0f)
            fpWeights[i] = 0f;
        else
            sum += fpWeights[i];
    }

    if (sum != 0f)
    {
        for (int i = 0; i < nFaces; i++)
            fpWeights[i] /= sum;
    }
}

// Step 6: Create velocity weights array
velocityWeights = new float[nFaces * 2];

// Step 7: Distribute weights to face velocities
Donate(fpWeights, velocityWeights, buf);
```

---

### GetPixelXProducts

```csharp
private float[] GetPixelXProducts(MeshFV2D mesh, int cIdx, PointM p,
                                  PixelComputeBuffer buf)
```

**Purpose**: Compute cross products from pixel to each face endpoint.

**Algorithm**:

```csharp
Cell cell = mesh.Cell(cIdx);
int nFaces = cell.Faces.Count;
float[] xProducts = buf.XProducts;
Point2Double pixelPt = new Point2Double(p);

for (int i = 0; i < nFaces; i++)
{
    int faceIdx = cell.Faces[i];
    Face face = mesh.Faces[faceIdx];

    int fpPrev = face.GetFPPrev(cIdx);  // First endpoint
    int fpNext = face.GetFPNext(cIdx);  // Second endpoint

    Point2Double pt1 = mesh.FacePoints[fpPrev].Point;
    Point2Double pt2 = mesh.FacePoints[fpNext].Point;

    // Cross product: (pixelPt - pt1) × (pt2 - pt1)
    xProducts[i] = (float)Vector.CrossProduct(pixelPt, pt1, pt2);
}

return xProducts;
```

**Python Implementation**:

```python
def get_pixel_cross_products(pixel_pt, facepoint_coords):
    """
    Compute cross products from pixel to each face edge.

    Parameters
    ----------
    pixel_pt : (x, y) tuple
        Pixel center coordinates
    facepoint_coords : list of (x, y) tuples
        Coordinates of cell facepoints in CCW order

    Returns
    -------
    cross_products : ndarray
        Cross product for each face
    """
    n = len(facepoint_coords)
    cross_products = np.zeros(n)

    for i in range(n):
        pt1 = facepoint_coords[i]
        pt2 = facepoint_coords[(i + 1) % n]

        # Vector from pt1 to pixel
        v1 = (pixel_pt[0] - pt1[0], pixel_pt[1] - pt1[1])

        # Vector from pt1 to pt2
        v2 = (pt2[0] - pt1[0], pt2[1] - pt1[1])

        # 2D cross product (z-component)
        cross_products[i] = v1[0] * v2[1] - v1[1] * v2[0]

    return cross_products
```

---

### Donate Method

```csharp
private void Donate(float[] fpWeights, float[] velocityWeights, PixelComputeBuffer buf)
```

**Purpose**: Convert facepoint weights to velocity weights by redistributing between adjacent faces.

**Algorithm**:

The "donation" process handles the fact that velocity is defined at face centers, while WSE is defined at cell vertices (facepoints). The method redistributes vertex weights to face weights.

```csharp
int nFaces = buf.Count;
float[] cwCanGive = buf.CWCanGive;
float[] ccwCanGive = buf.CCWCanGive;

// Step 1: Compute donation capacity for each facepoint
for (int i = 0; i < nFaces; i++)
{
    int prev = (i - 1 + nFaces) % nFaces;
    int next = (i + 1) % nFaces;

    float weight_i = fpWeights[i];
    float weight_prev = fpWeights[prev];
    float weight_next = fpWeights[next];

    float totalAdjacent = weight_prev + weight_next;

    if (totalAdjacent != 0f)
    {
        float ratio = weight_i / totalAdjacent;
        cwCanGive[i] = ratio * weight_prev;   // Can give to CW neighbor
        ccwCanGive[i] = ratio * weight_next;  // Can give to CCW neighbor
    }

    velocityWeights[i] = fpWeights[i];  // Initialize with facepoint weight
}

// Step 2: Perform donation between adjacent facepoints
for (int i = 0; i < nFaces; i++)
{
    int curr = i;
    int next = (i + 1) % nFaces;

    float ccwDonation = ccwCanGive[curr];  // Current wants to give CCW
    float cwDonation = cwCanGive[next];    // Next wants to give CW

    // Take minimum (both must agree to donate)
    float donation = Math.Min(ccwDonation, cwDonation);

    // Reduce facepoint weights
    velocityWeights[curr] -= donation;
    velocityWeights[next] -= donation;

    // Add to face velocity weight (index nFaces + i)
    velocityWeights[nFaces + i] = donation * 2f;
}
```

**Output Arrays**:

- `fpWeights[0..n-1]`: Weights for facepoints (used for WSE)
- `velocityWeights[0..n-1]`: Weights for facepoints (for velocity)
- `velocityWeights[n..2n-1]`: Weights for face centers (for velocity)

**Python Implementation**:

```python
def donate_weights(fp_weights):
    """
    Convert facepoint weights to velocity weights via donation.

    Parameters
    ----------
    fp_weights : ndarray
        Facepoint weights (size n)

    Returns
    -------
    velocity_weights : ndarray
        Velocity weights (size 2n)
        First n elements: facepoint contributions
        Last n elements: face center contributions
    """
    n = len(fp_weights)
    velocity_weights = np.zeros(2 * n)

    # Compute donation capacity
    cw_can_give = np.zeros(n)
    ccw_can_give = np.zeros(n)

    for i in range(n):
        prev = (i - 1) % n
        next = (i + 1) % n

        weight_i = fp_weights[i]
        weight_prev = fp_weights[prev]
        weight_next = fp_weights[next]

        total_adj = weight_prev + weight_next

        if total_adj > 0:
            ratio = weight_i / total_adj
            cw_can_give[i] = ratio * weight_prev
            ccw_can_give[i] = ratio * weight_next

        velocity_weights[i] = fp_weights[i]

    # Perform donation
    for i in range(n):
        curr = i
        next = (i + 1) % n

        donation = min(ccw_can_give[curr], cw_can_give[next])

        velocity_weights[curr] -= donation
        velocity_weights[next] -= donation
        velocity_weights[n + i] = donation * 2.0

    return velocity_weights
```

---

## Face WSE Computation

### Overview

For **sloped interpolation** (cell corners mode), RASMapper computes WSE at cell vertices by first computing WSE at face centers, then using planar regression.

**Note**: The actual face WSE computation is NOT in `RASGeometryMapPoints.cs`. It is implemented in the results processing classes (`HdfResultsMesh`, `HdfResultsPlan`). This class only handles the **interpolation weights**.

### Expected Workflow

Based on ras-commander's implementation findings:

1. **Extract Cell WSE** from HDF results (max, min, or timestep)
2. **Compute Face WSE** using hydraulic connectivity rules:
   - Use terrain gradients
   - Handle dry cells
   - Apply backfill/levee logic
3. **Compute Vertex WSE** via planar regression through adjacent face WSE values
4. **Interpolate Pixel WSE** using Ben's Weights on vertex values

---

## Interpolation Methods

### BensWeightsSquareCellREUSE

```csharp
private List<SlopingCellPoint> BensWeightsSquareCellREUSE(
    MeshFV2D mesh, int cIdx, RasterM backgroundRaster,
    Func<int, int> borrowReusablePixels, BitArray mask)
```

**Purpose**: Optimized Ben's Weights computation for square cells using bilinear interpolation.

**Algorithm**:

For square cells (4 facepoints in orthogonal grid), use fast bilinear interpolation instead of full Ben's Weights:

```csharp
// Step 1: Identify quadrant corners
Point2Double cellCenter = mesh.Cell(cIdx).Point;
List<Point2Double> facepoints = mesh.CellFacePoints(cIdx)
    .Select(fpIdx => mesh.FacePoints[fpIdx].Point).ToList();

// Determine which facepoint is in which quadrant
int[] quadrants = new int[4];  // [SW, NW, NE, SE]

for (int i = 0; i < 4; i++)
{
    Point2Double fp = facepoints[i];

    if (fp.X <= cellCenter.X && fp.Y <= cellCenter.Y)
        quadrants[0] = i;  // SW
    else if (fp.X <= cellCenter.X && fp.Y >= cellCenter.Y)
        quadrants[1] = i;  // NW
    else if (fp.X >= cellCenter.X && fp.Y >= cellCenter.Y)
        quadrants[2] = i;  // NE
    else
        quadrants[3] = i;  // SE
}

// Step 2: Compute bounding box in raster coords
double minX = Math.Min(facepoints[0].X, facepoints[2].X);
double maxX = Math.Max(facepoints[0].X, facepoints[2].X);
double minY = Math.Min(facepoints[0].Y, facepoints[2].Y);
double maxY = Math.Max(facepoints[0].Y, facepoints[2].Y);

double cellWidth = maxX - minX;
double cellHeight = maxY - minY;

// Step 3: Rasterize bounding box
int leftIdx, rightIdx, topIdx, botIdx;
new RasterizeRectangle(backgroundRaster).ComputeCells(
    facepoints, ref leftIdx, ref rightIdx, ref topIdx, ref botIdx);

// Step 4: Pre-compute normalized X fractions for each column
double[] xFractions = new double[rightIdx - leftIdx + 1];
double[] xFractionsInv = new double[rightIdx - leftIdx + 1];

for (int col = leftIdx; col <= rightIdx; col++)
{
    double pixelCenterX = backgroundRaster.CellCenterX(col);
    double xFrac = (pixelCenterX - minX) / cellWidth;

    // Clamp to (epsilon, 1-epsilon) to avoid edge singularities
    if (xFrac <= 0.0) xFrac = 1e-5;
    if (xFrac >= 1.0) xFrac = 0.99999;

    xFractions[col - leftIdx] = xFrac;
    xFractionsInv[col - leftIdx] = 1.0 - xFrac;
}

// Step 5: Loop over pixels and compute bilinear weights
for (int row = topIdx; row <= botIdx; row++)
{
    double pixelCenterY = backgroundRaster.CellCenterY(row);
    double yFrac = (pixelCenterY - minY) / cellHeight;

    if (yFrac <= 0.0) yFrac = 1e-5;
    if (yFrac >= 1.0) yFrac = 0.99999;

    double yFracInv = 1.0 - yFrac;

    for (int col = leftIdx; col <= rightIdx; col++)
    {
        int pixelIdx = backgroundRaster.CellIndex(row, col);

        if (mask[pixelIdx])
            continue;  // Already mapped

        double xFrac = xFractions[col - leftIdx];
        double xFracInv = xFractionsInv[col - leftIdx];

        // Bilinear weights
        float[] weights = new float[4];
        weights[quadrants[0]] = (float)(xFracInv * yFracInv);  // SW
        weights[quadrants[1]] = (float)(xFracInv * yFrac);     // NW
        weights[quadrants[2]] = (float)(xFrac * yFrac);        // NE
        weights[quadrants[3]] = (float)(xFrac * yFracInv);     // SE

        // Compute velocity weights via Donate()
        float[] velocityWeights = new float[8];
        Donate(weights, velocityWeights, buf);

        // Store result
        slopingCellPoint = new SlopingCellPoint(pixelIdx, weights, velocityWeights);
        result.Add(slopingCellPoint);

        mask[pixelIdx] = true;
    }
}
```

**Performance**:
- **Much faster** than full Ben's Weights (no cross product computation)
- Only valid for perfectly orthogonal square cells
- RASMapper auto-detects square cells via `mesh.SquareCells[cIdx]`

**Python Implementation**:

```python
def bens_weights_square_cell(cell_facepoints, raster, mask):
    """
    Fast bilinear interpolation for square mesh cells.

    Parameters
    ----------
    cell_facepoints : list of (x, y)
        4 facepoint coordinates
    raster : RasterM object
        Target raster grid
    mask : ndarray (bool)
        Pixel assignment mask

    Returns
    -------
    pixel_weights : list of SlopingCellPoint
        Weights for each pixel in cell
    """
    # Compute bounding box
    xs = [fp[0] for fp in cell_facepoints]
    ys = [fp[1] for fp in cell_facepoints]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    width = max_x - min_x
    height = max_y - min_y

    # Get raster indices
    left_idx, right_idx = raster.col_indices(min_x, max_x)
    top_idx, bot_idx = raster.row_indices(min_y, max_y)

    # Identify quadrant corners
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    quadrants = [None] * 4  # [SW, NW, NE, SE]
    for i, (x, y) in enumerate(cell_facepoints):
        if x <= center_x and y <= center_y:
            quadrants[0] = i
        elif x <= center_x and y >= center_y:
            quadrants[1] = i
        elif x >= center_x and y >= center_y:
            quadrants[2] = i
        else:
            quadrants[3] = i

    # Pre-compute x fractions
    x_fracs = []
    for col in range(left_idx, right_idx + 1):
        pixel_x = raster.cell_center_x(col)
        x_frac = (pixel_x - min_x) / width
        x_frac = np.clip(x_frac, 1e-5, 0.99999)
        x_fracs.append(x_frac)

    # Compute weights
    pixel_weights = []

    for row in range(top_idx, bot_idx + 1):
        pixel_y = raster.cell_center_y(row)
        y_frac = (pixel_y - min_y) / height
        y_frac = np.clip(y_frac, 1e-5, 0.99999)

        for col_offset, col in enumerate(range(left_idx, right_idx + 1)):
            pixel_idx = raster.cell_index(row, col)

            if mask[pixel_idx]:
                continue

            x_frac = x_fracs[col_offset]

            # Bilinear weights
            weights = np.zeros(4)
            weights[quadrants[0]] = (1 - x_frac) * (1 - y_frac)  # SW
            weights[quadrants[1]] = (1 - x_frac) * y_frac        # NW
            weights[quadrants[2]] = x_frac * y_frac              # NE
            weights[quadrants[3]] = x_frac * (1 - y_frac)        # SE

            # Velocity weights via donation
            velocity_weights = donate_weights(weights)

            pixel_weights.append({
                'index': pixel_idx,
                'fp_weights': weights,
                'velocity_weights': velocity_weights
            })

            mask[pixel_idx] = True

    return pixel_weights
```

---

### ConvertFlatToSloped

```csharp
private List<SlopingCellMap> ConvertFlatToSloped(MeshFV2D mesh, IPoints ipts,
                                                  List<FlatCellMap> flatVals)
```

**Purpose**: Convert flat (horizontal) cell mappings to sloped mappings by computing Ben's Weights.

**Algorithm**:

```csharp
List<SlopingCellMap> result = new List<SlopingCellMap>();
float areaTolerance = (float)mesh.AreaTolerance;

foreach (FlatCellMap flatCell in flatVals)
{
    List<SlopingCellPoint> slopedPoints = new List<SlopingCellPoint>();

    int nFaces = mesh.Cell(flatCell.Index).Faces.Count;
    PixelComputeBuffer buf = new PixelComputeBuffer(nFaces);

    foreach (int pointIdx in flatCell.MapPoints)
    {
        float[] fpWeights = null;
        float[] velocityWeights = null;

        PointM point = ipts.PointM(pointIdx);

        BensWeights(point, mesh, flatCell.Index, areaTolerance,
                    buf, ref fpWeights, ref velocityWeights);

        slopedPoints.Add(new SlopingCellPoint(pointIdx, fpWeights, velocityWeights));
    }

    result.Add(new SlopingCellMap(flatCell.Index, slopedPoints));
}

return result;
```

---

## Rasterization Methods

### Rasterize2DFlowAreasWithSpatialIndex

```csharp
private void Rasterize2DFlowAreasWithSpatialIndex(RasterizePolygon rasterizePolygons,
                                                   BitArray mask)
```

**Purpose**: Rasterize all 2D flow areas onto the target raster, computing both flat and sloped cell mappings.

**Algorithm**:

```csharp
for each 2D flow area mesh:

    1. Get spatial index for mesh cells

    2. Query cells overlapping raster extent

    3. Separate into flat and sloped cells:
       - Flat cells: Square cells or cells where ReduceShallowToHorizontal applies
       - Sloped cells: All other cells

    4. For flat cells:
       - Use fast rectangle rasterization for square cells
       - Use polygon rasterization for non-square cells
       - Store pixel indices in FlatCellMap

    5. For sloped cells:
       - Check if cell can be reused from previous raster (_translatableCells)
       - If square cell: Use BensWeightsSquareCellREUSE (fast bilinear)
       - If non-square: Use RasterizePolygon + full BensWeights
       - Store pixel indices + weights in SlopingCellMap

    6. Compute unique faces and facepoints for optimization

    7. Add to _flatAreas and _slopingAreas lists
```

**Key Optimization**: Square cells use bilinear interpolation instead of Ben's Weights.

---

### RasterizeStorageAreas

```csharp
private void RasterizeStorageAreas(RasterizePolygon rasterizePolygons, BitArray mask)
```

**Purpose**: Rasterize storage area polygons onto the target raster.

**Algorithm**:

```csharp
for each storage area feature:

    if feature is Polygon and overlaps raster:

        1. Create RasterizePolygon utility

        2. Call ComputeCells(polygon, callback)
           - Callback adds pixel index to MappedSAs list

        3. Update mask to mark pixels as mapped
```

**Output**: Pixels mapped to storage areas are stored in `MappedSAs` list.

---

### RasterizeCrossSectionRegions

```csharp
private void RasterizeCrossSectionRegions(BitArray mask)
```

**Purpose**: Rasterize cross-section interpolation surfaces (XSIS) onto the target raster.

**Algorithm**:

```csharp
for each XSIS feature (in render order):

    1. Get normalized TIN (triangulated irregular network)

    2. For each triangle in TIN:

       a. Create RasterizeTriangle utility

       b. Call ComputeCellsZMandDirection(p1, p2, p3, callback)
          - Callback adds pixel index to MappedXSISs list
          - Stores Z (elevation) and M (distance) values

       c. Update mask
```

**Output**: Pixels mapped to XSIS are stored in `MappedXSISs` list with Z and M values.

---

### RasterizePipeNetworkWithSpatialIndex

```csharp
private void RasterizePipeNetworkWithSpatialIndex(RasterizePolygon rasterizePolygons)
```

**Purpose**: Rasterize 1D pipe network meshes onto the target raster.

**Algorithm**:

```csharp
for each pipe network mesh:

    1. Get spatial index for 1D mesh cells

    2. Query cells overlapping raster extent

    3. For each nearby cell:

       a. Get pipe polygon representation

       b. Rasterize polygon using RasterizePolygon

       c. For each pixel in cell:
          - Compute Sloping1DCellInputs (USFace, DSFace, Fraction, NodeFraction)
          - Store in Sloping1DCellMap

    4. Add to _slopingAreas1DMesh list
```

**Output**: Pixels mapped to pipe networks stored in `_slopingAreas1DMesh` list.

---

## Python Implementation Guide

### Complete Workflow for Sloped Interpolation

```python
import numpy as np
from shapely.geometry import Point, Polygon

class BensWeightsInterpolator:
    """
    Python implementation of RASMapper's Ben's Weights interpolation.
    """

    def __init__(self, mesh_cells, mesh_facepoints):
        """
        Parameters
        ----------
        mesh_cells : dict
            cell_id -> list of facepoint indices (CCW order)
        mesh_facepoints : dict
            facepoint_id -> (x, y) coordinates
        """
        self.mesh_cells = mesh_cells
        self.mesh_facepoints = mesh_facepoints

    def compute_bens_weights(self, pixel_pt, cell_id):
        """
        Compute Ben's Weights for a pixel within a cell.

        Parameters
        ----------
        pixel_pt : (x, y) tuple
            Pixel center coordinates
        cell_id : int
            Mesh cell ID

        Returns
        -------
        fp_weights : ndarray
            Facepoint weights (size n)
        velocity_weights : ndarray
            Velocity weights (size 2n)
        """
        # Get cell facepoints
        fp_indices = self.mesh_cells[cell_id]
        fp_coords = [self.mesh_facepoints[idx] for idx in fp_indices]
        n = len(fp_coords)

        # Step 1: Compute cross products
        cross_products = self._get_cross_products(pixel_pt, fp_coords)

        # Step 2: Add epsilon to avoid zero products
        cross_products = np.where(
            np.abs(cross_products) < 1e-10,
            1e-5,
            cross_products
        )

        # Step 3: Compute weight for each facepoint
        weights = np.zeros(n)

        for j in range(n):
            curr = j
            prev = (j - 1) % n

            # Product of all cross products EXCEPT adjacent faces
            product = 1.0
            for k in range(n):
                if k != curr and k != prev:
                    product *= cross_products[k]

            # Get triangle cross product
            p1 = fp_coords[prev]
            p2 = fp_coords[curr]
            p3 = fp_coords[(curr + 1) % n]

            tri_cross = self._triangle_cross_product(p1, p2, p3)

            weights[j] = product * tri_cross

        # Step 4: Normalize
        sum_weights = np.sum(weights)
        if sum_weights != 0:
            weights /= sum_weights

        # Step 5: Handle negative weights
        if np.any(weights < 0):
            weights = np.maximum(weights, 0)
            sum_weights = np.sum(weights)
            if sum_weights > 0:
                weights /= sum_weights

        # Step 6: Compute velocity weights
        velocity_weights = self._donate_weights(weights)

        return weights, velocity_weights

    def _get_cross_products(self, pixel_pt, fp_coords):
        """Compute cross products from pixel to each face."""
        n = len(fp_coords)
        cross_products = np.zeros(n)

        for i in range(n):
            pt1 = fp_coords[i]
            pt2 = fp_coords[(i + 1) % n]

            # Vector from pt1 to pixel
            v1 = (pixel_pt[0] - pt1[0], pixel_pt[1] - pt1[1])

            # Vector from pt1 to pt2
            v2 = (pt2[0] - pt1[0], pt2[1] - pt1[1])

            # 2D cross product
            cross_products[i] = v1[0] * v2[1] - v1[1] * v2[0]

        return cross_products

    def _triangle_cross_product(self, p1, p2, p3):
        """Compute cross product of triangle (p2-p1) × (p3-p1)."""
        v1 = (p2[0] - p1[0], p2[1] - p1[1])
        v2 = (p3[0] - p1[0], p3[1] - p1[1])
        return v1[0] * v2[1] - v1[1] * v2[0]

    def _donate_weights(self, fp_weights):
        """Convert facepoint weights to velocity weights."""
        n = len(fp_weights)
        velocity_weights = np.zeros(2 * n)

        # Compute donation capacity
        cw_can_give = np.zeros(n)
        ccw_can_give = np.zeros(n)

        for i in range(n):
            prev = (i - 1) % n
            next = (i + 1) % n

            total_adj = fp_weights[prev] + fp_weights[next]

            if total_adj > 0:
                ratio = fp_weights[i] / total_adj
                cw_can_give[i] = ratio * fp_weights[prev]
                ccw_can_give[i] = ratio * fp_weights[next]

            velocity_weights[i] = fp_weights[i]

        # Perform donation
        for i in range(n):
            curr = i
            next = (i + 1) % n

            donation = min(ccw_can_give[curr], cw_can_give[next])

            velocity_weights[curr] -= donation
            velocity_weights[next] -= donation
            velocity_weights[n + i] = donation * 2.0

        return velocity_weights

    def rasterize_cell(self, cell_id, raster, mask, is_square=False):
        """
        Rasterize a single mesh cell.

        Parameters
        ----------
        cell_id : int
            Mesh cell ID
        raster : RasterM object
            Target raster grid
        mask : ndarray (bool)
            Pixel assignment mask
        is_square : bool
            Whether cell is square (use bilinear optimization)

        Returns
        -------
        pixel_weights : list of dicts
            Each dict: {'index': int, 'fp_weights': ndarray, 'velocity_weights': ndarray}
        """
        fp_indices = self.mesh_cells[cell_id]
        fp_coords = [self.mesh_facepoints[idx] for idx in fp_indices]

        # Create cell polygon
        cell_polygon = Polygon(fp_coords)

        # Get bounding box in raster coords
        minx, miny, maxx, maxy = cell_polygon.bounds

        left_col = raster.col_from_x(minx)
        right_col = raster.col_from_x(maxx)
        top_row = raster.row_from_y(maxy)
        bot_row = raster.row_from_y(miny)

        pixel_weights = []

        if is_square and len(fp_coords) == 4:
            # Use fast bilinear interpolation
            pixel_weights = self._rasterize_square_cell(
                cell_id, fp_coords, raster, mask,
                left_col, right_col, top_row, bot_row
            )
        else:
            # Use full Ben's Weights
            for row in range(top_row, bot_row + 1):
                for col in range(left_col, right_col + 1):
                    pixel_idx = raster.cell_index(row, col)

                    if mask[pixel_idx]:
                        continue

                    pixel_x, pixel_y = raster.cell_center(row, col)
                    pixel_pt = Point(pixel_x, pixel_y)

                    if cell_polygon.contains(pixel_pt):
                        fp_weights, vel_weights = self.compute_bens_weights(
                            (pixel_x, pixel_y), cell_id
                        )

                        pixel_weights.append({
                            'index': pixel_idx,
                            'fp_weights': fp_weights,
                            'velocity_weights': vel_weights
                        })

                        mask[pixel_idx] = True

        return pixel_weights

    def _rasterize_square_cell(self, cell_id, fp_coords, raster, mask,
                                left_col, right_col, top_row, bot_row):
        """Fast bilinear interpolation for square cells."""
        # Compute bounding box
        xs = [p[0] for p in fp_coords]
        ys = [p[1] for p in fp_coords]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        width = max_x - min_x
        height = max_y - min_y

        # Identify quadrant corners
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        quadrants = [None] * 4
        for i, (x, y) in enumerate(fp_coords):
            if x <= center_x and y <= center_y:
                quadrants[0] = i  # SW
            elif x <= center_x and y >= center_y:
                quadrants[1] = i  # NW
            elif x >= center_x and y >= center_y:
                quadrants[2] = i  # NE
            else:
                quadrants[3] = i  # SE

        pixel_weights = []

        for row in range(top_row, bot_row + 1):
            pixel_y = raster.cell_center_y(row)
            y_frac = np.clip((pixel_y - min_y) / height, 1e-5, 0.99999)

            for col in range(left_col, right_col + 1):
                pixel_idx = raster.cell_index(row, col)

                if mask[pixel_idx]:
                    continue

                pixel_x = raster.cell_center_x(col)
                x_frac = np.clip((pixel_x - min_x) / width, 1e-5, 0.99999)

                # Bilinear weights
                fp_weights = np.zeros(4)
                fp_weights[quadrants[0]] = (1 - x_frac) * (1 - y_frac)
                fp_weights[quadrants[1]] = (1 - x_frac) * y_frac
                fp_weights[quadrants[2]] = x_frac * y_frac
                fp_weights[quadrants[3]] = x_frac * (1 - y_frac)

                vel_weights = self._donate_weights(fp_weights)

                pixel_weights.append({
                    'index': pixel_idx,
                    'fp_weights': fp_weights,
                    'velocity_weights': vel_weights
                })

                mask[pixel_idx] = True

        return pixel_weights


# Example usage
def main():
    # Define a simple triangular mesh cell
    mesh_cells = {
        0: [0, 1, 2]  # Cell 0 has facepoints 0, 1, 2
    }

    mesh_facepoints = {
        0: (0.0, 0.0),
        1: (10.0, 0.0),
        2: (5.0, 8.66)  # Equilateral triangle
    }

    interpolator = BensWeightsInterpolator(mesh_cells, mesh_facepoints)

    # Test point inside triangle
    test_point = (5.0, 3.0)

    fp_weights, vel_weights = interpolator.compute_bens_weights(test_point, 0)

    print("Facepoint weights:", fp_weights)
    print("Velocity weights:", vel_weights)
    print("Sum of FP weights:", np.sum(fp_weights))
```

---

## Summary

### Key Takeaways

1. **RASGeometryMapPoints** is the core class for mapping pixels/points to HEC-RAS geometry
2. **Ben's Weights** (generalized barycentric coordinates) is used for arbitrary polygon interpolation
3. **Square cells** use optimized bilinear interpolation instead of Ben's Weights
4. **Velocity weights** are computed via the "Donate" process to redistribute vertex weights to face centers
5. **Rasterization** uses spatial indexing and polygon rasterization utilities for efficiency
6. **Face WSE computation** is handled in separate classes (not in RASGeometryMapPoints)

### Python Implementation Checklist

- [x] Ben's Weights core algorithm
- [x] Cross product computation
- [x] Weight donation for velocity
- [x] Bilinear interpolation for square cells
- [x] Cell rasterization logic
- [ ] Spatial indexing (use rtree or similar)
- [ ] Polygon rasterization (use rasterio or custom bresenham)
- [ ] Face WSE computation (implement hydraulic connectivity rules)
- [ ] Vertex WSE computation (implement planar regression)

### Related Documentation

- **Face WSE Computation**: See `HdfResultsMesh` class documentation
- **Planar Regression**: See `PlanarRegressionZ` class documentation
- **Render Modes**: See `RASMapper` settings documentation

---

**Document Version**: 1.0
**Date**: 2025-12-09
**Author**: Claude Code (ras-commander project)
