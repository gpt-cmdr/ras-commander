# NOAA Atlas 14 API Reference

Complete API documentation for NOAA Atlas 14 design storm generation.

## Module: `ras_commander.precip.StormGenerator`

All methods are static (no instantiation required).

---

## Precipitation Frequency Methods

### `get_precipitation_frequency()`

Query NOAA Atlas 14 for precipitation depth at a location.

```python
StormGenerator.get_precipitation_frequency(
    location,            # tuple (lat, lon) or str (station ID)
    duration_hours,      # int or float
    aep_percent          # float
)
```

**Returns**: `float` - Precipitation depth in inches

**Parameters**:
- `location`: (latitude, longitude) in decimal degrees WGS84
- `duration_hours`: Storm duration (6, 12, 24, 48, etc.)
- `aep_percent`: Annual Exceedance Probability (50, 20, 10, 4, 2, 1, 0.5, 0.2)

**Example**:
```python
# Get 24-hour, 1% AEP (100-year) precipitation
precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),  # Washington, DC
    duration_hours=24,
    aep_percent=1.0
)
print(f"24-hr, 1% AEP: {precip:.2f} inches")
```

**Common AEP Values**:
| AEP | Return Period | Common Name |
|-----|---------------|-------------|
| 50% | 2-year | Frequent |
| 20% | 5-year | Common |
| 10% | 10-year | Standard |
| 4% | 25-year | Design |
| 2% | 50-year | Design |
| 1% | 100-year | Base Flood |
| 0.5% | 200-year | Extreme |
| 0.2% | 500-year | PMF |

---

### `get_precipitation_frequency_table()`

Get precipitation-duration-frequency table for a location.

```python
StormGenerator.get_precipitation_frequency_table(
    location,            # tuple (lat, lon)
    durations=[6, 12, 24, 48],  # list[int]
    aeps=[10, 4, 2, 1, 0.5, 0.2]  # list[float]
)
```

**Returns**: `pandas.DataFrame` - DDF table

**Example**:
```python
ddf_table = StormGenerator.get_precipitation_frequency_table(
    location=(38.9, -77.0),
    durations=[6, 12, 24, 48],
    aeps=[10, 4, 2, 1, 0.5, 0.2]
)
#      6hr   12hr   24hr   48hr
# 10%  2.5   3.2    4.1    5.0
# 4%   3.1   4.0    5.2    6.3
# 2%   3.5   4.5    5.9    7.1
# 1%   4.0   5.2    6.7    8.1
```

---

## Design Storm Generation Methods

### `generate_design_storm()`

Create design storm hyetograph with temporal distribution.

```python
StormGenerator.generate_design_storm(
    total_precip,        # float (inches)
    duration_hours,      # int or float
    distribution="SCS_Type_II",  # str
    interval_minutes=15  # int
)
```

**Returns**: `pandas.Series` - Hyetograph (time index, precipitation values)

**Parameters**:
- `total_precip`: Total precipitation depth (inches)
- `duration_hours`: Storm duration (typically 6, 12, 24, or 48 hours)
- `distribution`: Temporal distribution pattern
- `interval_minutes`: Time step (5, 10, 15, 30, or 60 minutes)

**Temporal Distributions**:
- `"SCS_Type_II"` - Standard for most of US (24-hr peak at 12 hours)
- `"SCS_Type_IA"` - Pacific maritime climate (24-hr peak at 8 hours)
- `"SCS_Type_III"` - Gulf Coast and Florida (24-hr peak at 13 hours)
- `"Custom"` - User-defined pattern (requires custom_pattern parameter)

**Example**:
```python
hyetograph = StormGenerator.generate_design_storm(
    total_precip=6.7,  # inches (from Atlas 14)
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15
)
# Returns Series with 96 values (24 hours × 4 intervals/hour)
```

---

### `apply_temporal_distribution()`

Apply temporal pattern to precipitation total.

```python
StormGenerator.apply_temporal_distribution(
    total_precip,        # float
    distribution_pattern  # str or array-like
)
```

**Returns**: `numpy.ndarray` - Dimensionless hyetograph pattern

**Example**:
```python
pattern = StormGenerator.apply_temporal_distribution(
    total_precip=6.7,
    distribution_pattern="SCS_Type_II"
)
```

---

## Spatial Processing Methods

### `apply_areal_reduction()`

Apply Areal Reduction Factor (ARF) for large watersheds.

```python
StormGenerator.apply_areal_reduction(
    point_precip,        # float (inches)
    area_sqmi,           # float
    duration_hours       # int or float
)
```

**Returns**: `float` - Reduced precipitation (inches)

**Parameters**:
- `point_precip`: Point precipitation from Atlas 14
- `area_sqmi`: Watershed area in square miles
- `duration_hours`: Storm duration

**ARF Guidelines**:
| Watershed Size | ARF Range | Typical Reduction |
|----------------|-----------|-------------------|
| < 10 sq mi | 0.98-1.00 | Negligible |
| 10-100 sq mi | 0.90-0.98 | 2-10% |
| 100-500 sq mi | 0.85-0.95 | 5-15% |
| > 500 sq mi | 0.75-0.90 | 10-25% |

**Example**:
```python
point_precip = 6.7  # inches (from Atlas 14)
area = 500  # square miles

reduced = StormGenerator.apply_areal_reduction(
    point_precip=point_precip,
    area_sqmi=area,
    duration_hours=24
)
print(f"Point: {point_precip:.2f} in")
print(f"Areal (500 sq mi): {reduced:.2f} in ({(1-reduced/point_precip)*100:.1f}% reduction)")
```

---

### `interpolate_point_values()`

Interpolate Atlas 14 values to grid.

```python
StormGenerator.interpolate_point_values(
    locations,           # list[tuple] - (lat, lon) pairs
    values,              # list[float] - precipitation values
    grid                 # xarray Dataset or tuple (bounds, resolution)
)
```

**Returns**: `xarray.DataArray` - Interpolated precipitation grid

**Example**:
```python
# Define gauge locations and values
locations = [(38.9, -77.0), (38.8, -76.9), (39.0, -77.1)]
values = [6.7, 6.5, 6.9]

# Interpolate to grid
grid = StormGenerator.interpolate_point_values(
    locations=locations,
    values=values,
    grid=((-77.5, 38.5, -76.5, 39.5), 0.01)  # bounds, resolution
)
```

---

### `generate_multi_point_storms()`

Generate spatially distributed design storms.

```python
StormGenerator.generate_multi_point_storms(
    locations,           # list[tuple] - (lat, lon) pairs
    duration_hours,      # int
    aep_percent,         # float
    distribution="SCS_Type_II"  # str
)
```

**Returns**: `dict` - {location: hyetograph}

**Example**:
```python
storms = StormGenerator.generate_multi_point_storms(
    locations=[(38.9, -77.0), (38.8, -76.9)],
    duration_hours=24,
    aep_percent=1.0,
    distribution="SCS_Type_II"
)
# Returns: {(38.9, -77.0): Series(...), (38.8, -76.9): Series(...)}
```

---

## Export Methods

### `export_to_dss()`

Export hyetograph to HEC-DSS format.

```python
StormGenerator.export_to_dss(
    hyetograph,          # pandas Series
    dss_file,            # str or Path
    pathname=None        # str or None
)
```

**Requires**: `pydsstools` (lazy-loaded)

**Example**:
```python
StormGenerator.export_to_dss(
    hyetograph,
    dss_file="design_storm.dss",
    pathname="/PROJECT/PRECIP/DESIGN//15MIN/SYN/"
)
```

---

### `export_to_hms_gage()`

Export to HEC-HMS precipitation gage file.

```python
StormGenerator.export_to_hms_gage(
    hyetograph,          # pandas Series
    output_file,         # str or Path
    gage_id="PRECIP1"    # str
)
```

**Example**:
```python
StormGenerator.export_to_hms_gage(
    hyetograph,
    output_file="design_storm.gage",
    gage_id="PRECIP1"
)
```

---

### `export_to_csv()`

Export hyetograph to CSV.

```python
hyetograph.to_csv("design_storm.csv")
```

**Example**:
```python
# pandas Series has built-in to_csv
hyetograph.to_csv("design_storm.csv", header=["Precip_in"])
```

---

## Atlas 14 Regional Coverage

### Volumes and Regions

NOAA Atlas 14 covers the United States in 11 volumes:

| Volume | Region | Status |
|--------|--------|--------|
| 1 | Semiarid Southwest | Published |
| 2 | Ohio River Basin and Surrounding States | Published |
| 3 | Puerto Rico and Virgin Islands | Published |
| 4 | Hawaiian Islands | Published |
| 5 | Selected Pacific Islands | Published |
| 6 | California | Published |
| 7 | Alaska | Published |
| 8 | Midwestern States | Published |
| 9 | Southeastern States | Published |
| 10 | Northeastern States | Published |
| 11 | Texas | Published |

**Region Detection**: Automatic based on lat/lon coordinates

---

## SCS Temporal Distributions

### SCS Type II (Most of US)

Standard distribution for most of continental US:
- **Peak location**: 12 hours (50% of duration for 24-hr)
- **Peak intensity**: ~50% of total in 1-2 hours
- **Use for**: Mid-Atlantic, Midwest, Great Plains, Mountain West

**Cumulative Distribution**:
```
Time (hr):    0    2    4    6    8   10   11   12   13   14   16   18   20   22   24
Cumulative:  0%   2%   4%   7%  11%  15%  25%  50%  75%  81%  87%  92%  96%  98% 100%
```

### SCS Type IA (Pacific Maritime)

Pacific maritime climate:
- **Peak location**: 8 hours (33% of duration for 24-hr)
- **Peak intensity**: ~40% of total in 1-2 hours
- **Use for**: Pacific Northwest, coastal California

### SCS Type III (Gulf Coast)

Gulf Coast and Florida:
- **Peak location**: 13 hours (54% of duration for 24-hr)
- **Peak intensity**: ~55% of total in 1-2 hours
- **Use for**: Florida, Gulf Coast, Atlantic Coast south of NC

---

## Multi-Duration Design Storms

For comprehensive analysis, run multiple durations:

```python
durations = [6, 12, 24, 48]  # hours
aep = 1.0  # 1% = 100-year

for duration in durations:
    # Get precipitation
    precip = StormGenerator.get_precipitation_frequency(
        location=(38.9, -77.0),
        duration_hours=duration,
        aep_percent=aep
    )

    # Generate design storm
    hyetograph = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=duration,
        distribution="SCS_Type_II"
    )

    # Export
    StormGenerator.export_to_dss(
        hyetograph,
        dss_file=f"design_{duration}hr.dss"
    )
```

---

## Complete Workflow Example

### Single-Project Multi-Event Suite

```python
from ras_commander import init_ras_project, RasCmdr
from ras_commander.precip import StormGenerator

# Initialize project
ras = init_ras_project("path/to/project", "6.6")

# Project centroid
centroid = (38.9, -77.0)

# AEP suite
aeps = [10, 4, 2, 1, 0.5, 0.2]

# Generate and run all events
for aep in aeps:
    # Get precipitation
    precip = StormGenerator.get_precipitation_frequency(
        location=centroid,
        duration_hours=24,
        aep_percent=aep
    )

    # Apply ARF if needed
    if watershed_area_sqmi > 10:
        precip = StormGenerator.apply_areal_reduction(
            point_precip=precip,
            area_sqmi=watershed_area_sqmi,
            duration_hours=24
        )

    # Generate design storm
    hyetograph = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=24,
        distribution="SCS_Type_II",
        interval_minutes=15
    )

    # Export to DSS
    dss_file = f"design_{aep}pct.dss"
    StormGenerator.export_to_dss(hyetograph, dss_file)

    # Create plan (copy template and update DSS reference)
    # ... plan creation logic ...

    # Execute
    RasCmdr.compute_plan(plan_number)

    print(f"{aep}% AEP: {precip:.2f} in → Plan {plan_number}")
```

---

## Performance Considerations

### API Access
- **Speed**: < 5 seconds per query
- **Rate Limiting**: NOAA PFDS has request limits (respect usage guidelines)
- **Caching**: Automatic caching of API responses

### Design Storm Generation
- **Speed**: < 1 second for typical durations
- **Memory**: Minimal (< 1 MB per hyetograph)

---

## Error Handling

All methods raise informative exceptions:

```python
try:
    precip = StormGenerator.get_precipitation_frequency(
        location=(38.9, -77.0),
        duration_hours=24,
        aep_percent=1.0
    )
except ValueError as e:
    print(f"Invalid parameters: {e}")
except ConnectionError as e:
    print(f"NOAA PFDS unavailable: {e}")
except Exception as e:
    print(f"Error: {e}")
```

Common errors:
- `ValueError`: Invalid AEP, duration, or location
- `ConnectionError`: NOAA PFDS server unavailable
- `RuntimeError`: API response parsing error

---

## Data Sources

### NOAA Precipitation Frequency Data Server (PFDS)
- **URL**: https://hdsc.nws.noaa.gov/pfds/
- **Provider**: NOAA National Weather Service Hydrometeorological Design Studies Center
- **Format**: JSON API
- **Access**: Public (no authentication)
- **Documentation**: https://hdsc.nws.noaa.gov/pfds/pfds_api.html

---

## See Also

- **Main Skill**: [../SKILL.md](../SKILL.md)
- **AORC API**: [aorc-api.md](aorc-api.md)
- **Precip Module**: `ras_commander/precip/CLAUDE.md`
- **Example Notebooks**:
  - `examples/103_Running_AEP_Events_from_Atlas_14.ipynb`
  - `examples/104_Atlas14_AEP_Multi_Project.ipynb`
