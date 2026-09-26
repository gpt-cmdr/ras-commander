# Pedernales (12090206) Record of Deficiencies

- **ROD date:** 2026-09-25
- **Source program / lane:** `fema_ebfe` / `integrated_1d`
- **Model system:** 530 independent 1D steady-flow projects
- **Delivered HEC-RAS version:** 4.10 (4.1)
- **Validation engine:** HEC-RAS 6.6 through RAS Commander
- **Current status:** organized and qualified; 530/530 selected `p01` plans passed
- **Immutable source:** `F:\eBFE\raw\12090206\12090206_Models.zip`
- **CEWS staging root:**
  `H:\Data Library\eBFE\26-014 CWE\data_staging\pedernales_ebfe`

This record distinguishes verified source assembly from fresh HEC-RAS
execution. The organizer receipt proves archive identity, extraction, repair,
and active-reference closure. The aggregate runtime receipt independently
records one completed selected plan for every one of the 530 path-identified
projects.

## Source and organization evidence

| Check | Evidence |
|---|---|
| Source object | 138,116,094 bytes; multipart ETag `b73ad7fff398baa8132d40296a0e30ee-9` |
| Extraction | 5,109 files and 1,066 directories; 570,955,840 extracted bytes; size and CRC-32 verified |
| Project inventory | 530 `.prj` files; each selected `p01` chain resolves to `g01` and `f01` |
| Repairs | Eight delivered geometry/result/preprocessor assets copied to the three project folders that reference them; source copies retained |
| Active-reference audit | 530 projects closed with no errors in the organizer manifest |
| Organization manifest | `H:\Data Library\eBFE\26-014 CWE\data_staging\pedernales_ebfe\organized\Pedernales_12090206\agent\pedernales_manifest.json` |

The eight repairs affect MIDDLE CREEK, EAST FORK ROCKY CREEK, and WHITE OAK
CREEK. They correct delivery placement only. They do not synthesize hydraulic
inputs or modify the immutable archive.

## Terrain finding

Terrain is **not applicable** to this 1D steady corpus. None of the 530 active
models references terrain, land cover, infiltration, soils, or a RASMapper
terrain layer. Their absence is not a deficiency and must not be represented
as missing 2D source data.

## Deficiency register

| ID | Finding | Impact | Disposition |
|---|---|---|---|
| PE-001 | Eight delivered HDF/compute-message assets are stored under model folders other than the three projects that reference them. | The affected organized projects are incomplete until the delivered bytes are placed at their referenced locations. | Copy the exact delivered assets in the staged tree and verify source/destination size and CRC-32; retain both source locations. |
| PE-002 | HEC-RAS 4.1 is not installed on the validation host. | Native authored-version execution is unavailable. | Run the selected plans with the installed HEC-RAS 6.6 engine and record that version in every receipt. |
| PE-003 | The first 11-way batch produced 34 inconclusive safety-gate rejections when concurrent HEC-RAS processes made exact-process inventories incomplete. | Those records did not establish model failure or success. | Rerun only the 34 affected projects serially. All 34 passed; the reviewed aggregate now contains 530 unique passing source paths. Closed. |

## Runtime evidence

All 530 selected plan-01 computations ran from isolated copies through RAS
Commander with HEC-RAS 6.6 and two cores per plan. The aggregate receipt
contains 530 unique `source_folder` identities, 530 passing records, zero
remaining failures, and only plan `01`. The authored HEC-RAS 4.10 engine was
not available, so this evidence establishes compatibility and runnability in
6.6; it does not assert numerical identity with a native 4.10 execution.

The initial sharded pass yielded 496 conclusive passes and 34 safety-gate
rejections. Those 34 were rerun serially after a complete, empty HEC-RAS
process inventory was confirmed; every retry passed. The aggregate receipt
uses each successful retry in place of its inconclusive first attempt.

| Scope | Selected plan | Current evidence | Status |
|---|---:|---|---|
| `PEDERNALES RIVER` mainstem | `01` | `H:\Data Library\eBFE\26-014 CWE\data_staging\pedernales_ebfe\receipts\steady_mainstem_20260925\steady_plan_validation_20260925_133255.json` | Passed |
| Other 529 projects | `01` | Eleven sharded receipts plus 34 serial retry receipts | Passed |
| Full corpus | one plan per project | `H:\Data Library\eBFE\26-014 CWE\data_staging\pedernales_ebfe\receipts\steady_all_20260925\steady_plan_validation_20260925_140300.json` | **530/530 passed** |

The aggregate was accepted only after reconciling 530 terminal records, 530
unique source paths, the single selected plan number, and zero unresolved
failures. The individual sharded and retry receipts remain the detailed
process and compute-message evidence.

## Publication boundary

Pedernales may be cataloged as an organized and HEC-RAS 6.6-qualified
530-project source corpus. The example-project map uses one exact union of the
530 model footprints rather than 530 discovery rows. No hosted PMTiles or
completed-result viewer is claimed; a display derivative would not replace the
project inventory or runtime receipts.
