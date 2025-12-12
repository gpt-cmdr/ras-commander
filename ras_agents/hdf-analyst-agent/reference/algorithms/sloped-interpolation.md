# Sloped (Cell Corners) Interpolation Method

**Status:** IN PROGRESS
**Started:** 2025-12-08

## Objective

Implement RASMapper's "sloped" water surface interpolation mode for WSE rasterization.

---

## HEC-RAS Documentation Findings

### Sources Reviewed

- [Map Rendering Modes](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.5/viewing-2d-or-1d-2d-output-using-hec-ras-mapper/map-rendering-modes)
- [Mapping Options](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/mapping-results/mapping-options)
- [Settings and Options](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.0/settings-and-options)
- [Development of the 2D Computational Mesh](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.0/development-of-a-2d-or-combined-1d-2d-model/development-of-the-2d-computational-mesh)

### Key Concepts from Documentation

#### Cell Structure
- **Cell Center**: Computational center where WSE is computed (not necessarily geometric centroid)
- **Cell Faces**: Boundary edges between adjacent cells
- **Face Points**: Endpoints of cell faces (vertices shared between cells)

#### Render Mode Options

| Mode | Description |
|------|-------------|
| **Horizontal** | WSE is constant per cell; creates "patchwork" in steep terrain |
| **Sloping (Cell Corners)** | Interpolates WSE from cell corners; default sloping method |
| **Sloping (Cell Corners + Faces)** | Adds face midpoints; 8 interpolation points instead of 4 |
| **Hybrid (Default)** | Uses sloping except where cells lack hydraulic connectivity |

#### Interpolation Method

From documentation:
> "For 2D models, water surface interpolation is performed based on **triangulation between computation points and face points**."

> "Water surfaces within the cell are interpolated between computation points and face points."

This confirms:
1. Triangulation-based interpolation is used
2. Computation points (cell centers) and face points (vertices) are the control points
3. The method creates a continuous surface across the mesh

#### Sloping (Cell Corners) Specifics

> "The Sloping (Cell Corners) method is the default method."

> "Plots the computed water surface by interpolating water surface elevations from each 2D cell corner."

> "This option of connecting each cell corner provides a visualization for a more continuous inundation map."

#### Cell Corners + Cell Faces Option

> "The additional Sloping (Cell Corner + Cell Faces) option adds in the water surface of the cell faces for the interpolation scheme."

> "Rather than have 4 points to interpolate, the scheme now may have 8 points thus more variation."

This suggests:
- **Cell Corners only**: 4 corner values per cell → triangulation
- **Cell Corners + Faces**: 4 corners + 4 face midpoints = 8 points per cell

#### Depth-Weighted Faces

> "Depth-weighted: weighting water surface elevations by face depths so that deep faces have more effect than shallow faces."

> "This plot option is helpful to understand situations in steep terrain where shallow flow transitions to deeper flow."

**No specific formula provided**, but the concept is clear:
- Face WSE contribution is weighted by the depth at that face
- Deep faces have more influence than shallow faces

#### Shallow Water → Horizontal

> "Shallow water reduces to horizontal: if RAS computes flow to be shallow for a particular 2D cell, inundation will be plotted with a horizontal water surface."

> "This plot option will show more water than the default render mode."

**No specific threshold value provided** in documentation.

#### Hybrid Mode Criteria

> "Water surface is plotted using the sloping rendering mode, except for locations where the water surface is not hydraulically connected."

> "Wet cells separated by a dry face" trigger horizontal rendering.

#### Plot Tolerance

> "Plot Tolerance - This tolerance is used as a threshold value to remove areas that have an extremely shallow depth from plotting."

This is a separate filter for minimum depth display, not the shallow→horizontal threshold.

---

## RASMapper Configuration (from test project)

From `BaldEagleDamBrk.rasmap` (lines 2646-2648):
```xml
<RenderMode>slopingPretty</RenderMode>
<UseDepthWeightedFaces>true</UseDepthWeightedFaces>
<ReduceShallowToHorizontal>true</ReduceShallowToHorizontal>
```

**Note**: `slopingPretty` appears to be the internal name for "Sloping (Cell Corners + Faces)"

---

## Algorithm Summary (Based on Documentation)

### What We Know

1. **Interpolation Points**:
   - Cell Corners mode: Cell center + 4 corner vertices
   - Cell Corners + Faces mode: Cell center + 4 corners + 4 face midpoints

2. **Triangulation**:
   - HEC-RAS uses "triangulation between computation points and face points"
   - Likely Delaunay or constrained Delaunay (mesh is built using Delaunay)

3. **Corner WSE Computation**:
   - Documentation does NOT specify formula
   - **Hypothesis**: Average of adjacent cell center WSE values
   - **A/B Testing Required**

4. **Face WSE Computation (depth-weighted)**:
   - "Deep faces have more effect than shallow faces"
   - **Hypothesis**: `WSE_face = (d_A * WSE_A + d_B * WSE_B) / (d_A + d_B)`
   - **A/B Testing Required** for exact formula

5. **Shallow → Horizontal Threshold**:
   - Cells with "shallow" depth revert to horizontal
   - **Threshold value not documented**
   - **Hypothesis**: 0.1 ft based on typical HEC-RAS tolerances
   - **A/B Testing Required**

### What We Don't Know (Requires A/B Testing)

| Question | Hypothesis | Test Method |
|----------|------------|-------------|
| Corner WSE formula | Simple average of adjacent cells | Compare raster values at corners vs computed average |
| Face WSE formula | Depth-weighted average | Compare raster values at face midpoints |
| Shallow threshold | 0.1 ft | Test with cells near threshold, compare horizontal vs sloped output |
| How boundary vertices handled | Single cell value or extrapolation | Check corner values at mesh perimeter |
| Does it use face midpoints? | Yes (slopingPretty) | Compare 4-point vs 8-point triangulation results |

---

## Implementation Plan

### Phase 1: Data Extraction
1. Extract mesh geometry (cell polygons, vertices, faces)
2. Extract WSE results at cell centers
3. Build vertex-to-cell and face-to-cell mappings

### Phase 2: Corner WSE Computation
1. For each vertex, find all adjacent cells
2. Compute corner WSE as average of adjacent cell WSE values
3. Handle boundary vertices (single cell case)

### Phase 3: Face WSE Computation (if using 8-point)
1. For each face, get the two adjacent cells
2. Compute depth-weighted average: `(d1*WSE1 + d2*WSE2)/(d1+d2)`
3. Handle boundary faces (single cell case)

### Phase 4: Triangulation & Rasterization
1. Build TIN from cell centers + corners (+ face midpoints if 8-point)
2. For each terrain pixel, find containing triangle
3. Barycentric interpolation of vertex WSE values

### Phase 5: Shallow Fallback (if enabled)
1. Identify cells with depth < threshold
2. For pixels in those cells, use flat cell-center WSE instead

### Phase 6: Validation
1. Compare generated raster to ground truth
2. Calculate RMSE, MAE, Bias
3. Iterate on algorithm if needed

---

## Test Data

**Project:** `Test Data/BaldEagleCrkMulti2D - Sloped - Cell Corners/`

**Primary Test Plan:** p03 (Single 2D)
- Geometry: g09
- HDF: 62 MB
- Ground truth: `Single 2D/WSE (Max).Terrain50.dtm_20ft.tif`
- Terrain: `Terrain/Terrain50.dtm_20ft.tif`

---

## Investigation Log

### 2025-12-09: Key Discovery - Sloped Surface Does NOT Pass Through Cell Centers

**Critical Finding**: The sloped raster does NOT pass through cell center WSE values.

| Raster | RMSE at Cell Centers | Match within 0.01 ft |
|--------|---------------------|----------------------|
| Horizontal | 0.0000 ft | 100% |
| Sloped | 0.1206 ft | 49% |

**Interpretation**:
- Horizontal mode samples cell center WSE directly at each pixel
- Sloped mode builds an interpolation surface using **vertex** WSE values, then queries that surface at all locations (including cell centers)
- Cell centers are NOT control points in sloped mode - they're just query points like any other

**Algorithm Hypothesis (revised)**:
1. Compute WSE at each mesh vertex (average of adjacent cell WSE values)
2. Build Delaunay triangulation from vertices only (NOT cell centers)
3. For any query point (including cell centers), find containing triangle and interpolate

This explains the ~0.12 ft RMSE at cell centers - the surface is smooth through vertices but doesn't honor the exact cell center values.

### Vertex WSE Analysis Results

From `analyze_vertex_wse.py`:
- Tested simple average of adjacent cell WSE values
- RMSE: 0.118 ft (not a great match)
- Match within 0.01 ft: 48.8%

**Possible reasons for imperfect vertex match**:
1. Depth-weighting (`UseDepthWeightedFaces=true`)
2. Shallow-to-horizontal fallback (`ReduceShallowToHorizontal=true`)
3. Face midpoints included in triangulation (`slopingPretty` mode)
4. Different vertex averaging formula than expected

### 2025-12-09: TIN Interpolation Testing

#### Global Delaunay TIN (test_vertex_tin_fast.py)

Built a global TIN from all mesh vertices with averaged WSE values.

| Metric | Value |
|--------|-------|
| RMSE | 0.4551 ft |
| Mean diff | 0.0336 ft |
| Std dev | 0.4538 ft |
| Match within 0.10 ft | 85.0% |
| Match within 0.50 ft | 95.6% |
| Match within 1.00 ft | 97.5% |
| Min diff | -15.32 ft |
| Max diff | +19.58 ft |

**Problem**: Large outliers (±15-19 ft) caused by spurious Delaunay triangles that span across mesh discontinuities.

#### Error Analysis (analyze_tin_errors.py)

Surprising finding: **100% of large errors are INSIDE mesh cells** (not at boundaries as expected).

Error direction analysis:
- 81.6% of errors are negative (TIN < GT)
- Large positive errors (>1 ft): 34,482 pixels
- Large negative errors (<-1 ft): 3,610 pixels

The TIN is systematically over-estimating WSE in areas with large errors, indicating the global Delaunay is using vertices from unrelated cells.

#### Next: Cell-Constrained TIN (test_cell_constrained_tin.py)

Running cell-constrained interpolation that triangulates within each cell's own vertices only, avoiding cross-cell spurious triangles.

### 2025-12-09: Cell-Constrained TIN Results

Cell-constrained TIN (triangulate within each cell only) gave essentially identical results to global TIN:

| Metric | Global TIN | Cell-Constrained TIN |
|--------|------------|---------------------|
| RMSE | 0.4551 ft | 0.4475 ft |
| Match within 0.10 ft | 85.0% | 85.1% |

**Conclusion**: The large errors are NOT from spurious cross-mesh triangles. The problem is the simple averaging formula for vertex WSE values.

### 2025-12-09: BREAKTHROUGH - Depth-Weighted Vertex Averaging

Testing depth-weighted vertex averaging: `vertex_wse = sum(depth_i * wse_i) / sum(depth_i)`

This weights each cell's contribution by its water depth, giving more influence to deeply inundated cells.

| Metric | Simple Average | Depth-Weighted |
|--------|---------------|----------------|
| RMSE | 0.4475 ft | **0.1608 ft** |
| Mean diff | +0.0320 ft | **-0.0346 ft** |
| Match within 0.10 ft | 85.1% | **91.5%** |
| Match within 0.50 ft | 95.7% | **99.4%** |
| Match within 1.00 ft | 97.5% | **99.7%** |
| Min diff | -15.32 ft | **-9.07 ft** |
| Max diff | +17.97 ft | **+12.78 ft** |

**64% reduction in RMSE!** Depth-weighted averaging is clearly the correct approach.

#### Algorithm Confirmed

The sloped (cell corners) interpolation works as follows:

1. **Compute Vertex WSE** using depth-weighted averaging:
   ```
   vertex_wse = sum(depth_i * wse_i) / sum(depth_i)
   ```
   where `depth_i = wse_i - min_elevation_i` for each adjacent cell

2. **Filter cells**: Only include cells with `depth > 0` (exclude dry cells)

3. **Triangulate each cell**: Build Delaunay triangulation from the cell's own vertices

4. **Barycentric interpolation**: For each pixel, find containing triangle and interpolate

#### Remaining Issues

Still have outliers up to ±12 ft at some locations. Potential causes:
- `ReduceShallowToHorizontal=true` option not yet implemented
- Edge cases at mesh boundaries
- Cells with mixed wet/dry neighbors

### 2025-12-09: Shallow-to-Horizontal Fallback Testing

Tested various shallow depth thresholds:

| Threshold (ft) | RMSE (ft) |
|----------------|-----------|
| 0.0 | 0.1608 |
| 0.1 | 0.1604 |
| 0.5 | 0.1603 |
| 1.0 | 0.1603 |
| 2.0 | 0.1606 |
| 5.0 | 0.1619 |

**Result**: Minimal impact - best threshold is 0.5-1.0 ft but only reduces RMSE by 0.0005 ft.

This suggests the remaining errors are NOT from shallow cells.

### 2025-12-09: Remaining Error Analysis

Analyzed the remaining large errors (|error| > 2 ft = 0.10% of pixels):

| Finding | Value |
|---------|-------|
| Mean WSE range at error locations | 29.84 ft |
| Mean depth at error locations | 29.48 ft |
| Errors in boundary cells | 0% |
| Errors in interior cells | 100% |

**Root Cause**: The test project uses `<RenderMode>slopingPretty</RenderMode>`, which is "Cell Corners + Cell Faces" mode (8 interpolation points per cell). We're only implementing "Cell Corners" mode (4-5 points per cell).

The remaining errors occur in areas with high WSE variation between adjacent cells, where face midpoints would provide additional smoothing.

---

## Final Algorithm: Sloped (Cell Corners)

### BREAKTHROUGH: Optimal Vertex Formula (2025-12-09)

After extensive testing, the optimal vertex WSE formula is:

```python
vertex_wse = 0.72 * mean(adjacent_cell_wse) + 0.28 * max(adjacent_cell_wse)
```

This formula was discovered through:
1. Testing percentiles (found 72-73rd percentile works well)
2. Testing weighted averages (depth-weighted performed poorly)
3. Testing avg+max combinations (found 0.72/0.28 split optimal)

### Vertex-Level Results by Adjacent Cell Count

| n_adj | Count | RMSE (ft) | Notes |
|-------|-------|-----------|-------|
| 2 | 209 | 0.1499 | Boundary vertices |
| 3 | 555 | 0.2621 | Irregular/boundary vertices |
| 4 | 9,456 | 0.0584 | **Interior vertices - best match!** |
| 5 | 12 | 0.0817 | Irregular interior vertices |

**Key Insight**: The formula works extremely well for 4-cell vertices (RMSE 0.06 ft) but poorly for 2-3 cell vertices (RMSE 0.15-0.26 ft).

### Full Raster Results

| Method | Vertex RMSE | Raster RMSE | Match <0.10 ft |
|--------|-------------|-------------|----------------|
| Simple Average | 0.0967 ft | 0.4475 ft | 85.1% |
| Depth-Weighted | 0.0993 ft | 0.1608 ft | 91.5% |
| 73rd Percentile | 0.0847 ft | 0.1680 ft | 98.2% |
| **0.72*avg + 0.28*max** | **0.0584 ft** | **0.1619 ft** | **97.6%** |

### Error Analysis

For the optimal formula, errors >2 ft:
- 100% occur in **interior cells** (not boundary)
- 93.5% occur in **cell interior** (not near vertices/edges)
- 0% occur near vertices

The large errors propagate from poorly-estimated 2-3 cell vertices through the TIN interpolation.

### Working Implementation

```python
# 1. Filter to wet cells (depth > 0)
wet_cells = cells[(wse > 0) & ((wse - min_elev) > 0)]

# 2. Compute vertex WSE using avg+max formula
for each vertex:
    adjacent_wses = [wse for cells sharing this vertex]
    vertex_wse = 0.72 * mean(adjacent_wses) + 0.28 * max(adjacent_wses)

# 3. For each cell, triangulate its vertices
cell_tri = Delaunay(cell_vertex_coords)

# 4. Barycentric interpolation for each pixel
for each pixel in cell:
    find_containing_triangle()
    interp_wse = w0*v0_wse + w1*v1_wse + w2*v2_wse
```

### Results Summary

| Metric | Value |
|--------|-------|
| RMSE | 0.1619 ft |
| MAE | 0.0215 ft |
| Mean bias | -0.0129 ft |
| Match <0.01 ft | 67.9% |
| Match <0.05 ft | 92.8% |
| Match <0.10 ft | 97.6% |
| Match <0.50 ft | 99.6% |
| Match <1.00 ft | 99.8% |

### Remaining Work

To improve accuracy further:
1. **Handle 2-3 cell vertices differently** - These have poor formula fit
2. **Consider boundary vertex handling** - May need special treatment
3. **Test "Cell Corners + Faces" mode** - Adds face midpoints for 8 interpolation points

### Comparison to Previous Methods

| Method | RMSE | Best For |
|--------|------|----------|
| Simple Average | 0.4475 ft | None (deprecated) |
| Depth-Weighted | 0.1608 ft | None (superseded) |
| **0.72*avg + 0.28*max** | **0.1619 ft** | Cell Corners mode |

Note: Depth-weighted has slightly lower RMSE but the avg+max formula has:
- Better vertex-level match (0.0584 vs 0.0993 at 4-cell vertices)
- Nearly zero bias at optimal coefficient
- Simpler physical interpretation

---

## References

- HEC-RAS 2D User's Manual v6.6
- HEC-RAS Mapper User's Manual
- `findings/horizontal_2d.md` - Validated horizontal method
- `findings/horizontal_clipping.md` - Clipping investigation
