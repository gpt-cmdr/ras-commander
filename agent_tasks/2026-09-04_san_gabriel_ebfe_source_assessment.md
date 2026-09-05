# San Gabriel eBFE source assessment

**Assessment date:** 2026-09-04

**Source dataset:** FEMA Region 6 San Gabriel, `12070205_Models.zip`

**Purpose:** qualify the Round Rock/Florence San Gabriel models as a RAS
Commander eBFE source and future example project.

## Outcome

The archive contains five linked HEC-RAS 6.3 projects, not one monolithic 2D
model. Models 501–504 run independently and provide DSS boundary records to
downstream model 505. Round Rock is inside model 504. Florence is nearest model
503 and approximately 1.23 miles outside its 2D perimeter, so no single project
contains both city centers.

One 1% annual-chance plan per project was tested through RAS Commander. All
five reached the agreed verification threshold: HEC-RAS entered the unsteady
simulation phase. This is a startup smoke test, not proof that every plan
completes or reproduces the FEMA results.

The delivered package is not self-contained for geometry recomputation. Every
`.rasmap` references the same shared `RAS_Submittal\Terrain\Terrain.hdf`, and
`2D_Model_Inventory_LBSG.xlsx` lists that same file for every model. The
inventory defines the intended hydraulic delivery as separate Terrain, Land
Cover, Input, and Output ZIPs, but the compiled terrain is absent from the
Models, SpatialData, Documents, and ReferenceGuide downloads. This is a
documented delivery deficiency, not only an inferred missing runtime asset.

## Download and extraction audit

- Source URL: `https://ebfedata.s3.amazonaws.com/12070205_SanGabriel/12070205_Models.zip`
- Downloaded ZIP: `H:\Testing\eBFE Model Organization\Downloads\12070205_Models.zip`
- ZIP size: 25,588,106,947 bytes (23.83 GiB)
- Validated extraction: `H:\s\12070205_Models`
- Extraction audit: 992 archive members; 34,683,203,245 extracted bytes; zero
  missing members; zero size mismatches.
- The longest ZIP member name is already 282 characters before a destination
  is added. Its path was 287 characters under the short `H:\s` diagnostic
  extraction and would be longer than 300 characters under a descriptive raw
  cache. Normal Windows extraction failed there, and the existing downloader
  then treated the non-empty partial destination as complete on retry.
- The existing component extractor preserved file bytes but not archive member
  timestamps. HEC-RAS uses those timestamps to decide whether terrain,
  Manning's n, and infiltration associations changed, so the timestamp change
  forced geometry-table rebuilding and exposed the missing terrain.

New work should use the standard concise layout rather than a drive-root
diagnostic folder:

```text
H:\Testing\eBFE\12070205\
├── raw\
├── organized\
├── runs\
└── reports\
```

## Terrain delivery evidence

The separate public packages do not contain the omitted compiled terrain:

- `12070205_SpatialData.zip`: 3,434,033,533 bytes and 360 GIS members; zero
  `.tif`, `.hdf`, `.vrt`, `.rasmap`, HDEM, or terrain-named members.
- `12070205_Documents.zip`: 28 document members; its only terrain-named member
  is `Terrain_QAQC_Checklist.docx`.
- `ReferenceGuide.zip`: reference material only.

The Models archive contains `HDEM_1.tif`, `HDEM_2.tif`, and `HDEM_3.tif` under
`Terrain Submittal\Final\hdem`, but no compiled `Terrain.hdf`.

Additional documentation inside the Models submittal confirms the gap:

- `2D_Model_Inventory_LBSG.xlsx` defines the four-part delivery and names the
  same `Terrain\Terrain.hdf` on every 501–505 model sheet.
- `Doucet_LBSG_Terrain Project Narrative.docx` describes a watershed-wide
  seamless DEM mosaic, 10-foot resampling, and terrain QA/QC, but no compiled
  RAS terrain.
- `999999_Terrain_metadata.xml` marks the HDEM work complete but does not list
  a compiled RAS terrain. The XML is malformed at an unescaped
  `Doucet & Associates` value.
- `Certification_of_Completeness_211026b.pdf` certifies the submitted files as
  complete/final without identifying an exception for the omitted terrain.
- `Terrain_QAQC_Checklist.docx` records that the HDEM was initially absent and
  later supplied, but leaves terrain-modification documentation unresolved.
- Every `.rasmap` names the same three modification layers inside the missing
  terrain: `Hwy-Road Crossings (Channel)`, `Hwy-Road Crossings`, and
  `Lake Georgetown`. Their control data are not present in the final HDEMs.

The five source `.rasmap` files contain 40 compiled-terrain layer references;
all 40 already resolve to the intended shared delivery target. Their terrain
source/destination folder settings are inconsistent, so the organizer
normalizes both those folders and every layer reference around the stable
organized target `RAS Model\Terrain\Terrain.hdf`.

No inspected document says `Terrain.hdf` was delivered elsewhere.

## Selected plans and execution verification

| Model | Plan | Geometry | Unsteady | Role | Startup evidence |
|---|---:|---:|---:|---|---|
| LBSG_501 | 01 | 02 | 01 | Upstream | Plan HDF reported `Performing Unsteady Flow Simulation` |
| LBSG_502 | 02 | 03 | 01 | Upstream | Owned `RasUnsteady.exe` detected with complete preprocessing artifacts |
| LBSG_503 | 04 | 04 | 01 | Upstream; two outputs; Florence area | Plan HDF reported `Performing Unsteady Flow Simulation` |
| LBSG_504 | 05 | 05 | 01 | Upstream; Round Rock | Plan HDF reported `Performing Unsteady Flow Simulation` |
| LBSG_505 | 06 | 06 | 02 | Downstream collector | Six DSS families passed preflight; plan HDF entered unsteady simulation |

Models 501, 503, 504, and 505 subsequently reported `READ_UN_HDF_XS_TAB` while
opening a missing `Cross Sections` HDF group. Model 502 was intentionally
stopped at positive owned-process detection. These outcomes do not invalidate
the agreed startup threshold but do not establish clean full-plan completion.

## Corrections for an unsteady-start copy

1. Extract to a concise path and audit every member by path, size, and CRC32;
   never accept a merely non-empty destination.
2. Preserve ZIP timestamps and then apply the association dates recorded in
   each selected geometry HDF. This resolves the delivery's inconsistent ZIP
   DOS/extended-time conventions.
3. Preserve each project's `Input` and sibling `Land Cover`/`LandCover` folder.
4. Stage delivered plan-result HDFs beside their plan files.
5. Set `Run HTab=0` and `UNET Use Existing IB Tables=0` only for the five
   documented smoke plans so the delivered geometry tables remain in use.
6. Rewrite model 505's exact legacy cross-project DSS prefixes to the organized
   `LBSG_501`–`LBSG_504` siblings. Do not use basename matching because the
   bundle contains several distinct `100.dss` files.
7. Validate DSS record families rather than requiring one exact date-range
   D-part; the flow and precipitation records are split into catalog periods.
8. Keep the final HDEMs and terrain spatial inputs with the active project, but
   leave deeply nested LiDAR supplemental reports in the audited raw cache.
9. Normalize every terrain-layer `Filename` in all five `.rasmap` files to the
   one shared organized target, `RAS Model\Terrain\Terrain.hdf`, and normalize
   the terrain source/destination folders around that same layout.

No source folder was modified. A compiled terrain rebuild is not a correction
for this startup gate. Recovering FEMA's original `Terrain.hdf` or its
modification inputs remains necessary for faithful geometry recomputation and
a defensible full rerun.

## Terrain fidelity warning

A diagnostic terrain rebuilt from the three HDEMs provided mesh coverage but
changed delivered cell-minimum elevations:

| Model | Mean rebuilt minus delivered | Maximum absolute difference | Cells differing by more than 1 ft |
|---|---:|---:|---:|
| 501 | +2.158 ft | 55.48 ft | 24,950 |
| 502 | +0.259 ft | 35.92 ft | 7,527 |
| 503 | +0.315 ft | 55.27 ft | 7,559 |
| 504 | +0.566 ft | 69.78 ft | 42,234 |

The HDEM sidecars show only ArcGIS clipping/copying and do not contain the
three `.rasmap` modification layers. A rebuilt package must not be represented
as numerically identical to FEMA's delivered results.

## Implementation implications

- Add an additive `RasEbfeModels.organize_san_gabriel(...) -> Path` API and
  aliases `san-gabriel`, `sangabriel`, and `12070205`.
- Preserve the existing `organize_model()` and `available_models()` contracts;
  expose the cascade and deficiency details through `ModelMetadata.extra`.
- Make eBFE extraction atomic, long-path safe, member-audited, and
  timestamp-preserving while retaining incomplete legacy caches unchanged.
- Store the five-project manifest, exact DSS repairs, smoke plans, and terrain
  deficiency in the organized delivery's `agent/` records.
- Keep San Gabriel out of the interactive Example Project Explorer until the
  original terrain and the required full terrain/result publication gates are
  satisfied. It may be listed as an `unsteady_start` source candidate.
