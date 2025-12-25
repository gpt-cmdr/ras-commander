# RasCheck - Quality Assurance Module

This subpackage provides automated quality assurance checks for HEC-RAS models following FEMA and USACE modeling standards.

## Purpose

RasCheck implements comprehensive validation checks to identify common modeling issues before submission or peer review. It helps ensure models meet professional standards for hydraulic & hydrologic analysis.

**Supports Both Steady and Unsteady Flow**: RasCheck auto-detects the flow type from the plan HDF file and runs appropriate validation checks.

## Module Organization

The check subpackage contains 5 modules organized by function:

### RasCheck.py (Main Module)

**RasCheck** - Primary quality assurance interface (448 KB):

**NT Check** (Manning's n values):
- `nt_check()` - Validate Manning's n values against land cover standards
- Checks for:
  - Out-of-range Manning's n values
  - Inconsistent roughness across reaches
  - Bank vs channel roughness ratios
  - Subdivision method appropriateness

**XS Check** (Cross Section Validation):
- `xs_check()` - Cross section spacing, station ordering, and geometry
- Checks for:
  - Excessive cross section spacing (>1000 ft warning, >2000 ft error)
  - Station elevation monotonicity (no reversals)
  - Ineffective flow areas (proper placement and elevation)
  - Bank station placement
  - Expansion/contraction coefficients

**Structure Check** (Bridges and Culverts):
- `structure_check()` - Bridge and culvert geometry validation
- Checks for:
  - Low chord elevations vs cross section geometry
  - Pier spacing and alignment
  - Culvert slope vs channel slope
  - Deck width sufficiency
  - Approach section compatibility

**Floodway Check** (Floodway Encroachment):
- `floodway_check()` - Validate floodway analysis results
- Checks for:
  - Surcharge limits (typically 1.0 ft max)
  - Conveyance reduction validation
  - Equal conveyance method compliance
  - Base flood elevation consistency

**Profiles Check** (Profile Validation):
- `profiles_check()` - Water surface profile validation
- Checks for:
  - Critical depth transitions
  - Hydraulic jumps
  - Profile convergence
  - Extreme velocity warnings
  - Energy slope reasonableness

**Run All Checks**:
- `run_all()` - Execute complete validation suite (auto-detects steady vs unsteady)
- Returns comprehensive report with all findings

**Unsteady Flow Checks**:
- `check_unsteady_mass_balance()` - Volume conservation validation
  - Volume error percentage against thresholds (1% warning, 5% error default)
  - Inflow/outflow balance verification
  - Storage change validation
- `check_unsteady_computation()` - HEC-RAS warning/error analysis
  - Parses computation messages for warnings and errors
  - Detects convergence issues
  - Runtime performance metrics
- `check_unsteady_peaks()` - Peak value validation for 1D results
  - Maximum velocity thresholds (15 ft/s warning, 25 ft/s error)
  - Maximum WSE validation
  - Time series peak analysis
- `check_unsteady_stability()` - 2D stability and convergence (when 2D present)
  - Maximum iteration counts (20 warning, 40 error default)
  - Average iteration analysis (solver stress)
  - Water surface error validation
- `check_mesh_quality()` - 2D mesh quality (when 2D present)
  - Cell area validation (100-50,000 sq ft default range)
  - Aspect ratio checks (max 10:1 default)
  - Face velocity analysis

**Flow Type Detection**:
- Auto-detects steady vs unsteady from HDF file structure
- Returns `FlowType.STEADY`, `FlowType.UNSTEADY`, or `FlowType.GEOMETRY_ONLY`
- Geometry-only checks (NT) work for all flow types

### messages.py (Validation Messages)

**CheckMessage** - Standardized validation messages (106 KB):

**Message Categories**:
- `ERROR` - Critical issues that must be fixed
- `WARNING` - Issues requiring review/justification
- `INFO` - Informational notes
- `PASS` - Validation passed

**Message Templates**:
- Standardized text for each check type
- Consistent severity classification
- References to modeling standards (FEMA, USACE)
- Suggested remediation actions

**Functions**:
- `get_message_template()` - Retrieve message template by code
- `format_message()` - Format message with context-specific details
- `categorize_severity()` - Assign severity level based on threshold exceedance

### report.py (Report Generation)

**RasCheckReport** - Compilation and output formatting (23 KB):

**Report Types**:
- `generate_summary_report()` - Executive summary with counts by severity
- `generate_detailed_report()` - Complete findings with locations and values
- `generate_csv_report()` - Tabular output for further analysis
- `generate_html_report()` - Interactive HTML report with filtering

**Report Sections**:
1. Model metadata (project name, HEC-RAS version, check date)
2. Summary statistics (pass/warn/error counts by check type)
3. Detailed findings (sorted by severity, then check type)
4. Recommendations and next steps

**Output Formats**:
- Plain text (.txt)
- CSV (.csv)
- HTML (.html)
- JSON (.json) - for programmatic processing

### thresholds.py (Configurable Thresholds)

**CheckThresholds** - Quality assurance threshold configuration (18 KB):

**Threshold Categories**:

**Manning's n Ranges**:
- Channel types: natural (0.025-0.15), lined (0.012-0.025), vegetated (0.05-0.20)
- Overbank types: forest (0.10-0.20), agricultural (0.03-0.08), urban (0.015-0.05)

**Cross Section Spacing**:
- Warning: > 1000 ft
- Error: > 2000 ft
- Contraction/expansion: < 200 ft recommended

**Velocity Limits**:
- Warning: > 15 ft/s (channel)
- Error: > 25 ft/s (erosion concern)
- Low velocity warning: < 0.5 ft/s (sedimentation)

**Floodway Surcharge**:
- FEMA standard: 1.0 ft maximum
- USACE standard: 0.5 ft maximum (more conservative)
- Custom thresholds supported

**Functions**:
- `get_default_thresholds()` - Load FEMA/USACE standard thresholds
- `set_custom_thresholds()` - Override defaults for project-specific standards
- `validate_thresholds()` - Ensure threshold values are reasonable

### __init__.py (Package Interface)

**Public API**:
```python
from ras_commander.check import RasCheck

# Convenience imports
from ras_commander.check import (
    RasCheck,
    RasCheckReport,
    CheckThresholds,
    CheckMessage
)
```

## Usage Patterns

### Run All Checks (Auto-Detects Flow Type)

Complete validation suite with auto-detection:
```python
from ras_commander.check import RasCheck, FlowType

# Auto-detects steady or unsteady flow
results = RasCheck.run_all("01")

# Check what flow type was detected
print(f"Flow type: {results.flow_type}")  # FlowType.STEADY or FlowType.UNSTEADY

# Get error count
print(f"Errors: {results.get_error_count()}")

# Generate HTML report
results.to_html("validation_report.html")
```

### Steady Flow Example

For steady flow plans with multiple profiles:
```python
from ras_commander.check import RasCheck

# Run with specific profiles and floodway
results = RasCheck.run_all("01",
    profiles=['10yr', '50yr', '100yr', 'Floodway'],
    floodway_profile='Floodway',
    surcharge=1.0
)

# Flow type will be FlowType.STEADY
print(results.flow_type)
```

### Unsteady Flow Example

For unsteady flow plans (1D or 2D):
```python
from ras_commander.check import RasCheck

# Auto-detects unsteady, runs appropriate checks
results = RasCheck.run_all("01")

# Check results
print(f"Flow type: {results.flow_type}")  # FlowType.UNSTEADY

# Review mass balance
if results.mass_balance_summary is not None:
    print(results.mass_balance_summary)

# Review peaks
if results.peaks_summary is not None:
    print(results.peaks_summary[['cross_section', 'max_velocity', 'max_wse']])

# Check for 2D stability issues
if results.stability_summary is not None:
    print(results.stability_summary)
```

### Run Specific Check

Individual check execution:
```python
# NT Check only (works for both steady and unsteady)
from ras_commander import init_ras_project
init_ras_project("C:/Projects/MyModel", "6.6")
nt_results = RasCheck.check_nt(geom_hdf)

# Unsteady-specific checks
mass_balance = RasCheck.check_unsteady_mass_balance("01")
peaks = RasCheck.check_unsteady_peaks("01", geom_hdf)
stability = RasCheck.check_unsteady_stability("01")  # 2D only
mesh = RasCheck.check_mesh_quality("01", geom_hdf)    # 2D only
```

### Custom Thresholds

Override default standards:
```python
from ras_commander.check import RasCheck, CheckThresholds

# Set custom thresholds
thresholds = CheckThresholds()
thresholds.set_custom_thresholds({
    'max_xs_spacing_warn': 800,  # More conservative than default 1000 ft
    'max_floodway_surcharge': 0.5,  # USACE standard
    'max_velocity_warn': 12  # Lower threshold for erosive soils
})

# Run with custom thresholds
results = RasCheck.run_all_checks(
    "C:/Projects/MyModel",
    thresholds=thresholds
)
```

### Report Generation

Multiple output formats:
```python
from ras_commander.check import RasCheckReport

# Generate reports
RasCheckReport.generate_summary_report(results, "summary.txt")
RasCheckReport.generate_detailed_report(results, "detailed.txt")
RasCheckReport.generate_html_report(results, "report.html")
RasCheckReport.generate_csv_report(results, "findings.csv")
```

## Integration with RasFixit

The check subpackage identifies issues; the fixit subpackage repairs them:

**Workflow**:
1. **Check**: Identify issues with `RasCheck.run_all_checks()`
2. **Fix**: Repair issues with `RasFixit.fix_blocked_obstructions()`, etc.
3. **Verify**: Re-run checks to confirm fixes

**Example**:
```python
from ras_commander.check import RasCheck
from ras_commander.fixit import RasFixit

# 1. Check for issues
results = RasCheck.structure_check("C:/Projects/MyModel")

# 2. Fix blocked obstructions (if found)
if results.has_obstruction_issues():
    fix_results = RasFixit.fix_blocked_obstructions("C:/Projects/MyModel")

# 3. Verify fixes
final_results = RasCheck.structure_check("C:/Projects/MyModel")
```

## FEMA/USACE Standards

RasCheck implements validation criteria from:

**FEMA Standards**:
- FEMA Guidance Document 72 (Floodway Analysis)
- FEMA Base Level Engineering (BLE) specifications
- National Flood Insurance Program (NFIP) standards

**USACE Standards**:
- HEC-RAS Hydraulic Reference Manual
- EM 1110-2-1416 (River Hydraulics)
- EM 1110-2-1601 (Hydraulic Design)

**Customization**:
Users can override defaults to match local standards or project-specific requirements.

## Key Features

### Multi-Level Verifiability
- **HEC-RAS Projects**: Models remain openable in HEC-RAS GUI for traditional review
- **Visual Outputs**: RasCheck can generate plots highlighting flagged locations
- **Code Audit Trails**: All checks use @log_call decorators for execution tracking

### Comprehensive Coverage
- Manning's n validation (land cover standards)
- Cross section geometry (spacing, stations, ineffective areas)
- Structure validation (bridges, culverts)
- Floodway compliance (surcharge limits)
- Profile validation (critical depth, hydraulic jumps)

### Flexible Reporting
- Multiple output formats (text, CSV, HTML, JSON)
- Severity classification (error, warning, info, pass)
- Filterable and sortable findings
- Automated remediation suggestions

## Return Values

All check functions return a `CheckResults` object with:

**Attributes**:
- `errors` - List of critical issues (must fix)
- `warnings` - List of issues requiring review
- `info` - Informational notes
- `passed` - List of checks that passed

**Methods**:
- `has_errors()` - Boolean indicating critical issues
- `has_warnings()` - Boolean indicating warnings
- `summary()` - Text summary with counts
- `to_dict()` - Dictionary representation for JSON export

## Performance

RasCheck reads HEC-RAS geometry and plan files directly (plain text parsing):

**Speed**:
- Typical 1D model: 5-15 seconds
- Large 2D model: 30-60 seconds
- Parallel checking supported for multiple plans

**Memory**:
- Low memory footprint (processes files sequentially)
- Suitable for large models (10,000+ cross sections)

## Example Notebooks

Complete workflow demonstrations:

- `examples/300_quality_assurance_rascheck.ipynb` - Complete RasCheck workflow
- Integration with RasFixit shown in `examples/200_fixit_blocked_obstructions.ipynb`

## Common Checks Explained

### NT Check (Manning's n)
Validates roughness coefficients against land cover standards. Catches:
- Manning's n = 0 (uninitialized)
- Extreme values (n > 0.20 for most cases)
- Channel vs overbank inconsistencies

### XS Check (Cross Sections)
Validates cross section geometry and placement. Catches:
- Excessive spacing (> 1000 ft warning, > 2000 ft error)
- Station elevation reversals (data entry errors)
- Bank station placement errors
- Ineffective flow area issues

### Structure Check (Bridges/Culverts)
Validates structure geometry compatibility with channel. Catches:
- Low chord below channel invert (physical impossibility)
- Pier spacing issues
- Approach section incompatibility
- Culvert slope mismatches

### Floodway Check
Validates floodway analysis results against FEMA/USACE standards. Catches:
- Excessive surcharge (> 1.0 ft FEMA, > 0.5 ft USACE)
- Conveyance reduction violations
- Base flood elevation inconsistencies

### Profiles Check
Validates water surface profiles for hydraulic reasonableness. Catches:
- Critical depth transitions (may indicate poor geometry)
- Hydraulic jumps (may indicate subcritical/supercritical transition issues)
- Extreme velocities (erosion or sedimentation concerns)
- Profile convergence failures

## See Also

- Parent library context: `ras_commander/CLAUDE.md`
- Automated repairs: `ras_commander/fixit/AGENTS.md`
- Geometry parsing: `ras_commander/geom/AGENTS.md`
- Testing approach: `.claude/rules/testing/tdd-approach.md`
