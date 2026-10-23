# ras2fim-2D flood inundation mapping (optional)

`RasFim` maps water-surface elevation (WSE) profiles defined on HEC-RAS 2D
cells to depth and WSE rasters with the ras2fim-2D Step 05 method. It maps a
batch of profiles against one shared terrain, accepts a bounding box or a
polygon area of interest (AOI), and returns a product manifest DataFrame.

The feature is optional. Install the Python extra and the matching Linux x86-64
or Windows x86-64 engine wheel into the same environment:

```bash
pip install "ras-commander[fim]"
pip install /path/to/ras2fim_engine-0.1.0-py3-none-<platform>.whl
ras2fim-batch method
```

The repository `wheels/` folder includes both tested wheels, checksums, and
`BUILD.json` provenance. See `wheels/README.md` for the exact platform filenames.
Wheels are rebuilt by the `Engine wheels` workflow
and available as its platform artifacts with SHA-256 checksums. Linux wheels
target glibc 2.28 or newer. The wheel installs `ras2fim-batch` on the environment's
`PATH`; no Rust compiler or system GDAL is needed for the native engine.
The Python GIS stack remains required. Source builds are also supported.
The workflow does not publish to PyPI. Installed-binary synthetic mapping tests
run on both platforms; retained real-model agreement evidence remains Linux-only.

## Method

The method comes from ras2fim-2D Step 05 (Andy Carter, PE, Center for Water
and the Environment, The University of Texas at Austin; BSD 3-Clause). For each
profile:

1. Wet cells are the cells whose profile WSE is not NaN.
2. Samples are the wet cell centres in ascending `cell_idx` order, followed by
   the wet-cell polygon vertices outside the convex hull of those centres.
   Vertices that round to the same 0.01 model units are merged with their mean
   WSE.
3. WSE is interpolated linearly on the SciPy Delaunay triangulation of the
   samples over `np.arange` axes that span the wet-cell union at the terrain
   pixel width, then masked to that union.
4. Depth is WSE minus the terrain sampled at each pixel centre; negative
   depths become NaN. WSE is then terrain plus depth where depth is finite.
5. Depth and WSE are reprojected with nearest-neighbour resampling to the
   output CRS on a grid whose origin is snapped to a multiple of the output
   resolution.
6. The floodplain polygon covers pixels with `0 < depth <= 10000` in the
   model vertical units.

!!! warning "Not RAS Mapper stored maps"
    This method differs from RAS Mapper stored maps
    (`RasProcess.store_maps()`), which use HEC-RAS's own rendering of the
    hydraulic results. The two produce different rasters; do not substitute
    one for the other.

## Engine

The interpolation, terrain, and reprojection arithmetic runs in the
`ras2fim-batch` engine. Python prepares the global samples, the SciPy Delaunay
topology, the query axes, the wet mask, and the explicit final grid, then
validates each engine output before writing products. The engine source and
build instructions are in `rust/step05/` of the RAS Commander repository.
The tested scope is x86-64 Linux; a Windows engine build is not qualified.

`RasFim` resolves the engine in this order:

1. the `engine_path=` argument;
2. the `RAS_COMMANDER_FIM_ENGINE` environment variable;
3. `ras2fim-batch` on `PATH`.

A missing engine raises `FimEngineNotFoundError`. RAS Commander never builds,
downloads, or installs the engine, and it has no Python fallback for this
method.

```python
from ras_commander import RasFim

info = RasFim.get_engine_info("/opt/ras2fim/ras2fim-batch")
print(info["method"])
```

## Map a ras2fim-2D catalog

A ras2fim-2D hydraulic-results GeoPackage stores one polygon per cell in layer
`02_cells_wsel_ar`, with `cell_idx` and one `wsel_*` column per flow profile.
Cell centres come from the plan HDF through `HdfMesh.get_mesh_cell_points()`.

```python
from ras_commander import RasFim

manifest = RasFim.map_ras2fim_results(
    "results.gpkg",
    "model.p01.hdf",
    "terrain.tif",
    "fim_out",                      # new or empty folder
    engine_path="/opt/ras2fim/ras2fim-batch",
    output_crs="EPSG:3857",
    output_resolution=3.0,
    threads=8,
)
print(manifest[["profile", "status", "flooded_pixels", "depth_tif"]])
```

## Map cells from a plan HDF

`get_cells_from_plan_hdf()` builds a one-profile cell table from the plan's
maximum WSE and maximum depth. A cell is wet when its maximum depth exceeds
`min_depth`. Frames from several plans on the same geometry can be joined on
`cell_idx` to map them as one batch.

```python
cells = RasFim.get_cells_from_plan_hdf("model.p01.hdf", profile_name="wsel_max")
manifest = RasFim.map_profiles(
    cells, "terrain.tif", "fim_max",
    hdf_path="model.p01.hdf",
    profiles=["wsel_max"],
)
```

Any GeoDataFrame with `cell_idx`, cell polygons, and numeric profile columns in
the terrain CRS can be mapped the same way. Pass `centers=` (a GeoDataFrame of
`cell_idx` and centre points) instead of `hdf_path=` when the centres come from
elsewhere. When an HDF has more than one 2D flow area, pass `mesh_name=`.

## Area of interest

Pass either `bbox=(xmin, ymin, xmax, ymax)` or `polygon=`. A polygon can be a
Shapely Polygon or MultiPolygon, a GeoDataFrame, or a vector file (use
`polygon_layer=` for a multi-layer file). Holes and multiple parts are kept,
and file features are unioned. A bbox without `aoi_crs` is in `output_crs`;
a Shapely polygon requires `aoi_crs`; a file or frame CRS that conflicts with
`aoi_crs` is an error.

```python
manifest = RasFim.map_ras2fim_results(
    "results.gpkg", "model.p01.hdf", "terrain.tif", "fim_reach",
    polygon="reach.gpkg", polygon_layer="reach",
)
```

The AOI selects pixels of the final output grid whose centres lie inside it.
It never changes sample preparation, triangulation, query axes, the wet mask,
terrain sampling, the grid origin, or the reprojection, so an AOI product is
the crop of the full product. Products cover the AOI window; pixels outside a
polygon are NaN.

Wet-cell discovery, sample preparation, and triangulation always use every wet
cell of the profile, and the engine's lookup warp spans the full output grid.
AOI runtime therefore does not shrink in proportion to the AOI area.

## Terrain-anchored grids and coplanar samples (opt-in)

Two keywords depart from the upstream Step 05 recipe. Both default to the
upstream behaviour and are recorded in `fim_manifest.json` under `options`.

`grid_anchor="terrain"` places the query axes and the final grid on the
terrain pixel lattice. Upstream starts the query axes at the wet-union bounds
and snaps the final origin to a multiple of `output_resolution`, so the
terrain pixel each output pixel takes depends on the phase of the wet-union
bounds. On one 1 m terrain whose origin is not a multiple of the pixel size,
that put every output pixel of a reach one terrain column away from the
terrain pixel it lies on, and moved results when the cell set changed. With
the anchor, each output pixel takes the terrain pixel it lies on, products
stack with the terrain without resampling, and equal lattice positions give
bit-equal transforms. The anchor needs a north-up terrain with square pixels,
`output_crs` equal to the results CRS, and `output_resolution` equal to the
terrain pixel size; anything else raises `FimUnsupportedError`. Samples and
triangulation are unchanged.

`coplanar="ignore"` maps a profile whose samples include points Qhull reports
as coplanar or duplicate (for example two perimeter vertices closer than the
0.01-unit merge) without those points, as upstream `griddata` does. The
default `"error"` fails such a profile. The count per profile is in the
manifest's `coplanar_samples`.

```python
manifest = RasFim.map_profiles(
    cells, "terrain.tif", "fim_reach", centers=centers,
    output_crs=cells.crs, output_resolution=terrain_pixel_size,
    polygon=reach_polygon, aoi_crs=cells.crs,
    grid_anchor="terrain", coplanar="ignore",
)
```

## Batches, resources, and outputs

| Keyword | Meaning |
|---|---|
| `profiles` | Profile columns; default all columns starting with `profile_prefix` (`"wsel"`) |
| `profiles_per_request` | Profiles prepared and sent per engine call (default 4) |
| `max_inflight_profiles` | Profiles the engine evaluates concurrently in one call (default 1); they share one decoded-terrain cache and the `threads` pool |
| `threads` | Engine thread pool; default `min(cpu_count - 1, 16)` |
| `max_cache_mib` | Engine decoded-terrain cache budget (default 64) |
| `max_profile_mib` | Engine per-profile planned working-set budget (default 1024); a profile over budget fails before allocation |
| `nudge_method` | `"lookup"` (default) or `"full_warp"` |
| `keep_work` | Keep engine requests and raw outputs in `output_folder/.fim_work` |

The engine budgets are admission checks on the engine's planned allocations.
They are not a resident-memory limit for the engine or the Python process.
Each profile in flight counts against `max_profile_mib`.

Each profile writes the ras2fim-2D product names into `output_folder`:

- `09_<profile>_depth_nudge.tif` and `10_<profile>_wsel_nudge.tif`: float32,
  LZW-compressed, NaN nodata;
- `11_<profile>_floodplain_ar.gpkg`: one floodplain (Multi)Polygon, written
  when at least one pixel is flooded.

`fim_manifest.json` records the engine path and method record, the options,
the AOI, the input file identities, engine reports, and one entry per profile.
The returned DataFrame has the same rows. Its columns are declared as
`fim_product_manifest` in `ras_commander/schemas.py`, which also feeds the
published machine-readable DataFrame surface:

| Column | Meaning |
|---|---|
| `profile`, `status` | Profile name; `complete`, `no_flooded_pixels`, `empty_aoi`, `failed`, or `not_run` |
| `wet_cells`, `samples` | Wet cells and interpolation samples used for the global preparation |
| `depth_tif`, `wse_tif`, `floodplain_gpkg` | Product paths (`None` when not written) |
| `col_off`, `row_off`, `width`, `height`, `transform`, `crs` | Written window on the full output grid |
| `depth_finite_pixels`, `flooded_pixels` | Finite depth pixels and floodplain pixels |
| `error` | Diagnostic for `failed` or `not_run` rows |

## Errors and inputs

- `output_folder` must be new or empty; no existing file is replaced.
- Profile names use letters, digits, underscores, dots, or hyphens and must be
  unique ignoring case. Caller centres require unique integer `cell_idx` values
  and non-empty point geometries.
- Input files are opened read-only, and caller DataFrames are not modified.
  Their size and modification time are checked after mapping.
- The hydraulic results and the terrain must share a CRS; the output CRS needs
  an EPSG code.
- Coplanar samples, infinite WSE, grids that extend beyond the terrain, and
  similar inputs raise `FimUnsupportedError` or mark the profile `failed`.
- An engine exit other than 0 or 2, or an output that is missing, sized
  incorrectly, has inconsistent finite counts, or has values outside a polygon
  mask, fails the profile or raises `FimEngineError`.
- Typed errors isolate a failed profile from the others in its batch; they do
  not sandbox the engine process or bound its operating-system resources.
- After writing the manifest, `map_profiles()` raises `FimMappingError` when any
  profile failed; `error.manifest` holds the DataFrame. Pass
  `raise_on_failure=False` to return it instead.

The [FIM engine comparison](../development/fim-mapping-performance.md)
records the agreement checks and the measurement scope. Its throughput
observations come from the ras2fim-2D adapter, not from `RasFim`, and do not
establish a general speedup.

## Complete source reference

::: ras_commander.fim.RasFim.RasFim
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

::: ras_commander.fim._aoi.FimAoi
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

::: ras_commander.fim._prepare.FimPreparedProfile
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
