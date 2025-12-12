# Filter Features System

This document describes RASMapper's filter features system, which allows filtering features by attribute values and filtering polygon geometry through simplification algorithms.

---

## Overview

RASMapper provides two distinct filtering capabilities:

1. **Attribute Filtering** - Filter features based on column values (equals, contains, greater than, etc.)
2. **Polygon Simplification** - Reduce polygon vertex count using Douglas-Peucker-Ramer or Minimum Area Reduction algorithms

---

## Attribute Filtering

### Filter<T> Generic Class

**File**: `RasMapperLib/Filter.cs`

```csharp
public class Filter<T>
{
    public string ColumnName;     // Column/attribute name to filter on
    public T Value;               // Value to compare against
    public FilterOperation Operation;  // Comparison operation
    public bool AndBool;          // True = AND with previous, False = OR
    public bool IsDBNull;         // Check for null values
}
```

### FilterOperation Enum

**File**: `RasMapperLib/FilterOperation.cs`

```csharp
public enum FilterOperation
{
    EqualNumeric,   // Numeric equality (==)
    LessThan,       // <
    LTE,            // <=
    GreaterThan,    // >
    GTE,            // >=
    Equals,         // String equality
    Contains,       // String contains
    StartsWith,     // String starts with
    EndsWith        // String ends with
}
```

### FilterBuilderForm UI Mapping

**File**: `RasMapperLib/FilterBuilderForm.cs`

The UI provides these user-friendly operation names:

| UI Display | FilterOperation | Applies To |
|------------|-----------------|------------|
| "= (numeric)" | EqualNumeric | Numbers |
| "< (less than)" | LessThan | Numbers |
| "<= (less than or equal)" | LTE | Numbers |
| "> (greater than)" | GreaterThan | Numbers |
| ">= (greater than or equal)" | GTE | Numbers |
| "= (text, exact match)" | Equals | Strings |
| "contains" | Contains | Strings |
| "starts with" | StartsWith | Strings |
| "ends with" | EndsWith | Strings |

### Multiple Filter Combination

Filters can be combined using AND/OR logic:

```csharp
// Example: (Area > 1000) AND (Name contains "River")
var filters = new List<Filter<object>>
{
    new Filter<object>
    {
        ColumnName = "Area",
        Value = 1000.0,
        Operation = FilterOperation.GreaterThan,
        AndBool = true  // First filter, AND is default
    },
    new Filter<object>
    {
        ColumnName = "Name",
        Value = "River",
        Operation = FilterOperation.Contains,
        AndBool = true  // AND with previous filter
    }
};
```

---

## Polygon Simplification

### ExportFilteredPolygons Class

**File**: `RasMapperLib/ExportFilteredPolygons.cs`

Provides three polygon simplification methods accessible from the UI:

### Method 1: Douglas-Peucker-Ramer by Tolerance

Simplifies polygon by removing vertices within a tolerance distance from the simplified line.

```csharp
// UI selection: "Douglas-Peucker-Ramer (by tolerance)"
// User input: tolerance value (in coordinate units)
polygon = polygon.FilterXY(tolerance);
```

**Algorithm**: Classic Douglas-Peucker algorithm
- Larger tolerance = more simplification, fewer vertices
- Preserves overall shape within tolerance distance
- Good for reducing file size while maintaining shape accuracy

### Method 2: Douglas-Peucker-Ramer by Target Point Count

Iteratively adjusts tolerance to achieve a target number of vertices.

```csharp
// UI selection: "Douglas-Peucker-Ramer (by point count)"
// User inputs: maximum points, maximum tolerance
polygon = polygon.FilterXYIterative(maxPoints, maxTolerance);
```

**Algorithm**: Binary search on tolerance to hit target point count
- Guarantees maximum vertex count
- `maxTolerance` caps how much simplification is allowed
- Useful when you need a specific level of detail

### Method 3: Minimum Area Reduction

Removes vertices that create the smallest triangular area when removed.

```csharp
// UI selection: "Minimum Area Reduction"
// User input: target point count
polygon = polygon.FilterByArea(targetPoints);
```

**Algorithm**: Visvalingam-Whyatt algorithm variant
- Iteratively removes vertex with smallest effective area
- Preserves significant features better than Douglas-Peucker for some shapes
- Good for cartographic generalization

---

## UI Dialog Flow

From `ExportFilteredPolygons.ShowDialog()`:

1. **Step 1**: Select filter method from dropdown
   - "Douglas-Peucker-Ramer (by tolerance)"
   - "Douglas-Peucker-Ramer (by point count)"
   - "Minimum Area Reduction"

2. **Step 2**: Enter parameters based on method
   - Tolerance (for method 1)
   - Max points + max tolerance (for method 2)
   - Target points (for method 3)

3. **Step 3**: Click OK to apply filter

4. **Result**: Filtered polygon returned for export

---

## Python Implementation for ras-commander

### Attribute Filtering

```python
from enum import Enum
from dataclasses import dataclass
from typing import Any, List
import geopandas as gpd

class FilterOperation(Enum):
    """Filter operations matching RASMapper's FilterOperation enum."""
    EQUAL_NUMERIC = "equal_numeric"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "lte"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "gte"
    EQUALS = "equals"  # String exact match
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"

@dataclass
class Filter:
    """Attribute filter matching RASMapper's Filter<T> class."""
    column_name: str
    value: Any
    operation: FilterOperation
    and_bool: bool = True  # True = AND, False = OR
    is_null: bool = False

def apply_filter(gdf: gpd.GeoDataFrame, filter: Filter) -> gpd.Series:
    """
    Apply a single filter to a GeoDataFrame, returning boolean mask.

    Args:
        gdf: GeoDataFrame to filter
        filter: Filter specification

    Returns:
        Boolean Series indicating which rows match
    """
    col = gdf[filter.column_name]

    if filter.is_null:
        return col.isna()

    match filter.operation:
        case FilterOperation.EQUAL_NUMERIC:
            return col == filter.value
        case FilterOperation.LESS_THAN:
            return col < filter.value
        case FilterOperation.LESS_THAN_OR_EQUAL:
            return col <= filter.value
        case FilterOperation.GREATER_THAN:
            return col > filter.value
        case FilterOperation.GREATER_THAN_OR_EQUAL:
            return col >= filter.value
        case FilterOperation.EQUALS:
            return col.astype(str) == str(filter.value)
        case FilterOperation.CONTAINS:
            return col.astype(str).str.contains(str(filter.value), na=False)
        case FilterOperation.STARTS_WITH:
            return col.astype(str).str.startswith(str(filter.value), na=False)
        case FilterOperation.ENDS_WITH:
            return col.astype(str).str.endswith(str(filter.value), na=False)

def apply_filters(gdf: gpd.GeoDataFrame, filters: List[Filter]) -> gpd.GeoDataFrame:
    """
    Apply multiple filters to a GeoDataFrame with AND/OR logic.

    Args:
        gdf: GeoDataFrame to filter
        filters: List of Filter specifications

    Returns:
        Filtered GeoDataFrame
    """
    if not filters:
        return gdf

    # Start with first filter
    combined_mask = apply_filter(gdf, filters[0])

    # Apply subsequent filters with AND/OR logic
    for f in filters[1:]:
        mask = apply_filter(gdf, f)
        if f.and_bool:
            combined_mask = combined_mask & mask
        else:
            combined_mask = combined_mask | mask

    return gdf[combined_mask].copy()
```

### Polygon Simplification

```python
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform
import numpy as np

def simplify_douglas_peucker(polygon: Polygon, tolerance: float) -> Polygon:
    """
    Simplify polygon using Douglas-Peucker algorithm (by tolerance).

    Matches RASMapper's polygon.FilterXY(tolerance) method.

    Args:
        polygon: Shapely Polygon to simplify
        tolerance: Maximum distance from simplified line (in coordinate units)

    Returns:
        Simplified Polygon
    """
    return polygon.simplify(tolerance, preserve_topology=True)

def simplify_douglas_peucker_target_points(
    polygon: Polygon,
    max_points: int,
    max_tolerance: float
) -> Polygon:
    """
    Simplify polygon to target point count using iterative Douglas-Peucker.

    Matches RASMapper's polygon.FilterXYIterative(maxPoints, maxTolerance) method.
    Uses binary search to find tolerance that achieves target point count.

    Args:
        polygon: Shapely Polygon to simplify
        max_points: Target maximum number of vertices
        max_tolerance: Maximum allowed tolerance (caps simplification)

    Returns:
        Simplified Polygon with at most max_points vertices
    """
    # Get current point count
    current_points = len(polygon.exterior.coords)

    if current_points <= max_points:
        return polygon

    # Binary search for optimal tolerance
    low_tol = 0.0
    high_tol = max_tolerance
    best_result = polygon

    for _ in range(20):  # Max iterations for convergence
        mid_tol = (low_tol + high_tol) / 2
        simplified = polygon.simplify(mid_tol, preserve_topology=True)
        point_count = len(simplified.exterior.coords)

        if point_count <= max_points:
            best_result = simplified
            high_tol = mid_tol  # Try less simplification
        else:
            low_tol = mid_tol  # Need more simplification

        # Check convergence
        if high_tol - low_tol < max_tolerance * 0.001:
            break

    return best_result

def simplify_minimum_area(polygon: Polygon, target_points: int) -> Polygon:
    """
    Simplify polygon using Minimum Area Reduction (Visvalingam-Whyatt).

    Matches RASMapper's polygon.FilterByArea(targetPoints) method.
    Iteratively removes vertex that creates smallest triangular area.

    Args:
        polygon: Shapely Polygon to simplify
        target_points: Target number of vertices

    Returns:
        Simplified Polygon with approximately target_points vertices

    Note:
        This is a simplified implementation. For production use, consider
        using the `simplification` library which has optimized Visvalingam.
    """
    coords = list(polygon.exterior.coords)[:-1]  # Remove closing point

    if len(coords) <= target_points:
        return polygon

    def triangle_area(p1, p2, p3):
        """Calculate area of triangle formed by three points."""
        return abs((p2[0] - p1[0]) * (p3[1] - p1[1]) -
                   (p3[0] - p1[0]) * (p2[1] - p1[1])) / 2

    while len(coords) > target_points:
        # Calculate effective area for each point
        areas = []
        n = len(coords)
        for i in range(n):
            p1 = coords[(i - 1) % n]
            p2 = coords[i]
            p3 = coords[(i + 1) % n]
            areas.append(triangle_area(p1, p2, p3))

        # Remove point with minimum area
        min_idx = np.argmin(areas)
        coords.pop(min_idx)

    # Close the ring
    coords.append(coords[0])
    return Polygon(coords)

# Convenience function matching RASMapper's UI
def filter_polygon(
    polygon: Polygon,
    method: str,
    tolerance: float = None,
    max_points: int = None,
    max_tolerance: float = None,
    target_points: int = None
) -> Polygon:
    """
    Filter/simplify polygon using specified method.

    Matches RASMapper's ExportFilteredPolygons dialog options.

    Args:
        polygon: Shapely Polygon to simplify
        method: One of:
            - "douglas_peucker_tolerance"
            - "douglas_peucker_points"
            - "minimum_area"
        tolerance: For douglas_peucker_tolerance method
        max_points: For douglas_peucker_points method
        max_tolerance: For douglas_peucker_points method
        target_points: For minimum_area method

    Returns:
        Simplified Polygon
    """
    match method:
        case "douglas_peucker_tolerance":
            if tolerance is None:
                raise ValueError("tolerance required for douglas_peucker_tolerance")
            return simplify_douglas_peucker(polygon, tolerance)

        case "douglas_peucker_points":
            if max_points is None or max_tolerance is None:
                raise ValueError("max_points and max_tolerance required")
            return simplify_douglas_peucker_target_points(polygon, max_points, max_tolerance)

        case "minimum_area":
            if target_points is None:
                raise ValueError("target_points required for minimum_area")
            return simplify_minimum_area(polygon, target_points)

        case _:
            raise ValueError(f"Unknown method: {method}")
```

### Usage Examples

```python
import geopandas as gpd
from shapely.geometry import Polygon

# === Attribute Filtering ===

# Load features
gdf = gpd.read_file("features.shp")

# Filter: Area > 1000 AND Name contains "River"
filters = [
    Filter("Area", 1000.0, FilterOperation.GREATER_THAN),
    Filter("Name", "River", FilterOperation.CONTAINS, and_bool=True),
]
filtered_gdf = apply_filters(gdf, filters)

# Filter: Status = "Active" OR Priority >= 5
filters = [
    Filter("Status", "Active", FilterOperation.EQUALS),
    Filter("Priority", 5, FilterOperation.GREATER_THAN_OR_EQUAL, and_bool=False),
]
filtered_gdf = apply_filters(gdf, filters)

# === Polygon Simplification ===

polygon = Polygon([(0, 0), (1, 0.1), (2, 0), (2, 2), (1, 1.9), (0, 2), (0, 0)])

# Method 1: Douglas-Peucker by tolerance
simplified = filter_polygon(polygon, "douglas_peucker_tolerance", tolerance=0.5)

# Method 2: Douglas-Peucker by target point count
simplified = filter_polygon(polygon, "douglas_peucker_points",
                           max_points=50, max_tolerance=10.0)

# Method 3: Minimum Area Reduction
simplified = filter_polygon(polygon, "minimum_area", target_points=50)

# Apply to GeoDataFrame
gdf["geometry"] = gdf["geometry"].apply(
    lambda g: filter_polygon(g, "douglas_peucker_tolerance", tolerance=1.0)
    if isinstance(g, Polygon) else g
)
```

---

## Integration with ras-commander

### Proposed Module Structure

```
ras_commander/
├── filtering/
│   ├── __init__.py
│   ├── attribute_filter.py   # Filter class and apply_filters()
│   └── polygon_filter.py     # Polygon simplification functions
```

### Proposed API

```python
from ras_commander import RasFilter

# Attribute filtering
filtered_df = RasFilter.filter_features(
    gdf,
    [
        {"column": "Area", "op": ">", "value": 1000},
        {"column": "Name", "op": "contains", "value": "River"},
    ]
)

# Polygon simplification
simplified_gdf = RasFilter.simplify_polygons(
    gdf,
    method="douglas_peucker",
    tolerance=5.0
)

# Or target point count
simplified_gdf = RasFilter.simplify_polygons(
    gdf,
    method="douglas_peucker",
    max_points=100,
    max_tolerance=50.0
)

# Minimum area reduction
simplified_gdf = RasFilter.simplify_polygons(
    gdf,
    method="minimum_area",
    target_points=100
)
```

---

## Source File References

| File | Description |
|------|-------------|
| `RasMapperLib/Filter.cs` | Generic Filter<T> class |
| `RasMapperLib/FilterOperation.cs` | FilterOperation enum |
| `RasMapperLib/FilterBuilderForm.cs` | UI dialog for building filters |
| `RasMapperLib/ExportFilteredPolygons.cs` | Polygon simplification methods |
| `RasMapperLib/Polygon.cs` | FilterXY, FilterXYIterative, FilterByArea methods |

---

*Generated: 2025-12-09*
*Source: RasMapperLib.dll decompilation*
