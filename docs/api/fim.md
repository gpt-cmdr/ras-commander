# Flood inundation mapping (optional)

`RasFim` maps water-surface elevation (WSE) profiles defined on HEC-RAS 2D
cells to depth and WSE rasters with either the ras2fim-2D Step 05 method or
the horizontal or experimental plain-sloping methods below. It maps a
batch of profiles against one shared terrain, accepts a bounding box or a
polygon area of interest (AOI), and returns a product manifest DataFrame.

The feature is optional. Install the Python extra and the matching Linux x86-64
or Windows x86-64 engine wheel into the same environment:

```bash
uv pip install -e ".[fim,compute]"
uv pip install /path/to/ras2fim_engine-0.5.0-py3-none-<platform>.whl
ras2fim-batch method
```

Run these commands from this PR's checkout to use the new comparison and
scope checks. The `compute` extra supplies native process supervision for
the RAS Mapper comparison; Rust-only mapping needs the `fim` extra.

The repository `wheels/` folder includes both tested wheels, checksums, and
`BUILD.json` provenance. See `wheels/README.md` for the exact platform filenames.
Wheels are rebuilt by the `Engine wheels` workflow
and available as its platform artifacts with SHA-256 checksums. Linux wheels
target glibc 2.28 or newer. The wheel installs `ras2fim-batch` on the environment's
`PATH`; no Rust compiler or system GDAL is needed for the native engine.
The Python GIS stack remains required. Source builds are also supported.
The workflow does not publish to PyPI. Installed-binary synthetic mapping tests
run on both platforms. Step05 numerical qualification used Linux; horizontal
corpus checks passed on both Linux and Windows.

## Experimental plain sloping mapping

Use `map_sloping_profiles` to reconstruct RAS Mapper's plain **Sloping (Cell
Corners)** method from computed 2D HDF results. It is a separate optional Rust
method supplied by the 0.4.0 engine wheels. Earlier 0.3.0 wheels do not contain
this command. Use `ras2fim-batch method` to inspect installed capabilities.

```python
from ras_commander import RasFim

manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "canonical_terrain.tif", "sloping_catalog",
    profiles={"maximum": "Max", "t0054": 54, "t0108": 108},
    engine_path="/path/to/new/ras2fim-batch",
    threads=4,
    max_working_mib=4096,
    polygon="reach_boundary.gpkg",  # alternatively bbox=(xmin, ymin, xmax, ymax)
    write_floodplain=False,
)
performance = manifest.attrs["performance"]
```

Set `writer_threads=4` to use four GeoTIFF compression workers. The default is
one. This explicitly overrides `GDAL_NUM_THREADS` during ordinary and template
writes and restores the enclosing setting on success or failure. `threads`
controls native geometry extraction and Rust mapping; `writer_threads` controls
product compression. These pools can overlap on later profiles, so budget both.
Compression workers preserve decoded masks, values and storage layout; encoded
TIFF bytes can differ.

Numeric HDF payloads require the native Rust backend. The current qualification
uses `ras-commander-fast-hdf` 0.2.2 and current-main typed cell coordinates,
avoiding Shapely point construction. Immutable per-mesh result views are reused
for timestep profiles while retaining source identity checks on each read.
Performance attributes record the installed HDF backend version and preparation
phases, including geometry extraction and overlap validation. HDF metadata
inspection still uses h5py.

To match an existing raster's complete layout, pass
`template_raster="native_depth.tif"`. Only its grid, nodata and storage metadata
are read. Rust values are delivered directly on that grid in one write pass,
with nodata outside the mapped cells/AOI and no resampling. A template must
share the terrain pixel lattice and contain the processing window; its nodata
must not collide with a finite mapped value. Manifest offsets then refer to
the template grid. Omit it for compact terrain-window outputs.

Profile selectors are zero-based stored timestep indices or `"Max"`. Geometry,
terrain and pixel ownership are shared across the request. Each profile gets
its own hydraulic connectivity and corner reconstruction. Worker count controls
the bounded Rayon pool. An AOI reduces the terrain/output window while retaining
the complete mesh needed to reconstruct boundary values. Models containing 1D
river or cross-section elements are rejected before mapping.
Standalone storage-area surfaces outside the 2D mesh are excluded. The return
attributes `mapping_scope` and `model_scope`, and the JSON manifest, record
this boundary. The Bald Eagle dam-break reference also renders a storage area;
its exact sloping comparison is restricted to physical 2D cells, not the whole
native model image.

The method adds **no depth postprocessing cutoff**. It reproduces the native
float32 plot tolerance of 0.001 in model elevation units, including native
rounding; it does not replace this behavior with a 0.5 ft filter. The default disables depth weighting, shallow-to-horizontal rendering and
cell-face stencil enrichment. HEC documents these distinct controls in
[Mapping Options, HEC-RAS Mapper User's Manual 6.6](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/mapping-results/mapping-options).

Native 7.0.1 comparisons currently match raw valid/nodata masks and every
float32 depth/WSE value within the physical 2D footprint for Davis pipes and
conduits (Max and two timesteps), Bald Eagle dam break (Max), and Bald Eagle
bridges (Max). Bounded Max comparisons also match exactly on Spring River
(422,715 physical cells) and Spring Creek (340,163 physical cells), retaining
the complete mesh for reconstruction. Linux and Windows x86-64 native engine
checks include one/four-worker Davis Max/timestep comparisons; the five-model
corpus also passes on both platforms. Full-extent eBFE and other HEC-RAS versions
remain unqualified. A triangular AOI test also passes. Fresh single-map Windows
performance comparisons are recorded in the
[performance evidence](../development/fim-mapping-performance.md#plain-sloping-development-qualification).

The API writes products to a new or empty directory, records the engine method,
native option contract and timings, and removes products if the session aborts.
Performance evidence is returned in `attrs["performance"]` and retained in
`fim_manifest.json`. The memory budget is planned admission rather than an
enforced process RSS limit; HDF/Python preparation and polygonization also use
memory. A missing or incompatible engine raises without fallback. Mapping itself
does not load HEC-RAS assemblies; the private native component oracle is used
only during development qualification.

## Additional sloping options (engine 0.5)

### Reach-scale catalog masks

Both sloping modes accept the same bbox/polygon inputs as horizontal mapping.
Submit multiple timestep selectors in one call to share terrain and ownership:

```python
manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "canonical_terrain.tif", "reach_catalog",
    profiles={"t0054": 54, "t0108": 108},
    bbox=(xmin, ymin, xmax, ymax),
    aoi_crs="EPSG:2278",  # use the actual CRS of these bounds
    threads=4,
    writer_threads=4,
)
```

For a polygon, replace `bbox` with `polygon="reach_boundary.gpkg"` and,
if needed, `polygon_layer="reaches"`. Shapely geometries and GeoDataFrames
are also accepted. Supply one of bbox or polygon. Bbox coordinates default to
the mesh CRS unless `aoi_crs` is supplied. A Shapely polygon requires explicit
`aoi_crs`; file/frame CRS metadata is used when present.

The mask applies to every requested profile. The mapper reads the bounded
terrain window and writes compact Depth/WSE rasters with nodata outside the
polygon, using pixel-center inclusion. Complete hydraulic topology and cell
results remain available for reconstruction, preserving values at mask edges.
Omit `template_raster` for compact catalog delivery; a full-grid template
retains its full dimensions even when mapping is masked. An AOI reduces raster
work, but does not eliminate full-mesh preparation. These rules also apply to
`slopingPretty` and both of its native option flags.

Select `render_mode="slopingPretty"` for **Sloping (Cell Corners + Cell Faces)**.
The two booleans select the native controls independently:

```python
manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "canonical_terrain.tif", "enhanced_sloping",
    profiles={"maximum": "Max", "t0054": 54},
    render_mode="slopingPretty",
    use_depth_weighted_faces=True,
    reduce_shallow_to_horizontal=True,
    threads=4,
)
```

With both flags false, the mapper donates corner weights to adjacent cell
faces. `use_depth_weighted_faces=True` rebalances those weights using native
corner/face water depths. It requires the source HDF's stored
`Geometry/2D Flow Areas/<mesh>/FacePoints Elevation` arrays. Missing arrays
raise `FimUnsupportedError`; production mapping never invokes HEC-RAS to
create them or substitutes terrain samples. `reduce_shallow_to_horizontal=True`
uses native face-connectivity classifications to paint qualifying shallow cells
with the computed cell WSE. It bypasses their polygon interpolation work.
Both flags require slopingPretty; plain mode rejects them instead of silently
ignoring them. No additional depth cutoff is applied in either mode.

The selected native options and `rasmapper-sloping-with-faces/1` method appear
in the report and manifest; default plain mode retains its existing method ID.
The adapter checks the reported options against the request. Engine 0.4 remains
usable for plain mapping and raises explicitly for enhanced options.
All four enhanced combinations match raw Depth/WSE masks and float32 bits on
Bald Eagle bridges Max and Davis timesteps 54/108, with one/four workers on
Windows and Linux x86-64. This option matrix does not establish enhanced parity
for the large eBFE cases or other HEC-RAS versions. The physical-2D scope and
standalone-storage-area exclusion apply to both modes. Internal experimental
face-value and corner-adjustment switches are not exposed by this API.

## Horizontal cell mapping

This is a **2D surface-only** mapper. Model-backed entry points reject any
1D river centerline/reach or cross-section geometry before mapping, even
when a 2D mesh is selected from a mixed model. Coupled pipes/conduits and
SA/2D connections are permitted; their hydraulics must already be represented
in the computed cell WSE. The mapper does not solve structure hydraulics.
`RasFim.validate_2d_model(hdf_path)` exposes the same whole-model check.
Cell tables extracted by `get_cells_from_plan_hdf` retain source-HDF provenance
for later checks. For a manual cell table, supply `hdf_path=` to
`map_horizontal_profiles` to enforce model inspection; a standalone polygon
table cannot reveal elements in an unidentified source model.

Use `map_horizontal_profiles` when a cell-constant horizontal water surface is
the intended mapping method. It prepares terrain and pixel-to-cell ownership
once, then gathers the owning cell's WSE for every profile. Rust reads native
terrain blocks through terrio and reuses the decoded window. The native engine
also rasterizes the validated cells and polygon AOI through terrio, preserving
pixel-centre inclusion and feature order; Python writes final GIS products. It avoids convex
hulls, Delaunay triangulation and full-grid reprojection lookups. The Rust
backend is the default and requires a 0.3 or newer engine wheel. The explicit
`backend="numpy"` reference backend is retained for numerical qualification;
there is no automatic fallback.

```python
from ras_commander import RasFim

manifest = RasFim.map_horizontal_profiles(
    cells, "terrain_with_modifications.tif", "horizontal_catalog",
    profiles=["wsel_t0198", "wsel_t0199"],
    polygon="strict_domain.gpkg",
    min_depth=0.5,             # half-foot filter only when elevation units are feet
    max_working_mib=1024,
    threads=4,
    writer_threads=4,         # separate compression pool; budget both pools
    write_floodplain=False,
)
```

`threads` caps terrio rasterization and Rust pixel workers; `writer_threads` caps GeoTIFF compression
workers and defaults to one. The pools can overlap when Rust prepares the
next profile while Python writes the current one. Budget both pools for
catalog runs; four workers in each can use up to eight worker threads.
The writer setting overrides a caller GDAL_NUM_THREADS value, including
at its default of one. Compression uses a scoped [GDAL thread setting](https://gdal.org/en/stable/drivers/raster/gtiff.html#creation-options)
and restores the caller's previous setting. These controls do not change
float32 values, pixel ownership, the strict cutoff or the LZW output format.

Ownership and polygon masks are created once inside the native engine, without
staging a full ownership raster through Python. Compact 2D polygon geometry is
staged once per batch. The geometry/decode allocation plan is checked before
raster allocation; planned admission is not a hard process memory limit. Older
engines raise an explicit version error rather than falling back.

The terrain must be a single-band float32 GeoTIFF with declared nodata,
north-up square pixels, and the same CRS as the cells. Output stays on that
terrain lattice; there is no reprojection or nudge. The output extent is the
cell extent clipped to the AOI and terrain, so it can differ from
`map_profiles` for the same bounding box. Polygon holes and multiple
parts are retained. Only cells touching the constrained window are validated
and rasterized. Positive-area cell overlaps are rejected; shared edges use a
deterministic centre-based ownership rule. Geometry, terrain and WSE inputs
remain read-only, and output must be new or empty. Declared nodata and NaN
terrain pixels stay dry; other sentinel values present in the data but not
declared are treated as elevations.

NaN WSE marks dry cells; callers supply the cell wet/dry policy. Cell WSE is
normalized to float32 before subtracting terrain. Depth must be **strictly
greater** than `min_depth` to retain either product, with comparison in
float32. The threshold uses the input elevation units; it does not convert
feet to metres or establish a vertical datum. Native shallow-depth display
rules below this threshold are not reproduced.

The returned `fim_product_manifest` has the same columns and 09/10/11 filename
layout as Step05 products; those names do not identify the mapping method.
The JSON manifest records `method_id="horizontal-cell-constant/1"`,
`backend="rust"` (or the explicitly requested reference backend), float32 arithmetic, the threshold, source identities and
the terrain window. A `timings` section records ownership preparation,
input staging, stream reads (including waits for the engine), product writes
and mapping wall time; these are pipeline observations, not kernel-only
timings. `samples=0` because there is no interpolation. The
planned array admission budget excludes optional
floodplain polygonization and unaccounted runtime overhead; it is not a hard
process-memory cap. Rust profile arrays are streamed to the Python GIS writer
without retaining binary scratch rasters. Geometry and WSE staging use the
output volume, with a free-space check for staging only; final GeoTIFF space
is not included. `timeout` defaults to `None`. When set, it bounds the Rust
process and pipe-consumer lifetime, including product-writing backpressure.

This method implements cell-constant filling, consistent with the definition
of Horizontal rendering in the [HEC-RAS Mapper 6.6 Mapping Options](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/mapping-results/mapping-options).
It is separate from the ras2fim-2D triangulated method below. It does not
implement native sloping surfaces, mixed 1D/2D composition or structure-specific
renderers. Select the same render mode, terrain, timestep, grid and depth
filter when comparing with RAS Mapper; agreement with one mode does not
establish agreement with another.

## Compare with native horizontal stored maps

Use `compare_with_rasmapper` on an isolated copy of a computed project. It
runs `RasProcess.store_maps(render_mode="horizontal")` for native depth and
WSE, runs Rust horizontal mapping, and compares matching pixel centres. It
holds the native mapping project lock, checks the original `.rasmap` bytes,
and restores them on success or failure. Native mapping can write other
project-side caches, so stage the project rather than using an immutable source.

```python
comparison = RasFim.compare_with_rasmapper(
    "02", "terrain_with_modifications.tif", "horizontal_comparison",
    mesh_name="selected 2D area",
    terrain_name="registered terrain name",
    ras_object=project,
    ras_version="6.6",
    min_depth=0.5,       # model elevation units; feet in this example
    threads=4,
    max_working_mib=2048,
)
print(comparison[["profile", "csi", "depth_max_abs", "wse_exact_fraction"]])
print(comparison.attrs["performance"])
```

Without `cells`, this extracts maximum cell results from the selected plan
and mesh. For saved timesteps, supply a cell WSE table and
`profiles={"wsel_column": "DDMMMYYYY HH:MM:SS"}` with exact available native
timestamps. The caller must ensure those WSE columns describe the selected
plan, mesh and time. Unknown timestamps fail before native execution.
Use `mesh_name="*"` to include all physical 2D meshes. This assigns global
positional cell IDs so local IDs from different meshes cannot collide;
single-mesh extraction retains the original HDF cell IDs.

Supply a float32 terrain export of the exact registered terrain, with its
modifications applied. `RasTerrain.export_rasmapper_terrain` is the supported
native export API. Terrain identity remains the caller's responsibility;
the comparison does not silently substitute a different terrain.
If custom GeoTIFF CRS keys cannot be interpreted by the native reader, call
`RasFim.canonicalize_terrain_crs(source, new_output)` explicitly. It requires
an equivalent EPSG definition, copies the terrain with canonical CRS keys,
verifies all pixel bits and the grid, and writes a receipt. It performs no
reprojection or resampling. The retained Davis HARN terrain needs this step
with terrio 0.4.2. Terrain preparation is outside mapping timing.

The returned `fim_comparison` DataFrame and CSV include wet-mask CSI,
additional/missing wet pixels, common-wet depth differences, finite-pair WSE
differences, separate missing-WSE counts, native implied-terrain residuals and product paths. The JSON report
records native runtime provenance, terrain and registered-HDF hashes, the
effective float32 threshold, Rust batch timing and the
original/restored `.rasmap` hashes. Both depth masks use the strict cutoff
independently. The native TIFFs remain unmodified. No reference resampling is
performed: incompatible CRS, pixel sizes or fractional grid shifts fail.

The optional strict pixel filter is `min_depth`: direct horizontal mapping
defaults to `0.0`, and comparison defaults to `0.5` in model elevation units.
Both depth and WSE use the retained depth mask. `0.0` disables the half-unit
cutoff while retaining positive depths. Cell extraction's `min_depth` is a
separate cell wet/dry policy, not the raster postprocessing threshold.

By default, comparison also writes independently thresholded native LZW
delivery rasters, preserving the raw references. Timing columns distinguish
`native_seconds` (stored-map generation), `native_postprocess_seconds`,
`native_total_seconds`, `candidate_batch_seconds` and `comparison_seconds`.
`candidate_seconds` is populated only for a single-profile call; shared batch
time is not allocated repeatedly to individual profiles. Filtered native
paths are returned separately. Set `postprocess_reference=False` to omit
these written native products; comparison metrics still apply the cutoff.

`comparison.attrs["performance"]` is the additional performance return,
also persisted in JSON. It includes totals, worker settings, an observed
native-to-Rust ratio and any ratio exclusions. A ratio is withheld for an AOI,
unestablished full 2D coverage, native storage-area surfaces outside the 2D
cells, disabled native delivery postprocessing, or any depth/WSE/wet-mask
disagreement (including missing WSE). Input extraction, terrain
export/canonicalization, identity hashing and comparison scans are excluded
from mapping totals. Runs use Rust-first order and uncontrolled host/cache
conditions; the observations are not a general speed guarantee.

`native_performance=StoreMapPerformanceOptions(max_workers=2)` passes
Commander's independent-helper policy to native mapping. This mode requires
exactly one registered terrain, used implicitly by each helper. It records
the requested policy; memory admission or runtime caps may select fewer workers. The default
preserves aggregate `StoreAllMaps`. In the Davis qualification, aggregate
native generation intermittently returned incomplete WSE with valid depth.
Five independent-helper repetitions on Windows instead matched all depth/WSE pixels.
The notebook uses two native helpers for Davis and still raises on any
missing WSE; it never fills reference gaps with candidate data or retries
silently. Subsequent diagnosis captured a native pipe-rendering cache exception
during parallel rasterization; consistent EPSG:2871 metadata and explicit
projection initialization did not prevent it. One-CPU aggregate controls
passed 20/20 calls, supporting a native concurrency defect. Independent
helpers are not a guaranteed workaround. Both routes use the same Commander
`RasStoreMapHelper.exe`, which invokes installed RAS Mapper libraries.
[PR #677](https://github.com/gpt-cmdr/ras-commander/pull/677) fixes Commander's
separate false-success reporting of native fatal errors; it does not repair
the native race. See the [diagnosis and controls](../development/fim-mapping-performance.md)
for the tested conditions. Retained notebook outputs and timings are unchanged.

The evaluation footprint is the selected 2D cells intersected with the AOI.
A bbox or polygon constrains Rust mapping and comparison; native stored-map
generation still maps the selected plan. Native output must contain exactly
one depth and one WSE mosaic; select `terrain_name` to resolve multiple
registered terrains. Reported operation timings are not a controlled
throughput benchmark because the two calls include different preparation
stages. See `602_rust_horizontal_mapping_comparison.ipynb` for corpus setup.

### Reuse existing reference maps across depth cutoffs

`RasFim.compare_rasters` compares existing depth/WSE products without native
execution, file changes or reference resampling:

```python
metrics = RasFim.compare_rasters(
    "rust_depth.tif", "rust_wse.tif", "native_depth.tif", "native_wse.tif",
    cells=cells, min_depth=1.0, terrain_path="terrain.tif",
)
print(metrics["extra_wet"], metrics["missing_wet"], metrics["depth_max_abs"])
```

It applies the strict float32 cutoff independently, returns the same numeric
metrics as the native-generation comparison, and reports missing WSE
separately. It returns no generation timings. All rasters and the cell
footprint must share the CRS and aligned pixel lattice. Raw native inputs
must retain the low depths being tested; a previously applied higher cutoff
cannot be reversed. Raster provenance remains the caller's responsibility.

Notebook 602 shows 0.0, 0.5, 1.0 and 2.0 ft on Davis. Common-wet depth/WSE
matches at all four cutoffs; wet masks match at 0.5, 1.0 and 2.0 ft. At zero,
Rust retains 50 additional pixels below 0.001 ft, so zero-cutoff wet-mask
parity is not established. The default half-foot qualification is unchanged.

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
terrain pixel size; anything else raises `FimUnsupportedError`. Grid edges are
integer lattice positions, and the grid is clamped to the terrain extent where the
wet cells reach past it (those pixels would only read terrain nodata). Samples and
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
records the agreement checks and the measurement scope. Throughput tables
are observations of the listed workloads and do not establish a general speedup.

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
