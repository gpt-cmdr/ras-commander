# Gridded Precipitation Version and Format Support Plan

## Objective

Establish evidence-based gridded-precipitation support across HEC-RAS 5.x,
6.x, and 7.x, then use that support to qualify every ras-commander workflow
that authors or transforms AORC, MRMS, design-storm, or forecast rainfall.

The implementation must never silently run with zero or incorrectly scaled
rainfall. Unsupported native formats must produce an actionable error or use a
documented, validated translation path such as an HEC-DSS grid.

## Current Baseline: Issue #371

### PR #376 review follow-up (2026-09-25)

- API audit found and fixed GDAL GeoTransform ordering and beta qualification
  inheritance. An independent rasterio reopen verifies transform/extent/CRS/values.
- AORC storm-plan creation now preserves the first hourly amount explicitly;
  a real RasExamples clone/authoring regression verifies the resulting HDF.
- Guide examples now use implemented APIs. Notebook 722 redirects to 727;
  727/900/901/914/916 add precompute checks; 924 corrects its interval-depth
  figure label; 915/917/926 describe their actual scope. Changed code-cell
  outputs are cleared until reexecution rather than presented as fresh evidence.
- Notebook 729 reran successfully on Windows 6.6 after the transform fix.
- Native Wine DSS 6.6 now passes on CLB07: removing the launcher's combined
  disabling `WINEDLLOVERRIDES='mscoree,mshtml='` setting resolved the timeout.
  Final rainfall and WSE summary metrics match Windows 6.6. The experiment
  isolated that combined override, not individual DLL entries.
- Still open: full live NOAA product reruns for changed notebooks; 728's
  extended-DSS model qualification; a WPC model run beyond catalog/plot;
  remaining native NetCDF/GRIB temporal matrix and blocked 6.0/6.4.1/6.5 hosts.
  Do not infer all-format/all-version qualification from the representative runs.

The `fix/371-native-gridded-precip-hdf` branch provides the first reliable
baseline:

- authors HEC-RAS's native `Imported Raster Data` HDF payload;
- distinguishes rate, interval-amount, and cumulative source semantics;
- handles source units, the first timestep duration, precipitation ratio, grid
  orientation, and native chunking;
- fails before editing the unsteady text when the source is invalid;
- validates that preprocessing materialized solver-facing `Values` and
  `Timestamp` datasets in the temporary plan HDF;
- preserves mapped-drive paths for gridded DSS configuration;
- prevents AORC storm creation from leaving an orphaned unsteady clone when a
  NetCDF is missing; and
- demonstrates authoring, precompute validation, final-plan-HDF validation,
  and visual review in notebook 924.

This PR is a correctness fix, not a claim that every HEC-RAS version and input
format is already supported.

## Governing Validation Model

Every supported route must pass all applicable stages:

1. **Source validation** — file is readable, variable/record exists, CRS,
   orientation, units, nodata, interval meaning, timestamps, and grid spacing
   are explicit.
2. **Authoring validation** — `.u##` text and `.u##.hdf` contain the expected
   version-specific configuration and native source payload.
3. **Precompute validation** — HEC-RAS creates fresh `.tmp.hdf`, `.b##`, and
   `.x##` artifacts; the temporary HDF contains nonempty, aligned shallow
   precipitation `Values` and `Timestamp` datasets.
4. **Runtime-message review** — parse HEC-RAS messages for rainfall, raster,
   DSS, projection, temporal-coverage, and fallback warnings. Automated checks
   supplement rather than replace manual review.
5. **Postcompute validation** — completed plan HDF contains positive and
   quantitatively plausible precipitation-rate/cumulative-depth values and a
   corresponding hydraulic response.
6. **Visual review** — inspect at least one rainfall figure and one hydraulic
   result figure for orientation, extent, timing, magnitude, and obvious
   discontinuities.

## Phase 1 — Historical Capability Research

Build an authoritative version-by-version matrix before adding compatibility
guards.

### Version inventory

Inventory official releases and locally available executables, including at
least:

- HEC-RAS 5.0, 5.0.1, 5.0.3, 5.0.4, 5.0.5, 5.0.6, and 5.0.7;
- HEC-RAS 6.0, 6.1, 6.2, 6.3, 6.3.1, 6.4-series releases, 6.5, and 6.6;
- the installed 6.7 Beta 5 as historical evidence, kept distinct from stable
  support; and
- HEC-RAS 7.0, 7.0.1, and any later public 7.x release available during the
  audit.

Identify missing public patch releases and acquire/install them only through
official or already-authorized CLB sources.

### Evidence order

For each release, use:

1. official release notes and resolved/known-issues pages;
2. the matching 2D, Mapper, and user manuals;
3. official example projects and training material;
4. controlled native experiments; and
5. focused decompilation only when documentation and observable behavior do
   not resolve the format, HDF schema, or preprocessing decision path.

Decompiler work must record executable/assembly version, SHA-256, relevant
type and method names, and a concise interoperability finding. Do not copy
large vendor source listings into the repository.

### Research questions

For every version, determine:

- whether meteorological precipitation and 2D rain-on-grid are available;
- whether gridded HEC-DSS is accepted and which DSS generation/compression
  conventions are required;
- whether GDAL raster import is available;
- exactly which NetCDF, GRIB/GRIB2, GeoTIFF, or other raster formats the GUI
  and preprocessor accept;
- whether input is referenced directly, copied into `.u##.hdf`, or converted
  into another intermediate representation;
- the native HDF group, dataset, attribute, chunking, and timestamp schemas;
- whether `First Timestep Duration`, units conversion, interpolation, and
  precipitation ratio are supported and how defaults changed;
- known defects affecting import, preprocessing, spatial interpolation,
  timestamp coverage, units, or rainfall output; and
- whether Windows, Wine, or both can author, preprocess, and compute the route.

### Research deliverables

- `docs/development/gridded-precipitation-version-matrix.md`
- machine-readable capability data used by tests, without speculative entries;
- schema snapshots and small hashes/metadata reports under a dedicated
  research artifact folder;
- a bibliography of official sources; and
- an explicit list of unresolved findings that require decompilation or native
  experiments.

## Phase 2 — Controlled Cross-Version Qualification

Use a compact RasExamples 2D rain-on-grid project and a deterministic synthetic
storm so every version receives equivalent forcing.

### Test payloads

Prepare small fixtures with known values for each confirmed format:

- regular projected NetCDF with rate values;
- regular projected NetCDF with interval-amount values;
- GRIB/GRIB2 equivalent where supported;
- GeoTIFF time series through an explicit ras-commander-to-NetCDF/HDF adapter;
- gridded HEC-DSS with explicit pathname and metadata; and
- the native imported-raster HDF payload used by issue #371.

Include non-hourly timesteps, a nonzero first band, asymmetric spatial values,
and both millimeter and inch cases so temporal, orientation, and unit mistakes
cannot accidentally pass.

### Per-version protocol

For each executable/format pair:

1. clone an untouched fixture;
2. record executable path, product version, and SHA-256;
3. author the precipitation source through the public ras-commander API;
4. run preprocessing through the library-owned workflow;
5. inspect the temporary plan HDF and runtime messages;
6. run the smallest meaningful hydraulic compute;
7. inspect final per-cell rainfall and hydraulic response;
8. compare totals, timing, orientation, and spatial classes with the expected
   payload; and
9. retain a compact JSON/Markdown qualification record, not the large model
   output.

Run 5.x tests on Windows unless evidence proves a supported Wine route. Run the
currently supported Wine qualification on CLB07, beginning with HEC-RAS 6.6,
and expand Wine claims only after direct evidence.

### Status vocabulary

Each matrix entry must be one of:

- **Supported and qualified**
- **Supported with translation**
- **Supported with documented limitation**
- **Vendor defect / avoid**
- **Unsupported**
- **Not yet tested**

Absence of a failure is not sufficient for qualification; rainfall must appear
in solver-facing and final outputs with the expected magnitude and timing.

## Phase 3 — Version Guards and Format Routing

Implement guards only after the matrix supplies evidence.

### Capability model

Add one central capability registry keyed by normalized HEC-RAS version. It
should describe supported precipitation modes and formats, required metadata,
known vendor defects, and available translation routes. Avoid scattering
version comparisons throughout source adapters.

### Public API direction

Preserve these existing APIs:

- `RasUnsteady.set_gridded_precipitation()` for native raster authoring;
- `RasUnsteady.configure_gridded_dss_precipitation()` for existing DSS grids;
- `RasPrecipHdf` for explicit native HDF payload authoring; and
- `RasPreprocess.preprocess_plan()` for precompute validation.

Evaluate a higher-level API that accepts source data plus `format="auto"` and
`strategy="auto" | "native-raster" | "dss"`. Automatic routing must report
the selected route and its reason. It must never silently translate data or
change units/timestep meaning.

### Guard behavior

- Raise before model edits when a requested format is unsupported.
- When a validated DSS translation is available, recommend it explicitly or
  select it only under an explicit/clearly documented automatic strategy.
- Identify known vendor-bug versions and provide actionable upgrade,
  downgrade, or translation guidance.
- Keep warnings for risky-but-supported configurations distinct from errors.
- Include the detected version, requested format, and chosen route in logs and
  result objects.

## Phase 4 — Complete Supported Format Coverage

Implement and test every gridded precipitation format confirmed by the matrix.
Expected format families to investigate include:

- HEC-DSS gridded precipitation;
- GDAL-backed NetCDF;
- GRIB and GRIB2;
- GeoTIFF as a first-class ras-commander ingestion format, without claiming
  undocumented native HEC-RAS support, plus other confirmed GDAL rasters; and
- HEC-RAS's internal imported-raster HDF representation.

Do not advertise a generic GDAL format merely because GDAL itself can read it;
HEC-RAS preprocessing must be proven to accept and correctly materialize it.

Translation work should converge on a canonical in-memory precipitation cube:
values, times, CRS, x/y coordinates, nodata, units, and value semantics. Format
adapters then serialize that cube without duplicating accumulation logic.

## Phase 5 — Source/Product Workflows

After version and format routing is qualified, repair and expand all existing
gridded-input workflows.

### Existing workflows to requalify

- AORC historical precipitation and storm catalogs (`900`, `901`, `914`);
- MRMS QPE (`917`, `924`);
- HRRR forecast precipitation (`916`);
- WPC QPF forecast precipitation (`915`/`926`, after reconciling their current
  intended roles);
- Atlas 14 spatial/design storms (`722`, `727`); and
- existing NEXRAD/gridded-DSS examples and fixtures.

### Readily available major inputs to evaluate

- NOAA AORC;
- NOAA MRMS QPE;
- NOAA HRRR precipitation forecasts;
- NOAA/WPC QPF;
- NOAA Atlas 14 gridded frequency estimates;
- legacy NEXRAD/Stage IV products where they remain operationally relevant;
- HEC-Vortex and HEC-MetVue outputs; and
- additional federal products only when access is stable, metadata is
  sufficient, and a maintained translation path is realistic.

For each product, document native units, interval meaning, timestamp convention,
CRS/grid orientation, nodata behavior, data latency, and the preferred HEC-RAS
route by version.

## Phase 6 — Notebook and Regression Matrix

Every canonical workflow notebook must:

- use explicit `units` and `value_type`;
- set `first_timestep_hours` only from documented source semantics;
- make precipitation ratio intentional;
- run or explicitly validate preprocessing;
- inspect temporary plan-HDF rainfall datasets;
- inspect final plan-HDF rainfall and hydraulic response;
- display rainfall and hydraulic figures; and
- remind users to review HEC-RAS runtime messages and maps manually.

Keep committed notebooks reasonably sized. Heavy executions may retain their
full artifact notebook outside Git, while the repository keeps a cleaned
notebook plus contract tests and a compact qualification record.

## Proposed PR Sequence

1. **Issue #371 correctness PR** — native writer, preprocessing readiness,
   omitted safeguards, focused tests, notebook 924 contract, and present
   Windows/Wine evidence.
2. **Version evidence PR** — official-source research, capability matrix,
   reproducible harness, and no speculative runtime guards.
3. **Version guard/routing PR** — central registry, actionable errors, result
   provenance, and validated selection logic.
4. **Format adapters PR(s)** — DSS and each confirmed native raster family,
   split when reviewability requires it.
5. **Product workflow PR(s)** — AORC, MRMS, forecast, and design-storm adapters
   with small deterministic tests.
6. **Notebook qualification PR** — re-executed canonical examples and compact
   version/format evidence.

## Completion Criteria

- Every public 5.x–7.x version is researched and every available version is
  directly tested or explicitly marked unavailable/not yet tested.
- Every advertised input format has authoring, precompute, runtime-message,
  postcompute, and visual evidence on each supported version family.
- Unsupported combinations fail before editing a project or are routed through
  an explicitly validated translation.
- AORC, MRMS, HRRR, WPC, Atlas 14, and gridded-DSS workflows use the common
  semantics and routing layer.
- Example notebooks and automated tests agree with the capability matrix.
- Documentation retains the requirement for manual review of runtime messages,
  rainfall maps, and hydraulic response.
