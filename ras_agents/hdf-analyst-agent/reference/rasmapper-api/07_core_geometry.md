# RASMapper Core Geometry Classes

**Purpose:** Document the fundamental spatial geometry types used throughout RASMapper for representing points, shapes, TINs, and performing geometric operations.

**Date:** 2025-12-09
**Source:** Decompiled RasMapperLib.dll

---

## Table of Contents

1. [Overview](#overview)
2. [Point Types](#point-types)
3. [Shape Classes](#shape-classes)
4. [Triangulated Irregular Networks (TINs)](#triangulated-irregular-networks-tins)
5. [Barycentric Coordinates](#barycentric-coordinates)
6. [Rasterization](#rasterization)
7. [Plane Representation](#plane-representation)
8. [Python Implementation Notes](#python-implementation-notes)

---

## Overview

RASMapper uses a hierarchy of geometry classes to represent spatial data:

- **Point Types**: Various representations optimized for different use cases (float vs double, with/without Z/M)
- **Shape Classes**: Polygons, polylines, triangles, etc.
- **TIN Structures**: Delaunay triangulation for surface interpolation
- **Rasterization**: Converting vector geometry to raster grids
- **Planes**: Mathematical surface representation for interpolation

**Key Design Principles:**
- Lightweight structs for performance-critical operations
- Separate classes for mutable vs immutable features
- Z and M values are optional (NaN when absent)
- Extensive use of operator overloading for geometric calculations

---

## Point Types

### 1. PointM (Primary Point Type)

**File:** `PointM.cs`
**Type:** `struct` (value type, 32 bytes)
**Purpose:** Main point representation with optional Z (elevation) and M (measure) values

```csharp
public struct PointM
{
    public double X;    // Easting/Longitude
    public double Y;    // Northing/Latitude
    public double Z;    // Elevation (NaN if not present)
    public double M;    // Measure/attribute (NaN if not present)
}
```

**Key Features:**
- **Operator Overloading:** `+`, `-`, `*` for vector arithmetic (when `EnableOperators = true`)
- **Null Points:** `NullPoint()` returns `PointM(NaN, NaN)`
- **Distance Calculations:** `DistanceTo()`, `DistanceZTo()` (3D distance)
- **Interpolation:** `AtFractionBetween()`, `MidPoint()`
- **Validation:** `IsDefined()`, `IsNull()`, `HasZ()`, `HasM()`

**Important Methods:**
```csharp
// Distance between points (2D)
double DistanceTo(PointM other);

// Interpolate between two points
PointM AtFractionBetween(PointM ptB, double t);  // t ∈ [0, 1]

// Unit vector from this point to origin
PointM UnitVector();

// Translate by vector
PointM Translate(double deltaX, double deltaY);
```

**Python Equivalent:**
```python
# NumPy array: shape (4,) = [x, y, z, m]
point = np.array([x, y, z, m], dtype=np.float64)

# Or use dataclass
from dataclasses import dataclass
@dataclass
class PointM:
    x: float
    y: float
    z: float = np.nan
    m: float = np.nan
```

---

### 2. Point2D (Float Precision)

**File:** `Point2D.cs`
**Type:** `struct` (8 bytes)
**Purpose:** Lightweight 2D point with float precision for graphics

```csharp
public struct Point2D
{
    public float X;
    public float Y;
}
```

**Use Cases:**
- High-performance rasterization
- Graphics rendering where precision < 1e-6 is acceptable
- Memory-constrained operations

---

### 3. Point3D (Float Precision with Z)

**File:** `Point3D.cs`
**Type:** `struct` (12 bytes)

```csharp
public struct Point3D
{
    public float X;
    public float Y;
    public float Z;
}
```

**Special Methods:**
```csharp
// Midpoint between two 3D points
Point3D Mid(Point3D other);

// Interpolate point at specific Y value along line
Point3D PointAtY(Point3D other, float y);
```

---

### 4. Point2Double (High Precision 2D)

**File:** `Point2Double.cs`
**Type:** `struct` (16 bytes)

```csharp
public struct Point2Double : IGraphic
{
    public double X;
    public double Y;
}
```

**Purpose:** High-precision 2D operations without Z/M overhead

---

### 5. Point (Feature Class)

**File:** `Point.cs`
**Type:** `class` (inherits from `Feature`)
**Purpose:** Full-featured point with rendering capabilities

```csharp
public class Point : Feature
{
    protected double _x, _y, _z, _m;

    public override bool UsesPointSymbol { get; } = true;
    public override bool UsesPen { get; } = false;
    public override bool UsesBrush { get; } = false;
}
```

**When to Use:**
- Feature layers in GIS operations
- Need editing capabilities (`GetMutableView()`)
- Require plotting and symbology

---

## Shape Classes

### 1. Polygon

**File:** `Polygon.cs` (27,702 lines - very complex)
**Inheritance:** `Polygon : Polyline : MultiPoint : Feature`

**Key Capabilities:**
- Multi-part polygons (holes and islands)
- Contains point testing
- Area and centroid calculations
- Intersection and union operations
- Buffering

**Critical for RASMapper:**
- Mesh cell polygons (2D areas)
- Perimeter boundaries
- Flood extent delineation

---

### 2. Polyline

**File:** `Polyline.cs` (41,131 lines - very complex)
**Inheritance:** `Polyline : MultiPoint : Feature`

**Key Features:**
- Multi-part polylines
- Segment-based operations
- Length and stationing
- Intersection testing
- Profile extraction

**Critical for RASMapper:**
- Cross section locations
- Breaklines in TINs
- River centerlines

---

### 3. Triangle

**File:** `Triangle.cs`

```csharp
public class Triangle : AffineFeature
{
    private Point _ptA, _ptB, _ptC;
    private SegmentM _segA, _segB, _segC;  // Three edges

    public double Width { get; }
    public double Height { get; }
}
```

**Key Methods:**
```csharp
// Check if point is inside triangle
bool Contains(PointM ptm);

// Get subsegments of polyline contained in triangle
List<Tuple<double, double>> GetContainedSubsegments(Polyline polyline);

// Convert to polygon
Polygon DiscretizeToPolygon();

// Interior angles (radians)
double PtAThetaRadians();
double PtBThetaRadians();
double PtCThetaRadians();
```

**Containment Test:** Uses barycentric coordinates (see `TriangleShape.Contains()`)

---

### 4. TriangleShape (Computational Geometry)

**File:** `TriangleShape.cs`
**Type:** `struct`

```csharp
public struct TriangleShape
{
    public PointM pt0, pt1, pt2;
    public double tolerance;
}
```

**Key Algorithm: Barycentric Containment**

```csharp
public bool Contains(double ptx, double pty,
                    ref double lambda0, ref double lambda1, ref double lambda2)
{
    InterpolationWeights(ptx, pty, ref lambda0, ref lambda1, ref lambda2);

    // Point is inside if all weights are in [0, 1]
    return lambda0 >= -tolerance && lambda1 >= -tolerance && lambda2 >= -tolerance
        && lambda0 <= 1 + tolerance && lambda1 <= 1 + tolerance && lambda2 <= 1 + tolerance;
}

public void InterpolationWeights(double px, double py,
                                 ref double lambda0, ref double lambda1, ref double lambda2)
{
    double dy12 = pt1.Y - pt2.Y;
    double dx02 = pt0.X - pt2.X;
    double dx21 = pt2.X - pt1.X;
    double dy02 = pt0.Y - pt2.Y;

    double denom = dy12 * dx02 + dx21 * dy02;

    double dx = px - pt2.X;
    double dy = py - pt2.Y;

    lambda0 = (dy12 * dx + dx21 * dy) / denom;
    lambda1 = (dx02 * dy - dy02 * dx) / denom;
    lambda2 = 1.0 - lambda0 - lambda1;
}
```

**Interpolation:**
```csharp
bool ComputeZ(double ptx, double pty, ref double z)
{
    if (Contains(ptx, pty, ref lambda0, ref lambda1, ref lambda2))
    {
        z = pt0.Z * lambda0 + pt1.Z * lambda1 + pt2.Z * lambda2;
        return true;
    }
    return false;
}
```

**Python Implementation:**
```python
def barycentric_weights(px, py, p0, p1, p2):
    """Compute barycentric coordinates for point (px, py) in triangle."""
    dy12 = p1[1] - p2[1]
    dx02 = p0[0] - p2[0]
    dx21 = p2[0] - p1[0]
    dy02 = p0[1] - p2[1]

    denom = dy12 * dx02 + dx21 * dy02

    dx = px - p2[0]
    dy = py - p2[1]

    lambda0 = (dy12 * dx + dx21 * dy) / denom
    lambda1 = (dx02 * dy - dy02 * dx) / denom
    lambda2 = 1.0 - lambda0 - lambda1

    return lambda0, lambda1, lambda2

def contains(px, py, p0, p1, p2, tol=1e-6):
    """Check if point is inside triangle."""
    l0, l1, l2 = barycentric_weights(px, py, p0, p1, p2)
    return (l0 >= -tol and l1 >= -tol and l2 >= -tol and
            l0 <= 1+tol and l1 <= 1+tol and l2 <= 1+tol)

def interpolate_z(px, py, p0, p1, p2):
    """Interpolate Z value at point using barycentric coordinates."""
    l0, l1, l2 = barycentric_weights(px, py, p0, p1, p2)
    if contains(px, py, p0, p1, p2):
        return l0 * p0[2] + l1 * p1[2] + l2 * p2[2]
    return np.nan
```

---

## Triangulated Irregular Networks (TINs)

### TINFactory (Abstract Base)

**File:** `TINFactory.cs`

**Key Method: Point-in-Triangle Search**

```csharp
public int FindTriangleContainingPoint(PointM point)
{
    static int t = 0;  // Last found triangle (spatial coherence)
    static double[] crossProd = new double[3];

    int iterations = 0;
    int prevT = -1;

    do {
        DevelopmentTriangle tri = _triangles[t];

        // Compute cross products for all three edges
        crossProd[0] = CrossProduct(_points[tri.p0], _points[tri.p1], point);
        crossProd[1] = CrossProduct(_points[tri.p1], _points[tri.p2], point);
        crossProd[2] = CrossProduct(_points[tri.p2], _points[tri.p0], point);

        int minIdx = Min3Index(crossProd[0], crossProd[1], crossProd[2]);

        // If all cross products >= 0, point is inside
        if (crossProd[minIdx] >= 0.0)
            return t;

        // Move to adjacent triangle across edge with most negative cross product
        int nextT = minIdx switch {
            0 => tri.at0,
            1 => tri.at1,
            _ => tri.at2
        };

        // Prevent infinite loops
        if (prevT == nextT)
            return t;

        prevT = t;
        t = nextT;
        iterations++;

    } while (t != -1 && iterations < _triangles.Count);

    return -1;
}

protected double CrossProduct(PointM a, PointM b, PointM c)
{
    // 2D cross product: (b - a) × (c - a)
    return (b.X - a.X) * (c.Y - a.Y) - (b.Y - a.Y) * (c.X - a.X);
}
```

**Algorithm Explanation:**
1. Start with last successful triangle (spatial coherence)
2. Compute cross products for all three edges
3. If all positive → point is inside
4. If any negative → move to adjacent triangle across that edge
5. Continue until inside or no more triangles

**Python Implementation:**
```python
def find_triangle_containing_point(point, triangles, points, start_tri=0):
    """
    Find triangle containing point using walking algorithm.

    Args:
        point: (x, y) tuple
        triangles: List of (p0, p1, p2, at0, at1, at2) tuples
        points: Array of shape (N, 2) with point coordinates
        start_tri: Starting triangle index

    Returns:
        Triangle index or -1 if not found
    """
    t = start_tri
    prev_t = -1
    iterations = 0
    max_iter = len(triangles)

    while t != -1 and iterations < max_iter:
        tri = triangles[t]
        p0, p1, p2 = points[tri[0]], points[tri[1]], points[tri[2]]

        # Compute cross products
        cp0 = cross_product_2d(p0, p1, point)
        cp1 = cross_product_2d(p1, p2, point)
        cp2 = cross_product_2d(p2, p0, point)

        # Find minimum cross product
        cps = [cp0, cp1, cp2]
        min_idx = np.argmin(cps)

        # Check if inside
        if cps[min_idx] >= 0:
            return t

        # Move to adjacent triangle
        next_t = tri[3 + min_idx]  # at0, at1, or at2

        if next_t == prev_t:
            return t  # Prevent oscillation

        prev_t = t
        t = next_t
        iterations += 1

    return -1

def cross_product_2d(a, b, c):
    """2D cross product: (b - a) × (c - a)"""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
```

---

### DelaunayTINFactory

**File:** `DelaunayTINFactory.cs`

**Delaunay Triangulation Algorithm:**

1. **Initialize:** Create super-octagon bounding the data
2. **Insert Points:** Incrementally add points using Bowyer-Watson algorithm
3. **Enforce Constraints:** Add breaklines and perimeter edges
4. **Remove Bad Triangles:** Delete triangles outside perimeter

**Key Data Structure:**
```csharp
protected PointMs _points;                          // All points
protected List<DevelopmentTriangle> _triangles;     // All triangles
protected Stack<int> _deletedTrianglesStack;        // Reuse deleted indices
```

**Bowyer-Watson Insertion:**
```csharp
protected bool DelaunayInsertPoint(PointM point, bool translatePoint)
{
    // 1. Find triangle containing point
    int t, p;
    FindTriangleAndPointIndexes(point, ref t, ref p);

    // 2. If point already exists, update Z/M
    if (p >= 0) {
        UpdatePointZM(p, point);
        return false;
    }

    // 3. Add new point
    p = _points.Count;
    _points.Add(point);

    // 4. Find all triangles whose circumcircle contains the point
    Stack<int> stack = new Stack<int>();
    stack.Push(t);

    while (stack.Count > 0) {
        t = stack.Pop();
        _deletedTrianglesStack.Push(t);
        _triangles[t].MarkDeleted();

        // Check adjacent triangles
        if (IsTriangleInsideInsertionHole(_triangles[t].at0, point))
            stack.Push(_triangles[t].at0);
        if (IsTriangleInsideInsertionHole(_triangles[t].at1, point))
            stack.Push(_triangles[t].at1);
        if (IsTriangleInsideInsertionHole(_triangles[t].at2, point))
            stack.Push(_triangles[t].at2);
    }

    // 5. Retriangulate insertion hole
    MakeInsertionHoleFromDeletedTrianglesAndFill(p);

    return true;
}
```

---

## Barycentric Coordinates

### BaryCentric Class

**File:** `BaryCentric.cs`
**Note:** Class is empty in decompiled source - implementation is in `TriangleShape`

**Concept:** Represent a point inside a triangle using three weights (λ₀, λ₁, λ₂) such that:

```
P = λ₀·P₀ + λ₁·P₁ + λ₂·P₂
where λ₀ + λ₁ + λ₂ = 1
```

**Properties:**
- Point is inside triangle if all λᵢ ∈ [0, 1]
- Point is on edge if one λᵢ = 0
- Point is at vertex if one λᵢ = 1 and others = 0
- Weights interpolate linearly across triangle

**Use Cases in RASMapper:**
- Point-in-triangle testing
- Interpolating Z values from triangle vertices
- Rasterizing triangles with smooth gradients

---

## Rasterization

### RasterizeTriangle

**File:** `RasterizeTriangle.cs`

**Primary Method: Scanline Rasterization**

```csharp
public void ComputeCellsZ(PointM p0, PointM p1, PointM p2, Action<int, float> fillCellAction)
{
    // 1. Check if triangle intersects raster bounds
    if (/* all points outside bounds */)
        return;

    // 2. Create plane through triangle for Z interpolation
    PlaneM plane = default(PlaneM);
    plane.SetCoeffientsPtPtPt(p0, p1, p2);
    double dZ_dX = plane.dZ_dX() * _raster.CellSize;

    // 3. Sort points by Y coordinate (bottom to top)
    PointM.Sort3PointsByY(ref p0, ref p1, ref p2);

    if (p0.Y == p2.Y)  // Degenerate triangle
        return;

    // 4. Compute row range
    int topRow = _raster.Row(p2.Y);
    int bottomRow = _raster.Row(p0.Y);

    // 5. Compute edge slopes (dX/dY)
    double slope02 = (p2.X - p0.X) / (p2.Y - p0.Y);  // Left edge
    double slope12 = (p2.X - p1.X) / (p2.Y - p1.Y);  // Right edge
    double slope01 = (p1.X - p0.X) / (p1.Y - p0.Y);  // Middle edge

    // 6. Scanline loop: for each row
    double y = _raster.CellCenterY(topRow);
    double xLeft = p2.X + slope02 * (y - p2.Y);
    double xRight = p2.X + slope12 * (y - p2.Y);
    double xMid = p1.X + slope01 * (y - p1.Y);

    for (int row = topRow; row <= bottomRow; row++) {
        int rowOffset = row * _raster.Cols;

        // Determine left and right X bounds
        double xMin = xLeft;
        double xMax = (y > p1.Y && !double.IsNaN(xMid)) ? xMid : xRight;

        if (xMin > xMax)
            Swap(ref xMin, ref xMax);

        // Compute column range
        int colMin = _raster.Col(xMin);
        int colMax = _raster.Col(xMax);

        // Clip to raster bounds
        colMin = Math.Max(0, colMin);
        colMax = Math.Min(_raster.Cols - 1, colMax);

        // Fill row: for each column
        double x = _raster.CellCenterX(colMin);
        double z = plane.Z(x, y);

        for (int col = colMin; col <= colMax; col++) {
            fillCellAction(rowOffset + col, (float)z);
            z += dZ_dX;  // Increment by constant per column
        }

        // Move to next row
        y -= _raster.CellSize;
        xLeft -= slope02 * _raster.CellSize;
        xRight -= slope12 * _raster.CellSize;
        xMid -= slope01 * _raster.CellSize;
    }
}
```

**Algorithm Summary:**
1. Sort triangle vertices by Y
2. Compute edge slopes in X/Y space
3. For each raster row:
   - Compute left and right X bounds
   - For each column in bounds:
     - Interpolate Z using plane equation

**Python Implementation:**
```python
def rasterize_triangle_z(p0, p1, p2, raster_extent, cell_size):
    """
    Rasterize triangle with Z interpolation.

    Args:
        p0, p1, p2: Points as (x, y, z) tuples
        raster_extent: (minx, maxx, miny, maxy)
        cell_size: Grid cell size

    Returns:
        Sparse dict {(row, col): z_value}
    """
    # Sort points by Y
    pts = sorted([p0, p1, p2], key=lambda p: p[1])
    p0, p1, p2 = pts

    if p0[1] == p2[1]:  # Degenerate
        return {}

    # Fit plane through triangle
    # Plane: z = ax + by + c
    # Solve: [p0, p1, p2] @ [a, b, c]ᵀ = [z0, z1, z2]ᵀ
    A = np.array([
        [p0[0], p0[1], 1],
        [p1[0], p1[1], 1],
        [p2[0], p2[1], 1]
    ])
    z_vals = np.array([p0[2], p1[2], p2[2]])
    a, b, c = np.linalg.solve(A, z_vals)

    dz_dx = a * cell_size

    # Edge slopes
    slope_02 = (p2[0] - p0[0]) / (p2[1] - p0[1])
    slope_12 = (p2[0] - p1[0]) / (p2[1] - p1[1])
    slope_01 = (p1[0] - p0[0]) / (p1[1] - p0[1])

    # Row range
    minx, maxx, miny, maxy = raster_extent
    rows = int((maxy - miny) / cell_size)
    cols = int((maxx - minx) / cell_size)

    def row_from_y(y):
        return int((maxy - y) / cell_size)

    def col_from_x(x):
        return int((x - minx) / cell_size)

    def cell_center_y(row):
        return maxy - (row + 0.5) * cell_size

    def cell_center_x(col):
        return minx + (col + 0.5) * cell_size

    top_row = row_from_y(p2[1])
    bottom_row = row_from_y(p0[1])

    cells = {}

    # Scanline loop
    y = cell_center_y(top_row)
    x_left = p2[0] + slope_02 * (y - p2[1])
    x_right = p2[0] + slope_12 * (y - p2[1])
    x_mid = p1[0] + slope_01 * (y - p1[1])

    for row in range(top_row, bottom_row + 1):
        # Determine bounds
        x_min = x_left
        x_max = x_mid if y > p1[1] else x_right

        if x_min > x_max:
            x_min, x_max = x_max, x_min

        col_min = max(0, col_from_x(x_min))
        col_max = min(cols - 1, col_from_x(x_max))

        # Fill row
        x = cell_center_x(col_min)
        z = a * x + b * y + c

        for col in range(col_min, col_max + 1):
            cells[(row, col)] = z
            z += dz_dx

        # Next row
        y -= cell_size
        x_left -= slope_02 * cell_size
        x_right -= slope_12 * cell_size
        x_mid -= slope_01 * cell_size

    return cells
```

---

### RasterizeTriangles (Optimized Version)

**File:** `RasterizeTriangles.cs`

**Key Difference:** Uses `PlaneM` struct for Z/M interpolation in single pass

```csharp
public void ComputeCells(PointM p0, PointM p1, PointM p2,
                        Action<int, float, float> fillCellAction)
{
    PlaneM plane = default(PlaneM);
    plane.SetCoeffientsPtPtPt(p0, p1, p2);

    double dZ_dX = plane.dZ_dX() * _raster.CellSize;
    double dM_dX = plane.dM_dX() * _raster.CellSize;

    // ... scanline loop ...

    for (int col = colMin; col <= colMax; col++) {
        fillCellAction(rowOffset + col, (float)z, (float)m);
        z += dZ_dX;
        m += dM_dX;
    }
}
```

**Performance:** ~2x faster than separate Z and M passes

---

### RasterizeSegment

**File:** `RasterizeSegment.cs`

**Bresenham-style Line Rasterization:**

```csharp
public void ComputeCells(SegmentM segment, Action<int, int> fillCellAction)
{
    // 1. Clip segment to raster bounds
    if (!segment.ClipToExtent(_raster))
        return;

    // 2. Convert endpoints to row/col
    int row0 = _raster.Row(segment.A.Y);
    int col0 = _raster.Col(segment.A.X);
    int row1 = _raster.Row(segment.B.Y);
    int col1 = _raster.Col(segment.B.X);

    // 3. Bresenham-style traversal
    int dCol = col1 - col0;
    int dRow = row1 - row0;

    double dx = segment.DeltaX();
    double dy = segment.DeltaY();

    // 4. Handle special cases
    if (dCol == 0 && dRow == 0) {
        fillCellAction(row0, col0);
        return;
    }

    if (dCol == 0) {  // Vertical line
        int rowStep = Math.Sign(dRow);
        for (int r = row0; r != row1; r += rowStep)
            fillCellAction(r, col0);
        return;
    }

    if (dRow == 0) {  // Horizontal line
        int colStep = Math.Sign(dCol);
        for (int c = col0; c != col1; c += colStep)
            fillCellAction(row0, c);
        return;
    }

    // 5. General case: walk along grid
    int currentCol = col0;
    int currentRow = row0;

    fillCellAction(currentRow, currentCol);

    while (currentCol != col1 || currentRow != row1) {
        // Compute Y coordinate of top/bottom edge crossing
        double tY = (_raster.CellMinY(currentRow) - segment.A.Y) / dy;

        // Compute X coordinate of left/right edge crossing
        double tX = (_raster.CellMaxX(currentCol) - segment.A.X) / dx;

        // Move to whichever edge is crossed first
        if (tY < tX && currentRow < row1) {
            currentRow++;
        } else {
            currentCol++;
        }

        fillCellAction(currentRow, currentCol);
    }
}
```

**Algorithm:** Walk through grid cells intersected by line segment

---

## Plane Representation

### PlaneM Struct

**File:** `PlaneM.cs`

**Purpose:** Represent a plane in 3D space for Z and M interpolation

```csharp
public struct PlaneM
{
    // Plane equation: Ax + By + Cz + D = 0
    public double A, B, C, D;

    // M plane equation: Ex + Fy + Gm + H = 0
    public double E, F, G, H;
}
```

**Plane Fitting:**

```csharp
public void SetCoeffientsPtPtPt(PointM pt0, PointM pt1, PointM pt2)
{
    PointM delta01 = pt0.Delta(pt1);
    PointM delta02 = pt0.Delta(pt2);

    // Normal vector = delta01 × delta02
    A = delta01.Y * delta02.Z - delta01.Z * delta02.Y;
    B = delta01.Z * delta02.X - delta01.X * delta02.Z;
    C = delta01.X * delta02.Y - delta01.Y * delta02.X;

    // D from point on plane
    D = -A * pt0.X - B * pt0.Y - C * pt0.Z;

    // M plane coefficients (if M exists)
    if (!double.IsNaN(pt0.M)) {
        E = delta01.Y * delta02.M - delta01.M * delta02.Y;
        F = delta01.M * delta02.X - delta01.X * delta02.M;
        G = C;  // Reuse C
        H = -E * pt0.X - F * pt0.Y - G * pt0.M;
    }
}
```

**Z Interpolation:**

```csharp
public double Z(double x, double y)
{
    if (C == 0.0)
        return 0.0;

    // Solve for z: Ax + By + Cz + D = 0
    return (-D - A * x - B * y) / C;
}

public double dZ_dX()
{
    return -A / C;  // Partial derivative ∂z/∂x
}
```

**Python Implementation:**

```python
class PlaneM:
    """Plane representation for Z and M interpolation."""

    def __init__(self, p0, p1, p2):
        """
        Fit plane through three points.

        Args:
            p0, p1, p2: Points as (x, y, z, m) tuples
        """
        # Deltas
        d01 = np.array(p1) - np.array(p0)
        d02 = np.array(p2) - np.array(p0)

        # Normal vector (cross product)
        self.A = d01[1] * d02[2] - d01[2] * d02[1]
        self.B = d01[2] * d02[0] - d01[0] * d02[2]
        self.C = d01[0] * d02[1] - d01[1] * d02[0]

        # D coefficient
        self.D = -self.A * p0[0] - self.B * p0[1] - self.C * p0[2]

        # M plane (if M exists)
        if len(p0) > 3 and not np.isnan(p0[3]):
            self.E = d01[1] * d02[3] - d01[3] * d02[1]
            self.F = d01[3] * d02[0] - d01[0] * d02[3]
            self.G = self.C
            self.H = -self.E * p0[0] - self.F * p0[1] - self.G * p0[3]
        else:
            self.E = self.F = self.G = self.H = 0.0

    def z(self, x, y):
        """Interpolate Z at (x, y)."""
        if self.C == 0:
            return 0.0
        return (-self.D - self.A * x - self.B * y) / self.C

    def m(self, x, y):
        """Interpolate M at (x, y)."""
        if self.G == 0:
            return 0.0
        return (-self.H - self.E * x - self.F * y) / self.G

    def dz_dx(self):
        """Partial derivative ∂z/∂x."""
        return -self.A / self.C if self.C != 0 else 0.0

    def dm_dx(self):
        """Partial derivative ∂m/∂x."""
        return -self.E / self.G if self.G != 0 else 0.0
```

**Use in Rasterization:**

```python
# Fit plane
plane = PlaneM(p0, p1, p2)

# Precompute X-direction gradients
dz_dx = plane.dz_dx() * cell_size
dm_dx = plane.dm_dx() * cell_size

# In scanline loop
z = plane.z(x_start, y)
m = plane.m(x_start, y)

for col in range(col_min, col_max + 1):
    raster[row, col] = (z, m)
    z += dz_dx  # Constant increment per column
    m += dm_dx
```

**Efficiency:** Computing gradients once and incrementing is much faster than calling `plane.z(x, y)` for every pixel.

---

## Python Implementation Notes

### Recommended Libraries

```python
import numpy as np
import scipy.spatial  # Delaunay triangulation
import matplotlib.tri   # Triangulation utilities
from shapely.geometry import Point, Polygon, LineString
import rasterio
```

### Key NumPy Patterns

**Point Arrays:**
```python
# Shape: (N, 4) = [x, y, z, m]
points = np.array([[x0, y0, z0, m0],
                   [x1, y1, z1, m1],
                   ...], dtype=np.float64)
```

**Triangle Arrays:**
```python
# Shape: (M, 3) = indices into points array
triangles = np.array([[p0, p1, p2],
                      [p3, p4, p5],
                      ...], dtype=np.int32)
```

**Barycentric Interpolation (Vectorized):**
```python
def barycentric_interpolate_vectorized(px, py, triangles, points):
    """
    Interpolate Z at multiple points using barycentric coordinates.

    Args:
        px, py: Arrays of query point coordinates
        triangles: (M, 3) array of triangle vertex indices
        points: (N, 4) array of point coordinates [x, y, z, m]

    Returns:
        z_values: Array of interpolated Z values
    """
    # Get triangle vertices
    p0 = points[triangles[:, 0]]  # (M, 4)
    p1 = points[triangles[:, 1]]
    p2 = points[triangles[:, 2]]

    # Compute barycentric weights for all triangles
    dy12 = p1[:, 1] - p2[:, 1]
    dx02 = p0[:, 0] - p2[:, 0]
    dx21 = p2[:, 0] - p1[:, 0]
    dy02 = p0[:, 1] - p2[:, 1]

    denom = dy12 * dx02 + dx21 * dy02

    # For each query point
    z_values = np.full_like(px, np.nan)

    for i, (x, y) in enumerate(zip(px, py)):
        dx = x - p2[:, 0]
        dy = y - p2[:, 1]

        lambda0 = (dy12 * dx + dx21 * dy) / denom
        lambda1 = (dx02 * dy - dy02 * dx) / denom
        lambda2 = 1.0 - lambda0 - lambda1

        # Find first triangle containing point
        mask = ((lambda0 >= 0) & (lambda1 >= 0) & (lambda2 >= 0) &
                (lambda0 <= 1) & (lambda1 <= 1) & (lambda2 <= 1))

        if np.any(mask):
            tri_idx = np.where(mask)[0][0]
            z_values[i] = (lambda0[tri_idx] * p0[tri_idx, 2] +
                          lambda1[tri_idx] * p1[tri_idx, 2] +
                          lambda2[tri_idx] * p2[tri_idx, 2])

    return z_values
```

**Rasterization with NumPy:**
```python
def rasterize_triangles_numpy(triangles, points, extent, cell_size):
    """
    Rasterize triangulated surface to regular grid.

    Args:
        triangles: (M, 3) array of vertex indices
        points: (N, 4) array of [x, y, z, m]
        extent: (minx, maxx, miny, maxy)
        cell_size: Grid resolution

    Returns:
        z_grid: 2D array of Z values
    """
    minx, maxx, miny, maxy = extent
    rows = int((maxy - miny) / cell_size)
    cols = int((maxx - minx) / cell_size)

    # Initialize grid
    z_grid = np.full((rows, cols), np.nan, dtype=np.float32)

    # Create grid of cell centers
    x_coords = np.linspace(minx + cell_size/2, maxx - cell_size/2, cols)
    y_coords = np.linspace(maxy - cell_size/2, miny + cell_size/2, rows)

    # For each triangle
    for tri_idx in range(len(triangles)):
        p0, p1, p2 = points[triangles[tri_idx]]

        # Compute bounding box
        xmin = max(minx, min(p0[0], p1[0], p2[0]))
        xmax = min(maxx, max(p0[0], p1[0], p2[0]))
        ymin = max(miny, min(p0[1], p1[1], p2[1]))
        ymax = min(maxy, max(p0[1], p1[1], p2[1]))

        # Find affected cells
        col_min = np.searchsorted(x_coords, xmin)
        col_max = np.searchsorted(x_coords, xmax)
        row_min = np.searchsorted(y_coords[::-1], ymax)
        row_max = np.searchsorted(y_coords[::-1], ymin)

        # Rasterize triangle into grid
        for row in range(row_min, row_max + 1):
            y = y_coords[row]
            for col in range(col_min, col_max + 1):
                x = x_coords[col]

                # Check if inside and interpolate
                l0, l1, l2 = barycentric_weights(x, y, p0, p1, p2)
                if (l0 >= 0 and l1 >= 0 and l2 >= 0 and
                    l0 <= 1 and l1 <= 1 and l2 <= 1):
                    z = l0 * p0[2] + l1 * p1[2] + l2 * p2[2]
                    if np.isnan(z_grid[row, col]):
                        z_grid[row, col] = z

    return z_grid
```

---

## Summary of Key Algorithms

| Algorithm | File | Purpose | Python Equivalent |
|-----------|------|---------|-------------------|
| **Barycentric Coordinates** | `TriangleShape.cs` | Point-in-triangle, interpolation | Manual or `matplotlib.tri` |
| **Point-in-Triangle Search** | `TINFactory.cs` | Find containing triangle | `Delaunay.find_simplex()` |
| **Delaunay Triangulation** | `DelaunayTINFactory.cs` | Create TIN | `scipy.spatial.Delaunay` |
| **Scanline Rasterization** | `RasterizeTriangle.cs` | Triangle → raster | Custom or `rasterio.features` |
| **Bresenham Line** | `RasterizeSegment.cs` | Line → raster cells | `skimage.draw.line()` |
| **Plane Fitting** | `PlaneM.cs` | 3-point → plane equation | `np.linalg.solve()` or least squares |

---

## References

**Barycentric Coordinates:**
- [Wikipedia: Barycentric Coordinate System](https://en.wikipedia.org/wiki/Barycentric_coordinate_system)
- Used for: Point-in-triangle testing, interpolation

**Delaunay Triangulation:**
- [Wikipedia: Delaunay Triangulation](https://en.wikipedia.org/wiki/Delaunay_triangulation)
- Bowyer-Watson algorithm for incremental insertion

**Triangle Rasterization:**
- Scanline algorithm (top-down)
- Edge-walking with slope calculation

**Cross Product in 2D:**
- `(b - a) × (c - a) = (b.x - a.x)(c.y - a.y) - (b.y - a.y)(c.x - a.x)`
- Positive if c is left of line a→b
- Zero if collinear
- Negative if c is right of line a→b

---

**End of Document**
