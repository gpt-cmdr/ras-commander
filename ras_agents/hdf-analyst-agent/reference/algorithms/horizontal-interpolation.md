# Horizontal 2D Interpolation – Initial Findings

## Dataset
- **Project:** `C:/HCFCD/.../G103-38-00-E001 - Kingswood Diversion/RAS Model`
- **Plan used:** `Alt1_100yr` (`plan_number = "07"`, geometry `HCFCD_Final.g02.hdf`)
- **Reference rasters:** `Alt1_100yr/WSE (Max).vrt` and `Alt1_100yr/Depth (Max).vrt`
- **Terrain for depth:** `Terrain/TerrainAlt1.vrt`

## Workflow
1. Added `research/RasMapper Interpolation/ras_agent/rasmap_interpolation.py` - a CLI that:
   - loads the plan/geometry HDFs,
   - extracts max WSE per mesh cell via `HdfResultsMesh.get_mesh_max_ws`,
   - joins with 2D cell polygons and rasterizes them to the RASMapper grid,
   - optionally computes depth by subtracting a terrain raster,
   - compares the generated rasters to the stored `WSE/Depth (Max)` VRTs and writes metrics/difference grids.
2. Outputs for each run land in `research/RasMapper Interpolation/ras_agent/outputs/<project>_Plan<nn>/`.

Command used:
```
.\.venv\Scripts\python.exe "research\RasMapper Interpolation\ras_agent\rasmap_interpolation.py" ^
  --project "C:/HCFCD/.../G103-38-00-E001 - Kingswood Diversion/RAS Model" ^
  --plan 07 ^
  --variables WSE Depth ^
  --terrain "C:/HCFCD/.../Terrain/TerrainAlt1.vrt" ^
  --output-dir "research/RasMapper Interpolation/ras_agent/outputs" ^
  --save-difference
```

## Metrics (Plan 07 – Alt1_100yr)
| Variable | Count | Bias (ft) | MAE (ft) | RMSE (ft) | Max Abs (ft) |
|----------|------:|----------:|---------:|----------:|-------------:|
| WSE      | 15,400,273 | -0.0059 | 0.0076 | **0.0274** | 3.25 |
| Depth    | 15,400,273 | -0.0106 | 0.0447 | **0.1012** | 5.48 |

Notes:
- RMSE < 0.03 ft for WSE indicates the horizontal cell-filling matches RASMapper’s rasterization closely.
- Depth differences are larger near steep terrain or culverts where DEM resampling and the “horizontal” assumption diverge (~5.5 ft max); most of the domain stays within 0.1 ft.
- Difference rasters (`wse_diff.tif`, `depth_diff.tif`) are in `research/RasMapper Interpolation/ras_agent/outputs/HCFCD_Final_Plan07/`.

## Open Items / Next Steps
1. **Velocity:** RAS stores “Maximum Face Velocity”; implement cell aggregation (needs face → cell mapping) to rasterize velocity.
2. **Multiple terrains:** Allow plan-specific terrain selection (e.g., Alt2/Alt3) via CLI parameter or auto-detection from rasmap.
3. **Edge handling:** Clip max-abs spikes by masking outside the flood boundary to avoid reporting dry-cell artifacts.
4. **1D surfaces:** Extend script with XS-interpolation support so WSE rasters can be generated for purely 1D projects.
5. **Batch mode:** Add ability to run multiple plans and consolidate metrics for regression testing.

## Cell-Center Comparison
- Script: `research/RasMapper Interpolation/ras_agent/compare_mesh_vs_raster.py`
- Purpose: sample the stored `WSE (Max)` raster at every cell center and compare against `HdfResultsMesh.get_mesh_max_ws`.
- Output table + metrics: `research/RasMapper Interpolation/ras_agent/outputs/HCFCD_Final_Plan07/wse_cell_check/`.

Summary:
| Sample Set | Count | Bias (ft) | MAE (ft) | RMSE (ft) | Notes |
|------------|------:|----------:|---------:|----------:|-------|
| All cells with raster data | 18,536 | -0.101 | 0.103 | **2.134** | Errors dominated by dry perimeter cells where HDF stores 0.0 but raster inherits surrounding water. |
| Wet cells (HDF WSE > 0 ft) | 18,499 | -0.0075 | 0.0088 | **0.0274** | Matches the horizontal interpolation RMSE; confirms raster samples agree with HDF values at wetted cell centers. |

Takeaway: RASMapper keeps cell-center magnitudes intact for wetted locations, but GDAL’s stored raster also retains interpolated values along the mesh perimeter even when HDF reports 0. Filter on `WSE > 0` (or a small threshold) when validating cell-level agreement.

### Horizontal vs. Sloped Rasters (BaldEagleCrkMulti2D copies)
- Created two cloned projects under `Test Data/`:
  * `BaldEagleCrkMulti2D - Sloped - Cell Corners` (original setting, not used now)
  * `BaldEagleCrkMulti2D - Horizontal` (RASMapper raster setting flipped to **Horizontal** and stored maps regenerated).
- Running the same CLI against Plan 15 (`1D-2D Dambreak Refined Grid`) on the horizontal copy produced **exact** agreement:
  * WSE raster RMSE = 0.0 ft (all pixels match), MAE = 0.0 ft.
  * Cell-center comparison: all wet cells (7,364 samples) match within machine precision, confirming the perimeter propagation + horizontal rasterization is aligned with RASMapper’s horizontal mode.
- Depth differences for this project are large because the supplied terrain (`Terrain50.vrt`) doesn’t match the stored RASMapper raster’s embedded terrain; to validate depth precisely we need the same DEM that was used during map export.

Usage snippets:
```
.\.venv\Scripts\python.exe "research\RasMapper Interpolation\ras_agent\rasmap_interpolation.py" ^
  --project "research/RasMapper Interpolation/Test Data/BaldEagleCrkMulti2D - Horizontal" ^
  --plan 15 --variables WSE Depth ^
  --terrain "research/RasMapper Interpolation/Test Data/BaldEagleCrkMulti2D - Horizontal/Terrain/Terrain50.vrt" ^
  --output-dir "research/RasMapper Interpolation/ras_agent/outputs" ^
  --save-difference

.\.venv\Scripts\python.exe "research\RasMapper Interpolation\ras_agent\compare_mesh_vs_raster.py" ^
  --project "research/RasMapper Interpolation/Test Data/BaldEagleCrkMulti2D - Horizontal" ^
  --plan 15 ^
  --output-dir "research/RasMapper Interpolation/ras_agent/outputs"
```
