"""
Configuration constants for USGS gauge data integration.

This module defines constants for:
- USGS parameter and statistic codes
- HEC-RAS interval formats and table types
- Initial condition (IC) line prefixes
- Fixed-width format specifications
- Gauge data directory structure
- Performance classification thresholds
- Match quality thresholds

All constants are based on:
- USGS Water Data API documentation
- HEC-RAS unsteady flow file format specifications
- Moriasi et al. (2007) model evaluation guidelines
"""

from typing import Dict


# ============================================================================
# USGS Parameter Codes
# ============================================================================

USGS_PARAMETERS: Dict[str, str] = {
    'flow': '00060',          # Discharge (ft³/s)
    'stage': '00065',         # Gage height (ft)
    'velocity': '00055',      # Stream velocity (ft/s)
    'temperature': '00010',   # Water temperature (°C)
}
"""
USGS parameter codes for data retrieval.

These codes identify specific measurement types in the USGS Water Data API.
All retrievals use these standardized codes.

References:
    - USGS parameter codes: https://help.waterdata.usgs.gov/codes-and-parameters/parameters
    - dataretrieval-python documentation
"""


# ============================================================================
# USGS Statistic Codes
# ============================================================================

USGS_STATISTICS: Dict[str, str] = {
    'maximum': '00001',       # Daily maximum
    'minimum': '00002',       # Daily minimum
    'mean': '00003',          # Daily mean
    'instantaneous': '00011', # Instantaneous value
}
"""
USGS statistic codes for aggregated data.

Statistic codes define how data is aggregated when multiple measurements exist.
Typically used with daily values or for specifying which instantaneous values to retrieve.

Common Usage:
    - 'instantaneous': Use for real-time or continuous data retrieval
    - 'mean': Use for daily average values
    - 'maximum': Use for peak flow/stage identification
"""


# ============================================================================
# HEC-RAS Time Intervals
# ============================================================================

HECRAS_INTERVALS: Dict[str, str] = {
    '1MIN': '1T',
    '5MIN': '5T',
    '10MIN': '10T',
    '15MIN': '15T',
    '30MIN': '30T',
    '1HOUR': '1H',
    '2HOUR': '2H',
    '3HOUR': '3H',
    '4HOUR': '4H',
    '6HOUR': '6H',
    '8HOUR': '8H',
    '12HOUR': '12H',
    '1DAY': '1D',
}
"""
HEC-RAS interval format to pandas offset string mapping.

Maps HEC-RAS interval notation to pandas time offset strings for resampling.
These intervals are used when converting USGS data to HEC-RAS boundary condition format.

Usage:
    >>> interval_str = HECRAS_INTERVALS['15MIN']
    >>> df.resample(interval_str).mean()

References:
    - HEC-RAS Unsteady Flow User's Manual
    - pandas time series documentation
"""


# ============================================================================
# HEC-RAS Table Types
# ============================================================================

HECRAS_TABLE_TYPES: Dict[str, str] = {
    'flow': 'Flow Hydrograph=',
    'stage': 'Stage Hydrograph=',
    'lateral_inflow': 'Lateral Inflow Hydrograph=',
    'gate': 'Gate Openings=',
    'rating_curve': 'Rating Curve=',
    'precipitation': 'Precipitation Hydrograph=',
}
"""
HEC-RAS unsteady flow table type prefixes.

These are the line prefixes used in .u## files to identify different table types.
All boundary condition tables begin with these identifiers followed by location information.

Format:
    Flow Hydrograph=River,Reach,Station
    Stage Hydrograph=River,Reach,Station
    Lateral Inflow Hydrograph=River,Reach,Station
    Precipitation Hydrograph=2DAreaName

References:
    - HEC-RAS Unsteady Flow Data Entry chapter
    - RasUnsteady.py table parsing functions
"""


# ============================================================================
# Initial Condition Line Prefixes
# ============================================================================

IC_LINE_TYPES: Dict[str, str] = {
    'flow': 'Initial Flow Loc=',
    'storage_elev': 'Initial Storage Elev=',
    'rrr_elev': 'Initial RRR Elev=',
}
"""
Initial Condition (IC) line type prefixes in HEC-RAS unsteady flow files.

These prefixes identify IC point types in .u## files. IC points set starting
conditions for unsteady flow simulations.

Format Examples:
    Initial Flow Loc=River,Reach,Station,Flow
    Initial Storage Elev=AreaName,Elevation
    Initial RRR Elev=River,Reach,Station,Elevation

Usage:
    - 'flow': 1D flow at cross-section (ft³/s)
    - 'storage_elev': Water surface elevation in storage/2D area (ft)
    - 'rrr_elev': Water surface elevation at RRR area (ft)

References:
    - BaldEagleCrkMulti2D example project (validated format)
    - HEC-RAS Unsteady Flow User's Manual
"""


# ============================================================================
# Fixed-Width Format Settings
# ============================================================================

FIXED_WIDTH_FORMAT: Dict[str, int] = {
    'width': 8,           # Character width per value
    'decimals': 2,        # Decimal places for formatting
    'values_per_line': 10,  # Number of values per line
}
"""
Fixed-width format specifications for HEC-RAS boundary condition tables.

HEC-RAS uses 8-character fixed-width format for all boundary condition tables
and hydrograph data in unsteady flow files.

Format Rules:
    - Each value occupies exactly 8 characters
    - Values are right-justified
    - 10 values per line maximum
    - 2 decimal places typical (can vary for different data types)

Example Line:
    "   123.45   456.78   789.01   234.56   567.89   890.12   345.67   678.90   901.23   456.78"

References:
    - RasUnsteady.parse_fixed_width_table()
    - RasUnsteady.write_table_to_file()
"""


# ============================================================================
# Gauge Data Directory Structure
# ============================================================================

GAUGE_DATA_DIRS: Dict[str, str] = {
    'root': 'gauge_data',
    'raw': 'gauge_data/raw',
    'processed': 'gauge_data/processed',
    'metadata': 'gauge_data/metadata',
}
"""
Standard directory structure for storing USGS gauge data within HEC-RAS projects.

The gauge_data subfolder is created in the HEC-RAS project directory to organize
retrieved and processed gauge data.

Structure:
    gauge_data/
    ├── raw/             Raw USGS data as retrieved (CSV)
    ├── processed/       Resampled/aligned data ready for HEC-RAS
    └── metadata/        Site information and retrieval logs

File Naming Convention:
    raw/{site_id}_{start_date}_{end_date}_{parameter}.csv
    processed/{site_id}_{start_date}_{end_date}_{parameter}_{interval}.csv
    metadata/{site_id}_info.json

Example:
    gauge_data/raw/USGS-01547200_20110906_20110912_flow.csv
    gauge_data/processed/USGS-01547200_20110906_20110912_flow_15MIN.csv
    gauge_data/metadata/USGS-01547200_info.json
"""


# ============================================================================
# Performance Classification Thresholds
# ============================================================================

PERFORMANCE_THRESHOLDS: Dict[str, Dict[str, float]] = {
    'very_good': {'nse': 0.75, 'pbias': 10.0},
    'good': {'nse': 0.65, 'pbias': 15.0},
    'satisfactory': {'nse': 0.50, 'pbias': 25.0},
}
"""
Model performance classification thresholds for hydrologic validation.

Based on Moriasi et al. (2007) guidelines for evaluating model performance
using Nash-Sutcliffe Efficiency (NSE) and Percent Bias (PBIAS).

Classification:
    Very Good:      NSE > 0.75, |PBIAS| < 10%
    Good:           NSE > 0.65, |PBIAS| < 15%
    Satisfactory:   NSE > 0.50, |PBIAS| < 25%
    Unsatisfactory: NSE ≤ 0.50, |PBIAS| ≥ 25%

NSE (Nash-Sutcliffe Efficiency):
    - Range: -∞ to 1.0 (1.0 is perfect)
    - NSE > 0.0 means model is better than using the mean
    - NSE > 0.5 is generally considered acceptable
    - NSE > 0.75 is considered very good

PBIAS (Percent Bias):
    - Measures average tendency for over/under-prediction
    - Positive values: model underestimates (negative bias)
    - Negative values: model overestimates (positive bias)
    - |PBIAS| < 10% is excellent
    - |PBIAS| < 25% is acceptable

References:
    Moriasi, D.N., et al. (2007). "Model Evaluation Guidelines for Systematic
    Quantification of Accuracy in Watershed Simulations." Transactions of the ASABE,
    50(3): 885-900.

Usage:
    >>> nse = 0.72
    >>> pbias = abs(-8.5)
    >>> if nse > PERFORMANCE_THRESHOLDS['very_good']['nse'] and \
    ...    pbias < PERFORMANCE_THRESHOLDS['very_good']['pbias']:
    ...     rating = 'Very Good'
"""


# ============================================================================
# Gauge-to-Model Location Match Quality Thresholds
# ============================================================================

MATCH_QUALITY_THRESHOLDS: Dict[str, float] = {
    'excellent': 100.0,   # meters (within same cross-section)
    'good': 500.0,        # meters (within same reach)
    'fair': 1000.0,       # meters (within same river system)
}
"""
Distance thresholds for classifying gauge-to-model location match quality.

Used when matching USGS gauge locations to HEC-RAS model locations (cross-sections,
2D areas, etc.). Distances are calculated after transforming gauge coordinates
from WGS84 to the model's coordinate reference system.

Classification:
    Excellent: < 100 m   - Gauge likely at or very near the cross-section
    Good:      < 500 m   - Gauge within the same reach/area
    Fair:      < 1000 m  - Gauge in the general vicinity
    Poor:      ≥ 1000 m  - Gauge may not be representative

Distance Considerations:
    - Distances are horizontal (planimetric) only
    - Coordinate transformation accuracy affects distance
    - Stream sinuosity may cause larger distances even for good matches
    - 2D areas may have larger acceptable distances than 1D cross-sections

Usage:
    >>> distance_m = 250.0
    >>> if distance_m < MATCH_QUALITY_THRESHOLDS['excellent']:
    ...     quality = 'excellent'
    >>> elif distance_m < MATCH_QUALITY_THRESHOLDS['good']:
    ...     quality = 'good'

Note:
    These are suggested defaults. Project-specific thresholds may be more
    appropriate based on stream size, model resolution, and gauge density.
"""


# ============================================================================
# Additional HEC-RAS Constants
# ============================================================================

HECRAS_DATE_FORMAT: str = '%d%b%Y'
"""
Standard HEC-RAS date format string.

Format: DDMonYYYY (e.g., "06Sep2011", "15Jan2024")

Usage:
    >>> import datetime
    >>> dt = datetime.datetime(2011, 9, 6)
    >>> dt.strftime(HECRAS_DATE_FORMAT)
    '06Sep2011'
"""

HECRAS_TIME_FORMAT: str = '%H%M'
"""
Standard HEC-RAS time format string.

Format: HHMM (24-hour format, e.g., "0000", "1430", "2359")

Usage:
    >>> import datetime
    >>> dt = datetime.datetime(2011, 9, 6, 14, 30)
    >>> dt.strftime(HECRAS_TIME_FORMAT)
    '1430'
"""


# ============================================================================
# USGS API Constants
# ============================================================================

USGS_SITE_TYPE_STREAM: str = 'ST'
"""
USGS site type code for stream gauges.

Used when querying for monitoring locations to filter for stream gauges only.

Usage:
    >>> from dataretrieval import waterdata
    >>> gauges, _ = waterdata.get_monitoring_locations(
    ...     bbox=[-77.5, 40.5, -77.0, 41.0],
    ...     site_type_code=USGS_SITE_TYPE_STREAM
    ... )
"""

USGS_COORDINATE_SYSTEM: str = 'EPSG:4326'
"""
USGS coordinate system (WGS84 lat/lon).

All USGS gauge locations are provided in WGS84 geographic coordinates.
Must be transformed to model CRS for spatial matching operations.

Usage:
    >>> import pyproj
    >>> transformer = pyproj.Transformer.from_crs(
    ...     USGS_COORDINATE_SYSTEM,
    ...     model_crs,
    ...     always_xy=True
    ... )
"""


# ============================================================================
# Constant Access Functions
# ============================================================================

def get_parameter_code(parameter_name: str) -> str:
    """
    Get USGS parameter code by name.

    Args:
        parameter_name: Name of parameter ('flow', 'stage', 'velocity', 'temperature')

    Returns:
        USGS parameter code (5-digit string)

    Raises:
        KeyError: If parameter name is not recognized

    Example:
        >>> get_parameter_code('flow')
        '00060'
        >>> get_parameter_code('stage')
        '00065'
    """
    return USGS_PARAMETERS[parameter_name.lower()]


def get_statistic_code(statistic_name: str) -> str:
    """
    Get USGS statistic code by name.

    Args:
        statistic_name: Name of statistic ('maximum', 'minimum', 'mean', 'instantaneous')

    Returns:
        USGS statistic code (5-digit string)

    Raises:
        KeyError: If statistic name is not recognized

    Example:
        >>> get_statistic_code('instantaneous')
        '00011'
        >>> get_statistic_code('mean')
        '00003'
    """
    return USGS_STATISTICS[statistic_name.lower()]


def get_pandas_offset(hecras_interval: str) -> str:
    """
    Convert HEC-RAS interval to pandas time offset string.

    Args:
        hecras_interval: HEC-RAS interval name (e.g., '15MIN', '1HOUR', '1DAY')

    Returns:
        Pandas offset string for resampling (e.g., '15T', '1H', '1D')

    Raises:
        KeyError: If interval is not recognized

    Example:
        >>> get_pandas_offset('15MIN')
        '15T'
        >>> get_pandas_offset('1HOUR')
        '1H'
        >>> get_pandas_offset('1DAY')
        '1D'
    """
    return HECRAS_INTERVALS[hecras_interval.upper()]


def get_table_type_prefix(table_type: str) -> str:
    """
    Get HEC-RAS table type prefix by name.

    Args:
        table_type: Table type name (e.g., 'flow', 'stage', 'lateral_inflow')

    Returns:
        Table type prefix string (e.g., 'Flow Hydrograph=')

    Raises:
        KeyError: If table type is not recognized

    Example:
        >>> get_table_type_prefix('flow')
        'Flow Hydrograph='
        >>> get_table_type_prefix('stage')
        'Stage Hydrograph='
    """
    return HECRAS_TABLE_TYPES[table_type.lower()]


def get_ic_line_prefix(ic_type: str) -> str:
    """
    Get initial condition line prefix by type.

    Args:
        ic_type: IC type ('flow', 'storage_elev', 'rrr_elev')

    Returns:
        IC line prefix string (e.g., 'Initial Flow Loc=')

    Raises:
        KeyError: If IC type is not recognized

    Example:
        >>> get_ic_line_prefix('flow')
        'Initial Flow Loc='
        >>> get_ic_line_prefix('storage_elev')
        'Initial Storage Elev='
    """
    return IC_LINE_TYPES[ic_type.lower()]


def classify_performance(nse: float, pbias: float) -> str:
    """
    Classify model performance based on NSE and PBIAS metrics.

    Uses Moriasi et al. (2007) guidelines to classify model performance
    as Very Good, Good, Satisfactory, or Unsatisfactory.

    Args:
        nse: Nash-Sutcliffe Efficiency (range: -∞ to 1.0)
        pbias: Percent Bias (positive or negative, use absolute value for comparison)

    Returns:
        Performance classification: 'Very Good', 'Good', 'Satisfactory', 'Unsatisfactory'

    Example:
        >>> classify_performance(nse=0.82, pbias=8.5)
        'Very Good'
        >>> classify_performance(nse=0.68, pbias=12.3)
        'Good'
        >>> classify_performance(nse=0.45, pbias=28.0)
        'Unsatisfactory'
    """
    pbias_abs = abs(pbias)

    if (nse > PERFORMANCE_THRESHOLDS['very_good']['nse'] and
            pbias_abs < PERFORMANCE_THRESHOLDS['very_good']['pbias']):
        return 'Very Good'
    elif (nse > PERFORMANCE_THRESHOLDS['good']['nse'] and
          pbias_abs < PERFORMANCE_THRESHOLDS['good']['pbias']):
        return 'Good'
    elif (nse > PERFORMANCE_THRESHOLDS['satisfactory']['nse'] and
          pbias_abs < PERFORMANCE_THRESHOLDS['satisfactory']['pbias']):
        return 'Satisfactory'
    else:
        return 'Unsatisfactory'


def classify_match_quality(distance_m: float) -> str:
    """
    Classify gauge-to-model location match quality based on distance.

    Args:
        distance_m: Horizontal distance between gauge and model location (meters)

    Returns:
        Match quality classification: 'excellent', 'good', 'fair', 'poor'

    Example:
        >>> classify_match_quality(75.0)
        'excellent'
        >>> classify_match_quality(350.0)
        'good'
        >>> classify_match_quality(1200.0)
        'poor'
    """
    if distance_m < MATCH_QUALITY_THRESHOLDS['excellent']:
        return 'excellent'
    elif distance_m < MATCH_QUALITY_THRESHOLDS['good']:
        return 'good'
    elif distance_m < MATCH_QUALITY_THRESHOLDS['fair']:
        return 'fair'
    else:
        return 'poor'


# ============================================================================
# Constant Validation
# ============================================================================

def validate_constants() -> list:
    """
    Validate configuration constants for consistency.

    Performs basic sanity checks on constant values to ensure they are
    properly formatted and logically consistent.

    Returns:
        List of validation error messages (empty if all valid)

    Example:
        >>> errors = validate_constants()
        >>> if not errors:
        ...     print("All constants are valid")
    """
    errors = []

    # Validate USGS parameter codes are 5-digit strings
    for name, code in USGS_PARAMETERS.items():
        if not (isinstance(code, str) and len(code) == 5 and code.isdigit()):
            errors.append(f"USGS parameter code '{name}' is not a 5-digit string: {code}")

    # Validate USGS statistic codes are 5-digit strings
    for name, code in USGS_STATISTICS.items():
        if not (isinstance(code, str) and len(code) == 5 and code.isdigit()):
            errors.append(f"USGS statistic code '{name}' is not a 5-digit string: {code}")

    # Validate performance thresholds
    for level in ['very_good', 'good', 'satisfactory']:
        if level not in PERFORMANCE_THRESHOLDS:
            errors.append(f"Missing performance threshold level: {level}")
            continue
        if 'nse' not in PERFORMANCE_THRESHOLDS[level]:
            errors.append(f"Missing NSE threshold for {level}")
        if 'pbias' not in PERFORMANCE_THRESHOLDS[level]:
            errors.append(f"Missing PBIAS threshold for {level}")

    # Validate NSE thresholds are decreasing (very_good > good > satisfactory)
    nse_very_good = PERFORMANCE_THRESHOLDS.get('very_good', {}).get('nse', 0)
    nse_good = PERFORMANCE_THRESHOLDS.get('good', {}).get('nse', 0)
    nse_satisfactory = PERFORMANCE_THRESHOLDS.get('satisfactory', {}).get('nse', 0)

    if not (nse_very_good > nse_good > nse_satisfactory):
        errors.append("NSE thresholds should be: very_good > good > satisfactory")

    # Validate PBIAS thresholds are increasing (very_good < good < satisfactory)
    pbias_very_good = PERFORMANCE_THRESHOLDS.get('very_good', {}).get('pbias', 0)
    pbias_good = PERFORMANCE_THRESHOLDS.get('good', {}).get('pbias', 0)
    pbias_satisfactory = PERFORMANCE_THRESHOLDS.get('satisfactory', {}).get('pbias', 0)

    if not (pbias_very_good < pbias_good < pbias_satisfactory):
        errors.append("PBIAS thresholds should be: very_good < good < satisfactory")

    # Validate match quality thresholds are increasing
    if not (MATCH_QUALITY_THRESHOLDS['excellent'] <
            MATCH_QUALITY_THRESHOLDS['good'] <
            MATCH_QUALITY_THRESHOLDS['fair']):
        errors.append("Match quality thresholds should be: excellent < good < fair")

    # Validate fixed-width format values
    if FIXED_WIDTH_FORMAT['width'] != 8:
        errors.append("Fixed width format width should be 8 (HEC-RAS standard)")
    if FIXED_WIDTH_FORMAT['values_per_line'] != 10:
        errors.append("Fixed width format values_per_line should be 10 (HEC-RAS standard)")

    return errors
