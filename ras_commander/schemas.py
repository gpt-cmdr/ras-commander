"""
schemas.py -- canonical, declarative column contracts for ras-commander's public DataFrames.

This module is the **single source of truth** for the *stable* column surface of the project
DataFrames that ras-commander attaches to a :class:`RasPrj` instance
(``plan_df`` / ``geom_df`` / ``boundaries_df`` / ``rasmap_df``), plus a documented note for the
HDF result frames whose columns are only known at runtime.

It is consumed by ``.claude/scripts/generate_api_surface.py`` to emit the machine-readable
agent surface published at ``/ras/llms/api/dataframes.json`` (so LLMs and ras-commander-mcp can
resolve "what columns does ``plan_df`` have?" without scraping rendered HTML).

Why a declarative file rather than re-deriving columns from construction code: the construction
methods (``RasPrj.get_plan_entries`` / ``get_geom_entries`` / ``get_boundary_conditions``, and
``_land_classification_helper.empty_rasmap_dataframe``) remain the **runtime authority** and may
add extra, project-specific columns beyond this stable core. Pinning the documented contract here
gives agents a stable, reviewable schema and one place to update when a frame's columns change.
Where a frame is built from a static shape (``rasmap_df``), the generator cross-checks this
contract against the live construction and flags drift.

Each entry of :data:`DATAFRAME_SCHEMAS`:
    description   -- one-line summary of the frame
    accessor      -- how a caller obtains the frame from a RasPrj instance
    source        -- the construction site (for maintainers)
    columns       -- list of {name, dtype, description} for the STABLE core columns
    extra_columns -- True if additional project-parsed columns may appear at runtime
    dynamic       -- True if the full column set is only knowable at runtime (HDF frames)
"""

# Schema contract version -- bump when the documented column surface changes meaningfully.
SCHEMA_VERSION = "1.0"

DATAFRAME_SCHEMAS = {
    "plan_df": {
        "description": "One row per HEC-RAS plan in the project, with its linked geometry and flow files.",
        "accessor": "ras.plan_df  (or RasPrj instance .plan_df; refreshed by RasPrj.get_plan_entries())",
        "source": "RasPrj.get_plan_entries()",
        "extra_columns": True,  # additional key=value entries parsed from the .prj plan block
        "dynamic": False,
        "columns": [
            {"name": "plan_number", "dtype": "str", "description": "Plan identifier, e.g. '01'."},
            {"name": "unsteady_number", "dtype": "str | None", "description": "Linked unsteady-flow number, if the plan is unsteady."},
            {"name": "geometry_number", "dtype": "str | None", "description": "Linked geometry number."},
            {"name": "Geom File", "dtype": "str", "description": "Geometry file name (e.g. 'project.g01')."},
            {"name": "Geom Path", "dtype": "str", "description": "Absolute path to the geometry file."},
            {"name": "Flow File", "dtype": "str", "description": "Flow file name (unsteady .u## or steady .f##)."},
            {"name": "Flow Path", "dtype": "str", "description": "Absolute path to the flow file."},
            {"name": "full_path", "dtype": "str", "description": "Absolute path to the plan file (e.g. 'project.p01')."},
        ],
    },
    "geom_df": {
        "description": "One row per geometry file, with parsed structure counts and 1D/2D presence flags.",
        "accessor": "ras.geom_df  (refreshed by RasPrj.get_geom_entries())",
        "source": "RasPrj.get_geom_entries() (counts via GeomMetadata.get_geometry_counts(), HDF-preferred)",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "geom_file", "dtype": "str", "description": "Geometry file name (e.g. 'project.g01')."},
            {"name": "geom_number", "dtype": "str", "description": "Geometry identifier, e.g. '01'."},
            {"name": "full_path", "dtype": "str", "description": "Absolute path to the geometry file."},
            {"name": "hdf_path", "dtype": "str | None", "description": "Absolute path to the geometry HDF (.g##.hdf), if present."},
            {"name": "geom_title", "dtype": "str", "description": "Title from the 'Geom Title=' line."},
            {"name": "description", "dtype": "str", "description": "Text from the BEGIN/END DESCRIPTION block."},
            {"name": "has_1d_xs", "dtype": "bool", "description": "Whether the geometry contains 1D cross sections."},
            {"name": "has_2d_mesh", "dtype": "bool", "description": "Whether the geometry contains a 2D flow-area mesh."},
            {"name": "num_cross_sections", "dtype": "int", "description": "Count of 1D cross sections."},
            {"name": "num_inline_structures", "dtype": "int", "description": "Count of inline structures."},
            {"name": "num_bridges", "dtype": "int", "description": "Count of bridges."},
            {"name": "num_culverts", "dtype": "int", "description": "Count of culverts."},
            {"name": "num_weirs", "dtype": "int", "description": "Count of weirs."},
            {"name": "num_gates", "dtype": "int", "description": "Count of gates."},
            {"name": "num_lateral_structures", "dtype": "int", "description": "Count of lateral structures."},
            {"name": "num_sa_2d_connections", "dtype": "int", "description": "Count of storage-area / 2D connections."},
            {"name": "mesh_cell_count", "dtype": "int", "description": "Total 2D mesh cell count across areas."},
            {"name": "mesh_area_names", "dtype": "list[str]", "description": "Names of the 2D flow areas."},
        ],
    },
    "boundaries_df": {
        "description": "One row per boundary condition across the project's unsteady flow files.",
        "accessor": "ras.boundaries_df  (refreshed by RasPrj.get_boundary_conditions())",
        "source": "RasPrj.get_boundary_conditions() / RasPrj._parse_boundary_condition()",
        "extra_columns": True,  # merged columns from unsteady_df
        "dynamic": False,
        "columns": [
            {"name": "unsteady_number", "dtype": "str", "description": "Unsteady-flow file number the BC belongs to."},
            {"name": "boundary_condition_number", "dtype": "int", "description": "1-based index of the BC within its unsteady file."},
            {"name": "river_reach_name", "dtype": "str", "description": "River/reach the BC is attached to (1D), if any."},
            {"name": "river_station", "dtype": "str", "description": "River station of the BC (1D), if any."},
            {"name": "storage_area_name", "dtype": "str", "description": "Storage area the BC is attached to, if any."},
            {"name": "pump_station_name", "dtype": "str", "description": "Pump station the BC is attached to, if any."},
            {"name": "area_2d", "dtype": "str", "description": "2D flow area the BC is attached to, if any."},
            {"name": "bc_line_name", "dtype": "str", "description": "Named BC line (2D external boundary), if any."},
            {"name": "bc_type", "dtype": "str", "description": "Boundary type, e.g. 'Flow Hydrograph', 'Stage Hydrograph', 'Rating Curve', 'Normal Depth', 'Lateral Inflow', 'Uniform Lateral Inflow', 'Gate Opening', 'T.S. Gate Openings', 'Unknown'."},
        ],
    },
    "rasmap_df": {
        "description": "Single-row frame of RASMapper layer/terrain/land-cover/infiltration paths and settings.",
        "accessor": "ras.rasmap_df  (built by RasMap.initialize_rasmap_df())",
        "source": "_land_classification_helper.empty_rasmap_dataframe() (shape) + RasMap.parse_rasmap() (.rasmap XML)",
        # shape_fn: zero-arg callable returning this frame's empty shape; the docs build's schema
        # validator (validate_api_schemas.py) calls it and fails the build if these columns drift.
        "shape_fn": "ras_commander._land_classification_helper.empty_rasmap_dataframe",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "projection_path", "dtype": "str | None", "description": "Path to the projection (.prj) referenced by the .rasmap."},
            {"name": "profile_lines_path", "dtype": "list", "description": "Profile-line layer paths."},
            {"name": "soil_layer_path", "dtype": "list", "description": "Soil-layer (infiltration) paths."},
            {"name": "infiltration_hdf_path", "dtype": "list", "description": "Infiltration HDF layer paths."},
            {"name": "landcover_hdf_path", "dtype": "list", "description": "Land-cover HDF layer paths."},
            {"name": "terrain_hdf_path", "dtype": "list", "description": "Terrain HDF layer paths."},
            {"name": "reference_map_layer_names", "dtype": "list", "description": "Names of reference map layers."},
            {"name": "reference_map_layer_path", "dtype": "list", "description": "Paths of reference map layers."},
            {"name": "basemap_layer_names", "dtype": "list", "description": "Names of basemap layers."},
            {"name": "basemap_layer_path", "dtype": "list", "description": "Paths of basemap layers."},
            {"name": "current_settings", "dtype": "dict", "description": "RASMapper current-settings map (rendering/units/etc.)."},
        ],
    },
    "hdf_result_frames": {
        "description": "Result DataFrames returned by the Hdf* classes (mesh/xsec/plan/breach results).",
        "accessor": "Hdf*.<method>(plan_hdf)  -- e.g. HdfResultsMesh.get_mesh_timeseries(...), HdfResultsXsec.get_xsec_timeseries(...)",
        "source": "ras_commander.hdf.HdfResults* (columns derived from HDF group attributes & datasets at runtime)",
        "extra_columns": True,
        "dynamic": True,
        "columns": [],
        "note": (
            "HDF result frames are constructed from the HDF5 file's group attributes and dataset "
            "schemas at call time, so their exact columns depend on the model and plan and are not "
            "statically enumerable. See the HdfResultsMesh / HdfResultsXsec / HdfResultsPlan / "
            "HdfResultsBreach API pages for per-method return shapes."
        ),
    },
}
