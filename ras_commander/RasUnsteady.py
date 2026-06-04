"""
RasUnsteady - Operations for handling unsteady flow files in HEC-RAS projects.

This module is part of the ras-commander library and uses a centralized logging configuration.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs are written to both console and a rotating file handler.
- The default log file is 'ras_commander.log' in the 'logs' directory.
- The default log level is INFO.

To use logging in this module:
1. Use the @log_call decorator for automatic function call logging.
2. For additional logging, use logger.[level]() calls (e.g., logger.info(), logger.debug()).


Example:
    @log_call
    def my_function():
        logger.debug("Additional debug information")
        # Function logic here
        
-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasUnsteady:
- update_flow_title()
- read_unsteady_description()
- update_unsteady_description()
- update_restart_settings()
- set_restart_settings()
- get_restart_settings()
- set_hydrograph_fixed_start_time()
- extract_boundary_and_tables()
- print_boundaries_and_tables()
- identify_tables()
- parse_fixed_width_table()
- extract_tables()
- write_table_to_file()
- get_met_precipitation_config()
- set_precipitation_hyetograph()
- set_constant_precipitation()
- set_gridded_precipitation()
- configure_gridded_dss_precipitation()
- set_meteorological_station()
- get_meteorological_stations()
- set_point_evapotranspiration()
- get_point_evapotranspiration()

Precipitation Functions:
- get_met_precipitation_config() - Read Meteorological Data tab precipitation settings
- set_precipitation_hyetograph() - Write hyetograph DataFrame to unsteady file
- set_gridded_precipitation() - Configure GDAL raster precipitation
- configure_gridded_dss_precipitation() - Configure gridded DSS precipitation

Meteorological Point Data Functions:
- set_meteorological_station() - Create/update meteorological station metadata
- get_meteorological_stations() - Parse meteorological station metadata
- set_point_evapotranspiration() - Write point ET series from a DataFrame
- get_point_evapotranspiration() - Parse point ET series into a DataFrame

DSS Boundary Condition Functions:
- get_dss_boundaries() - Extract all DSS-linked BCs with full path info
- get_inline_hydrograph_boundaries() - Extract inline table BCs with time series data
- delete_boundary() - Remove one Boundary Location block from an unsteady file
- update_dss_run_identifier() - Update DSS path F-part for new scenarios
- set_boundary_dss_link() - Convert inline BC to DSS-linked (complete state transition)
- set_boundary_inline_hydrograph() - Write inline hydrograph, convert DSS to inline
- set_flow_hydrograph_slope() - Add or update `Flow Hydrograph Slope=` (EG slope) for a Flow Hydrograph BC
- set_normal_depth_boundary() - Add or update Normal Depth (Friction Slope=) for a 1D river or 2D BC line boundary
- get_unique_dss_subbasins() - Get unique HMS subbasin names from DSS paths
- update_dss_path_by_station() - Update DSS A-part for specific river station
- update_flow_multiplier_by_station() - Update/insert QMult for specific river station
- update_boundary_dss_paths() - Batch update DSS paths and multipliers
- get_rating_curve() - Read Rating Curve (stage, discharge) pairs from a boundary
- set_rating_curve() - Write or replace Rating Curve data on a boundary

Stage/Flow Hydrograph Functions (Internal Boundary):
- get_stage_flow_hydrograph() - Read observed stage/flow pairs from an internal BC
- set_stage_flow_hydrograph() - Write observed stage/flow pairs to an internal BC

Lateral Inflow Hydrograph Functions:
- get_lateral_inflow_hydrograph() - Read lateral inflow hydrograph data from a boundary
- set_lateral_inflow_hydrograph() - Write lateral inflow hydrograph data to a boundary

Uniform Lateral Inflow Hydrograph Functions:
- get_uniform_lateral_inflow_hydrograph() - Read uniform lateral inflow data (reach-based BC)
- set_uniform_lateral_inflow_hydrograph() - Write uniform lateral inflow data (reach-based BC)

Initial Conditions Method Selection:
- get_initial_flow_method() - Determine which IC method is active (restart_file, prior_ws, initial_flow_distribution, none)
- set_initial_flow_method() - Set the IC method selection (restart_file, prior_ws, initial_flow_distribution, none)
- get_prior_ws_filename() - Read Prior WS Filename and Profile from unsteady file
- set_prior_ws_filename() - Write Prior WS Filename and Profile to unsteady file

Initial Flow Distribution Table:
- get_initial_conditions() - Read all IC entries (flow, storage, rrr) as DataFrame
- set_initial_conditions() - Write IC entries from list of dicts or DataFrame (auto-sets IC method)
- validate_initial_flow_stations() - Check IC flow stations match geometry cross sections

Non-Newtonian Method Selection:
- get_non_newtonian_method() - Read the Non-Newtonian method integer and return name
- set_non_newtonian_method() - Set the Non-Newtonian method by integer or name

"""
import os
import numbers
import shutil
from datetime import datetime
from pathlib import Path
from .RasPrj import ras
from .LoggingConfig import get_logger
from .Decorators import log_call
import pandas as pd
import numpy as np
import re
from typing import Union, Optional, Any, Tuple, Dict, List



logger = get_logger(__name__)

# Module code starts here

class RasUnsteady:
    """
    Class for all operations related to HEC-RAS unsteady flow files.
    """
    _PRECIP_VARIABLE_CANDIDATES = (
        "APCP_surface",
        "APCP",
        "precip",
        "precipitation",
        "rain",
    )
    _BOUNDARY_TYPE_KEYWORDS: Tuple[Tuple[str, str], ...] = (
        ("Lateral Inflow Hydrograph=", "Lateral Inflow Hydrograph"),
        ("Uniform Lateral Inflow Hydrograph=", "Uniform Lateral Inflow Hydrograph"),
        ("Uniform Lateral Inflow=", "Uniform Lateral Inflow"),
        ("Observed Stage and Flow Hydrograph=", "Observed Stage and Flow"),
        ("Flow Hydrograph=", "Flow Hydrograph"),
        ("Stage Hydrograph=", "Stage Hydrograph"),
        ("Precipitation Hydrograph=", "Precipitation Hydrograph"),
        ("Rating Curve=", "Rating Curve"),
        ("Friction Slope=", "Normal Depth"),
        ("Gate Name=", "Gate Opening"),
        ("Gate Openings=", "Gate Opening"),
        ("Ground Water Interflow=", "Ground Water Interflow"),
        ("Navigation Dam=", "Navigation Dam"),
        ("Rule Operation=", "Rule Operation"),
    )
    _PROTECTED_BOUNDARY_TYPES = {
        "Flow Hydrograph",
        "Stage Hydrograph",
        "Normal Depth",
        "Rating Curve",
    }
    _GLOBAL_TRAILER_PREFIXES = (
        "Met Point Raster Parameters=",
        "Met Station Name=",
        "Met Station Gauge Height=",
        "Met Station LL=",
        "Met Station XY=",
        "Precipitation Mode=",
        "Wind Mode=",
        "Air Density Mode=",
        "Met BC=",
        "Non-Newtonian",
        "User Yeild=",
        "User Yield=",
        "Herschel-Bulkley",
        "Clastic",
        "Coulomb",
        "Voellmy",
        "Lava",
        "Temperature=",
        "Heat Ballance=",
        "Viscosity=",
        "Yield Strength=",
        "Consistency Factor=",
        "Profile Coefficient=",
        "Lava Param=",
    )

    @staticmethod
    def _find_precipitation_variable(
        dataset: Any,
        preferred: Optional[str] = None,
    ) -> Optional[str]:
        """Return the precipitation variable name used by HEC-RAS GDAL import."""
        candidates: List[str] = []
        if preferred:
            candidates.append(str(preferred))
        candidates.extend(
            name
            for name in RasUnsteady._PRECIP_VARIABLE_CANDIDATES
            if name not in candidates
        )
        for var_name in candidates:
            if var_name in dataset.data_vars:
                return var_name
        return None

    @staticmethod
    def _open_netcdf_dataset(netcdf_path: Path, xarray_module: Any) -> Any:
        """Open a NetCDF dataset, preferring the quieter h5netcdf backend."""
        try:
            return xarray_module.open_dataset(netcdf_path, engine="h5netcdf")
        except Exception as h5netcdf_error:
            logger.debug(
                "h5netcdf could not open %s; falling back to xarray default backend: %s",
                netcdf_path,
                h5netcdf_error,
            )
            return xarray_module.open_dataset(netcdf_path)

    @staticmethod
    def _decode_netcdf_text(value: Any) -> str:
        """Decode NetCDF string-like metadata to plain text."""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore").strip()
        if isinstance(value, np.bytes_):
            return value.tobytes().decode("utf-8", errors="ignore").strip()
        if isinstance(value, np.ndarray):
            if value.shape == ():
                return RasUnsteady._decode_netcdf_text(value.item())
            if value.dtype.kind in {"S", "U"}:
                return "".join(
                    RasUnsteady._decode_netcdf_text(item)
                    for item in value.tolist()
                ).strip()
        return str(value).strip()

    @staticmethod
    def _crs_metadata_to_wkt(value: Any) -> Optional[str]:
        """Convert NetCDF CRS metadata to the WKT string written by HEC-RAS."""
        crs_text = RasUnsteady._decode_netcdf_text(value)
        if not crs_text:
            return None

        upper_text = crs_text.upper()
        if upper_text.startswith(("PROJCS[", "GEOGCS[")):
            return crs_text

        try:
            from pyproj import CRS

            return CRS.from_user_input(crs_text).to_wkt(version="WKT1_GDAL")
        except Exception as exc:
            if upper_text.startswith(("PROJCRS[", "GEOGCRS[")):
                return crs_text
            raise ValueError(
                f"Could not parse NetCDF CRS metadata as WKT/EPSG: {crs_text!r}"
            ) from exc

    @staticmethod
    def _get_netcdf_crs_wkt(dataset: Any, precip_var: str) -> str:
        """Read CRS WKT from CF/rioxarray-style NetCDF metadata."""
        data_array = dataset[precip_var]
        metadata_sources: List[Any] = []
        metadata_source_names: set[str] = set()

        grid_mapping_name = data_array.attrs.get("grid_mapping")
        if grid_mapping_name and grid_mapping_name in dataset.variables:
            metadata_sources.append(dataset[grid_mapping_name])
            metadata_source_names.add(str(grid_mapping_name))

        for var_name in ("spatial_ref", "crs"):
            if var_name in dataset.variables and var_name not in metadata_source_names:
                metadata_sources.append(dataset[var_name])
                metadata_source_names.add(var_name)

        metadata_sources.extend([data_array, dataset])

        for source in metadata_sources:
            attrs = getattr(source, "attrs", {})
            for attr_name in (
                "spatial_ref",
                "crs_wkt",
                "crs",
                "epsg_code",
                "proj4",
            ):
                if attr_name not in attrs:
                    continue
                wkt = RasUnsteady._crs_metadata_to_wkt(attrs[attr_name])
                if wkt:
                    return wkt

        raise ValueError(
            f"NetCDF precipitation variable {precip_var!r} does not define CRS "
            "metadata. Add a CF grid_mapping variable with spatial_ref/crs_wkt "
            "or a parseable CRS attribute."
        )

    @staticmethod
    def _netcdf_interval_hours(times: Any) -> np.ndarray:
        """Return per-row interval hours for instantaneous-rate NetCDF rasters."""
        timestamps = pd.to_datetime(times)
        n_times = len(timestamps)
        interval_hours = np.zeros(n_times, dtype=np.float32)
        if n_times <= 1:
            return interval_hours

        deltas = (timestamps[1:] - timestamps[:-1]).total_seconds() / 3600.0
        deltas = np.asarray(deltas, dtype=np.float32)
        if not np.all(np.isfinite(deltas)) or np.any(deltas <= 0):
            raise ValueError("NetCDF precipitation times must be strictly increasing")

        interval_hours[1:] = deltas
        return interval_hours

    @staticmethod
    @log_call
    def update_flow_title(unsteady_file: str, new_title: str, ras_object: Optional[Any] = None) -> None:
        """
        Update the Flow Title in an unsteady flow file (.u*).

        The Flow Title provides a descriptive identifier for unsteady flow scenarios in HEC-RAS. 
        It appears in the HEC-RAS interface and helps differentiate between different flow files.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file or unsteady flow number
            new_title (str): New flow title (max 24 characters, will be truncated if longer)
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            None: The function modifies the file in-place and updates the ras object's unsteady dataframe

        Example:
            # Clone an existing unsteady flow file
            new_unsteady_number = RasPlan.clone_unsteady("02")
            
            # Get path to the new unsteady flow file
            new_unsteady_file = RasPlan.get_unsteady_path(new_unsteady_number)
            
            # Update the flow title
            new_title = "Modified Flow Scenario"
            RasUnsteady.update_flow_title(new_unsteady_file, new_title)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        unsteady_path = Path(unsteady_file)
        new_title = new_title[:24]  # Truncate to 24 characters if longer
        
        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise PermissionError(f"Permission denied when reading unsteady flow file: {unsteady_path}")
        
        updated = False
        for i, line in enumerate(lines):
            if line.startswith("Flow Title="):
                old_title = line.strip().split('=')[1]
                lines[i] = f"Flow Title={new_title}\n"
                updated = True
                logger.info(f"Updated Flow Title from '{old_title}' to '{new_title}'")
                break
        
        if updated:
            try:
                with open(unsteady_path, 'w', encoding='utf-8', errors='replace') as f:
                    f.writelines(lines)
                logger.debug(f"Successfully wrote modifications to unsteady flow file: {unsteady_path}")
            except PermissionError:
                logger.error(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
                raise PermissionError(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
            except IOError as e:
                logger.error(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
                raise IOError(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
            logger.info(f"Applied Flow Title modification to {unsteady_file}")
        else:
            logger.warning(f"Flow Title not found in {unsteady_file}")
    
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    @log_call
    def read_unsteady_description(unsteady_number_or_path: Union[str, Path], ras_object: Optional[Any] = None) -> str:
        """
        Read the description from an unsteady flow file (.u##).

        Args:
            unsteady_number_or_path (Union[str, Path]): The unsteady number (e.g., '01')
                or path to the unsteady flow file.
            ras_object (optional): RAS project object. If None, uses global 'ras' object.

        Returns:
            str: The description text, or empty string if not found.

        Raises:
            ValueError: If the unsteady flow file is not found.
        """
        from .RasUtils import RasUtils

        unsteady_file_path = Path(unsteady_number_or_path)
        if not unsteady_file_path.is_file():
            from .RasPlan import RasPlan
            unsteady_file_path = RasPlan.get_unsteady_path(unsteady_number_or_path, ras_object)
            if unsteady_file_path is None or not Path(unsteady_file_path).exists():
                raise ValueError(f"Unsteady flow file not found: {unsteady_number_or_path}")

        return RasUtils._read_description_block(unsteady_file_path)

    @staticmethod
    @log_call
    def update_unsteady_description(unsteady_number_or_path: Union[str, Path], description: str, ras_object: Optional[Any] = None) -> bool:
        """
        Update or insert the description in an unsteady flow file (.u##).

        Args:
            unsteady_number_or_path (Union[str, Path]): The unsteady number (e.g., '01')
                or path to the unsteady flow file.
            description (str): Description text to write.
            ras_object (optional): RAS project object. If None, uses global 'ras' object.

        Returns:
            bool: True if successful, False otherwise.

        Raises:
            ValueError: If the unsteady flow file is not found.
        """
        from .RasUtils import RasUtils

        unsteady_file_path = Path(unsteady_number_or_path)
        if not unsteady_file_path.is_file():
            from .RasPlan import RasPlan
            unsteady_file_path = RasPlan.get_unsteady_path(unsteady_number_or_path, ras_object)
            if unsteady_file_path is None or not Path(unsteady_file_path).exists():
                raise ValueError(f"Unsteady flow file not found: {unsteady_number_or_path}")

        return RasUtils._write_description_block(unsteady_file_path, description, 'Flow Title')

    @staticmethod
    def _resolve_unsteady_file_path(
        unsteady_number_or_path: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> Path:
        """
        Resolve an unsteady flow number or explicit path to a .u## file path.
        """
        unsteady_file_path = Path(unsteady_number_or_path)
        if unsteady_file_path.is_file():
            return unsteady_file_path

        from .RasPlan import RasPlan

        resolved_path = RasPlan.get_unsteady_path(unsteady_number_or_path, ras_object)
        if resolved_path is None or not Path(resolved_path).exists():
            raise ValueError(f"Unsteady flow file not found: {unsteady_number_or_path}")
        return Path(resolved_path)

    @staticmethod
    @log_call
    def get_initial_conditions(
        unsteady_number_or_path: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Parse initial condition entries from a HEC-RAS unsteady flow file.

        Args:
            unsteady_number_or_path: Unsteady flow number or path to a .u## file.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            pd.DataFrame: Initial flow, storage/2D elevation, and RRR elevation
                entries from the unsteady file.
        """
        from .usgs.initial_conditions import InitialConditions

        unsteady_file_path = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path,
            ras_object=ras_object,
        )
        return InitialConditions.parse_initial_conditions(unsteady_file_path)

    @staticmethod
    @log_call
    def set_initial_conditions(
        unsteady_number_or_path: Union[str, Path],
        ic_entries,
        ras_object: Optional[Any] = None,
        auto_set_method: bool = True,
    ) -> None:
        """
        Write initial condition entries to a HEC-RAS unsteady flow file.

        Replaces all existing ``Initial Flow Loc=``, ``Initial Storage Elev=``,
        and ``Initial RRR Elev=`` lines with the provided entries.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"03"``) or path to a ``.u##`` file.
        ic_entries : list[dict] or pd.DataFrame
            IC entries. Each row/dict must have:

            * ``type`` — ``'flow'``, ``'storage'``, or ``'rrr'``
            * ``river``, ``reach``, ``station``, ``value`` (for flow/rrr)
            * ``area_name``, ``value`` (for storage)
        ras_object : RasPrj, optional
            RAS project object. If None, uses global ``ras``.
        auto_set_method : bool, default True
            When True and entries are non-empty, automatically sets the IC
            method to ``initial_flow_distribution`` via
            ``set_initial_flow_method()``.

        Examples
        --------
        >>> import pandas as pd
        >>> ic_df = pd.DataFrame([
        ...     {'type': 'flow', 'river': 'White', 'reach': 'Muncie',
        ...      'station': 15696.24, 'value': 1500},
        ... ])
        >>> RasUnsteady.set_initial_conditions("01", ic_df, ras_object=ras)
        """
        from .usgs.initial_conditions import InitialConditions

        if isinstance(ic_entries, pd.DataFrame):
            entries = ic_entries.to_dict('records')
        else:
            entries = list(ic_entries)

        unsteady_file_path = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path,
            ras_object=ras_object,
        )
        InitialConditions.write_initial_conditions(unsteady_file_path, entries)

        if auto_set_method and entries:
            RasUnsteady.set_initial_flow_method(
                unsteady_number_or_path,
                method="initial_flow_distribution",
                ras_object=ras_object,
            )

    @staticmethod
    @log_call
    def validate_initial_flow_stations(
        unsteady_number_or_path: Union[str, Path],
        geom_number_or_path: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Validate that Initial Flow Loc stations match cross sections in geometry.

        Reads the IC table from the unsteady file and checks each ``flow`` entry
        against cross sections parsed from the geometry file. Reports matched,
        unmatched, and summary statistics.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number or path to a ``.u##`` file.
        geom_number_or_path : str or Path, optional
            Geometry file number or path. If None, resolves via the plan that
            references this unsteady file.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.

        Returns
        -------
        dict
            ``valid`` (bool): True if all flow stations have matching XS.
            ``matched`` (list[dict]): Entries with matching geometry XS.
            ``unmatched`` (list[dict]): Entries with no matching geometry XS.
            ``ic_count`` (int): Total flow IC entries checked.
            ``geom_xs_count`` (int): Total XS in geometry.
        """
        from ras_commander import ras as global_ras
        _ras = ras_object if ras_object is not None else global_ras

        ic_df = RasUnsteady.get_initial_conditions(
            unsteady_number_or_path, ras_object=ras_object,
        )
        flow_ics = ic_df[ic_df['type'] == 'flow'] if len(ic_df) > 0 else ic_df

        if geom_number_or_path is None:
            geom_path = None
            if hasattr(_ras, 'plan_df') and hasattr(_ras, 'unsteady_df'):
                try:
                    unsteady_path = RasUnsteady._resolve_unsteady_file_path(
                        unsteady_number_or_path, ras_object=ras_object,
                    )
                    u_name = unsteady_path.name
                    for _, plan_row in _ras.plan_df.iterrows():
                        u_num = plan_row.get('unsteady_number')
                        if u_num is not None and f".u{str(u_num).zfill(2)}" in u_name:
                            g_num = plan_row.get('Geom File')
                            if g_num is not None:
                                g_match = _ras.geom_df[
                                    _ras.geom_df['geom_number'] == str(g_num)
                                ]
                                if len(g_match) > 0:
                                    geom_path = Path(g_match.iloc[0]['full_path'])
                                break
                except Exception:
                    pass
        else:
            geom_path = Path(geom_number_or_path)
            if not geom_path.is_file() and hasattr(_ras, 'geom_df'):
                g_match = _ras.geom_df[
                    _ras.geom_df['geom_number'] == str(geom_number_or_path)
                ]
                if len(g_match) > 0:
                    geom_path = Path(g_match.iloc[0]['full_path'])

        geom_stations = set()
        if geom_path is not None and geom_path.is_file():
            try:
                from ras_commander.geom import GeomCrossSection
                xs_df = GeomCrossSection.get_cross_sections(geom_path)
                if xs_df is not None and len(xs_df) > 0:
                    for _, xs_row in xs_df.iterrows():
                        river = str(xs_row.get('river', '')).strip()
                        reach = str(xs_row.get('reach', '')).strip()
                        station = xs_row.get('station')
                        if station is not None:
                            geom_stations.add((river, reach, float(station)))
            except Exception as e:
                logger.warning(f"Could not parse geometry for validation: {e}")

        matched = []
        unmatched = []
        for _, ic_row in flow_ics.iterrows():
            river = str(ic_row.get('river', '')).strip()
            reach = str(ic_row.get('reach', '')).strip()
            station = ic_row.get('station')
            entry = {
                'river': river, 'reach': reach,
                'station': station, 'value': ic_row.get('value'),
            }
            if (river, reach, float(station)) in geom_stations:
                matched.append(entry)
            else:
                unmatched.append(entry)

        valid = len(unmatched) == 0 and len(flow_ics) > 0
        if not geom_stations:
            valid = True
            logger.info("No geometry XS available for validation; skipping station check")

        logger.info(
            f"IC validation: {len(matched)} matched, {len(unmatched)} unmatched "
            f"out of {len(flow_ics)} flow ICs ({len(geom_stations)} XS in geometry)"
        )
        return {
            'valid': valid,
            'matched': matched,
            'unmatched': unmatched,
            'ic_count': len(flow_ics),
            'geom_xs_count': len(geom_stations),
        }

    # -------------------------------------------------------------------------
    # Storage Area / 2D Flow Area Initial Elevation helpers
    # -------------------------------------------------------------------------

    @staticmethod
    @log_call
    def get_initial_storage_elevations(
        unsteady_number_or_path: Union[str, Path],
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Return only the storage/2D-area IC entries from the unsteady file.

        Convenience wrapper around ``get_initial_conditions()`` that filters
        to ``type == 'storage'`` rows.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number or path to a ``.u##`` file.
        ras_object : RasPrj, optional
            RAS project object.

        Returns
        -------
        pd.DataFrame
            Columns: ``type``, ``area_name``, ``value``.
        """
        ic_df = RasUnsteady.get_initial_conditions(
            unsteady_number_or_path, ras_object=ras_object,
        )
        if len(ic_df) == 0:
            return ic_df
        return ic_df[ic_df['type'] == 'storage'].reset_index(drop=True)

    @staticmethod
    @log_call
    def set_initial_storage_elevation(
        unsteady_number_or_path: Union[str, Path],
        area_name: str,
        elevation: float,
        ras_object: Optional[Any] = None,
    ) -> None:
        """Add or update a single storage/2D-area initial elevation.

        Reads the current IC table, replaces the entry for *area_name* (or
        appends it if absent), and writes the table back.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number or path to a ``.u##`` file.
        area_name : str
            Storage area or 2D flow area name (as stored in the geometry).
        elevation : float
            Initial water-surface elevation for this area.
        ras_object : RasPrj, optional
            RAS project object.
        """
        ic_df = RasUnsteady.get_initial_conditions(
            unsteady_number_or_path, ras_object=ras_object,
        )
        entries = ic_df.to_dict('records') if len(ic_df) > 0 else []

        replaced = False
        for entry in entries:
            if entry.get('type') == 'storage' and str(entry.get('area_name', '')).strip() == str(area_name).strip():
                entry['value'] = elevation
                replaced = True
                break
        if not replaced:
            entries.append({
                'type': 'storage',
                'area_name': area_name,
                'value': elevation,
                'river': None,
                'reach': None,
                'station': None,
            })

        RasUnsteady.set_initial_conditions(
            unsteady_number_or_path, entries, ras_object=ras_object,
        )
        logger.info(f"Set initial elevation for '{area_name}' = {elevation}")

    @staticmethod
    @log_call
    def get_min_storage_elevations(
        geom_hdf_path: Union[str, Path],
        ras_object: Optional[Any] = None,
    ) -> Dict[str, float]:
        """Read minimum elevations for all storage/2D areas from geometry HDF.

        Equivalent to the HEC-RAS GUI *Import Min SA Elevation(s)* button.
        Uses ``HdfStorageArea.get_storage_area_names()`` and
        ``HdfStorageArea.get_storage_area_properties()`` to extract the
        ``Min Elev`` attribute from the preprocessed geometry HDF.

        Parameters
        ----------
        geom_hdf_path : str or Path
            Path to a geometry HDF file (e.g. ``"model.g01.hdf"``).
        ras_object : RasPrj, optional
            RAS project object.

        Returns
        -------
        dict[str, float]
            Mapping of area name to minimum elevation.
        """
        from .hdf.HdfStorageArea import HdfStorageArea

        geom_hdf_path = Path(geom_hdf_path)
        sa_names = HdfStorageArea.get_storage_area_names(
            geom_hdf_path, ras_object=ras_object,
        )
        result: Dict[str, float] = {}
        for sa_name in sa_names:
            props = HdfStorageArea.get_storage_area_properties(
                geom_hdf_path, sa_name, ras_object=ras_object,
            )
            min_elev = props.get('min_elev') or props.get('Min Elev')
            if min_elev is not None:
                result[sa_name] = float(min_elev)
        logger.info(f"Read min elevations for {len(result)} storage areas from {geom_hdf_path.name}")
        return result

    @staticmethod
    @log_call
    def set_ic_from_output_profile(
        unsteady_number_or_path: Union[str, Path],
        source_plan_hdf: Union[str, Path],
        time_index: int = -1,
        include_1d: bool = True,
        include_storage: bool = True,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Populate IC table from a completed simulation's output profile.

        Reads flow at each 1D cross section and water-surface elevation at
        each storage area from the source HDF at the given time step, then
        writes the values as initial conditions in the target unsteady file.

        This replicates the HEC-RAS GUI menu action
        *Set Initial Conditions from Output File*.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Target unsteady flow number or ``.u##`` file path.
        source_plan_hdf : str or Path
            Path to a completed plan HDF file containing results.
        time_index : int, default -1
            Time step index to extract. ``-1`` selects the last time step.
        include_1d : bool, default True
            Include 1D cross-section flow values.
        include_storage : bool, default True
            Include storage-area water-surface elevations.
        ras_object : RasPrj, optional
            RAS project object.

        Returns
        -------
        pd.DataFrame
            The IC entries that were written, with columns matching
            ``get_initial_conditions()`` output.
        """
        import h5py

        source_plan_hdf = Path(source_plan_hdf)
        if not source_plan_hdf.exists():
            raise FileNotFoundError(f"Source plan HDF not found: {source_plan_hdf}")

        entries: list = []
        base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"

        with h5py.File(source_plan_hdf, "r") as hdf:
            if base not in hdf:
                raise ValueError(f"No unsteady time series results in {source_plan_hdf.name}")

            if include_1d:
                xs_path = f"{base}/Cross Sections"
                if xs_path in hdf and f"{xs_path}/Flow" in hdf:
                    attrs = hdf[f"{xs_path}/Cross Section Attributes"][:]
                    flow = hdf[f"{xs_path}/Flow"][time_index, :]
                    for i, attr in enumerate(attrs):
                        river = attr["River"].decode("utf-8").strip()
                        reach = attr["Reach"].decode("utf-8").strip()
                        station = attr["Station"].decode("utf-8").strip()
                        try:
                            station_val = float(station)
                        except ValueError:
                            station_val = station
                        entries.append({
                            "type": "flow",
                            "river": river,
                            "reach": reach,
                            "station": station_val,
                            "value": float(flow[i]),
                            "area_name": None,
                        })
                    logger.info(f"Read flow at {len(attrs)} cross sections from {source_plan_hdf.name}")

            if include_storage:
                sa_path = f"{base}/Storage Areas"
                geom_sa = "Geometry/Storage Areas/Attributes"
                if sa_path in hdf and f"{sa_path}/Water Surface" in hdf and geom_sa in hdf:
                    sa_attrs = hdf[geom_sa][:]
                    ws = hdf[f"{sa_path}/Water Surface"][time_index, :]
                    for i, sa in enumerate(sa_attrs):
                        name = sa["Name"].decode("utf-8").strip() if isinstance(sa["Name"], bytes) else str(sa["Name"]).strip()
                        if i < len(ws):
                            entries.append({
                                "type": "storage",
                                "area_name": name,
                                "value": float(ws[i]),
                                "river": None,
                                "reach": None,
                                "station": None,
                            })
                    logger.info(f"Read WSE for {len(sa_attrs)} storage areas from {source_plan_hdf.name}")

        if not entries:
            logger.warning("No IC entries extracted from output profile")
            return pd.DataFrame(columns=["type", "river", "reach", "station", "value", "area_name"])

        ic_df = pd.DataFrame(entries)
        RasUnsteady.set_initial_conditions(
            unsteady_number_or_path, ic_df, ras_object=ras_object,
        )
        logger.info(f"Wrote {len(entries)} IC entries from output profile to unsteady file")
        return ic_df

    NON_NEWTONIAN_METHODS = {
        0: "Newtonian Assumptions",
        1: "Bingham",
        2: "O'Brien (Quadratic)",
        3: "Clastic Grain-Flow",
        4: "Generalized Herschel-Bulkley",
    }

    BULKING_METHODS = {
        0: "Do Not Bulk",
        1: "Bulk Fluid Volume",
    }

    YIELD_METHODS = {
        0: "Exponential",
        1: "User Yield",
    }

    VISCOSITY_METHODS = {
        0: "Use Coulomb",
        1: "Maron and Pierce",
        2: "User Defined Viscosity",
        3: "User Visc Ratio",
    }

    @staticmethod
    @log_call
    def get_non_newtonian_method(
        unsteady_number_or_path: Union[str, Path],
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Read the Non-Newtonian method from an unsteady flow file.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"03"``) or path to a ``.u##`` file.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.

        Returns
        -------
        dict
            ``method_id`` (int): Integer method code (0-4).
            ``method_name`` (str): Human-readable method name.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith("Non-Newtonian Method="):
                    value_str = line.split('=', 1)[1].strip().rstrip(',').strip()
                    method_id = int(value_str)
                    method_name = RasUnsteady.NON_NEWTONIAN_METHODS.get(
                        method_id, f"Unknown ({method_id})"
                    )
                    return {'method_id': method_id, 'method_name': method_name}
        return {'method_id': 0, 'method_name': 'Newtonian Assumptions'}

    @staticmethod
    @log_call
    def set_non_newtonian_method(
        unsteady_number_or_path: Union[str, Path],
        method: Union[int, str],
        ras_object: Optional[Any] = None,
    ) -> None:
        """
        Set the Non-Newtonian method in an unsteady flow file.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"03"``) or path to a ``.u##`` file.
        method : int or str
            Method to set. Accepts integer (0-4) or name string:
            ``0``/``"Newtonian Assumptions"``, ``1``/``"Bingham"``,
            ``2``/``"O'Brien (Quadratic)"``, ``3``/``"Clastic Grain-Flow"``,
            ``4``/``"Generalized Herschel-Bulkley"``.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.

        Raises
        ------
        ValueError
            If the method is not a valid integer (0-4) or recognized name.
        """
        if isinstance(method, int):
            method_id = method
        elif isinstance(method, str):
            name_to_id = {v.lower(): k for k, v in RasUnsteady.NON_NEWTONIAN_METHODS.items()}
            method_lower = method.lower().strip()
            if method_lower in name_to_id:
                method_id = name_to_id[method_lower]
            elif method.strip().isdigit():
                method_id = int(method.strip())
            else:
                raise ValueError(
                    f"Unknown Non-Newtonian method: '{method}'. "
                    f"Valid names: {list(RasUnsteady.NON_NEWTONIAN_METHODS.values())}"
                )
        else:
            raise ValueError(f"method must be int or str, got {type(method)}")

        if method_id not in RasUnsteady.NON_NEWTONIAN_METHODS:
            raise ValueError(
                f"Invalid method_id {method_id}. Must be 0-4: "
                f"{RasUnsteady.NON_NEWTONIAN_METHODS}"
            )

        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        found = False
        for i, line in enumerate(lines):
            if line.startswith("Non-Newtonian Method="):
                lines[i] = f"Non-Newtonian Method= {method_id} \n"
                found = True
                break

        if not found:
            logger.warning(
                f"No 'Non-Newtonian Method=' line found in {unsteady_file.name}; "
                "line not written"
            )
            return

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        logger.info(
            f"Set Non-Newtonian method to {method_id} "
            f"({RasUnsteady.NON_NEWTONIAN_METHODS[method_id]}) "
            f"in {unsteady_file.name}"
        )

    @staticmethod
    @log_call
    def get_non_newtonian_concentration(
        unsteady_number_or_path: Union[str, Path],
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Read Non-Newtonian concentration and bulking parameters from a .u## file.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or path to a ``.u##`` file.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.

        Returns
        -------
        dict
            ``cv`` (float): Volumetric concentration in percent.
            ``bulking_method`` (int): 0=Do Not Bulk, 1=Bulk Fluid Volume.
            ``bulking_method_name`` (str): Human-readable bulking method name.
            ``max_cv`` (float): Maximum volumetric concentration in percent.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        result = {'cv': 0.0, 'bulking_method': 0, 'bulking_method_name': 'Do Not Bulk', 'max_cv': 0.0}
        key_map = {
            'Non-Newtonian Constant Vol Conc=': 'cv',
            'Non-Newtonian Max Cv=': 'max_cv',
        }
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                for key, field in key_map.items():
                    if line.startswith(key):
                        val_str = line.split('=', 1)[1].strip()
                        try:
                            result[field] = float(val_str)
                        except ValueError:
                            pass
                if line.startswith('Non-Newtonian Bulking Method='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        bm = int(val_str)
                        result['bulking_method'] = bm
                        result['bulking_method_name'] = RasUnsteady.BULKING_METHODS.get(
                            bm, f"Unknown ({bm})"
                        )
                    except ValueError:
                        pass
        return result

    @staticmethod
    @log_call
    def set_non_newtonian_concentration(
        unsteady_number_or_path: Union[str, Path],
        cv: Optional[float] = None,
        bulking_method: Optional[Union[int, str]] = None,
        max_cv: Optional[float] = None,
        ras_object: Optional[Any] = None,
    ) -> None:
        """
        Set Non-Newtonian concentration and bulking parameters in a .u## file.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or path to a ``.u##`` file.
        cv : float, optional
            Volumetric concentration in percent (e.g. 30.0 for 30%).
        bulking_method : int or str, optional
            ``0``/``"Do Not Bulk"`` or ``1``/``"Bulk Fluid Volume"``.
        max_cv : float, optional
            Maximum volumetric concentration in percent.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.
        """
        if cv is None and bulking_method is None and max_cv is None:
            return

        if bulking_method is not None:
            if isinstance(bulking_method, str):
                name_to_id = {v.lower(): k for k, v in RasUnsteady.BULKING_METHODS.items()}
                bm_lower = bulking_method.lower().strip()
                if bm_lower in name_to_id:
                    bulking_method = name_to_id[bm_lower]
                elif bulking_method.strip().isdigit():
                    bulking_method = int(bulking_method.strip())
                else:
                    raise ValueError(
                        f"Unknown bulking method: '{bulking_method}'. "
                        f"Valid: {list(RasUnsteady.BULKING_METHODS.values())}"
                    )
            if bulking_method not in RasUnsteady.BULKING_METHODS:
                raise ValueError(
                    f"Invalid bulking_method {bulking_method}. Must be 0-1: "
                    f"{RasUnsteady.BULKING_METHODS}"
                )

        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if cv is not None and line.startswith('Non-Newtonian Constant Vol Conc='):
                lines[i] = f"Non-Newtonian Constant Vol Conc={cv}\n"
            elif bulking_method is not None and line.startswith('Non-Newtonian Bulking Method='):
                lines[i] = f"Non-Newtonian Bulking Method= {bulking_method} \n"
            elif max_cv is not None and line.startswith('Non-Newtonian Max Cv='):
                lines[i] = f"Non-Newtonian Max Cv={max_cv}\n"

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        changes = []
        if cv is not None:
            changes.append(f"cv={cv}%")
        if bulking_method is not None:
            changes.append(f"bulking={RasUnsteady.BULKING_METHODS[bulking_method]}")
        if max_cv is not None:
            changes.append(f"max_cv={max_cv}%")
        logger.info(f"Set NN concentration params ({', '.join(changes)}) in {unsteady_file.name}")

    @staticmethod
    @log_call
    def get_non_newtonian_shear(
        unsteady_number_or_path: Union[str, Path],
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Read Non-Newtonian yield stress and viscosity parameters from a .u## file.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or path to a ``.u##`` file.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.

        Returns
        -------
        dict
            ``yield_method`` (int): 0=Exponential, 1=User Yield.
            ``yield_method_name`` (str): Human-readable yield method name.
            ``yield_coef`` (tuple[float, float]): Exponential yield coefficients (a, b).
            ``user_yield`` (float): User-specified yield stress in Pa.
            ``visc_method`` (int): 0=Use Coulomb, 1=Maron and Pierce, 2=User Defined Viscosity, 3=User Visc Ratio.
            ``visc_method_name`` (str): Human-readable viscosity method name.
            ``obrien_b`` (float): O'Brien exponential viscosity B coefficient.
            ``user_viscosity`` (float): User-defined dynamic viscosity in Pa·s.
            ``user_visc_ratio`` (float): Viscosity ratio multiplier.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        result = {
            'yield_method': 0, 'yield_method_name': 'Exponential',
            'yield_coef': (0.0, 0.0), 'user_yield': 0.0,
            'visc_method': 0, 'visc_method_name': 'Use Coulomb',
            'obrien_b': 0.0, 'user_viscosity': 0.0, 'user_visc_ratio': 0.0,
        }
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('Non-Newtonian Yield Method='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        ym = int(val_str)
                        result['yield_method'] = ym
                        result['yield_method_name'] = RasUnsteady.YIELD_METHODS.get(
                            ym, f"Unknown ({ym})"
                        )
                    except ValueError:
                        pass
                elif line.startswith('Non-Newtonian Yield Coef='):
                    val_str = line.split('=', 1)[1].strip()
                    parts = [p.strip() for p in val_str.split(',')]
                    try:
                        result['yield_coef'] = (float(parts[0]), float(parts[1]))
                    except (ValueError, IndexError):
                        pass
                elif line.startswith('User Yeild='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        result['user_yield'] = float(val_str)
                    except ValueError:
                        pass
                elif line.startswith('Non-Newtonian Sed Visc='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        vm = int(val_str)
                        result['visc_method'] = vm
                        result['visc_method_name'] = RasUnsteady.VISCOSITY_METHODS.get(
                            vm, f"Unknown ({vm})"
                        )
                    except ValueError:
                        pass
                elif line.startswith('Non-Newtonian Obrian B='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        result['obrien_b'] = float(val_str)
                    except ValueError:
                        pass
                elif line.startswith('User Viscosity Ratio='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        result['user_visc_ratio'] = float(val_str)
                    except ValueError:
                        pass
                elif line.startswith('User Viscosity='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        result['user_viscosity'] = float(val_str)
                    except ValueError:
                        pass
        return result

    @staticmethod
    @log_call
    def set_non_newtonian_shear(
        unsteady_number_or_path: Union[str, Path],
        yield_method: Optional[Union[int, str]] = None,
        yield_coef: Optional[tuple] = None,
        user_yield: Optional[float] = None,
        visc_method: Optional[Union[int, str]] = None,
        obrien_b: Optional[float] = None,
        user_viscosity: Optional[float] = None,
        user_visc_ratio: Optional[float] = None,
        ras_object: Optional[Any] = None,
    ) -> None:
        """
        Set Non-Newtonian yield stress and viscosity parameters in a .u## file.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or path to a ``.u##`` file.
        yield_method : int or str, optional
            ``0``/``"Exponential"`` or ``1``/``"User Yield"``.
        yield_coef : tuple of (float, float), optional
            Exponential yield coefficients (a, b) for tau_y = a * exp(b * Cv).
        user_yield : float, optional
            User-specified constant yield stress in Pa.
        visc_method : int or str, optional
            ``0``/``"Use Coulomb"``, ``1``/``"Maron and Pierce"``,
            ``2``/``"User Defined Viscosity"``, ``3``/``"User Visc Ratio"``.
        obrien_b : float, optional
            O'Brien exponential viscosity B coefficient.
        user_viscosity : float, optional
            User-defined dynamic viscosity in Pa·s.
        user_visc_ratio : float, optional
            Viscosity ratio multiplier.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.
        """
        all_none = all(v is None for v in [
            yield_method, yield_coef, user_yield, visc_method,
            obrien_b, user_viscosity, user_visc_ratio,
        ])
        if all_none:
            return

        if yield_method is not None:
            if isinstance(yield_method, str):
                name_to_id = {v.lower(): k for k, v in RasUnsteady.YIELD_METHODS.items()}
                ym_lower = yield_method.lower().strip()
                if ym_lower in name_to_id:
                    yield_method = name_to_id[ym_lower]
                elif yield_method.strip().isdigit():
                    yield_method = int(yield_method.strip())
                else:
                    raise ValueError(
                        f"Unknown yield method: '{yield_method}'. "
                        f"Valid: {list(RasUnsteady.YIELD_METHODS.values())}"
                    )
            if yield_method not in RasUnsteady.YIELD_METHODS:
                raise ValueError(
                    f"Invalid yield_method {yield_method}. Must be 0-1: "
                    f"{RasUnsteady.YIELD_METHODS}"
                )

        if visc_method is not None:
            if isinstance(visc_method, str):
                name_to_id = {v.lower(): k for k, v in RasUnsteady.VISCOSITY_METHODS.items()}
                vm_lower = visc_method.lower().strip()
                if vm_lower in name_to_id:
                    visc_method = name_to_id[vm_lower]
                elif visc_method.strip().isdigit():
                    visc_method = int(visc_method.strip())
                else:
                    raise ValueError(
                        f"Unknown viscosity method: '{visc_method}'. "
                        f"Valid: {list(RasUnsteady.VISCOSITY_METHODS.values())}"
                    )
            if visc_method not in RasUnsteady.VISCOSITY_METHODS:
                raise ValueError(
                    f"Invalid visc_method {visc_method}. Must be 0-3: "
                    f"{RasUnsteady.VISCOSITY_METHODS}"
                )

        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if yield_method is not None and line.startswith('Non-Newtonian Yield Method='):
                lines[i] = f"Non-Newtonian Yield Method= {yield_method} \n"
            elif yield_coef is not None and line.startswith('Non-Newtonian Yield Coef='):
                lines[i] = f"Non-Newtonian Yield Coef={yield_coef[0]}, {yield_coef[1]}\n"
            elif user_yield is not None and line.startswith('User Yeild='):
                lines[i] = f"User Yeild={user_yield}\n"
            elif visc_method is not None and line.startswith('Non-Newtonian Sed Visc='):
                lines[i] = f"Non-Newtonian Sed Visc= {visc_method} \n"
            elif obrien_b is not None and line.startswith('Non-Newtonian Obrian B='):
                lines[i] = f"Non-Newtonian Obrian B={obrien_b}\n"
            elif user_visc_ratio is not None and line.startswith('User Viscosity Ratio='):
                lines[i] = f"User Viscosity Ratio={user_visc_ratio}\n"
            elif user_viscosity is not None and line.startswith('User Viscosity='):
                lines[i] = f"User Viscosity={user_viscosity}\n"

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        changes = []
        if yield_method is not None:
            changes.append(f"yield_method={RasUnsteady.YIELD_METHODS[yield_method]}")
        if yield_coef is not None:
            changes.append(f"yield_coef=({yield_coef[0]}, {yield_coef[1]})")
        if user_yield is not None:
            changes.append(f"user_yield={user_yield} Pa")
        if visc_method is not None:
            changes.append(f"visc_method={RasUnsteady.VISCOSITY_METHODS[visc_method]}")
        if obrien_b is not None:
            changes.append(f"obrien_b={obrien_b}")
        if user_viscosity is not None:
            changes.append(f"user_viscosity={user_viscosity} Pa·s")
        if user_visc_ratio is not None:
            changes.append(f"user_visc_ratio={user_visc_ratio}")
        logger.info(f"Set NN shear params ({', '.join(changes)}) in {unsteady_file.name}")

    @staticmethod
    @log_call
    def get_non_newtonian_herschel_bulkley(
        unsteady_number_or_path: Union[str, Path],
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Read Generalized Herschel-Bulkley parameters from a .u## file.

        The HB model is: tau = tau_y + K * (du/dy)^n.
        When n=1 the model reduces to Bingham plastic.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or path to a ``.u##`` file.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.

        Returns
        -------
        dict
            ``k`` (float): Consistency factor K.
            ``n`` (float): Power index n.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        result = {'k': 0.0, 'n': 0.0}
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('Herschel-Bulkley Coef='):
                    val_str = line.split('=', 1)[1].strip()
                    parts = [p.strip() for p in val_str.split(',')]
                    try:
                        result['k'] = float(parts[0])
                        result['n'] = float(parts[1])
                    except (ValueError, IndexError):
                        pass
                    break
        return result

    @staticmethod
    @log_call
    def set_non_newtonian_herschel_bulkley(
        unsteady_number_or_path: Union[str, Path],
        k: Optional[float] = None,
        n: Optional[float] = None,
        ras_object: Optional[Any] = None,
    ) -> None:
        """
        Set Generalized Herschel-Bulkley parameters in a .u## file.

        The HB model is: tau = tau_y + K * (du/dy)^n.
        When n=1 the model reduces to Bingham plastic.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or path to a ``.u##`` file.
        k : float, optional
            Consistency factor K.
        n : float, optional
            Power index n (n=1 is Bingham plastic).
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.
        """
        if k is None and n is None:
            return

        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if line.startswith('Herschel-Bulkley Coef='):
                current = line.split('=', 1)[1].strip()
                parts = [p.strip() for p in current.split(',')]
                try:
                    cur_k = float(parts[0])
                    cur_n = float(parts[1])
                except (ValueError, IndexError):
                    cur_k, cur_n = 0.0, 0.0
                new_k = k if k is not None else cur_k
                new_n = n if n is not None else cur_n
                lines[i] = f"Herschel-Bulkley Coef={new_k}, {new_n}\n"
                break

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        changes = []
        if k is not None:
            changes.append(f"K={k}")
        if n is not None:
            changes.append(f"n={n}")
        logger.info(f"Set HB params ({', '.join(changes)}) in {unsteady_file.name}")

    CLASTIC_METHODS = {
        0: "Coulomb",
        1: "Voellmy",
    }

    HINDERED_FV_METHODS = {
        0: "No Hindered Settling",
        1: "User Specified K",
    }

    HIGH_C_TRANSPORT_METHODS = {
        0: "Yang and Molina",
        1: "Mehta-Boldock",
        2: "Simson Only",
    }

    @staticmethod
    @log_call
    def get_non_newtonian_clastic(
        unsteady_number_or_path: Union[str, Path],
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Read Clastic Grain-Flow and auxiliary Non-Newtonian parameters from a .u## file.

        Covers the Clastic method selector, friction angle (Coulomb Phi / legacy
        Voellmy Phi), Voellmy Xi, hindered settling, representative grain size,
        and high-concentration transport equation.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or path to a ``.u##`` file.
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.

        Returns
        -------
        dict
            ``clastic_method`` (int): 0=Coulomb, 1=Voellmy.
            ``clastic_method_name`` (str): Human-readable clastic method name.
            ``coulomb_phi`` (float): Friction angle phi in degrees.
            ``voellmy_x`` (float): Voellmy turbulence parameter Xi.
            ``hindered_fv`` (int): 0=No Hindered Settling, 1=User Specified K.
            ``hindered_fv_name`` (str): Human-readable hindered settling method.
            ``fv_k`` (float): k power parameter for hindered settling.
            ``ds`` (float): Representative grain size in mm (O'Brien only).
            ``high_c_transport`` (int): High-concentration transport equation selector.
            ``high_c_transport_name`` (str): Human-readable transport equation name.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        result = {
            'clastic_method': 0, 'clastic_method_name': 'Coulomb',
            'coulomb_phi': 0.0, 'voellmy_x': 0.0,
            'hindered_fv': 0, 'hindered_fv_name': 'No Hindered Settling',
            'fv_k': 0.0, 'ds': 0.0,
            'high_c_transport': 0, 'high_c_transport_name': 'Yang and Molina',
        }
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('Clastic Method='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        cm = int(val_str)
                        result['clastic_method'] = cm
                        result['clastic_method_name'] = RasUnsteady.CLASTIC_METHODS.get(
                            cm, f"Unknown ({cm})"
                        )
                    except ValueError:
                        pass
                elif line.startswith('Coulomb Phi=') or line.startswith('Voellmy Phi='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        result['coulomb_phi'] = float(val_str)
                    except ValueError:
                        pass
                elif line.startswith('Voellmy X='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        result['voellmy_x'] = float(val_str)
                    except ValueError:
                        pass
                elif line.startswith('Non-Newtonian Hindered FV='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        hfv = int(val_str)
                        result['hindered_fv'] = hfv
                        result['hindered_fv_name'] = RasUnsteady.HINDERED_FV_METHODS.get(
                            hfv, f"Unknown ({hfv})"
                        )
                    except ValueError:
                        pass
                elif line.startswith('Non-Newtonian FV K='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        result['fv_k'] = float(val_str)
                    except ValueError:
                        pass
                elif line.startswith('Non-Newtonian ds='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        result['ds'] = float(val_str)
                    except ValueError:
                        pass
                elif line.startswith('Non-Newtonian High C Transport='):
                    val_str = line.split('=', 1)[1].strip()
                    try:
                        hct = int(val_str)
                        result['high_c_transport'] = hct
                        result['high_c_transport_name'] = RasUnsteady.HIGH_C_TRANSPORT_METHODS.get(
                            hct, f"Unknown ({hct})"
                        )
                    except ValueError:
                        pass
        return result

    @staticmethod
    @log_call
    def set_non_newtonian_clastic(
        unsteady_number_or_path: Union[str, Path],
        clastic_method: Optional[Union[int, str]] = None,
        coulomb_phi: Optional[float] = None,
        voellmy_x: Optional[float] = None,
        hindered_fv: Optional[Union[int, str]] = None,
        fv_k: Optional[float] = None,
        ds: Optional[float] = None,
        high_c_transport: Optional[int] = None,
        ras_object: Optional[Any] = None,
    ) -> None:
        """
        Set Clastic Grain-Flow and auxiliary Non-Newtonian parameters in a .u## file.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or path to a ``.u##`` file.
        clastic_method : int or str, optional
            ``0``/``"Coulomb"`` or ``1``/``"Voellmy"``.
        coulomb_phi : float, optional
            Friction angle phi in degrees. Written as ``Coulomb Phi=``.
        voellmy_x : float, optional
            Voellmy turbulence parameter Xi (only for Voellmy method).
        hindered_fv : int or str, optional
            ``0``/``"No Hindered Settling"`` or ``1``/``"User Specified K"``.
        fv_k : float, optional
            k power parameter for hindered settling equation.
        ds : float, optional
            Representative grain size in mm (O'Brien method).
        high_c_transport : int, optional
            High-concentration transport equation selector (0-2+).
        ras_object : RasPrj, optional
            RAS project object. If None, uses the global ``ras`` object.
        """
        all_none = all(v is None for v in [
            clastic_method, coulomb_phi, voellmy_x, hindered_fv,
            fv_k, ds, high_c_transport,
        ])
        if all_none:
            return

        if clastic_method is not None:
            if isinstance(clastic_method, str):
                name_to_id = {v.lower(): k for k, v in RasUnsteady.CLASTIC_METHODS.items()}
                cm_lower = clastic_method.lower().strip()
                if cm_lower in name_to_id:
                    clastic_method = name_to_id[cm_lower]
                elif clastic_method.strip().isdigit():
                    clastic_method = int(clastic_method.strip())
                else:
                    raise ValueError(
                        f"Unknown clastic method: '{clastic_method}'. "
                        f"Valid: {list(RasUnsteady.CLASTIC_METHODS.values())}"
                    )
            if clastic_method not in RasUnsteady.CLASTIC_METHODS:
                raise ValueError(
                    f"Invalid clastic_method {clastic_method}. Must be 0-1: "
                    f"{RasUnsteady.CLASTIC_METHODS}"
                )

        if hindered_fv is not None:
            if isinstance(hindered_fv, str):
                name_to_id = {v.lower(): k for k, v in RasUnsteady.HINDERED_FV_METHODS.items()}
                hfv_lower = hindered_fv.lower().strip()
                if hfv_lower in name_to_id:
                    hindered_fv = name_to_id[hfv_lower]
                elif hindered_fv.strip().isdigit():
                    hindered_fv = int(hindered_fv.strip())
                else:
                    raise ValueError(
                        f"Unknown hindered FV method: '{hindered_fv}'. "
                        f"Valid: {list(RasUnsteady.HINDERED_FV_METHODS.values())}"
                    )
            if hindered_fv not in RasUnsteady.HINDERED_FV_METHODS:
                raise ValueError(
                    f"Invalid hindered_fv {hindered_fv}. Must be 0-1: "
                    f"{RasUnsteady.HINDERED_FV_METHODS}"
                )

        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if clastic_method is not None and line.startswith('Clastic Method='):
                lines[i] = f"Clastic Method= {clastic_method} \n"
            elif coulomb_phi is not None and (line.startswith('Coulomb Phi=') or line.startswith('Voellmy Phi=')):
                lines[i] = f"Coulomb Phi={coulomb_phi}\n"
            elif voellmy_x is not None and line.startswith('Voellmy X='):
                lines[i] = f"Voellmy X={voellmy_x}\n"
            elif hindered_fv is not None and line.startswith('Non-Newtonian Hindered FV='):
                lines[i] = f"Non-Newtonian Hindered FV= {hindered_fv} \n"
            elif fv_k is not None and line.startswith('Non-Newtonian FV K='):
                lines[i] = f"Non-Newtonian FV K={fv_k}\n"
            elif ds is not None and line.startswith('Non-Newtonian ds='):
                lines[i] = f"Non-Newtonian ds={ds}\n"
            elif high_c_transport is not None and line.startswith('Non-Newtonian High C Transport='):
                lines[i] = f"Non-Newtonian High C Transport= {high_c_transport} \n"

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        changes = []
        if clastic_method is not None:
            changes.append(f"clastic={RasUnsteady.CLASTIC_METHODS[clastic_method]}")
        if coulomb_phi is not None:
            changes.append(f"phi={coulomb_phi}°")
        if voellmy_x is not None:
            changes.append(f"xi={voellmy_x}")
        if hindered_fv is not None:
            changes.append(f"hindered_fv={RasUnsteady.HINDERED_FV_METHODS[hindered_fv]}")
        if fv_k is not None:
            changes.append(f"fv_k={fv_k}")
        if ds is not None:
            changes.append(f"ds={ds}mm")
        if high_c_transport is not None:
            changes.append(f"high_c_transport={high_c_transport}")
        logger.info(f"Set NN clastic params ({', '.join(changes)}) in {unsteady_file.name}")

    # -------------------------------------------------------------------------
    # Gate Openings — T.S. Gate Openings & Elev Controlled Gates
    # -------------------------------------------------------------------------

    @staticmethod
    @log_call
    def get_gate_openings(
        unsteady_number_or_path,
        boundary_index: int = 0,
        ras_object=None,
    ) -> dict:
        """Read gate opening data from a boundary location block.

        Scans the unsteady flow file for ``Boundary Location=`` blocks that
        contain a ``Gate Name=`` key, and returns gate metadata plus the time
        series opening values for the gate at *boundary_index* (0-based index
        among all gate-bearing boundaries in the file).

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or direct file path.
        boundary_index : int, optional
            0-based index of the gate boundary to read (default ``0``).
        ras_object : optional
            ``RasPrj`` instance for path resolution.

        Returns
        -------
        dict
            Keys:

            - ``gate_name`` (str): gate name from ``Gate Name=`` line
            - ``dss_path`` (str): DSS pathname (empty string if inline)
            - ``use_dss`` (bool): whether DSS link is active
            - ``interval`` (str): time interval, e.g. ``"1HOUR"``
            - ``use_fixed_start`` (bool): fixed-start-time flag
            - ``fixed_start`` (str): fixed start date/time string
            - ``count`` (int): number of opening values
            - ``values`` (list[float]): opening heights per time step
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        gate_blocks: list[dict] = []
        i = 0
        while i < len(lines):
            if lines[i].startswith('Boundary Location='):
                bl_idx = i
                i += 1
                # Look for Gate Name= within this boundary block
                while i < len(lines) and not lines[i].startswith('Boundary Location='):
                    if lines[i].startswith('Gate Name='):
                        gate = {
                            'gate_name': lines[i].split('=', 1)[1].strip(),
                            'dss_path': '',
                            'use_dss': False,
                            'interval': '1HOUR',
                            'use_fixed_start': False,
                            'fixed_start': '',
                            'count': 0,
                            'values': [],
                        }
                        i += 1
                        while i < len(lines) and not lines[i].startswith('Boundary Location='):
                            line = lines[i]
                            if line.startswith('Gate DSS Path='):
                                gate['dss_path'] = line.split('=', 1)[1].strip()
                            elif line.startswith('Gate Use DSS='):
                                gate['use_dss'] = line.split('=', 1)[1].strip().lower() == 'true'
                            elif line.startswith('Gate Time Interval='):
                                gate['interval'] = line.split('=', 1)[1].strip()
                            elif line.startswith('Gate Use Fixed Start Time='):
                                gate['use_fixed_start'] = line.split('=', 1)[1].strip().lower() == 'true'
                            elif line.startswith('Gate Fixed Start Date/Time='):
                                gate['fixed_start'] = line.split('=', 1)[1].strip()
                            elif line.startswith('Gate Openings='):
                                count = int(line.split('=', 1)[1].strip())
                                gate['count'] = count
                                vals: list[float] = []
                                i += 1
                                while i < len(lines) and len(vals) < count:
                                    parts = lines[i].split()
                                    if not parts or lines[i].startswith('Boundary Location='):
                                        break
                                    vals.extend(float(v) for v in parts)
                                    i += 1
                                gate['values'] = vals[:count]
                                gate_blocks.append(gate)
                                break  # done with this gate's data lines
                            i += 1
                        continue  # skip the outer i += 1
                    i += 1
            else:
                i += 1

        if boundary_index >= len(gate_blocks):
            raise IndexError(
                f"boundary_index={boundary_index} but only "
                f"{len(gate_blocks)} gate boundaries found in {unsteady_file.name}"
            )
        return gate_blocks[boundary_index]

    @staticmethod
    @log_call
    def set_gate_openings(
        unsteady_number_or_path,
        values: list,
        boundary_index: int = 0,
        gate_name: Optional[str] = None,
        interval: Optional[str] = None,
        ras_object=None,
    ) -> None:
        """Write gate opening time series to a boundary location block.

        Replaces the ``Gate Openings=`` count and all subsequent data lines for
        the gate at *boundary_index*.  Optionally updates gate name and time
        interval.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"02"``) or direct file path.
        values : list of float
            Opening heights per time step.
        boundary_index : int, optional
            0-based index of the gate boundary to write (default ``0``).
        gate_name : str, optional
            New gate name.  If ``None``, the existing name is kept.
        interval : str, optional
            New time interval (e.g. ``"15MIN"``).  If ``None``, kept.
        ras_object : optional
            ``RasPrj`` instance for path resolution.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Locate the Nth gate boundary's Gate Openings= line
        gate_count = 0
        target_openings_idx = None
        target_name_idx = None
        target_interval_idx = None
        i = 0
        while i < len(lines):
            if lines[i].startswith('Gate Name='):
                if gate_count == boundary_index:
                    target_name_idx = i
                    # Scan forward for metadata and openings line
                    j = i + 1
                    while j < len(lines) and not lines[j].startswith('Boundary Location='):
                        if lines[j].startswith('Gate Time Interval='):
                            target_interval_idx = j
                        elif lines[j].startswith('Gate Openings='):
                            target_openings_idx = j
                            break
                        j += 1
                    break
                gate_count += 1
            i += 1

        if target_openings_idx is None:
            raise IndexError(
                f"boundary_index={boundary_index} but only "
                f"{gate_count + 1} gate boundaries scanned in {unsteady_file.name}"
            )

        # Determine the range of old data lines after Gate Openings=
        old_count = int(lines[target_openings_idx].split('=', 1)[1].strip())
        data_start = target_openings_idx + 1
        data_end = data_start
        vals_read = 0
        while data_end < len(lines) and vals_read < old_count:
            parts = lines[data_end].split()
            if not parts or lines[data_end].startswith('Boundary Location='):
                break
            vals_read += len(parts)
            data_end += 1

        # Build new data lines: 8-char fixed-width fields, 10 per line
        new_data_lines = []
        for row_start in range(0, len(values), 10):
            chunk = values[row_start:row_start + 10]
            line_str = ''.join(f'{v:8g}' for v in chunk) + '\n'
            new_data_lines.append(line_str)

        # Replace the Gate Openings= header + data lines
        lines[target_openings_idx] = f'Gate Openings= {len(values)} \n'
        lines[data_start:data_end] = new_data_lines

        # Optional: update gate name
        if gate_name is not None and target_name_idx is not None:
            lines[target_name_idx] = f'Gate Name={gate_name}\n'

        # Optional: update interval
        if interval is not None and target_interval_idx is not None:
            lines[target_interval_idx] = f'Gate Time Interval={interval}\n'

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        logger.info(
            f"Set {len(values)} gate openings (boundary_index={boundary_index}) "
            f"in {unsteady_file.name}"
        )

    @staticmethod
    @log_call
    def get_groundwater_interflow(
        unsteady_number_or_path,
        boundary_index: int = 0,
        ras_object=None,
    ) -> dict:
        """Read groundwater interflow data from a boundary location block.

        Scans the unsteady flow file for ``Boundary Location=`` blocks that
        contain a ``Ground Water Interflow=`` key, and returns the interflow
        metadata plus time-series elevation values and Darcy parameters for
        the boundary at *boundary_index*.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"01"``) or direct file path.
        boundary_index : int, optional
            0-based index of the GW interflow boundary to read (default ``0``).
        ras_object : optional
            ``RasPrj`` instance for path resolution.

        Returns
        -------
        dict
            Keys:

            - ``interval`` (str): time interval, e.g. ``"1HOUR"``
            - ``count`` (int): number of elevation values
            - ``values`` (list[float]): groundwater elevation time series
            - ``darcy_k`` (float or None): hydraulic conductivity
            - ``darcy_k_per_day`` (float or None): conductivity per day
            - ``darcy_distance`` (float or None): Darcy flow distance
            - ``dss_path`` (str): DSS pathname (empty string if inline)
            - ``use_dss`` (bool): whether DSS link is active
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        gw_blocks: list[dict] = []
        i = 0
        while i < len(lines):
            if lines[i].startswith('Boundary Location='):
                i += 1
                interval = '1HOUR'
                while i < len(lines) and not lines[i].startswith('Boundary Location='):
                    if lines[i].startswith('Interval='):
                        interval = lines[i].split('=', 1)[1].strip()
                    if lines[i].startswith('Ground Water Interflow='):
                        count = int(lines[i].split('=', 1)[1].strip())
                        gw = {
                            'interval': interval,
                            'count': count,
                            'values': [],
                            'darcy_k': None,
                            'darcy_k_per_day': None,
                            'darcy_distance': None,
                            'dss_path': '',
                            'use_dss': False,
                        }
                        vals: list[float] = []
                        i += 1
                        while i < len(lines) and len(vals) < count:
                            if lines[i].startswith('Boundary Location=') or lines[i].startswith('Ground Water Darcy'):
                                break
                            parts = lines[i].split()
                            if parts:
                                vals.extend(float(v) for v in parts)
                            i += 1
                        gw['values'] = vals[:count]
                        while i < len(lines) and not lines[i].startswith('Boundary Location='):
                            line = lines[i]
                            if line.startswith('Ground Water Darcy K='):
                                gw['darcy_k'] = float(line.split('=', 1)[1].strip())
                            elif line.startswith('Ground Water Darcy K/day='):
                                gw['darcy_k_per_day'] = float(line.split('=', 1)[1].strip())
                            elif line.startswith('Ground Water Darcy Distance='):
                                gw['darcy_distance'] = float(line.split('=', 1)[1].strip())
                            elif line.startswith('DSS Path='):
                                gw['dss_path'] = line.split('=', 1)[1].strip()
                            elif line.startswith('Use DSS='):
                                gw['use_dss'] = line.split('=', 1)[1].strip().lower() == 'true'
                            i += 1
                        gw_blocks.append(gw)
                        continue
                    i += 1
            else:
                i += 1

        if boundary_index >= len(gw_blocks):
            raise IndexError(
                f"boundary_index={boundary_index} but only "
                f"{len(gw_blocks)} GW interflow boundaries found in {unsteady_file.name}"
            )
        return gw_blocks[boundary_index]

    @staticmethod
    @log_call
    def set_groundwater_interflow(
        unsteady_number_or_path,
        values: list,
        boundary_index: int = 0,
        darcy_k: Optional[float] = None,
        darcy_k_per_day: Optional[float] = None,
        darcy_distance: Optional[float] = None,
        interval: Optional[str] = None,
        ras_object=None,
    ) -> None:
        """Write groundwater interflow elevation data to a boundary block.

        Replaces the inline elevation time series and optionally updates the
        three Darcy parameters for the GW interflow boundary at
        *boundary_index*.

        Parameters
        ----------
        unsteady_number_or_path : str or Path
            Unsteady flow number (e.g. ``"01"``) or direct file path.
        values : list[float]
            Groundwater elevation time series values.
        boundary_index : int, optional
            0-based index of the GW interflow boundary to write (default ``0``).
        darcy_k : float, optional
            Hydraulic conductivity. If ``None``, existing value is preserved.
        darcy_k_per_day : float, optional
            Conductivity per day. If ``None``, existing value is preserved.
        darcy_distance : float, optional
            Darcy flow distance. If ``None``, existing value is preserved.
        interval : str, optional
            Time interval (e.g. ``"1HOUR"``). If ``None``, preserved.
        ras_object : optional
            ``RasPrj`` instance for path resolution.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object=ras_object,
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        gw_hit = 0
        target_header_idx = None
        target_data_start = None
        target_data_end = None
        target_darcy_lines: dict[str, int] = {}
        target_interval_idx = None

        i = 0
        while i < len(lines):
            if lines[i].startswith('Boundary Location='):
                i += 1
                while i < len(lines) and not lines[i].startswith('Boundary Location='):
                    if lines[i].startswith('Interval='):
                        candidate_interval_idx = i
                    if lines[i].startswith('Ground Water Interflow='):
                        if gw_hit == boundary_index:
                            target_header_idx = i
                            target_interval_idx = candidate_interval_idx
                            count = int(lines[i].split('=', 1)[1].strip())
                            target_data_start = i + 1
                            j = target_data_start
                            parsed = 0
                            while j < len(lines) and parsed < count:
                                if lines[j].startswith('Boundary Location=') or lines[j].startswith('Ground Water Darcy'):
                                    break
                                parts = lines[j].split()
                                if parts:
                                    parsed += len(parts)
                                j += 1
                            target_data_end = j
                            while j < len(lines) and not lines[j].startswith('Boundary Location='):
                                line = lines[j]
                                if line.startswith('Ground Water Darcy K='):
                                    target_darcy_lines['k'] = j
                                elif line.startswith('Ground Water Darcy K/day='):
                                    target_darcy_lines['k_day'] = j
                                elif line.startswith('Ground Water Darcy Distance='):
                                    target_darcy_lines['dist'] = j
                                j += 1
                            break
                        gw_hit += 1
                        i += 1
                        continue
                    i += 1
                if target_header_idx is not None:
                    break
            else:
                i += 1

        if target_header_idx is None:
            raise IndexError(
                f"boundary_index={boundary_index} but only "
                f"{gw_hit} GW interflow boundaries found in {unsteady_file.name}"
            )

        lines[target_header_idx] = f'Ground Water Interflow= {len(values)} \n'

        new_data_lines: list[str] = []
        for row_start in range(0, len(values), 10):
            row_vals = values[row_start:row_start + 10]
            row_str = ''.join(
                f'{v:8.2f}' if v != int(v) or abs(v) > 99999 else f'{int(v):>8}'
                for v in row_vals
            )
            new_data_lines.append(row_str + '\n')

        lines[target_data_start:target_data_end] = new_data_lines

        offset = len(new_data_lines) - (target_data_end - target_data_start)
        adjusted = {k: v + offset for k, v in target_darcy_lines.items()}
        if target_interval_idx is not None:
            target_interval_idx_adj = target_interval_idx  # before data, no offset

        if darcy_k is not None and 'k' in adjusted:
            lines[adjusted['k']] = f'Ground Water Darcy K={darcy_k}\n'
        if darcy_k_per_day is not None and 'k_day' in adjusted:
            lines[adjusted['k_day']] = f'Ground Water Darcy K/day={darcy_k_per_day}\n'
        if darcy_distance is not None and 'dist' in adjusted:
            lines[adjusted['dist']] = f'Ground Water Darcy Distance={darcy_distance}\n'
        if interval is not None and target_interval_idx is not None:
            lines[target_interval_idx_adj] = f'Interval={interval}\n'

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        logger.info(
            f"Set {len(values)} GW interflow values (boundary_index={boundary_index}) "
            f"in {unsteady_file.name}"
        )

    # ------------------------------------------------------------------
    # Navigation Dam
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def get_navigation_dam(
        unsteady_number_or_path,
        boundary_index: int = 0,
        ras_object=None,
    ) -> dict:
        """Read Navigation Dam BC data from a .u## file.

        Returns a dict with keys:
            params           – raw parameter string after 'Navigation Dam='
            sft_count        – number of SFT points
            sft_flow         – list of flow values (first row)
            sft_stage_open   – list of stage values with gates open (second row)
            sft_stage_closed – list of stage values with gates closed (third row)
            flow_monitor_rrr – raw string for Flow Monitor RRR line
            hinge_point_rrr  – raw string for Hinge Point RRR line
            cp_hinge_point   – raw string for CP Hinge Point values
            cp_min_pool      – raw string for CP Min Pool values
            cp_max_pool      – raw string for CP Max Pool values
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Find all Navigation Dam boundary blocks
        nav_indices = [
            i for i, line in enumerate(lines)
            if line.startswith('Navigation Dam=')
        ]
        if boundary_index >= len(nav_indices):
            raise IndexError(
                f"boundary_index={boundary_index} but only "
                f"{len(nav_indices)} Navigation Dam boundaries found"
            )
        start = nav_indices[boundary_index]

        result = {
            'params': lines[start].split('=', 1)[1].strip(),
        }

        # Parse SFT table (immediately follows Navigation Dam= line)
        sft_line = lines[start + 1]
        if not sft_line.strip().startswith('Navigation Dam SFT='):
            raise ValueError(
                f"Expected 'Navigation Dam SFT=' at line {start + 2}, "
                f"got: {sft_line.strip()[:60]}"
            )
        sft_count = int(sft_line.split('=')[1].strip())
        result['sft_count'] = sft_count

        # Read 3 rows of fixed-width data: flow, stage-open, stage-closed
        # Each row spans ceil(sft_count / 10) lines of 8-char fields
        num_data_lines = (sft_count + 9) // 10
        pos = start + 2
        rows = []
        for _ in range(3):
            vals = []
            for dl in range(num_data_lines):
                raw = lines[pos + dl]
                for j in range(0, len(raw.rstrip('\n')), 8):
                    chunk = raw[j:j+8].strip()
                    if chunk:
                        vals.append(float(chunk))
            rows.append(vals[:sft_count])
            pos += num_data_lines

        result['sft_flow'] = rows[0]
        result['sft_stage_open'] = rows[1]
        result['sft_stage_closed'] = rows[2]

        # Parse remaining Nav Dam fields until next Boundary Location or EOF
        result['flow_monitor_rrr'] = ''
        result['hinge_point_rrr'] = ''
        result['cp_hinge_point'] = ''
        result['cp_min_pool'] = ''
        result['cp_max_pool'] = ''

        for i in range(pos, min(pos + 20, len(lines))):
            line = lines[i]
            if line.startswith('Boundary Location='):
                break
            if line.startswith('Navigation Dam Flow Monitor RRR='):
                result['flow_monitor_rrr'] = line.split('=', 1)[1].strip()
            elif line.startswith('Navigation Dam Hinge Point RRR='):
                result['hinge_point_rrr'] = line.split('=', 1)[1].strip()
            elif line.startswith('Navigation Dam CP Hinge Point='):
                result['cp_hinge_point'] = line.split('=', 1)[1].strip()
            elif line.startswith('Navigation Dam CP Min Pool='):
                result['cp_min_pool'] = line.split('=', 1)[1].strip()
            elif line.startswith('Navigation Dam CP Max Pool='):
                result['cp_max_pool'] = line.split('=', 1)[1].strip()

        return result

    @staticmethod
    @log_call
    def set_navigation_dam(
        unsteady_number_or_path,
        boundary_index: int = 0,
        params: Optional[str] = None,
        sft_flow: Optional[list] = None,
        sft_stage_open: Optional[list] = None,
        sft_stage_closed: Optional[list] = None,
        flow_monitor_rrr: Optional[str] = None,
        hinge_point_rrr: Optional[str] = None,
        cp_hinge_point: Optional[str] = None,
        cp_min_pool: Optional[str] = None,
        cp_max_pool: Optional[str] = None,
        ras_object=None,
    ) -> None:
        """Write Navigation Dam BC data back to a .u## file.

        Only provided (non-None) parameters are updated; others are preserved.
        If SFT table rows are provided, all three (flow, stage_open, stage_closed)
        must be provided together with equal length.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        nav_indices = [
            i for i, line in enumerate(lines)
            if line.startswith('Navigation Dam=')
        ]
        if boundary_index >= len(nav_indices):
            raise IndexError(
                f"boundary_index={boundary_index} but only "
                f"{len(nav_indices)} Navigation Dam boundaries found"
            )
        start = nav_indices[boundary_index]

        # Update params line
        if params is not None:
            lines[start] = f'Navigation Dam={params}\n'

        # Update SFT table
        if sft_flow is not None or sft_stage_open is not None or sft_stage_closed is not None:
            if not (sft_flow is not None and sft_stage_open is not None and sft_stage_closed is not None):
                raise ValueError("All three SFT rows must be provided together")
            if not (len(sft_flow) == len(sft_stage_open) == len(sft_stage_closed)):
                raise ValueError("All three SFT rows must have equal length")

            new_count = len(sft_flow)
            old_sft_line = lines[start + 1]
            old_count = int(old_sft_line.split('=')[1].strip())
            old_data_lines = (old_count + 9) // 10
            new_data_lines = (new_count + 9) // 10

            # Format data rows in 8-char fixed-width, 10 per line
            def fmt_row(vals):
                result_lines = []
                for i in range(0, len(vals), 10):
                    chunk = vals[i:i+10]
                    result_lines.append(
                        ''.join(f'{v:8g}' for v in chunk) + '\n'
                    )
                return result_lines

            new_lines = [f'Navigation Dam SFT= {new_count} \n']
            new_lines.extend(fmt_row(sft_flow))
            new_lines.extend(fmt_row(sft_stage_open))
            new_lines.extend(fmt_row(sft_stage_closed))

            old_block_end = start + 1 + 1 + old_data_lines * 3  # SFT= line + 3 rows
            lines[start + 1:old_block_end] = new_lines

        # Update RRR and CP fields by scanning forward
        scan_start = start + 1
        for i in range(scan_start, min(scan_start + 40, len(lines))):
            line = lines[i]
            if line.startswith('Boundary Location=') and i > scan_start:
                break
            if flow_monitor_rrr is not None and line.startswith('Navigation Dam Flow Monitor RRR='):
                lines[i] = f'Navigation Dam Flow Monitor RRR={flow_monitor_rrr}\n'
            elif hinge_point_rrr is not None and line.startswith('Navigation Dam Hinge Point RRR='):
                lines[i] = f'Navigation Dam Hinge Point RRR={hinge_point_rrr}\n'
            elif cp_hinge_point is not None and line.startswith('Navigation Dam CP Hinge Point='):
                lines[i] = f'Navigation Dam CP Hinge Point={cp_hinge_point}\n'
            elif cp_min_pool is not None and line.startswith('Navigation Dam CP Min Pool='):
                lines[i] = f'Navigation Dam CP Min Pool={cp_min_pool}\n'
            elif cp_max_pool is not None and line.startswith('Navigation Dam CP Max Pool='):
                lines[i] = f'Navigation Dam CP Max Pool={cp_max_pool}\n'

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        logger.info(
            f"Set Navigation Dam data (boundary_index={boundary_index}) "
            f"in {unsteady_file.name}"
        )

    # ------------------------------------------------------------------
    # Rule Operations BC (raw text round-trip)
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def get_rules_bc(
        unsteady_number_or_path,
        boundary_index: int = 0,
        ras_object=None,
    ) -> dict:
        """Read Rule Operations BC as raw text from a .u## file.

        The Rules BC format is a complex scripting language; this method
        returns the raw lines for inspection or round-trip writing.

        Returns a dict with keys:
            rule_lines     – list of raw 'Rule Operation=...' and
                             'Rule Expression=...' lines (with newlines)
            gate_data      – list of raw 'Rule Gate Data=...' lines
            description    – text between BEGIN/END BOUNDARY DESCRIPTION if present
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Find Boundary Location blocks that contain Rule Operation lines
        # A Rules BC boundary has 'Rule Operation=' lines after the Boundary Location header
        rule_bc_starts = []
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                # Look ahead for Rule Operation= lines within this boundary block
                for j in range(i + 1, min(i + 50, len(lines))):
                    if lines[j].startswith('Boundary Location='):
                        break
                    if lines[j].startswith('Rule Operation='):
                        rule_bc_starts.append(i)
                        break

        if boundary_index >= len(rule_bc_starts):
            raise IndexError(
                f"boundary_index={boundary_index} but only "
                f"{len(rule_bc_starts)} Rule Operation boundaries found"
            )
        bc_start = rule_bc_starts[boundary_index]

        # Find boundary block end
        bc_end = len(lines)
        for i in range(bc_start + 1, len(lines)):
            if lines[i].startswith('Boundary Location='):
                bc_end = i
                break

        # Extract description
        description = ''
        for i in range(bc_start, bc_end):
            if lines[i].strip() == 'BEGIN BOUNDARY DESCRIPTION:':
                desc_lines = []
                for j in range(i + 1, bc_end):
                    if lines[j].strip() == 'END BOUNDARY DESCRIPTION:':
                        break
                    desc_lines.append(lines[j].rstrip('\n'))
                description = '\n'.join(desc_lines)
                break

        # Extract Rule Operation and Rule Expression lines
        rule_lines = []
        gate_data = []
        for i in range(bc_start, bc_end):
            if lines[i].startswith('Rule Operation=') or lines[i].startswith('Rule Expression='):
                rule_lines.append(lines[i])
            elif lines[i].startswith('Rule Gate Data='):
                gate_data.append(lines[i])

        return {
            'rule_lines': rule_lines,
            'gate_data': gate_data,
            'description': description,
        }

    @staticmethod
    @log_call
    def set_rules_bc(
        unsteady_number_or_path,
        boundary_index: int = 0,
        rule_lines: Optional[list] = None,
        gate_data: Optional[list] = None,
        description: Optional[str] = None,
        ras_object=None,
    ) -> None:
        """Write Rule Operations BC data back to a .u## file.

        This replaces the Rule Operation/Expression lines and optionally
        the gate data and description within the specified boundary block.
        Only provided (non-None) parameters are updated.
        """
        unsteady_file = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path, ras_object
        )
        with open(unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Find Rules BC boundaries (same logic as get_rules_bc)
        rule_bc_starts = []
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                for j in range(i + 1, min(i + 50, len(lines))):
                    if lines[j].startswith('Boundary Location='):
                        break
                    if lines[j].startswith('Rule Operation='):
                        rule_bc_starts.append(i)
                        break

        if boundary_index >= len(rule_bc_starts):
            raise IndexError(
                f"boundary_index={boundary_index} but only "
                f"{len(rule_bc_starts)} Rule Operation boundaries found"
            )
        bc_start = rule_bc_starts[boundary_index]

        bc_end = len(lines)
        for i in range(bc_start + 1, len(lines)):
            if lines[i].startswith('Boundary Location='):
                bc_end = i
                break

        # Update description if provided
        if description is not None:
            desc_start = None
            desc_end = None
            for i in range(bc_start, bc_end):
                if lines[i].strip() == 'BEGIN BOUNDARY DESCRIPTION:':
                    desc_start = i + 1
                if lines[i].strip() == 'END BOUNDARY DESCRIPTION:':
                    desc_end = i
                    break
            if desc_start is not None and desc_end is not None:
                new_desc = [description + '\n'] if description else []
                old_len = desc_end - desc_start
                lines[desc_start:desc_end] = new_desc
                bc_end += len(new_desc) - old_len

        # Replace Rule Operation/Expression lines if provided
        if rule_lines is not None:
            # Find range of existing rule lines
            first_rule = None
            last_rule = None
            for i in range(bc_start, bc_end):
                if lines[i].startswith('Rule Operation=') or lines[i].startswith('Rule Expression='):
                    if first_rule is None:
                        first_rule = i
                    last_rule = i

            if first_rule is not None:
                # Ensure rule_lines have newlines
                new_rule_lines = [
                    l if l.endswith('\n') else l + '\n' for l in rule_lines
                ]
                old_len = last_rule - first_rule + 1
                lines[first_rule:last_rule + 1] = new_rule_lines
                bc_end += len(new_rule_lines) - old_len

        # Replace gate data if provided
        if gate_data is not None:
            # Find existing gate data lines
            gate_indices = [
                i for i in range(bc_start, bc_end)
                if lines[i].startswith('Rule Gate Data=')
            ]
            new_gate_lines = [
                l if l.endswith('\n') else l + '\n' for l in gate_data
            ]
            if gate_indices:
                first_gate = gate_indices[0]
                last_gate = gate_indices[-1]
                lines[first_gate:last_gate + 1] = new_gate_lines
            elif new_gate_lines:
                # Insert gate data before bc_end (after last rule line)
                insert_pos = bc_end
                for i in range(bc_end - 1, bc_start, -1):
                    if lines[i].startswith('Rule Operation=') or lines[i].startswith('Rule Expression='):
                        insert_pos = i + 1
                        break
                lines[insert_pos:insert_pos] = new_gate_lines

        with open(unsteady_file, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(lines)

        logger.info(
            f"Set Rules BC data (boundary_index={boundary_index}) "
            f"in {unsteady_file.name}"
        )

    @staticmethod
    @log_call
    def update_restart_settings(unsteady_file: str, use_restart: bool, restart_filename: Optional[str] = None, ras_object: Optional[Any] = None) -> None:
        """
        Update the restart file settings in an unsteady flow file.

        Restart files in HEC-RAS allow simulations to continue from a previously saved state,
        which is useful for long simulations or when making downstream changes.
        This method controls restart-file usage only. To configure a plan to write restart
        files, use ``RasPlan.set_restart_output_settings()``.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file or unsteady number
            use_restart (bool): Whether to use a restart file (True) or not (False)
            restart_filename (str, optional): Path to the restart file (.rst)
                                             Required if use_restart is True
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            None: The function modifies the file in-place and updates the ras object's unsteady dataframe

        Example:
            # Enable restart file for an unsteady flow
            unsteady_file = RasPlan.get_unsteady_path("03")
            RasUnsteady.update_restart_settings(
                unsteady_file, 
                use_restart=True, 
                restart_filename="model_restart.rst"
            )
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        if hasattr(ras_obj, "get_unsteady_entries"):
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.is_file():
            from .RasPlan import RasPlan
            resolved_path = RasPlan.get_unsteady_path(unsteady_file, ras_obj)
            if resolved_path:
                unsteady_path = Path(resolved_path)
        
        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise PermissionError(f"Permission denied when reading unsteady flow file: {unsteady_path}")

        if use_restart and not restart_filename:
            logger.error("Restart filename must be specified when enabling restart.")
            raise ValueError("Restart filename must be specified when enabling restart.")

        original_lines = list(lines)
        new_value = "-1" if use_restart else "0"
        use_restart_index = None
        program_version_index = None
        retained_lines = []

        for line in lines:
            if line.startswith("Restart Filename="):
                continue
            if line.startswith("Program Version="):
                program_version_index = len(retained_lines)
            if line.startswith("Use Restart="):
                use_restart_index = len(retained_lines)
                old_value = line.strip().split("=", 1)[1]
                retained_lines.append(f"Use Restart={new_value}\n")
                logger.info(f"Updated Use Restart from {old_value} to {new_value}")
            else:
                retained_lines.append(line)

        if use_restart_index is None:
            insert_index = program_version_index + 1 if program_version_index is not None else 0
            retained_lines.insert(insert_index, f"Use Restart={new_value}\n")
            use_restart_index = insert_index
            logger.info(f"Inserted Use Restart={new_value} in {unsteady_path.name}")

        if use_restart:
            retained_lines.insert(use_restart_index + 1, f"Restart Filename={restart_filename}\n")
            logger.info(f"Set Restart Filename: {restart_filename}")

        if retained_lines != original_lines:
            try:
                with open(unsteady_path, 'w', encoding='utf-8', errors='replace') as f:
                    f.writelines(retained_lines)
                logger.debug(f"Successfully wrote modifications to unsteady flow file: {unsteady_path}")
            except PermissionError:
                logger.error(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
                raise PermissionError(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
            except IOError as e:
                logger.error(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
                raise IOError(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
            logger.info(f"Applied restart settings modification to {unsteady_file}")
        else:
            logger.info(f"Restart settings already current in {unsteady_file}")

        if hasattr(ras_obj, "get_unsteady_entries"):
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    @log_call
    def set_restart_settings(unsteady_file: str, use_restart: bool, restart_filename: Optional[str] = None, ras_object: Optional[Any] = None) -> None:
        """
        Set restart-file usage in an unsteady flow file.

        Alias for ``update_restart_settings()`` using setter-style naming. This
        method writes ``Use Restart`` and ``Restart Filename`` in the unsteady
        file. Restart output creation is configured separately on the plan file
        with ``RasPlan.set_restart_output_settings()``.
        """
        RasUnsteady.update_restart_settings(
            unsteady_file,
            use_restart=use_restart,
            restart_filename=restart_filename,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def get_restart_settings(unsteady_file: Union[str, Path], ras_object: Optional[Any] = None) -> Dict[str, Optional[Any]]:
        """
        Parse restart-file usage settings from an unsteady flow file.

        HEC-RAS stores restart-file usage in the unsteady-flow file using
        ``Use Restart`` and ``Restart Filename``. This is separate from plan
        restart output settings, which are stored as ``Write IC File`` keys.

        Args:
            unsteady_file: Path to an unsteady flow file or an unsteady number.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            Dict[str, Optional[Any]]: Parsed usage settings and raw values.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.is_file():
            from .RasPlan import RasPlan
            resolved_path = RasPlan.get_unsteady_path(unsteady_file, ras_obj)
            if resolved_path:
                unsteady_path = Path(resolved_path)

        raw_values = {
            "Use Restart": None,
            "Restart Filename": None,
        }

        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as file:
                for line in file:
                    if line.startswith("Use Restart="):
                        raw_values["Use Restart"] = line.split("=", 1)[1].strip()
                    elif line.startswith("Restart Filename=") and raw_values["Restart Filename"] is None:
                        raw_values["Restart Filename"] = line.split("=", 1)[1].strip()
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise PermissionError(f"Permission denied when reading unsteady flow file: {unsteady_path}")

        use_restart = None
        if raw_values["Use Restart"] is not None:
            use_restart = raw_values["Use Restart"].strip().lower() in {"-1", "1", "true"}

        return {
            "use_restart": use_restart,
            "restart_filename": raw_values["Restart Filename"],
            "raw": raw_values,
            "compatibility_note": (
                "HEC-RAS stores restart usage in unsteady-flow files as Use Restart "
                "and Restart Filename. Restart output/save settings are plan-file "
                "Write IC File keys in HEC-RAS 5.x through 7.0."
            ),
        }

    @staticmethod
    @log_call
    def get_initial_flow_method(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Determine which Initial Conditions method is active in an unsteady flow file.

        HEC-RAS uses implicit state to select the IC method:
        - ``Use Restart= -1`` or ``1`` → Restart File mode
        - ``Use Restart= 0`` with ``Prior WS Filename=`` → Prior Water Surface mode
        - ``Use Restart= 0`` with ``Initial Flow Loc=`` lines → Enter Initial Flow Distribution
        - ``Use Restart= 0`` without IC lines → no IC configured (HEC-RAS uses zero flow)

        Parameters
        ----------
        unsteady_file : str or Path
            Path to unsteady flow file or unsteady number.
        ras_object : optional
            RAS project object. If None, uses the global ``ras`` object.

        Returns
        -------
        dict
            Keys:
            - ``method`` (str): ``'restart_file'``, ``'prior_ws'``,
              ``'initial_flow_distribution'``, or ``'none'``
            - ``use_restart`` (bool): Parsed ``Use Restart`` flag
            - ``restart_filename`` (str or None): Restart filename when method is restart_file
            - ``prior_ws_filename`` (str or None): Plan file when method is prior_ws
            - ``prior_ws_profile`` (str or None): Profile name when method is prior_ws
            - ``ic_count`` (int): Number of ``Initial Flow Loc`` / ``Initial Storage Elev`` /
              ``Initial RRR Elev`` lines present
            - ``raw_use_restart`` (str or None): Raw value from file
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.is_file():
            from .RasPlan import RasPlan
            resolved_path = RasPlan.get_unsteady_path(unsteady_file, ras_obj)
            if resolved_path:
                unsteady_path = Path(resolved_path)

        raw_use_restart = None
        restart_filename = None
        prior_ws_filename = None
        prior_ws_profile = None
        ic_count = 0

        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if line.startswith("Use Restart="):
                        raw_use_restart = line.split("=", 1)[1].strip()
                    elif line.startswith("Restart Filename=") and restart_filename is None:
                        restart_filename = line.split("=", 1)[1].strip()
                    elif line.startswith("Prior WS Filename="):
                        prior_ws_filename = line.split("=", 1)[1].strip()
                    elif line.startswith("Prior WS Profile="):
                        prior_ws_profile = line.split("=", 1)[1].strip()
                    elif line.startswith("Initial Flow Loc="):
                        ic_count += 1
                    elif line.startswith("Initial Storage Elev="):
                        ic_count += 1
                    elif line.startswith("Initial RRR Elev="):
                        ic_count += 1
                    elif line.startswith("Boundary Location="):
                        break
        except FileNotFoundError:
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        use_restart = False
        if raw_use_restart is not None:
            use_restart = raw_use_restart.lower() in {"-1", "1", "true"}

        if use_restart:
            method = "restart_file"
        elif prior_ws_filename:
            method = "prior_ws"
        elif ic_count > 0:
            method = "initial_flow_distribution"
        else:
            method = "none"

        logger.info(
            f"IC method for {unsteady_path.name}: {method} "
            f"(Use Restart={raw_use_restart}, {ic_count} IC lines)"
        )

        return {
            "method": method,
            "use_restart": use_restart,
            "restart_filename": restart_filename if use_restart else None,
            "prior_ws_filename": prior_ws_filename if method == "prior_ws" else None,
            "prior_ws_profile": prior_ws_profile if method == "prior_ws" else None,
            "ic_count": ic_count,
            "raw_use_restart": raw_use_restart,
        }

    @staticmethod
    @log_call
    def set_initial_flow_method(
        unsteady_file: Union[str, Path],
        method: str,
        restart_filename: Optional[str] = None,
        prior_ws_filename: Optional[str] = None,
        prior_ws_profile: Optional[str] = None,
        ras_object: Optional[Any] = None
    ) -> None:
        """
        Set the Initial Conditions method selection in an unsteady flow file.

        Configures which IC approach HEC-RAS will use by writing the appropriate
        ``Use Restart`` value and optionally adding or removing associated lines.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to unsteady flow file or unsteady number.
        method : str
            One of:
            - ``'restart_file'`` — enable restart mode (requires *restart_filename*)
            - ``'prior_ws'`` — use prior water surface profile (requires
              *prior_ws_filename*; *prior_ws_profile* defaults to first profile)
            - ``'initial_flow_distribution'`` — disable restart; existing IC lines are kept
            - ``'none'`` — disable restart and remove all IC lines
        restart_filename : str, optional
            Required when *method* is ``'restart_file'``.
        prior_ws_filename : str, optional
            Plan file path (e.g. ``'ProjectName.p01'``). Required when *method*
            is ``'prior_ws'``.
        prior_ws_profile : str, optional
            Profile name within the prior steady plan. Defaults to empty string
            (HEC-RAS uses the first available profile).
        ras_object : optional
            RAS project object. If None, uses the global ``ras`` object.

        Raises
        ------
        ValueError
            If *method* is unknown or required arguments are missing.
        """
        valid_methods = {"restart_file", "prior_ws", "initial_flow_distribution", "none"}
        if method not in valid_methods:
            raise ValueError(f"method must be one of {valid_methods}, got '{method}'")

        if method == "restart_file" and not restart_filename:
            raise ValueError("restart_filename is required when method is 'restart_file'")

        if method == "prior_ws" and not prior_ws_filename:
            raise ValueError("prior_ws_filename is required when method is 'prior_ws'")

        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.is_file():
            from .RasPlan import RasPlan
            resolved_path = RasPlan.get_unsteady_path(unsteady_file, ras_obj)
            if resolved_path:
                unsteady_path = Path(resolved_path)

        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        new_value = "-1" if method == "restart_file" else "0"

        retained = []
        use_restart_idx = None
        program_version_idx = None

        for line in lines:
            if line.startswith("Restart Filename="):
                continue
            if line.startswith("Prior WS Filename="):
                continue
            if line.startswith("Prior WS Profile="):
                continue
            if method == "none" and (
                line.startswith("Initial Flow Loc=")
                or line.startswith("Initial Storage Elev=")
                or line.startswith("Initial RRR Elev=")
            ):
                continue
            if line.startswith("Program Version="):
                program_version_idx = len(retained)
            if line.startswith("Use Restart="):
                use_restart_idx = len(retained)
                retained.append(f"Use Restart={new_value}\n")
            else:
                retained.append(line)

        if use_restart_idx is None:
            insert_idx = (program_version_idx + 1) if program_version_idx is not None else 0
            retained.insert(insert_idx, f"Use Restart={new_value}\n")
            use_restart_idx = insert_idx

        if method == "restart_file":
            retained.insert(use_restart_idx + 1, f"Restart Filename={restart_filename}\n")
        elif method == "prior_ws":
            profile = prior_ws_profile if prior_ws_profile is not None else ""
            retained.insert(use_restart_idx + 1, f"Prior WS Filename={prior_ws_filename}\n")
            retained.insert(use_restart_idx + 2, f"Prior WS Profile={profile}\n")

        with open(unsteady_path, 'w', encoding='utf-8', errors='replace') as f:
            f.writelines(retained)

        logger.info(f"Set IC method to '{method}' in {unsteady_path.name}")

        if hasattr(ras_obj, "get_unsteady_entries"):
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    @log_call
    def get_prior_ws_filename(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> Dict[str, Optional[str]]:
        """
        Read Prior WS Filename and Profile from an unsteady flow file.

        When HEC-RAS is configured to use a prior steady-state water surface
        profile as initial conditions, the ``.u##`` file contains
        ``Prior WS Filename=`` and ``Prior WS Profile=`` lines.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to unsteady flow file or unsteady number.
        ras_object : optional
            RAS project object. If None, uses the global ``ras`` object.

        Returns
        -------
        dict
            Keys:
            - ``prior_ws_filename`` (str or None): Plan file reference
              (e.g. ``'ProjectName.p01'``)
            - ``prior_ws_profile`` (str or None): Profile name within that plan
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.is_file():
            from .RasPlan import RasPlan
            resolved_path = RasPlan.get_unsteady_path(unsteady_file, ras_obj)
            if resolved_path:
                unsteady_path = Path(resolved_path)

        prior_ws_filename = None
        prior_ws_profile = None

        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if line.startswith("Prior WS Filename="):
                        prior_ws_filename = line.split("=", 1)[1].strip()
                    elif line.startswith("Prior WS Profile="):
                        prior_ws_profile = line.split("=", 1)[1].strip()
                    elif line.startswith("Boundary Location="):
                        break
        except FileNotFoundError:
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        return {
            "prior_ws_filename": prior_ws_filename or None,
            "prior_ws_profile": prior_ws_profile or None,
        }

    @staticmethod
    @log_call
    def set_prior_ws_filename(
        unsteady_file: Union[str, Path],
        prior_ws_filename: str,
        prior_ws_profile: Optional[str] = None,
        ras_object: Optional[Any] = None
    ) -> None:
        """
        Write Prior WS Filename and Profile to an unsteady flow file.

        Convenience wrapper around ``set_initial_flow_method(method='prior_ws')``.
        Sets the IC method to prior water surface and writes the plan file
        reference and optional profile name.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to unsteady flow file or unsteady number.
        prior_ws_filename : str
            Plan file to use (e.g. ``'ProjectName.p01'``).
        prior_ws_profile : str, optional
            Profile name. Defaults to empty (HEC-RAS uses first profile).
        ras_object : optional
            RAS project object. If None, uses the global ``ras`` object.
        """
        RasUnsteady.set_initial_flow_method(
            unsteady_file,
            method="prior_ws",
            prior_ws_filename=prior_ws_filename,
            prior_ws_profile=prior_ws_profile,
            ras_object=ras_object,
        )

    @staticmethod
    def _empty_to_none(value: Optional[str]) -> Optional[str]:
        """Return stripped text, or None for missing/blank values."""
        if value is None:
            return None
        value = value.strip()
        return value if value else None

    @staticmethod
    def _parse_optional_float(value: Optional[str]) -> Optional[float]:
        """Parse a RAS text value as float when present."""
        value = RasUnsteady._empty_to_none(value)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            logger.debug("Could not parse meteorology numeric value: %s", value)
            return None

    @staticmethod
    @log_call
    def get_met_precipitation_config(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> Dict[str, Optional[Any]]:
        """
        Parse meteorologic precipitation configuration from a .u## file.

        HEC-RAS persists inactive precipitation settings in ``Met BC`` lines.
        This reader returns the active configuration implied by the top-level
        ``Precipitation Mode`` switch and ``Met BC=Precipitation|Mode`` value,
        plus the raw ``Met BC`` key-value pairs and any sidecar HDF attributes
        when ``<unsteady_file>.hdf`` exists.

        Args:
            unsteady_file: Path to a .u## file or an unsteady flow number.
            ras_object: Optional RAS project object used when resolving a flow number.

        Returns:
            Dict with normalized precipitation keys, ``raw`` dict of all
            ``Met BC=Precipitation|`` values, and ``hdf_attributes`` from the
            sidecar HDF (empty dict if no sidecar exists).
        """
        unsteady_path = Path(unsteady_file)
        if not unsteady_path.is_file():
            unsteady_path = RasUnsteady._resolve_unsteady_file_path(
                unsteady_file,
                ras_object=ras_object,
            )

        config: Dict[str, Optional[Any]] = {
            "enabled": False,
            "precipitation_mode": "",
            "mode": None,
            "source": None,
            "dss_filename": None,
            "dss_pathname": None,
            "interpolation": None,
            "constant_value": None,
            "constant_units": None,
            "gdal_filename": None,
            "gdal_group": None,
            "gdal_folder": None,
            "gdal_filter": None,
            "point_interpolation": None,
            "raw": {},
            "hdf_attributes": {},
        }

        met_values: Dict[str, str] = {}
        precipitation_mode: Optional[str] = None

        try:
            with open(unsteady_path, "r", encoding="utf-8", errors="ignore") as file:
                for line in file:
                    stripped = line.strip()
                    met_prefix = "Met BC=Precipitation|"
                    if stripped.startswith("Precipitation Mode="):
                        precipitation_mode = stripped.split("=", 1)[1].strip()
                    elif stripped.startswith(met_prefix):
                        met_entry = stripped[len(met_prefix):]
                        if "=" not in met_entry:
                            continue
                        met_key, value = met_entry.split("=", 1)
                        met_values[met_key] = value.strip()
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise PermissionError(f"Permission denied when reading unsteady flow file: {unsteady_path}")

        config["raw"] = dict(met_values)
        config["precipitation_mode"] = precipitation_mode or ""

        enabled = (precipitation_mode or "").strip().lower() == "enable"
        config["enabled"] = enabled
        if not enabled:
            RasUnsteady._read_hdf_precip_attrs(config, unsteady_path)
            return config

        mode = RasUnsteady._empty_to_none(met_values.get("Mode"))
        if mode is not None and mode.lower() == "none":
            mode = None
        config["mode"] = mode

        if mode == "Constant":
            config["constant_value"] = RasUnsteady._parse_optional_float(
                met_values.get("Constant Value")
            )
            config["constant_units"] = RasUnsteady._empty_to_none(
                met_values.get("Constant Units")
            )
        elif mode == "Point":
            config["point_interpolation"] = RasUnsteady._empty_to_none(
                met_values.get("Point Interpolation")
            )
        elif mode == "Gridded":
            source = RasUnsteady._empty_to_none(met_values.get("Gridded Source"))
            config["source"] = source
            if "Gridded Interpolation" in met_values:
                config["interpolation"] = met_values["Gridded Interpolation"].strip()

            if source == "DSS":
                config["dss_filename"] = RasUnsteady._empty_to_none(
                    met_values.get("Gridded DSS Filename")
                )
                config["dss_pathname"] = RasUnsteady._empty_to_none(
                    met_values.get("Gridded DSS Pathname")
                )
            elif source == "GDAL Raster File(s)":
                config["gdal_filename"] = RasUnsteady._empty_to_none(
                    met_values.get("Gridded GDAL Filename")
                )
                config["gdal_group"] = (
                    RasUnsteady._empty_to_none(met_values.get("Gridded GDAL Group"))
                    or RasUnsteady._empty_to_none(met_values.get("Gridded GDAL Datasetname"))
                )
                config["gdal_folder"] = RasUnsteady._empty_to_none(
                    met_values.get("Gridded GDAL Folder")
                )
                config["gdal_filter"] = RasUnsteady._empty_to_none(
                    met_values.get("Gridded GDAL Filter")
                )

        RasUnsteady._read_hdf_precip_attrs(config, unsteady_path)
        return config

    @staticmethod
    def _read_hdf_precip_attrs(
        config: Dict[str, Any], unsteady_path: Path
    ) -> None:
        """Read precipitation attributes from the sidecar .u##.hdf into config."""
        hdf_path = Path(str(unsteady_path) + ".hdf")
        if not hdf_path.exists():
            return
        try:
            import h5py

            precip_path = "Event Conditions/Meteorology/Precipitation"
            with h5py.File(hdf_path, "r") as hdf_file:
                if precip_path in hdf_file:
                    config["hdf_attributes"] = {
                        key: RasUnsteady._decode_hdf_attr_value(value)
                        for key, value in hdf_file[precip_path].attrs.items()
                    }
        except Exception:
            pass

    @staticmethod
    @log_call
    def set_hydrograph_fixed_start_time(
        unsteady_number_or_path: Union[str, Path],
        use_fixed_start_time: bool,
        fixed_start_datetime: Optional[Union[str, Tuple[str, str], datetime, pd.Timestamp]] = None,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Set fixed-start timing for inline hydrograph boundary conditions.

        HEC-RAS inline Flow/Stage/Lateral hydrographs are commonly stored as
        values relative to the simulation start. For warm-start continuation
        plans that begin after the original event start, the copied unsteady
        file needs ``Use Fixed Start Time`` enabled so the same hydrograph
        values remain aligned to the source-run clock.

        Args:
            unsteady_number_or_path: Unsteady flow number or path to a .u## file.
            use_fixed_start_time: Whether to enable fixed-start hydrograph timing.
            fixed_start_datetime: Fixed hydrograph start as a datetime,
                pandas Timestamp, ``(DDMMMYYYY, hhmm)`` pair, or
                ``"DDMMMYYYY,hhmm"`` string. Required when enabling fixed-start
                timing. Ignored when disabling.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            Dict[str, Any]: Updated file path, target settings, and line counts.

        Raises:
            ValueError: If enabling without a fixed start date/time, or if the
                unsteady file does not contain ``Use Fixed Start Time`` lines.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if use_fixed_start_time:
            if fixed_start_datetime is None:
                raise ValueError(
                    "fixed_start_datetime is required when use_fixed_start_time=True"
                )
            fixed_start_value = RasUnsteady._format_fixed_start_datetime(
                fixed_start_datetime
            )
        else:
            fixed_start_value = ","

        unsteady_path = RasUnsteady._resolve_unsteady_file_path(
            unsteady_number_or_path,
            ras_object=ras_obj,
        )

        with open(unsteady_path, "r", encoding="utf-8", errors="ignore") as file:
            lines = file.readlines()

        original_lines = list(lines)
        flag_value = "True" if use_fixed_start_time else "False"
        updated_lines = []
        updated_use_lines = 0
        updated_fixed_lines = 0
        inserted_fixed_lines = 0
        index = 0

        while index < len(lines):
            line = lines[index]
            if line.startswith("Use Fixed Start Time="):
                updated_lines.append(f"Use Fixed Start Time={flag_value}\n")
                updated_use_lines += 1
                next_index = index + 1
                if (
                    next_index < len(lines)
                    and lines[next_index].startswith("Fixed Start Date/Time=")
                ):
                    updated_lines.append(
                        f"Fixed Start Date/Time={fixed_start_value}\n"
                    )
                    updated_fixed_lines += 1
                    index += 2
                else:
                    updated_lines.append(
                        f"Fixed Start Date/Time={fixed_start_value}\n"
                    )
                    inserted_fixed_lines += 1
                    index += 1
                continue

            if line.startswith("Fixed Start Date/Time="):
                updated_lines.append(f"Fixed Start Date/Time={fixed_start_value}\n")
                updated_fixed_lines += 1
            else:
                updated_lines.append(line)
            index += 1

        if updated_use_lines == 0:
            raise ValueError(
                f"No 'Use Fixed Start Time=' lines found in {unsteady_path.name}"
            )

        if updated_lines != original_lines:
            with open(unsteady_path, "w", encoding="utf-8") as file:
                file.writelines(updated_lines)

            if hasattr(ras_obj, "get_boundary_conditions"):
                try:
                    ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                except Exception as exc:
                    logger.debug(f"boundaries_df refresh skipped: {exc}")

        logger.info(
            "Set hydrograph fixed start timing in %s: use_fixed_start_time=%s, "
            "fixed_start_datetime=%s, updated_use_lines=%d, "
            "updated_fixed_lines=%d, inserted_fixed_lines=%d",
            unsteady_path.name,
            use_fixed_start_time,
            fixed_start_value,
            updated_use_lines,
            updated_fixed_lines,
            inserted_fixed_lines,
        )

        return {
            "unsteady_file": str(unsteady_path),
            "use_fixed_start_time": use_fixed_start_time,
            "fixed_start_datetime": fixed_start_value,
            "updated_use_fixed_start_time_lines": updated_use_lines,
            "updated_fixed_start_datetime_lines": updated_fixed_lines,
            "inserted_fixed_start_datetime_lines": inserted_fixed_lines,
        }

    @staticmethod
    def _format_fixed_start_datetime(
        value: Union[str, Tuple[str, str], datetime, pd.Timestamp]
    ) -> str:
        """
        Format a HEC-RAS fixed hydrograph start date/time value.
        """
        if isinstance(value, pd.Timestamp):
            value = value.to_pydatetime()

        if isinstance(value, datetime):
            return f"{value.strftime('%d%b%Y').upper()},{value.strftime('%H%M')}"

        if isinstance(value, (tuple, list)) and len(value) == 2:
            date_part, time_part = value
            return f"{str(date_part).strip().upper()},{str(time_part).strip()}"

        if isinstance(value, str):
            raw = value.strip()
            parts = [part for part in re.split(r"[,\s]+", raw) if part]
            if len(parts) == 2:
                return f"{parts[0].upper()},{parts[1]}"

        raise ValueError(
            "fixed_start_datetime must be a datetime, pandas Timestamp, "
            "a (date, time) pair, or a 'DDMMMYYYY,hhmm' string"
        )

    @staticmethod
    @log_call
    def extract_boundary_and_tables(unsteady_file: str, ras_object: Optional[Any] = None) -> pd.DataFrame:
        """
        Extract boundary conditions and their associated tables from an unsteady flow file.

        Boundary conditions in HEC-RAS define time-varying inputs like flow hydrographs,
        stage hydrographs, gate operations, and lateral inflows. This function parses these
        conditions and their data tables from the unsteady flow file.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            pd.DataFrame: DataFrame containing boundary conditions with the following columns:
                - River Name, Reach Name, River Station: Location information
                - DSS File: Associated DSS file path if any
                - Tables: Dictionary containing DataFrames of time-series values

        Example:
            # Get the path to unsteady flow file "02"
            unsteady_file = RasPlan.get_unsteady_path("02")
            
            # Extract boundary conditions and tables
            boundaries_df = RasUnsteady.extract_boundary_and_tables(unsteady_file)
            print(f"Extracted {len(boundaries_df)} boundary conditions from the file.")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        unsteady_path = Path(unsteady_file)
        table_types = [
            'Flow Hydrograph=',
            'Gate Openings=',
            'Stage Hydrograph=',
            'Uniform Lateral Inflow=',
            'Lateral Inflow Hydrograph=',
            'Precipitation Hydrograph=',
            'Rating Curve='
        ]
        
        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise
        
        # Initialize variables
        boundary_data = []
        current_boundary = None
        current_tables = {}
        current_table = None
        table_values = []
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Check for Boundary Location line
            if line.startswith("Boundary Location="):
                # Save previous boundary if it exists
                if current_boundary is not None:
                    if current_table and table_values:
                        # Process any remaining table
                        try:
                            df = pd.DataFrame({'Value': table_values})
                            current_tables[current_table_name] = df
                        except Exception as e:
                            logger.warning(f"Error processing table {current_table_name}: {e}")
                    current_boundary['Tables'] = current_tables
                    boundary_data.append(current_boundary)
                
                # Start new boundary
                current_boundary = {
                    'Boundary Location': line.split('=', 1)[1].strip(),
                    'DSS File': '',
                    'Tables': {}
                }
                current_tables = {}
                current_table = None
                table_values = []
                
            # Check for DSS File line
            elif line.startswith("DSS File=") and current_boundary is not None:
                current_boundary['DSS File'] = line.split('=', 1)[1].strip()
                
            # Check for table headers
            elif any(line.startswith(t) for t in table_types) and current_boundary is not None:
                # If we were processing a table, save it
                if current_table and table_values:
                    try:
                        df = pd.DataFrame({'Value': table_values})
                        current_tables[current_table_name] = df
                    except Exception as e:
                        logger.warning(f"Error processing previous table: {e}")
                
                # Start new table
                try:
                    current_table = line.split('=')
                    current_table_name = current_table[0].strip()
                    num_values = int(current_table[1])
                    table_values = []
                    
                    # Read the table values
                    rows_needed = (num_values + 9) // 10  # Round up division
                    for _ in range(rows_needed):
                        i += 1
                        if i >= len(lines):
                            break
                        row = lines[i].strip()
                        # Parse fixed-width values (8 characters each)
                        j = 0
                        while j < len(row):
                            value_str = row[j:j+8].strip()
                            if value_str:
                                try:
                                    value = float(value_str)
                                    table_values.append(value)
                                except ValueError:
                                    # Try splitting merged values
                                    parts = re.findall(r'-?\d+\.?\d*', value_str)
                                    table_values.extend([float(p) for p in parts])
                            j += 8
                
                except (ValueError, IndexError) as e:
                    logger.error(f"Error processing table at line {i}: {e}")
                    current_table = None
                    
            i += 1
        
        # Add the last boundary if it exists
        if current_boundary is not None:
            if current_table and table_values:
                try:
                    df = pd.DataFrame({'Value': table_values})
                    current_tables[current_table_name] = df
                except Exception as e:
                    logger.warning(f"Error processing final table: {e}")
            current_boundary['Tables'] = current_tables
            boundary_data.append(current_boundary)
        
        # Create DataFrame
        boundaries_df = pd.DataFrame(boundary_data)
        if not boundaries_df.empty:
            # Split boundary location into components
            location_columns = ['River Name', 'Reach Name', 'River Station', 
                              'Downstream River Station', 'Storage Area Connection',
                              'Storage Area Name', 'Pump Station Name', 
                              'Blank 1', 'Blank 2']
            split_locations = boundaries_df['Boundary Location'].str.split(',', expand=True)
            # Ensure we have the right number of columns
            for i, col in enumerate(location_columns):
                if i < split_locations.shape[1]:
                    boundaries_df[col] = split_locations[i].str.strip()
                else:
                    boundaries_df[col] = ''
            boundaries_df = boundaries_df.drop(columns=['Boundary Location'])
        
        logger.info(f"Successfully extracted boundaries and tables from {unsteady_path}")
        return boundaries_df

    @staticmethod
    @log_call
    def print_boundaries_and_tables(boundaries_df: pd.DataFrame) -> None:
        """
        Print boundary conditions and their associated tables in a formatted, readable way.

        This function is useful for quickly visualizing the complex nested structure of 
        boundary conditions extracted by extract_boundary_and_tables().

        Parameters:
            boundaries_df (pd.DataFrame): DataFrame containing boundary information and 
                                         nested tables data from extract_boundary_and_tables()

        Returns:
            None: Output is printed to console

        Example:
            # Extract boundary conditions and tables
            boundaries_df = RasUnsteady.extract_boundary_and_tables(unsteady_file)
            
            # Print in a formatted way
            print("Detailed boundary conditions and tables:")
            RasUnsteady.print_boundaries_and_tables(boundaries_df)
        """
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_rows', None)
        print("\nBoundaries and Tablesin boundaries_df:")
        for idx, row in boundaries_df.iterrows():
            print(f"\nBoundary {idx+1}:")
            print(f"River Name: {row['River Name']}")
            print(f"Reach Name: {row['Reach Name']}")
            print(f"River Station: {row['River Station']}")
            print(f"DSS File: {row['DSS File']}")
            
            if row['Tables']:
                print("\nTables for this boundary:")
                for table_name, table_df in row['Tables'].items():
                    print(f"\n{table_name}:")
                    print(table_df.to_string())
            print("-" * 80)





    @staticmethod
    def _clean_boundary_selector(value: Optional[Any]) -> Optional[str]:
        """Normalize optional boundary selector values."""
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _detect_boundary_type(lines: List[str], start_idx: int, end_idx: int) -> str:
        """Return the first recognized boundary condition type in a block."""
        for line in lines[start_idx + 1:end_idx]:
            stripped = line.lstrip()
            for keyword, bc_type in RasUnsteady._BOUNDARY_TYPE_KEYWORDS:
                if stripped.startswith(keyword):
                    return bc_type
        return "Unknown"

    @staticmethod
    def _find_boundary_block_end(lines: List[str], start_idx: int, next_start_idx: Optional[int]) -> int:
        """
        Find the exclusive end of a ``Boundary Location=`` block.

        HEC-RAS writes project-level meteorology and non-Newtonian settings
        after the final boundary block in many .u## files. When there is no
        next boundary header, stop before those known global trailers so a
        forced deletion of the final boundary cannot erase project-level
        settings.
        """
        if next_start_idx is not None:
            return next_start_idx

        for i in range(start_idx + 1, len(lines)):
            if lines[i].startswith(RasUnsteady._GLOBAL_TRAILER_PREFIXES):
                return i
        return len(lines)

    @staticmethod
    def _find_boundary_blocks(lines: List[str]) -> List[Dict[str, Any]]:
        """Collect Boundary Location block metadata from an unsteady file."""
        starts = [
            i for i, line in enumerate(lines)
            if line.startswith("Boundary Location=")
        ]
        blocks: List[Dict[str, Any]] = []

        for boundary_index, start_idx in enumerate(starts):
            next_start = starts[boundary_index + 1] if boundary_index + 1 < len(starts) else None
            end_idx = RasUnsteady._find_boundary_block_end(lines, start_idx, next_start)
            loc_value = lines[start_idx][len("Boundary Location="):].rstrip("\r\n")
            parts = [part.strip() for part in loc_value.split(",")]
            blocks.append({
                "boundary_index": boundary_index,
                "start_idx": start_idx,
                "end_idx": end_idx,
                "location": loc_value,
                "parts": parts,
                "bc_type": RasUnsteady._detect_boundary_type(lines, start_idx, end_idx),
            })

        return blocks

    @staticmethod
    def _boundary_block_name(block: Dict[str, Any]) -> str:
        """Return a readable display name for a boundary block."""
        parts = block["parts"]
        if len(parts) >= 8 and parts[7]:
            if len(parts) >= 6 and parts[5]:
                return f"{parts[5]}/{parts[7]}"
            return parts[7]

        river = parts[0] if len(parts) > 0 else ""
        reach = parts[1] if len(parts) > 1 else ""
        station = parts[2] if len(parts) > 2 else ""
        if river or reach or station:
            return "/".join(part for part in (river, reach, station) if part)

        return block["location"].strip()

    @staticmethod
    def _boundary_block_matches(
        block: Dict[str, Any],
        river: Optional[str],
        reach: Optional[str],
        river_station: Optional[str],
        sa_2d_name: Optional[str],
        bc_line: Optional[str],
    ) -> bool:
        """Return True when a boundary block matches the provided selector group."""
        parts = block["parts"]
        if any(selector is not None for selector in (river, reach, river_station)):
            if river is not None and (len(parts) < 1 or parts[0] != river):
                return False
            if reach is not None and (len(parts) < 2 or parts[1] != reach):
                return False
            if river_station is not None and (len(parts) < 3 or parts[2] != river_station):
                return False
            return True

        if any(selector is not None for selector in (sa_2d_name, bc_line)):
            if sa_2d_name is not None and (len(parts) < 6 or parts[5] != sa_2d_name):
                return False
            if bc_line is not None and (len(parts) < 8 or parts[7] != bc_line):
                return False
            return True

        return False

    @staticmethod
    @log_call
    def delete_boundary(
        unsteady_file: Union[str, Path],
        river: Optional[str] = None,
        reach: Optional[str] = None,
        river_station: Optional[str] = None,
        sa_2d_name: Optional[str] = None,
        bc_line: Optional[str] = None,
        boundary_index: Optional[int] = None,
        force: bool = False,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Remove one ``Boundary Location=`` block from a HEC-RAS unsteady flow file.

        The method deletes from the matched ``Boundary Location=`` header through
        the line before the next boundary header. For the final boundary in files
        that carry project-level meteorology or non-Newtonian settings after the
        boundaries, deletion stops before those global trailers.

        Required external boundary guard
        --------------------------------
        ``Flow Hydrograph``, ``Stage Hydrograph``, ``Normal Depth``, and
        ``Rating Curve`` blocks are commonly required upstream/downstream model
        boundaries. To avoid silently producing an uncomputable model, these
        boundary types raise ``ValueError`` unless ``force=True`` is passed.
        Optional/internal boundary types such as ``Lateral Inflow Hydrograph``,
        ``Uniform Lateral Inflow Hydrograph``, observed stage/flow, gate,
        groundwater, navigation dam, rule operation, and precipitation blocks
        may be deleted without ``force``.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character unsteady
            number when a project-bound ``ras_object`` is available.
        river, reach, river_station : str, optional
            1D selector fields. Provided values are matched against the first
            three comma-separated fields of ``Boundary Location=``. Partial
            selectors are allowed but must resolve to exactly one block unless
            ``boundary_index`` disambiguates.
        sa_2d_name, bc_line : str, optional
            2D selector fields. ``sa_2d_name`` matches field index 5 and
            ``bc_line`` matches field index 7 in HEC-RAS 2D boundary location
            records. Partial selectors are allowed with the same ambiguity
            rules as 1D selectors.
        boundary_index : int, optional
            Zero-based positional index among ``Boundary Location=`` blocks.
            Can be used alone as a fallback selector or with selectors to
            disambiguate an otherwise ambiguous match.
        force : bool, default False
            Required to delete likely external upstream/downstream boundary
            types (Flow Hydrograph, Stage Hydrograph, Normal Depth, Rating
            Curve).
        ras_object : optional
            Custom RAS object. When initialized, ``boundaries_df`` is refreshed
            after deletion.

        Returns
        -------
        Dict[str, Any]
            Metadata with keys:

            - ``unsteady_file`` (str): path written
            - ``deleted`` (bool): always True on success
            - ``name`` (str): readable boundary name/location
            - ``matched_location`` (str): raw ``Boundary Location=`` value
            - ``bc_type`` (str): detected boundary condition type
            - ``boundary_index`` (int): zero-based matched block index
            - ``backup_path`` (str): path to the ``.bak`` backup
            - ``lines_removed`` (int): number of lines deleted
            - ``boundaries_df_refreshed`` (bool): True if refresh succeeded
            - ``required_boundary`` (bool): True when the guard classified the
              block as a likely required external boundary

        Raises
        ------
        ValueError
            If selectors are inconsistent, no boundary matches, multiple
            boundaries match without ``boundary_index`` disambiguation, or a
            protected external boundary is selected without ``force=True``.
        FileNotFoundError
            If the resolved unsteady file does not exist.
        """
        river = RasUnsteady._clean_boundary_selector(river)
        reach = RasUnsteady._clean_boundary_selector(reach)
        river_station = RasUnsteady._clean_boundary_selector(river_station)
        sa_2d_name = RasUnsteady._clean_boundary_selector(sa_2d_name)
        bc_line = RasUnsteady._clean_boundary_selector(bc_line)

        has_1d_selector = any(
            selector is not None for selector in (river, reach, river_station)
        )
        has_2d_selector = any(
            selector is not None for selector in (sa_2d_name, bc_line)
        )
        if has_1d_selector and has_2d_selector:
            raise ValueError(
                "Provide either 1D selectors (river, reach, river_station) "
                "or 2D selectors (sa_2d_name, bc_line), not both"
            )

        if boundary_index is not None:
            if isinstance(boundary_index, bool) or not isinstance(boundary_index, int):
                raise ValueError("boundary_index must be a zero-based integer")
            if boundary_index < 0:
                raise ValueError("boundary_index must be >= 0")

        if boundary_index is None and not (has_1d_selector or has_2d_selector):
            raise ValueError(
                "Provide a boundary selector or boundary_index to delete a boundary"
            )

        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        unsteady_path = RasUnsteady._resolve_unsteady_file_path(
            unsteady_file,
            ras_object=ras_obj,
        )
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            lines = f.readlines()

        blocks = RasUnsteady._find_boundary_blocks(lines)
        if not blocks:
            raise ValueError(f"No Boundary Location blocks found in {unsteady_path.name}")

        target_block: Optional[Dict[str, Any]] = None

        if has_1d_selector or has_2d_selector:
            matches = [
                block for block in blocks
                if RasUnsteady._boundary_block_matches(
                    block,
                    river,
                    reach,
                    river_station,
                    sa_2d_name,
                    bc_line,
                )
            ]
            if boundary_index is not None:
                selected = next(
                    (block for block in blocks if block["boundary_index"] == boundary_index),
                    None,
                )
                if selected is None:
                    raise ValueError(
                        f"boundary_index {boundary_index} is out of range; "
                        f"{len(blocks)} boundary blocks found"
                    )
                if selected not in matches:
                    raise ValueError(
                        f"boundary_index {boundary_index} does not match the "
                        "provided boundary selectors"
                    )
                target_block = selected
            else:
                if not matches:
                    selector = (
                        f"river={river!r}, reach={reach!r}, river_station={river_station!r}"
                        if has_1d_selector
                        else f"sa_2d_name={sa_2d_name!r}, bc_line={bc_line!r}"
                    )
                    raise ValueError(
                        f"No boundary matched in {unsteady_path.name} for {selector}"
                    )
                if len(matches) > 1:
                    choices = ", ".join(
                        f"{block['boundary_index']}:{RasUnsteady._boundary_block_name(block)}"
                        for block in matches
                    )
                    raise ValueError(
                        "Boundary selector is ambiguous. Provide boundary_index "
                        f"to disambiguate one of: {choices}"
                    )
                target_block = matches[0]
        else:
            selected = next(
                (block for block in blocks if block["boundary_index"] == boundary_index),
                None,
            )
            if selected is None:
                raise ValueError(
                    f"boundary_index {boundary_index} is out of range; "
                    f"{len(blocks)} boundary blocks found"
                )
            target_block = selected

        if target_block is None:
            raise ValueError("No boundary selected for deletion")

        bc_type = target_block["bc_type"]
        required_boundary = bc_type in RasUnsteady._PROTECTED_BOUNDARY_TYPES
        if required_boundary and not force:
            raise ValueError(
                f"Refusing to delete {bc_type} boundary "
                f"{RasUnsteady._boundary_block_name(target_block)!r} without "
                "force=True because it may be a required upstream/downstream "
                "external boundary"
            )
        if required_boundary and force:
            logger.warning(
                "Deleting likely required external %s boundary %s from %s because force=True",
                bc_type,
                RasUnsteady._boundary_block_name(target_block),
                unsteady_path.name,
            )

        start_idx = target_block["start_idx"]
        end_idx = target_block["end_idx"]
        if end_idx <= start_idx:
            raise ValueError(
                f"Invalid boundary block extent for index {target_block['boundary_index']}"
            )

        backup_path = Path(str(unsteady_path) + ".bak")
        shutil.copy2(unsteady_path, backup_path)
        lines_removed = end_idx - start_idx
        del lines[start_idx:end_idx]

        with open(unsteady_path, "w", encoding="utf-8", newline="") as f:
            f.writelines(lines)

        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        boundary_name = RasUnsteady._boundary_block_name(target_block)
        logger.info(
            "Deleted boundary %s (%s) from %s: %d lines removed",
            boundary_name,
            bc_type,
            unsteady_path.name,
            lines_removed,
        )

        return {
            "unsteady_file": str(unsteady_path),
            "deleted": True,
            "name": boundary_name,
            "matched_location": target_block["location"],
            "bc_type": bc_type,
            "boundary_index": target_block["boundary_index"],
            "backup_path": str(backup_path),
            "lines_removed": lines_removed,
            "boundaries_df_refreshed": boundaries_df_refreshed,
            "required_boundary": required_boundary,
        }


# Additional functions from the AWS webinar where the code was developed
# Need to add examples

    @staticmethod
    @log_call
    def identify_tables(lines: List[str]) -> List[Tuple[str, int, int]]:
        """
        Identify the start and end line numbers of tables in an unsteady flow file.

        HEC-RAS unsteady flow files contain numeric tables in a fixed-width format.
        This function locates these tables within the file and provides their positions.

        Parameters:
            lines (List[str]): List of file lines (typically from file.readlines())

        Returns:
            List[Tuple[str, int, int]]: List of tuples where each tuple contains:
                - table_name (str): The type of table (e.g., 'Flow Hydrograph=')
                - start_line (int): Line number where the table data begins
                - end_line (int): Line number where the table data ends

        Example:
            # Read the unsteady flow file
            with open(new_unsteady_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                
            # Identify tables in the file
            tables = RasUnsteady.identify_tables(lines)
            print(f"Identified {len(tables)} tables in the unsteady flow file.")
        """
        table_types = [
            'Flow Hydrograph=',
            'Gate Openings=',
            'Stage Hydrograph=',
            'Uniform Lateral Inflow=',
            'Lateral Inflow Hydrograph=',
            'Precipitation Hydrograph=',
            'Rating Curve='
        ]
        tables = []
        current_table = None

        for i, line in enumerate(lines):
            if any(table_type in line for table_type in table_types):
                if current_table:
                    tables.append((current_table[0], current_table[1], i-1))
                table_name = line.strip().split('=')[0] + '='
                try:
                    num_values = int(line.strip().split('=')[1])
                    current_table = (table_name, i+1, num_values)
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing table header at line {i}: {e}")
                    continue
        
        if current_table:
            tables.append((current_table[0], current_table[1], 
                          current_table[1] + (current_table[2] + 9) // 10))
        
        logger.debug(f"Identified {len(tables)} tables in the file")
        return tables

    @staticmethod
    @log_call
    def parse_fixed_width_table(lines: List[str], start: int, end: int) -> pd.DataFrame:
        """
        Parse a fixed-width table from an unsteady flow file into a pandas DataFrame.

        HEC-RAS uses a fixed-width format (8 characters per value) for numeric tables.
        This function converts this format into a DataFrame for easier manipulation.

        Parameters:
            lines (List[str]): List of file lines (from file.readlines())
            start (int): Starting line number for table data
            end (int): Ending line number for table data

        Returns:
            pd.DataFrame: DataFrame with a single column 'Value' containing the parsed numeric values

        Example:
            # Identify tables in the file
            tables = RasUnsteady.identify_tables(lines)
            
            # Parse a specific table (e.g., first flow hydrograph)
            table_name, start_line, end_line = tables[0]
            table_df = RasUnsteady.parse_fixed_width_table(lines, start_line, end_line)
        """
        data = []
        for line in lines[start:end]:
            # Skip empty lines or lines that don't contain numeric data
            if not line.strip() or not any(c.isdigit() for c in line):
                continue
                
            # Split the line into 8-character columns and process each value
            values = []
            for i in range(0, len(line.rstrip()), 8):
                value_str = line[i:i+8].strip()
                if value_str:  # Only process non-empty strings
                    try:
                        # Handle special cases where numbers are run together
                        if len(value_str) > 8:
                            # Use regex to find all numbers in the string
                            parts = re.findall(r'-?\d+\.?\d*', value_str)
                            values.extend([float(p) for p in parts])
                        else:
                            values.append(float(value_str))
                    except ValueError:
                        # If conversion fails, try to extract any valid numbers from the string
                        parts = re.findall(r'-?\d+\.?\d*', value_str)
                        if parts:
                            values.extend([float(p) for p in parts])
                        else:
                            logger.debug(f"Skipping non-numeric value: {value_str}")
                            continue
            
            # Only add to data if we found valid numeric values
            if values:
                data.extend(values)
        
        if not data:
            logger.warning("No numeric data found in table section")
            return pd.DataFrame(columns=['Value'])
            
        return pd.DataFrame(data, columns=['Value'])
    
    @staticmethod
    @log_call
    def extract_tables(unsteady_file: str, ras_object: Optional[Any] = None) -> Dict[str, pd.DataFrame]:
        """
        Extract all tables from an unsteady flow file and return them as DataFrames.

        This function combines identify_tables() and parse_fixed_width_table() to extract
        all tables from an unsteady flow file in a single operation.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            Dict[str, pd.DataFrame]: Dictionary where:
                - Keys are table names (e.g., 'Flow Hydrograph=')
                - Values are DataFrames with a 'Value' column containing numeric data

        Example:
            # Extract all tables from the unsteady flow file
            all_tables = RasUnsteady.extract_tables(new_unsteady_file)
            print(f"Extracted {len(all_tables)} tables from the file.")
            
            # Access a specific table
            flow_tables = [name for name in all_tables.keys() if 'Flow Hydrograph=' in name]
            if flow_tables:
                flow_df = all_tables[flow_tables[0]]
                print(f"Flow table has {len(flow_df)} values")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        unsteady_path = Path(unsteady_file)
        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise
        
        # Fix: Use RasUnsteady.identify_tables 
        tables = RasUnsteady.identify_tables(lines)
        extracted_tables = {}
        
        for table_name, start, end in tables:
            df = RasUnsteady.parse_fixed_width_table(lines, start, end)
            extracted_tables[table_name] = df
            logger.debug(f"Extracted table '{table_name}' with {len(df)} values")
        
        return extracted_tables

    @staticmethod
    @log_call
    def write_table_to_file(unsteady_file: str, table_name: str, df: pd.DataFrame, 
                           start_line: int, ras_object: Optional[Any] = None) -> None:
        """
        Write an updated table back to an unsteady flow file in the required fixed-width format.

        This function takes a modified DataFrame and writes it back to the unsteady flow file,
        preserving the 8-character fixed-width format that HEC-RAS requires.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file
            table_name (str): Name of the table to update (e.g., 'Flow Hydrograph=')
            df (pd.DataFrame): DataFrame containing the updated values with a 'Value' column
            start_line (int): Line number where the table data begins in the file
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            None: The function modifies the file in-place

        Example:
            # Identify tables in the unsteady flow file
            tables = RasUnsteady.identify_tables(lines)
            table_name, start_line, end_line = tables[0]
            
            # Parse and modify the table
            table_df = RasUnsteady.parse_fixed_width_table(lines, start_line, end_line)
            table_df['Value'] = table_df['Value'] * 0.75  # Scale values to 75%
            
            # Write modified table back to the file
            RasUnsteady.write_table_to_file(new_unsteady_file, table_name, table_df, start_line)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        unsteady_path = Path(unsteady_file)
        try:
            with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise
        
        # Format values into fixed-width strings
        formatted_values = []
        for i in range(0, len(df), 10):
            row = df['Value'].iloc[i:i+10]
            formatted_row = ''.join(f'{value:8.2f}' for value in row)
            formatted_values.append(formatted_row + '\n')
        
        # Replace old table with new formatted values
        lines[start_line:start_line+len(formatted_values)] = formatted_values
        
        try:
            with open(unsteady_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)
            logger.info(f"Successfully updated table '{table_name}' in {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
            raise
        except IOError as e:
            logger.error(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
            raise

    @staticmethod
    @log_call
    def set_precipitation_hyetograph(
        unsteady_file: Union[str, Path],
        hyetograph_df: pd.DataFrame,
        boundary_name: Optional[str] = None,
        ras_object: Optional[Any] = None
    ) -> None:
        """
        Set precipitation hyetograph in an unsteady flow file from a DataFrame.

        This method writes hyetograph data directly to the "Precipitation Hydrograph="
        section in HEC-RAS unsteady flow files (.u##). It automatically detects the
        time interval from the DataFrame and formats values in HEC-RAS fixed-width format.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g., "01")
        hyetograph_df : pd.DataFrame
            DataFrame with columns:
            - 'hour': Time in hours from storm start (end of interval)
            - 'incremental_depth': Precipitation depth for this interval (inches)
            - 'cumulative_depth': Cumulative precipitation depth (inches)
        boundary_name : str, optional
            Name of the 2D Flow Area or Storage Area to update.
            If None, updates the first Precipitation Hydrograph found.
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        None
            The function modifies the file in-place.

        Raises
        ------
        ValueError
            If DataFrame is missing required columns
        FileNotFoundError
            If unsteady flow file not found

        Example
        -------
        >>> from ras_commander import RasUnsteady, init_ras_project
        >>> from ras_commander.precip import StormGenerator
        >>>
        >>> # Generate hyetograph
        >>> gen = StormGenerator.download_from_coordinates(29.76, -95.37)
        >>> hyeto = gen.generate_hyetograph(
        ...     total_depth_inches=17.0,
        ...     duration_hours=24,
        ...     position_percent=50
        ... )
        >>>
        >>> # Write to unsteady file
        >>> RasUnsteady.set_precipitation_hyetograph("project.u01", hyeto)

        Notes
        -----
        **DataFrame Format**:
        - All methods in ras-commander.precip return DataFrames with the required columns
        - Atlas14Storm, FrequencyStorm, ScsTypeStorm (from hms-commander) also use this format

        **Interval Detection**:
        - Interval is calculated from `hour` column spacing (e.g., 1.0 → "1HOUR", 0.5 → "30MIN")
        - The Interval= line immediately preceding the Precipitation Hydrograph section is updated

        **Fixed-Width Format**:
        - Values formatted as 8-character fixed-width fields (8.2f)
        - 10 values per line
        - Precipitation Hydrograph uses sequential depth values (not time-depth pairs)
        - Count = number of depth values; timing from Interval= line

        **Depth Conservation**:
        - Total depth is logged for verification
        - Should match the total_depth_inches used in generation

        See Also
        --------
        StormGenerator.generate_hyetograph : Generate design storm hyetograph
        Atlas14Storm.generate_hyetograph : HMS-equivalent hyetograph (from hms-commander)
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass  # Allow standalone use without initialized project

        # Resolve unsteady file path
        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError("Cannot resolve unsteady number without an initialized ras_object")
            # It's an unsteady number, resolve to full path
            unsteady_num = unsteady_file.zfill(2)
            unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{unsteady_num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # Validate DataFrame columns
        required_columns = ['hour', 'incremental_depth', 'cumulative_depth']
        missing_columns = [col for col in required_columns if col not in hyetograph_df.columns]
        if missing_columns:
            raise ValueError(
                f"DataFrame missing required columns: {missing_columns}. "
                f"Required columns: {required_columns}"
            )

        # Calculate interval from hour column
        hours = hyetograph_df['hour'].values
        if len(hours) < 2:
            raise ValueError("DataFrame must have at least 2 rows to determine interval")

        interval_hours = hours[1] - hours[0]

        # Convert interval to HEC-RAS format string
        if interval_hours >= 1.0:
            if interval_hours == int(interval_hours):
                interval_str = f"{int(interval_hours)}HOUR"
            else:
                # Convert to minutes if fractional hour
                interval_min = int(interval_hours * 60)
                interval_str = f"{interval_min}MIN"
        else:
            interval_min = int(interval_hours * 60)
            interval_str = f"{interval_min}MIN"

        # Read the file
        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Get precipitation values (incremental depths)
        precip_values = hyetograph_df['incremental_depth'].values

        # Calculate total depth for logging
        total_depth = hyetograph_df['cumulative_depth'].iloc[-1]

        # Precipitation Hydrograph uses sequential depth values (NOT time-depth pairs).
        # Timing is determined by the Interval= line. Count = number of depth values.
        num_values = len(precip_values)

        # Format into fixed-width lines (8 chars each, 10 values per line)
        formatted_lines = []
        for i in range(0, len(precip_values), 10):
            row_values = precip_values[i:i+10]
            formatted_row = ''.join(f'{value:8.2f}' for value in row_values)
            formatted_lines.append(formatted_row + '\n')

        # Find the Precipitation Hydrograph section(s)
        precip_sections = []
        for i, line in enumerate(lines):
            if line.startswith('Precipitation Hydrograph='):
                precip_sections.append(i)

        if not precip_sections:
            raise ValueError(
                f"No 'Precipitation Hydrograph=' section found in {unsteady_path}. "
                "Ensure the unsteady file has a precipitation boundary condition defined."
            )

        # Determine which section to update
        if boundary_name is not None:
            # Find the section associated with the specified boundary
            target_section = None
            for precip_idx in precip_sections:
                # Search backwards for Boundary Location
                for j in range(precip_idx - 1, max(0, precip_idx - 50), -1):
                    if lines[j].startswith('Boundary Location='):
                        # Check if boundary name matches (usually in position 6 for storage area)
                        loc_parts = lines[j].replace('Boundary Location=', '').split(',')
                        for part in loc_parts:
                            if boundary_name.strip().lower() in part.strip().lower():
                                target_section = precip_idx
                                break
                        break
                if target_section is not None:
                    break

            if target_section is None:
                logger.warning(
                    f"Boundary '{boundary_name}' not found. "
                    f"Updating first Precipitation Hydrograph section."
                )
                target_section = precip_sections[0]
        else:
            target_section = precip_sections[0]

        precip_line_idx = target_section

        # Find the end of the old data section by scanning for next keyword line
        # Data starts right after the Precipitation Hydrograph= line
        old_data_start = precip_line_idx + 1
        old_data_end = old_data_start

        # Scan forward to find where data ends (next line with '=' keyword)
        for k in range(old_data_start, len(lines)):
            line = lines[k]
            # Data lines are numeric only; keyword lines contain '='
            if '=' in line:
                old_data_end = k
                break
            # Also check for empty lines that might mark end of section
            if not line.strip():
                # Empty line might be end of section, but continue checking
                pass
        else:
            # Reached end of file
            old_data_end = len(lines)

        # Update the Precipitation Hydrograph header line with new count
        new_precip_line = f"Precipitation Hydrograph= {num_values} \n"

        # Search backwards from Precipitation Hydrograph line for Interval line
        interval_updated = False
        for j in range(precip_line_idx - 1, max(0, precip_line_idx - 20), -1):
            if lines[j].startswith('Interval='):
                old_interval = lines[j].strip()
                lines[j] = f"Interval={interval_str}\n"
                interval_updated = True
                logger.debug(f"Updated {old_interval} to Interval={interval_str}")
                break

        if not interval_updated:
            logger.warning(
                f"Could not find Interval= line before Precipitation Hydrograph at line {precip_line_idx + 1}. "
                "Interval not updated."
            )

        # Replace the old data section with new formatted data
        # 1. Update header line
        lines[precip_line_idx] = new_precip_line

        # 2. Replace data lines
        new_lines = lines[:old_data_start] + formatted_lines + lines[old_data_end:]

        # Write updated content back to file
        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        logger.info(
            f"Updated Precipitation Hydrograph in {unsteady_path.name}: "
            f"{num_values} time steps, interval={interval_str}, "
            f"total depth={total_depth:.4f} inches"
        )

    @staticmethod
    @log_call
    def set_constant_precipitation(
        unsteady_file: Union[str, Path],
        value: float = 1.0,
        units: str = "in/hr",
        ras_object: Optional[Any] = None,
    ) -> None:
        """
        Configure constant (spatially and temporally uniform) precipitation.

        .. note::
            Constant precipitation is a **testing and 2D model-commissioning
            convenience**, not an engineering-deliverable forcing. Real event
            modeling uses a time-varying hyetograph
            (:meth:`set_precipitation_hyetograph`) or a gridded record
            (:meth:`set_gridded_precipitation` /
            :meth:`configure_gridded_dss_precipitation`). A uniform rate is
            useful for rain-on-grid mesh shakedown, where
            ``depth = rate * duration`` makes the 2D solver mass balance
            trivially hand-checkable, for numerical / stability sensitivity
            runs, and for cheap CI smoke-test fixtures.

        Writes the ``Precipitation Mode`` switch and the constant-mode
        ``Met BC=Precipitation|...`` keys, and updates the
        ``<unsteady_file>.hdf`` sidecar attributes when it exists.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g. "01").
        value : float, default 1.0
            Constant precipitation rate (must be finite and >= 0).
        units : {"in/hr", "mm/hr"}, default "in/hr"
            Constant precipitation rate units.
        ras_object : optional
            Custom RAS object used to resolve an unsteady number.

        Returns
        -------
        None
            Modifies the .u## file in-place and updates the .u##.hdf sidecar
            when present.

        Raises
        ------
        ValueError
            If ``value`` is not a finite, non-negative real number, or ``units``
            is not ``"in/hr"`` or ``"mm/hr"``.

        Examples
        --------
        >>> # Commission a 2D rain-on-grid mesh with 1 in/hr uniform rain
        >>> RasUnsteady.set_constant_precipitation("01", value=1.0, units="in/hr")

        See Also
        --------
        set_precipitation_hyetograph : Time-varying hyetograph (real events).
        set_gridded_precipitation : Gridded NetCDF precipitation (real events).
        configure_gridded_dss_precipitation : Gridded DSS precipitation.
        """
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            raise ValueError(f"value must be a real number, got {type(value).__name__}")
        constant_value = float(value)
        if not np.isfinite(constant_value):
            raise ValueError(f"value must be finite, got {constant_value!r}")
        if constant_value < 0:
            raise ValueError(f"value must be >= 0, got {constant_value!r}")
        if units not in {"in/hr", "mm/hr"}:
            raise ValueError("units must be either 'in/hr' or 'mm/hr'")

        unsteady_path = RasUnsteady._resolve_unsteady_file_path(
            unsteady_file,
            ras_object=ras_object,
        )
        # HEC-RAS writes constant values compactly (e.g. "1", "0.25").
        formatted_value = f"{constant_value:g}"

        logger.info(
            "Configuring constant precipitation in %s: value=%s, units=%s",
            unsteady_path, formatted_value, units,
        )

        with open(unsteady_path, "r", encoding="utf-8", errors="ignore") as file:
            lines = file.readlines()

        new_keys = {
            "Precipitation Mode": "Enable",
            "Met BC=Precipitation|Mode": "Constant",
            "Met BC=Precipitation|Constant Value": formatted_value,
            "Met BC=Precipitation|Constant Units": units,
        }

        # Update existing keys in place; track those still needing insertion.
        remaining = dict(new_keys)
        for i, line in enumerate(lines):
            for key in list(remaining):
                if line.startswith(key + "="):
                    lines[i] = f"{key}={remaining.pop(key)}\n"

        # Insert any missing keys at a stable meteorology location.
        if remaining:
            insert_at = RasUnsteady._get_default_met_insert_index(lines)
            block = [f"{k}={v}\n" for k, v in remaining.items()]
            lines[insert_at:insert_at] = block

        with open(unsteady_path, "w", encoding="utf-8") as file:
            file.writelines(lines)

        hdf_path = Path(str(unsteady_path) + ".hdf")
        if hdf_path.exists():
            RasUnsteady._update_constant_precipitation_hdf(
                hdf_path, constant_value, units
            )
        else:
            logger.warning(
                f"HDF file not found: {hdf_path} - constant precipitation "
                "attributes not written"
            )

        ras_obj = ras_object or ras
        if ras_obj is not None and hasattr(ras_obj, "get_unsteady_entries"):
            try:
                ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            except Exception as exc:
                logger.debug(f"unsteady_df refresh skipped: {exc}")

    @staticmethod
    def _update_constant_precipitation_hdf(
        hdf_path: Path,
        value: float,
        units: str,
    ) -> None:
        """Write constant-mode precipitation attributes to an unsteady .u##.hdf."""
        import h5py

        met_path = "Event Conditions/Meteorology"
        precip_grp_path = f"{met_path}/Precipitation"
        logger.info(f"Updating constant precipitation HDF attributes: {hdf_path}")
        try:
            with h5py.File(hdf_path, "a") as hdf_file:
                hdf_file.require_group("Event Conditions")
                hdf_file.require_group(met_path)
                precip_grp = hdf_file.require_group(precip_grp_path)

                precip_grp.attrs["Enabled"] = np.uint8(1)
                precip_grp.attrs["Mode"] = np.bytes_("Constant")
                precip_grp.attrs["Constant Value"] = np.float64(value)
                precip_grp.attrs["Constant Units"] = np.bytes_(units)

                RasUnsteady._ensure_meteorology_attributes_dataset(hdf_file, met_path)
        except Exception as e:
            logger.error(f"Error updating constant precipitation HDF attributes: {e}")
            raise

    @staticmethod
    def _update_precipitation_hdf(
        hdf_path: Path,
        netcdf_path: Path,
        netcdf_rel_path: str,
        interpolation: str = "Nearest",
        dataset_name: Optional[str] = None,
    ) -> None:
        """
        Import precipitation raster data into HDF in HEC-RAS 6.6 format.

        This function imports gridded precipitation from NetCDF into the HDF file
        in the exact format HEC-RAS 6.6 creates when using "Import Raster Data" in the GUI.

        The data is transformed from instantaneous rates to cumulative totals and
        flattened from (time, y, x) to (time, rows*cols) shape.

        HEC-RAS 6.6 Format Requirements (verified against GUI import):
        - Timestamps in ISO 8601 format: 'YYYY-MM-DD HH:MM:SS' (|S19)
        - No separate Timestamp dataset (timestamps only in Times attribute)
        - Values dataset: chunked, gzip compressed, fillvalue=nan
        - NoData attribute as float32(-9999.0)
        - Grid extent attributes on Values dataset (not on Imported Raster Data group)
        - Meteorology/Attributes dataset preserved for proper indexing

        Parameters
        ----------
        hdf_path : Path
            Path to the unsteady HDF file (.u##.hdf)
        netcdf_path : Path
            Absolute path to the NetCDF precipitation file
        netcdf_rel_path : str
            Relative path string for HDF attributes (e.g., ".\\Precipitation\\file.nc")
        interpolation : str
            Interpolation method ("Bilinear" or "Nearest"). Default is "Nearest"
            which matches HEC-RAS 6.6 GUI default.
        dataset_name : str, optional
            NetCDF data variable name to import. If omitted, a common
            precipitation variable name is detected from the file.
        """
        import h5py
        import numpy as np
        import uuid

        try:
            import xarray as xr
        except ImportError:
            logger.warning("xarray not available - cannot import precipitation into HDF")
            return

        logger.info(f"Updating precipitation in HDF: {hdf_path}")

        # Read the NetCDF file
        if not netcdf_path.exists():
            logger.warning(f"NetCDF file not found: {netcdf_path}")
            return

        try:
            with RasUnsteady._open_netcdf_dataset(netcdf_path, xr) as ds:
                precip_var = RasUnsteady._find_precipitation_variable(ds, dataset_name)
                if precip_var is None:
                    logger.warning(f"Could not find precipitation variable in {netcdf_path}")
                    return

                precip_data = ds[precip_var].values  # Shape: (time, y, x)
                times = ds['time'].values
                x_coords = ds['x'].values
                y_coords = ds['y'].values
                srs_wkt = RasUnsteady._get_netcdf_crs_wkt(ds, precip_var)

            n_times, n_rows, n_cols = precip_data.shape
            logger.info(f"  NetCDF: {n_times} timesteps, {n_rows}x{n_cols} grid")

        except ValueError as e:
            logger.error(f"Invalid NetCDF precipitation metadata: {e}")
            raise
        except Exception as e:
            logger.warning(f"Error reading NetCDF file: {e}")
            return

        # Calculate raster extent parameters
        cellsize = abs(x_coords[1] - x_coords[0]) if len(x_coords) > 1 else 2000.0
        x_min = float(x_coords.min())
        y_min = float(y_coords.min())
        y_max = float(y_coords.max())

        # Raster bounds (cell edges, not centers)
        raster_left = x_min - cellsize / 2
        raster_top = y_max + cellsize / 2

        # Transform data: flatten spatial dims and convert to cumulative
        # Shape: (time, y, x) -> (time, rows*cols)
        precip_flat = precip_data.reshape(n_times, n_rows * n_cols)

        # Replace NaN with 0 for cumsum calculation
        precip_flat = np.nan_to_num(precip_flat, nan=0.0).astype(np.float32)

        # HEC-RAS 6.6 writes the first cumulative row as zero, then integrates
        # instantaneous rates by each raster interval.
        interval_hours = RasUnsteady._netcdf_interval_hours(times)
        precip_amounts = precip_flat * interval_hours[:, np.newaxis]
        precip_cumulative = np.cumsum(precip_amounts, axis=0).astype(np.float32)

        # Create timestamp strings in HEC-RAS 6.6 format (ISO 8601)
        # Format: 'YYYY-MM-DD HH:MM:SS' stored as |S19 fixed-length bytes
        import pandas as pd
        timestamps = pd.to_datetime(times)
        timestamp_strs = [t.strftime('%Y-%m-%d %H:%M:%S') for t in timestamps]

        # Generate GUID for dataset
        guid = str(uuid.uuid4())

        # Update the HDF file
        try:
            with h5py.File(hdf_path, 'r+') as f:
                met_path = 'Event Conditions/Meteorology'
                precip_grp_path = f'{met_path}/Precipitation'

                # Create parent groups if they don't exist
                if precip_grp_path not in f:
                    logger.info(f"Creating precipitation group hierarchy in HDF")
                    if 'Event Conditions' not in f:
                        f.create_group('Event Conditions')
                    if met_path not in f:
                        f.create_group(met_path)
                    f.create_group(precip_grp_path)

                precip_grp = f[precip_grp_path]

                # Update Precipitation group attributes
                # HEC-RAS 6.6 uses uint8 for Enabled
                precip_grp.attrs['Enabled'] = np.uint8(1)
                precip_grp.attrs['Mode'] = np.bytes_('Gridded')
                precip_grp.attrs['Source'] = np.bytes_('GDAL Raster File(s)')
                precip_grp.attrs['GDAL Filename'] = np.bytes_(netcdf_rel_path)
                precip_grp.attrs['GDAL Datasetname'] = np.bytes_(precip_var)
                precip_grp.attrs['GDAL Filter'] = np.bytes_('')
                precip_grp.attrs['GDAL Folder'] = np.bytes_('')
                precip_grp.attrs['Interpolation Method'] = np.bytes_(interpolation)

                # HEC-RAS 6.6 requires Meteorology/Attributes dataset for indexing
                RasUnsteady._ensure_meteorology_attributes_dataset(f, met_path)

                # Create/recreate Imported Raster Data group
                # HEC-RAS 6.6: NO attributes on this group (grid attrs go on Values dataset)
                raster_grp_path = f'{precip_grp_path}/Imported Raster Data'
                if raster_grp_path in f:
                    del f[raster_grp_path]
                raster_grp = f.create_group(raster_grp_path)

                # HEC-RAS 6.6: NO separate Timestamp dataset (timestamps only in Times attribute)

                # Number of cells for dataset shape
                n_cells = n_rows * n_cols

                # Common attributes for Values datasets (HEC-RAS 6.6 format)
                values_attrs = {
                    'Data Type': np.bytes_('cumulative'),
                    'GUID': np.bytes_(guid),
                    'NoData': np.float32(-9999.0),  # HEC-RAS 6.6 uses float32
                    'Projection': np.bytes_(srs_wkt),
                    'Raster Cellsize': np.float64(cellsize),
                    'Raster Cols': np.int32(n_cols),
                    'Raster Left': np.float64(raster_left),
                    'Raster Rows': np.int32(n_rows),
                    'Raster Top': np.float64(raster_top),
                    'Rate Time Units': np.bytes_('Hour'),
                    'Storage Configuration': np.bytes_('Sequential'),
                    'Time Series Data Type': np.bytes_('Amount'),
                    'Times': np.array(timestamp_strs, dtype='S19'),  # HEC-RAS 6.6: ISO format |S19
                    'Units': np.bytes_('mm'),
                    'Version': np.bytes_('1.0'),
                }

                # Create Values dataset - HEC-RAS 6.6 format:
                # - Chunked as single chunk (n_times, n_cells)
                # - gzip compression level 1
                # - fillvalue = nan
                values_ds = raster_grp.create_dataset(
                    'Values',
                    data=precip_cumulative,
                    dtype=np.float32,
                    chunks=(n_times, n_cells),
                    compression='gzip',
                    compression_opts=1,
                    fillvalue=np.nan
                )
                for attr_name, attr_val in values_attrs.items():
                    values_ds.attrs[attr_name] = attr_val

                # Create Values (Vertical) dataset - same format
                values_vert_ds = raster_grp.create_dataset(
                    'Values (Vertical)',
                    data=precip_cumulative,
                    dtype=np.float32,
                    chunks=(n_times, n_cells),
                    compression='gzip',
                    compression_opts=1,
                    fillvalue=np.nan
                )
                for attr_name, attr_val in values_attrs.items():
                    values_vert_ds.attrs[attr_name] = attr_val

                logger.info(f"  Imported {n_times} timesteps, {n_cells} cells (cumulative)")
                logger.info(f"  Precip range: {precip_cumulative.min():.1f} - {precip_cumulative.max():.1f} mm")

        except Exception as e:
            logger.error(f"Error updating HDF file: {e}")
            raise

    @staticmethod
    def _format_met_dss_filename(dss_filename: Union[str, Path], unsteady_path: Path) -> str:
        """
        Normalize a DSS filename for RAS meteorology text/HDF attributes.

        Relative paths are written with RAS' conventional ``.\\`` prefix. Absolute
        paths under the unsteady file folder are converted to project-relative
        paths; absolute paths elsewhere are preserved.
        """
        raw_filename = str(dss_filename).strip()
        if not raw_filename:
            raise ValueError("dss_filename must not be empty")

        dss_path = Path(raw_filename)
        if dss_path.is_absolute():
            try:
                relative_path = dss_path.relative_to(unsteady_path.parent)
                return f".\\{relative_path}".replace("/", "\\")
            except ValueError:
                return str(dss_path)

        normalized = raw_filename.replace("/", "\\")
        if normalized.startswith((".\\", "..\\", "\\")):
            return normalized
        return f".\\{normalized}"

    @staticmethod
    def _normalize_gridded_interpolation(interpolation: str) -> str:
        """Normalize optional gridded interpolation names used by HEC-RAS."""
        interpolation_value = str(interpolation or "").strip()
        if not interpolation_value:
            return ""

        valid_values = {
            "nearest": "Nearest",
            "bilinear": "Bilinear",
        }
        normalized = valid_values.get(interpolation_value.lower())
        if normalized is None:
            raise ValueError(
                "interpolation must be '', 'Nearest', or 'Bilinear'"
            )
        return normalized

    @staticmethod
    def _get_default_met_insert_index(lines: List[str]) -> int:
        """Choose a stable insertion point for meteorologic BC metadata."""
        for i, line in enumerate(lines):
            if line.startswith("Boundary Location="):
                return i
        for i, line in enumerate(lines):
            if line.startswith("Program Version="):
                return i + 1
        for i, line in enumerate(lines):
            if line.startswith("Flow Title="):
                return i + 1
        return len(lines)

    @staticmethod
    def _ensure_meteorology_attributes_dataset(hdf_file: Any, met_path: str) -> None:
        """Ensure HEC-RAS' Meteorology/Attributes dataset indexes precipitation."""
        attrs_path = f"{met_path}/Attributes"
        attr_dtype = np.dtype([("Variable", "S32"), ("Group", "S42")])
        precip_row = np.array(
            [(b"Precipitation", b"Event Conditions/Meteorology/Precipitation")],
            dtype=attr_dtype,
        )

        if attrs_path not in hdf_file:
            hdf_file.create_dataset(
                attrs_path,
                data=precip_row,
                chunks=(1,),
                maxshape=(None,),
                compression="gzip",
                compression_opts=1,
            )
            return

        attrs_ds = hdf_file[attrs_path]
        if attrs_ds.dtype.names is None or "Variable" not in attrs_ds.dtype.names:
            logger.debug(
                "Meteorology/Attributes dataset has unexpected dtype; "
                "leaving existing dataset unchanged"
            )
            return

        existing = attrs_ds[...]
        for row in existing:
            variable = bytes(row["Variable"]).decode("utf-8", errors="ignore").rstrip("\x00")
            if variable == "Precipitation":
                return

        new_data = np.empty(len(existing) + 1, dtype=attr_dtype)
        for i, row in enumerate(existing):
            group_value = row["Group"] if "Group" in existing.dtype.names else b""
            new_data[i] = (bytes(row["Variable"]), bytes(group_value))
        new_data[-1] = precip_row[0]

        del hdf_file[attrs_path]
        hdf_file.create_dataset(
            attrs_path,
            data=new_data,
            chunks=(len(new_data),),
            maxshape=(None,),
            compression="gzip",
            compression_opts=1,
        )

    @staticmethod
    def _update_gridded_dss_precipitation_hdf(
        unsteady_path: Path,
        dss_filename: str,
        dss_pathname: str,
        interpolation: str = "",
    ) -> Path:
        """
        Write gridded DSS precipitation metadata to the unsteady sidecar HDF.

        This writes only configuration attributes. It does not write DSS grid
        records or import raster precipitation values.
        """
        import h5py

        hdf_path = Path(str(unsteady_path) + ".hdf")
        met_path = "Event Conditions/Meteorology"
        precip_grp_path = f"{met_path}/Precipitation"

        with h5py.File(hdf_path, "a") as hdf_file:
            if "Event Conditions" not in hdf_file:
                hdf_file.create_group("Event Conditions")
            if met_path not in hdf_file:
                hdf_file.create_group(met_path)
            if precip_grp_path not in hdf_file:
                hdf_file.create_group(precip_grp_path)

            precip_grp = hdf_file[precip_grp_path]
            precip_grp.attrs["Enabled"] = np.uint8(1)
            precip_grp.attrs["Mode"] = np.bytes_("Gridded")
            precip_grp.attrs["Source"] = np.bytes_("DSS")
            precip_grp.attrs["DSS Filename"] = np.bytes_(dss_filename)
            precip_grp.attrs["DSS Pathname"] = np.bytes_(dss_pathname)
            if interpolation:
                precip_grp.attrs["Interpolation Method"] = np.bytes_(interpolation)
            elif "Interpolation Method" in precip_grp.attrs:
                del precip_grp.attrs["Interpolation Method"]

            for stale_attr in (
                "GDAL Filename",
                "GDAL Datasetname",
                "GDAL Filter",
                "GDAL Folder",
            ):
                if stale_attr in precip_grp.attrs:
                    del precip_grp.attrs[stale_attr]

            RasUnsteady._ensure_meteorology_attributes_dataset(hdf_file, met_path)

        return hdf_path

    @staticmethod
    @log_call
    def configure_gridded_dss_precipitation(
        unsteady_file: Path,
        dss_filename: str,
        dss_pathname: str,
        interpolation: str = "",
    ) -> None:
        """
        Configure a .u## file to reference gridded DSS precipitation.

        This helper wires an existing DSS grid file into the HEC-RAS unsteady
        flow configuration. It does not write DSS data.

        Parameters
        ----------
        unsteady_file : Path
            Path to the unsteady flow file (.u##).
        dss_filename : str
            DSS filename for the gridded precipitation source. Relative values
            are written using RAS-style backslashes (for example,
            ``.\\Precipitation\\precip.dss``). Absolute paths inside the
            unsteady file folder are converted to that relative form; absolute
            paths elsewhere are preserved.
        dss_pathname : str
            DSS pathname for the precipitation grid record.
        interpolation : str, optional
            Spatial interpolation method. Use ``"Nearest"`` or ``"Bilinear"``.
            The default empty string leaves the RAS default unset in the .u##.

        Returns
        -------
        None
            The .u## file and its .u##.hdf sidecar metadata are updated in place.
        """
        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")
        unsteady_path = unsteady_path.resolve()

        dss_pathname = str(dss_pathname).strip()
        if not dss_pathname:
            raise ValueError("dss_pathname must not be empty")

        dss_filename_str = RasUnsteady._format_met_dss_filename(
            dss_filename,
            unsteady_path,
        )
        interpolation_value = RasUnsteady._normalize_gridded_interpolation(interpolation)

        desired_lines = [
            "Precipitation Mode=Enable\n",
            "Met BC=Precipitation|Mode=Gridded\n",
            "Met BC=Precipitation|Gridded Source=DSS\n",
        ]
        if interpolation_value:
            desired_lines.append(
                f"Met BC=Precipitation|Gridded Interpolation={interpolation_value}\n"
            )
        desired_lines.extend([
            f"Met BC=Precipitation|Gridded DSS Filename={dss_filename_str}\n",
            f"Met BC=Precipitation|Gridded DSS Pathname={dss_pathname}\n",
        ])

        remove_prefixes = (
            "Precipitation Mode=",
            "Met BC=Precipitation|Mode=",
            "Met BC=Precipitation|Gridded Source=",
            "Met BC=Precipitation|Gridded Interpolation=",
            "Met BC=Precipitation|Gridded DSS Filename=",
            "Met BC=Precipitation|Gridded DSS Pathname=",
            "Met BC=Precipitation|Gridded GDAL Filename=",
            "Met BC=Precipitation|Gridded GDAL Datasetname=",
            "Met BC=Precipitation|Gridded GDAL Filter=",
            "Met BC=Precipitation|Gridded GDAL Folder=",
        )
        anchor_prefixes = remove_prefixes + ("Met BC=Precipitation|",)

        with open(unsteady_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        insert_index = None
        for i, line in enumerate(lines):
            if line.startswith(anchor_prefixes):
                insert_index = i
                break
        if insert_index is None:
            insert_index = RasUnsteady._get_default_met_insert_index(lines)

        filtered_lines = []
        removed_before_insert = 0
        for i, line in enumerate(lines):
            if line.startswith(remove_prefixes):
                if i < insert_index:
                    removed_before_insert += 1
                continue
            filtered_lines.append(line)

        insert_index = max(0, insert_index - removed_before_insert)
        if insert_index == len(filtered_lines) and filtered_lines:
            if not filtered_lines[-1].endswith(("\n", "\r")):
                filtered_lines[-1] = f"{filtered_lines[-1]}\n"

        updated_lines = (
            filtered_lines[:insert_index]
            + desired_lines
            + filtered_lines[insert_index:]
        )

        with open(unsteady_path, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)

        hdf_path = RasUnsteady._update_gridded_dss_precipitation_hdf(
            unsteady_path=unsteady_path,
            dss_filename=dss_filename_str,
            dss_pathname=dss_pathname,
            interpolation=interpolation_value,
        )

        logger.info(
            f"Configured gridded DSS precipitation in {unsteady_path.name}: "
            f"{dss_filename_str}, {dss_pathname}; HDF metadata={hdf_path.name}"
        )

    @staticmethod
    def _decode_hdf_attr_value(value: Any) -> Any:
        """Decode scalar HDF attribute values to plain Python objects."""
        if isinstance(value, np.bytes_):
            return value.decode("utf-8", errors="ignore")
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return [RasUnsteady._decode_hdf_attr_value(item) for item in value]
        return value

    @staticmethod
    @log_call
    def set_gridded_precipitation(
        unsteady_file: Union[str, Path],
        netcdf_path: Union[str, Path],
        interpolation: str = "Bilinear",
        ras_object: Optional[Any] = None,
        dataset_name: Optional[str] = None,
    ) -> None:
        """
        Configure gridded precipitation from a NetCDF file in an unsteady flow file.

        This function modifies the meteorologic boundary conditions in an HEC-RAS
        unsteady flow file to use GDAL Raster (NetCDF) gridded precipitation instead
        of DSS or constant values.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g., "04")
        netcdf_path : str or Path
            Path to the NetCDF precipitation file. Can be absolute or relative to
            the project folder. The file should be in SHG projection (EPSG:5070)
            for proper import into HEC-RAS.
        interpolation : str, default "Bilinear"
            Spatial interpolation method. Options: "Bilinear", "Nearest"
        ras_object : optional
            Custom RAS object to use instead of the global one
        dataset_name : str, optional
            NetCDF data variable name. If omitted and the NetCDF exists, a
            common precipitation variable name is detected and written to the
            HEC-RAS ``Gridded GDAL Group`` field.

        Returns
        -------
        None
            The function modifies the file in-place.

        Examples
        --------
        >>> from ras_commander import RasUnsteady, init_ras_project
        >>> init_ras_project("/path/to/project", "7.0")
        >>>
        >>> # Set gridded precipitation from AORC NetCDF
        >>> RasUnsteady.set_gridded_precipitation(
        ...     unsteady_file="04",
        ...     netcdf_path="Precipitation/aorc_april2020_shg.nc"
        ... )

        Notes
        -----
        - The NetCDF file must be in SHG projection (EPSG:5070) for HEC-RAS import
        - Use PrecipAorc.download() with default settings to create compatible files
        - This function preserves existing DSS configuration but switches source to GDAL
        - The plan file's simulation dates should match the NetCDF time range
        - Precipitation data is automatically imported into the HDF file in the format
          HEC-RAS expects (cumulative totals, flattened grid)

        See Also
        --------
        PrecipAorc.download : Download AORC precipitation data as NetCDF
        HdfProject.get_project_bounds_latlon : Get project bounds for precipitation query
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Resolve unsteady file path
        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError("Cannot resolve unsteady number without an initialized ras_object")
            # It's an unsteady number, resolve to full path
            unsteady_num = unsteady_file.zfill(2)
            unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{unsteady_num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        interpolation = RasUnsteady._normalize_gridded_interpolation(interpolation)

        # Convert netcdf_path to relative path if within project folder
        netcdf_path = Path(netcdf_path)
        if netcdf_path.is_absolute():
            netcdf_full_path = netcdf_path
            try:
                netcdf_rel = netcdf_path.relative_to(ras_obj.project_folder)
                netcdf_str = f".\\{netcdf_rel}".replace("/", "\\")
            except ValueError:
                netcdf_str = str(netcdf_path)
        else:
            netcdf_full_path = ras_obj.project_folder / netcdf_path
            netcdf_str = f".\\{netcdf_path}".replace("/", "\\")

        if dataset_name is None and netcdf_full_path.exists():
            try:
                import xarray as xr

                with RasUnsteady._open_netcdf_dataset(netcdf_full_path, xr) as ds:
                    dataset_name = RasUnsteady._find_precipitation_variable(ds)
            except Exception as e:
                logger.warning(f"Could not detect NetCDF precipitation variable: {e}")

        logger.info(f"Configuring gridded precipitation in {unsteady_path}")
        logger.info(f"  NetCDF file: {netcdf_str}")
        logger.info(f"  Interpolation: {interpolation}")
        if dataset_name:
            logger.info(f"  Dataset: {dataset_name}")

        # Read the file
        with open(unsteady_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Track what we need to update
        precip_mode_updated = False
        mode_updated = False
        source_updated = False
        source_line = -1
        interp_updated = False
        interp_line = -1
        gdal_filename_updated = False
        gdal_filename_line = -1
        gdal_group_updated = False
        gdal_group_insert_line = -1

        for i, line in enumerate(lines):
            # Enable top-level Meteorological Data precipitation
            if line.startswith("Precipitation Mode="):
                lines[i] = "Precipitation Mode=Enable\n"
                precip_mode_updated = True

            # Ensure the precipitation variable itself is gridded
            elif line.startswith("Met BC=Precipitation|Mode="):
                lines[i] = "Met BC=Precipitation|Mode=Gridded\n"
                mode_updated = True

            # Update Gridded Source to GDAL Raster File(s)
            elif line.startswith("Met BC=Precipitation|Gridded Source="):
                lines[i] = "Met BC=Precipitation|Gridded Source=GDAL Raster File(s)\n"
                source_updated = True
                source_line = i
                logger.debug(f"Updated Gridded Source at line {i+1}")

            # Update or add Gridded Interpolation
            elif line.startswith("Met BC=Precipitation|Gridded Interpolation="):
                lines[i] = f"Met BC=Precipitation|Gridded Interpolation={interpolation}\n"
                interp_updated = True
                interp_line = i
                logger.debug(f"Updated Gridded Interpolation at line {i+1}")

            # Update or track GDAL Filename line
            elif line.startswith("Met BC=Precipitation|Gridded GDAL Filename="):
                lines[i] = f"Met BC=Precipitation|Gridded GDAL Filename={netcdf_str}\n"
                gdal_filename_updated = True
                gdal_filename_line = i + 1
                gdal_group_insert_line = i + 1
                logger.debug(f"Updated GDAL Filename at line {i+1}")

            # Update GDAL Group/Dataset line
            elif line.startswith((
                "Met BC=Precipitation|Gridded GDAL Group=",
                "Met BC=Precipitation|Gridded GDAL Datasetname=",
            )):
                if dataset_name:
                    lines[i] = f"Met BC=Precipitation|Gridded GDAL Group={dataset_name}\n"
                gdal_group_updated = True
                logger.debug(f"Updated GDAL Group at line {i+1}")

            # Track location after DSS Pathname for inserting GDAL Filename if needed
            elif line.startswith("Met BC=Precipitation|Gridded DSS Pathname="):
                gdal_filename_line = i + 1

        # If Interpolation line didn't exist, insert it after Gridded Source
        if not interp_updated and source_line >= 0:
            lines.insert(source_line + 1, f"Met BC=Precipitation|Gridded Interpolation={interpolation}\n")
            interp_updated = True
            interp_line = source_line + 1
            # Adjust line numbers for subsequent inserts
            if gdal_filename_line > source_line:
                gdal_filename_line += 1
            logger.debug(f"Inserted Gridded Interpolation at line {source_line+2}")

        # If GDAL Filename line didn't exist, insert it after the GDAL source
        # block. Empty GUI GDAL fixtures do not have DSS pathname lines, so
        # that older insertion anchor is optional.
        if not gdal_filename_updated and gdal_filename_line > 0:
            lines.insert(gdal_filename_line, f"Met BC=Precipitation|Gridded GDAL Filename={netcdf_str}\n")
            gdal_filename_updated = True
            gdal_group_insert_line = gdal_filename_line + 1
            logger.debug(f"Inserted GDAL Filename at line {gdal_filename_line+1}")
            if interp_line >= gdal_filename_line:
                interp_line += 1
        elif not gdal_filename_updated:
            insert_after = interp_line if interp_line >= 0 else source_line
            if insert_after >= 0:
                gdal_filename_line = insert_after + 1
                lines.insert(gdal_filename_line, f"Met BC=Precipitation|Gridded GDAL Filename={netcdf_str}\n")
                gdal_filename_updated = True
                gdal_group_insert_line = gdal_filename_line + 1
                logger.debug(f"Inserted GDAL Filename at line {gdal_filename_line+1}")

        if dataset_name and not gdal_group_updated:
            insert_at = gdal_group_insert_line if gdal_filename_updated else -1
            if insert_at > 0:
                lines.insert(insert_at, f"Met BC=Precipitation|Gridded GDAL Group={dataset_name}\n")
                gdal_group_updated = True
                logger.debug(f"Inserted GDAL Group at line {insert_at+1}")

        # Verify all updates were made
        if not precip_mode_updated:
            logger.warning("Could not find 'Precipitation Mode=' line")
        if not mode_updated:
            logger.warning("Could not find 'Met BC=Precipitation|Mode=' line")
        if not source_updated:
            logger.warning("Could not find 'Met BC=Precipitation|Gridded Source=' line")
        if not gdal_filename_updated:
            logger.warning("Could not add GDAL Filename line")

        # Write the updated file
        with open(unsteady_path, 'w', encoding='utf-8', errors='replace', newline='\r\n') as f:
            f.writelines(lines)

        logger.info(f"Successfully configured gridded precipitation in {unsteady_path}")

        # Import precipitation data into the HDF file
        hdf_path = Path(str(unsteady_path) + '.hdf')
        if hdf_path.exists():
            RasUnsteady._update_precipitation_hdf(
                hdf_path=hdf_path,
                netcdf_path=netcdf_full_path,
                netcdf_rel_path=netcdf_str,
                interpolation=interpolation,
                dataset_name=dataset_name,
            )
        else:
            logger.warning(f"HDF file not found: {hdf_path} - precipitation data not imported")

    @staticmethod
    def _format_met_float(value: Optional[float]) -> str:
        """Format optional floats for ras-commander-authored meteorological metadata."""
        if value is None:
            return ""
        if pd.isna(value):
            return ""
        formatted = f"{float(value):.8f}".rstrip("0").rstrip(".")
        return "0" if formatted in ("", "-0") else formatted

    @staticmethod
    def _parse_met_float(value: str) -> float:
        """Parse optional floats from meteorological metadata."""
        text = value.strip()
        if not text:
            return np.nan
        return float(text)

    @staticmethod
    def _validate_station_name(name: str) -> str:
        """Validate and normalize a meteorological station name."""
        station_name = str(name).strip()
        if not station_name:
            raise ValueError("Meteorological station name cannot be blank")
        if any(char in station_name for char in [",", "\r", "\n", "="]):
            raise ValueError("Meteorological station name cannot contain comma, newline, or equals characters")
        return station_name

    @staticmethod
    def _meteorological_station_lines(
        name: str,
        x: float,
        y: float,
        longitude: Optional[float] = None,
        latitude: Optional[float] = None,
        height_m: Optional[float] = None
    ) -> List[str]:
        """Build native HEC-RAS meteorological station metadata lines."""
        station_name = RasUnsteady._validate_station_name(name)
        return [
            f"Met Station Name={station_name}\n",
            f"Met Station Gauge Height={RasUnsteady._format_met_float(height_m)}\n",
            (
                "Met Station LL="
                f"{RasUnsteady._format_met_float(longitude)},{RasUnsteady._format_met_float(latitude)}\n"
            ),
            f"Met Station XY={RasUnsteady._format_met_float(x)},{RasUnsteady._format_met_float(y)}\n",
        ]

    @staticmethod
    def _parse_meteorological_station_line(line: str, line_number: int, unsteady_path: Path) -> Optional[Dict[str, Any]]:
        """Parse a legacy single-line ras-commander meteorological station line."""
        if line.startswith("Met Station="):
            raw_value = line.split("=", 1)[1].strip()
        elif line.startswith("Meteorological Station="):
            raw_value = line.split("=", 1)[1].strip()
        else:
            return None

        parts = [part.strip() for part in raw_value.split(",")]
        if len(parts) < 3:
            logger.warning(f"Skipping malformed meteorological station line {line_number}: {line.strip()}")
            return None

        while len(parts) < 6:
            parts.append("")

        return {
            "name": parts[0],
            "x": RasUnsteady._parse_met_float(parts[1]),
            "y": RasUnsteady._parse_met_float(parts[2]),
            "longitude": RasUnsteady._parse_met_float(parts[3]),
            "latitude": RasUnsteady._parse_met_float(parts[4]),
            "height_m": RasUnsteady._parse_met_float(parts[5]),
            "line_number": line_number,
            "unsteady_file": str(unsteady_path),
        }

    @staticmethod
    def _parse_native_meteorological_stations(lines: List[str], unsteady_path: Path) -> List[Dict[str, Any]]:
        """Parse native HEC-RAS meteorological station line groups."""
        records = []
        name_prefix = "Met Station Name="
        height_prefix = "Met Station Gauge Height="
        ll_prefix = "Met Station LL="
        xy_prefix = "Met Station XY="
        station_prefixes = (name_prefix, height_prefix, ll_prefix, xy_prefix)
        stop_prefixes = (
            "Met Point Raster Parameters=",
            "Precipitation Mode=",
            "Wind Mode=",
            "Air Density Mode=",
            "Wave Mode=",
            "Met BC=",
        )

        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.startswith(name_prefix):
                i += 1
                continue

            station_name = line[len(name_prefix):].strip()
            record: Dict[str, Any] = {
                "name": station_name,
                "x": np.nan,
                "y": np.nan,
                "longitude": np.nan,
                "latitude": np.nan,
                "height_m": np.nan,
                "line_number": i + 1,
                "unsteady_file": str(unsteady_path),
            }

            j = i + 1
            while j < len(lines):
                current_line = lines[j]
                if current_line.startswith(name_prefix):
                    break
                if current_line.startswith(height_prefix):
                    record["height_m"] = RasUnsteady._parse_met_float(current_line[len(height_prefix):])
                elif current_line.startswith(ll_prefix):
                    parts = [part.strip() for part in current_line[len(ll_prefix):].split(",")]
                    if len(parts) >= 2:
                        record["longitude"] = RasUnsteady._parse_met_float(parts[0])
                        record["latitude"] = RasUnsteady._parse_met_float(parts[1])
                elif current_line.startswith(xy_prefix):
                    parts = [part.strip() for part in current_line[len(xy_prefix):].split(",")]
                    if len(parts) >= 2:
                        record["x"] = RasUnsteady._parse_met_float(parts[0])
                        record["y"] = RasUnsteady._parse_met_float(parts[1])
                elif current_line.startswith(stop_prefixes):
                    break
                elif current_line.startswith("Met Station") and not current_line.startswith(station_prefixes):
                    break
                j += 1

            records.append(record)
            i = j

        return records

    @staticmethod
    def _remove_meteorological_station_block(lines: List[str], station_name: str) -> List[str]:
        """Remove native or legacy station metadata for a station name."""
        name_prefix = "Met Station Name="
        native_station_prefixes = (
            "Met Station Gauge Height=",
            "Met Station LL=",
            "Met Station XY=",
        )
        normalized_name = station_name.lower()
        cleaned_lines: List[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            if line.startswith(name_prefix) and line[len(name_prefix):].strip().lower() == normalized_name:
                i += 1
                while i < len(lines) and lines[i].startswith(native_station_prefixes):
                    i += 1
                continue

            parsed_legacy = RasUnsteady._parse_meteorological_station_line(line, i + 1, Path(""))
            if parsed_legacy is not None and parsed_legacy["name"].lower() == normalized_name:
                i += 1
                continue

            cleaned_lines.append(line)
            i += 1

        return cleaned_lines

    @staticmethod
    def _find_station_insert_index(lines: List[str]) -> int:
        """Find the native HEC-RAS insertion location for station metadata."""
        last_station_line = -1
        for i, line in enumerate(lines):
            if line.startswith((
                "Met Station Name=",
                "Met Station Gauge Height=",
                "Met Station LL=",
                "Met Station XY=",
            )):
                last_station_line = i
        if last_station_line >= 0:
            return last_station_line + 1

        for i, line in enumerate(lines):
            if line.startswith("Met Point Raster Parameters="):
                return i
        for i, line in enumerate(lines):
            if line.startswith("Precipitation Mode="):
                return i
        for i, line in enumerate(lines):
            if line.startswith("Met BC="):
                return i
        return len(lines)

    @staticmethod
    def _find_met_insert_index(lines: List[str]) -> int:
        """Find a stable insertion location for meteorological boundary metadata."""
        for i, line in enumerate(lines):
            if line.startswith("Met Point Raster Parameters="):
                return i + 1
        for i, line in enumerate(lines):
            if line.startswith("Precipitation Mode="):
                return i
        for i, line in enumerate(lines):
            if line.startswith("Met BC="):
                return i
        return len(lines)

    @staticmethod
    def _set_met_bc_line(lines: List[str], met_type: str, setting: str, value: str) -> None:
        """Update or insert a meteorological boundary condition setting."""
        prefix = f"Met BC={met_type}|{setting}="
        for i, line in enumerate(lines):
            if line.startswith(prefix):
                lines[i] = f"{prefix}{value}\n"
                return

        insert_idx = len(lines)
        for i, line in enumerate(lines):
            if line.startswith(f"Met BC={met_type}|"):
                insert_idx = i + 1
        lines.insert(insert_idx, f"{prefix}{value}\n")

    @staticmethod
    def _get_met_bc_value(lines: List[str], met_type: str, setting: str) -> Optional[str]:
        """Get a meteorological boundary condition setting value."""
        prefix = f"Met BC={met_type}|{setting}="
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        return None

    @staticmethod
    def _format_interval_from_hours(interval_hours: float) -> str:
        """Convert a numeric interval in hours to a HEC-RAS interval string."""
        interval_hours = float(interval_hours)
        if interval_hours <= 0:
            raise ValueError("Time interval must be positive")

        rounded_hours = round(interval_hours)
        if interval_hours >= 1.0 and abs(interval_hours - rounded_hours) < 1e-9:
            return f"{int(rounded_hours)}HOUR"

        interval_minutes = round(interval_hours * 60.0)
        if interval_minutes <= 0:
            raise ValueError("Time interval must be at least one minute")
        if abs(interval_hours - (interval_minutes / 60.0)) > 1e-6:
            raise ValueError("Time interval must resolve to whole minutes")
        return f"{int(interval_minutes)}MIN"

    @staticmethod
    def _detect_et_value_column(et_df: pd.DataFrame, value_column: Optional[str]) -> str:
        """Detect the value column for point ET input."""
        if value_column is not None:
            if value_column not in et_df.columns:
                raise ValueError(f"ET value column not found: {value_column}")
            return value_column

        candidates = [
            "evapotranspiration",
            "potential_evapotranspiration",
            "potential_et",
            "pet",
            "et",
            "value",
        ]
        lower_to_column = {str(column).lower(): column for column in et_df.columns}
        for candidate in candidates:
            if candidate in lower_to_column:
                return lower_to_column[candidate]

        numeric_columns = [
            column for column in et_df.columns
            if pd.api.types.is_numeric_dtype(et_df[column]) and str(column).lower() != "hour"
        ]
        if len(numeric_columns) == 1:
            return numeric_columns[0]

        raise ValueError(
            "Could not detect ET value column. Pass value_column or use one of: "
            "evapotranspiration, potential_evapotranspiration, potential_et, pet, et, value"
        )

    @staticmethod
    def _detect_et_times(
        et_df: pd.DataFrame,
        time_column: Optional[str]
    ) -> Tuple[np.ndarray, str, Optional[str]]:
        """Return elapsed hours, interval string, and optional start timestamp."""
        if time_column is not None:
            if time_column == "index":
                raw_times = et_df.index
            elif time_column in et_df.columns:
                raw_times = et_df[time_column]
            else:
                raise ValueError(f"ET time column not found: {time_column}")
            timestamps = pd.to_datetime(raw_times, errors="raise")
        elif isinstance(et_df.index, pd.DatetimeIndex):
            timestamps = pd.to_datetime(et_df.index, errors="raise")
        elif "hour" in et_df.columns:
            hours = pd.to_numeric(et_df["hour"], errors="raise").to_numpy(dtype=float)
            diffs = np.diff(hours)
            if len(diffs) == 0:
                raise ValueError("ET DataFrame must have at least 2 rows to determine interval")
            if np.any(diffs <= 0):
                raise ValueError("ET hour values must be strictly increasing")
            interval_hours = float(diffs[0])
            if np.max(np.abs(diffs - interval_hours)) > 1e-9:
                raise ValueError("ET hour values must have a uniform interval")
            return hours, RasUnsteady._format_interval_from_hours(interval_hours), None
        else:
            candidate_columns = ["datetime", "date_time", "timestamp", "time", "date"]
            lower_to_column = {str(column).lower(): column for column in et_df.columns}
            timestamp_column = None
            for candidate in candidate_columns:
                if candidate in lower_to_column:
                    timestamp_column = lower_to_column[candidate]
                    break
            if timestamp_column is None:
                raise ValueError(
                    "ET DataFrame must have a DatetimeIndex, a time_column, a datetime/time column, or an hour column"
                )
            timestamps = pd.to_datetime(et_df[timestamp_column], errors="raise")

        timestamp_series = pd.Series(timestamps)
        if len(timestamp_series) < 2:
            raise ValueError("ET DataFrame must have at least 2 rows to determine interval")
        if timestamp_series.isna().any():
            raise ValueError("ET timestamps cannot contain null values")

        diffs = timestamp_series.diff().dropna().dt.total_seconds().to_numpy(dtype=float) / 3600.0
        if np.any(diffs <= 0):
            raise ValueError("ET timestamps must be strictly increasing")
        interval_hours = float(diffs[0])
        if np.max(np.abs(diffs - interval_hours)) > 1e-9:
            raise ValueError("ET timestamps must have a uniform interval")

        elapsed_hours = (
            (timestamp_series - timestamp_series.iloc[0]).dt.total_seconds().to_numpy(dtype=float) / 3600.0
        )
        start_time = timestamp_series.iloc[0].strftime("%Y-%m-%d %H:%M:%S")
        return elapsed_hours, RasUnsteady._format_interval_from_hours(interval_hours), start_time

    @staticmethod
    def _normalise_point_et_dataframe(
        et_df: pd.DataFrame,
        value_column: Optional[str],
        time_column: Optional[str]
    ) -> Tuple[np.ndarray, np.ndarray, str, Optional[str]]:
        """Validate and normalize point ET input to hours, values, interval, and start time."""
        if not isinstance(et_df, pd.DataFrame):
            raise TypeError("et_df must be a pandas DataFrame")
        if len(et_df) < 2:
            raise ValueError("ET DataFrame must have at least 2 rows")

        detected_value_column = RasUnsteady._detect_et_value_column(et_df, value_column)
        values = pd.to_numeric(et_df[detected_value_column], errors="raise").to_numpy(dtype=float)
        if np.any(pd.isna(values)):
            raise ValueError("ET values cannot contain null values")

        hours, interval_str, start_time = RasUnsteady._detect_et_times(et_df, time_column)
        if len(hours) != len(values):
            raise ValueError("ET time and value arrays must have the same length")
        return hours, values, interval_str, start_time

    @staticmethod
    def _format_point_et_values(hours: np.ndarray, values: np.ndarray) -> List[str]:
        """Format point ET elapsed-hour/value pairs as chunked metadata lines."""
        paired_values: List[float] = []
        for hour, value in zip(hours, values):
            paired_values.append(float(hour))
            paired_values.append(float(value))

        formatted_lines = []
        for i in range(0, len(paired_values), 20):
            chunk = paired_values[i:i + 20]
            chunk_text = ",".join(RasUnsteady._format_met_float(value) for value in chunk)
            formatted_lines.append(f"Met BC=Evapotranspiration|Point Time Series Values={chunk_text}\n")
        return formatted_lines

    @staticmethod
    def _remove_point_et_block(lines: List[str], station_name: str) -> List[str]:
        """Remove an existing ras-commander-authored point ET block for a station."""
        start_prefix = "Met BC=Evapotranspiration|Point Time Series="
        end_prefix = "Met BC=Evapotranspiration|Point Time Series End="
        normalized_name = station_name.lower()
        cleaned_lines: List[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            if line.startswith(start_prefix):
                existing_name = line[len(start_prefix):].strip()
                if existing_name.lower() == normalized_name:
                    i += 1
                    while i < len(lines):
                        if lines[i].startswith(end_prefix):
                            i += 1
                            break
                        if lines[i].startswith(start_prefix):
                            break
                        i += 1
                    continue
            cleaned_lines.append(line)
            i += 1

        return cleaned_lines

    @staticmethod
    def _insert_point_et_block(lines: List[str], block_lines: List[str]) -> None:
        """Insert point ET block after the Evapotranspiration Met BC settings."""
        insert_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("Met BC=Evapotranspiration|"):
                insert_idx = i + 1
        if insert_idx < 0:
            insert_idx = RasUnsteady._find_met_insert_index(lines)
        lines[insert_idx:insert_idx] = block_lines

    @staticmethod
    @log_call
    def set_meteorological_station(
        unsteady_file: Union[str, Path],
        name: str,
        x: float,
        y: float,
        longitude: Optional[float] = None,
        latitude: Optional[float] = None,
        height_m: Optional[float] = None,
        ras_object: Optional[Any] = None
    ) -> None:
        """
        Create or update a meteorological station definition in an unsteady flow file.

        This writes the native HEC-RAS station metadata lines alongside the
        meteorological block. Existing precipitation settings are not modified.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g., "01").
        name : str
            Meteorological station name.
        x, y : float
            Project coordinates for the station.
        longitude, latitude : float, optional
            Geographic coordinates for the station.
        height_m : float, optional
            Station height in meters. HEC-RAS requires this for wind, but not ET.
        ras_object : optional
            Custom RAS object to use instead of the global one.
        """
        station_name = RasUnsteady._validate_station_name(name)
        unsteady_path = RasUnsteady._resolve_unsteady_file_path(unsteady_file, ras_object)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        station_lines = RasUnsteady._meteorological_station_lines(
            name=station_name,
            x=x,
            y=y,
            longitude=longitude,
            latitude=latitude,
            height_m=height_m,
        )

        lines = RasUnsteady._remove_meteorological_station_block(lines, station_name)
        insert_idx = RasUnsteady._find_station_insert_index(lines)
        lines[insert_idx:insert_idx] = station_lines

        with open(unsteady_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        logger.info(f"Updated meteorological station '{station_name}' in {unsteady_path}")

    @staticmethod
    @log_call
    def get_meteorological_stations(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Parse meteorological station definitions from an unsteady flow file.

        Returns
        -------
        pandas.DataFrame
            Columns: name, x, y, longitude, latitude, height_m, line_number,
            unsteady_file.
        """
        unsteady_path = RasUnsteady._resolve_unsteady_file_path(unsteady_file, ras_object)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        records = RasUnsteady._parse_native_meteorological_stations(lines, unsteady_path)
        native_names = {record["name"].lower() for record in records}
        for i, line in enumerate(lines, start=1):
            parsed = RasUnsteady._parse_meteorological_station_line(line, i, unsteady_path)
            if parsed is not None and parsed["name"].lower() not in native_names:
                records.append(parsed)

        columns = ["name", "x", "y", "longitude", "latitude", "height_m", "line_number", "unsteady_file"]
        return pd.DataFrame(records, columns=columns)

    @staticmethod
    @log_call
    def set_point_evapotranspiration(
        unsteady_file: Union[str, Path],
        station_name: str,
        et_df: pd.DataFrame,
        value_column: Optional[str] = None,
        time_column: Optional[str] = None,
        units: str = "mm/day",
        interpolation: str = "Nearest",
        x: Optional[float] = None,
        y: Optional[float] = None,
        longitude: Optional[float] = None,
        latitude: Optional[float] = None,
        height_m: Optional[float] = None,
        ras_object: Optional[Any] = None
    ) -> None:
        """
        Set point evapotranspiration mode and write station time-series data.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g., "01").
        station_name : str
            Meteorological station name used by the ET time series.
        et_df : pandas.DataFrame
            ET time series. Provide either a DatetimeIndex, a datetime/time column,
            or an ``hour`` column. Values are detected from common ET column names
            or can be specified with ``value_column``.
        value_column : str, optional
            ET value column. Defaults to common names such as ``evapotranspiration``,
            ``potential_et``, ``pet``, ``et``, or ``value``.
        time_column : str, optional
            Datetime column name. Use ``"index"`` to force the DataFrame index.
        units : str, default "mm/day"
            ET units written to the meteorological block.
        interpolation : str, default "Nearest"
            Point interpolation method for the ET meteorological boundary condition.
        x, y, longitude, latitude, height_m : float, optional
            Station metadata. If ``x`` and ``y`` are provided, the station definition
            is created or updated before the ET series is written.
        ras_object : optional
            Custom RAS object to use instead of the global one.
        """
        station_name = RasUnsteady._validate_station_name(station_name)
        if (x is None) ^ (y is None):
            raise ValueError("Both x and y are required when creating/updating a station from ET data")

        unsteady_path = RasUnsteady._resolve_unsteady_file_path(unsteady_file, ras_object)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        hours, values, interval_str, start_time = RasUnsteady._normalise_point_et_dataframe(
            et_df=et_df,
            value_column=value_column,
            time_column=time_column,
        )

        with open(unsteady_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        if x is not None and y is not None:
            station_lines = RasUnsteady._meteorological_station_lines(
                name=station_name,
                x=x,
                y=y,
                longitude=longitude,
                latitude=latitude,
                height_m=height_m,
            )
            lines = RasUnsteady._remove_meteorological_station_block(lines, station_name)
            insert_idx = RasUnsteady._find_station_insert_index(lines)
            lines[insert_idx:insert_idx] = station_lines

        RasUnsteady._set_met_bc_line(lines, "Evapotranspiration", "Mode", "Point Gage")
        RasUnsteady._set_met_bc_line(lines, "Evapotranspiration", "Constant Units", units)
        RasUnsteady._set_met_bc_line(lines, "Evapotranspiration", "Point Interpolation", interpolation)

        block_lines = [
            f"Met BC=Evapotranspiration|Point Time Series={station_name}\n",
            f"Met BC=Evapotranspiration|Point Time Series Interval={interval_str}\n",
            f"Met BC=Evapotranspiration|Point Time Series Units={units}\n",
            f"Met BC=Evapotranspiration|Point Time Series Count={len(values)}\n",
        ]
        if start_time is not None:
            block_lines.append(f"Met BC=Evapotranspiration|Point Time Series Start={start_time}\n")
        block_lines.extend(RasUnsteady._format_point_et_values(hours, values))
        block_lines.append(f"Met BC=Evapotranspiration|Point Time Series End={station_name}\n")

        lines = RasUnsteady._remove_point_et_block(lines, station_name)
        RasUnsteady._insert_point_et_block(lines, block_lines)

        with open(unsteady_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        logger.info(
            f"Configured point ET for station '{station_name}' in {unsteady_path} "
            f"({len(values)} values, interval {interval_str}, units {units})"
        )

    @staticmethod
    @log_call
    def get_point_evapotranspiration(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Parse ras-commander-authored point evapotranspiration data from an unsteady file.

        Returns
        -------
        pandas.DataFrame
            Columns: station_name, hour, value, interval, units, start_time,
            datetime, mode, point_interpolation, line_number, unsteady_file.
        """
        unsteady_path = RasUnsteady._resolve_unsteady_file_path(unsteady_file, ras_object)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        mode = RasUnsteady._get_met_bc_value(lines, "Evapotranspiration", "Mode")
        point_interpolation = RasUnsteady._get_met_bc_value(lines, "Evapotranspiration", "Point Interpolation")

        start_prefix = "Met BC=Evapotranspiration|Point Time Series="
        interval_prefix = "Met BC=Evapotranspiration|Point Time Series Interval="
        units_prefix = "Met BC=Evapotranspiration|Point Time Series Units="
        count_prefix = "Met BC=Evapotranspiration|Point Time Series Count="
        start_time_prefix = "Met BC=Evapotranspiration|Point Time Series Start="
        values_prefix = "Met BC=Evapotranspiration|Point Time Series Values="
        end_prefix = "Met BC=Evapotranspiration|Point Time Series End="

        records = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.startswith(start_prefix):
                i += 1
                continue

            station_name = line[len(start_prefix):].strip()
            line_number = i + 1
            interval = None
            units = None
            count = None
            start_time = None
            paired_values: List[float] = []
            i += 1

            while i < len(lines):
                current_line = lines[i]
                if current_line.startswith(end_prefix):
                    i += 1
                    break
                if current_line.startswith(start_prefix):
                    break
                if current_line.startswith(interval_prefix):
                    interval = current_line[len(interval_prefix):].strip()
                elif current_line.startswith(units_prefix):
                    units = current_line[len(units_prefix):].strip()
                elif current_line.startswith(count_prefix):
                    count = int(current_line[len(count_prefix):].strip())
                elif current_line.startswith(start_time_prefix):
                    start_time = current_line[len(start_time_prefix):].strip()
                elif current_line.startswith(values_prefix):
                    raw_values = current_line[len(values_prefix):].strip()
                    if raw_values:
                        paired_values.extend(float(value) for value in raw_values.split(",") if value.strip())
                i += 1

            if len(paired_values) % 2 != 0:
                raise ValueError(f"Point ET series for station '{station_name}' has an odd number of numeric values")

            value_pairs = list(zip(paired_values[0::2], paired_values[1::2]))
            if count is not None and count != len(value_pairs):
                raise ValueError(
                    f"Point ET count mismatch for station '{station_name}': expected {count}, found {len(value_pairs)}"
                )

            start_timestamp = pd.to_datetime(start_time, errors="coerce") if start_time else pd.NaT
            for hour, value in value_pairs:
                timestamp = pd.NaT
                if not pd.isna(start_timestamp):
                    timestamp = start_timestamp + pd.to_timedelta(float(hour), unit="h")
                records.append({
                    "station_name": station_name,
                    "hour": float(hour),
                    "value": float(value),
                    "interval": interval,
                    "units": units,
                    "start_time": start_time,
                    "datetime": timestamp,
                    "mode": mode,
                    "point_interpolation": point_interpolation,
                    "line_number": line_number,
                    "unsteady_file": str(unsteady_path),
                })

        columns = [
            "station_name",
            "hour",
            "value",
            "interval",
            "units",
            "start_time",
            "datetime",
            "mode",
            "point_interpolation",
            "line_number",
            "unsteady_file",
        ]
        return pd.DataFrame(records, columns=columns)

    # ==========================================================================
    # DSS Boundary Condition Functions
    # ==========================================================================

    @staticmethod
    @log_call
    def get_dss_boundaries(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Extract all DSS-linked boundary conditions from an unsteady flow file.

        This function parses .u## files and extracts boundary conditions that use
        DSS files (Use DSS=True), including the full DSS path information needed
        for updating precipitation scenarios.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        pd.DataFrame
            DataFrame with columns:
            - river: River name
            - reach: Reach name
            - station: River station
            - bc_type: Boundary condition type (Flow Hydrograph, Lateral Inflow, etc.)
            - interval: Time interval (e.g., 5MIN)
            - dss_file: DSS file path
            - dss_path: Full DSS path (//A/B/C/D/E/F/)
            - dss_part_a: DSS Part A (project)
            - dss_part_b: DSS Part B (location/subbasin)
            - dss_part_c: DSS Part C (parameter)
            - dss_part_d: DSS Part D (date)
            - dss_part_e: DSS Part E (interval)
            - dss_part_f: DSS Part F (run identifier)
            - use_dss: Boolean True/False
            - line_number: Line number of Boundary Location in file

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> dss_bcs = RasUnsteady.get_dss_boundaries("project.u01")
        >>> print(f"Found {len(dss_bcs)} DSS-linked boundaries")
        >>> # Get unique HMS subbasins (Part B)
        >>> subbasins = dss_bcs['dss_part_b'].unique()
        >>> print(f"Unique subbasins: {subbasins}")

        Notes
        -----
        DSS Path Format: //A/B/C/D/E/F/
        - Part A: Project identifier (often empty)
        - Part B: Location/Subbasin name (key for HMS matching)
        - Part C: Parameter (FLOW, STAGE, etc.)
        - Part D: Date reference
        - Part E: Time interval (5MIN, 1HOUR, etc.)
        - Part F: Run identifier (e.g., RUN:1%_24HR)
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass  # Allow standalone use without initialized project

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        boundaries = []
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith('Boundary Location='):
                bc = RasUnsteady._parse_boundary_block_dss(lines, i)
                if bc.get('use_dss') == 'True':
                    bc['line_number'] = i + 1  # 1-indexed for user reference
                    boundaries.append(bc)
            i += 1

        df = pd.DataFrame(boundaries)
        logger.info(f"Found {len(df)} DSS-linked boundaries in {unsteady_path.name}")
        return df

    @staticmethod
    def _parse_boundary_block_dss(lines: List[str], start_idx: int) -> Dict:
        """Parse a boundary block and extract DSS-related fields."""
        bc = {
            'river': '',
            'reach': '',
            'station': '',
            'bc_type': '',
            'interval': '',
            'dss_file': '',
            'dss_path': '',
            'dss_part_a': '',
            'dss_part_b': '',
            'dss_part_c': '',
            'dss_part_d': '',
            'dss_part_e': '',
            'dss_part_f': '',
            'use_dss': 'False',
            'data_count': 0
        }

        # Parse location line
        loc_line = lines[start_idx].replace('Boundary Location=', '')
        parts = [p.strip() for p in loc_line.split(',')]
        if len(parts) >= 1:
            bc['river'] = parts[0]
        if len(parts) >= 2:
            bc['reach'] = parts[1]
        if len(parts) >= 3:
            bc['station'] = parts[2]

        # Scan following lines for DSS info
        i = start_idx + 1
        while i < len(lines) and i < start_idx + 50:
            line = lines[i].strip()

            if line.startswith('Boundary Location='):
                break
            elif line.startswith('Interval='):
                bc['interval'] = line.replace('Interval=', '').strip()
            elif line.startswith('Flow Hydrograph='):
                bc['bc_type'] = 'Flow Hydrograph'
                try:
                    bc['data_count'] = int(line.replace('Flow Hydrograph=', '').strip())
                except:
                    pass
            elif line.startswith('Lateral Inflow Hydrograph='):
                bc['bc_type'] = 'Lateral Inflow Hydrograph'
                try:
                    bc['data_count'] = int(line.replace('Lateral Inflow Hydrograph=', '').strip())
                except:
                    pass
            elif line.startswith('Uniform Lateral Inflow='):
                bc['bc_type'] = 'Uniform Lateral Inflow'
                try:
                    bc['data_count'] = int(line.replace('Uniform Lateral Inflow=', '').strip())
                except:
                    pass
            elif line.startswith('Stage Hydrograph='):
                bc['bc_type'] = 'Stage Hydrograph'
            elif line.startswith('Friction Slope='):
                bc['bc_type'] = 'Normal Depth'
            elif line.startswith('Rating Curve='):
                bc['bc_type'] = 'Rating Curve'
            elif line.startswith('DSS File='):
                bc['dss_file'] = line.replace('DSS File=', '').strip()
            elif line.startswith('DSS Path='):
                dss_path = line.replace('DSS Path=', '').strip()
                bc['dss_path'] = dss_path
                # Parse DSS path parts
                if dss_path:
                    dss_parts = RasUnsteady._parse_dss_path(dss_path)
                    bc.update(dss_parts)
            elif line.startswith('Use DSS='):
                bc['use_dss'] = line.replace('Use DSS=', '').strip()

            i += 1

        return bc

    @staticmethod
    def _parse_dss_path(dss_path: str) -> Dict:
        """
        Parse a DSS path into its component parts.

        DSS Path Format: //A/B/C/D/E/F/
        Example: //P100A/FLOW/31MAY2007/5MIN/RUN:1%_24HR/
        """
        parts = {
            'dss_part_a': '',
            'dss_part_b': '',
            'dss_part_c': '',
            'dss_part_d': '',
            'dss_part_e': '',
            'dss_part_f': ''
        }

        # Remove leading slashes and split
        clean_path = dss_path.strip('/')
        segments = clean_path.split('/')

        if len(segments) >= 1:
            parts['dss_part_a'] = segments[0]
        if len(segments) >= 2:
            parts['dss_part_b'] = segments[1]
        if len(segments) >= 3:
            parts['dss_part_c'] = segments[2]
        if len(segments) >= 4:
            parts['dss_part_d'] = segments[3]
        if len(segments) >= 5:
            parts['dss_part_e'] = segments[4]
        if len(segments) >= 6:
            parts['dss_part_f'] = segments[5]

        return parts

    @staticmethod
    @log_call
    def get_inline_hydrograph_boundaries(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Extract all inline hydrograph boundary conditions from an unsteady flow file.

        This function parses .u## files and extracts boundary conditions that have
        inline time series data (Use DSS=False with Flow Hydrograph or Lateral Inflow
        tables). These are the manually-entered hydrographs that need to be matched
        to HMS subbasins for DSS conversion.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        pd.DataFrame
            DataFrame with columns:
            - river: River name
            - reach: Reach name
            - station: River station
            - bc_type: Boundary condition type
            - interval: Time interval (e.g., 5MIN)
            - data_count: Number of data points
            - values: numpy array of hydrograph values
            - peak_value: Maximum flow value
            - peak_index: Index of peak (time step)
            - time_to_peak_hrs: Time to peak in hours
            - min_value: Minimum flow value
            - line_number: Line number of Boundary Location in file

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> inline_bcs = RasUnsteady.get_inline_hydrograph_boundaries("project.u01")
        >>> print(f"Found {len(inline_bcs)} inline hydrograph boundaries")
        >>> for idx, bc in inline_bcs.iterrows():
        ...     print(f"{bc['river']}/{bc['reach']}/{bc['station']}: "
        ...           f"Peak={bc['peak_value']:.0f} cfs @ {bc['time_to_peak_hrs']:.1f} hrs")
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass  # Allow standalone use

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        boundaries = []
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith('Boundary Location='):
                bc = RasUnsteady._parse_boundary_block_inline(lines, i)
                if bc.get('has_inline_table') and bc.get('use_dss') == 'False':
                    bc['line_number'] = i + 1
                    boundaries.append(bc)
            i += 1

        df = pd.DataFrame(boundaries)

        # Remove internal fields
        if 'has_inline_table' in df.columns:
            df = df.drop(columns=['has_inline_table'])

        logger.info(f"Found {len(df)} inline hydrograph boundaries in {unsteady_path.name}")
        return df

    @staticmethod
    def _parse_boundary_block_inline(lines: List[str], start_idx: int) -> Dict:
        """Parse a boundary block and extract inline table data."""
        bc = {
            'river': '',
            'reach': '',
            'station': '',
            'bc_type': '',
            'interval': '',
            'data_count': 0,
            'values': None,
            'peak_value': None,
            'peak_index': None,
            'time_to_peak_hrs': None,
            'min_value': None,
            'use_dss': 'False',
            'has_inline_table': False
        }

        # Parse location line
        loc_line = lines[start_idx].replace('Boundary Location=', '')
        parts = [p.strip() for p in loc_line.split(',')]
        if len(parts) >= 1:
            bc['river'] = parts[0]
        if len(parts) >= 2:
            bc['reach'] = parts[1]
        if len(parts) >= 3:
            bc['station'] = parts[2]

        # Scan for boundary info and inline table
        i = start_idx + 1
        table_start = None
        expected_count = 0

        while i < len(lines) and i < start_idx + 100:
            line = lines[i].strip()

            if line.startswith('Boundary Location='):
                break
            elif line.startswith('Interval='):
                bc['interval'] = line.replace('Interval=', '').strip()
            elif line.startswith('Flow Hydrograph='):
                bc['bc_type'] = 'Flow Hydrograph'
                try:
                    expected_count = int(line.replace('Flow Hydrograph=', '').strip())
                    bc['data_count'] = expected_count
                    if expected_count > 0:
                        bc['has_inline_table'] = True
                        table_start = i + 1
                except:
                    pass
            elif line.startswith('Lateral Inflow Hydrograph='):
                bc['bc_type'] = 'Lateral Inflow Hydrograph'
                try:
                    expected_count = int(line.replace('Lateral Inflow Hydrograph=', '').strip())
                    bc['data_count'] = expected_count
                    if expected_count > 0:
                        bc['has_inline_table'] = True
                        table_start = i + 1
                except:
                    pass
            elif line.startswith('Uniform Lateral Inflow='):
                bc['bc_type'] = 'Uniform Lateral Inflow'
                try:
                    expected_count = int(line.replace('Uniform Lateral Inflow=', '').strip())
                    bc['data_count'] = expected_count
                    if expected_count > 0:
                        bc['has_inline_table'] = True
                        table_start = i + 1
                except:
                    pass
            elif line.startswith('Use DSS='):
                bc['use_dss'] = line.replace('Use DSS=', '').strip()

            i += 1

        # Parse inline table if present
        if bc['has_inline_table'] and table_start and expected_count > 0:
            values = RasUnsteady._parse_inline_values(lines, table_start, expected_count)
            if values is not None and len(values) > 0:
                bc['values'] = values
                bc['min_value'] = float(np.min(values))
                bc['peak_value'] = float(np.max(values))
                bc['peak_index'] = int(np.argmax(values))

                # Calculate time to peak
                if bc['interval']:
                    interval_mins = RasUnsteady._parse_interval_to_minutes(bc['interval'])
                    if interval_mins:
                        bc['time_to_peak_hrs'] = (bc['peak_index'] * interval_mins) / 60.0

        return bc

    @staticmethod
    def _parse_inline_values(lines: List[str], start_idx: int, expected_count: int) -> np.ndarray:
        """Parse inline table values from fixed-width format (8 chars per value)."""
        values = []
        i = start_idx

        while len(values) < expected_count and i < len(lines):
            line = lines[i]

            # Check if line looks like data
            if line.strip() and (line[0].isspace() or line[0].isdigit() or line[0] == '-'):
                # Parse 8-char fixed-width format
                for j in range(0, min(len(line), 80), 8):
                    chunk = line[j:j+8].strip()
                    if chunk:
                        try:
                            values.append(float(chunk))
                        except ValueError:
                            # Try regex for merged numbers
                            nums = re.findall(r'-?\d+\.?\d*', chunk)
                            values.extend([float(n) for n in nums])
            elif '=' in line:
                # Hit a keyword, stop parsing
                break

            i += 1

            # Safety limit
            if i > start_idx + 500:
                break

        return np.array(values[:expected_count]) if values else None

    @staticmethod
    def _parse_interval_to_minutes(interval: str) -> Optional[int]:
        """Convert interval string (e.g., '5MIN', '1HOUR') to minutes."""
        interval = interval.upper().strip()

        # Try numeric + MIN
        match = re.match(r'(\d+)\s*MIN', interval)
        if match:
            return int(match.group(1))

        # Try numeric + HOUR
        match = re.match(r'(\d+)\s*HOUR', interval)
        if match:
            return int(match.group(1)) * 60

        # Try numeric + HR
        match = re.match(r'(\d+)\s*HR', interval)
        if match:
            return int(match.group(1)) * 60

        return None

    @staticmethod
    @log_call
    def update_dss_run_identifier(
        unsteady_file: Union[str, Path],
        old_run_id: str,
        new_run_id: str,
        ras_object: Optional[Any] = None
    ) -> int:
        """
        Update the DSS path run identifier (F-part) for all matching boundaries.

        This function modifies the DSS Path values in a .u## file, changing the
        run identifier (Part F) from one value to another. This is useful when
        updating precipitation from TP40 to Atlas 14, where the run identifier
        indicates the storm scenario.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        old_run_id : str
            Current run identifier to replace (e.g., "RUN:1%_24HR")
        new_run_id : str
            New run identifier value (e.g., "RUN:1%_24HR_ATLAS14")
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        int
            Number of DSS paths updated

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Update run identifier from TP40 to Atlas 14
        >>> count = RasUnsteady.update_dss_run_identifier(
        ...     "project.u01",
        ...     old_run_id="RUN:1%_24HR",
        ...     new_run_id="RUN:1%_24HR_ATLAS14"
        ... )
        >>> print(f"Updated {count} DSS paths")

        Notes
        -----
        The DSS path format is: //A/B/C/D/E/F/
        This function modifies Part F (run identifier) while preserving all other parts.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        update_count = 0
        for i, line in enumerate(lines):
            if line.startswith('DSS Path='):
                dss_path = line.replace('DSS Path=', '').strip()
                if old_run_id in dss_path:
                    new_dss_path = dss_path.replace(old_run_id, new_run_id)
                    lines[i] = f'DSS Path={new_dss_path}\n'
                    update_count += 1
                    logger.debug(f"Updated DSS Path at line {i+1}: {dss_path} -> {new_dss_path}")

        if update_count > 0:
            with open(unsteady_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Updated {update_count} DSS paths in {unsteady_path.name}")
        else:
            logger.warning(f"No DSS paths found with run identifier '{old_run_id}'")

        return update_count

    @staticmethod
    @log_call
    def set_boundary_dss_link(
        unsteady_file: Union[str, Path],
        river: str,
        reach: str,
        station: str,
        dss_file: str,
        dss_path: str,
        interval: str = "5MIN",
        ras_object: Optional[Any] = None
    ) -> bool:
        """
        Convert an inline hydrograph boundary to use DSS linkage.

        This function modifies a boundary condition in a .u## file to use a DSS
        file reference instead of inline table data. It performs a complete state
        transition: sets Use DSS=True, adds DSS File/Path, sets the inline table
        count to 0, and removes any inline data lines.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        river : str
            River name for the boundary
        reach : str
            Reach name for the boundary
        station : str
            River station for the boundary
        dss_file : str
            Path to the DSS file (relative to project folder)
        dss_path : str
            Full DSS path (e.g., "//SUBBASIN/FLOW/DATE/5MIN/RUN:1%_24HR/")
        interval : str, default "5MIN"
            Time interval for the boundary condition
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        bool
            True if boundary was successfully updated, False if not found

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Link a boundary to DSS
        >>> success = RasUnsteady.set_boundary_dss_link(
        ...     "project.u01",
        ...     river="Turkey Creek",
        ...     reach="A119-00-00",
        ...     station="23601.19",
        ...     dss_file="P1000000.dss",
        ...     dss_path="//A119-01-00A/FLOW/31MAY2007/5MIN/RUN:1%_24HR/"
        ... )
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Find the boundary location
        boundary_idx = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_line = line.replace('Boundary Location=', '')
                parts = [p.strip() for p in loc_line.split(',')]
                if (len(parts) >= 3 and
                    parts[0] == river and
                    parts[1] == reach and
                    parts[2] == station):
                    boundary_idx = i
                    break

        if boundary_idx is None:
            logger.warning(f"Boundary not found: {river}/{reach}/{station}")
            return False

        # Inline table type keywords that may have data to remove
        TABLE_KEYWORDS = [
            'Flow Hydrograph=', 'Stage Hydrograph=', 'Lateral Inflow Hydrograph=',
            'Uniform Lateral Inflow=', 'Precipitation Hydrograph=',
            'Uniform Lateral Inflow Hydrograph='
        ]

        # Scan the boundary block to find all relevant lines and inline data
        i = boundary_idx + 1
        dss_file_idx = None
        dss_path_idx = None
        use_dss_idx = None
        interval_idx = None
        table_header_idx = None
        table_keyword = None
        inline_data_start = None
        inline_data_end = None

        while i < len(lines) and i < boundary_idx + 500:
            line = lines[i]

            if line.startswith('Boundary Location='):
                break
            elif line.startswith('DSS File='):
                dss_file_idx = i
            elif line.startswith('DSS Path='):
                dss_path_idx = i
            elif line.startswith('Use DSS='):
                use_dss_idx = i
            elif line.startswith('Interval='):
                interval_idx = i
            else:
                # Check for table header keywords
                for kw in TABLE_KEYWORDS:
                    if line.startswith(kw):
                        table_header_idx = i
                        table_keyword = kw
                        # Parse count
                        try:
                            count = int(line.replace(kw, '').strip())
                        except ValueError:
                            count = 0
                        if count > 0:
                            # Find extent of inline data lines
                            inline_data_start = i + 1
                            inline_data_end = inline_data_start
                            for k in range(inline_data_start, len(lines)):
                                data_line = lines[k]
                                if '=' in data_line or data_line.startswith('Boundary Location='):
                                    inline_data_end = k
                                    break
                                if not data_line.strip():
                                    continue
                            else:
                                inline_data_end = len(lines)
                        break
            i += 1

        # Step 1: Remove inline data lines (if any) - do this first to preserve indices
        lines_removed = 0
        if inline_data_start is not None and inline_data_end is not None and inline_data_end > inline_data_start:
            del lines[inline_data_start:inline_data_end]
            lines_removed = inline_data_end - inline_data_start
            logger.debug(f"Removed {lines_removed} inline data lines")
            # Adjust indices for removed lines
            if dss_file_idx is not None and dss_file_idx > inline_data_start:
                dss_file_idx -= lines_removed
            if dss_path_idx is not None and dss_path_idx > inline_data_start:
                dss_path_idx -= lines_removed
            if use_dss_idx is not None and use_dss_idx > inline_data_start:
                use_dss_idx -= lines_removed
            if interval_idx is not None and interval_idx > inline_data_start:
                interval_idx -= lines_removed

        # Step 2: Set table count to 0
        if table_header_idx is not None and table_keyword is not None:
            lines[table_header_idx] = f'{table_keyword} 0 \n'
            logger.debug(f"Set {table_keyword.strip()} count to 0")

        # Step 3: Update existing DSS/interval lines or insert missing ones
        if interval_idx is not None:
            lines[interval_idx] = f'Interval={interval}\n'
        if dss_file_idx is not None:
            lines[dss_file_idx] = f'DSS File={dss_file}\n'
        if dss_path_idx is not None:
            lines[dss_path_idx] = f'DSS Path={dss_path}\n'
        if use_dss_idx is not None:
            lines[use_dss_idx] = 'Use DSS=True\n'

        # Insert any missing lines after the table header (or after boundary location)
        insert_after = table_header_idx if table_header_idx is not None else boundary_idx
        insert_idx = insert_after + 1

        if interval_idx is None:
            lines.insert(insert_idx, f'Interval={interval}\n')
            insert_idx += 1
            # Adjust subsequent indices
            if dss_file_idx is not None and dss_file_idx >= insert_idx - 1:
                dss_file_idx += 1
            if dss_path_idx is not None and dss_path_idx >= insert_idx - 1:
                dss_path_idx += 1
            if use_dss_idx is not None and use_dss_idx >= insert_idx - 1:
                use_dss_idx += 1

        if dss_file_idx is None:
            lines.insert(insert_idx, f'DSS File={dss_file}\n')
            insert_idx += 1
            if dss_path_idx is not None and dss_path_idx >= insert_idx - 1:
                dss_path_idx += 1
            if use_dss_idx is not None and use_dss_idx >= insert_idx - 1:
                use_dss_idx += 1

        if dss_path_idx is None:
            lines.insert(insert_idx, f'DSS Path={dss_path}\n')
            insert_idx += 1
            if use_dss_idx is not None and use_dss_idx >= insert_idx - 1:
                use_dss_idx += 1

        if use_dss_idx is None:
            lines.insert(insert_idx, 'Use DSS=True\n')

        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        logger.info(f"Updated boundary {river}/{reach}/{station} to use DSS link "
                     f"(removed {lines_removed} inline data lines)")
        return True

    @staticmethod
    @log_call
    def set_boundary_inline_hydrograph(
        unsteady_file: Union[str, Path],
        hydrograph_df: pd.DataFrame,
        bc_type: str = "Flow Hydrograph",
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None
    ) -> bool:
        """
        Write an inline hydrograph table to a boundary condition, converting from DSS if needed.

        This method performs a complete DSS→inline state transition: sets Use DSS=False,
        removes DSS File/Path lines, writes inline hydrograph data in HEC-RAS fixed-width
        format, and updates the table count and Interval line.

        The method follows the same pattern as ``set_precipitation_hyetograph()`` for
        inline table writing.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g., "01")
        hydrograph_df : pd.DataFrame
            DataFrame with columns:

            - ``'hour'``: Time in hours from start (float)
            - ``'value'``: Hydrograph value at each time step (flow in cfs/cms or stage in ft/m)

        bc_type : str, default "Flow Hydrograph"
            Boundary condition type. Must be one of:

            - ``"Flow Hydrograph"``
            - ``"Stage Hydrograph"``
            - ``"Lateral Inflow Hydrograph"``
            - ``"Uniform Lateral Inflow"``

        river : str, optional
            River name to locate the boundary. If None, updates the first matching bc_type.
        reach : str, optional
            Reach name to locate the boundary.
        station : str, optional
            River station to locate the boundary.
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        bool
            True if boundary was successfully updated, False if not found

        Raises
        ------
        ValueError
            If DataFrame is missing required columns or bc_type is unsupported
        FileNotFoundError
            If unsteady flow file not found

        Example
        -------
        >>> import pandas as pd
        >>> from ras_commander import RasUnsteady
        >>> # Create a simple flow hydrograph
        >>> hours = list(range(25))
        >>> flows = [100, 150, 300, 600, 1200, 2000, 3000, 4000, 5000, 4500,
        ...          4000, 3500, 3000, 2500, 2000, 1700, 1400, 1200, 1000,
        ...          800, 600, 400, 300, 200, 100]
        >>> df = pd.DataFrame({'hour': hours, 'value': flows})
        >>> RasUnsteady.set_boundary_inline_hydrograph(
        ...     "project.u01", df, bc_type="Flow Hydrograph",
        ...     river="White", reach="Muncie", station="15696.24"
        ... )

        Notes
        -----
        **Inline Hydrograph Format** (HEC-RAS .u## files):

        Flow/Stage/Lateral hydrographs store values only (not time-value pairs).
        Each value is 8 characters wide, 10 values per line. The count on the header
        line is the number of values, and time is implied from the Interval setting.

        This differs from Precipitation Hydrograph which stores (time, depth) pairs.

        **State Transition**:

        When converting from DSS mode, this method:

        1. Sets ``Use DSS=False``
        2. Removes ``DSS File=`` and ``DSS Path=`` content (sets to empty)
        3. Writes inline data after the hydrograph header line
        4. Updates the value count and Interval line

        See Also
        --------
        set_boundary_dss_link : Convert inline boundary to DSS mode
        set_precipitation_hyetograph : Write precipitation hyetograph (uses time-value pairs)
        """
        SUPPORTED_TYPES = {
            "Flow Hydrograph": "Flow Hydrograph=",
            "Stage Hydrograph": "Stage Hydrograph=",
            "Lateral Inflow Hydrograph": "Lateral Inflow Hydrograph=",
            "Uniform Lateral Inflow": "Uniform Lateral Inflow=",
            "Uniform Lateral Inflow Hydrograph": "Uniform Lateral Inflow Hydrograph=",
        }

        if bc_type not in SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported bc_type: '{bc_type}'. "
                f"Supported types: {list(SUPPORTED_TYPES.keys())}"
            )

        table_keyword = SUPPORTED_TYPES[bc_type]

        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        # Resolve unsteady file path
        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError("Cannot resolve unsteady number without an initialized ras_object")
            unsteady_num = unsteady_file.zfill(2)
            unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{unsteady_num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # Validate DataFrame columns
        required_columns = ['hour', 'value']
        missing_columns = [col for col in required_columns if col not in hydrograph_df.columns]
        if missing_columns:
            raise ValueError(
                f"DataFrame missing required columns: {missing_columns}. "
                f"Required columns: {required_columns}"
            )

        # Extract values
        hours = hydrograph_df['hour'].values
        values = hydrograph_df['value'].values
        num_values = len(values)

        if num_values < 2:
            raise ValueError("DataFrame must have at least 2 rows")

        # Calculate interval from hour column
        interval_hours = float(hours[1] - hours[0])
        if interval_hours >= 1.0:
            if interval_hours == int(interval_hours):
                interval_str = f"{int(interval_hours)}HOUR"
            else:
                interval_min = int(interval_hours * 60)
                interval_str = f"{interval_min}MIN"
        else:
            interval_min = int(interval_hours * 60)
            interval_str = f"{interval_min}MIN"

        # Format values as fixed-width (8 chars each, 10 values per line)
        # Flow/Stage hydrographs use values only (not time-value pairs)
        formatted_lines = []
        for i in range(0, num_values, 10):
            row_values = values[i:i+10]
            formatted_row = ''.join(f'{v:8.2f}' if abs(v) < 1e7 else f'{v:8.1f}'
                                    for v in row_values)
            formatted_lines.append(formatted_row + '\n')

        # Read the file
        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Find the target boundary
        target_boundary_idx = None
        for idx, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                if river is not None or reach is not None or station is not None:
                    loc_line = line.replace('Boundary Location=', '')
                    parts = [p.strip() for p in loc_line.split(',')]
                    match = True
                    if river is not None and (len(parts) < 1 or parts[0] != river):
                        match = False
                    if reach is not None and (len(parts) < 2 or parts[1] != reach):
                        match = False
                    if station is not None and (len(parts) < 3 or parts[2] != station):
                        match = False
                    if match:
                        target_boundary_idx = idx
                        break
                else:
                    # No location filter - find first boundary with matching bc_type
                    # Scan ahead to check bc_type
                    for j in range(idx + 1, min(idx + 50, len(lines))):
                        if lines[j].startswith('Boundary Location='):
                            break
                        if lines[j].startswith(table_keyword):
                            target_boundary_idx = idx
                            break
                    if target_boundary_idx is not None:
                        break

        if target_boundary_idx is None:
            loc_str = f"{river}/{reach}/{station}" if river else "first matching"
            logger.warning(f"Boundary not found for {bc_type}: {loc_str}")
            return False

        # Scan the boundary block for relevant lines
        block_start = target_boundary_idx + 1
        table_header_idx = None
        interval_idx = None
        dss_file_idx = None
        dss_path_idx = None
        use_dss_idx = None
        old_data_start = None
        old_data_end = None
        block_end = len(lines)

        i = block_start
        while i < len(lines) and i < target_boundary_idx + 500:
            line = lines[i]

            if line.startswith('Boundary Location='):
                block_end = i
                break
            elif line.startswith('Interval='):
                interval_idx = i
            elif line.startswith(table_keyword):
                table_header_idx = i
                # Check if there are existing inline data lines
                try:
                    old_count = int(line.replace(table_keyword, '').strip())
                except ValueError:
                    old_count = 0
                if old_count > 0:
                    old_data_start = i + 1
                    # Find end of old data
                    for k in range(old_data_start, len(lines)):
                        data_line = lines[k]
                        if '=' in data_line or data_line.startswith('Boundary Location='):
                            old_data_end = k
                            break
                    else:
                        old_data_end = len(lines)
            elif line.startswith('DSS File='):
                dss_file_idx = i
            elif line.startswith('DSS Path='):
                dss_path_idx = i
            elif line.startswith('Use DSS='):
                use_dss_idx = i

            i += 1

        # Step 1: Remove old inline data (if any)
        lines_removed = 0
        if old_data_start is not None and old_data_end is not None and old_data_end > old_data_start:
            del lines[old_data_start:old_data_end]
            lines_removed = old_data_end - old_data_start
            # Adjust indices
            for attr in ['interval_idx', 'dss_file_idx', 'dss_path_idx', 'use_dss_idx']:
                val = locals().get(attr)
                if val is not None and val > old_data_start:
                    locals()[attr] = val - lines_removed
            # Re-read adjusted indices from locals
            if interval_idx is not None and interval_idx > old_data_start:
                interval_idx -= lines_removed
            if dss_file_idx is not None and dss_file_idx > old_data_start:
                dss_file_idx -= lines_removed
            if dss_path_idx is not None and dss_path_idx > old_data_start:
                dss_path_idx -= lines_removed
            if use_dss_idx is not None and use_dss_idx > old_data_start:
                use_dss_idx -= lines_removed

        # Step 2: Update table header with new count
        if table_header_idx is not None:
            lines[table_header_idx] = f'{table_keyword} {num_values} \n'
        else:
            # Insert table header after Interval line (or after boundary location)
            insert_pos = interval_idx + 1 if interval_idx is not None else target_boundary_idx + 1
            lines.insert(insert_pos, f'{table_keyword} {num_values} \n')
            table_header_idx = insert_pos
            # Adjust indices after insertion
            if interval_idx is not None and interval_idx >= insert_pos:
                interval_idx += 1
            if dss_file_idx is not None and dss_file_idx >= insert_pos:
                dss_file_idx += 1
            if dss_path_idx is not None and dss_path_idx >= insert_pos:
                dss_path_idx += 1
            if use_dss_idx is not None and use_dss_idx >= insert_pos:
                use_dss_idx += 1

        # Step 3: Insert new inline data right after table header
        insert_pos = table_header_idx + 1
        for j, data_line in enumerate(formatted_lines):
            lines.insert(insert_pos + j, data_line)
        lines_inserted = len(formatted_lines)

        # Adjust indices for inserted lines
        if interval_idx is not None and interval_idx >= insert_pos:
            interval_idx += lines_inserted
        if dss_file_idx is not None and dss_file_idx >= insert_pos:
            dss_file_idx += lines_inserted
        if dss_path_idx is not None and dss_path_idx >= insert_pos:
            dss_path_idx += lines_inserted
        if use_dss_idx is not None and use_dss_idx >= insert_pos:
            use_dss_idx += lines_inserted

        # Step 4: Update Interval line
        if interval_idx is not None:
            lines[interval_idx] = f'Interval={interval_str}\n'
        else:
            # Insert interval before table header
            lines.insert(table_header_idx, f'Interval={interval_str}\n')
            # Adjust all indices after this insertion
            if dss_file_idx is not None and dss_file_idx >= table_header_idx:
                dss_file_idx += 1
            if dss_path_idx is not None and dss_path_idx >= table_header_idx:
                dss_path_idx += 1
            if use_dss_idx is not None and use_dss_idx >= table_header_idx:
                use_dss_idx += 1

        # Step 5: Set Use DSS=False and clear DSS File/Path
        if use_dss_idx is not None:
            lines[use_dss_idx] = 'Use DSS=False\n'
        if dss_file_idx is not None:
            lines[dss_file_idx] = 'DSS File=\n'
        if dss_path_idx is not None:
            lines[dss_path_idx] = 'DSS Path=\n'

        # Write updated content back to file
        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        peak_value = float(np.max(values))
        logger.info(
            f"Updated {bc_type} inline hydrograph in {unsteady_path.name}: "
            f"{num_values} values, interval={interval_str}, "
            f"peak={peak_value:.2f}"
        )
        return True

    @staticmethod
    @log_call
    def set_flow_hydrograph_slope(
        unsteady_file: Union[str, Path],
        eg_slope: float,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        area_2d: Optional[str] = None,
        bc_line: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Add or update the energy-grade ``Flow Hydrograph Slope=`` line on a
        Flow Hydrograph boundary in a HEC-RAS unsteady flow file (.u##).

        ``Flow Hydrograph Slope=`` is the energy-grade slope HEC-RAS uses to
        distribute Flow Hydrograph inflow along a 2D Flow Area perimeter BC
        line (Tutorial 2, "Creating a Simple 2D Model"). It is a property of
        the Flow Hydrograph BC, not a generic boundary parameter; this writer
        therefore only operates on blocks that already declare a
        ``Flow Hydrograph=<count>`` keyword.

        Behavior
        --------
        - **Update path**: if a ``Flow Hydrograph Slope=`` line already exists
          inside the matched boundary block, its value is overwritten in place
          and no other line is touched.
        - **Insert path**: if no slope line exists, a new line is inserted in
          the canonical position observed in HEC-RAS-emitted output: after
          ``Flow Hydrograph QMult=`` if present, otherwise after
          ``Stage Hydrograph TW Check=`` if present, otherwise immediately
          before the first DSS metadata line (``DSS Path=``, ``DSS File=``,
          or ``Use DSS=``), otherwise just before the first ``=`` line that
          follows the inline hydrograph data.

        DSS path/file, Use DSS, Interval, ``Flow Hydrograph=`` count, and
        inline hydrograph data are never altered. The companion writers
        (``set_boundary_dss_link``, ``set_boundary_inline_hydrograph``) can
        be used freely before or after this call.

        Format conventions observed in real HEC-RAS .u## files
        ------------------------------------------------------
        HEC-RAS emits the line as ``Flow Hydrograph Slope= <value> `` — note
        the single leading space after ``=`` and the single trailing space
        before the newline, matching the surrounding ``Flow Hydrograph QMult=``
        line. This writer mirrors that spacing on both update and insert.

        Target resolution
        -----------------
        Provide *exactly one* of:

        - ``(river, reach, station)`` for a 1D river boundary.
        - ``(area_2d, bc_line)`` for a 2D BC line on a 2D Flow Area perimeter.
          ``bc_line`` is required: a Flow Hydrograph distribution slope is
          tied to a specific BC line, never area-wide.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character unsteady
            number (e.g. ``"01"``) when a project-bound ``ras_object`` is
            available.
        eg_slope : float
            Energy-grade slope (m/m or ft/ft). Must be in the inclusive range
            ``[1e-7, 1.0]`` and finite.
        river, reach, station : str, optional
            1D location selector. All three must be provided together.
        area_2d, bc_line : str, optional
            2D location selector. Both must be provided together.
        ras_object : optional
            Custom RAS object to use instead of the global one. When
            initialized for a project, ``boundaries_df`` is refreshed after
            the write.

        Returns
        -------
        Dict[str, Any]
            Reviewable before/after metadata with keys:

            - ``unsteady_file`` (str): absolute path written
            - ``matched_location`` (str): the matched ``Boundary Location=``
              value (without the leading ``Boundary Location=``)
            - ``bc_type`` (str): always ``'Flow Hydrograph'`` on success
            - ``previous_eg_slope`` (float | None): prior slope value, or
              ``None`` if no ``Flow Hydrograph Slope=`` line existed
            - ``new_eg_slope`` (float): slope written
            - ``updated_in_place`` (bool): True when an existing slope line
              was overwritten without insertion
            - ``lines_inserted`` (int): 1 if a new line was inserted, else 0
            - ``insert_anchor`` (str | None): the keyword anchor used to
              place the new line (``'Flow Hydrograph QMult='``,
              ``'Stage Hydrograph TW Check='``, ``'DSS Path='``,
              ``'DSS File='``, ``'Use DSS='``, or ``'<inline-data-tail>'``);
              ``None`` on update path
            - ``boundaries_df_refreshed`` (bool): True when ``ras_object``
              ``boundaries_df`` was refreshed after the write
            - ``block_before`` (str): boundary block text before the edit
            - ``block_after`` (str): boundary block text after the edit

        Raises
        ------
        ValueError
            If ``eg_slope`` is non-numeric, non-finite, or outside
            ``[1e-7, 1.0]``; if the target selectors are inconsistent (both
            1D and 2D, or neither); if a 1D selector is partial; if a 2D
            selector is missing ``bc_line``; if the matched block is not a
            Flow Hydrograph (e.g., Normal Depth, Stage Hydrograph, Rating
            Curve, Gate Opening); or if no boundary in the file matches the
            selectors.
        FileNotFoundError
            If the unsteady flow file does not exist.

        Examples
        --------
        Update an existing 2D Flow Hydrograph distribution slope:

        >>> from ras_commander import RasUnsteady
        >>> result = RasUnsteady.set_flow_hydrograph_slope(
        ...     "BaldEagleDamBrk.u02",
        ...     eg_slope=0.001,
        ...     area_2d="BaldEagleCr",
        ...     bc_line="Upstream Inflow",
        ... )
        >>> result["new_eg_slope"], result["updated_in_place"]
        (0.001, True)

        Add a slope line to a Flow Hydrograph block that has none yet:

        >>> result = RasUnsteady.set_flow_hydrograph_slope(
        ...     "project.u01",
        ...     eg_slope=0.0007,
        ...     area_2d="Upper 2D Area",
        ...     bc_line="Upstream Q",
        ... )
        >>> result["lines_inserted"], result["insert_anchor"]
        (1, 'DSS Path=')

        See Also
        --------
        set_boundary_dss_link : Convert inline BC to DSS-linked.
        set_boundary_inline_hydrograph : Write inline hydrograph table.
        """
        # 1) Validate slope. `numbers.Real` accepts Python int/float plus
        # numpy scalars (e.g. np.float64 returned from `boundaries_df`
        # columns), which `isinstance(x, (int, float))` does NOT under
        # NumPy 2.x. The bool-subclass-of-int guard fires first.
        if isinstance(eg_slope, bool) or not isinstance(eg_slope, numbers.Real):
            raise ValueError(
                f"eg_slope must be a real number, got {type(eg_slope).__name__}"
            )
        slope = float(eg_slope)
        if not np.isfinite(slope):
            raise ValueError(f"eg_slope must be finite, got {slope!r}")
        if not (1e-7 <= slope <= 1.0):
            raise ValueError(
                f"eg_slope {slope!r} is outside the supported range [1e-7, 1.0]"
            )

        # 2) Validate target selectors
        has_1d = any(x is not None for x in (river, reach, station))
        has_2d = any(x is not None for x in (area_2d, bc_line))
        if has_1d == has_2d:
            raise ValueError(
                "Provide exactly one selector group: (river, reach, station) "
                "OR (area_2d, bc_line)"
            )
        if has_1d and not (river and reach and station):
            raise ValueError(
                "1D selector requires all of river, reach, and station"
            )
        if has_2d and not (area_2d and bc_line):
            raise ValueError(
                "2D selector requires both area_2d and bc_line"
            )

        # 3) Resolve unsteady file path
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # 4) Read file and find target Boundary Location block
        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        def _matches_location(loc_value: str) -> bool:
            parts = [p.strip() for p in loc_value.split(',')]
            if has_1d:
                return (
                    len(parts) >= 3
                    and parts[0] == river
                    and parts[1] == reach
                    and parts[2] == station
                )
            if len(parts) < 6 or parts[5] != area_2d:
                return False
            if len(parts) < 8 or parts[7] != bc_line:
                return False
            return True

        boundary_idx = None
        matched_loc = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                if _matches_location(loc_value):
                    boundary_idx = i
                    matched_loc = loc_value
                    break

        if boundary_idx is None:
            sel = (
                f"river={river!r}/reach={reach!r}/station={station!r}"
                if has_1d
                else f"area_2d={area_2d!r}/bc_line={bc_line!r}"
            )
            raise ValueError(
                f"No boundary matched in {unsteady_path.name} for {sel}. "
                f"This function only edits Flow Hydrograph boundaries that "
                f"already exist as `Boundary Location=` blocks."
            )

        # 5) Walk the block; verify it is a Flow Hydrograph; locate slope/QMult/
        #    TW-check / DSS metadata indices; and find the inline-data tail.
        FLOW_HYDROGRAPH_HEADER = 'Flow Hydrograph='
        SLOPE_KEY = 'Flow Hydrograph Slope='
        QMULT_KEY = 'Flow Hydrograph QMult='
        TW_CHECK_KEY = 'Stage Hydrograph TW Check='
        DSS_LINE_KEYS = ('DSS Path=', 'DSS File=', 'Use DSS=')

        flow_header_idx: Optional[int] = None
        slope_idx: Optional[int] = None
        qmult_idx: Optional[int] = None
        tw_check_idx: Optional[int] = None
        first_dss_idx: Optional[int] = None
        first_dss_keyword: Optional[str] = None
        # First post-data `=` line (used as last-resort insert anchor)
        first_post_data_eq_idx: Optional[int] = None
        # Clamp the per-block scan range explicitly so sub-pass 2 cannot
        # spill into the next boundary if sub-pass 1 hits the safety cap
        # before finding the next `Boundary Location=`. Real blocks never
        # exceed ~80 lines (Muncie + full Met BC trailer is ~70), but
        # a hard clamp eliminates a silent-misplacement failure mode.
        BLOCK_SCAN_CAP = 1000
        block_end = min(boundary_idx + 1 + BLOCK_SCAN_CAP, len(lines))

        # Sub-pass 1: confirm the block is a Flow Hydrograph and locate header.
        j = boundary_idx + 1
        while j < block_end:
            line = lines[j]
            if line.startswith('Boundary Location='):
                block_end = j
                break
            if line.startswith(FLOW_HYDROGRAPH_HEADER):
                flow_header_idx = j
            j += 1

        if flow_header_idx is None:
            raise ValueError(
                f"Boundary at {matched_loc.strip()!r} is not a Flow Hydrograph "
                f"(no `Flow Hydrograph=<count>` header in block); "
                f"`Flow Hydrograph Slope=` only applies to Flow Hydrograph BCs"
            )

        # Sub-pass 2: from after the inline data, find anchors.
        try:
            count = int(lines[flow_header_idx].replace(FLOW_HYDROGRAPH_HEADER, '').split(',')[0].strip())
        except (ValueError, IndexError):
            count = 0
        # Inline-data lines run from flow_header_idx + 1 until the first line
        # that contains '=' (mirrors the convention used by sibling writers).
        post_data_idx = flow_header_idx + 1
        if count > 0:
            for k in range(flow_header_idx + 1, block_end):
                if '=' in lines[k] or lines[k].startswith('Boundary Location='):
                    post_data_idx = k
                    break
            else:
                post_data_idx = block_end

        for j in range(post_data_idx, block_end):
            line = lines[j]
            if line.startswith(SLOPE_KEY) and slope_idx is None:
                slope_idx = j
            elif line.startswith(QMULT_KEY) and qmult_idx is None:
                qmult_idx = j
            elif line.startswith(TW_CHECK_KEY) and tw_check_idx is None:
                tw_check_idx = j
            else:
                for dss_kw in DSS_LINE_KEYS:
                    if line.startswith(dss_kw) and first_dss_idx is None:
                        first_dss_idx = j
                        first_dss_keyword = dss_kw
                        break
            if first_post_data_eq_idx is None and '=' in line:
                first_post_data_eq_idx = j

        block_before = ''.join(lines[boundary_idx:block_end])

        previous_eg_slope: Optional[float] = None
        if slope_idx is not None:
            payload = lines[slope_idx].replace(SLOPE_KEY, '').strip()
            try:
                previous_eg_slope = float(payload.split(',')[0].strip())
            except (ValueError, IndexError):
                previous_eg_slope = None

        # 6) Compose new line and apply edit. HEC-RAS emits this line with a
        # leading space after `=` and a trailing space before the newline:
        #     `Flow Hydrograph Slope= 0.0005 \n`
        new_slope_line = f'Flow Hydrograph Slope= {slope} \n'

        lines_inserted = 0
        updated_in_place = False
        insert_anchor: Optional[str] = None

        if slope_idx is not None:
            lines[slope_idx] = new_slope_line
            updated_in_place = True
        else:
            if qmult_idx is not None:
                insert_pos = qmult_idx + 1
                insert_anchor = QMULT_KEY
            elif tw_check_idx is not None:
                insert_pos = tw_check_idx + 1
                insert_anchor = TW_CHECK_KEY
            elif first_dss_idx is not None:
                insert_pos = first_dss_idx
                insert_anchor = first_dss_keyword
            elif first_post_data_eq_idx is not None:
                insert_pos = first_post_data_eq_idx
                insert_anchor = '<inline-data-tail>'
            else:
                # Last resort: end of block. Should not happen for a real
                # Flow Hydrograph block but kept for robustness.
                insert_pos = block_end
                insert_anchor = '<block-end>'
            lines.insert(insert_pos, new_slope_line)
            lines_inserted = 1

        # Recompute block end for the after-snapshot
        new_block_end = boundary_idx + 1
        while (
            new_block_end < len(lines)
            and not lines[new_block_end].startswith('Boundary Location=')
        ):
            new_block_end += 1
        block_after = ''.join(lines[boundary_idx:new_block_end])

        # 7) Persist file
        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        # 8) Refresh boundaries_df where possible
        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        logger.info(
            "Set Flow Hydrograph Slope in %s: matched=%s, slope=%s, "
            "updated_in_place=%s, anchor=%s",
            unsteady_path.name,
            matched_loc.strip(),
            slope,
            updated_in_place,
            insert_anchor,
        )

        return {
            'unsteady_file': str(unsteady_path),
            'matched_location': matched_loc,
            'bc_type': 'Flow Hydrograph',
            'previous_eg_slope': previous_eg_slope,
            'new_eg_slope': slope,
            'updated_in_place': updated_in_place,
            'lines_inserted': lines_inserted,
            'insert_anchor': insert_anchor,
            'boundaries_df_refreshed': boundaries_df_refreshed,
            'block_before': block_before,
            'block_after': block_after,
        }

    @staticmethod
    @log_call
    def set_flow_hydrograph_qmin(
        unsteady_file: Union[str, Path],
        qmin: float,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        area_2d: Optional[str] = None,
        bc_line: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Add or update the ``Flow Hydrograph QMin=`` (minimum flow) line on a
        Flow Hydrograph boundary in a HEC-RAS unsteady flow file (.u##).

        The minimum flow value prevents HEC-RAS from applying flows below
        this threshold during the simulation. It is a property of the Flow
        Hydrograph BC.

        Behavior
        --------
        - **Update path**: if a ``Flow Hydrograph QMin=`` line already exists
          inside the matched boundary block, its value is overwritten in place.
        - **Insert path**: if no QMin line exists, a new line is inserted after
          ``Flow Hydrograph QMult=`` if present, otherwise after
          ``Stage Hydrograph TW Check=``, otherwise before the first DSS
          metadata line, otherwise just before the first ``=`` line that
          follows the inline hydrograph data.

        Target resolution
        -----------------
        Provide *exactly one* of:

        - ``(river, reach, station)`` for a 1D river boundary.
        - ``(area_2d, bc_line)`` for a 2D BC line on a 2D Flow Area perimeter.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character unsteady
            number (e.g. ``"01"``) when a project-bound ``ras_object`` is
            available.
        qmin : float
            Minimum flow value (cfs or cms). Must be non-negative and finite.
        river, reach, station : str, optional
            1D location selector. All three must be provided together.
        area_2d, bc_line : str, optional
            2D location selector. Both must be provided together.
        ras_object : optional
            Custom RAS object. ``boundaries_df`` is refreshed after the write.

        Returns
        -------
        Dict[str, Any]
            Reviewable before/after metadata with keys:

            - ``unsteady_file`` (str): absolute path written
            - ``matched_location`` (str): matched ``Boundary Location=`` value
            - ``bc_type`` (str): always ``'Flow Hydrograph'``
            - ``previous_qmin`` (float | None): prior QMin value, or ``None``
            - ``new_qmin`` (float): QMin written
            - ``updated_in_place`` (bool): True when existing line overwritten
            - ``lines_inserted`` (int): 1 if new line inserted, else 0
            - ``insert_anchor`` (str | None): keyword anchor for placement
            - ``boundaries_df_refreshed`` (bool)
            - ``block_before`` (str): boundary block text before edit
            - ``block_after`` (str): boundary block text after edit

        Raises
        ------
        ValueError
            If ``qmin`` is non-numeric, non-finite, or negative; if target
            selectors are inconsistent; if matched block is not a Flow
            Hydrograph; or if no boundary matches the selectors.
        FileNotFoundError
            If the unsteady flow file does not exist.

        Examples
        --------
        Set a minimum flow on a 1D boundary:

        >>> from ras_commander import RasUnsteady
        >>> result = RasUnsteady.set_flow_hydrograph_qmin(
        ...     "project.u01",
        ...     qmin=50.0,
        ...     river="White",
        ...     reach="Muncie",
        ...     station="15696.24",
        ... )
        >>> result["new_qmin"]
        50.0

        See Also
        --------
        set_flow_hydrograph_slope : Set energy-grade slope on Flow Hydrograph.
        update_flow_multiplier_by_station : Set QMult multiplier.
        """
        if isinstance(qmin, bool) or not isinstance(qmin, numbers.Real):
            raise ValueError(
                f"qmin must be a real number, got {type(qmin).__name__}"
            )
        qmin_val = float(qmin)
        if not np.isfinite(qmin_val):
            raise ValueError(f"qmin must be finite, got {qmin_val!r}")
        if qmin_val < 0:
            raise ValueError(f"qmin must be non-negative, got {qmin_val!r}")

        has_1d = any(x is not None for x in (river, reach, station))
        has_2d = any(x is not None for x in (area_2d, bc_line))
        if has_1d == has_2d:
            raise ValueError(
                "Provide exactly one selector group: (river, reach, station) "
                "OR (area_2d, bc_line)"
            )
        if has_1d and not (river and reach and station):
            raise ValueError(
                "1D selector requires all of river, reach, and station"
            )
        if has_2d and not (area_2d and bc_line):
            raise ValueError(
                "2D selector requires both area_2d and bc_line"
            )

        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        def _matches_location(loc_value: str) -> bool:
            parts = [p.strip() for p in loc_value.split(',')]
            if has_1d:
                return (
                    len(parts) >= 3
                    and parts[0] == river
                    and parts[1] == reach
                    and parts[2] == station
                )
            if len(parts) < 6 or parts[5] != area_2d:
                return False
            if len(parts) < 8 or parts[7] != bc_line:
                return False
            return True

        boundary_idx = None
        matched_loc = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                if _matches_location(loc_value):
                    boundary_idx = i
                    matched_loc = loc_value
                    break

        if boundary_idx is None:
            sel = (
                f"river={river!r}/reach={reach!r}/station={station!r}"
                if has_1d
                else f"area_2d={area_2d!r}/bc_line={bc_line!r}"
            )
            raise ValueError(
                f"No boundary matched in {unsteady_path.name} for {sel}. "
                f"This function only edits Flow Hydrograph boundaries that "
                f"already exist as `Boundary Location=` blocks."
            )

        FLOW_HYDROGRAPH_HEADER = 'Flow Hydrograph='
        QMIN_KEY = 'Flow Hydrograph QMin='
        QMULT_KEY = 'Flow Hydrograph QMult='
        TW_CHECK_KEY = 'Stage Hydrograph TW Check='
        DSS_LINE_KEYS = ('DSS Path=', 'DSS File=', 'Use DSS=')

        flow_header_idx: Optional[int] = None
        qmin_idx: Optional[int] = None
        qmult_idx: Optional[int] = None
        tw_check_idx: Optional[int] = None
        first_dss_idx: Optional[int] = None
        first_dss_keyword: Optional[str] = None
        first_post_data_eq_idx: Optional[int] = None
        BLOCK_SCAN_CAP = 1000
        block_end = min(boundary_idx + 1 + BLOCK_SCAN_CAP, len(lines))

        j = boundary_idx + 1
        while j < block_end:
            line = lines[j]
            if line.startswith('Boundary Location='):
                block_end = j
                break
            if line.startswith(FLOW_HYDROGRAPH_HEADER):
                flow_header_idx = j
            j += 1

        if flow_header_idx is None:
            raise ValueError(
                f"Boundary at {matched_loc.strip()!r} is not a Flow Hydrograph "
                f"(no `Flow Hydrograph=<count>` header in block); "
                f"`Flow Hydrograph QMin=` only applies to Flow Hydrograph BCs"
            )

        try:
            count = int(lines[flow_header_idx].replace(FLOW_HYDROGRAPH_HEADER, '').split(',')[0].strip())
        except (ValueError, IndexError):
            count = 0
        post_data_idx = flow_header_idx + 1
        if count > 0:
            for k in range(flow_header_idx + 1, block_end):
                if '=' in lines[k] or lines[k].startswith('Boundary Location='):
                    post_data_idx = k
                    break
            else:
                post_data_idx = block_end

        for j in range(post_data_idx, block_end):
            line = lines[j]
            if line.startswith(QMIN_KEY) and qmin_idx is None:
                qmin_idx = j
            elif line.startswith(QMULT_KEY) and qmult_idx is None:
                qmult_idx = j
            elif line.startswith(TW_CHECK_KEY) and tw_check_idx is None:
                tw_check_idx = j
            else:
                for dss_kw in DSS_LINE_KEYS:
                    if line.startswith(dss_kw) and first_dss_idx is None:
                        first_dss_idx = j
                        first_dss_keyword = dss_kw
                        break
            if first_post_data_eq_idx is None and '=' in line:
                first_post_data_eq_idx = j

        block_before = ''.join(lines[boundary_idx:block_end])

        previous_qmin: Optional[float] = None
        if qmin_idx is not None:
            payload = lines[qmin_idx].replace(QMIN_KEY, '').strip()
            try:
                previous_qmin = float(payload.split(',')[0].strip())
            except (ValueError, IndexError):
                previous_qmin = None

        new_qmin_line = f'Flow Hydrograph QMin= {qmin_val} \n'

        lines_inserted = 0
        updated_in_place = False
        insert_anchor: Optional[str] = None

        if qmin_idx is not None:
            lines[qmin_idx] = new_qmin_line
            updated_in_place = True
        else:
            if qmult_idx is not None:
                insert_pos = qmult_idx + 1
                insert_anchor = QMULT_KEY
            elif tw_check_idx is not None:
                insert_pos = tw_check_idx + 1
                insert_anchor = TW_CHECK_KEY
            elif first_dss_idx is not None:
                insert_pos = first_dss_idx
                insert_anchor = first_dss_keyword
            elif first_post_data_eq_idx is not None:
                insert_pos = first_post_data_eq_idx
                insert_anchor = '<inline-data-tail>'
            else:
                insert_pos = block_end
                insert_anchor = '<block-end>'
            lines.insert(insert_pos, new_qmin_line)
            lines_inserted = 1

        new_block_end = boundary_idx + 1
        while (
            new_block_end < len(lines)
            and not lines[new_block_end].startswith('Boundary Location=')
        ):
            new_block_end += 1
        block_after = ''.join(lines[boundary_idx:new_block_end])

        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        logger.info(
            "Set Flow Hydrograph QMin in %s: matched=%s, qmin=%s, "
            "updated_in_place=%s, anchor=%s",
            unsteady_path.name,
            matched_loc.strip(),
            qmin_val,
            updated_in_place,
            insert_anchor,
        )

        return {
            'unsteady_file': str(unsteady_path),
            'matched_location': matched_loc,
            'bc_type': 'Flow Hydrograph',
            'previous_qmin': previous_qmin,
            'new_qmin': qmin_val,
            'updated_in_place': updated_in_place,
            'lines_inserted': lines_inserted,
            'insert_anchor': insert_anchor,
            'boundaries_df_refreshed': boundaries_df_refreshed,
            'block_before': block_before,
            'block_after': block_after,
        }

    @staticmethod
    @log_call
    def set_normal_depth_boundary(
        unsteady_file: Union[str, Path],
        friction_slope: float,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        area_2d: Optional[str] = None,
        bc_line: Optional[str] = None,
        use_critical_fallback: bool = False,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Add or update a Normal Depth boundary condition for a target boundary
        in a HEC-RAS unsteady flow file (.u##).

        The method writes a ``Friction Slope=<slope>`` line (or
        ``Friction Slope=<slope>,<flag>`` when a flag is required, see below)
        into the matching boundary block. If the block already has a
        ``Friction Slope=`` line it is updated in place; otherwise the line is
        inserted immediately after the ``Boundary Location=`` line, and any
        other inline-table BC header (Flow Hydrograph, Stage Hydrograph,
        Lateral Inflow, Uniform Lateral Inflow, Precipitation Hydrograph,
        Rating Curve, Gate Name) plus its inline data and any DSS metadata
        lines (``Interval=``, ``DSS File=``, ``DSS Path=``, ``Use DSS=``) are
        stripped so the block ends up as a clean Normal Depth boundary.

        The function ONLY edits a boundary that already exists in the .u## as
        a ``Boundary Location=`` block. If the matched-by-name location is
        absent, ``ValueError`` is raised. Authoring brand-new boundary blocks
        from geometry definitions (``create-if-missing`` semantics with
        geometry-file validation) is tracked separately as a follow-up; see
        the *See Also* section.

        Format conventions observed in real HEC-RAS .u## files
        ------------------------------------------------------
        Both ``Friction Slope=<slope>`` and ``Friction Slope=<slope>,<flag>``
        forms appear in HEC-RAS-emitted files. 2D Normal Depth boundaries
        (e.g. on 2D BC lines) are typically written without the flag, while
        1D river Normal Depth boundaries usually include ``,0``. To stay
        compatible with both:

        - When **updating** an existing ``Friction Slope=`` line, the original
          flag presence is preserved unless ``use_critical_fallback=True``
          forces the flag to be present and set to ``1``.
        - When **inserting** a new line (type conversion or the block had no
          recognized type), the flag is omitted by default, and only emitted
          (as ``,1``) when ``use_critical_fallback=True``.

        Target resolution
        -----------------
        Provide *exactly one* of:

        - ``(river, reach, station)`` for a 1D river boundary, matched on the
          first three comma-separated fields of ``Boundary Location=``.
        - ``(area_2d, bc_line)`` for a 2D BC line attached to a 2D Flow Area,
          matched on the ``Boundary Location=`` 2D Flow Area name (field
          index 5) and the BC line / SA name (field index 7). For Normal
          Depth, ``bc_line`` is required: a Normal Depth boundary must attach
          to a specific 2D Flow Area perimeter BC line, never to the area as
          a whole.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character unsteady
            number (e.g. ``"01"``) when a project-bound ``ras_object`` is
            available.
        friction_slope : float
            Energy slope for the Normal Depth boundary (m/m or ft/ft). Must be
            in the inclusive range ``[1e-7, 1.0]``.
        river, reach, station : str, optional
            1D location selector. All three must be provided together and only
            when the 2D selectors are not used.
        area_2d : str, optional
            2D Flow Area name selector. Required for 2D targeting, and must be
            paired with ``bc_line``.
        bc_line : str, optional
            BC line name on the 2D Flow Area perimeter. Required for 2D
            targeting; Normal Depth never applies area-wide.
        use_critical_fallback : bool, default False
            Forces the flag to be present and set to ``1`` on the
            ``Friction Slope=`` line. When ``False`` (the default), the flag
            is omitted from newly inserted lines and preserved as-was for
            in-place updates. ``True`` writes ``Friction Slope=<slope>,1``.
        ras_object : optional
            Custom RAS object to use instead of the global one. When the object
            is initialized for a project, ``boundaries_df`` is refreshed after
            the write.

        Returns
        -------
        Dict[str, Any]
            Reviewable before/after metadata with keys:

            - ``unsteady_file`` (str): absolute path written
            - ``matched_location`` (str): the matched ``Boundary Location=``
              line value (without the leading ``Boundary Location=``)
            - ``previous_bc_type`` (str | None): boundary type before the edit,
              or ``None`` if the block had no recognized type keyword
            - ``previous_friction_slope`` (float | None): prior slope value,
              or ``None`` if no Friction Slope line existed
            - ``new_friction_slope`` (float): slope written
            - ``flag`` (int | None): the integer flag written on the line
              (typically ``0`` or ``1``), or ``None`` when the line was
              written without a flag
            - ``lines_removed`` (int): count of old type-header / inline-data /
              DSS-metadata lines stripped during a type conversion
            - ``lines_inserted`` (int): 1 if a new ``Friction Slope=`` line was
              inserted, otherwise 0
            - ``updated_in_place`` (bool): True when an existing
              ``Friction Slope=`` line was overwritten without insertion
            - ``boundaries_df_refreshed`` (bool): True when ``ras_object``
              ``boundaries_df`` was refreshed after the write
            - ``block_before`` (str): the boundary block text before the edit
            - ``block_after`` (str): the boundary block text after the edit

        Raises
        ------
        ValueError
            If ``friction_slope`` is non-numeric, non-finite, or outside
            ``[1e-7, 1.0]``; if the target selectors are inconsistent (both
            1D and 2D selectors provided, or neither); if a 1D selector is
            partial; if a 2D selector is missing ``bc_line``; or if no
            boundary in the file matches the selectors.
        FileNotFoundError
            If the unsteady flow file does not exist.

        Examples
        --------
        Set a Normal Depth boundary on a 2D BC line (writes
        ``Friction Slope=0.0003`` with no flag, matching the 2D format
        emitted by HEC-RAS for examples like BaldEagleCrkMulti2D):

        >>> from ras_commander import RasUnsteady
        >>> result = RasUnsteady.set_normal_depth_boundary(
        ...     "project.u01",
        ...     friction_slope=0.0003,
        ...     area_2d="BaldEagleCr",
        ...     bc_line="DSNormalDepth",
        ... )
        >>> result["new_friction_slope"], result["updated_in_place"]
        (0.0003, False)

        Update an existing Normal Depth slope on a 1D downstream boundary
        (preserves the original ``,<flag>`` form when present, e.g.
        ``Friction Slope=0.00064,0`` becomes ``Friction Slope=0.001,0``):

        >>> RasUnsteady.set_normal_depth_boundary(
        ...     "project.u01",
        ...     friction_slope=0.001,
        ...     river="White",
        ...     reach="Muncie",
        ...     station="237.6455",
        ... )

        See Also
        --------
        set_boundary_dss_link : Convert inline BC to DSS-linked.
        set_boundary_inline_hydrograph : Write inline hydrograph table.
        ras_commander.RasPrj.get_boundary_conditions : Parse boundaries to
            ``boundaries_df``.

        Notes
        -----
        **1D applicability**: Normal Depth is a downstream-only boundary
        condition for 1D reaches. HEC-RAS uses the Manning equation with
        the specified friction slope to compute the stage at the most
        downstream cross section. Do not apply this to upstream 1D
        boundaries — use Flow Hydrograph or Stage Hydrograph instead.

        **Follow-up scope (out of this function)**: validation that the
        selected boundary actually exists in the geometry file, and creating
        a brand-new ``Boundary Location=`` block when the boundary exists in
        geometry but is absent from the .u##. Tracked under a separate Linear
        ticket so the contracts for placement order, geometry discovery, and
        1D-vs-2D field padding can be designed end-to-end.
        """
        # 1) Validate slope. `numbers.Real` accepts Python int/float plus
        # numpy scalars (e.g. np.float64 returned from `boundaries_df`
        # columns), which `isinstance(x, (int, float))` does NOT under
        # NumPy 2.x. The bool-subclass-of-int guard fires first because
        # bool would otherwise pass through both checks.
        if isinstance(friction_slope, bool) or not isinstance(friction_slope, numbers.Real):
            raise ValueError(
                f"friction_slope must be a real number, got {type(friction_slope).__name__}"
            )
        fs = float(friction_slope)
        if not np.isfinite(fs):
            raise ValueError(f"friction_slope must be finite, got {fs!r}")
        if not (1e-7 <= fs <= 1.0):
            raise ValueError(
                f"friction_slope {fs!r} is outside the supported range [1e-7, 1.0]"
            )

        # 2) Validate target selectors
        has_1d = any(x is not None for x in (river, reach, station))
        has_2d = any(x is not None for x in (area_2d, bc_line))
        if has_1d == has_2d:
            raise ValueError(
                "Provide exactly one selector group: (river, reach, station) "
                "OR (area_2d, bc_line)"
            )
        if has_1d and not (river and reach and station):
            raise ValueError(
                "1D selector requires all of river, reach, and station"
            )
        if has_2d and not (area_2d and bc_line):
            # Normal Depth on a 2D Flow Area perimeter must attach to a
            # specific BC line. There is no "area-wide" Normal Depth — that
            # only makes sense for area-wide types (e.g. Precipitation
            # Hydrograph), not for Normal Depth.
            raise ValueError(
                "2D selector requires both area_2d and bc_line for Normal Depth"
            )

        # 3) Resolve unsteady file path (allow short numbers when ras is set)
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # 4) Read file and find target Boundary Location block
        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        def _matches_location(loc_value: str) -> bool:
            parts = [p.strip() for p in loc_value.split(',')]
            if has_1d:
                return (
                    len(parts) >= 3
                    and parts[0] == river
                    and parts[1] == reach
                    and parts[2] == station
                )
            # 2D layout: field 5 = 2D Flow Area name, field 7 = BC line name.
            # HEC-RAS emits both 8-field and 9-field forms for Boundary
            # Location; matching is keyed on field index, not field count.
            if len(parts) < 6 or parts[5] != area_2d:
                return False
            if len(parts) < 8 or parts[7] != bc_line:
                return False
            return True

        boundary_idx = None
        matched_loc = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                if _matches_location(loc_value):
                    boundary_idx = i
                    matched_loc = loc_value
                    break

        if boundary_idx is None:
            sel = (
                f"river={river!r}/reach={reach!r}/station={station!r}"
                if has_1d
                else f"area_2d={area_2d!r}/bc_line={bc_line!r}"
            )
            raise ValueError(
                f"No boundary matched in {unsteady_path.name} for {sel}. "
                f"This function only edits boundaries that already exist as "
                f"`Boundary Location=` blocks; create-if-missing semantics "
                f"are tracked as a follow-up."
            )

        # 5) Walk the block to identify Friction Slope, other BC type,
        #    DSS metadata lines, and BC-type-specific extra metadata that
        #    must be stripped on type conversion to Normal Depth.
        OTHER_BC_KEYWORDS = {
            'Flow Hydrograph=': 'Flow Hydrograph',
            'Stage Hydrograph=': 'Stage Hydrograph',
            'Lateral Inflow Hydrograph=': 'Lateral Inflow Hydrograph',
            'Uniform Lateral Inflow=': 'Uniform Lateral Inflow',
            'Uniform Lateral Inflow Hydrograph=': 'Uniform Lateral Inflow Hydrograph',
            'Precipitation Hydrograph=': 'Precipitation Hydrograph',
            'Rating Curve=': 'Rating Curve',
            'Gate Name=': 'Gate Opening',
            'Observed Stage and Flow Hydrograph=': 'Observed Stage and Flow',
        }
        DSS_METADATA_KEYS = ('Interval=', 'DSS File=', 'DSS Path=', 'Use DSS=')
        # Lines that real HEC-RAS Flow Hydrograph / Stage Hydrograph /
        # Lateral Inflow blocks carry alongside their inline data and DSS
        # metadata. Observed in Muncie.u01 and BaldEagleDamBrk.u02. These
        # are meaningless on a Normal Depth boundary and must be stripped
        # during type conversion or HEC-RAS will encounter unexpected
        # keys in the converted block.
        TYPE_SPECIFIC_EXTRAS = (
            'Flow Hydrograph Slope=',
            'Flow Hydrograph QMult=',
            'Flow Hydrograph QMin=',
            'Stage Hydrograph TW Check=',
            'Use Fixed Start Time=',
            'Fixed Start Date/Time=',
            'Is Critical Boundary=',
            'Critical Boundary Flow=',
        )

        block_end = len(lines)
        friction_idx = None
        other_type_idx = None
        other_type_keyword = None
        inline_data_start = None
        inline_data_end = None
        dss_metadata_idxs: List[int] = []
        type_extra_idxs: List[int] = []

        j = boundary_idx + 1
        while j < len(lines) and j < boundary_idx + 500:
            line = lines[j]
            if line.startswith('Boundary Location='):
                block_end = j
                break

            if line.startswith('Friction Slope='):
                friction_idx = j
            else:
                matched_other = False
                for kw in OTHER_BC_KEYWORDS:
                    if line.startswith(kw):
                        if other_type_idx is None:
                            other_type_idx = j
                            other_type_keyword = kw
                            try:
                                count = int(line.replace(kw, '').split(',')[0].strip())
                            except (ValueError, IndexError):
                                count = 0
                            if count > 0:
                                inline_data_start = j + 1
                                for k in range(inline_data_start, len(lines)):
                                    data_line = lines[k]
                                    if '=' in data_line or data_line.startswith(
                                        'Boundary Location='
                                    ):
                                        inline_data_end = k
                                        break
                                else:
                                    inline_data_end = len(lines)
                        matched_other = True
                        break
                if not matched_other:
                    matched_dss = False
                    for dss_kw in DSS_METADATA_KEYS:
                        if line.startswith(dss_kw):
                            dss_metadata_idxs.append(j)
                            matched_dss = True
                            break
                    if not matched_dss:
                        for extra_kw in TYPE_SPECIFIC_EXTRAS:
                            if line.startswith(extra_kw):
                                type_extra_idxs.append(j)
                                break
            j += 1

        block_before = ''.join(lines[boundary_idx:block_end])

        previous_friction_slope: Optional[float] = None
        previous_friction_flag: Optional[int] = None
        if friction_idx is not None:
            payload = lines[friction_idx].replace('Friction Slope=', '').strip()
            tokens = [t.strip() for t in payload.split(',')]
            try:
                previous_friction_slope = float(tokens[0])
            except (ValueError, IndexError):
                previous_friction_slope = None
            if len(tokens) >= 2 and tokens[1] != '':
                try:
                    previous_friction_flag = int(tokens[1])
                except ValueError:
                    previous_friction_flag = None

        if friction_idx is not None:
            previous_bc_type = 'Normal Depth'
        elif other_type_idx is not None:
            previous_bc_type = OTHER_BC_KEYWORDS.get(other_type_keyword)
        else:
            previous_bc_type = None

        # 6) Compose new line and apply edit. HEC-RAS emits both
        # ``Friction Slope=<slope>`` (typical for 2D BC lines) and
        # ``Friction Slope=<slope>,<flag>`` (typical for 1D river NDs);
        # preserve the form AND the flag value present on update, default
        # to no-flag on insert, and force flag=1 only when
        # ``use_critical_fallback=True``.
        if use_critical_fallback:
            flag: Optional[int] = 1
        elif friction_idx is not None and previous_friction_flag is not None:
            # Preserve the existing flag value (e.g. an existing flag=1 is
            # NOT silently reset to 0 when the user calls without
            # use_critical_fallback). The user opts into changing the flag
            # via the use_critical_fallback parameter.
            flag = previous_friction_flag
        else:
            flag = None
        new_fs_line = (
            f'Friction Slope={fs},{flag}\n' if flag is not None
            else f'Friction Slope={fs}\n'
        )

        lines_removed = 0
        lines_inserted = 0
        updated_in_place = False

        if friction_idx is not None:
            # Already a Normal Depth boundary — overwrite slope/flag in place.
            lines[friction_idx] = new_fs_line
            updated_in_place = True
        else:
            # Convert from another BC type (or fill in a type-less block).
            # Strip the prior type's header + inline data + DSS metadata
            # + any BC-type-specific extras (Flow Hydrograph QMult/Slope,
            # Stage Hydrograph TW Check, Use Fixed Start Time, etc.) so
            # the resulting Normal Depth block is structurally clean.
            delete_idxs: set = set()
            if other_type_idx is not None:
                delete_idxs.add(other_type_idx)
                if inline_data_start is not None and inline_data_end is not None:
                    for k in range(inline_data_start, inline_data_end):
                        delete_idxs.add(k)
            for d in dss_metadata_idxs:
                delete_idxs.add(d)
            for d in type_extra_idxs:
                delete_idxs.add(d)
            for idx in sorted(delete_idxs, reverse=True):
                del lines[idx]
                lines_removed += 1
            lines.insert(boundary_idx + 1, new_fs_line)
            lines_inserted = 1

        # Recompute end-of-block for the after-snapshot
        new_block_end = boundary_idx + 1
        while (
            new_block_end < len(lines)
            and not lines[new_block_end].startswith('Boundary Location=')
        ):
            new_block_end += 1
        block_after = ''.join(lines[boundary_idx:new_block_end])

        # 7) Persist file
        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        # 8) Refresh boundaries_df where possible
        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        logger.info(
            "Set Normal Depth boundary in %s: matched=%s, slope=%s, flag=%s, "
            "removed=%d, inserted=%d, updated_in_place=%s",
            unsteady_path.name,
            matched_loc.strip(),
            fs,
            flag if flag is not None else 'omitted',
            lines_removed,
            lines_inserted,
            updated_in_place,
        )

        return {
            'unsteady_file': str(unsteady_path),
            'matched_location': matched_loc,
            'previous_bc_type': previous_bc_type,
            'previous_friction_slope': previous_friction_slope,
            'new_friction_slope': fs,
            'flag': flag,
            'lines_removed': lines_removed,
            'lines_inserted': lines_inserted,
            'updated_in_place': updated_in_place,
            'boundaries_df_refreshed': boundaries_df_refreshed,
            'block_before': block_before,
            'block_after': block_after,
        }

    @staticmethod
    @log_call
    def set_stage_hydrograph_tw_check(
        unsteady_file: Union[str, Path],
        tw_check: int,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        area_2d: Optional[str] = None,
        bc_line: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Add or update a Stage Hydrograph TW Check flag on a Flow Hydrograph
        boundary in a HEC-RAS unsteady flow file (.u##).

        Despite the misleading keyword name ``Stage Hydrograph TW Check=``,
        this field appears inside **Flow Hydrograph** boundary blocks in
        HEC-RAS-emitted .u## files.  It controls whether HEC-RAS performs a
        tailwater check for the boundary (0 = disabled, 1 = enabled).

        Behavior
        --------
        - **Update path**: if a ``Stage Hydrograph TW Check=`` line already
          exists in the matched boundary block, its value is overwritten in
          place.
        - **Insert path**: if no TW Check line exists, a new line is inserted
          in the canonical position: after ``Flow Hydrograph QMult=`` if
          present, otherwise after ``Flow Hydrograph Slope=`` if present,
          otherwise immediately before the first DSS metadata line
          (``DSS Path=``, ``DSS File=``, ``Use DSS=``), otherwise just before
          the first ``=`` line after the inline hydrograph data.

        Target resolution
        -----------------
        Provide *exactly one* of:

        - ``(river, reach, station)`` for a 1D river boundary.
        - ``(area_2d, bc_line)`` for a 2D BC line on a 2D Flow Area perimeter.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character unsteady
            number (e.g. ``"01"``) when a project-bound ``ras_object`` is
            available.
        tw_check : int
            Tailwater check flag.  Must be 0 (disabled) or 1 (enabled).
        river, reach, station : str, optional
            1D location selector.  All three must be provided together.
        area_2d, bc_line : str, optional
            2D location selector.  Both must be provided together.
        ras_object : optional
            Custom RAS object.  When initialized for a project,
            ``boundaries_df`` is refreshed after the write.

        Returns
        -------
        Dict[str, Any]
            Reviewable metadata with keys:

            - ``unsteady_file`` (str): absolute path written
            - ``matched_location`` (str): the matched ``Boundary Location=``
            - ``bc_type`` (str): always ``'Flow Hydrograph'``
            - ``previous_tw_check`` (int | None): prior value, or ``None``
            - ``new_tw_check`` (int): value written
            - ``updated_in_place`` (bool): True if existing line overwritten
            - ``lines_inserted`` (int): 1 if new line inserted, else 0
            - ``insert_anchor`` (str | None): keyword anchor used for insert
            - ``boundaries_df_refreshed`` (bool)
            - ``block_before`` (str): boundary block text before edit
            - ``block_after`` (str): boundary block text after edit

        Raises
        ------
        ValueError
            If ``tw_check`` is not 0 or 1; if selectors are invalid; if the
            matched block is not a Flow Hydrograph.
        FileNotFoundError
            If the unsteady flow file does not exist.

        Examples
        --------
        Enable TW check on a 2D Flow Hydrograph boundary:

        >>> result = RasUnsteady.set_stage_hydrograph_tw_check(
        ...     "BaldEagleDamBrk.u02",
        ...     tw_check=1,
        ...     area_2d="BaldEagleCr",
        ...     bc_line="Upstream Inflow",
        ... )
        >>> result["new_tw_check"]
        1

        See Also
        --------
        set_flow_hydrograph_slope : Set distribution slope on Flow Hydrograph.
        """
        # 1) Validate tw_check
        if not isinstance(tw_check, int) or isinstance(tw_check, bool):
            raise ValueError(
                f"tw_check must be an integer (0 or 1), got {type(tw_check).__name__}"
            )
        if tw_check not in (0, 1):
            raise ValueError(
                f"tw_check must be 0 or 1, got {tw_check!r}"
            )

        # 2) Validate target selectors
        has_1d = any(x is not None for x in (river, reach, station))
        has_2d = any(x is not None for x in (area_2d, bc_line))
        if has_1d == has_2d:
            raise ValueError(
                "Provide exactly one selector group: (river, reach, station) "
                "OR (area_2d, bc_line)"
            )
        if has_1d and not (river and reach and station):
            raise ValueError(
                "1D selector requires all of river, reach, and station"
            )
        if has_2d and not (area_2d and bc_line):
            raise ValueError(
                "2D selector requires both area_2d and bc_line"
            )

        # 3) Resolve unsteady file path
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # 4) Read file and find target Boundary Location block
        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        def _matches_location(loc_value: str) -> bool:
            parts = [p.strip() for p in loc_value.split(',')]
            if has_1d:
                return (
                    len(parts) >= 3
                    and parts[0] == river
                    and parts[1] == reach
                    and parts[2] == station
                )
            if len(parts) < 6 or parts[5] != area_2d:
                return False
            if len(parts) < 8 or parts[7] != bc_line:
                return False
            return True

        boundary_idx = None
        matched_loc = ''
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc = line[len('Boundary Location='):]
                if _matches_location(loc):
                    boundary_idx = i
                    matched_loc = loc
                    break

        sel = (
            f"river={river!r}, reach={reach!r}, station={station!r}"
            if has_1d
            else f"area_2d={area_2d!r}, bc_line={bc_line!r}"
        )
        if boundary_idx is None:
            raise ValueError(
                f"No boundary matched in {unsteady_path.name} for {sel}. "
                f"This function only edits Flow Hydrograph boundaries that "
                f"already exist as `Boundary Location=` blocks."
            )

        # 5) Walk the block; verify it is a Flow Hydrograph; locate anchors.
        FLOW_HYDROGRAPH_HEADER = 'Flow Hydrograph='
        TW_CHECK_KEY = 'Stage Hydrograph TW Check='
        SLOPE_KEY = 'Flow Hydrograph Slope='
        QMULT_KEY = 'Flow Hydrograph QMult='
        DSS_LINE_KEYS = ('DSS Path=', 'DSS File=', 'Use DSS=')

        flow_header_idx: Optional[int] = None
        tw_check_idx: Optional[int] = None
        slope_idx: Optional[int] = None
        qmult_idx: Optional[int] = None
        first_dss_idx: Optional[int] = None
        first_dss_keyword: Optional[str] = None
        first_post_data_eq_idx: Optional[int] = None

        BLOCK_SCAN_CAP = 1000
        block_end = min(boundary_idx + 1 + BLOCK_SCAN_CAP, len(lines))

        j = boundary_idx + 1
        while j < block_end:
            line = lines[j]
            if line.startswith('Boundary Location='):
                block_end = j
                break
            if line.startswith(FLOW_HYDROGRAPH_HEADER):
                flow_header_idx = j
            j += 1

        if flow_header_idx is None:
            raise ValueError(
                f"Boundary at {matched_loc.strip()!r} is not a Flow Hydrograph "
                f"(no `Flow Hydrograph=<count>` header in block); "
                f"`Stage Hydrograph TW Check=` only applies to Flow Hydrograph BCs"
            )

        try:
            count = int(lines[flow_header_idx].replace(FLOW_HYDROGRAPH_HEADER, '').split(',')[0].strip())
        except (ValueError, IndexError):
            count = 0
        post_data_idx = flow_header_idx + 1
        if count > 0:
            for k in range(flow_header_idx + 1, block_end):
                if '=' in lines[k] or lines[k].startswith('Boundary Location='):
                    post_data_idx = k
                    break
            else:
                post_data_idx = block_end

        for j in range(post_data_idx, block_end):
            line = lines[j]
            if line.startswith(TW_CHECK_KEY) and tw_check_idx is None:
                tw_check_idx = j
            elif line.startswith(SLOPE_KEY) and slope_idx is None:
                slope_idx = j
            elif line.startswith(QMULT_KEY) and qmult_idx is None:
                qmult_idx = j
            else:
                for dss_kw in DSS_LINE_KEYS:
                    if line.startswith(dss_kw) and first_dss_idx is None:
                        first_dss_idx = j
                        first_dss_keyword = dss_kw
                        break
            if first_post_data_eq_idx is None and '=' in line:
                first_post_data_eq_idx = j

        block_before = ''.join(lines[boundary_idx:block_end])

        previous_tw_check: Optional[int] = None
        if tw_check_idx is not None:
            payload = lines[tw_check_idx].replace(TW_CHECK_KEY, '').strip()
            try:
                previous_tw_check = int(payload)
            except ValueError:
                previous_tw_check = None

        # 6) Compose new line and apply edit.
        new_tw_line = f'Stage Hydrograph TW Check={tw_check}\n'

        lines_inserted = 0
        updated_in_place = False
        insert_anchor: Optional[str] = None

        if tw_check_idx is not None:
            lines[tw_check_idx] = new_tw_line
            updated_in_place = True
        else:
            if qmult_idx is not None:
                insert_pos = qmult_idx + 1
                insert_anchor = QMULT_KEY
            elif slope_idx is not None:
                insert_pos = slope_idx + 1
                insert_anchor = SLOPE_KEY
            elif first_dss_idx is not None:
                insert_pos = first_dss_idx
                insert_anchor = first_dss_keyword
            elif first_post_data_eq_idx is not None:
                insert_pos = first_post_data_eq_idx
                insert_anchor = '<inline-data-tail>'
            else:
                insert_pos = block_end
                insert_anchor = '<block-end>'
            lines.insert(insert_pos, new_tw_line)
            lines_inserted = 1

        new_block_end = boundary_idx + 1
        while (
            new_block_end < len(lines)
            and not lines[new_block_end].startswith('Boundary Location=')
        ):
            new_block_end += 1
        block_after = ''.join(lines[boundary_idx:new_block_end])

        # 7) Persist file
        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        # 8) Refresh boundaries_df where possible
        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        logger.info(
            "Set Stage Hydrograph TW Check in %s: matched=%s, tw_check=%d, "
            "updated_in_place=%s, anchor=%s",
            unsteady_path.name,
            matched_loc.strip(),
            tw_check,
            updated_in_place,
            insert_anchor,
        )

        return {
            'unsteady_file': str(unsteady_path),
            'matched_location': matched_loc,
            'bc_type': 'Flow Hydrograph',
            'previous_tw_check': previous_tw_check,
            'new_tw_check': tw_check,
            'updated_in_place': updated_in_place,
            'lines_inserted': lines_inserted,
            'insert_anchor': insert_anchor,
            'boundaries_df_refreshed': boundaries_df_refreshed,
            'block_before': block_before,
            'block_after': block_after,
        }

    @staticmethod
    @log_call
    def get_unique_dss_subbasins(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> List[str]:
        """
        Get list of unique HMS subbasin names from DSS paths in unsteady file.

        This convenience function extracts the DSS Part B (location/subbasin)
        from all DSS-linked boundaries and returns the unique values. This is
        useful for identifying which HMS subbasins are used by the RAS model.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        List[str]
            Sorted list of unique subbasin names from DSS Part B

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> subbasins = RasUnsteady.get_unique_dss_subbasins("project.u01")
        >>> print(f"Model uses {len(subbasins)} HMS subbasins:")
        >>> for sb in subbasins[:10]:
        ...     print(f"  - {sb}")
        """
        df = RasUnsteady.get_dss_boundaries(unsteady_file, ras_object)

        if df.empty:
            return []

        # Get unique Part B values (subbasin names)
        subbasins = df['dss_part_b'].dropna().unique().tolist()
        subbasins = [s for s in subbasins if s]  # Remove empty strings
        subbasins.sort()

        logger.info(f"Found {len(subbasins)} unique HMS subbasins in DSS paths")
        return subbasins

    @staticmethod
    @log_call
    def update_dss_path_by_station(
        unsteady_file: Union[str, Path],
        river_station: str,
        new_a_part: str,
        old_a_part: str = None,
        ras_object: Optional[Any] = None
    ) -> int:
        """
        Update the DSS Path A-part for boundary conditions at a specific river station.

        This function modifies the DSS Path values in a .u## file, changing the
        A-part (first segment) from one value to another. Useful for mapping HMS
        subbasins to different DSS outputs.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        river_station : str
            River station identifier (partial match supported)
        new_a_part : str
            New A-part value (e.g., "A120A")
        old_a_part : str, optional
            Only replace if current A-part matches this value. If None, replaces
            regardless of current value.
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        int
            Number of DSS paths updated

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Update A-part for boundary at specific station
        >>> count = RasUnsteady.update_dss_path_by_station(
        ...     "project.u02",
        ...     river_station="23280.75",
        ...     old_a_part="A1200000_2347_J",
        ...     new_a_part="A120A"
        ... )
        >>> print(f"Updated {count} DSS paths")
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        update_count = 0
        i = 0
        while i < len(lines):
            line = lines[i]

            # Find matching Boundary Location
            if line.startswith('Boundary Location=') and river_station in line:
                # Look for DSS Path within this boundary block (search forward)
                j = i + 1
                while j < len(lines) and j < i + 50:
                    if lines[j].startswith('Boundary Location='):
                        break  # Next boundary block
                    if lines[j].startswith('DSS Path='):
                        dss_path = lines[j].replace('DSS Path=', '').strip()
                        # Parse current A-part
                        clean_path = dss_path.strip('/')
                        parts = clean_path.split('/')
                        if len(parts) >= 1:
                            current_a_part = parts[0]
                            # Check if we should update (old_a_part matches or not specified)
                            if old_a_part is None or current_a_part == old_a_part:
                                # Build new path with new A-part
                                parts[0] = new_a_part
                                new_dss_path = '//' + '/'.join(parts) + '/'
                                lines[j] = f'DSS Path={new_dss_path}\n'
                                update_count += 1
                                logger.debug(f"Updated DSS Path at line {j+1}: A-part '{current_a_part}' -> '{new_a_part}'")
                        break
                    j += 1
            i += 1

        if update_count > 0:
            with open(unsteady_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Updated {update_count} DSS paths in {unsteady_path.name}")
        else:
            if old_a_part:
                logger.warning(f"No DSS paths found for station '{river_station}' with A-part '{old_a_part}'")
            else:
                logger.warning(f"No DSS paths found for station '{river_station}'")

        return update_count

    @staticmethod
    @log_call
    def update_flow_multiplier_by_station(
        unsteady_file: Union[str, Path],
        river_station: str,
        new_multiplier: float,
        ras_object: Optional[Any] = None
    ) -> bool:
        """
        Update or insert Flow Hydrograph QMult for boundary at specific river station.

        If the `Flow Hydrograph QMult=` line exists, it will be updated. If it doesn't
        exist, it will be inserted after the Flow Hydrograph line.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        river_station : str
            River station identifier (partial match supported)
        new_multiplier : float
            New multiplier value (e.g., 0.5, 1.0)
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        bool
            True if multiplier was updated/inserted, False if boundary not found

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Set flow multiplier to 0.75 for specific boundary
        >>> success = RasUnsteady.update_flow_multiplier_by_station(
        ...     "project.u02",
        ...     river_station="5714.48",
        ...     new_multiplier=0.75
        ... )
        >>> if success:
        ...     print("Multiplier updated successfully")

        Notes
        -----
        The QMult line appears in unsteady files as:
            Flow Hydrograph QMult= 0.5

        If this line doesn't exist, it will be inserted after the Flow Hydrograph line
        in the boundary block.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        updated = False
        i = 0
        while i < len(lines):
            line = lines[i]

            # Find matching Boundary Location
            if line.startswith('Boundary Location=') and river_station in line:
                boundary_idx = i
                qmult_idx = None
                flow_hydro_idx = None
                block_end_idx = None

                # Scan the boundary block
                j = i + 1
                while j < len(lines) and j < i + 50:
                    current_line = lines[j]
                    if current_line.startswith('Boundary Location='):
                        block_end_idx = j
                        break
                    if current_line.startswith('Flow Hydrograph QMult='):
                        qmult_idx = j
                    if current_line.startswith('Flow Hydrograph='):
                        flow_hydro_idx = j
                    j += 1

                if block_end_idx is None:
                    block_end_idx = len(lines)

                # Format the new QMult line
                qmult_line = f'Flow Hydrograph QMult= {new_multiplier}\n'

                if qmult_idx is not None:
                    # Update existing line
                    old_value = lines[qmult_idx].replace('Flow Hydrograph QMult=', '').strip()
                    lines[qmult_idx] = qmult_line
                    logger.debug(f"Updated QMult at line {qmult_idx+1}: {old_value} -> {new_multiplier}")
                    updated = True
                elif flow_hydro_idx is not None:
                    # Insert after Flow Hydrograph line (skip the data values first)
                    # Find the end of hydrograph data by looking for next key=value line
                    insert_idx = flow_hydro_idx + 1
                    while insert_idx < block_end_idx:
                        test_line = lines[insert_idx].strip()
                        if '=' in test_line and not test_line[0].isdigit():
                            break
                        insert_idx += 1
                    lines.insert(insert_idx, qmult_line)
                    logger.debug(f"Inserted QMult at line {insert_idx+1}: {new_multiplier}")
                    updated = True
                else:
                    # No Flow Hydrograph found, insert after Boundary Location
                    lines.insert(boundary_idx + 1, qmult_line)
                    logger.debug(f"Inserted QMult at line {boundary_idx+2}: {new_multiplier}")
                    updated = True

                break  # Found and processed the matching boundary
            i += 1

        if updated:
            with open(unsteady_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Updated QMult to {new_multiplier} for station '{river_station}' in {unsteady_path.name}")
        else:
            logger.warning(f"Boundary not found for station '{river_station}'")

        return updated

    @staticmethod
    @log_call
    def update_boundary_dss_paths(
        unsteady_file: Union[str, Path],
        updates: List[Dict[str, Any]],
        ras_object: Optional[Any] = None
    ) -> int:
        """
        Apply multiple DSS path and multiplier updates to boundary conditions.

        This batch method processes multiple updates in a single file read/write
        cycle for efficiency. Each update can specify any combination of A-part
        change and/or multiplier change.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        updates : List[Dict[str, Any]]
            List of update dictionaries. Each dict can contain:
            - river_station: str (required) - partial match supported
            - new_a_part: str (optional) - new DSS A-part value
            - old_a_part: str (optional) - only replace if current A-part matches
            - new_multiplier: float (optional) - new QMult value
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        int
            Total number of updates applied

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> updates = [
        ...     {'river_station': '23280.75', 'old_a_part': 'A1200000_2347_J', 'new_a_part': 'A120A'},
        ...     {'river_station': '12727.63', 'old_a_part': 'A120D1', 'new_a_part': 'A120C'},
        ...     {'river_station': '5714.48', 'new_multiplier': 0.75},
        ...     {'river_station': '29113.3', 'new_a_part': 'A120B', 'new_multiplier': 0.5},
        ... ]
        >>> count = RasUnsteady.update_boundary_dss_paths("project.u02", updates)
        >>> print(f"Applied {count} updates")

        Notes
        -----
        This method reads the file once, applies all updates in memory, and writes
        once. This is more efficient than calling individual update methods for
        each boundary, especially when updating many boundaries.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        if not updates:
            logger.warning("No updates provided")
            return 0

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        total_updates = 0

        for update in updates:
            river_station = update.get('river_station')
            if not river_station:
                logger.warning("Update missing 'river_station' key, skipping")
                continue

            new_a_part = update.get('new_a_part')
            old_a_part = update.get('old_a_part')
            new_multiplier = update.get('new_multiplier')

            # Find the boundary block
            i = 0
            while i < len(lines):
                line = lines[i]

                if line.startswith('Boundary Location=') and river_station in line:
                    boundary_idx = i
                    block_end_idx = None
                    dss_path_idx = None
                    qmult_idx = None
                    flow_hydro_idx = None

                    # Scan the boundary block
                    j = i + 1
                    while j < len(lines) and j < i + 50:
                        current_line = lines[j]
                        if current_line.startswith('Boundary Location='):
                            block_end_idx = j
                            break
                        if current_line.startswith('DSS Path='):
                            dss_path_idx = j
                        if current_line.startswith('Flow Hydrograph QMult='):
                            qmult_idx = j
                        if current_line.startswith('Flow Hydrograph='):
                            flow_hydro_idx = j
                        j += 1

                    if block_end_idx is None:
                        block_end_idx = len(lines)

                    # Update DSS A-part if requested
                    if new_a_part and dss_path_idx is not None:
                        dss_path = lines[dss_path_idx].replace('DSS Path=', '').strip()
                        clean_path = dss_path.strip('/')
                        parts = clean_path.split('/')
                        if len(parts) >= 1:
                            current_a_part = parts[0]
                            if old_a_part is None or current_a_part == old_a_part:
                                parts[0] = new_a_part
                                new_dss_path = '//' + '/'.join(parts) + '/'
                                lines[dss_path_idx] = f'DSS Path={new_dss_path}\n'
                                total_updates += 1
                                logger.debug(f"Updated A-part for station '{river_station}': '{current_a_part}' -> '{new_a_part}'")

                    # Update/insert QMult if requested
                    if new_multiplier is not None:
                        qmult_line = f'Flow Hydrograph QMult= {new_multiplier}\n'

                        if qmult_idx is not None:
                            lines[qmult_idx] = qmult_line
                            total_updates += 1
                            logger.debug(f"Updated QMult for station '{river_station}': {new_multiplier}")
                        elif flow_hydro_idx is not None:
                            # Find insertion point after hydrograph data
                            insert_idx = flow_hydro_idx + 1
                            while insert_idx < block_end_idx:
                                test_line = lines[insert_idx].strip()
                                if '=' in test_line and not test_line[0].isdigit():
                                    break
                                insert_idx += 1
                            lines.insert(insert_idx, qmult_line)
                            # Adjust indices for subsequent operations
                            block_end_idx += 1
                            total_updates += 1
                            logger.debug(f"Inserted QMult for station '{river_station}': {new_multiplier}")
                        else:
                            lines.insert(boundary_idx + 1, qmult_line)
                            total_updates += 1
                            logger.debug(f"Inserted QMult for station '{river_station}': {new_multiplier}")

                    break  # Found and processed this station
                i += 1

        if total_updates > 0:
            with open(unsteady_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Applied {total_updates} updates to {unsteady_path.name}")
        else:
            logger.warning("No matching boundaries found for any updates")

        return total_updates

    @staticmethod
    @log_call
    def preview_dss_references(
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Consolidated DataFrame of all DSS paths across all unsteady files in project.

        Scans every unsteady flow file registered in ras.unsteady_df and extracts
        all DSS-linked boundary conditions into a single DataFrame.

        Parameters
        ----------
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        pd.DataFrame
            DataFrame with all columns from get_dss_boundaries() plus:
            - unsteady_number: The unsteady file number (e.g., '01')
            - unsteady_file: Full path to the unsteady file

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> all_dss = RasUnsteady.preview_dss_references()
        >>> print(f"Total DSS references: {len(all_dss)}")
        >>> print(all_dss[['unsteady_number', 'dss_part_b', 'dss_path']].head())
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        all_boundaries = []

        for _, row in ras_obj.unsteady_df.iterrows():
            unsteady_path = Path(row['full_path'])
            if not unsteady_path.exists():
                logger.warning(f"Unsteady file not found: {unsteady_path}")
                continue

            try:
                df = RasUnsteady.get_dss_boundaries(unsteady_path, ras_object=ras_obj)
                if not df.empty:
                    df['unsteady_number'] = row['unsteady_number']
                    df['unsteady_file'] = str(unsteady_path)
                    all_boundaries.append(df)
            except Exception as e:
                logger.warning(f"Error reading DSS boundaries from {unsteady_path.name}: {e}")

        if not all_boundaries:
            logger.info("No DSS references found across any unsteady files")
            return pd.DataFrame()

        result = pd.concat(all_boundaries, ignore_index=True)
        logger.info(f"Found {len(result)} total DSS references across {len(all_boundaries)} unsteady files")
        return result

    @staticmethod
    @log_call
    def batch_update_dss_references(
        path_mapping: Union[Dict[str, str], pd.DataFrame],
        unsteady_filter: Optional[List[str]] = None,
        dry_run: bool = True,
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Batch update DSS path substrings across multiple unsteady flow files.

        Extends update_boundary_dss_paths() to operate across all unsteady flow files
        in the project. Uses ras.unsteady_df for file discovery.

        Parameters
        ----------
        path_mapping : dict or pd.DataFrame
            If dict: {old_substring: new_substring} pairs for replacement.
            If DataFrame: must have columns 'old_value' and 'new_value'.
        unsteady_filter : list of str, optional
            List of unsteady numbers to process (e.g., ['01', '03']).
            If None, processes all unsteady files.
        dry_run : bool, default True
            If True, reports what would change without modifying files.
            Set to False to apply changes.
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        pd.DataFrame
            Report with columns:
            - unsteady_number: File number
            - unsteady_file: File path
            - river: River name
            - reach: Reach name
            - station: River station
            - dss_path_before: Original DSS path
            - dss_path_after: New DSS path (or same if no match)
            - line_number: Line number in file
            - status: 'updated', 'unchanged', or 'error'

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Preview what exists
        >>> all_dss = RasUnsteady.preview_dss_references()
        >>> # Define replacements
        >>> mapping = {'RUN:1%_24HR': 'RUN:1%_48HR', 'OLD_PROJECT': 'NEW_PROJECT'}
        >>> # Dry run first
        >>> report = RasUnsteady.batch_update_dss_references(mapping, dry_run=True)
        >>> print(report[report['status'] == 'updated'])
        >>> # Apply changes
        >>> report = RasUnsteady.batch_update_dss_references(mapping, dry_run=False)

        Notes
        -----
        Always run with dry_run=True first to verify changes before applying.
        The method validates results by re-reading DSS boundaries after updates.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Normalize path_mapping to dict
        if isinstance(path_mapping, pd.DataFrame):
            if 'old_value' not in path_mapping.columns or 'new_value' not in path_mapping.columns:
                raise ValueError("DataFrame must have 'old_value' and 'new_value' columns")
            mapping = dict(zip(path_mapping['old_value'], path_mapping['new_value']))
        else:
            mapping = dict(path_mapping)

        if not mapping:
            logger.warning("Empty path_mapping provided")
            return pd.DataFrame()

        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        report_rows = []

        for _, row in ras_obj.unsteady_df.iterrows():
            unsteady_num = row['unsteady_number']

            # Apply filter if provided
            if unsteady_filter is not None and unsteady_num not in unsteady_filter:
                continue

            unsteady_path = Path(row['full_path'])
            if not unsteady_path.exists():
                logger.warning(f"Unsteady file not found: {unsteady_path}")
                continue

            # Get current DSS boundaries
            try:
                boundaries_before = RasUnsteady.get_dss_boundaries(unsteady_path, ras_object=ras_obj)
            except Exception as e:
                logger.warning(f"Error reading {unsteady_path.name}: {e}")
                continue

            if boundaries_before.empty:
                continue

            # Check each boundary for matching substrings
            updates_for_file = []
            for _, bc in boundaries_before.iterrows():
                original_path = bc.get('dss_path', '')
                new_path = original_path

                for old_sub, new_sub in mapping.items():
                    if old_sub in new_path:
                        new_path = new_path.replace(old_sub, new_sub)

                status = 'updated' if new_path != original_path else 'unchanged'

                report_rows.append({
                    'unsteady_number': unsteady_num,
                    'unsteady_file': str(unsteady_path),
                    'river': bc.get('river', ''),
                    'reach': bc.get('reach', ''),
                    'station': bc.get('station', ''),
                    'dss_path_before': original_path,
                    'dss_path_after': new_path,
                    'line_number': bc.get('line_number', ''),
                    'status': status,
                })

                if status == 'updated':
                    updates_for_file.append({
                        'river_station': bc.get('station', ''),
                        'new_dss_path': new_path,
                    })

            # Apply changes if not dry run
            if not dry_run and updates_for_file:
                try:
                    # Read file, apply substring replacements directly
                    with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    for old_sub, new_sub in mapping.items():
                        content = content.replace(old_sub, new_sub)

                    with open(unsteady_path, 'w', encoding='utf-8') as f:
                        f.write(content)

                    logger.info(f"Applied {len(updates_for_file)} updates to {unsteady_path.name}")

                    # Validate by re-reading
                    boundaries_after = RasUnsteady.get_dss_boundaries(unsteady_path, ras_object=ras_obj)
                    logger.info(
                        f"Validation: {unsteady_path.name} has "
                        f"{len(boundaries_after)} DSS boundaries after update"
                    )
                except Exception as e:
                    logger.error(f"Error applying updates to {unsteady_path.name}: {e}")
                    # Mark affected rows as error
                    for row_dict in report_rows:
                        if (row_dict['unsteady_file'] == str(unsteady_path) and
                                row_dict['status'] == 'updated'):
                            row_dict['status'] = 'error'

        report = pd.DataFrame(report_rows)

        if dry_run:
            n_updates = len(report[report['status'] == 'updated']) if not report.empty else 0
            logger.info(f"Dry run: {n_updates} DSS paths would be updated across {len(report)} boundaries")
        else:
            n_updates = len(report[report['status'] == 'updated']) if not report.empty else 0
            logger.info(f"Applied: {n_updates} DSS paths updated")

        return report

    @staticmethod
    @log_call
    def get_rating_curve(
        unsteady_file: Union[str, Path],
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Read a Rating Curve from a boundary condition in a HEC-RAS unsteady flow file.

        Parses the ``Rating Curve= <pair_count>`` header and the fixed-width
        (stage, discharge) pair table that follows it.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character unsteady
            number (e.g. ``"01"``) when a project-bound ``ras_object`` is
            available.
        river, reach, station : str, optional
            1D location selector.  When all three are ``None`` the first
            Rating Curve boundary in the file is returned.
        ras_object : optional
            Custom RAS object to use instead of the global one.

        Returns
        -------
        pd.DataFrame or None
            DataFrame with columns ``['stage', 'discharge']`` containing the
            rating curve pairs, or ``None`` if no Rating Curve boundary was
            found matching the selectors.

        Raises
        ------
        FileNotFoundError
            If the unsteady flow file does not exist.

        Examples
        --------
        >>> from ras_commander import RasUnsteady
        >>> rc = RasUnsteady.get_rating_curve(
        ...     "Manning'snCalibra.u01",
        ...     river="Mississippi", reach="Lower Miss.", station="846",
        ... )
        >>> rc.head()
           stage  discharge
        0  211.0        0.0
        1  225.8    80000.0
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        RATING_CURVE_HEADER = 'Rating Curve='

        target_idx = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                parts = [p.strip() for p in loc_value.split(',')]

                if river is not None or reach is not None or station is not None:
                    if not (
                        len(parts) >= 3
                        and (river is None or parts[0] == river)
                        and (reach is None or parts[1] == reach)
                        and (station is None or parts[2] == station)
                    ):
                        continue

                block_end = len(lines)
                rc_header_idx = None
                for j in range(i + 1, min(i + 500, len(lines))):
                    if lines[j].startswith('Boundary Location='):
                        block_end = j
                        break
                    if lines[j].startswith(RATING_CURVE_HEADER):
                        rc_header_idx = j
                        break

                if rc_header_idx is not None:
                    target_idx = rc_header_idx
                    break

        if target_idx is None:
            logger.debug("No Rating Curve boundary found matching selectors")
            return None

        header_line = lines[target_idx]
        try:
            pair_count = int(header_line.replace(RATING_CURVE_HEADER, '').strip())
        except ValueError:
            logger.warning(f"Could not parse pair count from: {header_line.strip()}")
            return None

        values = []
        line_idx = target_idx + 1
        while len(values) < pair_count * 2 and line_idx < len(lines):
            data_line = lines[line_idx]
            if '=' in data_line or data_line.startswith('Boundary Location='):
                break
            for k in range(0, len(data_line.rstrip('\r\n')), 8):
                field = data_line[k:k + 8].strip()
                if field:
                    try:
                        values.append(float(field))
                    except ValueError:
                        pass
            line_idx += 1

        stages = values[0::2]
        discharges = values[1::2]
        n = min(len(stages), len(discharges))

        df = pd.DataFrame({
            'stage': stages[:n],
            'discharge': discharges[:n],
        })
        logger.info(
            f"Read Rating Curve from {unsteady_path.name}: "
            f"{len(df)} pairs, stage range [{df['stage'].min():.1f}, {df['stage'].max():.1f}]"
        )
        return df

    @staticmethod
    @log_call
    def set_rating_curve(
        unsteady_file: Union[str, Path],
        rating_curve_df: pd.DataFrame,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Write or replace a Rating Curve table on a boundary condition.

        If the matched boundary already has a ``Rating Curve=`` header and
        inline data, the existing data is replaced.  If the boundary exists
        but has no rating curve data yet, a ``Rating Curve=`` header and data
        lines are inserted.

        Rating Curves are static stage-discharge relationships and have no
        ``Interval=`` line.  The data is stored as (stage, discharge) pairs in
        8-character fixed-width format, 10 values per line (5 pairs).

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character unsteady
            number (e.g. ``"01"``) when a project-bound ``ras_object`` is
            available.
        rating_curve_df : pd.DataFrame
            DataFrame with columns ``['stage', 'discharge']``.  Must have at
            least 2 rows and be sorted by ascending stage.
        river, reach, station : str, optional
            1D location selector.  When all three are ``None`` the first
            Rating Curve boundary in the file is updated.
        ras_object : optional
            Custom RAS object to use instead of the global one.

        Returns
        -------
        Dict[str, Any]
            Reviewable metadata with keys:

            - ``unsteady_file`` (str): absolute path written
            - ``matched_location`` (str): matched ``Boundary Location=`` value
            - ``pair_count`` (int): number of (stage, discharge) pairs written
            - ``stage_range`` (list): ``[min_stage, max_stage]``
            - ``discharge_range`` (list): ``[min_discharge, max_discharge]``
            - ``previous_pair_count`` (int or None): prior pair count, or
              ``None`` if no Rating Curve data existed
            - ``boundaries_df_refreshed`` (bool): True when ``ras_object``
              ``boundaries_df`` was refreshed after the write

        Raises
        ------
        ValueError
            If DataFrame is missing required columns, has fewer than 2 rows,
            or no matching boundary is found.
        FileNotFoundError
            If the unsteady flow file does not exist.

        Examples
        --------
        >>> import pandas as pd
        >>> from ras_commander import RasUnsteady
        >>> rc = pd.DataFrame({
        ...     'stage': [210, 220, 230, 240, 250],
        ...     'discharge': [0, 50000, 200000, 500000, 1000000],
        ... })
        >>> result = RasUnsteady.set_rating_curve(
        ...     "Manning'snCalibra.u01", rc,
        ...     river="Mississippi", reach="Lower Miss.", station="846",
        ... )
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        required_columns = ['stage', 'discharge']
        missing = [c for c in required_columns if c not in rating_curve_df.columns]
        if missing:
            raise ValueError(
                f"DataFrame missing required columns: {missing}. "
                f"Required: {required_columns}"
            )
        if len(rating_curve_df) < 2:
            raise ValueError("Rating curve DataFrame must have at least 2 rows")

        stages = rating_curve_df['stage'].values
        discharges = rating_curve_df['discharge'].values
        pair_count = len(stages)

        interleaved = []
        for s, q in zip(stages, discharges):
            interleaved.append(float(s))
            interleaved.append(float(q))

        formatted_lines = []
        for k in range(0, len(interleaved), 10):
            row_vals = interleaved[k:k + 10]
            formatted_row = ''
            for v in row_vals:
                if abs(v) < 1e7:
                    formatted_row += f'{v:8.1f}' if v != int(v) or abs(v) > 99999 else f'{int(v):>8}'
                else:
                    formatted_row += f'{v:8.0f}'
            formatted_lines.append(formatted_row + '\n')

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        RATING_CURVE_HEADER = 'Rating Curve='

        boundary_idx = None
        matched_loc = None
        rc_header_idx = None
        block_end = None

        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                parts = [p.strip() for p in loc_value.split(',')]

                if river is not None or reach is not None or station is not None:
                    if not (
                        len(parts) >= 3
                        and (river is None or parts[0] == river)
                        and (reach is None or parts[1] == reach)
                        and (station is None or parts[2] == station)
                    ):
                        continue

                blk_end = len(lines)
                found_rc = None
                for j in range(i + 1, min(i + 500, len(lines))):
                    if lines[j].startswith('Boundary Location='):
                        blk_end = j
                        break
                    if lines[j].startswith(RATING_CURVE_HEADER):
                        found_rc = j

                if found_rc is not None:
                    boundary_idx = i
                    matched_loc = loc_value
                    rc_header_idx = found_rc
                    block_end = blk_end
                    break

        if boundary_idx is None:
            sel = f"river={river!r}/reach={reach!r}/station={station!r}" if river else "first matching"
            raise ValueError(
                f"No Rating Curve boundary found in {unsteady_path.name} for {sel}"
            )

        previous_pair_count = None
        try:
            previous_pair_count = int(
                lines[rc_header_idx].replace(RATING_CURVE_HEADER, '').strip()
            )
        except ValueError:
            pass

        old_data_start = rc_header_idx + 1
        old_data_end = old_data_start
        for k in range(old_data_start, block_end):
            if '=' in lines[k] or lines[k].startswith('Boundary Location='):
                old_data_end = k
                break
        else:
            old_data_end = block_end

        if old_data_end > old_data_start:
            del lines[old_data_start:old_data_end]

        lines[rc_header_idx] = f'{RATING_CURVE_HEADER} {pair_count} \n'

        insert_pos = rc_header_idx + 1
        for idx, data_line in enumerate(formatted_lines):
            lines.insert(insert_pos + idx, data_line)

        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        logger.info(
            "Set Rating Curve in %s: matched=%s, pairs=%d, "
            "stage=[%.1f, %.1f], discharge=[%.0f, %.0f]",
            unsteady_path.name,
            matched_loc.strip() if matched_loc else "?",
            pair_count,
            float(stages[0]), float(stages[-1]),
            float(discharges[0]), float(discharges[-1]),
        )

        return {
            'unsteady_file': str(unsteady_path),
            'matched_location': matched_loc,
            'pair_count': pair_count,
            'stage_range': [float(stages[0]), float(stages[-1])],
            'discharge_range': [float(discharges[0]), float(discharges[-1])],
            'previous_pair_count': previous_pair_count,
            'boundaries_df_refreshed': boundaries_df_refreshed,
        }

    @staticmethod
    @log_call
    def get_stage_flow_hydrograph(
        unsteady_file: Union[str, Path],
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Read observed stage/flow pairs from an internal boundary condition.

        Parses the ``Observed Stage and Flow Hydrograph=`` block from a ``.u##``
        file.  The block stores interleaved (stage, flow) pairs in 8-character
        fixed-width fields, 10 values per line (5 pairs per line).

        Parameters
        ----------
        unsteady_file : str or Path
            Path to unsteady flow file or unsteady number (e.g. ``"01"``).
        river : str, optional
            River name for location matching.
        reach : str, optional
            Reach name for location matching.
        station : str, optional
            River station for location matching.
        ras_object : optional
            RasPrj instance; falls back to the global ``ras`` object.

        Returns
        -------
        pd.DataFrame or None
            DataFrame with columns ``['stage', 'flow']``, one row per time
            step.  Returns ``None`` if the boundary or data block is not found.

        See Also
        --------
        set_stage_flow_hydrograph : Write stage/flow pairs back to a ``.u##`` file.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError("Cannot resolve unsteady number without an initialized ras_object")
            unsteady_num = unsteady_file.zfill(2)
            unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{unsteady_num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        KEYWORD = 'Observed Stage and Flow Hydrograph='

        target_idx = None
        for idx, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                if river is not None or reach is not None or station is not None:
                    loc_line = line.replace('Boundary Location=', '')
                    parts = [p.strip() for p in loc_line.split(',')]
                    match = True
                    if river is not None and (len(parts) < 1 or parts[0] != river):
                        match = False
                    if reach is not None and (len(parts) < 2 or parts[1] != reach):
                        match = False
                    if station is not None and (len(parts) < 3 or parts[2] != station):
                        match = False
                    if match:
                        target_idx = idx
                else:
                    for j in range(idx + 1, min(idx + 50, len(lines))):
                        if lines[j].startswith('Boundary Location='):
                            break
                        if lines[j].startswith(KEYWORD):
                            target_idx = idx
                            break
                if target_idx is not None:
                    break

        if target_idx is None:
            logger.warning("No matching boundary found for Observed Stage and Flow Hydrograph")
            return None

        header_idx = None
        for j in range(target_idx + 1, min(target_idx + 50, len(lines))):
            if lines[j].startswith('Boundary Location='):
                break
            if lines[j].startswith(KEYWORD):
                header_idx = j
                break

        if header_idx is None:
            logger.warning("Observed Stage and Flow Hydrograph header not found in boundary block")
            return None

        try:
            pair_count = int(lines[header_idx].replace(KEYWORD, '').strip())
        except ValueError:
            logger.warning("Could not parse pair count from header")
            return None

        total_values = pair_count * 2
        all_values: List[float] = []
        data_idx = header_idx + 1
        while len(all_values) < total_values and data_idx < len(lines):
            data_line = lines[data_idx]
            if '=' in data_line or data_line.startswith('Boundary Location='):
                break
            for k in range(0, len(data_line.rstrip('\n')), 8):
                field = data_line[k:k+8]
                stripped = field.strip()
                if stripped:
                    try:
                        all_values.append(float(stripped))
                    except ValueError:
                        break
                else:
                    all_values.append(0.0)
            data_idx += 1

        if len(all_values) < 2:
            logger.warning(f"Insufficient data: found {len(all_values)} values, expected {total_values}")
            return None

        stages = [all_values[i] for i in range(0, len(all_values), 2)]
        flows = [all_values[i] for i in range(1, len(all_values), 2)]
        min_len = min(len(stages), len(flows))

        return pd.DataFrame({'stage': stages[:min_len], 'flow': flows[:min_len]})

    @staticmethod
    def _fmt8(v: float) -> str:
        """Format a value into an 8-character fixed-width field matching HEC-RAS style."""
        if v == 0.0:
            return ' ' * 8
        if v == int(v) and abs(v) < 1e8:
            return f'{int(v):>8}'
        for decimals in range(6, 0, -1):
            s = f'{v:.{decimals}f}'.rstrip('0').rstrip('.')
            if len(s) <= 8:
                return s.rjust(8)
        s = f'{v:.0f}'
        return s[:8].rjust(8)

    @staticmethod
    @log_call
    def set_stage_flow_hydrograph(
        unsteady_file: Union[str, Path],
        stage_flow_df: pd.DataFrame,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> dict:
        """
        Write observed stage/flow pairs to an internal boundary condition.

        Creates or replaces the ``Observed Stage and Flow Hydrograph=`` block
        in a ``.u##`` file.  Data is written as interleaved (stage, flow) pairs
        in 8-character fixed-width format, 10 values per line (5 pairs per line).

        Parameters
        ----------
        unsteady_file : str or Path
            Path to unsteady flow file or unsteady number (e.g. ``"01"``).
        stage_flow_df : pd.DataFrame
            DataFrame with columns ``['stage', 'flow']``.
        river : str, optional
            River name for location matching.
        reach : str, optional
            Reach name for location matching.
        station : str, optional
            River station for location matching.
        ras_object : optional
            RasPrj instance; falls back to the global ``ras`` object.

        Returns
        -------
        dict
            - ``pair_count`` (int): Number of stage/flow pairs written.
            - ``matched_location`` (str): Raw ``Boundary Location=`` value matched.
            - ``unsteady_file`` (str): Path to the written file.
            - ``boundaries_df_refreshed`` (bool): True when ``ras_object``
              boundaries were refreshed after writing.

        Raises
        ------
        ValueError
            If DataFrame is missing required columns or is empty.
        FileNotFoundError
            If unsteady flow file not found.

        See Also
        --------
        get_stage_flow_hydrograph : Read stage/flow pairs from a ``.u##`` file.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError("Cannot resolve unsteady number without an initialized ras_object")
            unsteady_num = unsteady_file.zfill(2)
            unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{unsteady_num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        for col in ('stage', 'flow'):
            if col not in stage_flow_df.columns:
                raise ValueError(f"DataFrame missing required column: '{col}'")
        if len(stage_flow_df) == 0:
            raise ValueError("DataFrame is empty")

        pair_count = len(stage_flow_df)
        stages = stage_flow_df['stage'].values
        flows = stage_flow_df['flow'].values

        interleaved: List[float] = []
        for s, q in zip(stages, flows):
            interleaved.append(float(s))
            interleaved.append(float(q))

        formatted_lines: List[str] = []
        for i in range(0, len(interleaved), 10):
            row_vals = interleaved[i:i+10]
            formatted_lines.append(''.join(RasUnsteady._fmt8(v) for v in row_vals) + '\n')

        KEYWORD = 'Observed Stage and Flow Hydrograph='

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        target_idx = None
        for idx, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                if river is not None or reach is not None or station is not None:
                    loc_line = line.replace('Boundary Location=', '')
                    parts = [p.strip() for p in loc_line.split(',')]
                    match = True
                    if river is not None and (len(parts) < 1 or parts[0] != river):
                        match = False
                    if reach is not None and (len(parts) < 2 or parts[1] != reach):
                        match = False
                    if station is not None and (len(parts) < 3 or parts[2] != station):
                        match = False
                    if match:
                        target_idx = idx
                else:
                    for j in range(idx + 1, min(idx + 50, len(lines))):
                        if lines[j].startswith('Boundary Location='):
                            break
                        if lines[j].startswith(KEYWORD):
                            target_idx = idx
                            break
                if target_idx is not None:
                    break

        if target_idx is None:
            loc_str = f"{river}/{reach}/{station}" if river else "first matching"
            raise ValueError(
                f"No boundary matched in {unsteady_path.name} for {loc_str}. "
                f"Boundary must already exist as a `Boundary Location=` block."
            )

        header_idx = None
        old_data_start = None
        old_data_end = None
        block_end = len(lines)

        for j in range(target_idx + 1, min(target_idx + 500, len(lines))):
            if lines[j].startswith('Boundary Location='):
                block_end = j
                break
            if lines[j].startswith(KEYWORD):
                header_idx = j
                try:
                    old_count = int(lines[j].replace(KEYWORD, '').strip())
                except ValueError:
                    old_count = 0
                if old_count > 0:
                    old_data_start = j + 1
                    for k in range(old_data_start, block_end):
                        if '=' in lines[k] or lines[k].startswith('Boundary Location='):
                            old_data_end = k
                            break
                    else:
                        old_data_end = block_end
                break

        if header_idx is not None:
            lines[header_idx] = f'{KEYWORD} {pair_count} \n'
            if old_data_start is not None and old_data_end is not None:
                lines[old_data_start:old_data_end] = formatted_lines
            else:
                for i, fl in enumerate(formatted_lines):
                    lines.insert(header_idx + 1 + i, fl)
        else:
            insert_pos = block_end
            new_block = [f'{KEYWORD} {pair_count} \n'] + formatted_lines
            for i, bl in enumerate(new_block):
                lines.insert(insert_pos + i, bl)

        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        matched_location = lines[target_idx].replace('Boundary Location=', '').rstrip('\r\n')

        loc_parts = []
        if river:
            loc_parts.append(river)
        if reach:
            loc_parts.append(reach)
        if station:
            loc_parts.append(station)

        logger.info(
            f"Wrote {pair_count} stage/flow pairs to "
            f"{'/'.join(loc_parts) if loc_parts else 'first matching BC'} "
            f"in {unsteady_path.name}"
        )

        return {
            'pair_count': pair_count,
            'matched_location': matched_location,
            'unsteady_file': str(unsteady_path),
            'boundaries_df_refreshed': boundaries_df_refreshed,
        }

    # ------------------------------------------------------------------
    # Lateral Inflow Hydrograph Methods
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def get_lateral_inflow_hydrograph(
        unsteady_file: Union[str, Path],
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Read a Lateral Inflow Hydrograph from a boundary condition.

        Parses the ``Lateral Inflow Hydrograph= <count>`` header and the
        fixed-width flow values that follow it.  Also reads the optional
        ``Flow Hydrograph Slope=`` and ``Interval=`` fields from the same
        boundary block and attaches them as DataFrame ``attrs``.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character
            unsteady number (e.g. ``"01"``).
        river, reach, station : str, optional
            1D location selector.  When all three are ``None`` the first
            Lateral Inflow Hydrograph boundary in the file is returned.
            For 2D/SA boundaries the river/reach/station fields are empty;
            pass ``None`` to match the first lateral inflow found.
        ras_object : optional
            Custom RAS object to use instead of the global one.

        Returns
        -------
        pd.DataFrame or None
            DataFrame with columns ``['flow']`` and integer index
            representing ordinal time steps, or ``None`` if no matching
            boundary was found.

            DataFrame ``attrs`` include:

            - ``interval`` (str): e.g. ``"1HOUR"``
            - ``slope`` (float or None): ``Flow Hydrograph Slope`` value
            - ``matched_location`` (str): raw ``Boundary Location=`` value
            - ``value_count`` (int): number of flow values

        Raises
        ------
        FileNotFoundError
            If the unsteady flow file does not exist.

        Examples
        --------
        >>> from ras_commander import RasUnsteady
        >>> df = RasUnsteady.get_lateral_inflow_hydrograph(
        ...     "BaldEagleDamBrk.u01",
        ... )
        >>> print(f"Values: {len(df)}, peak: {df['flow'].max():.0f}")
        Values: 141, peak: 100000
        >>> print(f"Slope: {df.attrs['slope']}")
        Slope: 0.005
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        HEADER = 'Lateral Inflow Hydrograph='
        SLOPE_KEY = 'Flow Hydrograph Slope='

        target_idx = None
        matched_loc = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                parts = [p.strip() for p in loc_value.split(',')]

                if river is not None or reach is not None or station is not None:
                    if not (
                        len(parts) >= 3
                        and (river is None or parts[0] == river)
                        and (reach is None or parts[1] == reach)
                        and (station is None or parts[2] == station)
                    ):
                        continue

                block_end = len(lines)
                lat_header_idx = None
                for j in range(i + 1, min(i + 500, len(lines))):
                    if lines[j].startswith('Boundary Location='):
                        block_end = j
                        break
                    if lines[j].startswith(HEADER):
                        lat_header_idx = j

                if lat_header_idx is not None:
                    target_idx = lat_header_idx
                    matched_loc = loc_value
                    break

        if target_idx is None:
            logger.debug("No Lateral Inflow Hydrograph boundary found matching selectors")
            return None

        try:
            value_count = int(lines[target_idx].replace(HEADER, '').strip())
        except ValueError:
            logger.warning(f"Could not parse value count from: {lines[target_idx].strip()}")
            return None

        if value_count == 0:
            logger.debug("Lateral Inflow Hydrograph has count=0 (DSS-linked, no inline data)")
            return None

        # Find block_end for this boundary
        block_end = len(lines)
        for j in range(target_idx + 1, len(lines)):
            if lines[j].startswith('Boundary Location='):
                block_end = j
                break

        values = []
        line_idx = target_idx + 1
        while len(values) < value_count and line_idx < block_end:
            data_line = lines[line_idx]
            if '=' in data_line:
                break
            for k in range(0, len(data_line.rstrip('\r\n')), 8):
                field = data_line[k:k + 8].strip()
                if field:
                    try:
                        values.append(float(field))
                    except ValueError:
                        pass
            line_idx += 1

        # Read Interval and Slope from the block
        interval = None
        slope = None
        # Search from boundary location line to block end
        bc_start = target_idx
        for j in range(target_idx - 1, -1, -1):
            if lines[j].startswith('Boundary Location='):
                bc_start = j
                break
        for j in range(bc_start, block_end):
            stripped = lines[j].strip()
            if stripped.startswith('Interval='):
                interval = stripped.replace('Interval=', '').strip()
            if stripped.startswith(SLOPE_KEY):
                try:
                    slope = float(stripped.replace(SLOPE_KEY, '').strip())
                except ValueError:
                    pass

        df = pd.DataFrame({'flow': values[:value_count]})
        df.attrs['interval'] = interval
        df.attrs['slope'] = slope
        df.attrs['matched_location'] = matched_loc.strip() if matched_loc else None
        df.attrs['value_count'] = len(df)

        logger.info(
            f"Read Lateral Inflow Hydrograph from {unsteady_path.name}: "
            f"{len(df)} values, peak={df['flow'].max():.1f}, "
            f"interval={interval}, slope={slope}"
        )
        return df

    @staticmethod
    @log_call
    def set_lateral_inflow_hydrograph(
        unsteady_file: Union[str, Path],
        hydrograph_df: pd.DataFrame,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        slope: Optional[float] = None,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Write or replace a Lateral Inflow Hydrograph on a boundary condition.

        If the matched boundary already has a ``Lateral Inflow Hydrograph=``
        header and inline data, the existing data is replaced.  Optionally
        updates ``Flow Hydrograph Slope=`` in the same call.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character
            unsteady number (e.g. ``"01"``).
        hydrograph_df : pd.DataFrame
            DataFrame with a ``'flow'`` column containing lateral inflow
            values.  Must have at least 1 row.
        river, reach, station : str, optional
            1D location selector.  When all three are ``None`` the first
            Lateral Inflow Hydrograph boundary in the file is updated.
        slope : float, optional
            If provided, sets ``Flow Hydrograph Slope=`` for this boundary.
            Existing slope is updated or a new line is inserted.
        ras_object : optional
            Custom RAS object to use instead of the global one.

        Returns
        -------
        Dict[str, Any]
            Metadata with keys:

            - ``unsteady_file`` (str): absolute path written
            - ``matched_location`` (str): matched ``Boundary Location=`` value
            - ``value_count`` (int): number of flow values written
            - ``flow_range`` (list): ``[min_flow, max_flow]``
            - ``previous_value_count`` (int or None): prior count
            - ``slope_written`` (float or None): slope value written
            - ``boundaries_df_refreshed`` (bool): True when refreshed

        Raises
        ------
        ValueError
            If DataFrame is missing ``'flow'`` column, is empty, or no
            matching boundary is found.
        FileNotFoundError
            If the unsteady flow file does not exist.

        Examples
        --------
        >>> import pandas as pd
        >>> from ras_commander import RasUnsteady
        >>> flows = [1000 + i * 500 for i in range(25)]
        >>> df = pd.DataFrame({'flow': flows})
        >>> result = RasUnsteady.set_lateral_inflow_hydrograph(
        ...     "BaldEagleDamBrk.u01", df, slope=0.003,
        ... )
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        if 'flow' not in hydrograph_df.columns:
            raise ValueError(
                "DataFrame missing required column: 'flow'. "
                "Provide a DataFrame with a 'flow' column."
            )
        if len(hydrograph_df) == 0:
            raise ValueError("DataFrame is empty")

        flow_values = hydrograph_df['flow'].values
        value_count = len(flow_values)

        formatted_lines = []
        for k in range(0, value_count, 10):
            row_vals = flow_values[k:k + 10]
            row_str = ''
            for v in row_vals:
                fv = float(v)
                if abs(fv) < 1e7:
                    row_str += f'{fv:8.1f}' if fv != int(fv) or abs(fv) > 99999 else f'{int(fv):>8}'
                else:
                    row_str += f'{fv:8.0f}'
            formatted_lines.append(row_str + '\n')

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        HEADER = 'Lateral Inflow Hydrograph='
        SLOPE_KEY = 'Flow Hydrograph Slope='

        boundary_idx = None
        matched_loc = None
        lat_header_idx = None
        block_end = None

        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                parts = [p.strip() for p in loc_value.split(',')]

                if river is not None or reach is not None or station is not None:
                    if not (
                        len(parts) >= 3
                        and (river is None or parts[0] == river)
                        and (reach is None or parts[1] == reach)
                        and (station is None or parts[2] == station)
                    ):
                        continue

                blk_end = len(lines)
                found_lat = None
                for j in range(i + 1, min(i + 500, len(lines))):
                    if lines[j].startswith('Boundary Location='):
                        blk_end = j
                        break
                    if lines[j].startswith(HEADER):
                        found_lat = j

                if found_lat is not None:
                    boundary_idx = i
                    matched_loc = loc_value
                    lat_header_idx = found_lat
                    block_end = blk_end
                    break

        if boundary_idx is None:
            sel = f"river={river!r}/reach={reach!r}/station={station!r}" if river else "first matching"
            raise ValueError(
                f"No Lateral Inflow Hydrograph boundary found in "
                f"{unsteady_path.name} for {sel}"
            )

        previous_value_count = None
        try:
            previous_value_count = int(
                lines[lat_header_idx].replace(HEADER, '').strip()
            )
        except ValueError:
            pass

        old_data_start = lat_header_idx + 1
        old_data_end = old_data_start
        for k in range(old_data_start, block_end):
            if '=' in lines[k] or lines[k].startswith('Boundary Location='):
                old_data_end = k
                break
        else:
            old_data_end = block_end

        if old_data_end > old_data_start:
            del lines[old_data_start:old_data_end]

        lines[lat_header_idx] = f'{HEADER} {value_count} \n'

        insert_pos = lat_header_idx + 1
        for idx, data_line in enumerate(formatted_lines):
            lines.insert(insert_pos + idx, data_line)

        # Handle slope: update or insert
        slope_written = None
        if slope is not None:
            # Recalculate block_end after data insertion
            new_block_end = len(lines)
            for j in range(boundary_idx + 1, len(lines)):
                if lines[j].startswith('Boundary Location='):
                    new_block_end = j
                    break

            existing_slope_idx = None
            for j in range(boundary_idx, new_block_end):
                if lines[j].startswith(SLOPE_KEY):
                    existing_slope_idx = j
                    break

            slope_line = f'{SLOPE_KEY} {slope} \n'
            if existing_slope_idx is not None:
                lines[existing_slope_idx] = slope_line
            else:
                # Insert after the last data line
                insert_after = lat_header_idx + 1 + len(formatted_lines)
                lines.insert(insert_after, slope_line)
            slope_written = slope

        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        logger.info(
            "Set Lateral Inflow Hydrograph in %s: matched=%s, values=%d, "
            "flow=[%.1f, %.1f], slope=%s",
            unsteady_path.name,
            matched_loc.strip() if matched_loc else "?",
            value_count,
            float(flow_values.min()), float(flow_values.max()),
            slope_written,
        )

        return {
            'unsteady_file': str(unsteady_path),
            'matched_location': matched_loc,
            'value_count': value_count,
            'flow_range': [float(flow_values.min()), float(flow_values.max())],
            'previous_value_count': previous_value_count,
            'slope_written': slope_written,
            'boundaries_df_refreshed': boundaries_df_refreshed,
        }

    # ------------------------------------------------------------------
    # Uniform Lateral Inflow Hydrograph Methods
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def get_uniform_lateral_inflow_hydrograph(
        unsteady_file: Union[str, Path],
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Read a Uniform Lateral Inflow Hydrograph from a boundary condition.

        Parses the ``Uniform Lateral Inflow Hydrograph= <count>`` header and
        the fixed-width flow values that follow it.  Also reads the optional
        ``Flow Hydrograph Slope=`` and ``Interval=`` fields from the same
        boundary block and attaches them as DataFrame ``attrs``.

        Uniform lateral inflow is a **reach-based** BC type: the inflow is
        applied uniformly across a reach segment (between two river stations),
        unlike a point Lateral Inflow Hydrograph.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character
            unsteady number (e.g. ``"01"``).
        river, reach, station : str, optional
            1D location selector.  When all three are ``None`` the first
            Uniform Lateral Inflow Hydrograph boundary in the file is
            returned.
        ras_object : optional
            Custom RAS object to use instead of the global one.

        Returns
        -------
        pd.DataFrame or None
            DataFrame with columns ``['flow']`` and integer index
            representing ordinal time steps, or ``None`` if no matching
            boundary was found or count is 0 (DSS-linked).

            DataFrame ``attrs`` include:

            - ``interval`` (str): e.g. ``"1HOUR"``
            - ``slope`` (float or None): ``Flow Hydrograph Slope`` value
            - ``matched_location`` (str): raw ``Boundary Location=`` value
            - ``value_count`` (int): number of flow values

        Raises
        ------
        FileNotFoundError
            If the unsteady flow file does not exist.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        HEADER = 'Uniform Lateral Inflow Hydrograph='
        SLOPE_KEY = 'Flow Hydrograph Slope='

        target_idx = None
        matched_loc = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                parts = [p.strip() for p in loc_value.split(',')]

                if river is not None or reach is not None or station is not None:
                    if not (
                        len(parts) >= 3
                        and (river is None or parts[0] == river)
                        and (reach is None or parts[1] == reach)
                        and (station is None or parts[2] == station)
                    ):
                        continue

                block_end = len(lines)
                uni_header_idx = None
                for j in range(i + 1, min(i + 500, len(lines))):
                    if lines[j].startswith('Boundary Location='):
                        block_end = j
                        break
                    if lines[j].startswith(HEADER):
                        uni_header_idx = j

                if uni_header_idx is not None:
                    target_idx = uni_header_idx
                    matched_loc = loc_value
                    break

        if target_idx is None:
            logger.debug("No Uniform Lateral Inflow Hydrograph boundary found matching selectors")
            return None

        try:
            value_count = int(lines[target_idx].replace(HEADER, '').strip())
        except ValueError:
            logger.warning(f"Could not parse value count from: {lines[target_idx].strip()}")
            return None

        if value_count == 0:
            logger.debug("Uniform Lateral Inflow Hydrograph has count=0 (DSS-linked, no inline data)")
            return None

        block_end = len(lines)
        for j in range(target_idx + 1, len(lines)):
            if lines[j].startswith('Boundary Location='):
                block_end = j
                break

        values = []
        line_idx = target_idx + 1
        while len(values) < value_count and line_idx < block_end:
            data_line = lines[line_idx]
            if '=' in data_line:
                break
            for k in range(0, len(data_line.rstrip('\r\n')), 8):
                field = data_line[k:k + 8].strip()
                if field:
                    try:
                        values.append(float(field))
                    except ValueError:
                        pass
            line_idx += 1

        interval = None
        slope = None
        bc_start = target_idx
        for j in range(target_idx - 1, -1, -1):
            if lines[j].startswith('Boundary Location='):
                bc_start = j
                break
        for j in range(bc_start, block_end):
            stripped = lines[j].strip()
            if stripped.startswith('Interval='):
                interval = stripped.replace('Interval=', '').strip()
            if stripped.startswith(SLOPE_KEY):
                try:
                    slope = float(stripped.replace(SLOPE_KEY, '').strip())
                except ValueError:
                    pass

        df = pd.DataFrame({'flow': values[:value_count]})
        df.attrs['interval'] = interval
        df.attrs['slope'] = slope
        df.attrs['matched_location'] = matched_loc.strip() if matched_loc else None
        df.attrs['value_count'] = len(df)

        logger.info(
            f"Read Uniform Lateral Inflow Hydrograph from {unsteady_path.name}: "
            f"{len(df)} values, peak={df['flow'].max():.1f}, "
            f"interval={interval}, slope={slope}"
        )
        return df

    @staticmethod
    @log_call
    def set_uniform_lateral_inflow_hydrograph(
        unsteady_file: Union[str, Path],
        hydrograph_df: pd.DataFrame,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        slope: Optional[float] = None,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Write or replace a Uniform Lateral Inflow Hydrograph on a boundary.

        If the matched boundary already has a
        ``Uniform Lateral Inflow Hydrograph=`` header and inline data, the
        existing data is replaced.  Optionally updates
        ``Flow Hydrograph Slope=`` in the same call.

        Uniform lateral inflow is a **reach-based** BC type: the inflow is
        applied uniformly across a reach segment (between two river stations).

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##), or a 1-2 character
            unsteady number (e.g. ``"01"``).
        hydrograph_df : pd.DataFrame
            DataFrame with a ``'flow'`` column containing uniform lateral
            inflow values.  Must have at least 1 row.
        river, reach, station : str, optional
            1D location selector.  When all three are ``None`` the first
            Uniform Lateral Inflow Hydrograph boundary in the file is
            updated.
        slope : float, optional
            If provided, sets ``Flow Hydrograph Slope=`` for this boundary.
        ras_object : optional
            Custom RAS object to use instead of the global one.

        Returns
        -------
        Dict[str, Any]
            Metadata with keys:

            - ``unsteady_file`` (str): absolute path written
            - ``matched_location`` (str): matched ``Boundary Location=`` value
            - ``value_count`` (int): number of flow values written
            - ``flow_range`` (list): ``[min_flow, max_flow]``
            - ``previous_value_count`` (int or None): prior count
            - ``slope_written`` (float or None): slope value written
            - ``boundaries_df_refreshed`` (bool): True when refreshed

        Raises
        ------
        ValueError
            If DataFrame is missing ``'flow'`` column, is empty, or no
            matching boundary is found.
        FileNotFoundError
            If the unsteady flow file does not exist.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except Exception:
                pass

        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            if ras_obj is None or getattr(ras_obj, 'project_folder', None) is None:
                raise ValueError(
                    "Cannot resolve unsteady number without an initialized ras_object"
                )
            num = unsteady_file.zfill(2)
            unsteady_path = Path(ras_obj.project_folder) / f"{ras_obj.project_name}.u{num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        if 'flow' not in hydrograph_df.columns:
            raise ValueError(
                "DataFrame missing required column: 'flow'. "
                "Provide a DataFrame with a 'flow' column."
            )
        if len(hydrograph_df) == 0:
            raise ValueError("DataFrame is empty")

        flow_values = hydrograph_df['flow'].values
        value_count = len(flow_values)

        formatted_lines = []
        for k in range(0, value_count, 10):
            row_vals = flow_values[k:k + 10]
            row_str = ''
            for v in row_vals:
                fv = float(v)
                if abs(fv) < 1e7:
                    row_str += f'{fv:8.1f}' if fv != int(fv) or abs(fv) > 99999 else f'{int(fv):>8}'
                else:
                    row_str += f'{fv:8.0f}'
            formatted_lines.append(row_str + '\n')

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        HEADER = 'Uniform Lateral Inflow Hydrograph='
        SLOPE_KEY = 'Flow Hydrograph Slope='

        boundary_idx = None
        matched_loc = None
        uni_header_idx = None
        block_end = None

        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_value = line[len('Boundary Location='):].rstrip('\r\n')
                parts = [p.strip() for p in loc_value.split(',')]

                if river is not None or reach is not None or station is not None:
                    if not (
                        len(parts) >= 3
                        and (river is None or parts[0] == river)
                        and (reach is None or parts[1] == reach)
                        and (station is None or parts[2] == station)
                    ):
                        continue

                blk_end = len(lines)
                found_uni = None
                for j in range(i + 1, min(i + 500, len(lines))):
                    if lines[j].startswith('Boundary Location='):
                        blk_end = j
                        break
                    if lines[j].startswith(HEADER):
                        found_uni = j

                if found_uni is not None:
                    boundary_idx = i
                    matched_loc = loc_value
                    uni_header_idx = found_uni
                    block_end = blk_end
                    break

        if boundary_idx is None:
            sel = f"river={river!r}/reach={reach!r}/station={station!r}" if river else "first matching"
            raise ValueError(
                f"No Uniform Lateral Inflow Hydrograph boundary found in "
                f"{unsteady_path.name} for {sel}"
            )

        previous_value_count = None
        try:
            previous_value_count = int(
                lines[uni_header_idx].replace(HEADER, '').strip()
            )
        except ValueError:
            pass

        old_data_start = uni_header_idx + 1
        old_data_end = old_data_start
        for k in range(old_data_start, block_end):
            if '=' in lines[k] or lines[k].startswith('Boundary Location='):
                old_data_end = k
                break
        else:
            old_data_end = block_end

        if old_data_end > old_data_start:
            del lines[old_data_start:old_data_end]

        lines[uni_header_idx] = f'{HEADER} {value_count} \n'

        insert_pos = uni_header_idx + 1
        for idx, data_line in enumerate(formatted_lines):
            lines.insert(insert_pos + idx, data_line)

        slope_written = None
        if slope is not None:
            new_block_end = len(lines)
            for j in range(boundary_idx + 1, len(lines)):
                if lines[j].startswith('Boundary Location='):
                    new_block_end = j
                    break

            existing_slope_idx = None
            for j in range(boundary_idx, new_block_end):
                if lines[j].startswith(SLOPE_KEY):
                    existing_slope_idx = j
                    break

            slope_line = f'{SLOPE_KEY} {slope} \n'
            if existing_slope_idx is not None:
                lines[existing_slope_idx] = slope_line
            else:
                insert_after = uni_header_idx + 1 + len(formatted_lines)
                lines.insert(insert_after, slope_line)
            slope_written = slope

        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        boundaries_df_refreshed = False
        if ras_obj is not None:
            try:
                ras_obj.boundaries_df = ras_obj.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:
                logger.debug(f"boundaries_df refresh skipped: {exc}")

        logger.info(
            "Set Uniform Lateral Inflow Hydrograph in %s: matched=%s, values=%d, "
            "flow=[%.1f, %.1f], slope=%s",
            unsteady_path.name,
            matched_loc.strip() if matched_loc else "?",
            value_count,
            float(flow_values.min()), float(flow_values.max()),
            slope_written,
        )

        return {
            'unsteady_file': str(unsteady_path),
            'matched_location': matched_loc,
            'value_count': value_count,
            'flow_range': [float(flow_values.min()), float(flow_values.max())],
            'previous_value_count': previous_value_count,
            'slope_written': slope_written,
            'boundaries_df_refreshed': boundaries_df_refreshed,
        }
