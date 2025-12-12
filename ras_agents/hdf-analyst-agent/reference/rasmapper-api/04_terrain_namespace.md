# RasMapperLib.Terrain Namespace Documentation

## Overview

The `RasMapperLib.Terrain` namespace handles all terrain-related operations in RASMapper, including:
- **Multi-resolution tiled terrain storage** - Manages terrain data at multiple pyramid levels for efficient rendering
- **Terrain raster I/O** - Reads/writes GeoTIFF terrain files with GDAL
- **Render block interpolation** - Provides bilinear interpolation within terrain tiles
- **Stitch geometry** - Manages TIN mesh edges between terrain levels
- **Spatial indexing** - Organizes tiles/blocks for fast spatial queries

This namespace is critical for understanding how RASMapper displays terrain hillshade and performs terrain-based interpolation for hydraulic results.

---

## Architecture

### Data Hierarchy

```
RasterFileInfo (terrain file metadata)
  └── TileRasters[] (pyramid levels 0, 1, 2, ...)
       └── TileDescriptor (filename, level, tileIdx)
            └── TileData
                 ├── tileValues[] (elevation data)
                 ├── perimeterValues[] (edge elevations for stitching)
                 └── mask[] (bitflags for interpolation mode)
```

### Tile Organization

Terrain files are organized as **tiled multi-resolution pyramids**:
- **Level 0**: Highest resolution (native terrain)
- **Level 1**: 2x downsampled
- **Level 2**: 4x downsampled
- etc.

Each level is divided into **tiles** (typically 256×256 or 512×512 pixels) for efficient memory usage and disk I/O.

### Render Blocks

A **RenderBlock** is a 2×2 cell quad from a terrain tile, used for bilinear interpolation:
```
D -------- A
|          |
|    E     |  (E = average of corners)
|          |
C -------- B
```

The `RenderBlock` class provides `Interpolate(xfrac, yfrac)` to get elevation at any point within the quad using **triangular subdivision** (splits quad into 4 triangles meeting at center E).

---

## Class Details

### RasterFileInfo

**Purpose**: Stores metadata and pyramid structure for a single terrain raster file.

**Key Properties**:
- `Filename` (string) - Path to terrain GeoTIFF
- `Cols`, `Rows` (int) - Dimensions of level 0
- `Extent` (Extent) - Geographic bounding box
- `Levels` (int) - Number of pyramid levels
- `CellSize[]` (double[]) - Cell size for each level
- `TileSize[]` (int[]) - Tile width for each level
- `TileRasters[]` (RasterM[]) - Spatial grid of tiles at each level
- `RenderBlockTiles[]` (RasterM[]) - Spatial grid of render blocks at each level
- `TileHasAnyData[]` (BitArray[]) - Per-tile data availability flags

**Key Methods**:
- `RasterFileInfo(H5Reader hr, string directory, string baseTerrain, string groupname)`
  - Constructor reads terrain metadata from HDF5 project file
  - Extracts: filename, priority, extent, pyramid levels, tile sizes
  - Opens GeoTIFF with `FloatTiffReader` to get dimensions and rounding mode
  - Calls `SetAllRasterNoData()` to populate `TileHasAnyData` from HDF

- `ComputeLevel(double desiredCellSize)` → int
  - Finds pyramid level matching desired cell size
  - Returns level index where `CellSize[i] >= desiredCellSize`

- `SetAllRasterNoData(H5Reader hr)`
  - Reads `/Terrain/{terrain}/MinMax/{level}` datasets from HDF
  - Populates `TileHasAnyData` BitArrays
  - Checks column 2 of MinMax table: 1.0 = no data, 0.0 = has data

- `CreateTileSpatialIndex()` → SpatialIndex<int>
  - Returns spatial index for level 0 tile grid
  - Enables fast "which tiles overlap this extent?" queries

- `CreateRenderBlockSpatialIndex()` → SpatialIndex<int>
  - Returns spatial index for level 0 render block grid

**Python Implementation Notes**:
- Use `rasterio` to read GeoTIFF metadata (dimensions, transform, nodata)
- Use `h5py` to read MinMax tables from HDF
- Implement pyramid level selection based on map scale/zoom
- Build spatial index with `rtree` or `shapely.STRtree`

---

### TileDescriptor

**Purpose**: Unique identifier for a terrain tile (filename + level + index).

**Properties**:
- `Filename` (string) - Terrain file path
- `Level` (string) - Pyramid level as string
- `TileIdx` (string) - Tile index within level
- `FileWithoutPath` (string) - Filename without extension

**Methods**:
- `GetHashCode()` → int - Computes hash for dictionary keys
- `Equals(object obj)` → bool - Equality comparison

**Usage**: Dictionary key for caching loaded tiles in memory.

**Python Implementation**:
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class TileDescriptor:
    filename: str
    level: int
    tile_idx: int
```

---

### TileData

**Purpose**: Stores elevation values for a single terrain tile.

**Properties**:
- `tileValues` (float[]) - Elevation values in row-major order (length = tileSize²)
- `perimeterValues` (float[]) - Elevations at tile edges for stitching
- `mask` (byte[]) - Bitflags per cell for interpolation mode
- `TimeLastUsed` (long) - Timestamp for LRU cache eviction

**Bitflags in `mask`**:
```
Bit 0 (0x01): Cell has data
Bit 1 (0x02): Bottom edge needs stitch
Bit 2 (0x04): Right edge needs stitch
Bit 3 (0x08): Top edge needs stitch
Bit 4 (0x10): Left edge needs stitch
```

**Python Implementation**:
```python
import numpy as np

class TileData:
    def __init__(self, tile_size):
        self.tile_values = np.full((tile_size, tile_size), np.nan, dtype=np.float32)
        self.perimeter_values = None
        self.mask = np.zeros((tile_size, tile_size), dtype=np.uint8)
        self.time_last_used = 0
```

---

### RenderBlock

**Purpose**: Bilinear interpolation within a 2×2 terrain cell quad.

**Key Algorithm**: `Interpolate(xfrac, yfrac)` → float

Divides quad into 4 triangles meeting at center E:
```
Triangle selection based on (xfrac, yfrac):
- Upper triangle: xfrac > yfrac and xfrac < (1-yfrac)
- Right triangle: xfrac > yfrac and xfrac >= (1-yfrac)
- Lower triangle: xfrac <= yfrac and xfrac > (1-yfrac)
- Left triangle: xfrac <= yfrac and xfrac <= (1-yfrac)
```

Each triangle uses **planar interpolation**:
```csharp
// Example: Upper triangle (between A-B-E)
float dAB = _b - _a;           // Slope from A to B
float dAE = _e2 - (_a + _b);   // Slope from AB to E
return _a + dAB * xfrac + dAE * yfrac;
```

**Methods**:
- `SetTile(RasterM tile, float[] tileValues, float[] perimeterValues, byte[] mask, List<SegmentM> stitches)`
  - Initializes render block with tile data
  - Sets up perimeter value indices

- `SetRowCol(int rbRow, int rbCol)` → bool
  - Loads corner values for cell at (rbRow, rbCol)
  - Returns false if cell has no data (mask bit 0 = 0)
  - Handles edge cases where corners come from `perimeterValues`

- `Interpolate(float xfrac, float yfrac)` → float
  - Bilinear interpolation within current cell
  - `xfrac`, `yfrac` in [0, 1] relative to cell

- `PointA/B/C/D(int rbrow, int rbcol)` → PointM
  - Returns 3D point for each corner
  - Z = elevation, M = cell size

- `PointE(int rbrow, int rbcol)` → PointM
  - Returns center point (Z = average of 4 corners / 2)

**Python Implementation**:
```python
def interpolate_render_block(a, b, c, d, xfrac, yfrac):
    """Bilinear interpolation in 2x2 quad (RASMapper style)

    Quad layout:      D --- A
                      |     |
                      C --- B
    """
    e2 = (a + b + c + d) * 0.5
    yfrac_inv = 1.0 - yfrac

    if xfrac > yfrac:
        if xfrac < yfrac_inv:  # Upper triangle (A-B-E)
            dAB = b - a
            dAE = e2 - (a + b)
            return a + dAB * xfrac + dAE * yfrac
        else:  # Right triangle (B-C-E)
            dBE = e2 - (b + c)
            dBC = c - b
            return b + dBE * (1 - xfrac) + dBC * yfrac
    else:
        if xfrac > yfrac_inv:  # Lower triangle (C-D-E)
            dCD = c - d
            dCE = e2 - (c + d)
            return d + dCD * xfrac + dCE * yfrac_inv
        else:  # Left triangle (D-A-E)
            dDE = e2 - (d + a)
            dDA = d - a
            return a + dDE * xfrac + dDA * yfrac
```

---

### StitchCache

**Purpose**: Manages TIN edges (stitches) between terrain tiles/levels.

**Properties**:
- `_rowCache` (H5RowCache<double>) - Lazy-loaded HDF stitch data
- `_nRows` (int) - Number of stitch segments
- `_dsetIdx` (int) - HDF dataset index
- `_stitches` (List<SegmentM>) - Pre-loaded stitch segments

**Methods**:
- `StitchCache(string filename, string stitchDataset)`
  - Constructor for HDF-backed stitches
  - Opens dataset but doesn't load data yet

- `StitchCache(List<SegmentM> stitches)`
  - Constructor for in-memory stitches

- `Stitches()` → IEnumerable<SegmentM>
  - Lazy iterator over stitch segments
  - Reads from HDF row-by-row or yields from list
  - Each row: [AX, AY, AZ, BX, BY, BZ, M]

**Stitch Data Format** (HDF dataset):
```
Columns: [0]=AX, [1]=AY, [2]=AZ, [3]=BX, [4]=BY, [5]=BZ, [6]=M
Where: A, B are endpoints of edge, M is cell size
```

**Python Implementation**:
```python
import h5py

class StitchCache:
    def __init__(self, hdf_path=None, dataset_name=None, stitches=None):
        if hdf_path:
            self.hdf = h5py.File(hdf_path, 'r')
            self.dataset = self.hdf[dataset_name]
            self.count = self.dataset.shape[0]
        else:
            self.stitches = stitches or []
            self.count = len(self.stitches)

    def iter_stitches(self):
        if hasattr(self, 'dataset'):
            for row in self.dataset:
                yield {
                    'A': (row[0], row[1], row[2]),
                    'B': (row[3], row[4], row[5]),
                    'M': row[6]
                }
        else:
            for s in self.stitches:
                yield s
```

---

### Hierarchical Row/Column Classes

These classes organize the multi-level tile/block/raster hierarchy:

#### TileColumn / TileRow
- **Purpose**: Column/row index in the tile grid
- **Properties**:
  - `Index` (int) - Column/row number
  - `RenderBlockColumns` / `RenderBlockRows` (List)

#### RenderBlockColumn / RenderBlockRow
- **Purpose**: Column/row index in the render block grid
- **Properties**:
  - `index` (int) - Column/row number
  - `RasterColumns` / `RasterRows` (List)

#### RasterColumn / RasterRow (struct)
- **Purpose**: Final raster cell position with fractional offset
- **Properties**:
  - `Index` (int) - Cell index
  - `Fraction` (float) - Fractional position within cell [0, 1]

**Usage Pattern**:
```
User clicks map at (X, Y)
  → Find TileColumn/Row at X, Y
    → Find RenderBlockColumn/Row within tile
      → Find RasterColumn/Row within block
        → Use Fraction for interpolation
```

---

### PolylineSegmentStartStation (struct)

**Purpose**: Links polyline segments to their starting station values.

**Properties**:
- `PolylineIndex` (int) - Which polyline (for multi-part features)
- `SegmentIndex` (int) - Which segment within polyline
- `SegmentStartingStation` (double) - Distance from polyline start

**Usage**: For stationing along cross-sections, profiles, or other linear features overlaid on terrain.

---

## Supporting Types (from RasMapperLib namespace)

### RasterM

**Purpose**: Defines a georeferenced raster grid with coordinate transformation.

**Key Properties**:
- `Rows`, `Cols` (int) - Grid dimensions
- `MinX`, `MaxX`, `MinY`, `MaxY` (double) - Geographic extent
- `CellSize` (double) - Uniform cell size

**Key Methods**:
- `Row(double y)` → int - Convert Y coordinate to row index
- `Col(double x)` → int - Convert X coordinate to column index
- `CellCenter(int row, int col)` → PointM - Get cell center coordinates
- `CellMinX/MaxX/MinY/MaxY(int col/row)` → double - Cell extent helpers
- `RowAndFraction(double y, ref int r, ref float frac)` - Split Y into row + fraction
- `ColAndFraction(double x, ref int c, ref float frac)` - Split X into col + fraction

**Python Equivalent**:
```python
import rasterio.transform

class RasterM:
    def __init__(self, rows, cols, transform):
        self.rows = rows
        self.cols = cols
        self.transform = transform
        self.cell_size = transform.a  # Assumes square cells

    def row_col(self, x, y):
        return rasterio.transform.rowcol(self.transform, x, y)

    def xy(self, row, col):
        return rasterio.transform.xy(self.transform, row, col)
```

### PointM (struct)

**Purpose**: 3D point with optional measure value (X, Y, Z, M).

**Properties**:
- `X`, `Y`, `Z`, `M` (double) - Coordinates (Z, M can be NaN)

**Python Equivalent**:
```python
from dataclasses import dataclass

@dataclass
class PointM:
    x: float
    y: float
    z: float = float('nan')
    m: float = float('nan')
```

### SegmentM (struct)

**Purpose**: Line segment with 3D endpoints and measure values.

**Properties**:
- `A`, `B` (PointM) - Endpoints
- `Index` (int) - Optional segment identifier

**Key Methods**:
- `Length` (double) - 2D length
- `PointAtFraction(double t)` → PointM - Interpolate at t ∈ [0, 1]
- `MidPoint()` → PointM - Center point

**Python Equivalent**:
```python
from shapely.geometry import LineString

class SegmentM:
    def __init__(self, a: PointM, b: PointM):
        self.a = a
        self.b = b
        self.geom = LineString([(a.x, a.y), (b.x, b.y)])
```

---

## Terrain Processing Workflow

### 1. Terrain Loading

```csharp
// Read terrain metadata from HDF project file
H5Reader hr = new H5Reader(projectPath);
RasterFileInfo rfi = new RasterFileInfo(hr, directory, baseName, groupname);

// Select pyramid level based on zoom
int level = rfi.ComputeLevel(desiredCellSize);

// Find overlapping tiles
SpatialIndex<int> tileIndex = rfi.CreateTileSpatialIndex();
List<int> tileIndices = tileIndex.Query(mapExtent);
```

### 2. Tile Reading

```csharp
// Open GeoTIFF
FloatTiffReader reader = new FloatTiffReader(rfi.Filename);

// Read tile data
TileDescriptor desc = new TileDescriptor(rfi.Filename, level, tileIdx);
TileData data = new TileData();
data.tileValues = reader.ReadTile(level, tileIdx);
```

### 3. Render Block Interpolation

```csharp
// Set up render block for interpolation
RenderBlock rb = new RenderBlock();
rb.SetTile(tileRaster, data.tileValues, data.perimeterValues, data.mask, stitches);

// Interpolate at map pixel
foreach (int row in rows) {
    foreach (int col in cols) {
        if (rb.SetRowCol(row, col)) {
            float elevation = rb.Interpolate(xfrac, yfrac);
        }
    }
}
```

---

## TIN Operations

### Stitch Geometry

**Purpose**: Stitches connect terrain tiles/levels to form a continuous TIN.

**When Used**:
- **Between tiles**: Where adjacent tiles meet
- **Between pyramid levels**: When zooming in/out
- **At tile boundaries**: To prevent cracks in 3D rendering

**Stitch Data Storage**:
- Stored in HDF project file: `/Terrain/{terrain}/Stitches/{level}`
- Each stitch is a 3D line segment (SegmentM)
- Stitches form triangle edges in the TIN

**Rendering with Stitches**:
```csharp
// Load stitches for current level
StitchCache stitches = new StitchCache(hdfPath, $"/Terrain/{terrain}/Stitches/{level}");

// Render block automatically generates stitch edges
List<SegmentM> edgeSegments = new List<SegmentM>();
rb.SetTile(tileRaster, values, perimeterValues, mask, edgeSegments);

// edgeSegments now contains TIN edges for visualization
```

---

## Raster Operations

### Reading Terrain Rasters

**GeoTIFF Support**:
- RASMapper uses **GDAL** (via `GDALRaster` and `FloatTiffReader`)
- Supports tiled GeoTIFF with multiple pyramid levels
- Reads metadata: extent, projection, nodata value, rounding mode

**Rounding Modes** (from TiffMetadata):
```
Unknown = 0
Nearest = 1
Floor = 2
Ceiling = 3
```

**Reading Pattern**:
```csharp
using (FloatTiffReader reader = new FloatTiffReader(filename)) {
    int width = reader.GetImageWidth(level);
    int height = reader.GetImageHeight(level);
    int tileWidth = reader.GetTileWidth(level);
    int tilesWide = reader.GetNumTilesWide(level);

    float[] tileData = reader.ReadTile(level, tileIdx);
}
```

### Writing Terrain Rasters

**FLT Format** (ESRI Binary Raster):
```csharp
// Export float array as .flt file
raster.ExportAsFLT(filename, data, nodata);

// Writes companion .hdr file with metadata
raster.WriteFloatHeaderfile(filename, nodata);
```

**World File** (.tfw, .jgw, etc.):
```csharp
raster.WriteWorldFile(filename);

// Format:
// Line 1: Cell size X
// Line 2: 0
// Line 3: 0
// Line 4: -Cell size Y
// Line 5: X of upper-left corner
// Line 6: Y of upper-left corner
```

---

## Python Implementation Guide

### Complete Terrain Reader Example

```python
import h5py
import rasterio
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class TerrainInfo:
    filename: str
    extent: Tuple[float, float, float, float]  # minX, minY, maxX, maxY
    rows: int
    cols: int
    levels: int
    cell_sizes: List[float]
    tile_sizes: List[int]

    @classmethod
    def from_hdf(cls, hdf_path: str, terrain_name: str):
        """Read terrain metadata from HDF project file"""
        with h5py.File(hdf_path, 'r') as hdf:
            group = hdf[f'/Terrain/{terrain_name}']
            filename = group.attrs['File']

            # Read raster metadata
            with rasterio.open(filename) as src:
                rows, cols = src.height, src.width
                bounds = src.bounds
                extent = (bounds.left, bounds.bottom, bounds.right, bounds.top)

                # Assume pyramid levels stored as overviews
                levels = len(src.overviews(1)) + 1

                cell_sizes = [src.res[0] * (2 ** i) for i in range(levels)]
                tile_sizes = [src.block_shapes[0][0]] * levels  # Assume square tiles

        return cls(filename, extent, rows, cols, levels, cell_sizes, tile_sizes)

    def compute_level(self, desired_cell_size: float) -> int:
        """Find pyramid level matching desired cell size"""
        for i, cs in enumerate(self.cell_sizes):
            if abs(cs - desired_cell_size) < 1e-5 or cs > desired_cell_size:
                return i
        return len(self.cell_sizes) - 1

class TerrainReader:
    def __init__(self, terrain_info: TerrainInfo):
        self.info = terrain_info
        self.raster = rasterio.open(terrain_info.filename)

    def read_tile(self, level: int, tile_row: int, tile_col: int) -> np.ndarray:
        """Read a terrain tile at given pyramid level"""
        if level == 0:
            overview_level = None
        else:
            overview_level = level - 1

        tile_size = self.info.tile_sizes[level]
        window = rasterio.windows.Window(
            tile_col * tile_size,
            tile_row * tile_size,
            tile_size,
            tile_size
        )

        if overview_level is None:
            data = self.raster.read(1, window=window)
        else:
            data = self.raster.read(1, window=window, out_shape=(tile_size, tile_size))

        return data.astype(np.float32)

    def interpolate_bilinear(self, x: float, y: float, level: int = 0) -> float:
        """Interpolate terrain elevation at point using RenderBlock algorithm"""
        # Convert to row/col
        row_f, col_f = self.raster.index(x, y)
        row, col = int(np.floor(row_f)), int(np.floor(col_f))

        # Fractional parts
        yfrac = row_f - row
        xfrac = col_f - col

        # Read 2x2 corner elevations
        window = rasterio.windows.Window(col, row, 2, 2)
        corners = self.raster.read(1, window=window)

        if corners.shape != (2, 2):
            return np.nan

        # RenderBlock convention: D-A top, C-B bottom
        a = corners[0, 1]  # Upper-right
        b = corners[1, 1]  # Lower-right
        c = corners[1, 0]  # Lower-left
        d = corners[0, 0]  # Upper-left

        # Apply RenderBlock interpolation
        return interpolate_render_block(a, b, c, d, xfrac, yfrac)

def interpolate_render_block(a, b, c, d, xfrac, yfrac):
    """RenderBlock bilinear interpolation (see earlier example)"""
    e2 = (a + b + c + d) * 0.5
    yfrac_inv = 1.0 - yfrac

    if xfrac > yfrac:
        if xfrac < yfrac_inv:
            return a + (b - a) * xfrac + (e2 - (a + b)) * yfrac
        else:
            return b + (e2 - (b + c)) * (1 - xfrac) + (c - b) * yfrac
    else:
        if xfrac > yfrac_inv:
            return d + (c - d) * xfrac + (e2 - (c + d)) * yfrac_inv
        else:
            return a + (e2 - (d + a)) * xfrac + (d - a) * yfrac
```

### Usage Example

```python
# Initialize terrain reader
hdf_path = "MyProject.prj"
terrain_info = TerrainInfo.from_hdf(hdf_path, "Terrain")
reader = TerrainReader(terrain_info)

# Interpolate elevation at point
x, y = 500000, 4000000  # Map coordinates
elevation = reader.interpolate_bilinear(x, y)

# Read specific tile
level = 0  # Highest resolution
tile_row, tile_col = 5, 10
tile_data = reader.read_tile(level, tile_row, tile_col)
```

---

## Automation Opportunities

### 1. Batch Terrain Preprocessing

**Goal**: Generate terrain pyramids and MinMax tables for multiple terrain files.

**Approach**:
```python
def preprocess_terrain(tif_path: str, output_hdf: str):
    """Generate pyramid levels and MinMax tables"""
    import subprocess

    # Generate overviews with GDAL
    subprocess.run([
        'gdaladdo',
        '-r', 'average',
        '--config', 'COMPRESS_OVERVIEW', 'LZW',
        tif_path,
        '2', '4', '8', '16'
    ])

    # Compute MinMax tables
    with rasterio.open(tif_path) as src:
        for level in range(src.overviews(1)):
            minmax = compute_tile_minmax(src, level)
            save_to_hdf(output_hdf, f'/Terrain/Terrain/MinMax/{level}', minmax)
```

### 2. Terrain Sampling for Cross-Sections

**Goal**: Extract elevation profiles along 1D cross-sections.

**Approach**:
```python
def sample_terrain_along_line(terrain_reader, line_coords):
    """Sample terrain elevations along LineString"""
    from shapely.geometry import LineString

    line = LineString(line_coords)
    stations = np.linspace(0, line.length, 100)
    elevations = []

    for station in stations:
        point = line.interpolate(station)
        z = terrain_reader.interpolate_bilinear(point.x, point.y)
        elevations.append(z)

    return stations, elevations
```

### 3. Terrain Difference Analysis

**Goal**: Compare two terrain surfaces (e.g., before/after grading).

**Approach**:
```python
def compute_terrain_difference(terrain1_path, terrain2_path, output_path):
    """Generate difference raster between two terrains"""
    import rasterio

    with rasterio.open(terrain1_path) as src1, \
         rasterio.open(terrain2_path) as src2:

        # Read aligned data
        data1 = src1.read(1)
        data2 = src2.read(1)

        # Compute difference
        diff = data2 - data1

        # Write output
        profile = src1.profile
        with rasterio.open(output_path, 'w', **profile) as dst:
            dst.write(diff, 1)
```

### 4. Automated Hillshade Generation

**Goal**: Generate hillshade layers for visualization.

**Approach**:
```python
def generate_hillshade(terrain_path, output_path, azimuth=315, altitude=45):
    """Generate hillshade raster using GDAL"""
    from osgeo import gdal

    ds = gdal.Open(terrain_path)
    gdal.DEMProcessing(
        output_path,
        ds,
        'hillshade',
        azimuth=azimuth,
        altitude=altitude
    )
```

---

## Key Takeaways

1. **Multi-Resolution Strategy**: RASMapper uses pyramid levels for efficient terrain rendering at different zoom levels.

2. **Tiled Architecture**: Large terrains are divided into tiles (256×256 or 512×512) to manage memory.

3. **RenderBlock Interpolation**: The unique triangular subdivision within 2×2 quads provides smooth terrain interpolation.

4. **Stitch Geometry**: TIN edges stored in HDF prevent cracks between tiles and levels.

5. **HDF Integration**: Terrain metadata (MinMax, Stitches) stored in HDF project file for fast queries.

6. **Python Replication**: Use `rasterio` for I/O, `h5py` for HDF metadata, and implement `RenderBlock` interpolation for exact matching.

7. **Automation**: Leverage GDAL command-line tools for preprocessing, Python for analysis and batch operations.
