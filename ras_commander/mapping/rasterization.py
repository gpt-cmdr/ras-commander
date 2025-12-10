"""
Triangle rasterization for sloped water surface interpolation.

This module implements water surface rasterization for RASMapper's
"Sloped (Cell Corners)" mode. For now, we use a simplified approach
that rasterizes using linear interpolation within each mesh cell.

For the full sloped implementation, each cell is divided into triangles
connecting the cell center to adjacent vertices, and pixel values are
computed by interpolating along the plane defined by each triangle.
"""

from typing import Dict, Tuple, Optional, Callable, List
from pathlib import Path
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Constants
NODATA = np.float32(-9999.0)


class PlaneInterpolator:
    """
    Defines a plane through 3 points for linear interpolation.

    Used to interpolate WSE values within triangles during rasterization.
    """

    def __init__(self):
        self.a = 0.0  # dz/dx coefficient
        self.b = 0.0  # dz/dy coefficient
        self.c = 0.0  # z at origin
        self.valid = False

    def set_from_points(
        self,
        x0: float, y0: float, z0: float,
        x1: float, y1: float, z1: float,
        x2: float, y2: float, z2: float,
    ) -> bool:
        """
        Define plane through three points.

        Returns True if plane is valid (non-degenerate triangle).
        """
        # Vectors from p0 to p1 and p0 to p2
        dx1, dy1, dz1 = x1 - x0, y1 - y0, z1 - z0
        dx2, dy2, dz2 = x2 - x0, y2 - y0, z2 - z0

        # Normal vector via cross product
        nx = dy1 * dz2 - dz1 * dy2
        ny = dz1 * dx2 - dx1 * dz2
        nz = dx1 * dy2 - dy1 * dx2

        # Check for degenerate triangle
        if abs(nz) < 1e-10:
            self.valid = False
            return False

        self.a = -nx / nz  # dz/dx
        self.b = -ny / nz  # dz/dy
        self.c = z0 - self.a * x0 - self.b * y0

        self.valid = True
        return True

    def z_at(self, x: float, y: float) -> float:
        """Evaluate z at (x, y)."""
        return self.a * x + self.b * y + self.c

    @property
    def dz_dx(self) -> float:
        """Partial derivative dz/dx."""
        return self.a


def build_cell_triangles(
    topology: Dict,
    cell_wse: np.ndarray,
    vertex_wse: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Build triangles from mesh cells for rasterization.

    Each cell is divided into triangles connecting the cell center to
    adjacent vertices (facepoints).

    Parameters
    ----------
    topology : Dict
        Mesh topology from HdfMesh.get_mesh_sloped_topology().
    cell_wse : np.ndarray
        Water surface elevation per cell, shape (n_cells,).
    vertex_wse : np.ndarray
        Water surface elevation per vertex, shape (n_facepoints,).

    Returns
    -------
    triangles : np.ndarray
        Triangle vertices, shape (n_triangles, 3, 3).
        Each triangle has 3 vertices, each with (x, y, z).
    valid_mask : np.ndarray
        Boolean mask indicating valid (wet) triangles.
    """
    cell_centers = topology['cell_centers']
    facepoint_coords = topology['facepoint_coords']
    cell_face_info = topology['cell_face_info']
    cell_face_values = topology['cell_face_values']
    face_facepoints = topology['face_facepoints']

    n_cells = len(cell_centers)

    triangles_list = []
    valid_list = []

    for cell_idx in range(n_cells):
        cell_ws = cell_wse[cell_idx]

        # Skip dry cells
        if cell_ws == NODATA or cell_ws <= -9000:
            continue

        cell_x, cell_y = cell_centers[cell_idx]

        # Get faces for this cell
        start, count = cell_face_info[cell_idx]
        if count == 0:
            continue

        # Collect all vertices around the cell from faces
        face_data = cell_face_values[start:start + count]
        face_indices = face_data[:, 0]
        orientations = face_data[:, 1]

        # Build ordered list of vertices around the cell
        # Each face contributes both its endpoints
        vertices_around_cell = []
        for i, (face_idx, orient) in enumerate(zip(face_indices, orientations)):
            fp_a, fp_b = face_facepoints[face_idx]
            # Based on orientation, determine vertex order for CCW traversal
            if orient == 0:
                # Cell is on 'a' side - vertices go a->b
                if not vertices_around_cell or vertices_around_cell[-1] != fp_a:
                    vertices_around_cell.append(fp_a)
            else:
                # Cell is on 'b' side - vertices go b->a
                if not vertices_around_cell or vertices_around_cell[-1] != fp_b:
                    vertices_around_cell.append(fp_b)

        # Remove duplicates while preserving order
        seen = set()
        unique_vertices = []
        for v in vertices_around_cell:
            if v not in seen:
                seen.add(v)
                unique_vertices.append(v)
        vertices_around_cell = unique_vertices

        # Create triangles: (cell_center, vertex_i, vertex_i+1)
        n_verts = len(vertices_around_cell)
        if n_verts < 2:
            continue

        for i in range(n_verts):
            v0_idx = vertices_around_cell[i]
            v1_idx = vertices_around_cell[(i + 1) % n_verts]

            # Skip degenerate triangles (same vertex)
            if v0_idx == v1_idx:
                continue

            v0_ws = vertex_wse[v0_idx]
            v1_ws = vertex_wse[v1_idx]

            # Check if vertices are valid (not NODATA)
            if v0_ws == NODATA or v1_ws == NODATA:
                continue

            # Build triangle
            v0_x, v0_y = facepoint_coords[v0_idx]
            v1_x, v1_y = facepoint_coords[v1_idx]

            triangle = np.array([
                [cell_x, cell_y, cell_ws],
                [v0_x, v0_y, v0_ws],
                [v1_x, v1_y, v1_ws],
            ], dtype=np.float64)

            triangles_list.append(triangle)
            valid_list.append(True)

    if not triangles_list:
        return np.zeros((0, 3, 3), dtype=np.float64), np.zeros(0, dtype=bool)

    triangles = np.array(triangles_list, dtype=np.float64)
    valid_mask = np.array(valid_list, dtype=bool)

    return triangles, valid_mask


def rasterize_sloped_wse_griddata(
    topology: Dict,
    cell_wse: np.ndarray,
    vertex_wse: np.ndarray,
    transform,
    shape: Tuple[int, int],
    terrain: np.ndarray = None,
) -> np.ndarray:
    """
    Rasterize sloped WSE using scipy's griddata interpolation.

    This is a simpler approach that interpolates from all cell centers
    and vertices to the output grid.

    Parameters
    ----------
    topology : Dict
        Mesh topology from HdfMesh.get_mesh_sloped_topology().
    cell_wse : np.ndarray
        Water surface elevation per cell, shape (n_cells,).
    vertex_wse : np.ndarray
        Water surface elevation per vertex, shape (n_facepoints,).
    transform : Affine
        Raster transform defining the output grid.
    shape : Tuple[int, int]
        Output raster shape (height, width).
    terrain : np.ndarray, optional
        Terrain elevation raster for depth clipping.

    Returns
    -------
    np.ndarray
        WSE raster, shape (height, width), dtype float32.
    """
    from scipy.interpolate import griddata

    height, width = shape
    raster = np.full((height, width), NODATA, dtype=np.float32)

    # Collect all points with valid WSE
    cell_centers = topology['cell_centers']
    facepoint_coords = topology['facepoint_coords']

    # Cell center points
    valid_cells = (cell_wse != NODATA) & (cell_wse > -9000)
    cell_pts = cell_centers[valid_cells]
    cell_vals = cell_wse[valid_cells]

    # Vertex points
    valid_verts = (vertex_wse != NODATA) & (vertex_wse > -9000)
    vert_pts = facepoint_coords[valid_verts]
    vert_vals = vertex_wse[valid_verts]

    if len(cell_pts) == 0 and len(vert_pts) == 0:
        return raster

    # Combine points
    all_pts = np.vstack([cell_pts, vert_pts])
    all_vals = np.concatenate([cell_vals, vert_vals])

    logger.info(f"Interpolating from {len(all_pts)} points")

    # Create output grid coordinates
    cell_size = abs(transform.a)
    origin_x, origin_y = transform.c, transform.f

    # Create grid of pixel centers
    cols = np.arange(width)
    rows = np.arange(height)
    x_coords = origin_x + (cols + 0.5) * cell_size
    y_coords = origin_y - (rows + 0.5) * cell_size
    xi, yi = np.meshgrid(x_coords, y_coords)

    # Interpolate
    raster = griddata(
        all_pts,
        all_vals,
        (xi, yi),
        method='linear',
        fill_value=NODATA,
    ).astype(np.float32)

    # Apply terrain clipping if provided
    if terrain is not None:
        dry_mask = (raster != NODATA) & (raster <= terrain)
        raster[dry_mask] = NODATA

    return raster


def rasterize_sloped_wse_bens_weights(
    topology: Dict,
    cell_wse: np.ndarray,
    vertex_wse: np.ndarray,
    transform,
    shape: Tuple[int, int],
    terrain: np.ndarray = None,
    progress_callback: Callable[[int, int], None] = None,
) -> np.ndarray:
    """
    Rasterize sloped WSE using Ben's Weights (exact RASMapper algorithm).

    This implements the exact pixel-by-pixel interpolation used by RASMapper's
    "Sloped (Cell Corners)" mode using generalized barycentric coordinates.

    Parameters
    ----------
    topology : Dict
        Mesh topology from HdfMesh.get_mesh_sloped_topology().
    cell_wse : np.ndarray
        Water surface elevation per cell, shape (n_cells,).
    vertex_wse : np.ndarray
        Water surface elevation per vertex, shape (n_facepoints,).
    transform : Affine
        Raster transform defining the output grid.
    shape : Tuple[int, int]
        Output raster shape (height, width).
    terrain : np.ndarray, optional
        Terrain elevation raster for depth clipping.
    progress_callback : Callable, optional
        Callback for progress updates: callback(current_row, total_rows).

    Returns
    -------
    np.ndarray
        WSE raster, shape (height, width), dtype float32.
    """
    from shapely.geometry import box, Point
    from shapely.strtree import STRtree
    from shapely import Polygon as ShapelyPolygon
    from .sloped_interpolation import compute_bens_weights, NODATA as INTERP_NODATA

    height, width = shape
    raster = np.full((height, width), NODATA, dtype=np.float32)

    # Build cell polygons for spatial indexing
    facepoint_coords = topology['facepoint_coords']
    cell_face_info = topology['cell_face_info']
    cell_face_values = topology['cell_face_values']
    face_facepoints = topology['face_facepoints']
    n_cells = topology['n_cells']

    logger.info(f"Building spatial index for {n_cells} cells...")

    # Build cell polygons and extract facepoint indices per cell
    cell_polygons = []
    cell_facepoint_indices = []  # List of arrays, one per cell
    cell_bounds = []  # Bounding boxes for fast rejection
    cells_no_faces = 0
    cells_few_fps = 0
    cells_invalid_poly = 0

    for cell_idx in range(n_cells):
        start, count = cell_face_info[cell_idx]
        if count == 0:
            cell_polygons.append(None)
            cell_facepoint_indices.append(np.array([], dtype=np.int32))
            cell_bounds.append(None)
            cells_no_faces += 1
            continue

        # Get faces for this cell
        face_data = cell_face_values[start:start + count]
        face_indices = face_data[:, 0]
        orientations = face_data[:, 1]

        # Collect facepoints around the cell
        # Add both endpoints from each face, then deduplicate
        fp_set = set()
        for face_idx in face_indices:
            fp_a, fp_b = face_facepoints[face_idx]
            fp_set.add(fp_a)
            fp_set.add(fp_b)

        if len(fp_set) < 3:
            cell_polygons.append(None)
            cell_facepoint_indices.append(np.array([], dtype=np.int32))
            cell_bounds.append(None)
            cells_few_fps += 1
            continue

        # Order facepoints by angle from cell center for CCW traversal
        cell_center = topology['cell_centers'][cell_idx]
        fp_list = list(fp_set)
        fp_coords = facepoint_coords[fp_list]

        # Calculate angles from center
        dx = fp_coords[:, 0] - cell_center[0]
        dy = fp_coords[:, 1] - cell_center[1]
        angles = np.arctan2(dy, dx)

        # Sort by angle for CCW order
        sorted_indices = np.argsort(angles)
        unique_fps = [fp_list[i] for i in sorted_indices]

        if len(unique_fps) < 3:
            cell_polygons.append(None)
            cell_facepoint_indices.append(np.array([], dtype=np.int32))
            cell_bounds.append(None)
            cells_few_fps += 1
            continue

        # Build polygon
        coords = facepoint_coords[unique_fps]
        try:
            poly = ShapelyPolygon(coords)
            if poly.is_valid:
                cell_polygons.append(poly)
                cell_facepoint_indices.append(np.array(unique_fps, dtype=np.int32))
                cell_bounds.append(poly.bounds)  # (minx, miny, maxx, maxy)
            else:
                # Try to fix invalid polygon with buffer(0)
                fixed_poly = poly.buffer(0)
                if fixed_poly.is_valid and not fixed_poly.is_empty:
                    cell_polygons.append(fixed_poly)
                    cell_facepoint_indices.append(np.array(unique_fps, dtype=np.int32))
                    cell_bounds.append(fixed_poly.bounds)
                else:
                    cell_polygons.append(None)
                    cell_facepoint_indices.append(np.array([], dtype=np.int32))
                    cell_bounds.append(None)
                    cells_invalid_poly += 1
        except Exception:
            cell_polygons.append(None)
            cell_facepoint_indices.append(np.array([], dtype=np.int32))
            cell_bounds.append(None)
            cells_invalid_poly += 1

    # Build spatial index from valid polygons
    valid_polygons = [(i, poly) for i, poly in enumerate(cell_polygons) if poly is not None]
    if not valid_polygons:
        logger.warning("No valid cell polygons found")
        return raster

    polygon_indices = [i for i, _ in valid_polygons]
    polygon_geoms = [poly for _, poly in valid_polygons]
    tree = STRtree(polygon_geoms)

    logger.info(f"  Valid cell polygons: {len(valid_polygons)} / {n_cells} ({100*len(valid_polygons)/n_cells:.1f}%)")
    if cells_no_faces > 0:
        logger.info(f"    No faces: {cells_no_faces}")
    if cells_few_fps > 0:
        logger.info(f"    Too few facepoints (<3): {cells_few_fps}")
    if cells_invalid_poly > 0:
        logger.info(f"    Invalid polygon: {cells_invalid_poly}")

    logger.info(f"Rasterizing {height}x{width} grid using Ben's Weights...")

    # Get grid cell size and origin
    cell_size = abs(transform.a)
    origin_x, origin_y = transform.c, transform.f

    # Process rows in batches for progress reporting
    log_interval = max(1, height // 20)  # Log every 5%

    # Debug counters
    total_pixels = 0
    pixels_no_candidates = 0
    pixels_no_containing_cell = 0
    pixels_no_valid_vertices = 0
    pixels_successful = 0

    # Process each row
    for row in range(height):
        if row % log_interval == 0:
            logger.info(f"  Row {row}/{height} ({100*row/height:.1f}%)")
        if progress_callback:
            progress_callback(row, height)

        y = origin_y - (row + 0.5) * cell_size

        for col in range(width):
            total_pixels += 1
            x = origin_x + (col + 0.5) * cell_size

            # Query spatial index with point
            point = Point(x, y)
            candidate_indices = tree.query(point)

            if len(candidate_indices) == 0:
                pixels_no_candidates += 1
                continue

            # Find containing cell (use covers() to include boundary points)
            containing_cell = None
            nearest_dist = float('inf')
            nearest_cell = None

            for geom_idx in candidate_indices:
                cell_idx = polygon_indices[geom_idx]
                poly = polygon_geoms[geom_idx]
                # covers() includes boundary, contains() excludes it
                if poly.covers(point):
                    containing_cell = cell_idx
                    break
                else:
                    # Track nearest cell for fallback
                    centroid = poly.centroid
                    dist = (centroid.x - x)**2 + (centroid.y - y)**2
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest_cell = cell_idx

            # Fallback to nearest cell if containment fails (handles boundary pixels)
            if containing_cell is None:
                if nearest_cell is not None:
                    containing_cell = nearest_cell
                else:
                    pixels_no_containing_cell += 1
                    continue

            # Get facepoint indices for this cell
            fp_indices = cell_facepoint_indices[containing_cell]
            if len(fp_indices) < 3:
                continue

            # Get vertex WSE values
            vertex_values = vertex_wse[fp_indices]

            # Check for dry cell
            valid_mask = vertex_values != INTERP_NODATA
            if not np.any(valid_mask):
                pixels_no_valid_vertices += 1
                continue

            # Get facepoint coordinates
            coords = facepoint_coords[fp_indices]

            # Compute Ben's Weights
            weights = compute_bens_weights(x, y, coords)

            # Handle dry vertices by redistributing weights
            if not np.all(valid_mask):
                weights[~valid_mask] = 0
                total = np.sum(weights)
                if total > 0:
                    weights /= total
                else:
                    pixels_no_valid_vertices += 1
                    continue

            # Interpolate WSE
            wse = np.dot(weights, vertex_values)
            raster[row, col] = wse
            pixels_successful += 1

    logger.info(f"Rasterization complete")
    logger.info(f"  Total pixels: {total_pixels}")
    logger.info(f"  No candidates (outside mesh): {pixels_no_candidates} ({100*pixels_no_candidates/total_pixels:.1f}%)")
    logger.info(f"  No containing cell (between cells): {pixels_no_containing_cell} ({100*pixels_no_containing_cell/total_pixels:.1f}%)")
    logger.info(f"  No valid vertices (dry): {pixels_no_valid_vertices} ({100*pixels_no_valid_vertices/total_pixels:.1f}%)")
    logger.info(f"  Successful: {pixels_successful} ({100*pixels_successful/total_pixels:.1f}%)")

    # Apply terrain clipping if provided
    if terrain is not None:
        dry_mask = (raster != NODATA) & (raster <= terrain)
        raster[dry_mask] = NODATA

    return raster


def rasterize_sloped_wse(
    topology: Dict,
    cell_wse: np.ndarray,
    vertex_wse: np.ndarray,
    transform,
    shape: Tuple[int, int],
    terrain: np.ndarray = None,
    method: str = 'bens_weights',
) -> np.ndarray:
    """
    Rasterize sloped WSE to a grid.

    Parameters
    ----------
    topology : Dict
        Mesh topology from HdfMesh.get_mesh_sloped_topology().
    cell_wse : np.ndarray
        Water surface elevation per cell, shape (n_cells,).
    vertex_wse : np.ndarray
        Water surface elevation per vertex, shape (n_facepoints,).
    transform : Affine
        Raster transform defining the output grid.
    shape : Tuple[int, int]
        Output raster shape (height, width).
    terrain : np.ndarray, optional
        Terrain elevation raster for depth clipping.
    method : str, default 'bens_weights'
        Interpolation method:
        - 'bens_weights': Exact RASMapper algorithm (per-pixel barycentric)
        - 'griddata': scipy.griddata linear interpolation (faster but approximate)

    Returns
    -------
    np.ndarray
        WSE raster, shape (height, width), dtype float32.
    """
    if method == 'bens_weights':
        return rasterize_sloped_wse_bens_weights(
            topology, cell_wse, vertex_wse, transform, shape, terrain
        )
    elif method == 'griddata':
        return rasterize_sloped_wse_griddata(
            topology, cell_wse, vertex_wse, transform, shape, terrain
        )
    else:
        raise ValueError(f"Unknown method: {method}. Use 'bens_weights' or 'griddata'.")


def rasterize_sloped_wse_from_tif(
    topology: Dict,
    cell_wse: np.ndarray,
    vertex_wse: np.ndarray,
    terrain_path: Path,
    output_path: Path = None,
    method: str = 'bens_weights',
) -> np.ndarray:
    """
    Rasterize sloped WSE using terrain TIF for grid definition.

    Parameters
    ----------
    topology : Dict
        Mesh topology from HdfMesh.get_mesh_sloped_topology().
    cell_wse : np.ndarray
        Water surface elevation per cell.
    vertex_wse : np.ndarray
        Water surface elevation per vertex.
    terrain_path : Path
        Path to terrain GeoTIFF defining the output grid.
    output_path : Path, optional
        If provided, write output to GeoTIFF.
    method : str, default 'bens_weights'
        Interpolation method: 'bens_weights' (exact) or 'griddata' (fast).

    Returns
    -------
    np.ndarray
        WSE raster.
    """
    import rasterio

    with rasterio.open(terrain_path) as src:
        terrain = src.read(1)
        transform = src.transform
        crs = src.crs
        shape = terrain.shape

    raster = rasterize_sloped_wse(
        topology=topology,
        cell_wse=cell_wse,
        vertex_wse=vertex_wse,
        transform=transform,
        shape=shape,
        terrain=terrain,
        method=method,
    )

    if output_path is not None:
        with rasterio.open(
            output_path,
            'w',
            driver='GTiff',
            height=shape[0],
            width=shape[1],
            count=1,
            dtype=raster.dtype,
            crs=crs,
            transform=transform,
            nodata=NODATA,
        ) as dst:
            dst.write(raster, 1)

    return raster
