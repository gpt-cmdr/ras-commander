"""
ras_commander.usgs - USGS Gauge Data Integration for HEC-RAS

This subpackage provides tools for integrating USGS gauge data with HEC-RAS models,
including data retrieval, boundary condition generation, initial condition setting,
model validation, and performance metrics.

Modules:
    core: USGS data retrieval from NWIS (flow, stage, metadata)
    spatial: Spatial queries for USGS gauge discovery
    file_io: File management and caching for gauge data
    visualization: Comparison plots for model validation
    metrics: Statistical metrics for model validation (NSE, KGE, RMSE, etc.)
    real_time: Real-time monitoring and operational forecasting
    catalog: Gauge catalog generation and management

Public API:
    From core:
        - retrieve_flow_data: Retrieve flow time series from USGS
        - retrieve_stage_data: Retrieve stage time series from USGS
        - get_gauge_metadata: Get gauge metadata (location, drainage area)
        - check_data_availability: Check if data exists for period

    From spatial:
        - find_gauges_in_project: Query USGS gauges within project bounds
        - get_project_gauges_with_data: Find gauges with data for period

    From file_io:
        - get_gauge_data_dir: Get/create gauge_data directory structure
        - cache_gauge_data: Save USGS data to cache
        - load_cached_gauge_data: Load cached USGS data
        - get_cache_filename: Generate standardized filename
        - save_validation_results: Save validation metrics

    From visualization:
        - plot_timeseries_comparison: Main comparison plot (observed vs modeled)
        - plot_scatter_comparison: Scatter plot with 1:1 line
        - plot_residuals: 4-panel residual diagnostics
        - plot_hydrograph: Simple single time series plot

    From metrics:
        - nash_sutcliffe_efficiency: Calculate NSE metric
        - kling_gupta_efficiency: Calculate KGE metric and components
        - calculate_peak_error: Peak value and timing comparison
        - calculate_volume_error: Total volume comparison
        - classify_performance: Classify model performance rating
        - calculate_all_metrics: Comprehensive metric calculation

    From real_time:
        - get_latest_value: Get most recent gauge reading
        - get_recent_data: Get last N hours of data
        - refresh_data: Incrementally update cached data
        - monitor_gauge: Continuous monitoring with callbacks
        - detect_threshold_crossing: Detect threshold exceedance
        - detect_rapid_change: Detect rapid rises/recessions

    From catalog:
        - generate_gauge_catalog: Create standardized gauge data catalog
        - load_gauge_catalog: Load gauge catalog from standard location
        - load_gauge_data: Load historical data for specific gauge
        - get_gauge_folder: Get path to gauge folder
        - update_gauge_catalog: Refresh existing catalog with new data

Example:
    >>> from ras_commander.usgs import retrieve_flow_data, get_gauge_metadata
    >>>
    >>> # Get gauge information
    >>> metadata = get_gauge_metadata("08074500")
    >>> print(f"Station: {metadata['station_name']}")
    >>>
    >>> # Retrieve flow data for Hurricane Harvey
    >>> flow_df = retrieve_flow_data(
    ...     site_id="08074500",
    ...     start_datetime="2017-08-25",
    ...     end_datetime="2017-09-02",
    ...     data_type='iv'
    ... )
    >>> print(f"Peak flow: {flow_df['value'].max():.0f} cfs")
    >>>
    >>> # Real-time monitoring
    >>> from ras_commander.usgs import get_latest_value
    >>> latest = get_latest_value("08074500", parameter='flow')
    >>> print(f"Current flow: {latest['value']:.0f} cfs ({latest['age_minutes']:.1f} min old)")
"""

# Import and expose public API from core module
from .core import (
    RasUsgsCore,
)

# Import and expose public API from spatial module
from .spatial import (
    UsgsGaugeSpatial,
    find_gauges_in_project,
    get_project_gauges_with_data
)

# Import and expose public API from file_io module
from .file_io import (
    RasUsgsFileIo,
)

# Import visualization functions
from .visualization import (
    plot_timeseries_comparison,
    plot_scatter_comparison,
    plot_residuals,
    plot_hydrograph
)

# Import initial conditions management
from .initial_conditions import (
    InitialConditions,
)

# Import gauge matching functions
from .gauge_matching import (
    GaugeMatcher,
    transform_gauge_coords,
    match_gauge_to_cross_section,
    match_gauge_to_2d_area,
    auto_match_gauges
)

# Import boundary generation functions
from .boundary_generation import (
    BoundaryGenerator,
)

# Import time series processing functions
from .time_series import (
    TimeSeriesProcessor,
)

# Import metrics functions
from .metrics import (
    nash_sutcliffe_efficiency,
    kling_gupta_efficiency,
    calculate_peak_error,
    calculate_volume_error,
    classify_performance,
    calculate_all_metrics
)

# Import real-time monitoring functions
from .real_time import (
    RasUsgsRealTime,
)

# Import catalog functions
from .catalog import (
    generate_gauge_catalog,
    load_gauge_catalog,
    load_gauge_data,
    get_gauge_folder,
    update_gauge_catalog
)

# Import rate limiting utilities
from .rate_limiter import (
    UsgsRateLimiter,
    retry_with_backoff,
    configure_api_key,
    check_api_key,
    get_rate_limit_info
)

# Expose static methods directly at package level for convenience
# From core module
retrieve_flow_data = RasUsgsCore.retrieve_flow_data
retrieve_stage_data = RasUsgsCore.retrieve_stage_data
get_gauge_metadata = RasUsgsCore.get_gauge_metadata
check_data_availability = RasUsgsCore.check_data_availability

# From file_io module
get_gauge_data_dir = RasUsgsFileIo.get_gauge_data_dir
cache_gauge_data = RasUsgsFileIo.cache_gauge_data
load_cached_gauge_data = RasUsgsFileIo.load_cached_gauge_data
get_cache_filename = RasUsgsFileIo.get_cache_filename
save_validation_results = RasUsgsFileIo.save_validation_results

# From real_time module
get_latest_value = RasUsgsRealTime.get_latest_value
get_recent_data = RasUsgsRealTime.get_recent_data
refresh_data = RasUsgsRealTime.refresh_data
monitor_gauge = RasUsgsRealTime.monitor_gauge
detect_threshold_crossing = RasUsgsRealTime.detect_threshold_crossing
detect_rapid_change = RasUsgsRealTime.detect_rapid_change

# From boundary_generation module
generate_flow_hydrograph_table = BoundaryGenerator.generate_flow_hydrograph_table
generate_stage_hydrograph_table = BoundaryGenerator.generate_stage_hydrograph_table
update_boundary_hydrograph = BoundaryGenerator.update_boundary_hydrograph

# From time_series module
align_timeseries = TimeSeriesProcessor.align_timeseries
resample_to_hecras_interval = TimeSeriesProcessor.resample_to_hecras_interval
check_data_gaps = TimeSeriesProcessor.check_data_gaps

def check_dependencies():
    """
    Check if optional dependencies for USGS module are installed.

    Returns:
        dict: Dictionary with dependency names as keys and availability as boolean values.

    Example:
        >>> from ras_commander.usgs import check_dependencies
        >>> deps = check_dependencies()
        >>> if deps['dataretrieval']:
        ...     print("Ready to retrieve USGS data")
    """
    deps = {}

    # Check dataretrieval (required for USGS NWIS data)
    try:
        import dataretrieval
        deps['dataretrieval'] = True
    except ImportError:
        deps['dataretrieval'] = False

    # Check geopandas (required for spatial queries)
    try:
        import geopandas
        deps['geopandas'] = True
    except ImportError:
        deps['geopandas'] = False

    # Check pyproj (required for coordinate transforms)
    try:
        import pyproj
        deps['pyproj'] = True
    except ImportError:
        deps['pyproj'] = False

    # Check matplotlib (required for visualization)
    try:
        import matplotlib
        deps['matplotlib'] = True
    except ImportError:
        deps['matplotlib'] = False

    return deps


# Define what gets imported with "from ras_commander.usgs import *"
__all__ = [
    # Classes
    'RasUsgsCore',
    'UsgsGaugeSpatial',
    'RasUsgsFileIo',
    'InitialConditions',
    'GaugeMatcher',
    'RasUsgsRealTime',
    # Core data retrieval functions
    'retrieve_flow_data',
    'retrieve_stage_data',
    'get_gauge_metadata',
    'check_data_availability',
    # Spatial query functions
    'find_gauges_in_project',
    'get_project_gauges_with_data',
    # File I/O functions
    'get_gauge_data_dir',
    'cache_gauge_data',
    'load_cached_gauge_data',
    'get_cache_filename',
    'save_validation_results',
    # Gauge matching functions
    'transform_gauge_coords',
    'match_gauge_to_cross_section',
    'match_gauge_to_2d_area',
    'auto_match_gauges',
    # Visualization functions
    'plot_timeseries_comparison',
    'plot_scatter_comparison',
    'plot_residuals',
    'plot_hydrograph',
    # Metrics functions
    'nash_sutcliffe_efficiency',
    'kling_gupta_efficiency',
    'calculate_peak_error',
    'calculate_volume_error',
    'classify_performance',
    'calculate_all_metrics',
    # Real-time monitoring functions
    'get_latest_value',
    'get_recent_data',
    'refresh_data',
    'monitor_gauge',
    'detect_threshold_crossing',
    'detect_rapid_change',
    # Boundary generation functions
    'BoundaryGenerator',
    'generate_flow_hydrograph_table',
    'generate_stage_hydrograph_table',
    'update_boundary_hydrograph',
    # Time series processing functions
    'TimeSeriesProcessor',
    'align_timeseries',
    'resample_to_hecras_interval',
    'check_data_gaps',
    # Catalog functions
    'generate_gauge_catalog',
    'load_gauge_catalog',
    'load_gauge_data',
    'get_gauge_folder',
    'update_gauge_catalog',
    # Rate limiting utilities
    'UsgsRateLimiter',
    'retry_with_backoff',
    'configure_api_key',
    'check_api_key',
    'get_rate_limit_info',
    # Utility functions
    'check_dependencies',
]
