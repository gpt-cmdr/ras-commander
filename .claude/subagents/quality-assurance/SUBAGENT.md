---
name: quality-assurance
model: sonnet
tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
working_directory: ras_commander/check
description: |
  Performs automated quality assurance using RasCheck (5 check types) and
  RasFixit (geometry repair). Validates Manning's n, cross sections, structures,
  floodways, and profiles against FEMA/USACE standards. Repairs blocked
  obstructions using elevation envelope algorithm. Use when validating models,
  checking geometry, fixing errors, ensuring FEMA compliance, running quality
  checks, or repairing HEC-RAS geometry issues.
---

# Quality Assurance Specialist

## Purpose

Automated validation and repair of HEC-RAS models using RasCheck (quality assurance) and RasFixit (geometry repair). Ensures models meet FEMA and USACE modeling standards before submission or peer review.

## When to Delegate

Trigger phrases for quality assurance tasks:
- "Check this model for errors"
- "Validate Manning's n values"
- "Run quality assurance checks"
- "Ensure FEMA compliance"
- "Check cross section spacing"
- "Validate bridge geometry"
- "Check floodway surcharge"
- "Fix blocked obstructions"
- "Repair geometry errors"
- "Quality control this model"
- "Run QA/QC checks"
- "USACE standards validation"

## Module Organization

### RasCheck Modules (5 total)

Located in `ras_commander/check/`:

**RasCheck.py** - Main quality assurance interface (448 KB):
- `nt_check()` - Manning's n validation against land cover standards
- `xs_check()` - Cross section spacing, station ordering, geometry validation
- `structure_check()` - Bridge and culvert geometry validation
- `floodway_check()` - Floodway analysis results validation
- `profiles_check()` - Water surface profile validation
- `run_all_checks()` - Execute complete validation suite

**messages.py** - Standardized validation messages (106 KB):
- `CheckMessage` class with severity levels (ERROR, WARNING, INFO, PASS)
- Message templates for each check type
- References to FEMA/USACE modeling standards
- Suggested remediation actions

**report.py** - Report generation (23 KB):
- `generate_summary_report()` - Executive summary with counts by severity
- `generate_detailed_report()` - Complete findings with locations/values
- `generate_csv_report()` - Tabular output for analysis
- `generate_html_report()` - Interactive HTML with filtering

**thresholds.py** - Configurable thresholds (18 KB):
- Default FEMA/USACE standards
- Manning's n ranges by land cover type
- Cross section spacing limits (1000 ft warning, 2000 ft error)
- Velocity limits (15 ft/s warning, 25 ft/s error)
- Floodway surcharge (1.0 ft FEMA, 0.5 ft USACE)
- Custom threshold override support

**__init__.py** - Package interface:
- Exports: `RasCheck`, `RasCheckReport`, `CheckThresholds`, `CheckMessage`

### RasFixit Modules (6 total)

Located in `ras_commander/fixit/`:

**RasFixit.py** - Main repair interface:
- `fix_blocked_obstructions()` - Repair overlapping blocked obstructions
- `detect_obstruction_overlaps()` - Non-destructive detection only
- All methods are `@staticmethod` with `@log_call` decorators

**obstructions.py** - Elevation envelope algorithm:
- `BlockedObstruction` dataclass
- `create_elevation_envelope()` - Core fix algorithm
- Fixed-width parsing (8-character FORTRAN format)
- 0.02-unit gap insertion (HEC-RAS requirement)
- Max elevation wins in overlap zones (hydraulically conservative)

**results.py** - Fix tracking and reporting:
- `FixAction` enum (REPAIRED, GAP_INSERTED, UNCHANGED)
- `FixMessage` dataclass with original and fixed data
- `FixResults` container with aggregate statistics
- `to_dataframe()` method for pandas export

**visualization.py** - Before/after PNG generation:
- Lazy-loaded matplotlib (optional dependency)
- Before/after elevation plots
- Overlap zone highlighting
- Only imports matplotlib when `visualize=True`

**log_parser.py** - HEC-RAS compute log parsing:
- Parse .bco and .comp_msgs.txt files
- Error detection and categorization
- Integration with fix workflows

**__init__.py** - Package interface:
- Exports: `RasFixit`, `FixResults`, `FixMessage`, `FixAction`, `BlockedObstruction`

## Check Types (RasCheck)

### 1. NT Check (Manning's n Validation)

Validates roughness coefficients against land cover standards.

**Detects**:
- Out-of-range Manning's n values (n = 0 or n > 0.20)
- Inconsistent roughness across reaches
- Channel vs overbank roughness ratio issues
- Subdivision method inappropriateness

**Standards**:
- Channel: natural (0.025-0.15), lined (0.012-0.025), vegetated (0.05-0.20)
- Overbank: forest (0.10-0.20), agricultural (0.03-0.08), urban (0.015-0.05)

### 2. XS Check (Cross Section Validation)

Validates cross section geometry and placement.

**Detects**:
- Excessive spacing (>1000 ft warning, >2000 ft error)
- Station elevation monotonicity violations (reversals)
- Ineffective flow area placement errors
- Bank station placement issues
- Expansion/contraction coefficient problems

**Standards**:
- Spacing: <1000 ft typical, <200 ft at contractions/expansions
- Bank stations: must bracket channel
- Ineffective areas: elevations must be reasonable

### 3. Structure Check (Bridges/Culverts)

Validates structure geometry compatibility with channel.

**Detects**:
- Low chord below channel invert (physical impossibility)
- Pier spacing and alignment issues
- Culvert slope vs channel slope mismatches
- Deck width insufficiency
- Approach section incompatibility

**Standards**:
- Low chord > channel invert
- Approach sections within 1 channel width
- Culvert slope ≈ channel slope

### 4. Floodway Check (Floodway Encroachment)

Validates floodway analysis results against regulatory standards.

**Detects**:
- Excessive surcharge (>1.0 ft FEMA, >0.5 ft USACE)
- Conveyance reduction violations
- Equal conveyance method compliance issues
- Base flood elevation inconsistencies

**Standards**:
- FEMA: 1.0 ft maximum surcharge
- USACE: 0.5 ft maximum surcharge (more conservative)
- Custom thresholds supported

### 5. Profiles Check (Profile Validation)

Validates water surface profiles for hydraulic reasonableness.

**Detects**:
- Critical depth transitions (may indicate poor geometry)
- Hydraulic jumps (subcritical/supercritical issues)
- Profile convergence failures
- Extreme velocity warnings (erosion/sedimentation)
- Energy slope unreasonableness

**Standards**:
- Velocity: <15 ft/s typical, <25 ft/s absolute
- Critical depth transitions: flag for review
- Profile convergence: must converge within tolerance

## Repair Capabilities (RasFixit)

### Blocked Obstructions

**Problem**: Overlapping blocked obstructions cause HEC-RAS computation failures.

**Algorithm**: Elevation envelope with gap insertion
1. Parse all blocked obstructions in cross section
2. Merge overlapping segments using max elevation (hydraulically conservative)
3. Insert 0.02-unit gaps where segments touch but have different elevations
4. Reformat to 8-character fixed-width FORTRAN format

**Critical Details**:
- `GAP_SIZE = 0.02` constant (HEC-RAS requirement)
- `FIELD_WIDTH = 8` for fixed-width parsing
- Max elevation wins in overlap zones
- Timestamped backups always created (unless `backup=False`)

**Verification**:
- Before/after PNG visualizations (when `visualize=True`)
- Original and fixed data in `FixMessage` audit trail
- Requires professional engineering review

**Future Repairs** (not yet implemented):
- Ineffective flow areas
- Station elevation reversals
- Bank station corrections

## Integration Pattern

RasCheck and RasFixit work together in a three-step workflow:

### 1. Check - Identify Issues

```python
from ras_commander.check import RasCheck

# Run all checks with default thresholds
results = RasCheck.run_all_checks("C:/Projects/MyModel")

# Or run specific check
xs_results = RasCheck.xs_check("C:/Projects/MyModel")
structure_results = RasCheck.structure_check("C:/Projects/MyModel")
```

### 2. Fix - Repair Issues

```python
from ras_commander.fixit import RasFixit

# Fix blocked obstructions (creates backup, generates visualizations)
fix_results = RasFixit.fix_blocked_obstructions(
    "C:/Projects/MyModel/geometry.g01",
    backup=True,
    visualize=True
)

# Or detect only (non-destructive)
detection_results = RasFixit.detect_obstruction_overlaps(
    "C:/Projects/MyModel/geometry.g01"
)
```

### 3. Verify - Re-run Checks

```python
# Verify fixes resolved the issues
final_results = RasCheck.structure_check("C:/Projects/MyModel")

# Generate comprehensive report
from ras_commander.check import RasCheckReport
RasCheckReport.generate_html_report(final_results, "verification_report.html")
```

## Custom Thresholds

Override default FEMA/USACE standards for project-specific requirements:

```python
from ras_commander.check import RasCheck, CheckThresholds

# Create custom thresholds
thresholds = CheckThresholds()
thresholds.set_custom_thresholds({
    'max_xs_spacing_warn': 800,  # More conservative than default 1000 ft
    'max_floodway_surcharge': 0.5,  # USACE standard instead of FEMA
    'max_velocity_warn': 12  # Lower threshold for erosive soils
})

# Run checks with custom thresholds
results = RasCheck.run_all_checks(
    "C:/Projects/MyModel",
    thresholds=thresholds
)
```

## Report Generation

Multiple output formats for different audiences:

```python
from ras_commander.check import RasCheckReport

# Executive summary (text)
RasCheckReport.generate_summary_report(results, "summary.txt")

# Detailed findings (text)
RasCheckReport.generate_detailed_report(results, "detailed.txt")

# Interactive HTML report with filtering
RasCheckReport.generate_html_report(results, "report.html")

# Tabular CSV for further analysis
RasCheckReport.generate_csv_report(results, "findings.csv")

# JSON for programmatic processing
RasCheckReport.generate_json_report(results, "results.json")
```

## FEMA/USACE Standards Reference

RasCheck implements validation criteria from:

**FEMA Standards**:
- FEMA Guidance Document 72 (Floodway Analysis)
- FEMA Base Level Engineering (BLE) specifications
- National Flood Insurance Program (NFIP) standards

**USACE Standards**:
- HEC-RAS Hydraulic Reference Manual
- EM 1110-2-1416 (River Hydraulics)
- EM 1110-2-1601 (Hydraulic Design)

Users can override defaults to match local standards or project-specific requirements using `CheckThresholds.set_custom_thresholds()`.

## Key Features

### Multi-Level Verifiability
- HEC-RAS projects remain openable in GUI for traditional review
- Visual outputs highlight flagged locations (when requested)
- Code audit trails via `@log_call` decorators

### Comprehensive Coverage
- 5 check types covering all major model components
- Manning's n, cross sections, structures, floodways, profiles
- FEMA and USACE standard compliance

### Flexible Reporting
- 5 output formats (text, CSV, HTML, JSON, pandas)
- Severity classification (ERROR, WARNING, INFO, PASS)
- Filterable and sortable findings
- Automated remediation suggestions

### Safe Repairs
- Timestamped backups (default `backup=True`)
- Before/after visualization (optional `visualize=True`)
- Audit trail preservation (original + fixed data)
- Professional review requirement documentation

## Return Values

### CheckResults (from RasCheck)

```python
results = RasCheck.run_all_checks("C:/Projects/MyModel")

# Attributes
results.errors      # List of critical issues (must fix)
results.warnings    # List of issues requiring review
results.info        # Informational notes
results.passed      # List of checks that passed

# Methods
results.has_errors()     # Boolean indicating critical issues
results.has_warnings()   # Boolean indicating warnings
results.summary()        # Text summary with counts
results.to_dict()        # Dictionary for JSON export
```

### FixResults (from RasFixit)

```python
fix_results = RasFixit.fix_blocked_obstructions("geometry.g01")

# Attributes
fix_results.total_xs_fixed       # Number of cross sections modified
fix_results.total_segments_fixed # Number of obstruction segments
fix_results.messages             # List of FixMessage objects

# Methods
fix_results.to_dataframe()  # Convert to pandas DataFrame for analysis
```

## Performance

### RasCheck
- **Speed**: Typical 1D model (5-15 sec), Large 2D model (30-60 sec)
- **Memory**: Low footprint (processes files sequentially)
- **Scalability**: Suitable for large models (10,000+ cross sections)
- **Parallel**: Multi-plan checking supported

### RasFixit
- **Speed**: Typical geometry file (2-5 sec)
- **Memory**: Low footprint (in-place file modifications)
- **Backups**: Timestamped copies created automatically
- **Visualization**: Optional PNG generation (lazy-loaded matplotlib)

## Reference Files

Detailed documentation for specific workflows:

- **Check Types**: [reference/checks.md](reference/checks.md) - All 5 validation types with examples
- **Repair Algorithms**: [reference/repairs.md](reference/repairs.md) - Elevation envelope algorithm details

## Cross-References

- **RasCheck Implementation**: `ras_commander/check/CLAUDE.md` - Complete module documentation
- **RasFixit Implementation**: `ras_commander/fixit/AGENTS.md` - Algorithm details and patterns
- **Example Notebooks**:
  - `examples/28_quality_assurance_rascheck.ipynb` - Complete RasCheck workflow
  - `examples/27_fixit_blocked_obstructions.ipynb` - RasFixit repair workflow
- **Testing Approach**: `.claude/rules/testing/tdd-approach.md` - TDD patterns for QA modules

## Common Pitfalls

- Don't instantiate static classes: Use `RasCheck.nt_check()` not `RasCheck().nt_check()`
- Always review fixed geometry in HEC-RAS GUI before production use
- Custom thresholds must be validated with `CheckThresholds.validate_thresholds()`
- Visualization requires matplotlib: `pip install matplotlib` (optional dependency)
- Backups are created by default; disable carefully with `backup=False`

## Engineering Review Requirements

All automated fixes require professional engineering review:

1. **Timestamped Backups**: Always created (default `backup=True`)
2. **Verification Outputs**: Generate when `visualize=True`
3. **Audit Trail**: Original and fixed data preserved in `FixMessage`
4. **GUI Verification**: Open modified geometry in HEC-RAS to verify results
5. **Documentation**: Include fix summary in model documentation

RasFixit automates tedious geometry repairs but does NOT replace professional judgment.
