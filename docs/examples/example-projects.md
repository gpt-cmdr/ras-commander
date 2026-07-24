# Example Project Library

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-example-library.css?v=20260723Ttechnical-library01">

Explore HEC tutorial projects and organized public model releases used throughout
the RAS Commander examples. Select a model area on the map or open a project
below to review its geometry, terrain, and results.

## Project Explorer

<div class="ras-example-library" data-ras-example-library data-index="https://rascommander.info/data/rasexamples/hec-ras-7.0/example-projects.geojson?v=20260723Ttechnical-library01">
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
<script src="../../assets/javascripts/ras-example-project-profiles.js?v=20260723Ttechnical-library01"></script>
<script src="../../assets/javascripts/ras-example-projects-data.js?v=20260723Ttechnical-library01"></script>
<script src="../../assets/javascripts/ras-example-library.js?v=20260723Tscale-aware-pins01"></script>

## Related Workflows

- [Using RasExamples](../notebooks/100_using_ras_examples.md)
- [RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md)
- [Model Sources Showcase](../notebooks/958_model_sources_showcase.md)
- [Cloud-Native Geometry Export](../notebooks/960_cloud_native_geometry_export.md)
- [Cloud-Native Results Export](../notebooks/961_cloud_native_results_export.md)
- [Cloud-Native COG Results](../notebooks/962_cloud_native_cog_results_export.md)
- [Cloud-Native Export with ras2cng](../user-guide/cloud-native-export.md)
