---
name: repairing-geometry-issues
description: |
  Automated geometry repair using RasFixit and quality validation using RasCheck.
  Handles blocked obstructions, generates before/after visualizations, and
  creates audit trails. Use when fixing geometry errors, repairing obstructions,
  validating models, or ensuring FEMA compliance.
triggers:
  - "fix"
  - "repair"
  - "geometry"
  - "blocked obstruction"
  - "validate"
  - "check"
  - "RasCheck"
  - "RasFixit"
  - "FEMA"
  - "quality assurance"
  - "QA"
  - "overlapping"
  - "obstruction overlap"
  - "elevation envelope"
  - "geometry error"
  - "model validation"
  - "USACE"
  - "cHECk-RAS"
version: 1.0.0
---

# Repairing Geometry Issues

Expert guidance for detecting, fixing, and validating HEC-RAS geometry issues using ras-commander's RasCheck and RasFixit modules.

## Quick Start

```python
from ras_commander import RasFixit, RasCheck

# 1. Check for issues
results = RasCheck.run_all("01")

# 2. Fix blocked obstructions (if detected)
fix_results = RasFixit.fix_blocked_obstructions(
    "model.g01",
    backup=True,      # Create timestamped backup
    visualize=True    # Generate before/after PNGs
)

# 3. Verify fixes
final_results = RasCheck.run_all("01")
```

## When to Use This Skill

Use when:
- HEC-RAS geometry preprocessing fails
- Need to validate model quality (FEMA/USACE standards)
- Fixing overlapping blocked obstructions
- Preparing models for peer review or submission
- Ensuring FEMA Base Level Engineering compliance
- Detecting Manning's n or cross section issues
- Validating structure (bridge/culvert) geometry
- Checking floodway surcharge limits
- Need audit trail and visualizations for engineering review

## Core Workflow: Check → Fix → Verify

The geometry repair workflow follows three steps:

### 1. Check (Detection)

Use **RasCheck** to detect issues:
```python
from ras_commander.check import RasCheck

# Run all checks
results = RasCheck.run_all("01")

# Or run specific checks
nt_results = RasCheck.check_nt(geom_hdf)       # Manning's n
xs_results = RasCheck.check_xs(geom_hdf)       # Cross sections
struct_results = RasCheck.check_structures(geom_hdf)  # Bridges/culverts
```

### 2. Fix (Repair)

Use **RasFixit** to repair detected issues:
```python
from ras_commander import RasFixit

# Fix blocked obstructions (most common issue)
fix_results = RasFixit.fix_blocked_obstructions(
    "model.g01",
    backup=True,      # ALWAYS create backup
    visualize=True    # ALWAYS generate verification PNGs
)

# Non-destructive detection only (dry run)
detect_results = RasFixit.detect_obstruction_overlaps("model.g01")
```

### 3. Verify (Validation)

Re-run checks to confirm fixes:
```python
# Verify no overlaps remain
verify_results = RasFixit.detect_obstruction_overlaps("model.g01")
if verify_results.total_xs_fixed == 0:
    print("SUCCESS: All obstructions fixed!")

# Run full quality validation
final_results = RasCheck.run_all("01")
```

## RasCheck: Quality Validation

### Check Categories

RasCheck implements **5 comprehensive validation checks** based on FEMA's cHECk-RAS tool:

| Check Type | Function | Validates |
|------------|----------|-----------|
| **NT Check** | `check_nt()` | Manning's n, transition coefficients |
| **XS Check** | `check_xs()` | Cross section spacing, station ordering, reach lengths |
| **Structure Check** | `check_structures()` | Bridges, culverts, inline weirs |
| **Floodway Check** | `check_floodways()` | Surcharge limits, encroachment methods |
| **Profiles Check** | `check_profiles()` | WSE ordering, discharge consistency |

### Running Validation Checks

**All checks at once** (recommended):
```python
results = RasCheck.run_all("01")

print(f"Total messages: {len(results.messages)}")
print(f"Errors: {results.get_error_count()}")
print(f"Warnings: {results.get_warning_count()}")
```

**Individual checks** (for targeted validation):
```python
# Get HDF paths from plan
plan_row = ras.plan_df[ras.plan_df['plan_number'] == "01"].iloc[0]
geom_hdf = Path(plan_row['Geom Path']).with_suffix('.hdf')

# Run specific check
nt_results = RasCheck.check_nt(geom_hdf)
```

### Analyzing Results

**Convert to DataFrame**:
```python
df = results.to_dataframe()

# Filter by severity
errors = df[df['severity'] == 'ERROR']
warnings = df[df['severity'] == 'WARNING']

# Filter by check type
nt_issues = df[df['check_type'] == 'NT']

# Filter by station
station_issues = df[df['station'] == '12345.67']
```

**Generate reports**:
```python
from ras_commander.check import ReportMetadata

# HTML report with metadata
metadata = ReportMetadata(
    project_name=ras.project_name,
    plan_number="01",
    checked_by="Engineer Name"
)
results.to_html("validation_report.html", metadata=metadata)

# CSV export for Excel
df.to_csv("validation_messages.csv", index=False)
```

### Custom Thresholds

Override default FEMA/USACE standards:
```python
from ras_commander.check import create_custom_thresholds

custom = create_custom_thresholds({
    'mannings_n.overbank_max': 0.150,        # Stricter limit
    'reach_length.max_length_ft': 2000.0,    # More conservative
    'transitions.normal_contraction': 0.1,   # Custom coefficient
})

results = RasCheck.run_all("01", thresholds=custom)
```

### State-Specific Standards

Use state-specific floodway surcharge limits:
```python
from ras_commander.check import get_state_surcharge_limit

# Illinois uses stricter 0.1 ft limit (vs FEMA's 1.0 ft)
il_limit = get_state_surcharge_limit('IL')  # Returns 0.1

results = RasCheck.run_all(
    "01",
    floodway_profile="Floodway",
    surcharge=il_limit
)
```

States with non-standard limits:
- **IL**: 0.1 ft
- **WI**: 0.0 ft (no surcharge allowed)
- **MN**: 0.5 ft
- **NJ**: 0.2 ft
- **MI, IN, OH**: 0.5 ft
- **Default (TX, most states)**: 1.0 ft

## RasFixit: Automated Repair

### Blocked Obstruction Repair

**Problem**: Overlapping or adjacent blocked obstructions cause HEC-RAS preprocessing errors.

**Solution**: Elevation envelope algorithm with 0.02-unit gap insertion.

### Fix Workflow

**Step 1: Detect issues** (non-destructive):
```python
results = RasFixit.detect_obstruction_overlaps("model.g01")

print(f"Cross sections checked: {results.total_xs_checked}")
print(f"Cross sections with overlaps: {results.total_xs_fixed}")

# Review affected stations
for msg in results.messages:
    print(f"RS {msg.station}: {msg.original_count} → {msg.fixed_count}")
```

**Step 2: Apply fixes**:
```python
fix_results = RasFixit.fix_blocked_obstructions(
    "model.g01",
    backup=True,      # Creates .g01.backup_YYYYMMDD_HHMMSS
    visualize=True    # Creates folder with before/after PNGs
)

print(f"Fixed {fix_results.total_xs_fixed} cross sections")
print(f"Backup: {fix_results.backup_path}")
print(f"Visualizations: {fix_results.visualization_folder}")
```

**Step 3: Review visualizations**:
```python
# View PNG visualizations for engineering review
import matplotlib.pyplot as plt
from matplotlib.image import imread

png_files = sorted(fix_results.visualization_folder.glob("*.png"))
for png_file in png_files[:3]:  # First 3 stations
    img = imread(png_file)
    plt.figure(figsize=(14, 10))
    plt.imshow(img)
    plt.axis('off')
    plt.title(png_file.name)
    plt.show()
```

**Step 4: Export audit trail**:
```python
# Export to CSV for documentation
df = fix_results.to_dataframe()
df.to_csv("obstruction_fixes.csv", index=False)
```

### Elevation Envelope Algorithm

The repair algorithm is **hydraulically conservative**:

1. **Collect critical stations**: All start/end points of obstructions
2. **Maximum elevation wins**: In overlap zones, use highest elevation (most restrictive)
3. **Merge adjacent segments**: Combine segments with same elevation
4. **Insert 0.02-unit gaps**: Minimum separation where elevations differ

**Example**:
```
Original (overlapping):
  Segment 1: 100.0 - 200.0 ft, elev 35.0
  Segment 2: 150.0 - 250.0 ft, elev 36.0

Fixed (elevation envelope with gap):
  Segment 1: 100.0 - 150.0 ft, elev 35.0
  Segment 2: 150.02 - 250.0 ft, elev 36.0  # 0.02 gap inserted
```

### Fix Results Data Structure

**FixResults** contains:
- `total_xs_checked`: Cross sections scanned
- `total_xs_fixed`: Cross sections modified
- `messages`: List of FixMessage objects
- `backup_path`: Path to timestamped backup
- `visualization_folder`: Path to PNG folder

**FixMessage** contains:
- `station`: River station (e.g., "12345.67")
- `action`: FixAction enum (OVERLAP_RESOLVED, GAP_INSERTED, etc.)
- `original_data`: List of original (start, end, elev) tuples
- `fixed_data`: List of fixed (start, end, elev) tuples
- `original_count`: Number of original obstructions
- `fixed_count`: Number of fixed obstructions

## Log Parsing for Automated Workflows

Detect errors from HEC-RAS compute logs:

```python
from ras_commander.fixit import log_parser

# Parse log file
with open("compute.log", 'r') as f:
    log_content = f.read()

# Detect obstruction errors
errors = log_parser.detect_obstruction_errors(log_content)
print(f"Found {len(errors)} obstruction errors")

# Extract affected stations
stations = log_parser.extract_cross_section_ids(log_content)
print(f"Affected stations: {stations}")

# Generate report
report = log_parser.generate_error_report(errors)
print(report)
```

**Automated fix workflow**:
```python
def auto_fix_workflow(log_file, project_dir):
    """Detect errors from log, then fix geometry files."""

    # Check if log has obstruction errors
    if not log_parser.has_obstruction_errors(log_file):
        return None

    # Find all geometry files
    geom_files = log_parser.find_geometry_files_in_directory(project_dir)

    # Fix each geometry file
    for geom_path in geom_files:
        results = RasFixit.fix_blocked_obstructions(
            geom_path,
            backup=True,
            visualize=True
        )
        print(f"Fixed {results.total_xs_fixed} XS in {geom_path.name}")

    return results
```

## Engineering Review Requirements

**CRITICAL**: All automated fixes MUST be reviewed by a licensed professional engineer before use in production models.

### Required Documentation

1. **Timestamped backups**: Always use `backup=True`
2. **Before/after visualizations**: Always use `visualize=True`
3. **Audit trail**: Export `FixResults.to_dataframe()` to CSV
4. **Algorithm documentation**: Include elevation envelope algorithm description

### Verification Steps

1. **Visual inspection**: Review all PNG visualizations
2. **Compare hydraulics**: Run model with original and fixed geometry
3. **Spot check**: Manually verify critical cross sections
4. **Professional judgment**: Ensure fixes align with engineering intent

## Integration with Quality Assurance Subagent

For complex validation workflows, use the **quality-assurance** subagent:

```python
# Cross-reference with subagent
# See: .claude/subagents/quality-assurance/SUBAGENT.md
```

The subagent provides:
- Comprehensive validation workflows
- Report generation templates
- FEMA/USACE standards integration
- Multi-plan validation
- Advanced threshold customization

## Common Issues and Solutions

### Issue: Geometry preprocessing fails

**Solution**: Check for blocked obstruction overlaps
```python
results = RasFixit.detect_obstruction_overlaps("model.g01")
if results.total_xs_fixed > 0:
    fix_results = RasFixit.fix_blocked_obstructions(
        "model.g01",
        backup=True,
        visualize=True
    )
```

### Issue: FEMA validation warnings

**Solution**: Run RasCheck and generate report
```python
results = RasCheck.run_all("01")
results.to_html("fema_validation.html")

# Address errors (severity=ERROR)
errors = results.filter_by_severity(Severity.ERROR)
for error in errors:
    print(f"[{error.message_id}] RS {error.station}: {error.message}")
```

### Issue: Manning's n out of range

**Solution**: Use NT Check to identify issues
```python
nt_results = RasCheck.check_nt(geom_hdf)
df = nt_results.to_dataframe()

# Filter Manning's n issues
n_issues = df[df['message_id'].str.startswith('NT_RC')]
print(n_issues[['station', 'message']])
```

### Issue: Cross section spacing too large

**Solution**: Use XS Check with custom threshold
```python
custom = create_custom_thresholds({
    'reach_length.max_length_ft': 1500.0  # More conservative
})

xs_results = RasCheck.check_xs(geom_hdf, thresholds=custom)
```

## Reference Documentation

See detailed API documentation in:
- **reference/rascheck.md**: Complete RasCheck validation reference
- **reference/rasfixit.md**: Complete RasFixit repair reference

## Example Scripts

See complete workflow examples in:
- **examples/check-fix-verify.py**: Full Check → Fix → Verify workflow
- **examples/obstruction-repair.py**: Blocked obstruction repair example

## Example Notebooks

Complete workflows with visualizations:
- **examples/27_fixit_blocked_obstructions.ipynb**: RasFixit workflow
- **examples/28_quality_assurance_rascheck.ipynb**: RasCheck validation

## Cross-References

- **Quality Assurance Subagent**: `.claude/subagents/quality-assurance/SUBAGENT.md`
- **RasCheck Module**: `ras_commander/check/CLAUDE.md`
- **RasFixit Module**: `ras_commander/fixit/AGENTS.md`
- **Testing Approach**: `.claude/rules/testing/tdd-approach.md`

## Technology Notes

### RasCheck Architecture
- Reads HDF files (geometry preprocessor output)
- Plain text geometry file parsing for additional checks
- Follows FEMA cHECk-RAS validation logic
- Thread-safe for parallel validation
- Low memory footprint (suitable for large models)

### RasFixit Architecture
- Operates on plain text geometry files (.g##)
- Fixed-width FORTRAN parsing (8-character fields)
- Lazy loading of matplotlib (optional visualization)
- Timestamped backups for safety
- Audit trail preservation

### Performance
- **RasCheck**: 5-15 seconds for typical 1D model
- **RasFixit**: < 1 second per cross section repair
- **Visualization**: 2-3 seconds per PNG (optional)
