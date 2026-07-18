# Davis building footprints

`davis_building_footprints.pmtiles` is a vector PMTiles archive for overlaying
building footprints on the Davis storm-system benefit-area example. The
archive contains one vector layer, `buildings`, at zoom levels 12 through 17.
`davis_building_footprints.parquet` contains the same clipped features for
static GeoPandas figures in the example notebook.

- Feature count: 7,363 building polygons
- CRS: EPSG:4326
- Bounds: -121.768455, 38.542979, -121.725445, 38.572557
- Clip: example benefit-analysis extent with a 500-foot context buffer
- Source: [Microsoft Global ML Building Footprints](https://github.com/microsoft/GlobalMLBuildingFootprints)
- Source release: 2026-02-03, United States quadkey `023010210`
- License: [CDLA-Permissive-2.0](https://cdla.dev/permissive-2-0/)

The PMTiles metadata includes the source attribution and license. The source
tile was clipped without resampling or geometry generalization before PMTiles
tiling. The compact GeoParquet companion is included because Matplotlib and
GeoPandas do not read vector PMTiles directly.
