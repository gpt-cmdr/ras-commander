# RasCheck Validation Types Reference

Complete documentation for all 5 RasCheck validation types with FEMA/USACE standards, thresholds, and example usage.

## Overview

RasCheck provides 5 comprehensive validation types covering all major HEC-RAS model components:

1. **NT Check** - Manning's n roughness validation
2. **XS Check** - Cross section geometry and spacing
3. **Structure Check** - Bridge and culvert validation
4. **Floodway Check** - Floodway encroachment analysis
5. **Profiles Check** - Water surface profile validation

All checks return standardized `CheckResults` objects with severity classifications (ERROR, WARNING, INFO, PASS).

---

## 1. NT Check (Manning's n Validation)

### Purpose

Validates Manning's n roughness coefficients against established land cover standards to ensure hydraulically reasonable roughness values.

### What It Detects

**Critical Errors**:
- Manning's n = 0 (uninitialized values)
- Manning's n > 0.20 (unreasonably high for most cases)
- Manning's n < 0.010 (unreasonably low, even for concrete)

**Warnings**:
- Channel roughness exceeds typical range for land cover type
- Overbank roughness inconsistent with land cover description
- Bank vs channel roughness ratio outside reasonable bounds (2:1 to 5:1 typical)
- Subdivision method inappropriate for roughness variation

**Informational**:
- Roughness values at boundary of acceptable range
- Recommended verification for unusual values

### FEMA/USACE Standards

**Channel Types** (USACE EM 1110-2-1416):
- Natural streams (clean): 0.025-0.035
- Natural streams (with vegetation): 0.035-0.050
- Natural streams (heavy brush): 0.050-0.150
- Concrete-lined channels: 0.012-0.018
- Grass-lined channels: 0.020-0.030

**Overbank Types**:
- Forest/heavy brush: 0.10-0.20
- Agricultural crops: 0.03-0.08
- Short grass/pasture: 0.025-0.035
- Urban/residential: 0.015-0.05
- Paved surfaces: 0.012-0.020

**Bank vs Channel Ratios**:
- Typical range: 2:1 to 5:1 (overbank rougher than channel)
- Warning if ratio < 1.5:1 or > 10:1

### Thresholds (Configurable)

```python
# Default thresholds (from CheckThresholds)
{
    'min_mannings_n': 0.010,  # Error below this
    'max_mannings_n_channel': 0.150,  # Warning above this for channels
    'max_mannings_n_overbank': 0.200,  # Warning above this for overbanks
    'min_bank_ratio': 1.5,  # Warning if overbank/channel < this
    'max_bank_ratio': 10.0  # Warning if overbank/channel > this
}
```

### Example Usage

```python
from ras_commander.check import RasCheck

# Run NT check with default thresholds
results = RasCheck.nt_check("C:/Projects/MyModel")

# Check for errors
if results.has_errors():
    print("Critical Manning's n errors found:")
    for error in results.errors:
        print(f"  {error}")

# Custom thresholds for specific project
from ras_commander.check import CheckThresholds
thresholds = CheckThresholds()
thresholds.set_custom_thresholds({
    'max_mannings_n_channel': 0.100,  # More conservative
    'max_bank_ratio': 8.0  # Tighter ratio bounds
})

results = RasCheck.nt_check("C:/Projects/MyModel", thresholds=thresholds)
```

---

## 2. XS Check (Cross Section Validation)

### Purpose

Validates cross section geometry, spacing, and placement to ensure model stability and accuracy.

### What It Detects

**Critical Errors**:
- Excessive cross section spacing (>2000 ft)
- Station elevation reversals (data entry errors)
- Bank stations outside cross section bounds
- Ineffective flow areas with elevations below channel invert

**Warnings**:
- Cross section spacing >1000 ft
- Spacing <200 ft at contractions/expansions (need closer spacing)
- Bank station placement questionable
- Ineffective flow area elevations questionable
- Expansion/contraction coefficients outside typical range

**Informational**:
- Cross section spacing near threshold
- Bank station recommendations
- Ineffective area placement suggestions

### FEMA/USACE Standards

**Cross Section Spacing** (HEC-RAS Reference Manual):
- General rule: At least 4 cross sections per river mile
- Maximum spacing: 1000 ft for 1D models (warning threshold)
- Absolute maximum: 2000 ft (error threshold)
- At contractions/expansions: <200 ft spacing

**Bank Station Requirements**:
- Must bracket main channel
- Must be within cross section bounds
- Left bank station < right bank station

**Expansion/Contraction Coefficients** (HEC-RAS defaults):
- Expansion: 0.3-0.8 typical (0.5 default)
- Contraction: 0.1-0.3 typical (0.3 default)
- Warning if outside these ranges

**Ineffective Flow Areas**:
- Must have elevations > channel invert
- Should represent areas of low/no conveyance
- Placement consistent with topography

### Thresholds (Configurable)

```python
# Default thresholds
{
    'max_xs_spacing_warn': 1000,  # Warning threshold (ft)
    'max_xs_spacing_error': 2000,  # Error threshold (ft)
    'min_xs_spacing_contraction': 200,  # Minimum at contractions (ft)
    'expansion_coef_min': 0.3,  # Minimum expansion coefficient
    'expansion_coef_max': 0.8,  # Maximum expansion coefficient
    'contraction_coef_min': 0.1,  # Minimum contraction coefficient
    'contraction_coef_max': 0.3   # Maximum contraction coefficient
}
```

### Example Usage

```python
from ras_commander.check import RasCheck

# Run XS check
results = RasCheck.xs_check("C:/Projects/MyModel")

# Generate detailed report for review
from ras_commander.check import RasCheckReport
RasCheckReport.generate_detailed_report(results, "xs_check_report.txt")

# More conservative spacing for USACE project
thresholds = CheckThresholds()
thresholds.set_custom_thresholds({
    'max_xs_spacing_warn': 800,  # 800 ft warning
    'max_xs_spacing_error': 1500  # 1500 ft error
})
results = RasCheck.xs_check("C:/Projects/MyModel", thresholds=thresholds)
```

---

## 3. Structure Check (Bridge/Culvert Validation)

### Purpose

Validates bridge and culvert geometry for physical reasonableness and compatibility with channel geometry.

### What It Detects

**Critical Errors**:
- Low chord elevation below channel invert (physical impossibility)
- Culvert invert below channel invert
- Pier spacing creating unrealistic obstructions
- Deck width insufficient for bridge opening

**Warnings**:
- Low chord clearance < 2 ft above 100-year WSE (FEMA requirement)
- Approach sections > 1 channel width from structure
- Culvert slope significantly different from channel slope
- Pier alignment issues
- Bridge opening < 80% of channel width

**Informational**:
- Approach section placement recommendations
- Pier spacing suggestions
- Culvert sizing notes

### FEMA/USACE Standards

**Bridge Requirements** (FEMA):
- Low chord > 100-year WSE + 2 ft freeboard (minimum)
- Approach sections: 1 channel width upstream/downstream
- Bridge opening: >80% of channel width typical
- Deck width: Consistent with approach roadway

**Culvert Requirements** (USACE):
- Culvert slope ≈ channel slope (±20% typical)
- Invert elevation ≥ channel invert
- Inlet/outlet conditions appropriate
- Headwater/tailwater adequate

**Pier Placement**:
- Spacing: Typically >10 ft for maintenance access
- Alignment: Perpendicular to flow direction
- Scour protection: Required for most piers

### Thresholds (Configurable)

```python
# Default thresholds
{
    'min_low_chord_clearance': 2.0,  # Freeboard requirement (ft)
    'max_approach_distance_ratio': 1.0,  # Ratio to channel width
    'max_culvert_slope_deviation': 0.20,  # 20% deviation from channel
    'min_bridge_opening_ratio': 0.80,  # 80% of channel width
    'min_pier_spacing': 10.0  # Minimum pier spacing (ft)
}
```

### Example Usage

```python
from ras_commander.check import RasCheck

# Run structure check
results = RasCheck.structure_check("C:/Projects/MyModel")

# Focus on errors only
if results.has_errors():
    print("Critical structure errors requiring immediate attention:")
    for error in results.errors:
        print(f"  {error}")

# Generate HTML report for review meeting
from ras_commander.check import RasCheckReport
RasCheckReport.generate_html_report(results, "structure_report.html")
```

---

## 4. Floodway Check (Floodway Encroachment)

### Purpose

Validates floodway analysis results against FEMA and USACE regulatory standards for floodway encroachment.

### What It Detects

**Critical Errors**:
- Surcharge > regulatory limit (1.0 ft FEMA, 0.5 ft USACE)
- Conveyance reduction > allowable limit
- Base flood elevation inconsistencies
- Equal conveyance method violations

**Warnings**:
- Surcharge approaching regulatory limit (>80% of limit)
- Conveyance reduction approaching limit
- Floodway width variations
- Natural valley encroachment issues

**Informational**:
- Surcharge summary statistics
- Conveyance reduction summary
- Floodway width recommendations

### FEMA/USACE Standards

**FEMA Floodway Standards** (44 CFR 65.11):
- Maximum surcharge: 1.0 ft above base flood elevation
- Method: Equal conveyance reduction or detailed method
- Minimum conveyance: Sufficient to carry base flood without increasing WSE >1.0 ft

**USACE Floodway Standards** (EM 1110-2-1416):
- Maximum surcharge: 0.5 ft (more conservative than FEMA)
- Conveyance reduction: Typically 10-50% depending on method
- Natural valley line: Should follow terrain

**Encroachment Method**:
- Equal conveyance: Most common, reduces left/right overbank equally
- Detailed method: Engineering analysis with justification
- Natural valley: Follows topographic low points

### Thresholds (Configurable)

```python
# Default thresholds (FEMA)
{
    'max_floodway_surcharge': 1.0,  # FEMA standard (ft)
    'surcharge_warning_ratio': 0.8,  # Warn at 80% of limit
    'max_conveyance_reduction': 0.50  # 50% maximum reduction
}

# USACE thresholds (more conservative)
{
    'max_floodway_surcharge': 0.5,  # USACE standard (ft)
    'surcharge_warning_ratio': 0.8,
    'max_conveyance_reduction': 0.40  # 40% maximum reduction
}
```

### Example Usage

```python
from ras_commander.check import RasCheck, CheckThresholds

# FEMA project (1.0 ft surcharge limit)
results = RasCheck.floodway_check("C:/Projects/FemaModel")

# USACE project (0.5 ft surcharge limit)
usace_thresholds = CheckThresholds()
usace_thresholds.set_custom_thresholds({
    'max_floodway_surcharge': 0.5
})
results = RasCheck.floodway_check("C:/Projects/UsaceModel", thresholds=usace_thresholds)

# Generate report for regulatory submission
from ras_commander.check import RasCheckReport
RasCheckReport.generate_html_report(results, "floodway_compliance_report.html")
```

---

## 5. Profiles Check (Water Surface Profile Validation)

### Purpose

Validates water surface profiles for hydraulic reasonableness and computational stability.

### What It Detects

**Critical Errors**:
- Profile convergence failures
- Extreme velocities (>25 ft/s)
- Negative energy slopes
- Critical depth at boundaries (indicates computation issues)

**Warnings**:
- High velocities (>15 ft/s, erosion concern)
- Low velocities (<0.5 ft/s, sedimentation concern)
- Critical depth transitions (may indicate geometry issues)
- Hydraulic jumps (subcritical/supercritical transitions)
- Energy slope discontinuities

**Informational**:
- Profile statistics summary
- Velocity distribution notes
- Froude number summaries
- Mixed flow regime notifications

### FEMA/USACE Standards

**Velocity Limits** (USACE EM 1110-2-1601):
- Typical maximum: 15 ft/s (erosion threshold for most channels)
- Absolute maximum: 25 ft/s (extreme erosion, structural damage)
- Low velocity threshold: 0.5 ft/s (sedimentation concern)

**Profile Convergence** (HEC-RAS):
- Convergence tolerance: 0.01 ft default
- Maximum iterations: 20 typical
- Failure indicates geometry or boundary condition issues

**Critical Depth Transitions**:
- Flag for review (may indicate poor geometry)
- Verify appropriate regime (subcritical vs supercritical)
- Check for hydraulic structures forcing critical flow

**Hydraulic Jumps**:
- Verify physical reasonableness
- Check for appropriate modeling method
- Consider 2D modeling if jumps are problematic

### Thresholds (Configurable)

```python
# Default thresholds
{
    'max_velocity_warn': 15.0,  # Warning threshold (ft/s)
    'max_velocity_error': 25.0,  # Error threshold (ft/s)
    'min_velocity_warn': 0.5,  # Low velocity warning (ft/s)
    'max_froude_number': 1.2,  # Supercritical flow warning
    'energy_slope_tolerance': 0.001  # Energy slope discontinuity
}
```

### Example Usage

```python
from ras_commander.check import RasCheck

# Run profile check
results = RasCheck.profiles_check("C:/Projects/MyModel")

# Check for velocity issues specifically
velocity_errors = [e for e in results.errors if 'velocity' in e.lower()]
if velocity_errors:
    print("Velocity issues requiring attention:")
    for error in velocity_errors:
        print(f"  {error}")

# More conservative for erosive soils
thresholds = CheckThresholds()
thresholds.set_custom_thresholds({
    'max_velocity_warn': 12.0,  # Lower threshold
    'max_velocity_error': 20.0
})
results = RasCheck.profiles_check("C:/Projects/MyModel", thresholds=thresholds)
```

---

## Running All Checks

### Complete Validation Suite

Execute all 5 check types in a single operation:

```python
from ras_commander.check import RasCheck

# Run all checks with default FEMA thresholds
results = RasCheck.run_all_checks("C:/Projects/MyModel")

# Check overall status
if results.has_errors():
    print(f"Found {len(results.errors)} critical errors")
if results.has_warnings():
    print(f"Found {len(results.warnings)} warnings requiring review")

# Generate comprehensive report
from ras_commander.check import RasCheckReport
RasCheckReport.generate_html_report(results, "complete_qa_report.html")
```

### Custom Thresholds for All Checks

```python
from ras_commander.check import RasCheck, CheckThresholds

# Create custom thresholds for USACE project
thresholds = CheckThresholds()
thresholds.set_custom_thresholds({
    # XS Check
    'max_xs_spacing_warn': 800,
    # Structure Check
    'min_low_chord_clearance': 3.0,  # 3 ft freeboard
    # Floodway Check
    'max_floodway_surcharge': 0.5,  # USACE standard
    # Profiles Check
    'max_velocity_warn': 12.0
})

# Run all checks with custom thresholds
results = RasCheck.run_all_checks("C:/Projects/UsaceModel", thresholds=thresholds)
```

---

## Common Workflows

### Pre-Submission QA

```python
from ras_commander.check import RasCheck, RasCheckReport

# 1. Run all checks
results = RasCheck.run_all_checks("C:/Projects/SubmittalModel")

# 2. Generate reports for different audiences
RasCheckReport.generate_summary_report(results, "executive_summary.txt")
RasCheckReport.generate_detailed_report(results, "detailed_findings.txt")
RasCheckReport.generate_html_report(results, "qa_report.html")

# 3. Export to CSV for tracking
RasCheckReport.generate_csv_report(results, "findings_tracker.csv")
```

### Iterative Model Development

```python
from ras_commander.check import RasCheck

# Check after each major model modification
results_v1 = RasCheck.run_all_checks("C:/Projects/Model_v1")
results_v2 = RasCheck.run_all_checks("C:/Projects/Model_v2")

# Compare error counts
print(f"Version 1: {len(results_v1.errors)} errors")
print(f"Version 2: {len(results_v2.errors)} errors")
print(f"Improvement: {len(results_v1.errors) - len(results_v2.errors)} errors fixed")
```

### Integration with RasFixit

```python
from ras_commander.check import RasCheck
from ras_commander.fixit import RasFixit

# 1. Check for obstruction issues
check_results = RasCheck.structure_check("C:/Projects/MyModel")

# 2. Fix if issues found
if check_results.has_obstruction_issues():
    fix_results = RasFixit.fix_blocked_obstructions(
        "C:/Projects/MyModel/geometry.g01",
        visualize=True
    )

# 3. Verify fixes
verify_results = RasCheck.structure_check("C:/Projects/MyModel")
assert not verify_results.has_obstruction_issues()
```
