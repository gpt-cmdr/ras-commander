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
Four HMS-validated methods are available for design storm hyetograph generation:

1. **StormGenerator** (Alternating Block Method):
   - Flexible peak positioning (0-100%)
   - Works with any DDF data source
   - Does NOT match HEC-HMS temporal patterns

2. **Atlas14Storm** (Official NOAA Atlas 14 Temporal Distributions):
   - Matches HEC-HMS "Specified Pattern" exactly (10^-6 precision)
   - Uses official NOAA Atlas 14 temporal distribution curves
   - Supports all 5 quartiles (First, Second, Third, Fourth, All Cases)
   - Supports multiple durations (6h, 12h, 24h, 96h)
   - Guaranteed exact depth conservation

3. **FrequencyStorm** (TP-40 Temporal Pattern):
   - Matches HEC-HMS "User Specified Pattern" exactly (10^-6 precision)
   - TP-40 pattern compatible (Houston area)
   - Supports variable durations (6hr to 48hr validated)
   - Guaranteed exact depth conservation

4. **ScsTypeStorm** (SCS Type I/IA/II/III Distributions):
   - Matches HEC-HMS SCS distributions exactly (10^-6 precision)
   - Extracted from HEC-HMS 4.13 source code
   - All 4 SCS types (I, IA, II, III)
   - Duration: 24-hour only (HMS constraint)
   - Guaranteed exact depth conservation

Choose StormGenerator for flexible peak positioning or non-HMS workflows.
Choose Atlas14Storm for HMS-equivalent workflows with official Atlas 14 patterns (supports 6h, 12h, 24h, 96h).
Choose FrequencyStorm for TP-40 workflows or when 48-hour duration is needed.
Choose ScsTypeStorm for SCS Type I/IA/II/III distributions (24-hour only).

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

Example (Atlas14Storm - HMS Equivalent, Atlas 14):
    >>> from ras_commander.precip import Atlas14Storm, ATLAS14_AVAILABLE
    >>>
    >>> if ATLAS14_AVAILABLE:
    >>>     # Generate 100-year, 24-hour storm for Houston, TX
    >>>     hyeto = Atlas14Storm.generate_hyetograph(
    ...         total_depth_inches=17.9,
    ...         state="tx",
    ...         region=3,
    ...         aep_percent=1.0
    ...     )
    >>>     print(f"Total depth: {hyeto.sum():.6f} inches")  # Exact: 17.900000

Example (FrequencyStorm - HMS Equivalent, TP-40):
    >>> from ras_commander.precip import FrequencyStorm, FREQUENCY_STORM_AVAILABLE
    >>>
    >>> if FREQUENCY_STORM_AVAILABLE:
    >>>     # Generate TP-40 storm (24hr, 5-min, 67% peak - Houston defaults)
    >>>     hyeto = FrequencyStorm.generate_hyetograph(total_depth=13.20)
    >>>     print(f"Generated {len(hyeto)} intervals")  # 289 intervals

Example (ScsTypeStorm - HMS Equivalent, SCS Type II):
    >>> from ras_commander.precip import ScsTypeStorm, SCS_TYPE_AVAILABLE
    >>>
    >>> if SCS_TYPE_AVAILABLE:
    >>>     # Generate SCS Type II storm (most common)
    >>>     hyeto = ScsTypeStorm.generate_hyetograph(
    ...         total_depth_inches=10.0,
    ...         scs_type='II',
    ...         time_interval_min=60
    ...     )
    >>>     print(f"Total depth: {hyeto.sum():.6f} inches")  # Exact: 10.000000

Example (StormGenerator - Alternating Block):
    >>> from ras_commander.precip import StormGenerator
    >>>
    >>> # Download DDF data (returns DataFrame)
    >>> ddf = StormGenerator.download_from_coordinates(38.9, -77.0)
    >>> # Generate hyetograph using static method
    >>> hyeto = StormGenerator.generate_hyetograph(ddf, total_depth_inches=10.0, duration_hours=24, position_percent=50)

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

# Import from hms-commander (HMS-equivalent hyetograph generation)
try:
    from hms_commander import Atlas14Storm, Atlas14Config, FrequencyStorm, ScsTypeStorm
    ATLAS14_AVAILABLE = True
    FREQUENCY_STORM_AVAILABLE = True
    SCS_TYPE_AVAILABLE = True
except ImportError:
    # hms-commander not installed - HMS-equivalent features not available
    ATLAS14_AVAILABLE = False
    FREQUENCY_STORM_AVAILABLE = False
    SCS_TYPE_AVAILABLE = False
    Atlas14Storm = None
    Atlas14Config = None
    FrequencyStorm = None
    ScsTypeStorm = None

__all__ = [
    'PrecipAorc',
    'StormGenerator',
    'Atlas14Grid',                 # Remote access to NOAA Atlas 14 CONUS grids
    'Atlas14Variance',             # Spatial variance analysis for precipitation
    'Atlas14Storm',                # HMS-equivalent Atlas 14 hyetograph generation
    'Atlas14Config',               # Configuration dataclass for Atlas14Storm
    'FrequencyStorm',              # HMS-equivalent TP-40 hyetograph generation
    'ScsTypeStorm',                # HMS-equivalent SCS Type I/IA/II/III hyetograph generation
    'ATLAS14_AVAILABLE',           # Boolean flag indicating if Atlas14Storm is available
    'FREQUENCY_STORM_AVAILABLE',   # Boolean flag indicating if FrequencyStorm is available
    'SCS_TYPE_AVAILABLE',          # Boolean flag indicating if ScsTypeStorm is available
]
