---
title: Native Rust Mapping Engine
description: Map computed HEC-RAS 2D results with Rust horizontal and sloping interpolation, bounded timestep concurrency, bbox or polygon masks, and RAS Mapper comparisons.
social_image: assets/ras-commander-fast-map_social.png
social_image_alt: "RAS Commander Fast-Map: Native Rust Mapping Engine"
---
# Native Rust Mapping Engine

<p align="center"><img src="../assets/ras-commander-fast-map_logo.svg" alt="RAS Commander Fast-Map: Native Rust Mapping Engine" width="450"></p>

Use `RasFim` to map computed HEC-RAS 2D cell results to depth and water surface
elevation (WSE) rasters. The Rust Mapping Engine reads terrain blocks and
rasterizes pixel ownership through terrio, reconstructs the selected surface,
and evaluates pixels with bounded Rayon workers. The native HDF engine reads
numeric model inputs; Python supervises requests and writes final GIS products.
The native mapping engine needs no system GDAL, but the Python delivery stack
uses Rasterio/GDAL for GeoTIFF output and compression.

This is a **2D surface-only** mapper. Model-backed calls reject models containing
1D river/reach or cross-section geometry, including mixed models. Pipes,
conduits and SA/2D connections are permitted when their hydraulic effects are
already represented in the computed cell results. The engine does not solve
structure hydraulics or map standalone storage-area surfaces outside the 2D mesh.

## Install and inspect capabilities

The Mapping Engine is the separate
[`ras-commander-fast-map` repository](https://github.com/gpt-cmdr/ras-commander-fast-map),
[Python package](https://pypi.org/project/ras-commander-fast-map/) and
[Rust crate](https://crates.io/crates/ras-commander-fast-map).
It is optional; unlike the default [HDF Engine](native-engine.md#hdf-engine),
it is installed through the `fim` extra on qualified Windows/Linux x64 systems:

```bash
uv pip install "ras-commander[fim]"
ras2fim-batch method
```

From a Commander checkout, use `uv pip install -e ".[fim]"`. To install only
the engine, use `uv pip install ras-commander-fast-map` or the `fast-map` extra.
Uninstall the former `ras2fim-engine` package first when migrating from its
retained test wheels, because it owns the same compatible executable.

Wheels provide `ras2fim-batch` on Windows x64 and Linux x64 (glibc 2.28+), without
a Rust compiler. [Tagged engine releases](https://github.com/gpt-cmdr/ras-commander-fast-map/releases)
carry wheels, a source distribution, a crate archive, build identity and
SHA-256 checksums. `ras2fim-batch method` reports the package version, source
commit, numerical method identifiers and capabilities. Commander resolves
`engine_path=`, then `RAS_COMMANDER_FIM_ENGINE`, the executable on `PATH`, and
finally the script recorded by the installed external distribution. This last
step supports callers that launch the environment's Python by its full path.
A missing or incompatible engine raises explicitly; mapping has no automatic
Python fallback. The horizontal NumPy reference backend is an explicit
qualification choice.

Rust consumers can use the library without Python, or install its compatible CLI:

```bash
cargo add ras-commander-fast-map
cargo install ras-commander-fast-map --locked
```

The Rust import is `ras_commander_fast_map`. It consumes prepared geometry,
profile arrays and terrain; Commander and fast-HDF still own model/HDF extraction.
It does not read a plan HDF directly. The source moved from Commander's former
`rust/step05/` directory with filtered Git history and immutable numerical-file
fingerprints. Crate and wheel version 0.8.0 preserve those qualified methods;
the packaging extraction does not introduce a new interpolation algorithm.

Ordinary Rust mapping loads no HEC-RAS assemblies. Native reference generation
and explicit corner preparation need an installed supported HEC-RAS runtime.
Install `.[fim,compute]` when using the native comparison workflow.

## Select the surface method

| Method | API and selection | Inputs and scope |
|---|---|---|
| Horizontal | `RasFim.map_horizontal_profiles(...)` | A cell table with WSE profile columns; each pixel uses its owning cell's constant WSE. Supply HDF provenance for whole-model 2D inspection. |
| Sloping (cell corners) | `RasFim.map_sloping_profiles(...)`, default `render_mode="sloping"` | A computed plan HDF; reconstructs cell-corner surfaces for `"Max"` or zero-based stored timestep indices. |
| Sloping (cell corners + cell faces) | Same API, `render_mode="slopingPretty"` | Enriches the sloping stencil with cell faces. `reduce_shallow_to_horizontal` is an independent option. |
| Depth-weighted cell faces | Cell-face mode with `use_depth_weighted_faces=True` | Requires stored corner ground elevations and the native HDF corner-reader capability described below. |
| ras2fim-2D Step 05 | `RasFim.map_profiles(...)` or `map_ras2fim_results(...)` | A separate triangulated catalog method. It is not the RAS Mapper horizontal/sloping reconstruction and has separate qualification. |

The [FIM API guide](api/fim.md) gives complete signatures and output contracts.
HEC's [Mapping Options, HEC-RAS Mapper User's Manual 6.6](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/mapping-results/mapping-options)
describes the native surface controls. The RAS Commander comparisons below use
the installed 7.0.1 runtime and matching options.

Supply a single-band float32 GeoTIFF with declared nodata, north-up square
pixels and the model CRS. It must represent the same effective terrain as the
native reference, including relevant terrain modifications. Outputs stay on
that terrain lattice without reprojection or resampling. Sloping has no added
depth cutoff. Horizontal `min_depth=0` also adds none; a positive value is an
optional strict depth filter in model elevation units. Native float32 plotting
tolerance is part of reconstruction and is separate from this postprocessing.

## Map several timesteps within a reach

```python
from ras_commander import RasFim

manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "terrain.tif", "reach_catalog",
    profiles={"maximum": "Max", "t0054": 54, "t0108": 108},
    polygon="reach_boundary.gpkg",  # or bbox=(xmin, ymin, xmax, ymax)
    threads=4, writer_threads=1,
    max_inflight_profiles=2, max_working_mib=4096,
    write_floodplain=False,
)
print(manifest[["profile", "status", "depth_tif", "wse_tif"]])
print(manifest.attrs["performance"])
```

Output folders must be new or empty. The returned manifest records product
paths, grid windows, finite-pixel counts and failures; its `performance`
attribute separates preparation and mapping phases. No reference map or
native hydraulic compute is required for this call.

A bbox or polygon constrains terrain reads and output pixels while retaining
the complete hydraulic topology and results needed at boundaries. Polygon
holes and multipart areas are retained. Output outside the polygon is nodata.
Use mapping-time masks on the original terrain rather than cropping or
retile-preparing a replacement terrain for cell-face qualification. To match
an existing native raster's complete layout, pass `template_raster=`; its grid,
nodata and storage metadata are used without reading its pixel values as results.

`max_inflight_profiles` defaults to one. Increasing it shares geometry, stencils,
terrain and ownership within one request while evaluating several profiles.
Effective concurrency is bounded by the requested count, worker count, profile
count and planned memory. `threads` controls one native Rayon pool;
`writer_threads` controls a separate GeoTIFF compression pool. The pools can
overlap, so budget both. `max_working_mib` is planned allocation admission,
not a hard resident-memory limit. The one-profile measurements below do not
measure this additional catalog-concurrency opportunity.

For repeated reach requests, use `RasFim.prepare_sloping_model()` as a context
manager and call its `map_profiles()` method with different masks. It retains
Python-side geometry/indexing and staged model/WSE inputs. Each request still
starts the native executable, reconstructs stencils and decodes its terrain
window; it is not a persistent native terrain cache. Changed source inputs
invalidate the context. See [prepared model usage](api/fim.md#reuse-prepared-models-across-reach-requests).

## Map caller-computed elevations

`map_sloping_profiles(..., wsel_profiles=table)` and
`prepare_sloping_model(..., wsel_profiles=table)` accept named WSEL columns keyed
by `mesh_name` and mesh-local `cell_id`. Include every physical and ghost cell
of every mesh, and omit the mutually exclusive `profiles` selector argument.
NaN explicitly means dry. Supplied elevations cast to float32 without window
aggregation, decimal rounding or unit conversion. The original HDF supplies
hydraulic geometry/properties; the caller chooses one original or healed
mapping TIFF independently. Bbox/polygon masks and bounded profile concurrency
work with these inputs.

Fast-Map 0.8.0 already supports the vector transport; only Commander needs the
new API. The [input contract, Python 3.11 installation and runnable CSV example](api/fim.md#supply-cell-wsel-profiles)
describe source binding, units, completeness and failure behavior. Full-mask
and float32 selector-equivalence checks do not qualify arbitrary aggregate
profiles or changed terrains as RAS Mapper products.

## Prepare corners for depth weighting

Depth-weighted mapping needs native stored corner ground elevations. If the
plan does not contain `FacePoints Elevation`, prepare them explicitly once:

```python
corners = RasFim.prepare_corner_elevations(
    "model.p02.hdf", "prepared_corners",
    rasmap_path="model.rasmap", terrain_name="Terrain",
)
manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "terrain.tif", "weighted_catalog",
    profiles={"maximum": "Max", "t0054": 54},
    render_mode="slopingPretty",
    use_depth_weighted_faces=True,
    reduce_shallow_to_horizontal=True,
    postprocessing_hdf=corners["postprocessing_hdf"],
    threads=4, max_inflight_profiles=2, max_working_mib=4096,
)
```

Preparation requires Windows and HEC-RAS 7.0.1. It uses the registered terrain
and native corner sampler or stored property-table elevations, writes a fresh
`PostProcessing.hdf` and receipt, and leaves source HDF and rasmap bytes unchanged.
It does not run hydraulics or export reference maps. Preparation has its own
reported clock; reuse its cache across profiles and reach requests. Subsequent
cache-only mapping works on Windows and Linux without loading HEC-RAS.

The adjacent receipt binds the cache to the plan and native terrain/rasmap
inputs. Those recorded source files remain required for validation. Relative
paths support moving a complete prepared workspace across platforms. The same
cache arguments work with `prepare_sloping_model()`.

Cell-face requests require the engine 0.8 `native_donation_history` capability;
weighted requests also require `depth_weighted_faces`. Numeric corner reads
require fast-HDF's native `mesh_corner_elevations` entry point, included in
published 0.2.3. The original numerical qualification used development wheels from commit
`6920fd8efb36831c32161156eee6c7635eee0229`, CI run `40351630621`; those wheels also
report version 0.2.2. Current installations should use 0.2.3 or newer; those
historical version strings alone do not identify capability. The
general HDF API separately supports an h5py fallback, but production FIM does
not silently substitute it. See [corner prerequisites and provenance](api/fim.md#depth-weighted-sloping-faces-engine-08).

Matching cell-face output requires preserving the native source TIFF grid and
256-square tile layout. Arbitrarily retiled/cropped terrain and multi-source
mosaics are not qualified for this option. Mapping-time AOIs preserve source
tile history and replay required predecessor geometry outside the output mask.
Terrain-modification-specific matching remains outside the retained evidence;
preparing native corners does not modify the supplied raster terrain.

## Mapping-time comparisons

These tables compare final qualified implementations with native RAS Mapper
7.0.1 on five real 2D models. Both Depth and WSE have zero extra valid pixels,
missing valid pixels or differing float32 bits **within the stated comparison
scope**. There is no added depth cutoff, reference filtering or resampling.
The criterion includes masks, not just values where both products are valid.

### Horizontal and cell-corner sloping

| Model | Method | RAS Mapper (s) | Rust pipeline (s) | RAS Mapper / Rust |
|---|---|---:|---:|---:|
| eBFE Spring River | Horizontal | 230.787 | 91.462 | 2.52× |
| eBFE Spring River | Cell-corner sloping | 240.726 | 79.098 | 3.04× |
| eBFE Spring Creek | Horizontal | 190.275 | 99.050 | 1.92× |
| eBFE Spring Creek | Cell-corner sloping | 209.896 | 88.724 | 2.37× |
| Bald Eagle dam break | Horizontal | 7.693 | 5.855 | 1.31× |
| Bald Eagle dam break | Cell-corner sloping | 7.393 | 5.976 | 1.24× |
| Bald Eagle bridges | Horizontal | 8.897 | 4.935 | 1.80× |
| Bald Eagle bridges | Cell-corner sloping | 8.585 | 3.157 | 2.72× |
| Davis pipes/conduits | Horizontal | — | — | — |
| Davis pipes/conduits | Cell-corner sloping | 1.909 | 0.527 | 3.62× |

These are retained 2026-10-26 Windows engine 0.7.0 measurements; 0.7.1 did not
change these kernels. They have not been re-timed in 0.8. Davis horizontal native
export failed, so no ratio or horizontal match is claimed for that case.
Comparisons cover the physical 2D footprint; Spring River, Spring Creek and
bridges also have complete-native-grid horizontal checks. The dam native call
includes standalone storage-area work excluded from the comparison footprint.
See the [original timing protocol](development/fim-mapping-performance.md#final-implementation-versus-rasmapper)
for per-method preparation and delivery details.

### Depth-weighted cell faces

| Model | RAS Mapper (s) | Rust pipeline (s) | RAS Mapper / Rust |
|---|---:|---:|---:|
| eBFE Spring River | 467.13 | 63.68 | 7.34× |
| eBFE Spring Creek | 418.99 | 76.17 | 5.50× |
| Bald Eagle dam break | 11.54 | 6.50 | 1.78× |
| Bald Eagle bridges | 12.50 | 4.43 | 2.82× |
| Davis pipes/conduits | 3.44 | 0.71 | 4.81× |

This is the final 0.8.0 Windows implementation with both depth weighting and
shallow-to-horizontal enabled. River, Creek and bridges match complete native
grids, including nodata borders. Dam and Davis comparisons cover physical 2D
cells, excluding standalone storage-area surfaces. The dam native clock also
includes additional storage-area rendering, so its ratio compares workflow
calls with unequal work outside the supported 2D scope.

Both tables map one Max Depth/WSE pair with four-CPU affinity. Rust uses four
mapping workers and four initial compression workers; native export requests
one stored-map worker. Clocks include HDF staging, mapping and output delivery;
terrain preparation and comparison scanning are excluded. Explicit corner
preparation is also excluded from weighted mapping: the recorded separate
preparation times are 38.78 s for River, 57.51 s for Creek and 1.84 s for Davis.
The first two preparations competed with builds and are not controlled
preparation benchmarks.

Calls are single observations on a shared workstation with uncontrolled cache
state. Native references were retained before later final-engine measurements
for horizontal/plain sloping and River weighted mapping. Other weighted model
calls ran sequentially per model. These are not repeated, interleaved benchmark
estimates or general speed guarantees. The [performance and qualification report](development/fim-mapping-performance.md)
retains detailed coverage, reproducible runners, raw comparison criteria,
dependency identities and the native Davis failure diagnosis.

## Reproduce and inspect comparisons

Use `RasFim.compare_with_rasmapper()` for native horizontal reference generation
and API timing returns. It delegates stored-map work through `RasProcess`,
restores the original rasmap bytes, and exposes
`comparison.attrs["performance"]`. Use an isolated computed-project copy because
native mapping can write other project caches. The API documents when a ratio
is withheld rather than treating a partial match as equivalence.

For sloping, `scripts/benchmarks/fim_sloping_compare.py` maps an external case
and compares retained native Depth/WSE masks and float32 bits. Weighted cases
must supply matching render options and corner-cache arguments. Use
`--match-reference-grid` to include native nodata borders. Horizontal raw parity
has its own `scripts/benchmarks/fim_horizontal_parity.py` runner.
See [reproduction instructions](development/fim-mapping-performance.md#reproduce-comparisons)
and the [FIM API](api/fim.md) for input contracts and result interpretation.

These comparisons establish the stated numerical agreement on the listed
models and runtime. They do not establish hydraulic accuracy or parity for
every HEC-RAS version, terrain source layout or model feature.
