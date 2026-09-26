# Gridded Precipitation Version and Format Matrix

This report separates vendor documentation, schema evidence, native Windows
execution, and Wine execution. A process exit by itself is not a qualification:
the precipitation input must materialize, HEC-RAS messages must identify the
precipitation stage, final cell rainfall must be nonzero and quantitatively
consistent, and the hydraulic result must be nonempty.

The machine-readable companion is
[`gridded-precipitation-version-matrix.json`](gridded-precipitation-version-matrix.json).
The repeatable native harness is
[`scripts/qualification/gridded_precipitation_matrix.py`](https://github.com/gpt-cmdr/ras-commander/blob/main/scripts/qualification/gridded_precipitation_matrix.py).

## Conclusions

- Global spatial/time-varying meteorology and rain-on-grid begin in HEC-RAS
  6.0. HEC-RAS 5.x supports an older uniform precipitation-per-area mechanism,
  but not this gridded meteorology feature.
- HEC documents two native source families from 6.0 onward: gridded HEC-DSS
  and GDAL raster input limited to NetCDF or GRIB. GeoTIFF support elsewhere in
  RAS Mapper is not evidence for a native precipitation time-series route;
  ras-commander supports GeoTIFF by normalizing it to durable NetCDF plus the
  equivalent native HDF payload.
- The official Bald Eagle gridded-DSS example executed end to end on Windows
  6.3, 6.3.1, 6.6, 7.0, and 7.0.1. The installed 6.7 Beta 5 also executed, but
  remains prerelease historical evidence rather than a stable support target.
- HEC-RAS 6.1 and 6.2 correctly preprocess and solve the same rain case after a
  qualification-only replacement for the removed Windows `wmic CPU get`
  command. Their unmodified failures are host compatibility failures, not
  precipitation failures.
- The exact 6.3 and 6.3.1 releases retain ras-commander's existing
  process-local WMIC compatibility path from earlier host evidence. The DSS
  qualification runs summarized here did not need that fallback, so that fact
  is recorded separately rather than presented as evidence that the safeguard
  can be removed or generalized to hypothetical patch releases.
- For HEC-RAS 6.0, `RasTcu.accept()` and `RasTcu.status()` both report the
  exact installed runtime accepted, without GUI interaction, but launching the
  same executable still raises the vendor TCU modal. This API-registry/runtime
  disagreement blocks execution before precipitation preprocessing.
- The CLB07/Wine 6.4.1 cache has two independent profile blockers: its native,
  correctly registered prefix has no accepted donor available to
  `RasTcu.accept()`, while a mixed accepted profile reaches 6.4.1 but cannot
  create its RAS Mapper ActiveX component. Neither result is precipitation
  evidence.
- HEC-RAS 6.5 exits through an HEC-owned VB dialog titled `Error` whose body is
  `Unexpected error; quitting` on this Windows host, including from a clean
  short-path stage. The exact executable path and hash were confirmed. That is
  a startup/install/runtime failure and must not be described as a
  precipitation defect.
- A feature-snapshot GeoTIFF translation route executed end to end on
  CLB07/Wine 11 with HEC-RAS 6.6: native preprocessing materialized the exact
  interval values, the solver finished, cumulative rainfall was nonzero, and
  the hydraulic response was nonempty. This qualifies the translated route,
  not GeoTIFF as a vendor-native meteorology source.
- The prior HEC-RAS 6.6 Wine DSS timeout was a launcher environment defect.
  Removing `WINEDLLOVERRIDES='mscoree,mshtml='` allowed preprocessing in 13.3
  seconds and verified compute completion, with final rainfall and WSE matching
  Windows 6.6 exactly. Short-path and fresh-profile controls retaining that
  override still timed out. The experiment isolated the combined override;
  disabling `mscoree` is the likely .NET startup mechanism, not separately proven.
- The native NetCDF/GRIB cross-version semantic matrix is still open. The
  current evidence PR must not advertise or guard combinations that have only
  documentation evidence.

## Release chronology and capability

| Release | Public date | Global gridded precipitation | Evidence classification |
|---|---:|---|---|
| 5.0 | 2016-03-04 | Unsupported | Official documentation/examples and 5.0.7-to-6.0 schema comparison |
| 5.0.1 | 2016-04 | Unsupported | Same 5.x family evidence |
| 5.0.2 | 2016-08 | Unsupported; withdrawn | Official release notes; no unofficial binary acquired |
| 5.0.3 | 2016-09 | Unsupported | Same 5.x family evidence |
| 5.0.4 | 2018-03 | Unsupported | Same 5.x family evidence |
| 5.0.5 | 2018-06 | Unsupported | Same 5.x family evidence |
| 5.0.6 | 2018-11 | Unsupported | Same 5.x family evidence |
| 5.0.7 | 2019-03 | Unsupported | Official examples plus focused binary-schema comparison |
| 6.0 | 2021-05-28 | Introduced | Official documentation and fixture/schema evidence; native run blocked by TCU API/runtime disagreement |
| 6.1 | 2021-09-21 | Available with limitations | Windows DSS run qualified with host-compatibility shim |
| 6.2 | 2022-03-11 | Available with limitations | Windows DSS run qualified with host-compatibility shim |
| 6.3 | 2022-08-25 | Available with timing limitation | Windows DSS run qualified; exact-release process-local WMIC fallback retained from earlier host evidence |
| 6.3.1 | 2022-09-30 | Available with timing limitation | Windows DSS run qualified; exact-release process-local WMIC fallback retained from earlier host evidence |
| 6.4 | 2023-06-05 | Documented | No current local runtime; superseded by official 6.4.1 download |
| 6.4.1 | 2023-06-22 | Documented | CLB07/Wine runtime inventoried; exact-profile TCU/COM blockers prevent precipitation execution |
| 6.5 | 2024-02-02 | Documented | Native attempt fails in HEC/VB startup before model processing |
| 6.6 | 2024-09-30 | Supported and qualified for tested DSS route; translated GeoTIFF route qualified | Windows DSS plus CLB07/Wine 11 GeoTIFF end-to-end execution |
| 6.7 Beta 5 | 2025-10 | Historical beta only | Windows end-to-end execution; no stable support claim |
| 7.0 | 2026-04-17 | Supported and qualified for tested DSS route | Windows end-to-end execution |
| 7.0.1 | 2026-06-02 | Supported and qualified for tested DSS route | Windows end-to-end execution |

HEC withdrew 5.0.2 because of a critical simplified-breach defect. The
official archive does not offer it, and this audit did not use an unofficial
mirror. The current archive similarly offers 6.4.1 rather than the superseded
6.4 installer.

### Why 5.x is classified unsupported

The 5.0.7 official examples contain none of the 6.x global meteorology grammar
(`Precipitation Mode`, `Met BC=Precipitation`, or equivalent gridded entries).
A focused UTF-16 string inspection found none of `Precipitation Mode`,
`Gridded Source`, `Meteorology`, `Point Interpolation`, or `Constant Units` in
the matching 5.0.7 `RasMapperLib.dll`; every string is present in 6.0.

This was a schema-string comparison, not vendor-source decompilation. No
vendor source was copied. Reproducibility identifiers are:

| Assembly | Size | File version | SHA-256 |
|---|---:|---|---|
| 5.0.7 `RasMapperLib.dll` | 3,685,888 | 2.0.0.0 | `f23f43304d445356e50f760f1e54ee17d5b46b2c7a97991e7d73dad740c735ba` |
| 6.0 `RasMapperLib.dll` | 6,174,720 | 2.0.0.0 | `be896702ff0705034b3d17dab86a4d91e290dc69884f50dd3fdfb83518faf8c8` |

The old 5.x uniform hyetograph assigned to a storage area or 2D area remains a
valid, separate capability. It must not be labeled as gridded rain-on-grid.

## Executable qualification evidence

The test case is plan 06, **Gridded Precip - Infiltration**, from HEC-RAS 6.0's
official Bald Eagle Creek Multi-2D examples. It references a real NEXRAD
HEC-DSS grid and was shortened to a wet 80-minute window. The solver-facing
input has shape `3 x 268830`, maximum `3.6177184582`, and 230,735 nonzero
values. Successful nine-output-time runs have a final cell cumulative-rainfall
maximum of `0.1145427823`, 144,528 nonzero values, and nonzero water surfaces.

| Version | Integrated precipitation preprocessing | Solver/result | Classification |
|---|---|---|---|
| 6.0 | `RasTcu.accept()` reports exact-runtime acceptance, but the same executable raises the actual TCU dialog | Not run | ras-commander TCU registry/runtime compatibility blocker, not precipitation evidence |
| 6.1 | `Processing` and `Finished Processing Precipitation`; fresh temporary HDF contains the expected `3 x 268830` values | Raw run reaches solver then fails because WMIC is absent. With process-local CIM shim: verified finish, cumulative max `0.1145427823`, 126,462 nonzero values over 8 output times, nonzero WSE | Precipitation passes; host compatibility fails without shim |
| 6.2 | Same expected materialization and precipitation messages | Raw WMIC failure; shimmed run verified, 144,528 nonzero cumulative values over 9 output times, nonzero WSE | Precipitation passes; host compatibility fails without shim |
| 6.3 | Expected materialization and precipitation messages | `Finished Unsteady Flow Simulation`; expected rain and WSE | Qualified with documented period-average limitation; exact-release WMIC fallback available when the host lacks WMIC |
| 6.3.1 | Expected materialization and precipitation messages | `Finished Unsteady Flow Simulation`; expected rain and WSE | Qualified with documented period-average limitation; exact-release WMIC fallback available when the host lacks WMIC |
| 6.4 | No executable | Not run | Missing runtime |
| 6.4.1 on CLB07/Wine 11 | Native registered profile: `RasTcu.accept()` cannot find an accepted donor. Mixed accepted profile: `RasMapper Component did not load` / `ActiveX component can't create object` | Not reached | Exact-profile provisioning/COM blocker; no precipitation claim |
| 6.5 | No fresh result materialized before HEC-owned `Error: Unexpected error; quitting` dialog | Not reached | Confirmed startup/install/runtime failure on this host |
| 6.6 | Expected materialization and precipitation messages | `Finished Unsteady Flow Simulation`; expected rain and WSE | Qualified on Windows |
| 6.6 on CLB07/Wine 11, native DSS | Preprocessing completed in 13.3 seconds after removing the disabling DLL override; 3 x 268830 values | Verified completion; final cumulative max 0.11454278230667114 in, 144528 nonzero entries; WSE max 923.1984252929688 ft | Qualified; rainfall and WSE metrics match Windows 6.6 exactly |
| 6.6 on CLB07/Wine 11, translated GeoTIFF | Four exact interval rows materialized at 10:00, 11:00, 12:00, and 13:00; `Processing` and `Finished Processing Precipitation` | `Finished Unsteady Flow Simulation`; final cumulative max `0.1157457530` in over 18,066 cells; final hydraulic depth max `9.7182655334` ft over 7,576 wet cells | Qualified for the feature-snapshot GeoTIFF-to-NetCDF/native-HDF route |
| 6.7 Beta 5 | Expected materialization and precipitation messages | `Finished Unsteady Flow Simulation`; expected rain and WSE | Historical beta evidence only |
| 7.0 | Expected materialization and precipitation messages | `Finished Unsteady Flow Simulation`; expected rain and WSE | Qualified on Windows |
| 7.0.1 | Expected materialization and precipitation messages | `Finished Unsteady Flow Simulation`; expected rain and WSE | Qualified on Windows |

The 6.1/6.2 controlled rerun supplies only the CPU fields requested by the
legacy engine, using read-only Windows CIM queries in a temporary process-local
`PATH`. It does not change the HEC-RAS executable or project. The unmodified
failure emitted an empty `systemInfo.txt` followed by Intel Fortran severe
error 24. This evidence supports a separate ras-commander host-compatibility
fix; it is not a precipitation-format workaround. The controlled rerun used
the shim only for 6.1 and 6.2. HEC-RAS 6.3 and 6.3.1 qualified in this matrix
without it, while the library retains its earlier evidence-backed fallback for
those two exact releases. No shim claim is extrapolated to 6.3.2 or another
untested patch release.

### CLB07/Wine 6.6 native DSS control and successful rerun

The successful final plan HDF SHA-256 is
`6f8aa85125809c10393e47ed7c2f412203a2121db4e0b116493ca7ea7516e106`.
The executable SHA-256 remains
`a34e56a172ba06cde2d546f4d7282801c2b67040969d4ed23b41dfc755772134`.
Evidence receipts `wine66-dss-short.json`, `wine66-dss-fresh.json`, and
`wine66-dss-dotnet.json` and the diagnosis are retained in the research
worktree's ignored `working/` directory. The successful isolated model is
on CLB07 CT212 at `/mnt/scratch/dss-dotnet-20260925/6.6/`.
The comparison establishes matching rainfall/WSE summary metrics, not a
bitwise comparison of all hydraulic arrays. No other release is qualified
by this test.

### CLB07/Wine 6.6 translated GeoTIFF evidence

The direct Wine run used the HEC-RAS 6.6 RasExamples `BaldEagleCrkMulti2D`
project and three deterministic, asymmetric, single-band GeoTIFF interval
amounts. The feature snapshot translated those files to its cached NetCDF plus
native unsteady-HDF representation, then public `RasPreprocess` and `RasCmdr`
APIs performed preprocessing and compute. The HEC-RAS executable SHA-256 was
`a34e56a172ba06cde2d546f4d7282801c2b67040969d4ed23b41dfc755772134`.
`RasTcu.accept()` returned `already-accepted`; no GUI interaction occurred.

The temporary plan HDF contained exactly four `4 x 408` interval rows:

| Timestamp | Exact interval values (inches) | Counts |
|---|---|---|
| `09Aug2024 10:00:00.000` | `0.0` | 408 |
| `09Aug2024 11:00:00.000` | `0.01968505047`, `0.03937010095` | 204, 204 |
| `09Aug2024 12:00:00.000` | `0.00984252524`, `0.03937010095` | 192, 216 |
| `09Aug2024 13:00:00.000` | `0.00393700646` or its float32 rounding neighbor, `0.03937010095` | 272, 136 |

The final HDF reported `Processing Precipitation data`, `Finished Processing
Precipitation data`, `Finished Unsteady Flow Simulation`, and `Complete
Process`, with no precipitation error. Final cell cumulative rainfall reached
`0.1157457530` inches in 18,066 cells; final hydraulic depth reached
`9.7182655334` feet in 7,576 cells. The final HDF SHA-256 was
`0be34dbaf339192b44bee51134c50a3a0d31ba5980aa0c12c1e72a1d1d449afe`.
These results qualify this translation route on Wine 11 / HEC-RAS 6.6; they do
not imply native HEC-RAS GeoTIFF meteorology support or support on other
versions.

## Format matrix

| Source or representation | Vendor support | Qualification state | Required treatment |
|---|---|---|---|
| HEC-DSS grid | Documented from 6.0 | Executed on selected 6.x/7.x Windows releases | Preserve DSS pathname, units, and period semantics; validate temporary and final HDF |
| GDAL NetCDF | Documented from 6.0 | Documentation/schema evidence in this branch | Run rate, interval-amount, cumulative, first-step, units, orientation, and timing matrix before cross-version claim |
| GDAL GRIB/GRIB2 | Documented from 6.0 | Real filtered NOAA HRRR GRIB2 decoded and authored to native HDF; native executable preprocessing remains open | Qualify native preprocessing across representative encodings; never equate GDAL readability or ras-commander translation with native HEC-RAS support |
| WPC QPF GRIB2 | Vendor-known compression incompatibility through 7.0.1 | Supported with translation | Convert with HEC-Vortex or HEC-MetVue to validated DSS |
| GeoTIFF precipitation series | Not documented as a vendor-native meteorology source | Supported through ras-commander translation; qualified on Windows and CLB07/Wine 11 with HEC-RAS 6.6 | Explicit timestamps/units/semantics → content-addressed NetCDF plus native HDF payload; never advertise direct vendor GeoTIFF ingestion |
| Imported Raster Data HDF | Internal RAS materialization | Issue #371 implementation/test concern | Treat as internal solver-facing payload, not an external input-format promise |

## Version-specific defects and limitations

| Affected version(s) | Vendor finding | ras-commander policy candidate |
|---|---|---|
| 6.0-6.1 | Optional precipitation ratio is not applied; HEC lists the fix in 6.2 | Warn or reject non-unit ratio unless source values are intentionally pre-scaled; never silently compensate |
| 6.0-6.3.1 | Period-average to instantaneous interpolation can shift the result in time. The claimed 6.3 fix was incomplete; 6.4 centers the period and removes the one-period shift | Prefer interval totals/PER-CUM where semantics permit, or require 6.4+ for period-average data; add timing assertions |
| 6.2 | Storage areas can fail to receive simple time-series precipitation; HEC lists the fix in 6.3 | Keep this distinct from the global gridded route; test only if uniform storage-area precipitation is in scope |
| 6.2 and earlier visualization | Cumulative spatial-precipitation display and some constant/DSS surface defaults were corrected in 6.3 | Do not use map appearance alone as solver evidence; inspect HDF values |
| 6.4.1-6.6 | HEC lists missing infiltration losses for 1D elements using the finite-volume method, causing total rather than excess precipitation to enter the 1D system | Warn for 1D finite-volume plus infiltration; the 2D fixture in this report does not exercise this defect. A 7.x fix was not established from the reviewed notes |
| 6.5 | Newly created infiltration layers may not be recognized; HEC lists correction in 6.6 | Version-specific geometry/infiltration authoring test, separate from rainfall source routing |
| 6.5 and earlier migration | HEC 6.6 fixed migration of infiltration/percent-impervious associations and layer typing | Recompute and audit property tables when moving older projects; do not infer successful migration from project load |
| 6.3.1-7.0.1 | WPC QPF GRIB2 compression is not accepted | Route explicitly through Vortex/MetVue to DSS |

The HEC known-issues pages use rolling status labels that can appear adjacent
to the next row when extracted. This report relies on the issue description
and the later release's resolved-issues entry, not the color/status word alone.

## Downstream workflow audit

The table below records the initial audit. PR #376 follow-up changes retired
722's obsolete authoring cells, added explicit temporal semantics and
temporary-HDF checks to 727/900/901/914/916, corrected 924's precompute depth
label, and clarified the scope of 915/917/926. A fresh Windows 6.6 execution
of 729 passed after the cache transform correction. A RasExamples regression
verifies AORC's first nonzero interval in the authored HDF. Full live-product
reruns for each changed notebook and the remaining cross-version semantic
matrix are still separate qualification tasks; old outputs are not evidence
for newly changed source cells.

| Notebook | Current route | Current evidence | Required requalification |
|---|---|---|---|
| 727 Atlas 14 | Atlas 14 grid to NetCDF to native rain-on-grid | All 20 code cells executed; compute plus rainfall-rate figures | Retain as the design-storm canonical example; add temporary-HDF and manual-message/map review checks |
| 722 Atlas 14 | Legacy/conceptual mix of raw edits, gridded setup, and uniform comparison | 29 code cells, no committed outputs | Replace with a concise link/migration explanation to 727; do not keep raw text mutation as canonical |
| 728 DSS window extension | Existing DSS grid and `configure_gridded_dss_precipitation()` | 8 code cells, no committed outputs | Execute against a small fixture and verify the extended DSS time window plus pre/post HDF totals |
| 729 GeoTIFF | Explicit GeoTIFF series translated to durable NetCDF plus native HDF | Windows and CLB07/Wine 11 HEC-RAS 6.6 passed authoring, temporary-HDF validation, compute, and final rainfall/hydraulics | Retain as the canonical GeoTIFF example and keep Windows/Wine evidence release-specific |
| 900/901 AORC | AORC NetCDF and `set_gridded_precipitation()` | Nearly all cells executed; bulk plan creation/compute | Add explicit units/value semantics, first-timestep checks, temporary-HDF rainfall, final totals, hydraulic response, and manual diagnostics reminder |
| 914 historical validation | AORC NetCDF direct route | All 21 cells executed and computes | Remove stale suggestion that API setup may require manual authoring; add the same semantic/pre/post checks while retaining manual review |
| 924 MRMS | MRMS NetCDF direct route | Strong code contract but 12 code cells have no committed outputs | Re-execute after core writer lands; retain cumulative/rate and hydraulic visual checks; add temporary-HDF assertion and manual review reminder |
| 917 MRMS | GRIB2 to DSS, then uniform boundary hyetographs | 6 of 8 code cells have outputs and final hydraulic inspection | Label it accurately as a uniform-per-area comparison, or add a separate global gridded-DSS branch; do not treat it as native gridded qualification |
| 916 HRRR | HRRR GRIB converted to DSS | All 12 cells executed; validates DSS metadata, baseline/forecast, final rain and hydraulics | Retain as forecast/DSS canonical example; add temporary-HDF assertion and test more than one supported version family |
| 915 forecast overview | Downloads/dispatches forecast inputs | 9 of 10 cells have outputs; no active gridded authoring qualification | Keep as orchestration overview and link to 916/926; do not count it as format evidence |
| 926 WPC | WPC product converted to DSS | 1 of 5 code cells has output; validates catalog/plot only | Complete a RAS authoring, preprocessing, compute, rainfall, and hydraulic path using the mandatory DSS translation |

Every canonical notebook should finish by reminding users that automated
checks supplement, rather than replace, manual review of HEC-RAS runtime
messages, precipitation maps, timing, units, and hydraulic response.

## Proposed PR boundaries

1. **Version evidence PR (this branch):** this report, compact JSON capability
   evidence, the public-API qualification harness, and deterministic harness
   tests. No production guards or speculative support claims.
2. **Legacy Windows host compatibility PR:** extend the existing library-owned
   WMIC compatibility path to the evidence-backed 6.1/6.2 cohort (and 6.0 only
   after a runnable qualification). Test process scoping, exact queried fields,
   environment restoration, and unmodified-versus-shim evidence.
3. **Capability and routing PR:** one normalized-version registry; reject global
   gridded meteorology before 6.0; issue evidence-backed warnings for 6.0/6.1
   ratio and 6.0-6.3.1 period-average behavior; report route/reason. Leave 6.5
   as unqualified, not unsupported.
4. **Native raster semantic qualification PR:** deterministic asymmetric,
   non-hourly NetCDF and representative GRIB payloads across the minimum
   releases needed to prove schema transitions. Cover rate, interval amount,
   cumulative depth, first timestep, inches/millimeters, orientation, nodata,
   temporary HDF, messages, final rainfall, and hydraulics.
5. **Translation adapter PR:** establish a canonical precipitation cube,
   first-class GeoTIFF/GRIB-to-NetCDF ingestion, and explicit translation
   routes. The GeoTIFF feature now has direct HEC-RAS 6.6 Windows and Wine
   evidence; retain its value/timing/CRS/nodata acceptance tests. Qualify WPC
   QPF and other encodings separately rather than generalizing from GeoTIFF.
6. **Wine qualification PR:** retain the 6.6 translated-GeoTIFF and native DSS
   evidence, including the resolved disabling-DLL-override control. Resolve
   6.4.1 exact-profile TCU provisioning and COM registration
   before making any 6.4.1 precipitation claim. Keep Windows and Wine claims
   separate.
7. **Product/notebook PRs:** requalify AORC, MRMS, HRRR, WPC, Atlas 14, and
   NEXRAD/DSS using the common semantics and routing layer, then commit cleaned
   notebooks plus compact receipts rather than model outputs.

## Official sources

- [HEC-RAS downloads and archive](https://www.hec.usace.army.mil/software/hec-ras/download.aspx)
- [HEC-RAS 5.0.2 release notes](https://www.hec.usace.army.mil/software/hec-ras/documentation/HEC-RAS%205.0.2%20Release%20Notes.pdf)
- [HEC-RAS 6.0 new features](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.0/new-features)
- [HEC-RAS 6.0 global boundary conditions](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.0/boundary-and-initial-conditions-for-2d-flow-areas/global-boundary-conditions)
- [HEC-RAS 6.6 global boundary conditions](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.6/boundary-and-initial-conditions-for-2d-flow-areas/global-boundary-conditions)
- [HEC-RAS 6.2 resolved issues](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.2/resolved-issues)
- [HEC-RAS 6.3 resolved issues](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.3/resolved-issues)
- [HEC-RAS 6.4 resolved issues](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/6.4/resolved-issues)
- [HEC-RAS 6.4.1 known issues](https://www.hec.usace.army.mil/confluence/rasdocs/raski/6.4.1)
- [HEC-RAS 6.5 known issues](https://www.hec.usace.army.mil/confluence/rasdocs/raski/6.5)
- [HEC-RAS 6.6 known issues](https://www.hec.usace.army.mil/confluence/rasdocs/raski/6.6)
- [HEC-RAS 7.0 known issues](https://www.hec.usace.army.mil/confluence/rasdocs/raski/7.0)
- [HEC-RAS 7.0.1 known issues](https://www.hec.usace.army.mil/confluence/rasdocs/raski/7.0.1)
- [HEC meteorological-data workshop developed for 6.2](https://www.hec.usace.army.mil/confluence/rasdocs/rastraining/files/latest/217581413/217581477/1/1729729905441/4.5-W-Met%2BData.pdf)
- [HEC watershed-scale rain-on-mesh guide](https://www.hec.usace.army.mil/confluence/rasdocs/hgt/files/latest/290456384/290456405/1/1742410606032/Watershed%2BScale%2BRain-on-Mesh%2BModeling%2Bin%2BHEC-RAS.pdf)
- [HEC-DSSVue time-series conventions](https://www.hec.usace.army.mil/confluence/dssdocs/dssvueum/introduction/time-series-conventions)
- [HEC-Vortex](https://github.com/HydrologicEngineeringCenter/Vortex)
