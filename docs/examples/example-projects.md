# Example Project Library

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-example-library.css?v=20260906Tsan-gabriel-submodels01">

Explore HEC tutorial projects, organized public model releases, and explicitly
marked source-qualification candidates used throughout the RAS Commander
examples. Select a model area on the map or open a project below to review its
available geometry, terrain, and results.

## Project Explorer

<div class="ras-example-library" data-ras-example-library data-index="https://rascommander.info/data/rasexamples/hec-ras-7.0/current/example-projects.geojson">
  <div class="ras-library-map-shell">
    <div class="ras-library-map" data-library-map></div>
  </div>
  <div class="ras-library-map-footer">
    <span data-library-status>Select a project pin or model extent.</span>
  </div>
  <div class="ras-library-table-wrap">
    <table class="ras-library-table">
      <thead>
        <tr>
          <th scope="col">Project</th>
          <th scope="col">Technical Description</th>
          <th scope="col">HEC-RAS Version</th>
        </tr>
      </thead>
      <tbody data-project-table></tbody>
    </table>
  </div>
</div>

<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/pmtiles@4.3.0/dist/pmtiles.js"></script>
<script src="../../assets/javascripts/ras-example-project-profiles.js?v=20260925Tupper-guadalupe02"></script>
<script src="../../assets/javascripts/ras-example-projects-data.js?v=20260925Tupper-guadalupe02"></script>
<script src="../../assets/javascripts/ras-example-project-supplements.js?v=20260924Taustin-oyster01"></script>
<script src="../../assets/javascripts/ras-example-library.js?v=20260912Talabama-ble-corpus01"></script>

## Dashboard Qualification Status

San Gabriel appears in the dashboard only as a **deficient source candidate**.
Double Mountain Fork Brazos (12050004) is a four-project **source qualification
candidate** after all four selected two-core 1% AEP plans reached unsteady
computation. Middle Chattahoochee–Lake Harding (AL03130002) is one
**source and geometry qualification candidate** for its complete 197-model 1D
steady corpus; no hydraulic computation has been run for that corpus. Each
candidate name links to its qualification record. Austin–Oyster (12040205) is
an **unsteady-start-qualified source and geometry candidate** after plan `p08`
passed the bounded pre-compute workflow. Upper Guadalupe (12100201) is a
four-project **partially qualified source candidate**: UPGU1 reached unsteady
solver startup, while UPGU2–UPGU4 remain unqualified. The San Gabriel, Double Mountain Fork,
and Upper Guadalupe entries retain project-specific sub-model links. These
evidence links are not project-viewer links and
must not imply that the public delivery has a published result viewer.

| Source | RAS Commander entry point | Qualification | Known limitation |
|---|---|---|---|
| FEMA San Gabriel BLE (12070205) | `RasEbfeModels.organize_model("san-gabriel")` | Five linked HEC-RAS 6.3 projects; one 1% plan per project reached unsteady computation. A reconstructed-terrain LBSG_503 1% run also completed successfully with a 0.0236% volume error and 0.737-ft P95 maximum-WSE difference from the supplied result. LBSG_504 covers Round Rock and LBSG_503 is the Florence-area project. This is compute evidence only. | **Critical, model-blocking source gap:** the compiled `Terrain\Terrain.hdf` and its road-crossing/Lake Georgetown modification payloads were not provided. The HDEM-only reconstruction resolves paths and supports diagnostic QA, but does not make the public 2D model reproducible or usable downstream. |
| FEMA Double Mountain Fork Brazos eBFE (12050004) | `RasEbfeModels.organize_model("double-mountain-fork-brazos")` | Four chained HEC-RAS 6.10 projects (HEC-RAS 6.1 family). Exact API-derived footprints are published here, and all four selected two-core 1% AEP plans reached unsteady computation with `owned_process_artifacts` evidence and no timeout or error. This is source-qualification evidence, not a completed-result viewer. | Hydraulic inputs and compiled terrain are delivered. DMF2 correctly references `Terrain.Clone (1).hdf` with the `Polygons (1)` elevation modification. DMF1/DMF2 `g01` require native `RasMap` reassociation plus HEC-RAS table recomputation in the validation copy. Remaining nonhydraulic gaps are local basemap/profile-line references and an inaccurate DMF1 result count in `Readme.txt`. |
| FEMA Austin–Oyster eBFE (12040205) | `RasEbfeModels.organize_model("austin-oyster")` | One HEC-RAS 5.07 2D unsteady project with seven plans. Plan `p08` (`1PAC`) passed the bounded pre-compute workflow with two cores: an owned `RasUnsteady64.exe` and the complete fresh preprocessing artifact set were detected in 64.9 seconds. This is solver-start evidence, not a completed-result claim. | Reconstruction relocates fourteen Output assets and the projection, then corrects one RASMapper projection path. All 28 audited plan-HDF path attributes were already path-equivalent and were preserved byte-for-byte. The two genuinely undelivered references are display-only `Google Map.xml` and `Google Hybrid.xml`. The delivered terrain has no modification groups and the `.rasmap` references none. |
| FEMA Upper Guadalupe eBFE (12100201) | `RasEbfeModels.organize_model("upper-guadalupe")` | Four cascading HEC-RAS 6.3.1 2D unsteady projects, each with seven plans. Four exact API-derived model footprints and durable UPGU1–UPGU4 deficiency links are published here. UPGU1 `p01` reached owned unsteady-solver startup in a fresh two-core run. UPGU2's receipt records `natural_completion` without owned solver-start evidence after property-table rebuilding was observed; UPGU3–UPGU4 were not attempted. Supplied plan HDFs remain published artifacts, not fresh execution evidence. | The archive is CRC-clean and includes all four modified-terrain triplets. UPGU1–UPGU3 retain channel modifications; UPGU4 retains channel and polygon modifications. Reconstruction applies 344 unique staged actions and rewrites 224 fixed-length HDF association attributes, including 28 geometry-HDF attributes omitted by the source audit. Twenty-one omitted files are display/result/QC assets and do not include terrain or hydraulic startup inputs. |
| Alabama Middle Chattahoochee–Lake Harding BLE (AL03130002) | `AlabamaBleModels.organize_watershed("03130002", ...)` | One portable delivery contains 197 1D steady projects in eight source basins, 197 registered plans and geometry HDFs, and 5,365 cross sections. The landing outline is the union of all individual model footprints; one staged PMTiles derivative combines their geometry. This is source and geometry evidence only; no plan computation or result viewer has been qualified. | The publisher's bare object-store prefixes return 404, so discovery must join the Alabama ArcGIS model and link records and use only each link's public `WebPath`. One extra physical plan file, `OSANIPPA CREEK.p02`, is not registered by its project. Delivered plan metadata records 135 projects at 6.20, two at 6.31, and omits the version for 60. |

San Gabriel retains `unsteady_start` evidence but has delivery-readiness status
`critical_source_gap`. It must not be published as a runnable example until the
original compiled terrain, or complete source-equivalent terrain/modification
inputs, are recovered and verified and the remaining publication gates pass.
The organizer normalizes all five
`.rasmap` files so their 40 terrain and modification references resolve to the
single expected organized target, `RAS Model\Terrain\Terrain.hdf`, and creates
a durable [Record of Deficiencies](https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/2026-09-05_san_gabriel_record_of_deficiencies.md)
for any explicitly authorized reconstruction.

Double Mountain Fork Brazos keeps its supplied compiled terrain intact. In
particular, DMF2's modified `Terrain.Clone (1).hdf` is not missing and must not
be silently replaced by the unmodified terrain. The first organizer incorrectly
redirected valid outer terrain and land-cover references to incomplete `Input`
copies; identical Geometry Writer failures on network and local-disk validation
copies proved this was not a network/path-length problem. The specialized
organizer now preserves the delivered outer references. Its
[Record of Deficiencies](https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/2026-09-11_double_mountain_fork_brazos_record_of_deficiencies.md)
records the four-project chain, deterministic assembly repairs, 4/4 native
unsteady-start qualification, and the remaining publication gates.

Middle Chattahoochee–Lake Harding is deliberately represented by one outline
and one table row, not 197 dashboard entries. Its combined geometry PMTiles
must remain separate from the canonical, portable FIM inventory and will load
only after the staged archive is published at a validated HTTP byte-range URL.
The [Record of Deficiencies](https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/2026-09-12_middle_chattahoochee_lake_harding_alabama_ble_record_of_deficiencies.md)
records the source enumeration constraint, the orphan plan file, mixed version
metadata, immutable source layout, and the current no-computation boundary.

Austin–Oyster is qualified for source/geometry discovery and an unsteady-start
example claim, but not for a completed-results viewer. The
[Record of Deficiencies](https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/2026-09-23_austin_oyster_record_of_deficiencies.md)
reconciles the webmap's proposed 29 metadata edits with the independent finding
that all 28 HDF attributes were already correct, records the two display-only
omissions, and preserves the independent CEWS pre-compute evidence.

Upper Guadalupe is represented by four exact project polygons and one grouped
suite row. The [Record of Deficiencies](https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/2026-09-25_upper_guadalupe_record_of_deficiencies.md)
records the single-archive reconstruction, confirms delivery of hydraulically
material terrain modifications, separates supplied result artifacts from fresh
runtime evidence, records UPGU1's successful `p01` pre-compute gate, and keeps
UPGU2–UPGU4 explicitly unqualified. Until a
hosted viewer is requalified, the suite and its four subprojects link to that
durable record rather than dead viewer manifests.

## Related Workflows

- [Using RasExamples](../notebooks/100_using_ras_examples.md)
- [RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md)
- [Model Sources Showcase](../notebooks/958_model_sources_showcase.md)
- [Cloud-Native Geometry Export](../notebooks/960_cloud_native_geometry_export.md)
- [Cloud-Native Results Export](../notebooks/961_cloud_native_results_export.md)
- [Cloud-Native COG Results](../notebooks/962_cloud_native_cog_results_export.md)
- [Cloud-Native Export with ras2cng](../user-guide/cloud-native-export.md)
