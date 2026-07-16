# Example Project Library

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-example-library.css?v=20260714Tlibrarytable01">

!!! warning "Under construction"
    The Example Project Library is moving to a RAS Commander MapLibre viewer
    backed by PMTiles and WebGIS-hosted artifacts. The current promotion set
    includes HEC examples, ScienceBase releases, and an eBFE/BLE delivery.

RAS Commander uses repeatable HEC-RAS project fixtures for examples, tests,
documentation, and regression checks. The library combines several source
families rather than treating one archive as the entire example set:

- HEC tutorial and example projects
- HEC special sample datasets
- publicly available USGS ScienceBase model releases
- organized FEMA eBFE/BLE deliveries
- other public state, county, and federal model catalogs as they are reviewed

HEC's example projects are instructional fixtures, not production studies. They
are still useful because they are the same projects that HEC-RAS tutorials and
manual examples are based on. Public ScienceBase and eBFE/BLE sources play a
different role: they expose real delivery structure, metadata, scale, path
issues, and model packaging details.

Only projects with a verified coordinate reference system are eligible for the
web map viewer. Projects without a CRS can remain useful for notebook examples,
but they are not published as map-review targets until their CRS is resolved.

## Project Explorer

The explorer shows one model-limit polygon per promoted MapLibre project.
Click a polygon to review source metadata and open that project's webmap. The
table below is the same published catalog: each project name is linked once to
its viewer and the Project Information column summarizes the current bundle.
Projects stay out of this map until they have a valid CRS, a WGS84 model limit,
and a published MapLibre webmap.

<div class="ras-example-library" data-ras-example-library data-index="https://rascommander.info/data/rasexamples/hec-ras-7.0/example-projects.geojson?v=20260715Tterrainalpha01">
  <div class="ras-library-map-shell">
    <div class="ras-library-map" data-library-map></div>
  </div>
  <div class="ras-library-map-footer">
    <span data-library-status>Published MapLibre project extents</span>
    <span>Click a model extent to open its webmap.</span>
  </div>
  <div class="ras-library-table-wrap">
    <table class="ras-library-table">
      <thead>
        <tr>
          <th scope="col">Project</th>
          <th scope="col">Project Information</th>
          <th scope="col">Source</th>
          <th scope="col">CRS</th>
        </tr>
      </thead>
      <tbody data-project-table></tbody>
    </table>
  </div>
</div>

<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<script src="../../assets/javascripts/ras-example-projects-data.js?v=20260715Tterrainalpha01"></script>
<script src="../../assets/javascripts/ras-example-library.js?v=20260714Tlibrarytable01"></script>

## Related Workflows

- [Using RasExamples](../notebooks/100_using_ras_examples.md)
- [RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md)
- [Model Sources Showcase](../notebooks/958_model_sources_showcase.md)
- [Cloud-Native Geometry Export](../notebooks/960_cloud_native_geometry_export.md)
- [Cloud-Native Results Export](../notebooks/961_cloud_native_results_export.md)
- [Cloud-Native COG Results](../notebooks/962_cloud_native_cog_results_export.md)
- [Cloud-Native Export with ras2cng](../user-guide/cloud-native-export.md)
