# Raster BenefitArea Analysis

RAS Commander can generate a categorical BenefitArea raster by
comparing aligned pre-project and post-project Depth GeoTIFFs. The normal entry
point is `RasProcess.store_maps()` with a `BenefitAreaConfig`: it creates the
required Depth maps for both plans, selects one registered terrain, and then
classifies the depth reduction.

Water-surface elevation is not required for the classification. BenefitArea
mode therefore generates Depth only by default. WSE can be requested for
provenance or other review needs, but it adds StoreMaps runtime and storage.

## Classification

The default classification uses these thresholds:

- A pre-project cell is flooded when Depth is strictly greater than `0.05`.
- A cell qualifies for benefit when pre-project Depth minus effective
  post-project Depth is at least `0.25`.
- Post-project NoData is treated as dry only within the valid pre-project
  domain.

Both thresholds use the Depth raster's vertical/model units. The defaults
`0.05` and `0.25` assume feet. For a metric model, pass thresholds converted
to metres (or the project's actual vertical units) explicitly.

The output is a one-band `uint8` GeoTIFF with a categorical color table:

| Code | Category | Meaning |
|------|----------|---------|
| `0` | NoData/background | Outside the analysis domain, not classified, or removed by filtering |
| `1` | No Change | The post-project cell is flooded and no qualifying benefit exists, including cells newly flooded in the post-project result |
| `2` | Partially Benefited | The depth reduction qualifies, but post-project Depth remains greater than `0.05` |
| `3` | Fully Benefited | The depth reduction qualifies and the post-project cell is dry |

If `analysis_boundary` is supplied, classification is limited to cells whose
centers fall inside it. Cells inside `improvement_boundary` are excluded from
that analysis domain. Boundary datasets must contain polygon geometry. A bare
Shapely `Polygon` or `MultiPolygon` has no CRS metadata and is therefore
interpreted in the Depth raster's CRS; use a GeoSeries, GeoDataFrame, or vector
dataset when reprojection is required.

## Region Filtering and Polygon Output

`minimum_region_pixels=16` applies the component filter independently to
classes 1 through 3. Four-cell connectivity is used: components smaller than
the threshold are changed to code 0, while a component exactly equal to the
threshold is retained.

Set `minimum_region_pixels=None` to disable pixel filtering:

```python
from ras_commander import BenefitAreaConfig, RasBenefits

config = BenefitAreaConfig(
    pre_plan_number="01",
    terrain_tif=RasBenefits.get_registered_terrain_source(
        r"C:\Projects\Model\Terrain\BenefitsTerrain.hdf"
    ),
    minimum_region_pixels=None,
)
```

Polygon creation is optional. `polygon_output=True` writes a GeoPackage beside
the BenefitArea raster. An explicit path may use `.gpkg`, `.shp`, `.geojson`,
`.parquet`, or `.geoparquet`. GeoParquet output requires the optional dependency
installed with `pip install "ras-commander[geoparquet]"`. Polygon boundaries
follow the final raster cell edges using four-cell connectivity; they are not
smoothed or simplified by default.

Set `polygon_simplify_tolerance` to simplify polygon edges after
classification, filtering, statistics, and dissolve. The tolerance is expressed
in the output CRS map units. This affects only the optional polygon geometry;
the categorical raster remains the authoritative output.

!!! warning "Production-scale polygon memory"
    Raster classification and filtering are bounded-memory workflows.
    Polygonization is not: it materializes component geometries and dissolves
    them by class. On very large production grids, this can require
    substantially more memory than generating the authoritative categorical
    raster. Request the
    polygon only when the downstream deliverable needs it.

## Terrain Requirement

The paired StoreMaps workflow requires one readable, projected, one-band
GeoTIFF that is also the sole source recorded by a terrain HDF registered in
the project `.rasmap`. The supplied `terrain_tif` must resolve to that exact
source file. Both plan-result HDFs, including every populated 2D flow-area
terrain association, must reference that same terrain HDF. This constraint
ensures that each plan produces exactly one Depth GeoTIFF from the same terrain
surface and grid.

If the project terrain has multiple source rasters, consolidate it and register
a new one-source terrain before running the comparison:

```python
from ras_commander import RasBenefits, RasMap, RasTerrain

# If a VRT mosaic already exists, convert it to one GeoTIFF.
consolidated_tif = RasTerrain.vrt_to_tiff(
    vrt_path=r"C:\Projects\Model\Terrain\TerrainMosaic.vrt",
    output_path=r"C:\Projects\Model\Terrain\BenefitsTerrain.tif",
)

# Create a HEC-RAS terrain from that one source raster.
terrain_hdf = RasTerrain.create_terrain_from_rasters(
    input_rasters=[consolidated_tif],
    output_folder=r"C:\Projects\Model\Terrain",
    terrain_name="BenefitsTerrain",
    units="Feet",
)

# Register the terrain in the initialized project's RASMapper file.
RasMap.add_terrain_layer(
    terrain_hdf=terrain_hdf,
    rasmap_path=RasMap.get_rasmap_path(),
    layer_name="BenefitsTerrain",
)

# Read the exact sole TIFF path recorded by the HDF. HEC-RAS may create a
# prefixed companion TIFF rather than record consolidated_tif directly.
terrain_tif = RasBenefits.get_registered_terrain_source(terrain_hdf)
```

The lower-level alternatives are
`RasTerrain.create_terrain_hdf()` for terrain creation and
`RasMap.set_terrain_layer_visibility(..., exclusive=True)` for explicit
selection. Associate each source geometry with the common terrain using
`RasMap.associate_geometry_layers(..., terrain_hdf_path=terrain_hdf)` and
recompute both plans so their result HDFs record that association. BenefitArea
checks those plan-HDF associations before mapping, selects the configured
terrain temporarily, and restores the original `.rasmap` afterward. A project
may contain other registered terrains; they are allowed as long as both plans
reference the selected single-TIFF terrain.

## Generate Pre/Post Maps and BenefitArea

In this example plan `01` is pre-project and plan `02` is post-project. The
single call runs StoreMaps separately for both plans and then creates the
categorical raster:

```python
from ras_commander import (
    BenefitAreaConfig,
    RasBenefits,
    RasProcess,
    init_ras_project,
)

init_ras_project(r"C:\Projects\Model", "6.6")
terrain_hdf = r"C:\Projects\Model\Terrain\BenefitsTerrain.hdf"
terrain_tif = RasBenefits.get_registered_terrain_source(terrain_hdf)

config = BenefitAreaConfig(
    pre_plan_number="01",
    terrain_tif=terrain_tif,
    terrain_name="BenefitsTerrain",
    minimum_region_pixels=16,
    polygon_output=True,
    polygon_simplify_tolerance=None,  # exact raster-cell edges
)

outputs = RasProcess.store_maps(
    plan_number="02",              # post-project plan
    output_path="Benefits/01-to-02",
    profile="Max",
    benefit_area=config,
)

print(outputs["benefit_source_pre_depth"][0])
print(outputs["benefit_source_post_depth"][0])
print(outputs["benefit_area"][0])
print(outputs["benefit_area_polygon"][0])
```

In BenefitArea mode, `depth=True`, `wse=False`, and `velocity=False` are the
contextual defaults. Depth cannot be disabled. Use `output_path` for the
comparison root; `output_folder` is not supported because the two plans are
mapped into separate `p##` subdirectories.

To retain WSE maps for both plans, set `include_wse=True` on the configuration
or pass `wse=True` to `store_maps()`:

```python
from ras_commander import BenefitAreaConfig, RasBenefits, RasProcess

terrain_tif = RasBenefits.get_registered_terrain_source(
    r"C:\Projects\Model\Terrain\BenefitsTerrain.hdf"
)

config = BenefitAreaConfig(
    pre_plan_number="01",
    terrain_tif=terrain_tif,
    terrain_name="BenefitsTerrain",
    include_wse=True,
)

outputs = RasProcess.store_maps(
    plan_number="02",
    output_path="Benefits/01-to-02-with-wse",
    benefit_area=config,
)
```

WSE remains supplemental; it does not change the BenefitArea calculation.

## Calculate from Existing Depth Rasters

Use `RasBenefits.create_benefit_area()` directly when aligned Depth rasters
already exist:

```python
from ras_commander import RasBenefits

result = RasBenefits.create_benefit_area(
    pre_depth_tif="Pre/Depth (Max).tif",
    post_depth_tif="Post/Depth (Max).tif",
    terrain_tif="Terrain/BenefitsTerrain.tif",
    output_tif="Benefits/Benefit Area.tif",
    minimum_region_pixels=None,
    polygon_output="Benefits/Benefit Area.gpkg",
    polygon_simplify_tolerance=5.0,
)

print(result.statistics)
```

The Depth rasters must have identical shape, CRS, resolution, and origin. The
terrain may use a different resolution, but it must use the same projected CRS
and cover the Depth extent.

## Raster BenefitArea versus HdfBenefitAreas

`RasBenefits` and `HdfBenefitAreas` answer different questions and are not
interchangeable:

| API | Input and method | Primary output |
|-----|------------------|----------------|
| `RasBenefits` / `BenefitAreaConfig` | Compares aligned pre/post Depth rasters using configurable thresholds and optional pixel filtering | Categorical BenefitArea GeoTIFF and optional exact-edge or simplified polygons |
| `HdfBenefitAreas` | Compares maximum WSE at matched 2D mesh cells directly from two plan HDF files | Benefit/rise polygons and point GeoDataFrames |

Use `HdfBenefitAreas` for mesh-based WSE reduction and rise analysis. Use
`RasBenefits` when the deliverable is a categorical raster classification
generated from stored Depth maps.

## Public Types

- `BenefitAreaConfig` — pair-aware StoreMaps configuration.
- `BenefitAreaResult` — direct-raster result paths, thresholds, and class-area
  statistics.
- `BenefitCategory` — integer class codes 0 through 3.
- `RasBenefits` — terrain validation, array classification, region filtering,
  and raster/polygon generation.
- `RasProcess.store_benefit_area()` — explicit paired-plan orchestration;
  `RasProcess.store_maps(..., benefit_area=config)` is the usual entry point.
