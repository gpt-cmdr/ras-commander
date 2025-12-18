# RASMapper Automation

This subpackage provides tools for programmatic result mapping and raster export automation, bypassing the RASMapper GUI for batch workflows.

## Purpose

The mapping subpackage automates the conversion of HEC-RAS results to georeferenced rasters (GeoTIFF) and enables custom interpolation methods not available in the RASMapper GUI.

## Module Organization

The mapping subpackage contains 3 modules organized by function:

### rasterization.py (Raster Export)

**RasRasterization** - Convert HEC-RAS results to rasters (22 KB):

**Core Rasterization**:
- `results_to_raster()` - Convert HDF results to georeferenced GeoTIFF
- `batch_export_variables()` - Export multiple variables in one pass
- `export_max_envelope()` - Create maximum extent/depth/velocity rasters

**Supported Variables**:
- **Depth**: Water depth (ft or m)
- **Velocity**: Flow velocity (ft/s or m/s)
- **WSE**: Water surface elevation (ft or m)
- **Shear Stress**: Boundary shear stress (lb/ft² or N/m²)
- **Unit Discharge**: Flow per unit width (cfs/ft or m³/s/m)

**Resolution Control**:
- `set_resolution()` - Custom raster cell size (independent of HEC-RAS mesh)
- `match_mesh_resolution()` - Use HEC-RAS 2D mesh cell size
- `auto_resolution()` - Automatic resolution based on mesh density

**Extent Control**:
- `set_extent()` - Custom bounding box (xmin, ymin, xmax, ymax)
- `use_mesh_extent()` - Full 2D area extent
- `clip_to_polygon()` - Clip results to watershed or study area

**Coordinate Systems**:
- Inherits projection from HEC-RAS geometry HDF
- Supports reprojection to different CRS
- Output in GeoTIFF (GDAL-compatible)

### sloped_interpolation.py (Advanced Interpolation)

**SlopedInterpolation** - Floodplain interpolation algorithms (28 KB):

**Interpolation Methods**:

**1. Flat Water Surface** (RASMapper default):
- `flat_interpolation()` - Constant WSE across floodplain
- Simple and fast
- Appropriate for low-gradient floodplains

**2. Sloped Water Surface**:
- `sloped_interpolation()` - Linear water surface slope interpolation
- Accounts for energy gradient
- Better for high-gradient channels

**3. TIN-Based Interpolation**:
- `tin_interpolation()` - Triangulated Irregular Network interpolation
- Honors breaklines and mesh edges
- Most accurate for complex terrain

**4. IDW Interpolation**:
- `idw_interpolation()` - Inverse Distance Weighted interpolation
- Smooth transitions between mesh cells
- Configurable search radius and power parameter

**Algorithm Selection Guidance**:
- **Flat**: Low-gradient rivers, lakes, coastal (slope < 0.001)
- **Sloped**: Moderate-gradient streams (0.001 < slope < 0.01)
- **TIN**: Complex terrain, urban areas, mixed gradients
- **IDW**: Smooth visualization, presentation graphics

**Breakline Support**:
- `apply_breaklines()` - Enforce breaklines in interpolation
- Honor 1D cross sections as breaklines
- Respect 2D mesh refinement regions

**Performance**:
- Vectorized operations (NumPy/SciPy)
- Parallel processing for large meshes
- Memory-efficient streaming for very large models

### __init__.py (Package Interface)

**Public API**:
```python
from ras_commander.mapping import RasRasterization, SlopedInterpolation

# Convenience imports
from ras_commander.mapping import (
    RasRasterization,
    SlopedInterpolation
)
```

## Programmatic Result Mapping Workflow

Complete workflow without RASMapper GUI:

### 1. Load HEC-RAS Results

Access HDF data:
```python
from ras_commander import HdfResultsMesh
from ras_commander.mapping import RasRasterization

# Get maximum depth from results
max_depth = HdfResultsMesh.get_mesh_maximum(
    "01",
    variable="Depth"
)
```

### 2. Configure Rasterization

Set resolution and extent:
```python
# Custom resolution (10 ft cells)
RasRasterization.set_resolution(cell_size=10.0)

# Or match HEC-RAS mesh
RasRasterization.match_mesh_resolution("01")

# Set extent (optional - defaults to full mesh)
RasRasterization.set_extent(
    xmin=500000,
    ymin=4000000,
    xmax=510000,
    ymax=4010000
)
```

### 3. Export to Raster

Generate GeoTIFF:
```python
# Single variable
RasRasterization.results_to_raster(
    results=max_depth,
    output_file="max_depth.tif",
    variable="Depth",
    interpolation="sloped"  # or "flat", "tin", "idw"
)

# Batch export multiple variables
RasRasterization.batch_export_variables(
    plan_hdf="MyPlan.p01.hdf",
    variables=["Depth", "Velocity", "WSE"],
    output_dir="rasters/",
    interpolation="sloped"
)
```

### 4. Post-Process (Optional)

Additional raster operations:
```python
# Create maximum envelope across multiple time steps
max_envelope = RasRasterization.export_max_envelope(
    plan_hdf="01",
    variable="Depth",
    output_file="depth_envelope.tif"
)

# Clip to study area
RasRasterization.clip_to_polygon(
    raster="max_depth.tif",
    polygon="study_area.shp",
    output="max_depth_clipped.tif"
)
```

## Stored Map Generation Workflow

Automate RASMapper stored map creation:

### 1. Configure RASMapper (RasMap)

Set up mapping preferences:
```python
from ras_commander import RasMap

# Parse current RASMapper configuration
rasmap_config = RasMap.parse_rasmap("MyProject.rasmap")

# Update terrain and result layers
RasMap.update_terrain(rasmap_config, "terrain.tif")
RasMap.add_result_layer(rasmap_config, "MyPlan.p01.hdf", "Depth (ft)")
```

### 2. Generate Stored Map

Create stored map via RASMapper:
```python
# Generate stored map (requires RASMapper installed)
RasMap.generate_stored_map(
    rasmap_file="MyProject.rasmap",
    layer_name="Depth (ft)",
    output_name="MaxDepth_StoredMap"
)
```

### 3. Export Stored Map

Extract raster from stored map:
```python
# Export stored map to GeoTIFF
RasMap.export_stored_map(
    rasmap_file="MyProject.rasmap",
    stored_map="MaxDepth_StoredMap",
    output_file="stored_map_depth.tif"
)
```

## Interpolation Method Comparison

### Flat Water Surface
**Pros**:
- Fast computation
- Simple, well-understood
- Appropriate for low-gradient systems

**Cons**:
- Ignores energy gradient
- Poor for steep channels
- May show unrealistic pooling

**Use when**: Floodplain slope < 0.001, large reservoirs, coastal areas

### Sloped Water Surface
**Pros**:
- Accounts for energy gradient
- Better representation of flow direction
- Moderate computational cost

**Cons**:
- Assumes uniform slope
- May not honor complex terrain

**Use when**: 0.001 < slope < 0.01, natural channels, moderate gradients

### TIN Interpolation
**Pros**:
- Honors mesh edges and breaklines
- Most accurate for complex terrain
- Respects discontinuities

**Cons**:
- Slower computation
- Requires quality mesh

**Use when**: Urban areas, complex terrain, mixed gradients, high accuracy needed

### IDW Interpolation
**Pros**:
- Smooth results
- Good for visualization
- Configurable parameters

**Cons**:
- Can smooth over important features
- Computationally expensive for large areas

**Use when**: Presentation graphics, smooth visualization, irregular mesh

## Custom Resolution Guidelines

**High Resolution** (< 10 ft cells):
- Urban flood mapping
- Detailed infrastructure analysis
- Regulatory floodplain mapping
- **Caution**: Large file sizes, slow processing

**Medium Resolution** (10-50 ft cells):
- General floodplain mapping
- Most HEC-RAS 2D applications
- Balanced accuracy and file size

**Coarse Resolution** (> 50 ft cells):
- Regional studies
- Preliminary analysis
- Visualization for large watersheds
- Fast processing, smaller files

**Best Practice**: Match raster resolution to HEC-RAS mesh resolution (±50%)

## Coordinate System Handling

### Automatic Projection
Rasters inherit projection from HEC-RAS geometry:
```python
# Projection read from geometry HDF automatically
RasRasterization.results_to_raster(
    results=max_depth,
    output_file="max_depth.tif"
)
# Output CRS matches HEC-RAS model
```

### Reprojection
Convert to different coordinate system:
```python
# Reproject to different CRS
RasRasterization.results_to_raster(
    results=max_depth,
    output_file="max_depth_wgs84.tif",
    target_crs="EPSG:4326"  # WGS84 lat/lon
)
```

### Common Coordinate Systems
- **State Plane**: EPSG codes vary by state/zone
- **UTM**: EPSG codes based on zone (e.g., UTM Zone 17N = EPSG:32617)
- **WGS84**: EPSG:4326 (lat/lon)
- **Web Mercator**: EPSG:3857 (for web mapping)

## Key Features

### Multi-Level Verifiability
- **HEC-RAS Projects**: Results remain openable in RASMapper GUI for traditional review
- **Visual Outputs**: GeoTIFF rasters viewable in QGIS, ArcGIS, or any GIS software
- **Code Audit Trails**: All functions use @log_call decorators for execution tracking

### Batch Processing
- Export multiple variables simultaneously
- Process multiple plans in parallel
- Automated raster generation for reporting

### Custom Interpolation
- Algorithms beyond RASMapper GUI capabilities
- Fine-tuned control over interpolation parameters
- Support for custom breaklines and constraints

## Dependencies

**Required**:
- numpy (array operations)
- rasterio (raster I/O and creation)
- scipy (interpolation algorithms)
- geopandas (polygon clipping)

**Optional**:
- gdal (advanced raster operations)
- matplotlib (preview plots)

**Installation**:
```bash
pip install rasterio scipy geopandas
```

## Performance

### Speed
- **Small models** (< 10,000 cells): < 10 seconds per raster
- **Medium models** (10,000-100,000 cells): 30-120 seconds per raster
- **Large models** (> 100,000 cells): 2-10 minutes per raster

**Optimization**:
- Use coarser resolution for faster processing
- Parallel export of multiple variables
- Stream processing for very large meshes

### File Sizes
- **Float32** (default): ~4 MB per million cells
- **Compression**: LZW or DEFLATE can reduce by 50-70%
- **NoData optimization**: Only store valid result cells

## Example Notebooks

Complete workflow demonstrations:

- `examples/15_a_floodplain_mapping_gui.ipynb` - RASMapper GUI stored map generation
- `examples/15_b_floodplain_mapping_rasprocess.ipynb` - RasProcess raster exports
- `examples/15_c_floodplain_mapping_python_gis.ipynb` - Programmatic Python GIS mapping

## Common Workflows

### Maximum Depth Mapping
```python
from ras_commander.mapping import RasRasterization

# Get maximum depth
max_depth = HdfResultsMesh.get_mesh_maximum("01", variable="Depth")

# Export to raster
RasRasterization.results_to_raster(
    results=max_depth,
    output_file="max_depth.tif",
    interpolation="sloped"
)
```

### Multi-Variable Export
```python
# Export depth, velocity, and WSE
RasRasterization.batch_export_variables(
    plan_hdf="01",
    variables=["Depth", "Velocity", "WSE"],
    output_dir="results/rasters/",
    interpolation="sloped",
    resolution=10.0  # 10 ft cells
)
```

### Time Series Animation
```python
# Export raster for each timestep
time_steps = HdfResultsMesh.get_output_times("01")

for i, time in enumerate(time_steps):
    depth = HdfResultsMesh.get_mesh_timeseries("01", variable="Depth", time_index=i)

    RasRasterization.results_to_raster(
        results=depth,
        output_file=f"animation/depth_{i:04d}.tif",
        interpolation="flat"
    )
# Assemble into animation using external tool (ffmpeg, ArcGIS, etc.)
```

## Integration with GIS

### QGIS
Load rasters directly:
```python
# QGIS Python console
iface.addRasterLayer("max_depth.tif", "Maximum Depth")
```

### ArcGIS Pro
Use geoprocessing:
```python
import arcpy
arcpy.management.MakeRasterLayer("max_depth.tif", "Max Depth")
```

### Python GIS
Process with rasterio/geopandas:
```python
import rasterio
import geopandas as gpd

# Read raster
with rasterio.open("max_depth.tif") as src:
    depth_array = src.read(1)
    transform = src.transform

# Extract floodplain (depth > 0)
floodplain = depth_array > 0
```

## See Also

- Parent library context: `ras_commander/CLAUDE.md`
- RASMapper configuration: `ras_commander.RasMap`
- HDF mesh results: `ras_commander.HdfResultsMesh`
- Spatial data utilities: `.claude/rules/python/path-handling.md`
