# Sloped (Cell Corners) Interpolation Analysis

## Summary

The sloped interpolation mode in RASMapper creates a water surface that varies within each cell, producing a more realistic representation of the water surface gradient. This analysis documents the algorithm based on comparison with ground truth rasters.

## Key Findings

### 1. Cell Center WSE

The cell center uses the cell's WSE value directly. In uniform WSE regions (range < 0.01 ft between adjacent cells), GT matches cell center WSE with:
- Mean diff: -0.0003 ft
- RMSE: 0.0006 ft
- 93.1% match within 0.001 ft

### 2. Vertex (FacePoint) WSE Formula

At vertices (FacePoints), the GT WSE follows a **blend toward maximum** formula:

```
vertex_wse = (1 - alpha) * average + alpha * maximum
```

Where:
- `average` = mean WSE of adjacent wet cells
- `maximum` = max WSE of adjacent wet cells
- `alpha` ≈ 0.43-0.47 (optimized empirically)

This means the vertex WSE is positioned at approximately **74% of the way from min to max** (position 0.74 in [min, max] range).

### 3. Evidence for the Blend Formula

| Alpha | Mean Diff | RMSE | Match < 0.01 ft |
|-------|-----------|------|-----------------|
| 0.0 (simple avg) | -0.034 ft | 0.114 ft | 49% |
| 0.30 | -0.010 ft | 0.090 ft | 70% |
| 0.40 | -0.002 ft | 0.101 ft | 83% |
| 0.43 | +0.000 ft | 0.106 ft | 87% |
| 0.47 | +0.004 ft | 0.113 ft | 89% |

Alpha = 0.43 minimizes bias; alpha = 0.47 maximizes match rate.

### 4. Position Within [min, max] Range

Analysis of GT at vertices shows:
- Mean position: 0.741 (0 = min, 0.5 = avg, 1 = max)
- 83.6% of FacePoints have position between 0.6-0.8
- Position is consistent across WSE ranges (~0.74)
- 99.7% of GT values fall within [min, max] of adjacent cells

### 5. Interpolation Method

Within each cell:
1. Cell center has cell's WSE value
2. Vertices have blended WSE (0.57*avg + 0.43*max)
3. Triangulate from center to each pair of adjacent vertices
4. Use barycentric interpolation within triangles

### 6. Performance Results

**With simple average at vertices (alpha = 0):**
- RMSE: 0.173 ft
- MAE: 0.038 ft
- Mean diff: -0.036 ft (GT consistently higher)
- Match < 0.05 ft: 79%

**With blended formula (alpha = 0.43):**
- RMSE: 0.123 ft
- MAE: 0.020 ft
- Mean diff: -0.013 ft
- Match < 0.05 ft: 93%
- Match < 0.10 ft: 97%

### 7. Error Correlation

Error is directly proportional to WSE gradient:

| Gradient Range | Mean Diff | RMSE |
|----------------|-----------|------|
| 0.000-0.001 | -0.006 ft | 0.178 ft |
| 0.001-0.010 | -0.015 ft | 0.023 ft |
| 0.010-0.050 | -0.082 ft | 0.096 ft |
| 0.050-0.100 | -0.235 ft | 0.279 ft |
| 0.100-0.500 | -0.493 ft | 0.829 ft |

## Remaining Uncertainties

1. **Edge cases**: Large outliers (8+ ft difference) occur in steep gradient areas
2. **"Depth-weighted faces"**: The RASMapper option mentions this, but simple blend toward max performs well
3. **Shallow reduction**: RASMapper may have special handling for shallow cells

## Implementation Notes

The algorithm can be implemented using:
1. HdfMesh functions to get cell polygons and centers
2. HdfResultsMesh to get cell WSE values
3. HDF FacePoints data for accurate vertex locations
4. Barycentric interpolation within center-vertex triangles

## Files Created

- `wse_sloped_alpha0.43.tif` - Best-performing raster with blended vertex formula
- `wse_center_plus_vertices.tif` - Simple average at vertices
- `wse_global_tin.tif` - Global TIN with cell centers + FacePoints
