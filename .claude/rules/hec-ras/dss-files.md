# DSS File Operations

**Context**: Reading and validating HEC-DSS boundary conditions
**Priority**: High - affects boundary condition workflows
**Auto-loads**: Yes (DSS-related code)

## Primary Source

**See**: `ras_commander/dss/AGENTS.md` for complete DSS documentation.

## Overview

Use HEC-DSS files for time series boundary condition data. Access them through ras-commander's lazy-loaded Java bridge.

## Key Class

| Class | Purpose |
|-------|---------|
| `RasDss` | Catalog reading, data extraction, validation |

## DSS Pathname Format

```
//A/B/C/D/E/F/

Part A: Basin/Project identifier
Part B: Location identifier
Part C: Parameter (FLOW, STAGE, PRECIP)
Part D: Start date (01JAN2020)
Part E: Interval (1HOUR, 1DAY, IR-YEAR)
Part F: Version/Scenario
```

**Example**: `//BASIN/UPSTREAM/FLOW/01JAN2020/1HOUR/OBS/`

## Lazy Loading Architecture

DSS operations use lazy loading (Java bridge loads only when needed):

```python
from ras_commander.dss import RasDss

# Java bridge NOT loaded yet
catalog = RasDss.get_catalog(dss_file)  # Bridge loads here

# Subsequent calls use loaded bridge
data = RasDss.get_timeseries(dss_file, pathname)
```

**Benefits**:
- Faster import when DSS not needed
- Graceful degradation if DSS dependencies unavailable

## Validation Methods

```python
from ras_commander.dss import RasDss

# Quick boolean check
if RasDss.is_valid_pathname(pathname):
    proceed()

# Detailed validation report
report = RasDss.check_pathname(dss_file, pathname)
if not report.is_valid:
    report.print_report(show_passed=False)
```

## Quick Reference

```python
from ras_commander.dss import RasDss

# Read catalog
catalog = RasDss.get_catalog(dss_file)

# Check pathname exists
exists = RasDss.is_pathname_available(dss_file, pathname)

# Extract time series
df = RasDss.get_timeseries(dss_file, pathname, start_date, end_date)

# Comprehensive validation
report = RasDss.check_pathname(dss_file, pathname)
```

## Cross-References

**Skills** (related workflows):
- `dss_read_boundary-data` -- Use for DSS boundary condition extraction
- `usgs_integrate_gauges` -- Use when generating DSS from USGS gauge data

**Rules** (auto-loaded context):
- `.claude/rules/validation/validation-patterns.md` -- Validation patterns for DSS pathnames

**Primary sources**:
- `ras_commander/dss/AGENTS.md` -- Complete DSS documentation
- `examples/310_dss_boundary_extraction.ipynb` -- DSS extraction workflow

---

**Key Takeaway**: Call `RasDss.check_pathname()` for validation before HEC-RAS execution. DSS uses lazy loading -- Java bridge loads only when needed.
