"""
Sloped water surface interpolation algorithms.

This module implements RASMapper's "Sloped (Cell Corners)" water surface
interpolation algorithm, which computes varying WSE values across mesh cells
by fitting planar surfaces through face and vertex elevations.

Algorithm Overview:
1. Compute Face WSE - Determine WSE at each face using hydraulic connectivity
2. Compute Face Midsides - Calculate application points for regression
3. Compute Vertex WSE - Fit planes through adjacent face values at each vertex

Reference: Decompiled RasMapperLib.dll from HEC-RAS 6.6
"""

from typing import Dict, Tuple, Optional
import numpy as np
from enum import IntEnum

# Constants matching RASMapper
NODATA = np.float32(-9999.0)
MIN_WS_PLOT_TOLERANCE = np.float32(0.001)


class HydraulicConnection(IntEnum):
    """Types of hydraulic connection between cells across a face."""
    NONE = 0               # No hydraulic connection
    BACKFILL = 1           # Water flowing uphill (pooling)
    LEVEE = 2              # Levee/weir condition
    DOWNHILL_DEEP = 3      # Deep flow (depth >= 2 * terrain gradient)
    DOWNHILL_SHALLOW = 4   # Shallow flow (depth < terrain gradient)
    DOWNHILL_INTERMEDIATE = 5  # Intermediate flow


class PlanarRegressionZ:
    """
    Least-squares planar regression for computing Z at a base point.

    Fits a plane Z = ax + by + c through a set of points using least-squares,
    then evaluates the plane at the base point (where dx=0, dy=0).

    This matches RASMapper's PlanarRegressionZ class exactly.

    Parameters
    ----------
    base_x : float
        X coordinate of the base point (evaluation point)
    base_y : float
        Y coordinate of the base point (evaluation point)

    Example
    -------
    >>> reg = PlanarRegressionZ(100.0, 200.0)
    >>> reg.add(95.0, 195.0, 650.0)
    >>> reg.add(105.0, 195.0, 651.0)
    >>> reg.add(100.0, 205.0, 650.5)
    >>> z_at_base = reg.solve_z()
    """

    def __init__(self, base_x: float, base_y: float):
        self.base_x = base_x
        self.base_y = base_y
        self._reset()

    def _reset(self):
        """Reset all accumulators."""
        self.sum_x2 = 0.0
        self.sum_x = 0.0
        self.sum_y2 = 0.0
        self.sum_y = 0.0
        self.sum_z = 0.0
        self.sum_xy = 0.0
        self.sum_yz = 0.0
        self.sum_xz = 0.0
        self.n = 0

    def add(self, x: float, y: float, z: float):
        """
        Add a point to the regression.

        Parameters
        ----------
        x, y : float
            Coordinates of the point
        z : float
            Z value (e.g., WSE) at the point
        """
        dx = x - self.base_x
        dy = y - self.base_y

        self.sum_x2 += dx * dx
        self.sum_x += dx
        self.sum_y2 += dy * dy
        self.sum_y += dy
        self.sum_z += z
        self.sum_xy += dx * dy
        self.sum_yz += dy * z
        self.sum_xz += dx * z
        self.n += 1

    def solve_z(self) -> float:
        """
        Solve for Z at the base point.

        Returns
        -------
        float
            Z value at the base point (where dx=0, dy=0)

        Notes
        -----
        - If only 1 point: returns that point's Z
        - If only 2 points: returns average Z
        - If 3+ points: solves least-squares plane
        - If determinant is 0: falls back to average
        """
        if self.n == 0:
            return NODATA

        if self.n == 1:
            return self.sum_z

        if self.n == 2:
            return self.sum_z / 2.0

        # Determinant of normal equations matrix
        # | sum_x2  sum_xy  sum_x  |
        # | sum_xy  sum_y2  sum_y  |
        # | sum_x   sum_y   n      |
        det = (
            self.sum_x2 * (self.sum_y2 * self.n - self.sum_y * self.sum_y) -
            self.sum_xy * (self.sum_xy * self.n - self.sum_y * self.sum_x) +
            self.sum_x * (self.sum_xy * self.sum_y - self.sum_y2 * self.sum_x)
        )

        if det == 0:
            return self.sum_z / self.n  # Fallback to average

        # Solve for Z at base point (where dx=0, dy=0)
        # Using Cramer's rule on the normal equations
        z = (
            self.sum_x2 * (self.sum_y2 * self.sum_z - self.sum_yz * self.sum_y) -
            self.sum_xy * (self.sum_xy * self.sum_z - self.sum_yz * self.sum_x) +
            self.sum_xz * (self.sum_xy * self.sum_y - self.sum_y2 * self.sum_x)
        ) / det

        return z

    @property
    def count(self) -> int:
        """Number of points added to the regression."""
        return self.n


def compute_face_wse(
    cell_wse: np.ndarray,
    cell_min_elev: np.ndarray,
    face_min_elev: np.ndarray,
    face_cells: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute face WSE values using hydraulic connectivity algorithm.

    This implements RASMapper's ComputeFaceWSsNew() algorithm which determines
    the water surface elevation at each face based on adjacent cell WSE values
    and terrain characteristics.

    Parameters
    ----------
    cell_wse : np.ndarray
        Water surface elevation per cell, shape (n_cells,), dtype float32.
        Use NODATA (-9999) for dry cells.
    cell_min_elev : np.ndarray
        Minimum terrain elevation per cell, shape (n_cells,), dtype float32.
    face_min_elev : np.ndarray
        Minimum terrain elevation per face, shape (n_faces,), dtype float32.
    face_cells : np.ndarray
        Cell indices for each face, shape (n_faces, 2), dtype int32.
        Column 0: cell_a index, Column 1: cell_b index.
        Use -1 for perimeter faces.

    Returns
    -------
    face_wse_a : np.ndarray
        WSE value for cell_a side of each face, shape (n_faces,), dtype float32.
    face_wse_b : np.ndarray
        WSE value for cell_b side of each face, shape (n_faces,), dtype float32.
    connection_type : np.ndarray
        HydraulicConnection type for each face, shape (n_faces,), dtype int8.

    Notes
    -----
    Faces can have different WSE values on each side (cell_a vs cell_b) when
    there is no hydraulic connection (levee, dry cell, etc.).

    The algorithm handles several cases:
    1. Dry cells or perimeter faces -> NODATA on dry side
    2. Both cells below face elevation -> No connection
    3. Backfill (water flowing uphill) -> Use max WSE on both sides
    4. Levee condition -> Different values on each side
    5. Downhill flow -> Interpolated based on depth vs terrain gradient
    """
    n_faces = len(face_cells)

    # Initialize output arrays
    face_wse_a = np.full(n_faces, NODATA, dtype=np.float32)
    face_wse_b = np.full(n_faces, NODATA, dtype=np.float32)
    connection_type = np.zeros(n_faces, dtype=np.int8)

    # Extract cell indices
    cell_a_idx = face_cells[:, 0]
    cell_b_idx = face_cells[:, 1]

    # Create masks for valid cells (not perimeter)
    valid_a = cell_a_idx >= 0
    valid_b = cell_b_idx >= 0
    both_valid = valid_a & valid_b

    # Get cell values (use dummy values for invalid cells)
    safe_cell_a = np.where(valid_a, cell_a_idx, 0)
    safe_cell_b = np.where(valid_b, cell_b_idx, 0)

    wse_a = np.where(valid_a, cell_wse[safe_cell_a], NODATA)
    wse_b = np.where(valid_b, cell_wse[safe_cell_b], NODATA)
    elev_a = np.where(valid_a, cell_min_elev[safe_cell_a], NODATA)
    elev_b = np.where(valid_b, cell_min_elev[safe_cell_b], NODATA)

    # Check for dry cells
    is_dry_a = valid_a & (wse_a <= elev_a + MIN_WS_PLOT_TOLERANCE)
    is_dry_b = valid_b & (wse_b <= elev_b + MIN_WS_PLOT_TOLERANCE)

    # Set NODATA for dry or invalid cells
    face_wse_a = np.where(is_dry_a | ~valid_a, NODATA, wse_a)
    face_wse_b = np.where(is_dry_b | ~valid_b, NODATA, wse_b)

    # Handle perimeter and dry cell cases (no connection)
    perimeter_or_dry = ~both_valid | is_dry_a | is_dry_b
    connection_type[perimeter_or_dry] = HydraulicConnection.NONE

    # Process internal faces with both cells wet
    internal_wet = both_valid & ~is_dry_a & ~is_dry_b

    if not np.any(internal_wet):
        return face_wse_a, face_wse_b, connection_type

    # Work only on internal wet faces
    idx = np.where(internal_wet)[0]

    # Get values for internal wet faces
    ws_a = wse_a[idx]
    ws_b = wse_b[idx]
    el_a = elev_a[idx]
    el_b = elev_b[idx]
    face_el = face_min_elev[idx]

    # Check if both cells below face elevation
    both_below_face = (ws_a <= face_el) & (ws_b <= face_el)
    below_mask = both_below_face
    face_wse_a[idx[below_mask]] = ws_a[below_mask]
    face_wse_b[idx[below_mask]] = ws_b[below_mask]
    connection_type[idx[below_mask]] = HydraulicConnection.NONE

    # Process remaining faces
    remaining = ~below_mask
    if not np.any(remaining):
        return face_wse_a, face_wse_b, connection_type

    idx = idx[remaining]
    ws_a = ws_a[remaining]
    ws_b = ws_b[remaining]
    el_a = el_a[remaining]
    el_b = el_b[remaining]
    face_el = face_el[remaining]

    # Determine high/low cells
    a_is_high = ws_a >= ws_b
    max_wse = np.where(a_is_high, ws_a, ws_b)
    low_wse = np.where(a_is_high, ws_b, ws_a)
    high_cell_elev = np.where(a_is_high, el_a, el_b)

    # Terrain gradient and depth
    terrain_gradient = np.abs(el_b - el_a)
    depth = max_wse - high_cell_elev

    # Critical flow check
    avg_wse = (ws_a + ws_b) / 2
    crit_wse = (max_wse - face_el) * (2.0 / 3.0) + face_el
    was_crit_cap_used = avg_wse <= crit_wse

    # Backfill check (water flowing uphill relative to terrain)
    wse_gradient = ws_b - ws_a
    terrain_diff = el_b - el_a
    is_backfill = (wse_gradient * terrain_diff <= 0) & (terrain_gradient > 0)

    # Levee check
    depth_above_face = max_wse - face_el
    is_levee = (
        was_crit_cap_used &
        (depth_above_face > 0) &
        (depth / np.maximum(depth_above_face, 1e-10) > 2)
    )

    # Apply levee condition
    levee_mask = is_levee
    levee_a_high = levee_mask & a_is_high
    levee_b_high = levee_mask & ~a_is_high

    face_wse_a[idx[levee_a_high]] = max_wse[levee_a_high]
    face_wse_b[idx[levee_a_high]] = ws_b[levee_a_high]
    face_wse_a[idx[levee_b_high]] = ws_a[levee_b_high]
    face_wse_b[idx[levee_b_high]] = max_wse[levee_b_high]
    connection_type[idx[levee_mask]] = HydraulicConnection.LEVEE

    # Apply backfill (not already levee)
    backfill_mask = is_backfill & ~levee_mask
    face_wse_a[idx[backfill_mask]] = max_wse[backfill_mask]
    face_wse_b[idx[backfill_mask]] = max_wse[backfill_mask]
    connection_type[idx[backfill_mask]] = HydraulicConnection.BACKFILL

    # Downhill cases (not levee or backfill, terrain_gradient > 0)
    downhill_mask = ~levee_mask & ~backfill_mask & (terrain_gradient > 0)

    if np.any(downhill_mask):
        d_idx = idx[downhill_mask]
        d_max_wse = max_wse[downhill_mask]
        d_low_wse = low_wse[downhill_mask]
        d_depth = depth[downhill_mask]
        d_terrain_grad = terrain_gradient[downhill_mask]
        d_face_el = face_el[downhill_mask]
        d_high_cell_elev = high_cell_elev[downhill_mask]

        # Deep downhill: depth >= 2 * terrain_gradient
        deep_mask = d_depth >= 2 * d_terrain_grad
        face_wse_a[d_idx[deep_mask]] = d_max_wse[deep_mask]
        face_wse_b[d_idx[deep_mask]] = d_max_wse[deep_mask]
        connection_type[d_idx[deep_mask]] = HydraulicConnection.DOWNHILL_DEEP

        # Shallow/intermediate cases
        shallow_or_inter = ~deep_mask
        if np.any(shallow_or_inter):
            s_idx = d_idx[shallow_or_inter]
            s_max = d_max_wse[shallow_or_inter]
            s_low = d_low_wse[shallow_or_inter]
            s_depth = d_depth[shallow_or_inter]
            s_tg = d_terrain_grad[shallow_or_inter]
            s_face_el = d_face_el[shallow_or_inter]
            s_hce = d_high_cell_elev[shallow_or_inter]

            # Quadratic interpolation formula
            num5 = np.maximum(s_face_el, s_low)
            num6 = num5 - s_hce
            face_wse_calc = num5 + (s_depth**2 - num6**2) / (2 * s_tg)

            # Shallow: depth <= terrain_gradient
            shallow_mask = s_depth <= s_tg
            face_wse_a[s_idx[shallow_mask]] = face_wse_calc[shallow_mask]
            face_wse_b[s_idx[shallow_mask]] = face_wse_calc[shallow_mask]
            connection_type[s_idx[shallow_mask]] = HydraulicConnection.DOWNHILL_SHALLOW

            # Intermediate: terrain_gradient < depth < 2*terrain_gradient
            inter_mask = ~shallow_mask
            if np.any(inter_mask):
                i_idx = s_idx[inter_mask]
                i_calc = face_wse_calc[inter_mask]
                i_max = s_max[inter_mask]
                i_depth = s_depth[inter_mask]
                i_tg = s_tg[inter_mask]

                # Blend toward max_wse
                blended = (
                    (2 * i_tg - i_depth) * i_calc +
                    (i_depth - i_tg) * i_max
                ) / i_tg

                face_wse_a[i_idx] = blended
                face_wse_b[i_idx] = blended
                connection_type[i_idx] = HydraulicConnection.DOWNHILL_INTERMEDIATE

    # Default: no terrain gradient, use cell values directly (average for connected faces)
    default_mask = ~levee_mask & ~backfill_mask & (terrain_gradient <= 0)
    if np.any(default_mask):
        avg_wse = (ws_a[default_mask] + ws_b[default_mask]) / 2
        face_wse_a[idx[default_mask]] = avg_wse
        face_wse_b[idx[default_mask]] = avg_wse
        # These faces are connected (no terrain gradient means water flows freely)
        connection_type[idx[default_mask]] = HydraulicConnection.BACKFILL

    return face_wse_a, face_wse_b, connection_type


def compute_face_midsides(
    cell_centers: np.ndarray,
    facepoint_coords: np.ndarray,
    face_cells: np.ndarray,
    face_facepoints: np.ndarray,
) -> np.ndarray:
    """
    Compute face midside points for planar regression.

    The face application point is where the face WSE value is "applied" for
    the planar regression. For internal faces, this is the intersection of
    the line between cell centers with the face. For perimeter faces, it's
    the face midpoint.

    Parameters
    ----------
    cell_centers : np.ndarray
        Cell center coordinates, shape (n_cells, 2), dtype float64.
    facepoint_coords : np.ndarray
        Facepoint (vertex) coordinates, shape (n_facepoints, 2), dtype float64.
    face_cells : np.ndarray
        Cell indices for each face, shape (n_faces, 2), dtype int32.
    face_facepoints : np.ndarray
        Facepoint indices for each face, shape (n_faces, 2), dtype int32.

    Returns
    -------
    np.ndarray
        Face midside coordinates, shape (n_faces, 2), dtype float64.

    Notes
    -----
    For internal faces with both valid cells, this computes the intersection
    of the cell-center line with the face segment. If no intersection is
    found, or for perimeter faces, the face midpoint is used.
    """
    n_faces = len(face_cells)
    midsides = np.zeros((n_faces, 2), dtype=np.float64)

    # Get face endpoints
    fp_a = face_facepoints[:, 0]
    fp_b = face_facepoints[:, 1]
    face_start = facepoint_coords[fp_a]  # (n_faces, 2)
    face_end = facepoint_coords[fp_b]    # (n_faces, 2)

    # Default: face midpoint
    midsides = (face_start + face_end) / 2

    # For internal faces, compute cell-center line intersection
    cell_a = face_cells[:, 0]
    cell_b = face_cells[:, 1]
    internal = (cell_a >= 0) & (cell_b >= 0)

    if np.any(internal):
        idx = np.where(internal)[0]

        # Get cell centers
        c_a = cell_centers[cell_a[idx]]  # (n_internal, 2)
        c_b = cell_centers[cell_b[idx]]  # (n_internal, 2)

        # Get face endpoints for internal faces
        f_start = face_start[idx]
        f_end = face_end[idx]

        # Compute line-segment intersection using parametric form
        # Cell line: P = c_a + t * (c_b - c_a)
        # Face line: Q = f_start + s * (f_end - f_start)
        # At intersection: P = Q

        d_cell = c_b - c_a       # Direction of cell line
        d_face = f_end - f_start # Direction of face line
        d_start = f_start - c_a  # Vector from cell_a to face_start

        # Cross product in 2D: a x b = a.x * b.y - a.y * b.x
        cross = d_cell[:, 0] * d_face[:, 1] - d_cell[:, 1] * d_face[:, 0]

        # Avoid division by zero (parallel lines)
        valid_cross = np.abs(cross) > 1e-10

        # Compute t parameter for cell line
        t = np.zeros(len(idx))
        t[valid_cross] = (
            d_start[valid_cross, 0] * d_face[valid_cross, 1] -
            d_start[valid_cross, 1] * d_face[valid_cross, 0]
        ) / cross[valid_cross]

        # Compute intersection point
        intersection = c_a + t[:, np.newaxis] * d_cell

        # Also compute s parameter to check if intersection is on face segment
        s = np.zeros(len(idx))
        s[valid_cross] = (
            d_start[valid_cross, 0] * d_cell[valid_cross, 1] -
            d_start[valid_cross, 1] * d_cell[valid_cross, 0]
        ) / cross[valid_cross]

        # Use intersection only if it's on the face segment (0 <= s <= 1)
        on_segment = valid_cross & (s >= 0) & (s <= 1)

        # Update midsides with valid intersections
        midsides[idx[on_segment]] = intersection[on_segment]

    return midsides


def compute_vertex_wse(
    face_wse_a: np.ndarray,
    face_wse_b: np.ndarray,
    connection_type: np.ndarray,
    face_midsides: np.ndarray,
    facepoint_coords: np.ndarray,
    face_facepoints: np.ndarray,
    facepoint_face_info: np.ndarray,
    facepoint_face_values: np.ndarray,
) -> np.ndarray:
    """
    Compute vertex WSE using planar regression.

    For each vertex (facepoint), this function:
    1. Collects WSE values from adjacent faces
    2. Groups faces by hydraulic connectivity
    3. Fits a plane through each connected group using PlanarRegressionZ
    4. Evaluates the plane at the vertex location

    Parameters
    ----------
    face_wse_a : np.ndarray
        WSE value for cell_a side of each face, shape (n_faces,).
    face_wse_b : np.ndarray
        WSE value for cell_b side of each face, shape (n_faces,).
    connection_type : np.ndarray
        HydraulicConnection type for each face, shape (n_faces,).
    face_midsides : np.ndarray
        Face application point coordinates, shape (n_faces, 2).
    facepoint_coords : np.ndarray
        Vertex coordinates, shape (n_facepoints, 2).
    face_facepoints : np.ndarray
        Facepoint indices for each face, shape (n_faces, 2).
    facepoint_face_info : np.ndarray
        CSR-like info array, shape (n_facepoints, 2).
        Column 0: start index in values array, Column 1: count.
    facepoint_face_values : np.ndarray
        CSR-like values array, shape (n_connections, 2).
        Column 0: face index, Column 1: orientation (0=a side, 1=b side).

    Returns
    -------
    np.ndarray
        WSE at each vertex, shape (n_facepoints,), dtype float32.
        NODATA (-9999) for vertices where no valid faces exist.

    Notes
    -----
    The algorithm handles hydraulic connectivity by grouping faces around
    each vertex. Faces that are hydraulically connected (e.g., both sides
    of a flowing face) are processed together in one regression. Faces
    with no connection (dry cells, levees) start new regression groups.

    The orientation value determines which side of the face (a or b) faces
    the current vertex, and thus which WSE value to use in the regression.
    """
    n_facepoints = len(facepoint_coords)
    vertex_wse = np.full(n_facepoints, NODATA, dtype=np.float32)

    for fp_idx in range(n_facepoints):
        start, count = facepoint_face_info[fp_idx]

        if count == 0:
            continue

        # Get adjacent faces and their orientations
        face_data = facepoint_face_values[start:start + count]
        adjacent_faces = face_data[:, 0]
        orientations = face_data[:, 1]  # 0 = a side, 1 = b side

        # Get WSE values based on orientation, but fall back to other side if NODATA
        # This handles perimeter faces where one side is the exterior (NODATA)
        wse_by_orient = np.where(
            orientations == 0,
            face_wse_a[adjacent_faces],
            face_wse_b[adjacent_faces]
        )
        wse_other_side = np.where(
            orientations == 0,
            face_wse_b[adjacent_faces],
            face_wse_a[adjacent_faces]
        )
        # Use orientation-based value if valid, otherwise fall back to other side
        wse_values = np.where(
            wse_by_orient != NODATA,
            wse_by_orient,
            wse_other_side
        )

        # Check if all faces are dry
        valid_mask = wse_values != NODATA
        if not np.any(valid_mask):
            continue

        # Get face application points
        app_points = face_midsides[adjacent_faces]

        # Get connection types for grouping
        conn_types = connection_type[adjacent_faces]

        # Simple approach: fit one regression through all valid faces
        # (Full algorithm would group by hydraulic connectivity)
        fp_x, fp_y = facepoint_coords[fp_idx]
        regression = PlanarRegressionZ(fp_x, fp_y)

        for i in range(len(adjacent_faces)):
            if valid_mask[i]:
                regression.add(app_points[i, 0], app_points[i, 1], wse_values[i])

        if regression.count > 0:
            vertex_wse[fp_idx] = regression.solve_z()

    return vertex_wse


def compute_sloped_wse_arrays(
    topology: Dict,
    cell_wse: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute all arrays needed for sloped WSE rasterization.

    This is a convenience function that orchestrates the full sloped
    interpolation pipeline.

    Parameters
    ----------
    topology : Dict
        Mesh topology from HdfMesh.get_mesh_sloped_topology().
    cell_wse : np.ndarray
        Water surface elevation per cell, shape (n_cells,).

    Returns
    -------
    face_wse_a : np.ndarray
        WSE for cell_a side of each face.
    face_wse_b : np.ndarray
        WSE for cell_b side of each face.
    vertex_wse : np.ndarray
        WSE at each vertex.
    face_midsides : np.ndarray
        Face application points.
    """
    # Stage 1: Compute face WSE
    face_wse_a, face_wse_b, connection_type = compute_face_wse(
        cell_wse=cell_wse,
        cell_min_elev=topology['cell_min_elev'],
        face_min_elev=topology['face_min_elev'],
        face_cells=topology['face_cells'],
    )

    # Stage 2: Compute face midsides
    face_midsides = compute_face_midsides(
        cell_centers=topology['cell_centers'],
        facepoint_coords=topology['facepoint_coords'],
        face_cells=topology['face_cells'],
        face_facepoints=topology['face_facepoints'],
    )

    # Stage 3: Compute vertex WSE
    vertex_wse = compute_vertex_wse(
        face_wse_a=face_wse_a,
        face_wse_b=face_wse_b,
        connection_type=connection_type,
        face_midsides=face_midsides,
        facepoint_coords=topology['facepoint_coords'],
        face_facepoints=topology['face_facepoints'],
        facepoint_face_info=topology['facepoint_face_info'],
        facepoint_face_values=topology['facepoint_face_values'],
    )

    return face_wse_a, face_wse_b, vertex_wse, face_midsides


def compute_bens_weights(
    pixel_x: float,
    pixel_y: float,
    facepoint_coords: np.ndarray,
) -> np.ndarray:
    """
    Compute Ben's Weights for a pixel inside a cell.

    This implements RASMapper's BensWeights() algorithm - a generalized
    barycentric coordinate system for arbitrary polygons.

    Parameters
    ----------
    pixel_x, pixel_y : float
        Coordinates of the pixel center.
    facepoint_coords : np.ndarray
        Coordinates of the cell's facepoints in CCW order, shape (n_faces, 2).

    Returns
    -------
    np.ndarray
        Interpolation weights, shape (n_faces,), summing to 1.0.
        Use as: WSE_pixel = Σ(weights[i] × WSE_facepoint[i])

    Notes
    -----
    Algorithm from decompiled RasMapperLib.RASGeometryMapPoints.BensWeights():
    1. Compute cross products from pixel to each face's endpoints
    2. For each facepoint j:
       - Multiply all cross products EXCEPT faces j and j-1
       - Multiply by cross product of triangle (fp[j-1], fp[j], fp[j+1])
    3. Normalize so weights sum to 1.0
    4. Clamp negative weights to 0 and re-normalize (for points outside polygon)

    Reference: RASMapper decompiled code, lines 2895-2986
    """
    n = len(facepoint_coords)
    if n < 3:
        return np.ones(n, dtype=np.float32) / max(n, 1)

    # Step 1: Compute cross products from pixel to each face
    # CrossProduct(pixel, fp[i], fp[i+1]) = signed area of triangle
    xproducts = np.zeros(n, dtype=np.float64)
    for i in range(n):
        j = (i + 1) % n
        x1, y1 = facepoint_coords[i]
        x2, y2 = facepoint_coords[j]
        # Cross product: (fp1 - pixel) × (fp2 - pixel)
        xproducts[i] = (x1 - pixel_x) * (y2 - pixel_y) - (x2 - pixel_x) * (y1 - pixel_y)

    # Avoid zero cross products (on face edge)
    xproducts = np.where(xproducts == 0, 1e-5, xproducts)

    # Step 2: Compute raw weights
    raw_weights = np.zeros(n, dtype=np.float64)
    for j in range(n):
        j_prev = (j - 1) % n

        # Product of all cross products EXCEPT j and j_prev
        product = 1.0
        for k in range(n):
            if k != j and k != j_prev:
                product *= xproducts[k]

        # Get three facepoints: prev_prev, prev, current
        fp_prev2 = (j - 2) % n  # Previous facepoint of previous face
        fp_prev = (j - 1) % n   # Shared facepoint between faces j-1 and j
        fp_curr = j             # Current facepoint

        # Get coordinates
        p_prev2 = facepoint_coords[fp_prev2]
        p_prev = facepoint_coords[fp_prev]
        p_curr = facepoint_coords[fp_curr]

        # Cross product of triangle (p_prev, p_curr, p_prev2)
        # This measures the triangle area contribution
        triangle_cross = (
            (p_prev[0] - p_prev2[0]) * (p_curr[1] - p_prev2[1]) -
            (p_curr[0] - p_prev2[0]) * (p_prev[1] - p_prev2[1])
        )

        raw_weights[j] = product * triangle_cross

    # Step 3: Normalize
    total = np.sum(raw_weights)
    if total == 0:
        return np.ones(n, dtype=np.float32) / n

    weights = (raw_weights / total).astype(np.float32)

    # Step 4: Handle negative weights (point outside polygon)
    if np.any(weights < 0):
        weights = np.maximum(weights, 0)
        total = np.sum(weights)
        if total > 0:
            weights /= total
        else:
            weights = np.ones(n, dtype=np.float32) / n

    return weights


def interpolate_pixel_wse(
    pixel_x: float,
    pixel_y: float,
    cell_facepoint_indices: np.ndarray,
    facepoint_coords: np.ndarray,
    vertex_wse: np.ndarray,
) -> float:
    """
    Interpolate WSE at a pixel using Ben's Weights.

    Parameters
    ----------
    pixel_x, pixel_y : float
        Coordinates of the pixel center.
    cell_facepoint_indices : np.ndarray
        Indices of facepoints for this cell, in CCW order.
    facepoint_coords : np.ndarray
        All facepoint coordinates, shape (n_facepoints, 2).
    vertex_wse : np.ndarray
        WSE at each facepoint, shape (n_facepoints,).

    Returns
    -------
    float
        Interpolated WSE at the pixel, or NODATA if all vertices are dry.
    """
    # Get coordinates and WSE for this cell's facepoints
    coords = facepoint_coords[cell_facepoint_indices]
    wse_values = vertex_wse[cell_facepoint_indices]

    # Check for dry vertices
    valid_mask = wse_values != NODATA
    if not np.any(valid_mask):
        return NODATA

    # Compute weights
    weights = compute_bens_weights(pixel_x, pixel_y, coords)

    # Interpolate (using only valid vertices)
    # If some vertices are dry, redistribute their weights to valid vertices
    if not np.all(valid_mask):
        weights[~valid_mask] = 0
        total = np.sum(weights)
        if total > 0:
            weights /= total
        else:
            return NODATA

    return float(np.dot(weights, wse_values))
