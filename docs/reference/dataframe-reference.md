# DataFrame Reference

Complete reference for all DataFrames returned by ras-commander functions. Use this guide to understand DataFrame structures before writing data processing logic.

---

## Why DataFrames? The HEC-RAS Documentation Problem

HEC-RAS stores project data in a combination of plain text files (`.prj`, `.p##`, `.g##`, `.u##`, `.f##`) and HDF5 binary files (`.p##.hdf`, `.g##.hdf`). While these files are human-readable or viewable with standard tools, **they are completely undocumented in any official HEC-RAS documentation**.

The file formats use:
- Inconsistent delimiters (fixed-width columns, commas, equals signs)
- Cryptic keywords with no official reference
- Implicit relationships between files
- Version-specific variations across HEC-RAS releases
- Nested data structures with non-obvious hierarchies

Resources like [Breaking the HEC-RAS Code](https://hecrasmodel.blogspot.com/) by Krey Price represent the most complete third-party documentation available, but even comprehensive community efforts cannot cover every edge case or version change.

**This lack of documentation has historically hindered the development of robust automation toolsets.** Most HEC-RAS automation has been:
- Closed-source proprietary solutions
- Ad-hoc scripts solving narrow problems
- Brittle parsers that break with version updates
- Inaccessible to the broader water resources community

### The ras-commander Solution

**ras-commander provides Pythonic DataFrame access to all HEC-RAS file data**, transforming cryptic file formats into structured, queryable, and modifiable data structures.

The philosophy is simple:
1. **Parse once, use everywhere** - File parsing logic is centralized and tested
2. **DataFrames as the universal interface** - All data becomes pandas DataFrames with documented columns
3. **Read-modify-write patterns** - DataFrames enable intuitive data manipulation before writing back
4. **Open source transparency** - Every parsing decision is visible and improvable

---

## How Plain Text Becomes DataFrames

### Example: Parsing a Plan File

A HEC-RAS plan file (`.p01`) contains cryptic key-value pairs:

```
Plan Title=Unsteady Flow Simulation
Program Version=6.30
Short Identifier=p01
Simulation Date=01Jan2020,0000,07Jan2020,2400
Geom File=g01
Flow File=u01
Run HTab= -1
Run UNet= -1
Run PostProcess= 0
Computation Interval=2MIN
UNET D1 Cores= 1
UNET D2 Cores= 4
```

The `RasPrj` class parses this into a DataFrame row:

```python
from ras_commander import init_ras_project, ras

init_ras_project("/path/to/project", "6.5")

# The plan file is now a DataFrame row
print(ras.plan_df[['plan_number', 'Plan Title', 'Computation Interval', 'UNET D2 Cores']])
```

Output:
```
  plan_number                   Plan Title Computation Interval  UNET D2 Cores
0          01  Unsteady Flow Simulation                    2MIN              4
```

**What happened internally:**
1. The parser reads each line and splits on `=`
2. Keywords become column names, values become cell values
3. Type conversion handles integers, floats, and strings appropriately
4. Related files are cross-referenced (geometry, flow files)
5. The result is a queryable, filterable DataFrame

### Example: Parsing Geometry Data

Cross-section data in geometry files uses fixed-width formatting:

```
Type RM Length L Ch R = 1 ,1000.   ,500.   ,500.   ,500.
#Sta/Elev= 40
       0  660.41      25  660.55      50  660.74      75  660.89     100  661.01
     125  661.12     150  661.23     175  661.34     200  661.45     225  661.56
...
#Mann= 3 , 0 , 0
       0     .06       0     620     .035       0    1470      .06       0
Bank Sta=620,1470
```

The `RasGeometry` class transforms this into structured DataFrames:

```python
from ras_commander import RasGeometry

# Get cross-section inventory
xs_df = RasGeometry.get_cross_sections("/path/to/project.g01")
print(xs_df[['river', 'reach', 'river_station', 'left_bank', 'right_bank']])
```

Output:
```
        river    reach  river_station  left_bank  right_bank
0  Bald Eagle  Loc Hav        1000.0      620.0      1470.0
1  Bald Eagle  Loc Hav         800.0      615.0      1455.0
```

```python
# Get station-elevation pairs for a specific cross-section
sta_elev = RasGeometry.get_station_elevation(
    "/path/to/project.g01",
    river="Bald Eagle",
    reach="Loc Hav",
    station=1000.0
)
print(sta_elev.head())
```

Output:
```
   station  elevation
0      0.0     660.41
1     25.0     660.55
2     50.0     660.74
3     75.0     660.89
4    100.0     661.01
```

---

## The Read-Modify-Write Pattern

DataFrames don't just provide read access—they enable a consistent pattern for modifying HEC-RAS data:

### Pattern Overview

```python
# 1. READ: Parse file data into DataFrame
data_df = SomeClass.get_data(file_path)

# 2. MODIFY: Use pandas operations to change values
data_df.loc[condition, 'column'] = new_value

# 3. WRITE: Update the file with modified data
SomeClass.set_data(file_path, data_df)
```

### Example: Modifying Manning's n Values

```python
from ras_commander import RasGeometry

geom_path = "/path/to/project.g01"

# 1. READ: Get current Manning's n for a cross-section
mannings = RasGeometry.get_mannings_n(
    geom_path,
    river="Bald Eagle",
    reach="Loc Hav",
    station=1000.0
)
print("Before:", mannings)
```

Output:
```
   station  n_value  change_rate
0      0.0    0.060          0.0
1    620.0    0.035          0.0
2   1470.0    0.060          0.0
```

```python
# 2. MODIFY: Increase channel roughness by 20%
mannings.loc[mannings['n_value'] == 0.035, 'n_value'] *= 1.2
print("After:", mannings)
```

Output:
```
   station  n_value  change_rate
0      0.0    0.060          0.0
1    620.0    0.042          0.0
2   1470.0    0.060          0.0
```

```python
# 3. WRITE: Save modified values back to geometry file
RasGeometry.set_mannings_n(
    geom_path,
    river="Bald Eagle",
    reach="Loc Hav",
    station=1000.0,
    mannings_df=mannings
)
```

### Example: Modifying Breach Parameters

```python
from ras_commander import RasBreach

plan_path = "/path/to/project.p01"

# 1. READ: Get current breach parameters
breach_params = RasBreach.read_breach_block(plan_path, "Dam")
print(breach_params)
```

Output:
```
{'Final Bottom Width': 200.0,
 'Final Bottom Elev': 605.0,
 'Left Slope': 0.5,
 'Right Slope': 0.5,
 'Breach Weir Coef': 2.6,
 'Formation Time': 1.0,
 'Trigger': 'Water Surface',
 'Trigger Elevation': 630.0}
```

```python
# 2. MODIFY: Change breach parameters for sensitivity analysis
breach_params['Final Bottom Width'] = 300.0  # Wider breach
breach_params['Formation Time'] = 0.5        # Faster formation

# 3. WRITE: Update the plan file
RasBreach.update_breach_block(plan_path, "Dam", breach_params)
```

### Example: Batch Modification Across Plans

The DataFrame approach enables batch operations across multiple files:

```python
from ras_commander import init_ras_project, ras, RasPlan

init_ras_project("/path/to/project", "6.5")

# Modify computation interval for all unsteady plans
for _, plan in ras.plan_df[ras.plan_df['flow_type'] == 'Unsteady'].iterrows():
    RasPlan.set_computation_interval(
        plan['full_path'],
        interval="1MIN"  # Finer time step
    )
    print(f"Updated plan {plan['plan_number']}")
```

---

## Writing Your Own Parsing Functions

When ras-commander doesn't cover a specific data type you need, you can follow the established patterns to write your own parsing functions.

### Pattern: Fixed-Width Data

Many HEC-RAS files use 8 or 16-character fixed-width columns:

```python
def parse_fixed_width_data(lines: list, width: int = 8) -> pd.DataFrame:
    """
    Parse fixed-width formatted data from HEC-RAS files.

    Args:
        lines: List of text lines containing the data
        width: Character width of each column (typically 8 or 16)

    Returns:
        DataFrame with parsed numeric values
    """
    values = []
    for line in lines:
        # Split line into fixed-width chunks
        chunks = [line[i:i+width] for i in range(0, len(line), width)]
        # Convert to floats, handling empty/whitespace
        row_values = []
        for chunk in chunks:
            chunk = chunk.strip()
            if chunk:
                try:
                    row_values.append(float(chunk))
                except ValueError:
                    row_values.append(chunk)
        if row_values:
            values.append(row_values)

    return pd.DataFrame(values)
```

### Pattern: Key-Value Parsing

For keyword-based sections:

```python
def parse_key_value_section(lines: list) -> dict:
    """
    Parse key=value pairs from HEC-RAS files.

    Args:
        lines: List of text lines

    Returns:
        Dictionary of keyword -> value mappings
    """
    result = {}
    for line in lines:
        if '=' in line:
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()

            # Attempt type conversion
            try:
                if '.' in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass  # Keep as string

            result[key] = value

    return result
```

### Pattern: Writing Back to Files

When writing data back, preserve file structure:

```python
def update_section_in_file(
    file_path: Path,
    section_start: str,
    section_end: str,
    new_content: str
) -> None:
    """
    Replace a section in a HEC-RAS file while preserving surrounding content.

    Args:
        file_path: Path to the file
        section_start: Keyword marking section start
        section_end: Keyword marking section end (or next section)
        new_content: New content to insert
    """
    with open(file_path, 'r') as f:
        content = f.read()

    # Find section boundaries
    start_idx = content.find(section_start)
    end_idx = content.find(section_end, start_idx + len(section_start))

    if start_idx == -1:
        raise ValueError(f"Section '{section_start}' not found")

    # Reconstruct file with new section
    new_file = (
        content[:start_idx] +
        new_content +
        content[end_idx:]
    )

    with open(file_path, 'w') as f:
        f.write(new_file)
```

---

## DataFrame Benefits Summary

| Traditional Approach | ras-commander Approach |
|---------------------|------------------------|
| Write custom regex for each file type | Use tested, version-aware parsers |
| Debug parsing errors in production | DataFrames expose data for inspection |
| Manually track file relationships | Cross-referenced DataFrames handle linking |
| Brittle string manipulation for edits | Pandas operations with type safety |
| Undocumented internal data structures | Documented columns and types |
| Closed-source, siloed solutions | Open source, community-improvable |

**The goal is simple:** Any HEC-RAS automation task should start with `init_ras_project()` and proceed with DataFrame operations—not string parsing.

---

## Future: Agentic Documentation Improvement

The DataFrame approach enables a powerful future capability: **automated discovery and documentation of valid parameter values** through systematic exploration of HEC-RAS projects and GUI automation.

### The Vision

Currently, documenting valid options for HEC-RAS parameters requires:
- Manual inspection of files from many projects
- Trial-and-error testing in the GUI
- Cross-referencing with sparse official documentation
- Community knowledge sharing

**Agentic automation can systematically build this knowledge base.**

### Phase 1: Multi-Project Parameter Discovery

Parse a corpus of valid HEC-RAS projects to discover the full range of parameter values:

```python
# Conceptual workflow for parameter discovery
from ras_commander import RasExamples, init_ras_project
import pandas as pd

# Collect parameter values across many projects
all_computation_intervals = set()
all_friction_methods = set()
all_bc_types = set()

# Parse HEC-RAS example projects
for project_name in RasExamples.list_projects():
    path = RasExamples.extract_project(project_name)
    init_ras_project(path, "6.5")

    # Collect unique values from DataFrames
    all_computation_intervals.update(ras.plan_df['Computation Interval'].dropna())
    all_friction_methods.update(ras.plan_df['Friction Slope Method'].dropna())
    all_bc_types.update(ras.boundaries_df['bc_type'].dropna())

# Parse publicly available models (FEMA, USACE, state agencies)
for public_model in discover_public_models():
    # Same collection process...
    pass

# Generate documented valid values
print("Valid Computation Intervals:", sorted(all_computation_intervals))
# ['1SEC', '2SEC', '5SEC', '10SEC', '15SEC', '30SEC', '1MIN', '2MIN', '5MIN', ...]
```

**Data sources for corpus building:**
- HEC-RAS Example Projects (bundled with software)
- FEMA flood study models (publicly available)
- USACE project archives
- State agency hydraulic models
- Academic research repositories
- Community-contributed test projects

### Phase 2: GUI-Driven Parameter Verification

Combine with win32com automation (see `examples/17_extracting_profiles_with_hecrascontroller.ipynb`) to verify parameter values through the GUI:

```python
# Conceptual workflow for GUI verification
from ras_commander import RasControl

def discover_dropdown_options(dialog_path: str) -> list:
    """
    Use COM automation to enumerate dropdown options in HEC-RAS GUI.

    Args:
        dialog_path: Path to GUI element (e.g., "Plan Options > Computation Interval")

    Returns:
        List of valid dropdown values
    """
    # Open dialog, enumerate dropdown contents, close dialog
    # This captures the exact valid values HEC-RAS accepts
    pass

def verify_parameter_creates_valid_file(param_name: str, value: any) -> bool:
    """
    Set a parameter via GUI and verify the resulting file is valid.
    """
    # 1. Set parameter in GUI
    # 2. Save project
    # 3. Parse resulting file
    # 4. Run compute to verify HEC-RAS accepts it
    pass
```

### Phase 3: Change Detection Through GUI Toggling

Systematically toggle GUI options to discover what changes in plain text and HDF files:

```python
# Conceptual workflow for change detection
def discover_file_changes(gui_option: str, before_value: any, after_value: any) -> dict:
    """
    Toggle a GUI option and detect all resulting file changes.

    Returns:
        Dictionary mapping file types to changed content
    """
    # 1. Capture baseline files (plan, geometry, unsteady, HDF)
    baseline_plan = read_plan_file()
    baseline_hdf = read_hdf_structure()

    # 2. Toggle GUI option
    set_gui_option(gui_option, after_value)
    save_project()

    # 3. Capture changed files
    changed_plan = read_plan_file()
    changed_hdf = read_hdf_structure()

    # 4. Diff and report
    return {
        'plan_file': diff(baseline_plan, changed_plan),
        'hdf_file': diff(baseline_hdf, changed_hdf),
        'keyword_added': extract_new_keywords(baseline_plan, changed_plan),
        'hdf_paths_added': extract_new_hdf_paths(baseline_hdf, changed_hdf),
    }

# Example: What happens when enabling sediment transport?
changes = discover_file_changes(
    gui_option="Sediment Transport",
    before_value=False,
    after_value=True
)
print(changes)
# {
#     'plan_file': ['Run Sediment= -1', 'Sed File=s01'],
#     'keyword_added': ['Run Sediment', 'Sed File'],
#     'hdf_paths_added': ['/Results/Sediment/...']
# }
```

### Phase 4: Auto-Generated Documentation

Use discovered information to automatically enhance docstrings and documentation:

```python
# Example: Auto-generated docstring enhancement
def set_computation_interval(plan_path: Path, interval: str) -> None:
    """
    Set the computation interval for a plan.

    Args:
        plan_path: Path to plan file
        interval: Computation interval string

    Valid intervals (auto-discovered from 847 projects):
            '1SEC', '2SEC', '5SEC', '10SEC', '15SEC', '30SEC',
            '1MIN', '2MIN', '5MIN', '10MIN', '15MIN', '20MIN', '30MIN',
            '1HOUR', '2HOUR', '3HOUR', '4HOUR', '6HOUR', '8HOUR', '12HOUR', '24HOUR'

    File changes (auto-discovered via GUI toggling):
        - Plan file: Updates 'Computation Interval=' line
        - HDF file: No direct change (affects computation only)

    GUI location: Plan > Options > Computation Settings > Computation Interval

    Discovered in versions: 5.0.7, 6.0, 6.1, 6.3, 6.4, 6.5, 6.6
    """
    pass
```

### Implementation Roadmap

| Phase | Capability | Status |
|-------|------------|--------|
| **Phase 1** | Multi-project parsing for parameter discovery | Framework ready via `RasExamples` |
| **Phase 2** | GUI automation for dropdown enumeration | Foundation in `RasControl` |
| **Phase 3** | Change detection through GUI toggling | Requires development |
| **Phase 4** | Auto-generated docstrings and docs | Requires development |

### Benefits of Agentic Documentation

1. **Completeness** - Discover parameters that exist in real projects but aren't documented
2. **Version awareness** - Track which parameters appear in which HEC-RAS versions
3. **Validation** - Verify that documented values actually work
4. **Maintenance** - Automatically update docs when new HEC-RAS versions add options
5. **Community contribution** - Anyone can add projects to the corpus

### Contributing to Parameter Discovery

To help build the corpus of valid parameter values:

1. **Share anonymized project statistics** - Run the parameter collector on your projects
2. **Report undocumented parameters** - File issues when you find valid values not in docs
3. **Contribute public models** - Link to publicly available HEC-RAS projects
4. **Test edge cases** - Verify unusual parameter combinations work

This agentic approach transforms documentation from a manual, error-prone process into a systematic, verifiable, and continuously improving knowledge base.

---

## HEC-RAS Version Support and 2025 Roadmap

### Current Version Landscape

The HEC-RAS ecosystem spans multiple decades of development, with regulatory models still in active use across a wide version range:

| Version Range | Status | Regulatory Use |
|---------------|--------|----------------|
| **3.x** | Legacy | Significant number of regulatory models still in production |
| **4.x** | Legacy | Many active regulatory models |
| **5.x** | Stable | Widespread regulatory adoption |
| **6.x** | Current | Version 6.7 still in active development (as of Dec 2025) |
| **2025** | **Alpha** | Not yet suitable for regulatory work |

**Key point:** A significant portion of funded H&H (Hydrology & Hydraulics) work still involves regulatory models in versions 3.x through 5.x. Version 6.x regulatory models are only recently being published.

### HEC-RAS 2025: Current State

HEC-RAS 2025 represents a significant architectural shift:

1. **Alpha status** - The 2025 version is still in Alpha, not even Beta
2. **HDF-native architecture** - Entire program uses HDF (`.h5` extension) with no plain text files
3. **C# API planned** - USACE will release an official C# API for programmatic access
4. **Similar HDF structure** - The HDF file structure is very similar to version 6.x

### ras-commander Position on HEC-RAS 2025

**ras-commander will not develop features for HEC-RAS 2025 until:**

1. The official C# API is released
2. The program moves to Beta status
3. Funded regulatory work with this version begins

**Rationale:**

The intent of ras-commander is to **supplement USACE documentation and workflows**, not to front-run their development efforts. Building features against an Alpha product with an unreleased API would:

- Create maintenance burden as the API changes
- Potentially conflict with official tooling
- Distract from serving existing regulatory-model-based H&H needs

### Future 2025 Support Plan

When HEC-RAS 2025 reaches maturity:

| Milestone | ras-commander Action |
|-----------|---------------------|
| C# API released | Evaluate API design and compatibility |
| Beta release | Begin testing existing HDF logic against 2025 files |
| Full release | Develop Python bindings if no official Python API exists |
| Regulatory adoption begins | Prioritize 2025 features based on community needs |

**Good news:** Most of ras-commander's HDF logic should be portable to 2025. The HDF structure is very similar, and the library is already well-positioned to support this version once it reaches full release.

**If no Python API is released:** ras-commander will provide Python bindings for the C# API. A separate package may be created to maintain clean separation between version-specific functionality.

### Recommendation for Users

If you're interested in HEC-RAS 2025:

1. **Test independently** - Try ras-commander's HDF parsing logic against 2025 files and report compatibility
2. **Build your own frameworks** - Use ras-commander patterns as a foundation for 2025-specific tools
3. **Focus on production needs** - For regulatory work, version 6.x remains the appropriate target
4. **Contribute findings** - Share what works and what doesn't in GitHub issues

**It will take years for active H&H development to migrate to RAS 2025.** In its current Alpha state, it serves primarily as a preview of future capabilities rather than a production-ready platform. The most valuable contribution to the water resources community today is building robust tooling for the versions that power actual regulatory work.

---

## Quick Navigation

- [Project-Level DataFrames](#project-level-dataframes) - Core project data structures
- [HDF Results DataFrames](#hdf-results-dataframes) - Simulation results extraction
- [Breach Analysis DataFrames](#breach-analysis-dataframes) - Dam breach results
- [Geometry Parsing DataFrames](#geometry-parsing-dataframes) - Geometry file data
- [DSS Operations DataFrames](#dss-operations-dataframes) - Boundary condition data
- [Infrastructure DataFrames](#infrastructure-dataframes) - Pipes, pumps, structures
- [Time Series Results (xarray)](#time-series-results-xarray) - Multi-dimensional simulation results

---

## Project-Level DataFrames

These DataFrames are available as attributes on the `ras` object after calling `init_ras_project()`.

### plan_df

**Source**: `ras.plan_df` (attribute on RasPrj)
**Example notebook**: `examples/01_project_initialization.ipynb`

Contains metadata for all plan files (`.p##`) in the project.

| Column | Type | Description |
|--------|------|-------------|
| `plan_number` | str | Plan identifier (e.g., "01", "02") |
| `unsteady_number` | str/None | Associated unsteady file number |
| `geometry_number` | str | Associated geometry file number |
| `Plan Title` | str | Plan title from file header |
| `Program Version` | str | HEC-RAS version used |
| `Short Identifier` | str | Short plan identifier |
| `Simulation Date` | str | Simulation date/time window |
| `Computation Interval` | str | Time step (e.g., "2MIN", "1HOUR") |
| `Mapping Interval` | str | Output mapping interval |
| `Run HTab` | int | Run hydraulic tables flag (-1=True, 0=False) |
| `Run UNet` | int | Run unsteady network flag |
| `Run Sediment` | int | Run sediment transport flag |
| `Run PostProcess` | int | Run RASMapper flag (inverted: 0=True) |
| `Run WQNet` | int | Run water quality flag |
| `UNET Use Existing IB Tables` | int | Use existing IB tables |
| `UNET D1 Cores` | int | Number of 1D cores |
| `UNET D2 Cores` | int | Number of 2D cores |
| `PS Cores` | int | Post-processing cores |
| `DSS File` | str | DSS file reference |
| `Friction Slope Method` | int | Friction slope calculation method |
| `HDF_Results_Path` | str | Path to HDF results file |
| `Geom File` | str | Geometry file reference (e.g., "01") |
| `Geom Path` | Path | Full path to geometry file |
| `Flow File` | str | Flow file reference |
| `Flow Path` | Path | Full path to flow file |
| `full_path` | Path | Full path to plan file |
| `flow_type` | str | "Steady" or "Unsteady" |

**Sample Output**:
```
  plan_number unsteady_number geometry_number                     Plan Title  flow_type
0          01              02              01  Unsteady with Bridges and Dam   Unsteady
1          02            None              01                Steady Flow Run     Steady
```

---

### geom_df

**Source**: `ras.geom_df` (attribute on RasPrj)
**Example notebook**: `examples/01_project_initialization.ipynb`

Contains metadata for all geometry files (`.g##`) in the project.

| Column | Type | Description |
|--------|------|-------------|
| `geom_file` | str | Geometry file name (e.g., "g01") |
| `geom_number` | str | Geometry number (e.g., "01") |
| `full_path` | Path | Full path to geometry file |
| `hdf_path` | Path/None | Path to preprocessed HDF (if exists) |

**Sample Output**:
```
  geom_file geom_number                                          full_path
0       g01          01  /path/to/project/BaldEagle.g01
```

---

### flow_df

**Source**: `ras.flow_df` (attribute on RasPrj)
**Example notebook**: `examples/01_project_initialization.ipynb`

Contains metadata for all steady flow files (`.f##`) in the project.

| Column | Type | Description |
|--------|------|-------------|
| `flow_number` | str | Flow file number (e.g., "01", "02") |
| `full_path` | Path | Full path to flow file |
| `unsteady_number` | None | Always None for steady flow files |
| `geometry_number` | None | Associated geometry (if specified) |

**Sample Output**:
```
  flow_number                                          full_path
0          02  /path/to/project/BaldEagle.f02
1          01  /path/to/project/BaldEagle.f01
```

---

### unsteady_df

**Source**: `ras.unsteady_df` (attribute on RasPrj)
**Example notebook**: `examples/01_project_initialization.ipynb`

Contains metadata for all unsteady flow files (`.u##`) in the project.

| Column | Type | Description |
|--------|------|-------------|
| `unsteady_number` | str | Unsteady file number (e.g., "01", "02") |
| `full_path` | Path | Full path to unsteady file |
| `geometry_number` | str/None | Associated geometry number |
| `Flow Title` | str | Flow file title |
| `Program Version` | str | HEC-RAS version |
| `Use Restart` | int | Use restart file flag |
| `Precipitation Mode` | str | Precipitation mode setting |
| `Wind Mode` | str | Wind forces mode |
| `Met BC=Precipitation\|Mode` | str | Meteorological BC precipitation mode |
| `Met BC=Evapotranspiration\|Mode` | str | Meteorological BC ET mode |
| `Met BC=Precipitation\|Expanded View` | int | Expanded view flag |
| `Met BC=Precipitation\|Constant Units` | str | Precipitation units |
| `Met BC=Precipitation\|Gridded Source` | str | Gridded precip source |

**Sample Output**:
```
  unsteady_number         Flow Title Program Version  Use Restart Precipitation Mode
0              02  Flow Hydrograph 2            6.30            0            Disable
```

---

### boundaries_df

**Source**: `ras.boundaries_df` (attribute on RasPrj)
**Example notebook**: `examples/01_project_initialization.ipynb`, `examples/22_dss_boundary_extraction.ipynb`

Contains all boundary conditions defined across unsteady flow files.

| Column | Type | Description |
|--------|------|-------------|
| `unsteady_number` | str | Source unsteady file number |
| `boundary_condition_number` | int | BC sequence number (1-based) |
| `river_reach_name` | str | River/Reach name |
| `river_station` | str | River station location |
| `storage_area_name` | str | Storage area name (if applicable) |
| `pump_station_name` | str | Pump station name (if applicable) |
| `bc_type` | str | Boundary type (see table below) |
| `hydrograph_type` | str | Hydrograph type description |
| `Interval` | str | Data interval (e.g., "1HOUR") |
| `DSS Path` | str | DSS pathname (if DSS-based) |
| `Use DSS` | bool | Whether BC uses DSS data |
| `Use Fixed Start Time` | int | Fixed start time flag |
| `Fixed Start Date/Time` | str | Fixed start datetime |
| `Is Critical Boundary` | int | Critical boundary flag |
| `Critical Boundary Flow` | float | Critical flow threshold |
| `hydrograph_num_values` | int | Number of hydrograph values |
| `hydrograph_values` | list | Raw hydrograph data |
| `full_path` | Path | Path to source unsteady file |
| `Flow Title` | str | Flow file title |
| `Program Version` | str | HEC-RAS version |

**Boundary Types** (`bc_type`):

| Value | Description |
|-------|-------------|
| `Flow Hydrograph` | Inflow hydrograph at upstream boundary |
| `Stage Hydrograph` | Stage (WSE) hydrograph |
| `Normal Depth` | Normal depth downstream BC |
| `Rating Curve` | Stage-discharge rating curve |
| `Lateral Inflow Hydrograph` | Lateral inflow at interior location |
| `Uniform Lateral Inflow Hydrograph` | Distributed lateral inflow |
| `Gate Opening` | Time-varying gate opening |
| `Time Series Gate` | Gate with time series control |
| `EG Slope` | Energy grade line slope BC |
| `Known WS` | Known water surface elevation |

**Sample Output**:
```
  unsteady_number  boundary_condition_number          bc_type Use DSS  Interval
0              02                          1  Flow Hydrograph    True     1HOUR
1              02                          2     Gate Opening   False       NaN
2              02                          3          Unknown   False       NaN
```

---

## HDF Results DataFrames

DataFrames extracted from HEC-RAS HDF5 result files (`.p##.hdf`).

### Unsteady Summary

**Source**: `HdfResultsPlan.get_unsteady_summary(plan_hdf)`
**Example notebook**: `examples/10_hdf_results_extraction.ipynb`

Summary statistics for unsteady simulation results.

| Column | Type | Description |
|--------|------|-------------|
| `Plan File` | str | Plan file name |
| `Plan Title` | str | Plan title |
| `Type of Run` | str | Run type description |
| `Run Time Window` | str | Simulation time window |
| `Computation Time Step` | str | Computation interval |
| `Mapping Output Interval` | str | Mapping output interval |
| `Output Mode` | str | Output mode setting |
| `Solution` | str | Solution status |
| `Maximum WSEL Error` | float | Maximum water surface error |
| `Maximum Iterations` | int | Maximum iterations reached |

---

### Unsteady Info

**Source**: `HdfResultsPlan.get_unsteady_info(plan_hdf)`
**Example notebook**: `examples/10_hdf_results_extraction.ipynb`

Detailed unsteady simulation metadata.

| Column | Type | Description |
|--------|------|-------------|
| `attribute` | str | Attribute name |
| `value` | various | Attribute value |

Key attributes include: `Program Name`, `Program Version`, `Project File Name`, `Type of Run`, `Run Time Window`, `Solution`, `Simulation Time Step`, `Maximum Iterations`.

---

### Volume Accounting

**Source**: `HdfResultsPlan.get_volume_accounting(plan_hdf)`
**Example notebook**: `examples/10_hdf_results_extraction.ipynb`

Water volume balance accounting for each 2D flow area.

| Column | Type | Description |
|--------|------|-------------|
| `Flow Area` | str | 2D flow area name |
| `Inflow` | float | Total inflow volume (acre-ft or m³) |
| `Outflow` | float | Total outflow volume |
| `Change in Storage` | float | Net storage change |
| `Error` | float | Volume balance error |
| `Error Percent` | float | Error as percentage |

---

### Steady WSE

**Source**: `HdfResultsPlan.get_steady_wse(plan_hdf, profile=None)`
**Example notebook**: `examples/19_steady_flow_analysis.ipynb`

Water surface elevations from steady flow analysis.

**Single Profile** (when `profile` is specified):

| Column | Type | Description |
|--------|------|-------------|
| `River` | str | River name |
| `Reach` | str | Reach name |
| `Station` | float | River station |
| `WSE` | float | Water surface elevation |

**All Profiles** (when `profile=None`):

| Column | Type | Description |
|--------|------|-------------|
| `River` | str | River name |
| `Reach` | str | Reach name |
| `Station` | float | River station |
| `Profile` | str | Profile name (e.g., "100 year") |
| `WSE` | float | Water surface elevation |

**Sample Output (All Profiles)**:
```
        River    Reach   Station  Profile         WSE
0  Bald Eagle  Loc Hav  138154.4  .5 year  660.588928
1  Bald Eagle  Loc Hav  137690.8  .5 year  659.914612
2  Bald Eagle  Loc Hav  137327.0  .5 year  659.465759
...
```

---

### Steady Info

**Source**: `HdfResultsPlan.get_steady_info(plan_hdf)`
**Example notebook**: `examples/19_steady_flow_analysis.ipynb`

Metadata for steady flow simulation.

| Attribute | Type | Description |
|-----------|------|-------------|
| `Program Name` | str | "HEC-RAS - River Analysis System" |
| `Program Version` | str | HEC-RAS version string |
| `Project File Name` | str | Project file path |
| `Type of Run` | str | "Steady Flow Analysis" |
| `Run Time Window` | str | Start/end timestamps |
| `Solution` | str | Solution status |
| `Flow Filename` | str | Flow file name |
| `Flow Title` | str | Flow file title |

**Sample Output**:
```
                                                                   0
Program Name                         HEC-RAS - River Analysis System
Program Version                           HEC-RAS 6.6 September 2024
Type of Run                                     Steady Flow Analysis
Solution                                Steady Finished Successfully
```

---

### Mesh Summary

**Source**: `HdfResultsMesh.get_mesh_summary(plan_hdf)`
**Example notebook**: `examples/11_mesh_results_extraction.ipynb`

Summary statistics for 2D mesh cells.

| Column | Type | Description |
|--------|------|-------------|
| `mesh_name` | str | 2D flow area name |
| `cell_id` | int | Cell index (0-based) |
| `min_elevation` | float | Cell minimum elevation |
| `max_wse` | float | Maximum water surface elevation |
| `max_wse_time` | datetime | Time of maximum WSE |
| `max_depth` | float | Maximum water depth |
| `cell_x` | float | Cell center X coordinate |
| `cell_y` | float | Cell center Y coordinate |

---

### Mesh Last Iteration

**Source**: `HdfResultsMesh.get_mesh_last_iter(plan_hdf)`
**Example notebook**: `examples/11_mesh_results_extraction.ipynb`

Final iteration count for each mesh cell.

| Column | Type | Description |
|--------|------|-------------|
| `mesh_name` | str | 2D flow area name |
| `cell_id` | int | Cell index |
| `last_iteration` | int | Final solver iteration count |

---

## Breach Analysis DataFrames

DataFrames for dam breach analysis from `HdfResultsBreach` class.

### Breach Time Series

**Source**: `HdfResultsBreach.get_breach_timeseries(plan_hdf, structure_name)`
**Example notebook**: `examples/18_breach_results_extraction.ipynb`

Complete time series of breach evolution and hydraulics.

| Column | Type | Description |
|--------|------|-------------|
| `datetime` | datetime64 | Timestamp |
| `total_flow` | float | Total flow through structure (cfs/cms) |
| `weir_flow` | float | Flow over intact weir portion |
| `breach_flow` | float | Flow through breach opening |
| `hw` | float | Headwater elevation (upstream) |
| `tw` | float | Tailwater elevation (downstream) |
| `bottom_width` | float | Breach bottom width |
| `bottom_elevation` | float | Breach bottom elevation |
| `left_slope` | float | Left side slope (H:V) |
| `right_slope` | float | Right side slope (H:V) |
| `breach_velocity` | float | Flow velocity through breach |
| `breach_flow_area` | float | Breach flow cross-sectional area |

**Sample Output**:
```
               datetime    total_flow  breach_flow          hw          tw  bottom_width
0   1999-01-01 12:00:00    923.384338          NaN  630.002441  585.522766           NaN
...
428 1999-01-04 11:20:00  66875.054688  65052.839844  628.945923  605.716675         200.0
```

**Notes**:
- Values are `NaN` before breach initiation
- After breach completion, geometry values stabilize at final dimensions

---

### Breach Summary

**Source**: `HdfResultsBreach.get_breach_summary(plan_hdf, structure_name)`
**Example notebook**: `examples/18_breach_results_extraction.ipynb`

Summary statistics for breach event.

| Column | Type | Description |
|--------|------|-------------|
| `structure` | str | Structure name |
| `breach_initiated` | bool | Whether breach was triggered |
| `breach_at_time` | float | Time of breach initiation (hours) |
| `breach_at_date` | str | Date/time of breach initiation |
| `max_total_flow` | float | Maximum total flow (cfs/cms) |
| `max_total_flow_time` | datetime | Time of maximum flow |
| `max_breach_flow` | float | Maximum breach-only flow |
| `max_breach_flow_time` | datetime | Time of maximum breach flow |
| `final_breach_width` | float | Final breach bottom width |
| `final_breach_depth` | float | Final breach depth |
| `max_hw` | float | Maximum headwater elevation |
| `max_tw` | float | Maximum tailwater elevation |

**Sample Output**:
```
  structure  breach_initiated  max_total_flow  final_breach_width  final_breach_depth
0       Dam              True   244943.171875               200.0           23.746826
```

---

### Breaching Variables

**Source**: `HdfResultsBreach.get_breaching_variables(plan_hdf, structure_name)`
**Example notebook**: `examples/18_breach_results_extraction.ipynb`

Breach geometry evolution over time.

| Column | Type | Description |
|--------|------|-------------|
| `datetime` | datetime64 | Timestamp |
| `hw` | float | Headwater elevation |
| `tw` | float | Tailwater elevation |
| `bottom_width` | float | Breach bottom width |
| `bottom_elevation` | float | Breach bottom elevation |
| `left_slope` | float | Left side slope |
| `right_slope` | float | Right side slope |
| `breach_flow` | float | Flow through breach |
| `breach_velocity` | float | Breach velocity |
| `breach_flow_area` | float | Breach cross-sectional area |

---

### Structure Variables

**Source**: `HdfResultsBreach.get_structure_variables(plan_hdf, structure_name)`
**Example notebook**: `examples/18_breach_results_extraction.ipynb`

Time series of structure hydraulic variables.

| Column | Type | Description |
|--------|------|-------------|
| `datetime` | datetime64 | Timestamp |
| `total_flow` | float | Total flow through structure |
| `weir_flow` | float | Flow over weir/spillway |
| `hw` | float | Headwater elevation |
| `tw` | float | Tailwater elevation |

---

## Geometry Parsing DataFrames

DataFrames from geometry file (`.g##`) parsing via `RasGeometry` and related classes.

### Cross Sections

**Source**: `RasGeometry.get_cross_sections(geom_path)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Cross section metadata from geometry file.

| Column | Type | Description |
|--------|------|-------------|
| `river` | str | River name |
| `reach` | str | Reach name |
| `river_station` | float | River station |
| `description` | str | Cross section description |
| `num_sta_elev` | int | Number of station-elevation points |
| `left_bank` | float | Left bank station |
| `right_bank` | float | Right bank station |
| `num_mannings` | int | Number of Manning's n segments |
| `expansion_coef` | float | Expansion coefficient |
| `contraction_coef` | float | Contraction coefficient |

**Sample Output**:
```
        river    reach  river_station     description  num_sta_elev  left_bank  right_bank
0  Bald Eagle  Loc Hav      138154.40            None           156      620.0      1470.0
1  Bald Eagle  Loc Hav      137690.80            None           167      652.0      1494.0
```

---

### Station-Elevation Data

**Source**: `RasGeometry.get_station_elevation(geom_path, river, reach, station)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Station-elevation pairs for a specific cross section.

| Column | Type | Description |
|--------|------|-------------|
| `station` | float | Horizontal station (perpendicular to flow) |
| `elevation` | float | Ground elevation |

**Sample Output**:
```
     station  elevation
0        0.0     660.41
1       25.0     660.55
2       50.0     660.74
...
155   1550.0     665.12
```

---

### Manning's n Values

**Source**: `RasGeometry.get_mannings_n(geom_path, river, reach, station)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Manning's n roughness coefficients for cross section.

| Column | Type | Description |
|--------|------|-------------|
| `station` | float | Start station for n-value |
| `n_value` | float | Manning's n coefficient |
| `change_rate` | float | Rate of n-value change (usually 0) |

**Sample Output**:
```
   station  n_value  change_rate
0      0.0    0.060          0.0
1    620.0    0.035          0.0
2   1470.0    0.060          0.0
```

---

### Storage Areas

**Source**: `RasGeometry.get_storage_areas(geom_path)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Storage area definitions from geometry.

| Column | Type | Description |
|--------|------|-------------|
| `name` | str | Storage area name |
| `initial_elevation` | float | Initial water surface elevation |
| `num_points` | int | Number of perimeter points |
| `min_elevation` | float | Minimum elevation |
| `max_elevation` | float | Maximum elevation (if defined) |

---

### Storage Elevation-Volume

**Source**: `RasGeometry.get_storage_elevation_volume(geom_path, storage_name)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Elevation-volume relationship for storage area.

| Column | Type | Description |
|--------|------|-------------|
| `elevation` | float | Water surface elevation |
| `volume` | float | Storage volume at elevation |

---

### Lateral Structures

**Source**: `RasGeometry.get_lateral_structures(geom_path)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Lateral structure (weir) definitions.

| Column | Type | Description |
|--------|------|-------------|
| `name` | str | Lateral structure name |
| `river` | str | Connected river |
| `reach` | str | Connected reach |
| `us_station` | float | Upstream river station |
| `ds_station` | float | Downstream river station |
| `weir_coef` | float | Weir discharge coefficient |
| `num_profile_points` | int | Number of weir profile points |

---

### SA/2D Connections

**Source**: `RasGeometry.get_connections(geom_path)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Storage area and 2D flow area connections.

| Column | Type | Description |
|--------|------|-------------|
| `name` | str | Connection name |
| `type` | str | Connection type |
| `us_area` | str | Upstream area name |
| `ds_area` | str | Downstream area name |
| `weir_coef` | float | Weir coefficient |
| `num_gates` | int | Number of gates |
| `num_profile_points` | int | Weir profile point count |

---

### Inline Weirs

**Source**: `RasStruct.get_inline_weirs(geom_path)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Inline weir structures in 1D reaches.

| Column | Type | Description |
|--------|------|-------------|
| `river` | str | River name |
| `reach` | str | Reach name |
| `station` | float | River station |
| `name` | str | Structure name |
| `weir_coef` | float | Weir discharge coefficient |
| `num_gates` | int | Number of gates |
| `num_profile_points` | int | Profile point count |

---

### Bridges

**Source**: `RasStruct.get_bridges(geom_path)`
**Example notebook**: `examples/20_geometry_parsing.ipynb`

Bridge structure inventory.

| Column | Type | Description |
|--------|------|-------------|
| `river` | str | River name |
| `reach` | str | Reach name |
| `station` | float | River station |
| `name` | str | Bridge name |
| `deck_width` | float | Deck width |
| `num_piers` | int | Number of pier sets |
| `us_embankment_station` | float | Upstream embankment station |
| `ds_embankment_station` | float | Downstream embankment station |

---

### Culverts

**Source**: `RasStruct.get_culverts(geom_path)`
**Example notebook**: See API reference

Culvert definitions within bridge structures.

| Column | Type | Description |
|--------|------|-------------|
| `river` | str | River name |
| `reach` | str | Reach name |
| `station` | float | River station |
| `culvert_num` | int | Culvert index |
| `shape_code` | int | Shape code (see below) |
| `shape` | str | Shape name |
| `rise` | float | Culvert rise/height |
| `span` | float | Culvert span/width |
| `num_barrels` | int | Number of barrels |
| `invert_elevation` | float | Invert elevation |
| `length` | float | Culvert length |
| `manning_n` | float | Manning's n for culvert |
| `entrance_loss` | float | Entrance loss coefficient |
| `exit_loss` | float | Exit loss coefficient |

**Culvert Shape Codes**:

| Code | Shape |
|------|-------|
| 1 | Circular |
| 2 | Box |
| 3 | Pipe Arch |
| 4 | Ellipse |
| 5 | Arch |
| 6 | Semi-Circle |
| 7 | Low Profile Arch |
| 8 | High Profile Arch |
| 9 | Con Span |

---

## DSS Operations DataFrames

DataFrames from HEC-DSS file operations via `RasDss` class.

### DSS Catalog

**Source**: `RasDss.get_catalog(dss_file)`
**Example notebook**: `examples/22_dss_boundary_extraction.ipynb`

List of all data paths in a DSS file.

| Column | Type | Description |
|--------|------|-------------|
| `pathname` | str | Full DSS pathname |
| `A` | str | Part A (typically basin/project) |
| `B` | str | Part B (location) |
| `C` | str | Part C (parameter, e.g., "FLOW") |
| `D` | str | Part D (start date) |
| `E` | str | Part E (interval, e.g., "1HOUR") |
| `F` | str | Part F (version/scenario) |

---

### DSS Time Series

**Source**: `RasDss.read_timeseries(dss_file, pathname)`
**Example notebook**: `examples/22_dss_boundary_extraction.ipynb`

Time series data from DSS file.

| Column | Type | Description |
|--------|------|-------------|
| `datetime` | datetime64 | Timestamp |
| `value` | float | Data value |
| `units` | str | Data units (e.g., "CFS", "FT") |
| `type` | str | Data type (e.g., "PER-AVER", "INST-VAL") |

**Sample Output**:
```
              datetime         value units      type
0  1999-01-01 00:00:00    719.775321   CFS  PER-AVER
1  1999-01-01 01:00:00    812.445312   CFS  PER-AVER
2  1999-01-01 02:00:00   1024.332153   CFS  PER-AVER
...
```

---

### Boundary Extraction Summary

**Source**: `RasDss.extract_boundary_timeseries(boundaries_df, ras_object)`
**Example notebook**: `examples/22_dss_boundary_extraction.ipynb`

Summary of extracted DSS boundary conditions with statistics.

| Column | Type | Description |
|--------|------|-------------|
| `bc_type` | str | Boundary condition type |
| `Use DSS` | bool | Whether BC uses DSS |
| `dss_points` | int | Number of time series points |
| `dss_mean` | float | Mean value |
| `dss_max` | float | Maximum value |
| `dss_min` | float | Minimum value |
| `dss_data` | Series | Full time series (if requested) |

**Sample Output**:
```
                             bc_type Use DSS  dss_points      dss_mean      dss_max
0                    Flow Hydrograph    True       673.0  23749.776843  193738.197396
2          Lateral Inflow Hydrograph    True       673.0   7554.055251   28510.083069
4  Uniform Lateral Inflow Hydrograph    True       673.0   6448.671063   75262.300507
```

---

## Infrastructure DataFrames

DataFrames for pipes, pumps, and structures from HDF files.

### Pipe Network

**Source**: `HdfPipe.get_pipe_network(plan_hdf)`
**Example notebook**: `examples/12_pipe_pump_analysis.ipynb`

Pipe network topology and properties.

| Column | Type | Description |
|--------|------|-------------|
| `pipe_name` | str | Pipe segment name |
| `us_node` | str | Upstream node name |
| `ds_node` | str | Downstream node name |
| `length` | float | Pipe length |
| `diameter` | float | Pipe diameter |
| `manning_n` | float | Manning's roughness |
| `invert_us` | float | Upstream invert elevation |
| `invert_ds` | float | Downstream invert elevation |
| `slope` | float | Pipe slope |

---

### Pump Stations

**Source**: `HdfPump.get_pump_stations(plan_hdf)`
**Example notebook**: `examples/12_pipe_pump_analysis.ipynb`

Pump station definitions and properties.

| Column | Type | Description |
|--------|------|-------------|
| `pump_station` | str | Pump station name |
| `num_pumps` | int | Number of pumps |
| `sump_elevation` | float | Sump elevation |
| `on_elevation` | float | Pump on elevation |
| `off_elevation` | float | Pump off elevation |

---

### Pump Results

**Source**: `HdfPump.get_pump_results(plan_hdf)`
**Example notebook**: `examples/12_pipe_pump_analysis.ipynb`

Pump operation time series results.

| Column | Type | Description |
|--------|------|-------------|
| `datetime` | datetime64 | Timestamp |
| `pump_station` | str | Pump station name |
| `pump_num` | int | Pump number |
| `status` | int | Pump status (0=off, 1=on) |
| `flow` | float | Pump flow rate |
| `head` | float | Pump head |

---

### Structure Attributes

**Source**: `HdfStruc.get_geom_structures_attrs(plan_hdf)`
**Example notebook**: See API reference

Structure attributes from HDF geometry.

| Column | Type | Description |
|--------|------|-------------|
| `name` | str | Structure name |
| `type` | str | Structure type |
| `river` | str | River name (if 1D) |
| `reach` | str | Reach name (if 1D) |
| `station` | float | River station (if 1D) |
| `us_area` | str | Upstream 2D area (if 2D) |
| `ds_area` | str | Downstream 2D area (if 2D) |

---

## Time Series Results (xarray)

For multi-dimensional time series data, ras-commander uses **xarray** instead of pandas DataFrames. xarray provides labeled multi-dimensional arrays that efficiently handle the `(time × location × variable)` structure of HEC-RAS simulation results.

### Why xarray for Time Series?

| Data Type | Best Format | Reason |
|-----------|-------------|--------|
| Metadata (plans, files) | DataFrame | Tabular, one row per entity |
| Summary statistics | DataFrame | Tabular aggregations |
| Time series (1D cross sections) | xarray.Dataset | `(time × cross_section)` with coordinates |
| Time series (2D mesh) | xarray.Dataset | `(time × cell_id)` with spatial coordinates |
| Time series (boundaries) | xarray.Dataset | `(time × bc_name × face_id)` |

xarray advantages for time series:
- **Named dimensions** - Access data by label, not position
- **Coordinate metadata** - River, reach, station attached to each cross section
- **Efficient slicing** - Select by time range, location, or variable
- **NetCDF compatible** - Easy export for GIS and other tools
- **Lazy loading** - Handle large datasets that don't fit in memory

---

### Cross Section Time Series

**Source**: `HdfResultsXsec.get_xsec_timeseries(plan_hdf)`
**Example notebook**: `examples/10_hdf_results_extraction.ipynb`

Complete time series for all 1D cross sections in a model.

**Dimensions**:

| Dimension | Description |
|-----------|-------------|
| `time` | Simulation timestamps (datetime64) |
| `cross_section` | Cross section identifier string |

**Data Variables**:

| Variable | Shape | Units | Description |
|----------|-------|-------|-------------|
| `Water_Surface` | (time, cross_section) | ft or m | Water surface elevation |
| `Velocity_Total` | (time, cross_section) | ft/s or m/s | Total velocity |
| `Velocity_Channel` | (time, cross_section) | ft/s or m/s | Channel velocity |
| `Flow_Lateral` | (time, cross_section) | cfs or m³/s | Lateral inflow |
| `Flow` | (time, cross_section) | cfs or m³/s | Total flow |

**Coordinates** (attached to `cross_section` dimension):

| Coordinate | Type | Description |
|------------|------|-------------|
| `River` | str | River name |
| `Reach` | str | Reach name |
| `Station` | str | River station |
| `Name` | str | Cross section name |
| `Maximum_Water_Surface` | float | Max WSE over simulation |
| `Maximum_Flow` | float | Max flow over simulation |
| `Maximum_Channel_Velocity` | float | Max channel velocity |
| `Maximum_Velocity_Total` | float | Max total velocity |
| `Maximum_Flow_Lateral` | float | Max lateral flow |

**Usage Example**:

```python
from ras_commander import HdfResultsXsec

# Get all cross section time series
ds = HdfResultsXsec.get_xsec_timeseries("01")

# Access water surface for all cross sections
wse = ds['Water_Surface']  # xarray.DataArray (time × cross_section)

# Select specific cross section by name
xs_data = ds.sel(cross_section="River Mile 10.5")

# Select by river/reach using coordinate
bald_eagle = ds.where(ds.coords['River'] == 'Bald Eagle', drop=True)

# Get time series for specific location
wse_timeseries = ds['Water_Surface'].sel(cross_section="River Mile 10.5")
print(wse_timeseries.values)  # numpy array of WSE values

# Get maximum values (pre-computed as coordinates)
max_wse = ds.coords['Maximum_Water_Surface']

# Slice by time range
subset = ds.sel(time=slice('2020-01-01', '2020-01-03'))

# Convert to DataFrame for analysis
df = ds['Water_Surface'].to_dataframe().reset_index()
```

---

### 2D Mesh Cell Time Series

**Source**: `HdfResultsMesh.get_mesh_cells_timeseries(plan_hdf, mesh_names=None, var=None)`
**Example notebook**: `examples/11_mesh_results_extraction.ipynb`

Time series for 2D mesh cell-based variables.

**Returns**: `Dict[str, xr.Dataset]` - Dictionary mapping mesh names to Datasets

**Dimensions**:

| Dimension | Description |
|-----------|-------------|
| `time` | Simulation timestamps |
| `cell_id` | Cell index (0-based) |

**Data Variables** (when `var=None`, all available):

| Variable | Shape | Description |
|----------|-------|-------------|
| `Water Surface` | (time, cell_id) | Water surface elevation |
| `Depth` | (time, cell_id) | Water depth |
| `Cell Cumulative Precipitation` | (time, cell_id) | Accumulated precipitation |

**Usage Example**:

```python
from ras_commander import HdfResultsMesh

# Get all mesh cell time series
mesh_data = HdfResultsMesh.get_mesh_cells_timeseries("01")

# Access specific mesh
floodplain_ds = mesh_data['Floodplain']

# Get water surface for all cells
wse = floodplain_ds['Water Surface']  # (time × cell_id)

# Get depth at specific cell
cell_100_depth = floodplain_ds['Depth'].sel(cell_id=100)

# Find cells that exceeded depth threshold
max_depth = floodplain_ds['Depth'].max(dim='time')
flooded_cells = max_depth.where(max_depth > 2.0, drop=True)

# Get specific variable only (more efficient)
depth_only = HdfResultsMesh.get_mesh_cells_timeseries("01", var="Depth")
```

---

### 2D Mesh Face Time Series

**Source**: `HdfResultsMesh.get_mesh_faces_timeseries(plan_hdf, mesh_name)`
**Example notebook**: `examples/11_mesh_results_extraction.ipynb`

Time series for face-based variables (velocity, flow between cells).

**Dimensions**:

| Dimension | Description |
|-----------|-------------|
| `time` | Simulation timestamps |
| `face_id` | Face index (0-based) |

**Data Variables**:

| Variable | Shape | Description |
|----------|-------|-------------|
| `Face Velocity` | (time, face_id) | Velocity at cell faces |
| `Face Flow` | (time, face_id) | Flow through cell faces |

**Usage Example**:

```python
from ras_commander import HdfResultsMesh

# Get face time series for a mesh
ds = HdfResultsMesh.get_mesh_faces_timeseries("01", mesh_name="Floodplain")

# Get maximum velocity across all faces
max_velocity = ds['Face Velocity'].max(dim='time')

# Find faces with high velocity
high_velocity_faces = max_velocity.where(max_velocity > 5.0, drop=True)
```

---

### Boundary Condition Time Series

**Source**: `HdfResultsMesh.get_boundary_conditions_timeseries(plan_hdf)`
**Example notebook**: See API reference

Time series for all boundary conditions in the model.

**Dimensions**:

| Dimension | Description |
|-----------|-------------|
| `time` | Simulation timestamps |
| `bc_name` | Boundary condition name |
| `face_id` | Face index (for per-face variables) |

**Data Variables**:

| Variable | Shape | Description |
|----------|-------|-------------|
| `stage` | (time, bc_name) | Water surface at BC |
| `flow` | (time, bc_name) | Total flow at BC |
| `flow_per_face` | (time, bc_name, face_id) | Flow distributed per face |
| `stage_per_face` | (time, bc_name, face_id) | Stage per face |

**Usage Example**:

```python
from ras_commander import HdfResultsMesh

# Get all boundary condition time series
ds = HdfResultsMesh.get_boundary_conditions_timeseries("01")

# Get inflow hydrograph for specific BC
upstream_flow = ds['flow'].sel(bc_name='Upstream Inflow')

# Calculate total inflow volume
import numpy as np
dt_hours = 1.0  # Assuming hourly output
total_volume = upstream_flow.sum() * dt_hours * 3600  # acre-ft or m³

# Compare multiple BCs
inflows = ds['flow'].sel(bc_name=['BC1', 'BC2', 'BC3'])
```

---

### Reference Lines Time Series

**Source**: `HdfResultsXsec.get_ref_lines_timeseries(plan_hdf)`
**Example notebook**: See API reference

Time series for reference lines defined in RASMapper.

**Dimensions**:

| Dimension | Description |
|-----------|-------------|
| `time` | Simulation timestamps |
| `ref_line` | Reference line name |

**Data Variables**:

| Variable | Description |
|----------|-------------|
| `Flow` | Flow across reference line |
| `Velocity` | Average velocity |
| `Water_Surface` | Water surface elevation |

---

### Reference Points Time Series

**Source**: `HdfResultsXsec.get_ref_points_timeseries(plan_hdf)`
**Example notebook**: See API reference

Time series for reference points defined in RASMapper.

**Dimensions**:

| Dimension | Description |
|-----------|-------------|
| `time` | Simulation timestamps |
| `ref_point` | Reference point name |

**Data Variables**:

| Variable | Units | Description |
|----------|-------|-------------|
| `Flow` | cfs or m³/s | Flow at point |
| `Velocity` | ft/s or m/s | Velocity at point |
| `Water_Surface` | ft or m | Water surface elevation |
| `Depth` | ft or m | Water depth |

---

### Pipe Network Time Series

**Source**: `HdfPipe.get_pipe_network_timeseries(plan_hdf, variable)`
**Example notebook**: `examples/12_pipe_pump_analysis.ipynb`

Time series for pipe network variables.

**Parameters**:
- `variable`: One of `"Depth"`, `"Flow"`, `"Velocity"`, etc.

**Returns**: `xr.DataArray` with dimensions `(time, location)`

**Node Variables** (via `extract_timeseries_for_node`):

| Variable | Description |
|----------|-------------|
| `Depth` | Water depth at node |
| `Drop Inlet Flow` | Flow into drop inlets |
| `Flooded Volume` | Flood volume at node |
| `Lateral Inflow` | Lateral inflow |
| `Outfall Flow` | Flow out of system |
| `Overflow` | Overflow volume |
| `Ponded Area` | Surface ponding area |
| `Ponded Depth` | Surface pond depth |
| `Ponded Volume` | Ponded water volume |

**Conduit Variables** (via `extract_timeseries_for_conduit`):

| Variable | Description |
|----------|-------------|
| `Pipe Flow (US)` | Upstream pipe flow |
| `Pipe Flow (DS)` | Downstream pipe flow |
| `Velocity (US)` | Upstream velocity |
| `Velocity (DS)` | Downstream velocity |
| `Depth (US)` | Upstream depth |
| `Depth (DS)` | Downstream depth |

---

### Pump Station Time Series

**Source**: `HdfPump.get_pump_station_timeseries(plan_hdf, pump_station)`
**Example notebook**: `examples/12_pipe_pump_analysis.ipynb`

Time series for a specific pump station.

**Returns**: `xr.DataArray` with dimensions `(time, variable)`

**Variables**:

| Variable | Description |
|----------|-------------|
| `Flow` | Pump flow rate |
| `Stage HW` | Headwater stage |
| `Stage TW` | Tailwater stage |
| `Pump 1` | Pump 1 status/flow |
| `Pump 2` | Pump 2 status/flow |
| ... | Additional pumps |

**Usage Example**:

```python
from ras_commander import HdfPump

# Get pump station time series
da = HdfPump.get_pump_station_timeseries("01", pump_station="Main Pump Station")

# Get total pumped flow
total_flow = da.sel(variable='Flow')

# Check pump on/off cycles
pump1_status = da.sel(variable='Pump 1')
```

---

### Common xarray Operations

**Selecting Data**:

```python
# Select by coordinate value
xs_data = ds.sel(cross_section="River Mile 10.5")

# Select by index
first_10_xs = ds.isel(cross_section=slice(0, 10))

# Select time range
jan_data = ds.sel(time=slice('2020-01-01', '2020-01-31'))

# Boolean selection with coordinates
bald_eagle = ds.where(ds.coords['River'] == 'Bald Eagle', drop=True)
```

**Aggregations**:

```python
# Maximum over time
max_wse = ds['Water_Surface'].max(dim='time')

# Mean over cross sections
mean_flow = ds['Flow'].mean(dim='cross_section')

# Percentiles
p95_depth = ds['Depth'].quantile(0.95, dim='time')
```

**Converting to DataFrame**:

```python
# Single variable to DataFrame
df = ds['Water_Surface'].to_dataframe().reset_index()

# Full dataset to DataFrame (can be large!)
df_full = ds.to_dataframe().reset_index()

# Specific cross section to DataFrame
xs_df = ds.sel(cross_section="XS 100").to_dataframe()
```

**Exporting**:

```python
# Save to NetCDF (preserves all metadata)
ds.to_netcdf("results.nc")

# Save to CSV (loses dimensions, use for single variables)
ds['Water_Surface'].to_dataframe().to_csv("wse.csv")
```

---

## Common DataFrame Operations

### Filtering by Profile (Steady)

```python
# Get WSE for specific profile
wse_df = HdfResultsPlan.get_steady_wse("02")
wse_100yr = wse_df[wse_df['Profile'] == '100 year']

# Pivot for cross-profile comparison
pivot = wse_df.pivot_table(
    index=['River', 'Reach', 'Station'],
    columns='Profile',
    values='WSE'
)
```

### Filtering Boundaries by Type

```python
# Get only flow hydrographs
flow_bcs = ras.boundaries_df[
    ras.boundaries_df['bc_type'] == 'Flow Hydrograph'
]

# Get DSS-based boundaries only
dss_bcs = ras.boundaries_df[
    ras.boundaries_df['Use DSS'] == True
]
```

### Time Series Analysis (Breach)

```python
# Get breach data and find peak
ts = HdfResultsBreach.get_breach_timeseries("01", "Dam")
peak_flow = ts['total_flow'].max()
peak_time = ts.loc[ts['total_flow'].idxmax(), 'datetime']

# Calculate breach duration
breach_start = ts[ts['breach_flow'].notna()].iloc[0]['datetime']
breach_end = ts[ts['breach_flow'].notna()].iloc[-1]['datetime']
duration = breach_end - breach_start
```

### Merging Plan and Flow Data

```python
# Combine plan and flow information
plan_flow = ras.plan_df.merge(
    ras.flow_df,
    left_on='Flow File',
    right_on='flow_number',
    how='left',
    suffixes=('_plan', '_flow')
)
```

---

## See Also

- [Quick Reference](quick-reference.md) - HEC-RAS keywords and codes
- [HDF Structure](hdf-structure.md) - HDF file organization
- [Geometry Parsing](geometry-parsing.md) - Geometry file format details
- Example notebooks in `examples/` folder for working code
