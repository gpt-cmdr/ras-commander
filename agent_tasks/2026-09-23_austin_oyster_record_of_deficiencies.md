# Austin–Oyster Record of Deficiencies

- **ROD date:** 2026-09-23
- **Study:** FEMA Austin–Oyster eBFE
- **Study key / HUC8:** `12040205`
- **Source program / lane:** `fema_ebfe` / `integrated_2d`
- **Delivered HEC-RAS version:** 5.07
- **Model system:** one 2D unsteady project with seven registered plans
- **Audit state:** `audited`
- **Runtime qualification:** `unsteady_start`; independent pre-compute evidence
  reached an owned HEC-RAS 5.0.7 unsteady solver for plan `p08`
- **Immutable source record:** `F:\eBFE\raw\12040205`
- **Audit evidence:** `F:\eBFE\audit\12040205`
- **CEWS staging target:**
  `H:\Data Library\eBFE\26-014 CWE\data_staging\austin_oyster_ebfe`

This record separates delivered-source deficiencies, deterministic assembly
actions, and validation evidence. The eBFE audit is a replayable static
reconstruction record. Independent CEWS validation now establishes
preprocessing and unsteady-solver startup, but not a completed plan or
reproduction of the supplied results.

## Independent evidence assessment

The retained audit reports one 24,083,078,085-byte source archive whose size
matches its source sidecar. ZIP CRC-32 verification completed without CRC,
size, truncation, or unsafe-path failures. The archive contains 48 top-level
members and five nested archives. Complete recursive extraction produced 149
files totaling 24,411,258,917 bytes before assembly.

RAS Commander discovered and loaded one project:

```text
RAS Model\Hydraulic_Models\RAS_Submittal\Input\AustinOyster.prj
```

The project registers geometry `g02`, seven unsteady-flow files (`u01` through
`u07`), and seven plans (`p03` through `p09`): 10%, 4%, 2%, 1%-minus,
1%-plus, 1%, and 0.2% annual-chance events. The delivered project identifies
HEC-RAS version 5.07. Static inspection classifies it as 2D unsteady.

## Delivered hydraulic and mapping inputs

The public delivery contains the load-bearing resources required by its own
project configuration:

| Element | Delivered evidence |
|---|---|
| Compiled terrain | `Terrain\Terrain.hdf` |
| Terrain raster and VRT | `Terrain.DEM_10FT_Corrected.tif`; `Terrain.vrt` |
| Land cover | `LandCover\Landcover.tif` and compiled land-cover HDF |
| DSS hydrology | Seven referenced event DSS files; all seven pathnames independently reverified against delivered catalogs |
| Projection | `NAD_1983_2011_StatePlane_Texas_South_Central_FIPS_4204_FtUS.prj` |
| RASMapper configuration | `AustinOyster.rasmap` |
| Geometry | `AustinOyster.g02` and `AustinOyster.g02.hdf` |
| Supplied results | Seven plan HDFs, `AustinOyster.p03.hdf` through `AustinOyster.p09.hdf` |

The delivered `Terrain.hdf` is not missing and was not reconstructed. The
audit inspected its `/Modifications` content and found no modification groups.
The delivered `.rasmap` likewise contains no terrain-modification layers. This
agreement is the applicable ground truth: an organizer must preserve the
delivered terrain rather than manufacture, rebuild, or silently substitute it.

## Exact reconstruction ledger

The audit report proposed a 48-action reconstruction ledger. Independent
replay refined that proposal into the following observed operations and checks:

| Action class | Count | Purpose |
|---|---:|---|
| Recursive nested-archive extraction | 6 | Expand the outer archive, `RAS_Submittal.zip`, and its `Input.zip`, `LandCover.zip`, `Output.zip`, and `Terrain.zip` children while collapsing the repeated archive prefix. |
| `Output` to `Input` relocations | 14 | Move seven initial-condition files and seven supplied plan HDFs into the project directory expected by the project and RASMapper configuration. |
| Projection asset relocation | 1 | Move the delivered projection from the project root into the standardized `Projection` subdirectory. |
| Plan-HDF path attributes checked | 28 | Check four terrain/land-cover attributes in each supplied plan HDF. All 28 delivered values were already path-equivalent; zero were changed. |
| RASMapper projection correction | 1 | Change the projection reference from the project root to the delivered `Projection` subdirectory. |
| **Actual model-file relocations/edits** | **16** | Fifteen relocations and one RASMapper edit; no HDF mutation. |

The webmap reports **29 repair steps** because it counts 28 proposed plan-HDF
attribute mutations plus one `.rasmap` edit. Independent reconstruction of the
immutable archive classified all 28 HDF attributes as already path-equivalent
and preserved them unchanged. The audit's 44 structured rows remain useful as
an association/check surface, but they must not be reported as 44 delivered-
file deficiencies or actual mutations.

All repairs belong in a staged working copy. They do not authorize changes to
`F:\eBFE\raw\12040205` or imply that delivered source bytes were rewritten.

## Deficiency register

| ID | Finding | Hydraulic impact | Disposition |
|---|---|---|---|
| AO-001 | `AustinOyster.rasmap` references `%LocalAppData%\HEC\Mapping\506\XML\Google Map.xml`, which is not in the delivery. | None. This is an optional local basemap definition. | Preserve as a documented display-only omission; do not invent or redistribute a user-profile XML file. |
| AO-002 | `AustinOyster.rasmap` references `%LocalAppData%\HEC\Mapping\506\XML\Google Hybrid.xml`, which is not in the delivery. | None. This is an optional local basemap definition. | Preserve as a documented display-only omission; do not invent or redistribute a user-profile XML file. |
| AO-003 | Fourteen supplied project assets reside under delivered `Output` even though the reconstructed project expects them in `Input`. | The initial-condition and result HDF files are present but not portable in the delivery layout. | Deterministically relocate them in the staged copy; preserve the raw archive unchanged. |
| AO-004 | The audit classified 28 terrain/land-cover path attributes as repair steps, but independent replay found all 28 delivered values already path-equivalent. | None established from these attributes; rewriting them would create unnecessary source drift. | Check all 28 values, preserve equivalent delivered bytes, and fail closed on any conflicting nonempty value. |
| AO-005 | The RASMapper projection reference points to the project root rather than the delivered `Projection` directory. | Mapping/project CRS resolution is not portable as delivered. | Apply the single recorded `.rasmap` path correction in the staged copy. |
| AO-006 | The retained audit contains static checks only. `RasCheck` sampled plan `p03`, selected the `UNSTEADY` family, and recorded one error, but its audit record does not retain the error text. | Static parsing and `RasCheck` cannot prove geometry preprocessing or unsteady-solver startup. | Keep status at reconstruction/validation candidate until fresh RAS Commander execution evidence records solver startup, selected plan/version/cores, owned process artifacts, messages, and disposition of the sampled error. |

The independent gap review examined three scanner findings through the archive
member index. It confirmed AO-001 and AO-002 as real. It reclassified the third
finding—a `Backup.u01` DSS reference—as an analysis gap because the referenced
`25yr.dss` exists inside the nested `Input.zip`; the reconstruction recipe now
records how recursive extraction resolves it. There are therefore exactly two
undelivered files and two unresolved references, both display-only XML files.
No reviewed hydraulic input is missing.

## Static validation boundary

The audit records:

- one of one project loaded through RAS Commander;
- seven registered plans and seven registered unsteady-flow files;
- delivered and parsed geometry, geometry HDF, RASMapper configuration,
  terrain, land cover, projection, DSS inputs, and supplied result HDFs;
- zero unresolved absolute paths after standardization;
- seven of seven DSS boundaries resolved after independent reverification; and
- static `RasCheck` outcome `RAN`, with plan `p03` sampled and one error
  counted.

`RasCheck` is not HEC-RAS computation. The retained audit did not start
`Ras.exe`; the independent CEWS run did. On 2026-09-24, ras-commander
preprocessed plan `p08` (`1PAC`) with HEC-RAS 5.0.7 and two 2D cores, then
detected the owned `RasUnsteady64.exe` child together with fresh nonempty
`.p08.tmp.hdf`, `.b08`, `.x02`, and refreshed `.c02` artifacts. The corrected
run returned success in 64.9 seconds with signal source
`owned_process_artifacts`, and `verify_preprocessing("08")` returned true.
The solver was stopped at that boundary; no completed-plan claim is made.

The first bounded attempt exposed a ras-commander compatibility defect: the
owned-process detector recognized `RasUnsteady.exe` but not HEC-RAS 5.0.7's
`RasUnsteady64.exe`. That attempt reached unsteady computation but timed out at
7,200 seconds before owned cleanup. The detector was corrected with exact-name
tests, and the successful retry validates the repair against this model.

## CEWS staged-copy requirements

The CEWS working copy belongs under job `26-014 CWE` at:

```text
H:\Data Library\eBFE\26-014 CWE\data_staging\austin_oyster_ebfe
```

The staged copy contains the recursively extracted delivery, the independently
refined reconstruction, a source/audit provenance receipt, and validation
reports. It must not overwrite or masquerade as the immutable source. Any
runtime qualification must use an isolated run copy and invoke HEC-RAS only
through RAS Commander APIs.

## Qualification and publication gates

Austin–Oyster may be cataloged as an **unsteady-start-qualified source and
geometry example**. It must not be labeled completed-result validated or
numerically equivalent to the supplied results. Those stronger states require:

1. an independently verified CEWS staged copy matching the refined ledger;
2. RAS Commander project/path validation against that copy;
3. a completed native run and hydraulic-result review;
4. review of completion messages, including reconciliation of the static
   `RasCheck` error count;
5. confirmation that delivered terrain, land cover, DSS data, and projection
   remain the inputs actually used; and
6. separate geometry/result artifact and browser-publication checks before any
   viewer URL is activated.

No completed-result or numerical-equivalence claim is asserted by this record.
