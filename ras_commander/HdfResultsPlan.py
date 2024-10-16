"""
Class: HdfResultsPlan

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""

from typing import Dict, List, Union, Optional
from pathlib import Path
import h5py
import pandas as pd
import xarray as xr
from .Decorators import standardize_input, log_call
from .HdfBase import HdfBase
from .HdfResultsXsec import HdfResultsXsec
from .LoggingConfig import get_logger
import numpy as np
from datetime import datetime

logger = get_logger(__name__)


class HdfResultsPlan:
    """
    A class for handling HEC-RAS plan HDF file results related to unsteady flow and reference line/point outputs.

    This class provides methods for extracting and analyzing data from HEC-RAS plan HDF files,
    focusing on unsteady flow results, volume accounting, and reference line/point time series outputs.

    Methods in this class use the @standardize_input decorator to handle different input types
    (e.g., plan number, file path) and the @log_call decorator for logging method calls.

    Attributes:
        None

    Note:
        This class is designed to work with HEC-RAS plan HDF files and requires the HdfBase class
        for some of its operations.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_results_unsteady_attrs(hdf_path: Path) -> Dict:
        """
        Get unsteady attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: A dictionary containing the unsteady attributes.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            KeyError: If the "Results/Unsteady" group is not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady" not in hdf_file:
                    raise KeyError("Results/Unsteady group not found in the HDF file.")
                return dict(hdf_file["Results/Unsteady"].attrs)
        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading unsteady attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_results_unsteady_summary_attrs(hdf_path: Path) -> Dict:
        """
        Get results unsteady summary attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: A dictionary containing the results unsteady summary attributes.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            KeyError: If the "Results/Unsteady/Summary" group is not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady/Summary" not in hdf_file:
                    raise KeyError("Results/Unsteady/Summary group not found in the HDF file.")
                return dict(hdf_file["Results/Unsteady/Summary"].attrs)
        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading unsteady summary attributes: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_results_volume_accounting_attrs(hdf_path: Path) -> Dict:
        """
        Get volume accounting attributes from a HEC-RAS HDF plan file.

        Args:
            hdf_path (Path): Path to the HEC-RAS plan HDF file.

        Returns:
            Dict: A dictionary containing the volume accounting attributes.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            KeyError: If the "Results/Unsteady/Summary/Volume Accounting" group is not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Results/Unsteady/Summary/Volume Accounting" not in hdf_file:
                    raise KeyError("Results/Unsteady/Summary/Volume Accounting group not found in the HDF file.")
                return dict(hdf_file["Results/Unsteady/Summary/Volume Accounting"].attrs)
        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading volume accounting attributes: {str(e)}")

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_runtime_data(hdf_path: Path) -> Optional[pd.DataFrame]:
        """
        Extract runtime and compute time data from a single HDF file.

        Args:
            hdf_path (Path): The full path to the HDF file.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing runtime and compute time data, or None if data extraction fails.
        """
        if hdf_path is None:
            logger.error(f"Could not find HDF file for input")
            return None

        with h5py.File(hdf_path, 'r') as hdf_file:
            logger.info(f"Extracting Plan Information from: {Path(hdf_file.filename).name}")
            plan_info = hdf_file.get('/Plan Data/Plan Information')
            if plan_info is None:
                logger.warning("Group '/Plan Data/Plan Information' not found.")
                return None

            plan_name = plan_info.attrs.get('Plan Name', 'Unknown')
            plan_name = plan_name.decode('utf-8') if isinstance(plan_name, bytes) else plan_name
            logger.info(f"Plan Name: {plan_name}")

            start_time_str = plan_info.attrs.get('Simulation Start Time', 'Unknown')
            end_time_str = plan_info.attrs.get('Simulation End Time', 'Unknown')
            start_time_str = start_time_str.decode('utf-8') if isinstance(start_time_str, bytes) else start_time_str
            end_time_str = end_time_str.decode('utf-8') if isinstance(end_time_str, bytes) else end_time_str

            start_time = datetime.strptime(start_time_str, "%d%b%Y %H:%M:%S")
            end_time = datetime.strptime(end_time_str, "%d%b%Y %H:%M:%S")
            simulation_duration = end_time - start_time
            simulation_hours = simulation_duration.total_seconds() / 3600

            logger.info(f"Simulation Start Time: {start_time_str}")
            logger.info(f"Simulation End Time: {end_time_str}")
            logger.info(f"Simulation Duration (hours): {simulation_hours}")

            compute_processes = hdf_file.get('/Results/Summary/Compute Processes')
            if compute_processes is None:
                logger.warning("Dataset '/Results/Summary/Compute Processes' not found.")
                return None

            process_names = [name.decode('utf-8') for name in compute_processes['Process'][:]]
            filenames = [filename.decode('utf-8') for filename in compute_processes['Filename'][:]]
            completion_times = compute_processes['Compute Time (ms)'][:]

            compute_processes_df = pd.DataFrame({
                'Process': process_names,
                'Filename': filenames,
                'Compute Time (ms)': completion_times,
                'Compute Time (s)': completion_times / 1000,
                'Compute Time (hours)': completion_times / (1000 * 3600)
            })

            logger.debug("Compute processes DataFrame:")
            logger.debug(compute_processes_df)

            compute_processes_summary = {
                'Plan Name': [plan_name],
                'File Name': [Path(hdf_file.filename).name],
                'Simulation Start Time': [start_time_str],
                'Simulation End Time': [end_time_str],
                'Simulation Duration (s)': [simulation_duration.total_seconds()],
                'Simulation Time (hr)': [simulation_hours],
                'Completing Geometry (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Completing Geometry']['Compute Time (hours)'].values[0] if 'Completing Geometry' in compute_processes_df['Process'].values else 'N/A'],
                'Preprocessing Geometry (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Preprocessing Geometry']['Compute Time (hours)'].values[0] if 'Preprocessing Geometry' in compute_processes_df['Process'].values else 'N/A'],
                'Completing Event Conditions (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Completing Event Conditions']['Compute Time (hours)'].values[0] if 'Completing Event Conditions' in compute_processes_df['Process'].values else 'N/A'],
                'Unsteady Flow Computations (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Unsteady Flow Computations']['Compute Time (hours)'].values[0] if 'Unsteady Flow Computations' in compute_processes_df['Process'].values else 'N/A'],
                'Complete Process (hr)': [compute_processes_df['Compute Time (hours)'].sum()]
            }

            compute_processes_summary['Unsteady Flow Speed (hr/hr)'] = [simulation_hours / compute_processes_summary['Unsteady Flow Computations (hr)'][0] if compute_processes_summary['Unsteady Flow Computations (hr)'][0] != 'N/A' else 'N/A']
            compute_processes_summary['Complete Process Speed (hr/hr)'] = [simulation_hours / compute_processes_summary['Complete Process (hr)'][0] if compute_processes_summary['Complete Process (hr)'][0] != 'N/A' else 'N/A']

            compute_summary_df = pd.DataFrame(compute_processes_summary)
            logger.debug("Compute summary DataFrame:")
            logger.debug(compute_summary_df)

            return compute_summary_df



    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def reference_timeseries_output(hdf_path: Path, reftype: str = "lines") -> xr.Dataset:
        """
        Get timeseries output for reference lines or points.

        Args:
            hdf_path (Path): Path to the HDF file.
            reftype (str): Type of reference, either "lines" or "points" (default "lines").

        Returns:
            xr.Dataset: Dataset containing the timeseries output for reference lines or points.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
            ValueError: If an invalid reftype is provided.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsPlan._reference_timeseries_output(hdf_file, reftype)
        except FileNotFoundError:
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")
        except ValueError as ve:
            raise ValueError(f"Invalid reftype: {str(ve)}")
        except Exception as e:
            raise RuntimeError(f"Error getting reference timeseries output: {str(e)}")


    @staticmethod
    def _reference_timeseries_output(hdf_file: h5py.File, reftype: str = "lines") -> xr.Dataset:
        """
        Private method to return timeseries output data for reference lines or points from a HEC-RAS HDF plan file.

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

        times = HdfBase._get_unsteady_datetimes(hdf_file)

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

        


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def reference_lines_timeseries_output(hdf_path: Path) -> xr.Dataset:
        """
        Get timeseries output for reference lines.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            xr.Dataset: Dataset containing the timeseries output for reference lines.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
        """
        return HdfResultsPlan.reference_timeseries_output(hdf_path, reftype="lines")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def reference_points_timeseries_output(hdf_path: Path) -> xr.Dataset:
        """
        Get timeseries output for reference points.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            xr.Dataset: Dataset containing the timeseries output for reference points.

        Raises:
            FileNotFoundError: If the specified HDF file is not found.
        """
        return HdfResultsPlan.reference_timeseries_output(hdf_path, reftype="points")
    
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def reference_summary_output(hdf_path: Path, reftype: str = "lines") -> pd.DataFrame:
        """
        Get summary output for reference lines or points.

        Args:
            hdf_path (Path): Path to the HDF file.
            reftype (str): Type of reference, either "lines" or "points" (default "lines").

        Returns:
            pd.DataFrame: DataFrame containing the summary output for reference lines or points.

        Raises:
            ValueError: If an invalid reftype is provided.
        """
        if not hdf_path.exists():
            logger.error(f"HDF file not found: {hdf_path}")
            return pd.DataFrame()  # Return an empty DataFrame if the path doesn't exist

        try:
            # Get the timeseries output
            ds = HdfResultsPlan.reference_timeseries_output(hdf_path, reftype)
            
            if 'station' not in ds.dims:
                logger.error("No 'station' dimension found in the dataset.")
                return pd.DataFrame()  # Return an empty DataFrame if 'station' dimension is missing
            
            # Calculate summary statistics
            summary = ds.groupby('station').agg({
                'WSE': ['min', 'max', 'mean'],
                'Q': ['min', 'max', 'mean']
            })
            
            # Flatten column names
            summary.columns = ['_'.join(col).strip() for col in summary.columns.values]
            
            # Reset index to make 'station' a column
            summary = summary.reset_index()
            
            return summary
        except ValueError as ve:
            logger.error(f"Invalid reftype: {str(ve)}")
            return pd.DataFrame()  # Return an empty DataFrame on ValueError
        except Exception as e:
            logger.error(f"Error in reference_summary_output: {str(e)}")
            return pd.DataFrame()  # Return an empty DataFrame on general error
