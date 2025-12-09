# Steady Flow File Parsing Reference

Reference for HEC-RAS steady flow file (.f##) structure and parsing.

## Overview

Steady flow files contain **constant flow conditions** for steady flow analysis. They define:

- Multiple flow profiles (e.g., 10-year, 50-year, 100-year)
- Flow values at each river station
- Boundary conditions (known water surface, normal depth, rating curves)
- Change locations for flow values

## File Location

```
{project_folder}/{project_name}.f{number}
```

Example: `C:\Projects\Muncie\Muncie.f01`

## File Structure

### Header Section

```
Flow Title=Steady Flow Analysis
Program Version=6.50
Number of Profiles= 3
Profile Names=10-Year,50-Year,100-Year
```

| Key | Description |
|-----|-------------|
| `Flow Title=` | Display name (max 24 chars) |
| `Program Version=` | HEC-RAS version |
| `Number of Profiles=` | Count of flow profiles |
| `Profile Names=` | Comma-separated profile names |

### River/Reach Section

Flow data is organized by river and reach:

```
River Rch & RM=Big Creek,Upper,1000
```

**Format:** `River Rch & RM={river},{reach},{station}`

### Flow Change Locations

Flow values change at specific stations:

```
Flow Change Location= 1
         1000
```

- Count indicates number of change locations
- Stations are listed in fixed-width format

### Flow Values

```
Flow= 3
        1000       2500       5000
```

- Count matches `Number of Profiles`
- One value per profile at each change location
- Fixed-width 8-character format

### Boundary Conditions

#### Known Water Surface

```
Known WS= 3
       102       105       108
```

Fixed downstream water surface elevation for each profile.

#### Normal Depth

```
Friction Slope= 3
     0.001     0.001     0.001
```

Energy slope for normal depth calculation at downstream boundary.

#### Rating Curve

```
Rating Curve={reach},{station}
Rating Curve= 6
     100     102     500     104    1000     106
```

Stage-discharge relationship: (Q, WSE) pairs.

### Critical Depth

```
Critical Depth={reach},{station}
```

Forces critical depth at the specified location.

## Complete Example File

```
Flow Title=Multi-Profile Analysis
Program Version=6.50
Number of Profiles= 3
Profile Names=10-Year,50-Year,100-Year
River Rch & RM=Main River,Upper Reach,5000
Flow Change Location= 1
         5000
Flow= 3
        2000       5000      10000
River Rch & RM=Main River,Upper Reach,2500
Flow= 3
        2200       5500      11000
River Rch & RM=Main River,Upper Reach,0
Flow= 3
        2400       6000      12000
Boundary for River Rch & RM=Main River,Upper Reach,0
Friction Slope= 3
     0.002     0.002     0.002
```

## Fixed-Width Format Details

### 8-Character Fields

Steady flow files use the same FORTRAN-style fixed-width format as geometry and unsteady files:

```
Columns:  0-7      8-15     16-23    24-31    32-39
Values:   val1     val2     val3     val4     val5
Example:  "    2000    5000   10000"
```

- **Width**: 8 characters per value
- **Alignment**: Right-justified
- **Values per line**: Typically 5-10

### Parsing Example

```python
def parse_flow_values(line, num_profiles):
    """Parse flow values from fixed-width line."""
    values = []
    for i in range(0, len(line.rstrip()), 8):
        field = line[i:i+8].strip()
        if field:
            try:
                values.append(float(field))
            except ValueError:
                continue
    return values[:num_profiles]
```

## Parsing Implementation

### Manual Parsing

```python
import re
from pathlib import Path

def parse_steady_flow_file(flow_path):
    """Parse steady flow file into structured data."""
    with open(flow_path, 'r') as f:
        content = f.read()
        lines = content.split('\n')

    data = {
        'title': None,
        'num_profiles': 0,
        'profile_names': [],
        'flows': {},
        'boundaries': {}
    }

    # Extract header info
    title_match = re.search(r'Flow Title=(.+)', content)
    if title_match:
        data['title'] = title_match.group(1).strip()

    profiles_match = re.search(r'Number of Profiles=\s*(\d+)', content)
    if profiles_match:
        data['num_profiles'] = int(profiles_match.group(1))

    names_match = re.search(r'Profile Names=(.+)', content)
    if names_match:
        data['profile_names'] = [n.strip() for n in names_match.group(1).split(',')]

    # Parse flow values per reach
    reach_pattern = r'River Rch & RM=([^,]+),([^,]+),([^\n]+)'
    flow_pattern = r'Flow=\s*(\d+)\s*\n([\d\s.]+)'

    for match in re.finditer(reach_pattern, content):
        river, reach, station = match.groups()
        key = (river.strip(), reach.strip(), float(station.strip()))

        # Find associated flow values
        pos = match.end()
        flow_match = re.search(flow_pattern, content[pos:pos+500])
        if flow_match:
            values = [float(v) for v in flow_match.group(2).split()]
            data['flows'][key] = values

    return data
```

### Using RasPrj

```python
from ras_commander import init_ras_project, ras

# Initialize project
init_ras_project(r"C:\Projects\MyProject", "6.5")

# Access flow entries
print(ras.flow_df)

# Get specific flow file path
flow_path = ras.project_folder / f"{ras.project_name}.f01"
```

### HDF Steady Results

For executed steady plans, results are in HDF format:

```python
from ras_commander import HdfResultsPlan

# Check if plan has steady results
hdf_path = Path("MyProject.p01.hdf")
if HdfResultsPlan.is_steady_plan(hdf_path):
    # Get profile names
    profiles = HdfResultsPlan.get_steady_profile_names(hdf_path)
    print(f"Profiles: {profiles}")

    # Get water surface elevations
    wse_df = HdfResultsPlan.get_steady_wse(hdf_path)
    print(wse_df.head())

    # Get steady flow metadata
    info_df = HdfResultsPlan.get_steady_info(hdf_path)
    print(info_df)
```

## Profile Data Structure

### Flow Organization

Steady flow files organize data hierarchically:

```
Number of Profiles= 3
Profile Names=Q10,Q50,Q100
│
├── River 1, Reach 1
│   ├── Station 1000: [Q10_flow, Q50_flow, Q100_flow]
│   ├── Station 500:  [Q10_flow, Q50_flow, Q100_flow]
│   └── Station 0:    [Q10_flow, Q50_flow, Q100_flow]
│
└── River 1, Reach 2
    ├── Station 2000: [Q10_flow, Q50_flow, Q100_flow]
    └── Station 0:    [Q10_flow, Q50_flow, Q100_flow]
```

### Flow Change Locations

Flow typically changes at:
- Tributary junctions
- Lateral inflow points
- User-specified locations

Between change locations, flow remains constant.

## Boundary Condition Types

### Downstream Boundaries

| Type | Keyword | Description |
|------|---------|-------------|
| Known WS | `Known WS=` | Fixed water surface elevation |
| Normal Depth | `Friction Slope=` | Uses energy slope |
| Critical Depth | `Critical Depth=` | Forces critical depth |
| Rating Curve | `Rating Curve=` | Stage-discharge relationship |

### Multiple Profiles

Each boundary type needs values for **all profiles**:

```
# For 3 profiles, need 3 values
Friction Slope= 3
     0.001     0.0015     0.002
```

## Count Interpretation

| Keyword | Count Meaning |
|---------|---------------|
| `Number of Profiles=` | Total profile count |
| `Flow Change Location=` | Number of change stations |
| `Flow=` | Number of profiles (must match header) |
| `Known WS=` | Number of profiles |
| `Friction Slope=` | Number of profiles |
| `Rating Curve=` | Number of value pairs |

## Validation

### Check Profile Consistency

```python
def validate_steady_flow(data):
    """Validate steady flow file structure."""
    issues = []
    num_profiles = data['num_profiles']

    # Check profile names match count
    if len(data['profile_names']) != num_profiles:
        issues.append(f"Profile names ({len(data['profile_names'])}) "
                     f"doesn't match count ({num_profiles})")

    # Check flow values at each station
    for location, flows in data['flows'].items():
        if len(flows) != num_profiles:
            issues.append(f"Station {location}: {len(flows)} flows, "
                         f"expected {num_profiles}")

    return issues
```

### Verify Boundary Conditions

```python
def check_boundaries(flow_path, plan_path):
    """Verify downstream boundaries are defined."""
    # Parse plan to find downstream stations
    # Check flow file has boundary at each downstream station
    pass
```

## Comparison with Unsteady

| Aspect | Steady (.f##) | Unsteady (.u##) |
|--------|---------------|-----------------|
| Time dimension | No | Yes |
| Profile concept | Multiple discrete profiles | Single time series |
| Boundary data | Per-profile values | Time-value pairs |
| File complexity | Simpler | More complex |
| Output format | Profile tables | Time series |

## HDF Results Structure

Steady flow results in HDF:

```
/Results/Steady/Output/
├── Geometry/
│   └── Cross Sections/
│       └── {river}_{reach}/
│           ├── Water Surface      # (n_profiles, n_xs)
│           ├── Energy Grade Line  # (n_profiles, n_xs)
│           ├── Flow               # (n_profiles, n_xs)
│           └── Velocity Channel   # (n_profiles, n_xs)
└── Output Profiles/
    └── Profile Names              # Profile name strings
```

## See Also

- [HEC-RAS File Formats](file-formats.md) - Overview of all file types
- [Steady Flow Analysis](../user-guide/steady-flow-analysis.md) - Using steady flow features
- [HDF Structure](hdf-structure.md) - HDF output organization
- [Unsteady File Parsing](unsteady-parsing.md) - Compare with unsteady format
