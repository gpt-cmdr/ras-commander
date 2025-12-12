# RasDss API Reference

Complete API documentation for the RasDss class.

## Class Overview

```python
from ras_commander import RasDss
```

**Static Class**: All methods are static (no instantiation required)

**Technology**: HEC Monolith Java libraries via pyjnius

**Lazy Loading**: JVM and dependencies loaded on first method call

## Methods

### get_catalog

List all data pathnames in a DSS file.

```python
@staticmethod
def get_catalog(dss_file: Union[str, Path]) -> List[str]
```

**Parameters**:
- `dss_file`: Path to DSS file (string or Path object)

**Returns**:
- `List[str]`: All DSS pathnames in the file

**Example**:
```python
catalog = RasDss.get_catalog("Bald_Eagle_Creek.dss")
print(f"Total paths: {len(catalog)}")

for path in catalog[:10]:
    print(path)
```

**Notes**:
- Returns condensed pathnames (single slashes removed if empty)
- Pathnames sorted alphabetically
- Empty parts shown as single slash: `//LOCATION/FLOW///GAGE/`

---

### read_timeseries

Read a single DSS time series by pathname.

```python
@staticmethod
def read_timeseries(
    dss_file: Union[str, Path],
    pathname: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> pd.DataFrame
```

**Parameters**:
- `dss_file`: Path to DSS file
- `pathname`: DSS pathname (e.g., `//LOCATION/FLOW/01JAN2000/15MIN/RUN:PMF/`)
- `start_date`: Optional start date (not yet implemented)
- `end_date`: Optional end date (not yet implemented)

**Returns**:
- `pd.DataFrame`: Time series with DatetimeIndex and 'value' column

**DataFrame Structure**:
- **Index**: DatetimeIndex (datetime of each value)
- **Columns**: 'value' (float)
- **Attrs**: Metadata dictionary
  - `pathname`: Original DSS pathname
  - `units`: Data units (e.g., "CFS", "FEET")
  - `type`: Data type (e.g., "INST-VAL", "PER-AVER")
  - `interval`: Data interval in minutes (int)
  - `dss_file`: Absolute path to source DSS file

**Example**:
```python
pathname = "//BALD EAGLE 40/FLOW/01JAN1999/15MIN/RUN:PMF-EVENT/"
df = RasDss.read_timeseries("file.dss", pathname)

print(f"Points: {len(df)}")
print(f"Units: {df.attrs['units']}")
print(df.head())
```

**Raises**:
- `FileNotFoundError`: DSS file not found
- `ValueError`: Invalid pathname or data not found
- `RuntimeError`: Java/JVM errors

---

### read_multiple_timeseries

Read multiple DSS time series in batch.

```python
@staticmethod
def read_multiple_timeseries(
    dss_file: Union[str, Path],
    pathnames: List[str]
) -> Dict[str, Optional[pd.DataFrame]]
```

**Parameters**:
- `dss_file`: Path to DSS file
- `pathnames`: List of DSS pathnames to extract

**Returns**:
- `Dict[str, Optional[pd.DataFrame]]`: Dictionary mapping pathname to DataFrame
  - Successful extractions: DataFrame with time series
  - Failed extractions: None

**Example**:
```python
pathnames = [
    "//LOCATION1/FLOW/01JAN1999/15MIN/RUN:PMF/",
    "//LOCATION2/FLOW/01JAN1999/15MIN/RUN:PMF/",
]

results = RasDss.read_multiple_timeseries("file.dss", pathnames)

for pathname, df in results.items():
    if df is not None:
        print(f"{pathname}: {len(df)} points, {df.attrs['units']}")
    else:
        print(f"{pathname}: FAILED")
```

**Notes**:
- Continues on individual failures (returns None for failed paths)
- More efficient than multiple `read_timeseries()` calls
- DSS file opened once, pathnames read sequentially

---

### get_info

Get summary information about a DSS file.

```python
@staticmethod
def get_info(dss_file: Union[str, Path]) -> Dict
```

**Parameters**:
- `dss_file`: Path to DSS file

**Returns**:
- `Dict`: File metadata and statistics
  - `filename`: Basename of DSS file
  - `filepath`: Absolute path to file
  - `file_size_mb`: File size in megabytes
  - `total_paths`: Total number of pathnames
  - `sample_paths`: First 50 pathnames (list)

**Example**:
```python
info = RasDss.get_info("Bald_Eagle_Creek.dss")

print(f"File: {info['filename']}")
print(f"Size: {info['file_size_mb']:.2f} MB")
print(f"Total paths: {info['total_paths']}")

print("\nSample paths:")
for path in info['sample_paths'][:10]:
    print(f"  {path}")
```

**Notes**:
- Faster than `get_catalog()` for large files
- Provides enough info for validation without full catalog
- Sample limited to first 50 paths

---

### extract_boundary_timeseries

Extract DSS time series for all DSS-defined boundaries in a DataFrame.

```python
@staticmethod
def extract_boundary_timeseries(
    boundaries_df: pd.DataFrame,
    project_dir: Optional[Union[str, Path]] = None,
    ras_object: Optional[object] = None
) -> pd.DataFrame
```

**Parameters**:
- `boundaries_df`: Boundary conditions DataFrame (from `ras.boundaries_df`)
- `project_dir`: Optional project directory (if ras_object not provided)
- `ras_object`: Optional RasPrj instance (preferred, auto-detects project_dir)

**Returns**:
- `pd.DataFrame`: Enhanced boundaries_df with new 'dss_timeseries' column

**Enhanced DataFrame**:
- Original columns preserved
- New column: `dss_timeseries` (DataFrame or None)
  - DSS boundaries: Contains extracted time series DataFrame
  - Manual boundaries: None

**Example**:
```python
from ras_commander import init_ras_project, RasDss

ras = init_ras_project("project_path", "6.6")

# Extract all DSS data
enhanced = RasDss.extract_boundary_timeseries(
    ras.boundaries_df,
    ras_object=ras
)

# Access extracted data
dss_boundaries = enhanced[enhanced['Use DSS'] == True]
for idx, row in dss_boundaries.iterrows():
    if row['dss_timeseries'] is not None:
        df = row['dss_timeseries']
        print(f"{row['bc_type']}: {len(df)} points")
```

**Workflow**:
1. Filters boundaries for `Use DSS == True`
2. Resolves DSS file paths (relative to project directory)
3. Reads each DSS pathname
4. Stores DataFrames in new column
5. Logs success/failure counts

**Logging Output**:
```
INFO - Found 7 DSS-defined boundaries
INFO - Row 0: Extracted 673 points from Bald_Eagle_Creek.dss
INFO - Row 2: Extracted 673 points from Bald_Eagle_Creek.dss
...
INFO - Extraction complete: 7 success, 0 failed
```

**Notes**:
- Handles missing files gracefully (logs warning, continues)
- Handles invalid pathnames gracefully (logs warning, continues)
- DSS file paths resolved relative to project directory
- Returns copy of original DataFrame (does not modify in-place)

---

### shutdown_jvm

Placeholder for JVM lifecycle management.

```python
@staticmethod
def shutdown_jvm() -> None
```

**Parameters**: None

**Returns**: None

**Notes**:
- Currently a no-op (does nothing)
- JVM shutdown not typically needed with pyjnius
- JVM lives for entire Python process lifetime
- Included for API completeness

---

## DSS Pathname Format

DSS pathnames have 7 parts separated by slashes:

```
/A/B/C/D/E/F/
```

### Part Definitions

| Part | Name | Description | Examples |
|------|------|-------------|----------|
| A | Project | Project or basin name | BALD EAGLE, SACRAMENTO |
| B | Location | Gauge, river station, or location | MILESBURG, GAGE-01 |
| C | Parameter | Data type or parameter | FLOW, STAGE, PRECIP, TEMP |
| D | Start Date | Beginning date (if time series) | 01JAN2000, 15SEP1999 |
| E | Interval | Time interval | 15MIN, 1HOUR, 1DAY |
| F | Version | Scenario, version, or source | RUN:PMF, GAGE, OBS |

### Examples

**Flow Hydrograph**:
```
//BALD EAGLE 40/FLOW/01JAN1999/15MIN/RUN:PMF-EVENT/
```
- A: (empty)
- B: BALD EAGLE 40
- C: FLOW
- D: 01JAN1999
- E: 15MIN
- F: RUN:PMF-EVENT

**Stage Observation**:
```
//MILESBURG GAGE/STAGE/01JUN2020/1HOUR/OBS/
```
- B: MILESBURG GAGE
- C: STAGE
- D: 01JUN2020
- E: 1HOUR
- F: OBS

**Paired Data** (elevation-storage):
```
//SAYERS - ELEVATION-STORAGE/ELEVATION-STORAGE///TABLE/
```
- D, E: Empty (not time series)
- F: TABLE

### Common Parameter Names

| Parameter | Description | Typical Units |
|-----------|-------------|---------------|
| FLOW | Streamflow discharge | CFS, CMS |
| STAGE | Water surface elevation | FEET, METERS |
| PRECIP | Precipitation | IN, MM |
| PRECIP-INC | Incremental precipitation | IN, MM |
| TEMPERATURE | Air temperature | DEG F, DEG C |
| ELEVATION-STORAGE | Elevation-storage curve | FEET, AC-FT |
| INFILTRATION | Infiltration rate | IN/HR |

### Common Interval Names

| Interval | Description |
|----------|-------------|
| 15MIN | 15 minutes |
| 1HOUR | 1 hour |
| 1DAY | 1 day |
| IR-MONTH | Irregular monthly |
| IR-YEAR | Irregular yearly |

## JVM Configuration

### Automatic Configuration

First DSS method call triggers:
1. HEC Monolith download check (if needed)
2. JVM classpath setup
3. Native library path setup
4. JVM start

### Manual JAVA_HOME

If Java not auto-detected:
```bash
# Windows
set JAVA_HOME=C:\Program Files\Java\jdk-11

# Linux/Mac
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk
```

### Classpath

JVM classpath includes HEC Monolith JARs:
- hec.jar
- heclib.jar
- rma.jar
- hecData.jar
- grid.jar
- hec-dssvue.jar
- lib/javaHeclib.jar

## Testing

Run module directly for basic test:
```bash
python -m ras_commander.dss.RasDss
```

This tests:
- JVM configuration
- Monolith download (if needed)
- Catalog reading
- Time series extraction

## See Also

- **Troubleshooting**: [troubleshooting.md](troubleshooting.md)
- **Examples**: [../examples/](../examples/)
- **Developer Docs**: `ras_commander/dss/AGENTS.md`
- **Example Notebook**: `examples/22_dss_boundary_extraction.ipynb`
