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

Automated validation and repair of HEC-RAS models using:
- **RasCheck** - Quality assurance (5 check types, FEMA/USACE standards)
- **RasFixit** - Geometry repair (blocked obstructions, elevation envelope algorithm)

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

## Primary Source Documents

### Complete RasCheck Documentation
**Location**: `C:\GH\ras-commander\ras_commander\check\CLAUDE.md` (262 lines)

This is the AUTHORITATIVE source for all RasCheck information:
- All 5 check types (NT, XS, Structure, Floodway, Profiles)
- FEMA/USACE standards and thresholds
- Complete API documentation
- Usage patterns and examples

**When working with RasCheck**: Always read check/CLAUDE.md first.

### Complete RasFixit Documentation
**Location**: `C:\GH\ras-commander\ras_commander\fixit\AGENTS.md` (119 lines)

This is the AUTHORITATIVE source for all RasFixit information:
- Elevation envelope algorithm details
- Module organization and patterns
- 0.02-unit gap insertion requirement
- Engineering review requirements

**When working with RasFixit**: Always read fixit/AGENTS.md first.

### Example Notebooks
**RasFixit Workflow**: `examples/200_fixit_blocked_obstructions.ipynb` (203 KB)
- Complete repair workflow demonstration
- Before/after visualization
- Integration with RasCheck

**RasCheck Workflow**: `examples/300_quality_assurance_rascheck.ipynb` (24 KB)
- All 5 check types demonstrated
- Custom threshold configuration
- Report generation examples

## Quick Reference

### RasCheck - 5 Check Types

**1. NT Check** - Manning's n validation
- Detects: Out-of-range values, channel/overbank inconsistencies
- Standards: Channel (0.025-0.15), Overbank (0.03-0.20)

**2. XS Check** - Cross section validation
- Detects: Spacing issues (>1000 ft warn, >2000 ft error), station reversals
- Standards: <1000 ft spacing, bank stations bracket channel

**3. Structure Check** - Bridge/culvert validation
- Detects: Low chord issues, pier spacing, culvert slope mismatches
- Standards: Low chord > channel invert, approach sections within 1 width

**4. Floodway Check** - Regulatory compliance
- Detects: Excessive surcharge (>1.0 ft FEMA, >0.5 ft USACE)
- Standards: FEMA (1.0 ft), USACE (0.5 ft), custom supported

**5. Profiles Check** - Hydraulic reasonableness
- Detects: Extreme velocities (>15 ft/s warn, >25 ft/s error), convergence failures
- Standards: Velocity limits, critical depth transitions, hydraulic jumps

**See check/CLAUDE.md for complete documentation.**

### RasFixit - Geometry Repair

**Current Capability**: Blocked Obstructions
- Algorithm: Elevation envelope with gap insertion
- Safety: Timestamped backups (default), before/after PNG (optional)
- Verification: Audit trails, professional review required

**Future Capabilities** (not yet implemented):
- Ineffective flow areas
- Station elevation reversals
- Bank station corrections

**See fixit/AGENTS.md for complete documentation.**

## CRITICAL: 0.02-Unit Gap Requirement

When working with blocked obstructions repairs:

**HEC-RAS requires minimum 0.02-unit separation between adjacent obstruction segments.**

This is a FORTRAN-era fixed-width format requirement that MUST NOT be changed:
- `GAP_SIZE = 0.02` constant (do not modify)
- `FIELD_WIDTH = 8` constant (do not modify)
- Gap inserted when segments touch but have different elevations
- Max elevation wins in overlap zones (hydraulically conservative)

**Location**: `ras_commander/fixit/obstructions.py` (lines ~110)

Changing this value will cause HEC-RAS computation failures.

## Integration Pattern: Check → Fix → Verify

**Step 1: Check - Identify Issues**
```python
from ras_commander.check import RasCheck

# Run all checks
results = RasCheck.run_all_checks("C:/Projects/MyModel")

# Or specific check
structure_results = RasCheck.structure_check("C:/Projects/MyModel")
```

**Step 2: Fix - Repair Issues**
```python
from ras_commander.fixit import RasFixit

# Fix with backup and visualization
fix_results = RasFixit.fix_blocked_obstructions(
    "C:/Projects/MyModel/geometry.g01",
    backup=True,      # Creates timestamped backup
    visualize=True    # Generates before/after PNGs
)
```

**Step 3: Verify - Re-run Checks**
```python
# Verify fixes resolved issues
final_results = RasCheck.structure_check("C:/Projects/MyModel")

# Generate comprehensive report
from ras_commander.check import RasCheckReport
RasCheckReport.generate_html_report(final_results, "verification_report.html")
```

## Custom Thresholds (FEMA vs USACE)

Override defaults for project-specific requirements:

```python
from ras_commander.check import RasCheck, CheckThresholds

# USACE standards (more conservative than FEMA)
thresholds = CheckThresholds()
thresholds.set_custom_thresholds({
    'max_xs_spacing_warn': 800,           # vs 1000 ft FEMA
    'max_floodway_surcharge': 0.5,        # vs 1.0 ft FEMA
    'max_velocity_warn': 12,              # vs 15 ft/s FEMA
    'min_low_chord_clearance': 3.0        # vs 2.0 ft FEMA
})

results = RasCheck.run_all_checks("C:/Projects/MyModel", thresholds=thresholds)
```

**Complete threshold reference**: See check/CLAUDE.md

## Report Generation

**5 output formats** for different audiences:

```python
from ras_commander.check import RasCheckReport

RasCheckReport.generate_summary_report(results, "summary.txt")      # Executive
RasCheckReport.generate_detailed_report(results, "detailed.txt")    # Complete
RasCheckReport.generate_html_report(results, "report.html")         # Interactive
RasCheckReport.generate_csv_report(results, "findings.csv")         # Tabular
RasCheckReport.generate_json_report(results, "results.json")        # Programmatic
```

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
results.has_errors()     # Boolean
results.has_warnings()   # Boolean
results.summary()        # Text summary
results.to_dict()        # For JSON export
```

### FixResults (from RasFixit)
```python
fix_results = RasFixit.fix_blocked_obstructions("geometry.g01")

# Attributes
fix_results.total_xs_fixed       # Number of cross sections modified
fix_results.total_segments_fixed # Number of obstruction segments repaired
fix_results.messages             # List of FixMessage objects (audit trail)

# Methods
fix_results.to_dataframe()  # Convert to pandas DataFrame
```

## Professional Engineering Review Requirements

**All automated fixes require PE review before production use:**

1. **Timestamped Backups**: Always created (default `backup=True`)
2. **Before/After Visualization**: Generate with `visualize=True`
3. **Audit Trail**: Original and fixed data in `FixMessage` objects
4. **HEC-RAS GUI Verification**: Open modified geometry, verify plots look reasonable
5. **Test Run**: Execute model, verify computational stability
6. **Documentation**: Include fix summary in engineering report

RasFixit automates tedious geometry repairs but **does NOT replace professional judgment**.

**Documentation Template**: See fixit/AGENTS.md for engineering report template.

## FEMA/USACE Standards

RasCheck implements validation from:

**FEMA Standards**:
- FEMA Guidance Document 72 (Floodway Analysis)
- FEMA Base Level Engineering (BLE) specifications
- National Flood Insurance Program (NFIP) standards

**USACE Standards**:
- HEC-RAS Hydraulic Reference Manual
- EM 1110-2-1416 (River Hydraulics)
- EM 1110-2-1601 (Hydraulic Design)

**Complete standards reference**: See check/CLAUDE.md

## Performance

**RasCheck**:
- Typical 1D model: 5-15 seconds
- Large 2D model: 30-60 seconds
- Parallel checking: Supported for multiple plans

**RasFixit**:
- Typical geometry file: 2-5 seconds
- Large file (10,000+ XS): 10-15 seconds
- Visualization adds: 5-10 seconds (lazy-loaded matplotlib)

## Module Organization

### RasCheck Modules (ras_commander/check/)
- `RasCheck.py` - Main interface (5 check methods, 448 KB)
- `messages.py` - Standardized messages (106 KB)
- `report.py` - Report generation (23 KB)
- `thresholds.py` - Configurable thresholds (18 KB)
- `__init__.py` - Public API
- `CLAUDE.md` - **Complete documentation (262 lines)**

### RasFixit Modules (ras_commander/fixit/)
- `RasFixit.py` - Main interface (fix and detect methods)
- `obstructions.py` - Elevation envelope algorithm
- `results.py` - FixAction, FixMessage, FixResults
- `visualization.py` - Before/after PNG (lazy-loaded)
- `log_parser.py` - HEC-RAS log parsing
- `__init__.py` - Public API
- `AGENTS.md` - **Complete documentation (119 lines)**

## Common Pitfalls

- **Don't instantiate static classes**: Use `RasCheck.nt_check()` not `RasCheck().nt_check()`
- **Always review fixed geometry**: Open in HEC-RAS GUI before production use
- **Custom thresholds validation**: Use `CheckThresholds.validate_thresholds()`
- **Visualization requires matplotlib**: `pip install matplotlib` (optional dependency)
- **Don't disable backups**: Default `backup=True` is intentional safety feature
- **Read primary sources**: check/CLAUDE.md and fixit/AGENTS.md have complete details

## Workflow Decision Tree

**When user requests quality assurance work:**

1. **Is this a CHECK request?**
   - Read `ras_commander/check/CLAUDE.md` for complete API
   - Check examples: `examples/300_quality_assurance_rascheck.ipynb`
   - Use `RasCheck.run_all_checks()` or specific check methods
   - Generate appropriate report format

2. **Is this a FIX request?**
   - Read `ras_commander/fixit/AGENTS.md` for complete algorithm details
   - Check examples: `examples/200_fixit_blocked_obstructions.ipynb`
   - Use `RasFixit.fix_blocked_obstructions()` with `visualize=True`
   - Remember: Professional review required, 0.02-unit gap is CRITICAL

3. **Is this a CHECK→FIX→VERIFY workflow?**
   - Read both check/CLAUDE.md and fixit/AGENTS.md
   - Follow integration pattern (see "Integration Pattern" section above)
   - Generate verification reports showing before/after results

**Always start with the primary source documents before writing code.**

## Cross-References

- **RasCheck Complete Docs**: `ras_commander/check/CLAUDE.md` (262 lines)
- **RasFixit Complete Docs**: `ras_commander/fixit/AGENTS.md` (119 lines)
- **RasFixit Workflow**: `examples/200_fixit_blocked_obstructions.ipynb`
- **RasCheck Workflow**: `examples/300_quality_assurance_rascheck.ipynb`
- **Testing Patterns**: `.claude/rules/testing/tdd-approach.md`
- **Parent Library**: `ras_commander/CLAUDE.md`

## Summary

This subagent is a **navigator to primary sources**. The complete documentation lives in:
1. `ras_commander/check/CLAUDE.md` - All RasCheck details
2. `ras_commander/fixit/AGENTS.md` - All RasFixit details
3. Example notebooks 200 and 300 - Complete workflows

**Always read the primary sources before implementing quality assurance features.**
