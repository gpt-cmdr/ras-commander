# ras_commander.fim Contract

Local rules for the optional ras2fim-2D flood inundation mapping (FIM) subpackage.
Parent `ras_commander/AGENTS.md` and root `AGENTS.md` still apply.

## Scope

- `RasFim.map_profiles` maps 2D cell WSE profiles with the ras2fim-2D Step 05 method through the external
  `ras2fim-batch` engine. It is not RAS Mapper stored mapping; never describe the products as
  equivalent to `RasProcess.store_maps()` output.
- The engine is optional: the `fim` extra installs ras-commander-fast-map on
  qualified Windows/Linux x64 platforms. Resolve explicit `engine_path`, then
  `RAS_COMMANDER_FIM_ENGINE`, PATH, and the installed distribution's script.
  Runtime mapping never builds/downloads/installs it or falls back to Python arithmetic.
- Do not reimplement the engine numerics in Python or Rust here. Python owns sample preparation,
  SciPy Delaunay export, grid derivation, product writing, and the manifest. The engine source
  is https://github.com/gpt-cmdr/ras-commander-fast-map. The Step05 numerical path remains identical to the reviewed ras2fim-2D
  copy; the independent horizontal module has its own method contract and qualification.
- `map_horizontal_profiles` is a separate, explicit cell-constant method. Rust is the default;
  NumPy is an explicit qualification reference, never a fallback. It uses float32 cell WSE,
  terrain-lattice ownership and native float32 visibility WSE >= terrain + 0.001
  before subtraction. Preserve operation order: a post-subtraction tolerance is
  not equivalent. Zero min_depth adds no cutoff; positive optional filters apply
  to depth and WSE after native visibility. Method /2 requires engine0.7 or newer. It does not implement native sloping, 1D or structure-specific rendering.
  Its manifest records `method_id`, `backend`, threshold and grid. Shared product names
  are layout conventions; determine the method from the manifest.

## Invariants

- `map_sloping_profiles` is a separate experimental native plain-sloping method,
  `rasmapper-plain-sloping/1`. It reads complete HDF topology and virtual cell WSE
  through the Rust HDF backend; Rust reconstructs hydraulic face connections,
  corner values and polygon/square pixel weights. Preserve binary32 operation
  order, side-specific disconnected corner values and native intrinsic plot
  tolerance. It has no additional depth cutoff. The optional `slopingPretty`
  mode adds native corner-to-face weight donation and optional
  shallow-to-horizontal selection. Keep plain defaults unchanged;
  the selected method/options must appear in the engine report and manifest.
  Depth-weighted faces require the advertised engine capability and stored
  corner ground elevations read by the native HDF backend. Cache-only inputs
  require a verified preparation receipt binding the plan and terrain sources.
  `prepare_corner_elevations` is an explicit Windows/7.0.1 native preparation
  operation, separate from production mapping and its clocks. Never sample
  missing corner elevations or load HEC-RAS inside ordinary mapping.
- Cell-face mapping requires `native_donation_history`. Preserve retained donor
  scratch in fixed 256-point ranges per source terrain tile. Replay complete
  physical cell geometry, including predecessors outside AOIs, for affected
  cells; independently clearing pixel scratch changes native values. Keep the
  original source TIFF lattice/tile layout. Full Windows weighted+shallow Max
  checks pass all five models, including River and Creek, with complete mask/bit
  equality. Arbitrary retiled terrain and multi-source mosaics are unqualified.
- Sloping AOIs constrain terrain/ownership/output pixels only. Keep the complete
  geometry for hydraulic connectivity and corner reconstruction across boundaries.
  Geometry, terrain and ownership are reused across all profiles in one request.
- Sloping raw-mask/bit qualification targets native 7.0.1. Max profiles on Davis
  pipes/conduits and Bald Eagle dam/bridge meshes, plus two Davis timesteps,
  currently pass. Bounded Max tests also pass on Spring River and Spring Creek
  with full global topology. Final Windows Max checks also match the full
  physical 2D footprints of both eBFE fixtures. This evidence does not establish
  full-extent Linux eBFE or unweighted face-mode eBFE,
  other native versions, 1D,
  storage areas outside the physical 2D footprint, or all option combinations.
- `terrain_hdf` (sloping, horizontal, whole simulation) maps on the original
  priority-1 source TIFF with the engine's `terrain_scope`
  (`top-priority-source-footprint/1`). Priority comes only from source
  `Priority` attributes (0 highest) or, when none exist, the terrain's own VRT
  order; both must agree when present. Refuse partial, duplicate or conflicting
  declarations, modified terrains, non-256 tiling and storage-area plans. A
  `canonicalize_terrain_crs` copy is accepted only through its receipt and a
  fresh pixel-hash match. Engine `unsupported:` refusals surface as
  `FimUnsupportedError` (`_engine.EngineRefusal`) so callers fall back to an
  exported terrain; never widen the footprint or mosaic lower-priority sources.
- `map_whole_simulation` stages every stored output time's raw cell WSE, cell
  minimum elevations and float64 hours since the plan's simulation start; the
  engine owns the wet gate and accumulation. Arrival time and percent
  inundated are the qualified defaults; duration and irregular intervals need
  `allow_unqualified`. Storage-area plans are refused.
- Sloping `velocity=True` stages HDF face normals with face polyline lengths and
  per-profile face velocities (Max: `Maximum Face Velocity`). Plain sloping
  with HDF profiles only. Native velocity validity masks can differ from the
  rendered depth mask on a small fraction of edge pixels (bridges p05 Max:
  826 native-only and 1,196 extra of 973,532); values on common pixels match.
- `_sloping_oracle.py` is a development reference reader only. Production mapping
  must not import it or depend on installed HEC-RAS DLLs. Never commit decompiled
  vendor source, captured project geometry, or generated raster evidence.

- Model-backed mapping rejects any 1D river centerline/reach or cross-section geometry before
  mesh selection or engine execution. Coupled pipe hydraulic tables alone are permitted.
  Preserve source-HDF provenance on extracted cell tables; standalone polygon tables cannot
  establish the dimensional scope of an unseen source model.
- Step05 preparation is global. Wet samples, triangulation, query axes, and the wet mask use every wet
  cell before any AOI. An AOI selects output pixels on the final grid only. Never subset or
  retriangulate for an AOI.
- Preserve the upstream sample order and float semantics; changes need qualification against the
  retained Step 05 oracle. The defaults (`grid_anchor="ras2fim"`, `coplanar="error"`) are the
  upstream recipe; the opt-in `grid_anchor="terrain"` and `coplanar="ignore"` are recorded
  departures and never become defaults silently.
- Horizontal ownership and terrain are prepared once for the constrained terrain window and
  reused across profiles. Spatially filter geometry before checking/rasterizing it. Reject
  overlapping interiors instead of smoothing or averaging across cells. Planned array
  admission excludes polygonization and is not a hard RSS limit.
- Inputs are read-only. Products go to a new or empty `output_folder`. Input file identities are
  checked after mapping.
- Failures are explicit: missing engine, engine exit codes other than 0/2, inconsistent units, and
  unsupported inputs raise or mark the profile `failed`; `map_profiles` raises `FimMappingError`
  after writing `fim_manifest.json`.
- Cell centres come from `HdfMesh.get_mesh_cell_points`, never raw HDF paths.
- Sloping uses typed centers (`include_geometry=False`) and reuses immutable,
  source-indexed per-mesh timestep views. Retain required-native payload reads
  and per-read source identity validation. Overlap predicate batches are bounded;
  batching must not omit candidate pairs or alter ownership.
- Sloping `writer_threads` explicitly scopes GDAL compression settings, including
  the default of one, and restores the enclosing setting on exceptions. Rust
  `threads` and compression workers are separate budgets that can overlap.
- Sloping `max_inflight_profiles` defaults to one. All in-flight profiles share
  one Rayon pool; cap effective admission by requested concurrency, threads,
  profile count and available planned memory. Keep stencils/terrain/ownership
  immutable, preserve per-profile arithmetic and ordered stream/report emission.
  Failures clean already delivered products. Require an advertised capability
  for concurrency, retaining sequential compatibility with older engines.
- The returned manifest columns are declared as `fim_product_manifest` in `ras_commander/schemas.py`.

## Testing

- Supplied `wsel_profiles` tables bind complete mesh-local cell IDs to the original
  source HDF. Require every mesh and every physical/ghost row; never fill absent
  IDs from Max or a timestep. NaN explicitly means dry and becomes finite float32
  minimum; reject infinity/overflow. Preserve float32 bits and caller ordering of
  profile columns while aligning row IDs. Caller snapshots/staged hashes identify
  the source, and an AOI never relaxes completeness. Aggregation, decimal rounding,
  elevation-unit/datum correctness and new-terrain qualification remain caller
  responsibilities. The mapping terrain stays independent of hydraulic geometry.

- Unit tests use synthetic frames and a simulated engine. Engine-backed tests are opt-in through
  `RAS_COMMANDER_FIM_ENGINE` and `RAS_COMMANDER_FIM_FIXTURE`; they never run HEC-RAS.
- Do not commit fixtures, prepared inputs, engine builds, or products.

- `compare_with_rasmapper` generates native horizontal maps only through `RasProcess`,
  uses the same re-entrant project lock, verifies/restores the original rasmap bytes in finally,
  and rejects reference resampling. Its scope is the selected 2D cell footprint/AOI, not native
  1D/structure/sloping rendering. Report reference missing WSE separately from finite pairs.
- Comparison performance belongs in `DataFrame.attrs["performance"]` and its JSON receipt.
  Separate native stored-map generation, independent optional filtered delivery writes, Rust
  batch time and comparison scanning. Do not multiply shared batch preparation by profile count
  or promote a speed ratio for unmatched AOI, mesh or storage-area scope.
