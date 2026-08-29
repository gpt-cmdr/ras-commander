# Terrain Modules

Classes for terrain creation, terrain modification writing, and terrain modification analysis.

!!! note "Platform Requirements"
    `RasTerrainMod` requires Windows with pythonnet and a HEC-RAS installation (uses RasMapperLib.dll via .NET interop). `RasTerrain.export_rasmapper_terrain()` runs natively on Windows and through a configured Wine runtime on Linux. Other `RasTerrain` and `RasTerrainModWriter` methods retain their documented platform requirements.

## RasTerrain

Terrain HDF creation from rasters using `RasProcess.exe CreateTerrain`.

### Terrain Creation Methods

- `create_terrain_hdf(input_rasters, output_hdf, projection_prj, units="Feet", stitch=True, hecras_version="7.0", timeout_seconds=600)` - Create HEC-RAS terrain HDF from input rasters
- `create_terrain_from_rasters(input_rasters, output_folder, terrain_name="Terrain", units="Feet", stitch=True, hecras_version="7.0", generate_prj=True)` - Convenience wrapper with automatic PRJ generation

### Native Registered-Terrain Export

- `export_rasmapper_terrain(ras_project_path, output_tif, terrain_name=None, extent=None, downsample_factor=1, rasterize_modifications=True, overwrite=False, timeout_seconds=1800, hecras_version=None, ras_object=None, receipt_path=None)` - Consolidate a registered RAS Mapper terrain to one semantically validated GeoTIFF

The native export loads the exact terrain entry from the project's `.rasmap`.
Consequently, source priority/order, stitches, masks, and terrain-modification
surfaces remain HEC-RAS behavior. The base raster always uses nearest-neighbor
and the output cell size is exactly the finest registered source cell size
times `1`, `2`, `4`, or `8`. Requested bounds snap outward to the authoritative
source grid.

The method writes to a unique same-directory partial, validates the GeoTIFF,
then atomically promotes it. `overwrite=False` is the default. A JSON receipt
is written beside the TIFF by default, and the returned `TerrainExportResult`
is bool-compatible. The derivative is not registered back into the project.

```python
from pathlib import Path
from ras_commander import RasMap, RasTerrain

project = Path(r"C:\Models\Example\Example.prj")
print(RasMap.list_terrain_layers(project)[["name", "resolved_path"]])

result = RasTerrain.export_rasmapper_terrain(
    project,
    Path(r"C:\Exports\channel_window_2x.tif"),
    terrain_name="Terrain",
    extent=(100000.0, 200000.0, 101000.0, 201000.0),
    downsample_factor=2,
    rasterize_modifications=True,
    hecras_version="6.6",
)

if not result:
    raise RuntimeError(result.error)
print(result.output_path)
print(result.receipt_path)
print(result.source_inventory)
```

On Linux, configure `RasProcess.configure_wine()` first. The host clones the
configured Wine prefix into task-local state by default. An orchestration
system that already supplies a prefix owned exclusively by the current task
may set `RAS_COMMANDER_TERRAIN_WINE_PREFIX_IS_TASK_LOCAL=1`; do not set it for
a shared prefix.

`RasTerrainMod.compute_modified_terrain_raster()` remains available for small,
row-sampled analytical rasters. It is not a fallback for this native,
modification-aware consolidation operation.

### Utility Methods

- `vrt_to_tiff(vrt_path, output_path, compression="LZW", create_overviews=True, overview_levels=None, nodata_value=None, hecras_version="7.0")` - Convert VRT to single optimized TIFF using HEC-RAS bundled GDAL
- `get_available_versions()` - List installed HEC-RAS versions with terrain creation support

### Bank Line Generation

- `compute_bank_lines(geom_path, crs=None, ras_object=None)` - Generate bank-line geometry from cross-section bank stations

### Usage

```python
from ras_commander import RasTerrain

# Create terrain from rasters
terrain_hdf = RasTerrain.create_terrain_from_rasters(
    input_rasters=["dem_north.tif", "dem_south.tif"],
    output_folder="terrain/",
    terrain_name="Project_Terrain",
    units="Feet",
    hecras_version="7.0",
)
```

## RasTerrainModWriter

Line and polygon terrain modification HDF/`.rasmap` writing. Also available as the alias `RasTerrainModification`.

### Line Modification Methods

- `add_high_ground_modification(terrain_hdf_path, rasmap_path, name, polyline_points, top_width=20.0, side_slope=2.0, ...)` - Add levee/road terrain modification with trapezoidal profile along polyline (TakeHigher mode)
- `add_fill_surface_modification(terrain_hdf_path, rasmap_path, name, polyline_points, top_width=20.0, side_slope=2.0, ...)` - Add fill-surface (SetValue) modification along polyline
- `add_channel_modification(terrain_hdf_path, rasmap_path, name, polyline_points, width=50.0, depth=10.0, left_slope=3.0, right_slope=3.0, ...)` - Add trapezoidal channel modification (TakeLower mode)

### Polygon Modification Methods

- `add_modification_polygon(terrain_hdf_path, name, polygon_coords, elevation_method="boundary_from_terrain", control_points=None, ...)` - Add polygon multipoint modification (detention pond/wetland grading)

### Group Management

- `add_modification_group(terrain_hdf_path, rasmap_path, group_name="Modifications")` - Add empty modification group to terrain HDF and `.rasmap`

### Query Methods

- `list_modifications(terrain_hdf_path)` - List all terrain modifications stored in HDF sidecar group
- `get_modification_profile(terrain_hdf_path, name)` - Read modification station/elevation profile

### Analysis Methods

- `sample_modification_surface(terrain_hdf_path, name, points, existing_elevations=None, ...)` - Evaluate line modification surface at XY points
- `apply_modification_to_profile(terrain_hdf_path, name, profile, ...)` - Apply line modification to existing terrain profile
- `compare_before_after_profiles(rasmap_existing, rasmap_modified, geom_hdf_path, x_coords, y_coords, ...)` - Compare terrain profiles before/after modification

### Usage

```python
from ras_commander import RasTerrainModWriter

# Add a levee (high ground)
RasTerrainModWriter.add_high_ground_modification(
    terrain_hdf_path="Terrain/Terrain.hdf",
    rasmap_path="Project.rasmap",
    name="Proposed Levee",
    polyline_points=[(x1, y1), (x2, y2), (x3, y3)],
    top_width=20.0,
    side_slope=3.0,
    elevation=25.0,
)

# Add a detention pond (polygon)
RasTerrainModWriter.add_modification_polygon(
    terrain_hdf_path="Terrain/Terrain.hdf",
    name="Detention Pond",
    polygon_coords=[(x1, y1), (x2, y2), (x3, y3), (x4, y4)],
    control_points=[(cx, cy, target_elev)],
    mode="set_value",
    rasmap_path="Project.rasmap",
)
```

## RasTerrainMod

Terrain profile and volume comparison with modifications applied. Uses RasMapperLib.dll via pythonnet to sample the actual modified terrain surface.

!!! warning "Windows Only"
    Requires Windows, pythonnet, and an installed HEC-RAS version. Call `setup_gdal_bridge()` once before other methods.

### Setup

- `setup_gdal_bridge(hecras_version="7.0", python_dir=None, create_junction=True)` - Configure HEC-RAS GDAL runtime for pythonnet before loading

### Terrain Sampling

- `get_terrain_extent(rasmap_path, geom_hdf_path, ras_object=None)` - Get terrain bounding box with modifications applied
- `get_terrain_profile(rasmap_path, geom_hdf_path, x_coords, y_coords, filter_tolerance=0.01, ras_object=None)` - Sample terrain elevation along polyline
- `get_terrain_volume_elevation(rasmap_path, geom_hdf_path, x_coords, y_coords, ...)` - Compute elevation-volume curve for polygon

### Comparison Methods

- `compare_terrain_profiles(rasmap_existing, rasmap_proposed, geom_hdf_path, x_coords, y_coords, ...)` - Compare terrain profiles between existing and proposed (cut/fill analysis)
- `compare_terrain_volumes(rasmap_existing, rasmap_proposed, geom_hdf_path, x_coords, y_coords, ...)` - Compare elevation-volume curves for no-net-fill analysis

### Raster Export

- `compute_modified_terrain_raster(rasmap_path, geom_hdf_path, terrain_tif_path, output_tif_path=None, ...)` - Compute full-resolution raster of terrain with modifications applied

### Usage

```python
from ras_commander.terrain import RasTerrainMod

# One-time setup
RasTerrainMod.setup_gdal_bridge("7.0")

# Compare existing vs proposed terrain along a profile
comparison = RasTerrainMod.compare_terrain_profiles(
    rasmap_existing="Existing.rasmap",
    rasmap_proposed="Proposed.rasmap",
    geom_hdf_path="Model.g01.hdf",
    x_coords=[x1, x2, x3],
    y_coords=[y1, y2, y3],
)
print(comparison[['station', 'existing_elevation', 'proposed_elevation', 'difference']])
```

## Related Examples

| Notebook | Description |
|----------|-------------|
| `316_terrain_modifications.ipynb` | Terrain modification writer: high ground, channel, polygon |
| `920_terrain_creation.ipynb` | Terrain HDF creation from rasters |
| `930_terrain_modification_analysis.ipynb` | Cut/fill analysis with RasTerrainMod |
