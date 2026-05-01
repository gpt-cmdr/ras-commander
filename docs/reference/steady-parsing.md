# Steady Flow File Parsing Reference

Reference for HEC-RAS steady flow file (`.f##`) structure and the
`RasSteady` authoring API.

## Overview

Steady flow files define the constant profile inputs used by 1D steady plans:

- Profile names, such as `Q10`, `Q50`, and `Q100`
- Flow values at each flow-change station
- Profile-specific upstream and downstream boundary conditions
- Optional DSS import metadata used by the HEC-RAS steady flow editor

Use `RasPlan.get_flow_path("01")` or `ras.flow_df` to discover existing files,
then use `RasSteady` to read, create, update, and write the `.f##` content.

## File Location

```text
{project_folder}/{project_name}.f{number}
```

Example: `C:\Projects\Muncie\Muncie.f01`

## File Structure

### Header

```text
Flow Title=Multi-Profile Analysis
Program Version=6.60
Number of Profiles= 3
Profile Names=Q10,Q50,Q100
```

`Number of Profiles=` must match the number of names in `Profile Names=` and
the number of flow values in every flow-change block.

### Flow Change Blocks

HEC-RAS stores each flow-change location as a `River Rch & RM=` line followed
by one fixed-width row or block of flow values:

```text
River Rch & RM=Main River,Upper Reach,5000
    2000    5000   10000
River Rch & RM=Main River,Upper Reach,2500
    2200    5500   11000
```

Each numeric block has one value per profile, in profile order.

### Boundary Blocks

Boundary conditions are written per reach and per profile:

```text
Boundary for River Rch & Prof#=Main River,Upper Reach, 1
Up Type= 2
Dn Type= 3
Dn Slope=   0.001
Boundary for River Rch & Prof#=Main River,Upper Reach, 2
Up Type= 1
Up Known WS=   101.5
Dn Type= 1
Dn Known WS=   98.25
```

`RasSteady` exposes the HEC-RAS type codes as constants:

| Constant | Code | Meaning |
|----------|------|---------|
| `RasSteady.NO_BOUNDARY` | `0` | No boundary on that side |
| `RasSteady.KNOWN_WS` | `1` | Known water surface |
| `RasSteady.CRITICAL_DEPTH` | `2` | Critical depth |
| `RasSteady.NORMAL_DEPTH` | `3` | Normal depth using friction slope |
| `RasSteady.RATING_CURVE` | `4` | Rating curve |

Rating curves are written as a counted block of stage-flow pairs:

```text
Dn Type= 4
Dn Rating Curve= 3
      80      40      85     120      90     300
```

## API Usage

### Read and Round Trip

```python
from ras_commander import RasPlan, RasSteady

flow_path = RasPlan.get_flow_path("01")
flow_data = RasSteady.read_flow_file(flow_path)

print(flow_data["profile_names"])
print(flow_data["flow_changes"][0]["flows"])

RasSteady.write_flow_file("Working.f02", flow_data)
```

### Create a New Steady Flow File

This pattern replaces notebook cells that previously required opening the
HEC-RAS steady flow editor by hand.

```python
from ras_commander import RasPlan, RasSteady

new_flow_path = project_folder / f"{project_name}.f02"

RasSteady.create_flow_file(
    new_flow_path,
    flow_title="Calibration Profiles",
    profile_names=["Base", "High"],
    flow_changes=[
        {
            "river": "Main River",
            "reach": "Upper Reach",
            "station": "5000",
            "flows": [1000, 2500],
        },
        {
            "river": "Main River",
            "reach": "Upper Reach",
            "station": "2500",
            "flows": [1250, 2750],
        },
    ],
    boundaries=[
        RasSteady.boundary(
            "Main River",
            "Upper Reach",
            upstream=RasSteady.critical_depth(),
            downstream=RasSteady.normal_depth([0.001, 0.002]),
        ),
    ],
)

# Apply the authored steady flow file to a plan after registering it in the
# project file or cloning an existing flow entry through RasPlan.
RasPlan.set_steady("02", "02")
```

### Known Water Surface and Rating Curve

Compact boundary definitions can provide one value per profile. `RasSteady`
expands them into profile-specific HEC-RAS boundary blocks when writing.

```python
boundaries = [
    RasSteady.boundary(
        "Main River",
        "Upper Reach",
        downstream=RasSteady.known_water_surface([98.5, 100.0, 101.2]),
    ),
    RasSteady.boundary(
        "Tributary",
        "Lower Reach",
        downstream=RasSteady.rating_curve(
            [(95.0, 100.0), (100.0, 500.0), (105.0, 1200.0)]
        ),
    ),
]
```

## Validation Rules

`RasSteady.validate_flow_file_data()` runs before every write and raises a
`ValueError` when:

- The profile name count does not match `Number of Profiles=`
- Any flow-change block has a flow count that differs from the profile count
- A compact known-water-surface or normal-depth boundary list has the wrong
  number of profile-specific values
- A profile-specific boundary references a profile outside `1..N`
- A rating curve is empty or does not form stage-flow pairs

## Fixed-Width Numeric Blocks

HEC-RAS uses 8-character fixed-width numeric columns for flow and rating curve
values. `RasSteady` parses by column position and writes right-aligned values:

```text
Columns:  0-7      8-15     16-23
Values:   value1   value2   value3
Example:  "    2000    5000   10000"
```

Avoid parsing these rows with whitespace-only splitting in reusable code.

## See Also

- [HEC-RAS File Formats](file-formats.md)
- [Unsteady File Parsing](unsteady-parsing.md)
- [Steady Flow Analysis](../user-guide/steady-flow-analysis.md)
