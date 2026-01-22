# HDF Subpackage - Developer Guidance

This document provides guidance for AI agents and developers working with the `ras_commander.hdf` subpackage.

## Overview

The HDF subpackage provides comprehensive HDF5 file operations for HEC-RAS plan files (.p##.hdf) and geometry files (.g##.hdf). It contains 18 classes organized by function.

## Module Structure

```
ras_commander/hdf/
├── __init__.py              # Public API exports
├── AGENTS.md                # This file
│
├── # Core
├── HdfBase.py               # Foundation class
├── HdfUtils.py              # Utility functions
├── HdfPlan.py               # Plan file info
│
├── # Geometry
├── HdfMesh.py               # 2D mesh operations
├── HdfXsec.py               # Cross-section geometry
├── HdfBndry.py              # Boundary features
├── HdfStruc.py              # Structure geometry (2D)
├── HdfHydraulicTables.py    # HTAB extraction
│
├── # Results
├── HdfResultsPlan.py        # Plan results (steady/unsteady)
├── HdfResultsMesh.py        # Mesh results
├── HdfResultsXsec.py        # XS results
├── HdfResultsBreach.py      # Breach results
│
├── # Infrastructure
├── HdfPipe.py               # Pipe networks
├── HdfPump.py               # Pump stations
├── HdfInfiltration.py       # Infiltration parameters
│
├── # Visualization
├── HdfPlot.py               # General plotting
├── HdfResultsPlot.py        # Results visualization
│
└── # Analysis
    ├── HdfBenefitAreas.py    # 2D benefit area polygons (WSE reduction analysis)
    └── HdfFluvialPluvial.py  # Fluvial-pluvial analysis
```

## Lazy Loading Pattern

Heavy dependencies are lazy-loaded inside methods to reduce import overhead:

### Dependencies by Category

| Dependency | Import Time | Used In |
|------------|-------------|---------|
| **Core (always loaded)** | | |
| h5py | ~20ms | All classes |
| numpy | ~50ms | All classes |
| pandas | ~100ms | All classes |
| **Lazy Loaded** | | |
| geopandas | ~200ms | HdfMesh, HdfXsec, HdfBndry, HdfStruc, HdfPipe, HdfPump |
| shapely | ~50ms | HdfMesh, HdfXsec, HdfBndry, HdfBase |
| xarray | ~100ms | HdfResultsMesh, HdfResultsXsec, HdfPipe, HdfPump |
| matplotlib | ~300ms | HdfPlot, HdfResultsPlot |
| scipy | ~150ms | HdfUtils (KDTree only) |

### Implementation Pattern

```python
# At module level - only core dependencies
import h5py
import numpy as np
import pandas as pd
from typing import TYPE_CHECKING

# Type hints only - not imported at runtime
if TYPE_CHECKING:
    from geopandas import GeoDataFrame

# Inside methods - lazy load heavy dependencies
@staticmethod
def get_mesh_cell_polygons(hdf_path: Path) -> 'GeoDataFrame':
    # Lazy imports for heavy dependencies
    from geopandas import GeoDataFrame
    from shapely.geometry import Polygon
    from shapely.ops import polygonize

    # Method implementation...
    return GeoDataFrame(...)
```

## Class Hierarchy

```
HdfBase (foundation)
  ├── HdfMesh (uses HdfBase)
  ├── HdfPlan (uses HdfBase)
  ├── HdfXsec (uses HdfBase)
  ├── HdfBndry (uses HdfBase)
  ├── HdfStruc (uses HdfBase, HdfXsec)
  ├── HdfResultsMesh (uses HdfBase, HdfMesh)
  ├── HdfResultsPlan (uses HdfBase)
  ├── HdfResultsXsec (uses HdfBase)
  ├── HdfResultsBreach (uses HdfBase)
  ├── HdfBenefitAreas (uses HdfMesh, HdfResultsMesh)
  ├── HdfFluvialPluvial (uses HdfMesh, HdfResultsMesh)
  └── HdfUtils (standalone utilities)

Specialized:
  ├── HdfPipe (standalone)
  ├── HdfPump (standalone)
  ├── HdfInfiltration (standalone)
  ├── HdfHydraulicTables (standalone)
  ├── HdfPlot (visualization)
  └── HdfResultsPlot (visualization)
```

## Import Patterns

### From Parent Package (Recommended)
```python
from ras_commander import HdfResultsPlan, HdfMesh

wse = HdfResultsPlan.get_steady_wse("plan.hdf")
cells = HdfMesh.get_mesh_cell_polygons("plan.hdf")
```

### From Subpackage (Direct)
```python
from ras_commander.hdf import HdfResultsPlan, HdfMesh
```

## Decorator Usage

All public methods use consistent decorators:

1. **`@staticmethod`** - All methods are static
2. **`@log_call`** - Automatic function call logging
3. **`@standardize_input(file_type='plan_hdf'|'geom_hdf')`** - Input path standardization

### File Type Expectations

| file_type | Extension | Classes |
|-----------|-----------|---------|
| `plan_hdf` | .p##.hdf | HdfResultsPlan, HdfResultsMesh, HdfResultsXsec, HdfResultsBreach |
| `geom_hdf` | .g##.hdf | HdfMesh, HdfXsec, HdfStruc, HdfBndry, HdfHydraulicTables |

## Adding New HDF Methods

When adding new methods:

1. **Use Decorators**:
   ```python
   @staticmethod
   @log_call
   @standardize_input(file_type='plan_hdf')
   def new_method(hdf_path: Path) -> pd.DataFrame:
   ```

2. **Lazy Load Heavy Dependencies**:
   ```python
   def get_something_with_geometry(hdf_path: Path) -> 'GeoDataFrame':
       from geopandas import GeoDataFrame
       from shapely.geometry import Polygon
       # ... method body
   ```

3. **Use h5py Context Manager**:
   ```python
   with h5py.File(hdf_path, 'r') as hdf_file:
       # Read data
       data = hdf_file["/some/path"][()]
   ```

4. **Handle Errors Gracefully**:
   ```python
   try:
       # HDF operations
   except Exception as e:
       logger.error(f"Error reading from {hdf_path}: {str(e)}")
       return pd.DataFrame()  # or GeoDataFrame() or {}
   ```

## Common HDF Paths

### Plan HDF (.p##.hdf)
```
/Results/Unsteady/Output/Output Blocks/...
/Results/Summary/...
/Plan Data/Plan Parameters
```

### Geometry HDF (.g##.hdf)
```
/Geometry/2D Flow Areas/{mesh_name}/...
/Geometry/Cross Sections/...
/Geometry/Structures/...
```

## Testing

Test import and basic functionality:
```python
from ras_commander import HdfMesh, HdfResultsPlan

# Check methods exist
assert hasattr(HdfMesh, 'get_mesh_cell_polygons')
assert hasattr(HdfResultsPlan, 'get_steady_wse')
```

## Version History

- **v0.80.0**: Initial HDF implementation
- **v0.80.3**: Added steady flow support
- **v0.81.0**: Added HdfHydraulicTables
- **v0.86.0**: Moved to `hdf/` subpackage with lazy loading
