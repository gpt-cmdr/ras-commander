# Release Notes

## Version History

### Unreleased

**Version-Aware GeoTIFF/GRIB Precipitation Ingestion**

- Correct the translated NetCDF GeoTransform to GDAL ordering, with an
  independent rasterio reopen check for transform, CRS, extent, and values.
- Preserve AORC's first hourly accumulation in `create_storm_plans()` by
  passing explicit amount/mm/one-hour semantics; add a RasExamples HDF regression.
- Refresh precipitation documentation to use implemented APIs. Retire the
  obsolete notebook 722 authoring cells in favor of 727; add temporary-HDF
  checks to Atlas 14, AORC, historical-event, and HRRR workflows, correct the
  MRMS precompute plot label, and clarify uniform-boundary/WPC example scope.
- Qualify native DSS on CLB07/Wine 11 with HEC-RAS 6.6. The prior timeout was
  caused by the harness's disabling DLL override; removing the combined
  `mscoree,mshtml` override restored preprocessing and verified computation.
- Prevent beta versions from inheriting stable-release qualification.

- Add first-class `RasUnsteady.set_gridded_precipitation_geotiff()` support for
  one multiband GeoTIFF or a timestamped sequence of single-band GeoTIFFs.
  Inputs are normalized to cumulative precipitation, written to a validated
  content-addressed project NetCDF, and materialized through the native HDF
  writer. The `.u##` references the durable NetCDF rather than advertising
  GeoTIFF as a vendor-native HEC-RAS meteorology source.
- Add the same explicit normalization route for projected GRIB/GRIB2 through
  `set_gridded_precipitation_grib()`. WPC QPF's vendor-documented compression
  limitation remains routed through HEC-Vortex/HEC-MetVue to DSS when the local
  GDAL stack cannot decode it.
- Exercise the GRIB route with a real filtered NOAA HRRR GRIB2 precipitation
  record, including explicit message selection and positive-value native HDF
  authoring. This is format-decoding/authoring evidence; native HEC-RAS GRIB
  preprocessing remains documentation-backed until its executable matrix is
  complete.
- Require explicit timestamps, units, and rate/amount/cumulative semantics;
  validate CRS, affine orientation, square cells, band counts, monotonic time,
  nonnegative precipitation, and consistent grids. NoData fails by default and
  is converted to dry cells only with `nodata_policy="zero"`.
- Validate raster and GRIB unit metadata as temporal semantics as well as depth
  units, including HEC-RAS rate spellings such as `mmph` and GDAL's
  `GRIB_UNIT`; reject rate/amount mismatches and non-hourly rates that require
  an explicit conversion.
- Make the persistent cache genuinely semantic: source paths no longer affect
  identity, and reuse verifies values, time/x/y coordinates, CRS, transform,
  units, and temporal type before accepting an existing NetCDF.
- Add `PrecipCapabilities` and
  `RasUnsteady.get_gridded_precipitation_capabilities()` so HEC-RAS 5.x is
  rejected for global gridded meteorology and the 6.0-6.1 ratio and
  6.0-6.3.1 period-average timing defects are visible to callers.
- Make source/route qualification fail closed for invalid combinations and
  retain exact release-level evidence rather than extrapolating to patch
  releases that were not tested.
- Apply the HEC-RAS 6.0-6.1 ratio safeguard to DSS as well as raster inputs,
  including retained text settings, while allowing `ratio=1.0` to clear an
  ineffective value. Preserve the established
  `set_gridded_precipitation()` `None` return contract; the new source-specific
  adapters provide structured result objects.
- Extend the process-local WMIC compatibility shim from HEC-RAS 6.3 to the
  executable-evidence-backed 6.1-6.3 family. This repairs modern-Windows solver
  startup without modifying HEC-RAS or the caller's environment.
- Add notebook 729 and an opt-in RasExamples qualification test. A native
  Windows HEC-RAS 6.6 run imported a deterministic 4-by-17-by-24 cumulative
  GeoTIFF-derived cube, materialized fresh temporary-plan-HDF rainfall,
  completed the Bald Eagle p06 simulation, and produced positive final
  per-cell precipitation and hydraulic results. The notebook preserves the
  source, precompute, rainfall, and hydraulic figures for manual review.
- Qualify the same public GeoTIFF workflow end to end on CLB07 with HEC-RAS
  6.6 under Wine 11.0: preprocessing emitted the expected four solver rows,
  runtime messages contained no precipitation error, and the final HDF held
  positive cumulative rainfall and hydraulic depth across the mesh.

**Native Gridded-Precipitation Authoring and Precompute Readiness (#371)**

- Add `RasPrecipHdf`, a focused writer for HEC-RAS's native
  `Precipitation/Imported Raster Data` payload. Grids are normalized to
  north-up/west-first order, regular square cells are required, dataset chunking
  follows native HEC-RAS specimens, and invalid inputs are rejected before the
  HDF is changed.
- Make `RasUnsteady.set_gridded_precipitation()` fail fast for missing files,
  dependencies, and variables; create a missing `.u##.hdf`; write the HDF
  before changing the `.u##` text; and expose source `units`, `value_type`,
  `first_timestep_hours`, and precipitation `ratio`. Rate, interval-amount, and
  cumulative inputs are now converted explicitly instead of assuming an hourly
  rate and silently discarding the first band.
- Require solver-ready precipitation during `RasPreprocess.preprocess_plan()`.
  For a gridded-rain plan, the early `.bco` marker is no longer sufficient:
  preprocessing waits for fresh, complete artifacts and the materialized
  plan-HDF `Precipitation/Values` and `Timestamp` datasets. An `Imported
  Raster Data` payload by itself is reported as incomplete rather
  than being returned as a successful Linux precompute.
- Qualify the complete public-API workflow on CLB07 with HEC-RAS 6.6 under
  Wine 11.0 and the native Linux solver. Both a 7-by-25 test payload and the
  reported 76-by-1190 dimensions materialized correctly and were read by the
  solver with no precipitation errors. The native `Imported Raster Data`
  group is the correct authoring location; HEC-RAS preprocessing creates the
  shallower solver-facing datasets.
- Restore the remaining safeguards from the earlier unmerged feature branch:
  AORC storm-plan creation now validates each caller-supplied NetCDF before
  cloning, gridded DSS configuration preserves mapped-drive paths with
  `RasUtils.safe_resolve()`, and unreadable precipitation sidecars emit a
  diagnostic warning instead of being silently ignored.
- Expand notebook 924 into an explicit authoring/precompute/postcompute
  qualification. A Windows HEC-RAS 7.0 run materialized a 5-by-30 source grid,
  produced positive cumulative rainfall in 18,066 mesh cells, and produced a
  nonzero hydraulic response. The finalized code also requalified on CLB07
  with HEC-RAS 6.6/Wine 11.0, materializing aligned 7-by-25 `Values` and
  7-element `Timestamp` datasets.

**Refinement-Region Authoring and Mesh Density (#369)**

- Author real geometry through RAS Mapper's native `MeshRegions` layer on
  Windows/Wine, with a same-file backup and a fresh product reload before
  success is reported. The portable/synthetic fallback now writes all nine
  native Attributes fields and the semantic polygon dataset metadata instead
  of the incomplete three-field record that RAS Mapper silently ignored.
- Pass every active refinement-region FID to
  `PointGenerator.RegenerateMeshPoints`; previously the region argument was
  always empty, so valid regions still had no effect on seed density.
- Add a region-only `RasExamples` Chippewa_2D integration gate. A 200-ft base
  mesh becomes a locally 40-ft mesh, with product reload and measured
  inside-polygon nearest-neighbor spacing asserted. Native Windows results are
  identical on installed HEC-RAS 6.0, 6.1, 6.2, 6.3, 6.3.1, 6.5, 6.6, and
  6.7 Beta 5; 6.4/6.4.1 was not locally installed for qualification. HEC-RAS
  6.6 also passes under Wine 11.0 on CLB07 for both the product-layer writer
  and the native-schema fallback: 2,118 generated computation points, 4,376
  faces, 1,600 centers inside the region at 40-ft median nearest-neighbor
  spacing, and 122.327 ft outside. The Wine runner prepares the documented
  task-local `C:\Python311\GDAL` link from Linux before loading RAS Mapper.

Implementation provenance: an anticipatory version of these corrections was
preserved in July on the unmerged `codex/h-native-mesh-authoring` branch
([commit `9a963aa37`](https://github.com/gpt-cmdr/ras-commander/commit/9a963aa3781729a9d0db31fe0c3206c3e3566c78)).
That work was never opened as a PR or merged because refinement-region
authoring had not yet been needed directly. This release ports only the focused
authoring, schema, activation, and regression-test changes rather than the
branch's larger native-host experiment.

### v0.102.0 (September 2026)

**Headless Mesh Generation on HEC-RAS 6.0 – 7.0.1**

- `GeomMesh.generate()` now works with HEC-RAS 6.0 through 7.0.1, including
  the 6.7 betas. Previously it required 6.6 or later and failed on 6.0 – 6.5
  with a .NET "No method matches" error (#367).
- Adapt to the RasMapperLib signatures that changed between releases: the
  `MeshFV2D` constructor (minimum face-length ratio added in 6.6), the
  breakline-aware `RegenerateMeshPoints` seeding (4, 6, or 7 parameters), and
  `CreatePropertyTables`, so `GeomMesh.compute_property_tables()` also works on
  6.0 – 6.2. Before 6.6 the minimum face-length ratio step of the retry ladder
  is skipped because RasMapperLib has no such parameter.
- Find HEC-RAS 6.0 – 6.5 when no newer release is installed, and replace the
  misleading "HEC-RAS 6.6 not found" error.
- Meshes and seed points are identical to 6.6 on every release tested, natively
  on Windows and under Wine for 6.5, 6.6, and 7.0.1.

**Preprocessing on HEC-RAS 6.0 – 6.2**

- `RasPreprocess.preprocess_plan()` no longer reports success when HEC-RAS
  6.0 – 6.2 skip the geometry because a referenced land-cover, infiltration,
  or sediment file is missing. With those releases it now fails before launch
  and names each missing file. HEC-RAS 6.3 and later are unaffected (#367).

**Documentation**

- Add "HEC-RAS Version Support for Headless Mesh Generation" to the geometry
  API docs: supported releases, why each needs different calls, known
  limitations, version selection, and Wine notes (#367).

### v0.101.0 (September 2026)

**RasMapperLib Saves Under Wine**

- Fix `GeomMesh.generate()` under Wine, where it reported success but left the
  geometry HDF unchanged and wrote stale perimeter-cell centers as 2D seed
  points, so HEC-RAS preprocessing failed with "N point(s) detected outside
  the perimeter of the 2D-area" (#361, #363).
- Fix `RasGeometryCompute.audit_reach_lengths()` under Wine, where the
  recomputed reach lengths were discarded before they were saved (#363).
- Hold RASMapper's own `MultiLayerReloadSuppressor` over in-process geometry
  edits and saves through the new
  `ras_commander.dotnet.geometry_save.suppress_feature_table_reloads()`, so a
  feature layer's file watcher can no longer reload stale data from disk
  partway through `RASGeometry.Save()`. Results under Wine now match native
  Windows for HEC-RAS 6.6 and 7.0.1.

**Portable Steady Execution**

- Add the portable container steady execution stack: the v1 request and
  receipt contract, the in-container `execute_request` entry point with the
  Linux-to-Wine handoff, `RasPortableDocker`, `RasSlurm`, and a stdlib-only
  Slurm launcher (#358).
- Add an optional `stored_maps` block to portable steady requests. Stored
  steady-profile maps are generated only after the hydraulic results pass
  validation, and the outcome is recorded in the receipt (#360).
- Add `RasQualification.stage_project()`,
  `RasQualification.project_tree_fingerprint()`, and
  `validate_steady_results()` (#355).

**Steady Flow Files and Stored Maps**

- Keep every numeric field written to steady flow files within HEC-RAS's
  8-character fixed-width columns (#356).
- Treat `map_types` as exact for `RasMap.store_all_maps(mode="steady_profiles")`
  and allow `inundation_boundary` to be combined with it, so callers can turn
  off the inundation boundary polygon (#357).
- Recognize RASMapper's inundation boundary file names that carry the
  specified depth, and keep the map products that were produced when one is
  missing (#359).
- Run the stored-map helper from local storage when the project is on a
  network filesystem, avoiding the .NET remote-assembly load failure
  (`0x80131515`) (#362).

**USGS 3DEP Terrain**

- Select 3DEP projects by coverage, newest per area, instead of a single
  newest project, closing silent coverage gaps (#354).
- Add `Usgs3depAws.build_terrain_raster()` for one gap-free, project-CRS
  GeoTIFF with prioritized backfill and explicit vertical unit conversion,
  plus `plan_terrain_tiles()` and `prefetch_terrain_tiles()` for offline
  builds from a shared tile store (#354).
- Record per-tile download provenance, and locate 1 m tiles by their north
  edge (#354).

### v0.100.0 (September 2026)

**Text and HDF Geometry Extents**

- Build 1D model footprints directly from plain-text `XS GIS Cut Line`
  endpoints when compiled geometry HDF content is absent or incomplete.
- Prefer usable HDF geometry component by component, then fill missing 1D,
  2D, and storage-area geometry from the matching text geometry file.
- Enable the fallback by default across project extents, WGS84 bounds, and
  GeoJSON export. Set `fallback_to_plaintext=False` to require HDF-only
  results.
- Make `include_storage=True` include storage-area polygons from HDF through
  `HdfStruc.get_storage_area_polygons()` before considering text geometry.
- Preserve geometry provenance in 1D breakout catalogs and improve HDF
  cross-section handling for legacy schemas, multipart cut lines, explicit
  project context, and exact edge-line diagnostics.

**1D Breakout and Network Conflation**

- Add generic, extent-first `RasNetworkConflation` workflows with pluggable
  NWM Hydrofabric and NextGen adapters, candidate evidence, coverage metrics,
  and fail-closed topology handling.
- Add `RasBreakout1D` for independent one-reach steady-flow breakouts with
  separate buffered compute and one-cross-section-overlap raster domains.
- Add `RasBreakout1D.assemble_network_edge()` to combine adjacent source-model
  slices into one restationed project while preserving complete node blocks,
  source provenance, steady-flow changes, and endpoint boundaries.
- Resolve joins against source centerlines, reject intersecting cross-source
  cut lines, recompute main-channel lengths, and expose station and seam
  GeoDataFrames. Overbank reach lengths remain provisional until the caller
  selects complete regeneration or join-boundary-only recomputation.

**Exact 2D Geometry Preparation**

- Add guarded, atomic replacement of breaklines, refinement regions, and
  reference lines, plus exact geometry-text-to-HDF refresh through the
  explicitly initialized HEC-RAS version.
- Add `RasBreakout2D` for contained pure-2D breakout preparation with
  one-base-cell inward-containment checks, transactional restoration of
  non-target HDFs, association preservation, remeshing, and parent cut-face
  flux evidence. It prepares geometry but does not author boundary conditions
  or claim a hydraulic run.

**Cross-Section and Steady-Map Primitives**

- Add `RasCrossSections.get_points()` and `HdfXsec.get_xs_coords()` as the
  unified text/HDF cross-section point export, preserving native elevations,
  point order, Manning zones, banks, CRS, units, and source metadata.
- Add batched steady-profile mapping through
  `RasMap.store_all_maps(mode="steady_profiles")` and
  `RasProcess.store_maps_at_steady_profiles()`, using one temporary RASMapper
  transaction and one aggregate helper launch per plan.
- Add strict standalone-result unit metadata through
  `HdfBase.get_result_unit_metadata()` while retaining the project text marker
  as authoritative when a `.prj` file is available.

**Federal Model Sources and Archive Recovery**

- Add Alabama BLE watershed discovery, verified download, safe extraction,
  organization, portable inventory generation, and map-catalog integration.
- Add Alabama Flood Effective and Preliminary model adapters using the shared
  hardened ArcGIS, provenance, download, and extraction machinery;
  Preliminary sources remain explicitly non-regulatory.
- Add a bounded, forward-walking reader for eBFE ZIP deliveries that lack an
  End of Central Directory record, with CRC and size verification and explicit
  truncation reporting.
- Add the optional `ebfe` extra for Deflate64 ZIP method 9 on supported Python
  versions, plus a common renderer for engineer-facing eBFE audit and repair
  documents.

**Named eBFE Workflows and Example Library**

- Add source, organization, and deficiency-review workflows for the five-model
  San Gabriel suite, the 2,378-project Lower Colorado-Cummins steady 1D
  collection, and the four linked Double Mountain Fork Brazos 2D projects.
- Preserve delivered terrain and resource relationships, guard source-specific
  repairs with fingerprints, and distinguish static delivery closure,
  preprocessing readiness, and full hydraulic qualification.
- Publish exact API-derived project footprints in the Example Projects
  dashboard, including distinct San Gabriel and Double Mountain Fork model
  extents, project-specific evidence links, and guarded viewer links that are
  disabled when manifests are unavailable or invalid.
- Document the San Gabriel supplied-versus-rebuilt maximum-WSE COG comparison
  and validate its COG layout, CRS, masks, and pixel statistics without
  overstating source-terrain reproducibility.

**RASMapper and Legacy Execution Compatibility**

- Make `rasmap_df` parse outcomes observable through additive path, lifecycle,
  document-error, and field-error provenance while preserving its single-row
  summary and valid sibling layers after partial parsing.
- Use the verified project-first command layout for HEC-RAS 5.x, retain the
  explicit project/plan layout for 6.0+, and safely match project-only legacy
  launches during cancellation.
- Validate exact, release-specific Terms and Conditions sentinels, fail before
  compute when acceptance is definitively absent, and mutate acceptance state
  only through explicit `RasTcu.accept()` calls.

**Execution Evidence and Cleanup**

- Add `RasCmdr.inspect_execution_evidence()` for immutable, source-aware
  completion observations across HDF, stored-message, legacy-output, process,
  and Controller channels.
- Preserve unavailable, uninspected, failed, and explicit-false states rather
  than collapsing them into one boolean, and require exact `Complete Process`
  records instead of matching misleading substrings.
- Select the result family from the plan program version, fail closed on unsafe
  ambiguity or conflicting completion evidence, and keep mechanical completion
  separate from errors, freshness, runtime, and hydraulic acceptance.
- Add `RasCmdr.remove_plan_execution_artifacts()` and apply exact artifact
  ownership, cleanup, freshness, process-exit, and transactional publication
  rules across local, parallel, Controller, Docker, PsExec, and remote
  workflows. Opposing result formats are normalized around each owned run.
- Preserve mapped-drive launch paths, reject stale byte-identical results, and
  report structured preflight and execution details through `ComputeResult`.

**Matched Docker Compute**

- Add a matched Wine preprocessing and native Linux unsteady-compute workflow
  for HEC-RAS 6.5, 6.6, and 7.0.1.
- Add CPU selection, progress callbacks, validated resume behavior, sequential
  batch execution, host-side receipt verification, and a stable batch-summary
  schema.
- Include the scoped container build assets and operational guidance while
  excluding generated qualification payloads and duplicate release records.

### v0.99.2 (August 2026)

**Native Registered-Terrain Export**

- Add `RasTerrain.export_rasmapper_terrain()` for supervised, bounded RAS
  Mapper single-raster export with native source ordering, stitches, masks,
  optional vector modifications, semantic validation, and Windows/Wine support.
- Deprecate the row-sampled
  `RasTerrainMod.compute_modified_terrain_raster()` compatibility method in
  0.99.2. New callers should use the native registered-terrain export; removal
  is scheduled for 1.1.

**Lean Command-Line Compute Integration**

- Add `ras-commander[compute]` (and the `execution` alias) for command-line
  `RasCmdr.compute_plan()` workers without RasControl/COM or the geospatial and
  plotting dependency stack.
- Add `ras_commander.compute` as a narrow integration facade for project
  inventory, plan execution, compute-message parsing, and direct steady-result
  HDF extraction.
- Preserve normal compute semantics, including ras-commander-owned command
  construction and post-compute DataFrame refreshes; no reduced-refresh flags
  were added.
- Lazy-load optional top-level and HDF exports so the lean install remains
  import-safe, while retaining the historical public import names. The `full`
  extra restores the previous broad dependency surface.
- Keep lightweight map option types available from their historical modules,
  including their documented and pickle-visible module identities, without
  importing the optional geospatial stack into a compute-only worker.
- Correct HDF steady `max_depth` extraction to use `Maximum Depth Total`
  instead of `Hydraulic Depth Channel`, expose hydraulic depth separately, and
  join downstream channel reach length by full river/reach/station identity.
  Result arrays now fail closed when profile or cross-section dimensions do
  not align. Immutable HEC-RAS 6.0.0, 6.3.1, 6.4.1, 6.6, and 7.0 fixtures
  cover the available 6.x-to-7.0 steady-result schemas and sentinel
  normalization behavior.
- Qualify the narrow `RasCmdr.compute_plan()` path against exact HEC-RAS
  6.3.0.2 under Wine without RasControl/COM. The real 38-row ras2fim result CSV
  is byte-identical to the immutable Windows Controller baseline; the
  [qualification report](hec-ras-6302-wine-compute-plan-qualification.md)
  records identities, TCU handling, failed experiments, parity, and remaining
  downstream gates.
- Extend the lean `ras_commander.compute` facade for Linux-hosted unsteady
  workflows. `RasPreprocess.preprocess_plan()` now recognizes an owned
  `RasUnsteady.exe` plus complete `.tmp.hdf`/`.b##`/`.x##` artifacts when a
  release leaves `.bco` empty, records the exact stop or full-result-copy path,
  fails closed on timeout and legal-assent dialogs, and supervises only the
  launched process tree. `run_ras_geom_preprocess()` adds the matching bounded
  vendor geometry-preprocessor step with hashes, message parsing, and semantic
  HDF checks.

**C01-C06 Reliability Hardening**

- Preserve the existing precipitation-file line endings and surrounding bytes
  during targeted key replacement, and fail closed on malformed or ambiguous
  records instead of rewriting them speculatively.
- Fail closed when DSS boundary selection or timestamp representation is
  ambiguous rather than silently selecting a pathname or truncating time.
- Reject timezone-aware DSS writer inputs until the caller explicitly selects
  a model clock, expose explicit DSS6/DSS7 selection for grid creation, and use
  canonical `area_2d` / `bc_line_name` inventory columns while retaining the
  deprecated `sa_2d_name` / `bc_line` aliases for compatibility.
- Treat native HDF result datasets as read-only inputs when deriving missing
  depth products, and fail closed when required mesh topology or result
  alignment cannot be established.
- Require exact legacy completion evidence before exporting result products,
  exclude nonfinite result samples from raster interpolation, and omit
  unavailable hydrograph variables from exported Parquet metadata.
- Treat equivalent HRRR timestamps as equal across differing NumPy datetime
  storage resolutions, avoiding false cycle-plus-step validation failures.
- Allow initial-condition method mutation against an explicit unsteady-flow
  path without requiring unrelated global project initialization.
- Match 1D and 2D unsteady boundary blocks with exact semantic selectors and
  fail closed on ambiguous or index-mismatched DSS-link mutations.
- Restore the concise plan-geometry mutation summary at INFO while retaining
  file paths and refreshed DataFrames at DEBUG.
- Normalize relative components in mapped-drive fallbacks without converting
  HEC-RAS-compatible drive-letter paths to UNC paths.

### v0.99.1 (July 2026)

**Qualified Raster Processing on Linux/Wine**

- Add the `hecras-setup-linux-wine-ras2cng` skill, fail-closed host preflight,
  and notebook 511 for isolated headless deployments.
- Serialize RASMapper stored-map helpers under Wine and constrain the inherited
  helper process tree to one CPU, avoiding nondeterministic CLR access
  violations and non-returning mapper calls observed with unsafe CPU topology.
- Require one writable Wine prefix and project copy per task; scale concurrent
  work across isolated tasks rather than sharing an active prefix or HDF model.
- Qualify Muncie HEC-RAS 7.0.1 WSE, depth, and velocity rasters against the
  Windows golden with exact dimensions, georeferencing, and pixel hashes.
- Deprecate `mode="native"` in favor of `mode="configured"`; configured maps use
  the packaged RAS Mapper helper because `RasProcess.exe StoreAllMaps` does not
  preserve the required stored-map interpolation/render behavior.

**Raster Processing Performance**

- Add typed StoreMap performance policies, physical-memory and Windows-commit
  admission, terrain-based worker estimates, and child-scoped GDAL controls.
- Add memory-aware independent-map processing on Windows with profiling and
  self-contained performance decision reports.
- Preserve ordered serial handling for products that cannot safely be generated
  as independent map-helper processes.

**Raster BenefitArea Analysis**

- Add pair-aware `RasProcess.store_maps(..., benefit_area=...)` orchestration
  with Depth-only defaults and optional supplemental WSE outputs.
- Add categorical BenefitArea GeoTIFF generation from aligned pre/post Depth
  maps, configurable thresholds and boundaries, and optional four-connected
  component filtering.
- Add optional exact-cell-edge polygon outputs in GeoPackage, Shapefile,
  GeoJSON, and GeoParquet formats.
- Require one readable, projected, one-band single-TIFF terrain and provide
  actionable terrain creation, registration, and selection guidance.
- Verify both plan HDFs and populated 2D flow areas reference that same terrain
  before mapping; RAS Mapper terrain visibility does not override plan-HDF
  terrain associations.

**HRRR Forecast Timing**

- `PrecipHrrr.get_basin_average()` now returns source-derived `valid_time` and
  fractional `forecast_lead_hours` columns for hourly and subhourly products.
- The legacy 1-based `forecast_hour` record index remains available for
  compatibility but is no longer described as elapsed forecast time.
- Basin-average INFO logging now reports record count, valid-time spacing, and
  the lead-hour range instead of treating every record as one hour.

### v0.96.2 (May 2026)

**Precipitation & Dependencies**

- Bump hms-commander dependency to >=0.3.1 (probability_column support)
- Add ABM textbook validation notebook (723) with hms-commander integration
- Fix precipitation hydrograph incremental-depth formatting in RasUnsteady
- Fix Plan 07 uniform precipitation and mode conflict in 722 notebook

### v0.96.0

**1D Geometry Authoring Sprint**

- **GeomCrossSection**: Robust 1D cross-section builder API with terrain sampling, NLCD Manning's n, Douglas-Peucker reduction
- **GeomBridge**: Bridge geometry authoring API (deck, piers, abutments, approach sections)
- **GeomLevee**: Levee read/write API with station-only parsing support
- **GeomCrossSection**: Blocked obstruction read/write exposed as public API
- **HdfStorageArea**: Volume-elevation curve extraction from HDF
- **ManningsFromLandCover**: NLCD-to-Manning's n assignment with block limit enforcement
- **Breaking**: `CoastalBoundary` moved to `ras_commander.boundaries` subpackage

### v0.95.0

**Mesh Generation & Land Classification**

- **GeomMesh**: Headless 2D mesh generation via RasMapperLib.dll (text-first architecture, auto GDAL, cell size sync)
- **GeomStorage**: 2D flow area perimeter writer with breakline spacing, refinement regions, property tables
- **RasPermutation**: Parameter sweep framework with Cartesian product generation
- **HdfResultsQuery**: Spatial query class for 2D mesh results
- **HdfLandCover**: `set_landcover_mannings_n()` for native RASMapper sidecar updates (`set_landcover_raster_map()` remains a compatibility alias)
- **RasCalibrate**: Calibration framework with grid search and scipy optimize
- **GeomReferenceFeatures**: Reference lines and points for 2D calibration
- Cloud-native export notebooks (960–962) with GeoParquet and COG workflows
- eBFE delivery validation notebook suite (950–957)

### v0.94.0

**HEC-RAS 7.0 Support**

- Default HEC-RAS version bumped from 6.6 to 7.0 across repo
- Release tag mapping for HEC-RAS 7.0 in RasExamples
- Blank HEC-RAS 7.0 template project scaffold
- `RasUtils.discover_ras_versions()` with Registry and Wine/Linux support
- `UsgsObservations` and `UsgsDrainageAreaComparison` study primitives
- STOFS-3D coastal boundary notebook rewrite (917)

### v0.93.0

**Notebook QAQC & Stability**

- QAQC all 69 example notebooks — 59 pass, 15 issues fixed
- Filter non-XS types in HTAB/check consumers
- GeomStorage Round 2 QAQC (precision overflow, control chars)
- `RasProcess`: Honor configured Wine executable for Linux builds
- Papermill as primary notebook execution engine

### v0.92.0

**Plan Management & Map Storage**

- `RasPlan.delete()` and `renumber()` for plans, geometries, and flow files
- `RasMap.add_calculated_layer()` for WSE comparison layers
- `compute_modified_terrain_raster()` for full-resolution terrain mod export
- `RasCmdr`: Scope parallel consolidation to plan outputs
- `RasProcess`: Adaptive render mode for cross-version compatibility
- `GeomStorage`: 2D subgrid sampling options API (spatially varied Manning's on faces, composite classification)
- Fix `RasCheck` HTAB defaults and surface notebook errors

### v0.91.0

**Terrain Modifications & GUI Automation**

- `RasTerrainModWriter`: Line and polygon terrain modification HDF/rasmap writing (high ground, channel, fill surface, detention pond)
- `RasTerrainMod`: Terrain profile and volume comparison via RasMapperLib.dll
- `HdfInfiltration`: Final Manning's n and infiltration APIs
- `HdfLandCover`: Land-cover sidecar extraction
- GUI floodplain mapping automation with HDF completion detection
- `RasPreprocess`: Public API for Linux preprocessing (Phase 1)

### v0.90.1

**Linux Execution & Agent Integration**

- `RasCmdr.compute_plan_linux()` for native Linux HEC-RAS execution
- `RasProcess`: Output path parameter and `store_all_maps()` method
- SA polygon extraction from geometry HDF
- GUI subpackage extracted from monolithic `RasGuiAutomation`
- Linux execution notebook (510)

### v0.89.0–v0.89.2

**DSS ReLink, File Operations, XYZ Extraction**

- DSS ReLink primitives for HMS-RAS boundary matching
- `RasPlan.delete()` and `renumber()` operations for all file types
- `RasProcess`: Linux/Wine support for headless map generation
- `GeomCrossSection.get_xs_coords()` for plain-text XYZ extraction
- Description read/write for all HEC-RAS file types
- `results_df` returned from compute functions
- Dynamic section-end search (replace fixed `DEFAULT_SEARCH_RANGE`)

### v0.88.0–v0.88.6

**Precipitation, Callbacks, USGS, Remote**

- `StormGenerator`: Static API for Atlas 14 DDF download and hyetograph generation
- `Atlas14Storm`, `FrequencyStorm`, `ScsTypeStorm`: HMS-equivalent precipitation methods
- `stream_callback` parameter for real-time execution monitoring
- `ConsoleCallback`, `FileLoggerCallback`, `ProgressBarCallback`, `SynchronizedCallback`
- USGS gauge integration (spatial discovery, data retrieval, gauge matching, BC generation)
- `RasModPuls`: Modified Puls routing extraction from 2D simulations
- `HdfChannelCapacity`: 1D channel capacity analysis (multi-AEP)
- `AbmHyetographGrid`: ABM hyetograph grid generation
- `results_df` fallback for HEC-RAS pre-6.4 versions
- Remote execution subpackage reorganization

### v0.85.0

**Remote Execution Subpackage**

- Refactored `ras_commander.remote` from module to subpackage
- Added `DockerWorker` for container-based execution
- Lazy loading for remote dependencies
- Optional extras: `[remote-ssh]`, `[remote-aws]`, `[remote-all]`

### Earlier Versions

See [GitHub Releases](https://github.com/gpt-cmdr/ras-commander/releases) for complete history.

## Upgrade Guide

### From v0.95 to v0.96+

**Breaking Changes**:

- `CoastalBoundary` moved from `ras_commander` to `ras_commander.boundaries`

**Migration**:
```python
# Old
from ras_commander import CoastalBoundary

# New
from ras_commander.boundaries import CoastalBoundary
```

**New Features**:
- Import `GeomCrossSection` for the cross-section builder
- Import `GeomBridge` for bridge authoring
- Import `HdfStorageArea` for volume-elevation curves
- Import `ManningsFromLandCover` for NLCD Manning's n

### From v0.93 to v0.94+

**Breaking Changes**: None

**New Features**:
- Default version is now HEC-RAS 7.0 (pass `"6.6"` explicitly for older versions)
- Import `RasPermutation` for parameter sweeps
- Import `RasCalibrate` for calibration workflows
- Import `HdfResultsQuery` for spatial queries

### From v0.90 to v0.91+

**Breaking Changes**: None

**New Features**:
- Import `RasTerrainModWriter` for terrain modifications
- Import `RasTerrainMod` for terrain comparison (Windows only)
- Import `HdfInfiltration`, `HdfLandCover` for land-cover APIs

### From v0.88 to v0.89+

**Breaking Changes**: None

**New Features**:
- `StormGenerator` instance API deprecated (use static methods with `ddf_data=`)
- Import `RasModPuls` for Modified Puls routing
- `stream_callback` parameter on all compute methods

## Deprecation Policy

- Deprecated features marked with warnings
- Removed after two minor versions
- Breaking changes only in major versions
