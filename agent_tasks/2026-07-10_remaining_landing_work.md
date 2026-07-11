# Remaining Work To Land On Main

Date: 2026-07-10

Status: **Precipitation replay completed.** PR #275 merged the selective DSS,
MRMS, stored-map, and notebook payload on 2026-07-11. The subsequent HRRR
temporal-contract correction described below was validated from current
`main`; the remaining items are independent backlogs.

## Goal

Preserve useful unlanded work without replaying stale feature branches over
current `main`. Every candidate must be reassessed against the APIs, notebooks,
and fixes that have already landed, then delivered through a focused branch and
independently validated.

## Main State At HRRR Follow-Up Start

- `origin/main` is `f814a9e0`, including PR #275.
- There are no open pull requests.
- PR #260 was closed and its approved slices landed through PRs #262-#273.
- PR #251 was superseded by PR #274.
- The notebook 710 and 711 follow-ups were closed by PRs #272 and #271.

## Completed Precipitation Replay Tranche

Selective replay of `origin/feature/dss-container-qpkit-notebooks`:

- audit the six branch commits against current `main`;
- port only still-needed `RasProcess` and `PrecipMrms` fixes with focused tests;
- separate notebook input-cell improvements from stored-output churn in
  notebooks 916 and 917;
- reconcile the workflows with the precipitation and asynchronous HDF fixes
  landed in PR #274;
- add a uniquely numbered WPC QPF-to-DSS example as notebook 926;
- execute notebooks 916, 917, and 926 and require independent notebook review
  before publication; and
- prepare a focused PR rather than merging the source branch wholesale.

### Branch Audit Findings

The six branch commits must be ported manually. No commit is safe to
cherry-pick wholesale:

- `985d6ca7` addresses a real stored-map move failure, but its extended-path
  conversion is invalid for UNC paths and must preserve newer `main` behavior
  around logging and `PostProcessing.hdf`.
- `fbbbd7fa` and `ab11a3ae` add useful common-grid reconciliation and early
  frame limiting, but they treat each raster as a separate timestep. They do
  not mosaic multiple terrain rasters produced for the same timestep.
- The executed New Orleans run proves that grouped-tile support is required:
  of 361 timesteps, 39 produced one depth raster, 120 produced two, and 202
  produced three. Notebook 917 selected only `maps["depth"][0]`, omitting valid
  hydraulic results from the remaining terrain tiles.
- The branch's new `915_wpc_qpf_precipitation_forecast.ipynb` conflicts with
  the existing notebook 915 and does not write DSS grids. Its purported writer
  cells only build and print pathname strings.
- Historical outputs from `3fdee719` and `6ed11d02` predate the current logging
  and precipitation fixes and must not be replayed.

### qpkit Verification

- Upstream qpkit merged the WPC QPF writer as commit `64455cb9` and tag
  `v0.1.0`.
- The focused QPF writer suite passes (`7 passed`), including a real DSS
  round-trip test.
- The broader upstream qpkit API/DSS/model suite currently reports `14 failed,
  30 passed`; the failures are concentrated in stale HRRR/QPE expectations
  that no longer match the implementation. Do not represent the full release
  as clean or silently change the existing HRRR/MRMS notebook pin without live
  validation.
- Any qpkit notebook section must suppress qpkit's per-file INFO chatter and
  print a concise download/write/catalog summary instead.

### Approved Implementation Scope

The user approved this full scope, including notebook 926, on 2026-07-10:

1. Harden `RasProcess.store_maps()` move paths for drive and UNC locations.
2. Add a public `PrecipMrms` stored-map loader that mosaics all terrain tiles
   per timestep, reconciles frames, and limits frames before raster reads.
3. Add focused path, mosaic, resolution, CRS, and frame-limit tests.
4. Update notebook 917 to retain every terrain tile and use `RasDss` for DSS
   catalog verification.
5. Add live-verified optional qpkit sections to notebooks 916 and 917 without
   replaying historical outputs.
6. Rewrite the WPC workflow as a real, uniquely numbered notebook 926 using
   qpkit `v0.1.0`.

### Validation Record

- Focused `RasProcess`, `PrecipMrms`, and HRRR regression suite: 44 passed,
  with two known environment/test-fixture warnings.
- Final stored-map regression rerun: 30 passed with `MPLBACKEND=Agg`. The
  default Tk backend in the local UV Python is incomplete, and the successful
  run still emits the known netCDF/numpy binary warning plus a post-exit
  Windows `0xc0000139` diagnostic; pytest itself exits 0.
- Notebook 916: 13/13 code cells executed; independent review PASS.
- Notebook 926: 5/5 code cells executed; independent review PASS.
- Notebook 917: 8/8 code cells executed from source in 4,040.7 seconds;
  independent review PASS. The executed notebook, terminal log, and six MP4s
  are under `H:/Symphony/ras-commander/PR-DSS-QPKIT-PRECIP/`.
- Final focused MRMS suite: 19 passed with one known netCDF/numpy binary
  compatibility warning; pytest exited 0 before the known Windows post-exit
  diagnostic.
- Focused sequential-precipitation and DSS-grid suite: 56 passed with four
  pre-existing unregistered `slow` marker warnings.
- Final combined `RasProcess`, MRMS, sequential-precipitation, and DSS-grid
  regression run: 87 passed with six known environment/fixture warnings;
  pytest exited 0.

### Notebook 917 Corrective Record

- The first complete rerun was rejected even though the notebook process
  exited 0. A July 2026 regression serialized precipitation as interleaved
  `(hour, depth)` fields while HEC-RAS expects exactly one incremental depth
  per `Interval=` step. HEC-RAS therefore consumed hour values as rainfall,
  producing hydraulically invalid peak rates and cumulative depths.
- `RasUnsteady`, `RasPrj`, and the USGS boundary replacement parser now read
  and write the native sequential-depth format. The final HDF forcing checks
  match the rounded serialized inputs exactly: Davis `0.22 in/hr` and
  `1.73 in`; New Orleans `0.95 in/hr` and `4.10 in`. Both no-rain baselines
  remain zero.
- `RasDss.read_grid()` now provides exact spatial-grid value and metadata
  readback. The qpkit verification catalog contains 37 records and its
  deterministic peak-hour record reads row 3, column 5 as
  `6.900000095367432 mm`, `PER-CUM`, Albers, with the complete CRS, cell size,
  shape, origin, lower-left cell, missing-value count, and nodata value stored
  in notebook output.
- Hydraulic comparison cells are selected by maximum concurrent
  event-minus-baseline depth. Davis cell 600 increases `2.568577 ft`; New
  Orleans cell 17519 increases `19.675402 ft`. Pump flow and WSE comparisons
  provide additional response evidence.
- The final raster audit produced 30 consolidated frames per case. Davis
  preserved its native `28.845-ft` cells with two whole-timestamp HDF fills;
  New Orleans consolidated 76 retained multi-terrain tiles at `10 ft` with
  three whole-timestamp HDF fills. Every final frame matched HDF wetness.
- The independent review rated model context Thorough, hydraulic relevancy
  Pass, visual quality Acceptable, and demonstration completeness Complete.
  Its overall verdict was PASS with no required revisions.

### Notebook 917 Terrain And Output Policy

- Terrain discovery is limited to the terrain HDF layers registered in the
  project's `.rasmap`; unrelated TIFFs in the Terrain folder are excluded.
- The dominant active terrain is selected by valid-data coverage, not by the
  rectangular raster extent. Davis therefore preserves its native
  28.845245-ft cells.
- Multi-terrain New Orleans frames are written broad/coarse first and then
  overwritten by finer/local valid pixels. Its dominant source is 3.28 ft, so
  the approved sub-10-ft policy consolidates the selected frames at 10 ft.
- At most 30 representative frames are selected across each full consecutive
  five-minute event window, including both endpoints. Every selected timestamp
  is written as one consolidated GeoTIFF.
- HDF gap fills use the same case-specific consolidation resolution. Every
  final GeoTIFF is reopened and checked for CRS, transform, resolution,
  dimensions, nodata, and timestamp metadata.
- Real-file smoke tests passed for both projects before execution. The final
  source-matching execution and independent artifact review also passed.

## HRRR Temporal-Contract Follow-Up

`PrecipHrrr.get_basin_average()` previously labeled its sequential row index
as `forecast_hour` and logged every record as one hour. That was incorrect for
HRRR `wrfsubhf`, which returned four 15-minute records per forecast hour in the
live notebook validation.

The focused correction:

- preserves `forecast_hour` as a documented legacy 1-based record index;
- adds source-derived `valid_time` and fractional `forecast_lead_hours`;
- requires one coherent forecast cycle, strictly increasing leads, unique
  chronological valid times, and agreement between `time + step` and
  `valid_time`; and
- logs record count, valid-time spacing, and lead range instead of calling the
  record count hours.

Validation evidence:

- focused HRRR basin-average suite: 10 passed;
- combined HRRR, MRMS, and unsteady precipitation suite: 52 passed with the
  established headless Matplotlib backend and one pre-existing `slow` marker
  warning;
- notebook 916: 13/13 code cells executed from source in 1,505.56 seconds with
  no errors or warning output and one embedded two-panel figure;
- live extraction: 72 quarter-hour records covering lead hours 0.25-18.00,
  with 0.047 inches total and a 0.006-inch peak 15-minute depth;
- qpkit verification: seven GRIB2 files downloaded, six hourly `PER-CUM` grids
  written and cataloged at 3,000 m resolution with exact pathname agreement;
  and
- independent notebook review: PASS (model context Partial, hydraulic
  relevancy Pass for the forcing-data scope, visual quality Acceptable, and
  demonstration completeness Complete).

Notebook 916 intentionally remains an input-data/API example. Its rectangular
averaging geometry is not a delineated watershed, and it does not claim a
HEC-RAS hydraulic response calculation.

## Remaining Independent Backlogs

- `2026-04-29_ebfe_validation_matrix_completion_plan.md`: real eBFE validation
  and model-delivery work; substantial and independent of precipitation.
- `notebook_inventory_audit_2026-06-26.md`: duplicate `219` numbering and
  template-like 900-series examples remain open.
- `2026-06-22_docs_navigability_audit.md`: residual public-doc navigation,
  consistency, and landing-page work requires a fresh verification pass.
- `origin/claude/joss-paper-ras-commander-KXMbR`: unlanded JOSS paper work;
  orthogonal to the active precipitation tranche and stale enough to require a
  dedicated reassessment.
- `origin/feature/711-rasremote-mannings-sensitivity`: optional advanced remote
  and Sabinal-specific 711 concepts only. Do not merge the branch wholesale;
  the public notebook refresh already landed in PR #271.

## Branch Triage Rules

- Treat merged PR heads as cleanup candidates, not sources of new work.
- Treat closed superseded branches as historical evidence unless an exact hunk
  is proven absent from current `main`.
- Compare notebook input cells independently from output and metadata changes.
- Rerun changed notebooks from a clean environment and preserve faithful
  outputs; do not rewrite outputs in the docs build.
- Keep generated model data and temporary execution artifacts untracked.
