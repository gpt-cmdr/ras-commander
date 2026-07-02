# Example Project Library

!!! warning "Under construction"
    This is the landing page for the GeoLibre-based Example Project Library.
    The first pilot, Muncie, is published through the RAS Commander WebGIS
    artifact service. The broader project explorer is still being assembled.

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
GeoLibre explorer. Projects without a CRS can remain useful for notebook
examples, but they are not published as map-review targets until their CRS is
resolved.

## Current Pilot

| Project | Source | CRS | WebGIS status |
|---------|--------|-----|---------------|
| Muncie | HEC tutorial/example project | `EPSG:2965` | Published via WebGIS |

The generated Muncie bundle currently includes:

- project id:
  `muncie-muncie-rerun-7-0-20260628-193916-4120d261`
- three geometry archives: `g01`, `g02`, and `g04`
- two terrain COGs at 5 ft native resolution: `Terrain` and
  `TerrainWithChannel`
- result tables for plans `p03` and `p04`
- GeoLibre layer groups matching the RAS Mapper review pattern: `Results`,
  `Geometries`, and `Terrains`
- terrain and result layers disabled by default for initial map load
- Hilbert sorting and `join_index` metadata for geometry/result joins
- no local path leaks in the published project manifest

Live public paths:

| Resource | Link |
|----------|------|
| GeoLibre review | [Open Muncie in GeoLibre](https://web.geolibre.app/?url=https%3A%2F%2Frascommander.info%2Fdata%2Frasexamples%2Fhec-ras-7.0%2Fprojects%2Fmuncie-muncie-rerun-7-0-20260628-193916-4120d261%2Fgeolibre%2Fproject.geolibre.json%3Fv%3D20260702T193406Z&layout=compact) |
| Project catalog | [catalog.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/catalog.json) |
| Project manifest | [project.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/project.json) |
| GeoLibre manifest | [project.geolibre.json](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/geolibre/project.geolibre.json) |
| Terrain COG | [terrain.cog.tif](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/terrain/terrain.cog.tif) |
| Terrain with channel COG | [terrainwithchannel.cog.tif](https://rascommander.info/data/rasexamples/hec-ras-7.0/projects/muncie-muncie-rerun-7-0-20260628-193916-4120d261/archive/terrain/terrainwithchannel.cog.tif) |

The GeoLibre review link loads the hosted `project.geolibre.json` directly from
the RAS Commander WebGIS artifact service.

## WebGIS Publishing Model

The docs site should not store raw HEC-RAS projects or large generated GIS
artifacts in the repository. The intended flow is:

1. acquire or extract the source project through RAS Commander
2. compute or inspect the project through the normal RAS Commander workflow
3. export cloud-native artifacts with ras2cng
4. post-process terrain, geometry, and results for web review
5. publish validated artifacts to the WebGIS data root
6. link the docs page to the WebGIS catalog and GeoLibre project files

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
- PMTiles should be generated for large or commonly reviewed vector layers.
- COGs should be used for terrain and raster result surfaces.
- Layers should be grouped for review as `Results`, `Geometries`, and
  `Terrains`.
- Terrain and result layers should default to off in GeoLibre.
- Small geometry or overview layers can default on when they make the first map
  load useful without creating a heavy browser request.
- Result tables should use `join_index` metadata to avoid duplicating geometry.
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
- `project.geolibre.json` uses hosted URLs, not local file paths
- COG and PMTiles assets support HTTP range requests
- large layers have sensible default visibility
- GeoLibre opens the project from the public URL

## Related Workflows

- [Using RasExamples](../notebooks/100_using_ras_examples.md)
- [RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md)
- [Model Sources Showcase](../notebooks/958_model_sources_showcase.md)
- [Cloud-Native Geometry Export](../notebooks/960_cloud_native_geometry_export.md)
- [Cloud-Native Results Export](../notebooks/961_cloud_native_results_export.md)
- [Cloud-Native COG Results](../notebooks/962_cloud_native_cog_results_export.md)
- [Cloud-Native Export with ras2cng](../user-guide/cloud-native-export.md)
