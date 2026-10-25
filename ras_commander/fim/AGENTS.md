# ras_commander.fim Contract

Local rules for the optional ras2fim-2D flood inundation mapping (FIM) subpackage.
Parent `ras_commander/AGENTS.md` and root `AGENTS.md` still apply.

## Scope

- `RasFim.map_profiles` maps 2D cell WSE profiles with the ras2fim-2D Step 05 method through the external
  `ras2fim-batch` engine. It is not RAS Mapper stored mapping; never describe the products as
  equivalent to `RasProcess.store_maps()` output.
- The engine is optional and explicit: `engine_path`, `RAS_COMMANDER_FIM_ENGINE`, or `PATH`.
  Never build, download, or install it, and never fall back to Python arithmetic.
- Do not reimplement the engine numerics in Python or Rust here. Python owns sample preparation,
  SciPy Delaunay export, grid derivation, product writing, and the manifest. The engine source
  is `rust/step05/`. The Step05 numerical path remains identical to the reviewed ras2fim-2D
  copy; the independent horizontal module has its own method contract and qualification.
- `map_horizontal_profiles` is a separate, explicit cell-constant method. Rust is the default;
  NumPy is an explicit qualification reference, never a fallback. It uses float32 cell WSE,
  terrain-lattice ownership and subtraction, with the caller's pixel depth filter applied to
  depth and WSE. It does not implement native sloping, 1D or structure-specific rendering.
  Its manifest records `method_id`, `backend`, threshold and grid. Shared product names
  are layout conventions; determine the method from the manifest.

## Invariants

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
- The returned manifest columns are declared as `fim_product_manifest` in `ras_commander/schemas.py`.

## Testing

- Unit tests use synthetic frames and a simulated engine. Engine-backed tests are opt-in through
  `RAS_COMMANDER_FIM_ENGINE` and `RAS_COMMANDER_FIM_FIXTURE`; they never run HEC-RAS.
- Do not commit fixtures, prepared inputs, engine builds, or products.

- `compare_with_rasmapper` generates native horizontal maps only through `RasProcess`,
  uses the same re-entrant project lock, verifies/restores the original rasmap bytes in finally,
  and rejects reference resampling. Its scope is the selected 2D cell footprint/AOI, not native
  1D/structure/sloping rendering. Report reference missing WSE separately from finite pairs.
