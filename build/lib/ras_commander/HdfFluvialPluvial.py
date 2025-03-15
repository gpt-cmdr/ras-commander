"""
Class: HdfFluvialPluvial

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfFluvialPluvial:
- calculate_fluvial_pluvial_boundary()
- _process_cell_adjacencies()
- _identify_boundary_edges()

"""

from typing import Dict, List, Tuple
import pandas as pd
import geopandas as gpd
from collections import defaultdict
from shapely.geometry import LineString, MultiLineString  # Added MultiLineString import
from tqdm import tqdm
from .HdfMesh import HdfMesh
from .HdfUtils import HdfUtils
from .Decorators import standardize_input
from .HdfResultsMesh import HdfResultsMesh
from .LoggingConfig import get_logger
from pathlib import Path

logger = get_logger(__name__)

class HdfFluvialPluvial:
    """
    A class for analyzing and visualizing fluvial-pluvial boundaries in HEC-RAS 2D model results.

    This class provides methods to process and visualize HEC-RAS 2D model outputs,
    specifically focusing on the delineation of fluvial and pluvial flood areas.
    It includes functionality for calculating fluvial-pluvial boundaries based on
    the timing of maximum water surface elevations.

    Key Concepts:
    - Fluvial flooding: Flooding from rivers/streams
    - Pluvial flooding: Flooding from rainfall/surface water
    - Delta_t: Time threshold (in hours) used to distinguish between fluvial and pluvial cells.
               Cells with max WSE time differences greater than delta_t are considered boundaries.

    Data Requirements:
    - HEC-RAS plan HDF file containing:
        - 2D mesh cell geometry (accessed via HdfMesh)
        - Maximum water surface elevation times (accessed via HdfResultsMesh)

    Usage Example:
        >>> ras = init_ras_project(project_path, ras_version)
        >>> hdf_path = Path("path/to/plan.hdf")
        >>> boundary_gdf = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
        ...     hdf_path, 
        ...     delta_t=12
        ... )
    """
    def __init__(self):
        self.logger = get_logger(__name__)  # Initialize logger with module name
    
    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def calculate_fluvial_pluvial_boundary(hdf_path: Path, delta_t: float = 12) -> gpd.GeoDataFrame:
        """
        Calculate the fluvial-pluvial boundary based on cell polygons and maximum water surface elevation times.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file
            delta_t (float): Threshold time difference in hours. Cells with time differences
                        greater than this value are considered boundaries. Default is 12 hours.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing the fluvial-pluvial boundaries with:
                - geometry: LineString features representing boundaries
                - CRS: Coordinate reference system matching the input HDF file

        Raises:
            ValueError: If no cell polygons or maximum water surface data found in HDF file
            Exception: If there are errors during boundary calculation

        Note:
            The returned boundaries represent locations where the timing of maximum water surface
            elevation changes significantly (> delta_t), indicating potential transitions between
            fluvial and pluvial flooding mechanisms.
        """
        try:
            # Get cell polygons from HdfMesh
            logger.info("Getting cell polygons from HDF file...")
            cell_polygons_gdf = HdfMesh.get_mesh_cell_polygons(hdf_path)
            if cell_polygons_gdf.empty:
                raise ValueError("No cell polygons found in HDF file")

            # Get max water surface data from HdfResultsMesh
            logger.info("Getting maximum water surface data from HDF file...")
            max_ws_df = HdfResultsMesh.get_mesh_max_ws(hdf_path)
            if max_ws_df.empty:
                raise ValueError("No maximum water surface data found in HDF file")

            # Convert timestamps using the renamed utility function
            logger.info("Converting maximum water surface timestamps...")
            if 'maximum_water_surface_time' in max_ws_df.columns:
                max_ws_df['maximum_water_surface_time'] = max_ws_df['maximum_water_surface_time'].apply(
                    lambda x: HdfUtils.parse_ras_datetime(x) if isinstance(x, str) else x
                )

            # Process cell adjacencies
            logger.info("Processing cell adjacencies...")
            cell_adjacency, common_edges = HdfFluvialPluvial._process_cell_adjacencies(cell_polygons_gdf)
            
            # Get cell times from max_ws_df
            logger.info("Extracting cell times from maximum water surface data...")
            cell_times = max_ws_df.set_index('cell_id')['maximum_water_surface_time'].to_dict()
            
            # Identify boundary edges
            logger.info("Identifying boundary edges...")
            boundary_edges = HdfFluvialPluvial._identify_boundary_edges(
                cell_adjacency, common_edges, cell_times, delta_t
            )

            # FOCUS YOUR REVISIONS HERE: 
            # Join adjacent LineStrings into simple LineStrings by connecting them at shared endpoints
            logger.info("Joining adjacent LineStrings into simple LineStrings...")
            
            def get_coords(geom):
                """Helper function to extract coordinates from geometry objects
                
                Args:
                    geom: A Shapely LineString or MultiLineString geometry
                
                Returns:
                    tuple: Tuple containing:
                        - list of original coordinates [(x1,y1), (x2,y2),...]
                        - list of rounded coordinates for comparison
                        - None if invalid geometry
                """
                if isinstance(geom, LineString):
                    orig_coords = list(geom.coords)
                    # Round coordinates to 0.01 for comparison
                    rounded_coords = [(round(x, 2), round(y, 2)) for x, y in orig_coords]
                    return orig_coords, rounded_coords
                elif isinstance(geom, MultiLineString):
                    orig_coords = list(geom.geoms[0].coords)
                    rounded_coords = [(round(x, 2), round(y, 2)) for x, y in orig_coords]
                    return orig_coords, rounded_coords
                return None, None

            def find_connecting_line(current_end, unused_lines, endpoint_counts, rounded_endpoints):
                """Find a line that connects to the current endpoint
                
                Args:
                    current_end: Tuple of (x, y) coordinates
                    unused_lines: Set of unused line indices
                    endpoint_counts: Dict of endpoint occurrence counts
                    rounded_endpoints: Dict of rounded endpoint coordinates
                
                Returns:
                    tuple: (line_index, should_reverse, found) or (None, None, False)
                """
                rounded_end = (round(current_end[0], 2), round(current_end[1], 2))
                
                # Skip if current endpoint is connected to more than 2 lines
                if endpoint_counts.get(rounded_end, 0) > 2:
                    return None, None, False
                
                for i in unused_lines:
                    start, end = rounded_endpoints[i]
                    if start == rounded_end and endpoint_counts.get(start, 0) <= 2:
                        return i, False, True
                    elif end == rounded_end and endpoint_counts.get(end, 0) <= 2:
                        return i, True, True
                return None, None, False

            # Initialize data structures
            joined_lines = []
            unused_lines = set(range(len(boundary_edges)))
            
            # Create endpoint lookup dictionaries
            line_endpoints = {}
            rounded_endpoints = {}
            for i, edge in enumerate(boundary_edges):
                coords_result = get_coords(edge)
                if coords_result:
                    orig_coords, rounded_coords = coords_result
                    line_endpoints[i] = (orig_coords[0], orig_coords[-1])
                    rounded_endpoints[i] = (rounded_coords[0], rounded_coords[-1])

            # Count endpoint occurrences
            endpoint_counts = {}
            for start, end in rounded_endpoints.values():
                endpoint_counts[start] = endpoint_counts.get(start, 0) + 1
                endpoint_counts[end] = endpoint_counts.get(end, 0) + 1

            # Iteratively join lines
            while unused_lines:
                # Start a new line chain
                current_points = []
                
                # Find first unused line
                start_idx = unused_lines.pop()
                start_coords, _ = get_coords(boundary_edges[start_idx])
                if start_coords:
                    current_points.extend(start_coords)
                
                # Try to extend in both directions
                continue_joining = True
                while continue_joining:
                    continue_joining = False
                    
                    # Try to extend forward
                    next_idx, should_reverse, found = find_connecting_line(
                        current_points[-1], 
                        unused_lines,
                        endpoint_counts,
                        rounded_endpoints
                    )
                    
                    if found:
                        unused_lines.remove(next_idx)
                        next_coords, _ = get_coords(boundary_edges[next_idx])
                        if next_coords:
                            if should_reverse:
                                current_points.extend(reversed(next_coords[:-1]))
                            else:
                                current_points.extend(next_coords[1:])
                        continue_joining = True
                        continue
                    
                    # Try to extend backward
                    prev_idx, should_reverse, found = find_connecting_line(
                        current_points[0], 
                        unused_lines,
                        endpoint_counts,
                        rounded_endpoints
                    )
                    
                    if found:
                        unused_lines.remove(prev_idx)
                        prev_coords, _ = get_coords(boundary_edges[prev_idx])
                        if prev_coords:
                            if should_reverse:
                                current_points[0:0] = reversed(prev_coords[:-1])
                            else:
                                current_points[0:0] = prev_coords[:-1]
                        continue_joining = True
                
                # Create final LineString from collected points
                if current_points:
                    joined_lines.append(LineString(current_points))

            # FILL GAPS BETWEEN JOINED LINES
            logger.info(f"Starting gap analysis for {len(joined_lines)} line segments...")
            
            def find_endpoints(lines):
                """Get all endpoints of the lines with their indices"""
                endpoints = []
                for i, line in enumerate(lines):
                    coords = list(line.coords)
                    endpoints.append((coords[0], i, 'start'))
                    endpoints.append((coords[-1], i, 'end'))
                return endpoints
            
            def find_nearby_points(point1, point2, tolerance=0.01):
                """Check if two points are within tolerance distance"""
                return (abs(point1[0] - point2[0]) <= tolerance and 
                       abs(point1[1] - point2[1]) <= tolerance)
            
            def find_gaps(lines, tolerance=0.01):
                """Find gaps between line endpoints"""
                logger.info("Analyzing line endpoints to identify gaps...")
                endpoints = []
                for i, line in enumerate(lines):
                    coords = list(line.coords)
                    start = coords[0]
                    end = coords[-1]
                    endpoints.append({
                        'point': start,
                        'line_idx': i,
                        'position': 'start',
                        'coords': coords
                    })
                    endpoints.append({
                        'point': end,
                        'line_idx': i,
                        'position': 'end',
                        'coords': coords
                    })
                
                logger.info(f"Found {len(endpoints)} endpoints to analyze")
                gaps = []
                
                # Compare each endpoint with all others
                for i, ep1 in enumerate(endpoints):
                    for ep2 in endpoints[i+1:]:
                        # Skip if endpoints are from same line
                        if ep1['line_idx'] == ep2['line_idx']:
                            continue
                            
                        point1 = ep1['point']
                        point2 = ep2['point']
                        
                        # Skip if points are too close (already connected)
                        if find_nearby_points(point1, point2):
                            continue
                            
                        # Check if this could be a gap
                        dist = LineString([point1, point2]).length
                        if dist < 10.0:  # Maximum gap distance threshold
                            gaps.append({
                                'start': ep1,
                                'end': ep2,
                                'distance': dist
                            })
                
                logger.info(f"Identified {len(gaps)} potential gaps to fill")
                return sorted(gaps, key=lambda x: x['distance'])

            def join_lines_with_gap(line1_coords, line2_coords, gap_start_pos, gap_end_pos):
                """Join two lines maintaining correct point order based on gap positions"""
                if gap_start_pos == 'end' and gap_end_pos == 'start':
                    # line1 end connects to line2 start
                    return line1_coords + line2_coords
                elif gap_start_pos == 'start' and gap_end_pos == 'end':
                    # line1 start connects to line2 end
                    return list(reversed(line2_coords)) + line1_coords
                elif gap_start_pos == 'end' and gap_end_pos == 'end':
                    # line1 end connects to line2 end
                    return line1_coords + list(reversed(line2_coords))
                else:  # start to start
                    # line1 start connects to line2 start
                    return list(reversed(line1_coords)) + line2_coords

            # Process gaps and join lines
            processed_lines = joined_lines.copy()
            line_groups = [[i] for i in range(len(processed_lines))]
            gaps = find_gaps(processed_lines)
            
            filled_gap_count = 0
            for gap_idx, gap in enumerate(gaps, 1):
                logger.info(f"Processing gap {gap_idx}/{len(gaps)} (distance: {gap['distance']:.3f})")
                
                line1_idx = gap['start']['line_idx']
                line2_idx = gap['end']['line_idx']
                
                # Find the groups containing these lines
                group1 = next(g for g in line_groups if line1_idx in g)
                group2 = next(g for g in line_groups if line2_idx in g)
                
                # Skip if lines are already in the same group
                if group1 == group2:
                    continue
                
                # Get the coordinates for both lines
                line1_coords = gap['start']['coords']
                line2_coords = gap['end']['coords']
                
                # Join the lines in correct order
                joined_coords = join_lines_with_gap(
                    line1_coords,
                    line2_coords,
                    gap['start']['position'],
                    gap['end']['position']
                )
                
                # Create new joined line
                new_line = LineString(joined_coords)
                
                # Update processed_lines and line_groups
                new_idx = len(processed_lines)
                processed_lines.append(new_line)
                
                # Merge groups and remove old ones
                new_group = group1 + group2
                line_groups.remove(group1)
                line_groups.remove(group2)
                line_groups.append(new_group + [new_idx])
                
                filled_gap_count += 1
                logger.info(f"Successfully joined lines {line1_idx} and {line2_idx}")
            
            logger.info(f"Gap filling complete. Filled {filled_gap_count} out of {len(gaps)} gaps")
            
            # Get final lines (take the last line from each group)
            final_lines = [processed_lines[group[-1]] for group in line_groups]
            
            logger.info(f"Final cleanup complete. Resulting in {len(final_lines)} line segments")
            joined_lines = final_lines

            # Create final GeoDataFrame with CRS from cell_polygons_gdf
            logger.info("Creating final GeoDataFrame for boundaries...")
            boundary_gdf = gpd.GeoDataFrame(
                geometry=joined_lines, 
                crs=cell_polygons_gdf.crs
            )

            # Clean up intermediate dataframes
            logger.info("Cleaning up intermediate dataframes...")
            del cell_polygons_gdf
            del max_ws_df

            logger.info("Fluvial-pluvial boundary calculation completed successfully.")
            return boundary_gdf

        except Exception as e:
            self.logger.error(f"Error calculating fluvial-pluvial boundary: {str(e)}")
            return None
        
        
    @staticmethod
    def _process_cell_adjacencies(cell_polygons_gdf: gpd.GeoDataFrame) -> Tuple[Dict[int, List[int]], Dict[int, Dict[int, LineString]]]:
        """
        Optimized method to process cell adjacencies by extracting shared edges directly.
        
        Args:
            cell_polygons_gdf (gpd.GeoDataFrame): GeoDataFrame containing 2D mesh cell polygons
                                                   with 'cell_id' and 'geometry' columns.

        Returns:
            Tuple containing:
                - Dict[int, List[int]]: Dictionary mapping cell IDs to lists of adjacent cell IDs.
                - Dict[int, Dict[int, LineString]]: Nested dictionary storing common edges between cells,
                                                    where common_edges[cell1][cell2] gives the shared boundary.
        """
        cell_adjacency = defaultdict(list)
        common_edges = defaultdict(dict)

        # Build an edge to cells mapping
        edge_to_cells = defaultdict(set)

        # Function to generate edge keys
        def edge_key(coords1, coords2, precision=8):
            # Round coordinates
            coords1 = tuple(round(coord, precision) for coord in coords1)
            coords2 = tuple(round(coord, precision) for coord in coords2)
            # Create sorted key to handle edge direction
            return tuple(sorted([coords1, coords2]))

        # For each polygon, extract edges
        for idx, row in cell_polygons_gdf.iterrows():
            cell_id = row['cell_id']
            geom = row['geometry']
            if geom.is_empty or not geom.is_valid:
                continue
            # Get exterior coordinates
            coords = list(geom.exterior.coords)
            num_coords = len(coords)
            for i in range(num_coords - 1):
                coord1 = coords[i]
                coord2 = coords[i + 1]
                key = edge_key(coord1, coord2)
                edge_to_cells[key].add(cell_id)

        # Now, process edge_to_cells to build adjacency
        for edge, cells in edge_to_cells.items():
            cells = list(cells)
            if len(cells) >= 2:
                # For all pairs of cells sharing this edge
                for i in range(len(cells)):
                    for j in range(i + 1, len(cells)):
                        cell1 = cells[i]
                        cell2 = cells[j]
                        # Update adjacency
                        if cell2 not in cell_adjacency[cell1]:
                            cell_adjacency[cell1].append(cell2)
                        if cell1 not in cell_adjacency[cell2]:
                            cell_adjacency[cell2].append(cell1)
                        # Store common edge
                        common_edge = LineString([edge[0], edge[1]])
                        common_edges[cell1][cell2] = common_edge
                        common_edges[cell2][cell1] = common_edge

        logger.info("Cell adjacencies processed successfully.")
        return cell_adjacency, common_edges

    @staticmethod
    def _identify_boundary_edges(cell_adjacency: Dict[int, List[int]], 
                               common_edges: Dict[int, Dict[int, LineString]], 
                               cell_times: Dict[int, pd.Timestamp], 
                               delta_t: float) -> List[LineString]:
        """
        Identify boundary edges between cells with significant time differences.

        Args:
            cell_adjacency (Dict[int, List[int]]): Dictionary of cell adjacencies
            common_edges (Dict[int, Dict[int, LineString]]): Dictionary of shared edges between cells
            cell_times (Dict[int, pd.Timestamp]): Dictionary mapping cell IDs to their max WSE times
            delta_t (float): Time threshold in hours

        Returns:
            List[LineString]: List of LineString geometries representing boundaries
        """
        # Validate cell_times data
        valid_times = {k: v for k, v in cell_times.items() if pd.notna(v)}
        if len(valid_times) < len(cell_times):
            logger.warning(f"Found {len(cell_times) - len(valid_times)} cells with invalid timestamps")
            cell_times = valid_times

        # Use a set to store processed cell pairs and avoid duplicates
        processed_pairs = set()
        boundary_edges = []
        
        # Track time differences for debugging
        time_diffs = []

        with tqdm(total=len(cell_adjacency), desc="Processing cell adjacencies") as pbar:
            for cell_id, neighbors in cell_adjacency.items():
                if cell_id not in cell_times:
                    logger.debug(f"Skipping cell {cell_id} - no timestamp data")
                    pbar.update(1)
                    continue
                    
                cell_time = cell_times[cell_id]

                for neighbor_id in neighbors:
                    if neighbor_id not in cell_times:
                        logger.debug(f"Skipping neighbor {neighbor_id} of cell {cell_id} - no timestamp data")
                        continue
                        
                    # Create a sorted tuple of the cell pair to ensure uniqueness
                    cell_pair = tuple(sorted([cell_id, neighbor_id]))
                    
                    # Skip if we've already processed this pair
                    if cell_pair in processed_pairs:
                        continue
                        
                    neighbor_time = cell_times[neighbor_id]
                    
                    # Ensure both timestamps are valid
                    if pd.isna(cell_time) or pd.isna(neighbor_time):
                        continue
                    
                    # Calculate time difference in hours
                    time_diff = abs((cell_time - neighbor_time).total_seconds() / 3600)
                    time_diffs.append(time_diff)
                    
                    logger.debug(f"Time difference between cells {cell_id} and {neighbor_id}: {time_diff:.2f} hours")

                    if time_diff >= delta_t:
                        logger.debug(f"Found boundary edge between cells {cell_id} and {neighbor_id} "
                                   f"(time diff: {time_diff:.2f} hours)")
                        boundary_edges.append(common_edges[cell_id][neighbor_id])
                    
                    # Mark this pair as processed
                    processed_pairs.add(cell_pair)

                pbar.update(1)

        # Log summary statistics
        if time_diffs:
            logger.info(f"Time difference statistics:")
            logger.info(f"  Min: {min(time_diffs):.2f} hours")
            logger.info(f"  Max: {max(time_diffs):.2f} hours")
            logger.info(f"  Mean: {sum(time_diffs)/len(time_diffs):.2f} hours")
            logger.info(f"  Number of boundaries found: {len(boundary_edges)}")
            logger.info(f"  Delta-t threshold: {delta_t} hours")

        return boundary_edges