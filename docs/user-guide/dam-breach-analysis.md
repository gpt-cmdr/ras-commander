# Dam Breach Analysis

RAS Commander provides tools for both modifying dam breach parameters and extracting breach results.

## Architecture

The library separates breach operations into two classes:

| Class | File Type | Purpose |
|-------|-----------|---------|
| `RasBreach` | Plan files (.p##) | Modify breach **parameters** |
| `HdfResultsBreach` | HDF files (.p##.hdf) | Extract breach **results** |

!!! note "Naming Differences"
    Structure names may differ between plan files and HDF results. Always verify names in both sources.

## Modifying Breach Parameters

### List Breach Structures

```python
from ras_commander import RasBreach, init_ras_project

init_ras_project("/path/to/project", "6.5")

# List structures with breach data in plan file
structures = RasBreach.list_breach_structures_plan("01")
print(structures)
# Example: ['Dam1', 'Dam2', 'Levee North']
```

### Read Breach Block

```python
# Get breach parameters for a structure
params = RasBreach.read_breach_block("01", "Dam1")
print(params)

# Returns dictionary with:
# - breach_mode: Overtopping, Piping, etc.
# - start_time: Breach initiation time
# - formation_time: Time to full breach
# - bottom_elevation: Final breach bottom
# - bottom_width: Final breach width
# - left_slope, right_slope: Side slopes
# - weir_coefficient: Breach weir coefficient
# - piping_coefficient: (if piping mode)
# - trigger_elevation: (if overtopping)
```

### Update Breach Parameters

```python
# Modify breach parameters
RasBreach.update_breach_block(
    plan_number="01",
    structure_name="Dam1",
    start_time=10.0,           # Hours from simulation start
    formation_time=2.0,        # Hours for breach to fully form
    bottom_elevation=850.0,    # Final breach bottom (ft)
    bottom_width=100.0,        # Final breach width (ft)
    left_slope=1.0,            # H:V ratio
    right_slope=1.0
)
```

### Batch Parameter Updates

```python
# Define sensitivity scenarios
scenarios = [
    {"formation_time": 1.0, "name": "Fast"},
    {"formation_time": 2.0, "name": "Medium"},
    {"formation_time": 4.0, "name": "Slow"},
]

for scenario in scenarios:
    # Clone plan
    new_plan = RasPlan.clone_plan("01", new_plan_shortid=scenario["name"])

    # Update breach
    RasBreach.update_breach_block(
        new_plan,
        "Dam1",
        formation_time=scenario["formation_time"]
    )

    # Execute
    RasCmdr.compute_plan(new_plan, dest_folder=f"./breach_{scenario['name']}")
```

## Extracting Breach Results

### Breach Time Series

```python
from ras_commander import HdfResultsBreach, RasPlan

hdf_path = RasPlan.get_results_path("01")

# Get complete breach time series
ts = HdfResultsBreach.get_breach_timeseries(hdf_path, "Dam1")
print(ts.columns)
# Includes: time, breach_flow, breach_stage, breach_width, breach_depth, etc.

# Plot breach flow
import matplotlib.pyplot as plt
ts.plot(x='time', y='breach_flow')
plt.title("Dam Breach Hydrograph")
plt.xlabel("Time (hours)")
plt.ylabel("Flow (cfs)")
plt.show()
```

### Breach Summary Statistics

```python
# Get summary statistics
summary = HdfResultsBreach.get_breach_summary(hdf_path, "Dam1")
print(summary)

# Returns:
# - peak_flow: Maximum breach discharge
# - peak_flow_time: Time of peak
# - peak_stage: Maximum stage at breach
# - total_volume: Total volume through breach
# - max_width: Maximum breach width
# - final_bottom: Final breach bottom elevation
```

### Breach Geometry Evolution

```python
# Get breach geometry over time
geometry = HdfResultsBreach.get_breaching_variables(hdf_path, "Dam1")
print(geometry.columns)
# Includes: time, bottom_elevation, top_width, side_slopes

# Plot breach evolution
fig, axes = plt.subplots(2, 1, figsize=(10, 8))

geometry.plot(x='time', y='bottom_elevation', ax=axes[0])
axes[0].set_ylabel("Bottom Elevation (ft)")
axes[0].set_title("Breach Evolution")

geometry.plot(x='time', y='top_width', ax=axes[1])
axes[1].set_ylabel("Top Width (ft)")
axes[1].set_xlabel("Time (hours)")

plt.tight_layout()
plt.show()
```

### Structure Flow Variables

```python
# Get structure flow variables
flow_vars = HdfResultsBreach.get_structure_variables(hdf_path, "Dam1")
print(flow_vars.columns)
# Includes: time, headwater, tailwater, flow, velocity
```

## Complete Workflow

```python
from ras_commander import (
    init_ras_project, RasExamples, RasCmdr, RasPlan,
    RasBreach, HdfResultsBreach
)
import matplotlib.pyplot as plt
import pandas as pd

# Setup with dam breach example
path = RasExamples.extract_project("Dam Breaching")
init_ras_project(path, "6.5")

# Find plan with breach
plan = "01"  # Adjust based on project

# Check current breach parameters
structures = RasBreach.list_breach_structures_plan(plan)
print(f"Structures with breach: {structures}")

if structures:
    dam = structures[0]
    params = RasBreach.read_breach_block(plan, dam)
    print(f"\nCurrent parameters for {dam}:")
    for k, v in params.items():
        print(f"  {k}: {v}")

    # Run the plan
    success = RasCmdr.compute_plan(plan, dest_folder="./breach_run")

    if success:
        # Extract results
        hdf_path = RasPlan.get_results_path(plan)

        # Summary
        summary = HdfResultsBreach.get_breach_summary(hdf_path, dam)
        print(f"\nBreach Summary:")
        print(f"  Peak Flow: {summary['peak_flow']:,.0f} cfs")
        print(f"  Peak Time: {summary['peak_flow_time']:.1f} hours")

        # Time series
        ts = HdfResultsBreach.get_breach_timeseries(hdf_path, dam)

        # Plot
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

        ts.plot(x='time', y='breach_flow', ax=axes[0], legend=False)
        axes[0].set_ylabel("Breach Flow (cfs)")
        axes[0].set_title(f"Dam Breach Results - {dam}")

        ts.plot(x='time', y='breach_stage', ax=axes[1], legend=False)
        axes[1].set_ylabel("Stage (ft)")
        axes[1].set_xlabel("Time (hours)")

        plt.tight_layout()
        plt.savefig("breach_results.png", dpi=150)
        plt.show()
```

## Important Notes

1. **Structure naming**: Plan file names may differ from HDF result names
2. **Breach modes**: Overtopping, Piping, and user-defined triggers are supported
3. **Units**: All parameters use project units (typically ft, cfs)
4. **Version**: Dam breach operations added in v0.81.0+

## See Also

- `examples/18_breach_results_extraction.ipynb` - Complete workflow examples
- [HDF Data Extraction](hdf-data-extraction.md) - General HDF access
- [Plan Execution](plan-execution.md) - Running breach scenarios
