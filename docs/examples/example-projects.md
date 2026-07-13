# Example Project Library

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-example-library.css?v=20260713Textents02">

!!! warning "Under construction"
    The Example Project Library is moving to a RAS Commander MapLibre viewer
    backed by PMTiles and WebGIS-hosted artifacts. Muncie, New Orleans Metro,
    and St. Joseph are the first published pilots.

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
Click a polygon to review source metadata and open that project's webmap.
Projects stay out of this map until they have a valid CRS, a WGS84 model limit,
and a published MapLibre webmap.

<div class="ras-example-library" data-ras-example-library data-index="https://rascommander.info/data/rasexamples/hec-ras-7.0/example-projects.geojson?v=20260712Textents01">
  <div class="ras-library-map-shell">
    <div class="ras-library-map" data-library-map></div>
  </div>
  <div class="ras-library-map-footer">
    <span data-library-status>Published MapLibre project extents</span>
    <span>Click a model extent to open its webmap.</span>
  </div>
  <div class="ras-library-projects" data-project-list></div>
</div>

<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<script src="../../assets/javascripts/ras-example-projects-data.js?v=20260713Textents02"></script>
<script src="../../assets/javascripts/ras-example-library.js?v=20260713Textents04"></script>

## Current MapLibre Projects

| Project | Source | CRS | Viewer |
|---------|--------|-----|--------|
| Muncie | HEC tutorial/example project | `EPSG:2965` | [Open MapLibre viewer](example-project-viewer.md) |
| New Orleans Metro | HEC tutorial/example project | `EPSG:3457` | [Open MapLibre viewer](https://rascommander.info/ras/examples/example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fneworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a%2Fviewer%2Fmanifest.json%3Fv%3D20260703Tneworleans01) |
| St. Joseph / St. Joe Elkhart FIM | USGS ScienceBase model release | `EPSG:2965` | [Open MapLibre viewer](https://rascommander.info/ras/examples/example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fst-joseph-st-joe-elkhart-fim-6f8e01d0%2Fviewer%2Fmanifest.json%3Fv%3D20260711Tstjoseph01) |

The generated Muncie bundle currently includes:

- project id:
  `muncie-muncie-rerun-7-0-20260628-193916-4120d261`
- three geometry archives: `g01`, `g02`, and `g04`
- RAS-style geometry sublayers for model extents, 2D flow areas, mesh cells,
  mesh faces, breaklines, centerlines, structures, and cross sections
- terrain published as raster PMTiles with the RAS Commander terrain color ramp,
  plus a source COG for click-query elevation values
- vector result layers for plans `p03` and `p04`
- raster result COGs from RasProcess Stored Maps for plans `p03` and `p04`,
  plus colorized raster PMTiles display derivatives
- click identify for visible vector metadata and visible COG-backed raster values
- default visibility with terrain and geometry `g04` enabled, other geometries
  and result layers disabled
- Hilbert sorting and `join_index` metadata for geometry/result joins
- no local path leaks in the published project manifest

Live public paths:

| Resource | Link |
|----------|------|
| MapLibre viewer | [Muncie Map Viewer](example-project-viewer.md) |
| MapLibre manifest | [manifest.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tidentify02) |
| Geometry PMTiles | [geometry.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/geometry.pmtiles) |
| Vector results PMTiles | [results.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/results.pmtiles) |
| Raster results PMTiles | [p04 depth](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/result-p04-depth-max.pmtiles), [p04 WSE](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/result-p04-wse-max.pmtiles), [p04 velocity](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/result-p04-velocity-max.pmtiles), [p03 depth](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/result-p03-depth-max.pmtiles), [p03 WSE](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/result-p03-wse-max.pmtiles), [p03 velocity](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/result-p03-velocity-max.pmtiles) |
| Stored Map COGs | [p04 depth COG](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/stored-maps/p04/depth-max.cog.tif), [p04 WSE COG](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/stored-maps/p04/wse-max.cog.tif), [p04 velocity COG](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/stored-maps/p04/velocity-max.cog.tif), [p03 depth COG](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/stored-maps/p03/depth-max.cog.tif), [p03 WSE COG](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/stored-maps/p03/wse-max.cog.tif), [p03 velocity COG](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/stored-maps/p03/velocity-max.cog.tif) |
| Terrain PMTiles | [terrain.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/terrain.pmtiles) |
| Terrain COG | [terrain.cog.tif](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/terrain/terrain.cog.tif) |
| Project catalog | [catalog.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/catalog.json) |
| Project manifest | [project.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/project.json) |

The New Orleans Metro bundle currently includes:

- project id:
  `neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a`
- one geometry archive: `g02`
- terrain published as raster PMTiles
- no result layers in the viewer yet; the available result parquet is marked
  geometry-free and needs a join-to-geometry post-processing step before it can
  be tiled or queried consistently

Live public paths:

| Resource | Link |
|----------|------|
| MapLibre viewer | [New Orleans Metro Map Viewer](https://rascommander.info/ras/examples/example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fneworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a%2Fviewer%2Fmanifest.json%3Fv%3D20260703Tneworleans01) |
| MapLibre manifest | [manifest.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a/viewer/manifest.json?v=20260703Tneworleans01) |
| Geometry PMTiles | [geometry.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a/viewer/tiles/geometry.pmtiles) |
| Terrain PMTiles | [terrain.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a/viewer/tiles/terrain.pmtiles) |
| Project manifest | [project.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/neworleansmetro-neworleansmetro-rerun-7-0-20260628-194053-e13b599a/project.json) |

The St. Joseph / St. Joe Elkhart FIM bundle currently includes:

- project id:
  `st-joseph-st-joe-elkhart-fim-6f8e01d0`
- one geometry archive: `g18`
- RAS-style geometry sublayers for model extents, river centerline, and cross
  sections
- no terrain layer and no renderable result layers in the viewer yet

Live public paths:

| Resource | Link |
|----------|------|
| MapLibre viewer | [St. Joseph Map Viewer](https://rascommander.info/ras/examples/example-project-viewer/?manifest=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fst-joseph-st-joe-elkhart-fim-6f8e01d0%2Fviewer%2Fmanifest.json%3Fv%3D20260711Tstjoseph01) |
| MapLibre manifest | [manifest.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/st-joseph-st-joe-elkhart-fim-6f8e01d0/viewer/manifest.json?v=20260711Tstjoseph01) |
| Geometry PMTiles | [geometry.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/st-joseph-st-joe-elkhart-fim-6f8e01d0/viewer/tiles/geometry.pmtiles) |
| Project manifest | [project.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/st-joseph-st-joe-elkhart-fim-6f8e01d0/project.json) |

## WebGIS Publishing Model

The docs site should not store raw HEC-RAS projects or large generated GIS
artifacts in the repository. The intended flow is:

1. acquire or extract the source project through RAS Commander
2. compute or inspect the project through the normal RAS Commander workflow
3. export cloud-native artifacts with ras2cng
4. post-process terrain, geometry, vector results, and Stored Map rasters into
   MapLibre-ready PMTiles or COGs
5. publish validated artifacts to the WebGIS data root
6. link the docs page to the WebGIS catalog and MapLibre project manifest

The public artifact namespace is:

```text
/data/rasexamples/hec-ras-7.0/
```

That namespace is served by a dedicated RAS Commander WebGIS artifact service.
The docs page links to those paths through `rascommander.info`; the docs origin
reverse-proxies `/data/*` to the isolated WebGIS service.

## Performance Policy

The library is also the place where RAS Commander documents practical web GIS
patterns for HEC-RAS projects.

- GeoParquet remains the analysis/archive format for geometry and raw
  element-level result attributes.
- Vector PMTiles is the browser delivery format for commonly reviewed geometry
  layers and queryable vector-result layers.
- Raster results should come from RasProcess Stored Maps and publish as COG or
  raster PMTiles derivatives with HTTP byte-range support. These are the visual
  depth, water-surface, velocity, and similar map products.
- Vector results should not be treated as the visual result map unless a
  separate interpolation or surface-generation step has created a raster
  product.
- Terrain should publish as PMTiles or COG derivatives with HTTP byte-range
  support.
- Terrain and only the first/default geometry should be enabled initially.
- Large geometries, results, and optional terrain derivatives should default to
  disabled unless they are required for the first review view.
- Result tables should use `join_index` metadata to avoid duplicating geometry
  in the archive layer.
- Terrain should not be upsampled. If a source terrain is coarser than 10 ft,
  publish at the smallest native resolution instead of forcing a finer grid.

This keeps the dataset usable while preserving the cloud-native artifacts needed
for repeatable analysis and browser review.

## Next Candidates

After Muncie, New Orleans Metro, and St. Joseph, the next projects should be
added one at a time as their WebGIS bundles are published and validated:

- Bald Eagle Creek 1D and Bald Eagle Creek Multi-2D
- at least one eBFE/BLE delivery
- at least one more ScienceBase release

Do not add the 1D steady BLE model collection to this landing page. That set
should be handled as its own consolidated map once the grouping, symbology, and
metadata pattern are clear.

Each project entry should be added only after:

- the catalog entry has a valid CRS and WGS84 bounding box
- `HdfProject.get_project_extent(geometry_type="footprint")` has produced a
  raw, WGS84 model-limit polygon in the published WebGIS catalog
- the MapLibre manifest uses hosted URLs, not local file paths
- PMTiles or COG assets support HTTP range requests
- large layers have sensible default visibility
- the viewer opens from the public docs URL

## Related Workflows

- [Using RasExamples](../notebooks/100_using_ras_examples.md)
- [RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md)
- [Model Sources Showcase](../notebooks/958_model_sources_showcase.md)
- [Cloud-Native Geometry Export](../notebooks/960_cloud_native_geometry_export.md)
- [Cloud-Native Results Export](../notebooks/961_cloud_native_results_export.md)
- [Cloud-Native COG Results](../notebooks/962_cloud_native_cog_results_export.md)
- [Cloud-Native Export with ras2cng](../user-guide/cloud-native-export.md)
