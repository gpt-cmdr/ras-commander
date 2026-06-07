# Post-fire debris-flow 2D model (non-Newtonian), built from scratch

Companion scripts for the notebook
[`examples/319_post_fire_debris_flow_nonnewtonian.ipynb`](../319_post_fire_debris_flow_nonnewtonian.ipynb).

They build a complete 2D HEC-RAS debris-flow model **from a blank template** for the
**Ether Hollow** post-fire watershed (Utah, 2020 fire) and run a clear-water baseline plus
**Bingham** non-Newtonian variants, then derive hazard-intensity / arrival-time maps and a
parameter-sensitivity band. All inputs are public (USGS post-fire debris-flow predictions,
USGS 3DEP 1 m lidar, an HMS design hydrograph).

## Requirements

- **Windows + HEC-RAS 7.0**, run from an **interactive desktop session** — the `build` and
  `run` phases drive RAS Mapper / `Ras.exe` and the geometry preprocessor.
- `ras-commander` and its geospatial deps (`geopandas`, `rasterio`, `shapely`, `pyproj`,
  `h5py`, `matplotlib`).
- A `ras-commander` build that includes `create_project_from_template`,
  `GeomMesh.generate_computation_points`, and the 3DEP `product_link` fix.

## Inputs

Place under `<root>/data/ether_hollow/`:

- `burn/eth2020_Basin_DFPredictions_15min_12mmh.shp` (+ siblings) and
  `burn/eth2020_basinpt_feat.shp` — USGS post-fire DF predictions / basin points (EPSG:26912).
- `DebrisProjection_USCust.prj` — the US-Customary (feet UTM 12N) model CRS.
- `HMS_Hydrograph_SI.xlsx` — design hydrograph (the `US Cust` sheet is read, in cfs).

3DEP lidar is downloaded on demand into `data/ether_hollow/3dep/`.

## Run

```bash
# 1. data  (no HEC-RAS): basin select -> 3DEP mosaic -> runout corridor -> feet terrain
python ether_hollow_debris_flow.py --phase data --root .

# 2. build (HEC-RAS, interactive): greenfield 2D mesh + BC lines + terrain-in-mesh
python ether_hollow_debris_flow.py --phase build --root . --workdir ether_hollow_proj

# 3. run   (HEC-RAS, interactive): clear-water baseline + Bingham variants
python ether_hollow_debris_flow.py --phase run --root . --workdir ether_hollow_proj \
       --yields 700,2500 --cv 0.70 --viscosity-pa 100
```

Useful flags: `--no-corridor` (basin-only isolation run), `--mannings-n`,
`--sim-hours`, `--comp-interval`, `--inflow-width-ft` / `--outflow-width-ft`.

## Hazard + sensitivity analysis

After a `run`, point the analysis scripts at the project workspace (it holds
`EtherHollow.g01.hdf`, `result_<variant>.p01.hdf`, and the feet terrain):

```bash
python hazard_maps.py ether_hollow_proj ether_hollow_proj/EtherHollow_terrain_ft.tif
python sensitivity_plot.py sensitivity_status.jsonl
```

`hazard_maps.py` writes `hazard_intensity.png` (time-synchronized depth×velocity classes)
and `hazard_arrival.png` (first-wetting time). `sensitivity_plot.py` plots the yield-stress
and Manning's-n sweeps.

## Convergence + sensitivity

```bash
python rigor_analysis.py rigor_status.jsonl   # timestep convergence + Cv/viscosity/yield panels
```
Findings here: the peaks are converged at a 1 s computation interval (0.5 s identical; 2 s
unstable); Cv (bulking), viscosity, and yield stress are all material controls.

## Notes

- **Units:** the model is US-Customary (feet); non-Newtonian rheology is entered in **SI
  (Pa, Pa·s)** — HEC-RAS does not convert it.
- **Concentration is entered in PERCENT** (`--cv` here is a fraction and is written ×100).
  The clear-water inflow is **not** pre-bulked; HEC-RAS bulks it internally via *Bulk Fluid
  Volume* at `Cv` (BF = 1/(1−Cv) = 3.33 at Cv = 0.70). The run records the realized inflow
  peak/volume as a mass-balance check — confirm the bulked inflow ≈ 1/(1−Cv)× the clear one.
- The 2D-area perimeter is healed (`make_valid` + orient + simplify) before meshing — a dirty
  buffered-corridor polygon otherwise produces zero mesh cells.
- **Calibration status:** the demo's debris volume is ~3.5× the USGS empirical prediction for
  this basin, so the footprints are an **uncalibrated upper-bound scenario**, not a calibrated
  product. Mesh-resolution, inflow-placement, and equation-set studies plus field validation
  are needed before relying on a hazard polygon.
