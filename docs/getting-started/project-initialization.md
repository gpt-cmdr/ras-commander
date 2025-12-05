# Project Initialization

Understanding how to properly initialize HEC-RAS projects is fundamental to using RAS Commander effectively.

## Basic Initialization

The `init_ras_project()` function discovers project files and populates the RAS object with DataFrames containing project metadata.

```python
from ras_commander import init_ras_project, ras

# Basic initialization with version number
init_ras_project(r"C:\Projects\MyProject", "6.5")
```

## HEC-RAS Executable Specification

You can specify the HEC-RAS executable in several ways:

### Version Number

Use a version string to reference the default installation path:

```python
# Standard installation on C: drive
init_ras_project(r"C:\Projects\MyProject", "6.5")

# Also accepts formats like "65", "6.5", "6.5.0"
init_ras_project(r"C:\Projects\MyProject", "66")
```

### Full Executable Path

For non-standard installations or HEC-RAS on other drives:

```python
init_ras_project(
    r"C:\Projects\MyProject",
    r"D:\Programs\HEC\HEC-RAS\6.5\Ras.exe"
)
```

### Auto-Detection

Omit the version to attempt detection from plan files:

```python
init_ras_project(r"C:\Projects\MyProject")
```

!!! warning
    Auto-detection may fail if plan files don't contain version information.

## Understanding the RAS Object

After initialization, the `ras` object contains:

### DataFrames

| Attribute | Description |
|-----------|-------------|
| `ras.plan_df` | Plan files (.p01, .p02, etc.) with paths, titles, linked files |
| `ras.geom_df` | Geometry files (.g01, .g02, etc.) with basic metadata |
| `ras.flow_df` | Steady flow files (.f01, .f02, etc.) |
| `ras.unsteady_df` | Unsteady flow files (.u01, .u02, etc.) |
| `ras.boundaries_df` | Boundary conditions extracted from unsteady files |
| `ras.rasmap_df` | RASMapper configuration paths (terrain, land cover) |

### Properties

| Attribute | Description |
|-----------|-------------|
| `ras.project_folder` | Path to project directory |
| `ras.project_name` | Project name (without extension) |
| `ras.prj_file` | Path to .prj file |
| `ras.ras_exe_path` | Path to HEC-RAS executable |

### Example: Exploring a Project

```python
from ras_commander import init_ras_project, ras

init_ras_project(r"C:\Projects\Muncie", "6.5")

print(f"Project: {ras.project_name}")
print(f"Folder: {ras.project_folder}")
print(f"HEC-RAS: {ras.ras_exe_path}")

print("\n=== Plans ===")
print(ras.plan_df[['plan_number', 'plan_title', 'geom_number', 'hdf_path']])

print("\n=== Geometry Files ===")
print(ras.geom_df[['geom_number', 'file_path']])

print("\n=== Boundary Conditions ===")
print(ras.boundaries_df[['Name', 'Type', 'Interval']])
```

## DataFrame Reference

Detailed information about each DataFrame available after project initialization.

### plan_df Columns

| Column | Type | Description |
|--------|------|-------------|
| `plan_number` | str | Plan identifier ("01", "02", ...) |
| `full_path` | Path | Full path to .p## file |
| `Short Identifier` | str | User-defined short name |
| `Plan Title` | str | User-defined full title |
| `Geom File` | str | Geometry file reference (g##) |
| `Flow File` | str | Flow file reference (f## or u##) |
| `unsteady_number` | str | Unsteady flow number if used |
| `geometry_number` | str | Geometry number used |
| `Simulation Date` | str | Start/end dates string |
| `Computation Interval` | str | Time step (e.g., "2MIN") |
| `Run HTab`, `Run UNet` | int | Run flags |
| `UNET D1 Cores`, `UNET D2 Cores` | int | Core settings |
| `HDF_Results_Path` | Path | Path to results HDF if exists |

### boundaries_df Columns

| Column | Type | Description |
|--------|------|-------------|
| `unsteady_number` | str | Links to .u## file |
| `boundary_condition_number` | int | Sequential ID within file |
| `river_reach_name` | str | River/reach location |
| `river_station` | str | Station location |
| `storage_area_name` | str | SA name (if applicable) |
| `bc_type` | str | Boundary type |
| `hydrograph_type` | str | Specific hydrograph type |
| `Interval` | str | Time interval |
| `hydrograph_num_values` | int | Number of data points |

### Common Query Patterns

```python
# Find plans using specific geometry
g01_plans = ras.plan_df[ras.plan_df['geometry_number'] == '01']

# Get plans with completed results
completed = ras.plan_df[ras.plan_df['HDF_Results_Path'].notna()]

# Count boundary conditions by type
bc_counts = ras.boundaries_df['bc_type'].value_counts()

# Get flow hydrographs only
flow_bcs = ras.boundaries_df[ras.boundaries_df['bc_type'] == 'Flow Hydrograph']

# Find unsteady files using restart
restart_files = ras.unsteady_df[ras.unsteady_df['Use Restart'] == 'True']
```

### HDF Entries Helper

```python
# Get only plans with HDF results
hdf_entries = ras.get_hdf_entries()
print(f"Plans with results: {len(hdf_entries)}")
```

## Working with Multiple Projects

For scripts that need to work with multiple HEC-RAS projects simultaneously:

### Using Named Instances

```python
from ras_commander import RasPrj, init_ras_project, RasCmdr

# Create separate instances
upstream_model = RasPrj()
downstream_model = RasPrj()

# Initialize each
init_ras_project(r"C:\Projects\Upstream", "6.5", ras_object=upstream_model)
init_ras_project(r"C:\Projects\Downstream", "6.5", ras_object=downstream_model)

# Access data from each
print(f"Upstream plans: {upstream_model.plan_df['plan_number'].tolist()}")
print(f"Downstream plans: {downstream_model.plan_df['plan_number'].tolist()}")

# Execute specifying the project
RasCmdr.compute_plan("01", ras_object=upstream_model)
RasCmdr.compute_plan("01", ras_object=downstream_model)
```

### Return Value Pattern

`init_ras_project()` returns the initialized RAS object:

```python
project = init_ras_project(r"C:\Projects\MyProject", "6.5", ras_object=RasPrj())
print(project.plan_df)
```

## Refreshing Project Data

If project files change externally (e.g., after running HEC-RAS manually), re-initialize to refresh:

```python
# After external changes
init_ras_project(ras.project_folder, "6.5")

# Or for a named instance
init_ras_project(project.project_folder, "6.5", ras_object=project)
```

## Best Practices

1. **Single Project Scripts**: Use the global `ras` object for simplicity
2. **Multiple Projects**: Always use named `RasPrj` instances and pass `ras_object` to all functions
3. **Consistency**: Don't mix global `ras` and named instances in the same logical section
4. **Version Specification**: Explicitly specify version rather than relying on auto-detection
5. **Path Handling**: Use raw strings (`r"..."`) or forward slashes for Windows paths

## Common Issues

### Project File Not Found

```python
# Ensure the path contains a .prj file
from pathlib import Path

project_path = Path(r"C:\Projects\MyProject")
prj_files = list(project_path.glob("*.prj"))

if not prj_files:
    print("No .prj file found in directory")
else:
    init_ras_project(project_path, "6.5")
```

### Missing HEC-RAS Installation

```python
from pathlib import Path

ras_exe = Path(r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe")
if not ras_exe.exists():
    print(f"HEC-RAS not found at {ras_exe}")
    # Try alternative location
    ras_exe = Path(r"D:\Programs\HEC\HEC-RAS\6.5\Ras.exe")

init_ras_project(r"C:\Projects\MyProject", str(ras_exe))
```
