# RASMapper layers and associations

Import `RasMap` from `ras_commander` and call its static methods. Project-path
readers and initialized-project methods have different signatures: pass the
project path or `ras_object` accepted by the selected method rather than assuming
every method uses the global project.

| Operation | Input | Return / persisted effect |
|---|---|---|
| `parse_rasmap`, layer-list methods | `.rasmap` or project path, as documented below | DataFrames or lists describing configured layers |
| `add_terrain_layer` | Existing terrain HDF | Registers terrain in `.rasmap`; does not create elevation data |
| `add_landcover_layer`, `add_soils_layer`, `add_infiltration_layer` | Classification sources and project | Created layer HDF path and registration |
| Classification polygon CRUD | Layer HDF, feature selectors and polygon/class data | GeoDataFrame; native polygon edits for authoring calls |
| Reference maps and basemaps | Existing vector file or supported basemap name | `.rasmap` registration, with method-specific path or Boolean return |
| Geometry association inspection/validation | Compiled geometry HDF or project | Association dictionaries or diagnostic DataFrames |
| `associate_geometry_layers` | Compiled geometry and terrain/classification paths | Updated geometry HDF path |
| `recompute_property_tables` | Geometry and selected native version | Updated HDF path after native property-table processing |

Native classification creation and polygon authoring require the HEC-RAS
runtime supported by that method; reading a layer inventory is a separate
operation. Check source CRS, project units and extent explicitly; see the
[spatial extent contract](../../user-guide/spatial-data.md#authoritative-extents-for-raster-inputs).

Before computing property tables, inspect and validate the compiled-HDF
associations. Afterwards inspect final cell properties, including Manning's n,
using the [HDF API](../hdf.md). An XML registration alone is insufficient.
`RasProcess.validate_geometry_association_cli()` on the
[geometry completion page](geometry-completion.md) is a **mutating native reference
validator**, intended for disposable copies, not a read-only association check.

Examples with retained outputs: [233 — classification polygons](../../notebooks/233_mannings_region_polygon_authoring.md)
and [931 — native terrain export](../../notebooks/931_native_rasmapper_terrain_export.md).

## Layer discovery and authoring

::: ras_commander.RasMap
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - parse_rasmap
        - list_land_classification_layers
        - list_terrain_layers
        - list_landcover_layers
        - list_soils_layers
        - list_infiltration_layers
        - list_land_classification_polygons
        - add_land_classification_polygon
        - update_land_classification_polygon
        - delete_land_classification_polygon
        - add_landcover_layer
        - add_soils_layer
        - add_infiltration_layer
        - get_rasmap_path
        - initialize_rasmap_df
        - get_terrain_names
        - list_map_layers
        - list_reference_map_layers
        - list_basemap_layers
        - set_map_layer_visibility
        - list_standard_basemap_layers
        - add_reference_map_layer
        - add_basemap_layer
        - add_map_layer
        - remove_map_layer
        - ensure_rasmap_compatible
        - add_terrain_layer
        - prune_event_condition_layers
        - ensure_2d_encroachment_plan_layers

## Compiled geometry associations

::: ras_commander.RasMap
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - associate_geometry_layers
        - set_geometry_association
        - get_geometry_association
        - list_geometry_associations
        - validate_geometry_associations
        - get_hdf_geometry_association
        - recompute_property_tables

## Layer validation

`RasMapValidation` performs format, CRS, raster and spatial checks and returns
validation results (or the Boolean convenience result from `is_valid_layer`).
These checks do not run the hydraulic solver.

::: ras_commander.RasMapValidation
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - check_layer_format
        - check_layer_crs
        - check_raster_metadata
        - check_spatial_extent
        - check_terrain_layer
        - check_land_cover_layer
        - check_layer
        - is_valid_layer

