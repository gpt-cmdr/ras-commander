# Test Report

## Hydraulic qualification

Each row used a fresh Python process and a disposable copy of the same Muncie
project. All rows passed:

- native RASMapper authoring;
- native geometry association;
- native property-table recompute;
- completed plan with required final arrays;
- geometry base-Manning edit propagated to final arrays;
- sidecar Manning edit/native 5.x rebuild propagated to final arrays;
- zero changes to non-Manning face-table columns.

| Version | Host | Cells | Face rows | Base edit cells / faces | Sidecar edit cells / faces |
|---|---|---:|---:|---:|---:|
| 5.0.7 | CLB08 | not emitted | 46,505 | n/a / 11,248 | n/a / 314 |
| 6.0 | CLB08 | 5,765 | 46,505 | 1,418 / 11,248 | 36 / 314 |
| 6.1 | CLB08 | 5,765 | 46,505 | 1,418 / 11,248 | 36 / 314 |
| 6.2 | CLB08 | 5,765 | 46,505 | 1,418 / 11,248 | 36 / 314 |
| 6.3.1 | CLB08 | 5,765 | 46,505 | 1,418 / 11,248 | 36 / 314 |
| 6.4.1 | CLB12 | 5,765 | 47,055 | 1,418 / 11,374 | 36 / 307 |
| 6.5 | CLB12 | 5,765 | 47,055 | 1,418 / 11,374 | 36 / 307 |
| 6.6 | CLB08 | 5,765 | 47,055 | 1,418 / 11,374 | 36 / 307 |
| 6.7 Beta 5 | CLB08 | 5,765 | 47,055 | 1,418 / 11,374 | 36 / 307 |
| 7.0 | CLB08 | 5,765 | 47,055 | 1,418 / 11,374 | 36 / 307 |

HEC-RAS 6.7 Beta 5 is also exercised as a supplemental between-release row,
but is not counted as a stable-release requirement.

See `results/version_matrix/` for the machine-readable manifests, disposable
run paths, associations, schemas, deltas, and SHA-256 hashes.
`results/diagnostics/` preserves the two 6.0 failures that exposed the TCU
detection bug and the completed-run parser false negative.

## Focused regression suite

Command:

```text
python -m pytest tests/test_landcover_native.py \
  tests/test_hdf_landcover_logging.py \
  tests/test_rasmap_land_classification.py \
  tests/test_spatial_extent.py \
  tests/test_geometry_association.py \
  tests/test_legacy_plan_execution_helpers.py \
  tests/test_results_parser.py \
  tests/test_rastcu.py \
  tests/test_gdal_runtime.py \
  tests/test_geom_preprocessor.py \
  tests/test_hdf_infiltration_native.py \
  tests/test_infiltration_override_native.py \
  tests/test_hdf_mesh_face_hydraulic_properties.py \
  tests/test_rascmdr_compute_plan_control_flow.py -q
```

Final result: 263 passed. The three emitted warnings are intentional
deprecation warnings for the renamed non-authoritative Python raster estimate.
The durable terminal record is
`H:\Symphony\ras-commander\CLB-903\terminal-logs\20260725_155904_final-focused-regression-green.terminal.log`.

`git diff --check`, Python compilation, and Ruff checks on the changed API and
test modules pass. Repository-wide format modernization is intentionally
outside this focused change.

## Repository-wide suite

The repository-wide single-process run reached 1,806 passed and 55 skipped,
with 20 failures and 8 errors outside this change's focused gate. Principal
causes included a test-injected `clr` module with `__spec__ = None` contaminating
later pythonnet integrations, missing/external fixture drift, citation/notebook
drift, and a native JVM/DSS access violation. The land-cover tests pass when
run in a fresh process, and the live HEC runs above provide the authoritative
integration gate for this change.

## Native classification-polygon CRUD qualification

The public land-cover polygon methods now use the nested native
`LandCoverClassificationLayer` (`PolygonFeatureLayer`) instead of writing HDF
datasets with h5py. The qualified contract is intentionally narrow:

- HEC-RAS 6.0 through 7.0/7.0.1;
- sidecars whose root `LC Type` is exactly `LandCover`;
- one valid, hole-free polygon feature (a one-member `MultiPolygon` is
  normalized; true multipart input and interior rings are rejected before
  mutation);
- assignment to an existing native classification only;
- class IDs are validated, not remapped;
- transaction rollback restores both the HDF and any pre-existing RASMapper
  backup if native editing or readback verification fails.

This polygon-CRUD contract is limited to Land Cover. Soils, infiltration,
sediment, and other **classification-polygon** mutation paths remain
read-only/fail-closed because their attempted native polygon save did not
return reliably. That boundary does not apply to the separately qualified
native infiltration sidecar-parameter setters or geometry-level infiltration
Base Override and named-region APIs documented below and in
`infiltration_override_native/`. Creating a new polygon-only class was also
rejected: native
`LandCoverLayer.Save()` persisted partial artifacts but did not return
reliably in the in-process workflow. New classifications must be added by
rebuilding the land-classification layer.

Disposable live results:

| Requested version | Resolved install | Result | Evidence path |
|---|---|---|---|
| 6.0 | `C:\Program Files (x86)\HEC\HEC-RAS\6.0` | add/read/delete smoke passed | `H:\CLB_Claws\symphony\CLB-903\polygon-crud-6.0-smoke` |
| 6.6 | `C:\Program Files (x86)\HEC\HEC-RAS\6.6` | full add/update/delete, rollback, and multipart rejection passed; hole persistence was later disqualified hydraulically | `H:\CLB_Claws\symphony\CLB-903\polygon-crud-6.6-proof` |
| 7.0 | `C:\Program Files (x86)\HEC\HEC-RAS\7.0.1` | full add/update/delete, rollback, and multipart rejection passed; hole persistence was later disqualified hydraulically | `H:\CLB_Claws\symphony\CLB-903\polygon-crud-7.0-proof` |

The 6.6 run added an `Open Water` polygon (ID 11, Manning's n 0.041)
with bounds `(1970071.7000, 289202.4446, 1984836.7000, 299520.4446)`
and one hole, then updated it to `Main Channel` (ID 1, Manning's n
0.052) with bounds
`(1989266.2000, 302615.8446, 2002554.7000, 311902.0446)`.
The forced-failure rollback SHA-256 remained
`019712987703911a80f611604c3a64b23505992b1ade11863529435ee52355cb`.

The 7.0 request resolved to the installed 7.0.1 build. It added `Open Water`
(ID 11, Manning's n 0.043) with bounds
`(2008460.7000, 316029.2446, 2023225.7000, 326347.2446)` and one hole,
then updated it to `Main Channel` (ID 1, Manning's n 0.054) with bounds
`(2029131.7000, 330474.4446, 2042420.2000, 339760.6446)`.
The forced-failure rollback SHA-256 remained
`cfb937e408ca117c44e09b8fc00381007bd88c69e6b9d31dbc0c14c5c530b6b9`.

Those two historical hole artifacts proved only native persistence and
readback. Notebook 213's final-array gate showed HEC-RAS filling 427 of 440
hole-core cells, including cells 2,500 feet from the ring. RasDecomp confirmed
that `LandCoverLayer.GetPolysAsMappedTuples()` converts a multipart native
polygon to one single-ring `Geospatial.Vectors.Polygon`, discarding its part
starts before classification resampling. The same conversion exists in 6.0,
6.6, 7.0, and 7.0.1. Public add/update operations now reject interior rings
before backup or native loading; list/read remains hole-aware for inspecting
pre-existing sidecars.

Runtime HEC-RAS 6.6 and 7.0.1 both authored the classification attribute field
as `Classification`. Readers accept both `Classification` and `Name` for
forward/backward compatibility. A regression test also fixes RASMapper's
feature-relative `Polygon Parts` offsets when a later feature contains a hole.

Prepared final-Manning qualification sidecars retain an added `Open Water`
polygon fully inside the original `Main Channel` polygon. The polygon bounds
are `(2063347.2881, 352125.3883, 2083124.6947, 367770.6226)` and its area is
`12612721.9911` square project units:

- HEC-RAS 6.6: Manning's n 0.082 at
  `H:\CLB_Claws\symphony\CLB-903\polygon-final-n-6.6\LandCover.hdf`.
- HEC-RAS 7.0/7.0.1: Manning's n 0.083 at
  `H:\CLB_Claws\symphony\CLB-903\polygon-final-n-7.0\LandCover.hdf`.

These disposable sidecars are the handoff inputs for the separate geometry
association, native property-table recompute, and final-results-HDF gate.

## Transactional sidecar setter requalification

After adding ras-commander-owned transaction snapshots and unique durable
backups around the native parameter-table setters, fresh Python processes
requalified both sidecar families:

| Artifact | Runtime | Requested / observed value | Result path |
|---|---|---:|---|
| Land cover | 6.0 | Mixed Forest n = 0.121 | `C:\CLB\sidecar-transaction-qualification-20260725-60` |
| Land cover | 6.4.1 (CLB12 interactive session) | Mixed Forest n = 0.124 | `C:\CLB\clb903-sidecar-64-20260725-1101` |
| Land cover | 6.6 | Mixed Forest n = 0.122 | `C:\CLB\sidecar-transaction-qualification-20260725-66` |
| Land cover | 7.0.1 | Mixed Forest n = 0.123 | `C:\CLB\sidecar-transaction-qualification-20260725-701` |
| SCS infiltration | 6.0 | NoData CN = 76 | `C:\CLB\infiltration-sidecar-transaction-20260725-60` |
| SCS infiltration | 6.4.1 (CLB12 interactive session) | NoData CN = 79 | `C:\CLB\clb903-sidecar-64-20260725-1101` |
| SCS infiltration | 6.6 | NoData CN = 77 | `C:\CLB\infiltration-sidecar-transaction-20260725-66` |
| SCS infiltration | 7.0.1 | NoData CN = 78 | `C:\CLB\infiltration-sidecar-transaction-20260725-701` |

Every result reloaded the requested native value, returned an existing unique
`backup_path`, and marked `recompute_required=True`. Failure-injection tests
also prove rollback after a rejected partial native save, table/property
reload mismatch, `KeyboardInterrupt`, and replacement of RASMapper's fixed
backup artifact. The CLB12 evidence was produced by
`scripts/qualify_sidecar_transactions.py`; its machine-readable result is
stored at `results/sidecar_transactions/6.4.1.json`.

## Executed example-notebook qualification

All four revised examples were executed from clean disposable projects and
then reviewed by independent notebook-review agents. Repository copies are
byte-identical to the accepted executed artifacts.

| Notebook | Native execution gate | Key result | Verdict |
|---|---|---|---|
| 212 | HEC-RAS 7.0 April 2026, two controlled Windows solves | 19,597 total centers; 18,066 active; 1,531 excluded; 11,520 active WSE changes; 270-second breach advance | PASS |
| 213 | HEC-RAS 7.0 April 2026, native polygon CRUD and two Windows solves | 2,976 changed cell Manning values; zero center-off-polygon Manning changes; 5,924 WSE changes; breach initiation/peak/geometry preserved | PASS |
| 218 | HEC-RAS 7.0 April 2026, native Base Override plus named-region edit and two Windows solves | final geometry/plan arrays byte-equal; 18,053 WSE changes; 145 cumulative-infiltration changes | PASS |
| 414 | HEC-RAS 7.0 April 2026, three native Linux solves | exact control/modified non-Manning face tables; 4,890 active cells changed by isolated depth-varying n; extension-only control hydraulically neutral at 0.001 ft | PASS |

Notebook 212 independently proved that only Deciduous Forest
`0.100 -> 0.108` and Mixed Forest `0.120 -> 0.132` changed in the controlled
inputs. Its regenerated face tables contained 433,897 versus 433,960 rows:
402,362 exact full-key matches and 63,133 unmatched elevation keys on stable
Face IDs, for a net increase of 63 rows. The final target-footprint cross-tab
accounted for every active cell: 5,304 changed/inside, 4,173 changed/outside,
17 unchanged/inside, and 8,572 unchanged/outside. Baseline breach initiation
at 02:41:30 versus modified initiation at 02:37:00 explains why the maximum
`+4.020 ft` WSE response includes nonlinear breach-wave amplification.

Notebook 213 exercised add, one-member-MultiPolygon normalization/update,
transient add/delete, persistent readback, and rejection-before-backup for
interior rings and true multipart polygons. The final association contained
one `BaldEagleCr` flow-area row with Terrain50 and the expected global Land
Cover, Terrain, and Infiltration layers. Independent HDF review confirmed
identical breach initiation, 530,807.25-cfs peak and time, final dimensions,
and geometry progression; the maximum breach-flow trace difference was
71.1875 cfs, or about 0.0134 percent of peak.

Notebook 414 isolated the advanced temporary-HDF workflow with a baseline,
extension-only control, and depth-varying-n case. Control and modified outputs
had bit-identical Face ID, elevation, area, wetted perimeter, and face-point
indexes across 487,688 rows; only Manning's n changed. All comparisons joined
to exactly 5,391 active cells. The isolated response changed 4,890 cells above
0.001 feet (mean `-0.0637 ft`, range `-0.3347` to `+0.0164 ft`, 95th
percentile absolute change `0.2727 ft`). All 1,358 unselected faces remained
byte-equivalent.

Durable notebooks and terminal logs are under
`H:\Symphony\ras-commander\CLB-903\notebooks\` and
`H:\Symphony\ras-commander\CLB-903\terminal-logs\`.
