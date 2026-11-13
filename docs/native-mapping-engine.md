---
title: Native Rust Mapping Engine
description: Map computed HEC-RAS results to rasters and inundation boundaries.
---
<a id="mapping-computed-results"></a>

<a id="flood-inundation-mapping-optional"></a>

# Native Rust Mapping Engine

`RasFim` maps computed HEC-RAS profiles to depth and water-surface elevation
(WSE) rasters. The 2D routes provide ras2fim-2D Step 05, horizontal and sloping
surfaces; canonical 1D and mixed routes provide explicitly gated prepared
Depth/WSE workflows. Mapping shares terrain across profiles, accepts a bounding
box or polygon area of interest (AOI), and returns a product manifest DataFrame.

## Install and inspect capabilities

The `fim` extra installs the
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

Use typed discovery to distinguish an advertised feature from a numerical
qualification claim:

```python
from ras_commander import RasFim

capabilities = RasFim.get_capabilities()
sloping = capabilities.methods["sloping"]
print(sloping.api_contract, sloping.intended_use)
print(sloping.numerical_qualification)
```

An absent qualification declaration remains unknown. Diagnostic methods retain
their published request schemas for reproducibility. Canonical 1D/mixed
preparation is available through the explicit opt-in APIs below; discovery does
not establish general numerical qualification or support for refused variants. `supports_storage_areas()` and
`supports_effective_terrain()` return `False` for a missing engine or feature;
engine failures and malformed metadata raise instead.

<a id="select-the-surface-method"></a>

## Select a mapping method

| Feature | Entry point |
|---|---|
| Cell-corner and cell-face sloping surfaces | `RasFim.map_sloping_profiles()` |
| Cell-constant surfaces | `RasFim.map_horizontal_profiles()` |
| Storage-area level pools | `storage_areas=True` on supported mapping calls |
| Velocity and depth/velocity products | `velocity=True`, `derived_products`, `RasFim.map_derived_max()` |
| Max shear stress | `shear_stress=True` on `RasFim.map_sloping_profiles()` |
| Arrival time, duration and percent inundated | `RasFim.map_whole_simulation()` |
| Repeated reach/timestep jobs | `RasFim.map_catalog()` |
| Zero-depth vector boundaries | `RasFim.map_inundation_boundaries()` |
| Triangulated ras2fim-2D catalogs | `RasFim.map_profiles()` |
| Stored 1D Depth/WSE with diagnostic opt-in | `RasFim.prepare_one_d_model()`, `RasFim.map_one_d_profiles()` |
| Mixed 1D/2D Depth/WSE with diagnostic opt-in | `RasFim.prepare_coupled_model()`, `RasFim.map_coupled_profiles()` |

<a id="experimental-plain-sloping-mapping"></a>

<a id="map-several-timesteps-within-a-reach"></a>

## Plain sloping mapping

Use `map_sloping_profiles` to reconstruct RAS Mapper's plain **Sloping (Cell
Corners)** method from computed 2D HDF results. Inspect installed capabilities
with `RasFim.get_capabilities()` and check the qualification scope below.
Request-contract stability and numerical qualification are separate: a stable
transport does not establish parity for every model or option combination.
Commander provides explicit, qualification-gated 1D preparation through
`prepare_one_d_model()` and mixed-model preparation through
`prepare_coupled_model()`. Both require explicit unqualified execution opt-in.
The 2D entry points continue to refuse 1D/mixed inputs.

Use `RasFim.inspect_model_scope(hdf_path)` to inspect dimensional metadata before
choosing a mapping route. The immutable result distinguishes 1D, 2D, mixed
1D/2D and storage-only geometry, including source reach declarations when
available. Its candidate method keys describe dimensional applicability;
check installed capabilities and qualification separately. Inspection does not
load an engine, run HEC-RAS or bypass `validate_2d_model()`.

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

Numeric HDF payloads require the native Rust backend. Typed cell coordinates
avoid Shapely point construction. Immutable per-mesh result views are reused
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
Standalone storage-area surfaces outside the 2D mesh are excluded unless
`storage_areas=True` (see [Storage-area level pools](#storage-area-level-pools)).
The return attributes `mapping_scope` and `model_scope`, and the JSON manifest,
record this boundary. The Bald Eagle dam-break reference also renders a storage area;
its exact sloping comparison is restricted to physical 2D cells, not the whole
native model image.

The method adds **no depth postprocessing cutoff**. It reproduces the native
float32 plot tolerance of 0.001 in model elevation units, including native
rounding; it does not replace this behavior with a 0.5 ft filter. The default disables shallow-to-horizontal rendering and
cell-face stencil enrichment. HEC documents these distinct controls in
[Mapping Options, HEC-RAS Mapper User's Manual 6.6](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/mapping-results/mapping-options).

Retained 7.0.1 comparisons report matching valid/nodata masks and every
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
[performance evidence](development/fim-mapping-performance.md#plain-sloping-development-qualification).

The retained matching runs do not establish universal repeatability. A matched
Spring Creek repeat-export comparison found 19 native Depth/WSE pixels changed
while Fast-Map output stayed stable; the cause remains unresolved. Preserve
source/runtime identity and compare complete masks and Float32 bits for each
qualification scope.

The API writes products to a new or empty directory, records the engine method,
native option contract and timings, and removes products if the session aborts.
Performance evidence is returned in `attrs["performance"]` and retained in
`fim_manifest.json`. The memory budget is planned admission rather than an
enforced process RSS limit; HDF/Python preparation and polygonization also use
memory. A missing or incompatible engine raises without fallback. Mapping itself
does not load HEC-RAS assemblies; the private native component oracle is used
only during development qualification.

### Native runtime comparison scope

Within the stated coverage, the native-runtime checks below compare complete
valid/nodata masks and every valid Float32 bit, with exact CRS and integer-window
framing. They use the
frozen Windows engine artifact, original terrain layouts and complete global
hydraulic geometry. The criterion is numerical equality to the named native
renderer, not calibration or general model qualification.
Runtime versions identify the loaded Mapper, independently of the stored
results' producer. These checks do not rerun the hydraulic solver or establish
solver-version equivalence.

| Fixture and options | Native runtime | Products and coverage | Result |
|---|---|---|---|
| Mixed XS/2D fixture; plain corners, original single source, explicit stored-tile-grid `/1`; saved 57/69/81 and Max | 6.6 and 7.0.1 | Depth/WSE, eight complete products per runtime | Exact |
| Bald Eagle; original two-source terrain and priority-mask history; Max, saved 72 and all 145 saved times | 6.6 and 7.0.1 | Twelve complete spatial/velocity/derived-Max products per runtime | Exact; temporal products are outside this result |
| Baxter; Big/Bigger/Biggest steady profiles and prepared storage/XS composition; GDAL one thread, 128 MiB cache, native CPU one | 6.6 and 7.0.1 | Six complete Depth/WSE products per runtime, 4,838,744 pixels each | Exact; fresh exports and actual loaded renderer hashes verified |
| Lawson and White Oak; selected canonical 1D profiles, native-normalized M and obstruction records | 6.6 | Four stripe-pilot Depth/WSE products | Exact only within the recorded stripes |
| Lawson and White Oak p19/p15; selected canonical 1D profiles | 7.0.1 | Six complete Depth/WSE products, contiguous stripes plus zero-valid exterior scans | Exact |

The 7.0.1 mandatory matrix has **32 of 32 products exact**. These cases do not enable diagnostic defaults or
qualify other profiles, terrain configurations, geometry variants or platforms.
The 6.6 stripe pilots are not full-raster canonical 1D qualification.

These frozen checks preserve raw native georeferencing (`fix_georef=False`),
source terrain identity and complete physical geometry. A matching subset must
also account for native-valid pixels outside the delivered window. Runtime
version, source preparation and artifact identity are separate evidence; a
package version alone does not identify a qualification artifact.

Davis entries elsewhere on this page describe retained comparison preparations.
They do not establish original-source raw-native-grid equality. Fresh 7.0.1
Davis checks stop at grid framing before mask/value comparisons, and the
explicit stored-tile-grid `/1` contract rejects its differing logical-tile and
output-affine centers. No source-tag replacement, coordinate fitting or
resampling is used to bypass that refusal.

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

<a id="map-caller-computed-elevations"></a>

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

On Linux x64 with glibc 2.28+, including
a Python 3.11 container with a Commander checkout copied to `/app`, install:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir '.[fim]'
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
[qualification record](development/fim-mapping-performance.md#caller-supplied-wsel-qualification).
Selector equivalence does **not** establish RAS Mapper parity for arbitrary
window aggregates, healed terrains or unqualified rendering combinations.
Existing depth-weighting/corner requirements and 2D-only restrictions remain.

<a id="additional-sloping-options-engine-05"></a>

## Additional sloping options

<a id="global-terrain-lattice-aoi-coverage-engine-0101"></a>

### Global terrain-lattice AOI coverage

Horizontal and sloping polygon masks require an engine advertising
`aoi_mask="global-terrain-lattice/1"`. An engine without this capability refuses
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

<a id="depth-weighted-sloping-faces-engine-08"></a>

<a id="prepare-corners-for-depth-weighting"></a>

## Depth-weighted sloping faces

Set `render_mode="slopingPretty", use_depth_weighted_faces=True` to rebalance
corner/face weights using native water depths. The shallow-to-horizontal control
remains independent. Both controls default to false; no added depth cutoff is
applied. Cell-face requests require the `native_donation_history`
capability; weighted requests also require `depth_weighted_faces`. Numeric corner reads
require the native fast-HDF corner reader; a wheel without that entry
point raises explicitly. The HDF reader separately supports an explicit h5py
fallback, but the FIM pipeline never silently substitutes it.

Check for the native `mesh_corner_elevations` entry point before preparing
weighted requests. Retained qualification records identify the tested artifacts.

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

With depth weighting and shallow-to-horizontal enabled, retained comparisons match
native 7.0.1 Max Depth/WSE masks and float32 bits on Spring River, Spring Creek,
Bald Eagle dam break, Bald Eagle bridges, and Davis pipes/conduits. Comparisons
cover physical 2D output; River, Creek and bridges also match the entire native
raster grid including nodata borders. Standalone storage-area surfaces remain
excluded. Spring Creek repeat-export variation remains unresolved, as described
under plain sloping. See the [qualification and timing table](development/fim-mapping-performance.md#depth-weighted-sloping-faces-engine-08)
for scope and timing details.

## Reuse prepared models across reach requests

Use `RasFim.prepare_sloping_model` when several reach requests use the same
computed model, terrain and profile selectors. Preparation returns a
`FimPreparedSlopingModel` context that retains Python-side model inputs and
staged native inputs until it is closed. Cell-face requests require the
advertised face-mode and native donation-history capabilities.

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

The `hydraulic_cache` and `multi_window_cache` capabilities control native
retention. `hydraulic_cache_mib` (default 64) retains reconstructed
hydraulic state by staged WSE-file identity and interpolation options, sharing
it across different reaches. `window_cache_mib` (default 64) bounds an LRU
cache of ownership, terrain and plain-sloping weights for multiple windows.
Larger budgets can retain more reaches; measure them against the workload.
`validation_cache_mib` (default 8) retains successful overlap/validity checks
for identical cell subsets. It never certifies a different or larger subset.
Each cache accepts 0 to disable retention and integers through 4096 MiB.
Without hydraulic-cache support, caching is disabled and recorded as zero;
changing the window budget from 64 requires `multi_window_cache`. Native cache budgets
are admitted inside `max_working_mib`; validation retention is reserved inside
`max_prepared_mib`, capped at one eighth of that budget.

Stateless `RasFim.map_sloping_profiles()` calls reuse a passed cell validation
when the planned cell polygons are unchanged. The key is a SHA-256 of the
ordered polygon coordinates and ring structure with the Shapely and GEOS
versions, not a file name, size or timestamp, so a changed geometry, AOI cell
subset or library version validates again. Only passes are recorded, as small
JSON files under the user data directory (`fim-cell-validation`); a missing,
damaged or mismatching record runs the full validation.
`RAS_COMMANDER_FIM_VALIDATION_CACHE` names another directory, and `0` or `off`
keeps reuse inside the process. `preparation.cell_validation_reused` reports
the outcome. The overlap check uses up to `threads` workers; accepted and
refused cell sets are unchanged.

A positive-area overlap is accepted only as coordinate-roundoff residue: its
area fits an eight-ULP boundary-error envelope at the coordinates' scale and
no output pixel centre of the planned window lies inside it (checked in both
the cropped and the global terrain-lattice arithmetic). Each accepted residue
raises a `RuntimeWarning`; ownership polygons and hydraulic topology are
unchanged. Because that judgement depends on the grid plan, a validation that
accepted any residue is never recorded for reuse, by the stateless store or by
a prepared model's `validation_cache_mib` cache, and is repeated on every call.

### Engine-written final delivery format

`final_format` on `RasFim.map_sloping_profiles()`, a prepared model's
`map_profiles()` and `RasFim.map_catalog()` asks an engine advertising
`native_final_format` to write Depth and WSE once in their delivery form: a
tiled DEFLATE (predictor 1) float32 GeoTIFF with a numeric nodata value. It
requires `product_writer="native"`. No array is streamed to Python and Rasterio
writes nothing, so there is no fallback: an engine without the capability is
refused before inputs are staged.

```python
RasFim.map_sloping_profiles(
    plan_hdf, terrain_tif, output_folder, profiles={"Max": "Max"},
    product_writer="native",
    final_format={"nodata": -9999.0, "overviews": [2, 4], "grid": "terrain"},
)
```

| Key | Default | Contract |
|---|---|---|
| `nodata` | required | Finite and exactly representable as float32; written for every invalid pixel |
| `block_size` | 256 | Square tile edge, a multiple of 16 from 16 through 4096 |
| `zlevel` | 6 | zlib level 1 through 9 |
| `overviews` | `[]` | Consecutive powers of two such as `[2, 4]`; GDAL average arithmetic |
| `grid` | `"window"` | `"window"` (the mapped window), `"terrain"` (the whole terrain grid) or `[col, row, width, height]` terrain pixels that contain the mapped window |

Product names (`09_<profile>_depth_nudge.tif`, `10_<profile>_wsel_nudge.tif`)
are unchanged. Manifest rows describe the delivered grid (`col_off`, `row_off`,
`width`, `height`, `transform`), and the manifest `final_format` block records
the request, the window's position on that grid and, for full-array rendering,
the engine's per-file counts. Commander verifies the completion record and each
file (grid, CRS, float32, nodata, DEFLATE, tiling, overview factors and the
`rio_overview` resampling item) before moving it into the output folder.

Window pixels keep the product's float32 bits; only the invalid marker,
placement, tiling, compression and overviews differ from the Rasterio route. A
valid value that is infinite, or that GDAL's nodata mask would read as the
nodata value, is refused with `FimUnsupportedError` rather than masked; choose
a nodata value outside the product range. Floodplain polygons, template
delivery, velocity and derived products need arrays in Python and stay on the
Rasterio writer.

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

`RasFim.map_sloping_profiles(...,
product_writer="native")` and the context's `map_profiles()` write terrio LZW
GeoTIFFs directly without
transferring raster arrays through Python. The default remains `"rasterio"`.
Native delivery requires `native_geotiff_outputs`, preserves float32 pixels,
NaN nodata and the requested CRS/grid, and uses one compression worker.
It currently excludes templates, floodplain polygonization and velocity.
The same cache and writer controls are available on `RasFim.map_catalog()`;
native catalog delivery currently requires sloping jobs.

Use opt-in row batches for plain sloping:

```python
manifest = RasFim.map_sloping_profiles(
    plan_hdf, terrain_tif, "row_maps",
    profiles={"Max": "Max"}, product_writer="native", row_stream_rows=256,
)
```

The prepared context's `map_profiles()` accepts the same control. Zero keeps
the existing full-array path; integers from 1 through 4096 require the engine's
`native_row_streaming` capability. Requests with cell-face sloping, velocity,
storage areas or a Max reduction are refused. The engine writes raster row
batches within the requested Rust worker pool; full ownership and terrain
arrays remain resident. Commander still uses conservative full-window memory
admission. This option does not establish lower total memory requirements or
a speedup for a model.

See the [prepared-context evidence](development/fim-mapping-performance.md#prepared-model-contexts-across-reach-requests)
for reuse behavior and numerical comparison scope.

<a id="bounded-timestep-concurrency-engine-06"></a>

## Bounded timestep concurrency

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
depend on the workload. Sequential execution remains the default;
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

**CRSs without an EPSG code.** <a id="crss-without-an-epsg-code"></a> Engines that
advertise `crs_any` on a method record (Fast-Map 0.20+: `effective_terrain`,
`sloping`, `horizontal`, and `native_final_format` of the 1D methods) accept a
terrain and results CRS that PROJ identifies by no EPSG code, such as
`ESRI:102630`. The request then carries the CRS as `crs_geokeys`, the GeoKey
tags of a GeoTIFF in that CRS. The engine writes them verbatim into its
GeoTIFFs, so GDAL reads the output CRS as the source's (US survey feet and
datum included):

- **Mapping** (`map_sloping_profiles`, `prepare_sloping_model`, horizontal):
  the terrain's own GeoKey tags, with `crs_identity` `{"kind": "geokeys"}`.
  The engine checks that they are the terrain's. rasterio/PROJ decide whether
  the CRS has an EPSG code; the engine's own identification is never used
  instead (it can name a code GDAL does not). The results CRS must still
  equal the terrain CRS.
- **`build_effective_terrain`**: a source TIFF with tags is handled as above.
  RAS Mapper writes terrain sources in such a CRS with **no CRS tags at all**.
  For those, the CRS is the terrain HDF's `Projection`. GDAL encodes it in a
  one-pixel GeoTIFF, which must read back as the same CRS, and the engine
  checks that every source carries no CRS (`{"kind": "untagged"}`). For the
  Helena terrain (ESRI:102630) these tags are byte-identical to the ones in
  RAS Mapper's own export. The receipt's `crs` records the basis
  (`terrain_hdf_projection` or `source_tiff_geokeys`).
- **1D `final_format`**: GDAL's tags for the model CRS, checked the same way.

- **Boundaries** (legacy and native): the request carries GDAL's WKT of the
  terrain CRS (`crs_wkt`). The engine writes it verbatim as the GeoJSON's
  legacy `crs` member, which geopandas/GDAL read back exactly
  (`is_exact_same`). Native boundaries also accept RAS Mapper sources that
  carry no CRS: the terrain HDF `Projection` must equal the model CRS, and
  the sources are sent as `untagged`. Boundary staging stages that
  `Projection` as `crs_wkt` and resolves the AOI in it. Empty `(0, 0)` stitch
  TIN arrays (single-source terrains) are staged as no stitch TIN.
- **Untagged sources on the mapping routes**: sloping, prepared sloping and
  horizontal mapping also accept a source TIFF with no CRS tags. Its CRS is
  the `Projection` of the one sibling `HEC Terrain` HDF whose `Terrain/*`
  `File` names it; none or more than one such HDF leaves the source without
  a CRS (refused as before). The Python horizontal path still needs a tagged
  terrain.
- **Step05 `map_profiles`**: a terrain without an EPSG code is sent by its
  GeoKeys. An `output_crs` without one is sent as `nudge.dst_wkt`, and the
  products are labelled with `output_crs` by rasterio.
- **Whole-simulation products and coupled mapping**: the horizontal, 2D and
  XS requests carry `crs_geokeys`. Coupled mapping also needs `crs_any` on
  every component method.

Each path needs its method's `crs_any`; otherwise the earlier EPSG refusal
applies. EPSG terrains produce the same requests as before, and the capability
is asked of the engine only for a CRS without an EPSG code.

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
directly, through a prepared model and with `terrain_hdf`. This is
candidate-to-candidate CRS-binding equivalence, not a comparison to the raw
native stored-map grid.

Retained comparisons against HEC-RAS 7.0.1 stored maps (plain sloping, Max):

| Model | Terrain | Valid pixels | Depth/WSE mask and bit differences |
|---|---|---|---|
| BaldEagleCrkMulti2D bridges p05 | `dtm_20ft` (priority 1 of 2) | 973,902 | 0 / 0 |
| Davis p02 | canonical copy of the single source | 22,041 | 0 / 0 |

The Davis row retains the canonical-terrain comparison result; its reference
framing policy is not established by this table. It is not a raw original-source
native-grid qualification. Fresh raw 7.0.1 output uses a different derived
pixel spacing and fails strict framing before numerical comparison. The
stored-tile-grid `/1` mixed-only option does not admit the Davis layout or
provide an ordinary 2D workaround.

On bridges p05 the mapping itself takes about as long on the source TIFF as on
an export (7.3 s against 4.9 to 6.8 s end to end, six threads); the saving is
the export, which took 242.6 s through `RasTerrain.export_rasmapper_terrain`.
Bridges whole-simulation and horizontal requests are refused on the source
TIFF because 28 mapped 2D pixels lie outside its footprint.

## Build the effective terrain, with modifications

`RasFim.build_effective_terrain` writes the grid that
`RasTerrain.export_rasmapper_terrain(downsample_factor=1)` produces, in Rust
and without HEC-RAS. For a terrain with `/Modifications` it needs an engine
that advertises `rasmapper-effective-terrain/2` with a `modifications` record;
an engine that advertises only `/1` refuses every modified terrain.

```python
receipt = RasFim.build_effective_terrain(
    "Terrain/Terrain.hdf", "effective.tif",
    rasmap_path="Project.rasmap", hecras_version="6.6",
)
receipt["method_id"], receipt["hecras_version"], receipt["modification_layers"]
```

- Every HDF layer RAS Mapper applies is staged: ground lines (`Type=Levee`,
  any elevation type including `Add`, named systems, control points, NaN
  templates), polygons (constant, or boundary elevations from perimeter
  control points or a stored profile) and ellipses (any rotation).
- `hecras_version` names the HEC-RAS release whose export to reproduce. Each
  qualified release maps to an engine rule: 7.0, 7.0.1 and 7.0.2 to `7.0.1`;
  6.6 to `6.6`; the 6.7 betas to `6.7` with an engine that advertises it in
  `effective_terrain.hecras_versions`, else to `6.6` (Fast-Map 0.18.0). The
  receipt's `hecras_version` is the rule. Any other release (6.5 and earlier,
  or later than 7.0.2) raises `FimUnsupportedError` with `reason`
  `unqualified_hecras_version` before the engine runs: those releases'
  exports match no rule (per-release qualification, 2026-11-12). Without the
  argument, the version comes from `ras_object`, else from the newest
  `Program Version` of the project's plan and geometry files; when neither
  names a version, the 7.0.1 rule is used.
- With `rasmap_path`, RAS Mapper applies the HDF modifications only when the
  terrain layer has an `ElevationModificationGroup` named exactly
  `Modifications`; without one, or with the group under another name (for
  example `Hydroconnectors`), the terrain is treated as unmodified. The
  receipt's `rasmap_warnings` records why (`modification_group_misnamed` or
  `modification_group_missing`); rename the group to `Modifications` to apply
  the layers.
- A source CRS without an EPSG code, such as `ESRI:102630` (NAD83 / Alabama
  West, US survey feet), needs an engine whose `effective_terrain` record
  advertises `crs_any` (Fast-Map 0.20+). See
  [CRSs without an EPSG code](#crss-without-an-epsg-code). With older engines
  it raises `FimUnsupportedError`, because their requests carry the CRS as an
  EPSG code and they label the output from it alone; use the RAS Mapper
  export there. `terrain_crs_fnv1a64` only covers a CRS that rasterio
  identifies by EPSG but the engine does not; it cannot replace the code.
- Forms the engine does not reproduce raise `FimUnsupportedError`: boundary
  elevations sampled from the terrain, shape-Z polygons, polygons with more
  than one ring, named ground lines with control points or a NaN template,
  named ground lines under 6.6 or 6.7, and other RAS layer types. A polygon
  takes its boundary elevations from a control point only when the point lies
  outside the ring within Elev Pt Tolerance; points inside the ring are
  interior mass points, so a boundary polygon whose control points all lie
  inside needs a stored profile (and is refused under 6.6). Use the RAS Mapper
  export for those terrains.
- A polygon feature with more than one ring (a hole in either winding, or
  separate or overlapping parts) is refused while the layers are read, before
  the engine runs. RAS Mapper joins and triangulates such rings in a way that
  cannot be reproduced as a rule. The error's `reason` is
  `multi_ring_polygon`, and the message carries `[reason: multi_ring_polygon]`,
  so callers can route the terrain to the RAS Mapper export without calling
  the engine. Single-ring polygons are unaffected.

<a id="read-the-modification-layers"></a>

### Read the modification layers

`RasFim.read_terrain_modifications` returns the `modification_layers` that
`build_effective_terrain` would send to the engine, without running it. Use it
to route a modified terrain before any terrain work: `status == "staged"` means
every layer is a form the reader stages, `"refused"` means the terrain needs the
RAS Mapper export, and `refusal` says why. `status` describes the layers the HDF
stores, not whether RAS Mapper applies them: check
`top_priority_terrain_source()["modified"]` before treating the layers as
applied, or pass `rasmap_path` and read `warnings`. RAS Mapper applies nothing
when no group is named `Modifications` (`modification_group_missing`, or only
misnamed groups); a misnamed group beside a correct one is only ignored.

```python
record = RasFim.read_terrain_modifications(
    "Terrain/Terrain.hdf", rasmap_path="Project.rasmap", hecras_version="6.6",
)
record["status"], record["refusal"]          # "staged" | "none" | "refused"
record["hecras_version"], record["length_units"]
[(layer["kind"], layer["name"], layer["priority"]) for layer in record["layers"]]
```

The record (`ras-commander-terrain-modifications/1`) carries `terrain_hdf`,
`method_id` (`rasmapper-effective-terrain/2`), `status`, `refusal`,
`refusal_reason` (the `reason` code of the reader's `FimUnsupportedError`, for
example `multi_ring_polygon` for a polygon with more than one ring, or `None`),
`hecras_version` and `length_units` with their `*_basis` (`"default"` when no
project file states the value and the 7.0.1 rules or feet are assumed),
`warnings` and `layers`. Layers
are `ground_line`, `polygon` or `ellipse` records in the engine request form;
the field list, units and refusal reasons are in the
[`RasFim` reference](api/core.md#mapping). The HEC-RAS version and unit system
are resolved as `build_effective_terrain` resolves them, from the HDF's own
project folder after links are resolved; an explicit `length_units` applies to
the reader only. Project files that state different units refuse a terrain
with layers to stage and leave an unmodified one `"none"`. With `rasmap_path`,
`warnings` lists registration problems: a misnamed or missing `Modifications`
group (RAS Mapper then applies nothing), layers the group lists that the HDF
does not store (`rasmap_layer_not_in_hdf`; `build_effective_terrain` refuses
the terrain) and a rasmap that does not register the terrain. `strict=True` raises
`FimUnsupportedError` instead of returning a refusal. A staged terrain can
still be refused by an older engine; compare the layers with the engine's
`modifications` capability record. The reader does not apply the rasmap
`ElevationModificationGroup` gate; `top_priority_terrain_source()["modified"]`
reports it.

## Sloping velocity

`velocity=True` adds `velocity_tif` (`12_<profile>_velocity.tif`) to each
manifest row, rendered by the engine's `rasmapper-sloping-velocity/0` method.
Max uses `Maximum Face Velocity` with the Max WSE; a timestep index uses
`Face Velocity` at that output time. Face normals carry face polyline lengths.
RAS Mapper's velocity values do not depend on the render mode; it clips them
with the active mode's depth. `velocity_depth="rendered"` (default) clips with
this request's depth (`sloping`, or `slopingPretty` on an engine that
advertises it in `velocity_render_modes`). `velocity_depth="horizontal"`
clips with the horizontal cell-constant depth, reproducing RAS Mapper's
horizontal-mode velocity; the WSE/depth products stay sloping. HDF profiles
only; `wsel_profiles`, `template_raster` and storage-area plans are refused.

**slopingPretty options.** `reduce_shallow_to_horizontal` and
`use_depth_weighted_faces` are accepted with velocity, per-time derived
products and `map_derived_max` when the engine's sloping record advertises
`velocity_with_faces` (`rasmapper-with-faces-velocity-derived/1`) and lists the
option in `velocity_with_faces_options`; older engines refuse them. RAS Mapper
clips every velocity-based product with the depth rendered with the *same*
options, so the options change the mask, never the velocity values. Pass the
options the project's RAS Mapper uses: `RasProcess.store_maps(render_mode=
"slopingPretty")` turns shallow reduction **on**; use
`"slopingPretty:false:false"` for the plain mode.

`derived_products=("depth_x_velocity", "depth_x_velocity_squared", "froude")`
adds `<product>_tif` (`13_<profile>_<product>.tif`) from the same clipping
depth and velocity, in RAS Mapper's operation order (Froude uses the plan's
float32 gravity, 32.174 or 9.80665). For Max use `map_derived_max`:

```python
products = RasFim.map_derived_max(
    "model.p05.hdf", "terrain.tif", "max_derived",
    render_mode="sloping",  # or velocity_depth="horizontal"
)
products[["product", "tif", "valid_pixels"]]
```

RAS Mapper's Max D x V, D x V^2 and Froude are the per-output-time products'
pixelwise maximum (the valid area is the union over times), not Max depth
times Max velocity. The engine reduces every stored output time
(`reduce_max/1`) without writing per-time rasters.

| Native 7.0.1 reference | Product | Valid pixels | Bit / mask differences |
|---|---|---|---|
| bridges p05 Max, sloping | velocity | 973,902 | 0 / 0 |
| bridges p05 Max, horizontal clip | velocity | 973,532 | 0 / 0 |
| bridges p05 Max, slopingPretty plain / shallow reduction / depth-weighted / both | WSE, Depth, velocity | 974,095 / 974,142 / 974,216 / 974,256 | 0 / 0 |
| bridges p05 Max over 433 times, slopingPretty (same four) | D x V, D x V^2, Froude | 974,110 / 974,191 / 974,231 / 974,291 | 0 / 0 |
| Davis p02 Max, slopingPretty (same four) | WSE, Depth, velocity | 21,402 / 21,591 / 20,703 / 21,114 | 0 / 0 |
| Davis p02 Max over 217 times, slopingPretty (same four) | D x V, D x V^2, Froude | 21,315 / 21,862 / 20,880 / 21,287 | 0 / 0 |
| bridges p05 03JAN1999 00:00, sloping | velocity, D x V, D x V^2, Froude | 402,616 | 0 / 0 |
| bridges p05 03JAN1999 00:00, horizontal | velocity, D x V, D x V^2, Froude | 402,500 | 0 / 0 |
| bridges p05 Max over 433 times, sloping | D x V, D x V^2, Froude | 973,956 | 0 / 0 |
| bridges p05 Max over 433 times, horizontal | D x V, D x V^2, Froude | 973,531 | 0 / 0 |
| Davis p02 (Max, 11JAN2000 06:00, Max over 217 times) | all | 8,586-20,560 | at most 5 pixels within 2 ulp / 0 |

The earlier bridges slopingPretty row (75 / 28 mask pixels) compared a plain
slopingPretty run with a reference made with shallow reduction on (the
`store_maps` default above). With matching options the slopingPretty rows are
identical; they used Fast-Map 0.14.0, the Terrain50 1x export (bridges) and the
canonical Davis terrain copy.

The Davis row records the stated prepared comparison scope and residuals; it
does not establish exact raw-native-grid velocity or derived products. Fresh
original-source 7.0.1 checks stop at framing before pixels. Velocity and derived
products are outside the stored-tile-grid `/1` contract, and no compatible
ordinary 2D grid extension is exposed.

Velocity comparisons require matching render modes: horizontal-mode velocity
must not be compared with sloping-mode depth.
Shear stress uses its own method; see [Max shear stress](#max-shear-stress).

## Max shear stress

`shear_stress=True` adds `shear_stress_tif` (`15_<profile>_shear_stress.tif`,
float32, NaN nodata, lb/ft2 or N/m2) for the Max profile, rendered by the
engine's `rasmapper-face-shear-max/1` method
(`RasFim.supports_shear_stress()`):

```python
frame = RasFim.map_sloping_profiles(
    "model.p05.hdf", "terrain.tif", "shear",
    shear_stress=True,  # profiles default to {"Max": "Max"}
    shear_depth="rendered",  # or "horizontal" for RAS Mapper's horizontal mode
)
frame.loc[0, "shear_stress_tif"]
```

RAS Mapper's Shear Stress (Max) is a face quantity, not a pixel maximum over
time. At every stored output time each face's shear is
`k*|V|*V*n^2/R^(1/3)` (`k` = 28.258362 US Customary, 9810 SI; the Manning
friction-slope form of `gamma*R*S_f`), with `V` the mean of the face's two
least-squares facepoint velocities, `R` from the `Faces Area Elevation` table
at the sloping face water surface, and `n` the face's first Manning's n. Each
face keeps its largest magnitude (RAS Mapper's PostProcessing
`Maximum Shear`); facepoints average their faces and the plain sloping weights
paint them. The values do not depend on the render mode; `shear_depth` sets
the mask (the rendered sloping Max depth, or the horizontal cell-constant
Max depth). The engine's [shear-stress notes](https://github.com/gpt-cmdr/ras-commander-fast-map/blob/main/docs/shear-stress.md)
give the complete rule.

The call stages every stored output time's cell `Water Surface` and
`Face Velocity`, plus the face tables. Max only, plain `sloping`, HDF
profiles; `wsel_profiles`, prepared models, storage-area plans, native
products, row streaming and `template_raster` are refused.
`attrs["shear_stress"]` records the rule and the engine's face pass.

| Native 7.0.1 reference | Clipping depth | Valid pixels | Bit / mask differences |
|---|---|---|---|
| bridges p05 Max (433 times) | sloping | 973,902 | 0 / 0 |
| bridges p05 Max | horizontal | 973,532 | 0 / 0 |
| Davis p02 Max (217 times, 2 meshes) | sloping | 22,041 | 0 / 0 |
| Davis p02 Max | horizontal | 20,560 | 0 / 0 |

Per-face Max equals RAS Mapper's PostProcessing `Maximum Shear` bit for bit on
both models (54,636 and 5,590 faces). Bridges also matches on the priority-1
source TIFF (`terrain_hdf`). Measured on a shared Windows host: bridges 25 s /
1.0 GB peak against RAS Mapper's 94-191 s / 0.9 GB for the same map; Davis
2.5 s / 0.18 GB against 45-74 s / 0.35 GB.

## Whole-simulation products

`terrain_crs_fnv1a64` accepts an explicitly verified engine WKT fingerprint when
the engine cannot identify the source terrain EPSG code. Model and terrain must
still share a CRS and resolve to an EPSG code through Rasterio. It never relabels
coordinates or overrides an identified engine EPSG code. The manifest records
the requested fingerprint and accepted terrain identity.

`map_whole_simulation` produces arrival time, percent time inundated and
duration from every stored output time, through the engine's
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
- Plans with 1D elements are refused. Plans with storage areas are refused
  unless `storage_areas=True`; a storage-area pixel is then wet when its depth
  is greater than `threshold` (a level pool has no cell gate).
- `duration` runs to RAS Mapper's recession time on an engine advertising
  `duration_rule` `rasmapper-backward-window-recession/1` (qualified below);
  a different recession rule needs `allow_unqualified=True`.
  Irregular output intervals are refused without `allow_unqualified`.
  `duration` together with `storage_areas=True` is refused.

| Model (native 7.0.1, 0.5 ft) | Output times | Valid pixels | Arrival / percent / duration differences |
|---|---|---|---|
| Davis p02 | 217 | 4,879 | 0 / 0 / 0 |
| BaldEagleCrkMulti2D bridges p05 | 433 | 959,043 | 0 / 0 / 0 |

These retained comparisons reported equal horizontal and sloping stored-map
products on the stated prepared terrains. The table does not establish the
Davis reference's raw framing policy. Fresh original-source raw 7.0.1 Davis
arrival, duration and percent-inundated references remain uncompared after a
grid-framing refusal. The original-source Bald Eagle temporal route separately
refuses 28 wet pixels requiring lower-priority sources/stitches. The existing
temporal API targets 2D models; the canonical 1D/mixed APIs provide Depth/WSE,
not temporal products.

## Storage-area level pools

RAS Mapper draws a standalone storage area as a horizontal pool. With
`storage_areas=True` (`map_sloping_profiles`, `map_whole_simulation`) or
`storage_areas={profile: "Max" | index}` (`map_horizontal_profiles`, with the
source plan HDF), the engine's `storage-area-level-pool/1` method does the same:
every pixel whose centre is inside a storage-area polygon
(`Geometry/Storage Areas`) gets that area's WSE (`Maximum Water Surface` for
Max, the stored `Water Surface` for a timestep), visible where float32
`wse >= terrain + 0.001`, depth `wse - terrain`, in every render mode. The
output window grows to cover the storage areas.

```python
if RasFim.supports_storage_areas():
    manifest = RasFim.map_sloping_profiles(
        "BaldEagleDamBrk.p07.hdf", "terrain.tif", "out", storage_areas=True,
    )
    manifest.attrs["storage_areas"]  # names, method and mapped pixel count
```

Refused (`FimUnsupportedError`) rather than guessed: storage areas overlapping
2D cells or each other, velocity, caller-supplied `wsel_profiles`, prepared
models and, with `terrain_hdf`, any storage-area pixel outside the priority-1
source footprint (BaldEagleCrkMulti2D has 28; map on an export instead).

| Native 7.0.1 comparison | Products | Storage-area pixels | Differences |
|---|---|---|---|
| BaldEagleCrkMulti2D p07 | Max Depth/WSE horizontal, sloping, slopingPretty (with/without shallow reduction); 02JAN1999 13:00 horizontal and sloping | 466,912 (Max) | 0 mask, 0 bits |
| BaldEagleCrkMulti2D p04 (2D levee structures) | Max Depth/WSE in the same four modes; 13:00 sloping | 461,639 (Max) | 0 mask, 0 bits |
| p07 and p04 | Arrival time and percent inundated at 0.5 ft | 464,106 / 458,764 | 0 mask, 0 bits |

Duration differences (8 and 46 pixels, one output interval) are all 2D pixels.
Both models have one storage area connected to the 2D area; multiple storage
areas and storage-area-to-storage-area connections are not covered.

## Horizontal cell mapping

Horizontal mapping requires the advertised `horizontal-cell-constant/2` method.

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
backend is the default. The explicit
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
raster allocation; planned admission is not a hard process memory limit.
Missing engine capabilities raise explicitly rather than falling back.

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

Both comparison APIs default to zero added cutoff;
`compare_with_rasmapper` also defaults to no reference-delivery rewrite.
For zero-cutoff raw comparison, `RasFim.compare_rasters(..., min_depth=0)`
preserves every valid pixel, including zero depths, and compares float32 bits.
Positive cutoffs remain optional independent filters of candidate and reference.
A missing zero-depth pixel is a mask difference; matching common values alone
does not establish raster parity. The standalone
`scripts/benchmarks/fim_horizontal_parity.py` runner checks complete physical-2D
masks and float32 values against retained native references, requiring zero
extra, missing, different and outside-footprint pixels for both products.

<a id="mapping-time-comparisons"></a>

<a id="horizontal-and-cell-corner-sloping"></a>

<a id="depth-weighted-cell-faces"></a>

<a id="reproduce-and-inspect-comparisons"></a>

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
reprojection or resampling. The retained Davis HARN comparison terrain needs
this preparation; see the qualification record for the tested reader build.
Terrain preparation is outside mapping timing.

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
the native race. See the [diagnosis and controls](development/fim-mapping-performance.md)
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

Notebook 602 demonstrates cutoffs of 0.0, 0.5, 1.0 and 2.0 ft on Davis.
The horizontal method's completed full-model native comparisons match complete
zero-added-cutoff masks and Float32 values; see the performance page for the
tested cases and artifacts. The half-foot filter is optional and is not the
comparison default.

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
Windows and Linux wheels are qualified for the method/model scopes listed in
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

JSON manifest transforms retain binary64 round-trip precision. Missing and
nonfinite metadata values are written as JSON null.

Sloping diagnostics separate command completion from process exit.
`engine_returncode` is the observed natural exit code, or null when none was
observed. A successful command on a live persistent process records
`engine_command_status="complete"`. `engine_cleanup_termination_requested` and
`engine_cleanup_returncode` describe supervisory cleanup separately.
Coupled manifest `reports` include entries with `kind="engine_execution"`,
component and profile identities, observed return code, bounded stderr and
execution status. Final profile status also incorporates product and report
validation.

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

The [FIM engine comparison](development/fim-mapping-performance.md)
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
`native_geotiff_outputs`. Check
`RasFim.get_engine_info()["method"]["sloping"]` for capability flags.
Use `product_writer="rasterio"`
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

See [catalog measurements and reproduction](development/fim-mapping-performance.md#reach-timestep-catalog-throughput).

<a id="complete-source-reference"></a>

## Class reference

Method signatures and return types are documented with the [core classes](api/core.md#mapping).

<a id="deterministic-vector-boundaries"></a>

## Deterministic inundation boundaries

`RasFim.map_inundation_boundaries()` generates vector zero-depth contours in
Rust. It supports horizontal and plain cell-corner sloping surfaces, multiple
stored timesteps, and bbox or polygon constraints. It adds no depth cutoff.

```python
boundaries = RasFim.map_inundation_boundaries(
    "model.p02.hdf", "Terrain/Original.tif", "boundary_catalog",
    terrain_hdf="Terrain/Terrain.hdf",
    profiles={"maximum": "Max", "t108": 108},
    interpolation="sloping",  # or "horizontal"
    polygon="reach.gpkg", threads=4, max_inflight_profiles=2,
    max_working_mib=2048,
)
print(boundaries[["profile", "polygons", "holes", "boundary_geojson"]])
print(boundaries.attrs["performance"])
```

The function returns one manifest row per profile, including empty products.
GeoJSON stores the projected CRS explicitly. `boundary_manifest.json` records
the method, source identities, terrain metadata, concurrency and timings.

Use the original, unmodified single-source float32 TIFF with 256-pixel tiles and its
associated terrain HDF. The HDF supplies sample-coverage masks, perimeter
values and complete stitch TIN connectivity. A flattened replacement TIFF is
insufficient evidence for those arrays. Multi-source terrain HDFs, 1D model
elements, and cell-face/shallow/depth-weighted boundary options are refused.
An AOI outside the source sample grid is refused. AOIs preserve full source
tiles plus a sample halo; only final contour polygons are clipped.

Nonempty or linked `/Modifications` objects in the terrain HDF are refused
before numeric reads. The API cannot infer externally registered modifications
from a TIFF/HDF pair: supply a terrain with no external modifications. An empty
modification group is permitted and recorded. A replacement effective TIFF also
needs matching regenerated terrain metadata and separate qualification.

For deterministic boundary mapping of a model with multiple terrain sources,
first preprocess a dedicated single mapping terrain. Preserve source priority,
CRS, grid, nodata and effective elevations, then generate its matching terrain
HDF from that single source.
Keep the project terrain unchanged and verify the prepared surface against the
original effective terrain. Record preparation provenance and reuse this
TIFF/HDF pair across all reach and timestep requests. This is a one-time
preparation workflow; a flattened TIFF paired with the old multi-source HDF
does not satisfy the input contract. Newly prepared layouts require qualification
before numerical equivalence is claimed.

The default `method="deterministic"` selects
`deterministic-zero-depth-contours/1`. It uses a stable
all-subject NonZero union and a 0.001 projected-coordinate-unit lattice,
retaining canonical exterior and interior rings. Native RASMapper boundary
exports can differ in hole topology and coordinates, including between
identical native Max calls. Products record `native_vector_parity=False`;
this method does not claim native polygon equality. Existing Depth/WSE raster
methods and their qualification are unchanged.

The accepted vector behavior is deterministic Rust contour merging with
disclosed native differences. The observed native variability occurred in
Commander-driven RASMapper 7.0.1 exports. The order-sensitive merge belongs to
the native implementation; Commander performs no native polygon union.
Repeated standalone GUI exports have not been qualified.

The intrinsic cell-wet gate is float32 `WSE > minimum_elevation + 0.001`.
Signed sample depths remain available to find zero crossings; raster plot
visibility is not applied to contour samples. Valid negative depths, including
-9999, are distinct from missing samples. Sample activation from terrain masks
is distinct from a polygon clipping mask.

This path requires a Fast-Map engine advertising the boundary capability
(`boundary.method_id` `deterministic-zero-depth-contours/1`). The terrain tile
`Mask` is an 8-bit HDF5
bitfield. When the installed fast-HDF reader does not advertise bitfield
support, its raw bytes are staged through h5py as
uint8, exactly as the terrain-scope staging does; every other array uses the
required native reader. The library never builds, downloads or installs an
engine during mapping, and never substitutes h5py arithmetic. Geometry, terrain and ownership are shared across profiles
inside a call. One Rayon pool bounds tile and timestep work. Budgets are planned
allocation admission, not hard process RSS limits.

Legacy custom GeoTIFF keys can be described differently by the native reader.
The default CRS comparison remains strict. After independently verifying the
original TIFF, model and terrain-HDF CRS, pass `terrain_crs_fnv1a64` from the
matching engine's `terrain-info` record to pin that reader identity explicitly.
The pin and effective identity are retained in the manifest. It does not
reproject coordinates or modify the TIFF.

### Compare native polygons

To compare the native serial contour contract, set `method="native_serial"`
and `allow_unqualified=True` on the same boundary APIs. This selects
`rasmapper-serial-zero-depth-contours/1`; inspect the returned qualification
and source receipts before treating a comparison as a numerical pass.
The method admits stored XS and storage surfaces in addition to physical 2D
cells, with physical coverage resolved before dry or missing-water filtering.
It retains original terrain sources in native order, their own tile frames,
all source masks and perimeters, and one complete global stitch TIN.
Terrain modifications, face options, steady encroachment and blocked-obstruction
polygons are refused.

For this method, `terrain_path` identifies the first original source in the
effective native terrain order. Complete stored Priority values are sorted
ascending, preserving native enumeration for ties; incomplete Priority metadata
retains native enumeration. Creation-indexed layouts with missing or tied
priorities are refused. This order can differ from a VRT mosaic's top-priority
source. If a legacy terrain HDF has no stored projection, admission requires a matching
sibling VRT and agreement between its CRS, the model and every original TIFF.
The VRT supplies CRS evidence; it does not replace the original terrain samples.
A bound CRS retains its projected source CRS and binding provenance. No datum,
coordinate or unit transformation is applied.

Terrain masks and perimeters are read by active tile row. Their backing files
still count toward `max_prepared_mib`; this disk allowance is distinct from
working RAM. Complete hydraulic geometry and the global stitch TIN remain
available throughout contouring. Empty tile units retain their positions in
the merge sequence. Ambiguous physical 2D ownership at fuzzy polygon edges is
refused rather than assigned an arbitrary native claim.

For a generated native reference, pass
`native_performance=StoreMapPerformanceOptions(native_polygon_serial=True)`
with a single native mapping worker. Import `StoreMapPerformanceOptions` from
`ras_commander`. The helper verifies the actual native serial polygon-loop
flag; CPU affinity alone does not guarantee serial contour merging. Stored
steady profile names select their actual profile indices. Keep the native
runtime identity and interpolation options with retained references.
Retain the rendering-helper and merge-host identities as well: the .NET host
also determines native tie ordering at equal-height intersections.
Generated native-serial comparisons record the requested runtime label and
helper/library content identities before and after export. A changed identity
refuses the comparison; the project rasmap is restored on failure.

On Windows, an optional `native_job_memory_limit_mb` in these performance
options caps the combined private committed memory of the native helper and
its merge descendants. It requires `max_workers=1`, serial polygons and
`memory_policy="enforce"`, with a verified 6.6 or 7.0.1 runtime. File-backed
resident pages are separate from private commit. This native execution control
does not change Rust mapping admission.

Native-serial AOIs preserve every source tile and the complete hydraulic
geometry. Only the final full vector is intersected with the requested polygon,
using an unrounded GEOS intersection for both candidate and reference. The
manifest records `aoi_clipping_method="unrounded-geos-intersection/1"`.
There is no geometry repair, coordinate snapping, reprojection or raster-mask
polygonization in this comparison.

Native-serial comparisons admit both complete input geometries together under
`max_working_mib`, including parsing and comparison scratch. GeoJSON coordinates
and XY Polygon shapefile headers are counted before geometry allocation. The
comparison manifest records the plan. Increasing the budget can admit larger
boundaries; this planned allowance is not a hard process-memory cap. GeoPackage
references retain the bounded reader's vertex limit.

Normal mapping and comparison require valid polygon topology. To investigate
a completed boundary that fails this check, use `preserve_raw_geometry=True`
with `method="native_serial"`, `allow_unqualified=True` and no AOI options.
The diagnostic preserves unchanged vector artifacts and records their source
identities, CRS, counts and validity reason. It raises `FimGeometryError`,
whose `diagnostic_manifest`, `artifacts` and `validity_reason` identify the
retained evidence; it does not return a successful product or comparison row.
An engine refusal before a complete vector exists cannot supply a raw vector.

Raw comparison distinguishes ordered Float64 XY equality from exact ring-bit
equality that ignores ring starts, orientation and part order. It preserves
collinear points, internal repeated vertices and signed zeros. Invalid inputs
receive no topology equality, area differences, IoU or Hausdorff metrics.
Receipts record profile coverage and keep qualification and native-vector parity
false, even when raw coordinates match. Neither repair nor rounding is applied.

The Windows x64 native-serial checks use plain sloping, zero-depth contours,
original terrain layouts and the verified native serial polygon loop. For valid
fixtures, complete geometry and unrounded Float64 ring bits agree after normalizing only ring
start, direction and part order; collinear and repeated vertices remain.

| Fixture and selected profiles | Native runtime | Checked extent and result |
|---|---|---|
| Baxter; Big, Bigger and Biggest steady profiles | 6.6 and 7.0.1 | Full extent, full-source/polygon-with-hole/empty AOIs, workers 1/4: exact valid geometry and coordinates |
| Davis; Max and saved index 108 | 7.0.1 | Same full/AOI and worker checks: exact; native 6.6 reference generation failed |
| Bald Eagle; Max and saved index 108, original two terrain sources and storage | 6.6 and 7.0.1 | Full extent, workers 1/4: exact valid geometry and coordinates |
| Reese; mixed-model Max | 6.6 and 7.0.1 | Full extent, workers 3: exact valid geometry and all 950,441 closed-ring vertices |
| White Oak p19 Max; cross-sections and storage | 6.6 and 7.0.1 | Full extent, workers 2: all 5,136,224 vertices match as raw ring bits; the shared self-intersection prevents valid-vector delivery |

These checks use one in-flight profile for Reese/White Oak and at most two for
the other fixtures, 2 GiB prepared storage, and working allowances of 3 GiB
for Reese, 12 GiB for White Oak and 4 GiB otherwise. The complete-vector and
AOI checks do not qualify other profiles, modified terrain, another platform
or native execution modes. Spring and Whisky have no completed native
full-boundary reference within the bounded runs. Qualification defaults remain
closed; raw equality does not make invalid topology suitable for GIS delivery.

```python
from ras_commander import StoreMapPerformanceOptions

comparison = RasFim.compare_inundation_boundaries(
    "model.p02.hdf", "Terrain/Original.tif", "boundary_comparison",
    terrain_hdf="Terrain/Terrain.hdf", plan_number="02", ras_object=ras,
    profiles={"maximum": "Max", "t108": 108},
    interpolation="sloping", threads=4,
    method="native_serial", allow_unqualified=True,
    native_performance=StoreMapPerformanceOptions(native_polygon_serial=True),
)
print(comparison[["profile", "extra_area", "missing_area", "geometry_equal"]])
print(comparison.attrs["performance"])
```

Use an initialized copy of the computed project for native generation.
`RasProcess.store_maps()` generates the references and restores the original
rasmap bytes; native execution can create other project caches. Alternatively,
pass `native_boundaries={profile: vector_path}` to compare retained references
without HEC-RAS, including on Linux. References require their stored matching
CRS; no reprojection, geometry repair, reference rounding or depth filtering
is applied.

The comparison reports both directions of area difference, complete topology,
unrounded topological equality, `coordinates_equal` for unrounded vertices,
and a separate quantized-coordinate equality metric. Unrounded vertex comparison
ignores ring orientation, ring starting vertex and part order, while retaining
collinear vertices.
Native generation, shared Rust batch time and comparison scans have separate
clocks. Repeated `candidate_batch_seconds` values identify one shared batch
clock; do not sum them as independent profile times. A speed ratio is withheld
while numerical qualification remains open. Discrete Hausdorff distance is omitted with
an explicit receipt exclusion when the vertex-pair budget exceeds 25 million.
See the [boundary qualification issue](https://github.com/gpt-cmdr/ras-commander-fast-map/issues/4).

## Prepare and map stored 1D surfaces

Use `RasFim.prepare_one_d_model()` to stage native stored interpolation TINs,
normalized strip M, render ranks and per-cross-section levee/end-obstruction
records. `RasFim.map_one_d_profiles()` runs the staged inputs through Rust and
writes Depth/WSE GeoTIFFs and `fim_manifest.json`. Neither operation loads HEC-RAS.
Missing stored geometry must be prepared separately through Commander geometry
APIs on an isolated model copy.

Preparation follows the HDF backend policy (`auto` by default). Compound XS
obstruction tables can use h5py reads under that policy; required-native mode
refuses when the installed HDF engine cannot read their datatype. Preserve the
project's projection and terrain metadata when staging a plan HDF that does
not store its CRS.

```python
prepared = RasFim.prepare_one_d_model(
    plan_hdf, original_source_tif, preparation_folder,
    profiles={"maximum": "Max", "initial": 0, "later": 12},
    allow_unqualified=True, max_working_mib=512,
)
products = prepared.map_profiles(
    output_folder, profiles=["maximum", "later"], bbox=selected_bounds,
    allow_unqualified=True, engine_path=engine,
    threads=4, max_working_mib=512, timeout=120,
)
assert products.attrs["qualified"] is False
```

This diagnostic path uses `one-d-xs-surface-diagnostic/5` and its existing
`fast-map-one-d-diagnostic/3` transport. The default `allow_unqualified=False`
refuses execution. The preparation receipt identifies the version-specific
normalization and endpoint-selection rules. Full-corpus and broader raster
qualification remain gates. Transport availability
does not establish numerical qualification. With engines that advertise
`render_workers`, the XS pass renders source-terrain tile rows on up to
`threads` workers, reduced to fit `max_working_mib`. Admission counts the
engine's per-worker scratch: tile claims, triangle candidates, terrain-TIFF
decode buffers when the engine reads the terrain itself, and `final_format`
writer buffers. When one worker does not fit, mapping is refused before any
engine call. With engines that advertise
`multi_profile`, each engine call covers up to the advertised `multi_profile.max`
selected profiles, so inputs and the prepared surface are read and built once per
call. Neither option changes output bits.
Older engines run one sequential XS request per profile. A separate storage
request uses up to four workers within the requested thread budget; with
`inline_storage`, composition runs in the XS request on its admitted worker
count. Manifests record the
requested and effective counts, `xs_render_workers` and `xs_profiles_per_request`.
`threads_effective` counts only the requests issued: on the inline route it is
the XS worker count, never the four-thread separate storage call.

With engines that advertise `terrain_tiff`, the engine reads the source terrain
GeoTIFF itself and applies only its Float32 nodata value. A terrain with a
per-dataset or alpha mask keeps the staged Rasterio read, which turns masked
pixels into NaN, so the direct read never exposes masked pixels as terrain.

With engines that advertise `inline_storage`, storage level pools and their
composition run inside the batched XS request: physical storage labels are
rasterized once and no separate storage or composition process runs. Products
are bit-identical to the separate calls; manifests record `storage_inline`.

`final_format` has the `map_sloping_profiles()` contract (`nodata`, `block_size`,
`zlevel`, `overviews`, `grid`). With an engine advertising `native_final_format`
on the 1D (or storage-composition) method, the engine applies the AOI pixel
mask, counts finite and flooded Depth pixels and writes each Depth/WSE GeoTIFF
once; Commander verifies the header and file and moves it into place. Valid
pixel bits and the nodata mask equal the Rasterio-written products. Manifest
rows record the delivered grid (`col_off`, `row_off`, `width`, `height` and
`transform` on the terrain), as sloping rows do; `final_format.window_on_grid`
locates the mapped window. A valid value that is infinite or reads as `nodata`
is refused (`FimUnsupportedError`, wrapped in `FimMappingError`); no product is
delivered. The model CRS needs an EPSG code, unless the engine's
`native_final_format` advertises `crs_any` (see
[CRSs without an EPSG code](#crss-without-an-epsg-code)). There is no Rasterio
fallback.

The diagnostic scope includes stored unsteady or explicit steady XS profiles,
including junction ordering, levees, endpoint obstruction blocks and disjoint
storage level pools. Mixed 2D/pipe geometry, blocked polygons, actual
encroachment datasets and degenerate triangles refuse. No triangle is dropped.
Storage polygons take precedence over XS coverage even when their pools are
dry; overlapping pools and storage/2D overlap remain refused. Without
`inline_storage`, Rust renders pools through a separate `fast-map-storage/1`
call, using `storage-area-level-pool/1`, then composes products through a
separate coupled schema `/2` call with zero 2D cells. With `inline_storage`,
the same pool and composition methods run inside the XS request.
These transports require advertised capabilities and retain `qualified=False`.
Final composed products identify the coupled-storage method and request schema,
with separate XS and storage component contracts in the manifest.

This 1D preparation path preserves finite, single-ring self-crossing storage
polygons with nonnegative native signed area and renders their raw rings using
even-odd filling. It does not repair or reorder the coordinates. Receipts record
the geometry policy, validity reason, winding and WKB hashes. Invalid multipart
polygons and negative-area invalid rings remain refused. Other mapping paths
retain strict storage-polygon validation.

Preparation applies native zero-based cross-section stationing before selecting
and evaluating levees and endpoint obstructions. Receipts retain stored and
translated Float32 stations. Finite reversed obstruction records retain their
stored order and endpoints; they are not swapped or removed.

Normalization uses exact upstream/downstream endpoint Z and the first stored
point nearest each M target (0, -1, +1), including first-point tie precedence,
as source-verified for 6.6 and 7.0.1. Selected point indices are receipted.
Named output mappings select unsteady saved indices or `"Max"`. For steady
results, explicitly select a stored profile index or its stored name; there is
no inferred Max aggregation. For example, `profiles={"design": "Biggest"}`.
Ordered selector sequences remain accepted with generated profile names,
preserving duplicate selectors. Prepared reuse selects an ordered
subset of prepared names. Global result
identities must match XS feature order. Units must resolve to US Customary, with
model and terrain in the same projected US survey foot CRS. Different NAD83
realizations require explicit preparation, never a CRS label replacement.

Supply the original single-band Float32, north-up square-pixel terrain with
256-pixel tiles. An AOI windows output while preserving complete XS/TIN geometry,
original grid origin and tile scan history. This path does not consolidate
multi-source terrain or reconstruct source-priority/stitch masks; those layouts
require separate validated terrain preparation and remain unqualified here.

The preparation receipt binds source and payload SHA-256 hashes, global source
grid, units, per-XS station bounds/polyline lengths, ordered obstruction blocks,
selected sides, Float32 clip/WSE bits and normalization offsets. Its binary
`point-m-evidence.f64` contains raw and normalized M for every global TIN point.
Prepared-model reuse checks these hashes before and after mapping. Inputs remain
read-only; destination folders must be new or empty. A prepared instance also
binds the preparation receipt's fingerprint and rejects receipt edits. A batch
publishes its TIFFs only after complete rendering and source/payload/engine
verification. A failed batch removes its products and writes a failed manifest;
`FimMappingError.manifest` contains the failed profile rows.
Use `raise_on_failure=False` to return that failed manifest instead.
Manifests record selected profiles, AOI and mask policy, resource options,
engine identity and source/payload hashes. Canonical 1D polygon delivery uses
`global-terrain-lattice/1`, consistent with horizontal/sloping: complete projected
AOI geometry is normalized against the original full terrain transform, with
lower-y/left pixel-center ties included and upper-y/right ties excluded. Holes,
multiparts and reversed rings retain that rule. Reprojected bboxes use the same
polygon rule; same-CRS bboxes remain unmasked pixel-center windows. Coordinate,
edge/intersection scratch and mask allocations are admitted before mask creation
or terrain reads. The mask is applied once to final composed Depth/WSE, preserving
physical storage ownership and all retained hydraulic values. Manifests retain
original AOI WKB/CRS and projected WKB/CRS identity. This is Commander delivery
geometry, not a new Rust engine capability or broader 1D qualification.

## Prepare and map mixed 1D/2D surfaces

Use `RasFim.prepare_coupled_model()` for a computed unsteady model containing
actual cross-section interpolation surfaces and physical 2D cells. It stages
complete global XS/TIN and mesh dependencies, including ghost cells, and proves
that selected profiles bind the same stored output timestamp axis in every
component. Model and original terrain must use the same projected US survey foot
CRS and US Customary hydraulics. The terrain retains its full grid and 256-pixel
tile history.

```python
prepared = RasFim.prepare_coupled_model(
    plan_hdf, original_source_tif, preparation_folder,
    profiles={"initial": 0, "later": 12},
    allow_unqualified=True, engine_path=engine,
)
products = prepared.map_profiles(
    output_folder, profiles=["later", "initial"], bbox=selected_bounds,
    allow_unqualified=True, engine_path=engine,
    threads=4, max_working_mib=1024,
)
assert products.attrs["qualified"] is False
```

`RasFim.map_coupled_profiles()` provides the source-path convenience route.
Preparation and mapping refuse by default before engine lookup or output writes.
Only plain corner-sloping Depth/WSE is admitted. Mixed steady results, pipes,
blocked polygons, encroachments and degenerate geometry remain unsupported.
Existing 1D-only and strict 2D admission are unchanged.

### Mixed models with storage areas

With `ras-commander-fast-map` 0.18.0 or later, mixed models that contain
storage areas are prepared and mapped through the same calls. Preparation
stages the storage-area polygons and one Float32 water surface per area and
profile (`Maximum Water Surface` for `"Max"`, otherwise the stored output row),
and proves that the storage-area series uses the shared Base Output timestamp
axis. For each profile the mapper runs the XS and 2D components, then the
storage-only transport (`fast-map-storage/1`, `storage-area-level-pool/1`), and
composes all three with coupled schema `/2`
(`one-d-two-d-storage-coverage-first-diagnostic/1`). Physical storage coverage
suppresses the XS surface before visibility, as 2D coverage does, including
where the storage area is dry. The receipt's `storage` record binds the names,
polygons and levels; the manifest identifies the schema `/2` method and the
storage component contract, with `qualified=False`.

Refused with `FimUnsupportedError` before any write:

- a storage area whose interior overlaps a 2D flow area perimeter at a terrain
  pixel centre (the engine rejects physical storage/2D overlap until it is
  qualified; a shared edge is admitted);
- storage areas with `grid_contract="rasmapper-stored-tile-grid/1"`, because
  the stored-grid coupled schema `/3` excludes storage;
- engines older than Fast-Map 0.18.0, or engines that lack the `storage` and
  `coupled_storage_diagnostic` contracts.

Storage support does not change qualification: the route still requires
`allow_unqualified=True`.

The engine must advertise `export_physical_ownership`. The sloping pass exports
UInt32 labels from the same physical polygon burn used by its products, including
dry and terrain-nodata coverage. Coupled schema `/1` composes the existing clipped
XS and plain sloping products; physical 2D coverage suppresses XS before visibility
filtering. No ownership is inferred from water levels. Any polygon delivery mask
is applied only to final composition using `global-terrain-lattice/1`.

Supply a self-contained terrain TIFF with a declared nodata value. Dataset and
alpha masks, external mask files and auxiliary sidecar dependencies are refused
so both components use the same bound terrain validity.

`FimPreparedCoupledModel` binds its immutable preparation receipt, sources,
payloads, engine, profiles and original grid. Reconstructed, edited or incomplete
receipts refuse. Prepared reuse selects an ordered subset of prepared names.
Preparation and mapping require new or empty destinations. Source and payload
hashes are checked around mapping and whole-batch publication; failures roll
back products and retain a failed manifest. `FimMappingError.manifest` and
`raise_on_failure=False` follow the canonical 1D lifecycle. Manifests identify
the coupled method/schema and component contracts, with `qualified=False`.
This API does not promote mixed-model numerical qualification.

Stored `"Max"` summaries are accepted when the XS and complete mesh summaries
are present; the retained mixed-model comparisons cover saved-output profiles.
Manifests record thread counts separately for serial XS/composition and the
2D pool. Source-path convenience runs mark their temporary preparation paths
as ephemeral; use `prepare_coupled_model()` for retained, reusable inputs.
Preparation binds the engine artifact, so changing it requires re-preparation.
Input hashing is repeated around profiles and publication to verify provenance.

For native stored tile sampling, pass
`grid_contract="rasmapper-stored-tile-grid/1"` to mixed preparation or the
source-path mapping call. The prepared model seals that choice and its mapping
method inherits it. The terrain TIFF and original source transform stay intact;
the engine derives logical tile sampling and the delivery transform separately.
Commander independently derives the same layout and compares binary64 values
bit for bit before accepting component reports.
The receipt, reports and manifest retain both transforms and the selected
component contracts. `grid_contract=None` uses source-grid delivery.

The native-grid preparation receipt is
`ras-commander-coupled-preparation/2`. Its `grid` retains the source terrain
transform; `grid_contract` binds source dimensions, original tile size and the
full derived output transform. The manifest and DataFrame attrs include
`grid_contract`, `source_geo_transform`, `output_geo_transform` and
`options.grid_contract`. These geotransforms use GDAL coefficient order
`(x_origin, x_step, x_rotation, y_origin, y_rotation, y_step)`.
Row `transform` uses Affine order `(a, b, c, d, e, f)` for the delivered window;
`col_off` and `row_off` locate that window on the full **derived delivery
lattice**. The original source pixel addresses and terrain bytes remain bound
separately.

The option is exposed by `prepare_coupled_model()` and
`map_coupled_profiles()`. The prepared model inherits its sealed choice;
`prepared.map_profiles()` accepts no grid override. Supplying an override
through `map_coupled_profiles()` with a prepared object raises `ValueError`.
Unknown grid-contract values raise `FimUnsupportedError`.
Standalone `map_one_d_profiles()`, `map_sloping_profiles()`, prepared sloping
models and catalogs do not expose this option.

This opt-in accepts self-contained, north-up, square-pixel, single-source
Float32 terrain with original 256-pixel tiles. It checks every actual source
row and column to require bit-identical logical-tile and full delivery-grid
centers before payload staging. Commander and Rust apply the same fixed
layout limits: positive source dimensions up to 2,147,483,647 and at most
32,768 logical 256-pixel tiles. Layout verification uses constant scratch;
`max_working_mib` governs admitted preparation and rendering allocations.
Unsupported layouts refuse before bulk source hashing and staging.
Bboxes and polygon masks
use the full selected delivery lattice; terrain reads retain original integer
pixel addresses. Physical ownership remains independent of wet/dry filtering.
Storage, pipe geometry, terrain-scope mosaics, velocity and temporal products
are outside this mixed contract. An engine must advertise all three component
contracts; an older or incompatible engine refuses before preparation writes.
This option still requires `allow_unqualified=True` and records
`qualified=False`; it does not establish numerical qualification.
