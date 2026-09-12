# Double Mountain Fork Brazos Record of Deficiencies (ROD)

- **ROD date:** 2026-09-11
- **Study:** FEMA Double Mountain Fork Brazos eBFE (12050004)
- **Delivered HEC-RAS version:** 6.10 (HEC-RAS 6.1 family)
- **Model system:** four chained 2D unsteady projects
- **Compute evidence:** 4/4 plans reached unsteady computation
- **Delivery readiness:** `source_qualification_candidate`
- **Delivered source:** `F:\eBFE\raw\12050004`
- **Durable organized source:**
  `H:\Testing\eBFE\12050004\organized-final-v3`
- **Accepted qualification run root:**
  `H:\Testing\eBFE\12050004\runs\native-qualification-20260911-2024`

This record distinguishes deficiencies in the public delivery from repairs made
only in the organized validation copy. The delivered source folders are treated
as immutable. A candidate entry on the example-project dashboard is discovery
and qualification evidence, not a claim that a published result viewer exists.

## Delivery and extraction record

The delivery contains seven top-level source objects totaling 68,682,636,198
bytes (63.966 GiB): four model archives (`DMF1.zip` through `DMF4.zip`), a model
inventory workbook, hydraulic metadata XML, and `Readme.txt`. Archive auditing
found 322 members and 78,131,657,559 uncompressed bytes, with no CRC, size,
truncation, or unsafe-path failures. Thirteen zero-length members are legitimate
directory or placeholder entries.

The organizer preserves the delivered doubled model layout because its internal
relative paths depend on it:

- `RAS Model\DMF1\DMF1\Input\DMF_1.prj`
- `RAS Model\DMF2\DMF2\Input\DMF2.prj`
- `RAS Model\DMF3\DMF3\Input\DMF_3.prj`
- `RAS Model\DMF4\DMF4\Input\DMF_BrazosRiver4.prj`

The hydraulic cascade is `DMF_1` to `DMF2` to `DMF_3` to
`DMF_BrazosRiver4`. DMF2 consumes `DMF_1.dss`; DMF3 consumes `DMF2.dss` and
`NFDMFB_3.dss`; and DMF4 consumes `DMF_3.dss`.

## Deficiency register

| ID | Deficiency | Impact | Status / disposition |
|---|---|---|---|
| DMFB-001 | The four archives must be assembled without flattening, and submitter-specific absolute or cross-project plan references require deterministic portability repairs. Structured audit evidence records 47 repair rows (18 RASMapper and 29 plan-file references) plus 12 DSS compatibility copies. The delivered outer terrain and land-cover references described below are already correct and are not repair targets. | Flattening the model tree or applying a blanket path rewrite can break valid terrain, land-cover, infiltration, projection, DSS, or result references. | **Mitigated in the specialized organizer.** `RasEbfeModels.organize_model("double-mountain-fork-brazos")` preserves the correct outer resource references, applies only the recorded portability repairs, and does not modify the source folders. |
| DMFB-002 | The public audit narrative lists eight standardization actions but omits the required DMF4 projection correction from `.\NAD 1983 State Plane Texas North Central FIPS 4202.prj` to `.\Projection\NAD 1983 State Plane Texas North Central FIPS 4202.prj`. | An implementation based only on the prose report leaves DMF4's RASMapper projection unresolved. | **Mitigated in the organizer and regression tests.** The structured audit evidence and final closure, rather than the incomplete prose count, govern the repair recipe. |
| DMFB-003 | Two model files reference `%LocalAppData%\HEC\Mapping\5.1\XML\Google Satellite.xml`, and one references Google Hybrid. Those user-profile basemap definitions are not part of the delivery. | The optional background maps may not load on another workstation. Hydraulic computation is not blocked. | **Open, nonhydraulic.** Do not invent or redistribute user-profile basemap definitions. |
| DMFB-004 | DMF1 and DMF3 contain unresolved references to `Profile Lines.shp`; copies with the same basename occur elsewhere in the four-project delivery, but the audit cannot establish which copy was intended. | Optional profile-line display content may be absent. Choosing a same-named file without provenance could misrepresent the source. | **Open, nonhydraulic.** Leave the references documented rather than guessing. |
| DMFB-005 | `Readme.txt` says DMF1 has seven result HDF and initial-condition files, while the archive contains eight of each. | Delivery documentation understates the supplied result set and can mislead automated or human inventory checks. | **Open documentation defect.** Inventory the archive contents as delivered. |
| DMFB-006 | The delivered DMF1 and DMF2 `g01` geometry HDFs lack the named 2D-area terrain, land-cover, and infiltration associations/property tables required by Geometry Writer. The referenced terrain, land cover, and infiltration inputs themselves are present. | HEC-RAS geometry preprocessing cannot advance to the unsteady solver from those delivered geometry HDFs without regenerating the named-area associations and property tables. | **Mitigated for isolated qualification; remains a source geometry preprocessing gap.** RAS Commander's native `RasMap` association API assigned the named 2D areas and HEC-RAS recomputed the property tables. No input was fabricated and the delivered terrain was not replaced. |
| DMFB-007 | The first general-purpose organizer incorrectly rewrote valid outer terrain and land-cover references to incomplete copies under each `Input` folder. | Geometry Writer failed before unsteady startup even though FEMA supplied the required terrain and land-cover data. | **Implementation-discovered validation-copy defect, corrected.** The specialized organizer now preserves DMF1 `..\Terrain` / `..\Landcover`, DMF2's modified `Terrain.Clone (1).hdf` / `LandCover`, and DMF3/DMF4 `..\Terrain` / `..\LandCover` resources. This was not a FEMA source deficiency. |
| DMFB-008 | The first Geometry Writer failure reproduced identically from an `H:` network-share validation copy and an `I:` local-disk validation copy. | Network transport, mapped-drive behavior, and path length were plausible but incorrect explanations for the failure. | **Ruled out by controlled repetition.** Both attempts stopped at the same geometry association/property-table condition. Evidence paths are recorded below. |
| DMFB-009 | DMF3 and DMF4 have delivered property tables, but their named-area associations still depend on the assembled path context. | Retaining stale or ambiguous association metadata can make validation nondeterministic across workstations. | **Mitigated in the validation copies.** The associations were refreshed natively through `RasMap`; HEC-RAS retained/recomputed its own property data before both plans reached unsteady computation. |
| DMFB-010 | The public audit did not execute HEC-RAS. Static path closure and `RasCheck` evidence alone did not prove that the unsteady solver starts. | Example-library qualification required fresh runtime evidence for the selected 1% AEP plan in every sub-model. | **Qualified 4/4 at the accepted `unsteady_start` gate.** Every isolated two-core plan produced RAS Commander's `owned_process_artifacts` proof with fresh nonempty temporary HDF, boundary, and geometry-preprocessor files. All four returned success with no timeout or error. |

## Terrain completeness and critical 2D rule

The compiled terrain is **not missing** from this delivery. All four sub-models
include their referenced compiled terrain. DMF2 deliberately references
`Terrain.Clone (1).hdf`, which contains the `Polygons (1)` elevation
modification; it must not be replaced with the unmodified `Terrain.hdf`.

The correct delivered outer associations are DMF1 `..\Terrain` and
`..\Landcover`; DMF2's modified `Terrain.Clone (1).hdf` and `LandCover`; and
DMF3/DMF4 `..\Terrain` and `..\LandCover`. The durable organized source keeps
those resource locations rather than creating incomplete substitutes under
`Input`.

Complete compiled terrain, including terrain modifications, is essential for
downstream 2D repeatability. If a 2D delivery omits that information, geometry
preprocessing and hydraulic results may not be reproducible and the model must
be flagged as critically deficient rather than treated as usable merely because
a supplied result HDF can be displayed. That critical rule applies generally;
it is recorded here to prevent the DMF2 modified terrain from being flattened,
substituted, or mistakenly described as missing.

## Project-specific qualification records

### DMF1

`DMF_1.prj` is the upstream project. The selected 1% AEP plan is `p04`, using
geometry `g01` and unsteady-flow file `u03`. The isolated two-core run reached
unsteady computation with `signal_source="owned_process_artifacts"` in
3,076.8656 seconds and returned no timeout or error.

The qualified copy used native named-area association under DMFB-006. Its
HEC-RAS property-table rebuild completed in 1,240.18 seconds.

### DMF2

`DMF2.prj` follows DMF1 and consumes `DMF_1.dss`. The selected 1% AEP plan is
`p01`, using geometry `g01` and unsteady-flow file `u01`. Its referenced
`Terrain.Clone (1).hdf` includes the `Polygons (1)` modification and is the
correct delivered terrain.

The isolated two-core run reached unsteady computation with
`signal_source="owned_process_artifacts"` in 28.8292 seconds and returned no
timeout or error.

The qualified copy used native named-area association and property-table
regeneration under DMFB-006. The table rebuild completed in 1,875.44 seconds
using the delivered modified terrain clone; it did not rebuild or replace
FEMA's terrain.

### DMF3

`DMF_3.prj` follows DMF2 and consumes both `DMF2.dss` and `NFDMFB_3.dss`. The
selected 1% AEP plan is `p01`, using geometry `g01` and unsteady-flow file
`u02`. The isolated two-core run reached unsteady computation with
`signal_source="owned_process_artifacts"` in 35.5964 seconds and returned no
timeout or error.

Its delivered property tables exist. The isolated validation copy refreshed
the named-area associations through `RasMap`; native table preparation completed
in 627.21 seconds.

### DMF4

`DMF_BrazosRiver4.prj` is the downstream project and consumes `DMF_3.dss`. The
selected 1% AEP plan is `p01`, using geometry `g01` and unsteady-flow file
`u01`. Its projection path requires the DMFB-002 correction. The isolated
two-core run reached unsteady computation with
`signal_source="owned_process_artifacts"` in 32.2249 seconds and returned no
timeout or error.

Its delivered property tables exist. The isolated validation copy refreshed
the named-area associations through `RasMap`; native table preparation completed
in 695.18 seconds.

## Failed qualification attempts and diagnosis

The initial specialized qualification attempts did not reach the unsteady
solver. On the `H:` network-share copy, Geometry Writer stopped after the first
organizer had redirected valid outer resource references to incomplete `Input`
copies. Repeating the same validation from local disk on `I:` produced the same
failure. That controlled repetition rules out the network share and path length
as the cause.

The retained evidence is:

- `H:\Testing\eBFE\12050004\reports\12050004_unsteady_start_attempt2_network_share.json`
- `H:\Testing\eBFE\12050004\reports\direct-existing-associations\12050004_unsteady_start_qualification.json`

Review of the delivered geometry HDFs then isolated DMFB-006: DMF1 and DMF2
lack the named 2D-area association/property-table state Geometry Writer needs,
while their actual terrain, land-cover, and infiltration inputs are present.
The accepted qualification workflow preserved the delivered outer resource
paths, applied native named-area associations through `RasMap`, and let HEC-RAS
recompute the missing tables. DMF3 and DMF4 already have property tables, but
their associations were refreshed through the same native path for deterministic
validation. The durable source handoff was then regenerated as
`organized-final-v3` with relocation-safe evidence paths and passed a second-call
reuse audit. These actions are validation-copy repairs; no source folder is
modified.

A third disposable DMF1 attempt tested a provisional named-area-attribute
shortcut. It remained in native geometry preparation for 3,599.12 seconds and
produced no BCO, temporary HDF, boundary-file, or geometry-preprocessor-file
readiness evidence. After API review rejected the shortcut as non-native, the
owned run was cancelled through the scoped
`RasCmdr.cancel_plan("04")` API. The attempt ended with `success=false`,
`signal_source="natural_completion"`, and exit code 15. It is not qualification
evidence and is not counted toward the four-model gate.

The final validation workflow uses only native
`RasMap.associate_geometry_layers(...)` followed by
`RasMap.recompute_property_tables(...)`. No provisional direct HDF-attribute
shortcut is part of the organizer or accepted qualification procedure.

## Native unsteady-start qualification results

The accepted run used HEC-RAS 6.1 for the delivered `Program Version=6.10`
model family and requested two cores for every selected 1% AEP plan. RAS
Commander read back two cores for each plan, and all four plans returned
`success=true`, `qualified_unsteady_start=true`, no timeout, and no error.

| Model | Plan | Geometry | Cores | Signal source | Native table preparation | Reported startup elapsed |
|---|---|---|---:|---|---:|---:|
| DMF1 | `p04` | `g01` | 2 | `owned_process_artifacts` | 1,240.18 s | 3,076.8656 s |
| DMF2 | `p01` | `g01` | 2 | `owned_process_artifacts` | 1,875.44 s | 28.8292 s |
| DMF3 | `p01` | `g01` | 2 | `owned_process_artifacts` | 627.21 s | 35.5964 s |
| DMF4 | `p01` | `g01` | 2 | `owned_process_artifacts` | 695.18 s | 32.2249 s |

The evidence report records `qualified_model_count=4` and
`all_qualified=true`:

`H:\Testing\eBFE\12050004\reports\native-qualification-20260911-2024\12050004_unsteady_start_qualification.json`

For each model, `owned_process_artifacts` means RAS Commander observed its
owned `RasUnsteady.exe` process together with newly generated, nonempty plan
temporary HDF, boundary, and geometry-preprocessor files. This satisfies the
user-approved unsteady-start threshold; it does not claim plan completion or
numerical equivalence with the supplied FEMA results.

## Qualification and publication gates

All four exact WGS84 model footprints were independently derived from each
organized project's `geom_df` `g01` HDF path with
`HdfProject.get_project_extent(geometry_type="footprint", buffer_percent=0,
fill_holes=True)`. Each result is a valid, non-bounding-box polygon in source
CRS EPSG:2276, transformed to EPSG:4326 for the dashboard. Evidence is retained
at `H:\Testing\eBFE\12050004\reports\12050004_project_footprints.geojson`.
Bounding boxes, HUC outlines, and inferred connector polygons are not acceptable
substitutes.

Each candidate must retain an empty viewer, artifact manifest, and project
manifest until the full publication workflow supplies completed hydraulic
results, terrain and stored-map products, cloud-native artifacts, manifests,
and browser QA. Reaching unsteady computation is sufficient for the present
source-qualification gate but does not by itself satisfy those publication
gates.
