# DSS Operations

RAS Commander provides read access to HEC-DSS files for extracting boundary condition data.

## Overview

The `RasDss` class reads HEC-DSS time series data using HEC's Monolith Java libraries:

- Supports DSS Version 6 and Version 7 files
- Auto-downloads required libraries (~17 MB) on first use
- Lazy loading - no overhead unless DSS methods are called
- Tested with 84 DSS files totaling 6.64 GB

## Requirements

```bash
# Install pyjnius (Java bridge)
pip install pyjnius

# Requires Java 8+ (JRE or JDK)
# Verify: java -version
```

## Basic Usage

### List DSS Contents

```python
from ras_commander import RasDss

dss_file = "/path/to/boundary.dss"

# Get catalog of all paths
catalog = RasDss.get_catalog(dss_file)
print(catalog)

# Catalog contains:
# - A Part: Location
# - B Part: Parameter
# - C Part: Type
# - D Part: Start date
# - E Part: Interval
# - F Part: Version
```

### Read Time Series

```python
# Read single time series
pathname = "/BASIN/GAGE1/FLOW/01JAN2020/1HOUR/OBS/"
df = RasDss.read_timeseries(dss_file, pathname)
print(df)

# DataFrame with datetime index and value column
```

### Read Multiple Time Series

```python
# Read several paths at once
pathnames = [
    "/BASIN/GAGE1/FLOW/01JAN2020/1HOUR/OBS/",
    "/BASIN/GAGE2/FLOW/01JAN2020/1HOUR/OBS/",
    "/BASIN/GAGE3/FLOW/01JAN2020/1HOUR/OBS/",
]

results = RasDss.read_multiple_timeseries(dss_file, pathnames)

for path, df in results.items():
    print(f"{path}: {len(df)} records")
```

## Integration with HEC-RAS Projects

### Extract Boundary Timeseries

Automatically extract all DSS-based boundary conditions from a project:

```python
from ras_commander import init_ras_project, ras, RasDss

init_ras_project("/path/to/project", "6.5")

# Get boundary conditions
print(ras.boundaries_df)

# Extract DSS data for all boundaries
boundary_data = RasDss.extract_boundary_timeseries(
    ras.boundaries_df,
    ras_object=ras
)

# Returns dictionary: {boundary_name: DataFrame}
for name, df in boundary_data.items():
    print(f"{name}: {len(df)} timesteps")
```

### DSS File Information

```python
# Get file summary
info = RasDss.get_info(dss_file)
print(info)

# Returns:
# - version: DSS version (6 or 7)
# - num_records: Total record count
# - pathnames: List of all paths
# - file_size: Size in bytes
```

## Complete Workflow

```python
from ras_commander import init_ras_project, ras, RasDss
import matplotlib.pyplot as plt

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Find DSS files referenced in project
boundaries = ras.boundaries_df
dss_boundaries = boundaries[boundaries['source_type'] == 'DSS']
print(f"Found {len(dss_boundaries)} DSS-based boundaries")

if len(dss_boundaries) > 0:
    # Extract all DSS data
    bc_data = RasDss.extract_boundary_timeseries(boundaries, ras)

    # Plot first boundary
    first_bc = list(bc_data.keys())[0]
    df = bc_data[first_bc]

    plt.figure(figsize=(12, 4))
    plt.plot(df.index, df['value'])
    plt.title(f"Boundary Condition: {first_bc}")
    plt.xlabel("Time")
    plt.ylabel("Value")
    plt.grid(True)
    plt.show()
```

## Catalog Filtering

```python
# Get catalog
catalog = RasDss.get_catalog(dss_file)

# Filter by parameter (B Part)
flow_records = catalog[catalog['B'] == 'FLOW']

# Filter by location (A Part)
gage1_records = catalog[catalog['A'].str.contains('GAGE1')]

# Get unique parameters
parameters = catalog['B'].unique()
print(f"Available parameters: {parameters}")
```

## Error Handling

```python
from ras_commander import RasDss

try:
    catalog = RasDss.get_catalog("/path/to/file.dss")
except FileNotFoundError:
    print("DSS file not found")
except RuntimeError as e:
    if "Java" in str(e):
        print("Java not found - install Java 8+")
    elif "pyjnius" in str(e):
        print("Install pyjnius: pip install pyjnius")
    else:
        print(f"DSS error: {e}")
```

## Performance Notes

1. **First use**: Library downloads HEC Monolith (~17 MB)
2. **Large files**: Successfully tested up to 1.3 GB DSS files
3. **Memory**: Large time series may require chunked reading
4. **Caching**: Catalog is cached per file during session

## Writing Gridded DSS Precipitation

`RasDss.write_grid_timeseries()` writes one spatial DSS grid record per
timestep. This is the direct HEC Monolith path for creating gridded
precipitation DSS files without HEC-Vortex.

```python
from datetime import datetime
import numpy as np
from ras_commander import RasDss

data = np.arange(5 * 10 * 10, dtype="float32").reshape(5, 10, 10)
times = [datetime(2020, 1, 1, hour) for hour in range(1, 6)]

written = RasDss.write_grid_timeseries(
    dss_file="precip.synthetic.dss",
    pathname="/SHG/WATERSHED/PRECIP/01JAN2020:0000/01JAN2020:0100/SYNTHETIC/",
    data=data,
    times=times,
    grid_info={
        "cellsize": 2000,
        "origin": (1096000, 1516000),
        "crs": "SHG",
        "units": "mm",
        "data_type": "PER-CUM",
    },
)
```

The pathname is a template. Parts A/B/C/F are preserved, while Parts D/E are
rebuilt for each timestep using the start/end window. For period data such as
precipitation, pass either `n_times + 1` boundary times or `n_times` interval
end times.

### Grid Java API Mapping

| Python input | HEC Monolith class/member |
| --- | --- |
| `dss_file` | `hec.heclib.grid.GriddedData.setDSSFileName()` |
| A/B/C/F pathname parts | `GriddedData.setGriddedPathnameParts()` |
| timestep D/E windows | `GridInfo.setGridTimes()` and `GriddedData.setGriddedTimeWindow()` |
| grid frame values | `hec.heclib.grid.GridData(float[], GridInfo)` |
| SHG CRS metadata | `hec.heclib.grid.AlbersInfo` |
| custom WKT metadata | `hec.heclib.grid.SpecifiedGridInfo` |
| cell counts, cell size, origin | `GridInfo.setCellInfo()` |
| units and DSS data type | `GridInfo.setParameterInfo()` |
| precipitation compression | `GridInfo.setCompressionInfo()` |

The Monolith JAR also exposes `hec.io.GridContainer`, but the ras-commander
Monolith cache does not include a `SpatialGridBean` class. The equivalent grid
payload is `GridData` plus a `GridInfo` subclass. ras-commander writes via
`GriddedData.storeGriddedData()` because that route is stable from pyjnius for
the bundled HEC Monolith version.

## Supported Features

| Feature | Status |
|---------|--------|
| Read time series | Supported |
| Read catalog | Supported |
| DSS Version 6 | Supported |
| DSS Version 7 | Supported |
| Write time series | Supported |
| Write gridded precipitation | Supported |
| Paired data | Not yet supported |
| General grid reading API | Not yet supported |

## Technology Stack

```
Python Script
    │
    ├── RasDss (ras_commander)
    │       │
    │       └── pyjnius (Java bridge)
    │               │
    │               └── HEC Monolith Libraries
    │                       │
    │                       └── DSS File (V6/V7)
```

## See Also

- `examples/22_dss_boundary_extraction.ipynb` - Complete workflow
- [Project Initialization](../getting-started/project-initialization.md) - Accessing `boundaries_df`
- [HEC-DSS Documentation](https://www.hec.usace.army.mil/software/hec-dss/)
