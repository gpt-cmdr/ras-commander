"""
Class: HdfResultsXsec

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""

import h5py
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Union, Optional, List
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .Decorators import standardize_input, log_call
from .LoggingConfig import setup_logging, get_logger
import xarray as xr

logger = get_logger(__name__)


class HdfResultsXsec:
    """
    A class for handling cross-section results from HEC-RAS HDF files.

    This class provides methods to extract and process steady flow simulation results
    for cross-sections, including water surface elevations, flow rates, energy grades,
    and additional parameters such as encroachment stations and velocities.

    The class relies on the HdfBase and HdfUtils classes for core HDF file operations
    and utility functions.

    Attributes:
        None

    Methods:
        steady_profile_xs_output: Extract steady profile cross-section output for a specified variable.
        cross_sections_wsel: Get water surface elevation data for cross-sections.
        cross_sections_flow: Get flow data for cross-sections.
        cross_sections_energy_grade: Get energy grade data for cross-sections.
        cross_sections_additional_enc_station_left: Get left encroachment station data for cross-sections.
        cross_sections_additional_enc_station_right: Get right encroachment station data for cross-sections.
        cross_sections_additional_area_total: Get total ineffective area data for cross-sections.
        cross_sections_additional_velocity_total: Get total velocity data for cross-sections.
    """

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def steady_profile_xs_output(hdf_path: Path, var: str, round_to: int = 2) -> pd.DataFrame:
        """
        Create a DataFrame from steady cross section results based on the specified variable.

        Parameters:
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.
        var : str
            The variable to extract from the steady cross section results.
        round_to : int, optional
            Number of decimal places to round the results to (default is 2).

        Returns:
        -------
        pd.DataFrame
            DataFrame containing the steady cross section results for the specified variable.
        """
        XS_STEADY_OUTPUT_ADDITIONAL = [
            "Additional Encroachment Station Left",
            "Additional Encroachment Station Right",
            "Additional Area Ineffective Total",
            "Additional Velocity Total",
        ]
                
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Determine the correct path based on the variable
                if var in XS_STEADY_OUTPUT_ADDITIONAL:
                    path = f"/Results/Steady/Cross Sections/Additional Output/{var}"
                else:
                    path = f"/Results/Steady/Cross Sections/{var}"
                
                # Check if the path exists in the HDF file
                if path not in hdf_file:
                    return pd.DataFrame()

                # Get the profile names
                profiles = HdfBase.steady_flow_names(hdf_path)
                
                # Extract the steady data
                steady_data = hdf_file[path]
                
                # Create a DataFrame with profiles as index
                df = pd.DataFrame(steady_data, index=profiles)
                
                # Transpose the DataFrame and round values
                df_t = df.T.copy()
                for p in profiles:
                    df_t[p] = df_t[p].apply(lambda x: round(x, round_to))

                return df_t
        except Exception as e:
            HdfUtils.logger.error(f"Failed to get steady profile cross section output: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def cross_sections_wsel(hdf_path: Path) -> pd.DataFrame:
        """
        Return the water surface elevation information for each 1D Cross Section.

        Parameters:
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.

        Returns:
        -------
        pd.DataFrame
            A DataFrame containing the water surface elevations for each cross section and event.
        """
        return HdfResultsXsec.steady_profile_xs_output(hdf_path, "Water Surface")

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def cross_sections_flow(hdf_path: Path) -> pd.DataFrame:
        """
        Return the Flow information for each 1D Cross Section.

        Parameters:
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.

        Returns:
        -------
        pd.DataFrame
            A DataFrame containing the flow for each cross section and event.
        """
        return HdfResultsXsec.steady_profile_xs_output(hdf_path, "Flow")

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def cross_sections_energy_grade(hdf_path: Path) -> pd.DataFrame:
        """
        Return the energy grade information for each 1D Cross Section.

        Parameters:
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.

        Returns:
        -------
        pd.DataFrame
            A DataFrame containing the energy grade for each cross section and event.
        """
        return HdfResultsXsec.steady_profile_xs_output(hdf_path, "Energy Grade")

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def cross_sections_additional_enc_station_left(hdf_path: Path) -> pd.DataFrame:
        """
        Return the left side encroachment information for a floodway plan hdf.

        Parameters:
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.

        Returns:
        -------
        pd.DataFrame
            A DataFrame containing the cross sections left side encroachment stations.
        """
        return HdfResultsXsec.steady_profile_xs_output(
            hdf_path, "Encroachment Station Left"
        )

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def cross_sections_additional_enc_station_right(hdf_path: Path) -> pd.DataFrame:
        """
        Return the right side encroachment information for a floodway plan hdf.

        Parameters:
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.

        Returns:
        -------
        pd.DataFrame
            A DataFrame containing the cross sections right side encroachment stations.
        """
        return HdfResultsXsec.steady_profile_xs_output(
            hdf_path, "Encroachment Station Right"
        )

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def cross_sections_additional_area_total(hdf_path: Path) -> pd.DataFrame:
        """
        Return the 1D cross section area for each profile.

        Parameters:
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.

        Returns:
        -------
        pd.DataFrame
            A DataFrame containing the wet area inside the cross sections.
        """
        return HdfResultsXsec.steady_profile_xs_output(hdf_path, "Area Ineffective Total")

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def cross_sections_additional_velocity_total(hdf_path: Path) -> pd.DataFrame:
        """
        Return the 1D cross section velocity for each profile.

        Parameters:
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.

        Returns:
        -------
        pd.DataFrame
            A DataFrame containing the velocity inside the cross sections.
        """
        return HdfResultsXsec.steady_profile_xs_output(hdf_path, "Velocity Total")

