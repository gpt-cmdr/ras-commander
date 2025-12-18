# RasCheck - Quality Assurance Module

This subpackage provides automated quality assurance checks for HEC-RAS models following FEMA and USACE modeling standards.

## Purpose

RasCheck implements comprehensive validation checks to identify common modeling issues before submission or peer review. It helps ensure models meet professional standards for hydraulic & hydrologic analysis.

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
- `run_all_checks()` - Execute complete validation suite
- Returns comprehensive report with all findings

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

### Run All Checks

Complete validation suite:
```python
from ras_commander.check import RasCheck

# Run all checks with default thresholds
results = RasCheck.run_all_checks("C:/Projects/MyModel")

# Generate summary report
print(results.summary())
```

### Run Specific Check

Individual check execution:
```python
# NT Check only
nt_results = RasCheck.nt_check("C:/Projects/MyModel")

# XS Check only
xs_results = RasCheck.xs_check("C:/Projects/MyModel")
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
