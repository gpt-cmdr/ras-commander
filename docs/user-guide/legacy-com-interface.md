# Legacy COM Interface

The `RasControl` class provides access to HEC-RAS 3.x-6.x via the HECRASController COM interface.

## Overview

For older HEC-RAS versions that don't support command-line execution or HDF output, RasControl provides:

- Plan execution via COM automation
- Steady state profile extraction
- Unsteady time series extraction
- Version migration validation

## Supported Versions

| Version | Support |
|---------|---------|
| 3.1 | Full |
| 4.1 | Full |
| 5.0.x (501-507) | Full |
| 6.0 | Full |
| 6.3 | Full |
| 6.6 | Full |

## Initialization

```python
from ras_commander import init_ras_project, RasControl

# Initialize with version number
init_ras_project("/path/to/project", "4.1")

# Or with specific version code
init_ras_project("/path/to/project", "506")  # HEC-RAS 5.0.6
```

## Running Plans

```python
# Run a plan (uses plan number, not file path)
success, messages = RasControl.run_plan("02")

if success:
    print("Plan completed successfully")
else:
    print(f"Plan failed: {messages}")
```

The COM interface:
1. Opens HEC-RAS in the background
2. Loads the project
3. Sets the current plan
4. Executes the plan
5. Closes HEC-RAS

## Steady State Results

```python
# Extract steady state profiles
results = RasControl.get_steady_results("02")
print(results)

# DataFrame columns:
# - river
# - reach
# - station
# - profile (PF 1, PF 2, etc.)
# - wse (water surface elevation)
# - velocity
# - flow
# - area
# - top_width
```

### Plot Steady Profiles

```python
import matplotlib.pyplot as plt

results = RasControl.get_steady_results("02")

# Plot water surface for each profile
fig, ax = plt.subplots(figsize=(12, 6))

for profile in results['profile'].unique():
    profile_data = results[results['profile'] == profile]
    ax.plot(
        profile_data['station'],
        profile_data['wse'],
        label=profile
    )

ax.set_xlabel('River Station')
ax.set_ylabel('Water Surface Elevation (ft)')
ax.set_title('Steady Flow Profiles')
ax.legend()
ax.invert_xaxis()  # Upstream on left
plt.show()
```

## Unsteady Results

```python
# Get available output times
times = RasControl.get_output_times("01")
print(f"Available times: {times}")
# Includes special "Max WS" timestep

# Extract unsteady results
results = RasControl.get_unsteady_results("01", max_times=20)
print(results)

# DataFrame columns:
# - river
# - reach
# - station
# - time (datetime or "Max WS")
# - wse
# - velocity
# - flow
```

### Plot Time Series at Cross Section

```python
import matplotlib.pyplot as plt

results = RasControl.get_unsteady_results("01", max_times=50)

# Filter to single cross section (exclude Max WS)
station = 1000.0
xs_data = results[
    (results['station'] == station) &
    (results['time'] != "Max WS")
]

fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

axes[0].plot(xs_data['time'], xs_data['wse'])
axes[0].set_ylabel('Water Surface (ft)')
axes[0].set_title(f'Station {station}')

axes[1].plot(xs_data['time'], xs_data['flow'])
axes[1].set_ylabel('Flow (cfs)')
axes[1].set_xlabel('Time')

plt.tight_layout()
plt.show()
```

## Setting Current Plan

```python
# Set by plan title
RasControl.set_current_plan("Steady Flow Run")

# Then perform operations
results = RasControl.get_steady_results()  # Uses current plan
```

## Version Comparison Workflow

Compare results between HEC-RAS versions for migration validation:

```python
from ras_commander import init_ras_project, RasControl, RasPrj
import pandas as pd

versions = ["4.1", "5.0.6", "6.6"]
all_results = {}

for version in versions:
    project = RasPrj()
    init_ras_project("/path/to/project", version, ras_object=project)

    # Run plan
    success, _ = RasControl.run_plan("02", ras_object=project)

    if success:
        results = RasControl.get_steady_results("02", ras_object=project)
        all_results[version] = results

# Compare WSE at key stations
compare_df = pd.DataFrame()
for version, results in all_results.items():
    wse_col = results.groupby('station')['wse'].mean()
    compare_df[version] = wse_col

print("WSE Comparison by Version:")
print(compare_df)

# Calculate differences
compare_df['diff_4.1_to_6.6'] = compare_df['6.6'] - compare_df['4.1']
print(f"\nMax difference: {compare_df['diff_4.1_to_6.6'].abs().max():.2f} ft")
```

## Open-Operate-Close Pattern

RasControl uses an open-operate-close pattern to prevent conflicts:

```python
# Each operation is self-contained
success1, _ = RasControl.run_plan("01")  # Opens, runs, closes
success2, _ = RasControl.run_plan("02")  # Opens, runs, closes

# No lingering HEC-RAS windows
```

## Integration with Modern Workflow

Combine RasControl (legacy) with modern RAS Commander features:

```python
from ras_commander import (
    init_ras_project, RasControl, RasCmdr, ras
)

# For legacy extraction
init_ras_project("/path/to/old_project", "4.1")
legacy_results = RasControl.get_steady_results("01")

# For modern execution
init_ras_project("/path/to/new_project", "6.6")
RasCmdr.compute_plan("01")

# Use HDF extraction for modern results
from ras_commander import HdfResultsPlan
modern_wse = HdfResultsPlan.get_steady_wse(ras.plan_df['hdf_path'].iloc[0])
```

## Error Handling

```python
from ras_commander import RasControl

try:
    success, messages = RasControl.run_plan("99")  # Non-existent
except ValueError as e:
    print(f"Plan not found: {e}")
except RuntimeError as e:
    if "COM" in str(e):
        print("COM interface error - check HEC-RAS installation")
    else:
        raise
```

## Requirements

- Windows operating system
- HEC-RAS installed (version you want to use)
- pywin32 package: `pip install pywin32`

## Limitations

- Windows only (COM interface)
- One HEC-RAS instance at a time per version
- No direct HDF access (use file-based output)
- Slower than command-line execution

## See Also

- `examples/17_extracting_profiles_with_hecrascontroller.ipynb`
- [Plan Execution](plan-execution.md) - Modern execution methods
- [Steady Flow Analysis](steady-flow-analysis.md) - HDF-based steady results
