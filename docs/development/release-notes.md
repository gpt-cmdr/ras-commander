# Release Notes

## Version History

### v0.99.1 (Current published release — July 2026)

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
- **HdfLandCover**: `set_landcover_raster_map()` for sidecar HDF writes
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
