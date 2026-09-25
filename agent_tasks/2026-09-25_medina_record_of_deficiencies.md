# Medina (12100302) Record of Deficiencies

- **ROD date:** 2026-09-25
- **Source program / lane:** `fema_ebfe` / `integrated_2d`
- **Model system:** five HEC-RAS 6.4.1 2D unsteady projects
- **Current status:** organized; four source-complete projects qualified at
  `unsteady_start`; UpperMedinaHeadwaters blocked by a critical source gap
- **Immutable source:** `F:\eBFE\raw\12100302\12100302_Models.zip`
- **CEWS staging root:**
  `H:\Data Library\eBFE\26-014 CWE\data_staging\medina_ebfe`

## Source identity and recoverable archive

The public source is 52,085,665,792 bytes with multipart ETag
`5474dc597ff3a2fb4418a59807a439ff-6210`. The object matches FEMA's retained
size and ETag, but the publisher's ZIP itself ends inside one compressed
member. A streaming audit recovered and CRC-verified 407 files. Exactly one
member is unrecoverable:

```text
Engineering Models/Hydraulic Models/UpperMedinaHeadwaters/Output/UpperMedinaHW.p01.hdf
```

That file is a supplied **result HDF** for plan `p01`. Its truncation is a real
delivery defect, but it does not prevent source computation and is not the
critical hydraulic-source gap described below. The organizer accepts only
this exact publisher truncation and fails closed if any other member is short
or fails CRC/size verification.

## Project and supporting-data inventory

| Project | Selected 1% plan | Compiled modified terrain | Runtime status |
|---|---:|---|---|
| Leon1 | `p01` | Delivered; `Terrain (1).hdf`, `Channels` modification | Qualified: unsteady start |
| Leon2 | `p03` | Delivered; `Terrain (1).hdf`, `Channels` modification | Qualified: unsteady start |
| Leon3 | `p02` | Delivered; `Terrain (1).hdf`, `Channels` modification | Qualified: unsteady start |
| MiddleLowerMedina (`MLM`) | `p03` | Delivered; `Terrain_Clipped.hdf`, `Channels` modification | Qualified: unsteady start |
| UpperMedinaHeadwaters | `p04` | **Not delivered**; required `UpperMedinaHW_TerrainModifications` group unavailable | Blocked source gap |

Land cover, infiltration, and soils are delivered for **all five** projects.
They require association/path repair in the staged copy; they are not missing
source data. DSS inputs and project CRS material are likewise assembled from
delivered members. Optional basemap, profile/display, and supplied-result
references that remain unresolved must not be conflated with active hydraulic
source inputs.

## Critical terrain deficiency

UpperMedinaHeadwaters references a compiled `Terrain.hdf` containing the
load-bearing `UpperMedinaHW_TerrainModifications` group. The public delivery
does not contain that HDF. This is a critical deficiency for a 2D model: the
project is not repeatable, downstream-usable, or source-runnable merely because
other raster inputs or supplied result artifacts can be viewed. A bare DEM
rebuild would not reproduce the missing terrain modifications and must not be
silently substituted.

The other four projects include their compiled modified terrain and are not
terrain-deficient. The deficiency applies specifically to
UpperMedinaHeadwaters, not to the whole five-project inventory.

## Reconstruction boundary

The fail-closed organizer recovers the 407 verified members, performs 68
delivered Output-asset placements, stages four local projection copies and
rewrites their RASMapper paths, and repairs one DSS path. It verifies the
fixed-length active-geometry HDF path associations; all were already
path-equivalent, so it made zero HDF attribute updates and zero supplied-result
HDF changes. It does not synthesize the missing UpperMedinaHeadwaters terrain
or claim HEC-RAS execution.

## Deficiency register

| ID | Finding | Hydraulic impact | Disposition |
|---|---|---|---|
| ME-001 | UpperMedinaHeadwaters' compiled modified `Terrain.hdf` is absent. | Critical. The active 2D geometry cannot reproduce its referenced terrain modifications; the project is unusable downstream. | Obtain the original compiled modified terrain or an authoritative source-equivalent replacement. Keep the project blocked until then. |
| ME-002 | The FEMA ZIP is publisher-truncated inside `UpperMedinaHW.p01.hdf`. | Supplied-result loss for one plan; not a source-compute blocker. | Record the exact unrecoverable member, recover the other CRC-valid members, and never present the truncated result as complete. |
| ME-003 | Delivered active assets and path associations are not portable in their archive locations. | Four source-complete projects need deterministic assembly before testing. | Apply only the audited relocations and path repairs in a staged copy; preserve the immutable source. |
| ME-004 | Initial preprocessing attempts from H: network run copies exceeded the bounded startup wait. | Network I/O obscured assessment of the four otherwise source-complete projects. | Re-stage unchanged source copies on fixed local I: storage. All four local retries reached owned unsteady-solver startup and passed the gate. |

## Runtime evidence

| Project | Plan | Cores | Signal | Fresh preprocessing artifacts | Elapsed | Status |
|---|---:|---:|---|---|---:|---|
| Leon1 | `p01` | 2 | `owned_process_artifacts` | `tmp.hdf` 616,595,927 B; `b01` 2,724 B; `x01` 2,475 B | 1,158.6 s | Passed |
| Leon2 | `p03` | 2 | `owned_process_artifacts` | `tmp.hdf` 190,690,460 B; `b03` 2,724 B; `x01` 2,475 B | 436.3 s | Passed |
| Leon3 | `p02` | 2 | `owned_process_artifacts` | `tmp.hdf` 111,813,767 B; `b02` 3,853 B; `x01` 15,255 B | 290.2 s | Passed |
| MiddleLowerMedina | `p03` | 2 | `owned_process_artifacts` | `tmp.hdf` 376,861,613 B; `b03` 2,744 B; `x01` 19,170 B | 966.4 s | Passed |
| UpperMedinaHeadwaters | `p04` | 2 | Original modified terrain must first be supplied | Blocked; do not run as qualified source |

Organization manifest (completed with four source-complete projects and the
UpperMedinaHeadwaters source block preserved):
`H:\Data Library\eBFE\26-014 CWE\data_staging\medina_ebfe\organized\Medina_12100302\agent\medina_manifest.json`.

Reviewed runtime receipts:

- `medina_leon1_p01_unsteady_start_20260925_local_retry.json`
- `medina_leon2_p03_unsteady_start_20260925_local_retry.json`
- `medina_leon3_p02_unsteady_start_20260925_local_retry.json`
- `medina_mlm_p03_unsteady_start_20260925_local_retry.json`

They are retained under
`H:\Data Library\eBFE\26-014 CWE\data_staging\medina_ebfe\receipts`.
Each records an unchanged organized source, complete fresh preprocessing
artifacts, accepted owned-process evidence, and zero surviving exact process
matches. Fixed local I: storage is the execution tier for large 2D
preprocessing; authoritative organized sources and durable receipts remain on
H:. This avoids treating a network-I/O timeout as a model failure.

No static audit or publisher-supplied result HDF is fresh computation evidence.
Solver start for the four complete projects does not establish full-plan
completion or numerical equivalence.

## Publication boundary

The example-project entry must retain all five submodel footprints and show
project-level status. Leon1, Leon2, Leon3, and MiddleLowerMedina are qualified
at `unsteady_start`. UpperMedinaHeadwaters must remain
visibly `critical_source_gap`; grouping it with the four complete projects must
not imply that its missing modified terrain is supplied.
