# DSS Modules

Classes for reading HEC-DSS files.

## RasDss

Read HEC-DSS files for boundary condition extraction.

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

# Extract all boundary conditions from project
from ras_commander import init_ras_project, ras
init_ras_project("/path/to/project", "6.5")
bc_data = RasDss.extract_boundary_timeseries(ras.boundaries_df, ras)
```

## Requirements

- `pip install pyjnius`
- Java 8+ (JRE or JDK)
- HEC Monolith libraries (auto-downloaded on first use)
