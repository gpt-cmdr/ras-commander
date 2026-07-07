"""
Class: HdfResultsXsec

Contains methods for extracting 1D results data from HDF files. 
This includes cross section timeseries, structures and reference line/point timeseries as these are all 1D elements.

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfResultsXsec:
- get_xsec_timeseries(): Extract cross-section timeseries data including water surface, velocity, and flow
- get_ref_lines_timeseries(): Get timeseries output for reference lines
- get_ref_points_timeseries(): Get timeseries output for reference points

TO BE IMPLEMENTED: 
DSS Hydrograph Extraction for 1D and 2D Structures. 

Planned functions:
- get_bridge_timeseries(): Extract timeseries data for bridge structures
- get_inline_structures_timeseries(): Extract timeseries data for inline structures

Notes:
- All functions use the get_ prefix to indicate they return data
- Results data functions use results_ prefix to indicate they handle results data
- All functions include proper error handling and logging
- Functions return xarray Datasets for efficient handling of multi-dimensional data
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Tuple, Sequence

import h5py
import numpy as np
import pandas as pd
import xarray as xr

from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)

class HdfResultsXsec:
    """
    A static class for extracting and processing 1D results data from HEC-RAS HDF files.

    This class provides methods to extract and process unsteady flow simulation results
    for cross-sections, reference lines, and reference points. All methods are static
    and designed to be used without class instantiation.

    The class handles:
    - Cross-section timeseries (water surface, velocity, flow)
    - Reference line timeseries
    - Reference point timeseries

    Dependencies:
        - HdfBase: Core HDF file operations
        - HdfUtils: Utility functions for HDF processing
    """
    _BASE_TS_PATH = (
        "Results/Unsteady/Output/Output Blocks/Base Output/"
        "Unsteady Time Series"
    )
    _XSEC_OUTPUT_PATH = f"{_BASE_TS_PATH}/Cross Sections"
    _TIME_STAMP_PATH = f"{_BASE_TS_PATH}/Time Date Stamp (ms)"


# Tested functions from AWS webinar where the code was developed
# Need to add examples


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_xsec_timeseries(hdf_path: Path) -> xr.Dataset:
        """
        Extract Water Surface, Velocity Total, Velocity Channel, Flow Lateral, and Flow data from HEC-RAS HDF file.
        Includes Cross Section Only and Cross Section Attributes as coordinates in the xarray.Dataset.
        Also calculates maximum values for key parameters.

        Parameters:
        -----------
        hdf_path : Path
            Path to the HEC-RAS results HDF file

        Returns:
        --------
        xr.Dataset
            Xarray Dataset containing the extracted cross-section results with appropriate coordinates and attributes.
            Includes maximum values for Water Surface, Flow, Channel Velocity, Total Velocity, and Lateral Flow.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Define base paths
                base_output_path = HdfResultsXsec._XSEC_OUTPUT_PATH
                time_stamp_path = HdfResultsXsec._TIME_STAMP_PATH
                required_dataset_paths = [
                    f"{base_output_path}/Cross Section Attributes",
                    f"{base_output_path}/Cross Section Only",
                    time_stamp_path,
                    f"{base_output_path}/Water Surface",
                    f"{base_output_path}/Velocity Total",
                    f"{base_output_path}/Velocity Channel",
                    f"{base_output_path}/Flow Lateral",
                    f"{base_output_path}/Flow",
                ]
                HdfResultsXsec._validate_xsec_timeseries_paths(
                    hdf_path,
                    hdf_file,
                    required_dataset_paths,
                )
                
                # Extract Cross Section Attributes
                attrs_dataset = hdf_file[f"{base_output_path}/Cross Section Attributes"][:]
                rivers = [attr['River'].decode('utf-8').strip() for attr in attrs_dataset]
                reaches = [attr['Reach'].decode('utf-8').strip() for attr in attrs_dataset]
                stations = [attr['Station'].decode('utf-8').strip() for attr in attrs_dataset]
                names = [attr['Name'].decode('utf-8').strip() for attr in attrs_dataset]
                
                # Extract Cross Section Only (Unique Names)
                cross_section_only_dataset = hdf_file[f"{base_output_path}/Cross Section Only"][:]
                cross_section_names = [cs.decode('utf-8').strip() for cs in cross_section_only_dataset]
                
                # Extract Time Stamps and convert to datetime
                time_stamps = hdf_file[time_stamp_path][:]
                if any(isinstance(ts, bytes) for ts in time_stamps):
                    time_stamps = [ts.decode('utf-8') for ts in time_stamps]
                # Convert RAS format timestamps to datetime
                times = pd.to_datetime(time_stamps, format='%d%b%Y %H:%M:%S:%f')
                
                # Extract Required Datasets
                water_surface = hdf_file[f"{base_output_path}/Water Surface"][:]
                velocity_total = hdf_file[f"{base_output_path}/Velocity Total"][:]
                velocity_channel = hdf_file[f"{base_output_path}/Velocity Channel"][:]
                flow_lateral = hdf_file[f"{base_output_path}/Flow Lateral"][:]
                flow = hdf_file[f"{base_output_path}/Flow"][:]
                
                # Calculate maximum values along time axis
                max_water_surface = np.max(water_surface, axis=0)
                max_flow = np.max(flow, axis=0)
                max_velocity_channel = np.max(velocity_channel, axis=0)
                max_velocity_total = np.max(velocity_total, axis=0)
                max_flow_lateral = np.max(flow_lateral, axis=0)
                
                # Create Xarray Dataset
                ds = xr.Dataset(
                    {
                        'Water_Surface': (['time', 'cross_section'], water_surface),
                        'Velocity_Total': (['time', 'cross_section'], velocity_total),
                        'Velocity_Channel': (['time', 'cross_section'], velocity_channel),
                        'Flow_Lateral': (['time', 'cross_section'], flow_lateral),
                        'Flow': (['time', 'cross_section'], flow),
                    },
                    coords={
                        'time': times,
                        'cross_section': cross_section_names,
                        'River': ('cross_section', rivers),
                        'Reach': ('cross_section', reaches),
                        'Station': ('cross_section', stations),
                        'Name': ('cross_section', names),
                        'Maximum_Water_Surface': ('cross_section', max_water_surface),
                        'Maximum_Flow': ('cross_section', max_flow),
                        'Maximum_Channel_Velocity': ('cross_section', max_velocity_channel),
                        'Maximum_Velocity_Total': ('cross_section', max_velocity_total),
                        'Maximum_Flow_Lateral': ('cross_section', max_flow_lateral)
                    },
                    attrs={
                        'description': 'Cross-section results extracted from HEC-RAS HDF file',
                        'source_file': hdf_path.name
                    }
                )
                
                return ds

        except KeyError as e:
            message = e.args[0] if e.args else str(e)
            logger.error(
                "%s",
                message,
            )
            logger.debug(
                "Full HDF path for failed cross-section results extraction: %s",
                hdf_path,
                exc_info=True,
            )
            raise
        except Exception as e:
            logger.error(
                "Error extracting cross-section results from %s: %s",
                hdf_path.name,
                e,
            )
            logger.debug(
                "Full HDF path for failed cross-section results extraction: %s",
                hdf_path,
                exc_info=True,
            )
            raise

    @staticmethod
    def _validate_xsec_timeseries_paths(
        hdf_path: Path,
        hdf_file: h5py.File,
        required_dataset_paths: Sequence[str],
    ) -> None:
        """Raise an actionable error if required 1D time-series data is absent."""
        for dataset_path in required_dataset_paths:
            if dataset_path not in hdf_file:
                raise KeyError(
                    HdfResultsXsec._missing_xsec_timeseries_message(
                        hdf_path,
                        hdf_file,
                        dataset_path,
                    )
                )

    @staticmethod
    def _missing_xsec_timeseries_message(
        hdf_path: Path,
        hdf_file: h5py.File,
        dataset_path: str,
    ) -> str:
        """Return condition-specific guidance for missing 1D result datasets."""
        filename = hdf_path.name

        if "Results" not in hdf_file:
            return (
                f"Cannot extract 1D cross-section time series from {filename}: "
                "/Results is absent; this appears to be a minimal, geometry-only, "
                "or uncomputed HDF."
            )

        if "Results/Steady" in hdf_file and "Results/Unsteady" not in hdf_file:
            return (
                f"Cannot extract 1D unsteady cross-section time series from {filename}: "
                "file contains steady results, not unsteady time-series output. "
                "Use HdfResultsPlan.get_steady_wse() for steady profiles."
            )

        if "Results/Unsteady" not in hdf_file:
            return (
                f"Cannot extract 1D unsteady cross-section time series from {filename}: "
                "/Results/Unsteady is absent; the HDF does not contain unsteady "
                "time-series output."
            )

        if HdfResultsXsec._XSEC_OUTPUT_PATH not in hdf_file:
            return (
                f"Cannot extract 1D cross-section time series from {filename}: "
                "unsteady results exist but Cross Sections output is absent."
            )

        return (
            f"Missing required 1D cross-section result dataset in {filename}: "
            f"{dataset_path}"
        )



    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_ref_lines_timeseries(
        hdf_path: Path,
        variables: Optional[Union[str, Sequence[str]]] = None
    ) -> xr.Dataset:
        """
        Extract timeseries output data for reference lines from HEC-RAS HDF file.

        Parameters:
        -----------
        hdf_path : Path
            Path to the HEC-RAS results HDF file
        variables : str or sequence of str, optional
            HDF dataset names to include. If omitted, all numeric datasets with
            shape (time, reference_line) are returned.

        Returns:
        --------
        xr.Dataset
            Dataset containing numeric native HDF time-series data for reference lines.
            Returns empty dataset if reference line data not found.

        Raises:
        -------
        FileNotFoundError
            If the specified HDF file is not found
        KeyError
            If required datasets are missing from the HDF file
        """
        return HdfResultsXsec._reference_timeseries_output(
            hdf_path,
            reftype="lines",
            variables=variables,
        )

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_ref_points_timeseries(
        hdf_path: Path,
        variables: Optional[Union[str, Sequence[str]]] = None
    ) -> xr.Dataset:
        """
        Extract timeseries output data for reference points from HEC-RAS HDF file.

        This method extracts flow, velocity, and water surface elevation data for all
        reference points defined in the model. Reference points are user-defined locations
        where detailed output is desired.

        Parameters:
        -----------
        hdf_path : Path
            Path to the HEC-RAS results HDF file
        variables : str or sequence of str, optional
            HDF dataset names to include. If omitted, all numeric datasets with
            shape (time, reference_point) are returned.

        Returns:
        --------
        xr.Dataset
            Dataset containing numeric native HDF time-series variables for each
            reference point.
            
            The dataset includes coordinates:
            - time: Simulation timesteps
            - refpt_id: Unique identifier for each reference point
            - refpt_name: Name of each reference point
            - mesh_name: Associated 2D mesh area name
            
            Returns empty dataset if reference point data not found.

        Raises:
        -------
        FileNotFoundError
            If the specified HDF file is not found
        KeyError
            If required datasets are missing from the HDF file

        Examples:
        --------
        >>> ds = HdfResultsXsec.get_ref_points_timeseries("path/to/plan.hdf")
        >>> # Get water surface timeseries for first reference point
        >>> ws = ds['Water Surface'].isel(refpt_id=0)
        >>> # Get all data for a specific reference point by name
        >>> point_data = ds.sel(refpt_name='Point1')
        """
        return HdfResultsXsec._reference_timeseries_output(
            hdf_path,
            reftype="points",
            variables=variables,
        )
    

    @staticmethod
    def _reference_timeseries_output(
        hdf_file: Union[h5py.File, Path],
        reftype: str = "lines",
        variables: Optional[Union[str, Sequence[str]]] = None
    ) -> xr.Dataset:
        """
        Internal method to return timeseries output data for reference lines or points from a HEC-RAS HDF plan file.

        Parameters
        ----------
        hdf_file : h5py.File
            Open HDF file object.
        reftype : str, optional
            The type of reference data to retrieve. Must be either "lines" or "points".
            (default: "lines")
        variables : str or sequence of str, optional
            HDF dataset names to include. If omitted, all matching numeric
            time-series datasets are returned.

        Returns
        -------
        xr.Dataset
            An xarray Dataset with reference line or point timeseries data.
            Returns an empty Dataset if the reference output data is not found.

        Raises
        ------
        ValueError
            If reftype is not "lines" or "points".
        """
        if reftype == "lines":
            output_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Reference Lines"
            abbrev = "refln"
            ref_label = "line"
        elif reftype == "points":
            output_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Reference Points"
            abbrev = "refpt"
            ref_label = "point"
        else:
            raise ValueError('reftype must be either "lines" or "points".')

        filename = HdfResultsXsec._hdf_filename(hdf_file)
        should_close = not isinstance(hdf_file, h5py.File)
        if should_close:
            hdf_file = h5py.File(hdf_file, "r")
            filename = HdfResultsXsec._hdf_filename(hdf_file)

        variable_filter = HdfResultsXsec._normalize_reference_variable_filter(variables)

        try:
            try:
                reference_group = hdf_file[output_path]
            except KeyError:
                logger.debug(
                    "Reference %s time-series group not found in %s; returning empty Dataset.",
                    ref_label,
                    filename,
                )
                return xr.Dataset()

            if "Name" not in reference_group:
                message = (
                    f"Reference {ref_label} time-series group in {filename} is missing "
                    "required dataset 'Name'; cannot build feature coordinates."
                )
                logger.error("%s", message)
                raise KeyError(message)

            if HdfResultsXsec._TIME_STAMP_PATH not in hdf_file:
                message = (
                    f"Reference {ref_label} time-series group in {filename} exists but "
                    "unsteady timestamps are missing; this appears to be incomplete "
                    "or minimal results output."
                )
                logger.error("%s", message)
                raise KeyError(message)

            reference_names = reference_group["Name"][:]
            names = []
            mesh_areas = []
            for s in reference_names:
                name, mesh_area = HdfResultsXsec._decode_reference_name_mesh(s)
                names.append(name)
                mesh_areas.append(mesh_area)

            times = HdfBase.get_unsteady_timestamps(hdf_file)
            feature_count = len(names)
            expected_shape = (len(times), feature_count)

            das = {}
            for var, dataset in reference_group.items():
                if variable_filter is not None and var not in variable_filter:
                    continue
                if not HdfResultsXsec._is_reference_timeseries_dataset(
                    var,
                    dataset,
                    expected_shape,
                ):
                    continue

                values = dataset[:]
                units = HdfResultsXsec._decode_reference_attr(
                    dataset.attrs.get("Units", "")
                )
                da = xr.DataArray(
                    values,
                    name=var,
                    dims=["time", f"{abbrev}_id"],
                    coords={
                        "time": times,
                        f"{abbrev}_id": range(values.shape[1]),
                        f"{abbrev}_name": (f"{abbrev}_id", names),
                        "mesh_name": (f"{abbrev}_id", mesh_areas),
                    },
                    attrs={"units": units, "hdf_path": f"{output_path}/{var}"},
                )
                das[var] = da
            if not das:
                logger.debug(
                    "Reference %s group found in %s, but no numeric datasets matched "
                    "expected shape %s; returning empty Dataset.",
                    ref_label,
                    filename,
                    expected_shape,
                )
            return xr.Dataset(das)
        finally:
            if should_close:
                hdf_file.close()

    @staticmethod
    def _hdf_filename(hdf_file: Union[h5py.File, Path]) -> str:
        """Return a display-safe filename for an HDF file object or path."""
        if isinstance(hdf_file, h5py.File):
            return Path(hdf_file.filename).name
        return Path(hdf_file).name

    @staticmethod
    def _normalize_reference_variable_filter(
        variables: Optional[Union[str, Sequence[str]]]
    ) -> Optional[set]:
        """Normalize an optional reference output variable filter."""
        if variables is None:
            return None
        if isinstance(variables, str):
            return {variables}
        return set(variables)

    @staticmethod
    def _is_reference_timeseries_dataset(
        name: str,
        dataset: h5py.Dataset,
        expected_shape: Tuple[int, int],
    ) -> bool:
        """Return True for numeric reference feature time-series datasets."""
        if not isinstance(dataset, h5py.Dataset):
            return False

        lower_name = name.lower()
        if (
            lower_name == "name"
            or "unit" in lower_name
            or "index" in lower_name
            or "string" in lower_name
        ):
            return False

        if dataset.shape != expected_shape:
            return False

        try:
            return np.issubdtype(dataset.dtype, np.number)
        except TypeError:
            return False

    @staticmethod
    def _decode_reference_attr(value: object) -> str:
        """Decode optional HDF string attributes to plain strings."""
        if isinstance(value, (bytes, np.bytes_)):
            return value.decode("utf-8")
        if isinstance(value, np.ndarray):
            if value.size == 0:
                return ""
            return HdfResultsXsec._decode_reference_attr(value.flat[0])
        return str(value) if value is not None else ""

    @staticmethod
    def _decode_reference_name_mesh(value: object) -> Tuple[str, str]:
        """Decode a reference feature name and optional mesh suffix."""
        text = HdfResultsXsec._decode_reference_attr(value).strip()
        if "|" not in text:
            return text, ""
        name, mesh_area = text.split("|", 1)
        return name.strip(), mesh_area.strip()
