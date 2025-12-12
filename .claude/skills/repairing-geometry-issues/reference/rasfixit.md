# RasFixit Repair Reference

Complete reference for RasFixit automated geometry repair algorithms, outputs, and engineering requirements.

## Overview

RasFixit provides automated repair for HEC-RAS geometry issues. Currently implements blocked obstruction repair with elevation envelope algorithm. Future releases will add additional repair types.

## Current Capabilities

### Blocked Obstruction Repair

**Problem**: Overlapping or adjacent blocked obstructions cause HEC-RAS geometry preprocessing errors.

**Solution**: Elevation envelope algorithm that:
1. Resolves overlaps using maximum elevation (hydraulically conservative)
2. Inserts 0.02-unit gaps where different elevations meet (HEC-RAS requirement)
3. Creates before/after visualizations for engineering review
4. Generates audit trail with original and fixed data

## API Reference

### Main Functions

#### `RasFixit.fix_blocked_obstructions()`

Fix overlapping blocked obstructions in geometry file.

**Signature**:
```python
RasFixit.fix_blocked_obstructions(
    geom_path: str | Path,
    backup: bool = True,
    visualize: bool = False,
    dry_run: bool = False
) -> FixResults
```

**Parameters**:
- `geom_path`: Path to geometry file (.g##)
- `backup`: Create timestamped backup (default: True, **RECOMMENDED**)
- `visualize`: Generate before/after PNG visualizations (default: False, **RECOMMENDED**)
- `dry_run`: Detect only, don't modify file (default: False)

**Returns**: `FixResults` object with repair summary and details

**Example**:
```python
from ras_commander import RasFixit

results = RasFixit.fix_blocked_obstructions(
    "model.g01",
    backup=True,      # ALWAYS use for production models
    visualize=True    # ALWAYS use for engineering review
)

print(f"Fixed {results.total_xs_fixed} cross sections")
print(f"Backup: {results.backup_path}")
print(f"Visualizations: {results.visualization_folder}")
```

#### `RasFixit.detect_obstruction_overlaps()`

Non-destructive detection of overlapping obstructions.

**Signature**:
```python
RasFixit.detect_obstruction_overlaps(
    geom_path: str | Path
) -> FixResults
```

**Parameters**:
- `geom_path`: Path to geometry file (.g##)

**Returns**: `FixResults` object with detection results (no file modification)

**Example**:
```python
# Pre-flight check before running HEC-RAS
results = RasFixit.detect_obstruction_overlaps("model.g01")

if results.total_xs_fixed > 0:
    print(f"WARNING: {results.total_xs_fixed} cross sections have overlaps")
    for msg in results.messages:
        print(f"  RS {msg.station}: {msg.original_count} obstructions")
else:
    print("No overlaps detected - geometry file is clean")
```

## Elevation Envelope Algorithm

### Algorithm Overview

The elevation envelope algorithm resolves overlaps while preserving hydraulic behavior:

1. **Collect critical stations**: Extract all start/end stations from blocked obstructions
2. **Build elevation envelope**: For each segment between stations, use **maximum elevation**
3. **Merge adjacent segments**: Combine consecutive segments with same elevation
4. **Insert gaps**: Add 0.02-unit gaps where different elevations meet

### Hydraulic Conservatism

The algorithm is **hydraulically conservative**:
- Uses maximum elevation in overlap zones (most restrictive for flow)
- Preserves all flow restrictions from original obstructions
- Never reduces obstruction elevations
- Suitable for FEMA/USACE submission without manual adjustment

### Gap Insertion

**HEC-RAS requirement**: Adjacent blocked obstructions must have minimum 0.02-unit separation.

**Implementation**:
```python
GAP_SIZE = 0.02  # Fixed constant, do not change

# Gap inserted when:
# - Two segments touch (end1 == start2)
# - AND elevations differ (elev1 != elev2)

# Result:
# Original: Seg1(100.0-150.0, 35.0), Seg2(150.0-200.0, 36.0)
# Fixed:    Seg1(100.0-150.0, 35.0), Seg2(150.02-200.0, 36.0)
```

### Algorithm Example

**Original obstructions** (overlapping):
```
Seg1: Station 100.0 - 200.0, Elevation 35.0
Seg2: Station 150.0 - 250.0, Elevation 36.0
Seg3: Station 180.0 - 230.0, Elevation 34.5
```

**Step 1**: Collect critical stations
```
Stations: [100.0, 150.0, 180.0, 200.0, 230.0, 250.0]
```

**Step 2**: Build elevation envelope (max elevation in each segment)
```
100.0-150.0: max(35.0) = 35.0
150.0-180.0: max(35.0, 36.0) = 36.0
180.0-200.0: max(35.0, 36.0, 34.5) = 36.0
200.0-230.0: max(36.0, 34.5) = 36.0
230.0-250.0: max(36.0) = 36.0
```

**Step 3**: Merge adjacent segments with same elevation
```
100.0-150.0: 35.0
150.0-230.0: 36.0  (merged 4 segments)
230.0-250.0: 36.0
```

**Step 4**: Insert 0.02 gaps where elevations differ
```
Fixed obstructions (3 segments):
  Seg1: 100.0 - 150.0,   Elevation 35.0
  Seg2: 150.02 - 230.0,  Elevation 36.0  (gap inserted)
  Seg3: 230.02 - 250.0,  Elevation 36.0  (gap inserted, but same elev - could merge)
```

**Final optimization**: Merge segments 2 and 3 (same elevation)
```
Fixed obstructions (2 segments):
  Seg1: 100.0 - 150.0,   Elevation 35.0
  Seg2: 150.02 - 250.0,  Elevation 36.0
```

## Data Structures

### FixResults

**Attributes**:
- `total_xs_checked` (int): Number of cross sections scanned
- `total_xs_fixed` (int): Number of cross sections modified
- `messages` (List[FixMessage]): Detailed results for each cross section
- `backup_path` (Path | None): Path to backup file (if backup=True)
- `visualization_folder` (Path | None): Path to PNG folder (if visualize=True)

**Methods**:
```python
# Convert to DataFrame
df = results.to_dataframe()

# Check if any fixes were applied
has_fixes = results.total_xs_fixed > 0

# Iterate over messages
for msg in results.messages:
    print(f"RS {msg.station}: {msg.message}")
```

### FixMessage

**Attributes**:
- `station` (str): River station (e.g., "12345.67")
- `action` (FixAction): Action taken (OVERLAP_RESOLVED, GAP_INSERTED, etc.)
- `message` (str): Human-readable description
- `original_data` (List[Tuple[float, float, float]]): Original (start, end, elev)
- `fixed_data` (List[Tuple[float, float, float]]): Fixed (start, end, elev)
- `original_count` (int): Number of original obstructions
- `fixed_count` (int): Number of fixed obstructions

**Example**:
```python
msg = results.messages[0]

print(f"Station: {msg.station}")
print(f"Action: {msg.action.value}")

print("\nOriginal:")
for start, end, elev in msg.original_data:
    print(f"  {start:.2f} - {end:.2f}, Elevation: {elev:.2f}")

print("\nFixed:")
for start, end, elev in msg.fixed_data:
    print(f"  {start:.2f} - {end:.2f}, Elevation: {elev:.2f}")
```

### FixAction Enum

**Values**:
- `OVERLAP_RESOLVED`: Overlapping obstructions resolved using elevation envelope
- `GAP_INSERTED`: 0.02-unit gap inserted between adjacent obstructions
- `SEGMENT_MERGED`: Adjacent segments with same elevation merged
- `NO_ACTION`: No issues detected, no changes needed

## Visualization Outputs

### PNG Generation

When `visualize=True`, RasFixit generates before/after PNG visualizations for each fixed cross section.

**Output structure**:
```
model_g01_Obstructions_Fixed/
├── RS_12345.67_Obstructions_Fixed.png
├── RS_23456.78_Obstructions_Fixed.png
└── RS_34567.89_Obstructions_Fixed.png
```

**PNG content**:
- **Top panel**: Original obstruction configuration (red bars)
- **Bottom panel**: Fixed obstruction configuration (green bars)
- **Legend**: Obstruction numbers and elevations
- **Title**: River station and fix summary

### Lazy Loading

Visualization uses **lazy loading** to keep matplotlib optional:
```python
# matplotlib imported only when visualize=True
# No overhead if visualize=False
```

Dependencies:
- matplotlib (required only for `visualize=True`)
- No other visualization dependencies

## Backup and Audit Trail

### Timestamped Backups

When `backup=True` (default and **RECOMMENDED**):
```
Original file: model.g01
Backup created: model.g01.backup_20231215_143022
```

**Backup naming**:
- Format: `{original_name}.backup_{YYYYMMDD}_{HHMMSS}`
- Preserves original file completely
- Multiple backups allowed (each run creates new backup)

**Restore from backup**:
```python
import shutil
from pathlib import Path

backup_path = Path("model.g01.backup_20231215_143022")
original_path = Path("model.g01")

shutil.copy(backup_path, original_path)
print("Restored from backup")
```

### Audit Trail

Export FixResults to CSV for documentation:
```python
df = results.to_dataframe()
df.to_csv("obstruction_fixes_audit_trail.csv", index=False)
```

**CSV columns**:
- `station`: River station
- `action`: Fix action taken
- `original_count`: Number of original obstructions
- `fixed_count`: Number of fixed obstructions
- `message`: Description of fix
- `original_data`: JSON representation of original obstructions
- `fixed_data`: JSON representation of fixed obstructions

## Fixed-Width Parsing

### FORTRAN-Style Format

HEC-RAS geometry files use **8-character fixed-width fields**:
```
FIELD_WIDTH = 8  # Do not change

# Example:
"  100.50  200.75   35.20"
 ^^^^^^^^^^^^^^^^^^^^^^^^
 8 chars  8 chars  8 chars
```

### Overflow Handling

Values that don't fit in 8 characters are represented as asterisks:
```
# Normal:  "  123.45"
# Overflow: "********"
```

RasFixit detects and handles overflow automatically.

### Section Terminators

Blocked obstruction data block ends at these markers:
- `Bank Sta=` - Bank station definition
- `#XS Ineff=` - Ineffective flow areas
- `#Mann=` - Manning's n values
- `XS Rating Curve=` - Rating curve data
- `XS HTab` - Hydraulic property tables
- `Exp/Cntr=` - Expansion/contraction coefficients

## Engineering Review Requirements

**CRITICAL**: All automated repairs require professional engineering review.

### Required Documentation

1. **Backup file**: Always use `backup=True`
   - Enables rollback if issues discovered
   - Preserves original geometry for comparison

2. **Visualizations**: Always use `visualize=True`
   - PNG visualizations for each fixed cross section
   - Before/after comparison
   - Engineering review and approval

3. **Audit trail**: Export to CSV
   - Documents all changes made
   - Original and fixed data preserved
   - Suitable for submission to FEMA/USACE

4. **Algorithm documentation**: Include with submission
   - Elevation envelope algorithm description
   - Hydraulic conservatism explanation
   - Reference to ras-commander documentation

### Verification Steps

Before accepting automated fixes:

1. **Visual inspection**:
   ```python
   # Review all PNG visualizations
   png_files = sorted(results.visualization_folder.glob("*.png"))
   for png_file in png_files:
       # Review manually or with matplotlib
       pass
   ```

2. **Compare hydraulics**:
   ```python
   # Run model with both geometries, compare results
   # Expect minimal WSE differences (< 0.01 ft typical)
   ```

3. **Spot check critical stations**:
   ```python
   # Manually verify high-impact cross sections
   critical_stations = ["12345.67", "23456.78"]
   for msg in results.messages:
       if msg.station in critical_stations:
           print(f"Review: RS {msg.station}")
   ```

4. **Professional judgment**:
   - Ensure fixes align with engineering intent
   - Verify hydraulic behavior is preserved
   - Document any anomalies or concerns

### Sign-Off Requirements

All fixes require:
- Licensed Professional Engineer (PE) review and approval
- Documentation package (backups, visualizations, audit trail)
- Hydraulic comparison results (original vs fixed)
- Written justification for automated repair approach

## Performance Characteristics

**Speed**:
- Detection: < 0.1 seconds per cross section
- Repair: < 0.5 seconds per cross section
- Visualization: 2-3 seconds per PNG

**Memory**:
- Low memory footprint (processes one XS at a time)
- Suitable for large models (1000+ cross sections)

**File Size**:
- Geometry file size unchanged (same number of characters)
- Backup files identical to original
- PNG files: 100-200 KB each

## Testing and Validation

### Test Data

Example project with known obstruction issues:
```
examples/example_projects/A120-00-00/A120_00_00.g01
- 91 cross sections total
- 15 cross sections with overlaps
- Real-world Harris County Flood Control District model
```

### Validation Workflow

```python
# 1. Test detection
results = RasFixit.detect_obstruction_overlaps("test_model.g01")
assert results.total_xs_fixed > 0, "Expected overlaps not found"

# 2. Apply fixes on copy
import shutil
shutil.copy("test_model.g01", "test_copy.g01")
fix_results = RasFixit.fix_blocked_obstructions(
    "test_copy.g01",
    backup=True,
    visualize=True
)

# 3. Verify no overlaps remain
verify_results = RasFixit.detect_obstruction_overlaps("test_copy.g01")
assert verify_results.total_xs_fixed == 0, "Overlaps still present"

# 4. Compare hydraulics
# (Run HEC-RAS on both files, compare WSE)
```

## Future Capabilities (Planned)

Additional repair types in development:
- Ineffective flow area corrections
- Bank station auto-placement
- Station-elevation reversal fixes
- Manning's n range corrections
- Cross section spacing optimization

## Cross-References

- **RasCheck integration**: `ras_commander/check/CLAUDE.md`
- **Main module docs**: `ras_commander/fixit/AGENTS.md`
- **Example notebook**: `examples/27_fixit_blocked_obstructions.ipynb`
- **Quality assurance subagent**: `.claude/subagents/quality-assurance/SUBAGENT.md`
