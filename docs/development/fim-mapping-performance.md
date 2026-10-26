# Native FIM mapping performance

Use `RasFim.map_horizontal_profiles()` for cell-constant horizontal mapping or
`RasFim.map_sloping_profiles()` for cell-corner sloping. Both methods map
physical 2D cells, reject models containing 1D river/cross-section geometry,
and support bbox/polygon output constraints. Rust reads numeric HDF inputs,
rasterizes ownership through terrio, reconstructs sloping surfaces and maps
pixels with bounded Rayon workers. Python manages requests and GeoTIFF delivery.
Production mapping requires no HEC-RAS assemblies.

## Final implementation versus RASMapper

| Model | Physical 2D cells | Interpolation | RASMapper (s) | Final Rust pipeline (s) | RASMapper / Rust | Raw comparison |
|---|---:|---|---:|---:|---:|---|
| eBFE Spring River | 422,715 | Horizontal | 230.787 | 91.462 | 2.52× | Exact mask and values (2D) |
| eBFE Spring River | 422,715 | Sloping: cell corners | 240.726 | 79.098 | 3.04× | Exact mask and values (2D) |
| eBFE Spring Creek | 340,163 | Horizontal | 190.275 | 99.050 | 1.92× | Exact mask and values (2D) |
| eBFE Spring Creek | 340,163 | Sloping: cell corners | 209.896 | 88.724 | 2.37× | Exact mask and values (2D) |
| Bald Eagle dam break | 87,039 | Horizontal | 7.693 | 5.855 | 1.31× | Exact mask and values (2D) |
| Bald Eagle dam break | 87,039 | Sloping: cell corners | 7.393 | 5.976 | 1.24× | Exact mask and values (2D) |
| Bald Eagle bridges | 24,718 | Horizontal | 8.897 | 4.935 | 1.80× | Exact mask and values (2D) |
| Bald Eagle bridges | 24,718 | Sloping: cell corners | 8.585 | 3.157 | 2.72× | Exact mask and values (2D) |
| Davis pipes/conduits | 2,716 | Horizontal | — | — | — | Native export failed |
| Davis pipes/conduits | 2,716 | Sloping: cell corners | 1.909 | 0.527 | 3.62× | Exact mask and values (2D) |


The table reports the final qualified horizontal/sloping implementation's
2026-10-26 Windows measurements against native RASMapper 7.0.1. Both Depth and
WSE have identical complete validity masks and valid float32 bits within the
physical 2D footprint. There is no added depth cutoff, reference filtering or
resampling. Equality only where both rasters are valid is insufficient.

Native exports/times were retained from the same-day reference run; Rust 0.7.0
was measured afterwards rather than interleaved. Engine 0.7.1 removes an
unreleased control without changing these horizontal/plain-sloping kernels.
These measurements are observations, not a universal speed guarantee.

Each row maps one Max Depth/WSE pair on the complete native pixel lattice,
nodata border and storage layout. The clock includes HDF preparation, launch,
mapping and output delivery. Native/project initialization, canonical terrain
preparation and comparison scanning are outside the clocks. Sloping uses
metadata-only direct-template delivery. Horizontal includes cell-table
preparation and a matching-grid raster rewrite using one compression worker.
No floodplain polygonization or profile concurrency is included.

Processes inherit four-CPU affinity. Rust mapping and initial compression each
use four workers; native export requests one worker. The first horizontal
bridge clock includes dependency imports; later calls use warm imports.
No mapping warm-up is excluded. Filesystem caches and shared-workstation load
are uncontrolled.

The dam-break reference also renders standalone storage-area surfaces outside
physical 2D cells. Those pixels are excluded from comparison, but their native
rendering time is included. Its ratio therefore compares the measured workflows,
not equal work outside the supported scope. Davis horizontal native export
failed with exit 99; no time or ratio is claimed. See issue
[#678](https://github.com/gpt-cmdr/ras-commander/issues/678).

## Plain sloping development qualification

Native 7.0.1 Max qualification covers Spring River (422,715 physical cells),
Spring Creek (340,163), Bald Eagle dam break (87,039), Bald Eagle bridges
(24,718), and Davis pipes/conduits (2,716). Windows checks cover the full
physical 2D footprints; Linux eBFE evidence is bounded while retaining global
topology. Davis also covers stored timestep indices 54 and 108. Other native
versions, 1D surfaces, and standalone storage areas remain outside this evidence.

The optional unweighted `render_mode="slopingPretty"` adds cell faces.
Its shallow-to-horizontal control can be off or on. Both settings match raw
native bridge Max and Davis 54/108 masks and float32 bits with one/four workers
on Windows and Linux. No elapsed-time comparison is claimed for this mode here.

## Complete horizontal validity

`horizontal-cell-constant/2` evaluates native binary32
`WSE >= float32(terrain + 0.001)` before depth subtraction. A post-subtraction
cutoff is not equivalent. Zero optional `min_depth` adds no cutoff and preserves
native-valid zero depths. Rust and the explicit NumPy reference use this rule;
older /1 engines raise explicitly.

Full Windows Spring River, Spring Creek, dam and bridge Max checks have zero
extra, missing, bit-different or outside-footprint pixels for both bands.
Spring River, Spring Creek and bridges also match the entire native raster
grid, including nodata borders, without a footprint mask. The dam reference
contains 464,445 standalone storage-area pixels outside physical 2D scope.
Comparison metrics retain valid zero depths and compare float32 bits, including
signed zero.

## Catalog throughput

```python
manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "canonical_terrain.tif", "reach_catalog",
    profiles={"maximum": "Max", "t0054": 54},
    polygon="reach_boundary.gpkg",  # or bbox=(xmin, ymin, xmax, ymax)
    threads=4, writer_threads=1, max_inflight_profiles=2,
)
```

Geometry, stencils, terrain and ownership are shared across profiles in one
request. Effective profile concurrency is capped by requested concurrency,
worker count, profile count and planned memory. One Rayon pool bounds native
work. Results stream in request order. The default remains one in-flight
profile. Memory admission is planned rather than a hard RSS limit.

AOIs constrain terrain/ownership/output pixels while retaining the complete
hydraulic topology and cell results needed at boundaries. Omit
`template_raster` for compact catalog outputs; a metadata-only template supports
delivery on the complete native grid. Compression workers have a separate
budget and may overlap native workers. GDAL settings are restored on success
and failure.

## Prepared model contexts across reach requests

For repeated reach requests, use `RasFim.prepare_sloping_model()` as a context
manager. It retains physical cell polygons/indexing, scope, terrain metadata and
complete staged mesh/WSE files. Repeated selectors share files. Each request
still starts a fresh native process, reconstructs stencils and decodes its
terrain window. Source size/mtime changes invalidate the context; close waits
for active calls and releases staging. No current prepared-context speed ratio
is claimed on this page.

## Reproduce comparisons

`scripts/benchmarks/fim_sloping_compare.py` maps an external case and compares
raw Depth/WSE masks and float32 bits to retained native references. Use
`--match-reference-grid` for nodata-border delivery. Its receipt separates
mapping time from comparison scanning and records input/reference identities.
`scripts/benchmarks/fim_horizontal_parity.py` reproduces horizontal qualification
without invoking HEC-RAS or filtering the references.

Real-model pytest cases use `RAS_COMMANDER_SLOPING_CASE` and
`RAS_COMMANDER_SLOPING_OPTIONS_CASES`; datasets and generated rasters stay
external. The latter selects unweighted cases only. Tests cover single/multiple
workers, AOIs, timesteps, bounded concurrency, delivery failures and context
lifecycle. Installed-wheel smoke covers file and streaming delivery on Windows,
Linux and glibc 2.28. Retained wheel hashes and source provenance are under
`wheels/`. Step05 remains a separate ras2fim-2D method; its products are not
RASMapper sloping products.

## Roadmap and dependencies

Depth-weighted faces are deferred. They require a shared Rust/Python HDF reader
for stored corner ground elevations in geometry/plan HDFs and native
`PostProcessing.hdf`, plus mesh-order/identity and effective-terrain provenance
validation. Missing inputs need an explicit, separately timed Commander native
preparation API using the same terrain and obstructions as RASMapper. Production
mapping must remain native-runtime independent. Reintroduce the control only
after complete-mask/float32-bit qualification, including Spring River and Spring
Creek, and renewed benchmarks. The pre-deferral implementation is preserved on
`archive/fim-depth-weighted-20261026`.

Later performance work includes chunked HDF staging, persistent native terrain
and stencil reuse across reach requests, and bounded pixel-weight caches.
Separate `ras-commander-fast-fim` packaging remains a future integration step.
