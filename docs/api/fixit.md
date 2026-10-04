# Fixit Module

Automated geometry repair for HEC-RAS models.

## Overview

The `fixit` module provides automated fix capabilities for common HEC-RAS geometry issues. It complements the `check` module by providing repair functionality for detected issues.

!!! warning "Engineering Review Required"
    All fixes should be reviewed by a licensed professional engineer before accepting changes to production models. The visualization outputs provide an audit trail showing original and fixed configurations.

## Supported Fixes

| Fix Type | Method | Description |
|----------|--------|-------------|
| Blocked obstruction overlaps | `fix_blocked_obstructions()` / `detect_obstruction_overlaps()` | Elevation-envelope rewrite and spacing |
| HTAB starting elevations | `fix_htab_starting_elevations()` / `detect_htab_issues()` | Raise a starting elevation below the invert by the requested margin |
| Bank stations | `fix_bank_stations()` / `detect_bank_station_issues()` | Normalize station/elevation formatting and insert or snap bank points |
| Ineffective flow areas | `fix_ineffective_flow()` / `detect_ineffective_flow_issues()` | Repair the documented legacy right-station-zero sentinel case |
| Manning's n | `fix_mannings_n()` / `detect_mannings_n_issues()` | Reconstruct missing legacy values or align breakpoints with current banks |

All five families operate on plain-text geometry. Writers default to
`backup=True` and accept `dry_run=True`; detection wrappers use the corresponding
dry-run path. Bank/ineffective/Manning writers also accept `rs_list`. The
ineffective-area and Manning repairs target documented legacy upgrade patterns,
not arbitrary geometry or roughness calibration. HTAB `margin` uses the source
elevation units. Review the operation-specific messages before writing to a copy.

Dry-run `total_xs_fixed` counts proposed/targeted changes, not saved edits.
Bank normalization can target every selected Type 1 cross section even when
its values already appear correct. `FixResults.get_fixed_count()` counts
non-`NO_ACTION` messages, which need not equal unique cross sections.
`to_dataframe()` returns no columns when there are no messages.

For 2D mesh diagnostics and repair, use [Meshing](meshing.md).

## Quick Start

```python
from ras_commander import RasFixit

# Detect overlaps (non-destructive)
results = RasFixit.detect_obstruction_overlaps("model.g04")
print(f"Found {results.total_xs_fixed} cross sections with overlaps")

# Fix with visualization for engineering review
results = RasFixit.fix_blocked_obstructions(
    "model.g04",
    backup=True,      # Create timestamped backup
    visualize=True    # Generate before/after PNGs
)
print(f"Fixed {results.total_xs_fixed} cross sections")
print(f"Visualizations: {results.visualization_folder}")
```

## RasFixit

<a id="ras_commander.fixit.RasFixit"></a>

::: ras_commander.fixit.RasFixit.RasFixit
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - fix_blocked_obstructions
        - detect_obstruction_overlaps
        - fix_htab_starting_elevations
        - detect_htab_issues
        - fix_bank_stations
        - detect_bank_station_issues
        - fix_ineffective_flow
        - detect_ineffective_flow_issues
        - fix_mannings_n
        - detect_mannings_n_issues

### Method Details

#### fix_blocked_obstructions

Main method for fixing overlapping blocked obstructions.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `geom_path` | str, Path | required | Path to HEC-RAS geometry file (.g##) |
| `backup` | bool | True | Create timestamped backup before modification |
| `visualize` | bool | False | Generate before/after PNG comparisons |
| `dry_run` | bool | False | Detect issues without modifying file |

**Returns:** `FixResults` object containing:

- `total_xs_checked`: Number of cross sections examined
- `total_xs_fixed`: Number of cross sections modified
- `backup_path`: Path to backup file (if created)
- `visualization_folder`: Path to PNG visualizations (if generated)
- `messages`: List of `FixMessage` objects with detailed fix information

**Example:**

```python
from ras_commander import RasFixit

# Fix with all options
results = RasFixit.fix_blocked_obstructions(
    "BaldEagle.g01",
    backup=True,
    visualize=True
)

# Examine results
for msg in results.messages:
    print(f"RS {msg.station}: {msg.original_count} -> {msg.fixed_count} obstructions")
    print(f"  Visualization: {msg.visualization_path}")

# Export to DataFrame
df = results.to_dataframe()
df.to_csv("fix_report.csv")
```

## Result Classes

### FixResults

::: ras_commander.fixit.results.FixResults
    options:
      show_root_heading: true
      heading_level: 3

### FixMessage

::: ras_commander.fixit.results.FixMessage
    options:
      show_root_heading: true
      heading_level: 3

### FixAction

::: ras_commander.fixit.results.FixAction
    options:
      show_root_heading: true
      heading_level: 3

## Log Parser

The `log_parser` module provides utilities for detecting obstruction errors from HEC-RAS compute logs.

```python
from ras_commander.fixit import log_parser

# Parse log for errors
errors = log_parser.detect_obstruction_errors(log_content)

# Find geometry files
geom_files = log_parser.find_geometry_files_in_directory(project_dir)

# Generate report
print(log_parser.generate_error_report(errors))
```

### Functions

| Function | Description |
|----------|-------------|
| `detect_obstruction_errors(log_content)` | Parse log text, return list of error dicts |
| `extract_geometry_files(log_content, project_dir)` | Find geometry file references in log |
| `find_geometry_files_in_directory(directory)` | Scan directory for .g## files |
| `has_obstruction_errors(log_file_path)` | Quick boolean check for errors |
| `generate_error_report(errors)` | Format errors for human review |
| `extract_cross_section_ids(log_content)` | Get list of affected river stations |

### Automated Workflow Example

```python
from ras_commander import RasFixit
from ras_commander.fixit import log_parser

# Step 1: Check log for errors
if log_parser.has_obstruction_errors("compute.log"):

    # Step 2: Parse errors
    with open("compute.log", "r") as f:
        errors = log_parser.detect_obstruction_errors(f.read())

    print(f"Found {len(errors)} obstruction errors")

    # Step 3: Find and fix geometry files
    geom_files = log_parser.find_geometry_files_in_directory(project_dir)

    for geom_path in geom_files:
        results = RasFixit.fix_blocked_obstructions(
            geom_path,
            visualize=True
        )
        print(f"Fixed {results.total_xs_fixed} cross sections in {geom_path}")
```

## Algorithm Details

### Elevation Envelope

The core algorithm for fixing overlapping obstructions:

1. **Collect Critical Stations**: Extract all start/end stations from obstructions
2. **Find Max Elevation**: For each segment between stations, use the maximum elevation from all overlapping obstructions (preserves the higher blocked elevation)
3. **Merge Segments**: Combine adjacent segments with identical elevations
4. **Insert Gaps**: Apply the implementation’s 0.02-unit spacing where different elevations meet

```
Original:  [100-120@elev5, 110-130@elev3]  (overlap 110-120)

Step 1 - Critical stations: [100, 110, 120, 130]

Step 2 - Max elevation per segment:
  100-110: elev 5 (only covered by first obstruction)
  110-120: elev 5 (max of 5 and 3)
  120-130: elev 3 (only covered by second obstruction)

Step 3 - Merge same-elevation:
  100-120: elev 5 (merged)
  120-130: elev 3

Step 4 - Insert gap:
  100-120: elev 5
  120.02-130: elev 3  (0.02 gap added)

Result: [100-120@elev5, 120.02-130@elev3]
```

### Why Max Elevation?

The envelope retains the higher blocked elevation in overlapping intervals.
That is an algorithmic choice, not proof of conservative flood levels for every
model. Review the changed geometry and its hydraulic effects.

### Gap Insertion

The implementation inserts 0.02 project station units between adjacent envelope
segments with different elevations. This spacing is not a universal hydraulic
tolerance or evidence that the rewrite preserves all model behavior.

## Integration with Check Module

The `fixit` module complements the `check` module:

```python
from ras_commander import RasCheck, RasFixit

# Supply plan and geometry HDF paths plus the selected steady profiles
check_results = RasCheck.check_xs(plan_hdf, geom_hdf, profiles)
obstruction_issues = [m for m in check_results.messages
                      if m.message_id.startswith('XS_BO')]

if obstruction_issues:
    print(f"Found {len(obstruction_issues)} obstruction issues")

    # Fix with RasFixit (operates on plain text geometry files)
    fix_results = RasFixit.fix_blocked_obstructions(
        "model.g01",
        visualize=True
    )
    print(f"Fixed {fix_results.total_xs_fixed} cross sections")
```

| Module | Input | Purpose |
|--------|-------|---------|
| `RasCheck.check_xs` | Plan and geometry HDFs plus selected profiles | Detect cross-section issues during results review |
| `RasFixit` | Geometry files (.g##) | Repair issues in source geometry |

## Visualization Output

When `visualize=True`, the module generates PNG files showing:

- **Top Panel**: Original obstructions (with overlaps) using 'viridis' colormap
- **Bottom Panel**: Fixed obstructions (elevation envelope) using 'plasma' colormap

Files are saved to: `{ProjectName}_g{##}_Obstructions_Fixed/RS_{station}.png`

These visualizations are critical for engineering review - they show exactly what changes were made and why.

## Example Project

The repository includes the **HCFCD M3 Model A120-00-00** (Harris County Flood Control District) as a real-world example with blocked obstruction issues:

- **Location**: `examples/example_projects/A120-00-00/`
- **Geometry files**: `A120_00_00.g01`, `A120_00_00.g02`
- **Cross sections**: 91 total, 15 with overlapping obstructions
- **Source**: `examples/data/A120-00-00.zip`

An example notebook for blocked obstructions will be added in a future release; the API above covers the current workflow end-to-end.
