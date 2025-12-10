"""
ras-commander precipitation subpackage: Gridded precipitation data access.

This subpackage provides tools to download and prepare gridded precipitation data
from various sources for use in HEC-RAS rain-on-grid 2D models:

- AORC (Analysis of Record for Calibration) - Historical reanalysis 1979-present
- MRMS (Multi-Radar Multi-Sensor) - Real-time and historical radar (future)
- QPF (Quantitative Precipitation Forecast) - NWS forecasts (future)

The primary workflow is:
1. Extract project extent from HEC-RAS HDF file using HdfProject
2. Download precipitation data for the extent and time period
3. Export as NetCDF for direct import into HEC-RAS

Example:
    >>> from ras_commander import HdfProject
    >>> from ras_commander.precip import PrecipAorc
    >>>
    >>> # Get project bounds in lat/lon
    >>> west, south, east, north = HdfProject.get_project_bounds_latlon(
    ...     "project.g01.hdf",
    ...     buffer_percent=50.0
    ... )
    >>>
    >>> # Download AORC precipitation
    >>> output_path = PrecipAorc.download(
    ...     bounds=(west, south, east, north),
    ...     start_time="2018-09-01",
    ...     end_time="2018-09-03",
    ...     output_path="Precipitation/aorc_precip.nc"
    ... )

Dependencies:
    Install with: pip install ras-commander[precip]

    Required packages:
    - xarray>=2023.0.0
    - zarr>=2.14.0
    - s3fs>=2023.0.0
    - netCDF4>=1.6.0
"""

from .PrecipAorc import PrecipAorc
from .StormGenerator import StormGenerator

__all__ = ['PrecipAorc', 'StormGenerator']
