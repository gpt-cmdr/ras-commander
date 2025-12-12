# Steady vs Unsteady Flow Results

Understanding the differences between steady state and unsteady flow result extraction.

## Detection Methods

### Automatic Plan Type Detection

Always start by checking the plan type:

```python
from ras_commander import HdfResultsPlan

# Check if plan is steady or unsteady
is_steady = HdfResultsPlan.is_steady_plan("02")

if is_steady:
    print("Extracting steady state results...")
    # Use steady-specific methods
else:
    print("Extracting unsteady results...")
    # Use time series methods
```

### Plan Information Method

Alternative approach using plan metadata:

```python
plan_info = HdfResultsPlan.get_plan_info("02")
run_type = plan_info['Type of Run'].iloc[0]

if "Steady" in run_type:
    # Steady flow workflow
    pass
elif "Unsteady" in run_type:
    # Unsteady flow workflow
    pass
```

## Steady State Extraction Patterns

### Profile-Based Results

Steady state simulations produce **profiles** (not time series):

```python
# List available profiles
profiles = HdfResultsPlan.get_steady_profile_names("02")
# Example: ['.5 year', '1 year', '2 year', '5 year', '10 year', '25 year', '50 year', '100 year']

# Extract single profile
wse_100yr = HdfResultsPlan.get_steady_wse("02", profile_name="100 year")

# Extract all profiles
wse_all = HdfResultsPlan.get_steady_wse("02")
```

### Available Variables

Discover what data is available:

```python
vars_dict = HdfResultsPlan.list_steady_variables("02")

# Cross section variables (basic)
print(vars_dict['cross_sections'])
# ['Water Surface', 'Energy Grade', 'Flow']

# Additional variables (detailed)
print(vars_dict['additional'])
# ['Velocity Total', 'Velocity Channel', 'Flow Total', 'Flow Channel',
#  'Flow Left OB', 'Flow Right OB', 'Manning n Channel', 'Manning n Left OB',
#  'Hydraulic Depth Total', 'Hydraulic Radius Total', 'Top Width Total', ...]

# Structure variables (if inline structures present)
print(vars_dict['structures'])
```

### Extract Specific Variables

```python
# Water surface elevation (most common)
wse = HdfResultsPlan.get_steady_wse("02", profile_name="100 year")

# Velocity
velocity = HdfResultsPlan.get_steady_data("02", variable="Velocity Total", profile_name="100 year")

# Flow
flow = HdfResultsPlan.get_steady_data("02", variable="Flow Total", profile_name="100 year")

# Depth
depth = HdfResultsPlan.get_steady_data("02", variable="Hydraulic Depth Total", profile_name="100 year")

# Manning's n
mannings = HdfResultsPlan.get_steady_data("02", variable="Manning n Channel", profile_name="100 year")
```

### Common Steady Workflows

#### Compare Return Periods

```python
# Extract all profiles
wse_all = HdfResultsPlan.get_steady_wse("02")

# Pivot for easy comparison
wse_pivot = wse_all.pivot_table(
    index=['River', 'Reach', 'Station'],
    columns='Profile',
    values='WSE'
)

# Calculate differences
wse_pivot['Diff_100yr_vs_05yr'] = wse_pivot['100 year'] - wse_pivot['.5 year']

# Find locations with largest increase
critical_sections = wse_pivot.nlargest(10, 'Diff_100yr_vs_05yr')
```

#### Profile Progression Analysis

```python
# Extract specific station
station_data = wse_all[wse_all['Station'] == '136202.3']

# Plot WSE vs return period
import matplotlib.pyplot as plt
plt.plot(range(len(profiles)), station_data['WSE'])
plt.xticks(range(len(profiles)), profiles, rotation=45)
plt.ylabel("WSE (ft)")
plt.xlabel("Return Period")
```

## Unsteady Flow Extraction Patterns

### Time Series Results

Unsteady simulations produce **time series** (not profiles):

```python
# Get cross section time series
xsec_ts = HdfResultsXsec.get_xsec_timeseries("01")

# Access as xarray Dataset
wse_ts = xsec_ts["Water_Surface"]  # (time, cross_section)
velocity_ts = xsec_ts["Velocity_Total"]
flow_ts = xsec_ts["Flow"]
```

### Available Variables

Unsteady cross section variables are fixed:
- `Water_Surface`
- `Velocity_Total`
- `Velocity_Channel`
- `Flow`
- `Flow_Lateral`

Plus coordinate data:
- `Maximum_Water_Surface` (max over all times)
- `Maximum_Flow`
- `Maximum_Channel_Velocity`
- `Maximum_Velocity_Total`

### Extract Specific Locations and Times

```python
# Get specific cross section
target_xs = "Bald Eagle       Loc Hav          136202.3"
wse_at_xs = xsec_ts["Water_Surface"].sel(cross_section=target_xs)

# Get specific time range
start_time = pd.Timestamp("1999-01-02 00:00:00")
end_time = pd.Timestamp("1999-01-03 00:00:00")
wse_subset = xsec_ts["Water_Surface"].sel(time=slice(start_time, end_time))

# Convert to DataFrame for analysis
df = wse_at_xs.to_dataframe()
```

### 2D Mesh Results

For 2D flow areas:

```python
# Maximum envelope (most common)
max_wse = HdfResultsMesh.get_mesh_maximum("01", variable="Water Surface")
max_depth = HdfResultsMesh.get_mesh_maximum("01", variable="Depth")
max_velocity = HdfResultsMesh.get_mesh_maximum("01", variable="Velocity")

# Time series at specific cells (use sparingly - large data)
mesh_ts = HdfResultsMesh.get_mesh_timeseries(
    "01",
    timestep_indices=[0, 50, 100, 150],  # Don't use "all" unless necessary
    variables=["Water Surface", "Depth"]
)
```

### Common Unsteady Workflows

#### Peak Analysis at Cross Sections

```python
# Get cross section time series
xsec_ts = HdfResultsXsec.get_xsec_timeseries("01")

# Find peak WSE at each cross section
peak_wse = xsec_ts["Water_Surface"].max(dim="time")

# Find when peak occurred
peak_time_idx = xsec_ts["Water_Surface"].argmax(dim="time")
peak_times = xsec_ts["time"].isel(time=peak_time_idx)

# Create summary
peaks_df = pd.DataFrame({
    'cross_section': peak_wse.cross_section.values,
    'river': xsec_ts["River"].values,
    'reach': xsec_ts["Reach"].values,
    'station': xsec_ts["Station"].values,
    'peak_wse': peak_wse.values,
    'peak_time': peak_times.values
})
```

#### Hydrograph at Specific Location

```python
# Extract specific cross section
target_xs = "Bald Eagle       Loc Hav          136202.3"
flow_ts = xsec_ts["Flow"].sel(cross_section=target_xs)

# Plot hydrograph
plt.figure(figsize=(12, 6))
plt.plot(flow_ts.time, flow_ts.values)
plt.ylabel("Flow (cfs)")
plt.xlabel("Time")
plt.title(f"Flow Hydrograph at {target_xs}")
plt.xticks(rotation=45)
```

#### Compare Multiple Simulations

```python
# Extract from multiple plans
plans = ["01", "02", "03"]
results = {}

for plan in plans:
    xsec_ts = HdfResultsXsec.get_xsec_timeseries(plan)
    target_data = xsec_ts["Water_Surface"].sel(cross_section=target_xs)
    results[f"Plan {plan}"] = target_data

# Plot comparison
plt.figure(figsize=(14, 7))
for plan_name, data in results.items():
    plt.plot(data.time, data.values, label=plan_name, linewidth=2)
plt.legend()
plt.ylabel("WSE (ft)")
plt.xlabel("Time")
```

## Key Differences Summary

| Aspect | Steady State | Unsteady Flow |
|--------|-------------|---------------|
| **Output Type** | Profiles (e.g., "100 year") | Time series (datetime) |
| **Detection** | `is_steady_plan()` returns True | `is_steady_plan()` returns False |
| **Primary Method** | `get_steady_wse()` | `get_xsec_timeseries()` |
| **Variable Discovery** | `list_steady_variables()` | Fixed set (WSE, Vel, Flow) |
| **Data Structure** | DataFrame (River, Reach, Station, Profile, Value) | xarray.Dataset (time, cross_section) |
| **Common Analysis** | Compare return periods | Analyze peaks and timing |
| **2D Results** | Not applicable | `get_mesh_maximum()`, `get_mesh_timeseries()` |

## Workflow Decision Tree

```
Start
  │
  ├─→ is_steady_plan() == True?
  │    │
  │    ├─→ Yes: STEADY STATE WORKFLOW
  │    │    ├─ List profiles: get_steady_profile_names()
  │    │    ├─ Extract WSE: get_steady_wse()
  │    │    ├─ Discover vars: list_steady_variables()
  │    │    └─ Extract vars: get_steady_data()
  │    │
  │    └─→ No: UNSTEADY FLOW WORKFLOW
  │         ├─ 1D results: get_xsec_timeseries()
  │         ├─ 2D results: get_mesh_maximum() or get_mesh_timeseries()
  │         ├─ Breach results: get_breach_timeseries()
  │         └─ Timesteps: get_output_times()
  │
  └─→ Extract metadata: get_plan_info(), get_compute_messages()
```

## Best Practices

### For Steady State

1. **Always list profiles first**: Understand what return periods are available
2. **Extract all profiles at once**: More efficient than individual queries
3. **Use pivot tables**: Best way to compare profiles across locations
4. **Check variable names**: Use `list_steady_variables()` before extraction

### For Unsteady

1. **Use xarray for analysis**: Leverage xarray's powerful selection and aggregation
2. **Extract specific timesteps**: Avoid memory issues with large 2D meshes
3. **Use maximum envelopes**: Usually sufficient for 2D analysis
4. **Check output times**: Ensure simulation completed successfully

### Universal

1. **Always check plan type**: Use `is_steady_plan()` first
2. **Read computation messages**: Verify simulation success
3. **Validate results**: Check for reasonable values
4. **Use appropriate tools**: Don't try to extract time series from steady plans

## Common Mistakes

### Attempting Time Series from Steady Plans

**Wrong:**
```python
# This will fail - steady plans don't have time series
xsec_ts = HdfResultsXsec.get_xsec_timeseries("02")  # Plan 02 is steady
```

**Correct:**
```python
# Check plan type first
if HdfResultsPlan.is_steady_plan("02"):
    wse = HdfResultsPlan.get_steady_wse("02")
else:
    xsec_ts = HdfResultsXsec.get_xsec_timeseries("02")
```

### Extracting All Mesh Timesteps

**Wrong (memory intensive):**
```python
# Will consume massive memory for large meshes
mesh_ts = HdfResultsMesh.get_mesh_timeseries("01", timestep_indices="all")
```

**Correct:**
```python
# Use maximum envelope for most analyses
max_wse = HdfResultsMesh.get_mesh_maximum("01", variable="Water Surface")

# Or extract specific timesteps if needed
mesh_ts = HdfResultsMesh.get_mesh_timeseries("01", timestep_indices=[0, 50, 100])
```

### Assuming Variable Names

**Wrong:**
```python
# Variable name might not exist
velocity = HdfResultsPlan.get_steady_data("02", variable="Velocity")  # Fails
```

**Correct:**
```python
# Discover available variables first
vars_dict = HdfResultsPlan.list_steady_variables("02")
print(vars_dict['additional'])
# Use exact name: "Velocity Total"
velocity = HdfResultsPlan.get_steady_data("02", variable="Velocity Total")
```
