---
name: extracting-hecras-results
description: |
  Extract HEC-RAS hydraulic results from HDF files including water surface elevations (WSE),
  depths, velocities, and flows for both steady and unsteady simulations. Handles cross section
  time series, 2D mesh results, maximum envelopes, and dam breach results. Use when you need to
  extract, analyze, or post-process HEC-RAS simulation outputs, retrieve water levels, query
  velocity fields, get depth grids, extract flow data, analyze breach hydrographs, or pull
  hydraulic variables from .hdf result files.
---

# Extracting HEC-RAS Results

Extract and analyze hydraulic results from HEC-RAS HDF output files for both steady state and unsteady flow simulations.

## Quick Start

```python
from ras_commander import (
    HdfResultsPlan,
    HdfResultsMesh,
    HdfResultsXsec,
    HdfResultsBreach
)

# Check simulation type
is_steady = HdfResultsPlan.is_steady_plan("01")

# Extract steady flow results
if is_steady:
    profiles = HdfResultsPlan.get_steady_profile_names("01")
    wse = HdfResultsPlan.get_steady_wse("01", profile_name="100 year")

# Extract unsteady flow results
else:
    # Get cross section time series
    xsec_ts = HdfResultsXsec.get_xsec_timeseries("01")

    # Get 2D mesh maximum envelope
    max_wse = HdfResultsMesh.get_mesh_maximum("01", variable="Water Surface")

    # Get time series at specific locations
    mesh_ts = HdfResultsMesh.get_mesh_timeseries("01", timestep_indices=[0, 10, 20])
```

## Steady vs Unsteady Detection

Always check simulation type before extraction:

```python
# Detect plan type
is_steady = HdfResultsPlan.is_steady_plan("02")
plan_info = HdfResultsPlan.get_plan_info("02")

print(f"Plan type: {'Steady' if is_steady else 'Unsteady'}")
print(f"Program version: {plan_info['Program Version'].iloc[0]}")
```

**Return structure for `get_plan_info()`:**
```python
pd.DataFrame with columns:
    - Program Name
    - Program Version
    - Project File Name
    - Type of Run
    - Run Time Window
    - Solution (status message)
```

## Steady Flow Results

### Profile Names and Water Surface Elevations

```python
# List available profiles
profiles = HdfResultsPlan.get_steady_profile_names("02")
# Returns: ['.5 year', '1 year', '2 year', '5 year', '10 year', ...]

# Extract single profile
wse_100yr = HdfResultsPlan.get_steady_wse("02", profile_name="100 year")

# Extract by index
wse_first = HdfResultsPlan.get_steady_wse("02", profile_index=0)

# Extract all profiles at once
wse_all = HdfResultsPlan.get_steady_wse("02")  # Returns all profiles
```

**Return structure for `get_steady_wse()`:**
```python
pd.DataFrame with columns:
    - River (str)
    - Reach (str)
    - Station (str)
    - Profile (str) - only when extracting multiple profiles
    - WSE (float) - water surface elevation
```

### Discover Available Variables

```python
# List all available steady state variables
vars_dict = HdfResultsPlan.list_steady_variables("02")

print(f"Cross section vars: {vars_dict['cross_sections']}")
# ['Water Surface', 'Energy Grade', 'Flow']

print(f"Additional vars: {vars_dict['additional']}")
# ['Velocity Total', 'Velocity Channel', 'Flow Total',
#  'Manning n Channel', 'Hydraulic Depth Total', ...]

print(f"Structure vars: {vars_dict['structures']}")
# (if inline structures present)
```

### Extract Specific Variables

```python
# Get velocity for all profiles
velocity = HdfResultsPlan.get_steady_data("02", variable="Velocity Total")

# Get multiple variables
flow = HdfResultsPlan.get_steady_data("02", variable="Flow")
depth = HdfResultsPlan.get_steady_data("02", variable="Hydraulic Depth Total")
```

### Steady Flow Metadata

```python
# Get plan information and attributes
info = HdfResultsPlan.get_steady_info("02")

# Returns DataFrame with:
#   - Program Version
#   - Solution (e.g., "Steady Finished Successfully")
#   - Flow Title
#   - Flow Filename
#   - Run Time Window
```

## Unsteady Flow Results

### Cross Section Time Series

Extract time series data for all cross sections:

```python
# Get all variables as xarray Dataset
xsec_data = HdfResultsXsec.get_xsec_timeseries("01")

# Access specific variable
wse_ts = xsec_data["Water_Surface"]  # (time, cross_section)
velocity_ts = xsec_data["Velocity_Total"]
flow_ts = xsec_data["Flow"]

# Get specific cross section
target_xs = "Bald Eagle       Loc Hav          136202.3"
wse_at_xs = wse_ts.sel(cross_section=target_xs)

# Convert to pandas for analysis
wse_df = wse_at_xs.to_dataframe()
```

**Return structure for `get_xsec_timeseries()`:**
```python
xarray.Dataset with:
    Dimensions:
        - time (datetime64[ns])
        - cross_section (str)

    Coordinates:
        - time
        - cross_section (full identifier: "River Reach Station")
        - River
        - Reach
        - Station
        - Name
        - Maximum_Water_Surface (max value across all times)
        - Maximum_Flow
        - Maximum_Channel_Velocity
        - Maximum_Velocity_Total

    Data variables:
        - Water_Surface (time, cross_section)
        - Velocity_Total (time, cross_section)
        - Velocity_Channel (time, cross_section)
        - Flow (time, cross_section)
        - Flow_Lateral (time, cross_section)
```

### 2D Mesh Results

#### Maximum Envelopes

```python
# Get maximum water surface over entire simulation
max_wse = HdfResultsMesh.get_mesh_maximum("01", variable="Water Surface")

# Get maximum depth
max_depth = HdfResultsMesh.get_mesh_maximum("01", variable="Depth")

# Get maximum velocity
max_vel = HdfResultsMesh.get_mesh_maximum("01", variable="Velocity")
```

**Return structure for `get_mesh_maximum()`:**
```python
pd.DataFrame with columns:
    - cell_id (int)
    - max_value (float) - maximum value for the variable
    - max_time (datetime64) - when maximum occurred
    - geometry (shapely.Polygon) - cell polygon
```

#### Time Series at Mesh Cells

```python
# Get time series for all cells at specific timesteps
mesh_ts = HdfResultsMesh.get_mesh_timeseries(
    "01",
    timestep_indices=[0, 50, 100, 150],
    variables=["Water Surface", "Depth", "Velocity"]
)

# Get continuous time series (be careful with file size)
mesh_ts_all = HdfResultsMesh.get_mesh_timeseries("01", timestep_indices="all")
```

**Return structure for `get_mesh_timeseries()`:**
```python
pd.DataFrame with columns:
    - cell_id (int)
    - timestep (int)
    - datetime (datetime64)
    - Water_Surface (float)
    - Depth (float)
    - Velocity (float)
    - ... (other requested variables)
```

### Output Times

```python
# Get all output timesteps
times = HdfResultsPlan.get_output_times("01")

# Returns DataFrame with:
#   - timestep (int): 0, 1, 2, ...
#   - datetime (datetime64): timestamp
#   - hours (float): hours since start
```

### Computation Messages

```python
# Extract computation log
messages = HdfResultsPlan.get_compute_messages("01")

# Returns: string with full computation log
# Check for warnings, errors, volume accounting, etc.
```

## Dam Breach Results

### Identify Breach Structures

```python
from ras_commander import HdfStruc

# List SA/2D connections
structures = HdfStruc.list_sa2d_connections("02")

# Get breach capability info
breach_info = HdfStruc.get_sa2d_breach_info("02")
```

**Return structure for `get_sa2d_breach_info()`:**
```python
pd.DataFrame with columns:
    - structure (str)
    - has_breach (bool)
    - breach_at_date (str) - when breach occurred
    - breach_at_time (float) - hours from start
    - centerline_breach (float) - location
```

### Breach Time Series

```python
# Get complete breach time series
breach_ts = HdfResultsBreach.get_breach_timeseries("02", "Dam")

# Includes:
#   - datetime
#   - total_flow (combined weir + breach)
#   - weir_flow
#   - breach_flow
#   - hw (headwater elevation)
#   - tw (tailwater elevation)
#   - bottom_width (breach width evolution)
#   - bottom_elevation
#   - left_slope, right_slope
#   - breach_velocity
#   - breach_flow_area
```

### Breach Summary Statistics

```python
# Get peak values and timing
summary = HdfResultsBreach.get_breach_summary("02", "Dam")

# Returns DataFrame with:
#   - structure
#   - breach_initiated (bool)
#   - breach_at_time (float)
#   - breach_at_date (str)
#   - max_total_flow (float)
#   - max_total_flow_time (datetime)
#   - max_breach_flow (float)
#   - max_breach_flow_time (datetime)
#   - final_breach_width (float)
#   - final_breach_depth (float)
#   - max_hw (float)
#   - max_tw (float)
```

### Breach Geometry Evolution

```python
# Get breach-specific variables over time
breach_geom = HdfResultsBreach.get_breaching_variables("02", "Dam")

# Returns DataFrame with:
#   - datetime
#   - hw, tw
#   - bottom_width (evolution)
#   - bottom_elevation
#   - left_slope, right_slope
#   - breach_flow
#   - breach_velocity
#   - breach_flow_area
```

### Structure Flow Variables

```python
# Get structure hydraulic variables
struct_vars = HdfResultsBreach.get_structure_variables("02", "Dam")

# Returns all available variables for the structure
```

## Common Workflows

### Compare Steady Profiles

```python
# Extract all profiles
wse_all = HdfResultsPlan.get_steady_wse("02")

# Pivot for comparison
wse_pivot = wse_all.pivot_table(
    index=['River', 'Reach', 'Station'],
    columns='Profile',
    values='WSE'
)

# Calculate differences
wse_pivot['Diff_100yr_vs_05yr'] = wse_pivot['100 year'] - wse_pivot['.5 year']

# Find locations with largest differences
top_diff = wse_pivot.nlargest(10, 'Diff_100yr_vs_05yr')
```

### Extract Peak Unsteady Values

```python
# Get cross section time series
xsec_ts = HdfResultsXsec.get_xsec_timeseries("01")

# Find peak WSE at each cross section
peak_wse = xsec_ts["Water_Surface"].max(dim="time")

# Find when peak occurred
peak_time_idx = xsec_ts["Water_Surface"].argmax(dim="time")
peak_times = xsec_ts["time"].isel(time=peak_time_idx)

# Create summary DataFrame
peaks_df = pd.DataFrame({
    'cross_section': peak_wse.cross_section.values,
    'peak_wse': peak_wse.values,
    'peak_time': peak_times.values
})
```

### Create Longitudinal Profile

```python
# Extract specific timestep
xsec_ts = HdfResultsXsec.get_xsec_timeseries("01")

# Get data at specific time
timestep_idx = 100
wse_profile = xsec_ts["Water_Surface"].isel(time=timestep_idx)

# Plot WSE vs station
import matplotlib.pyplot as plt
plt.plot(xsec_ts["Station"].values, wse_profile.values)
plt.xlabel("Station (ft)")
plt.ylabel("Water Surface Elevation (ft)")
plt.gca().invert_xaxis()  # Upstream on left
```

### Analyze Breach Scenarios

```python
# Compare multiple breach simulations
plans = ["02", "03", "04"]
breach_summaries = []

for plan in plans:
    summary = HdfResultsBreach.get_breach_summary(plan, "Dam")
    summary['plan'] = plan
    breach_summaries.append(summary)

comparison = pd.concat(breach_summaries, ignore_index=True)

# Compare peak flows
print(comparison[['plan', 'max_breach_flow', 'final_breach_width']])
```

## Integration with hdf-analyst Subagent

For complex analysis, coordinate with the hdf-analyst subagent:

```python
# You (extracting-hecras-results skill) handle:
# - Basic extraction
# - Standard workflows
# - Common patterns

# Delegate to hdf-analyst for:
# - Custom HDF path navigation
# - Advanced xarray operations
# - Performance optimization
# - Specialized analysis
```

## Reference Documentation

- **Detailed API**: [reference/api.md](reference/api.md) - Complete method signatures and parameters
- **Steady vs Unsteady**: [reference/steady-vs-unsteady.md](reference/steady-vs-unsteady.md) - Detection methods and extraction patterns
- **Examples**:
  - [examples/steady.py](examples/steady.py) - Steady flow extraction
  - [examples/unsteady.py](examples/unsteady.py) - Unsteady time series

## Related Skills

- **executing-hecras-plans**: Run simulations to generate HDF results
- **hdf-analyst**: Advanced HDF file operations and custom analysis

## Common Issues

**Issue**: Structure names differ between plan files and HDF
- **Solution**: Use `HdfStruc.list_sa2d_connections()` to get HDF names
- **Example**: Plan file "Dam" might be "BaldEagleCr Dam" in HDF

**Issue**: Missing data for some timesteps
- **Solution**: Check if simulation completed successfully with `get_compute_messages()`
- **Example**: Partial runs may have fewer timesteps than expected

**Issue**: Large memory usage with mesh time series
- **Solution**: Extract specific timesteps only, not all
- **Example**: Use `timestep_indices=[0, 50, 100]` instead of `timestep_indices="all"`

**Issue**: Cannot find specific variable
- **Solution**: Use `list_steady_variables()` or inspect HDF structure
- **Example**: Variable names differ between HEC-RAS versions

## See Also

- `C:\GH\ras-commander\ras_commander\hdf\AGENTS.md` - HDF subpackage developer guidance
- `C:\GH\ras-commander\examples\19_steady_flow_analysis.ipynb` - Complete steady workflow
- `C:\GH\ras-commander\examples\03_unsteady_flow_operations.ipynb` - Complete unsteady workflow
- `C:\GH\ras-commander\examples\18_breach_results_extraction.ipynb` - Complete breach workflow
