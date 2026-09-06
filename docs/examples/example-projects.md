# Example Project Library

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-example-library.css?v=20260724Tlibrary-final03">

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
<script src="../../assets/javascripts/ras-example-project-profiles.js?v=20260905Tsan-gabriel01"></script>
<script src="../../assets/javascripts/ras-example-projects-data.js?v=20260724Tlibrary-final03"></script>
<script src="../../assets/javascripts/ras-example-project-supplements.js?v=20260905Tsan-gabriel01"></script>
<script src="../../assets/javascripts/ras-example-library.js?v=20260905Tsan-gabriel01"></script>

## Dashboard Qualification Status

The San Gabriel model system appears in the dashboard as a **source
qualification candidate**. Its five-project footprint and technical profile are
discoverable now, but the card intentionally has no project-viewer link until a
complete results publication passes the remaining qualification gates.

| Source | RAS Commander entry point | Qualification | Known limitation |
|---|---|---|---|
| FEMA San Gabriel BLE (12070205) | `RasEbfeModels.organize_model("san-gabriel")` | Five linked HEC-RAS 6.3 projects; one 1% plan per project reached unsteady computation. LBSG_504 covers Round Rock and LBSG_503 is the Florence-area project. A validated working copy uses one shared terrain rebuilt from the three HDEMs. | The original compiled `Terrain\Terrain.hdf` and its road-crossing/Lake Georgetown modification payloads were not provided. The HDEM-only reconstruction resolves all 40 paths but is not source-equivalent. |

San Gabriel remains an `unsteady_start` source example until the original
compiled terrain or its modification inputs are recovered and the full public
terrain/results publication gates pass. The organizer normalizes all five
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
