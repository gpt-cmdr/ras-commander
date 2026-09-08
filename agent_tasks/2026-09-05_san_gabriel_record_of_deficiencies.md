# San Gabriel Record of Deficiencies (ROD)

- **ROD date:** 2026-09-05
- **Study:** FEMA San Gabriel BLE (12070205)
- **Compute evidence:** Accepted at `unsteady_start`
- **Delivery readiness:** `critical_source_gap`
- **Downstream usable:** no
- **Reproducible:** no
- **Delivered source:** `H:\s\12070205_Models`
- **Organized validation copy:**
  `H:\Testing\eBFE\12070205\organized\SanGabriel_12070205`

This record distinguishes deficiencies in the public delivery from mitigations
made in the organized validation copy. The delivered source was not modified.

## Deficiency register

| ID | Deficiency | Impact | Status / disposition |
|---|---|---|---|
| SG-001 | Every project and `2D_Model_Inventory_LBSG.xlsx` name one shared `Terrain\Terrain.hdf`, but the Models, SpatialData, Documents, and ReferenceGuide packages do not contain that compiled file. | For this 2D model, geometry preprocessing and hydraulic results cannot be faithfully reproduced from the public delivery. A supplied result HDF being viewable does not make the source usable downstream. | **CRITICAL / model-blocking.** The HDEM-only rebuild supports startup testing only. It does not cure the missing source or make the delivery publishable as a runnable, reproducible 2D example. |
| SG-002 | The HDEMs omit the `Hwy-Road Crossings (Channel)`, `Hwy-Road Crossings`, and `Lake Georgetown` elevation-modification payloads named in all five RASMapper files. No inspected report or sidecar provides reconstructable control data for them. | The reconstructed terrain is not source-equivalent and can change cell-minimum elevations and hydraulic results. | **CRITICAL / model-blocking.** Do not use the HDEM-only reconstruction for downstream hydraulic modeling, FEMA numerical reproduction, calibration, or geometry-elevation fidelity claims. Recover the original compiled terrain or complete source-equivalent terrain/modification inputs first. |
| SG-003 | LBSG_501, 503, 504, and 505 entered unsteady computation and then reported `READ_UN_HDF_XS_TAB` for a missing `Cross Sections` HDF group. LBSG_502 was stopped after positive owned-solver-start detection. | Full-plan completion and result equivalence remain unverified. | **Accepted limitation** for the user-approved `unsteady_start` threshold only. |
| SG-004 | `999999_Terrain_metadata.xml` is malformed because `Doucet & Associates` is not XML-escaped. | Automated XML parsing fails without tolerant handling or a corrected copy. | **Open documentation defect.** It does not prevent reading the HDEM rasters. |
| SG-005 | The Models archive includes a 282-character member name. A normal descriptive Windows extraction path exceeds common path limits, and an earlier non-atomic retry could mistake a partial destination for success. | Extraction may fail silently or leave an incomplete model tree. | **Mitigated in ras-commander.** The extractor is atomic, Windows long-path aware, timestamp preserving, and validates every member by path, size, and CRC32. The active workspace follows `H:\Testing\eBFE\<HUC8>\{raw,organized,runs,reports}`. |
| SG-006 | `RasProcess.exe CreateTerrain` returned code 0 and produced a structurally valid HDF, but emitted a non-fatal stderr warning whose text was not retained because DEBUG logging was not enabled. | No observed build failure; the warning cannot be independently classified from the retained log. | **Monitor.** Retain the validated HDF/hash. Rebuild with DEBUG logging if exact warning provenance becomes necessary. |
| SG-007 | The first isolated LBSG_503 `p04` reconstructed-terrain run completed geometry preprocessing, but HEC-RAS 6.3 could not execute the removed Windows `wmic` utility. `RasUnsteady.exe` reached end-of-file reading its empty `systemInfo.txt` and exited with code 24. | The attempt produced only a 13,369-byte summary HDF and no hydraulic result datasets. The failure was a host/runtime compatibility issue, not evidence that the reconstructed terrain failed preprocessing. | **Mitigated and verified in ras-commander.** HEC-RAS 6.3 launches with a process-local, CPU-query-only WMIC compatibility shim backed by Windows CIM. A fresh isolated two-core rerun finished successfully and passed RAS Commander completion verification. The library does not install a Windows feature, change the system PATH, or expose a new public parameter. The failed run remains preserved. |

## HDEM-only terrain reconstruction

The three HDEMs form one watershed-wide source and were used to create one
shared terrain for LBSG_501 through LBSG_505. No separate per-model terrain was
created.

- API: `RasTerrain.create_terrain_hdf(...)`
- HEC-RAS terrain engine: 6.3
- Build host: native Windows
- Raster order: `HDEM_1.tif`, `HDEM_2.tif`, `HDEM_3.tif`
- Projection: delivered
  `Projection_NAD_1983_StatePlane_Texas_Central_FIPS_4203_Feet.prj`
- Units: feet
- Stitching: enabled
- Runtime: approximately 4 minutes 14 seconds
- Output:
  `H:\Testing\eBFE\12070205\organized\SanGabriel_12070205\RAS Model\Terrain\Terrain.hdf`
- Output size: 22,088,515 bytes
- SHA-256:
  `7b012fd68e8bdc7870180a223d85091592f02853fc64566a4dfe3927c18a33be`

The three Float32 inputs are 10-foot rasters in EPSG:2277 with NAVD88 feet
metadata. Their pairwise valid-data overlaps are negligible and equal where
they overlap, so the recorded order is deterministic but did not introduce a
material overlap-priority choice.

## Post-build validation

- `RasTerrain._validate_terrain_hdf(...)` passed.
- The HDF contains 27 groups and 75 datasets.
- Terrain GUID: `1286bb1f-9910-4425-8eb3-f20748d32970`.
- The terrain contains source layers `Terrain.HDEM_1`, `Terrain.HDEM_2`, and
  `Terrain.HDEM_3`, plus stitch datasets.
- All five `.rasmap` files parse to the same shared output.
- All 40 terrain and elevation-modification references match that output and
  exist after the build.
- No geometry HDF was reassociated or modified after terrain creation.

## Documentation evidence

The model inventory names one shared terrain for all five projects. The terrain
narrative describes a watershed-wide seamless 10-foot DEM mosaic but does not
identify a compiled HEC-RAS terrain delivery. The terrain metadata and QA/QC
documents describe the HDEM while leaving terrain-modification documentation
unresolved. The certification calls the submitted files complete/final but
does not identify an exception or an alternate location for `Terrain.hdf`.

The derived terrain therefore resolves the runtime path deficiency for the
organized validation copy, but it does not cure the critical source-fidelity
gap or make the public 2D delivery reproducible or usable downstream.

## LBSG_503 hydraulic comparison

The first isolated two-core `p04` run rebuilt the 2D property tables from the
HDEM-only terrain and entered the unsteady solver, then stopped at SG-007 before
hydraulic output began. Evidence is retained at:

`H:\Testing\eBFE\12070205\runs\503_1pct_rebuilt_20260905`

A fresh copy was rerun after the scoped RAS Commander compatibility mitigation
at:

`H:\Testing\eBFE\12070205\runs\503_1pct_rebuilt_wmicfix_20260905`

The rerun finished `Unsteady Finished Successfully` in 29 minutes 30 seconds,
and RAS Commander verified completion. The supplied FEMA `p04` result is
preserved separately within each run folder.

The reconstructed-terrain run is **hydraulically reasonable for startup and QA
screening**, but it is not numerically source-equivalent:

- all 124,511 wet cells match the supplied result;
- maximum WSE mean absolute difference is 0.205 ft, with 95 percent within
  0.737 ft and 96.58 percent within 1 ft;
- maximum depth mean absolute difference is 0.231 ft across 122,457 comparable
  cells, with 95 percent within 0.927 ft and 95.39 percent within 1 ft;
- volume-accounting error is 0.0236 percent versus 0.0193 percent supplied; and
- localized maxima reach 43.761 ft for WSE and 32.141 ft for depth, while
  boundary outflow is 1,429.734 acre-feet higher and ending storage is
  1,427.807 acre-feet lower.

The complete comparison and top spatial outliers are retained under the rerun
folder as `hydraulic_comparison.md`, `hydraulic_comparison.json`,
`hydraulic_comparison.csv`, and `hydraulic_outliers.csv`. The localized
differences reinforce SG-002: the HDEM-only reconstruction is appropriate for
this validation threshold, not FEMA numerical reproduction or calibration.
