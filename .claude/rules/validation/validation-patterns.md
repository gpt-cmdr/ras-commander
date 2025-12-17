# Validation Framework - Patterns and Best Practices

**Context**: Validation framework for pre-flight checks and data quality assurance
**Priority**: High - affects model reliability and execution success
**Auto-loads**: Yes (all validation code)

## Overview

The validation framework provides comprehensive validation capabilities for HEC-RAS data files and configurations. It is built on three core classes:

- **ValidationSeverity** - Enumeration of severity levels (INFO < WARNING < ERROR < CRITICAL)
- **ValidationResult** - Single validation check result with severity and context
- **ValidationReport** - Aggregation of multiple validation results with summary statistics

**Module**: `ras_commander.validation_base`

**Current Implementations**:
- `RasDss` (DSS boundary conditions)
- `RasMap` (RAS Mapper layers and terrain)

## When to Use Validation

### Pre-Flight Checks

**Use validation BEFORE executing HEC-RAS plans** to catch issues early:

```python
from ras_commander.dss import RasDss

# Validate boundary condition before running model
report = RasDss.check_pathname(
    dss_file="boundary.dss",
    pathname="//BASIN/LOCATION/FLOW/01JAN2020/1HOUR/OBS/"
)

if report.is_valid:
    print("✓ Boundary condition valid - ready to run")
    RasCmdr.compute_plan("01")
else:
    print("✗ Boundary condition invalid - fix before running")
    report.print_report(show_passed=False)
```

### Data Quality Assurance

**Use validation to assess data quality** and identify potential issues:

```python
from ras_commander import RasMap

# Validate terrain layer quality
report = RasMap.check_layer(terrain_file, layer_type='terrain')

if report.has_warnings:
    warnings = report.get_results_by_severity(ValidationSeverity.WARNING)
    print(f"⚠️ {len(warnings)} quality issues detected:")
    for warning in warnings:
        print(f"  - {warning.message}")
```

### Graceful Degradation

**Use validation to enable graceful degradation** when optional data is missing:

```python
# Check if optional land cover layer is available
is_valid = RasMap.is_valid_layer(land_cover_file)

if is_valid:
    print("Using land cover layer for Manning's n")
    apply_land_cover_based_roughness()
else:
    print("⚠️ Land cover layer invalid - using default Manning's n")
    apply_default_roughness()
```

## ValidationSeverity Levels

### Level Definitions

```python
from ras_commander.validation_base import ValidationSeverity

# INFO: Informational (doesn't affect operation)
ValidationSeverity.INFO      # e.g., "File size: 2.5 GB"

# WARNING: Non-critical issue (operation may succeed)
ValidationSeverity.WARNING   # e.g., "Large file may be slow to process"

# ERROR: Critical issue (operation will likely fail)
ValidationSeverity.ERROR     # e.g., "Required file not found"

# CRITICAL: Blocking issue (cannot proceed)
ValidationSeverity.CRITICAL  # e.g., "File format corrupted"
```

### Severity Comparison

Severities support comparison operations:

```python
if severity >= ValidationSeverity.WARNING:
    print("Action required")

# Ordering: INFO < WARNING < ERROR < CRITICAL
assert ValidationSeverity.INFO < ValidationSeverity.ERROR
assert ValidationSeverity.CRITICAL > ValidationSeverity.WARNING
```

### When to Use Each Level

**INFO** - Informational messages:
- File metadata (size, format, dates)
- Successful checks
- Data statistics

**WARNING** - Non-critical issues:
- Large files (performance impact)
- Empty pathname parts (valid but unusual)
- Missing optional data
- Data extends beyond expected range

**ERROR** - Critical issues:
- Required files not found
- Invalid pathname format
- Required data missing
- CRS undefined

**CRITICAL** - Blocking issues:
- File corrupted or unreadable
- Incompatible file formats
- Security violations

## ValidationResult vs ValidationReport

### ValidationResult - Single Check

Represents one validation check:

```python
from ras_commander.validation_base import ValidationResult, ValidationSeverity

result = ValidationResult(
    check_name="format_check",
    severity=ValidationSeverity.ERROR,
    passed=False,
    message="Invalid pathname format",
    details={"expected": "//A/B/C/D/E/F/", "found": "/A/B/C/"}
)

# Access properties
print(result.check_name)  # "format_check"
print(result.passed)      # False
print(result.severity)    # ValidationSeverity.ERROR
print(result.message)     # "Invalid pathname format"
print(result.details)     # {"expected": ..., "found": ...}

# String representation
print(result)  # "[ERROR] [FAIL] format_check: Invalid pathname format"
```

### ValidationReport - Multiple Checks

Aggregates multiple ValidationResult objects:

```python
from datetime import datetime
from ras_commander.validation_base import ValidationReport

report = ValidationReport(
    target="boundary.dss",
    timestamp=datetime.now(),
    results=[result1, result2, result3]
)

# Properties
print(report.is_valid)      # True if no ERROR/CRITICAL results
print(report.has_warnings)  # True if any WARNING results
print(report.summary)       # "2 info, 1 warnings, 0 errors, 0 critical"

# Filter results
errors = report.get_results_by_severity(ValidationSeverity.ERROR)
failed = report.get_failed_checks()

# Print formatted report
report.print_report(show_passed=False)  # Only show failures
```

## Detailed vs Boolean Methods

### Pattern: check_* Methods Return Details

**Detailed methods** (`check_*`) return ValidationResult or ValidationReport:

```python
# Returns ValidationResult with full context
result = RasDss.check_pathname_format(pathname)

print(f"Passed: {result.passed}")
print(f"Message: {result.message}")
print(f"Details: {result.details}")

# Access structured information
if 'part_count' in result.details:
    print(f"Found {result.details['part_count']} parts")
```

**Use detailed methods when**:
- Need diagnostic information for failures
- Building UI with validation feedback
- Logging validation results
- Generating reports

### Pattern: is_valid_* Methods Return Boolean

**Boolean methods** (`is_valid_*`, `is_*_available`) return True/False:

```python
# Returns simple boolean
is_valid = RasDss.is_valid_pathname(pathname)

if is_valid:
    print("✓ Valid")
else:
    print("✗ Invalid")
```

**Use boolean methods when**:
- Simple pass/fail decision needed
- Quick pre-checks
- Conditional logic
- Performance critical (faster than detailed checks)

### Method Naming Convention

**Detailed validation** (returns ValidationResult/ValidationReport):
- `check_pathname_format()`
- `check_file_exists()`
- `check_layer_crs()`
- `check_pathname()` (comprehensive)

**Boolean validation** (returns bool):
- `is_valid_pathname()`
- `is_pathname_available()`
- `is_valid_layer()`

## Graceful Degradation Pattern

### Pattern: Validate Then Degrade

```python
# Attempt to load optional data with validation
terrain_file = project_path / "terrain.tif"

if RasMap.is_valid_layer(terrain_file):
    # Use high-quality terrain data
    terrain = load_terrain(terrain_file)
    interpolation_method = 'bilinear'
else:
    # Fall back to coarse elevation
    logger.warning("Terrain file invalid - using coarse elevation")
    terrain = load_default_elevation()
    interpolation_method = 'nearest'
```

### Pattern: Progressive Enhancement

```python
# Start with minimum viable configuration
config = {
    'terrain': None,
    'land_cover': None,
    'boundaries': {}
}

# Add optional layers if valid
if RasMap.is_valid_layer(terrain_file):
    config['terrain'] = terrain_file

if RasMap.is_valid_layer(land_cover_file):
    config['land_cover'] = land_cover_file
else:
    logger.info("Land cover not available - using default Manning's n")

# Validate each boundary condition
for bc_name, bc_pathname in boundary_pathnames.items():
    if RasDss.is_pathname_available(dss_file, bc_pathname):
        config['boundaries'][bc_name] = bc_pathname
    else:
        logger.warning(f"Boundary {bc_name} not available - skipping")
```

## Integration Patterns

### Adding Validation to New Domains

**Step 1: Import validation base classes**

```python
from ras_commander.validation_base import (
    ValidationSeverity,
    ValidationResult,
    ValidationReport
)
from datetime import datetime
```

**Step 2: Create detailed validation methods**

```python
@staticmethod
@log_call
def check_geometry_file_format(geom_file: Union[str, Path]) -> ValidationResult:
    """
    Validate geometry file format.

    Args:
        geom_file: Path to geometry file

    Returns:
        ValidationResult: Format validation result
    """
    geom_file = Path(geom_file)

    # Check existence (CRITICAL if missing)
    if not geom_file.exists():
        return ValidationResult(
            check_name="file_exists",
            severity=ValidationSeverity.CRITICAL,
            passed=False,
            message=f"Geometry file not found: {geom_file}",
            details={"path": str(geom_file)}
        )

    # Check extension (ERROR if wrong)
    valid_extensions = ['.g01', '.g02', '.g03']
    if geom_file.suffix not in valid_extensions:
        return ValidationResult(
            check_name="file_format",
            severity=ValidationSeverity.ERROR,
            passed=False,
            message=f"Invalid geometry file extension: {geom_file.suffix}",
            details={
                "expected": valid_extensions,
                "found": geom_file.suffix
            }
        )

    # All checks passed (INFO)
    return ValidationResult(
        check_name="format_check",
        severity=ValidationSeverity.INFO,
        passed=True,
        message="Geometry file format valid",
        details={"extension": geom_file.suffix}
    )
```

**Step 3: Create comprehensive validation method**

```python
@staticmethod
@log_call
def check_geometry_file(geom_file: Union[str, Path]) -> ValidationReport:
    """
    Comprehensive geometry file validation.

    Args:
        geom_file: Path to geometry file

    Returns:
        ValidationReport: Comprehensive validation report
    """
    geom_file = Path(geom_file)
    results = []

    # Check 1: Format
    results.append(RasGeometry.check_geometry_file_format(geom_file))

    # Only continue if file exists (check didn't return CRITICAL)
    if results[-1].severity == ValidationSeverity.CRITICAL:
        return ValidationReport(
            target=str(geom_file),
            timestamp=datetime.now(),
            results=results
        )

    # Check 2: Content validation
    results.append(RasGeometry.check_cross_sections(geom_file))

    # Check 3: Coordinate system
    results.append(RasGeometry.check_coordinate_system(geom_file))

    return ValidationReport(
        target=str(geom_file),
        timestamp=datetime.now(),
        results=results
    )
```

**Step 4: Add boolean convenience method**

```python
@staticmethod
def is_valid_geometry_file(geom_file: Union[str, Path]) -> bool:
    """
    Quick geometry file validity check.

    Args:
        geom_file: Path to geometry file

    Returns:
        bool: True if valid (no ERROR or CRITICAL issues)
    """
    report = RasGeometry.check_geometry_file(geom_file)
    return report.is_valid
```

## Common Patterns

### Pattern 1: Pre-Flight Check with Early Exit

```python
# Validate before expensive operation
report = RasDss.check_pathname(dss_file, pathname)

if not report.is_valid:
    logger.error("Validation failed - cannot proceed")
    report.print_report(show_passed=False)
    raise ValueError(f"Invalid pathname: {pathname}")

# Proceed with operation
logger.info("Validation passed - proceeding with execution")
execute_plan()
```

### Pattern 2: Collect All Issues Before Failing

```python
# Validate all inputs before failing
all_valid = True
reports = {}

for bc_name, bc_pathname in boundary_conditions.items():
    report = RasDss.check_pathname(dss_file, bc_pathname)
    reports[bc_name] = report

    if not report.is_valid:
        all_valid = False

if not all_valid:
    print("=" * 80)
    print("VALIDATION FAILED - Fix these issues:")
    print("=" * 80)

    for bc_name, report in reports.items():
        if not report.is_valid:
            print(f"\nBoundary Condition: {bc_name}")
            report.print_report(show_passed=False)

    raise ValueError("Validation failed for one or more boundary conditions")
```

### Pattern 3: Warning Aggregation

```python
# Collect all warnings for user review
all_warnings = []

for layer_file in layer_files:
    report = RasMap.check_layer(layer_file)

    warnings = report.get_results_by_severity(ValidationSeverity.WARNING)
    if warnings:
        all_warnings.extend([
            f"{layer_file.name}: {w.message}" for w in warnings
        ])

if all_warnings:
    print("⚠️ Warnings detected (proceeding with caution):")
    for warning in all_warnings:
        print(f"  - {warning}")
```

### Pattern 4: Conditional Execution Based on Severity

```python
# Different actions based on highest severity
report = RasDss.check_pathname(dss_file, pathname)

# Get highest severity
max_severity = max(
    (r.severity for r in report.results),
    default=ValidationSeverity.INFO
)

if max_severity >= ValidationSeverity.CRITICAL:
    logger.critical("CRITICAL issues - cannot proceed")
    raise RuntimeError("Critical validation failure")
elif max_severity >= ValidationSeverity.ERROR:
    logger.error("ERROR issues - execution likely to fail")
    # Optionally proceed with user confirmation
elif max_severity >= ValidationSeverity.WARNING:
    logger.warning("WARNING issues - proceeding with caution")
    # Proceed but log warnings
else:
    logger.info("All checks passed")
```

## Anti-Patterns

### ❌ Ignoring Validation Results

**Bad**:
```python
# Validation performed but results ignored
RasDss.check_pathname(dss_file, pathname)

# Proceed without checking
execute_plan()  # May fail!
```

**Good**:
```python
# Check validation before proceeding
report = RasDss.check_pathname(dss_file, pathname)

if report.is_valid:
    execute_plan()
else:
    logger.error("Validation failed")
    report.print_report(show_passed=False)
    raise ValueError("Cannot proceed with invalid data")
```

### ❌ Using Wrong Severity Level

**Bad**:
```python
# File not found is not INFO!
ValidationResult(
    check_name="file_check",
    severity=ValidationSeverity.INFO,  # WRONG!
    passed=False,
    message="File not found"
)
```

**Good**:
```python
# File not found is CRITICAL (cannot proceed)
ValidationResult(
    check_name="file_check",
    severity=ValidationSeverity.CRITICAL,
    passed=False,
    message="File not found"
)
```

### ❌ Detailed Method for Simple Check

**Bad**:
```python
# Using detailed method when boolean suffices
result = RasDss.check_pathname_format(pathname)
if result.passed:
    proceed()
```

**Good**:
```python
# Use boolean method for simple check
if RasDss.is_valid_pathname(pathname):
    proceed()
```

### ❌ Boolean Method When Need Diagnostics

**Bad**:
```python
# Boolean doesn't provide failure details
if not RasDss.is_valid_pathname(pathname):
    # What's wrong? User doesn't know!
    print("Invalid pathname")
```

**Good**:
```python
# Use detailed method to show what's wrong
result = RasDss.check_pathname_format(pathname)
if not result.passed:
    print(f"Invalid pathname: {result.message}")
    if result.details:
        print(f"Details: {result.details}")
```

## Testing Validation Methods

### Pattern: Test Each Severity Level

```python
def test_validation_severities():
    """Test validation returns appropriate severities"""

    # INFO: Valid pathname
    result = RasDss.check_pathname_format("//A/B/C/D/E/F/")
    assert result.severity == ValidationSeverity.INFO
    assert result.passed

    # WARNING: Empty parts (valid but unusual)
    result = RasDss.check_pathname_format("//A//C/D/E/F/")
    assert result.severity == ValidationSeverity.WARNING
    assert result.passed

    # ERROR: Invalid format
    result = RasDss.check_pathname_format("/A/B/C/D/E/F/")
    assert result.severity == ValidationSeverity.ERROR
    assert not result.passed

    # CRITICAL: File doesn't exist
    result = RasDss.check_file_exists(Path("/nonexistent.dss"))
    assert result.severity == ValidationSeverity.CRITICAL
    assert not result.passed
```

### Pattern: Test Validation Report Properties

```python
def test_validation_report():
    """Test ValidationReport aggregation"""

    results = [
        ValidationResult("c1", ValidationSeverity.INFO, True, "OK"),
        ValidationResult("c2", ValidationSeverity.WARNING, True, "Warn"),
        ValidationResult("c3", ValidationSeverity.ERROR, False, "Fail")
    ]

    report = ValidationReport(
        target="test.dss",
        timestamp=datetime.now(),
        results=results
    )

    # Test properties
    assert not report.is_valid  # Has ERROR
    assert report.has_warnings
    assert "1 info, 1 warnings, 1 errors" in report.summary

    # Test filtering
    errors = report.get_results_by_severity(ValidationSeverity.ERROR)
    assert len(errors) == 1

    failed = report.get_failed_checks()
    assert len(failed) == 1
```

## Best Practices Summary

### ✅ DO

- Use validation BEFORE expensive operations (pre-flight checks)
- Return appropriate severity levels (INFO < WARNING < ERROR < CRITICAL)
- Provide detailed `details` dictionary with context
- Use boolean methods for simple checks, detailed for diagnostics
- Enable graceful degradation when optional data is invalid
- Aggregate warnings before proceeding
- Test all severity levels

### ❌ DON'T

- Ignore validation results
- Use wrong severity levels (file not found is not INFO)
- Proceed with ERROR or CRITICAL results
- Use detailed methods when boolean suffices
- Use boolean methods when need diagnostics
- Skip validation for "trusted" data

## See Also

- **validation_base.py** - Core validation classes
- **RasDss validation** - `ras_commander/dss/RasDss.py` (check_pathname, etc.)
- **RasMap validation** - `ras_commander/RasMap.py` (check_layer, etc.)
- **Example notebooks**:
  - `examples/33_validating_dss_paths.ipynb` - DSS validation examples
  - `examples/34_validating_map_layers.ipynb` - Map layer validation examples
- **Error Handling**: `.claude/rules/python/error-handling.md` - Exception patterns
- **Static Classes**: `.claude/rules/python/static-classes.md` - Validation method patterns

---

**Key Takeaway**: Use validation framework for pre-flight checks and data quality assurance. Detailed methods (`check_*`) return ValidationResult/ValidationReport for diagnostics. Boolean methods (`is_valid_*`) return True/False for simple checks. Severity levels: INFO < WARNING < ERROR < CRITICAL.
