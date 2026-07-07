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
- get_plan_met_precip()
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
    Initial water surface elevation calculation method.

    Attributes:
    - method: Calculation method name (e.g., "Normal Depth", "Known WSE", "Critical Depth")
    - slope: Normal depth slope (if method is "Normal Depth")
    - wse: Known water surface elevation (if method is "Known WSE")
    - regime: Flow regime (if found in Plan Information)
    - note: Additional information (if method not found)
    - error: Error message (if exception occurred)
    """
    method: str
    slope: Optional[float]
    wse: Optional[float]
    regime: Optional[str]
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
                time_str = plan_info.attrs.get('Simulation End Time')
                return HdfUtils.parse_ras_datetime(time_str.decode('utf-8'))
        except Exception as e:
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
                for key in hdf_file[plan_info_path].attrs.keys():
                    value = hdf_file[plan_info_path].attrs[key]
                    if isinstance(value, bytes):
                        value = HdfUtils.convert_ras_string(value)
                    attrs[key] = value
                
                return attrs
        except Exception as e:
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
                for key in hdf_file[plan_params_path].attrs.keys():
                    value = hdf_file[plan_params_path].attrs[key]
                    
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
            raise ValueError(f"Failed to get plan parameter attributes: {str(e)}")

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
        program_version = hdf_file[info_path].attrs.get("Program Version")
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
                    for key, value in params_group.attrs.items()
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
                        for key, value in hdf_file[info_path].attrs.items()
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
                for key in hdf_file[precip_path].attrs.keys():
                    value = hdf_file[precip_path].attrs[key]
                    if isinstance(value, bytes):
                        value = HdfUtils.convert_ras_string(value)
                    attrs[key] = value
                
                return attrs
        except Exception as e:
            logger.error(f"Failed to get precipitation attributes: {str(e)}")
            return {}
        
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
                for key, value in geom_group.attrs.items():
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
            logger.error(f"Failed to read HDF file {hdf_path}: {str(e)}")
            raise ValueError(f"Failed to read HDF file {hdf_path}: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to get geometry attributes: {str(e)}")
            raise ValueError(f"Failed to get geometry attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_starting_wse_method(hdf_path: Path) -> StartingWSEMethodDict:
        """
        Extract initial water surface elevation calculation method from plan HDF.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file

        Returns
        -------
        StartingWSEMethodDict
            Initial condition method with keys:
            - method: calculation method name (e.g., "Normal Depth", "Known WSE", "Critical Depth", "EGL Slope Line")
            - slope: normal depth slope (if method is "Normal Depth")
            - wse: known water surface elevation (if method is "Known WSE")
            - Additional method-specific parameters

        Notes
        -----
        The method determines how HEC-RAS calculates initial water surface elevations
        at the start of an unsteady flow simulation or downstream boundary for steady flow.
        Returns dict with 'method': 'Unknown' if boundary condition data not found.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                result = {}

                # Try to get starting WSE method from Plan Parameters
                plan_params_path = HdfPlan._PLAN_PARAMETERS_PATH
                if plan_params_path in hdf_file:
                    plan_params = hdf_file[plan_params_path]

                    # Extract starting WSE method attributes
                    # Common attribute names (adjust based on actual HDF structure):
                    method_attrs = [
                        'Downstream Reach Boundary Condition',
                        'Initial Condition Method',
                        'Starting Water Surface',
                        'Boundary Condition Type',
                    ]

                    for attr_name in method_attrs:
                        if attr_name in plan_params.attrs:
                            value = plan_params.attrs[attr_name]
                            if isinstance(value, bytes):
                                value = HdfUtils.convert_ras_string(value)
                            result['method'] = value
                            break

                    # If method is Normal Depth, get the slope
                    if 'method' in result and 'Normal' in str(result['method']):
                        slope_attrs = [
                            'Normal Depth Slope',
                            'Downstream Slope',
                            'Friction Slope',
                        ]
                        for slope_attr in slope_attrs:
                            if slope_attr in plan_params.attrs:
                                slope_value = plan_params.attrs[slope_attr]
                                if isinstance(slope_value, (np.number, float, int)):
                                    result['slope'] = float(slope_value)
                                    break

                    # If method is Known WSE, get the elevation
                    if 'method' in result and 'Known' in str(result['method']):
                        wse_attrs = [
                            'Known Water Surface',
                            'Starting WSE',
                            'Boundary Water Surface',
                        ]
                        for wse_attr in wse_attrs:
                            if wse_attr in plan_params.attrs:
                                wse_value = plan_params.attrs[wse_attr]
                                if isinstance(wse_value, (np.number, float, int)):
                                    result['wse'] = float(wse_value)
                                    break

                # If method not found in Plan Parameters, try Plan Information
                if 'method' not in result:
                    plan_info_path = HdfPlan._PLAN_INFORMATION_PATH
                    if plan_info_path in hdf_file:
                        plan_info = hdf_file[plan_info_path]
                        for attr_name in ['Flow Regime', 'Simulation Type']:
                            if attr_name in plan_info.attrs:
                                value = plan_info.attrs[attr_name]
                                if isinstance(value, bytes):
                                    value = HdfUtils.convert_ras_string(value)
                                result['regime'] = value

                # If still no method found, return indication
                if 'method' not in result:
                    logger.debug(
                        "Starting WSE method not found in %s; returning method='Unknown'.",
                        hdf_path.name,
                    )
                    result['method'] = 'Unknown'
                    result['note'] = 'Boundary condition method not found in HDF file'

                logger.debug(f"Successfully extracted starting WSE method: {result.get('method', 'Unknown')}")
                return result

        except Exception as e:
            logger.error(f"Error reading starting WSE method from {hdf_path}: {str(e)}")
            return {'method': 'Error', 'error': str(e)}


