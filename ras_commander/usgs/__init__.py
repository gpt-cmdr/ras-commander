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
    >>> # Cache the data
    >>> path = cache_gauge_data(flow_df, "08074500", "2017-08-25",
    ...                          "2017-09-02", "flow", "C:/models/my_project")
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

# Import metrics functions
from .metrics import (
    nash_sutcliffe_efficiency,
    kling_gupta_efficiency,
    calculate_peak_error,
    calculate_volume_error,
    classify_performance,
    calculate_all_metrics
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

# Define what gets imported with "from ras_commander.usgs import *"
__all__ = [
    # Classes
    'RasUsgsCore',
    'UsgsGaugeSpatial',
    'RasUsgsFileIo',
    'InitialConditions',
    'GaugeMatcher',
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
]
