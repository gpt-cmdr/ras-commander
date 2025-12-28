"""
ras-commander precipitation subpackage: Gridded precipitation data access.

This subpackage provides tools to download and prepare gridded precipitation data
from various sources for use in HEC-RAS rain-on-grid 2D models:

- AORC (Analysis of Record for Calibration) - Historical reanalysis 1979-present
- Atlas 14 (NOAA) - Design storm generation with HMS-equivalent temporal distributions
- Atlas14Grid - Spatially distributed PFE grids with remote access (HTTP range requests)
- Atlas14Variance - Spatial variance analysis for uniform vs. distributed rainfall decisions
- MRMS (Multi-Radar Multi-Sensor) - Real-time and historical radar (future)
- QPF (Quantitative Precipitation Forecast) - NWS forecasts (future)

The primary workflow is:
1. Extract project extent from HEC-RAS HDF file using HdfProject
2. Download precipitation data for the extent and time period
3. Export as NetCDF for direct import into HEC-RAS

Design Storm Generation:
Two methods are available for design storm hyetograph generation:

1. **StormGenerator** (Alternating Block Method):
   - Flexible peak positioning (0-100%)
   - Works with any DDF data source
   - Does NOT match HEC-HMS temporal patterns

2. **Atlas14Storm** (Official NOAA Temporal Distributions):
   - Matches HEC-HMS "Specified Pattern" exactly (10^-6 precision)
   - Uses official NOAA Atlas 14 temporal distribution curves
   - Supports all 5 quartiles (First, Second, Third, Fourth, All Cases)
   - Guaranteed exact depth conservation

Choose StormGenerator for flexible peak positioning or non-HMS workflows.
Choose Atlas14Storm for HMS-equivalent workflows or official Atlas 14 patterns.

Spatial Variance Analysis:
Atlas14Grid and Atlas14Variance provide tools to assess whether uniform rainfall
assumptions are valid for a HEC-RAS model domain:

3. **Atlas14Grid** (Gridded PFE Access):
   - Remote access to NOAA CONUS NetCDF via HTTP range requests
   - Downloads only data within project extent (99.9% data reduction)
   - Integrates with HEC-RAS 2D flow areas for automatic extent detection

4. **Atlas14Variance** (Variance Analysis):
   - Calculate min/max/mean/range statistics within model domain
   - Assess whether uniform rainfall is appropriate
   - Generate reports and visualizations

Example (Atlas14Storm - HMS Equivalent):
    >>> from ras_commander.precip import Atlas14Storm
    >>>
    >>> # Generate 100-year, 24-hour storm for Houston, TX
    >>> hyeto = Atlas14Storm.generate_hyetograph(
    ...     total_depth_inches=17.9,
    ...     state="tx",
    ...     region=3,
    ...     aep_percent=1.0
    ... )
    >>> print(f"Total depth: {hyeto.sum():.6f} inches")  # Exact: 17.900000

Example (StormGenerator - Alternating Block):
    >>> from ras_commander.precip import StormGenerator
    >>>
    >>> gen = StormGenerator.download_from_coordinates(38.9, -77.0)
    >>> hyeto = gen.generate_hyetograph(ari=100, duration_hours=24, position_percent=50)

Example (Atlas14Grid - Spatial PFE):
    >>> from ras_commander.precip import Atlas14Grid
    >>>
    >>> # Get precipitation frequency for HEC-RAS project extent
    >>> pfe = Atlas14Grid.get_pfe_from_project(
    ...     geom_hdf="MyProject.g01.hdf",
    ...     extent_source="2d_flow_area",
    ...     durations=[6, 12, 24],
    ...     return_periods=[10, 50, 100]
    ... )

Example (Atlas14Variance - Assess Uniformity):
    >>> from ras_commander.precip import Atlas14Variance
    >>>
    >>> # Check if uniform rainfall is appropriate (using 2D flow area)
    >>> results = Atlas14Variance.analyze("MyProject.g01.hdf")
    >>> ok, msg = Atlas14Variance.is_uniform_rainfall_appropriate(results)
    >>> print(msg)
    >>>
    >>> # Or analyze using HUC12 watershed boundary
    >>> results = Atlas14Variance.analyze(
    ...     "MyProject.g01.hdf",
    ...     use_huc12_boundary=True
    ... )

Example (AORC - Historical Data):
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
    - fsspec>=2023.0.0 (for Atlas14Grid remote access)
    - h5py>=3.0.0 (for Atlas14Grid)
    - geopandas>=0.12.0 (for Atlas14Variance)
    - pygeohydro (optional, for HUC12 watershed boundaries in Atlas14Variance)
"""

from .PrecipAorc import PrecipAorc
from .StormGenerator import StormGenerator
from .Atlas14Grid import Atlas14Grid
from .Atlas14Variance import Atlas14Variance

# Import Atlas14Storm from hms-commander (HMS-equivalent temporal distributions)
try:
    from hms_commander import Atlas14Storm, Atlas14Config
    ATLAS14_AVAILABLE = True
except ImportError:
    # hms-commander not installed - Atlas14Storm not available
    ATLAS14_AVAILABLE = False
    Atlas14Storm = None
    Atlas14Config = None

__all__ = [
    'PrecipAorc',
    'StormGenerator',
    'Atlas14Grid',       # Remote access to NOAA Atlas 14 CONUS grids
    'Atlas14Variance',   # Spatial variance analysis for precipitation
    'Atlas14Storm',      # HMS-equivalent Atlas 14 hyetograph generation
    'Atlas14Config',     # Configuration dataclass for Atlas14Storm
    'ATLAS14_AVAILABLE', # Boolean flag indicating if Atlas14Storm is available
]
