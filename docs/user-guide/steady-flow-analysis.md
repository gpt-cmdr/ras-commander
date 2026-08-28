# Steady Flow Analysis

RAS Commander supports extraction and analysis of steady flow results from HEC-RAS HDF files.

## Overview

Steady flow analysis produces water surface profiles for multiple flow scenarios (profiles) rather than time-varying results. RAS Commander provides methods to:

- Detect steady vs. unsteady plans
- Extract profile names
- Retrieve water surface elevations
- Access flow metadata

## Detecting Steady Plans

```python
from ras_commander import HdfResultsPlan, init_ras_project, RasPlan

init_ras_project("/path/to/project", "6.5")

# Get HDF path
hdf_path = RasPlan.get_results_path("01")

# Check if steady state
is_steady = HdfResultsPlan.is_steady_plan(hdf_path)
print(f"Plan 01 is {'steady' if is_steady else 'unsteady'}")
```

## Profile Names

```python
if HdfResultsPlan.is_steady_plan(hdf_path):
    # Get profile names
    profiles = HdfResultsPlan.get_steady_profile_names(hdf_path)
    print(f"Profiles: {profiles}")
    # Example: ['PF 1', 'PF 2', 'PF 3', ...]
```

## Water Surface Elevations

```python
# Get WSE for all profiles
wse_df = HdfResultsPlan.get_steady_wse(hdf_path)
print(wse_df)

# Columns include:
# - river
# - reach
# - station (river station)
# - WSE for each profile (PF 1, PF 2, etc.)
```

### Example Output

```
    river       reach    station    PF 1    PF 2    PF 3
0   Big Creek   Upper    1000.0    105.2   106.1   107.3
1   Big Creek   Upper    900.0     104.8   105.6   106.9
2   Big Creek   Upper    800.0     104.3   105.1   106.4
...
```

## Steady Flow Metadata

```python
# Get steady flow information
info = HdfResultsPlan.get_steady_info(hdf_path)
print(info)

# Returns dictionary with:
# - num_profiles: Number of profiles
# - profile_names: List of profile names
# - num_reaches: Number of reaches
# - reach_names: List of reach names
```

## Complete Cross-Section Results Without COM

`get_steady_results()` reads the modern plan HDF directly and returns one row
per profile and cross section:

```python
results = HdfResultsPlan.get_steady_results(hdf_path)
results = results[
    [
        "river", "reach", "node_id", "profile", "wsel", "flow",
        "max_depth", "channel_length",
    ]
]
```

`max_depth` is the HEC-RAS `Maximum Depth Total` result. This is distinct from
`hydraulic_depth`, which is also returned from `Hydraulic Depth Channel`.
`channel_length` is joined from geometry cross-section attributes using the
full `(river, reach, station)` identity; HEC-RAS non-finite terminal reach-length
sentinels are normalized to zero.

The selected sources are recorded on the returned DataFrame:

```python
print(results.attrs["max_depth_source"])
print(results.attrs["channel_length_source"])
```

HEC-RAS layouts without `Maximum Depth Total` use `Hydraulic Depth Channel` as
an explicit legacy fallback and record that fallback in `max_depth_source`.

## Complete Workflow

```python
from ras_commander import (
    init_ras_project, RasExamples, RasCmdr,
    RasPlan, HdfResultsPlan
)
import matplotlib.pyplot as plt

# Setup
path = RasExamples.extract_project("Bald Eagle Creek")
init_ras_project(path, "6.5")

# Find and run a steady plan
steady_plans = []
for _, row in ras.plan_df.iterrows():
    plan_hdf = row['hdf_path']
    if plan_hdf and HdfResultsPlan.is_steady_plan(plan_hdf):
        steady_plans.append(row['plan_number'])

if steady_plans:
    plan = steady_plans[0]
    print(f"Running steady plan: {plan}")

    # Execute
    RasCmdr.compute_plan(plan)

    # Extract results
    hdf_path = RasPlan.get_results_path(plan)

    # Get profiles
    profiles = HdfResultsPlan.get_steady_profile_names(hdf_path)
    print(f"Profiles computed: {profiles}")

    # Get water surface
    wse = HdfResultsPlan.get_steady_wse(hdf_path)

    # Plot profile comparison
    fig, ax = plt.subplots(figsize=(12, 6))

    for profile in profiles[:3]:  # First 3 profiles
        ax.plot(wse['station'], wse[profile], label=profile)

    ax.set_xlabel('River Station')
    ax.set_ylabel('Water Surface Elevation (ft)')
    ax.set_title('Steady Flow Water Surface Profiles')
    ax.legend()
    ax.invert_xaxis()  # Upstream on left
    plt.show()
```

## Comparison with Unsteady

| Aspect | Steady | Unsteady |
|--------|--------|----------|
| Output | Multiple profiles | Time series |
| Detection | `is_steady_plan()` | `not is_steady_plan()` |
| WSE extraction | `get_steady_wse()` | `HdfResultsXsec.get_xsec_timeseries()` |
| Profiles | Named (PF 1, PF 2) | Timesteps |

## Legacy Steady Flow (RasControl)

For HEC-RAS 3.x-5.x steady flow using the COM interface:

```python
from ras_commander import RasControl, init_ras_project

# Initialize with legacy version
init_ras_project("/path/to/project", "4.1")

# Run steady plan
success, messages = RasControl.run_plan("02")

# Extract steady results via COM
results_df = RasControl.get_steady_results("02")
print(results_df)

# Columns: river, reach, station, profile, wse, velocity, flow, etc.
```

See [Legacy COM Interface](legacy-com-interface.md) for complete RasControl documentation.

## Notes

- Steady flow support was added in v0.80.3+
- Works with HEC-RAS 6.x+ HDF files
- `Maximum Depth Total` and geometry `Len Channel` semantics are regression
  tested against immutable HEC-RAS 6.0.0, 6.3.1, 6.4.1, 6.6, and 7.0 fixtures.
  The current CLB catalog contains no computed steady-result HDF from 6.1,
  6.2, or 6.5, so those exact releases remain explicit fixture gaps.
- For legacy versions (3.x-5.x), use `RasControl.get_steady_results()`
- See `examples/19_steady_flow_analysis.ipynb` for complete examples
