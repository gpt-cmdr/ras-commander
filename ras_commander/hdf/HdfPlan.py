"""
Class: HdfPlan

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.

-----

All of the methods in this class are static and are designed to be used without instantiation.


- get_plan_start_time()
- get_plan_end_time()
- get_plan_timestamps_list()
- get_plan_information()
- get_plan_parameters()
- get_hdf_output_settings()
- get_plan_met_precip()
- get_plan_met_precip_values()
- get_geometry_information()
- get_starting_wse_method()






"""

import h5py
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Union
import re
import numpy as np

from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import setup_logging, get_logger
from ..fast_hdf import read_attr, read_attrs, read_typed, reraise_required

logger = get_logger(__name__)


# TypedDict definitions for dict-returning methods
class PlanInformationDict(TypedDict, total=False):
    """
    Plan information attributes from HDF Plan Data/Plan Information.

    Common attributes (not exhaustive - HDF may contain additional fields):
    - Simulation Start Time: str
    - Simulation End Time: str
    - Flow Regime: str (e.g., "Unsteady", "Steady")
    - Computation Level: str
    - Program Version: str
    - Simulation Type: str
    - Plan Name: str
    - Short Identifier: str
    - Geometry File: str
    - Flow File: str
    """
    pass  # All fields optional, types vary


class PlanMetPrecipDict(TypedDict, total=False):
    """
    Precipitation attributes from Event Conditions/Meteorology/Precipitation.

    Common attributes (not exhaustive - HDF may contain additional fields):
    - Precipitation Method: str
    - Time Series: str or array
    - Spatial Distribution: str
    - Units: str
    """
    pass  # All fields optional, types vary


class StartingWSEMethodDict(TypedDict, total=False):
    """
    Water-surface boundary conditions that start the computation.

    Attributes:
    - method: unsteady "Computed"/"Restart File" (stored Startup Mode); steady
      "Known WS", "Normal Depth", "Critical Depth", "Rating Curve", "Multiple";
      or "Unknown"/"Error"
    - slope: Normal depth slope (method "Normal Depth", all boundaries agree)
    - wse: Known water surface (method "Known WS", all boundaries agree)
    - regime: Steady flow regime from the plan file
    - boundaries: One dict per boundary that was read
    - source: HDF group or flow file that was read
    - startup_mode: Unsteady initial-condition startup mode
    - restart_file: Unsteady restart filename (restart-initialized plans)
    - warmup_steps: Unsteady 1D-2D Number of Warmup Steps
    - note: Additional information (method not found, values differ)
    - error: Error message (if exception occurred)
    """
    method: str
    slope: Optional[float]
    wse: Optional[float]
    regime: Optional[str]
    boundaries: List[Dict[str, Any]]
    source: str
    startup_mode: str
    restart_file: str
    warmup_steps: int
    note: Optional[str]
    error: Optional[str]


class HdfPlan:
    """
    A class for handling HEC-RAS plan HDF files.

    Provides static methods for extracting data from HEC-RAS plan HDF files including 
    simulation times, plan information, and geometry attributes. All methods use 
    @standardize_input for handling different input types and @log_call for logging.

    Note: This code is partially derived from the rashdf library (https://github.com/fema-ffrd/rashdf)
    under MIT license.
    """
    _PLAN_PARAMETERS_PATH = "Plan Data/Plan Parameters"
    _PLAN_INFORMATION_PATH = "Plan Data/Plan Information"

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_start_time(hdf_path: Path) -> datetime:
        """
        Get the plan start time from the plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            datetime: The plan start time in UTC format.

        Raises:
            ValueError: If there's an error reading the plan start time.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfBase.get_simulation_start_time(hdf_file)
        except Exception as e:
            reraise_required(e)
            raise ValueError(f"Failed to get plan start time: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_end_time(hdf_path: Path) -> datetime:
        """
        Get the plan end time from the plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            datetime: The plan end time.

        Raises:
            ValueError: If there's an error reading the plan end time.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                plan_info = hdf_file.get('Plan Data/Plan Information')
                if plan_info is None:
                    raise ValueError("Plan Information not found in HDF file")
                time_str = read_attr(plan_info, 'Simulation End Time', None)
                return HdfUtils.parse_ras_datetime(time_str.decode('utf-8'))
        except Exception as e:
            reraise_required(e)
            raise ValueError(f"Failed to get plan end time: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_timestamps_list(hdf_path: Path) -> List[datetime]:
        """
        Get the list of output timestamps from the plan simulation.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            List[datetime]: Chronological list of simulation output timestamps in UTC.

        Raises:
            ValueError: If there's an error retrieving the plan timestamps.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfBase.get_unsteady_timestamps(hdf_file)
        except Exception as e:
            reraise_required(e)
            raise ValueError(f"Failed to get plan timestamps: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_information(hdf_path: Path) -> PlanInformationDict:
        """
        Get plan information from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            PlanInformationDict: Plan information including simulation times, flow regime,
                computation settings, etc.

        Raises:
            ValueError: If there's an error retrieving the plan information.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                plan_info_path = "Plan Data/Plan Information"
                if plan_info_path not in hdf_file:
                    raise ValueError(f"Plan Information not found in {hdf_path}")
                
                attrs = {}
                stored = read_attrs(hdf_file[plan_info_path])
                for key in stored.keys():
                    value = stored[key]
                    if isinstance(value, bytes):
                        value = HdfUtils.convert_ras_string(value)
                    attrs[key] = value
                
                return attrs
        except Exception as e:
            reraise_required(e)
            raise ValueError(f"Failed to get plan information attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_parameters(hdf_path: Path) -> pd.DataFrame:
        """
        Get plan parameter attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            pd.DataFrame: A DataFrame containing the plan parameters with columns:
                - Parameter: Name of the parameter
                - Value: Value of the parameter (decoded if byte string)
                - Plan: Plan number (01-99) extracted from the filename (ProjectName.pXX.hdf)
            Returns empty DataFrame if Plan Parameters not found (e.g., steady flow results).

        Raises:
            ValueError: If there's an error retrieving the plan parameter attributes.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                plan_params_path = HdfPlan._PLAN_PARAMETERS_PATH
                if plan_params_path not in hdf_file:
                    logger.debug(
                        "Plan Parameters not found in %s; returning empty parameter table.",
                        hdf_path.name,
                    )
                    return pd.DataFrame(columns=['Plan', 'Parameter', 'Value'])
                
                # Extract parameters
                params_dict = {}
                stored = read_attrs(hdf_file[plan_params_path])
                for key in stored.keys():
                    value = stored[key]
                    
                    # Handle different types of values
                    if isinstance(value, bytes):
                        value = HdfUtils.convert_ras_string(value)
                    elif isinstance(value, np.ndarray):
                        # Handle array values
                        if value.dtype.kind in {'S', 'a'}:  # Array of byte strings
                            value = [v.decode('utf-8') if isinstance(v, bytes) else v for v in value]
                        else:
                            value = value.tolist()  # Convert numpy array to list
                        
                        # If it's a single-item list, extract the value
                        if len(value) == 1:
                            value = value[0]
                    
                    params_dict[key] = value
                
                # Create DataFrame from parameters
                df = pd.DataFrame.from_dict(params_dict, orient='index', columns=['Value'])
                df.index.name = 'Parameter'
                df = df.reset_index()
                
                # Extract plan number from filename
                filename = Path(hdf_path).name
                plan_match = re.search(r'\.p(\d{2})\.', filename)
                if plan_match:
                    plan_num = plan_match.group(1)
                else:
                    plan_num = "00"  # Default if no match found
                    logger.warning(
                        "Could not extract plan number from filename %s; "
                        "using fallback Plan value '00'.",
                        filename,
                    )
                
                df['Plan'] = plan_num
                
                # Reorder columns to put Plan first
                df = df[['Plan', 'Parameter', 'Value']]
                
                return df

        except Exception as e:
            reraise_required(e)
            raise ValueError(f"Failed to get plan parameter attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_hdf_output_settings(hdf_path: Path) -> Dict[str, Any]:
        """
        Report how a computed plan HDF was actually written (compression and cadence).

        Use this to confirm that the plan-file settings written by
        ``RasPlan.set_hdf_compression`` / ``RasPlan.update_plan_intervals`` were honored.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            dict with:
                - ``write_parameters``: ``HDF ...`` attributes from
                  ``Plan Data/Plan Parameters`` (compression, chunk size, ...).
                - ``time_series``: DataFrame, one row per 2D/1D unsteady time-series
                  dataset (``name``, ``shape``, ``chunks``, ``compression``,
                  ``compression_opts``, ``shuffle``, ``stored_mb``, ``raw_mb``,
                  ``ratio``).
                - ``n_timesteps``: length of ``Time Date Stamp`` under Base Output
                  (the mapping-interval cadence, not the Hydrograph Output Interval), or None.
                - ``file_size_mb``: size of the HDF file on disk.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                write_parameters: Dict[str, Any] = {}
                params_path = HdfPlan._PLAN_PARAMETERS_PATH
                if params_path in hdf_file:
                    stored = read_attrs(hdf_file[params_path])
                    for key in stored.keys():
                        if key.startswith("HDF "):
                            write_parameters[key] = HdfPlan._decode_hdf_attr_value(
                                stored[key]
                            )

                rows: List[Dict[str, Any]] = []
                ts_root = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
                n_timesteps = None
                if ts_root in hdf_file:
                    stamp_path = f"{ts_root}/Time Date Stamp"
                    if stamp_path in hdf_file:
                        n_timesteps = int(hdf_file[stamp_path].shape[0])

                    def _collect(name, obj):
                        if isinstance(obj, h5py.Dataset) and obj.ndim == 2 and obj.size > 0:
                            raw = obj.size * obj.dtype.itemsize
                            stored = obj.id.get_storage_size()
                            rows.append({
                                "name": name,
                                "shape": obj.shape,
                                "chunks": obj.chunks,
                                "compression": obj.compression,
                                "compression_opts": obj.compression_opts,
                                "shuffle": obj.shuffle,
                                "stored_mb": stored / 1e6,
                                "raw_mb": raw / 1e6,
                                "ratio": stored / raw if raw else None,
                            })

                    hdf_file[ts_root].visititems(_collect)

            return {
                "write_parameters": write_parameters,
                "time_series": pd.DataFrame(
                    rows,
                    columns=["name", "shape", "chunks", "compression", "compression_opts",
                             "shuffle", "stored_mb", "raw_mb", "ratio"],
                ),
                "n_timesteps": n_timesteps,
                "file_size_mb": Path(hdf_path).stat().st_size / 1e6,
            }
        except Exception as e:
            reraise_required(e)
            raise ValueError(f"Failed to get HDF output settings: {str(e)}")

    @staticmethod
    def _decode_hdf_attr_value(value: Any) -> Any:
        """
        Convert HDF attribute scalars/arrays to Python values.
        """
        if isinstance(value, bytes):
            return HdfUtils.convert_ras_string(value)
        if isinstance(value, np.bytes_):
            return HdfUtils.convert_ras_string(bytes(value))
        if isinstance(value, np.ndarray):
            return [
                HdfPlan._decode_hdf_attr_value(item)
                for item in value.tolist()
            ]
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and np.isnan(value):
            return None
        return value

    @staticmethod
    def _value_at_index(value: Any, index: int) -> Any:
        """
        Return a per-mesh HDF attribute value for one mesh index.
        """
        if isinstance(value, list):
            if not value:
                return None
            if index < len(value):
                return value[index]
            if len(value) == 1:
                return value[0]
            return None
        return value

    @staticmethod
    def _parse_major_version(version: Any) -> Optional[int]:
        """
        Parse the leading major HEC-RAS version number from an HDF attribute.
        """
        if version is None:
            return None
        match = re.search(r"\d+", str(version))
        if not match:
            return None
        try:
            return int(match.group(0))
        except ValueError:
            return None

    @staticmethod
    def _get_plan_hdf_program_version(hdf_file: h5py.File) -> Optional[str]:
        """
        Return Program Version from the plan information group when present.
        """
        info_path = HdfPlan._PLAN_INFORMATION_PATH
        if info_path not in hdf_file:
            return None
        program_version = read_attr(hdf_file[info_path], "Program Version", None)
        if program_version is None:
            return None
        return str(HdfPlan._decode_hdf_attr_value(program_version))

    @staticmethod
    def _find_legacy_output_file_for_plan(hdf_path: Path) -> Optional[Path]:
        """
        Return a sibling legacy HEC-RAS .O## output file for this plan HDF if present.
        """
        match = re.search(r"\.p(?P<plan_number>\d{2})\.hdf$", hdf_path.name, re.IGNORECASE)
        if not match:
            return None

        project_name = hdf_path.name[:match.start()]
        plan_number = match.group("plan_number")
        for suffix in (f".O{plan_number}", f".o{plan_number}"):
            candidate = hdf_path.with_name(f"{project_name}{suffix}")
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _missing_plan_parameters_message(hdf_path: Path, hdf_file: h5py.File) -> str:
        """
        Build concise guidance for HDF calls that require Plan Parameters.
        """
        message_parts = [
            "HdfPlan.get_2d_flow_options() requires a HEC-RAS 5.x+ computed "
            "plan HDF containing 'Plan Data/Plan Parameters'.",
            f"{hdf_path.name} does not contain that group.",
        ]

        program_version = HdfPlan._get_plan_hdf_program_version(hdf_file)
        major_version = HdfPlan._parse_major_version(program_version)
        if program_version and major_version is not None and major_version < 5:
            message_parts.append(
                f"Program Version {program_version} indicates HEC-RAS 4.x or earlier."
            )

        legacy_output = HdfPlan._find_legacy_output_file_for_plan(hdf_path)
        if legacy_output is not None:
            message_parts.append(f"Found legacy output file {legacy_output.name}.")

        message_parts.append(
            "HEC-RAS 4.x and earlier did not produce plan HDF output; those "
            "results are stored in legacy .O## files and should be accessed "
            "with RasControl."
        )
        return " ".join(message_parts)

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_2d_flow_options(
        hdf_path: Path,
        mesh_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract 2D unsteady computation options stored in a plan HDF output.

        Args:
            hdf_path: Path to the HEC-RAS plan HDF file.
            mesh_name: Optional 2D flow area name to filter returned areas.

        Returns:
            Dict[str, Any]: Parsed 2D options using the same public option names
                as ``RasPlan.get_2d_flow_options()``.
        """
        from ..RasPlan import RasPlan

        hdf_option_keys = {
            "theta": "2D Theta",
            "theta_warmup": "2D Theta Warmup",
            "water_surface_tolerance": "2D Water Surface Tolerance",
            "volume_tolerance": "2D Volume Tolerance",
            "max_iterations": "2D Maximum Iterations",
            "equation_set": "2D Equation Set",
            "initial_conditions_time_hours": "2D Initial Conditions Ramp Up Time (hrs)",
            "ramp_up_fraction": "2D Boundary Condition Ramp Up Fraction",
            "time_slices": "2D Number of Time Slices",
            "eddy_viscosity": "2D Longitudinal Mixing Coefficient",
            "transverse_eddy_viscosity": "2D Transverse Mixing Coefficient",
            "smagorinsky_mixing": "2D Smagorinsky Mixing Coefficient",
            "boundary_condition_volume_check": "2D Boundary Condition Volume Check",
            "latitude": "2D Latitude for Coriolis",
            "cores": "2D Cores (per mesh)",
            "solver_type": "2D Matrix Solver",
        }

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                params_path = HdfPlan._PLAN_PARAMETERS_PATH
                if params_path not in hdf_file:
                    raise ValueError(HdfPlan._missing_plan_parameters_message(hdf_path, hdf_file))

                params_group = hdf_file[params_path]
                attrs = {
                    key: HdfPlan._decode_hdf_attr_value(value)
                    for key, value in read_attrs(params_group).items()
                }

                names = attrs.get("2D Names") or []
                if not isinstance(names, list):
                    names = [names]

                mesh_count = len(names)
                if mesh_count == 0:
                    mesh_count = max(
                        (
                            len(value) for value in attrs.values()
                            if isinstance(value, list)
                        ),
                        default=0,
                    )

                areas = []
                for index in range(mesh_count):
                    name = HdfPlan._value_at_index(names, index)
                    area = {"name": str(name).strip() if name is not None else None}
                    for api_key, hdf_key in hdf_option_keys.items():
                        if hdf_key not in attrs:
                            continue
                        raw_value = HdfPlan._value_at_index(attrs[hdf_key], index)
                        area[api_key] = RasPlan._coerce_2d_option_value(api_key, raw_value)
                    areas.append(area)

                if mesh_name is not None:
                    normalized = mesh_name.strip().lower()
                    areas = [
                        area for area in areas
                        if (area.get("name") or "").strip().lower() == normalized
                    ]
                    if not areas:
                        raise ValueError(f"2D flow area '{mesh_name}' not found in {hdf_path.name}")

                plan_info = {}
                info_path = HdfPlan._PLAN_INFORMATION_PATH
                if info_path in hdf_file:
                    plan_info = {
                        key: HdfPlan._decode_hdf_attr_value(value)
                        for key, value in read_attrs(hdf_file[info_path]).items()
                    }

                global_options = {}
                if "2D Coriolis" in attrs:
                    global_options["coriolis"] = RasPlan._coerce_2d_option_value(
                        "coriolis",
                        attrs["2D Coriolis"],
                    )

                return {
                    "source": "hdf",
                    "hdf_path": str(hdf_path),
                    "program_version": plan_info.get("Program Version"),
                    "plan": {},
                    "default": global_options,
                    "areas": areas,
                }

        except Exception as e:
            reraise_required(e)
            raise ValueError(f"Failed to get 2D flow options from HDF: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_met_precip(hdf_path: Path) -> PlanMetPrecipDict:
        """
        Get precipitation attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            PlanMetPrecipDict: Precipitation attributes including method, time series data,
                and spatial distribution if available. Returns empty dict if
                no precipitation data exists.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                precip_path = "Event Conditions/Meteorology/Precipitation"
                if precip_path not in hdf_file:
                    logger.debug(
                        "Precipitation data not found in %s; returning empty precipitation attributes.",
                        hdf_path.name,
                    )
                    return {}
                
                attrs = {}
                stored = read_attrs(hdf_file[precip_path])
                for key in stored.keys():
                    value = stored[key]
                    if isinstance(value, bytes):
                        value = HdfUtils.convert_ras_string(value)
                    attrs[key] = value
                
                return attrs
        except Exception as e:
            reraise_required(e)
            logger.error(f"Failed to get precipitation attributes: {str(e)}")
            return {}
        
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_plan_met_precip_values(
        hdf_path: Union[str, Path, int, h5py.File], *, ras_object: Optional[Any] = None,
        group_path: str = "Event Conditions/Meteorology/Precipitation",
    ) -> Dict[str, Any]:
        """Read materialized solver precipitation arrays without unit conversion.

        Args:
            hdf_path: Plan HDF path, plan identifier or open HDF handle accepted
                by the HDF input decorator.
            ras_object: Optional RasPrj context for resolving plan identifiers.
            group_path: Exact HDF precipitation group. The default reads a
                compiled plan. For a retained meteorology-only snapshot, pass
                ``"Meteorology/Precipitation"`` explicitly. No alternate group
                is selected when the requested data are absent.

        Returns:
            Dictionary with ``values`` (time by precipitation-grid cell), raw
            ``timestamps``, group ``attributes``, ``value_attributes`` and
            ``timestamp_attributes``. Arrays are independent copies. Attribute
            byte strings are decoded; timestamp encodings and numerical values
            are preserved. Cell columns are precipitation-grid indexes, not
            hydraulic mesh-cell indexes. No depth/rate or time-unit inference
            is made. Native materialization was checked on HEC-RAS 6.6.

        Raises:
            KeyError: Solver Values/Timestamp datasets are absent. An imported
                raster sidecar alone is not materialized solver precipitation.
            ValueError: The group path is empty or not a string, or dataset
                dimensions or time-axis lengths are inconsistent.

        Notes:
            Opens the source read-only and does not execute HEC-RAS. Snapshot
            arrays retain the same units, timestamp encodings and shape checks
            as compiled-plan arrays. This read does not establish that another
            plan used the retained precipitation.
        """
        if not isinstance(group_path, str) or not group_path.strip('/'):
            raise ValueError("group_path must be a nonempty HDF group path")
        group_path = group_path.rstrip('/')

        def attributes(obj):
            return {
                key: value.decode('utf-8') if isinstance(value, bytes) else value
                for key, value in read_attrs(obj).items()
            }

        with h5py.File(hdf_path, 'r') as hdf:
            values_path = group_path + '/Values'
            times_path = group_path + '/Timestamp'
            if values_path not in hdf or times_path not in hdf:
                raise KeyError(f"Materialized precipitation Values/Timestamp absent in {hdf_path}")
            values = hdf[values_path]
            times = hdf[times_path]
            if (values.ndim != 2 or not all(values.shape) or times.ndim != 1
                    or values.shape[0] != times.shape[0]):
                raise ValueError(f"Inconsistent precipitation shapes: {values.shape}, {times.shape}")
            return {
                'values': read_typed(values, Ellipsis), 'timestamps': read_typed(times, Ellipsis),
                'attributes': attributes(hdf[group_path]),
                'value_attributes': attributes(values),
                'timestamp_attributes': attributes(times),
            }

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_geometry_information(hdf_path: Path) -> pd.DataFrame:
        """
        Get root level geometry attributes from the HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            pd.DataFrame: DataFrame with geometry attributes including Creation Date/Time,
                        Version, Units, and Projection information.

        Raises:
            ValueError: If Geometry group is missing or there's an error reading attributes.
        """
        logger.debug(f"Getting geometry attributes from {hdf_path}")
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                geom_attrs_path = "Geometry"
                logger.debug(f"Checking for Geometry group in {hdf_path}")
                if geom_attrs_path not in hdf_file:
                    logger.error(f"Geometry group not found in {hdf_path}")
                    raise ValueError(f"Geometry group not found in {hdf_path}")

                attrs = {}
                geom_group = hdf_file[geom_attrs_path]
                logger.debug("Getting root level geometry attributes")
                # Get root level geometry attributes only
                for key, value in read_attrs(geom_group).items():
                    if isinstance(value, bytes):
                        try:
                            value = HdfUtils.convert_ras_string(value)
                        except UnicodeDecodeError:
                            logger.warning(f"Failed to decode byte string for root attribute {key}")
                            continue
                    attrs[key] = value
                    logger.debug(f"Geometry attribute: {key} = {value}")

                logger.debug(f"Successfully extracted {len(attrs)} root level geometry attributes")
                return pd.DataFrame({"Value": pd.Series(attrs, dtype=object)})

        except (OSError, RuntimeError) as e:
            reraise_required(e)
            logger.error(f"Failed to read HDF file {hdf_path}: {str(e)}")
            raise ValueError(f"Failed to read HDF file {hdf_path}: {str(e)}")
        except Exception as e:
            reraise_required(e)
            logger.error(f"Failed to get geometry attributes: {str(e)}")
            raise ValueError(f"Failed to get geometry attributes: {str(e)}")

    # Boundary-condition groups under Event Conditions/Unsteady/Boundary Conditions
    # that set a water surface, and the method name reported for each.
    _UNSTEADY_BC_PATH = "Event Conditions/Unsteady/Boundary Conditions"
    _UNSTEADY_IC_PATH = "Event Conditions/Unsteady/Initial Conditions"
    _WS_BOUNDARY_GROUPS = {
        "Normal Depths": "Normal Depth",
        "Rating Curves": "Rating Curve",
        "Stage Hydrographs": "Stage Hydrograph",
    }
    _BC_LOCATION_ATTRS = {
        "River": "river",
        "Reach": "reach",
        "RS": "rs",
        "2D Flow Area": "2d_flow_area",
        "BC Line": "bc_line",
        "Storage Area": "storage_area",
    }
    _PLAN_FLOW_REGIMES = {
        "Subcritical Flow": "Subcritical",
        "Supercritical Flow": "Supercritical",
        "Mixed Flow": "Mixed",
    }

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_starting_wse_method(hdf_path: Path) -> StartingWSEMethodDict:
        """
        Report how the computation's starting water surface is established.

        HEC-RAS does not store a single "starting WSE method" attribute. This
        reads where HEC-RAS records it:

        - **Unsteady plans** (the plan HDF has
          ``Event Conditions/Unsteady/Boundary Conditions``, written when the
          plan is computed): the starting water surface comes from the
          initialization, not from a boundary. HEC-RAS either reads a restart
          (initial conditions) file or computes water surfaces from the
          initial flows with a steady backwater pass, followed by the warm-up.
          ``method`` is the ``Startup Mode`` attribute of
          ``Event Conditions/Unsteady/Initial Conditions``. The ``Normal
          Depths`` (friction slope), ``Rating Curves`` and ``Stage
          Hydrographs`` members are reported in ``boundaries`` only.
        - **Steady plans** (``Event Conditions/Steady``): HEC-RAS writes no
          boundary data to the HDF. The steady flow file named by the plan
          HDF's ``Plan Information`` ``Flow Filename`` attribute is read from
          the HDF's folder (file name matched case-insensitively) with
          :meth:`RasSteady.read_flow_file`. The plan text file
          (``Plan Filename``) supplies the flow regime: ``Subcritical Flow``
          selects the downstream (``Dn``) boundaries, ``Supercritical Flow``
          the upstream (``Up``) boundaries, ``Mixed Flow`` both.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file

        Returns
        -------
        StartingWSEMethodDict
            - ``method``, unsteady plans: the stored ``Startup Mode``,
              ``"Computed"`` (water surfaces computed from the initial flows,
              then warm-up; every public corpus plan) or ``"Restart File"``
              (initial conditions read from ``restart_file``); any other stored
              value is returned verbatim. ``"Unknown"`` (with ``note``) when no
              ``Startup Mode`` is stored (HEC-RAS 5.0.x).
            - ``method``, steady plans: ``"Known WS"``, ``"Normal Depth"``,
              ``"Critical Depth"`` or ``"Rating Curve"`` when every selected
              boundary has that type; ``"Multiple"`` when they differ;
              ``"Unknown"`` (with ``note``) when no boundary could be read.
            - ``method`` is ``"Error"`` (with ``error``) when reading failed.
            - ``slope``: steady only; the normal-depth friction slope when the
              method is ``"Normal Depth"`` and every selected boundary agrees.
              Per-boundary slopes are always in ``boundaries``.
            - ``wse``: steady only; the known water surface when the method is
              ``"Known WS"`` and every selected boundary has the same value.
            - ``regime``: steady plans only, ``"Subcritical"``,
              ``"Supercritical"`` or ``"Mixed"`` from the plan file.
            - ``boundaries``: one dict per selected boundary (type, location,
              and its slope / known WS / rating-curve points when stored).
            - ``source``: the HDF group or flow file that was read.
            - ``startup_mode``: unsteady initial-condition startup mode.
            - ``restart_file``: unsteady ``Restart Filename`` when stored.
            - ``warmup_steps``: unsteady ``1D-2D Number of Warmup Steps`` from
              ``Plan Data/Plan Parameters`` when stored.

        Notes
        -----
        Values are not filled when they cannot be read: ``slope``/``wse`` are
        omitted when boundaries disagree (see ``boundaries``); ``regime`` is
        omitted for unsteady plans and when the plan file or its regime line is
        absent, in which case both boundary sides of a steady flow file are
        reported. Unsteady boundary positions (upstream/downstream) are not
        stored in the HDF and are not inferred. Quasi-unsteady (``.q##``) flow
        files are not read. Earlier releases looked for plan attributes HEC-RAS
        does not write and returned ``"Unknown"`` for every real plan.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                result = None
                if HdfPlan._UNSTEADY_BC_PATH in hdf_file:
                    result = HdfPlan._unsteady_starting_wse(hdf_file)
                elif "Event Conditions/Steady" in hdf_file:
                    flow_name = HdfPlan._plan_info_text(hdf_file, "Flow Filename")
                    plan_name = HdfPlan._plan_info_text(hdf_file, "Plan Filename")
                else:
                    result = {
                        'method': 'Unknown',
                        'note': ("No unsteady boundary conditions "
                                 f"({HdfPlan._UNSTEADY_BC_PATH}) or steady event "
                                 "conditions in the plan HDF"),
                    }
            if result is None:
                result = HdfPlan._steady_starting_wse(Path(hdf_path), flow_name, plan_name)

            if result['method'] == 'Unknown':
                logger.debug(
                    "Starting WSE method not found in %s; returning method='Unknown'.",
                    hdf_path.name,
                )
            logger.debug(f"Successfully extracted starting WSE method: {result.get('method', 'Unknown')}")
            return result

        except Exception as e:
            reraise_required(e)
            logger.error(f"Error reading starting WSE method from {hdf_path}: {str(e)}")
            return {'method': 'Error', 'error': str(e)}

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, np.ndarray) and value.size == 1:
            value = value.reshape(()).item()
        if isinstance(value, (bytes, np.bytes_)):
            value = bytes(value).decode('utf-8', 'replace')
        return str(value).strip()

    @staticmethod
    def _plan_info_text(hdf_file: h5py.File, name: str) -> Optional[str]:
        info = hdf_file.get(HdfPlan._PLAN_INFORMATION_PATH)
        if info is None or name not in info.attrs:
            return None
        return HdfPlan._text(read_attr(info, name)) or None

    @staticmethod
    def _summarize_boundaries(result: Dict[str, Any], boundaries: List[Dict[str, Any]],
                              empty_note: str) -> Dict[str, Any]:
        result['boundaries'] = boundaries
        types = sorted({b['type'] for b in boundaries})
        if not types:
            result['method'] = 'Unknown'
            result['note'] = empty_note
            return result
        if len(types) > 1:
            result['method'] = 'Multiple'
            result['note'] = f"Boundary types differ: {', '.join(types)}; see 'boundaries'"
            return result
        result['method'] = types[0]
        for key, method in (('slope', 'Normal Depth'), ('wse', 'Known WS')):
            if types[0] != method:
                continue
            values = {b.get(key) for b in boundaries}
            if len(values) == 1 and None not in values:
                result[key] = values.pop()
            else:
                result['note'] = f"{method} values differ between boundaries; see 'boundaries'"
        return result

    @staticmethod
    def _unsteady_starting_wse(hdf_file: h5py.File) -> Dict[str, Any]:
        result: Dict[str, Any] = {'source': HdfPlan._UNSTEADY_BC_PATH}
        ic = hdf_file.get(HdfPlan._UNSTEADY_IC_PATH)
        if ic is not None and 'Startup Mode' in ic.attrs:
            result['startup_mode'] = HdfPlan._text(read_attr(ic, 'Startup Mode'))
        if ic is not None and 'Restart Filename' in ic.attrs:
            result['restart_file'] = HdfPlan._text(read_attr(ic, 'Restart Filename'))
        params = hdf_file.get(HdfPlan._PLAN_PARAMETERS_PATH)
        if params is not None and '1D-2D Number of Warmup Steps' in params.attrs:
            result['warmup_steps'] = int(np.asarray(
                read_attr(params, '1D-2D Number of Warmup Steps')).reshape(-1)[0])
        group = hdf_file[HdfPlan._UNSTEADY_BC_PATH]
        boundaries = []
        for group_name, method in HdfPlan._WS_BOUNDARY_GROUPS.items():
            members = group.get(group_name)
            if not isinstance(members, h5py.Group):
                continue
            for location, dataset in members.items():
                if not isinstance(dataset, h5py.Dataset):
                    continue
                entry: Dict[str, Any] = {'type': method, 'location': location}
                for attr_name, key in HdfPlan._BC_LOCATION_ATTRS.items():
                    if attr_name in dataset.attrs:
                        entry[key] = HdfPlan._text(read_attr(dataset, attr_name))
                if group_name == "Normal Depths" and dataset.size >= 1:
                    entry['slope'] = float(np.asarray(read_typed(dataset)).reshape(-1)[0])
                elif group_name == "Rating Curves":
                    entry['points'] = int(dataset.shape[0]) if dataset.shape else 0
                boundaries.append(entry)
        # The initialization, not the outlet boundary, is the unsteady starting method.
        result['boundaries'] = boundaries
        if result.get('startup_mode'):
            result['method'] = result['startup_mode']
        else:
            result['method'] = 'Unknown'
            result['note'] = (f"No Startup Mode attribute in {HdfPlan._UNSTEADY_IC_PATH} "
                              "(not written by HEC-RAS 5.0.x); initialization not determined")
        return result

    @staticmethod
    def _sibling_file(folder: Path, name: Optional[str]) -> Optional[Path]:
        """``folder/name``, matching the file name case-insensitively (HEC-RAS mixes case)."""
        if not name:
            return None
        exact = folder / name
        if exact.is_file():
            return exact
        wanted = name.lower()
        try:
            for candidate in folder.iterdir():
                if candidate.name.lower() == wanted and candidate.is_file():
                    return candidate
        except OSError:
            return None
        return None

    @staticmethod
    def _plan_flow_regime(plan_path: Optional[Path]) -> Optional[str]:
        if plan_path is None:
            return None
        with open(plan_path, 'r', encoding='utf-8', errors='replace') as plan_file:
            for line in plan_file:
                regime = HdfPlan._PLAN_FLOW_REGIMES.get(line.strip())
                if regime:
                    return regime
        return None

    @staticmethod
    def _steady_starting_wse(hdf_path: Path, flow_name: Optional[str],
                             plan_name: Optional[str]) -> Dict[str, Any]:
        from ..RasSteady import RasSteady

        if not flow_name:
            return {'method': 'Unknown',
                    'note': "Steady plan HDF has no Plan Information 'Flow Filename' attribute"}
        if not re.fullmatch(r".+\.f\d\d", flow_name, flags=re.IGNORECASE):
            return {'method': 'Unknown',
                    'note': f"Flow file {flow_name} is not a steady flow file (.f##)"}
        flow_path = HdfPlan._sibling_file(hdf_path.parent, flow_name)
        if flow_path is None:
            return {'method': 'Unknown',
                    'note': f"Steady flow file {flow_name} not found next to {hdf_path.name}"}

        data = RasSteady.read_flow_file(flow_path)
        result: Dict[str, Any] = {'source': flow_path.name}
        regime = HdfPlan._plan_flow_regime(HdfPlan._sibling_file(hdf_path.parent, plan_name))
        if regime:
            result['regime'] = regime
        sides = {'Subcritical': ('downstream',), 'Supercritical': ('upstream',)}.get(
            regime, ('upstream', 'downstream'))
        names = data.get('profile_names') or []

        boundaries = []
        for block in data.get('boundaries', []):
            for side in sides:
                spec = block.get(side) or {}
                boundary_type = spec.get('type', RasSteady.NO_BOUNDARY)
                if boundary_type == RasSteady.NO_BOUNDARY:
                    continue
                values = {'wse': spec.get('known_ws'), 'slope': spec.get('slope')}
                if 'profile' in block:
                    profiles = [block['profile']]
                else:
                    # Legacy "Boundary for River Rch & RM=" blocks hold one value per profile.
                    count = max((len(v) for v in values.values() if isinstance(v, list)), default=0)
                    profiles = list(range(1, count + 1)) or [None]
                for index, profile in enumerate(profiles):
                    entry: Dict[str, Any] = {
                        'type': RasSteady.BOUNDARY_TYPE_NAMES[boundary_type],
                        'side': side,
                        'river': block.get('river'),
                        'reach': block.get('reach'),
                        'profile': profile,
                    }
                    if profile is not None and 1 <= profile <= len(names):
                        entry['profile_name'] = names[profile - 1]
                    for key, value in values.items():
                        if isinstance(value, list):
                            value = value[index] if index < len(value) else None
                        if value is not None:
                            entry[key] = float(value)
                    if spec.get('rating_curve'):
                        entry['rating_curve'] = [tuple(float(v) for v in pair)
                                                 for pair in spec['rating_curve']]
                    boundaries.append(entry)
        return HdfPlan._summarize_boundaries(
            result, boundaries, f"No {'/'.join(sides)} boundary defined in {flow_path.name}")


