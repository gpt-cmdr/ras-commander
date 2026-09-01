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
SCHEMA_VERSION = "1.6"

DATAFRAME_SCHEMAS = {
    "ras_breakout_1d_validation": {
        "description": (
            "One row per structural validation check for a RasBreakout1D "
            "extraction."
        ),
        "accessor": "Breakout1DResult.validation.checks_df",
        "source": "RasBreakout1D.validate()",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "check", "dtype": "str", "description": "Stable structural check identifier."},
            {"name": "severity", "dtype": "str", "description": "ERROR or WARNING."},
            {"name": "passed", "dtype": "bool", "description": "Whether the check passed."},
            {"name": "detail", "dtype": "str", "description": "Human-readable evidence for the check."},
        ],
    },
    "ras_breakout_1d_geometry_comparison": {
        "description": (
            "One row per retained cross section comparing complete source and "
            "destination geometry payloads."
        ),
        "accessor": "RasBreakout1D.compare_geometry(...)",
        "source": "RasBreakout1D.compare_geometry()",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "River", "dtype": "str", "description": "Exact river identifier."},
            {"name": "Reach", "dtype": "str", "description": "Exact reach identifier."},
            {"name": "RS", "dtype": "str", "description": "Exact retained river station."},
            {"name": "content_equal", "dtype": "bool", "description": "Whether the full node payload after the reach-length header matches."},
            {"name": "source_block_sha256", "dtype": "str", "description": "Source node-payload SHA-256."},
            {"name": "destination_block_sha256", "dtype": "str", "description": "Destination node-payload SHA-256."},
        ],
    },
    "ras_breakout_1d_results_comparison": {
        "description": (
            "Retained-section steady results joined by river, reach, station, "
            "and profile with source/destination values and numeric deltas."
        ),
        "accessor": "RasBreakout1D.compare_results(...)",
        "source": "RasBreakout1D.compare_results()",
        "extra_columns": True,
        "dynamic": True,
        "columns": [
            {"name": "river", "dtype": "str", "description": "Exact river identifier."},
            {"name": "reach", "dtype": "str", "description": "Exact reach identifier."},
            {"name": "node_id", "dtype": "str", "description": "Retained cross-section station."},
            {"name": "profile", "dtype": "str", "description": "Steady profile name."},
            {"name": "_merge", "dtype": "category", "description": "Source/destination join presence."},
        ],
    },
    "project_asset_inventory": {
        "description": (
            "One row per HEC-RAS project asset reference or linked dataset, "
            "with provenance, filesystem identity, inspection state, and readiness."
        ),
        "accessor": "inspect_project_assets(project, ...)",
        "source": "RasProject.inspect_project_assets()",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "inventory_schema_version", "dtype": "int64[pyarrow]", "description": "Row-schema version; currently 1."},
            {"name": "inventory_id", "dtype": "string[pyarrow]", "description": "UUID shared by one inspection snapshot."},
            {"name": "inspection_depth", "dtype": "string[pyarrow]", "description": "Requested project, current_plan, or all_plans depth."},
            {"name": "asset_id", "dtype": "string[pyarrow]", "description": "Stable identity for this reference within the snapshot."},
            {"name": "parent_asset_id", "dtype": "string[pyarrow] | null", "description": "Containing asset row, when applicable."},
            {"name": "asset_kind", "dtype": "string[pyarrow]", "description": "Mechanical asset/reference category."},
            {"name": "asset_role", "dtype": "string[pyarrow]", "description": "Declared input, derived prerequisite, existing result, display reference, or unknown."},
            {"name": "plan_number", "dtype": "string[pyarrow] | null", "description": "Owning plan number when plan-scoped."},
            {"name": "unsteady_number", "dtype": "string[pyarrow] | null", "description": "Owning unsteady-flow number when applicable."},
            {"name": "required", "dtype": "bool[pyarrow] | null", "description": "Whether the reference is mechanically required; null means unknown."},
            {"name": "owner_file", "dtype": "string[pyarrow] | null", "description": "File containing the reference."},
            {"name": "owner_sha256", "dtype": "string[pyarrow] | null", "description": "Snapshot hash of owner_file when hashing was requested."},
            {"name": "reference_raw", "dtype": "string[pyarrow] | null", "description": "Exact stored reference text."},
            {"name": "resolved_path", "dtype": "string[pyarrow] | null", "description": "Mapped-drive-preserving resolved display path."},
            {"name": "path_scope", "dtype": "string[pyarrow] | null", "description": "Internal, external, or ambiguous project scope."},
            {"name": "portable", "dtype": "bool[pyarrow] | null", "description": "Whether the path is self-contained under the project root."},
            {"name": "exists", "dtype": "bool[pyarrow] | null", "description": "Observed path existence."},
            {"name": "is_file", "dtype": "bool[pyarrow] | null", "description": "Whether the path is a regular file."},
            {"name": "is_dir", "dtype": "bool[pyarrow] | null", "description": "Whether the path is a directory."},
            {"name": "volume_id", "dtype": "string[pyarrow] | null", "description": "Filesystem volume identity when obtainable."},
            {"name": "file_id", "dtype": "string[pyarrow] | null", "description": "Filesystem object identity when obtainable."},
            {"name": "size_bytes", "dtype": "int64[pyarrow] | null", "description": "Observed regular-file size."},
            {"name": "mtime_ns", "dtype": "int64[pyarrow] | null", "description": "Observed nanosecond modification time."},
            {"name": "sha256", "dtype": "string[pyarrow] | null", "description": "Streamed file digest when requested."},
            {"name": "dataset_name", "dtype": "string[pyarrow] | null", "description": "Exact HDF, DSS, or GDAL dataset/pathname reference."},
            {"name": "expected_start", "dtype": "timestamp[ns, tz=UTC][pyarrow] | null", "description": "Plan-window start applicable to the dataset."},
            {"name": "expected_end", "dtype": "timestamp[ns, tz=UTC][pyarrow] | null", "description": "Plan-window end applicable to the dataset."},
            {"name": "available_start", "dtype": "timestamp[ns, tz=UTC][pyarrow] | null", "description": "Observed dataset coverage start."},
            {"name": "available_end", "dtype": "timestamp[ns, tz=UTC][pyarrow] | null", "description": "Observed dataset coverage end."},
            {"name": "inspection_state", "dtype": "string[pyarrow]", "description": "Available, missing, ambiguous, not_inspected, failed, or not_applicable."},
            {"name": "readiness", "dtype": "string[pyarrow]", "description": "Ready, not_ready, unknown, or not_required."},
            {"name": "reason_code", "dtype": "string[pyarrow] | null", "description": "Machine-readable inspection reason."},
            {"name": "detail", "dtype": "string[pyarrow] | null", "description": "Bounded human-readable diagnostic."},
            {"name": "source_api", "dtype": "string[pyarrow]", "description": "Parser or API that produced the row."},
        ],
    },
    "boundary_block_inventory": {
        "description": (
            "One exact, snapshot-bound row per unsteady-flow Boundary Location block "
            "in an atomically staged project."
        ),
        "accessor": (
            "RasUnsteady.inspect_boundary_blocks(staged_project, "
            "unsteady_number=...)"
        ),
        "source": "RasBoundary.inspect_boundary_blocks()",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "inventory_schema_version", "dtype": "int64[pyarrow]", "description": "Boundary inventory row-schema version."},
            {"name": "inventory_id", "dtype": "string[pyarrow]", "description": "UUID shared by one exact boundary snapshot."},
            {"name": "stage_operation_id", "dtype": "string[pyarrow]", "description": "Owning atomic-stage operation identity."},
            {"name": "staged_project_file", "dtype": "string[pyarrow]", "description": "Exact staged HEC-RAS project file."},
            {"name": "staged_root", "dtype": "string[pyarrow]", "description": "Verified staged project root."},
            {"name": "unsteady_number", "dtype": "string[pyarrow]", "description": "Two-digit staged unsteady-flow number."},
            {"name": "owner_relative_path", "dtype": "string[pyarrow]", "description": "Unsteady file path relative to the stage root."},
            {"name": "owner_sha256", "dtype": "string[pyarrow]", "description": "Exact unsteady-file content digest."},
            {"name": "owner_size_bytes", "dtype": "int64[pyarrow]", "description": "Exact unsteady-file byte length."},
            {"name": "owner_mtime_ns", "dtype": "int64[pyarrow]", "description": "Observed unsteady-file nanosecond mtime."},
            {"name": "volume_id", "dtype": "string[pyarrow]", "description": "Filesystem volume identity bound into the snapshot."},
            {"name": "file_id", "dtype": "string[pyarrow]", "description": "Filesystem file identity bound into the snapshot."},
            {"name": "boundary_index", "dtype": "int64[pyarrow]", "description": "Zero-based raw block order."},
            {"name": "boundary_condition_number", "dtype": "int64[pyarrow]", "description": "One-based compatibility ordinal."},
            {"name": "occurrence_ordinal", "dtype": "int64[pyarrow]", "description": "Zero-based occurrence among equal location/type blocks."},
            {"name": "boundary_count", "dtype": "int64[pyarrow]", "description": "Total block count in this file snapshot."},
            {"name": "boundary_location_raw", "dtype": "string[pyarrow]", "description": "Exact text following Boundary Location=."},
            {"name": "location_kind", "dtype": "string[pyarrow]", "description": "Proved 1d or 2d location shape."},
            {"name": "river", "dtype": "string[pyarrow]", "description": "First 1D location field."},
            {"name": "reach", "dtype": "string[pyarrow]", "description": "Second 1D location field."},
            {"name": "river_station", "dtype": "string[pyarrow]", "description": "Third 1D location field."},
            {"name": "area_2d", "dtype": "string[pyarrow]", "description": "2D flow-area location field."},
            {"name": "bc_line", "dtype": "string[pyarrow]", "description": "2D boundary-condition line field."},
            {"name": "bc_type", "dtype": "string[pyarrow]", "description": "Exactly detected boundary block type."},
            {"name": "start_byte", "dtype": "int64[pyarrow]", "description": "Inclusive block start byte."},
            {"name": "end_byte_exclusive", "dtype": "int64[pyarrow]", "description": "Exclusive block end byte."},
            {"name": "block_length_bytes", "dtype": "int64[pyarrow]", "description": "Exact byte length of the block."},
            {"name": "block_sha256", "dtype": "string[pyarrow]", "description": "Exact block-content digest."},
            {"name": "encoding", "dtype": "string[pyarrow]", "description": "Strictly detected source encoding."},
            {"name": "has_bom", "dtype": "bool[pyarrow]", "description": "Whether the file begins with a supported BOM."},
            {"name": "newline", "dtype": "string[pyarrow]", "description": "Uniform CRLF, LF, or CR convention."},
            {"name": "boundary_id", "dtype": "string[pyarrow]", "description": "Snapshot-, identity-, extent-, and digest-bound selector."},
            {"name": "inspection_state", "dtype": "string[pyarrow]", "description": "Available or explicit failed inspection state."},
            {"name": "reason_code", "dtype": "string[pyarrow]", "description": "Machine-readable inspection reason when present."},
            {"name": "detail", "dtype": "string[pyarrow]", "description": "Bounded human-readable diagnostic when present."},
        ],
    },
    "plan_df": {
        "description": "One row per HEC-RAS plan in the project, with its linked geometry and flow files.",
        "accessor": "ras.plan_df  (or RasPrj instance .plan_df; refreshed by RasPrj.get_plan_entries())",
        "source": "RasPrj.get_plan_entries()",
        "extra_columns": True,  # additional key=value entries parsed from the .prj plan block
        "dynamic": False,
        "columns": [
            {"name": "plan_number", "dtype": "str", "description": "Plan identifier, e.g. '01'."},
            {"name": "unsteady_number", "dtype": "str | None", "description": "Linked unsteady-flow number, if the plan is unsteady."},
            {"name": "flow_type", "dtype": "str", "description": "Flow computation mode: 'Steady', 'Unsteady', 'Quasi-Unsteady', or 'Unknown'; orthogonal features such as sediment or dam breach are not flow types."},
            {"name": "geometry_number", "dtype": "str | None", "description": "Linked geometry number."},
            {"name": "geometry_type", "dtype": "str", "description": "Derived geometry class: '1D', '2D', '1D/2D', or 'Unknown'."},
            {"name": "has_1d_xs", "dtype": "boolean", "description": "Nullable flag indicating whether the linked geometry contains 1D cross sections."},
            {"name": "has_2d_mesh", "dtype": "boolean", "description": "Nullable flag indicating whether the linked geometry contains a 2D mesh."},
            {"name": "num_cross_sections", "dtype": "Int64", "description": "Nullable count of 1D cross sections in the linked geometry."},
            {"name": "mesh_cell_count", "dtype": "Int64", "description": "Nullable total 2D mesh cell count in the linked geometry."},
            {"name": "mesh_area_names", "dtype": "list[str] | None", "description": "Names of 2D flow areas in the linked geometry, when metadata is available."},
            {"name": "geometry_metadata_source", "dtype": "str", "description": "Metadata source used for classification: 'hdf', 'text', or 'unavailable'."},
            {"name": "geometry_metadata_valid", "dtype": "boolean", "description": "Whether linked-geometry metadata was successfully classified."},
            {"name": "geometry_metadata_error", "dtype": "str | None", "description": "Diagnostic retained when geometry metadata inspection failed or fell back."},
            {"name": "plan_type", "dtype": "str", "description": "Finite compute class: 'steady_1d', 'unsteady_1d', 'unsteady_2d', 'unsteady_1d_2d', 'quasi_unsteady_1d', or 'unknown'."},
            {"name": "plan_classification_valid", "dtype": "boolean", "description": "Whether flow and geometry metadata produce a supported, unambiguous compute class."},
            {"name": "plan_classification_reason", "dtype": "str | None", "description": "Reason an unsupported or ambiguous plan classified as 'unknown'."},
            {"name": "Geom File", "dtype": "str", "description": "Geometry file name (e.g. 'project.g01')."},
            {"name": "Geom Path", "dtype": "str", "description": "Absolute path to the geometry file."},
            {"name": "Flow File", "dtype": "str", "description": "Normalized flow-file number for steady .f##, unsteady .u##, or quasi-unsteady .q## input."},
            {"name": "Flow Path", "dtype": "str", "description": "Absolute path to the flow file."},
            {"name": "Sediment File", "dtype": "str | None", "description": "Normalized sediment-file number selected by the plan, if present."},
            {"name": "Sediment Path", "dtype": "str | None", "description": "Absolute path expected for the selected sediment file; existence/readiness is reported by the asset inventory."},
            {"name": "breach_definition_count", "dtype": "Int64", "description": "Number of stored Breach Loc definitions; zero means none were found and null means inspection failed."},
            {"name": "breach_active_count", "dtype": "Int64", "description": "Number of stored definitions whose local RasBreach is_active flag is true; not evidence that a breach initiated."},
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
            {"name": "geometry_type", "dtype": "str", "description": "Derived geometry class: '1D', '2D', '1D/2D', or 'Unknown'."},
            {"name": "has_1d_xs", "dtype": "boolean", "description": "Nullable flag indicating whether the geometry contains 1D cross sections."},
            {"name": "has_2d_mesh", "dtype": "boolean", "description": "Nullable flag indicating whether geometry text declares a 2D flow area or HDF metadata identifies a mesh area."},
            {"name": "num_cross_sections", "dtype": "Int64", "description": "Nullable count of 1D cross sections."},
            {"name": "num_inline_structures", "dtype": "Int64", "description": "Nullable count of inline structures."},
            {"name": "num_bridges", "dtype": "Int64", "description": "Nullable count of bridges."},
            {"name": "num_culverts", "dtype": "Int64", "description": "Nullable count of culverts."},
            {"name": "num_weirs", "dtype": "Int64", "description": "Nullable count of weirs."},
            {"name": "num_gates", "dtype": "Int64", "description": "Nullable count of gates."},
            {"name": "num_lateral_structures", "dtype": "Int64", "description": "Nullable count of lateral structures."},
            {"name": "num_sa_2d_connections", "dtype": "Int64", "description": "Nullable count of storage-area / 2D connections."},
            {"name": "mesh_cell_count", "dtype": "Int64", "description": "Nullable total 2D mesh cell count across areas."},
            {"name": "mesh_area_names", "dtype": "list[str]", "description": "Names of the 2D flow areas."},
            {"name": "geometry_metadata_source", "dtype": "str", "description": "Metadata source used for classification: 'hdf', 'text', or 'unavailable'."},
            {"name": "geometry_metadata_valid", "dtype": "boolean", "description": "Whether geometry metadata was successfully classified."},
            {"name": "geometry_metadata_error", "dtype": "str | None", "description": "Diagnostic retained when HDF or text metadata inspection failed or fell back."},
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
    "hydrofabric_matches": {
        "description": (
            "One explicit matched, ambiguous, or unmatched row per HEC-RAS "
            "geometry, reach, and cross section."
        ),
        "accessor": "RasHydrofabric.conflate(...).matches",
        "source": "RasHydrofabric.conflate()",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "element_type", "dtype": "str", "description": "Model element granularity: geometry, reach, or cross_section."},
            {"name": "geometry_id", "dtype": "str", "description": "Owning HEC-RAS geometry/model identifier."},
            {"name": "reach_id", "dtype": "str | None", "description": "Reach identifier for reach and cross-section rows."},
            {"name": "xs_id", "dtype": "str | None", "description": "Cross-section identifier for cross-section rows."},
            {"name": "feature_id", "dtype": "str | None", "description": "Accepted hydrofabric identifier; null for ambiguous and unmatched rows."},
            {"name": "best_candidate_feature_id", "dtype": "str | None", "description": "Highest-scoring candidate retained for audit even when no match is accepted."},
            {"name": "status", "dtype": "str", "description": "Explicit matched, ambiguous, or unmatched status."},
            {"name": "confidence_score", "dtype": "float64", "description": "Top normalized multi-criteria score in [0, 1]."},
            {"name": "score_margin", "dtype": "float64 | None", "description": "Top score minus runner-up score."},
            {"name": "candidate_count", "dtype": "int64", "description": "Number of candidates evaluated for the element."},
            {"name": "match_method", "dtype": "str", "description": "Multi-criteria resolution or explicit no-candidate method."},
            {"name": "reason_codes", "dtype": "tuple[str, ...]", "description": "Machine-readable supporting and status reason codes."},
            {"name": "adapter", "dtype": "str", "description": "Hydrofabric adapter used for schema normalization."},
            {"name": "flowpath_measure", "dtype": "float64 | None", "description": "Cross-section measure from the flowpath geometry start in analysis-CRS units."},
            {"name": "flowpath_measure_fraction", "dtype": "float64 | None", "description": "Normalized cross-section measure from 0 at flowpath start to 1 at its end."},
            {"name": "flowpath_measure_from_end", "dtype": "float64 | None", "description": "Cross-section measure from the flowpath geometry end in analysis-CRS units."},
            {"name": "measure_method", "dtype": "str | None", "description": "intersection or nearest method used for an accepted cross-section measure."},
            {"name": "offset_distance", "dtype": "float64 | None", "description": "Cross-section-to-flowpath offset in analysis-CRS units."},
            {"name": "geometry", "dtype": "geometry", "description": "Source HEC-RAS model-element geometry."},
        ],
    },
    "hydrofabric_candidates": {
        "description": (
            "Ranked hydrofabric candidates with all spatial, topological, and "
            "hydrologic score evidence."
        ),
        "accessor": "RasHydrofabric.conflate(...).candidates",
        "source": "RasHydrofabric.conflate()",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "element_type", "dtype": "str", "description": "Model element granularity: geometry, reach, or cross_section."},
            {"name": "geometry_id", "dtype": "str", "description": "Owning HEC-RAS geometry/model identifier."},
            {"name": "reach_id", "dtype": "str | None", "description": "Reach identifier when applicable."},
            {"name": "xs_id", "dtype": "str | None", "description": "Cross-section identifier when applicable."},
            {"name": "feature_id", "dtype": "str", "description": "Candidate hydrofabric feature identifier normalized as text."},
            {"name": "candidate_rank", "dtype": "int64", "description": "One-based score rank within the model element."},
            {"name": "confidence_score", "dtype": "float64", "description": "Normalized multi-criteria score in [0, 1]."},
            {"name": "reason_codes", "dtype": "tuple[str, ...]", "description": "Machine-readable evidence reason codes."},
            {"name": "adapter", "dtype": "str", "description": "Hydrofabric adapter used for schema normalization."},
            {"name": "footprint_overlap_score", "dtype": "float64", "description": "Flowpath length fraction inside the model footprint."},
            {"name": "footprint_overlap_ratio", "dtype": "float64", "description": "Raw flowpath/model-footprint overlap ratio."},
            {"name": "centerline_distance_score", "dtype": "float64", "description": "Normalized symmetric centerline-proximity score."},
            {"name": "centerline_mean_distance", "dtype": "float64", "description": "Sampled symmetric mean distance in analysis-CRS units."},
            {"name": "direction_agreement_score", "dtype": "float64 | None", "description": "Directed angular agreement score."},
            {"name": "angular_difference_deg", "dtype": "float64 | None", "description": "Directed angular difference in degrees."},
            {"name": "xs_intersection_score", "dtype": "float64 | None", "description": "Fraction of reach cross sections intersected by the candidate."},
            {"name": "xs_intersection_count", "dtype": "int64", "description": "Reach cross sections intersected by the candidate."},
            {"name": "xs_total_count", "dtype": "int64", "description": "Cross sections associated with the reach."},
            {"name": "topological_continuity_score", "dtype": "float64 | None", "description": "Connectivity support across adjacent model reaches."},
            {"name": "hydrologic_score", "dtype": "float64 | None", "description": "Stream-order and drainage-area support score."},
            {"name": "stream_order", "dtype": "float64 | None", "description": "Adapter-normalized candidate stream order."},
            {"name": "drainage_area", "dtype": "float64 | None", "description": "Adapter-normalized candidate drainage area."},
            {"name": "sequence_consistency_score", "dtype": "float64 | None", "description": "Reach/cross-section ordering agreement along the flowpath."},
            {"name": "to_feature_id", "dtype": "str | None", "description": "Adapter-normalized downstream feature or nexus identifier."},
            {"name": "hydrosequence", "dtype": "float64 | None", "description": "Adapter-normalized hydrosequence value."},
            {"name": "flowpath_measure", "dtype": "float64 | None", "description": "Candidate cross-section measure from flowpath start."},
            {"name": "flowpath_measure_fraction", "dtype": "float64 | None", "description": "Candidate normalized flowpath measure."},
            {"name": "flowpath_measure_from_end", "dtype": "float64 | None", "description": "Candidate cross-section measure from flowpath end."},
            {"name": "measure_method", "dtype": "str | None", "description": "intersection or nearest measure method."},
            {"name": "offset_distance", "dtype": "float64 | None", "description": "Cross-section-to-candidate offset in analysis-CRS units."},
            {"name": "geometry", "dtype": "geometry", "description": "Candidate hydrofabric flowpath geometry."},
        ],
    },
    "hydrofabric_reach_metrics": {
        "description": (
            "One row per HEC-RAS reach with its network-edge association, "
            "cross-section limits, alignment metrics, coverage, and flags."
        ),
        "accessor": "RasHydrofabric.conflate(...).reach_metrics",
        "source": "RasHydrofabric._build_reach_metrics()",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "geometry_id", "dtype": "str", "description": "Owning HEC-RAS geometry/model identifier."},
            {"name": "reach_id", "dtype": "str", "description": "HEC-RAS reach identifier."},
            {"name": "feature_id", "dtype": "str | None", "description": "Accepted network-edge identifier; null unless matched."},
            {"name": "best_candidate_feature_id", "dtype": "str | None", "description": "Best network-edge candidate retained for review."},
            {"name": "status", "dtype": "str", "description": "Matched, ambiguous, or unmatched association state."},
            {"name": "confidence_score", "dtype": "float64", "description": "Top multi-criteria association score."},
            {"name": "upstream_xs_id", "dtype": "str | None", "description": "First intersecting cross section from the directed network geometry start."},
            {"name": "downstream_xs_id", "dtype": "str | None", "description": "Last intersecting cross section from the directed network geometry start."},
            {"name": "xs_intersection_count", "dtype": "int64", "description": "Distinct RAS cross sections intersecting the selected network edge."},
            {"name": "coverage_start", "dtype": "float64 | None", "description": "Upstream cross-section measure divided by network-edge length."},
            {"name": "coverage_end", "dtype": "float64 | None", "description": "Downstream cross-section measure divided by network-edge length."},
            {"name": "coverage_ratio", "dtype": "float64 | None", "description": "Network-edge fraction between the selected XS limits."},
            {"name": "ras_length", "dtype": "float64 | None", "description": "RAS centerline length between selected XS limits."},
            {"name": "network_length", "dtype": "float64 | None", "description": "Network length between selected XS limits."},
            {"name": "network_to_ras_ratio", "dtype": "float64 | None", "description": "Network length divided by RAS centerline length."},
            {"name": "centerline_offset_count", "dtype": "int64", "description": "Cross sections contributing centerline offsets."},
            {"name": "centerline_offset_mean", "dtype": "float64 | None", "description": "Mean RAS-centerline to network crossing offset."},
            {"name": "centerline_offset_std", "dtype": "float64 | None", "description": "Population standard deviation of centerline offsets."},
            {"name": "centerline_offset_min", "dtype": "float64 | None", "description": "Minimum centerline offset."},
            {"name": "centerline_offset_max", "dtype": "float64 | None", "description": "Maximum centerline offset."},
            {"name": "thalweg_offset_count", "dtype": "int64", "description": "Cross sections contributing thalweg offsets."},
            {"name": "thalweg_offset_mean", "dtype": "float64 | None", "description": "Mean thalweg-point to network crossing offset."},
            {"name": "thalweg_offset_std", "dtype": "float64 | None", "description": "Population standard deviation of thalweg offsets."},
            {"name": "thalweg_offset_min", "dtype": "float64 | None", "description": "Minimum thalweg offset."},
            {"name": "thalweg_offset_max", "dtype": "float64 | None", "description": "Maximum thalweg offset."},
            {"name": "ambiguous", "dtype": "bool", "description": "Whether candidate scores are too close to resolve."},
            {"name": "eclipsed", "dtype": "bool", "description": "Whether no two distinct XS limits intersect the selected edge."},
            {"name": "connectivity_evaluable", "dtype": "bool", "description": "Whether normalized network node fields permit divergence review."},
            {"name": "divergent", "dtype": "bool", "description": "Whether the selected edge belongs to or terminates at a network split."},
            {"name": "insufficient_coverage", "dtype": "bool", "description": "Whether XS limits span less than the configured minimum edge fraction."},
            {"name": "flagged", "dtype": "bool", "description": "Any ambiguous, unmatched, eclipsed, divergent, or insufficient-coverage condition."},
            {"name": "reason_codes", "dtype": "tuple[str, ...]", "description": "Machine-readable review reasons."},
            {"name": "geometry", "dtype": "geometry", "description": "HEC-RAS reach centerline geometry."},
        ],
    },
    "hydrofabric_huc_intersections": {
        "description": "Model-footprint intersections with an optional HUC polygon layer.",
        "accessor": "RasHydrofabric.conflate(...).huc_intersections",
        "source": "RasHydrofabric.conflate()",
        "extra_columns": False,
        "dynamic": False,
        "columns": [
            {"name": "geometry_id", "dtype": "str", "description": "HEC-RAS geometry/model identifier."},
            {"name": "huc_id", "dtype": "str", "description": "HUC identifier preserved as text."},
            {"name": "intersection_area", "dtype": "float64", "description": "Intersection area in squared analysis-CRS units."},
            {"name": "geometry_area_fraction", "dtype": "float64 | None", "description": "Fraction of the model footprint within the HUC."},
            {"name": "huc_area_fraction", "dtype": "float64 | None", "description": "Fraction of the HUC within the model footprint."},
            {"name": "geometry", "dtype": "geometry", "description": "Footprint/HUC intersection geometry."},
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
    "infiltration_override_table_df": {
        "description": (
            "Class-ordered geometry infiltration parameter table for either "
            "the geometry-wide base fallback or one selected native region."
        ),
        "accessor": (
            "HdfInfiltration.get_infiltration_baseoverrides(...) or "
            "HdfInfiltration.get/set/scale_infiltration_region_overrides(...)"
        ),
        "source": (
            "HdfInfiltration and _infiltration_override_native "
            "(native ParameterSet class order)"
        ),
        "extra_columns": True,
        "dynamic": True,
        "columns": [
            {
                "name": "Land Cover Name",
                "dtype": "str",
                "description": (
                    "Native combined land-cover/soil classification name."
                ),
            },
        ],
        "note": (
            "Remaining numeric parameter columns are supplied by the active "
            "HEC-RAS infiltration ParameterSet and vary by method/version "
            "(for SCS Curve Number these include Curve Number, Abstraction "
            "Ratio, and Minimum Infiltration Rate). Regional native reads add "
            "geometry_hdf_path, region_name, and zero-based region_id attrs; "
            "mutations also add backup_path and recompute_required."
        ),
    },
}
