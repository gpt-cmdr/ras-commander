# Lazy Loading Architecture

The `ras_commander.hdf` subpackage implements a three-level lazy loading strategy to minimize import overhead while maintaining full functionality.

## Why Lazy Loading?

**Problem**: Heavy scientific packages increase import time:
- geopandas: ~200ms
- matplotlib: ~300ms
- xarray: ~100ms
- scipy: ~150ms
- **Total overhead**: ~750ms just for imports

**Solution**: Load dependencies only when methods that need them are called.

**Result**:
- Subpackage import: <200ms (h5py, numpy, pandas only)
- First method call with heavy deps: +200-500ms (one-time cost)
- Subsequent calls: No overhead (already loaded)

## Three-Level Loading Strategy

### Level 1: Always Loaded (Module Import)
Loaded when importing `ras_commander.hdf` or any class:

```python
import h5py           # ~20ms - HDF5 file operations
import numpy as np    # ~50ms - Numerical arrays
import pandas as pd   # ~100ms - DataFrames
from pathlib import Path
from typing import List, Dict, Optional
```

**Total overhead**: ~170ms

**Used by**: All HDF classes (universal dependencies)

### Level 2: Lazy Loaded (Inside Methods)
Loaded only when specific methods are called:

```python
@staticmethod
def get_mesh_cell_polygons(hdf_path: Path) -> 'GeoDataFrame':
    # Lazy imports - only loaded when this method is called
    from geopandas import GeoDataFrame
    from shapely.geometry import Polygon
    from shapely.ops import polygonize

    # Method implementation...
```

**Overhead**: 200-300ms first call, 0ms subsequent calls

**Used by**: Methods returning GeoDataFrame or creating geometries

### Level 3: Conditional Lazy Loading
Loaded only if specific features are used within a method:

```python
@staticmethod
def find_nearest_cell(hdf_path: Path, point, mesh_name: str) -> dict:
    from geopandas import GeoDataFrame
    from shapely.geometry import Point

    # Only import scipy if we have many cells (spatial index needed)
    if len(cells) > 100:
        from scipy.spatial import KDTree  # ~150ms
        # Use KDTree for fast spatial query
    else:
        # Simple distance calculation (no scipy needed)
        pass
```

**Overhead**: Conditional based on data size/feature usage

## Dependency Loading Table

Complete dependency loading timing and usage:

| Dependency | Load Time | Loading Level | Used In Classes | Import Pattern |
|------------|-----------|---------------|-----------------|----------------|
| **Core (Always Loaded)** |
| h5py | ~20ms | Level 1 | All classes | Module-level |
| numpy | ~50ms | Level 1 | All classes | Module-level |
| pandas | ~100ms | Level 1 | All classes | Module-level |
| pathlib | ~1ms | Level 1 | All classes | Module-level |
| typing | ~1ms | Level 1 | All classes | Module-level |
| **Geometry (Lazy Loaded)** |
| geopandas | ~200ms | Level 2 | HdfMesh, HdfXsec, HdfBndry, HdfStruc, HdfPipe, HdfPump | Method-level |
| shapely | ~50ms | Level 2 | HdfMesh, HdfXsec, HdfBndry, HdfBase | Method-level |
| **Analysis (Lazy Loaded)** |
| xarray | ~100ms | Level 2 | HdfResultsMesh, HdfResultsXsec, HdfPipe, HdfPump | Method-level |
| scipy | ~150ms | Level 3 | HdfUtils (KDTree only) | Conditional |
| **Visualization (Lazy Loaded)** |
| matplotlib | ~300ms | Level 2 | HdfPlot, HdfResultsPlot | Method-level |
| matplotlib.pyplot | ~50ms | Level 2 | HdfPlot, HdfResultsPlot | Method-level |

## Implementation Pattern

### Module-Level Imports (Level 1)
At the top of each HDF class file:

```python
"""Module docstring."""

# Standard library (always loaded)
from pathlib import Path
from typing import List, Dict, Optional, TYPE_CHECKING
import logging

# Core scientific (always loaded)
import h5py
import numpy as np
import pandas as pd

# Type hints only - NOT loaded at runtime
if TYPE_CHECKING:
    from geopandas import GeoDataFrame
    from shapely.geometry import Point, Polygon, LineString

# Internal imports (minimal overhead)
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)
```

**Key Pattern**: `TYPE_CHECKING` block allows type hints without import overhead.

### Method-Level Imports (Level 2)
Inside each method that needs heavy dependencies:

```python
@staticmethod
@standardize_input(file_type='plan_hdf')
def get_mesh_cell_polygons(hdf_path: Path) -> 'GeoDataFrame':
    """
    Return 2D flow mesh cell polygons.

    Returns:
        GeoDataFrame: Cell polygons with geometry and attributes.
    """
    # Lazy imports for geometry operations
    from geopandas import GeoDataFrame
    from shapely.geometry import Polygon
    from shapely.ops import polygonize

    # Rest of method implementation
    try:
        with h5py.File(hdf_path, 'r') as hdf_file:
            # ... create polygons
            return GeoDataFrame(...)
    except Exception as e:
        logger.error(f"Error: {e}")
        return GeoDataFrame()
```

**Benefits**:
1. Type hint `'GeoDataFrame'` (string) in signature - no import needed
2. Actual import only happens when method is called
3. Subsequent calls reuse already-loaded module (no overhead)

### Conditional Imports (Level 3)
For optional performance features:

```python
@staticmethod
def find_nearest_cell(hdf_path: Path, point, mesh_name: str) -> dict:
    from geopandas import GeoDataFrame
    from shapely.geometry import Point

    cells = get_mesh_cell_points(hdf_path, mesh_name)

    # Only use spatial index for large datasets
    if len(cells) > 1000:
        # Lazy load scipy for KDTree spatial index
        from scipy.spatial import KDTree

        coords = np.array([[p.x, p.y] for p in cells.geometry])
        tree = KDTree(coords)
        dist, idx = tree.query([point.x, point.y])
        return cells.iloc[idx].to_dict()
    else:
        # Simple distance calculation (no scipy)
        cells['distance'] = cells.geometry.distance(point)
        return cells.loc[cells['distance'].idxmin()].to_dict()
```

**Benefits**:
1. Small datasets avoid scipy overhead entirely
2. Large datasets get performance benefit of KDTree
3. User doesn't need to decide - automatic optimization

## Import Order and Dependencies

### Dependency Graph

```
Level 1 (Module Import):
  h5py (no deps)
  numpy (no deps)
  pandas (depends on numpy)
    ↓
Level 2 (Method Call):
  shapely (depends on numpy)
  geopandas (depends on pandas, shapely, numpy)
  xarray (depends on numpy, pandas)
  matplotlib (depends on numpy)
    ↓
Level 3 (Conditional):
  scipy (depends on numpy)
```

### Safe Import Order
When lazy loading multiple dependencies in a method:

```python
def method_with_many_deps(hdf_path: Path) -> 'GeoDataFrame':
    # Import in dependency order (safest, though Python handles cycles)
    import numpy as np  # Already loaded (Level 1), but explicit
    from shapely.geometry import Polygon  # Requires numpy
    from geopandas import GeoDataFrame    # Requires shapely, pandas, numpy

    # Method implementation
```

**Note**: In practice, order doesn't matter much because:
1. numpy/pandas already loaded (Level 1)
2. Python's import system handles circular dependencies
3. Each module imported only once per interpreter session

## Type Hints Without Import Overhead

### String Annotations (Python 3.7+)
Use string type hints to avoid imports:

```python
def get_mesh_areas(hdf_path: Path) -> 'GeoDataFrame':
    from geopandas import GeoDataFrame
    # ... implementation
```

**Why it works**: String annotations aren't evaluated at import time, only by type checkers.

### TYPE_CHECKING Block (Python 3.5+)
For multiple type hints:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from geopandas import GeoDataFrame
    from shapely.geometry import Point, Polygon, LineString

# Now can use in type hints without import overhead
def method(point: Point) -> 'GeoDataFrame':
    from geopandas import GeoDataFrame
    from shapely.geometry import Point
    # ... implementation
```

**Why it works**: `TYPE_CHECKING` is `False` at runtime, `True` for type checkers.

## Performance Measurements

### Import Time Comparison

**Without Lazy Loading** (all imports at module level):
```python
import ras_commander.hdf  # 750ms first time
```

**With Lazy Loading** (current implementation):
```python
import ras_commander.hdf  # 170ms first time

# First method call with geopandas
HdfMesh.get_mesh_cell_polygons("file.hdf")  # +200ms (one-time)

# Subsequent calls
HdfMesh.get_mesh_cell_polygons("file.hdf")  # 0ms overhead
```

### Memory Footprint

**Without Lazy Loading**:
- All dependencies loaded: ~150MB memory
- Even if never used

**With Lazy Loading**:
- Core only: ~50MB memory
- After using geometry methods: ~100MB
- After using visualization: ~150MB
- Only loads what's used

## Best Practices for Adding New Methods

### 1. Use String Type Hints
```python
def new_method(hdf_path: Path) -> 'GeoDataFrame':
    # Implementation
```

### 2. Lazy Import Heavy Dependencies
```python
def new_method(hdf_path: Path) -> 'GeoDataFrame':
    from geopandas import GeoDataFrame  # Lazy load
    from shapely.geometry import Polygon
    # Implementation
```

### 3. Add TYPE_CHECKING Import for IDE Support
```python
# At module level
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from geopandas import GeoDataFrame

# In method
def new_method(hdf_path: Path) -> 'GeoDataFrame':
    from geopandas import GeoDataFrame  # Still need runtime import
```

### 4. Consider Conditional Loading
```python
def new_method(hdf_path: Path, use_advanced: bool = False):
    from geopandas import GeoDataFrame

    if use_advanced:
        from scipy.spatial import KDTree  # Only if needed
        # Advanced implementation
    else:
        # Simple implementation (no scipy)
```

## Common Pitfalls

### ❌ Don't: Import at Module Level for Lazy Loaded Deps
```python
# At top of file
import geopandas as gpd  # BAD - loads at import time

def method():
    return gpd.GeoDataFrame(...)
```

### ✅ Do: Import Inside Methods
```python
# At top of file - only TYPE_CHECKING
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from geopandas import GeoDataFrame

def method() -> 'GeoDataFrame':
    from geopandas import GeoDataFrame  # GOOD - lazy load
    return GeoDataFrame(...)
```

### ❌ Don't: Import Inside Loops
```python
def method():
    for i in range(1000):
        from geopandas import GeoDataFrame  # BAD - wasteful (though cached)
```

### ✅ Do: Import Once at Method Level
```python
def method():
    from geopandas import GeoDataFrame  # GOOD - once per method call

    for i in range(1000):
        # Use GeoDataFrame
```

## Testing Lazy Loading

### Verify Import Time
```python
import time

# Test module import
start = time.time()
import ras_commander.hdf
print(f"Module import: {(time.time() - start) * 1000:.0f}ms")

# Test first method call
start = time.time()
from ras_commander import HdfMesh
cells = HdfMesh.get_mesh_cell_polygons("file.hdf")
print(f"First call: {(time.time() - start) * 1000:.0f}ms")

# Test subsequent call
start = time.time()
cells = HdfMesh.get_mesh_cell_polygons("file.hdf")
print(f"Second call: {(time.time() - start) * 1000:.0f}ms")
```

**Expected output**:
```
Module import: 170ms
First call: 450ms (includes geopandas load + execution)
Second call: 250ms (execution only, geopandas cached)
```

### Verify Memory Usage
```python
import sys
import psutil

# Before import
process = psutil.Process()
mem_before = process.memory_info().rss / 1024 / 1024

import ras_commander.hdf
mem_after_import = process.memory_info().rss / 1024 / 1024

from ras_commander import HdfMesh
HdfMesh.get_mesh_cell_polygons("file.hdf")
mem_after_call = process.memory_info().rss / 1024 / 1024

print(f"Import overhead: {mem_after_import - mem_before:.0f}MB")
print(f"Method call overhead: {mem_after_call - mem_after_import:.0f}MB")
```
