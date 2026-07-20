# Working with Spatial Data and RASMapper

RAS Commander provides comprehensive tools for working with HEC-RAS spatial datasets, including terrain, land cover, infiltration layers, and automated map generation. This guide covers accessing RASMapper configuration data and modifying spatial parameters for model calibration.

## Overview

When you initialize a RAS project, the library automatically parses the RASMapper file (`.rasmap`) and populates the `rasmap_df` DataFrame with paths to all spatial datasets. This provides programmatic access to terrain models, land cover layers, soil data, and more.

## Understanding rasmap_df

The `rasmap_df` DataFrame is automatically populated when you call `init_ras_project()`. It contains paths and metadata for all spatial datasets referenced in your RASMapper configuration.

```python
from ras_commander import init_ras_project, ras

# Initialize project - automatically parses .rasmap file
init_ras_project(r"C:\Projects\MyRasModel", "7.0")

# Access rasmap DataFrame
print(ras.rasmap_df)
```

### Available Spatial Data Types

The `rasmap_df` typically contains paths to:

- **Terrain data** - Digital elevation models (DEM/DTM)
- **Land cover datasets** - Manning's n roughness layers
- **Soil layers** - Hydrologic soil groups for infiltration
- **Infiltration data** - Green-Ampt or SCS CN parameters
- **Profile lines** - Cross-section locations
- **Boundary features** - Flow and stage boundary locations

### Accessing Specific Data Paths

```python
# rasmap_df is a compact project summary. Several columns contain lists.
summary = ras.rasmap_df.iloc[0]

terrain_paths = summary["terrain_hdf_path"]
landcover_paths = summary["landcover_hdf_path"]
soil_paths = summary["soil_layer_path"]
infiltration_paths = summary["infiltration_hdf_path"]

print(terrain_paths)
```

For discoverable automation, prefer the layer-list methods below. They return one row per RASMapper layer rather than one compact project-summary row.

## Discovering RASMapper Layers

`RasMap` can list terrain, land-cover, soils, and infiltration layers directly from the `.rasmap` catalog. These methods are useful when building QA/QC tools because they expose the layer names that users see in RASMapper and the paths that automation needs.

```python
from ras_commander import RasExamples, RasMap

project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")

terrain_layers = RasMap.list_terrain_layers(project_path)
landcover_layers = RasMap.list_landcover_layers(project_path)
soils_layers = RasMap.list_soils_layers(project_path)
infiltration_layers = RasMap.list_infiltration_layers(project_path)

print(terrain_layers[[
    "name",
    "filename",
    "resolved_path",
    "checked",
    "type",
    "resample_method",
    "surface_on",
]])

print(landcover_layers[[
    "name",
    "classification_kind",
    "resolved_path",
    "selected_parameter",
]])
```

### Layer Discovery Methods

| Method | Reads | Typical use |
|--------|-------|-------------|
| `RasMap.list_terrain_layers(project_path)` | `.rasmap` `Terrains/Layer` entries | Find valid terrain layer names and HDF paths |
| `RasMap.list_land_classification_layers(project_path)` | `.rasmap` `Type="LandCoverLayer"` entries | Inspect every land-classification style layer |
| `RasMap.list_landcover_layers(project_path)` | Filtered land-classification rows | Manning's n / land-cover sidecar workflows |
| `RasMap.list_soils_layers(project_path)` | Filtered land-classification rows | Hydrologic soils discovery |
| `RasMap.list_infiltration_layers(project_path)` | Filtered land-classification rows | Infiltration sidecar discovery |

!!! note "rasmap_df vs list methods"
    `ras.rasmap_df` remains a compact initialization summary. Use it when you want a quick project overview. Use `RasMap.list_*_layers()` when users need names, per-layer metadata, and paths for a workflow.

## Geometry HDF Associations

HEC-RAS stores layer availability in the `.rasmap` file, but compiled geometry and plan/result HDF files also carry `/Geometry` attributes that record which terrain, land-cover, infiltration, and sediment bed-material layers are associated with a geometry.

Use `RasMap.get_hdf_geometry_association()` for read-only QA/QC:

```python
from pathlib import Path
from ras_commander import RasMap

project_path = Path(r"C:\Projects\MyModel")
geometry_hdf = project_path / "MyModel.g01.hdf"
plan_hdf = project_path / "MyModel.p01.hdf"

geometry_assoc = RasMap.get_hdf_geometry_association(geometry_hdf)
plan_assoc = RasMap.get_hdf_geometry_association(plan_hdf)

print(geometry_assoc.get("terrain_hdf_path"))
print(geometry_assoc.get("terrain_layer_name"))
print(plan_assoc.get("landcover_hdf_path"))
```

Common returned keys include:

| Key | HEC-RAS attribute |
|-----|-------------------|
| `terrain_hdf_path` | `Terrain Filename` |
| `terrain_layer_name` | `Terrain Layername` |
| `landcover_hdf_path` | `Land Cover Filename` |
| `landcover_layer_name` | `Land Cover Layername` |
| `infiltration_hdf_path` | `Infiltration Filename` |
| `infiltration_layer_name` | `Infiltration Layername` |
| `sediment_soils_hdf_path` | `SedimentSoilsFilename` |

### Writing Geometry Associations

Use `RasMap.associate_geometry_layers()` to write HEC-style `/Geometry` association attributes to an existing compiled geometry HDF.

```python
from pathlib import Path
from ras_commander import RasMap

project_path = Path(r"C:\Projects\MyModel")
geometry_hdf = project_path / "MyModel.g01.hdf"
terrain_hdf = project_path / "Terrain" / "ExistingTerrain.hdf"
landcover_hdf = project_path / "Land Classification" / "LandCover.hdf"

RasMap.associate_geometry_layers(
    project_path,
    geometry_hdf,
    terrain_hdf_path=terrain_hdf,
    landcover_hdf_path=landcover_hdf,
)

updated = RasMap.get_hdf_geometry_association(geometry_hdf)
print(updated["terrain_hdf_path"])
print(updated["landcover_hdf_path"])
```

!!! warning "Existing compiled geometry HDF required"
    `RasMap.associate_geometry_layers()` updates attributes on an existing `.g##.hdf`. It does not compile a plain-text `.g##` file into HDF and does not create missing geometry datasets. Treat true `.g##` to `.g##.hdf` generation as HEC-RAS/Ras.exe behavior unless a native endpoint is explicitly available.

!!! tip "Layer name resolution"
    When possible, ras-commander resolves `Terrain Layername`, `Land Cover Layername`, and `Infiltration Layername` from the `.rasmap` catalog. If the layer cannot be found in `.rasmap`, it falls back to the file stem.

### Native RasProcess Reference Validator

`RasProcess.validate_geometry_association_cli()` wraps the native `RasProcess.exe SetGeometryAssociation` command as a reference validator. It is intentionally not the primary workflow because the native command mutates the supplied HDF in place.

```python
from ras_commander import RasProcess

result = RasProcess.validate_geometry_association_cli(
    geometry_hdf,
    terrain_hdf_path=terrain_hdf,
    landcover_hdf_path=landcover_hdf,
    ras_version="7.0",
)

print(result["passed"])
print(result["command_args"])
print(result["mismatches"])
```

!!! danger "Validation/reference only"
    Run the native validator only on a disposable copy or a model you intentionally want `RasProcess.exe` to mutate. Normal automation should use `RasMap.associate_geometry_layers()`.

## Map Layer Management

`RasMap` can read and write top-level RASMapper `MapLayers` entries. These include reference map layers such as shapefiles and GeoJSON, plus standard HEC-RAS basemap layers such as USGS Topo or Google Hybrid.

### Discovering Map Layers

```python
from ras_commander import RasMap

all_layers = RasMap.list_map_layers(r"C:\Projects\MyModel")
reference_layers = RasMap.list_reference_map_layers(r"C:\Projects\MyModel")
basemap_layers = RasMap.list_basemap_layers(r"C:\Projects\MyModel")
standard_basemaps = RasMap.list_standard_basemap_layers()

print(all_layers[["name", "type", "category", "filename"]])
print(standard_basemaps["name"].tolist())
```

`RasMap.list_map_layers()` returns a DataFrame when called with an explicit project path. The legacy active-project call shape, `RasMap.list_map_layers()`, is still available for older notebooks and returns `list[dict]` with a `FutureWarning`.

### Adding Reference Map Layers

```python
from ras_commander import RasMap

RasMap.add_reference_map_layer(
    r"C:\Projects\MyModel",
    r"C:\Projects\MyModel\custom_layers\boundaries.geojson",
    layer_name="Boundary Conditions",
    layer_type="PolylineFeatureLayer",
)

RasMap.add_reference_map_layer(
    r"C:\Projects\MyModel",
    r"C:\GIS\levee_centerline.shp",
    layer_name="Levee Centerline",
)
```

!!! warning "WGS84 Requirement for GeoJSON"
    GeoJSON files for RASMapper must be in WGS84 (EPSG:4326) coordinates. `RasMap.add_reference_map_layer()` validates this before editing the `.rasmap` and raises `ValueError` when the source is projected or otherwise not WGS84-compatible.

    ```python
    gdf_wgs84 = gdf.to_crs("EPSG:4326")
    gdf_wgs84.to_file("output.geojson", driver="GeoJSON")
    ```

### Adding Basemap Layers

```python
RasMap.add_basemap_layer(r"C:\Projects\MyModel", "USGS Topo", checked=True)
RasMap.add_basemap_layer(r"C:\Projects\MyModel", "Google Hybrid", checked=False)
```

### Removing Layers

```python
RasMap.remove_map_layer("Old Analysis Layer")
```

## Geometry Visibility Control

Control which geometry layers are visible in RASMapper. This is useful when a project has multiple geometries and you want to focus on a specific one. For documentation and QA/QC workflows, you can also toggle child geometry elements, set a deterministic RASMapper view, open standalone RASMapper, and capture a screenshot.

### Listing Geometries

```python
# List all geometry layers with visibility status
geoms = RasMap.list_geometries()
for g in geoms:
    status = "✓" if g['checked'] else " "
    print(f"[{status}] {g['geom_number']}: {g['name']}")
```

Example output:
```
[✓] 06: Original 1D Model
[ ] 08: 1D-2D Dam Break Model Refined Grid
[ ] 09: Alternative Geometry
```

### Setting Visibility

```python
# Show a specific geometry
RasMap.set_geometry_visibility("08", visible=True)

# Hide a specific geometry
RasMap.set_geometry_visibility("06", visible=False)

# Hide all geometries except one
RasMap.set_all_geometries_visibility(visible=False, except_geom="08")
RasMap.set_geometry_visibility("08", visible=True)
```

### Geometry Identifier Formats

The geometry visibility functions accept multiple identifier formats:

| Format | Example | Notes |
|--------|---------|-------|
| Number | `"08"` or `"8"` | Geometry number |
| With prefix | `"g08"` or `"G08"` | Common notation |
| By name | `"1D-2D Dam Break Model"` | Full geometry name |
| Filename | `"g08.hdf"` | Filename pattern |

### Geometry Element View Control

Use `RasMap.list_geometry_layers()` when you need the geometry tree that users
see inside RASMapper. The returned DataFrame includes one row for each compiled
geometry and one row for each child element such as cross sections, 2D flow
areas, mesh perimeters, and structures.

```python
from ras_commander import RasMap

layers = RasMap.list_geometry_layers(r"C:\Projects\MyModel")
print(layers[[
    "layer_id",
    "category",
    "geometry_number",
    "layer_type",
    "checked",
    "geometry_hdf_path",
]])
```

Toggle child geometry elements with `set_geometry_layer_visibility()`. The
`exclusive=True` option hides other geometry elements first, which is useful for
clean screenshots. For structure or breakline review, keep the 2D flow area
visible with the target structure layer so the mesh/area context remains in the
snapshot.

```python
RasMap.set_geometry_layer_visibility(
    r"C:\Projects\MyModel",
    geometry_number="04",
    layer_type=["RASD2FlowArea", "LateralStructureLayer"],
    checked=True,
    exclusive=True,
)
```

Use the matching result and map-layer state helpers to build figure recipes.
Calling them without a selector targets all layers in that section; calling them
with `exclusive=True` hides non-matching layers and shows only the selected
context.

```python
# Hide all result rasters for a clean geometry/terrain figure
RasMap.set_result_layer_visibility(
    r"C:\Projects\MyModel",
    checked=False,
)

# Or show only one plan/layer result
RasMap.set_result_layer_visibility(
    r"C:\Projects\MyModel",
    plan_name="Existing Conditions",
    layer_name="Depth",
    checked=True,
    exclusive=True,
)

# Show only land-classification map layers, or select by name/type
RasMap.set_map_layer_visibility(
    r"C:\Projects\MyModel",
    category="land_classification",
    checked=True,
    exclusive=True,
)
```

RASMapper visibility is layer-based, but ras-commander can build
feature-focused viewports from compiled geometry HDFs. This does not hide the
rest of the RASMapper layer. It uses the selected feature only to center the
viewport, then zooms out enough to show the surrounding mesh, terrain, land
cover, and profile context. Use `list_geometry_features()` to discover feature
names and ids for supported layer types such as 2D flow areas, lateral
structures, breaklines, and cross sections.

```python
features = RasMap.list_geometry_features(
    r"C:\Projects\MyModel\MyModel.g04.hdf",
    layer_type="LateralStructureLayer",
)
print(features[[
    "feature_id",
    "feature_index",
    "feature_name",
    "min_x",
    "min_y",
    "max_x",
    "max_y",
]])
```

RASMapper stores the current viewport in project coordinates. You can write it
directly or let ras-commander compute bounds from the compiled geometry HDF:

```python
# Write an exact project-coordinate viewport
RasMap.set_current_view(
    r"C:\Projects\MyModel",
    min_x=402800,
    min_y=1799900,
    max_x=413100,
    max_y=1806400,
)

# Or zoom to a geometry element using HDF coordinate datasets
RasMap.zoom_to_geometry_layer(
    r"C:\Projects\MyModel",
    geometry_number="04",
    layer_type="LateralStructureLayer",
    feature_name="Lateral Structure 1",
)
```

When a feature selector is provided and `padding_fraction` is omitted,
ras-commander expands the feature extent by 50% overall, which is 25% padding on
each side. Pass `padding_fraction=` explicitly when a tighter or wider view is
needed.

For terrain-backed review images, turn on the terrain layer and ask RASMapper
to update raster legends from the current view. The legend checkbox is stored as
`RegenerateForScreen="True"` on `SurfaceFill` XML entries; ras-commander sets it
for terrain and result surfaces by default.

```python
RasMap.set_terrain_layer_visibility(
    r"C:\Projects\MyModel",
    terrain_name="TerrainWithChannel",
    checked=True,
    exclusive=True,
)
RasMap.set_update_legend_with_view(r"C:\Projects\MyModel")
```

Then launch standalone RASMapper and capture what it draws:

```python
process = RasMap.open_rasmapper(r"C:\Projects\MyModel", ras_version="6.6")
snapshot = RasMap.capture_rasmapper_snapshot(
    pid=process.pid,
    output_path=r"C:\Projects\MyModel\qa\lateral_structure_view.png",
    delay_seconds=3,
    timeout_seconds=1800,
)
RasMap.close_rasmapper(pid=process.pid)
```

!!! note "Standalone RASMapper endpoint"
    `RasMap.open_rasmapper()` launches `RasMapper.exe model.rasmap` directly.
    It does not automate HEC-RAS menus. Configure the `.rasmap` layer and
    `CurrentView` state before opening the window.

### Spatial Review Packages

For agentic QA/QC and repeatable documentation, use
`RasMap.create_spatial_review_package()` as the higher-level workflow. It writes
an evidence bundle with before/after `.rasmap` XML, layer catalogs, preflight
checks, view metadata, and a findings template. Screenshot capture is optional
so the same workflow can run headlessly in tests or with standalone RASMapper on
a Windows review machine.

The current worked examples for this workflow family are
[122_rasmapper_spatial_review.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/122_rasmapper_spatial_review.ipynb)
for review-bundle orchestration and
[123_rasmapper_geometry_layer_updates.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/123_rasmapper_geometry_layer_updates.ipynb)
for mutation-backed geometry refresh and validation.

By default, review packages and screenshots are written to a project subfolder
named `RASMapper Screenshots`. Pass `output_dir=` only when a workflow needs a
different location.

```python
review = RasMap.create_spatial_review_package(
    r"C:\Projects\MyModel",
    geometry_number="04",
    layer_type=["RASD2FlowArea", "LateralStructureLayer"],
    feature_name="Lateral Structure 1",
    terrain_name="TerrainWithChannel",
    result_plan_name="Existing Conditions",
    result_layer_name="Depth",
    map_layer_category="land_classification",
    capture_snapshot=True,
    snapshot_timeout_seconds=1800,
    ras_version="6.6",
)

print(review["artifacts"])
print(review["preflight"])
```

The package includes:

- `review_state.json` - machine-readable setup, preflight, view, and artifact metadata
- `rasmap_before.xml` / `rasmap_after.xml` - presentation-state audit trail
- `geometry_layers.csv`, `result_layers.csv`, `map_layers.csv`, and `layers.csv` - discoverable layer catalogs
- `geometry_features.csv` and `selected_features.csv` - HDF feature catalog and selected viewport target
- `selected_result_layers.csv` and `selected_map_layers.csv` - selected figure context
- `findings.md` - review template for agent or engineer notes
- `rasmapper_spatial_review.png` - optional RASMapper screenshot

By default, `create_spatial_review_package()` hides result and map layers so
geometry, terrain, and selected structure context are not obscured. Pass
`include_results=True`, `include_map_layers=True`, or specific result/map layer
selectors to intentionally include those layers in the figure.

The standalone RASMapper wait timeout defaults to 1800 seconds because large
projects can take many minutes to open. Override `timeout_seconds` on
`capture_rasmapper_snapshot()` or `snapshot_timeout_seconds` on
`create_spatial_review_package()` when a workflow needs a shorter smoke-test
timeout or a longer review window.

## Terrain Data Access

The `RasMap` class provides methods for working with terrain datasets.

### Getting RASMapper File Path

```python
from ras_commander import RasMap

# Get path to .rasmap file
rasmap_file = RasMap.get_rasmap_path()
print(f"RASMapper file: {rasmap_file}")
```

### Listing Available Terrains

```python
# Get list of all terrain names in project
terrains = RasMap.get_terrain_names(rasmap_file)
print(f"Available terrains: {terrains}")
# Output: ['Terrain50', 'Terrain10', 'LiDAR_2020']
```

This is useful when you have multiple terrain datasets and need to specify which one to use for map generation or analysis.

For richer terrain metadata, use `RasMap.list_terrain_layers(project_path)` as shown above.

## Land Cover and Soil Layers

Land cover and soil data are critical for 2D modeling, controlling Manning's n roughness and infiltration parameters.

### Accessing Land Cover Data

Land cover datasets define Manning's n values across 2D flow areas. These are typically stored as HDF files referenced in the RASMapper configuration.

```python
# Discover land-cover sidecars and RASMapper layer names
landcover_layers = RasMap.list_landcover_layers(project_path)
landcover_path = landcover_layers.iloc[0]["resolved_path"]

# Land cover is used for Manning's n assignment
# See Manning's n Calibration section below for modification
```

### Accessing Soil Layer Data

Soil layers define hydrologic soil groups (A, B, C, D) used for infiltration calculations.

```python
# Discover hydrologic soils layers
soils_layers = RasMap.list_soils_layers(project_path)
soil_path = soils_layers.iloc[0]["resolved_path"]

# Soil data is used with infiltration methods
# See Infiltration Data Handling section below
```

## Automating Stored Map Generation

HEC-RAS can generate stored maps (raster outputs like depth and water surface elevation) through the GUI. RAS Commander provides two approaches for automation:

1. **`RasProcess.store_maps()`** - Headless CLI-based generation (recommended)
2. **`RasMap.postprocess_stored_maps()`** - GUI automation approach

### Headless Generation with RasProcess (Recommended)

The `RasProcess` class uses the undocumented RasProcess.exe CLI tool bundled with HEC-RAS to generate stored maps without opening the GUI. This is faster and more reliable for batch processing.

```python
from ras_commander import RasCmdr, RasProcess

# First, ensure the simulation has been run
RasCmdr.compute_plan("01")

# Generate stored maps (headless - no GUI)
results = RasProcess.store_maps(
    plan_number="01",
    profile="Max",
    wse=True,
    depth=True,
    velocity=True
)

# Results is a dict of generated file paths
for map_type, files in results.items():
    print(f"{map_type}: {len(files)} file(s)")
    for f in files:
        print(f"  - {f}")
```

#### Available Map Types

| Parameter | Description | Default |
|-----------|-------------|---------|
| `wse` | Water Surface Elevation | True |
| `depth` | Water Depth | True |
| `velocity` | Velocity Magnitude | True |
| `froude` | Froude Number | False |
| `shear_stress` | Bed Shear Stress | False |
| `depth_x_velocity` | D×V Hazard Index | False |
| `depth_x_velocity_sq` | D×V² Impact Index | False |

#### Profile Selection

```python
# Generate Max values (default)
results = RasProcess.store_maps(plan_number="01", profile="Max")

# Generate Min values
results = RasProcess.store_maps(plan_number="01", profile="Min")

# Generate for specific timestep
timestamps = RasProcess.get_plan_timestamps("01")
results = RasProcess.store_maps(plan_number="01", profile=timestamps[10])
```

#### Batch Processing All Plans

```python
# Generate maps for ALL plans with HDF results
all_results = RasProcess.store_all_maps(
    profile="Max",
    wse=True,
    depth=True,
    velocity=True,
    froude=True
)

for plan_num, files in all_results.items():
    total = sum(len(f) for f in files.values())
    print(f"Plan {plan_num}: {total} files generated")
```

### GUI-Based Generation with RasMap

The `RasMap.postprocess_stored_maps()` method opens the HEC-RAS GUI to generate maps. Use this when RasProcess is not available or for compatibility with older HEC-RAS versions.

```python
from ras_commander import RasCmdr, RasMap

# First, ensure the simulation has been run
RasCmdr.compute_plan("01")

# Generate stored maps (opens HEC-RAS GUI)
success = RasMap.postprocess_stored_maps(
    plan_number="01",
    specify_terrain="Terrain50",
    layers=["Depth", "WSEL"]
)

if success:
    print("Stored maps generated successfully!")
```

### Available Map Layers

Common layer types you can generate:

- `"Depth"` - Flow depth (ft or m)
- `"WSEL"` - Water surface elevation (ft or m)
- `"Velocity"` - Flow velocity magnitude (ft/s or m/s)
- `"Shear"` - Bed shear stress (lb/ft² or N/m²)
- `"Froude Number"` - Froude number (dimensionless)

### Advanced Map Generation Options

```python
# Generate multiple layers for multiple plans
for plan_num in ["01", "02", "03"]:
    RasMap.postprocess_stored_maps(
        plan_number=plan_num,
        specify_terrain="Terrain50",
        layers=["Depth", "WSEL", "Velocity"]
    )

# Generate maximum values for unsteady flow
RasMap.postprocess_stored_maps(
    plan_number="05",
    specify_terrain="LiDAR_2020",
    layers=["Depth (Max)", "WSEL (Max)", "Velocity (Max)"]
)
```

### Custom Output Path

By default, RasProcess.exe writes output to a folder named after the plan's ShortID (e.g., `./PlanShortID/`). This is hardcoded in RasProcess.exe and cannot be overridden via CLI arguments.

The `output_path` parameter works around this by using individual `StoreMap` XML commands with an absolute `OutputBaseFilename`, writing files directly to your requested directory:

```python
# Output to a custom directory
results = RasProcess.store_maps(
    plan_number="01",
    output_path="C:/MyProject/FloodMaps",
    profile="Max",
    wse=True,
    depth=True
)

# Files are now in C:/MyProject/FloodMaps/
for map_type, files in results.items():
    for f in files:
        print(f"  {f}")
```

Relative paths are resolved against the project folder:

```python
# Relative path - resolves to <project_folder>/exported_rasters/
results = RasProcess.store_maps(
    plan_number="01",
    output_path="exported_rasters",
    depth=True
)
```

!!! note "How It Works"
    The default `StoreAllMaps` CLI command hardcodes output to `<project_folder>/<Plan ShortID>/` with no override. When `output_path` is specified, `store_maps()` uses individual `StoreMap` XML commands instead, passing the resolved absolute path as `OutputBaseFilename`. C#'s `Path.Combine()` discards the ShortID prefix when the second argument is absolute, so files are written directly to the requested directory.

### Default Output Location

Without `output_path`, generated stored maps are saved in the project directory:

```
MyRasModel/
├── MyRasModel.rasmap
├── MyRasModel.p01
├── MyRasModel.p01.hdf
└── MyRasModel.p01/
    ├── Depth (Max).tif
    ├── WSEL (Max).tif
    └── Velocity (Max).tif
```

## Raster BenefitArea

`RasProcess.store_maps()` can treat a pre/post plan pair as a custom BenefitArea
product. It generates aligned Depth rasters for both plans and classifies cells
as No Change (`1`), Partially Benefited (`2`), or Fully Benefited (`3`), with
`0` reserved for NoData/background.

BenefitArea mode is Depth-only by default. WSE is optional and does not affect
the classification; enable it only when the additional review raster is worth
the StoreMaps time and storage.

```python
from ras_commander import BenefitAreaConfig, RasBenefits, RasProcess

terrain_tif = RasBenefits.get_registered_terrain_source(
    r"C:\Projects\FloodModel\Terrain\BenefitsTerrain.hdf"
)

config = BenefitAreaConfig(
    pre_plan_number="01",
    terrain_tif=terrain_tif,
    terrain_name="BenefitsTerrain",
    minimum_region_pixels=16,  # use None to disable pixel filtering
    polygon_output=True,       # writes a GeoPackage beside the raster
)

outputs = RasProcess.store_maps(
    plan_number="02",          # post-project plan
    output_path="Benefits/01-to-02",
    profile="Max",
    benefit_area=config,
)

print(outputs["benefit_area"][0])
```

The terrain must be a readable, one-band GeoTIFF and the sole source recorded
by a terrain HDF registered in the project `.rasmap`. If the current terrain
has multiple sources, use `RasTerrain.vrt_to_tiff()` to consolidate a VRT,
create a one-source HDF with `RasTerrain.create_terrain_from_rasters()` or
`RasTerrain.create_terrain_hdf()`, and register it with
`RasMap.add_terrain_layer()`. Associate both source geometries through
`RasMap.associate_geometry_layers(..., terrain_hdf_path=...)` and recompute the
plans so both result HDFs record that same terrain. The workflow verifies those
associations, selects the terrain exclusively for each StoreMaps call, and
restores the original RASMapper configuration. Visibility alone does not
override a different terrain stored in a plan HDF.

Set `include_wse=True` in `BenefitAreaConfig` (or pass `wse=True` to
`store_maps()`) to retain pre/post WSE maps. Set `minimum_region_pixels=None` to
skip the four-connected component filter. `polygon_output=True` creates exact
raster-edge polygons; an explicit `.gpkg`, `.shp`, `.geojson`, `.parquet`, or
`.geoparquet` path is also accepted. Install
`ras-commander[geoparquet]` before requesting either GeoParquet suffix.

This raster workflow is distinct from `HdfBenefitAreas`, which reads maximum
WSE at 2D mesh cells and returns benefit/rise GeoDataFrames rather than a
categorical raster. See the [Benefits Analysis API](../api/benefits.md)
for thresholds, class definitions, terrain setup, and direct-raster usage.

## Calculated Layers (WSE Comparison)

RASMapper Calculated Layers perform raster algebra on plan results. The most common use case is comparing Water Surface Elevation (WSE) between Existing and Proposed conditions to identify benefits and adverse impacts.

### Listing Plan Results and Existing Calculated Layers

```python
from ras_commander import init_ras_project, RasMap

init_ras_project(r"C:\Projects\FloodModel", "7.0")

# Discover available plan result layers
plans = RasMap.list_results_plans()
for p in plans:
    print(f"  {p['name']}")

# List any existing calculated layers
layers = RasMap.list_calculated_layers()
for l in layers:
    print(f"  {l['name']} (under {l['parent_plan']})")
```

### Batch WSE Comparison (Existing vs Proposed)

Generate comparison layers for multiple AEP/boundary condition pairs at once. The formula is `Proposed WSE - Existing WSE`:

- **Positive values** = WSE raised by project (adverse impact)
- **Negative values** = WSE lowered by project (benefit)

```python
created = RasMap.add_wse_comparison_layers(
    plan_pairs=[
        {"exist_plan": "Exist_10yr_Reg_BO", "prop_plan": "Prop_10yr_Reg_BO", "tag": "10yr_Reg"},
        {"exist_plan": "Exist_10yr_Loc_BO", "prop_plan": "Prop_10yr_Loc_BO", "tag": "10yr_Loc"},
        {"exist_plan": "Exist_25yr_Reg_BO", "prop_plan": "Prop_25yr_Reg_BO", "tag": "25yr_Reg"},
        {"exist_plan": "Exist_25yr_Loc_BO", "prop_plan": "Prop_25yr_Loc_BO", "tag": "25yr_Loc"},
        {"exist_plan": "Exist_100yr_Reg_BO", "prop_plan": "Prop_100yr_Reg_BO", "tag": "100yr_Reg"},
        {"exist_plan": "Exist_100yr_Loc_BO", "prop_plan": "Prop_100yr_Loc_BO", "tag": "100yr_Loc"},
    ],
    exist_terrain="Bathy_QESDrone_",
    prop_terrain="Terrain_Proposed_20260313",
)
print(f"Created {len(created)} comparison layers")
```

Each call generates:

1. A `.rasscript` file (VB.NET raster algebra) in `Calculated Layers/`
2. A `<Layer Type="CalculatedLayer">` XML entry in the `.rasmap`
3. A viewport-dynamic diverging color ramp (blue=benefit, red=adverse)

### Custom Calculated Layers

For non-standard comparisons, use `add_calculated_layer()` directly with custom VB.NET script content:

```python
RasMap.add_calculated_layer(
    layer_name="CustomDiff",
    host_plan_name="Prop_10yr_Reg_BO",
    script_content=my_vbnet_script,
    raster_maps=[
        {"result": "Exist_10yr_Reg_BO"},
        {"result": "Prop_10yr_Reg_BO"},
    ],
    terrain_names=["Bathy_QESDrone_", "Terrain_Proposed_20260313"],
)
```

### Removing Calculated Layers

```python
# Remove a single layer (optionally delete the .rasscript file too)
RasMap.remove_calculated_layer("CompareWSE_10yr_Reg", delete_script=True)
```

!!! note "Dry Cell Handling"
    When a cell is wet in one plan but dry in the other, the terrain elevation for the
    dry plan's scenario is substituted as the WSE estimate. Each plan uses its own terrain
    for this fallback (existing terrain for existing-dry cells, proposed terrain for
    proposed-dry cells).

## Manning's n Calibration Workflow

Calibrating Manning's n roughness coefficients is a common modeling task. RAS Commander provides tools to programmatically adjust Manning's n values for 2D flow areas.

### Reading Current Manning's n Values

```python
from ras_commander import RasGeo, RasPlan

# Get geometry file path for the plan
geom_path = RasPlan.get_geom_path("01")

# Extract current Manning's n values
mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)
print(mannings_df)
```

The returned DataFrame contains:

- `Land Cover Class` - Land cover type name
- `Base Manning's n Value` - Current roughness coefficient
- Other metadata depending on your model configuration

### Modifying Manning's n Values

```python
# Increase all Manning's n values by 20%
mannings_df['Base Manning\'s n Value'] *= 1.2

# Or modify specific land cover classes
mannings_df.loc[
    mannings_df['Land Cover Class'] == 'Forest',
    'Base Manning\'s n Value'
] = 0.15

# Write modified values back to geometry file
RasGeo.set_mannings_baseoverrides(geom_path, mannings_df)
```

### Clearing Geometry Preprocessor Files

!!! warning "Critical Step: Clear Geometry Preprocessor"
    After modifying Manning's n values (or any geometry parameters), you **must** clear the geometry preprocessor files. Otherwise, HEC-RAS will use the cached preprocessed geometry and ignore your changes.

```python
# Clear preprocessed geometry files
RasGeo.clear_geompre_files()

# Now re-run the simulation with updated Manning's n
RasCmdr.compute_plan("01")
```

### Calibration Loop Example

```python
# Automated calibration loop
calibration_factors = [0.8, 1.0, 1.2, 1.4]

for factor in calibration_factors:
    # Modify Manning's n
    geom_path = RasPlan.get_geom_path("01")
    mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)
    mannings_df['Base Manning\'s n Value'] *= factor
    RasGeo.set_mannings_baseoverrides(geom_path, mannings_df)

    # Clear preprocessor and run
    RasGeo.clear_geompre_files()
    RasCmdr.compute_plan("01", dest_folder=f"run_n_factor_{factor}")

    # Extract and compare results
    # (See HDF data extraction guide)
```

## Infiltration Data Handling

For 2D unsteady flow models with infiltration, RAS Commander provides the `HdfInfiltration` class to read and modify infiltration parameters stored in HDF files.

### Reading Infiltration Parameters

```python
from ras_commander import HdfInfiltration, ras

# Get infiltration HDF path from rasmap_df
infiltration_path = ras.rasmap_df['infiltration_hdf_path'][0][0]

# Extract current infiltration parameters
infil_df = HdfInfiltration.get_infiltration_baseoverrides(infiltration_path)
print(infil_df)
```

The DataFrame typically contains columns like:

- `Land Cover Class` - Land cover type
- `Maximum Deficit` - Maximum infiltration deficit (in)
- `Initial Deficit` - Initial infiltration deficit (in)
- `Potential Percolation Rate` - Percolation rate (in/hr)
- `Hydraulic Conductivity` - Soil hydraulic conductivity (in/hr)

### Scaling Infiltration Parameters

```python
# Define scale factors for each parameter
scale_factors = {
    'Maximum Deficit': 1.2,        # Increase by 20%
    'Initial Deficit': 1.0,         # No change
    'Potential Percolation Rate': 0.8  # Decrease by 20%
}

# Apply scaling and get updated DataFrame
updated_df = HdfInfiltration.scale_infiltration_data(
    infiltration_path,
    infil_df,
    scale_factors
)

# The scaled values are automatically written to the HDF file
```

### Infiltration Calibration Workflow

```python
from ras_commander import HdfInfiltration, RasGeo, RasCmdr

# 1. Get infiltration data path
infiltration_path = ras.rasmap_df['infiltration_hdf_path'][0][0]
infil_df = HdfInfiltration.get_infiltration_baseoverrides(infiltration_path)

# 2. Modify infiltration parameters
scale_factors = {
    'Maximum Deficit': 1.3,
    'Initial Deficit': 1.1,
    'Potential Percolation Rate': 0.9
}
updated_df = HdfInfiltration.scale_infiltration_data(
    infiltration_path,
    infil_df,
    scale_factors
)

# 3. Clear geometry preprocessor
RasGeo.clear_geompre_files()

# 4. Re-run simulation
RasCmdr.compute_plan("01", dest_folder="calibration_infil_run1")
```

### Common Infiltration Parameters

**Green-Ampt Method:**

- `Hydraulic Conductivity` - Rate of water movement through soil
- `Suction Head` - Soil capillary suction
- `Initial Moisture Deficit` - Initial soil moisture deficit

**SCS Curve Number Method:**

- `Curve Number` - Composite CN based on soil type and land use
- `Initial Abstraction Ratio` - Ia/S ratio (typically 0.2)

## Complete Spatial Data Workflow Example

This example demonstrates a complete workflow combining terrain, Manning's n, and infiltration adjustments:

```python
from ras_commander import (
    init_ras_project, ras, RasMap, RasGeo, RasPlan,
    RasCmdr, HdfInfiltration
)

# 1. Initialize project
init_ras_project(r"C:\Projects\FloodModel", "7.0")

# 2. Check available spatial data
print("Available terrains:", RasMap.get_terrain_names(RasMap.get_rasmap_path()))
print("Rasmap data:\n", ras.rasmap_df)

# 3. Calibration: Adjust Manning's n
geom_path = RasPlan.get_geom_path("01")
mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)

# Increase forest roughness
mannings_df.loc[
    mannings_df['Land Cover Class'] == 'Forest',
    'Base Manning\'s n Value'
] = 0.18

RasGeo.set_mannings_baseoverrides(geom_path, mannings_df)

# 4. Calibration: Adjust infiltration
infiltration_path = ras.rasmap_df['infiltration_hdf_path'][0][0]
infil_df = HdfInfiltration.get_infiltration_baseoverrides(infiltration_path)

scale_factors = {
    'Maximum Deficit': 1.25,
    'Potential Percolation Rate': 0.85
}
HdfInfiltration.scale_infiltration_data(infiltration_path, infil_df, scale_factors)

# 5. Clear preprocessor and run
RasGeo.clear_geompre_files()
RasCmdr.compute_plan("01", dest_folder="calibrated_run")

# 6. Generate result maps
RasMap.postprocess_stored_maps(
    plan_number="01",
    specify_terrain="Terrain50",
    layers=["Depth (Max)", "WSEL (Max)", "Velocity (Max)"]
)

print("Calibration run complete with updated spatial parameters!")
```

## Best Practices

### Always Clear Geometry Preprocessor

!!! warning "Critical for Geometry Changes"
    Whenever you modify geometry-related data (Manning's n, cross sections, structures, etc.), always call:
    ```python
    RasGeo.clear_geompre_files()
    ```
    This ensures HEC-RAS rebuilds the geometry from your modified files rather than using cached preprocessed data.

### Version Control Spatial Data

When calibrating models:

1. Keep original spatial datasets backed up
2. Use `dest_folder` parameter to create separate run directories
3. Document scaling factors and modifications in your scripts
4. Track which parameters changed between calibration iterations

### Verify Changes Before Running

```python
# Good practice: Verify changes before running expensive simulations
mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)
print("Manning's n summary:")
print(mannings_df['Base Manning\'s n Value'].describe())

# Check for unrealistic values
if (mannings_df['Base Manning\'s n Value'] > 0.5).any():
    print("Warning: Some Manning's n values exceed 0.5!")
```

### Use Descriptive Folder Names

```python
# Good: Descriptive folder names for calibration runs
RasCmdr.compute_plan("01", dest_folder="n_increased_20pct_infil_decreased_15pct")

# Bad: Generic folder names
RasCmdr.compute_plan("01", dest_folder="run1")
```

## Troubleshooting

### Maps Not Generating

If `postprocess_stored_maps()` fails:

1. Verify the simulation completed successfully
2. Check that the HDF file exists (`MyModel.p01.hdf`)
3. Ensure terrain name matches exactly (case-sensitive)
4. Confirm RASMapper file is not corrupted

### Manning's n Changes Not Applied

If Manning's n modifications don't affect results:

1. **Most common:** Forgot to call `RasGeo.clear_geompre_files()`
2. Check that you're modifying the correct geometry file
3. Verify the plan references the geometry file you modified
4. Ensure no errors in `set_mannings_baseoverrides()`

### Infiltration Changes Not Applied

If infiltration modifications don't affect results:

1. Call `RasGeo.clear_geompre_files()` after infiltration changes
2. Verify the infiltration HDF path is correct
3. Check that your plan uses infiltration (2D unsteady flow)
4. Ensure infiltration is enabled in the unsteady flow file

## Related Topics

- [Geometry Operations](geometry-operations.md) - Modifying cross sections, structures, and connections
- [HDF Data Extraction](hdf-data-extraction.md) - Reading simulation results from HDF files
- [Plan Execution](plan-execution.md) - Running simulations and parallel execution
- [Workflows & Patterns](workflows-and-patterns.md) - Common workflow patterns including calibration

## Additional Resources

- HEC-RAS Mapper User's Manual - Understanding RASMapper data structures
- HEC-RAS 2D Modeling User's Manual - Manning's n and infiltration guidance
- RAS Commander API Reference - Complete method documentation
