# Upper Guadalupe (12100201) Record of Deficiencies

**Study:** FEMA eBFE Upper Guadalupe, HUC8 12100201  
**Area:** Kerr County and the Upper Guadalupe watershed, Texas  
**Model suite:** UPGU1 → UPGU2 → UPGU3 → UPGU4  
**Status:** source qualification candidate; UPGU1 unsteady-start qualified

This record distinguishes the publisher-supplied result artifacts from fresh
execution evidence. The delivery includes plan HDF result files, but those files
do not demonstrate that the reconstructed portable copy will run. Only UPGU1
may be described as unsteady-start validated. UPGU2–UPGU4 remain unqualified.

## Source identity and archive validation

The immutable source is
`F:\eBFE\raw\12100201\12100201_Models.zip`. It was pinned from the FEMA eBFE
object at
`https://ebfedata.s3.amazonaws.com/12100201_UpperGuadalupe/12100201_Models.zip`.

| Check | Evidence |
|---|---|
| Object size | 58,575,220,457 bytes |
| ETag | `67e7b10db40c2659eee9a5f1e6032b47-6983` |
| ZIP inventory | 277 files and 23 directories |
| Extraction validation | zero member-extraction failures and zero ZIP CRC failures |
| Projects | four of four projects opened during the source audit |
| Authored HEC-RAS version | 6.3.1 for all four projects |
| Model type | 2D unsteady |

No source folder is edited in place. Reconstruction and computation use an
independent staged copy.

## Delivered hydraulic source

Each project registers seven unsteady plans: `p01` through `p07`. These cover
the 1%, 0.2%, 10%, 4%, 2%, lower 1%, and upper 1% annual-chance conditions.
The archive also supplies the geometry, unsteady-flow inputs, DSS data,
infiltration and soils data, projection, RASMapper configuration, preprocessed
geometry HDF, and 28 plan HDF result artifacts.

### Terrain completeness

Terrain is delivered for all four projects. Each delivery includes its complete
terrain triplet, rather than an HDEM-only substitute. The terrain is not a
generic unmodified surface:

- UPGU1, UPGU2, and UPGU3 contain channel terrain modifications.
- UPGU4 contains channel and polygon terrain modifications.
- The four RASMapper configurations contain five terrain-modification elements
  in total.

These terrain modifications are hydraulically material. They must be retained
and associated with the correct geometry during staging; replacing any of the
delivered terrain HDFs with a newly compiled bare-earth surface would invalidate
repeatability. The fail-closed organizer verifies all 12 terrain payload files
(four HDF/VRT/raster triplets) and the exact five `/Modifications` groups before
setting `terrain_source_complete`.

## Reconstruction findings

The detailed audit emitted 392 recipe rows. After duplicate action identities
are collapsed, those rows represent 344 unique actions; 293 were classified as
blocking by the audit. The raw rows comprise:

| Recipe family | Rows | Required treatment |
|---|---:|---|
| Output-to-Input asset placement | 56 | Relocate or copy within the staged delivery only |
| HDF path attributes | 196 | Rewrite to staged, path-equivalent targets |
| DSS references | 41 | Rewrite to delivered staged DSS files |
| Plan text references | 28 | Rewrite to staged plan dependencies |
| RASMapper references | 71 | Rewrite to staged projection, terrain, and result assets |

The recipe's 196 HDF rows cover the seven association attributes in each of
the 28 supplied plan HDFs. Native HEC-RAS execution exposed an additional
blocking omission: the same seven stale associations were still embedded in
each of the four geometry HDFs. The geometry writer consequently reported the
land-cover and infiltration files missing and refused to enter hydraulics.
The portable-source contract therefore covers **224 HDF attributes**: 196 in
plan HDFs plus 28 in geometry HDFs.

A second native attempt exposed an HDF serialization constraint not visible in
ordinary path comparison. HEC-RAS 6.3.1 rejected variable-length HDF string
attributes with `Illegal characters in path`; the delivered attributes are
fixed-length byte strings. The organizer now preserves that native storage
type while rewriting all 224 values. The retained repair receipt is
`H:\Data Library\eBFE\26-014 CWE\data_staging\upper_guadalupe_ebfe\receipts\upper_guadalupe_geometry_hdf_repair.json`.

The audit report describes the 56 Output-to-Input assets as if they had been
"shipped in a separate archive." That wording is incorrect. All 56 source
assets are members of the same `12100201_Models.zip`; reconstruction changes
their organized location, not the source corpus.

The archive delivers the common coordinate-system file only under UPGU1 even
though the UPGU2–UPGU4 RASMapper files reference a project-local copy. The
organizer verifies that single delivered file, materializes a byte-identical
copy for each project, and rewrites each `.rasmap` to its local portable path.
This is a packaging/path deficiency, not a missing coordinate system.

The rendered report also says that 20 DSS references resolve. Independent
review found 21 of 21 audited DSS records resolve once the portable path
corrections are applied. The archive contains ten DSS files across the four
projects; the active records represent project-local precipitation and the
three upstream-to-downstream transfer families.

## Actual source omissions

Independent review reduced the apparent gap list to 21 distinct undelivered
files across 155 references:

| Missing class | Files | References | Hydraulic-start impact |
|---|---:|---:|---|
| Result VRTs | 14 | 144 | RASMapper result-display deficiency; not a source-compute input |
| Stale or unregistered result-HDF names | 4 | 6 | Result/display reference deficiency; not an active hydraulic input |
| GIS/profile/QC variants | 3 | 5 | GIS or QA/QC deficiency; not a solver-start input |

The missing VRTs prevent a claim that every supplied RASMapper result layer is
complete. They do not mean that terrain is missing, and they do not block the
selected source plans from entering computation. The supplied result HDFs may
still be inspected as published artifacts, but they are not a substitute for
fresh source-run evidence.

## Fresh pre-compute qualification

The required acceptance point is an owned unsteady-solver process or equivalent
fresh compute artifact observed after successful preprocessing. A solver-start
observation is not a completed-result, stability, calibration, or hydraulic
accuracy claim.

| Project | Selected plan | Cores | Preprocessing | Unsteady solver start | Evidence |
|---|---|---:|---|---|---|
| UPGU1 | `p01` (`UPGU1_1pct`) | 2 | Passed | Passed | `owned_process_artifacts`; 717.84 s; fresh 326,866,279-byte `.tmp.hdf`, 2,791-byte `.b01`, and 2,480-byte `.x01` |
| UPGU2 | `p01` (`UPGU2_1pct`) | 2 | Failed/no proof | Not established | Property-table rebuilding was observed, but the receipt records `natural_completion` without owned solver-start evidence |
| UPGU3 | `p01` (`UPGU3_1pct`) | 2 | Not run | Not established | Not attempted |
| UPGU4 | `p01` (`UPGU4_1pct`) | 2 | Not run | Not established | Not attempted |

The retained runtime receipt is
`H:\Data Library\eBFE\26-014 CWE\data_staging\upper_guadalupe_ebfe\receipts\upper_guadalupe_20260925T161515Z_unsteady_start.json`.
It records UPGU1's successful owned-process signal and UPGU2's failed/no-proof
outcome. The public registry therefore uses `validation_status="partial"`; it
does not promote UPGU2–UPGU4 or claim full-plan completion.

## Project-specific records

### UPGU1

UPGU1 is the upstream member of the cascade. It has plans `p01`–`p07`, a
delivered modified-terrain triplet with channel modifications, and seven
publisher-supplied plan HDF result artifacts. Its selected `p01` reached the
unsteady solver in the isolated two-core qualification copy.

### UPGU2

UPGU2 is the second member of the cascade. It has plans `p01`–`p07`, a
delivered modified-terrain triplet with channel modifications, and seven
publisher-supplied plan HDF result artifacts. Fresh solver-start qualification
was not established.

### UPGU3

UPGU3 is the third member of the cascade. It has plans `p01`–`p07`, a
delivered modified-terrain triplet with channel modifications, and seven
publisher-supplied plan HDF result artifacts. Fresh solver-start qualification
was not attempted.

### UPGU4

UPGU4 is the downstream member of the cascade. It has plans `p01`–`p07`, a
delivered modified-terrain triplet with channel and polygon modifications, and
seven publisher-supplied plan HDF result artifacts. Fresh solver-start
qualification was not attempted.

## Dashboard and publication contract

The example-project dashboard represents the suite as one grouped table entry
with four selectable subprojects. Each map feature remains the exact
API-derived UPGU1–UPGU4 footprint; no footprint may be replaced with a bounding
box or a single watershed envelope. Until a hosted viewer is requalified, each
subproject and the grouped suite link to this durable record instead of relying
on a dead viewer manifest.

Publication language must preserve these boundaries:

- **Published artifacts:** supplied plan HDFs and other result assets in the
  FEMA archive.
- **Source qualification:** portable reconstruction for all four projects;
  fresh unsteady-start evidence applies only to UPGU1.
- **Not established by solver start:** completed results, numerical stability,
  calibration quality, or equivalence to the publisher-supplied result files.
