# RasFixit Repair Algorithms Reference

Complete documentation for RasFixit automated geometry repair capabilities with algorithm details, examples, and professional review requirements.

## Overview

RasFixit provides automated repair of HEC-RAS geometry issues identified by RasCheck. Currently implements one repair type with more planned:

**Current**:
- Blocked Obstructions (elevation envelope algorithm)

**Future** (not yet implemented):
- Ineffective flow areas
- Station elevation reversals
- Bank station corrections

All repairs preserve original and fixed data in audit trails and require professional engineering review.

---

## Blocked Obstructions Repair

### Problem Statement

Overlapping blocked obstructions in cross sections cause HEC-RAS computation failures with cryptic error messages. This occurs when:

1. Multiple blocked obstruction segments overlap on the station axis
2. Obstruction segments touch but have different elevations (creates discontinuity)
3. Data entry errors create physically impossible geometries

**Symptom**: HEC-RAS fails to run with errors like "blocked obstruction error" or silent failures during geometry preprocessing.

**Impact**: Model cannot be executed until geometry is manually corrected (tedious for 100+ cross sections).

### Solution: Elevation Envelope Algorithm

RasFixit implements an automated repair using the elevation envelope method:

1. **Parse**: Extract all blocked obstruction segments from cross section
2. **Merge**: Create elevation envelope using max elevation in overlap zones (hydraulically conservative)
3. **Gap Insertion**: Insert 0.02-unit gaps where segments touch but have different elevations
4. **Reformat**: Output to 8-character fixed-width FORTRAN format required by HEC-RAS

### Algorithm Details

#### Step 1: Parse Blocked Obstructions

**Input Format** (from .g## file):
```
#Blocked Obstruction
    100.0    50.0    200.0    50.0    300.0    60.0
```

**Parsing Rules**:
- Fixed-width format: 8 characters per value
- Station-elevation pairs: (station1, elev1, station2, elev2, ...)
- Continues until section terminator: `Bank Sta=`, `#XS Ineff=`, `#Mann=`, etc.

**Data Structure** (BlockedObstruction dataclass):
```python
@dataclass
class BlockedObstruction:
    station_start: float
    station_end: float
    elevation: float
```

#### Step 2: Create Elevation Envelope

**Overlap Detection**:
- Segment A overlaps Segment B if: `max(A.start, B.start) < min(A.end, B.end)`
- Create merged segments with maximum elevation in overlap zones

**Example**:
```
Original:
  Segment 1: Station 100-200, Elevation 50.0
  Segment 2: Station 150-250, Elevation 55.0

Merged:
  Segment 1: Station 100-150, Elevation 50.0
  Segment 2: Station 150-250, Elevation 55.0  (max elevation wins)
```

**Algorithm** (from obstructions.py):
```python
def create_elevation_envelope(obstructions):
    # Sort by station
    sorted_obs = sorted(obstructions, key=lambda x: x.station_start)

    # Merge overlaps using max elevation
    merged = []
    for obs in sorted_obs:
        if not merged or obs.station_start >= merged[-1].station_end:
            merged.append(obs)
        else:
            # Overlap detected - use max elevation
            if obs.elevation > merged[-1].elevation:
                merged[-1].elevation = obs.elevation
                merged[-1].station_end = max(merged[-1].station_end, obs.station_end)

    return merged
```

#### Step 3: Gap Insertion

**HEC-RAS Requirement**: Adjacent obstruction segments MUST be separated by at least 0.02 units.

**Gap Insertion Rules**:
- If two segments touch (Segment1.end == Segment2.start)
- AND have different elevations (Segment1.elev != Segment2.elev)
- INSERT 0.02-unit gap by shifting Segment2.start to Segment1.end + 0.02

**Critical Constant**:
```python
GAP_SIZE = 0.02  # DO NOT CHANGE - HEC-RAS requirement
```

**Example**:
```
Before:
  Segment 1: Station 100-200, Elevation 50.0
  Segment 2: Station 200-300, Elevation 55.0  (touching, different elevations)

After:
  Segment 1: Station 100-200.00, Elevation 50.0
  Segment 2: Station 200.02-300.00, Elevation 55.0  (0.02-unit gap)
```

#### Step 4: Fixed-Width Formatting

**HEC-RAS Format**: FORTRAN-style 8-character fixed-width fields

**Formatting Rules**:
- Each value: 8 characters, right-aligned, 2 decimal places
- 8 values per line maximum
- Overflow (>8 chars): Use asterisks `********`

**Critical Constant**:
```python
FIELD_WIDTH = 8  # DO NOT CHANGE - HEC-RAS requirement
```

**Example Output**:
```
#Blocked Obstruction
   100.00    50.00   200.00    50.00   200.02    55.00   300.00    55.00
```

### Safety Features

#### 1. Timestamped Backups

**Default Behavior** (`backup=True`):
- Create backup before ANY modification
- Backup filename: `{original}_{timestamp}.bak`
- Example: `geometry.g01_20240115_143022.bak`

**Disable** (use with caution):
```python
RasFixit.fix_blocked_obstructions("geometry.g01", backup=False)
```

#### 2. Before/After Visualization

**Optional Feature** (`visualize=True`):
- Generates PNG plots showing before/after geometry
- Highlights overlap zones and gaps
- Useful for engineering review and documentation

**Requirements**:
- matplotlib (optional dependency)
- Lazy-loaded only when `visualize=True`

**Example**:
```python
results = RasFixit.fix_blocked_obstructions(
    "geometry.g01",
    visualize=True  # Creates PNG files
)
# Output: geometry_g01_obstructions_before.png
#         geometry_g01_obstructions_after.png
```

#### 3. Audit Trail Preservation

**FixMessage Dataclass**:
- Stores original obstruction data
- Stores fixed obstruction data
- Includes fix action (REPAIRED, GAP_INSERTED, UNCHANGED)
- Enables traceability for professional review

**Example**:
```python
results = RasFixit.fix_blocked_obstructions("geometry.g01")

for msg in results.messages:
    print(f"XS: {msg.xs_id}")
    print(f"Action: {msg.action}")
    print(f"Original segments: {len(msg.original_data)}")
    print(f"Fixed segments: {len(msg.fixed_data)}")
```

### Usage Examples

#### Basic Repair

```python
from ras_commander import RasFixit

# Fix blocked obstructions with defaults (backup=True, visualize=False)
results = RasFixit.fix_blocked_obstructions("C:/Projects/MyModel/geometry.g01")

# Check results
print(f"Fixed {results.total_xs_fixed} cross sections")
print(f"Fixed {results.total_segments_fixed} obstruction segments")
```

#### Repair with Visualization

```python
from ras_commander import RasFixit

# Fix with before/after PNG generation
results = RasFixit.fix_blocked_obstructions(
    "C:/Projects/MyModel/geometry.g01",
    backup=True,
    visualize=True  # Requires matplotlib
)

# Review PNG files before accepting changes
# Files: geometry_g01_obstructions_before.png
#        geometry_g01_obstructions_after.png
```

#### Detection Only (Non-Destructive)

```python
from ras_commander import RasFixit

# Detect issues without modifying file
results = RasFixit.detect_obstruction_overlaps("C:/Projects/MyModel/geometry.g01")

if results.total_xs_fixed > 0:
    print(f"Found {results.total_xs_fixed} cross sections with overlapping obstructions")
    print("Run fix_blocked_obstructions() to repair")
else:
    print("No overlapping obstructions detected")
```

#### Batch Processing

```python
from ras_commander import RasFixit
from pathlib import Path

# Fix all geometry files in project
geom_files = Path("C:/Projects/MyModel").glob("*.g??")

for geom_file in geom_files:
    print(f"Processing {geom_file.name}...")
    results = RasFixit.fix_blocked_obstructions(
        str(geom_file),
        backup=True,
        visualize=True
    )

    if results.total_xs_fixed > 0:
        print(f"  Fixed {results.total_xs_fixed} cross sections")
        # Convert to DataFrame for analysis
        df = results.to_dataframe()
        df.to_csv(f"{geom_file.stem}_fix_report.csv", index=False)
```

### Return Values

**FixResults Dataclass**:
```python
@dataclass
class FixResults:
    total_xs_fixed: int          # Number of cross sections modified
    total_segments_fixed: int    # Number of obstruction segments repaired
    messages: List[FixMessage]   # Detailed fix messages

    def to_dataframe(self) -> pd.DataFrame:
        # Convert to pandas DataFrame for analysis
```

**FixMessage Dataclass**:
```python
@dataclass
class FixMessage:
    xs_id: str                      # Cross section identifier
    action: FixAction               # REPAIRED, GAP_INSERTED, UNCHANGED
    original_data: List[BlockedObstruction]  # Before fix
    fixed_data: List[BlockedObstruction]     # After fix
    message: str                    # Human-readable description
```

**FixAction Enum**:
```python
class FixAction(Enum):
    REPAIRED = "repaired"           # Overlaps merged
    GAP_INSERTED = "gap_inserted"   # 0.02-unit gaps added
    UNCHANGED = "unchanged"         # No issues detected
```

### Integration with RasCheck

**Workflow**: Check → Fix → Verify

```python
from ras_commander.check import RasCheck
from ras_commander.fixit import RasFixit

# Step 1: Check for obstruction issues
print("Step 1: Checking for obstruction issues...")
check_results = RasCheck.structure_check("C:/Projects/MyModel")

# Step 2: Fix if issues found
if check_results.has_obstruction_issues():
    print("Step 2: Fixing blocked obstructions...")
    fix_results = RasFixit.fix_blocked_obstructions(
        "C:/Projects/MyModel/geometry.g01",
        backup=True,
        visualize=True
    )

    print(f"Fixed {fix_results.total_xs_fixed} cross sections")

    # Step 3: Verify fixes
    print("Step 3: Verifying fixes...")
    verify_results = RasCheck.structure_check("C:/Projects/MyModel")

    if not verify_results.has_obstruction_issues():
        print("Success! All obstruction issues resolved.")
    else:
        print("Warning: Some issues remain. Manual review required.")
else:
    print("No obstruction issues detected.")
```

### Performance

**Speed**:
- Typical geometry file: 2-5 seconds
- Large file (10,000+ cross sections): 10-15 seconds

**Memory**:
- Low footprint (in-place file modifications)
- Reads/writes file sequentially
- Suitable for large models

**Visualization**:
- PNG generation adds 5-10 seconds
- Lazy-loaded matplotlib (no overhead if `visualize=False`)

### Common Issues and Solutions

#### Issue 1: Asterisks in Output (`********`)

**Cause**: Value exceeds 8-character field width (e.g., station 12345678.90)

**Solution**: This is correct HEC-RAS behavior for overflow values. HEC-RAS can read these correctly.

**Prevention**: Use shorter station values when possible.

#### Issue 2: Fix Creates New Gaps

**Cause**: 0.02-unit gap insertion is intentional and required by HEC-RAS

**Solution**: This is correct behavior. Gaps prevent computation errors.

**Verification**: Open geometry in HEC-RAS GUI to confirm gaps are acceptable.

#### Issue 3: Max Elevation Not Always Conservative

**Cause**: In some cases, lower elevation may be more conservative hydraulically

**Solution**: Algorithm uses max elevation (standard practice). Review results in HEC-RAS GUI.

**Override**: Manually edit geometry if specific hydraulics require different approach.

### Professional Review Requirements

**RasFixit automates tedious repairs but does NOT replace engineering judgment.**

All fixed geometry MUST be reviewed by a licensed professional engineer before production use:

1. **Open in HEC-RAS GUI**:
   - Verify cross section plots look reasonable
   - Check 3D visualization for geometry issues
   - Run geometry preprocessor to confirm no errors

2. **Review Visualizations**:
   - Examine before/after PNG files
   - Verify gaps are appropriate
   - Check max elevation approach is conservative

3. **Audit Trail Documentation**:
   - Export `FixResults.to_dataframe()` to CSV
   - Include in model documentation
   - Document professional review in engineering report

4. **Test Run**:
   - Run HEC-RAS with fixed geometry
   - Verify computational stability
   - Compare results to baseline (if available)

5. **Engineering Judgment**:
   - Assess hydraulic reasonableness of fixes
   - Verify conservative approach is appropriate for project
   - Document any manual overrides in model report

### Engineering Report Documentation

**Recommended Documentation** (include in model report):

```markdown
## Geometry Repair (Blocked Obstructions)

**Tool**: ras-commander RasFixit v0.XX.X
**Date**: [Repair date]
**Engineer**: [Your name, PE license number]

**Issues Identified**:
- [Number] cross sections with overlapping blocked obstructions
- Identified via RasCheck structure validation

**Repair Method**:
- Elevation envelope algorithm (max elevation in overlap zones)
- 0.02-unit gaps inserted per HEC-RAS requirements
- Hydraulically conservative approach (maximum obstruction elevations)

**Verification**:
- Timestamped backup created: [filename]
- Before/after visualizations reviewed
- Geometry opened in HEC-RAS GUI and verified
- Test run completed successfully
- Results compared to baseline [if applicable]

**Engineering Review**:
[Your assessment of the fixes, any manual overrides, and professional judgment]

**Conclusion**:
Repaired geometry is hydraulically reasonable and suitable for [project purpose].
```

---

## Future Repair Types (Not Yet Implemented)

### Ineffective Flow Areas

**Planned Capability**: Automatic correction of ineffective flow area placement errors.

**Issues to Detect**:
- Ineffective areas with elevations below channel invert
- Ineffective areas extending beyond cross section bounds
- Overlapping ineffective flow areas

**Repair Algorithm**:
- Clip ineffective areas to cross section bounds
- Adjust elevations to reasonable values
- Merge overlapping areas

### Station Elevation Reversals

**Planned Capability**: Automatic correction of station-elevation data entry errors.

**Issues to Detect**:
- Station values that decrease from left to right (should always increase)
- Elevation reversals that create non-monotonic profiles

**Repair Algorithm**:
- Sort station-elevation pairs by station
- Smooth elevation transitions
- Flag for manual review if corrections are significant

### Bank Station Corrections

**Planned Capability**: Automatic adjustment of bank station placement.

**Issues to Detect**:
- Bank stations outside cross section bounds
- Left bank > right bank (reversed)
- Bank stations not bracketing main channel

**Repair Algorithm**:
- Adjust bank stations to reasonable positions
- Ensure left < right ordering
- Verify channel bracketing

---

## Testing

### Test Data

**HCFCD M3 Model A100-00-00** (included in ras-commander):
- Location: `examples/example_projects/HCFCD_M3_A100-00-00/`
- Issues: 104 cross sections with overlapping obstructions
- File: `A100_00_00.g04`
- Use case: Real-world model with complex obstruction issues

### Example Test

```python
from ras_commander import RasFixit, RasExamples

# Extract test project
project_path = RasExamples.extract_project("HCFCD M3 A100-00-00")

# Locate geometry file
import os
geom_file = os.path.join(project_path, "A100_00_00.g04")

# Test detection
print("Testing detection...")
detection_results = RasFixit.detect_obstruction_overlaps(geom_file)
print(f"Found {detection_results.total_xs_fixed} cross sections with issues")

# Test fix (on copy)
import shutil
test_file = geom_file.replace(".g04", "_test.g04")
shutil.copy(geom_file, test_file)

print("Testing fix...")
fix_results = RasFixit.fix_blocked_obstructions(test_file, visualize=True)
print(f"Fixed {fix_results.total_xs_fixed} cross sections")
print(f"Fixed {fix_results.total_segments_fixed} segments")

# Verify no issues remain
verify_results = RasFixit.detect_obstruction_overlaps(test_file)
assert verify_results.total_xs_fixed == 0, "Issues remain after fix"

print("Test passed!")
```

---

## See Also

- **RasCheck Integration**: [checks.md](checks.md) - Obstruction detection workflow
- **RasFixit Implementation**: `ras_commander/fixit/AGENTS.md` - Developer guidance
- **Example Notebook**: `examples/27_fixit_blocked_obstructions.ipynb` - Complete workflow
- **Algorithm Source**: `ras_commander/fixit/obstructions.py` - Elevation envelope implementation
