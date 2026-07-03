# Example Project Library

!!! warning "Under construction"
    The Example Project Library is moving to a RAS Commander MapLibre viewer
    backed by PMTiles and WebGIS-hosted artifacts. Muncie is the first pilot.

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

## Current Pilot

| Project | Source | CRS | Viewer |
|---------|--------|-----|--------|
| Muncie | HEC tutorial/example project | `EPSG:2965` | [Open MapLibre viewer](example-project-viewer.md) |

The generated Muncie bundle currently includes:

- project id:
  `muncie-muncie-rerun-7-0-20260628-193916-4120d261`
- three geometry archives: `g01`, `g02`, and `g04`
- RAS-style geometry sublayers for model extents, 2D flow areas, mesh cells,
  mesh faces, breaklines, centerlines, structures, and cross sections
- terrain published as raster PMTiles with the RAS Commander terrain color ramp
- individual result layers for plans `p03` and `p04`
- default visibility with terrain and geometry `g04` enabled, other geometries
  and result layers disabled
- Hilbert sorting and `join_index` metadata for geometry/result joins
- no local path leaks in the published project manifest

Live public paths:

| Resource | Link |
|----------|------|
| MapLibre viewer | [Muncie Map Viewer](example-project-viewer.md) |
| MapLibre manifest | [manifest.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/manifest.json?v=20260703Tmaplibre03) |
| Geometry PMTiles | [geometry.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/geometry.pmtiles) |
| Results PMTiles | [results.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/results.pmtiles) |
| Terrain PMTiles | [terrain.pmtiles](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/viewer/tiles/terrain.pmtiles) |
| Project catalog | [catalog.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/catalog.json) |
| Project manifest | [project.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/project.json) |

## WebGIS Publishing Model

The docs site should not store raw HEC-RAS projects or large generated GIS
artifacts in the repository. The intended flow is:

1. acquire or extract the source project through RAS Commander
2. compute or inspect the project through the normal RAS Commander workflow
3. export cloud-native artifacts with ras2cng
4. post-process terrain, geometry, and results into MapLibre-ready PMTiles
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

- GeoParquet remains the analysis/archive format for geometry and result
  attributes.
- PMTiles is the browser delivery format for commonly reviewed vector layers.
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

After Muncie, the next projects should be added one at a time as their WebGIS
bundles are published and validated:

- Bald Eagle Creek 1D and Bald Eagle Creek Multi-2D
- New Orleans Metro
- at least one eBFE/BLE delivery
- at least two ScienceBase releases

Each project entry should be added only after:

- the catalog entry has a valid CRS and WGS84 bounding box
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
