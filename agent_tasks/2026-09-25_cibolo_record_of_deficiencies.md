# Cibolo (12100304) Record of Deficiencies

- **ROD date:** 2026-09-25
- **Source program / lane:** `fema_ebfe` / `integrated_2d`
- **Model system:** one 2D unsteady project with seven plans
- **Delivered / validation HEC-RAS version:** 5.07 / 5.0.7
- **Canonical 1% plan:** `p14`, geometry `g05`, unsteady flow `u02`
- **Current status:** organized; canonical plan `p14` qualified at
  `unsteady_start`
- **Immutable source:** `F:\eBFE\raw\12100304\12100304_Models.zip`
- **CEWS staging root:**
  `H:\Data Library\eBFE\26-014 CWE\data_staging\cibolo_ebfe`

## Source and delivered hydraulic inputs

| Check | Evidence |
|---|---|
| Source object | 38,827,758,483 bytes; multipart ETag `7d88e8a2b047780c8df9fd486c7bb34d-4629` |
| Archive structure | Outer archive contains the inventory and `Hydraulic_Models/_Final.zip`; the nested archive contains 258 files and 16 directories |
| Extraction audit | Zero CRC failures, size mismatches, or truncated members |
| Project inventory | `Cibolo.prj`, seven plans (`p05`-`p10`, `p14`), geometry `g05`, and unsteady files `u01`-`u07` |
| Canonical test | Current plan `p14`, title `Cibolo100YR`, binds `g05` and `u02` |

The public delivery contains the computational terrain
`Cibolo_Terrain_Burn.hdf`, its VRT and component rasters, the compiled and
raster Manning's-n land cover, seven hydrology DSS files, projection,
RASMapper configuration, geometry HDF, and supplied result HDFs. Terrain and
land cover are delivered; neither is reconstructed. The delivered terrain HDF
contains no modification groups, consistent with the model configuration.

## Required reconstruction

The audited 16-step assembly consists of one nested extraction, seven DSS
asset placements, seven active DSS path rewrites, and one RASMapper projection
rewrite. These are delivery-layout corrections, not replacements for missing
hydraulic source.

Five unresolved references remain after active-model repair:

- two user-profile Google basemap XML files;
- one profile-line shapefile used for display; and
- one backup plan geometry plus one backup unsteady DSS reference.

They are backup-only or display-only and do not block canonical plan `p14`.

## Deficiency register

| ID | Finding | Impact | Disposition |
|---|---|---|---|
| CI-001 | The runnable project is nested in `_Final.zip`. | Direct outer-archive extraction does not produce the active project tree. | Recursively extract both archive levels with traversal, collision, size, and CRC checks. |
| CI-002 | Seven active unsteady files reference DSS paths from the publisher's build system. | Active hydrology is not portable as delivered. | Stage the seven delivered DSS files under project-local `Hydrology` and rewrite only the audited references. |
| CI-003 | The RASMapper projection path does not match the organized location. | Mapping CRS resolution is not portable. | Copy the delivered projection under project-local `Projection` and apply the exact `.rasmap` rewrite. |
| CI-004 | Backup/display references are not delivered. | No canonical hydraulic-start impact; incomplete backup/display layers remain. | Retain as nonblocking deficiencies; do not invent replacements. |
| CI-005 | Initial preprocessing attempts from the H: network run copy did not reach an accepted startup signal within the bounded wait. | Network I/O obscured source-runnability assessment even though exact-process cleanup remained healthy. | Re-stage the unchanged source on fixed local I: storage and repeat through RAS Commander. The retry passed and is retained below. |

## Runtime evidence

| Project | Plan | Cores | Signal | Fresh artifacts | Elapsed | Status |
|---|---:|---:|---|---|---:|---|
| Cibolo | `p14` | 2 | `owned_process_artifacts` | `p14.tmp.hdf` 357,887,740 B; `b14` 2,677 B; `x05` 2,412 B; required legacy `c05` 2,964 B | 499.4 s | Passed |

Organization manifest (completed with active hydraulic reference closure and
`terrain_source_complete=true`):
`H:\Data Library\eBFE\26-014 CWE\data_staging\cibolo_ebfe\organized\Cibolo_12100304\agent\cibolo_manifest.json`.

Reviewed runtime receipt:
`H:\Data Library\eBFE\26-014 CWE\data_staging\cibolo_ebfe\receipts\cibolo_p14_unsteady_start_20260925_local_retry.json`.

The isolated local-fixed-disk copy was made from the unchanged organized
source. RAS Commander verified preprocessing, detected owned unsteady-solver
startup, excluded supplied result HDFs from the evidence set, and confirmed
zero matching processes after bounded cancellation. The authoritative source
and durable receipts remain on H:; fixed local storage is the execution tier
for large 2D preprocessing because the network run copies repeatedly exceeded
the bounded startup wait.

No supplied plan HDF and no static `RasCheck` record substitutes for this
fresh startup evidence. Solver start does not establish full plan completion,
stability, calibration, or numerical equivalence.

## Publication boundary

Cibolo is qualified as a source candidate at `unsteady_start`. Its example-
project footprint must come from the project geometry API, not from a bounding
box. Do not present it as a completed-result or numerical-equivalence example.
