---
name: reading-dss-boundary-data
description: |
  Reads HEC-DSS files (V6 and V7) for boundary condition extraction using
  RasDss class. Handles JVM configuration, HEC Monolith download, catalog
  reading, and time series extraction. Use when working with DSS files,
  extracting boundary data, reading HEC-HMS output, or integrating DSS workflows.
triggers:
  - "DSS"
  - "HEC-DSS"
  - "boundary condition"
  - "time series"
  - "JVM"
  - "Java"
  - "catalog"
  - "pathname"
  - "HEC-HMS"
  - "Monolith"
  - "pyjnius"
  - "read DSS"
  - "extract DSS"
  - "DSS boundary"
version: 1.0.0
---

# Reading DSS Boundary Data

Expert guidance for extracting boundary condition data from HEC-DSS files using ras-commander's RasDss class.

## Quick Start

```python
from ras_commander import init_ras_project, RasDss

# Initialize project
ras = init_ras_project("path/to/project", "6.6")

# Read DSS catalog
catalog = RasDss.get_catalog("file.dss")

# Extract single time series
df = RasDss.read_timeseries("file.dss", pathname)

# Extract ALL boundary DSS data (recommended)
enhanced = RasDss.extract_boundary_timeseries(
    ras.boundaries_df,
    ras_object=ras
)
```

## When to Use This Skill

Use when:
- Working with HEC-DSS files (V6 or V7)
- Extracting boundary conditions from DSS
- Reading HEC-HMS model output
- Integrating DSS workflows with HEC-RAS
- Need to catalog DSS file contents
- Converting DSS data to pandas DataFrames

## Technology Overview

### HEC-DSS Format
- **DSS** = Data Storage System
- Binary format for time series and paired data
- Used by HEC-HMS, HEC-ResSim, HEC-FIA
- Versions: V6 (older) and V7 (current)
- Data identified by **pathname** (7-part string)

### DSS Pathname Format
```
/A/B/C/D/E/F/
```
- **A**: Project or basin name
- **B**: Location (e.g., gauge, river station)
- **C**: Parameter (FLOW, STAGE, PRECIP, etc.)
- **D**: Start date (e.g., 01JAN2000)
- **E**: Time interval (15MIN, 1HOUR, 1DAY, etc.)
- **F**: Version or scenario (RUN:SCENARIO, GAGE, OBS, etc.)

Example:
```
//BALD EAGLE 40/FLOW/01JAN1999/15MIN/RUN:PMF-EVENT/
```

## Lazy Loading Architecture

### No Overhead Until First Use
RasDss uses three-level lazy loading:

1. **Package Import**: Lightweight, no Java loaded
   ```python
   from ras_commander import RasDss  # Fast, no JVM
   ```

2. **First Method Call**: Configures JVM, downloads Monolith
   ```python
   catalog = RasDss.get_catalog("file.dss")  # Triggers setup
   ```

3. **Subsequent Calls**: Uses cached JVM and libraries
   ```python
   df = RasDss.read_timeseries(...)  # Fast, reuses JVM
   ```

### What Gets Downloaded?
**HEC Monolith** (~20 MB, one-time):
- 7 JAR files from HEC Nexus
- Platform-specific native library (javaHeclib.dll/.so/.dylib)
- Downloaded to `~/.ras-commander/dss/`
- Auto-download on first use

### Dependencies
**Required** (must install manually):
```bash
pip install pyjnius
```

**Required** (system):
- Java JRE or JDK 8+ (set JAVA_HOME)

**Auto-downloaded**:
- HEC Monolith libraries

## Core Workflows

### 1. Read DSS Catalog

List all data in a DSS file:

```python
catalog = RasDss.get_catalog("Bald_Eagle_Creek.dss")
print(f"Total paths: {len(catalog)}")

for path in catalog[:10]:
    print(path)
```

Output:
```
//BALD EAGLE AT MILESBURG/FLOW/01SEP2004/15MIN/GAGE/
//FISHING CREEK/FLOW-BASE/01JUN1972/15MIN/RUN:1972 CALIBRATION EVENT/
...
```

### 2. Get DSS File Info

Quick summary without reading all paths:

```python
info = RasDss.get_info("file.dss")
print(f"File: {info['filename']}")
print(f"Size: {info['file_size_mb']:.2f} MB")
print(f"Total paths: {info['total_paths']}")
print(f"Sample paths: {info['sample_paths'][:5]}")
```

### 3. Extract Single Time Series

Read one pathname:

```python
pathname = "//BALD EAGLE 40/FLOW/01JAN1999/15MIN/RUN:PMF-EVENT/"
df = RasDss.read_timeseries("file.dss", pathname)

print(f"Points: {len(df)}")
print(f"Date range: {df.index.min()} to {df.index.max()}")
print(f"Value range: {df['value'].min():.2f} to {df['value'].max():.2f}")
print(f"Units: {df.attrs['units']}")
```

**DataFrame Structure**:
- Index: DatetimeIndex
- Column: 'value' (float)
- Attrs: pathname, units, type, interval, dss_file

### 4. Extract Multiple Time Series

Batch read multiple paths:

```python
pathnames = [
    "//LOCATION1/FLOW/01JAN1999/15MIN/RUN:PMF/",
    "//LOCATION2/FLOW/01JAN1999/15MIN/RUN:PMF/",
]

results = RasDss.read_multiple_timeseries("file.dss", pathnames)

for pathname, df in results.items():
    if df is not None:
        print(f"{pathname}: {len(df)} points")
    else:
        print(f"{pathname}: FAILED")
```

### 5. Extract ALL Boundary DSS Data (Recommended)

Automatically extract DSS data for all DSS-defined boundaries:

```python
from ras_commander import init_ras_project, RasDss

# Initialize project
ras = init_ras_project("project_path", "6.6")

# Extract all DSS boundary data
enhanced = RasDss.extract_boundary_timeseries(
    ras.boundaries_df,
    ras_object=ras
)

# Access extracted data
for idx, row in enhanced.iterrows():
    if row['Use DSS'] and row['dss_timeseries'] is not None:
        df = row['dss_timeseries']
        print(f"{row['bc_type']}: {len(df)} points")
```

**Result**: Original boundaries_df with new 'dss_timeseries' column containing DataFrames.

## Working with Extracted Data

### Access Time Series

```python
# Get first DSS boundary
dss_boundaries = enhanced[enhanced['Use DSS'] == True]
first_dss = dss_boundaries.iloc[0]

# Access time series DataFrame
df = first_dss['dss_timeseries']

# Statistics
print(df['value'].describe())

# Metadata
print(f"Units: {df.attrs['units']}")
print(f"Pathname: {df.attrs['pathname']}")
print(f"Interval: {df.attrs['interval']} minutes")
```

### Plot Time Series

```python
import matplotlib.pyplot as plt

df = row['dss_timeseries']
df['value'].plot(figsize=(12, 4))
plt.title(f"{row['bc_type']} - {row['river_reach_name']}")
plt.ylabel(f"Flow ({df.attrs['units']})")
plt.grid(True)
plt.show()
```

### Export to CSV

```python
# Drop DataFrame column for CSV export
export_df = enhanced.drop(columns=['dss_timeseries'])

# Add summary statistics
for idx, row in enhanced.iterrows():
    if row['Use DSS'] and row['dss_timeseries'] is not None:
        df = row['dss_timeseries']
        export_df.at[idx, 'dss_points'] = len(df)
        export_df.at[idx, 'dss_mean'] = df['value'].mean()
        export_df.at[idx, 'dss_max'] = df['value'].max()

export_df.to_csv("boundaries_summary.csv", index=False)
```

## Common Patterns

### Pattern 1: Find Flow Hydrographs

```python
catalog = RasDss.get_catalog("file.dss")
flow_paths = [p for p in catalog if '/FLOW/' in p]
print(f"Found {len(flow_paths)} flow time series")
```

### Pattern 2: Extract by Date Range

```python
# Note: Start/end date filtering not yet implemented
# Extract full series and filter with pandas
df = RasDss.read_timeseries("file.dss", pathname)
df_filtered = df.loc['2000-01-01':'2000-01-07']
```

### Pattern 3: Compare Manual vs DSS Boundaries

```python
manual = enhanced[enhanced['Use DSS'] == False]
dss = enhanced[enhanced['Use DSS'] == True]

print(f"Manual boundaries: {len(manual)}")
print(f"DSS boundaries: {len(dss)}")
```

### Pattern 4: Validate DSS Files

```python
# Check if DSS file exists before extraction
from pathlib import Path

dss_file = Path("file.dss")
if not dss_file.exists():
    print(f"DSS file not found: {dss_file}")
else:
    catalog = RasDss.get_catalog(dss_file)
    print(f"File OK: {len(catalog)} paths")
```

## Error Handling

### Common Errors

**1. pyjnius Not Installed**
```
ImportError: pyjnius is required for DSS file operations.
Install with: pip install pyjnius
```
**Fix**: `pip install pyjnius`

**2. Java Not Found**
```
RuntimeError: JAVA_HOME not set and Java not found automatically.
Please install Java JRE/JDK 8+ and set JAVA_HOME.
```
**Fix**: Install Java and set JAVA_HOME environment variable

**3. JVM Already Started**
```
RuntimeError: JVM configuration already done.
```
**Fix**: Restart Python process or notebook kernel

**4. DSS File Not Found**
```
FileNotFoundError: DSS file not found: ...
```
**Fix**: Use absolute paths or resolve relative to project directory

### Robust Error Handling

```python
from pathlib import Path

try:
    dss_file = Path("file.dss").resolve()
    if not dss_file.exists():
        raise FileNotFoundError(f"DSS file not found: {dss_file}")

    catalog = RasDss.get_catalog(dss_file)
    print(f"Success: {len(catalog)} paths")

except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install: pip install pyjnius")

except RuntimeError as e:
    print(f"Java/JVM error: {e}")
    print("Check JAVA_HOME and Java installation")

except Exception as e:
    print(f"Unexpected error: {e}")
```

## Integration with HEC-RAS

### Workflow 1: Extract and Analyze

```python
from ras_commander import init_ras_project, RasDss

# Initialize project
ras = init_ras_project("project_path", "6.6")

# Get plan boundaries
plan_boundaries = ras.boundaries_df[
    ras.boundaries_df['unsteady_number'] == '07'
]

# Extract DSS data
enhanced = RasDss.extract_boundary_timeseries(
    plan_boundaries,
    ras_object=ras
)

# Count DSS boundaries
dss_count = (enhanced['Use DSS'] == True).sum()
print(f"Plan 07: {dss_count} DSS boundaries")
```

### Workflow 2: DSS + Manual Boundaries

```python
# Separate DSS and manual boundaries
dss_bc = enhanced[enhanced['Use DSS'] == True]
manual_bc = enhanced[enhanced['Use DSS'] == False]

print("DSS Boundaries:")
for idx, row in dss_bc.iterrows():
    if row['dss_timeseries'] is not None:
        df = row['dss_timeseries']
        print(f"  {row['bc_type']}: {len(df)} points")

print("\nManual Boundaries:")
for idx, row in manual_bc.iterrows():
    print(f"  {row['bc_type']}: {row['hydrograph_num_values']} points")
```

## Cross-References

- **API Reference**: See [dss-api.md](reference/dss-api.md) for complete method signatures
- **Troubleshooting**: See [troubleshooting.md](reference/troubleshooting.md) for Java/JVM issues
- **Examples**: See [examples/](examples/) for complete scripts
- **Source**: See `ras_commander/dss/AGENTS.md` for developer guidance

## Key Takeaways

1. **Lazy Loading**: No overhead until first DSS method call
2. **Auto-Download**: HEC Monolith installed automatically
3. **Unified API**: DSS and manual boundaries in same DataFrame
4. **One-Call Extraction**: `extract_boundary_timeseries()` handles all DSS data
5. **Metadata Preserved**: Units, pathname, interval in df.attrs
6. **V6 and V7**: Both DSS versions supported

## Example Project

The BaldEagleCrkMulti2D example contains DSS boundary conditions:
```python
from ras_commander import RasExamples
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")
```

See `examples/22_dss_boundary_extraction.ipynb` for complete workflow.
