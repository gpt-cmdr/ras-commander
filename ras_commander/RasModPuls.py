"""
RasModPuls - Modified Puls Routing Extraction from HEC-RAS 2D Models

.. note::
    **BETA**: This module is currently beta and has not been validated in production.
    The workflow, API, and outputs may change in future releases.
    Feedback from third-party users is welcome — please open an issue at
    https://github.com/gpt-cmdr/ras-commander/issues

Automates the Region 2 (Freese & Nichols) methodology for extracting
storage-outflow (S-Q) relationships from 2D HEC-RAS stepped-hydrograph
simulations into HEC-HMS paired data tables.

Workflow:
    1. Write a stepped inflow hydrograph to a HEC-RAS unsteady file
    2. Execute the 2D HEC-RAS model
    3. Extract S-Q table from HDF results at plateau timesteps
    4. Export to HEC-HMS Modified Puls routing table

Reference Methodology:
    Region 2 (Freese & Nichols) raw_operations_region2.txt, Section 3.8

Example:
    >>> from ras_commander import RasModPuls, init_ras_project, RasCmdr
    >>> from shapely.geometry import LineString
    >>>
    >>> init_ras_project("path/to/project", "7.0")
    >>> flows = RasModPuls.write_stepped_hydrograph("project.u01", flows=[500, 1000, 2000, 5000])
    >>> RasCmdr.compute_plan("01")
    >>> profile_line = LineString([(x1, y1), (x2, y2)])
    >>> sq_df = RasModPuls.extract_storage_outflow("project.p01.hdf", profile_line, "01")
    >>> n = RasModPuls.compute_subreach_count(travel_time_hours=6.0)
"""

import math
import logging
from datetime import timedelta
from pathlib import Path
from typing import List, Optional, Union, Any

import h5py
import numpy as np
import pandas as pd

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)


class RasModPuls:
    """
    Modified Puls routing extraction from HEC-RAS 2D models.

    All methods are static — do not instantiate this class.

    Key Methods:
        - write_stepped_hydrograph(): Write stepped inflow hydrograph to .u## file
        - extract_storage_outflow(): Extract S-Q table from stepped simulation HDF
        - compute_subreach_count(): Compute Modified Puls subreach count (Region 2 formula)
        - add_reference_lines_from_bc_lines(): Write reference lines to geometry HDF from BC lines
    """

    # -------------------------------------------------------------------------
    # Primary Utility: Subreach Count
    # -------------------------------------------------------------------------

    @staticmethod
    @log_call
    def compute_subreach_count(
        travel_time_hours: float,
        dt_hours: float = 1.0,
        safety_factor: float = 1.5,
        max_subreaches: int = 30,
        min_subreaches: int = 1,
    ) -> int:
        """
        Compute Modified Puls subreach count per Region 2 methodology.

        Formula: n = ceil(travel_time / dt * safety_factor), capped at max_subreaches.

        The safety factor provides additional routing diffusion to prevent
        numerical instability. For the 10-year event, travel time equals
        the hydrograph timing from the 2D routing simulation.

        Args:
            travel_time_hours: Travel time of the ~10-yr event through the reach (hours)
            dt_hours: HEC-HMS routing time step (hours, default 1.0)
            safety_factor: Multiplier on travel time / dt (default 1.5 per R2 methodology)
            max_subreaches: Maximum allowed subreaches (default 30)
            min_subreaches: Minimum allowed subreaches (default 1)

        Returns:
            int: Number of Modified Puls subreaches

        Example:
            >>> n = RasModPuls.compute_subreach_count(travel_time_hours=6.0, dt_hours=1.0)
            >>> # n = ceil(6.0 / 1.0 * 1.5) = ceil(9.0) = 9
        """
        if travel_time_hours <= 0:
            raise ValueError(f"travel_time_hours must be positive, got {travel_time_hours}")
        if dt_hours <= 0:
            raise ValueError(f"dt_hours must be positive, got {dt_hours}")

        n = math.ceil(travel_time_hours / dt_hours * safety_factor)
        n = max(min_subreaches, min(max_subreaches, n))
        logger.debug(
            "Subreach count: n=%s (travel_time=%sh, dt=%sh, factor=%s)",
            n,
            travel_time_hours,
            dt_hours,
            safety_factor,
        )
        return n

    # -------------------------------------------------------------------------
    # Step 1: Write Stepped Hydrograph
    # -------------------------------------------------------------------------

    @staticmethod
    @log_call
    def write_stepped_hydrograph(
        unsteady_file: Union[str, Path],
        flows: Optional[List[float]] = None,
        min_flow: Optional[float] = None,
        max_flow: Optional[float] = None,
        n_steps: Optional[int] = None,
        step_duration_hours: float = 24.0,
        warmup_flow: Optional[float] = None,
        warmup_duration_hours: float = 6.0,
        log_spaced: bool = True,
        bc_type: str = "Flow Hydrograph",
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> List[float]:
        """
        Write a stepped inflow hydrograph to a HEC-RAS unsteady flow file.

        Supports two input modes:
          - Explicit list of flows (``flows`` parameter)
          - Generated log-spaced or linear steps (``min_flow``, ``max_flow``, ``n_steps``)

        At each step, the flow is held constant for ``step_duration_hours`` so the
        2D model reaches steady state before the next step. The storage-outflow pair
        is extracted at the END of each step (just before the next increase).

        Args:
            unsteady_file: Path to unsteady flow file (.u##) or unsteady number (e.g., "01")
            flows: Explicit list of flow values (cfs) in ascending order.
                   Mutually exclusive with min_flow/max_flow/n_steps.
            min_flow: Minimum flow value for auto-generation (requires max_flow and n_steps)
            max_flow: Maximum flow value for auto-generation (requires min_flow and n_steps)
            n_steps: Number of flow steps for auto-generation (requires min_flow and max_flow)
            step_duration_hours: Duration each flow step is held constant (default 24 hours)
            warmup_flow: Optional low-flow warmup step before first real step.
                         If None, no warmup step is added.
            warmup_duration_hours: Duration of warmup step (default 6 hours)
            log_spaced: If True, auto-generated steps are log-spaced (default True).
                        Linear spacing if False.
            bc_type: Boundary condition type (default "Flow Hydrograph").
                     See RasUnsteady.set_boundary_inline_hydrograph for options.
            river: River name for locating BC in file (None = first match)
            reach: Reach name for locating BC in file (None = first match)
            station: Station for locating BC in file (None = first match)
            ras_object: RasPrj object (uses global ras if None)

        Returns:
            List[float]: Flow values written (in order, not including warmup)

        Raises:
            ValueError: If neither ``flows`` nor ``min_flow``/``max_flow``/``n_steps`` provided
            ValueError: If flow values are not in ascending order
        """
        from .RasUnsteady import RasUnsteady

        # ---- Resolve flow list -----------------------------------------------
        if flows is not None:
            if any(f <= 0 for f in flows):
                raise ValueError("All flow values must be positive")
            flow_list = list(flows)
        elif min_flow is not None and max_flow is not None and n_steps is not None:
            if min_flow <= 0 or max_flow <= min_flow:
                raise ValueError("Require min_flow > 0 and max_flow > min_flow")
            if n_steps < 2:
                raise ValueError("n_steps must be >= 2")
            if log_spaced:
                flow_list = list(np.geomspace(min_flow, max_flow, n_steps))
            else:
                flow_list = list(np.linspace(min_flow, max_flow, n_steps))
        else:
            raise ValueError(
                "Provide either 'flows' or all of 'min_flow', 'max_flow', 'n_steps'"
            )

        logger.debug(
            "Preparing stepped hydrograph: steps=%s, flows=%s, step_duration=%sh, "
            "warmup_flow=%s, warmup_duration=%sh, target=%s, bc_type=%s, "
            "river=%s, reach=%s, station=%s",
            len(flow_list),
            [round(f, 1) for f in flow_list],
            step_duration_hours,
            warmup_flow,
            warmup_duration_hours,
            unsteady_file,
            bc_type,
            river,
            reach,
            station,
        )

        # ---- Build hydrograph DataFrame --------------------------------------
        # Use uniform 1-hour resolution so set_boundary_inline_hydrograph
        # correctly detects interval as 1HOUR (it reads hours[1] - hours[0]).
        # HEC-RAS handles constant-value blocks fine at any time step interval.
        hours: List[float] = []
        values: List[float] = []

        # Warmup phase — each integer hour gets its own row
        if warmup_flow is not None:
            n_warmup = max(1, round(warmup_duration_hours))
            for h in range(n_warmup):
                hours.append(float(h))
                values.append(float(warmup_flow))

        # Step phases — each integer hour within each step gets its own row
        current_hour = float(len(hours))
        for flow in flow_list:
            n_step = max(1, round(step_duration_hours))
            for h in range(n_step):
                hours.append(current_hour + h)
                values.append(float(flow))
            current_hour += n_step

        # Final closing point
        hours.append(current_hour)
        values.append(float(flow_list[-1]))

        hydro_df = pd.DataFrame({"hour": hours, "value": values})

        # ---- Write to unsteady file ------------------------------------------
        RasUnsteady.set_boundary_inline_hydrograph(
            unsteady_file=unsteady_file,
            hydrograph_df=hydro_df,
            bc_type=bc_type,
            river=river,
            reach=reach,
            station=station,
            ras_object=ras_object,
        )

        logger.info(
            "Stepped hydrograph written: %s steps over %.1f hours",
            len(flow_list),
            current_hour,
        )
        return flow_list

    # -------------------------------------------------------------------------
    # Step 2: Extract Storage-Outflow Table
    # -------------------------------------------------------------------------

    @staticmethod
    @log_call
    def extract_storage_outflow(
        plan_hdf_path: Union[str, Path],
        downstream_profile_line: Any,
        plan_number: str,
        step_duration_hours: Optional[float] = None,
        warmup_duration_hours: float = 6.0,
        n_steps: Optional[int] = None,
        ras_object: Optional[Any] = None,
        flow_area_name: Optional[str] = None,
        n_rows: int = 15,
        distance_threshold: float = 10.0,
        angle_threshold: float = 60.0,
    ) -> pd.DataFrame:
        """
        Extract Modified Puls storage-outflow table from a stepped hydrograph simulation.

        At each plateau timestep (end of each step):
          - **Q** = sum of ``Face Flow`` values across downstream transect faces
          - **S** = total water volume (sum of cell depth × cell area / 43560) in acre-feet

        The plateau timestep is the LAST timestep of each step, captured just before
        the next flow increase. Plateau detection uses the ``step_duration_hours``
        parameter; if not provided, auto-detection is used from the Face Flow series.

        Args:
            plan_hdf_path: Path to 2D unsteady plan HDF file or plan number (e.g. "01")
            downstream_profile_line: GeoDataFrame or Shapely LineString / MultiLineString
                                     defining the Q extraction transect. Should cross the
                                     mesh perpendicularly near the downstream BC line.
            plan_number: Plan number (e.g., "01") — used to resolve HDF path if needed
            step_duration_hours: Duration of each stepped flow plateau (hours).
                                  If None, auto-detected from HDF time series.
            warmup_duration_hours: Duration of warmup step before first real step (hours,
                                   default 6.0). Set to 0 if no warmup was used.
            n_steps: Number of flow steps. If None, auto-detected from HDF time series.
            ras_object: RasPrj object (uses global ras if None)
            flow_area_name: 2D mesh area name. Auto-detected if only one mesh exists.
            n_rows: Target number of rows in output S-Q table (default 15).
                    Output is resampled/interpolated to this count if needed.
            distance_threshold: Max distance (model units) from profile line to include a face (default 10)
            angle_threshold: Max angle (degrees) between face normal and profile line to include (default 60)

        Returns:
            pd.DataFrame: S-Q table with columns:
                          - ``storage_acft``: Water storage in acre-feet
                          - ``outflow_cfs``: Outflow in cfs
                          Sorted ascending by outflow_cfs. Always includes (0, 0) as first row.

        Raises:
            ValueError: If the mesh or Face Flow data cannot be found
            ValueError: If fewer than 2 plateau timesteps are detected
        """
        from .hdf.HdfMesh import HdfMesh
        from .hdf.HdfBase import HdfBase

        # ---- Resolve HDF path -----------------------------------------------
        hdf_path = Path(plan_hdf_path) if not str(plan_hdf_path).endswith('.hdf') else Path(plan_hdf_path)
        if not hdf_path.suffix:
            # Looks like a plan number — resolve via ras_object
            hdf_path = RasModPuls._resolve_hdf_path(plan_number, ras_object)
        elif not hdf_path.is_absolute() or not hdf_path.exists():
            # Try resolving as plan number
            try:
                hdf_path = RasModPuls._resolve_hdf_path(str(plan_hdf_path), ras_object)
            except Exception:
                pass

        if not hdf_path.exists():
            raise FileNotFoundError(f"Plan HDF not found: {hdf_path}")

        logger.debug("Extracting S-Q table from %s", hdf_path)

        # ---- Get downstream profile line faces ------------------------------
        geom_hdf = RasModPuls._get_geom_hdf_path(hdf_path, plan_number, ras_object)

        cell_faces_gdf = HdfMesh.get_mesh_cell_faces(
            geom_hdf if geom_hdf else hdf_path
        )

        if cell_faces_gdf is None or len(cell_faces_gdf) == 0:
            raise ValueError("No mesh cell faces found in HDF file")

        # Resolve flow area name
        if flow_area_name is None:
            mesh_names = cell_faces_gdf['mesh_name'].unique().tolist()
            if len(mesh_names) == 1:
                flow_area_name = mesh_names[0]
            else:
                raise ValueError(
                    f"Multiple mesh areas found: {mesh_names}. "
                    "Specify flow_area_name parameter."
                )

        mesh_faces_gdf = cell_faces_gdf[cell_faces_gdf['mesh_name'] == flow_area_name].copy()

        # Extract the profile line geometry
        profile_geom = downstream_profile_line
        if hasattr(profile_geom, 'geometry'):
            # It's a GeoDataFrame
            from shapely.ops import unary_union
            profile_geom = unary_union(profile_geom.geometry.values)

        # Get faces along the downstream profile line
        profile_faces = HdfMesh.get_faces_along_profile_line(
            profile_line=profile_geom,
            cell_faces_gdf=mesh_faces_gdf,
            distance_threshold=distance_threshold,
            angle_threshold=angle_threshold,
        )

        if profile_faces is None or len(profile_faces) == 0:
            raise ValueError(
                f"No mesh faces found along downstream profile line. "
                f"Check distance_threshold ({distance_threshold}) and angle_threshold ({angle_threshold})."
            )

        face_ids = profile_faces['face_id'].tolist()
        logger.debug("Found %s faces along downstream profile line", len(face_ids))

        # ---- Open HDF and extract time series --------------------------------
        with h5py.File(hdf_path, 'r') as hdf:
            # Timestamps
            timestamps = HdfBase.get_unsteady_timestamps(hdf)
            n_timesteps = len(timestamps)

            if n_timesteps < 2:
                raise ValueError(f"HDF has only {n_timesteps} timesteps — too few for S-Q extraction")

            # Face Flow
            face_flow_path = (
                f"Results/Unsteady/Output/Output Blocks/Base Output/"
                f"Unsteady Time Series/2D Flow Areas/{flow_area_name}/Face Flow"
            )
            if face_flow_path not in hdf:
                raise ValueError(
                    f"Face Flow dataset not found at: {face_flow_path}\n"
                    f"Ensure the plan outputs face flows for mesh '{flow_area_name}'."
                )

            face_flow_all = hdf[face_flow_path][:]  # shape: [n_timesteps, n_faces]
            face_flow_transect = face_flow_all[:, face_ids]  # [n_timesteps, n_profile_faces]

            # Cell Depth time series — derived from Water Surface minus terrain elevation.
            # HEC-RAS 6.x does not reliably output a standalone "Depth" dataset even when
            # "Cell Depth" is checked in the plan output settings.  Computing depth from
            # Water Surface (always present when face flow is enabled) and the static
            # Cells Minimum Elevation (geometry) is equivalent and more robust.
            ws_path = (
                f"Results/Unsteady/Output/Output Blocks/Base Output/"
                f"Unsteady Time Series/2D Flow Areas/{flow_area_name}/Water Surface"
            )
            if ws_path not in hdf:
                raise ValueError(
                    f"Water Surface dataset not found at: {ws_path}\n"
                    f"Ensure the plan outputs water surface for mesh '{flow_area_name}'."
                )
            ws_all = hdf[ws_path][:]  # shape: [n_timesteps, n_cells]

            elev_path = f"Geometry/2D Flow Areas/{flow_area_name}/Cells Minimum Elevation"
            if elev_path not in hdf:
                raise ValueError(
                    f"Cells Minimum Elevation not found at: {elev_path}\n"
                    f"Verify the geometry HDF contains 2D flow area '{flow_area_name}'."
                )
            cell_min_elev = hdf[elev_path][:]  # shape: [n_cells]

            # depth = WS - terrain, clipped to zero for dry cells
            depth_all = np.maximum(ws_all - cell_min_elev[np.newaxis, :], 0.0)

            # Cell surface areas [n_cells] in sq ft
            cell_area_path = f"Geometry/2D Flow Areas/{flow_area_name}/Cells Surface Area"
            if cell_area_path not in hdf:
                raise ValueError(f"Cell surface area dataset not found: {cell_area_path}")

            cell_areas = hdf[cell_area_path][:]  # sq ft, one per cell

        # ---- Detect plateau timesteps ----------------------------------------
        plateau_indices = RasModPuls._detect_plateau_indices(
            timestamps=timestamps,
            step_duration_hours=step_duration_hours,
            warmup_duration_hours=warmup_duration_hours,
            n_steps=n_steps,
            face_flow_transect=face_flow_transect,
        )

        if len(plateau_indices) < 2:
            raise ValueError(
                f"Only {len(plateau_indices)} plateau timestep(s) detected. "
                "Verify step_duration_hours matches the written hydrograph."
            )

        logger.debug("Detected %s plateau timesteps", len(plateau_indices))

        # ---- Extract Q and S at each plateau ---------------------------------
        rows = []
        for idx in plateau_indices:
            # Q: total flow across transect (sum of face flows, handle sign)
            q_raw = face_flow_transect[idx, :]
            q = float(np.sum(np.abs(q_raw)))  # cfs

            # S: volume in acre-feet
            depths_at_t = depth_all[idx, :]  # ft, one per cell
            wet_mask = depths_at_t > 0
            vol_cuft = float(np.sum(depths_at_t[wet_mask] * cell_areas[wet_mask]))
            s = vol_cuft / 43560.0  # acre-feet

            rows.append({"outflow_cfs": q, "storage_acft": s})

        sq_df = pd.DataFrame(rows)

        # ---- Quality cleanup -------------------------------------------------
        sq_df = RasModPuls._clean_sq_table(sq_df, n_rows=n_rows)

        logger.info(
            "S-Q extraction complete: %s rows, %s plateau timesteps, %s faces, "
            "Q range: %.0f - %.0f cfs, S range: %.1f - %.1f ac-ft",
            len(sq_df),
            len(plateau_indices),
            len(face_ids),
            sq_df['outflow_cfs'].min(),
            sq_df['outflow_cfs'].max(),
            sq_df['storage_acft'].min(),
            sq_df['storage_acft'].max(),
        )
        return sq_df

    # -------------------------------------------------------------------------
    # Optional: Reference Lines from BC Lines
    # -------------------------------------------------------------------------

    @staticmethod
    @log_call
    def add_reference_lines_from_bc_lines(
        geom_hdf_path: Union[str, Path],
        bc_line_names: List[str],
        mesh_name: Optional[str] = None,
        distance_threshold: float = 10.0,
        angle_threshold: float = 60.0,
    ) -> int:
        """
        Add reference lines to a geometry HDF by tracing mesh faces along BC lines.

        This enables native HEC-RAS reference line output for the locations that
        match the BC lines. Not required for ``extract_storage_outflow()``, which
        reads face flows directly.

        Implementation:
            1. Get BC line geometries from ``HdfBndry.get_bc_lines()``
            2. Get mesh cell faces from ``HdfMesh.get_mesh_cell_faces()``
            3. For each BC line, find faces along it with ``HdfMesh.get_faces_along_profile_line()``
            4. Combine faces to linestring with ``HdfMesh.combine_faces_to_linestring()``
            5. Write to ``Geometry/Reference Lines`` in geometry HDF

        Args:
            geom_hdf_path: Path to geometry HDF file (.g##.hdf)
            bc_line_names: List of BC line names to convert to reference lines
            mesh_name: 2D mesh area name (auto-detect if only one mesh exists)
            distance_threshold: Max distance (model units) from BC line to face (default 10)
            angle_threshold: Max angle (degrees) between face normal and BC line (default 60)

        Returns:
            int: Number of reference lines successfully written

        Note:
            Modifies the geometry HDF file in-place. Consider making a backup first.
        """
        from .hdf.HdfBndry import HdfBndry
        from .hdf.HdfMesh import HdfMesh
        from shapely.geometry import mapping

        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")

        # Get BC lines and mesh faces
        bc_lines_gdf = HdfBndry.get_bc_lines(geom_hdf_path)
        cell_faces_gdf = HdfMesh.get_mesh_cell_faces(geom_hdf_path)

        if bc_lines_gdf is None or len(bc_lines_gdf) == 0:
            logger.warning("No BC lines found in geometry HDF")
            return 0

        # Resolve mesh name
        if mesh_name is None:
            mesh_names = cell_faces_gdf['mesh_name'].unique().tolist()
            if len(mesh_names) == 1:
                mesh_name = mesh_names[0]
            else:
                raise ValueError(
                    f"Multiple mesh areas found: {mesh_names}. Specify mesh_name parameter."
                )

        mesh_faces_gdf = cell_faces_gdf[cell_faces_gdf['mesh_name'] == mesh_name].copy()

        # Check which column holds BC names
        name_col = 'Name' if 'Name' in bc_lines_gdf.columns else bc_lines_gdf.columns[0]

        written = 0
        ref_line_data = []
        creation_warning_logged = False

        for bc_name in bc_line_names:
            bc_rows = bc_lines_gdf[bc_lines_gdf[name_col] == bc_name]
            if len(bc_rows) == 0:
                logger.warning(f"BC line '{bc_name}' not found in geometry HDF")
                creation_warning_logged = True
                continue

            bc_geom = bc_rows.iloc[0].geometry

            # Find faces along this BC line
            profile_faces = HdfMesh.get_faces_along_profile_line(
                profile_line=bc_geom,
                cell_faces_gdf=mesh_faces_gdf,
                distance_threshold=distance_threshold,
                angle_threshold=angle_threshold,
            )

            if profile_faces is None or len(profile_faces) == 0:
                logger.warning(f"No faces found along BC line '{bc_name}'")
                creation_warning_logged = True
                continue

            # Combine faces to linestring
            ref_linestring = HdfMesh.combine_faces_to_linestring(profile_faces)
            if ref_linestring is None:
                logger.warning(f"Could not combine faces for BC line '{bc_name}'")
                creation_warning_logged = True
                continue

            ref_line_data.append({
                'name': bc_name,
                'geometry': ref_linestring,
            })
            logger.debug(
                "Built reference line for BC '%s': %s faces",
                bc_name,
                len(profile_faces),
            )

        if not ref_line_data:
            if not creation_warning_logged:
                logger.warning("No reference lines created")
            else:
                logger.debug("No reference lines created")
            return 0

        # Write to geometry HDF
        written = RasModPuls._write_reference_lines_to_hdf(geom_hdf_path, ref_line_data, mesh_name)
        logger.info(f"Wrote {written} reference line(s) to geometry HDF")
        return written

    # -------------------------------------------------------------------------
    # Private Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _resolve_hdf_path(plan_number: str, ras_object: Optional[Any]) -> Path:
        """Resolve plan HDF path from plan number via ras_object."""
        try:
            from . import ras as global_ras
            _ras = ras_object if ras_object is not None else global_ras
            plan_num = plan_number.lstrip('p')
            plan_row = _ras.plan_df[_ras.plan_df['plan_number'] == plan_num]
            if len(plan_row) == 0:
                raise ValueError(f"Plan {plan_number} not found in project")
            hdf_path = plan_row['HDF_Results_Path'].iloc[0]
            if hdf_path is None or (hasattr(hdf_path, '__class__') and hdf_path != hdf_path):
                raise ValueError(f"Plan {plan_number} has not been executed (no HDF file)")
            return Path(str(hdf_path))
        except Exception as e:
            raise ValueError(f"Cannot resolve HDF path for plan {plan_number}: {e}") from e

    @staticmethod
    def _get_geom_hdf_path(
        plan_hdf_path: Path,
        plan_number: str,
        ras_object: Optional[Any],
    ) -> Optional[Path]:
        """
        Try to find the geometry HDF path for face geometry (preferred source).
        Falls back to plan HDF if geometry HDF not available.
        """
        try:
            from . import ras as global_ras
            _ras = ras_object if ras_object is not None else global_ras
            plan_num = plan_number.lstrip('p') if plan_number else None
            if plan_num:
                plan_row = _ras.plan_df[_ras.plan_df['plan_number'] == plan_num]
                if len(plan_row) > 0:
                    geom_num = plan_row['Geom File'].iloc[0]
                    geom_row = _ras.geom_df[_ras.geom_df['geom_number'] == geom_num]
                    if len(geom_row) > 0:
                        geom_file = Path(str(geom_row['full_path'].iloc[0]))
                        geom_hdf = Path(str(geom_file) + '.hdf')
                        if geom_hdf.exists():
                            return geom_hdf
        except Exception:
            pass
        return None

    @staticmethod
    def _detect_plateau_indices(
        timestamps: list,
        step_duration_hours: Optional[float],
        warmup_duration_hours: float,
        n_steps: Optional[int],
        face_flow_transect: np.ndarray,
    ) -> List[int]:
        """
        Detect the HDF timestep indices at the end of each flow plateau.

        If step_duration_hours is provided, compute plateau times analytically.
        Otherwise, auto-detect from the Face Flow time series by finding
        the last index before each major flow increase.

        Returns:
            List[int]: Timestep indices (one per plateau)
        """
        start_dt = timestamps[0]

        if step_duration_hours is not None:
            # Analytical: plateau ends at warmup + step_i * step_duration
            plateau_indices = []
            step_idx = 0
            plateau_hour = warmup_duration_hours + step_duration_hours  # end of step 1

            while True:
                plateau_dt = start_dt + timedelta(hours=plateau_hour)
                if plateau_dt > timestamps[-1]:
                    break

                # Find closest timestep index
                diffs = [abs((t - plateau_dt).total_seconds()) for t in timestamps]
                closest = int(np.argmin(diffs))
                # Use the timestep just BEFORE the plateau target (end of step = last steady index)
                # Go back one step to be safe (capture the last truly "steady" output)
                idx = max(0, closest - 1)
                if idx not in plateau_indices:
                    plateau_indices.append(idx)

                step_idx += 1
                plateau_hour += step_duration_hours

                if n_steps is not None and step_idx >= n_steps:
                    break

            return plateau_indices

        else:
            # Auto-detect from total flow magnitude changes
            total_q = np.abs(face_flow_transect).sum(axis=1)  # [n_timesteps]

            # Smooth to reduce noise
            from scipy.signal import savgol_filter
            if len(total_q) > 15:
                try:
                    smooth_q = savgol_filter(total_q, min(11, len(total_q) // 3 * 2 + 1), 3)
                except Exception:
                    smooth_q = total_q
            else:
                smooth_q = total_q

            # Find indices where flow increases significantly (> 5% jump)
            dq = np.diff(smooth_q)
            max_q = smooth_q.max()
            if max_q == 0:
                raise ValueError("Face flow is zero for all timesteps — check model outputs")

            jump_threshold = max_q * 0.05
            jump_indices = np.where(dq > jump_threshold)[0]

            # Plateau end = index just before each jump (or last index for final step)
            plateau_indices = []
            prev = 0
            for ji in jump_indices:
                if ji > prev:
                    plateau_indices.append(int(ji))
                prev = ji + 1

            # Include final plateau end
            plateau_indices.append(len(total_q) - 1)

            return plateau_indices

    @staticmethod
    def _clean_sq_table(sq_df: pd.DataFrame, n_rows: int) -> pd.DataFrame:
        """
        Clean and resample the raw S-Q table.

        Steps:
            1. Ensure (0, 0) origin row
            2. Sort by outflow_cfs ascending
            3. Remove duplicate Q values (keep highest S)
            4. Enforce monotonically increasing S
            5. Resample to n_rows if needed
        """
        # Add origin
        origin = pd.DataFrame([{"outflow_cfs": 0.0, "storage_acft": 0.0}])
        sq_df = pd.concat([origin, sq_df], ignore_index=True)

        # Sort by Q
        sq_df = sq_df.sort_values("outflow_cfs").reset_index(drop=True)

        # Remove duplicates (keep max S for each Q)
        sq_df = sq_df.groupby("outflow_cfs", as_index=False)["storage_acft"].max()

        # Enforce monotonically increasing S
        sq_df = sq_df.sort_values("outflow_cfs").reset_index(drop=True)
        s_vals = sq_df["storage_acft"].values.copy()
        for i in range(1, len(s_vals)):
            if s_vals[i] <= s_vals[i - 1]:
                s_vals[i] = s_vals[i - 1] * 1.001  # tiny nudge
        sq_df["storage_acft"] = s_vals

        # Resample to n_rows if needed
        if len(sq_df) > n_rows:
            # Interpolate at n_rows evenly spaced Q values
            q_interp = np.linspace(sq_df["outflow_cfs"].min(), sq_df["outflow_cfs"].max(), n_rows)
            s_interp = np.interp(q_interp, sq_df["outflow_cfs"].values, sq_df["storage_acft"].values)
            sq_df = pd.DataFrame({"outflow_cfs": q_interp, "storage_acft": s_interp})

        return sq_df[["storage_acft", "outflow_cfs"]].reset_index(drop=True)

    @staticmethod
    def _write_reference_lines_to_hdf(
        geom_hdf_path: Path,
        ref_line_data: list,
        mesh_name: str,
    ) -> int:
        """
        Write reference line geometries to the geometry HDF file.

        Reference lines are stored at 'Geometry/Reference Lines' as a dataset
        of coordinate arrays, similar to BC lines.
        """
        import json

        written = 0
        try:
            with h5py.File(geom_hdf_path, 'r+') as hdf:
                ref_group_path = "Geometry/Reference Lines"

                # Create group if not exists
                if ref_group_path not in hdf:
                    ref_group = hdf.create_group(ref_group_path)
                else:
                    ref_group = hdf[ref_group_path]

                for item in ref_line_data:
                    name = item['name']
                    geom = item['geometry']

                    # Get coordinates from LineString
                    if hasattr(geom, 'coords'):
                        coords = np.array(list(geom.coords), dtype=np.float64)
                    else:
                        logger.warning(f"Cannot extract coords from geometry for '{name}'")
                        continue

                    # Store as dataset named after the reference line
                    ds_name = f"Points/{name}"
                    if ds_name in ref_group:
                        del ref_group[ds_name]

                    ref_group.create_dataset(ds_name, data=coords)

                    # Store attributes
                    if f"Attributes/{name}" in ref_group:
                        del ref_group[f"Attributes/{name}"]
                    attr_ds = ref_group.create_dataset(
                        f"Attributes/{name}",
                        data=np.bytes_(name),
                    )
                    attr_ds.attrs['SA-2D'] = np.bytes_(mesh_name)
                    attr_ds.attrs['Type'] = np.bytes_('Reference Line')

                    written += 1
                    logger.debug(f"Wrote reference line '{name}' with {len(coords)} points")

        except Exception:
            logger.debug("Failed to write reference lines to HDF", exc_info=True)
            raise

        return written
