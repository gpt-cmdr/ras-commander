# DSS Subpackage - Developer Guidance

This document provides guidance for AI agents and developers working with the `ras_commander.dss` subpackage.

## Overview

The DSS subpackage provides HEC-DSS file operations using HEC Monolith Java libraries via pyjnius. All dependencies are lazy-loaded to minimize import overhead.

## Module Structure

```
ras_commander/dss/
├── __init__.py          # Public API exports
├── AGENTS.md            # This file
├── RasDss.py            # Main DSS class with static methods
└── _hec_monolith.py     # HEC Monolith library downloader (private)
```

## Lazy Loading Architecture

### Three-Level Lazy Loading

1. **Parent Package Level** (`ras_commander/__init__.py`):
   - Uses `__getattr__` to defer `dss` subpackage import
   - `from ras_commander import RasDss` triggers lazy load
   - Users who don't use DSS never load the subpackage

2. **Subpackage Level** (`dss/__init__.py`):
   - Imports `RasDss` class eagerly (lightweight)
   - No Java/pyjnius imports at this level

3. **Method Level** (`RasDss.py`):
   - `_configure_jvm()` called on first DSS method use
   - `jnius_config` imported only when needed
   - `jnius.autoclass` imported only after JVM configured
   - HEC Monolith downloaded automatically on first use

### Import Timeline

```
import ras_commander              # Fast - no DSS code loaded
from ras_commander import RasDss  # Loads dss/__init__.py (fast)
RasDss.get_catalog("file.dss")    # Loads pyjnius, starts JVM, downloads Monolith
```

## Public API

### RasDss Class (Static Methods)

#### Read Methods

| Method | Purpose | Returns |
|--------|---------|---------|
| `get_catalog(dss_file)` | List all paths in DSS file | `List[str]` |
| `read_timeseries(dss_file, pathname)` | Read single time series | `DataFrame` |
| `read_multiple_timeseries(dss_file, pathnames)` | Read multiple time series | `Dict[str, DataFrame]` |
| `get_info(dss_file)` | Get file metadata | `Dict` |
| `extract_boundary_timeseries(boundaries_df, ...)` | Extract BC data | `DataFrame` |
| `shutdown_jvm()` | Placeholder (no-op) | `None` |

#### Write Methods

| Method | Purpose | Returns |
|--------|---------|---------|
| `write_timeseries(dss_file, pathname, times, values, ...)` | Write time series from arrays | `None` |
| `write_timeseries_from_dataframe(dss_file, pathname, df, ...)` | Write time series from DataFrame | `None` |

##### `write_timeseries()`

```python
RasDss.write_timeseries(
    dss_file: Union[str, Path],        # Path to DSS file (created if missing)
    pathname: str,                     # DSS pathname, e.g. "//BASIN/LOC/FLOW//1HOUR/FORECAST/"
    times: Union[List, np.ndarray, pd.DatetimeIndex],  # Timestamps
    values: Union[List, np.ndarray],   # Numeric values (same length as times)
    units: str = "CFS",                # Units string (e.g. "CFS", "FEET", "MM")
    data_type: str = "INST-VAL",       # Data type: "INST-VAL", "PER-AVER", "PER-CUM", "INST-CUM"
    create_if_missing: bool = True,    # Create DSS file and parent dirs if absent
) -> None
```

**DSS Pathname Format**: `"//A/B/C/D/E/F/"` — parts are Basin, Location, Parameter, Start Date, Interval, Version.
Leave Part D blank when writing (HEC-DSS fills it automatically): `"//BASIN/UPSTREAM/FLOW//1HOUR/FORECAST/"`.

**Time encoding**: Internally converts datetimes to integer minutes since HEC epoch (1899-12-31 00:00:00).
Timestamps must be timezone-naive or UTC-equivalent.

##### `write_timeseries_from_dataframe()`

```python
RasDss.write_timeseries_from_dataframe(
    dss_file: Union[str, Path],        # Path to DSS file (created if missing)
    pathname: str,                     # DSS pathname
    df: pd.DataFrame,                  # DataFrame with DatetimeIndex
    value_column: str = "value",       # Column name containing numeric values
    units: str = "CFS",                # Units string
    data_type: str = "INST-VAL",       # Data type (see above)
    create_if_missing: bool = True,    # Create DSS file and parent dirs if absent
) -> None
```

**DataFrame schema**: `df` must have a `DatetimeIndex` and at least one numeric column
(named by `value_column`). Extra columns are ignored.

**Example**:
```python
from ras_commander import RasDss
import pandas as pd

# Write from arrays
RasDss.write_timeseries(
    dss_file="boundary.dss",
    pathname="//MyBasin/Upstream/FLOW//1HOUR/FORECAST/",
    times=pd.date_range("2024-01-01", periods=24, freq="1h"),
    values=[100, 120, 150, 200, 180, 160] + [100] * 18,
    units="CFS",
    data_type="INST-VAL",
)

# Write from DataFrame
df = pd.DataFrame(
    {"value": [100, 120, 150, 200]},
    index=pd.date_range("2024-01-01", periods=4, freq="1h")
)
RasDss.write_timeseries_from_dataframe(
    dss_file="boundary.dss",
    pathname="//MyBasin/Upstream/FLOW//1HOUR/FORECAST/",
    df=df,
    value_column="value",
    units="CFS",
)
```

**Lazy-loading note**: Write methods trigger the same three-level lazy load as read methods —
`_configure_jvm()` is called on first write, pyjnius starts the JVM, and HEC Monolith
(~20 MB) is auto-downloaded if not already cached at `~/.ras-commander/dss/`.
The JVM can only be started once per process; if `_configure_jvm()` has already been
called (e.g., by a prior read call), write methods reuse the running JVM.

### Validation Methods

DSS pathname validation methods (see `examples/33_validating_dss_paths.ipynb`):

| Method | Purpose | Returns |
|--------|---------|---------|
| `check_pathname_format(pathname)` | Validate DSS pathname structure | `ValidationResult` |
| `check_file_exists(dss_file)` | Verify file exists and is accessible | `ValidationResult` |
| `check_pathname_exists(dss_file, pathname)` | Verify pathname in catalog | `ValidationResult` |
| `check_data_availability(dss_file, pathname, ...)` | Verify time series data coverage | `ValidationResult` |
| `check_pathname(dss_file, pathname, ...)` | Comprehensive validation (all checks) | `ValidationReport` |
| `is_valid_pathname(pathname)` | Quick format check (boolean) | `bool` |
| `is_pathname_available(dss_file, pathname)` | Quick availability check (boolean) | `bool` |

### DataFrame Metadata

Time series DataFrames include metadata in `df.attrs`:
- `pathname`: Original DSS path
- `units`: Data units (e.g., "CFS")
- `type`: Data type (e.g., "INST-VAL")
- `interval`: Data interval in minutes
- `dss_file`: Absolute path to source file

## Dependencies

### Required (Lazy Loaded)
- **pyjnius**: `pip install pyjnius`
- **Java JRE/JDK 8+**: Must be installed, JAVA_HOME set

### Auto-Downloaded
- **HEC Monolith** (~20 MB): Downloaded to `~/.ras-commander/dss/`
  - 7 JAR files from HEC Nexus/Maven
  - Platform-specific native library (javaHeclib.dll/.so/.dylib)

### Always Available
- `pandas`, `numpy`: Core dependencies
- `requests`, `tqdm`: For downloading Monolith

## Adding New DSS Methods

When adding new methods to `RasDss`:

1. **Configure JVM First**:
   ```python
   @staticmethod
   @log_call
   def new_method(dss_file: Union[str, Path]) -> ...:
       # Must be called before any jnius imports
       RasDss._configure_jvm()

       # Now safe to import Java classes
       from jnius import autoclass
       HecDss = autoclass('hec.heclib.dss.HecDss')
       ...
   ```

2. **Use Decorator**: Always use `@log_call` for traceability

3. **Handle Cleanup**: Use try/finally to close DSS files:
   ```python
   dss = HecDss.open(dss_file)
   try:
       # operations
   finally:
       dss.done()
   ```

4. **Path Resolution**: Always resolve to absolute paths:
   ```python
   dss_file = str(Path(dss_file).resolve())
   ```

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

## Common Issues

### Java Not Found
- Set `JAVA_HOME` environment variable
- Or install Java and ensure it's in PATH

### pyjnius Import Error
- Install with: `pip install pyjnius`
- Ensure JAVA_HOME is set before importing pyjnius

### JVM Already Started
- JVM can only be configured once per process
- If using in notebooks, restart kernel to reconfigure

### DSS File Not Found
- Use absolute paths or resolve relative to project directory
- Check file exists before calling DSS methods

## Integration with Parent Package

### Import Pattern
```python
# Preferred - lazy loads DSS only when used
from ras_commander import RasDss

# Also works - direct import
from ras_commander.dss import RasDss
```

### With RasPrj
```python
from ras_commander import init_ras_project, RasDss

ras = init_ras_project("project_path", "6.6")
enhanced = RasDss.extract_boundary_timeseries(
    ras.boundaries_df,
    ras_object=ras
)
```

## Version History

- **v0.82.0**: Initial RasDss implementation
- **v0.86.0**: Moved to `dss/` subpackage with lazy loading
- **v0.89.x**: Added `write_timeseries()` and `write_timeseries_from_dataframe()` write methods
