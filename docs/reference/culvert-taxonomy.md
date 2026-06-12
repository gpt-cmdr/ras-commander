# Culvert Taxonomy

This page documents the validation reference in
`ras_commander/resources/culvert_taxonomy.json`. The JSON is the authoritative
machine-readable artifact for culvert shape codes, chart/scale selections,
geometry-record fields, group/barrel constraints, and HDF storage names.

## Evidence Base

The taxonomy was produced for CLB-494 from three sources:

- RASDecomp reflection of HEC-RAS 7.0 `RasMapperLib.dll`
  (`RasMapperLib.CulvertShapeTypes`, `CulvertChartNumbers`,
  `CulvertScaleNumbers`, `CulvertGroupLayer`, and `CulvertBarrelLayer`).
- RASDecomp string scan of HEC-RAS 7.0 `Ras.exe`, plus the existing
  RASDecomp 6.6 GUI map.
- Official HEC-RAS documentation for culvert editor field names, grouping
  limits, barrel limits, and FHWA chart/scale rules:
  [Entering and Editing Culvert Data](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/entering-and-editing-geometric-data/bridges-and-culverts/entering-and-editing-culvert-data),
  [Types of Culverts](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/latest/modeling-culverts/general-culvert-modeling-guidelines/types-of-culverts),
  [FHWA Chart and Scale Numbers](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/latest/modeling-culverts/culvert-data-and-coefficients/fhwa-chart-and-scale-numbers),
  and [Culvert Shape and Size](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/6.3/modeling-culverts/culvert-data-and-coefficients/culvert-shape-and-size).

Generated RASDecomp evidence for this issue is preserved under
`H:/Symphony/ras-commander/CLB-494/` by the Symphony artifact stash.

One evidence discrepancy is intentionally captured in the JSON:
RASMapperLib 7.0 reflection resolves the third ConSpan scale for charts 60 and
61 to `NinetyDegreeHeadwall`/scale 1, while the official HEC-RAS FHWA chart
table lists scale 3 as `90 degree wingwall angle`. The taxonomy uses the
official GUI/FHWA table value for validation and retains the reflection note for
traceability.

## Shape Codes

HEC-RAS 7.0 exposes nine culvert shapes. RASDecomp did not find a separate
user-defined shape code; nonstandard arch and ConSpan sizes are handled under
the existing shape codes by interpolation or scaling.

| Code | ras-commander name | HEC-RAS/RASMapper label | RASMapper enum | Allowed chart IDs |
|------|--------------------|-------------------------|----------------|-------------------|
| 1 | Circular | Circular | `Circle` | 1, 2, 3, 55, 56 |
| 2 | Box | Box | `Box` | 8, 9, 10, 11, 12, 13, 16, 17, 18, 19, 57, 58, 59 |
| 3 | Pipe Arch | Pipe Arch | `PipeArch` | 34, 35, 36 |
| 4 | Ellipse | Ellipse | `Ellipse` | 29, 30 |
| 5 | Arch | Arch | `Arch` | 41, 42, 43 |
| 6 | Semi-Circle | Semi-Circle | `SemiCircle` | 41, 42, 43 |
| 7 | Low Profile Arch | Low Arch | `LowArch` | 52 |
| 8 | High Profile Arch | High Arch | `HighArch` | 52 |
| 9 | Con Span | Conspan Arch | `ConspanArch` | 60, 61 |

The full scale list for each chart is in `shapes[].allowed_charts[]` in the
JSON. API validation should check a selected scale against the selected chart,
not only against the shape, because scale IDs are reused across charts.

## Geometry Records

Plain-text geometry stores culverts with two record families:

```text
Culvert={shape},{span},{rise},{length},{mannings_n},{entrance_loss},{exit_loss},{chart_id},{scale_id},{upstream_invert},{upstream_station},{downstream_invert},{downstream_station},{name},{culvert_code},{auxiliary_integer}
Multiple Barrel Culv={shape},{span},{rise},{length},{mannings_n},{entrance_loss},{exit_loss},{chart_id},{scale_id},{upstream_invert},{downstream_invert},{num_barrels},{name},{culvert_code},{auxiliary_integer}
```

`Multiple Barrel Culv=` is followed by fixed-width upstream/downstream station
pairs. The current `GeomCulvert` API preserves historical field names
`InletType` and `OutletType`; the taxonomy maps them to the GUI labels
`Chart #` and `Scale#` so validation errors can use HEC-RAS nomenclature.

Optional detail records are:

- `Culvert Bottom n=`
- `Culvert Bottom Depth=`
- `BC Culvert Barrel=`

## Groups And Barrels

A culvert group is a culvert type. Use a new group when shape, size, slope,
roughness, chart number, scale number, invert elevations, or loss coefficients
differ.

Validation constraints:

- Maximum culvert groups at a crossing: 10.
- Maximum identical barrels in a group: 25.
- Every barrel needs upstream and downstream centerline stations.
- Barrel GIS data is only needed when culverts connect to 2D flow area cells.

## HDF Mapping

RASMapper stores group-level culvert metadata separately from barrel
centerlines in geometry HDF files:

| Layer | HDF path |
|-------|----------|
| Culvert Groups | `Geometry/Structures/Culvert Groups` |
| Culvert Barrels | `Geometry/Structures/Culvert Groups/Barrels` |

Group columns include `Shape ID`, `Shape Name`, `Chart ID`, `Chart Name`,
`Scale ID`, `Scale Name`, `Rise`, `Span`, `Length`, `US Distance`,
`Top Mann`, `Bot Mann`, `Depth Bot Mann`, `Depth Blocked`,
`Entrance Loss Coef`, `Exit Loss Coef`, `Invert US`, `Invert DS`, and
`Use Momentum`.

Barrel columns include `Group ID`, `Group Name`, `Barrel Name`, `US Station`,
`DS Station`, and `Default Centerline`.

Plan-result HDF storage is keyed by structure and culvert group names rather
than shape code. RASMapper exposes the relevant result-name builders and readers
through `StructureLayer.GetCulvertVariablesDataset*`,
`StructureLayer.GetCulvertGroupDataset*`, and
`CulvertGroupLayer.ReadResultVariables*`.
