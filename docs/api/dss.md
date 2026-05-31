# DSS Modules

Classes for reading and writing HEC-DSS files.

## RasDss

Read HEC-DSS files for boundary condition extraction and write DSS time-series
or gridded precipitation records.

### Methods

#### get_catalog(dss_file)
Get catalog of all paths in a DSS file.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file

**Returns:** DataFrame with columns A, B, C, D, E, F parts

#### read_timeseries(dss_file, pathname)
Read a single time series from DSS.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file
- `pathname` (str): Full DSS pathname

**Returns:** DataFrame with datetime index and value column

#### read_multiple_timeseries(dss_file, pathnames)
Read multiple time series at once.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file
- `pathnames` (list): List of DSS pathnames

**Returns:** Dict of {pathname: DataFrame}

#### write_timeseries(dss_file, pathname, times, values)
Write a single time series to DSS.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file
- `pathname` (str): Full DSS pathname
- `times` (list|DatetimeIndex|ndarray): Datetime values
- `values` (list|ndarray): Numeric values
- `units` (str): Units, default `CFS`
- `data_type` (str): DSS data type, default `INST-VAL`

#### write_grid_timeseries(dss_file, pathname, data, times, grid_info)
Write a time-varying spatial grid series to DSS.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file
- `pathname` (str): DSS grid pathname template; A/B/C/F are preserved and D/E
  are replaced per timestep
- `data` (ndarray): Shape `(n_times, n_rows, n_cols)`
- `times` (list|DatetimeIndex|ndarray): `n_times + 1` interval boundaries or
  `n_times` interval end times
- `grid_info` (dict): Grid metadata such as `cellsize`, `origin`, `crs`,
  `units`, and `data_type`

**Returns:** List of DSS pathnames written.

Common SHG precipitation metadata:

```python
grid_info = {
    "cellsize": 2000,
    "origin": (1096000, 1516000),
    "crs": "SHG",
    "units": "mm",
    "data_type": "PER-CUM",
}
```

#### extract_boundary_timeseries(boundaries_df, ras_object)
Extract all DSS boundary conditions from a project.

**Parameters:**
- `boundaries_df` (DataFrame): From ras.boundaries_df
- `ras_object` (RasPrj): Project object

**Returns:** Dict of {boundary_name: DataFrame}

#### get_info(dss_file)
Get DSS file information.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file

**Returns:** Dict with version, num_records, pathnames, file_size

## Usage

```python
from ras_commander.dss import RasDss

# Get catalog of DSS contents
catalog = RasDss.get_catalog("/path/to/file.dss")
print(catalog)

# Read time series
pathname = "/BASIN/GAGE1/FLOW/01JAN2020/1HOUR/OBS/"
df = RasDss.read_timeseries("/path/to/file.dss", pathname)
print(df)

# Write a small SHG gridded precipitation DSS
import numpy as np
import pandas as pd

data = np.arange(5 * 10 * 10, dtype="float32").reshape(5, 10, 10)
times = pd.date_range("2020-01-01 01:00", periods=5, freq="h")
written = RasDss.write_grid_timeseries(
    "/path/to/precip.dss",
    "/SHG/WATERSHED/PRECIP/01JAN2020:0000/01JAN2020:0100/SYNTHETIC/",
    data,
    times,
    {
        "cellsize": 2000,
        "origin": (1096000, 1516000),
        "crs": "SHG",
        "units": "mm",
        "data_type": "PER-CUM",
    },
)
print(written)

# Extract all boundary conditions from project
from ras_commander import init_ras_project, ras
init_ras_project("/path/to/project", "6.5")
bc_data = RasDss.extract_boundary_timeseries(ras.boundaries_df, ras)
```

## Grid Java API Mapping

`write_grid_timeseries()` uses the same lazy pyjnius/HEC Monolith setup as the
time-series methods. The Python inputs map to Java objects as follows:

| Python input | HEC Monolith class/member |
| --- | --- |
| `dss_file` | `hec.heclib.grid.GriddedData.setDSSFileName()` |
| A/B/C/F parts of `pathname` | `GriddedData.setGriddedPathnameParts()` |
| Generated D/E timestep windows | `GridInfo.setGridTimes()` and `GriddedData.setGriddedTimeWindow()` |
| `data[i]` flattened row-major | `hec.heclib.grid.GridData(float[], GridInfo)` |
| `grid_info["crs"] == "SHG"` | `hec.heclib.grid.AlbersInfo` with NAD83 SHG parameters |
| Other WKT CRS strings | `hec.heclib.grid.SpecifiedGridInfo.setSpatialReference()` |
| `cellsize`, `origin`, cell counts | `GridInfo.setCellInfo()` |
| `units`, `data_type` | `GridInfo.setParameterInfo()` |
| compression settings | `GridInfo.setCompressionInfo()` |

The bundled HEC Monolith exposes `hec.io.GridContainer`, but the ras-commander
Monolith cache does not include a `SpatialGridBean` class. The equivalent grid
payload is `GridData` plus a `GridInfo` subclass (`AlbersInfo`,
`SpecifiedGridInfo`, or `HrapInfo`). This writer stores records through
`GriddedData.storeGriddedData()` because that is the stable grid write path from
pyjnius for the Monolith version used by ras-commander.

## Requirements

- `pip install pyjnius`
- Java 8+ (JRE or JDK)
- HEC Monolith libraries (auto-downloaded on first use)
