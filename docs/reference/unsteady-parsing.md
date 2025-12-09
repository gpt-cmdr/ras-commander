# Unsteady Flow File Parsing Reference

Reference for HEC-RAS unsteady flow file (.u##) structure and parsing.

## Overview

Unsteady flow files contain **time-varying boundary conditions** for unsteady flow simulations. They define:

- Flow hydrographs (inflow boundaries)
- Stage hydrographs (downstream boundaries)
- Lateral inflows
- Gate operations
- Precipitation hydrographs (for rain-on-grid when not using gridded data)
- Rating curves

## File Location

```
{project_folder}/{project_name}.u{number}
```

Example: `C:\Projects\Muncie\Muncie.u01`

## File Structure

### Header Section

```
Flow Title=100-Year Storm Event
Program Version=6.50
Use Restart=-1
Restart Filename=Muncie.p01.rst
```

| Key | Description | Values |
|-----|-------------|--------|
| `Flow Title=` | Display name (max 24 chars) | String |
| `Program Version=` | HEC-RAS version that created file | e.g., `6.50` |
| `Use Restart=` | Restart file usage | `-1`=use, `0`=don't use |
| `Restart Filename=` | Path to restart file | Relative path |

### Boundary Location Block

Each boundary condition starts with a location definition:

```
Boundary Location=Big Creek,Upper Reach,1000,         ,                ,                ,                ,
```

**Format:** 9 comma-separated fields (some may be empty):

| Field | Description |
|-------|-------------|
| 1 | River Name |
| 2 | Reach Name |
| 3 | River Station |
| 4 | Downstream River Station (for reach boundaries) |
| 5 | Storage Area Connection |
| 6 | Storage Area Name |
| 7 | Pump Station Name |
| 8-9 | Reserved (blank) |

### Interval Specification

```
Interval=15MIN
```

Defines the time interval for the following table data. Common values:
- `1MIN`, `5MIN`, `15MIN`, `30MIN`, `1HOUR`, `6HOUR`, `1DAY`

### DSS References

External time series can be referenced from DSS files:

```
DSS File=..\Hydrology\boundary_data.dss
DSS Path=/BIG CREEK/UPPER REACH/FLOW/01JAN2020/15MIN/COMPUTED/
```

## Table Types

### Flow Hydrograph

Inflow boundary condition (Q vs time):

```
Flow Hydrograph= 48
     100     150     200     300     450     600     800    1000    1200    1400
    1600    1800    2000    2200    2400    2600    2800    3000    2800    2600
    2400    2200    2000    1800    1600    1400    1200    1000     800     600
     500     400     350     300     250     200     180     160     150     140
     130     120     115     110     105     100     100     100
```

- Count after `=` indicates total number of values
- Values are **paired**: (time, flow), (time, flow), ...
- Times are in hours from simulation start
- Fixed-width format: 8 characters per value, 10 values per line

### Stage Hydrograph

Downstream stage boundary:

```
Stage Hydrograph= 24
       0    10.5     0.5    10.8       1    11.2     1.5    11.8       2    12.5
     2.5    13.2       3    13.8     3.5    14.2       4    14.0     4.5    13.5
       5    13.0     5.5    12.5       6    12.0     6.5    11.5
```

Paired values: (time, stage elevation)

### Gate Openings

Gate operation schedule:

```
Gate Openings= 6
       0       0     0.5     0.5       1       1       2       1       4     0.5
       6       0
```

Paired values: (time, gate opening fraction or height)

### Lateral Inflow Hydrograph

Lateral inflow along a reach:

```
Lateral Inflow Hydrograph= 20
       0      50     0.5     100       1     200     1.5     350       2     500
     2.5     450       3     400     3.5     300       4     200       5     100
```

### Uniform Lateral Inflow

Constant lateral inflow rate:

```
Uniform Lateral Inflow= 2
       0    0.05
```

Values: (time, inflow rate per unit length)

### Precipitation Hydrograph

Rainfall for rain-on-grid (when not using gridded meteorology):

```
Precipitation Hydrograph= 12
       0       0     0.5     0.1       1     0.25     1.5     0.5       2     0.8
     2.5       1       3     0.8     3.5     0.5       4     0.2     4.5       0
```

Paired values: (time, precipitation rate in in/hr or mm/hr)

### Rating Curve

Stage-discharge relationship for boundaries:

```
Rating Curve= 10
    10.0     100    11.0     500    12.0    1500    13.0    3000    14.0    5000
```

Paired values: (stage, discharge)

## Fixed-Width Format Details

### 8-Character Fields

All numeric tables use FORTRAN-style fixed-width formatting:

```
Columns:  0-7      8-15     16-23    24-31    32-39    40-47    48-55    56-63    64-71    72-79
Values:   val1     val2     val3     val4     val5     val6     val7     val8     val9     val10
```

- **Width**: 8 characters per value
- **Alignment**: Right-justified, left-padded with spaces
- **Line limit**: 10 values per line (80 characters total)
- **Last line**: May have fewer values

### Parsing Fixed-Width Tables

```python
def parse_fixed_width_table(lines, start, num_values):
    """Parse fixed-width table from unsteady file."""
    values = []
    line_idx = start

    while len(values) < num_values and line_idx < len(lines):
        line = lines[line_idx]
        # Parse 8-character chunks
        for i in range(0, len(line.rstrip()), 8):
            field = line[i:i+8].strip()
            if field:
                try:
                    values.append(float(field))
                except ValueError:
                    # Handle merged values (e.g., "197.96657.39")
                    import re
                    parts = re.findall(r'-?\d+\.?\d*', field)
                    values.extend([float(p) for p in parts])
        line_idx += 1

    return values
```

!!! warning "Never Use `.split()`"
    Fixed-width data must be parsed by column position, not by whitespace splitting. Values may touch without separators when they fill their columns.

## Complete Example File

```
Flow Title=Hurricane Event
Program Version=6.50
Use Restart=0
Boundary Location=Main River,Upper,5280,         ,                ,                ,                ,
Interval=15MIN
Flow Hydrograph= 24
       0     100    0.25     200     0.5     500    0.75    1000       1    2000
    1.25    3500     1.5    5000    1.75    6000       2    5500    2.25    4500
    2.5    3500    2.75    2500       3    1500    3.25    1000     3.5     500
    3.75     300       4     200
Boundary Location=Main River,Lower,0,         ,                ,                ,                ,
Interval=15MIN
Stage Hydrograph= 8
       0      98     0.5      99       1     100       2     101       3     100
       4      99     4.5      98       5      98
Boundary Location=,         ,,         ,                ,Reservoir_1                ,                ,
Interval=1HOUR
DSS File=..\Meteorology\rainfall.dss
DSS Path=/BASIN/RESERVOIR_1/PRECIP-INC/01JAN2020/1HOUR/OBSERVED/
```

## Parsing Implementation

### RasUnsteady Methods

| Method | Description |
|--------|-------------|
| `extract_boundary_and_tables()` | Parse all boundaries with their tables |
| `identify_tables()` | Locate table start/end positions |
| `parse_fixed_width_table()` | Convert fixed-width to DataFrame |
| `extract_tables()` | Extract all tables as dict of DataFrames |
| `write_table_to_file()` | Write modified table back to file |

### RasPrj Methods

| Method | Description |
|--------|-------------|
| `_parse_unsteady_file()` | Extract metadata from unsteady file |
| `_parse_boundary_condition()` | Parse individual boundary blocks |
| `get_boundary_conditions()` | Get all boundaries as DataFrame |

### Extracting Boundaries

```python
from ras_commander import RasUnsteady, RasPlan

# Get path to unsteady file
unsteady_path = RasPlan.get_unsteady_path("01")

# Extract all boundaries and their tables
boundaries_df = RasUnsteady.extract_boundary_and_tables(unsteady_path)

# Print boundary information
for idx, row in boundaries_df.iterrows():
    print(f"Boundary {idx + 1}:")
    print(f"  River: {row['River Name']}")
    print(f"  Reach: {row['Reach Name']}")
    print(f"  Station: {row['River Station']}")
    print(f"  DSS File: {row['DSS File']}")

    # Access tables
    for table_name, table_df in row['Tables'].items():
        print(f"  {table_name}: {len(table_df)} values")
```

### DataFrame Output Structure

**boundaries_df columns:**

| Column | Description |
|--------|-------------|
| `River Name` | River name from boundary location |
| `Reach Name` | Reach name |
| `River Station` | River station |
| `Downstream River Station` | For reach-type boundaries |
| `Storage Area Connection` | Storage area connection flag |
| `Storage Area Name` | Storage area name (if applicable) |
| `Pump Station Name` | Pump station (if applicable) |
| `DSS File` | External DSS file path |
| `Tables` | Dict of {table_name: DataFrame} |

### Modifying Tables

```python
from ras_commander import RasUnsteady
import pandas as pd

# Read current tables
unsteady_path = RasPlan.get_unsteady_path("01")
tables = RasUnsteady.extract_tables(unsteady_path)

# Modify flow hydrograph (scale by 1.2)
if 'Flow Hydrograph' in tables:
    tables['Flow Hydrograph']['Value'] *= 1.2

    # Write back
    RasUnsteady.write_table_to_file(
        unsteady_path,
        'Flow Hydrograph=',
        tables['Flow Hydrograph']
    )
```

## Count Interpretation

!!! danger "Critical: Count Meaning Varies"
    The number after `=` in table headers represents different things:

| Table Type | Count Meaning | Total Values |
|------------|---------------|--------------|
| `Flow Hydrograph=` | Number of pairs | count × 2 |
| `Stage Hydrograph=` | Number of pairs | count × 2 |
| `Gate Openings=` | Number of pairs | count × 2 |
| `Rating Curve=` | Number of pairs | count × 2 |
| `Precipitation Hydrograph=` | Number of pairs | count × 2 |

All hydrograph/curve types store **paired values** (time, value), so the actual number of numeric values is `count × 2`.

## Validation

### Check Boundary Completeness

```python
def validate_unsteady_file(unsteady_path):
    """Validate unsteady file structure."""
    boundaries_df = RasUnsteady.extract_boundary_and_tables(unsteady_path)

    issues = []
    for idx, row in boundaries_df.iterrows():
        # Check for empty location
        if not row['River Name'] and not row['Storage Area Name']:
            issues.append(f"Boundary {idx}: Missing location information")

        # Check for missing tables
        if not row['Tables'] and not row['DSS File']:
            issues.append(f"Boundary {idx}: No data tables or DSS reference")

    return issues
```

### Verify Table Lengths

```python
def verify_table_counts(boundaries_df):
    """Verify table data matches declared counts."""
    for idx, row in boundaries_df.iterrows():
        for table_name, table_df in row['Tables'].items():
            # Tables store pairs, so length should be even
            if len(table_df) % 2 != 0:
                print(f"Warning: {table_name} has odd number of values")
```

## Relationship to HDF

Most boundary conditions are stored in plain text `.u##` files. However, **gridded precipitation** is stored in HDF:

| Data Type | Storage Location |
|-----------|------------------|
| Flow/Stage hydrographs | Plain text `.u##` |
| Gate operations | Plain text `.u##` |
| Lateral inflows | Plain text `.u##` |
| Point precipitation | Plain text `.u##` |
| **Gridded precipitation** | **HDF** `/Event Conditions/Meteorology/` |

When using gridded meteorology (NetCDF, DSS grids), the unsteady file contains a reference but the actual data is in the plan HDF file.

## See Also

- [HEC-RAS File Formats](file-formats.md) - Overview of all file types
- [Boundary Conditions](../user-guide/boundary-conditions.md) - Working with boundaries
- [DSS Operations](../user-guide/dss-operations.md) - Reading DSS boundary data
- [Geometry Parsing](geometry-parsing.md) - Fixed-width parsing patterns
