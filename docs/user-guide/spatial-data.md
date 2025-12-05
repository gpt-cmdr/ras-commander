# Working with Spatial Data and RASMapper

RAS Commander provides comprehensive tools for working with HEC-RAS spatial datasets, including terrain, land cover, infiltration layers, and automated map generation. This guide covers accessing RASMapper configuration data and modifying spatial parameters for model calibration.

## Overview

When you initialize a RAS project, the library automatically parses the RASMapper file (`.rasmap`) and populates the `rasmap_df` DataFrame with paths to all spatial datasets. This provides programmatic access to terrain models, land cover layers, soil data, and more.

## Understanding rasmap_df

The `rasmap_df` DataFrame is automatically populated when you call `init_ras_project()`. It contains paths and metadata for all spatial datasets referenced in your RASMapper configuration.

```python
from ras_commander import init_ras_project, ras

# Initialize project - automatically parses .rasmap file
init_ras_project(r"C:\Projects\MyRasModel", "6.6")

# Access rasmap DataFrame
print(ras.rasmap_df)
```

### Available Spatial Data Types

The `rasmap_df` typically contains paths to:

- **Terrain data** - Digital elevation models (DEM/DTM)
- **Land cover datasets** - Manning's n roughness layers
- **Soil layers** - Hydrologic soil groups for infiltration
- **Infiltration data** - Green-Ampt or SCS CN parameters
- **Profile lines** - Cross-section locations
- **Boundary features** - Flow and stage boundary locations

### Accessing Specific Data Paths

```python
# Example: Get terrain HDF path
terrain_path = ras.rasmap_df['terrain_hdf_path'][0]

# Example: Get infiltration data path
infiltration_path = ras.rasmap_df['infiltration_hdf_path'][0][0]

# Example: Get land cover layer path
landcover_path = ras.rasmap_df['landcover_hdf_path'][0]
```

## Terrain Data Access

The `RasMap` class provides methods for working with terrain datasets.

### Getting RASMapper File Path

```python
from ras_commander import RasMap

# Get path to .rasmap file
rasmap_file = RasMap.get_rasmap_path()
print(f"RASMapper file: {rasmap_file}")
```

### Listing Available Terrains

```python
# Get list of all terrain names in project
terrains = RasMap.get_terrain_names(rasmap_file)
print(f"Available terrains: {terrains}")
# Output: ['Terrain50', 'Terrain10', 'LiDAR_2020']
```

This is useful when you have multiple terrain datasets and need to specify which one to use for map generation or analysis.

## Land Cover and Soil Layers

Land cover and soil data are critical for 2D modeling, controlling Manning's n roughness and infiltration parameters.

### Accessing Land Cover Data

Land cover datasets define Manning's n values across 2D flow areas. These are typically stored as HDF files referenced in the RASMapper configuration.

```python
# Get land cover layer path from rasmap_df
landcover_path = ras.rasmap_df['landcover_hdf_path'][0]

# Land cover is used for Manning's n assignment
# See Manning's n Calibration section below for modification
```

### Accessing Soil Layer Data

Soil layers define hydrologic soil groups (A, B, C, D) used for infiltration calculations.

```python
# Get soil layer path from rasmap_df
soil_path = ras.rasmap_df['soil_hdf_path'][0]

# Soil data is used with infiltration methods
# See Infiltration Data Handling section below
```

## Automating Stored Map Generation

HEC-RAS can generate stored maps (raster outputs like depth and water surface elevation) through the GUI, but `RasMap.postprocess_stored_maps()` automates this process.

### Basic Stored Map Generation

```python
from ras_commander import RasCmdr, RasMap

# First, ensure the simulation has been run
RasCmdr.compute_plan("01")

# Generate stored maps automatically
success = RasMap.postprocess_stored_maps(
    plan_number="01",
    specify_terrain="Terrain50",
    layers=["Depth", "WSEL"]
)

if success:
    print("Stored maps generated successfully!")
```

### Available Map Layers

Common layer types you can generate:

- `"Depth"` - Flow depth (ft or m)
- `"WSEL"` - Water surface elevation (ft or m)
- `"Velocity"` - Flow velocity magnitude (ft/s or m/s)
- `"Shear"` - Bed shear stress (lb/ft² or N/m²)
- `"Froude Number"` - Froude number (dimensionless)

### Advanced Map Generation Options

```python
# Generate multiple layers for multiple plans
for plan_num in ["01", "02", "03"]:
    RasMap.postprocess_stored_maps(
        plan_number=plan_num,
        specify_terrain="Terrain50",
        layers=["Depth", "WSEL", "Velocity"]
    )

# Generate maximum values for unsteady flow
RasMap.postprocess_stored_maps(
    plan_number="05",
    specify_terrain="LiDAR_2020",
    layers=["Depth (Max)", "WSEL (Max)", "Velocity (Max)"]
)
```

### Output Locations

Generated stored maps are saved in the project directory:

```
MyRasModel/
├── MyRasModel.rasmap
├── MyRasModel.p01
├── MyRasModel.p01.hdf
└── MyRasModel.p01/
    ├── Depth (Max).tif
    ├── WSEL (Max).tif
    └── Velocity (Max).tif
```

## Manning's n Calibration Workflow

Calibrating Manning's n roughness coefficients is a common modeling task. RAS Commander provides tools to programmatically adjust Manning's n values for 2D flow areas.

### Reading Current Manning's n Values

```python
from ras_commander import RasGeo, RasPlan

# Get geometry file path for the plan
geom_path = RasPlan.get_geom_path("01")

# Extract current Manning's n values
mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)
print(mannings_df)
```

The returned DataFrame contains:

- `Land Cover Class` - Land cover type name
- `Base Manning's n Value` - Current roughness coefficient
- Other metadata depending on your model configuration

### Modifying Manning's n Values

```python
# Increase all Manning's n values by 20%
mannings_df['Base Manning\'s n Value'] *= 1.2

# Or modify specific land cover classes
mannings_df.loc[
    mannings_df['Land Cover Class'] == 'Forest',
    'Base Manning\'s n Value'
] = 0.15

# Write modified values back to geometry file
RasGeo.set_mannings_baseoverrides(geom_path, mannings_df)
```

### Clearing Geometry Preprocessor Files

!!! warning "Critical Step: Clear Geometry Preprocessor"
    After modifying Manning's n values (or any geometry parameters), you **must** clear the geometry preprocessor files. Otherwise, HEC-RAS will use the cached preprocessed geometry and ignore your changes.

```python
# Clear preprocessed geometry files
RasGeo.clear_geompre_files()

# Now re-run the simulation with updated Manning's n
RasCmdr.compute_plan("01")
```

### Calibration Loop Example

```python
# Automated calibration loop
calibration_factors = [0.8, 1.0, 1.2, 1.4]

for factor in calibration_factors:
    # Modify Manning's n
    geom_path = RasPlan.get_geom_path("01")
    mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)
    mannings_df['Base Manning\'s n Value'] *= factor
    RasGeo.set_mannings_baseoverrides(geom_path, mannings_df)

    # Clear preprocessor and run
    RasGeo.clear_geompre_files()
    RasCmdr.compute_plan("01", dest_folder=f"run_n_factor_{factor}")

    # Extract and compare results
    # (See HDF data extraction guide)
```

## Infiltration Data Handling

For 2D unsteady flow models with infiltration, RAS Commander provides the `HdfInfiltration` class to read and modify infiltration parameters stored in HDF files.

### Reading Infiltration Parameters

```python
from ras_commander import HdfInfiltration, ras

# Get infiltration HDF path from rasmap_df
infiltration_path = ras.rasmap_df['infiltration_hdf_path'][0][0]

# Extract current infiltration parameters
infil_df = HdfInfiltration.get_infiltration_baseoverrides(infiltration_path)
print(infil_df)
```

The DataFrame typically contains columns like:

- `Land Cover Class` - Land cover type
- `Maximum Deficit` - Maximum infiltration deficit (in)
- `Initial Deficit` - Initial infiltration deficit (in)
- `Potential Percolation Rate` - Percolation rate (in/hr)
- `Hydraulic Conductivity` - Soil hydraulic conductivity (in/hr)

### Scaling Infiltration Parameters

```python
# Define scale factors for each parameter
scale_factors = {
    'Maximum Deficit': 1.2,        # Increase by 20%
    'Initial Deficit': 1.0,         # No change
    'Potential Percolation Rate': 0.8  # Decrease by 20%
}

# Apply scaling and get updated DataFrame
updated_df = HdfInfiltration.scale_infiltration_data(
    infiltration_path,
    infil_df,
    scale_factors
)

# The scaled values are automatically written to the HDF file
```

### Infiltration Calibration Workflow

```python
from ras_commander import HdfInfiltration, RasGeo, RasCmdr

# 1. Get infiltration data path
infiltration_path = ras.rasmap_df['infiltration_hdf_path'][0][0]
infil_df = HdfInfiltration.get_infiltration_baseoverrides(infiltration_path)

# 2. Modify infiltration parameters
scale_factors = {
    'Maximum Deficit': 1.3,
    'Initial Deficit': 1.1,
    'Potential Percolation Rate': 0.9
}
updated_df = HdfInfiltration.scale_infiltration_data(
    infiltration_path,
    infil_df,
    scale_factors
)

# 3. Clear geometry preprocessor
RasGeo.clear_geompre_files()

# 4. Re-run simulation
RasCmdr.compute_plan("01", dest_folder="calibration_infil_run1")
```

### Common Infiltration Parameters

**Green-Ampt Method:**

- `Hydraulic Conductivity` - Rate of water movement through soil
- `Suction Head` - Soil capillary suction
- `Initial Moisture Deficit` - Initial soil moisture deficit

**SCS Curve Number Method:**

- `Curve Number` - Composite CN based on soil type and land use
- `Initial Abstraction Ratio` - Ia/S ratio (typically 0.2)

## Complete Spatial Data Workflow Example

This example demonstrates a complete workflow combining terrain, Manning's n, and infiltration adjustments:

```python
from ras_commander import (
    init_ras_project, ras, RasMap, RasGeo, RasPlan,
    RasCmdr, HdfInfiltration
)

# 1. Initialize project
init_ras_project(r"C:\Projects\FloodModel", "6.6")

# 2. Check available spatial data
print("Available terrains:", RasMap.get_terrain_names(RasMap.get_rasmap_path()))
print("Rasmap data:\n", ras.rasmap_df)

# 3. Calibration: Adjust Manning's n
geom_path = RasPlan.get_geom_path("01")
mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)

# Increase forest roughness
mannings_df.loc[
    mannings_df['Land Cover Class'] == 'Forest',
    'Base Manning\'s n Value'
] = 0.18

RasGeo.set_mannings_baseoverrides(geom_path, mannings_df)

# 4. Calibration: Adjust infiltration
infiltration_path = ras.rasmap_df['infiltration_hdf_path'][0][0]
infil_df = HdfInfiltration.get_infiltration_baseoverrides(infiltration_path)

scale_factors = {
    'Maximum Deficit': 1.25,
    'Potential Percolation Rate': 0.85
}
HdfInfiltration.scale_infiltration_data(infiltration_path, infil_df, scale_factors)

# 5. Clear preprocessor and run
RasGeo.clear_geompre_files()
RasCmdr.compute_plan("01", dest_folder="calibrated_run")

# 6. Generate result maps
RasMap.postprocess_stored_maps(
    plan_number="01",
    specify_terrain="Terrain50",
    layers=["Depth (Max)", "WSEL (Max)", "Velocity (Max)"]
)

print("Calibration run complete with updated spatial parameters!")
```

## Best Practices

### Always Clear Geometry Preprocessor

!!! warning "Critical for Geometry Changes"
    Whenever you modify geometry-related data (Manning's n, cross sections, structures, etc.), always call:
    ```python
    RasGeo.clear_geompre_files()
    ```
    This ensures HEC-RAS rebuilds the geometry from your modified files rather than using cached preprocessed data.

### Version Control Spatial Data

When calibrating models:

1. Keep original spatial datasets backed up
2. Use `dest_folder` parameter to create separate run directories
3. Document scaling factors and modifications in your scripts
4. Track which parameters changed between calibration iterations

### Verify Changes Before Running

```python
# Good practice: Verify changes before running expensive simulations
mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)
print("Manning's n summary:")
print(mannings_df['Base Manning\'s n Value'].describe())

# Check for unrealistic values
if (mannings_df['Base Manning\'s n Value'] > 0.5).any():
    print("Warning: Some Manning's n values exceed 0.5!")
```

### Use Descriptive Folder Names

```python
# Good: Descriptive folder names for calibration runs
RasCmdr.compute_plan("01", dest_folder="n_increased_20pct_infil_decreased_15pct")

# Bad: Generic folder names
RasCmdr.compute_plan("01", dest_folder="run1")
```

## Troubleshooting

### Maps Not Generating

If `postprocess_stored_maps()` fails:

1. Verify the simulation completed successfully
2. Check that the HDF file exists (`MyModel.p01.hdf`)
3. Ensure terrain name matches exactly (case-sensitive)
4. Confirm RASMapper file is not corrupted

### Manning's n Changes Not Applied

If Manning's n modifications don't affect results:

1. **Most common:** Forgot to call `RasGeo.clear_geompre_files()`
2. Check that you're modifying the correct geometry file
3. Verify the plan references the geometry file you modified
4. Ensure no errors in `set_mannings_baseoverrides()`

### Infiltration Changes Not Applied

If infiltration modifications don't affect results:

1. Call `RasGeo.clear_geompre_files()` after infiltration changes
2. Verify the infiltration HDF path is correct
3. Check that your plan uses infiltration (2D unsteady flow)
4. Ensure infiltration is enabled in the unsteady flow file

## Related Topics

- [Geometry Operations](geometry-operations.md) - Modifying cross sections, structures, and connections
- [HDF Data Extraction](hdf-data-extraction.md) - Reading simulation results from HDF files
- [Plan Execution](plan-execution.md) - Running simulations and parallel execution
- [Workflows & Patterns](workflows-and-patterns.md) - Common workflow patterns including calibration

## Additional Resources

- HEC-RAS Mapper User's Manual - Understanding RASMapper data structures
- HEC-RAS 2D Modeling User's Manual - Manning's n and infiltration guidance
- RAS Commander API Reference - Complete method documentation
