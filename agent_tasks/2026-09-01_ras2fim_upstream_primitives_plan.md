# ras2fim upstream primitives implementation plan

Date: 2026-09-01

## Goal

Add only the generic ras-commander APIs that the private ras2fim fork needs,
without moving ras2fim inventory, hydrofabric, scenario, rating-curve, or
release-policy concerns upstream.

## Confirmed existing capabilities

- Exact 1D and 2D footprints already exist in `HdfProject` and `HdfXsec`.
- Project discovery, plan/geometry metadata, terrain discovery, cloning,
  steady-flow authoring, execution, steady-result extraction, and compute-message
  QA already exist.
- Text-project units are available through `RasPrj.get_project_units()` in PR
  #327 and are authoritative whenever the project `.prj` is available.

## Upstream implementation scope

### 1. Unified cross-section points

- Land PR #327 after changing project-backed HDF extraction to pass the unit
  value parsed from the project `.prj` as an explicit override.
- Preserve HDF unit discovery only for direct, lower-level HDF calls that do not
  have project context.

### 2. Batched steady-profile stored maps

Public contracts:

- `RasProcess.store_maps_at_steady_profiles(...)` is the execution engine.
- `RasMap.store_all_maps(mode="steady_profiles", ...)` is the canonical,
  JSON-serializable facade.

Required behavior:

- Resolve profile names and zero-based indexes from
  `HdfResultsPlan.get_steady_profile_names()`.
- Accept all profiles, exact profile names, or zero-based profile indexes.
- Reject missing names, duplicate names in the result HDF, duplicate requests,
  and filenames that collide after RASMapper-safe normalization.
- Add every requested profile/map combination to the `.rasmap` in one XML
  parse/write transaction.
- Optionally add one inundation-boundary polygon for the highest selected
  profile or an explicitly selected profile.
- Invoke aggregate `StoreAllMaps` exactly once per plan. Do not loop through
  `RasProcess.store_maps()`.
- Restore the original `.rasmap` even on failure.
- Return deterministic profile-to-asset records from `RasProcess`; serialize
  those records into the existing `RasMap.store_all_maps()` summary shape.
- Use the existing Windows/Wine helper and mapper-compatible HDF context.

Performance qualification:

- Record profile count, configured map count, XML-configuration wall time,
  helper wall time, total wall time, and generated file count in result metadata.
- Keep execution aggregate/serial by design: the optimization is avoiding one
  helper startup and one XML rewrite per profile.
- Later compare this single-launch path with the legacy repeated-launch ras2fim
  worker on the Iowa/RRASSLER sample and a larger BLE model.

### 3. Standalone result-HDF unit metadata

Public contract:

- `HdfBase.get_result_unit_metadata(hdf_path)` returns normalized metadata from
  an HEC-RAS plan-result HDF.

Required behavior:

- Name and documentation must state that this is for a standalone result HDF
  when the full project `.prj` is unavailable.
- A full-project workflow must use `RasPrj.get_project_units()` instead.
- Promote the strict evidence and contradiction handling already implemented by
  `HdfResultsProducts._unit_metadata()`.
- Return JSON-serializable unit system, horizontal/length units,
  vertical/depth units, velocity units, source, and evidence.
- Raise on missing, unrecognized, or contradictory embedded metadata.
- Refactor `HdfResultsProducts` to call the public reader so the logic has one
  source of truth.

## Explicitly out of upstream scope

- Persistent model inventory/registry and supersession policy.
- Hydrofabric conflation and confidence policy.
- HUC8 catalog identifiers and overrides.
- Discharge ladders, two-pass refinement, rating curves, and ras2fim QA policy.
- ras2fim checkpoints, worker/container supervision, DEM clipping,
  simplification, geocurves, and release packaging.
- New footprint APIs.
- Terrain-agreement work, which is generic but optional and not required for
  this integration slice.

## Verification

- Focused unit tests for bulk XML configuration, profile selection and
  validation, one-helper invocation, result grouping, rasmap restoration,
  facade dispatch, and unit evidence/contradictions.
- Existing stored-map, RasMap mode, HDF result-product, cross-section, project,
  and schema tests.
- Documentation build if API pages change.
- Real HEC-RAS qualification on Windows and Wine when a suitable steady model
  and installed runtime are available; do not substitute direct executable
  calls for ras-commander APIs.

## Implementation status

- PR #327 (unified cross-section points) was corrected per the API audit,
  passed its focused suite and CI, and merged to `main` as `4a0cef6a1`.
- `HdfBase.get_result_unit_metadata()` is implemented as a strict,
  standalone plan-result-HDF fallback. Documentation and docstrings state that
  `RasPrj.get_project_units()` is authoritative when the project is available.
- `RasProcess.store_maps_at_steady_profiles()` and
  `RasMap.store_all_maps(mode="steady_profiles")` are implemented with one
  bulk stored-layer XML transaction and one aggregate helper launch per plan.
- Public DataFrame schema version 1.8 includes both `cross_section_points` and
  `steady_profile_stored_maps`.
- Integrated focused verification: 155 passed, 16 skipped.
- Broad repository verification reached 2,455 passed and 121 skipped; its 41
  failures and two setup errors were in environment/package-artifact cases
  outside the changed paths (notably missing `netCDF4`/`pythonnet`, installed
  package-metadata expectations, and local native validation fixtures).
- Python compilation and `git diff --check`: passed.
- Documentation CI-equivalent generation and MkDocs build: passed; only the
  repository's pre-existing non-strict notebook link/date warnings remain.
- Real HEC-RAS and Windows/Wine performance qualification remains a downstream
  qualification task requiring a suitable computed steady project/runtime.
