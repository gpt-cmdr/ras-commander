# RasMapperLib.Mesh Namespace Documentation

**Generated:** 2025-12-09
**Purpose:** Reverse-engineer RASMapper mesh interpolation algorithms for Python implementation

---

## 1. Namespace Overview

The `RasMapperLib.Mesh` namespace contains the core data structures and algorithms for representing HEC-RAS 2D unstructured mesh topology. It provides:

- **Mesh topology primitives**: Cells, Faces, FacePoints (vertices)
- **Hydraulic connectivity**: Rules for water surface interpolation across faces
- **Velocity computation**: Data structures for face-centered velocity calculations
- **Mesh validation**: Status codes for mesh quality checks
- **Binary serialization**: Streaming methods for efficient data storage

**Key Design Pattern:** RASMapper uses a **half-edge-like mesh structure** where:
- **Cells** (polygons) contain references to their bounding **Faces**
- **Faces** (edges) reference two adjacent **Cells** and two **FacePoints**
- **FacePoints** (vertices) contain references to all adjacent **Faces**

This structure enables efficient traversal in both clockwise/counter-clockwise directions around cells and vertices.

---

## 2. Class Hierarchy

```
RasMapperLib.Mesh/
├── Cell (struct)                    # Mesh cell (polygon)
├── Face (class)                     # Shared edge between cells
├── FacePoint (struct)               # Vertex (corner point)
├── FaceValues (struct)              # Face-centered WSE with connectivity
├── FacePointVels (struct)           # Vertex-centered velocity vectors
├── FaceAroundFacePoint (struct)     # Face adjacency for vertex
├── FaceMidside (struct)             # Midpoint of face (for refinement)
├── FaceVelocityCoef (struct)        # Coefficient matrix for velocity interpolation
├── Vector2D (struct)                # 2D vector with magnitude
├── Segment2Double (struct)          # 2D line segment
├── HydraulicConnection (enum)       # Face connectivity type
└── MeshStatus (enum)                # Mesh validation status codes
```

**External Dependencies:**
- `Point2Double` - 2D point coordinates (double precision)
- `PointM` - 2D point with measure value
- `PointMs` - Collection of PointM

---

## 3. Key Classes with Details

### 3.1 Cell (struct)

**Purpose:** Represents a mesh cell (2D polygon) with center point and face connectivity.

**Properties:**
```csharp
public Point2Double Point;           // Cell center coordinates
public float MinimumElevation;       // Minimum terrain elevation in cell
public IList<int> Faces;             // Ordered face indices (CCW)
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `NextCCWFaceByGlobalIndex` | `int NextCCWFaceByGlobalIndex(int face)` | Get next face counter-clockwise from given global face index |
| `NextCWFaceByGlobalIndex` | `int NextCWFaceByGlobalIndex(int face)` | Get next face clockwise from given global face index |
| `NextCCWFaceByLocalIndex` | `int NextCCWFaceByLocalIndex(int face)` | Get next face CCW by local index in Faces list |
| `NextCWFaceByLocalIndex` | `int NextCWFaceByLocalIndex(int face)` | Get next face CW by local index in Faces list |
| `IsInitialized` | `bool IsInitialized()` | Check if cell has face connectivity |
| `Stream` (static) | `void Stream(BinaryWriter bw, IList<Cell> cells)` | Serialize cells to binary |
| `Stream` (static) | `Cell[] Stream(BinaryReader br)` | Deserialize cells from binary |

**Usage for Automation:**
- **Traversing cell boundaries:** Use `NextCCWFaceByLocalIndex` to walk around cell perimeter
- **Building cell polygons:** Iterate through `Faces` and collect FacePoint coordinates
- **Topology validation:** Check `IsInitialized()` before using cell data

**Python Implementation Notes:**
```python
@dataclass
class Cell:
    point: tuple[float, float]       # Center (x, y)
    min_elevation: float
    faces: list[int]                 # Ordered CCW face indices

    def next_ccw_face(self, local_idx: int) -> int:
        """Get next face counter-clockwise (wraps around)"""
        return self.faces[(local_idx + 1) % len(self.faces)]

    def next_cw_face(self, local_idx: int) -> int:
        """Get next face clockwise (wraps around)"""
        return self.faces[(local_idx - 1) % len(self.faces)]
```

---

### 3.2 Face (class)

**Purpose:** Represents a shared edge between two cells, with two endpoint FacePoints.

**Properties:**
```csharp
public int cellA;                    // First adjacent cell index
public int cellB;                    // Second adjacent cell index (-1 if perimeter)
public int fpA;                      // First FacePoint index
public int fpB;                      // Second FacePoint index
public float MinimumElevation;       // Minimum terrain elevation along face
public PointMs InternalPoints;       // Intermediate points (for curved faces)
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `OtherCell` | `int OtherCell(int cellIdx)` | Given one cell, return the other cell across this face |
| `OtherFacepoint` | `int OtherFacepoint(int fpIdx)` | Given one FacePoint, return the other endpoint |
| `GetFPNext` | `int GetFPNext(int cellIdx)` | Get next FacePoint (CCW from cell perspective) |
| `GetFPPrev` | `int GetFPPrev(int cellIdx)` | Get previous FacePoint (CW from cell perspective) |
| `SetFPNext` | `void SetFPNext(int cellIdx, int setTo)` | Set next FacePoint for a cell |
| `SetFPPrev` | `void SetFPPrev(int cellIdx, int setTo)` | Set previous FacePoint for a cell |
| `CommonCell` | `int CommonCell(Face otherFace)` | Find cell shared between two faces (-1 if none) |
| `IsEitherCell` | `bool IsEitherCell(int cellIdx)` | Check if cell belongs to this face |
| `IsNull` | `bool IsNull()` | Check if this is a null/invalid face |
| `NullFace` (static) | `Face NullFace()` | Create null face sentinel |

**Critical Detail - Perimeter Detection:**
```csharp
if (cellB == -1) {
    // This is a perimeter face (only one cell)
}
```

**Usage for Automation:**
- **Finding neighbors:** Use `OtherCell(myCell)` to traverse mesh
- **Building face geometry:** Use `fpA` and `fpB` to get endpoint coordinates
- **Perimeter detection:** Check `cellB == -1` for boundary faces

**Python Implementation Notes:**
```python
@dataclass
class Face:
    cell_a: int                      # First cell (-1 = exterior)
    cell_b: int                      # Second cell (-1 = perimeter)
    fp_a: int                        # First vertex
    fp_b: int                        # Second vertex
    min_elevation: float
    internal_points: list[tuple[float, float]] = None

    def is_perimeter(self) -> bool:
        """Check if this is a boundary face"""
        return self.cell_b == -1

    def other_cell(self, cell_idx: int) -> int:
        """Get the cell on other side of face"""
        if self.cell_a == cell_idx:
            return self.cell_b
        elif self.cell_b == cell_idx:
            return self.cell_a
        else:
            raise ValueError(f"Cell {cell_idx} not in face")

    def get_endpoints(self) -> tuple[int, int]:
        """Get both FacePoint indices"""
        return (self.fp_a, self.fp_b)
```

---

### 3.3 FacePoint (struct)

**Purpose:** Represents a mesh vertex (corner point) with adjacency to surrounding faces.

**Properties:**
```csharp
public Point2Double Point;           // Vertex coordinates (x, y)
public IList<int> Faces;             // Ordered face indices (CCW around vertex)
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `CCWFaceByLocalIndex` | `int CCWFaceByLocalIndex(int fi)` | Get next face CCW around vertex (local index) |
| `CWFaceByLocalIndex` | `int CWFaceByLocalIndex(int fi)` | Get next face CW around vertex (local index) |
| `CCWFaceByGlobalIndex` | `int CCWFaceByGlobalIndex(int face)` | Get next face CCW around vertex (global index) |
| `CWFaceByGlobalIndex` | `int CWFaceByGlobalIndex(int face)` | Get next face CW around vertex (global index) |
| `IsNull` | `bool IsNull()` | Check if this is a null/invalid FacePoint |
| `PointM` | `PointM PointM()` | Convert to PointM type |

**Static Members:**
```csharp
public static FacePoint NullFacePoint;  // Sentinel for invalid vertex
```

**Usage for Automation:**
- **Vertex star traversal:** Use `CCWFaceByLocalIndex` to walk around vertex
- **Planar regression:** Iterate through `Faces` to collect adjacent face WSE values
- **Ben's Weights:** Use vertex positions to compute barycentric coordinates

**Python Implementation Notes:**
```python
@dataclass
class FacePoint:
    point: tuple[float, float]       # Vertex (x, y)
    faces: list[int]                 # Ordered CCW face indices

    def adjacent_faces(self) -> list[int]:
        """Get all adjacent face indices"""
        return self.faces

    def is_perimeter(self, mesh_faces: list[Face]) -> bool:
        """Check if vertex is on perimeter (has perimeter face)"""
        return any(mesh_faces[f].is_perimeter() for f in self.faces)
```

---

### 3.4 FaceValues (struct)

**Purpose:** Stores water surface elevation (or other values) at a face with hydraulic connectivity information.

**Properties:**
```csharp
public float ValueA;                 // WSE on cellA side
public float ValueB;                 // WSE on cellB side
public HydraulicConnection HydraulicConnection;  // Connectivity type
```

**Computed Properties:**
```csharp
public bool IsHydraulicallyConnected  // True if connected (not None or Levee)
```

**Critical Algorithm - Hydraulic Connectivity:**
```csharp
if (HydraulicConnection != HydraulicConnection.None &&
    HydraulicConnection != HydraulicConnection.Levee) {
    // Face is hydraulically connected - use single WSE
    return ValueA;
} else {
    // Face is disconnected - use separate WSE for each side
    return "Disc: " + ValueA + " / " + ValueB;
}
```

**Usage for Automation:**
- **Face WSE computation:** This is the OUTPUT of the Stage 1 algorithm
- **Vertex WSE computation:** Input to Stage 2 planar regression
- **Connectivity handling:** Check `IsHydraulicallyConnected` before averaging

**Python Implementation Notes:**
```python
from enum import IntEnum

class HydraulicConnection(IntEnum):
    NONE = 0                         # No connection (different WSE on each side)
    BACKFILL = 1                     # Backfilled connection
    DOWNHILL_DEEP = 2                # Deep flow downhill
    DOWNHILL_INTERMEDIATE = 3        # Intermediate flow downhill
    DOWNHILL_SHALLOW = 4             # Shallow flow downhill
    LEVEE = 5                        # Levee/wall (disconnected)

@dataclass
class FaceValues:
    value_a: float                   # WSE on cell A side
    value_b: float                   # WSE on cell B side
    connection: HydraulicConnection

    @property
    def is_connected(self) -> bool:
        """Check if hydraulically connected"""
        return (self.connection != HydraulicConnection.NONE and
                self.connection != HydraulicConnection.LEVEE)

    def get_wse(self, cell_idx: int, face: Face) -> float:
        """Get WSE for specific cell side"""
        if face.cell_a == cell_idx:
            return self.value_a
        elif face.cell_b == cell_idx:
            return self.value_b
        else:
            raise ValueError("Cell not in face")
```

---

### 3.5 FacePointVels (struct)

**Purpose:** Stores velocity vectors at a vertex (array to support time series).

**Properties:**
```csharp
public Vector2D[] Velocity;          // Array of velocity vectors
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `Copy` | `FacePointVels Copy()` | Deep copy of velocity array |

**Usage for Automation:**
- **Velocity rasterization:** Similar to WSE, but vector-valued
- **Vector interpolation:** Use Ben's Weights with 2D vectors

**Python Implementation Notes:**
```python
@dataclass
class FacePointVels:
    velocity: np.ndarray             # Shape: (n_times, 2) or just (2,)

    def copy(self):
        return FacePointVels(self.velocity.copy())
```

---

### 3.6 FaceAroundFacePoint (struct)

**Purpose:** Describes a face's relationship to a FacePoint, used for sorting faces by bearing angle.

**Properties:**
```csharp
public int faceIndex;                // Global face index
public int faceOrientation;          // Which FacePoint (fpA=0 or fpB=1)
public double bearing;               // Angle from vertex to face
public bool isPerimeter;             // True if perimeter face
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `CompareBearings` (static) | `int CompareBearings(a, b)` | Compare for sorting by bearing angle |

**Usage for Automation:**
- **Vertex star sorting:** Order faces CCW around vertex by bearing
- **Planar regression:** Select adjacent faces by angle
- **Gap detection:** Identify missing faces in vertex star

**Python Implementation Notes:**
```python
@dataclass
class FaceAroundFacePoint:
    face_index: int
    face_orientation: int            # 0=fpA, 1=fpB
    bearing: float                   # Radians from vertex
    is_perimeter: bool

    @staticmethod
    def compare_bearings(a, b):
        """Comparator for sorting by bearing"""
        return (a.bearing > b.bearing) - (a.bearing < b.bearing)
```

---

### 3.7 Vector2D (struct)

**Purpose:** 2D vector with magnitude and operations (velocity, normals, etc.).

**Properties:**
```csharp
public float X;
public float Y;
```

**Computed Properties:**
```csharp
public float Magnitude;              // Sqrt(X^2 + Y^2)
```

**Static Members:**
```csharp
public static readonly Vector2D NoData = new Vector2D(-9999f, -9999f);
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `Dot` | `float Dot(Vector2D other)` | Dot product |
| `MakeUnit` | `Vector2D MakeUnit()` | Normalize to unit vector |
| `Perpendicular` | `Vector2D Perpendicular()` | Rotate 90° CCW |
| `ScaleToLength` | `Vector2D ScaleToLength(float len)` | Scale to specific length |
| `IsNoData` | `bool IsNoData()` | Check for NODATA sentinel |

**Operators:**
```csharp
Vector2D operator +(Vector2D a, Vector2D b)
Vector2D operator /(Vector2D v, float scalar)
Vector2D operator *(Vector2D v, float scalar)
Vector2D operator *(float scalar, Vector2D v)
bool operator ==(Vector2D a, Vector2D b)
bool operator !=(Vector2D a, Vector2D b)
```

**Python Implementation Notes:**
```python
import numpy as np

class Vector2D:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    @property
    def magnitude(self) -> float:
        return np.sqrt(self.x**2 + self.y**2)

    def dot(self, other: 'Vector2D') -> float:
        return self.x * other.x + self.y * other.y

    def perpendicular(self) -> 'Vector2D':
        return Vector2D(-self.y, self.x)

    def make_unit(self) -> 'Vector2D':
        mag = self.magnitude
        return Vector2D(self.x / mag, self.y / mag)

    def is_nodata(self) -> bool:
        return self.x == -9999 or self.y == -9999
```

---

### 3.8 FaceVelocityCoef (struct)

**Purpose:** Coefficient matrix for computing vertex velocity from adjacent face velocities.

**Properties:**
```csharp
public float A11, A22, A12;          // Coefficient matrix elements
private int _ct;                     // Count of face normals added
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `AddFaceNormal` | `void AddFaceNormal(Vector2D norm)` | Accumulate face normal contribution |
| `AddWeightedFaceNormal` | `void AddWeightedFaceNormal(Vector2D norm, float wK)` | Add weighted face normal |
| `Complete` | `void Complete()` | Finalize matrix (compute inverse) |
| `Compute` | `Vector2D Compute(float B1, float B2)` | Solve for velocity vector |

**Algorithm - Least Squares Velocity Reconstruction:**

This implements a **weighted least squares** method to reconstruct vertex velocity from adjacent face-centered velocities.

**Step 1: Accumulate face normals**
```csharp
foreach (face in adjacentFaces) {
    Vector2D norm = face.Normal;
    A11 += norm.X * norm.X;
    A22 += norm.Y * norm.Y;
    A12 += norm.X * norm.Y;
}
```

**Step 2: Compute matrix inverse**
```csharp
float det = A11 * A22 - A12 * A12;
if (det != 0) {
    A11 *= 1.0 / det;
    A22 *= 1.0 / det;
    A12 *= 1.0 / det;
}
```

**Step 3: Solve for velocity**
```csharp
Vector2D velocity = Compute(B1, B2);
// Where B1, B2 are from face velocity projections
```

**Usage for Automation:**
- **Velocity interpolation:** Convert face-centered to vertex-centered velocities
- **Mesh smoothing:** Weighted averaging of vector fields

**Python Implementation Notes:**
```python
import numpy as np

class FaceVelocityCoef:
    def __init__(self):
        self.A11 = 0.0
        self.A22 = 0.0
        self.A12 = 0.0
        self._ct = 0

    def add_face_normal(self, norm: Vector2D):
        """Accumulate face normal contribution"""
        self.A11 += norm.x * norm.x
        self.A22 += norm.y * norm.y
        self.A12 += norm.x * norm.y
        self._ct += 1

    def add_weighted_face_normal(self, norm: Vector2D, weight: float):
        """Add weighted face normal"""
        self.A11 += norm.x * norm.x * weight
        self.A22 += norm.y * norm.y * weight
        self.A12 += norm.x * norm.y * weight
        self._ct += 1

    def complete(self):
        """Finalize coefficient matrix (invert)"""
        det = self.A11 * self.A22 - self.A12**2
        if det == 0:
            # Singular matrix - use identity
            self.A11 = 1.0 / self._ct
            self.A12 = 0.0
            self.A22 = 1.0 / self._ct
        else:
            # Multiply by 1/det (matrix inversion)
            inv_det = 1.0 / det
            self.A11 *= inv_det
            self.A22 *= inv_det
            self.A12 *= inv_det

    def compute(self, B1: float, B2: float) -> Vector2D:
        """Solve for velocity vector"""
        x = self.A22 * B1 - self.A12 * B2
        y = -self.A12 * B1 + self.A11 * B2
        return Vector2D(x, y)
```

---

### 3.9 FaceMidside (struct)

**Purpose:** Stores midpoint of a face (used for mesh refinement).

**Properties:**
```csharp
public Point2Double Point;           // Midpoint coordinates
public int SegmentIndex;             // Index of parent face
```

**Usage for Automation:**
- **Mesh subdivision:** Split faces at midpoints
- **Curved boundaries:** Approximate curves with piecewise linear segments

---

### 3.10 Segment2Double (struct)

**Purpose:** 2D line segment with utility methods.

**Properties:**
```csharp
public Point2Double A;               // Start point
public Point2Double B;               // End point
```

**Key Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `MaxY` | `double MaxY()` | Maximum Y coordinate |
| `MinY` | `double MinY()` | Minimum Y coordinate |
| `DeltaY` | `double DeltaY()` | Y difference (B.Y - A.Y) |

**Usage for Automation:**
- **Bounding box calculations**
- **Scanline intersection tests**

---

## 4. Data Structures

### 4.1 HydraulicConnection (enum)

**Purpose:** Defines how water surface elevation is computed across a face.

```csharp
public enum HydraulicConnection : byte {
    None = 0,                        // No hydraulic connection (separate WSE)
    Backfill = 1,                    // Backfilled terrain connection
    DownhillDeep = 2,                // Deep flow downhill
    DownhillIntermediate = 3,        // Intermediate depth flow
    DownhillShallow = 4,             // Shallow flow downhill
    Levee = 5                        // Levee/wall (no connection)
}
```

**Critical Algorithm Logic:**

RASMapper uses this enum to determine face WSE computation:

| Connection Type | Face WSE Behavior |
|----------------|-------------------|
| `None` | Disconnected: `ValueA` and `ValueB` differ |
| `Backfill` | Connected: Use terrain gradient to backfill |
| `DownhillDeep` | Connected: Downhill propagation (deep) |
| `DownhillIntermediate` | Connected: Downhill propagation (intermediate) |
| `DownhillShallow` | Connected: Downhill propagation (shallow) |
| `Levee` | Disconnected: Structure blocks flow |

**Usage for Automation:**
- **Stage 1 (Face WSE):** Determine connectivity rules
- **Stage 2 (Vertex WSE):** Only use connected faces for regression
- **Rendering:** Visualize connectivity as face colors

**Python Implementation:**
```python
from enum import IntEnum

class HydraulicConnection(IntEnum):
    NONE = 0
    BACKFILL = 1
    DOWNHILL_DEEP = 2
    DOWNHILL_INTERMEDIATE = 3
    DOWNHILL_SHALLOW = 4
    LEVEE = 5

    def is_connected(self) -> bool:
        """Check if connection allows WSE propagation"""
        return self not in (HydraulicConnection.NONE, HydraulicConnection.LEVEE)
```

---

### 4.2 MeshStatus (enum)

**Purpose:** Error codes for mesh validation and quality checks.

```csharp
public enum MeshStatus {
    FewerThanMinPerimeterPoints,     // Too few boundary points
    PerimeterPolygonError,           // Invalid perimeter geometry
    FewerThanMinNumCells,            // Too few cells
    DuplicatePoints,                 // Duplicate vertex coordinates
    PointsOutsidePerimeter,          // Vertices outside boundary
    DisconnectedGraphs,              // Multiple disconnected meshes
    FacePerimeterConnectionError,    // Face-boundary topology error
    CellAreaTotalError,              // Cell area mismatch
    MaxFacesPerCellExceeded,         // Cell has too many faces
    MaxFacesPerFacepointExceeded,    // Vertex has too many faces
    BreaklineError,                  // Breakline constraint violation
    UnknownError,                    // Generic error
    MinFaceLenError,                 // Face too short
    OldVersion,                      # Mesh file version mismatch
    Complete,                        # Mesh is valid
    CellMinFaceError                 # Cell has too few faces
}
```

**Usage for Automation:**
- **Mesh import validation:** Check mesh quality before processing
- **Error reporting:** Map status codes to user messages
- **Quality control:** Detect mesh topology problems

---

## 5. Algorithm Documentation

### 5.1 Mesh Topology Traversal

**Problem:** Walk around a cell or vertex in counter-clockwise order.

**Cell Traversal (CCW around cell boundary):**
```csharp
Cell cell = cells[cellIdx];
for (int i = 0; i < cell.Faces.Count; i++) {
    int faceIdx = cell.Faces[i];
    Face face = faces[faceIdx];

    // Get FacePoint in CCW direction from this cell
    int fpIdx = face.GetFPNext(cellIdx);
    FacePoint fp = facepoints[fpIdx];

    // Process vertex...
}
```

**Vertex Traversal (CCW around vertex star):**
```csharp
FacePoint fp = facepoints[fpIdx];
for (int i = 0; i < fp.Faces.Count; i++) {
    int faceIdx = fp.Faces[i];
    Face face = faces[faceIdx];

    // Get adjacent cell
    int cellIdx;
    if (face.fpA == fpIdx) {
        cellIdx = face.cellA;  // fpA points to cellA
    } else {
        cellIdx = face.cellB;  // fpB points to cellB
    }

    // Process cell...
}
```

**Python Implementation:**
```python
def traverse_cell_boundary(cell: Cell, faces: list[Face],
                          facepoints: list[FacePoint]) -> list[tuple[float, float]]:
    """Walk CCW around cell and collect vertex coordinates"""
    vertices = []
    for face_idx in cell.faces:
        face = faces[face_idx]
        # Determine which FacePoint is "next" from this cell's perspective
        if face.cell_a == cell.idx:
            fp_idx = face.fp_b  # CCW for cellA
        else:
            fp_idx = face.fp_a  # CCW for cellB
        vertices.append(facepoints[fp_idx].point)
    return vertices

def traverse_vertex_star(fp: FacePoint, faces: list[Face]) -> list[int]:
    """Walk CCW around vertex and collect adjacent cell indices"""
    cells = []
    for face_idx in fp.faces:
        face = faces[face_idx]
        # Determine which cell to use
        if face.fp_a == fp.idx:
            cells.append(face.cell_a)
        elif face.fp_b == fp.idx:
            cells.append(face.cell_b)
    return cells
```

---

### 5.2 Face WSE Computation (Stage 1)

**Problem:** Compute water surface elevation at face centers from cell-centered HDF results.

**Algorithm (from decompiled RASMapper):**

```csharp
FaceValues[] ComputeFaceWSE(Cell[] cells, Face[] faces, float[] cellWSE) {
    FaceValues[] faceWSE = new FaceValues[faces.Length];

    for (int i = 0; i < faces.Length; i++) {
        Face face = faces[i];
        float wseA = cellWSE[face.cellA];
        float wseB = (face.cellB == -1) ? -9999f : cellWSE[face.cellB];

        // Determine hydraulic connection type
        HydraulicConnection conn = DetermineConnection(face, wseA, wseB);

        // Apply connectivity rules
        if (conn == HydraulicConnection.Backfill) {
            // Backfill: use terrain gradient
            wseB = BackfillWSE(face, wseA);
        } else if (conn == HydraulicConnection.DownhillDeep ||
                   conn == HydraulicConnection.DownhillIntermediate ||
                   conn == HydraulicConnection.DownhillShallow) {
            // Downhill: propagate WSE
            wseB = wseA;  // Simplified
        }

        faceWSE[i] = new FaceValues(wseA, wseB, conn);
    }

    return faceWSE;
}
```

**Python Implementation (Simplified):**
```python
def compute_face_wse(cells: list[Cell], faces: list[Face],
                     cell_wse: np.ndarray) -> list[FaceValues]:
    """Compute face-centered WSE with hydraulic connectivity"""
    face_wse = []

    for face in faces:
        wse_a = cell_wse[face.cell_a]
        wse_b = -9999.0 if face.cell_b == -1 else cell_wse[face.cell_b]

        # Determine connection type (simplified)
        if face.is_perimeter():
            conn = HydraulicConnection.NONE
        elif wse_a == wse_b:
            conn = HydraulicConnection.BACKFILL
        else:
            conn = HydraulicConnection.DOWNHILL_INTERMEDIATE

        face_wse.append(FaceValues(wse_a, wse_b, conn))

    return face_wse
```

**Note:** Full implementation in `ras-commander` at `ras_commander/mapping/face_wse.py`

---

### 5.3 Vertex WSE Computation (Stage 2)

**Problem:** Compute water surface elevation at vertices from face WSE values.

**Algorithm (Planar Regression):**

```csharp
float[] ComputeVertexWSE(FacePoint[] facepoints, Face[] faces, FaceValues[] faceWSE) {
    float[] vertexWSE = new float[facepoints.Length];

    for (int i = 0; i < facepoints.Length; i++) {
        FacePoint fp = facepoints[i];

        // Collect WSE from adjacent faces
        List<float> wseValues = new List<float>();
        List<Point2Double> facePoints = new List<Point2Double>();

        foreach (int faceIdx in fp.Faces) {
            Face face = faces[faceIdx];
            FaceValues fv = faceWSE[faceIdx];

            if (!fv.IsHydraulicallyConnected) continue;  // Skip disconnected

            // Get face center point
            Point2Double facePt = GetFaceCenter(face, facepoints);
            facePoints.Add(facePt);

            // Get WSE value for this face
            float wse = fv.ValueA;  // Or ValueB depending on orientation
            wseValues.Add(wse);
        }

        // Planar regression
        if (wseValues.Count >= 3) {
            vertexWSE[i] = PlanarRegressionZ(fp.Point, facePoints, wseValues);
        } else {
            vertexWSE[i] = wseValues.Average();
        }
    }

    return vertexWSE;
}
```

**Python Implementation:**
```python
def compute_vertex_wse(facepoints: list[FacePoint], faces: list[Face],
                       face_wse: list[FaceValues]) -> np.ndarray:
    """Compute vertex WSE using planar regression"""
    vertex_wse = np.full(len(facepoints), -9999.0)

    for i, fp in enumerate(facepoints):
        wse_vals = []
        face_pts = []

        for face_idx in fp.faces:
            face = faces[face_idx]
            fv = face_wse[face_idx]

            if not fv.is_connected:
                continue

            # Get face center
            face_center = get_face_center(face, facepoints)
            face_pts.append(face_center)
            wse_vals.append(fv.value_a)

        if len(wse_vals) >= 3:
            # Planar regression
            vertex_wse[i] = planar_regression_z(fp.point, face_pts, wse_vals)
        elif len(wse_vals) > 0:
            vertex_wse[i] = np.mean(wse_vals)

    return vertex_wse
```

**Note:** Full implementation in `ras-commander` at `ras_commander/mapping/vertex_wse.py`

---

### 5.4 Ben's Weights Interpolation (Stage 3)

**Problem:** Interpolate WSE at raster pixels from vertex WSE values.

**Algorithm (Generalized Barycentric Coordinates):**

```csharp
float InterpolatePixelWSE(Point2Double pixel, int[] cellVertices,
                         FacePoint[] facepoints, float[] vertexWSE) {
    // Compute Ben's Weights
    float[] weights = new float[cellVertices.Length];
    float sumWeights = 0f;

    for (int i = 0; i < cellVertices.Length; i++) {
        int vi = cellVertices[i];
        int vj = cellVertices[(i + 1) % cellVertices.Length];

        Point2Double pi = facepoints[vi].Point;
        Point2Double pj = facepoints[vj].Point;

        // Cross product weighting
        Vector2D edgeVec = new Vector2D(pj.X - pi.X, pj.Y - pi.Y);
        Vector2D pixelVec = new Vector2D(pixel.X - pi.X, pixel.Y - pi.Y);

        float cross = edgeVec.X * pixelVec.Y - edgeVec.Y * pixelVec.X;
        weights[i] = cross;
        sumWeights += cross;
    }

    // Normalize weights
    for (int i = 0; i < weights.Length; i++) {
        weights[i] /= sumWeights;
    }

    // Interpolate WSE
    float wse = 0f;
    for (int i = 0; i < cellVertices.Length; i++) {
        wse += weights[i] * vertexWSE[cellVertices[i]];
    }

    return wse;
}
```

**Python Implementation:**
```python
def compute_bens_weights(pixel: tuple[float, float],
                        vertices: list[tuple[float, float]]) -> np.ndarray:
    """Compute generalized barycentric coordinates (Ben's Weights)"""
    n = len(vertices)
    weights = np.zeros(n)

    for i in range(n):
        j = (i + 1) % n

        # Edge vector
        edge_x = vertices[j][0] - vertices[i][0]
        edge_y = vertices[j][1] - vertices[i][1]

        # Pixel vector
        pixel_x = pixel[0] - vertices[i][0]
        pixel_y = pixel[1] - vertices[i][1]

        # Cross product
        weights[i] = edge_x * pixel_y - edge_y * pixel_x

    # Normalize
    weights /= np.sum(weights)
    return weights

def interpolate_pixel_wse(pixel: tuple[float, float],
                          cell_vertices: list[int],
                          facepoints: list[FacePoint],
                          vertex_wse: np.ndarray) -> float:
    """Interpolate WSE at pixel using Ben's Weights"""
    vertices = [facepoints[v].point for v in cell_vertices]
    weights = compute_bens_weights(pixel, vertices)

    wse = 0.0
    for i, v_idx in enumerate(cell_vertices):
        wse += weights[i] * vertex_wse[v_idx]

    return wse
```

**Note:** Full implementation in `ras-commander` at `ras_commander/mapping/bens_weights.py`

---

## 6. Python Implementation Notes

### 6.1 Data Structure Mapping

**C# struct → Python dataclass:**
```python
from dataclasses import dataclass
import numpy as np

@dataclass
class Cell:
    point: tuple[float, float]
    min_elevation: float
    faces: list[int]

@dataclass
class Face:
    cell_a: int
    cell_b: int
    fp_a: int
    fp_b: int
    min_elevation: float
    internal_points: list[tuple[float, float]] = None

@dataclass
class FacePoint:
    point: tuple[float, float]
    faces: list[int]
```

### 6.2 Binary Serialization

RASMapper uses custom binary serialization (`Stream` methods). To read these in Python:

```python
import struct

def read_cells(f) -> list[Cell]:
    """Read Cell array from binary stream"""
    count = struct.unpack('i', f.read(4))[0]
    cells = []

    for _ in range(count):
        x, y = struct.unpack('dd', f.read(16))
        min_elev = struct.unpack('f', f.read(4))[0]
        face_count = struct.unpack('i', f.read(4))[0]
        faces = list(struct.unpack(f'{face_count}i', f.read(4*face_count)))

        cells.append(Cell((x, y), min_elev, faces))

    return cells
```

**Note:** This is speculative - actual format may differ.

### 6.3 HDF Access (Recommended)

Instead of binary serialization, use HEC-RAS HDF files directly:

```python
from ras_commander import HdfMesh, HdfResultsMesh

# Read mesh topology
geom_hdf = "project.g01.hdf"
cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
cell_faces = HdfMesh.get_mesh_cell_faces(geom_hdf)

# Read results
plan_hdf = "project.p01.hdf"
max_ws = HdfResultsMesh.get_mesh_max_ws(plan_hdf)
```

---

## 7. Automation Opportunities

### 7.1 Direct RASMapper Automation (via .NET)

**Approach:** Use `pythonnet` to call RASMapper directly.

```python
import clr
clr.AddReference("RasMapperLib")
from RasMapperLib.Mesh import Cell, Face, FacePoint

# Create mesh structures
cell = Cell(Point2Double(0, 0))
```

**Pros:**
- Exact RASMapper behavior
- No algorithm reimplementation

**Cons:**
- Windows-only
- Requires RASMapper installation
- Limited to available public API

### 7.2 Python Reimplementation (Current Approach)

**Approach:** Reimplement algorithms in pure Python.

**Pros:**
- Cross-platform
- Full control over algorithm
- Can optimize for batch processing

**Cons:**
- Must reverse-engineer algorithms
- May have subtle differences from RASMapper

### 7.3 Hybrid Approach

**Approach:** Use RASMapper for mesh creation, Python for interpolation.

```python
# Option 1: Export mesh to JSON/binary
rasMapper.ExportMesh("mesh.json")
mesh = load_mesh("mesh.json")

# Option 2: Use HDF as intermediate
mesh = load_mesh_from_hdf("project.g01.hdf")

# Python interpolation
wse_raster = interpolate_sloped(mesh, results, terrain)
```

---

## 8. Key Takeaways for ras-commander Implementation

### 8.1 Mesh Topology Structure

- **Cells** contain ordered lists of **Faces** (CCW)
- **Faces** connect two **Cells** and two **FacePoints**
- **FacePoints** contain ordered lists of **Faces** (CCW)
- Perimeter faces have `cellB == -1`

### 8.2 WSE Interpolation Pipeline

**Stage 1: Face WSE (hydraulic connectivity)**
- Input: Cell-centered WSE from HDF
- Output: Face-centered WSE with `HydraulicConnection` type
- Key classes: `FaceValues`, `HydraulicConnection`

**Stage 2: Vertex WSE (planar regression)**
- Input: Face-centered WSE
- Output: Vertex-centered WSE
- Key method: Planar regression through adjacent face WSE

**Stage 3: Raster WSE (Ben's Weights)**
- Input: Vertex-centered WSE
- Output: Rasterized WSE
- Key algorithm: Generalized barycentric coordinates

### 8.3 Critical Details

1. **Hydraulic Connectivity:** Faces can be connected or disconnected (levees, dry cells)
2. **Perimeter Handling:** Perimeter faces (`cellB == -1`) require special treatment
3. **NODATA Propagation:** Missing WSE values propagate through pipeline
4. **Bearing-Based Sorting:** Vertex stars are sorted by bearing angle (CCW)

### 8.4 Implementation Status in ras-commander

✅ **Completed:**
- Stage 1: `compute_face_wse()` in `ras_commander/mapping/face_wse.py`
- Stage 2: `compute_vertex_wse()` in `ras_commander/mapping/vertex_wse.py`
- Stage 3: `rasterize_sloped_wse()` in `ras_commander/mapping/sloped.py`
- Validation: <0.0001 ft median error on Plan 15

⚠️ **Remaining Gaps:**
- 29% vertex coverage gap (perimeter vertices, dry cells)
- Large outliers at 1D-2D connections (40 ft max diff)
- 8% cell polygon failures (<3 facepoints)

---

## 9. References

- **HEC-RAS HDF Structure:** `ras-commander` documentation
- **Decompiled Source:** `RasMapperLib.dll` via ILSpy
- **Validation Project:** `Test Data/BaldEagleCrkMulti2D - Sloped - Cell Corners/`
- **Python Implementation:** `ras-commander/ras_commander/mapping/`

---

**Document Version:** 1.0
**Last Updated:** 2025-12-09
