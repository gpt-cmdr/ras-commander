# Flood inundation mapping (optional)

`RasFim` maps water-surface elevation (WSE) profiles defined on HEC-RAS 2D
cells to depth and WSE rasters with either the ras2fim-2D Step 05 method or
the horizontal or experimental plain-sloping methods below. It maps a
batch of profiles against one shared terrain, accepts a bounding box or a
polygon area of interest (AOI), and returns a product manifest DataFrame.

The feature is optional. The `fim` extra installs the external
`ras-commander-fast-map` wheel on qualified Windows/Linux x64 platforms:

```bash
uv pip install "ras-commander[fim,compute]"
ras2fim-batch method
```

For a source checkout, use `uv pip install -e ".[fim,compute]"` instead.
The `compute` extra supplies native process supervision for the RAS Mapper
comparison; Rust mapping needs the `fim` extra.

The engine has its own [repository](https://github.com/gpt-cmdr/ras-commander-fast-map),
[Python package](https://pypi.org/project/ras-commander-fast-map/) and
[Rust crate](https://crates.io/crates/ras-commander-fast-map).
[Tagged releases](https://github.com/gpt-cmdr/ras-commander-fast-map/releases)
carry Windows/Linux wheels, a source distribution, checksums and build identity.
Linux wheels target glibc 2.28 or newer. The compatible executable remains
`ras2fim-batch`; no Rust compiler or system GDAL is needed when using a wheel.
The Python GIS stack remains required for preparation and final delivery.
Rust consumers can use the crate directly or install the CLI with
`cargo install ras-commander-fast-map --locked`. Model/HDF preparation remains
in Commander. Runtime mapping does not download, build or install packages.
Uninstall the former `ras2fim-engine` package before installing Fast-Map if
both would own the same executable.

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
rounding; it does not replace this behavior with a 0.5 ft filter. The default disables shallow-to-horizontal rendering and
cell-face stencil enrichment. HEC documents these distinct controls in
[Mapping Options, HEC-RAS Mapper User's Manual 6.6](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/mapping-results/mapping-options).

Native 7.0.1 comparisons currently match raw valid/nodata masks and every
float32 depth/WSE value within the physical 2D footprint for Davis pipes and
conduits (Max and two timesteps), Bald Eagle dam break (Max), and Bald Eagle
bridges (Max). Bounded Max comparisons also match exactly on Spring River
(422,715 physical cells) and Spring Creek (340,163 physical cells), retaining
the complete mesh for reconstruction. Linux and Windows x86-64 native engine
checks include one/four-worker Davis Max/timestep comparisons; the five-model
corpus also passes on both platforms. The final Windows Max comparisons also
match across the full physical 2D footprints of Spring River and Spring Creek.
Full-extent Linux eBFE, unweighted face-mode eBFE and other HEC-RAS versions remain
unqualified. A triangular AOI test also passes. Fresh single-map Windows
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

## Invalid cell polygons

!!! note "Scope"
    `map_sloping_profiles()`, `prepare_sloping_model()`,
    `map_horizontal_profiles()` (through `get_cells_from_plan_hdf()`),
    `map_whole_simulation()` and `compare_with_rasmapper()` accept
    `invalid_cells=`, with the same values, default and manifest record.
    Step 05 `map_profiles()` still refuses meshes with invalid cells. See
    [Horizontal, whole-simulation and comparison mapping](#horizontal-whole-simulation-and-comparison-mapping).

HEC-RAS can compute a mesh in which one face polyline of a cell crosses
another face of the same cell, making a self-intersecting "bowtie" ring.
Strict polygon assembly refuses the whole mesh for one such cell. Sloping
mapping instead assembles the mesh non-strictly and applies
`invalid_cells=` to the affected cells:

| `invalid_cells` | Pixel ownership for the invalid cell |
|---|---|
| `"repair"` (default) | Regions enclosed by the cell's noded face polylines, minus area owned by valid cells. The largest part is kept; equal areas go to the part with the lower-left bounds. |
| `"hull"` | Convex hull of the cell's face points, with the same overlap removal. |
| `"omit"` | None. The cell's pixels are unmapped. |
| `"raise"` | Strict refusal (`MeshCellPolygonError`), but only when the AOI, or the whole mesh without one, intersects an affected cell. |

A crossing face also distorts the cell on its other side. That valid cell can
then overlap its own neighbours, which the ownership check refuses. Overlaps
are resolved for the valid cells touching an invalid cell's face-point hull and
for every cell connected to them through further overlaps. Cells are processed
in ascending cell ID; each loses the area of lower-ID cells it overlaps:

- If pieces remain, every piece stays with the original cell ID
  (`action="overlap_trimmed"`, `pieces` > 1 when split). Holes are kept.
- If nothing remains, the cell owns no pixels (`action="overlap_consumed"`,
  `fallback_area` 0).

Overlaps elsewhere in the mesh are still refused. Only pixel ownership changes:
hydraulic connectivity, corner values and interpolation stencils always use the
complete HDF topology, including for consumed cells. A split cell is sent to
the engine as one ownership polygon per piece with the same mesh/cell address.

```python
manifest = RasFim.map_sloping_profiles(
    "model.p01.hdf", "terrain.tif", "maps/p01",
    invalid_cells="repair",  # default; "raise" restores the strict refusal
)
for cell in manifest.attrs["invalid_cells"]["cells"]:
    print(cell["mesh"], cell["cell_id"], cell["action"], cell["fallback_area"])
```

`fim_manifest.json` and `attrs["invalid_cells"]` record
`{"schema": "fim-invalid-cells/1", "policy", "count", "cells"}`. Each cell
entry has:

| Field | Meaning |
|---|---|
| `mesh`, `cell_id` | HDF mesh name and zero-based mesh-local cell ID. |
| `reason` | `no_polygon`, plus the GEOS explanation of the face ring (for example `Self-intersection[x y]`), or the overlap reason for trimmed and consumed cells. |
| `action` | `repaired`, `convex_hull`, `omitted`, `overlap_trimmed` or `overlap_consumed`. |
| `original_area` | Area enclosed by the noded face polylines (invalid cells) or of the untrimmed polygon (valid cells), in model units squared. |
| `fallback_area` | Area actually mapped: `null` for an omitted invalid cell, `0.0` for a consumed cell. |
| `pieces` | Number of ownership polygons mapped for the cell (0 when omitted or consumed). |
| `overlap_with` | Lower-ID cells that kept the shared area (trimmed and consumed cells). |
| `intersects_aoi` | Whether the cell's extent (face-point hull or original polygon) intersects the request AOI; `null` without an AOI. |

The list is empty (`count == 0`) for valid meshes, whose polygons, ownership
and products are unchanged. A prepared context fixes the policy and lists the
cells in `info["invalid_cells"]`. Its `map_profiles()` accepts `invalid_cells`
only as `None` or the prepared value. With `"raise"`, preparation succeeds and
each request refuses only if its AOI intersects an affected cell. If no
ownership polygon remains at all, the error names the policy and the cells.

**Evidence for the default.** The evidence is limited. On Glaise Creek–White
River p01 (eBFE 1101001306; 582,934 cells; three self-intersecting cells in
`default geometry`), each policy was compared with native HEC-RAS 7.0.1
RAS Mapper sloping Max stored maps on 10 ft terrain windows around the cells:

- Inside the three cells' hulls RAS Mapper has 25 wet pixels: 15 at cell
  457262, 10 at 497876 and none at 36699, which is entirely dry. Within 60 ft
  of the cells it has 156.
- `repair` and `hull` matched all of them, with identical masks and float32
  bits. Giving overlaps to the higher cell ID missed one pixel.
- `omit` left 22 holes where RAS Mapper maps the cell.
- Every other pixel in the windows matched under all policies.

So RAS Mapper does map pixels inside such cells, and `repair` is a
conservative default that reproduced it in these cases. This is not general
equivalence: RAS Mapper's own treatment of a bowtie is undocumented, and three
cells on one model cannot show it. `hull` claims more unowned area (1,201 ft²
more than `repair` at the dry cell 36699), so it remains an explicit option.

### Horizontal, whole-simulation and comparison mapping

These methods first assemble the cell polygons strictly, as before. Only when
strict assembly refuses the mesh do they apply `invalid_cells=` with the
ownership rules above. Valid meshes therefore keep exactly the polygons and
products they had, and their manifest records `count == 0`.

- `get_cells_from_plan_hdf(invalid_cells=...)` fixes the ownership of the
  table it returns. A split cell is one MultiPolygon row, so `cell_idx` stays
  unique; omitted and consumed cells have no row. The policy and cells are in
  `attrs["fim_invalid_cells"]`.
- `map_horizontal_profiles(cells, ..., invalid_cells=...)` must receive the
  value the table was extracted with; any other value raises `ValueError`.
  Each piece of a split cell owns its pixels with the cell's WSE. `"raise"`
  refuses when the AOI, or the whole table without one, intersects an
  affected cell. A table without the record is mapped strictly.
- `map_whole_simulation(..., invalid_cells=...)` has no AOI, so `"raise"`
  refuses any plan with an affected cell.
- `compare_with_rasmapper(..., invalid_cells=...)` passes the value to both
  calls and refuses `"raise"` before native mapping. The compared footprint
  keeps omitted and consumed cells, so `"omit"` reports the native pixels it
  leaves unmapped. `comparison.json` records `invalid_cells`.
- `map_profiles()` and `prepare_profile()` (Step 05) refuse tables with
  affected cells (`FimUnsupportedError`).

```python
cells = RasFim.get_cells_from_plan_hdf("model.p01.hdf")  # invalid_cells="repair"
manifest = RasFim.map_horizontal_profiles(cells, "terrain.tif", "maps/horizontal")
print(manifest.attrs["invalid_cells"]["count"])
```

**Evidence (Glaise Creek p01, native HEC-RAS 7.0.1).** RAS Mapper stored maps
came from `RasProcess.store_maps` on 512 × 512-pixel windows of the 10 ft source
terrain around cells 36699, 457262 and 497876, as for sloping:

- Horizontal Max: `repair` gives the native depth on every window pixel, with
  identical masks and float32 bits. That includes 113 wet pixels inside the
  affected cells (the three cells and their trimmed neighbours). Native WSE
  also matches, except one pixel at cell 36699's crossing point. There, RAS
  Mapper writes cell 36699's WSE but leaves depth dry; the pixel centre lies in
  valid cell 36420, whose WSE is below the terrain. `omit` leaves 87 holes.
  Pixels outside the affected cells are identical under every policy.
- `compare_with_rasmapper` on each window (single-source terrain):
  `repair` gives CSI 1.0 with no depth or WSE difference. `omit` misses 43, 14
  and 30 wet pixels.
- Whole simulation (threshold 0.5 ft): `repair` gives the native arrival time
  and percent inundated on every pixel, with identical float32 bits. That
  includes 33 wet pixels inside the affected cells; cell 36699 is dry at this
  threshold. `omit` misses 25.

The limits stated for sloping apply here too.

## Supply cell WSEL profiles

Pass `wsel_profiles=` to `RasFim.map_sloping_profiles()` or
`RasFim.prepare_sloping_model()` when the requested elevations are computed by
the caller, such as cell-level maxima over a discharge window. Leave
`profiles=None`; supplying both is an error. Window selection, aggregation and
any decimal rounding belong to the caller. This API never substitutes an HDF
timestep or whole-plan maximum for supplied values.

Use a wide pandas DataFrame. `mesh_name` and `cell_id` identify rows; **every
other column** is a named WSEL profile. Drop geometry and diagnostic columns
before passing the table. The contract is declared as `fim_cell_wsel_profiles`
in `ras_commander.schemas.DATAFRAME_SCHEMAS`.

| Field or condition | Contract |
|---|---|
| `mesh_name` | Exact HDF mesh name, including case. Include every source mesh. |
| `cell_id` | Nonnegative integer HDF cell ID, local to its mesh, starting at zero. |
| Coverage | Every physical **and ghost** cell exactly once. Obtain complete keys with `HdfMesh.get_mesh_cell_points(hdf_path, include_ghost_cells=True, include_geometry=False)`. |
| Row order | Arbitrary; values are aligned by mesh/cell identity before staging. |
| Profile columns | Real numeric dtypes. Safe distinct names identify outputs; names must also be distinct ignoring case and cannot be reserved Windows filenames. |
| Dry values | NaN (including nullable numeric missing values) explicitly means dry and is encoded as finite float32 minimum, approximately −3.4028235 × 10³⁸. Other finite stored sentinels pass through unchanged. |
| Precision | Values cast once to float32. No decimal rounding, aggregation, unit or datum conversion is applied. Infinity, float32 overflow, complex, Boolean and numeric-string columns are rejected. |
| Units | Absolute WSEL in the vertical units and datum of HDF hydraulic properties and the chosen terrain. The caller establishes this agreement. |
| Identity errors | Missing, extra, duplicate or unknown mesh/cell IDs raise. An AOI does not relax complete input coverage or fill omitted ghost values. |
| Source binding | `hdf_path` supplies authoritative geometry/properties. Optional table attrs `fim_source_hdf` and `crs` are checked against that source. Correct numeric IDs alone cannot detect a caller's mislabeled model or vertical datum. |
| Ownership | Do not mutate the table during a call. Preparation owns staged values after its constructor returns; later caller changes do not alter the context. |

Read a complete caller-produced table, bind its declared source, and map it:

```python
from pathlib import Path
import pandas as pd
from ras_commander import RasFim

hdf = Path("model.p02.hdf")
table = pd.read_csv("cell_window_maxima.csv", dtype={"mesh_name": str, "cell_id": "int64"})
# CSV columns: mesh_name,cell_id,window_01,window_02,...
# Include physical and ghost rows; blank numeric values explicitly mean dry.
table.attrs["fim_source_hdf"] = str(hdf.resolve())
manifest = RasFim.map_sloping_profiles(
    hdf, "chosen_mapping_terrain.tif", "window_catalog",
    wsel_profiles=table,
    polygon="reach_boundary.gpkg",  # or bbox=(xmin, ymin, xmax, ymax)
    threads=4, max_inflight_profiles=2, max_working_mib=2048,
)
print(manifest[["profile", "status", "depth_tif", "wse_tif"]])
print(manifest.attrs["profile_source"])
```

For repeated masks, pass the same table to `prepare_sloping_model()` and then
call the context's `map_profiles()` with subsets of the prepared column names.
`max_prepared_mib` admits the input snapshot and retained prepared files;
one-shot mapping checks the planned snapshot against `max_working_mib`.
These checks are planned admission, not process RSS limits. Input DataFrame,
transient arrays, geometry and GIS delivery also consume memory. Prepared
metadata has `unique_selectors=0` and `profile_views_prepared=0` for supplied
inputs. Profile values in its `info["profiles"]` are `None`, marking caller
vectors rather than HDF selectors. Rendered requests record per-mesh/profile canonical
float32 hashes and explicit dry-marker counts under `profile_source`.

Select one independent `terrain_path`, original or healed. It must satisfy the
same grid, CRS and raster requirements as ordinary mapping. Hydraulic geometry
and properties continue to come from the original HDF; neither hydraulics nor
the terrain is modified. No terrain healer is bundled or invoked by this API.
Mapping-time bbox/polygon masks retain global hydraulic inputs.

Fast-Map accepts these vectors from 0.8.0 onward; no new engine build is
required. Commander's `fim` extra requires Fast-Map **0.10.1** or later. The
new Commander keyword requires a version or source commit containing this
feature. On Linux x64 with glibc 2.28+, including
a Python 3.11 container with a Commander checkout copied to `/app`, install:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir '.[fim]' 'ras-commander-fast-map==0.10.1'
ENTRYPOINT ["python", "scripts/examples/map_supplied_wsel.py"]
```

Mount source HDF/geometry files, the TIFF, CSV and an output parent into the
container. Supply paths within that container; output folders must be new or
empty. The engine wheel needs no Rust compiler or system GDAL. The optional
Terrio healer in a consuming application is independent of this installation.
This Dockerfile is an installation recipe; qualification used Linux CPython
3.11 directly rather than a Docker build.

The runnable CSV example is `scripts/examples/map_supplied_wsel.py`. The
qualification harness `scripts/benchmarks/fim_supplied_wsel_compare.py` creates
complete tables through public native HDF readers and checks both complete
validity masks and every valid float32 bit against selector mapping. Davis
pipes/conduits Max and timesteps 54/108 pass on Windows and Linux with shuffled
IDs, one/four workers, two in-flight profiles and prepared snapshots, for plain
sloping and unweighted cell-face sloping. Explicit NaN dryness and a separately
changed terrain copy are also tested. See the
[qualification record](../development/fim-mapping-performance.md#caller-supplied-wsel-qualification).
Selector equivalence does **not** establish RAS Mapper parity for arbitrary
window aggregates, healed terrains or unqualified rendering combinations.
Existing depth-weighting/corner requirements and 2D-only restrictions remain.

## Additional sloping options (engine 0.5)

### Global terrain-lattice AOI coverage (engine 0.10.1)

Horizontal and sloping polygon masks require an engine advertising
`aoi_mask="global-terrain-lattice/1"`. An older engine raises explicitly for
polygon masking; unbounded and same-CRS bbox requests remain compatible.
The NumPy horizontal reference uses the same coverage contract.

AOI vertices are normalized once against the original terrain transform.
Pixels are tested at global centers `(column + 0.5, -row - 0.5)` in pixel units,
with y increasing northward. Even-odd scanlines include their lower-y endpoint
and exclude their upper-y endpoint. Filled spans include the left endpoint
and exclude the right. Rectangles therefore include their minimum x/y edges
and exclude maximum x/y edges. Holes, multipart polygons and reversed rings
retain this rule; bbox windows use the same normalized coordinate convention.
There is no geometric epsilon, resampling or added depth cutoff.

Integer crop offsets only select emitted pixels: they do not enter edge
intersection arithmetic. At exact pixel-center ties, this deliberately changes
coverage from legacy GDAL/terrio masks, whose inclusion can depend on crop
origin. It does not promise to reproduce those legacy ties. Hydraulic cell
ownership and interpolation are unchanged. Manifests identify the AOI rule.

The reproduction harness `scripts/benchmarks/fim_aoi_full_crop_compare.py`
compares bounded rasters with independently masked full results using the
NumPy rule, checking all extra/missing pixels and valid float32 bits. It also
counts reference-valid pixels omitted outside the bounded raster extent.
Retain the same source terrain TIFF and its grid/tile layout; changing or
retile-preparing the terrain is a different operation.

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
`slopingPretty` and its shallow-to-horizontal control.

Select `render_mode="slopingPretty"` for **Sloping (Cell Corners + Cell Faces)**.
This unweighted mode donates corner weights to adjacent cell faces.
`reduce_shallow_to_horizontal=True` uses native face-connectivity classifications
to paint qualifying shallow cells with their computed cell WSE, bypassing their
polygon interpolation work. That control requires slopingPretty; plain mode
rejects it. Neither mode applies an additional depth cutoff.

```python
manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "canonical_terrain.tif", "sloping_faces",
    profiles={"maximum": "Max", "t0054": 54},
    render_mode="slopingPretty",
    reduce_shallow_to_horizontal=True,
    threads=4,
)
```

The selected options and `rasmapper-sloping-with-faces/1` method appear in the
report and manifest. Plain mode retains `rasmapper-plain-sloping/1`.
Unweighted face mode, with the shallow control off or on, matches native 7.0.1
raw masks and float32 bits on Bald Eagle bridges Max and Davis timesteps 54/108,
with one/four workers on Windows and Linux x86-64. This does not establish
unweighted face-mode parity for the large eBFE cases or other HEC-RAS versions.
The physical-2D scope and standalone-storage-area exclusion apply to both modes.

## Depth-weighted sloping faces (engine 0.8)

Set `render_mode="slopingPretty", use_depth_weighted_faces=True` to rebalance
corner/face weights using native water depths. The shallow-to-horizontal control
remains independent. Both controls default to false; no added depth cutoff is
applied. Cell-face requests require engine 0.8's `native_donation_history`
capability; weighted requests also require `depth_weighted_faces`. Numeric corner reads
require the native fast-HDF corner reader; an older wheel without that entry
point raises explicitly. The HDF reader separately supports an explicit h5py
fallback, but the FIM pipeline never silently substitutes it.

The reader is included in published fast-HDF 0.2.3. The original qualification
used CI development wheels from commit
`6920fd8efb36831c32161156eee6c7635eee0229`, which also report version 0.2.2.
Check for the `mesh_corner_elevations` entry point; the version string alone is
insufficient for those historical development builds. Install fast-HDF 0.2.3 or
newer; the retained qualification records identify the original artifacts.

If the plan contains `FacePoints Elevation`, mapping reads it directly. Otherwise
prepare a fresh cache once on Windows with HEC-RAS 7.0.1 installed:

```python
prepared = RasFim.prepare_corner_elevations(
    "model.p02.hdf", "prepared_corners",
    rasmap_path="model.rasmap", terrain_name="Terrain",
)
manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "canonical_terrain.tif", "weighted_catalog",
    profiles={"maximum": "Max", "t0054": 54},
    render_mode="slopingPretty", use_depth_weighted_faces=True,
    reduce_shallow_to_horizontal=True,
    postprocessing_hdf=prepared["postprocessing_hdf"],
    polygon="reach.gpkg", threads=4, max_inflight_profiles=2, max_working_mib=4096,
)
```

Preparation uses the exact registered terrain and its modifications. It copies
stored property-table corner values when present; otherwise it runs the native
terrain corner sampler with obstructions enabled. It writes a fresh
`PostProcessing.hdf` and a receipt to a new/empty folder, leaves source HDF and
rasmap bytes unchanged, and returns separate preparation time. It does not run
hydraulics or export a reference map. Only this explicit preparation operation
loads HEC-RAS assemblies; ordinary mapping remains Rust-native.

`corner_elevation_source="auto"` refuses conflicting arrays. An explicit
`"geometry"` or `"mapping_cache"` selects that layout. Cache-only mapping also
requires the adjacent preparation receipt: it verifies the plan binding, cache
bytes and recorded terrain/rasmap source identities. Historical mesh terrain
dates can differ from fresh native sampling; only a verified current-terrain
preparation can supersede that stale-date result, and the original checks remain
in the manifest. A cache existing with the correct corner count is insufficient.

Pass the same cache arguments to `prepare_sloping_model` to share staged corner
inputs across reach requests. The context watches the cache, receipt and native
preparation dependencies. Changed inputs invalidate the context. Corner source,
dataset, hashes, terrain metadata and checks are returned under
`DataFrame.attrs["performance"]["corner_elevations"]`.
Receipts include relative source paths for moving a complete prepared workspace
between Windows and Linux. Recorded source files remain required for validation.
Byte-identical copies with changed timestamps are verified by their hashes;
verified digests are reused in a bounded cache keyed by file fingerprints.

The raster terrain must also represent the effective terrain used by the native
reference. Corner preparation does not change the supplied raster.
Cell-face donation additionally uses the source TIFF lattice and tile boundaries.
Preserve the native source grid and tile layout for stored-map matching; arbitrary
retiled/cropped terrain inputs and multi-source mosaics are not qualified for
this option. An AOI on the mapping call preserves the source tile layout and
replays the required predecessor geometry outside the output mask.

With depth weighting and shallow-to-horizontal enabled, engine 0.8 matches
native 7.0.1 Max Depth/WSE masks and float32 bits on Spring River, Spring Creek,
Bald Eagle dam break, Bald Eagle bridges, and Davis pipes/conduits. Comparisons
cover physical 2D output; River, Creek and bridges also match the entire native
raster grid including nodata borders. Standalone storage-area surfaces remain
excluded. See the [qualification and timing table](../development/fim-mapping-performance.md#depth-weighted-sloping-faces-engine-08)
for scope and timing details.

## Reuse prepared models across reach requests

Use `RasFim.prepare_sloping_model` when several reach requests use the same
computed model, terrain and profile selectors. Preparation returns a
`FimPreparedSlopingModel` context that retains Python-side model inputs and
staged native inputs until it is closed. Plain sloping retains compatibility
with engines 0.6/0.7; cell-face requests require engine 0.8.

```python
with RasFim.prepare_sloping_model(
    "model.p02.hdf", "canonical_terrain.tif",
    profiles={"t0054": 54, "t0108": 108},
    render_mode="slopingPretty",
    reduce_shallow_to_horizontal=True,
    threads=4,
    max_working_mib=4096,
    max_prepared_mib=1024,
) as model:
    first = model.map_profiles(
        "reach_one", profiles=["t0054", "t0108"],
        polygon="reach_one.gpkg", writer_threads=1,
    )
    second = model.map_profiles(
        "reach_two", profiles=["t0108"],
        polygon="reach_two.gpkg", writer_threads=1,
    )
    print(model.info)
```

The factory fixes the model, terrain, interpolation options, engine, native
worker count and available profile names. Its `profiles` maps names to `"Max"`
or zero-based stored timestep indices; omission prepares Max. A request's
`profiles` selects a subset of those **names**, rather than new timestep
selectors. Omit it to map the complete prepared set. Repeated selectors are
staged once, even when several names refer to the same result.

The context retains physical cell polygons and their spatial index, model
scope, engine capabilities, terrain metadata, complete staged mesh arrays and
the selected WSE rows in immutable temporary files. With `native_session=True`
(the default), a capable engine also retains one serialized process, native
geometry, interpolation stencils and terrain blocks across calls. Prepare the
union of the needed timestep selectors once, then keep the context open while
mapping successive reaches. `native_session=False` starts a fresh native
process per request. Numeric HDF staging uses bounded contiguous-time slabs.

Fast-Map 0.11.0 additionally advertises `hydraulic_cache` and
`multi_window_cache`. `hydraulic_cache_mib` (default 64) retains reconstructed
hydraulic state by staged WSE-file identity and interpolation options, sharing
it across different reaches. `window_cache_mib` (default 64) bounds an LRU
cache of ownership, terrain and plain-sloping weights for multiple windows.
Larger budgets can retain more reaches; measure them against the workload.
`validation_cache_mib` (default 8) retains successful overlap/validity checks
for identical cell subsets. It never certifies a different or larger subset.
Each cache accepts 0 to disable retention and integers through 4096 MiB.
On older engines, hydraulic caching is disabled and recorded as zero; changing
the window budget from 64 requires the new capability. Native cache budgets
are admitted inside `max_working_mib`; validation retention is reserved inside
`max_prepared_mib`, capped at one eighth of that budget.

Each request resolves its bbox or polygon, plans the output window, validates
selected cell overlaps, builds ownership and raster arrays, and writes its
products. Complete global mesh topology and prepared results remain available
at AOI boundaries. `template_raster`, `write_floodplain`, `writer_threads`,
`max_inflight_profiles`, `timeout` and AOI inputs have the same meaning as on
`map_sloping_profiles`. The output folder must be new or empty. A request can
override the factory's `max_working_mib`; compression has its separate worker
budget. Preparation does not change the physical-2D mapping scope, native
qualification scope or zero-added-cutoff behavior described above.

`max_prepared_mib` admits a retained-geometry estimate, actual staged-file bytes
and the validation-cache reservation. The fixed prepared profile set and
bounded caches constrain retained state across requests. This budget and
`max_working_mib` are admission checks, not limits on
process RSS or total Python/GDAL memory; transient HDF reads and preparation
allocations are outside retained admission. Preparation that exceeds its budget
raises and cleans its temporary inputs. `info` returns a copy of preparation
metadata, including counts, planned/staged bytes and `prepare_seconds`. Each
request retains this copy in `attrs["performance"]["prepared_context"]`; its
`total_seconds` measures that request and excludes the earlier preparation.

The context checks HDF, terrain and engine size and nanosecond modification
time before and after preparation and each mapping request. It also watches
the source-text geometry file when the 2D-model guard resolves one. These are
file identity checks, not content hashes. If no source-text geometry was
initially available, model scope is rechecked; a newly resolved geometry file
requires a new context. A changed source invalidates and closes
the context, then raises; create a new context explicitly to use changed
inputs. Request-specific polygon and template files retain their own identity
checks. Inputs are read-only. A failed mapping request removes that request's
delivered products; source invalidation also releases the prepared state.

Use the context manager to release temporary inputs on success or exception.
Alternatively call `close()` explicitly; it is idempotent, and `closed` reports
whether the context has been released. Calls on one context are serialized,
including calls from different threads; `close()` waits for an active request.
A closed context cannot map again. This synchronization does not provide
cross-context scheduling or combine their memory and worker budgets.

With Fast-Map 0.11.0, `RasFim.map_sloping_profiles(...,
product_writer="native")` and the context's `map_profiles()` write terrio LZW
GeoTIFFs directly without
transferring raster arrays through Python. The default remains `"rasterio"`.
Native delivery requires `native_geotiff_outputs`, preserves float32 pixels,
NaN nodata and the requested CRS/grid, and uses one compression worker.
It currently excludes templates, floodplain polygonization and velocity.
The same cache and writer controls are available on `RasFim.map_catalog()`;
native catalog delivery currently requires sloping jobs. These capabilities
are part of the 0.11.0 release line; use an explicit qualified engine build
until that release is published.

See the [prepared-context evidence](../development/fim-mapping-performance.md#prepared-model-contexts-across-reach-requests)
for reuse behavior and numerical comparison scope.

## Bounded timestep concurrency (engine 0.6)

Set `max_inflight_profiles=2` or `4` on `map_sloping_profiles` to evaluate
several timesteps concurrently. The default remains one. Geometry, interpolation
stencils, ownership and terrain are shared; each profile has independent
hydraulic reconstruction and output arrays. Per-profile arithmetic is unchanged.

```python
manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "canonical_terrain.tif", "reach_catalog",
    profiles={"t0054": 54, "t0108": 108},
    polygon="reach_boundary.gpkg",
    threads=4,
    writer_threads=1,
    max_inflight_profiles=2,
    max_working_mib=4096,
)
report = manifest.attrs["performance"]["engine_report"]
print(report["effective_inflight_profiles"])
```

All concurrent maps use the same `threads`-sized Rust pool. Effective concurrency
is capped by this limit, profile count and memory admission. If only one map
fits the planned budget, the engine uses one; if the serial plan exceeds the
budget, it raises before allocating raster arrays. This is planned admission,
not an enforced process RSS limit. Python/GDAL memory is additional.

The scheduler processes bounded batches and emits maps in request order, even
if later profiles finish first. A failed batch aborts the session and removes
earlier delivered products. Reports record requested/effective concurrency,
planned bytes and each additional slot's allowance. Per-profile elapsed stage
times overlap, so their sum is not aggregate wall time.

HDF row reads and binary staging remain sequential before Rust starts, and
Python writes products sequentially. Compression can overlap subsequent native
work; `writer_threads` remains a separate budget. Throughput gains therefore
depend on the workload. Older engines retain the default sequential path;
requesting concurrency without the advertised capability raises explicitly.

## Map on the priority-1 terrain source (no terrain export)

RAS Mapper writes stored maps per terrain source, on that source's own grid.
Inside the footprint of the highest-priority source, the effective terrain is
that source's original TIFF. Pass the registered terrain HDF as `terrain_hdf`
and its priority-1 source TIFF as `terrain_path`; no RAS Mapper terrain export
or HEC-RAS installation is needed.

```python
source = RasFim.top_priority_terrain_source("Terrain/Terrain50.hdf")
# {'tif': Path('Terrain/Terrain50.dtm_20ft.tif'), 'source_count': 2,
#  'modified': False, 'priority_basis': 'vrt_order', ...}
manifest = RasFim.map_sloping_profiles(
    "model.p05.hdf", source["tif"], "maps",
    terrain_hdf="Terrain/Terrain50.hdf", velocity=True,
)
manifest.attrs["terrain_scope"]   # method, source, priority basis, mask dataset
```

- Priority comes from the source groups' integer `Priority` attributes (0 is
  the highest) or, when no source carries one, from the terrain's own VRT,
  which lists sources highest priority first. Partial, duplicate or
  conflicting declarations are refused.
- The engine (`top-priority-source-footprint/1`) reads the source's level-0
  terrain-HDF `Mask`. Pixels outside the footprint are accepted only in cells
  that fail the wet gate. Otherwise it refuses, and RasFim raises
  `FimUnsupportedError` so the caller can map on an exported terrain instead.
  Horizontal and whole-simulation requests have no wet-gate exemption, so any
  mapped pixel outside the footprint is refused.
- Terrains with modifications, non-256-tiled sources and plans with storage
  areas are refused. Plain sloping only for `map_sloping_profiles`.
- When the source TIFF's CRS is not readable by the engine, pass its
  `RasFim.canonicalize_terrain_crs()` copy; it is accepted through its receipt
  after the source pixels re-hash to the same value. For sloping, you can
  instead map the source TIFF directly with `terrain_crs_fnv1a64` (below).

**Terrain CRS the engine cannot identify (sloping).** HEC-RAS 7.0.1 can write
terrain GeoTIFFs whose WKT the engine reads as `PROJCS["unknown", ...]` with no
EPSG code, although rasterio identifies the EPSG code. Davis 7.0.1 is an
example. `map_sloping_profiles` and `prepare_sloping_model` then raise
`FimUnsupportedError`. Pass `terrain_crs_fnv1a64` with the
`crs_wkt_fnv1a64` value reported by `ras2fim-batch terrain-info <terrain>`,
as for `map_profiles`. The validation is the same:

- the hash must equal the engine's (otherwise `FimEngineError`);
- rasterio must still resolve the terrain CRS to an EPSG code equal to the
  results CRS;
- an engine-reported EPSG code takes precedence, and the hash is not used.

The accepted identity is recorded as `terrain_crs_identity` in
`fim_manifest.json` (and in a prepared model's `info`), for example
`{"kind": "caller_verified_wkt", "fnv1a64": "e446f7bd6bdb4d7f"}`. A prepared
model fixes the value at preparation.

On Davis 7.0.1 p02 (Max), mapping the original terrain with the hash gives
depth and WSE bit-identical to mapping its EPSG:2871 copy: 22,041 valid pixels,
directly, through a prepared model and with `terrain_hdf`.

Conformance against native HEC-RAS 7.0.1 stored maps (plain sloping, Max):

| Model | Terrain | Valid pixels | Depth/WSE mask and bit differences |
|---|---|---|---|
| BaldEagleCrkMulti2D bridges p05 | `dtm_20ft` (priority 1 of 2) | 973,902 | 0 / 0 |
| Davis p02 | canonical copy of the single source | 22,041 | 0 / 0 |

On bridges p05 the mapping itself takes about as long on the source TIFF as on
an export (7.3 s against 4.9 to 6.8 s end to end, six threads); the saving is
the export, which took 242.6 s through `RasTerrain.export_rasmapper_terrain`.
Bridges whole-simulation and horizontal requests are refused on the source
TIFF because 28 mapped 2D pixels lie outside its footprint.

## Sloping velocity

`velocity=True` adds `velocity_tif` (`12_<profile>_velocity.tif`) to each
manifest row, rendered by the engine's `rasmapper-sloping-velocity/0` method.
Max uses `Maximum Face Velocity` with the Max WSE; a timestep index uses
`Face Velocity` at that output time. Face normals carry face polyline lengths.
Velocity is drawn where the rendered depth is greater than zero. It requires
plain sloping with HDF profiles; `wsel_profiles`, `template_raster` and
storage-area plans are refused.

| Model (native 7.0.1, Max) | Common pixels | Bit differences | Mask differences |
|---|---|---|---|
| BaldEagleCrkMulti2D bridges p05 | 972,706 | 0 | 826 native-only, 1,196 extra |
| Davis p02 | 22,041 | 3 (at most 3e-8) | 0 |

The native velocity validity mask is not always the depth mask; the bridges
differences are edge pixels.

## Whole-simulation products

`map_whole_simulation` produces arrival time and percent time inundated (and,
opt-in, duration) from every stored output time, through the engine's
`native-whole-simulation-horizontal/1` method:

```python
manifest = RasFim.map_whole_simulation(
    "model.p02.hdf", "terrain.tif", "adr", threshold=0.5,
)  # products=("arrival_time", "percent_inundated")
manifest[["product", "tif", "units", "wet_pixels"]]
```

- A pixel is wet at an output time when its rendered depth is greater than
  `threshold` and its cell passes `wse > cell minimum + threshold` (float32).
- `arrival_time` is the first wet output time in hours since the plan's
  simulation start; `percent_inundated` is `100 * wet times / all times`.
  Never-wet pixels are NaN.
- `duration` requires `allow_unqualified=True`: some native recession
  durations are one output interval shorter. Irregular output intervals are
  also refused without it.
- Plans with storage areas or 1D elements are refused.

| Model (native 7.0.1, 0.5 ft) | Output times | Valid pixels | Arrival / percent differences |
|---|---|---|---|
| Davis p02 | 217 | 4,879 | 0 / 0 |
| BaldEagleCrkMulti2D bridges p05 | 433 | 959,043 | 0 / 0 |

Both match RAS Mapper's horizontal and sloping stored maps, which are identical
on these models. These methods target pure 2D models for FIM library creation;
1D models, storage areas and other products remain with RAS Mapper.

## Horizontal cell mapping

Horizontal method /2 requires engine 0.7 or newer. Older /1 engines raise explicitly.

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

NaN WSE marks dry cells; callers supply the cell wet/dry policy. Native pixel
visibility compares `WSE >= float32(terrain + 0.001)` in float32 before depth
subtraction. Preserve that order: comparing the resulting depth against 0.001
would remove some native-valid boundary pixels. Native-valid zero depths can
also occur when terrain-plus-tolerance rounds back to terrain.

`min_depth=0` adds no depth cutoff. A positive `min_depth` optionally retains
only depths strictly greater than that value after native visibility, masking
Depth and WSE together. All thresholds use model elevation units; they do not
convert feet to metres or establish a vertical datum. This intrinsic native
plotting tolerance is separate from optional depth postprocessing.

The returned `fim_product_manifest` has the same columns and 09/10/11 filename
layout as Step05 products; those names do not identify the mapping method.
The JSON manifest records `method_id="horizontal-cell-constant/2"`,
`backend="rust"` (or the explicitly requested reference backend), float32 arithmetic,
the native plot tolerance, optional positive cutoff, source identities and
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

Both comparison APIs now default to zero added cutoff;
`compare_with_rasmapper` also defaults to no reference-delivery rewrite.
For zero-cutoff raw comparison, `RasFim.compare_rasters(..., min_depth=0)`
preserves every valid pixel, including zero depths, and compares float32 bits.
Positive cutoffs remain optional independent filters of candidate and reference.
A missing zero-depth pixel is a mask difference; matching common values alone
does not establish raster parity. The standalone
`scripts/benchmarks/fim_horizontal_parity.py` runner checks complete physical-2D
masks and float32 values against retained native references, requiring zero
extra, missing, different and outside-footprint pixels for both products.

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
    ras_version="7.0.1",
    min_depth=0.0,       # raw comparison; no added depth cutoff
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
original/restored `.rasmap` hashes. Positive optional cutoffs apply to both
depth masks independently; zero preserves all valid pixels. The native TIFFs remain unmodified. No reference resampling is
performed: incompatible CRS, pixel sizes or fractional grid shifts fail.

The optional strict pixel filter is `min_depth`: direct horizontal mapping
and comparison both default to `0.0` in model elevation units.
Both depth and WSE use the retained depth mask. `0.0` preserves all valid pixels, including zero depths. Cell extraction's `min_depth` is a
separate cell wet/dry policy, not the raster postprocessing threshold.

With `postprocess_reference=True`, comparison also writes independently
thresholded native LZW delivery rasters, preserving the raw references. Timing columns distinguish
`native_seconds` (stored-map generation), `native_postprocess_seconds`,
`native_total_seconds`, `candidate_batch_seconds` and `comparison_seconds`.
`candidate_seconds` is populated only for a single-profile call; shared batch
time is not allocated repeatedly to individual profiles. Filtered native
paths are returned separately. The default `postprocess_reference=False`
omits these delivery rewrites. Positive cutoffs still apply independently
when computing comparison metrics.

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
An earlier /1 qualification retained 50 additional pixels below 0.001 ft.
That is historical evidence, not the current /2 status: engine0.7 now matches
complete zero-added-cutoff masks and float32 values on the four completed
full-model native cases documented in the performance page. The half-foot
filter remains optional, rather than the comparison default.

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
build instructions are in the external
[ras-commander-fast-map repository](https://github.com/gpt-cmdr/ras-commander-fast-map).
The standalone package preserves the qualified 0.8 numerical methods. Windows
and Linux wheels are qualified; individual method/model scopes are listed in
the performance report.

`RasFim` resolves the engine in this order:

1. the `engine_path=` argument;
2. the `RAS_COMMANDER_FIM_ENGINE` environment variable;
3. `ras2fim-batch` on `PATH`;
4. the script recorded by the installed `ras-commander-fast-map` distribution.

A missing engine raises `FimEngineNotFoundError`. Runtime calls never build,
download, or install the engine, and there is no Python fallback for this
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

## Schedule reach/timestep catalogs

Use `RasFim.map_catalog()` when each reach has a known list of relevant saved
output times. Pass the NextGen watershed polygon associated with each reach;
the library does not infer a watershed from a flowline or buffer it.

```python
from ras_commander import RasFim

jobs = [
    {
        "job_id": "reach_a", "reach_id": "wb-example-a",
        "hdf_path": "model.p02.hdf", "terrain_path": "mapping_terrain.tif",
        "polygon": "watersheds.gpkg", "polygon_layer": "reach_a",
        "timesteps": [48, 49, 54, 108],
    },
    {
        "job_id": "reach_b",
        "hdf_path": "model.p02.hdf", "terrain_path": "mapping_terrain.tif",
        "polygon": "watersheds.gpkg", "polygon_layer": "reach_b",
        "timesteps": [108, 48, 108],
    },
]
products = RasFim.map_catalog(
    jobs, "catalog_output", threads=4, max_workers=1,
    max_memory_mib=8192, max_working_mib=2048, max_prepared_mib=1024,
    max_profiles_per_batch=64,
)
print(products[["job_id", "request_ordinal", "timestep", "status"]])
print(products.attrs["performance"])
```

Job and timestep order in the result follows the input, even when execution is
reordered. Repeated selectors produce separate ordinal Depth/WSE files; shared
staging does not remove requested outputs. `job_id` is a unique,
case-insensitive folder name matching `[A-Za-z0-9_-]{1,64}`, excluding reserved
Windows file names. Output folders must be new or empty. Use `"Max"` for a Max
profile. Integer selectors are zero-based saved-output indices, not elapsed
hours. Complete hydraulic topology is retained and no depth cutoff is added.

Jobs default to plain sloping. Set `interpolation="horizontal"` within a job
for cell-constant mapping. Sloping jobs also accept `render_mode`,
`reduce_shallow_to_horizontal`, `use_depth_weighted_faces`,
`postprocessing_hdf`, `corner_elevation_source` and `invalid_cells` from the
existing sloping API. A job accepts one polygon or bbox, with the existing
`polygon_layer`/`aoi_crs` rules. Unknown fields raise. Velocity, terrain
preparation, supplied WSEL tables and floodplain polygonization remain separate
operations; the catalog does not run HEC-RAS.

### Build jobs from a watershed layer

When one vector layer contains many watersheds, select each feature before
creating its job. Passing the complete layer to every job maps the same union
repeatedly. The example below uses the caller's reach-to-time selection; it
does not derive relevant hydraulic conditions or select times automatically.
Replace `divide_id` with the actual watershed identifier column.

```python
import geopandas as gpd
from ras_commander import RasFim

watersheds = gpd.read_file("watersheds.gpkg", layer="divides")
times_by_reach = {
    "wb-example-a": [48, 49, 54, 108],
    "wb-example-b": [108, 48, 108],
}
jobs = []
for ordinal, (reach_id, times) in enumerate(times_by_reach.items()):
    area = watersheds.loc[watersheds["divide_id"] == reach_id].copy()
    if len(area) != 1 or area.crs is None:
        raise ValueError(f"Expected one georeferenced watershed for {reach_id}")
    jobs.append({
        "job_id": f"reach_{ordinal:06d}", "reach_id": reach_id,
        "hdf_path": "model.p02.hdf", "terrain_path": "mapping_terrain.tif",
        "polygon": area, "timesteps": times, "interpolation": "sloping",
    })

if __name__ == "__main__":
    products = RasFim.map_catalog(
        jobs, "catalog_output", strategy="reuse",
        threads=4, max_workers=1, writer_threads=1,
        max_inflight_profiles=1, max_profiles_per_batch=32,
        max_memory_mib=8192, max_working_mib=4096,
        max_prepared_mib=1024, memory_headroom_mib=256,
        window_cache_mib=64, hydraulic_cache_mib=64, validation_cache_mib=8,
        product_writer="native", raise_on_failure=False,
    )
    print(products[["job_id", "request_ordinal", "timestep", "status"]])
    print(products.attrs["catalog_status"])
    print(products.attrs["performance"])
    print(products.attrs["catalog_manifest"])
```

This example needs the catalog API and an engine advertising
`native_geotiff_outputs` (Fast-Map 0.11.0 release line). Before publication,
use an explicit qualified development engine. Check
`RasFim.get_engine_info()["method"]["sloping"]`; capability flags, rather than
the version string alone, control support. Use `product_writer="rasterio"`
for horizontal jobs or the default delivery path. Native output currently
supports sloping jobs without velocity, templates or floodplain polygonization.
Keep the `__main__` guard when placing the call in a Python script.

The selected GeoDataFrame carries its CRS; Shapely geometries need an explicit
`aoi_crs`. To use a bbox instead, replace `polygon` with
`bbox=(xmin, ymin, xmax, ymax)` and identify its CRS. A job has one AOI; use
separate jobs for separate area/time groups, even when reach IDs repeat.
Polygon holes and multipart geometry remain part of the mask. Do not replace
a watershed with its bounding rectangle when its exact coverage is required.

Use a single qualified mapping TIFF. Resolve multiple terrain sources or
terrain modifications into a mapping terrain before catalog execution and
verify its CRS and surface against the intended reference. Cell-face parity
also depends on the qualified source grid/tile layout; an arbitrary mosaic or
retile is not qualified by these examples. Apply the AOI at mapping time rather
than making an independently cropped terrain per reach. The catalog currently
does not accept the one-shot/prepared `terrain_crs_fnv1a64` override.

### Choose a throughput policy

| Workload | Starting policy | What to measure next |
|---|---|---|
| Many polygons on one model/terrain with overlapping time lists | `strategy="reuse", max_workers=1` | Hydraulic cache hits and full-catalog wall time; increase hydraulic retention only if reconstructed times can remain resident. |
| Repeated requests for the same windows | Keep reuse and the default window/validation caches | Window hits, retained bytes and peak process-tree memory; window retention alone did not improve the Spring Creek pilot median. |
| Independent models or little shared preparation | Try `strategy="parallel", max_workers=2` | Total makespan against reuse with the same global CPU/RAM budgets; preparation and caches may be duplicated. |
| Many times within one polygon | Start with `max_inflight_profiles=1`; test 2 | Native admission, memory high-water mark and whole-call time. In-flight profiles share a worker's Rayon pool; they do not add CPUs. |
| Very long or mostly disjoint time lists | Bound `max_profiles_per_batch` | Staging cost versus extra preparation waves. Smaller batches bound staged results but can reduce reuse. |

The example's 4 GiB working allowance is a starting configuration, not a
prediction of required memory. One worker reserves 4,096 + 1,024 + 256 =
5,376 MiB for admission. Two such workers need at least 10,752 MiB of global
allowance and sufficient available host memory; an 8,192 MiB allowance admits
only one. Increasing `max_workers` alone does not override these checks.

Cache ceilings are reservations within the existing working/prepared budgets,
not additional memory allowances. Increase the working budget together with
larger native caches. Zero disables a cache. Complete hydraulic topology and
selected WSE rows remain global, including cells outside the AOI; terrain and
output operations are windowed. A small watershed therefore does not imply a
proportional reduction in startup, HDF staging, hydraulic reconstruction or
total memory. The API uses bounded time-slab HDF reads and native terrain block
reads; do not manually clip hydraulic arrays to a reach.

Use a new output folder for each tuning trial. Compare the returned
`performance` attributes and `catalog_manifest.json`, including actual CPU
partitions, wall time, sampled RSS/private memory and per-request cache reports.
Inspect `catalog_status` and each row's `status`; an empty/dry AOI can be a
legitimate result, while `failed`, `not_run` and cancellation require handling.
With `raise_on_failure=False`, the partial manifest is returned for inspection;
it does not turn a partial catalog into a complete one. Retry in a fresh folder.

### Reuse, concurrency and memory admission

`strategy="reuse"` combines compatible model/terrain/method/options groups,
stages their selected-time union once and keeps identical windows adjacent.
Each sloping preparation wave owns one serialized native session. Terrain
tiles, geometry and eligible plain-sloping weights can be reused. Horizontal
waves retain one cell table with directly assigned float32 profile columns.
`max_profiles_per_batch` bounds both request occurrences and unique staged
selectors; a longer union creates further preparation waves. A wave never
prunes hydraulic dependencies to the polygon.

Start with one worker. To measure independent jobs concurrently, set
`strategy="parallel", max_workers=2` (or another bound). This keeps jobs as
independent units and can duplicate source preparation/cache memory. The
scheduler has no universal fitted speedup rule: the documented Spring Creek
pilot favored reuse over multiplying workers. Choose the policy from measured
whole-catalog makespan, including initialization and writes.

The global `threads` budget selects logical CPUs from the caller's allowed
affinity set and partitions them among admitted worker processes. Native and
compression threads inherit each partition. `writer_threads` must fit every
partition; it does not gain extra CPUs. `max_inflight_profiles=1` remains the
default. Windows/Linux CPU-affinity support is required; the caller's own work
is outside this worker budget.

Before launch, each worker reserves
`max_working_mib + max_prepared_mib + memory_headroom_mib`. The scheduler reduces
worker count to fit this reservation under `max_memory_mib`; it refuses a plan
that cannot admit one worker. Admission is also capped by currently available
host memory minus headroom. Native and prepared limits retain their existing
planned-allocation meanings. Decoder temporaries and runtime overhead are not
exact RSS predictions. The supervisor samples aggregate worker/descendant RSS
and private memory, aborting on a sampled budget excess or low available host
memory. Sampling can miss short peaks; these controls are not hard OS memory
limits. The caller's pre-existing memory is excluded. Set budgets using
observed high-water marks with headroom. On platforms without a private-byte
counter, the private-memory field uses an RSS proxy; the
published Windows table reports the actual private/commit counter.

### Results, cancellation and partial catalogs

`fim_catalog_manifest` adds `job_id`, `reach_id`, `request_ordinal` and
`timestep` to the existing product columns. `catalog_manifest.json` records job
snapshots, source identities, CPU partitions, controls, per-request native
reports and overall timing/sampled-memory evidence. Each job also has a
`fim_manifest.json`. Native per-request reports are stored in the job's
`request-*.json` files. While running, per-job manifests contain acknowledged
rows; the compact top-level checkpoint links them. Final rows are also inlined
in the top-level receipt. Empty AOIs retain their existing mapping status.

Pass a `threading.Event`-compatible `cancel_event` to request cancellation.
Cancellation and job failures stop admission, terminate owned workers and
native descendants, remove uncommitted files, and preserve acknowledged
products and an aborted/cancelled receipt. Pending rows are marked explicitly.
By default a `FimMappingError` carries the partial DataFrame in `manifest`;
`raise_on_failure=False` returns it. This is a fail-fast catalog, not a retry or
resume API. Use a new output folder for a retry. `timeout` applies to each
native batch; it is not a whole-catalog deadline.

See [catalog measurements and reproduction](../development/fim-mapping-performance.md#reach-timestep-catalog-throughput).

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

::: ras_commander.fim.FimPreparedSlopingModel
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
