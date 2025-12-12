# RASMapper Sloped (Cell Corners) - Vertex WSE Formula Analysis

## Summary

This document summarizes extensive research into how RASMapper computes vertex Water Surface Elevation (WSE) values in "Sloped (Cell Corners)" rendering mode.

**Key Finding**: The exact algorithm has not been fully reverse-engineered. The best approximation achieves ~84% match within 0.01 ft, but fails to achieve exact replication.

---

## Best Formula Found

### Cell-Based Min/Max Blend (alpha = 0.73)

```
corner_wse = 0.27 * wse_min + 0.73 * wse_max
```

Where:
- `wse_min` = minimum WSE of adjacent cells
- `wse_max` = maximum WSE of adjacent cells

**Performance:**
| Metric | Value |
|--------|-------|
| Match < 0.01 ft | **83.9%** |
| Match < 0.05 ft | 96.5% |
| Match < 0.10 ft | 97.7% |
| RMSE | 0.1396 ft |

### By Vertex Type

| Vertex Type | Count | Best Alpha | Match < 0.01 |
|-------------|-------|------------|--------------|
| 4-cell (interior) | 9,473 | 0.74 | 86.0% |
| 3-cell (T-junction) | 540 | 0.93 | 55.1% |
| 2-cell (boundary) | 18 | 0.87 | 72.2% |

### By WSE Range (Critical Factor)

| WSE Range | Count | Match < 0.01 | Comment |
|-----------|-------|--------------|---------|
| < 0.01 ft | 3,327 | **99.8%** | Uniform regions |
| 0.01-0.05 ft | 2,167 | **99.2%** | Near-uniform |
| 0.05-0.2 ft | 2,431 | 85.2% | Moderate gradient |
| 0.2-0.5 ft | 1,542 | 50.6% | High gradient |
| 0.5-2 ft | 503 | 20.9% | Steep gradient |
| > 2 ft | 73 | 1.4% | Very steep |

**Key Insight**: The formula works well for uniform and low-gradient areas (99%+ match), but fails in high-gradient areas (<50% match).

---

## Alternative Formulas Tested

### Face-Based Two-Stage Algorithm

Stage 1: Compute face WSE = average of two adjacent cells
Stage 2: Compute corner = blend of min/max face values

```
face_wse = (cell_A + cell_B) / 2
corner_wse = 0.27 * face_min + 0.73 * face_max
```

**Result**: 72.7% match < 0.01 ft, RMSE = 0.0860 (slightly worse than cell-based)

### Depth-Based Formulas

Various depth-based formulas were tested based on user insight about "half depth" when one cell is below terrain:

| Formula | Match < 0.01 | RMSE | Comment |
|---------|--------------|------|---------|
| Terrain + half max depth | 3.1% | 13.8 ft | Does not work |
| Terrain + half avg depth | 8.4% | 13.1 ft | Does not work |
| Depth-weighted WSE | 49.1% | 0.11 ft | Same as simple avg |
| Half-depth at faces | 42.5% | 2.09 ft | Makes things worse |

### IDW Interpolation

| Power | Match < 0.01 | Comment |
|-------|--------------|---------|
| 0 (simple avg) | 49.0% | Baseline |
| 1.0 | 49.1% | No improvement |
| 2.0 | 49.1% | No improvement |

IDW doesn't help because all vertices have equal distance (176.8 ft) to adjacent cells in this regular mesh.

### Adaptive Alpha Formulas

| Condition | Alpha | Combined Match |
|-----------|-------|----------------|
| Depth 0-2 ft | 0.63 | 83.8% |
| Depth 2-5 ft | 0.72 | (depth-adaptive) |
| Depth 5+ ft | 0.74 | |
| 4-cell vertex | 0.74 | 85.0% |
| 3-cell vertex | 0.90 | (type-adaptive) |
| 2-cell vertex | 0.87 | |

Type-adaptive slightly improves to 85.0% match.

---

## Analysis of Mismatches

The 16.1% of vertices that don't match < 0.01 ft share these characteristics:

1. **WSE Range > 0.2 ft**: 76% of mismatches have high gradient
2. **3-cell vertices**: 51.5% mismatch rate vs 14.0% for 4-cell
3. **Shallow depth (0-2 ft)**: 34.7% mismatch rate vs 11.7% for deep (20+ ft)

### Error Direction
- Over-prediction (pred > GT): 40.3% — observed alpha ≈ 0.62
- Under-prediction (pred < GT): 59.7% — observed alpha ≈ 0.85

This suggests the true alpha varies spatially, which our fixed formula cannot capture.

---

## What Doesn't Work

1. **Half-depth formulas**: Applying "terrain + depth/2" universally produces terrible results
2. **IDW interpolation**: No improvement over simple average for regular meshes
3. **Face-based half-depth**: Making faces depth-aware makes results worse
4. **Global Delaunay TIN**: Creates wrong triangles that cross cell boundaries
5. **Single fixed alpha**: Cannot capture the variation in high-gradient areas

---

## Hypotheses for Further Investigation

1. **RASMapper Settings**: The "UseDepthWeightedFaces" and "ReduceShallowToHorizontal" options may involve additional logic not captured here

2. **Cell Geometry Factors**: The formula may depend on cell shape, face lengths, or angles

3. **Post-Processing**: There may be smoothing or clamping applied after initial interpolation

4. **Gradient-Dependent Algorithm**: High-gradient areas may use a fundamentally different algorithm

5. **The "half depth" rule**: The user's insight about using "half the depth when one cell is below terrain" may apply only to specific edge cases at mesh boundaries, not universally

---

## Recommended Implementation

For practical use, implement the best available approximation:

```python
def compute_vertex_wse(adjacent_cell_wses: List[float]) -> float:
    """
    Compute vertex WSE using the best-fit formula.

    Args:
        adjacent_cell_wses: List of WSE values from adjacent cells (wet cells only)

    Returns:
        Interpolated WSE value at the vertex

    Note:
        This achieves ~84% match within 0.01 ft for uniform/low-gradient areas.
        High-gradient areas (WSE range > 0.2 ft) have lower accuracy.
    """
    if len(adjacent_cell_wses) == 0:
        return float('nan')
    if len(adjacent_cell_wses) == 1:
        return adjacent_cell_wses[0]

    wse_min = min(adjacent_cell_wses)
    wse_max = max(adjacent_cell_wses)
    wse_range = wse_max - wse_min

    # For uniform regions, use simple average
    if wse_range < 0.01:
        return sum(adjacent_cell_wses) / len(adjacent_cell_wses)

    # For gradient regions, use alpha blend
    alpha = 0.73
    return (1 - alpha) * wse_min + alpha * wse_max
```

---

## Test Data

Analysis performed on:
- **Project**: BaldEagleCrkMulti2D - Sloped - Cell Corners
- **Plan**: p03 (Single 2D)
- **Ground Truth**: WSE (Max).Terrain50.dtm_20ft.tif
- **Vertices Analyzed**: 10,043 (from HDF FacePoints)
- **Mesh Type**: Regular 250 ft grid

---

## Conclusion

**The exact RASMapper "Sloped (Cell Corners)" algorithm has not been fully reverse-engineered.**

The best approximation (alpha=0.73 min/max blend) achieves:
- 99%+ match in uniform/low-gradient regions
- ~84% overall match within 0.01 ft
- ~42% match in high-gradient areas (WSE range > 0.2 ft)

To achieve exact replication (>99% match everywhere), additional research is needed to understand:
1. The depth-dependent logic suggested by documentation
2. How RASMapper handles high-gradient transitions
3. Any post-processing or smoothing steps applied

For most practical applications, the implemented formula provides acceptable results. For exact replication of RASMapper output, using RASMapper itself remains the only guaranteed solution.
