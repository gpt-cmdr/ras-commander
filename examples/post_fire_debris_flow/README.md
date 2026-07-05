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

The intensity uses a **cell-centered** velocity — HEC-RAS stores only face-normal velocities,
so a per-cell vector is reconstructed by least-squares (`u·n_f = v_f` over the cell's faces)
and its magnitude used. Taking the max face speed instead biases velocity ~10 % high (the
high-hazard *area* is unchanged here — the debris-flow high class is depth-dominated).

## Convergence + sensitivity

```bash
python rigor_analysis.py rigor_status.jsonl   # timestep convergence + Cv/viscosity/yield panels
```
Findings here: the peaks are converged at a 1 s computation interval (0.5 s identical; 2 s
unstable); Cv (bulking), viscosity, and yield stress are all material controls.

## Channel breaklines (mesh refinement along the thalweg)

A uniform mesh over-deepens the channel (a wide cell averaged across a narrow, deep thalweg
piles water artificially). Aligning cell faces to the channel centerline with **breaklines**
resolves the cross-section and removes that artifact.

```bash
# 1. delineate channel centerlines with TauDEM (run where TauDEM is installed; see below)
python delineate_channels.py --dem ether_hollow_proj/EtherHollow_terrain_ft.tif \
       --domain prep/basin_perimeter_ft.json --out data/ether_hollow/channel_breakline_ft.json \
       --stream-area-km2 0.04 --simplify-ft 3 --plot taudem_centerlines.png

# 2. build with breaklines (HEC-RAS, interactive): refine the mesh along the thalweg
python ether_hollow_debris_flow.py --phase build --breaklines \
       --channel-width-ft 30 --channel-cell-ft 12 --root . --workdir ether_hollow_proj

# 3. comparison figures (no HEC-RAS): cell outlines over terrain, uniform vs refined
python mesh_compare_plot.py \
       --uniform   ether_hollow_uniform/EtherHollow.g01.hdf \
       --refined   ether_hollow_proj/EtherHollow.g01.hdf \
       --terrain   ether_hollow_proj/EtherHollow_terrain_ft.tif \
       --breakline data/ether_hollow/channel_breakline_ft.json
```

`mesh_compare_plot.py` writes **`mesh_uniform.png`** and **`mesh_refined.png`** — two
separate figures, each drawing the actual mesh **cell polygons (no fill)** — or cell faces
with `--faces` — over the feet terrain hillshade via `HdfMesh.get_mesh_cell_polygons`, with
the channel centerline (red) overlaid in the same coordinate system. (This replaces the old
single cell-centers scatter, which mixed two coordinate systems in one axes.) Cell counts in
the titles are the true totals (`Cells Center Coordinate`), not the polygonized subset.

Framing: `--zoom-buffer-ft` crops to the channel corridor (0 = full domain); `--reach-center
CX CY --reach-half-ft 350` draws a tight square window where individual cells are visible —
the clearest way to see the 12 ft channel band against the 33 ft base grid. The committed
notebook figures use a ~700 ft reach window on the main thalweg:

```bash
python mesh_compare_plot.py --uniform ... --refined ... --terrain ... --breakline ... \
       --reach-center 1485606 14579723 --reach-half-ft 350
```

`delineate_channels.py` runs the TauDEM stream sequence (PitRemove → D8FlowDir → AreaD8 →
Threshold → StreamNet), clips the network to the 2D domain, and extracts the **continuous
main-stem** centerline as a single polyline before simplifying (Douglas-Peucker) and writing
`channel_breakline_ft.json`. The main-stem step matters: `linemerge` alone splits the trunk at
every confluence, so picking the longest merged pieces yields a *discontinuous* thalweg with
gaps; instead the segments are assembled into a graph and the longest path (head→outlet) is
taken as one unbroken centerline (`--max-lines` keeps additional disjoint tributaries). Pass
`--plot taudem_centerlines.png` for a hillshade + domain + streams + thalweg diagnostic. The
build phase then authors them
via `GeomStorage.set_breaklines` with **near = far** cell spacing (a uniform fine corridor,
no coarsening) and `GeomMesh.set_breakline_spacing(near_repeats, protection_radius=1)`, sizing
`near_repeats` (≥ 2 — at least two refined rows each side) to span the channel width;
`GeomMesh.generate` enforces the breaklines (the .NET `EnforceBreaklines` regen) and repairs
bad faces via its auto-fix loop. Verify with `HdfBndry.get_breaklines(...)`.

> **Build order matters.** `GeomMesh.generate`'s seeder reads breaklines from the compiled
> HDF, not the `.g01` text, so the build compiles the breaklines into the HDF (a
> `compute_plan(force_geompre=True)`) *before* `generate` — otherwise the seeder sees zero
> breaklines and `near_repeats` is silently ignored (only Ras.exe enforcement adds a thin
> 1-row band).

Effect (Ether Hollow, τy = 700 Pa): the channel-aligned refinement drops the spurious max
depth 19.1 → 13.4 ft as the resolved continuous thalweg carries the flow; peak velocity rises
modestly (17.3 → 20.0 fps), mesh 10,647 → 15,546 cells.
**Mesh and timestep refine together**: the 12 ft mesh needs a 0.5 s computation interval (the
33 ft mesh is converged at 1 s) — at 1 s the refined mesh runs Courant ≈ 2 and inflates peak
velocity to ~25 fps.

**Extra prerequisite for delineation:** **TauDEM 5.x** binaries (`PitRemove`, `D8FlowDir`,
`AreaD8`, `Threshold`, `StreamNet`) on PATH, and **MS-MPI** (`mpiexec`) for multi-process runs
(optional — falls back to a single process). Delineation is CPU-only and can run off the
HEC-RAS host; stage the resulting JSON to the build machine.

## Notes

- **Units:** the model is US-Customary (feet); non-Newtonian rheology is entered in **SI
  (Pa, Pa·s)** — HEC-RAS does not convert it.
- **Concentration is entered in PERCENT** (`--cv` here is a fraction and is written ×100).
  The clear-water inflow is **not** pre-bulked; HEC-RAS bulks it internally via *Bulk Fluid
  Volume* at `Cv` (BF = 1/(1−Cv) = 3.33 at Cv = 0.70). The run records the realized inflow
  peak/volume as a mass-balance check — confirm the bulked inflow ≈ 1/(1−Cv)× the clear one.
- The 2D-area perimeter is healed (`make_valid` + orient + simplify) before meshing — a dirty
  buffered-corridor polygon otherwise produces zero mesh cells.
- **Calibration / scenario bracket:** the default HMS-driven run delivers ~3.5× the USGS
  empirically predicted debris volume — an **upper-bound scenario**. `--inflow-scale` produces
  a **volume-matched** run: scaling the inflow to ~0.29 brings the bulked debris volume to
  ≈ the USGS 9,019 m³ (clear peak ~95 cfs, within the BAER-reported mouth range 82–221 cfs),
  which roughly halves peak velocity (17.7 → 10.9 fps) and shrinks runout ~35 %. Report the
  pair as a bracket. **Field validation** against observed Ether Hollow deposits still requires
  post-event imagery / a deposit survey not in the public USGS DF-prediction dataset; the
  volume + BAER-peak match is calibration to the available benchmarks, not deposit validation.
