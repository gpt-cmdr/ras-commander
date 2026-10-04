# DSS Operations

RAS Commander reads and writes HEC-DSS boundary and precipitation data.

`RasDss.write_grid_timeseries()` already writes arrays directly to gridded DSS
through HEC Monolith. Existing Monolith users do not need pydsstools for this
capability. The native writer below is an optional backend alternative.

## Direct precipitation arrays to DSS7

`RasDss.write_precip_grid_arrays()` writes NumPy arrays through the native
[pydsstools](https://github.com/gyanz/pydsstools) library by Gyan Basyal (gyanz),
without Java, Vortex, or intermediate timestep raster files. NetCDF remains the
default output of the gridded Atlas 14 generators; DSS is an explicit alternative.

```bash
uv pip install "ras-commander[dss-native]"
```

This extra uses pydsstools 3.x (at least 3.1). For the tested **3.1.0** release,
Windows x64 wheels cover CPython 3.9–3.13; there is no CPython 3.14 Windows
wheel. Python 3.11/3.12 requires NumPy >=1.26,<2; Python 3.13 requires NumPy
>=2.1. Dependencies also include pandas, affine, pyproj, and pydantic >=2,<3.
Install these together through the extra so the resolver honors their version
constraints. The Windows roundtrip tests use Python 3.12.

**Windows runtime requirement:** the inspected CPython 3.12 wheel imports
`VCRUNTIME140.dll` and Windows Universal CRT components. It does not bundle
these DLLs. The Python distribution may supply the Visual C runtime; otherwise
install the applicable [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).
On the validation workstation, uv's CPython supplied `VCRUNTIME140.dll` and
Windows supplied `ucrtbase.dll`. Passing tests on that development machine
does not establish installation on a clean Windows machine.

A compatible **wheel needs the runtime, not a compiler**. Building pydsstools
from source on Windows additionally requires Visual Studio Build Tools with
the C++ workload; see the [upstream installation guide](https://pydsstools.readthedocs.io/en/latest/installation.html).
Use a supported Python/wheel combination if a source build is not intended.

```python
from affine import Affine
import numpy as np
import pandas as pd
from ras_commander import RasDss

# Two interval depths (mm), north-most row first, west-most column first.
depths = np.array([[[1., 2.], [3., np.nan]], [[4., 5.], [6., np.nan]]])
paths = RasDss.write_precip_grid_arrays(
    "rainfall.dss", "/UTM15/BASIN/PRECIP///DESIGN/", depths,
    pd.date_range("2020-01-01", periods=3, freq="6min"),
    transform=Affine(100, 0, 300000, 0, -100, 3300000),
    crs="EPSG:26915", units="mm", grid_reference_origin=(0, 0),
)
```

Pass **n+1 interval boundaries for n grids**, using the same timezone-naive
clock as the receiving model. Each record is PER-CUM precipitation depth over
its D/E start/end times. Supply incremental depths, not rainfall intensity or
cumulative totals since storm start. `units="inches"` is also supported; the
writer labels units explicitly and does not multiply or divide input values.

The transform maps pixel corners in `(a,b,c,d,e,f)` Affine order. Grids must
have square, unrotated cells in an explicit projected CRS. Geographic Atlas 14
arrays must first be reprojected; this method does not interpret latitude and
longitude as projected coordinates. NaN, masked cells, and an explicit `nodata=`
sentinel become native DSS missing values. Negative depths and infinity fail.

For consumers that address rainfall by fixed cell indexes, pass
`grid_reference_origin=(x0, y0)` in CRS units. The lower-left raster corner must
be a whole number of cells from that reference. For example, a legacy HMS HRAP
file discretization can require `(0, 0)` rather than local raster indexes.
Without this option, the native writer indexes from the raster's lower-left
corner. Equal physical extents alone do not establish compatibility with an
index-based discretization.

An HMS 4.13 check using the official `tenk` example reproduced all four basins'
precipitation and discharge exactly with both Monolith grids and native grids
using the required reference origin. The locally indexed native variant
completed computation but supplied zero rainfall. Check computed precipitation
as well as completion status when changing a grid source.

The HEC-RAS 6.6 Davis check also required `(0, 0)` for its aligned native SHG
grid; local indexes otherwise placed the raster at the wrong location. With
the reference restored, NetCDF, Monolith DSS and native DSS all computed and
materialized the intended 110-cell, six-interval precipitation field. This
qualifies those versioned configurations, not every projection or model setup.

Before enabling global gridded rainfall, explicitly review and remove any
superseded legacy `Precipitation Hydrograph` boundary in a staged project.
HEC-RAS 6.6 rejected the tested combination before preprocessing. The gridded
setters conservatively reject that combination across versions before mutation;
they never delete a boundary automatically. Use `inspect_boundary_blocks()` and
`delete_boundary()` to select and remove the intended block.

After native preprocessing, `HdfPlan.get_plan_met_precip_values()` reads the
solver's raw precipitation Values and Timestamp arrays with their attributes.
It rejects an imported-raster sidecar without materialized solver datasets.
The reader preserves encoded timestamps and numerical values; use method and
unit metadata when comparing interval depths with cumulative import series.

The writer creates DSS7 specified-time grids, closes and checks the temporary
file, then publishes it. Existing files are protected by default;
`overwrite=True` replaces the **entire file**, rather than appending records.
New-file publication uses a same-directory hard link to prevent concurrent
writers from overwriting each other; the destination filesystem must support
hard links. Explicit overwrite uses atomic replacement.
The tests verify native DSS readback of values, orientation, missing cells,
CRS, units, and interval pathnames. They do not establish acceptance by every
RAS/HMS version. Configure a receiving RAS project through
`RasUnsteady.configure_gridded_dss_precipitation()` and validate the intended
engine/version as part of the project workflow.

## Overview

The `RasDss` class reads HEC-DSS time series data using HEC's Monolith Java libraries:

- Supports DSS Version 6 and Version 7 files
- Auto-downloads required libraries (~17 MB) on first use
- Lazy loading - no overhead unless DSS methods are called
- Tested with 84 DSS files totaling 6.64 GB

## Java bridge requirements

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
    dss_version=6,
)
```

The pathname is a template. Parts A/B/C/F are preserved, while Parts D/E are
rebuilt for each timestep using the start/end window. For period data such as
precipitation, pass either `n_times + 1` boundary times or `n_times` interval
end times.

Monolith `write_grid_timeseries()` and `read_grid()` use HEC's south-first row
order. For north-up raster arrays, pass `data[:, ::-1, :]` to the Monolith
writer; the native `write_precip_grid_arrays()` accepts north-first arrays
directly. Both run columns west to east. End-of-day E parts use the previous
date with `2400`, matching the actual DSS catalog and returned exact paths.

For specified-grid cross-library exchange, supply ASCII WKT1_GDAL projection
text. The tested pydsstools 3.1 reader cannot decode Unicode characters in some
WKT2 strings written through Monolith. This concerns projection serialization;
changing WKT syntax does not reproject the rainfall.

`dss_version` is keyword-only. Pass `6` or `7` when creating a new database,
or omit it to retain the HEC bridge default. An explicit version must match an
existing file. All writer timestamps must be timezone-naive: convert aware
data to the intended HEC-RAS model clock and remove timezone metadata before
calling the API.

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
