# ras_commander/hdf/HdfBenefitAreas.py
"""
Benefit and rise area analysis for HEC-RAS 2D models.

Compares maximum water surface elevations between existing and proposed conditions
to identify areas of WSE reduction (benefit) and WSE increase (rise).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from collections import defaultdict
import logging

import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.ops import unary_union

from ras_commander.LoggingConfig import log_call

logger = logging.getLogger(__name__)


class HdfBenefitAreas:
    """
    Analysis of benefit and rise areas from HEC-RAS 2D plan comparisons.

    **IMPORTANT**: This module currently supports **2D mesh areas only**. Analysis
    uses mesh cell polygons and maximum WSE at cell centers. For 1D cross section
    benefit analysis, see roadmap feature request.

    This class provides methods to compare maximum water surface elevations between
    existing and proposed conditions, identifying areas where WSE is reduced (benefit)
    or increased (rise/adverse impact).

    The analysis produces five GeoDataFrames:
    - benefit_polygons: Contiguous areas with WSE reduction
    - rise_polygons: Contiguous areas with WSE increase
    - existing_points: Max WSE points from existing plan
    - proposed_points: Max WSE points from proposed plan
    - difference_points: Matched points with WSE differences

    Example:
        >>> from ras_commander import init_ras_project, HdfBenefitAreas
        >>>
        >>> # Initialize project
        >>> init_ras_project("/path/to/project", "6.6")
        >>>
        >>> # Compare existing vs proposed using plan numbers
        >>> results = HdfBenefitAreas.identify_benefit_areas(
        ...     existing_hdf_path="01",
        ...     proposed_hdf_path="02",
        ...     min_delta=0.1
        ... )
        >>>
        >>> # OR use file paths directly (no project init needed)
        >>> results = HdfBenefitAreas.identify_benefit_areas(
        ...     existing_hdf_path="/path/to/existing.p01.hdf",
        ...     proposed_hdf_path="/path/to/proposed.p02.hdf",
        ...     min_delta=0.1
        ... )
        >>>
        >>> # Access results
        >>> benefit = results['benefit_polygons']
        >>> print(f"Benefit area: {benefit.geometry.area.sum() / 43560:.1f} acres")
    """

    @staticmethod
    @log_call
    def identify_benefit_areas(
        existing_hdf_path: Union[str, Path],
        proposed_hdf_path: Union[str, Path],
        min_delta: float = 0.1,
        match_precision: int = 6,
        adjacency_method: str = "polygon_edges",
        dissolve: bool = True,
        ras_object: Optional[Any] = None
    ) -> Dict[str, gpd.GeoDataFrame]:
        """
        Identify benefit and rise areas by comparing two HEC-RAS 2D plans.

        **2D Models Only**: This method analyzes 2D mesh areas. For 1D cross section
        benefit analysis, see roadmap feature request.

        Compares maximum water surface elevations between existing and proposed
        conditions to identify areas where WSE is reduced (benefit) or increased
        (rise/adverse impact). Creates contiguous polygons using mesh cell adjacency.

        Args:
            existing_hdf_path: Path to existing condition HDF file. Can be:
                              - Plan number (e.g., "01")
                              - HDF filename (e.g., "plan.p01.hdf")
                              - Full path (e.g., "/path/to/plan.p01.hdf")
            proposed_hdf_path: Path to proposed condition HDF file. Can be:
                              - Plan number (e.g., "02")
                              - HDF filename (e.g., "plan.p02.hdf")
                              - Full path (e.g., "/path/to/plan.p02.hdf")
            min_delta: Minimum WSE difference threshold (feet). Points with
                      |wse_difference| < min_delta are excluded from polygon creation.
                      Default: 0.1 feet
            match_precision: Decimal precision for coordinate matching between plans.
                            Points are matched by rounding x,y to this many decimals.
                            Default: 6 (sub-millimeter precision)
            adjacency_method: Method for building cell adjacency ("polygon_edges" or "topology").
                             - "polygon_edges": Uses shared polygon edges (default, matches QGIS)
                             - "topology": Uses face_cells from mesh topology (more robust)
                             Default: "polygon_edges"
            dissolve: Whether to dissolve polygons by contiguous group. If False,
                     returns individual mesh cell polygons. Default: True
            ras_object: Optional RAS project object (for multi-project workflows).
                       If None, uses global ras object.

        Returns:
            Dictionary with five GeoDataFrames:
              - benefit_polygons: Areas with WSE reduction (wse_difference < 0)
                  Columns: group_id, cell_count, area_sqft, area_acres, geometry
              - rise_polygons: Areas with WSE increase (wse_difference > 0)
                  Columns: group_id, cell_count, area_sqft, area_acres, geometry
              - existing_points: Max WSE points from existing plan
                  Columns: mesh_name, cell_id, max_wse, geometry
              - proposed_points: Max WSE points from proposed plan
                  Columns: mesh_name, cell_id, max_wse, geometry
              - difference_points: Matched points with WSE differences
                  Columns: mesh_name, cell_id, existing_wse, proposed_wse,
                          wse_difference, change_type, geometry

        Raises:
            FileNotFoundError: If plan HDF files not found
            ValueError: If plans have incompatible mesh structures or no matching points

        Notes:
            - WSE difference = proposed - existing
            - Negative difference = benefit (WSE reduced)
            - Positive difference = rise (WSE increased)
            - Area calculations assume coordinates are in feet (area_sqft = polygon.area)
            - area_acres = area_sqft / 43560

        Example:
            >>> from ras_commander import init_ras_project, HdfBenefitAreas
            >>>
            >>> # Initialize project
            >>> init_ras_project("/path/to/project", "6.6")
            >>>
            >>> # Option 1: Use plan numbers
            >>> results = HdfBenefitAreas.identify_benefit_areas(
            ...     existing_hdf_path="01",
            ...     proposed_hdf_path="02",
            ...     min_delta=0.1
            ... )
            >>>
            >>> # Option 2: Use file paths directly (no project initialization needed)
            >>> results = HdfBenefitAreas.identify_benefit_areas(
            ...     existing_hdf_path="/path/to/existing.p01.hdf",
            ...     proposed_hdf_path="/path/to/proposed.p02.hdf",
            ...     min_delta=0.1
            ... )
            >>>
            >>> # Print summary
            >>> benefit = results['benefit_polygons']
            >>> rise = results['rise_polygons']
            >>> print(f"Benefit area: {benefit.geometry.area.sum() / 43560:.1f} acres")
            >>> print(f"Rise area: {rise.geometry.area.sum() / 43560:.1f} acres")
            >>>
            >>> # Export to GeoPackage
            >>> benefit.to_file("benefit_areas.gpkg", layer="benefit", driver="GPKG")
            >>> rise.to_file("benefit_areas.gpkg", layer="rise", driver="GPKG")
        """
        # Import inside method to avoid circular imports
        from ras_commander.hdf import HdfResultsMesh, HdfMesh, HdfUtils
        from ras_commander import ras as global_ras

        # Use provided ras_object or global
        _ras = ras_object if ras_object is not None else global_ras

        # Standardize inputs (handle plan numbers OR file paths)
        existing_path = HdfBenefitAreas._standardize_hdf_input(
            existing_hdf_path, "existing", _ras
        )
        proposed_path = HdfBenefitAreas._standardize_hdf_input(
            proposed_hdf_path, "proposed", _ras
        )

        # Validate paths exist
        if not existing_path.exists():
            raise FileNotFoundError(
                f"Existing plan HDF not found: {existing_path}\n"
                f"If using plan number, run RasCmdr.compute_plan() first."
            )

        if not proposed_path.exists():
            raise FileNotFoundError(
                f"Proposed plan HDF not found: {proposed_path}\n"
                f"If using plan number, run RasCmdr.compute_plan() first."
            )

        # Step 1: Extract max WSE points from both plans
        logger.info(f"Loading max WSE from existing plan: {existing_path}")
        existing_points = HdfResultsMesh.get_mesh_max_ws(existing_path)

        logger.info(f"Loading max WSE from proposed plan: {proposed_path}")
        proposed_points = HdfResultsMesh.get_mesh_max_ws(proposed_path)

        if existing_points is None or existing_points.empty:
            raise ValueError(f"No max WSE data found in existing plan: {existing_path}")

        if proposed_points is None or proposed_points.empty:
            raise ValueError(f"No max WSE data found in proposed plan: {proposed_path}")

        # Step 2: Match points between plans and compute differences
        logger.info("Matching points between plans...")
        matched_df = HdfBenefitAreas._match_points_by_xy(
            existing_points, proposed_points, match_precision
        )

        if matched_df.empty:
            raise ValueError("No matching points found between the two plans")

        # Step 3: Apply threshold and classify points
        logger.info(f"Applying minimum delta threshold of {min_delta} feet...")
        benefit_points, rise_points = HdfBenefitAreas._apply_threshold_and_classify(
            matched_df, min_delta
        )

        # Step 4: Load mesh cell polygons from existing plan
        logger.info(f"Loading mesh cells from existing plan: {existing_path}")
        cells_gdf = HdfMesh.get_mesh_cell_polygons(existing_path)

        if cells_gdf is None or cells_gdf.empty:
            raise ValueError(f"No mesh cells found in existing plan: {existing_path}")

        # Step 5: Build contiguous polygons
        logger.info("Building contiguous benefit areas...")
        benefit_polygons = HdfBenefitAreas._build_contiguous_polygons(
            benefit_points, cells_gdf, "Benefit Area", adjacency_method, dissolve,
            existing_path if adjacency_method == "topology" else None
        )

        logger.info("Building contiguous rise areas...")
        rise_polygons = HdfBenefitAreas._build_contiguous_polygons(
            rise_points, cells_gdf, "Rise Area", adjacency_method, dissolve,
            existing_path if adjacency_method == "topology" else None
        )

        # Step 6: Prepare output GeoDataFrames
        # Add column renames to match expected schema
        existing_output = existing_points.rename(columns={'maximum_water_surface': 'max_wse'})
        existing_output = existing_output[['mesh_name', 'cell_id', 'max_wse', 'geometry']]

        proposed_output = proposed_points.rename(columns={'maximum_water_surface': 'max_wse'})
        proposed_output = proposed_output[['mesh_name', 'cell_id', 'max_wse', 'geometry']]

        # Add change_type classification to matched points
        matched_df['change_type'] = matched_df['wse_difference'].apply(
            lambda x: "Benefit (WSE Reduced)" if x < 0 else (
                "Rise (WSE Increased)" if x > 0 else "No Change"
            )
        )

        logger.info("Analysis complete")
        logger.info(f"  Benefit areas: {len(benefit_polygons) if not benefit_polygons.empty else 0}")
        logger.info(f"  Rise areas: {len(rise_polygons) if not rise_polygons.empty else 0}")
        logger.info(f"  Matched points: {len(matched_df)}")

        return {
            'benefit_polygons': benefit_polygons,
            'rise_polygons': rise_polygons,
            'existing_points': existing_output,
            'proposed_points': proposed_output,
            'difference_points': matched_df
        }

    @staticmethod
    def _standardize_hdf_input(
        hdf_input: Union[str, Path],
        label: str,
        ras_object: Any
    ) -> Path:
        """
        Standardize HDF input to Path object.

        Handles three input types:
        1. Plan number (e.g., "01") - resolves via ras_object
        2. HDF filename (e.g., "plan.p01.hdf") - resolves via ras_object folder
        3. Full path (e.g., "/path/to/plan.p01.hdf") - uses directly

        Args:
            hdf_input: Plan number, filename, or full path
            label: Label for error messages ("existing" or "proposed")
            ras_object: RAS project object for resolving plan numbers

        Returns:
            Path: Resolved HDF file path

        Raises:
            ValueError: If input cannot be resolved to HDF path
        """
        from ras_commander.hdf import HdfUtils

        # Convert to string for pattern matching
        input_str = str(hdf_input)

        # Case 1: Full path (contains directory separators)
        if '/' in input_str or '\\' in input_str:
            return Path(hdf_input)

        # Case 2: HDF filename (ends with .hdf)
        if input_str.endswith('.hdf'):
            if ras_object is None or not hasattr(ras_object, 'folder'):
                raise ValueError(
                    f"Cannot resolve HDF filename '{input_str}' without initialized project. "
                    f"Either provide full path or call init_ras_project() first."
                )
            return Path(ras_object.folder) / input_str

        # Case 3: Plan number (assume anything else is a plan number)
        # Remove 'p' prefix if present (e.g., "p01" -> "01")
        plan_number = input_str.lstrip('p')

        if ras_object is None:
            raise ValueError(
                f"Cannot resolve plan number '{plan_number}' without initialized project. "
                f"Call init_ras_project() first."
            )

        # Resolve plan number to HDF path
        try:
            # Get project folder
            if hasattr(ras_object, 'folder') and ras_object.folder is not None:
                project_folder = ras_object.folder
            else:
                # Try alternate attribute names
                if hasattr(ras_object, 'project_folder'):
                    project_folder = ras_object.project_folder
                else:
                    raise ValueError(
                        f"RAS project object doesn't have a 'folder' attribute. "
                        f"Ensure init_ras_project() was called successfully."
                    )

            hdfs = HdfUtils.resolve_hdf_paths(
                project_folder,
                plan_number,
                ras_object=ras_object
            )
            hdf_path = hdfs['plan']

            if hdf_path is None:
                # Return a Path that doesn't exist - this will trigger FileNotFoundError later
                # Construct expected path for better error message
                return Path(project_folder) / f"{Path(project_folder).name}.p{plan_number}.hdf"

            return Path(hdf_path)

        except Exception as e:
            # If we can't resolve, try constructing expected path
            # This allows FileNotFoundError to be raised later with the expected path
            logger.warning(f"Could not resolve {label} plan '{input_str}': {e}")
            if hasattr(ras_object, 'folder') and ras_object.folder:
                return Path(ras_object.folder) / f"unknown.p{plan_number}.hdf"
            else:
                raise ValueError(
                    f"Failed to resolve {label} plan '{input_str}': {e}"
                )

    @staticmethod
    def _match_points_by_xy(
        existing_points: gpd.GeoDataFrame,
        proposed_points: gpd.GeoDataFrame,
        precision: int
    ) -> gpd.GeoDataFrame:
        """
        Match points between existing and proposed plans by rounded X,Y coordinates.

        Args:
            existing_points: GeoDataFrame with existing max WSE points
            proposed_points: GeoDataFrame with proposed max WSE points
            precision: Decimal precision for coordinate rounding

        Returns:
            GeoDataFrame with matched points and WSE differences
        """
        # Extract coordinates and round to precision
        existing_df = existing_points.copy()
        existing_df['x_round'] = existing_df.geometry.x.round(precision)
        existing_df['y_round'] = existing_df.geometry.y.round(precision)

        proposed_df = proposed_points.copy()
        proposed_df['x_round'] = proposed_df.geometry.x.round(precision)
        proposed_df['y_round'] = proposed_df.geometry.y.round(precision)

        # Merge on rounded coordinates (and mesh_name for multi-mesh support)
        matched = existing_df.merge(
            proposed_df,
            on=['mesh_name', 'x_round', 'y_round'],
            how='inner',
            suffixes=('_existing', '_proposed')
        )

        if matched.empty:
            logger.warning("No matching points found between plans")
            return gpd.GeoDataFrame()

        # Compute WSE difference (proposed - existing, negative = benefit)
        matched['existing_wse'] = matched['maximum_water_surface_existing']
        matched['proposed_wse'] = matched['maximum_water_surface_proposed']
        matched['wse_difference'] = matched['proposed_wse'] - matched['existing_wse']

        # Use existing point geometry
        matched['geometry'] = matched['geometry_existing']

        # Select final columns
        result = matched[[
            'mesh_name',
            'cell_id_existing',  # Will rename to cell_id
            'existing_wse',
            'proposed_wse',
            'wse_difference',
            'geometry'
        ]].copy()

        result.rename(columns={'cell_id_existing': 'cell_id'}, inplace=True)

        # Convert back to GeoDataFrame
        result = gpd.GeoDataFrame(result, geometry='geometry', crs=existing_points.crs)

        logger.info(f"Matched {len(result)} points out of {len(existing_points)} existing points")

        return result

    @staticmethod
    def _apply_threshold_and_classify(
        matched_df: gpd.GeoDataFrame,
        min_delta: float
    ) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """
        Apply minimum delta threshold and classify points into benefit/rise.

        Args:
            matched_df: GeoDataFrame with matched points and wse_difference
            min_delta: Minimum absolute WSE difference to include

        Returns:
            Tuple of (benefit_points, rise_points) GeoDataFrames
        """
        # Filter by threshold
        significant = matched_df[abs(matched_df['wse_difference']) >= min_delta].copy()

        if significant.empty:
            logger.warning(f"No points exceed minimum delta threshold of {min_delta} feet")
            empty_gdf = gpd.GeoDataFrame(columns=matched_df.columns, crs=matched_df.crs)
            return empty_gdf, empty_gdf

        # Classify
        benefit = significant[significant['wse_difference'] < 0].copy()
        rise = significant[significant['wse_difference'] > 0].copy()

        logger.info(f"Found {len(benefit)} benefit points and {len(rise)} rise points")

        return benefit, rise

    @staticmethod
    def _build_contiguous_polygons(
        points_df: gpd.GeoDataFrame,
        cells_gdf: gpd.GeoDataFrame,
        area_type: str,
        adjacency_method: str,
        dissolve: bool,
        hdf_path: Optional[Path] = None
    ) -> gpd.GeoDataFrame:
        """
        Build contiguous polygon groups from classified points.

        Args:
            points_df: GeoDataFrame with classified points (benefit or rise)
            cells_gdf: GeoDataFrame with mesh cell polygons
            area_type: Label for area type ("Benefit Area" or "Rise Area")
            adjacency_method: Method for building adjacency ("polygon_edges" or "topology")
            dissolve: Whether to dissolve polygons by group
            hdf_path: Path to HDF file (required if adjacency_method="topology")

        Returns:
            GeoDataFrame with contiguous polygon groups
        """
        if points_df.empty:
            # Return empty GeoDataFrame with expected schema
            return gpd.GeoDataFrame({
                'group_id': [],
                'cell_count': [],
                'area_sqft': [],
                'area_acres': [],
                'geometry': []
            }, crs=cells_gdf.crs)

        # Step 1: Associate points with cells using spatial join
        logger.info(f"Associating {len(points_df)} points with mesh cells...")
        points_with_cells = gpd.sjoin(
            points_df, cells_gdf[['cell_id', 'mesh_name', 'geometry']],
            how='inner', predicate='within'
        )

        # Get unique cell IDs (with mesh_name for multi-mesh support)
        target_cells = points_with_cells[['mesh_name', 'cell_id_right']].drop_duplicates()
        target_cells.rename(columns={'cell_id_right': 'cell_id'}, inplace=True)

        if target_cells.empty:
            logger.warning(f"No cells associated with {area_type} points")
            return gpd.GeoDataFrame({
                'group_id': [],
                'cell_count': [],
                'area_sqft': [],
                'area_acres': [],
                'geometry': []
            }, crs=cells_gdf.crs)

        logger.info(f"Associated {len(target_cells)} cells with {area_type} points")

        # Step 2: Build adjacency
        if adjacency_method == "topology":
            adjacency = HdfBenefitAreas._build_adjacency_topology(
                target_cells, cells_gdf, hdf_path
            )
        else:  # polygon_edges
            adjacency = HdfBenefitAreas._build_adjacency_polygon_edges(
                target_cells, cells_gdf
            )

        # Step 3: Find contiguous groups using flood-fill
        logger.info("Grouping cells into contiguous areas...")
        cell_groups = HdfBenefitAreas._connected_components(
            target_cells, adjacency
        )

        logger.info(f"Created {len(cell_groups)} contiguous {area_type} groups")

        # Step 4: Build polygon features for each group
        polygon_features = HdfBenefitAreas._build_group_polygons(
            cell_groups, cells_gdf, dissolve
        )

        return polygon_features

    @staticmethod
    def _build_adjacency_polygon_edges(
        target_cells: pd.DataFrame,
        cells_gdf: gpd.GeoDataFrame
    ) -> Dict[Tuple[str, int], List[Tuple[str, int]]]:
        """
        Build cell adjacency using shared polygon edges.

        This method matches the QGIS implementation: cells that share an edge
        (based on rounded coordinates) are considered adjacent.

        Args:
            target_cells: DataFrame with (mesh_name, cell_id) of target cells
            cells_gdf: GeoDataFrame with all mesh cells

        Returns:
            Dictionary mapping (mesh_name, cell_id) to list of adjacent (mesh_name, cell_id)
        """
        logger.info("Building adjacency using polygon edges...")

        # Build edge-to-cells mapping
        edge_to_cells = defaultdict(set)

        def edge_key(coords1, coords2, precision=6):
            """Create normalized edge key from two coordinates."""
            coords1 = tuple(round(coord, precision) for coord in coords1)
            coords2 = tuple(round(coord, precision) for coord in coords2)
            return tuple(sorted([coords1, coords2]))

        # Filter cells to target cells only
        target_cell_keys = set(zip(target_cells['mesh_name'], target_cells['cell_id']))

        for _, cell_row in cells_gdf.iterrows():
            cell_key = (cell_row['mesh_name'], cell_row['cell_id'])

            # Skip if not in target set
            if cell_key not in target_cell_keys:
                continue

            geom = cell_row.geometry

            if geom is None or geom.is_empty or not geom.is_valid:
                continue

            # Extract edges from polygon exterior
            try:
                coords = list(geom.exterior.coords)
                for i in range(len(coords) - 1):
                    edge = edge_key(coords[i], coords[i + 1])
                    edge_to_cells[edge].add(cell_key)
            except Exception as e:
                logger.warning(f"Could not extract edges from cell {cell_key}: {e}")
                continue

        # Build adjacency from shared edges
        adjacency = defaultdict(set)
        for edge, cells in edge_to_cells.items():
            if len(cells) >= 2:
                cells_list = list(cells)
                for i in range(len(cells_list)):
                    for j in range(i + 1, len(cells_list)):
                        cell1, cell2 = cells_list[i], cells_list[j]
                        adjacency[cell1].add(cell2)
                        adjacency[cell2].add(cell1)

        # Convert sets to lists
        adjacency_dict = {k: list(v) for k, v in adjacency.items()}

        logger.info(f"Built adjacency for {len(adjacency_dict)} cells")

        return adjacency_dict

    @staticmethod
    def _build_adjacency_topology(
        target_cells: pd.DataFrame,
        cells_gdf: gpd.GeoDataFrame,
        hdf_path: Path
    ) -> Dict[Tuple[str, int], List[Tuple[str, int]]]:
        """
        Build cell adjacency using mesh topology (face_cells).

        More robust than edge-based adjacency, uses HEC-RAS mesh connectivity data.

        Args:
            target_cells: DataFrame with (mesh_name, cell_id) of target cells
            cells_gdf: GeoDataFrame with all mesh cells
            hdf_path: Path to HDF file

        Returns:
            Dictionary mapping (mesh_name, cell_id) to list of adjacent (mesh_name, cell_id)
        """
        from ras_commander.hdf import HdfMesh

        logger.info("Building adjacency using mesh topology...")

        # Get topology for each mesh
        meshes = target_cells['mesh_name'].unique()
        adjacency = defaultdict(set)

        for mesh_name in meshes:
            try:
                # Get face_cells array (N_faces x 2, cell pairs sharing each face)
                topo = HdfMesh.get_mesh_sloped_topology(hdf_path, mesh_name)

                if 'face_cells' not in topo:
                    logger.warning(f"No face_cells found for mesh {mesh_name}, falling back to edge-based")
                    continue

                face_cells = topo['face_cells']

                # Build adjacency from face_cells
                # Each row is [cell1, cell2] where -1 indicates boundary
                for cell1, cell2 in face_cells:
                    if cell1 == -1 or cell2 == -1:
                        continue  # Boundary face

                    key1 = (mesh_name, cell1)
                    key2 = (mesh_name, cell2)

                    # Only include if both cells are in target set
                    target_keys = set(zip(
                        target_cells[target_cells['mesh_name'] == mesh_name]['mesh_name'],
                        target_cells[target_cells['mesh_name'] == mesh_name]['cell_id']
                    ))

                    if key1 in target_keys and key2 in target_keys:
                        adjacency[key1].add(key2)
                        adjacency[key2].add(key1)

            except Exception as e:
                logger.warning(f"Could not get topology for mesh {mesh_name}: {e}")
                continue

        # Convert sets to lists
        adjacency_dict = {k: list(v) for k, v in adjacency.items()}

        logger.info(f"Built topology-based adjacency for {len(adjacency_dict)} cells")

        return adjacency_dict

    @staticmethod
    def _connected_components(
        target_cells: pd.DataFrame,
        adjacency: Dict[Tuple[str, int], List[Tuple[str, int]]]
    ) -> List[List[Tuple[str, int]]]:
        """
        Find connected components using flood-fill (BFS).

        Args:
            target_cells: DataFrame with (mesh_name, cell_id) of target cells
            adjacency: Adjacency mapping

        Returns:
            List of contiguous groups (each group is list of (mesh_name, cell_id) tuples)
        """
        # Convert target cells to set of tuples
        unvisited = set(zip(target_cells['mesh_name'], target_cells['cell_id']))
        groups = []

        while unvisited:
            # Start new group
            start_cell = unvisited.pop()
            current_group = [start_cell]
            queue = [start_cell]

            # Flood-fill BFS
            while queue:
                current_cell = queue.pop(0)

                # Check all adjacent cells
                for neighbor in adjacency.get(current_cell, []):
                    if neighbor in unvisited:
                        unvisited.remove(neighbor)
                        current_group.append(neighbor)
                        queue.append(neighbor)

            groups.append(current_group)

        logger.info(f"Found {len(groups)} connected components")

        return groups

    @staticmethod
    def _build_group_polygons(
        cell_groups: List[List[Tuple[str, int]]],
        cells_gdf: gpd.GeoDataFrame,
        dissolve: bool
    ) -> gpd.GeoDataFrame:
        """
        Build polygon features for contiguous groups.

        Args:
            cell_groups: List of cell groups (each group is list of (mesh_name, cell_id))
            cells_gdf: GeoDataFrame with all mesh cells
            dissolve: Whether to dissolve polygons by group

        Returns:
            GeoDataFrame with polygon features
        """
        # Build lookup: (mesh_name, cell_id) -> geometry
        cell_lookup = {}
        for _, row in cells_gdf.iterrows():
            key = (row['mesh_name'], row['cell_id'])
            cell_lookup[key] = row.geometry

        features = []

        for group_idx, cell_group in enumerate(cell_groups):
            # Get geometries for this group
            group_geoms = []
            for cell_key in cell_group:
                if cell_key in cell_lookup:
                    geom = cell_lookup[cell_key]
                    if geom is not None and geom.is_valid and not geom.is_empty:
                        group_geoms.append(geom)

            if not group_geoms:
                continue

            # Dissolve or keep separate
            if dissolve:
                try:
                    merged_geom = unary_union(group_geoms)
                except Exception as e:
                    logger.warning(f"Could not dissolve group {group_idx + 1}: {e}")
                    continue

                if merged_geom is None or not merged_geom.is_valid:
                    continue

                # Calculate area (assume coordinates in feet)
                area_sqft = merged_geom.area

                features.append({
                    'group_id': group_idx + 1,
                    'cell_count': len(cell_group),
                    'area_sqft': area_sqft,
                    'area_acres': area_sqft / 43560.0,
                    'geometry': merged_geom
                })
            else:
                # Keep individual cells
                for geom in group_geoms:
                    area_sqft = geom.area
                    features.append({
                        'group_id': group_idx + 1,
                        'cell_count': 1,
                        'area_sqft': area_sqft,
                        'area_acres': area_sqft / 43560.0,
                        'geometry': geom
                    })

        # Convert to GeoDataFrame
        if features:
            result = gpd.GeoDataFrame(features, crs=cells_gdf.crs)
        else:
            result = gpd.GeoDataFrame({
                'group_id': [],
                'cell_count': [],
                'area_sqft': [],
                'area_acres': [],
                'geometry': []
            }, crs=cells_gdf.crs)

        return result
