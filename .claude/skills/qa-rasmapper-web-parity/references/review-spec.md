# Review Specification

The runner accepts YAML or JSON with these fields:

```yaml
schema: rascommander.rasmapper-web-parity/v1
project: H:/path/to/computed/project/Model.prj
project_crs: EPSG:2965
ras_version: "7.0"
web_viewer_url: https://rascommander.info/ras/examples/example-project-viewer/?manifest=...
web_manifest_url: https://rascommander.info/data/.../viewer/manifest.json
geometry_number: "04"
geometry_layers: [RASD2FlowArea, BreakLineLayer]
terrain_name: Terrain
plan_name: Plan 03
result_layer_name: Depth
result_profile: Max
rasmapper_result:
  plan: "03"
  plan_name: Plan 03
  layer_name: Depth
  map_type: Depth
  terrain_name: Terrain
  profile_index: 2147483647
  profile_name: Max
selected_web_layer: p03-depth-max
ramp_id: rasmapper.depth
range_mode: current-view
render_mode: slopingPretty
basemap: hybrid
expanded_tree_paths: [Geometries/Geometry 04, Results/Plan p03]
desktop: {width: 1440, height: 1100}
mobile: {width: 390, height: 844}
rasmapper: {width: 1440, height: 900, dpi: 96, render_delay_seconds: 15}
visible_web_layers: [basemap-hybrid, terrain, ras-geometry-g04-model-extents]
rasmapper_regions:
  map: [300, 80, 1430, 850]
  tree: [0, 80, 300, 850]
  legend: [0, 600, 300, 850]
expected_roots: [features, geometries, results, map-layers, terrains]
required_web_layers: [terrain, ras-geometry-g04-model-extents, p03-depth-max]
numeric_probes:
  - id: depth-center
    raster: H:/path/to/depth.cog.tif
    x: -85.38
    y: 40.20
    coordinate_crs: EPSG:4326
    expected: 2.35
    tolerance: 0.01
```

`rasmapper_regions` are `[left, top, right, bottom]` pixel boxes in the captured RASMapper
outer window. Declare them only after inspecting the first deterministic capture. Basemap
pixels are not stable golden evidence; compare model/raster alignment and transparent nodata.

`rasmapper_result` is optional. When present, the runner registers the computed plan HDF and
a dynamic `RASResultsMap` only in the copied review workspace before capture. This leaves the
source `.rasmap` unchanged while giving RASMapper and the web viewer the same map type/profile.
