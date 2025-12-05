# Working with Boundary Conditions

Boundary conditions define the upstream and downstream hydraulic conditions for HEC-RAS models. The ras-commander library provides tools to access, analyze, and modify boundary conditions through the `boundaries_df` dataframe and the `RasUnsteady` class.

## Overview

Boundary conditions in HEC-RAS can include:

- **Flow Hydrographs**: Time-series flow data at upstream locations
- **Stage Hydrographs**: Time-series water surface elevation data
- **Normal Depth**: Downstream boundary defined by slope
- **Rating Curves**: Stage-discharge relationships
- **Gate Operations**: Time-varying gate openings
- **Lateral Inflows**: Distributed flow inputs
- **Storage Area Connections**: Time-varying elevations or flows

!!! info "Read-Only Access"
    The `boundaries_df` dataframe provides read-only access to boundary condition metadata. To modify boundary condition data, use the `RasUnsteady` class methods.

## Accessing Boundary Conditions

After initializing a RAS project, boundary condition metadata is available through `ras.boundaries_df`:

```python
from ras_commander import init_ras_project, ras

# Initialize project
init_ras_project(r"C:\HEC\projects\MyProject\MyProject.prj", "6.5")

# Access boundary conditions
boundary_conditions = ras.boundaries_df

if boundary_conditions is not None and not boundary_conditions.empty:
    print(f"Found {len(boundary_conditions)} boundary conditions:")
    print(boundary_conditions.head())
else:
    print("No boundary conditions found or unsteady flow files not present")
```

!!! tip "Project Requirements"
    Boundary conditions are only available for projects with unsteady flow files (.u##). Steady flow models do not have boundary conditions in the same format.

## Understanding the Boundaries DataFrame

The `boundaries_df` dataframe contains comprehensive metadata about each boundary condition:

### Key Columns

| Column | Description | Example Values |
|--------|-------------|----------------|
| `unsteady_number` | Links to unsteady flow file (.u##) | "01", "02" |
| `boundary_condition_number` | Sequential ID for each BC | 1, 2, 3... |
| `river_reach_name` | River/reach name (for river BCs) | "Muncie", "Tributary" |
| `river_station` | River station (for river BCs) | "10000", "5280.5" |
| `storage_area_name` | Storage area name (for SA BCs) | "Detention Basin 1" |
| `pump_station_name` | Pump station name (for pump BCs) | "Pump 1" |
| `bc_type` | Boundary condition type | "Flow Hydrograph", "Stage Hydrograph" |
| `hydrograph_type` | Specific hydrograph format | "1", "2", "3" |
| `Interval` | Time interval for data | "1HOUR", "15MIN", "1DAY" |
| `hydrograph_num_values` | Number of data points | 48, 96, 168 |
| `hydrograph_name` | Optional name/description | "100-Year Event" |
| `DSS_path` | Path to DSS file (if applicable) | "/A/B/C/01JAN2000/1HOUR/F/" |

### Example Output

```python
print(boundary_conditions.columns.tolist())
# Output:
# ['unsteady_number', 'boundary_condition_number', 'river_reach_name',
#  'river_station', 'storage_area_name', 'pump_station_name', 'bc_type',
#  'hydrograph_type', 'Interval', 'hydrograph_num_values', 'hydrograph_name',
#  'DSS_path', ...]
```

## Filtering Boundary Conditions by Type

Use pandas filtering to isolate specific boundary condition types:

### Flow Hydrographs

```python
# Get all flow hydrographs
flow_hydrographs = boundary_conditions[
    boundary_conditions['bc_type'] == 'Flow Hydrograph'
]

print(f"\nFlow Hydrographs ({len(flow_hydrographs)}):")
print(flow_hydrographs[[
    'river_reach_name',
    'river_station',
    'hydrograph_num_values',
    'Interval'
]])
```

### Stage Hydrographs

```python
# Get all stage hydrographs
stage_hydrographs = boundary_conditions[
    boundary_conditions['bc_type'] == 'Stage Hydrograph'
]

print(f"\nStage Hydrographs ({len(stage_hydrographs)}):")
print(stage_hydrographs[[
    'river_reach_name',
    'river_station',
    'hydrograph_num_values'
]])
```

### Normal Depth Boundaries

```python
# Get normal depth boundaries (downstream)
normal_depth = boundary_conditions[
    boundary_conditions['bc_type'] == 'Normal Depth'
]

print(f"\nNormal Depth Boundaries ({len(normal_depth)}):")
print(normal_depth[['river_reach_name', 'river_station']])
```

### DSS-Linked Boundaries

```python
# Find boundaries linked to DSS files
dss_boundaries = boundary_conditions[
    boundary_conditions['DSS_path'].notna()
]

print(f"\nDSS-Linked Boundaries ({len(dss_boundaries)}):")
print(dss_boundaries[[
    'river_reach_name',
    'river_station',
    'bc_type',
    'DSS_path'
]])
```

## Analyzing Boundary Data

### Summary Statistics

```python
import pandas as pd

# Count boundary types
bc_type_counts = boundary_conditions['bc_type'].value_counts()
print("\nBoundary Condition Type Summary:")
print(bc_type_counts)

# Analyze time intervals
interval_counts = boundary_conditions['Interval'].value_counts()
print("\nTime Interval Distribution:")
print(interval_counts)

# Summary by unsteady file
print("\nBoundary Conditions by Unsteady File:")
print(boundary_conditions.groupby('unsteady_number')['bc_type'].value_counts())
```

### Finding Specific Boundaries

```python
# Find boundaries at a specific river station
station_boundaries = boundary_conditions[
    boundary_conditions['river_station'] == '10000'
]

# Find boundaries for a specific river/reach
river_boundaries = boundary_conditions[
    boundary_conditions['river_reach_name'].str.contains('Muncie', na=False)
]

# Find boundaries with most data points
max_values = boundary_conditions['hydrograph_num_values'].max()
largest_boundaries = boundary_conditions[
    boundary_conditions['hydrograph_num_values'] == max_values
]
```

## Modifying Boundary Conditions

To modify boundary condition data values, use the `RasUnsteady` class:

### Reading Boundary Data

```python
from ras_commander import RasUnsteady

# Extract all tables from unsteady flow file
tables = RasUnsteady.extract_tables("u01")

# Available table types (keys vary by project)
print("Available tables:")
for key in tables.keys():
    print(f"  {key}")

# Access specific boundary data
if 'Flow Hydrograph=' in tables:
    flow_hydrograph = tables['Flow Hydrograph=']
    print("\nFlow Hydrograph Data:")
    print(flow_hydrograph.head())
```

!!! warning "Table Key Format"
    Table keys include the equals sign (e.g., `'Flow Hydrograph='`, `'Stage Hydrograph='`). This matches the format in HEC-RAS unsteady flow files.

### Modifying Boundary Data

```python
# Example: Scale flow hydrograph by 20%
if 'Flow Hydrograph=' in tables:
    original_flow = tables['Flow Hydrograph=']

    # Modify the data (keep time column, scale flow column)
    modified_flow = original_flow.copy()
    modified_flow.iloc[:, 1] = modified_flow.iloc[:, 1] * 1.2

    # Write back to file
    RasUnsteady.write_table_to_file(
        "u01",
        "Flow Hydrograph=",
        modified_flow
    )
    print("Flow hydrograph scaled by 1.2x")
```

### Creating New Boundary Data

```python
import pandas as pd
import numpy as np

# Create a new flow hydrograph
time_hours = np.arange(0, 48, 1)  # 48 hours
base_flow = 100  # cfs
peak_flow = 5000  # cfs

# Simple triangular hydrograph
flows = np.concatenate([
    np.linspace(base_flow, peak_flow, 12),  # Rising limb
    np.linspace(peak_flow, base_flow, 36)   # Falling limb
])

new_hydrograph = pd.DataFrame({
    'Time': time_hours,
    'Flow': flows
})

# Write to unsteady file
RasUnsteady.write_table_to_file(
    "u02",
    "Flow Hydrograph=",
    new_hydrograph
)
```

!!! danger "File Backup"
    Always backup your unsteady flow files (.u##) before modifying them. Incorrect modifications can corrupt the file and make it unreadable by HEC-RAS.

## Visualizing Boundary Conditions

### Plot Flow Hydrograph

```python
import matplotlib.pyplot as plt

# Extract and plot flow hydrograph
tables = RasUnsteady.extract_tables("u01")
if 'Flow Hydrograph=' in tables:
    flow_data = tables['Flow Hydrograph=']

    plt.figure(figsize=(12, 6))
    plt.plot(flow_data.iloc[:, 0], flow_data.iloc[:, 1], 'b-', linewidth=2)
    plt.xlabel('Time (hours)', fontsize=12)
    plt.ylabel('Flow (cfs)', fontsize=12)
    plt.title('Upstream Flow Hydrograph', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()
```

### Plot Stage Hydrograph

```python
# Extract and plot stage hydrograph
if 'Stage Hydrograph=' in tables:
    stage_data = tables['Stage Hydrograph=']

    plt.figure(figsize=(12, 6))
    plt.plot(stage_data.iloc[:, 0], stage_data.iloc[:, 1], 'r-', linewidth=2)
    plt.xlabel('Time (hours)', fontsize=12)
    plt.ylabel('Stage (ft)', fontsize=12)
    plt.title('Downstream Stage Hydrograph', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()
```

### Compare Multiple Boundaries

```python
# Plot multiple flow hydrographs
fig, axes = plt.subplots(2, 1, figsize=(12, 10))

tables_u01 = RasUnsteady.extract_tables("u01")
tables_u02 = RasUnsteady.extract_tables("u02")

if 'Flow Hydrograph=' in tables_u01:
    flow_u01 = tables_u01['Flow Hydrograph=']
    axes[0].plot(flow_u01.iloc[:, 0], flow_u01.iloc[:, 1], 'b-', label='Plan 01')

if 'Flow Hydrograph=' in tables_u02:
    flow_u02 = tables_u02['Flow Hydrograph=']
    axes[0].plot(flow_u02.iloc[:, 0], flow_u02.iloc[:, 1], 'r-', label='Plan 02')

axes[0].set_xlabel('Time (hours)')
axes[0].set_ylabel('Flow (cfs)')
axes[0].set_title('Flow Hydrograph Comparison')
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Add stage comparison if available
if 'Stage Hydrograph=' in tables_u01:
    stage_u01 = tables_u01['Stage Hydrograph=']
    axes[1].plot(stage_u01.iloc[:, 0], stage_u01.iloc[:, 1], 'b-', label='Plan 01')

if 'Stage Hydrograph=' in tables_u02:
    stage_u02 = tables_u02['Stage Hydrograph=']
    axes[1].plot(stage_u02.iloc[:, 0], stage_u02.iloc[:, 1], 'r-', label='Plan 02')

axes[1].set_xlabel('Time (hours)')
axes[1].set_ylabel('Stage (ft)')
axes[1].set_title('Stage Hydrograph Comparison')
axes[1].legend()
axes[1].grid(True, alpha=0.3)

plt.tight_layout()
plt.show()
```

## Complete Workflow Example

```python
from ras_commander import init_ras_project, ras, RasUnsteady
import matplotlib.pyplot as plt
import pandas as pd

# 1. Initialize project
init_ras_project(r"C:\HEC\projects\FloodStudy\FloodStudy.prj", "6.5")

# 2. Analyze boundary conditions
boundaries = ras.boundaries_df
print(f"Total boundary conditions: {len(boundaries)}")
print(f"\nBoundary types:\n{boundaries['bc_type'].value_counts()}")

# 3. Filter for flow hydrographs
flow_bcs = boundaries[boundaries['bc_type'] == 'Flow Hydrograph']
print(f"\n{len(flow_bcs)} flow hydrographs found")

# 4. Extract and modify boundary data
tables = RasUnsteady.extract_tables("u01")
if 'Flow Hydrograph=' in tables:
    original_flow = tables['Flow Hydrograph=']

    # Create 1.5x scaled scenario
    scaled_flow = original_flow.copy()
    scaled_flow.iloc[:, 1] = scaled_flow.iloc[:, 1] * 1.5

    # Write to new unsteady file
    RasUnsteady.write_table_to_file("u02", "Flow Hydrograph=", scaled_flow)

    # 5. Visualize comparison
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(original_flow.iloc[:, 0], original_flow.iloc[:, 1],
            'b-', linewidth=2, label='Original')
    ax.plot(scaled_flow.iloc[:, 0], scaled_flow.iloc[:, 1],
            'r-', linewidth=2, label='1.5x Scaled')
    ax.set_xlabel('Time (hours)', fontsize=12)
    ax.set_ylabel('Flow (cfs)', fontsize=12)
    ax.set_title('Boundary Condition Comparison', fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

    print("\nModified boundary condition created and visualized")
```

## Limitations and Considerations

!!! warning "Read-Only DataFrame"
    The `boundaries_df` dataframe is for metadata access only. Modifying values in this dataframe will not affect the actual HEC-RAS project files. Use `RasUnsteady` methods to modify boundary data.

!!! note "Unsteady Flow Only"
    Boundary conditions are specific to unsteady flow models. Steady flow models use flow files (.f##) with a different structure accessed through `ras.flow_df`.

!!! tip "DSS File Integration"
    For boundaries linked to DSS files, use the `RasDss` class to extract and analyze time series data. See the [DSS Operations](dss-operations.md) guide for details.

### Common Issues

1. **Empty boundaries_df**: Occurs when no unsteady flow files exist or cannot be parsed
2. **Missing table keys**: Not all unsteady files contain all boundary types
3. **Time interval mismatch**: Ensure modified data matches the original time interval
4. **Column format**: Boundary data tables typically have two columns (time, value)

## Best Practices

1. Always check if `boundaries_df` exists and is not empty before accessing
2. Use descriptive variable names when filtering boundary types
3. Backup unsteady files before modifying
4. Verify modifications by re-reading the file
5. Document units and coordinate systems in comments
6. Use version control for boundary condition modifications
7. Test modified boundaries with small test runs before full simulations

## Related Documentation

- [Common Workflows and Patterns](workflows-and-patterns.md) - Complete analysis workflows
- [DSS Operations](dss-operations.md) - Working with DSS boundary condition files
- [Plan Execution](plan-execution.md) - Executing unsteady flow plans
- [Project Initialization](../getting-started/project-initialization.md) - Setting up RAS projects

## API Reference

For detailed API documentation, see:

- `RasUnsteady.extract_tables()` - Extract boundary data tables
- `RasUnsteady.write_table_to_file()` - Write modified boundary data
- `RasPrj.boundaries_df` - Access boundary condition metadata
- `RasDss` class - DSS file operations for boundary conditions
