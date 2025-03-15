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
from typing import Union, Optional, List, Dict, Tuple

import h5py
import numpy as np
import pandas as pd
import xarray as xr

from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .Decorators import standardize_input, log_call
from .LoggingConfig import get_logger

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
                base_output_path = "/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections/"
                time_stamp_path = "/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp (ms)"
                
                # Extract Cross Section Attributes
                attrs_dataset = hdf_file[f"{base_output_path}Cross Section Attributes"][:]
                rivers = [attr['River'].decode('utf-8').strip() for attr in attrs_dataset]
                reaches = [attr['Reach'].decode('utf-8').strip() for attr in attrs_dataset]
                stations = [attr['Station'].decode('utf-8').strip() for attr in attrs_dataset]
                names = [attr['Name'].decode('utf-8').strip() for attr in attrs_dataset]
                
                # Extract Cross Section Only (Unique Names)
                cross_section_only_dataset = hdf_file[f"{base_output_path}Cross Section Only"][:]
                cross_section_names = [cs.decode('utf-8').strip() for cs in cross_section_only_dataset]
                
                # Extract Time Stamps and convert to datetime
                time_stamps = hdf_file[time_stamp_path][:]
                if any(isinstance(ts, bytes) for ts in time_stamps):
                    time_stamps = [ts.decode('utf-8') for ts in time_stamps]
                # Convert RAS format timestamps to datetime
                times = pd.to_datetime(time_stamps, format='%d%b%Y %H:%M:%S:%f')
                
                # Extract Required Datasets
                water_surface = hdf_file[f"{base_output_path}Water Surface"][:]
                velocity_total = hdf_file[f"{base_output_path}Velocity Total"][:]
                velocity_channel = hdf_file[f"{base_output_path}Velocity Channel"][:]
                flow_lateral = hdf_file[f"{base_output_path}Flow Lateral"][:]
                flow = hdf_file[f"{base_output_path}Flow"][:]
                
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
                        'source_file': str(hdf_path)
                    }
                )
                
                return ds

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting cross section results: {e}")
            raise



    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_ref_lines_timeseries(hdf_path: Path) -> xr.Dataset:
        """
        Extract timeseries output data for reference lines from HEC-RAS HDF file.

        Parameters:
        -----------
        hdf_path : Path
            Path to the HEC-RAS results HDF file

        Returns:
        --------
        xr.Dataset
            Dataset containing flow, velocity, and water surface data for reference lines.
            Returns empty dataset if reference line data not found.

        Raises:
        -------
        FileNotFoundError
            If the specified HDF file is not found
        KeyError
            If required datasets are missing from the HDF file
        """
        return HdfResultsXsec._reference_timeseries_output(hdf_path, reftype="lines")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_ref_points_timeseries(hdf_path: Path) -> xr.Dataset:
        """
        Extract timeseries output data for reference points from HEC-RAS HDF file.

        This method extracts flow, velocity, and water surface elevation data for all
        reference points defined in the model. Reference points are user-defined locations
        where detailed output is desired.

        Parameters:
        -----------
        hdf_path : Path
            Path to the HEC-RAS results HDF file

        Returns:
        --------
        xr.Dataset
            Dataset containing the following variables for each reference point:
            - Flow [cfs or m³/s]
            - Velocity [ft/s or m/s]
            - Water Surface [ft or m]
            
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
        return HdfResultsXsec._reference_timeseries_output(hdf_path, reftype="points")
    

    @staticmethod
    def _reference_timeseries_output(hdf_file: h5py.File, reftype: str = "lines") -> xr.Dataset:
        """
        Internal method to return timeseries output data for reference lines or points from a HEC-RAS HDF plan file.

        Parameters
        ----------
        hdf_file : h5py.File
            Open HDF file object.
        reftype : str, optional
            The type of reference data to retrieve. Must be either "lines" or "points".
            (default: "lines")

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
        elif reftype == "points":
            output_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Reference Points"
            abbrev = "refpt"
        else:
            raise ValueError('reftype must be either "lines" or "points".')

        try:
            reference_group = hdf_file[output_path]
        except KeyError:
            logger.error(f"Could not find HDF group at path '{output_path}'. "
                         f"The Plan HDF file may not contain reference {reftype[:-1]} output data.")
            return xr.Dataset()

        reference_names = reference_group["Name"][:]
        names = []
        mesh_areas = []
        for s in reference_names:
            name, mesh_area = s.decode("utf-8").split("|")
            names.append(name)
            mesh_areas.append(mesh_area)

        times = HdfBase.get_unsteady_timestamps(hdf_file)

        das = {}
        for var in ["Flow", "Velocity", "Water Surface"]:
            group = reference_group.get(var)
            if group is None:
                continue
            values = group[:]
            units = group.attrs["Units"].decode("utf-8")
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
        return xr.Dataset(das)
