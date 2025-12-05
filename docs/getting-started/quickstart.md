# Quick Start

This guide covers the essential operations to get started with RAS Commander.

## Initialize a Project

```python
from ras_commander import init_ras_project, ras

# Initialize with version number (uses default installation path)
init_ras_project(r"C:\Projects\MyRASProject", "6.5")

# Or specify full path to Ras.exe
init_ras_project(r"C:\Projects\MyRASProject", r"D:\HEC-RAS\6.5\Ras.exe")
```

The global `ras` object now contains your project data.

## Explore Project Structure

```python
# View available plans
print(ras.plan_df)

# View geometry files
print(ras.geom_df)

# View unsteady flow files
print(ras.unsteady_df)

# View boundary conditions
print(ras.boundaries_df)

# View HDF result files
print(ras.get_hdf_entries())
```

## Execute Plans

### Single Plan

```python
from ras_commander import RasCmdr

# Execute plan 01
success = RasCmdr.compute_plan("01")
print(f"Execution {'succeeded' if success else 'failed'}")
```

### Execute to Destination Folder

```python
# Execute with results saved to separate folder
success = RasCmdr.compute_plan(
    "01",
    dest_folder=r"C:\Results\Run1",
    overwrite_dest=True
)
```

### Parallel Execution

```python
# Run multiple plans simultaneously
results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"],
    max_workers=3,
    num_cores=2
)

for plan, success in results.items():
    print(f"Plan {plan}: {'OK' if success else 'FAILED'}")
```

## Extract HDF Results

```python
from ras_commander import HdfResultsMesh, HdfResultsXsec

# Get path to HDF file
hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'hdf_path'].iloc[0]

# Extract maximum water surface elevation (2D)
max_wse = HdfResultsMesh.get_mesh_max_ws(hdf_path)
print(max_wse.head())

# Extract cross-section results (1D)
xsec_wse = HdfResultsXsec.get_xsec_timeseries(hdf_path, "Water Surface")
print(xsec_wse.head())
```

## Modify Plan Parameters

```python
from ras_commander import RasPlan

# Set number of compute cores
RasPlan.set_num_cores("01", 4)

# Change geometry file
RasPlan.set_geom("01", "02")  # Use geometry file g02

# Update computation interval
RasPlan.set_computation_interval("01", "5MIN")

# Update description
RasPlan.set_description("01", "Modified run with 5-minute interval")
```

## Work with Example Projects

```python
from ras_commander import RasExamples

# List available example projects
all_projects = RasExamples.list_projects()
print(all_projects)

# Extract a project for testing
path = RasExamples.extract_project("Muncie")
print(f"Extracted to: {path}")

# Initialize the extracted project
init_ras_project(path, "6.5")
```

## Multiple Projects

```python
from ras_commander import RasPrj, init_ras_project, RasCmdr

# Create separate project instances
project1 = RasPrj()
project2 = RasPrj()

# Initialize each
init_ras_project(r"C:\Project1", "6.5", ras_object=project1)
init_ras_project(r"C:\Project2", "6.5", ras_object=project2)

# Execute plans specifying which project
RasCmdr.compute_plan("01", ras_object=project1)
RasCmdr.compute_plan("01", ras_object=project2)
```

## Next Steps

- **[Project Initialization](project-initialization.md)**: Detailed project setup options
- **[Plan Execution](../user-guide/plan-execution.md)**: Advanced execution modes
- **[HDF Data Extraction](../user-guide/hdf-data-extraction.md)**: Working with results
- **[Example Notebooks](../examples/index.md)**: 30+ complete examples
