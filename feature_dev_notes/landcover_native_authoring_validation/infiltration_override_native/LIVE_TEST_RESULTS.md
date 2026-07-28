# Live Native Qualification Results

Run date: 2026-07-25

## Fixture

Each HEC version ran in a fresh Python process against a separate disposable
copy of:

- `example_projects/BaldEagleCrkMulti2D/BaldEagleDamBrk.g09.hdf`
- `Land Classification/LandCover.hdf`
- `Land Classification/LandCover.tif`
- `Soils Data/Infiltration.hdf`
- `Soils Data/Hydrologic Soil Groups.hdf`
- `Soils Data/Hydrologic Soil Groups.tif`

The source geometry started without `/Geometry/Infiltration`, had one native
Land Cover region, and resolved 136 native infiltration classes from its
associated sidecar.

## Results

| Runtime | Output directory | Requested values | Result |
| --- | --- | --- | --- |
| HEC-RAS 6.0 | `H:\tmp\infiltration_native_api_60` | CN 76, abstraction 0.15, minimum rate 0.05 | PASS |
| HEC-RAS 6.6 | `H:\tmp\infiltration_native_api_66` | CN 77, abstraction 0.20, minimum rate 0.10 | PASS |
| HEC-RAS 7.0 | `H:\tmp\infiltration_native_api_70` | CN 78, abstraction 0.25, minimum rate 0.20 | PASS |

For every runtime:

1. `create_infiltration_override_regions(...)` created and named one native
   infiltration override polygon.
2. `set_infiltration_base_overrides(...)` wrote 136 class rows.
3. A fresh native `RASGeometry` reload reproduced the region name, class
   order, parameter schema, and requested values.
4. HEC authored the keys `Attributes`, `Base Overrides`, `Polygon Info`,
   `Polygon Parts`, `Polygon Points`, and `Variables`.
5. Both mutations retained timestamped pre-edit backups in the output
   directory.

## Per-region parameter-table qualification

The additive `get_infiltration_region_overrides()` and
`set_infiltration_region_overrides()` APIs were then exercised in fresh
Python processes against the prepared disposable geometries above:

| Runtime | Requested regional values | Result |
| --- | --- | --- |
| HEC-RAS 6.0 | CN 53, abstraction 0.13, minimum rate 0.03 | PASS |
| HEC-RAS 6.6 | CN 52, abstraction 0.12, minimum rate 0.02 | PASS |
| HEC-RAS 7.0 | CN 52, abstraction 0.12, minimum rate 0.02 | PASS |

For each runtime, the selected 136-class table reloaded through the public
native `GetParameterTable` surface, the geometry-wide Base Overrides were
byte-for-value unchanged through the edit, the selected name/zero-based ID
were stable, and a third distinct durable backup was retained. RasDecomp shows
the same public `GetParameterTable` / `SetParameterTable` implementation
architecture in all three releases.

An additional HEC-RAS 7.0 test edited a geometry after geometry preprocessing.
HEC-RAS had changed that `.g09.hdf` root `File Type` from
`HEC-RAS Geometry` to `HEC-RAS Results` while leaving `Geometry` as its only
root group. The role guard now accepts that exact native geometry-only shape
but continues to reject plan/result HDFs containing `Plan Data`, `Results`, or
`Event Conditions`.

HEC-RAS 5.0.7 was assessed through its RASDecomp baseline and does not expose
the required native infiltration override layer/API. The implementation
rejects 5.x rather than guessing at an incompatible schema.

The disposable HDF/TIFF corpus remains external to the repository at the
paths above. This note is the durable, reviewable result manifest.

## End-to-end plan-array qualification

Executed notebook 218 completed a fresh HEC-RAS 7.0 April 2026 baseline and
modified plan after native geometry-wide and regional edits:

- Base Overrides: Curve Number 65, initial abstraction ratio 0.20, and minimum
  infiltration rate 0.10;
- selected `Main Channel` region: Curve Number 55, initial abstraction ratio
  0.15, and minimum infiltration rate 0.05;
- 215 active cells were fully covered by the regional polygon, 16,817 were
  fully disjoint Base-Override cells, and 1,034 intersected the boundary;
- the selected-region values appeared only in the spatially attributed final
  arrays while the geometry and plan copies of those final arrays were
  byte-equal;
- 18,053 active maximum-WSE values changed, with maximum absolute change
  6.379 feet, and 145 cumulative-infiltration values changed.

The fresh independent notebook review verdict was PASS. Durable execution
evidence is:

- `H:\Symphony\ras-commander\CLB-903\notebooks\218_infiltration_base_override_authoring_executed.ipynb`
- `H:\Symphony\ras-commander\CLB-903\terminal-logs\20260725_135425_218_infiltration_base_override_authoring.terminal.log`
