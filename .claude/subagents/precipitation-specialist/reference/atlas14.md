# NOAA Atlas 14 API Reference

Complete API reference for NOAA Atlas 14 design storm generation with precipitation frequency estimates.

## Overview

NOAA Atlas 14 provides authoritative precipitation frequency estimates for design storm analysis. This module queries the NOAA HDSC Precipitation Frequency Data Server (PFDS) and generates synthetic design storms with standard temporal distributions.

## StormGenerator Class

All methods are static and use `@log_call` decorators for execution tracking.

### Precipitation Frequency Queries

#### get_precipitation_frequency()

Query Atlas 14 point precipitation values for design AEP events.

**Signature**:
```python
StormGenerator.get_precipitation_frequency(
    location: Union[Tuple[float, float], str],
    duration_hours: float,
    aep_percent: float,
    units: str = "imperial"
) -> float
```

**Parameters**:
- `location`: (lat, lon) tuple or station ID string
- `duration_hours`: Storm duration (0.25 to 96 hours)
- `aep_percent`: Annual exceedance probability (0.2 to 50)
- `units`: "imperial" (inches) or "metric" (mm)

**Returns**: Precipitation depth (inches or mm)

**Common AEP Values**:
- 50% (2-year event)
- 20% (5-year event)
- 10% (10-year event)
- 4% (25-year event)
- 2% (50-year event)
- 1% (100-year event)
- 0.5% (200-year event)
- 0.2% (500-year event)

**Example**:
```python
from ras_commander.precip import StormGenerator

# Get 24-hour, 1% AEP (100-year) precipitation for Richmond, VA
precip = StormGenerator.get_precipitation_frequency(
    location=(37.5407, -77.4360),
    duration_hours=24,
    aep_percent=1.0,
    units="imperial"
)
print(f"24-hr, 1% AEP: {precip:.2f} inches")
# Output: 24-hr, 1% AEP: 7.65 inches

# Get 6-hour, 10% AEP (10-year) in metric
precip_mm = StormGenerator.get_precipitation_frequency(
    location=(37.5407, -77.4360),
    duration_hours=6,
    aep_percent=10.0,
    units="metric"
)
print(f"6-hr, 10% AEP: {precip_mm:.1f} mm")
```

**Performance**: < 5 seconds per query (API access with automatic caching)

#### get_precipitation_frequency_table()

Retrieve complete frequency table for a location.

**Signature**:
```python
StormGenerator.get_precipitation_frequency_table(
    location: Union[Tuple[float, float], str],
    units: str = "imperial"
) -> pd.DataFrame
```

**Returns**: DataFrame with rows=durations, columns=AEPs

**Example**:
```python
# Get complete frequency table
table = StormGenerator.get_precipitation_frequency_table(
    location=(37.5407, -77.4360),
    units="imperial"
)

print(table)
#           50%   20%    10%    4%     2%     1%     0.5%   0.2%
# 6hr      1.5   2.1    2.6    3.3    3.8    4.4    5.0    5.8
# 12hr     1.8   2.6    3.2    4.1    4.8    5.6    6.4    7.5
# 24hr     2.2   3.2    4.0    5.2    6.2    7.2    8.4    9.8
# 48hr     2.6   3.8    4.8    6.3    7.5    8.9   10.5   12.5

# Export for documentation
table.to_csv("atlas14_frequency_table.csv")
```

### Design Storm Generation

#### generate_design_storm()

Create complete design storm hyetograph with temporal distribution.

**Signature**:
```python
StormGenerator.generate_design_storm(
    total_precip: float,
    duration_hours: float,
    distribution: str = "SCS_Type_II",
    interval_minutes: int = 15
) -> pd.DataFrame
```

**Parameters**:
- `total_precip`: Total precipitation depth (inches or mm)
- `duration_hours`: Storm duration (must match distribution)
- `distribution`: Temporal pattern (see below)
- `interval_minutes`: Output timestep (5, 10, 15, 30, 60)

**Returns**: DataFrame with columns `['datetime', 'cumulative_precip', 'incremental_precip']`

**Temporal Distributions**:
- `SCS_Type_II`: Standard for most US (24-hour)
- `SCS_Type_IA`: Pacific maritime climate (24-hour)
- `SCS_Type_III`: Gulf Coast and Florida (24-hour)
- `SCS_6hr`: 6-hour SCS pattern
- `SCS_12hr`: 12-hour SCS pattern
- `Uniform`: Constant intensity (any duration)

**Example**:
```python
# Query Atlas 14 for design precipitation
precip = StormGenerator.get_precipitation_frequency(
    location=(37.5407, -77.4360),
    duration_hours=24,
    aep_percent=1.0  # 100-year event
)

# Generate 24-hour SCS Type II hyetograph
hyetograph = StormGenerator.generate_design_storm(
    total_precip=precip,
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15
)

print(hyetograph.head())
#          datetime  cumulative_precip  incremental_precip
# 0  2024-01-01 00:00:00          0.05               0.05
# 1  2024-01-01 00:15:00          0.11               0.06
# 2  2024-01-01 00:30:00          0.18               0.07

# Check peak intensity
peak = hyetograph['incremental_precip'].max()
peak_time = hyetograph.loc[hyetograph['incremental_precip'].idxmax(), 'datetime']
print(f"Peak intensity: {peak:.2f} in/15min at {peak_time}")
```

#### apply_temporal_distribution()

Apply temporal pattern to total precipitation.

**Signature**:
```python
StormGenerator.apply_temporal_distribution(
    total_precip: float,
    distribution: str,
    interval_minutes: int = 15
) -> np.ndarray
```

**Returns**: Numpy array of incremental precipitation values

**Use case**: When you need raw distribution values without DataFrame wrapper

### Areal Reduction Factors

#### apply_areal_reduction()

Apply areal reduction factor for large watersheds.

**Signature**:
```python
StormGenerator.apply_areal_reduction(
    point_precip: float,
    area_sqmi: float,
    duration_hours: float,
    method: str = "NOAA_TP40"
) -> float
```

**Parameters**:
- `point_precip`: Point precipitation from Atlas 14 (inches or mm)
- `area_sqmi`: Watershed area (square miles)
- `duration_hours`: Storm duration (6, 12, 24, 48 hours)
- `method`: ARF methodology ("NOAA_TP40", "UK_FEH", "custom")

**Returns**: Areal-reduced precipitation (same units as input)

**ARF Guidelines**:
- < 10 sq mi: ARF ≈ 1.00 (no reduction)
- 10-100 sq mi: ARF = 0.95-0.98
- 100-1000 sq mi: ARF = 0.85-0.95
- > 1000 sq mi: ARF < 0.85

**Example**:
```python
# Get point precipitation
point_precip = StormGenerator.get_precipitation_frequency(
    location=(37.5407, -77.4360),
    duration_hours=24,
    aep_percent=1.0
)
print(f"Point precipitation: {point_precip:.2f} inches")

# Apply ARF for 500 sq mi watershed
watershed_area = 500.0
reduced_precip = StormGenerator.apply_areal_reduction(
    point_precip=point_precip,
    area_sqmi=watershed_area,
    duration_hours=24
)
print(f"Areal precipitation (500 sq mi): {reduced_precip:.2f} inches")
print(f"ARF: {reduced_precip / point_precip:.3f}")

# Output:
# Point precipitation: 7.65 inches
# Areal precipitation (500 sq mi): 6.88 inches
# ARF: 0.900
```

#### get_areal_reduction_factor()

Get ARF value without applying to precipitation.

**Signature**:
```python
StormGenerator.get_areal_reduction_factor(
    area_sqmi: float,
    duration_hours: float,
    method: str = "NOAA_TP40"
) -> float
```

**Returns**: ARF multiplier (0.0 to 1.0)

**Example**:
```python
# Get ARF for documentation
arf_24hr = StormGenerator.get_areal_reduction_factor(
    area_sqmi=500,
    duration_hours=24
)
print(f"24-hour ARF for 500 sq mi: {arf_24hr:.3f}")

# Create ARF table
areas = [10, 50, 100, 500, 1000, 5000]
for area in areas:
    arf = StormGenerator.get_areal_reduction_factor(area, duration_hours=24)
    print(f"{area:5.0f} sq mi: ARF = {arf:.3f}")
```

### Spatial Processing

#### interpolate_point_values()

Interpolate Atlas 14 values to grid for spatially distributed storms.

**Signature**:
```python
StormGenerator.interpolate_point_values(
    locations: List[Tuple[float, float]],
    duration_hours: float,
    aep_percent: float,
    grid_resolution_km: float = 4.0
) -> xr.DataArray
```

**Use case**: Spatially varying design storms for 2D HEC-RAS or HEC-HMS

#### generate_multi_point_storms()

Generate design storms at multiple locations.

**Signature**:
```python
StormGenerator.generate_multi_point_storms(
    locations: List[Tuple[float, float]],
    duration_hours: float,
    aep_percent: float,
    distribution: str = "SCS_Type_II"
) -> Dict[str, pd.DataFrame]
```

**Returns**: Dictionary mapping location IDs to hyetograph DataFrames

### Output Formats

#### export_to_dss()

Export design storm to HEC-DSS format.

**Signature**:
```python
StormGenerator.export_to_dss(
    hyetograph: pd.DataFrame,
    dss_file: Union[str, Path],
    pathname: str
) -> None
```

**DSS Pathname for Design Storms**:
- Use "SYN" (synthetic) for version field
- Include AEP in location field (e.g., "PRECIP_1PCT")

**Example**:
```python
# Generate design storm
hyetograph = StormGenerator.generate_design_storm(
    total_precip=7.65,
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15
)

# Export to DSS
StormGenerator.export_to_dss(
    hyetograph,
    dss_file="design_storm_100yr.dss",
    pathname="/PROJECT/PRECIP_1PCT/PRECIPITATION-INCREMENTAL//15MIN/SYN/"
)
```

#### export_to_hms_gage()

Export to HEC-HMS precipitation gage file format.

**Signature**:
```python
StormGenerator.export_to_hms_gage(
    hyetograph: pd.DataFrame,
    output_file: Union[str, Path],
    gage_id: str,
    units: str = "inches"
) -> None
```

**Example**:
```python
# Export to HMS gage file
StormGenerator.export_to_hms_gage(
    hyetograph,
    output_file="design_storm_100yr.gage",
    gage_id="PRECIP_1PCT",
    units="inches"
)
```

#### export_to_csv()

Export to CSV for review or custom processing.

**Example**:
```python
# Simple CSV export
hyetograph.to_csv("design_storm_100yr.csv", index=False)
```

## Multi-Event Workflows

### Generate AEP Suite

Create multiple design storms for full frequency analysis.

**Example**:
```python
from ras_commander.precip import StormGenerator

# Define AEP suite
aep_events = [10, 4, 2, 1, 0.5, 0.2]  # 10-year to 500-year
location = (37.5407, -77.4360)

# Generate all events
for aep in aep_events:
    # Query Atlas 14
    precip = StormGenerator.get_precipitation_frequency(
        location=location,
        duration_hours=24,
        aep_percent=aep
    )

    # Apply ARF (500 sq mi watershed)
    reduced = StormGenerator.apply_areal_reduction(
        point_precip=precip,
        area_sqmi=500,
        duration_hours=24
    )

    # Generate design storm
    hyetograph = StormGenerator.generate_design_storm(
        total_precip=reduced,
        duration_hours=24,
        distribution="SCS_Type_II",
        interval_minutes=15
    )

    # Export to DSS
    dss_file = f"design_storm_{aep}pct.dss"
    StormGenerator.export_to_dss(
        hyetograph,
        dss_file=dss_file,
        pathname=f"/PROJECT/PRECIP_{aep}PCT/PRECIPITATION-INCREMENTAL//15MIN/SYN/"
    )

    print(f"Generated {aep}% AEP storm: {reduced:.2f} inches")
```

## Complete Workflow Example

```python
from ras_commander.precip import StormGenerator
from pathlib import Path

# 1. Define location and event
location = (37.5407, -77.4360)  # Richmond, VA
aep = 1.0  # 100-year event
duration = 24  # hours

# 2. Query Atlas 14
point_precip = StormGenerator.get_precipitation_frequency(
    location=location,
    duration_hours=duration,
    aep_percent=aep,
    units="imperial"
)
print(f"Point precipitation: {point_precip:.2f} inches")

# 3. Apply areal reduction (if watershed > 10 sq mi)
watershed_area = 500.0  # sq mi
areal_precip = StormGenerator.apply_areal_reduction(
    point_precip=point_precip,
    area_sqmi=watershed_area,
    duration_hours=duration
)
print(f"Areal precipitation: {areal_precip:.2f} inches")

# 4. Generate design storm
hyetograph = StormGenerator.generate_design_storm(
    total_precip=areal_precip,
    duration_hours=duration,
    distribution="SCS_Type_II",
    interval_minutes=15
)

# 5. Export to multiple formats
# DSS for HEC-RAS
StormGenerator.export_to_dss(
    hyetograph,
    dss_file="design_storm_100yr.dss",
    pathname="/PROJECT/PRECIP_1PCT/PRECIPITATION-INCREMENTAL//15MIN/SYN/"
)

# HMS gage file
StormGenerator.export_to_hms_gage(
    hyetograph,
    output_file="design_storm_100yr.gage",
    gage_id="PRECIP_1PCT"
)

# CSV for review
hyetograph.to_csv("design_storm_100yr.csv", index=False)

print("Design storm generation complete")
```

## See Also

- Parent module: `ras_commander/precip/CLAUDE.md`
- AORC workflows: [aorc-api.md](aorc-api.md)
- Example notebooks:
  - `examples/103_Running_AEP_Events_from_Atlas_14.ipynb` (single project)
  - `examples/104_Atlas14_AEP_Multi_Project.ipynb` (batch processing)
