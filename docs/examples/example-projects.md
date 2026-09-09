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
<script src="../../assets/javascripts/ras-example-project-profiles.js?v=20260906Tsan-gabriel-submodels01"></script>
<script src="../../assets/javascripts/ras-example-projects-data.js?v=20260906Texact-extents01"></script>
<script src="../../assets/javascripts/ras-example-project-supplements.js?v=20260909Tcandidate-detail-links01"></script>
<script src="../../assets/javascripts/ras-example-library.js?v=20260909Tcandidate-detail-links01"></script>

## Dashboard Qualification Status

The San Gabriel model system appears in the dashboard only as a **deficient
source candidate**. Its five sub-model footprints and technical profile are
discoverable, and each sub-model name in the table links to its project-specific
qualification record. These evidence links are not project-viewer links and
must not imply that the public delivery is a runnable or reproducible 2D example.

| Source | RAS Commander entry point | Qualification | Known limitation |
|---|---|---|---|
| FEMA San Gabriel BLE (12070205) | `RasEbfeModels.organize_model("san-gabriel")` | Five linked HEC-RAS 6.3 projects; one 1% plan per project reached unsteady computation. A reconstructed-terrain LBSG_503 1% run also completed successfully with a 0.0236% volume error and 0.737-ft P95 maximum-WSE difference from the supplied result. LBSG_504 covers Round Rock and LBSG_503 is the Florence-area project. This is compute evidence only. | **Critical, model-blocking source gap:** the compiled `Terrain\Terrain.hdf` and its road-crossing/Lake Georgetown modification payloads were not provided. The HDEM-only reconstruction resolves paths and supports diagnostic QA, but does not make the public 2D model reproducible or usable downstream. |

San Gabriel retains `unsteady_start` evidence but has delivery-readiness status
`critical_source_gap`. It must not be published as a runnable example until the
original compiled terrain, or complete source-equivalent terrain/modification
inputs, are recovered and verified and the remaining publication gates pass.
The organizer normalizes all five
`.rasmap` files so their 40 terrain and modification references resolve to the
single expected organized target, `RAS Model\Terrain\Terrain.hdf`, and creates
a durable [Record of Deficiencies](https://github.com/gpt-cmdr/ras-commander/blob/main/agent_tasks/2026-09-05_san_gabriel_record_of_deficiencies.md)
for any explicitly authorized reconstruction.

## Related Workflows

- [Using RasExamples](../notebooks/100_using_ras_examples.md)
- [RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md)
- [Model Sources Showcase](../notebooks/958_model_sources_showcase.md)
- [Cloud-Native Geometry Export](../notebooks/960_cloud_native_geometry_export.md)
- [Cloud-Native Results Export](../notebooks/961_cloud_native_results_export.md)
- [Cloud-Native COG Results](../notebooks/962_cloud_native_cog_results_export.md)
- [Cloud-Native Export with ras2cng](../user-guide/cloud-native-export.md)
