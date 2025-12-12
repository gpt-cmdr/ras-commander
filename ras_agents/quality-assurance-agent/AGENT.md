# Quality Assurance Agent

**Purpose**: Production-ready reference documentation for hydraulic model quality assurance and validation following FEMA cHECk-RAS standards.

**Domain**: Model validation, quality assurance, FEMA NFIP compliance

**Status**: Production (migrated from feature_dev_notes with security verification)

---

## ⚠️ IMPORTANT DISCLAIMER

This is an **UNOFFICIAL** Python implementation inspired by the FEMA cHECk-RAS tool.
It is **NOT affiliated with, endorsed by, or supported by FEMA**.

**Original cHECk-RAS:**
- Developed by Dewberry for FEMA
- Upgraded by IBM (2021)
- Property of FEMA National Flood Insurance Program

**This Python implementation:**
- Part of ras-commander open source library
- Independent clean-room implementation
- Follows FEMA guidelines but is not an official tool

For official cHECk-RAS support, contact FEMA NFIP.

---

## Primary Sources

**Production Implementation**:
- `ras_commander/check/RasCheck.py` - Main validation class (5 check modules, 156 checks)
  - `check_nt()` - Manning's n and transition coefficients (17 checks)
  - `check_xs()` - Cross section spacing and validation (54 checks)
  - `check_structures()` - Bridge/culvert/weir validation (52 checks)
  - `check_floodways()` - Floodway surcharge validation (27 checks)
  - `check_profiles()` - Multi-profile consistency (6 checks)
- `ras_commander/check/messages.py` - 100+ standardized validation messages
- `ras_commander/check/thresholds.py` - FEMA validation thresholds
- `ras_commander/check/report.py` - HTML/CSV report generation

**Detailed Specifications** (this directory):
- `reference/specifications/overview.md` - Implementation status and scope (~83% coverage)
- `reference/specifications/rascheck-class.md` - RasCheck class architecture
- `reference/specifications/check-nt.md` - Manning's n validation (17 checks)
- `reference/specifications/check-xs.md` - Cross section validation (59 checks)
- `reference/specifications/check-xs.md` - Cross section validation (59 checks)
- `reference/specifications/check-structures.md` - Structure validation (60 checks)
- `reference/specifications/check-floodways.md` - Floodway validation (45 checks)
- `reference/specifications/check-profiles.md` - Multi-profile validation (6 checks)
- `reference/specifications/messages.md` - Message catalog design
- `reference/specifications/reporting.md` - Report generation design
- `reference/specifications/thresholds.md` - FEMA validation thresholds
- `reference/specifications/gap-analysis.md` - HDF data requirements

**Reference Analysis**:
- `reference/comparison-analysis.md` - Python vs original cHECk-RAS comparison

**Working Example**:
- `examples/28_quality_assurance_rascheck.ipynb` - Complete QA workflow

**Subagent Definition**:
- `.claude/subagents/quality-assurance.md` - Expert subagent for QA tasks

---

## Quick Reference

### Basic RasCheck Workflow

```python
from ras_commander import init_ras_project
from ras_commander.check import RasCheck

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Run all checks
results = RasCheck.run_all(
    plan_number="01",
    state="Ohio"  # For state-specific floodway limits
)

# Generate HTML report
RasCheck.generate_report(
    results,
    output_file="qa_report.html",
    format="html"
)
```

### Individual Check Modules

```python
# Manning's n validation
nt_results = RasCheck.check_nt("01")

# Cross section validation
xs_results = RasCheck.check_xs("01")

# Structure validation
struct_results = RasCheck.check_structures("01")

# Floodway validation
floodway_results = RasCheck.check_floodways("01", state="Minnesota")

# Multi-profile validation
profile_results = RasCheck.check_profiles("01")
```

### Access Validation Messages

```python
from ras_commander.check import messages

# Get specific message
msg = messages.NT_RC_01L
print(msg.severity)  # "Error" or "Warning"
print(msg.description)  # Full message text

# List all Manning's n messages
nt_messages = [m for m in messages.ALL_MESSAGES if m.id.startswith("NT_")]
```

---

## Critical Validation Thresholds

### Manning's n Ranges (Public FEMA Standards)

**Channel:**
- Minimum: 0.012 (clean, straight channel)
- Maximum: 0.200 (heavy brush with debris)
- Typical Range: 0.025 - 0.040

**Overbank:**
- Minimum: 0.015 (smooth pasture)
- Maximum: 0.500 (dense timber/brush)
- Typical Range: 0.030 - 0.150

**Transition Coefficients:**
- Regular XS Contraction: 0.1
- Regular XS Expansion: 0.3
- Structure Contraction: 0.3
- Structure Expansion: 0.5

### Cross Section Spacing

- **Maximum Length:** 5,000 ft
- **Minimum Length:** 10 ft
- **Length Ratio:** ≤ 2.0 (consecutive sections)

**Additional Criteria** (all must be exceeded):
- Velocity head change > 0.5
- Conveyance ratio < 0.7 or > 1.4
- Water depth factor > 1.1
- Top width factor > 2.0

### Floodway Surcharge (44 CFR 60.3)

**Federal Default:** 1.0 ft

**State-Specific Limits** (more restrictive):
- Minnesota, Ohio: 0.5 ft
- New Jersey: 0.2 ft
- Michigan, Illinois, Indiana: 0.1 ft

### Bridge/Structure

- **Section Spacing:** 50 - 500 ft from bridge
- **Weir Coefficient:** 2.5 - 3.1 (typical: 2.6)
- **Culvert Entrance Coefficient:** 0.2 - 1.0
- **Min Clearance:** 1.0 ft (high chord to water surface)

**See**: `reference/specifications/thresholds.md` for complete threshold documentation.

---

## Common Workflows

### 1. Run Complete QA Validation

**Typical use**: Pre-submittal FEMA model review

```python
from ras_commander import init_ras_project
from ras_commander.check import RasCheck

# Initialize
init_ras_project("/path/to/fema/model", "6.5")

# Run all 156 checks
results = RasCheck.run_all(
    plan_number="01",
    state="Ohio"  # Apply state-specific floodway limits
)

# Generate report
RasCheck.generate_report(
    results,
    output_file="fema_qa_report.html",
    format="html",
    include_warnings=True
)

print(f"Errors: {results['error_count']}")
print(f"Warnings: {results['warning_count']}")
```

**See**: `examples/28_quality_assurance_rascheck.ipynb` for complete workflow.

### 2. Validate Manning's n Only

**Typical use**: After geometry modifications

```python
# Check Manning's n ranges and transition coefficients
nt_results = RasCheck.check_nt("01")

# Review issues
for issue in nt_results['issues']:
    print(f"{issue['severity']}: {issue['message']}")
    print(f"  Location: {issue['river']}, {issue['reach']}, XS {issue['rs']}")
```

**See**: `reference/specifications/check-nt.md` for 17 NT check specifications.

### 3. Floodway Compliance Check

**Typical use**: Floodway determination submittal

```python
# Apply state-specific surcharge limit
floodway_results = RasCheck.check_floodways(
    plan_number="01",
    state="Minnesota"  # 0.5 ft limit (more restrictive than federal 1.0 ft)
)

# Identify surcharge exceedances
exceedances = [i for i in floodway_results['issues']
               if i['message_id'].startswith('SC_')]

print(f"Surcharge exceedances: {len(exceedances)}")
```

**See**: `reference/specifications/check-floodways.md` for floodway validation logic.

### 4. Structure Validation

**Typical use**: Bridge/culvert modeling review

```python
# Validate bridge/culvert configurations
struct_results = RasCheck.check_structures("01")

# Filter by structure type
bridge_issues = [i for i in struct_results['issues']
                 if 'Bridge' in i['location']]
culvert_issues = [i for i in struct_results['issues']
                  if 'Culvert' in i['location']]
```

**See**: `reference/specifications/check-structures.md` for 60 structure checks.

---

## Check Coverage Status

**Implementation Completeness** (as of December 2024):

| Module | Checks | Implemented | Coverage |
|--------|--------|-------------|----------|
| NT (Manning's n) | 17 | 17 | 100% ✅ |
| XS (Cross Sections) | 59 | 54 | 92% ✅ |
| Structures | 60 | 52 | 87% ✅ |
| Floodways | 45 | 27 | 60% 🟡 |
| Profiles | 6 | 6 | 100% ✅ |
| **TOTAL** | **187** | **156** | **83%** ✅ |

**Missing Checks** (31 total):
- 5 XS checks (complex geometry analysis)
- 8 Structure checks (advanced configurations)
- 18 Floodway checks (multi-scenario analysis)

**See**: `reference/specifications/overview.md` for complete gap analysis.

---

## Message Categories

**Severity Levels:**
- **Error** - Must be corrected (FEMA submittal will be rejected)
- **Warning** - Should be reviewed (may require justification)

**Message Prefixes:**
- **NT_** - Manning's n and transition coefficients
- **XS_** - Cross section issues
- **ST_** - Structure issues
- **FW_** - Floodway issues
- **PR_** - Profile issues

**Common Error Messages:**

```
NT_RC_01L - Manning's n value for LOB is outside acceptable range
NT_RC_01R - Manning's n value for ROB is outside acceptable range
NT_RC_03C - Manning's n value for channel is outside acceptable range

XS_DT_01 - Reach length exceeds maximum spacing of 5,000 ft
XS_EC_01 - Water surface elevation exceeds ground elevation

ST_BR_01 - Bridge section spacing is outside recommended range
FW_SC_01 - Floodway surcharge exceeds [state limit]
```

**See**: `reference/specifications/messages.md` for complete message catalog (100+ messages).

---

## FEMA Standards Reference

**Primary Regulations:**
- **44 CFR 60.3** - Floodway encroachment standards (1-foot surcharge)
- **FEMA Guidelines and Standards for Flood Risk Analysis and Mapping**
- **HEC-RAS Hydraulic Reference Manual** - Manning's n tables

**Public Domain Sources:**
- Chow, V.T. (1959) - *Open-Channel Hydraulics* (Manning's n values)
- USGS Water Supply Papers - Channel roughness data
- State NFIP regulations - State-specific requirements

**All validation thresholds are based on publicly documented FEMA/NFIP standards.**

**See**: `reference/comparison-analysis.md` for Python vs original cHECk-RAS analysis.

---

## Navigation Map

**Need implementation details?**
→ `ras_commander/check/RasCheck.py` (production code)

**Need validation specifications?**
→ `reference/specifications/` (11 detailed spec documents)

**Need FEMA standards reference?**
→ `reference/specifications/thresholds.md` (complete threshold documentation)

**Need working example?**
→ `examples/28_quality_assurance_rascheck.ipynb` (complete workflow)

**Need expert assistance?**
→ Use `quality-assurance` subagent (`.claude/subagents/quality-assurance.md`)

**Implementation gap analysis?**
→ `reference/specifications/gap-analysis.md` (missing vs implemented checks)

---

## Integration Notes

**Hierarchical Knowledge Pattern:**
```
User workflow → examples/28_... → ras_commander/check/RasCheck.py → ras_agents/quality-assurance-agent/reference/
```

**Specifications guide implementation:**
- Validation logic defined in `reference/specifications/`
- Production code implements logic in `ras_commander/check/`
- Example notebooks demonstrate usage in `examples/`

**Single Source of Truth:**
- Thresholds: `ras_commander/check/thresholds.py` (code) + `reference/specifications/thresholds.md` (documentation)
- Messages: `ras_commander/check/messages.py` (code) + `reference/specifications/messages.md` (design)
- Logic: `ras_commander/check/RasCheck.py` (code) + `reference/specifications/` (specs)

---

## Migration Notes

**Source**: `feature_dev_notes/cHECk-RAS/` (gitignored, not tracked)

**Migrated**: 2025-12-12

**Security Verification**: All files scanned for sensitive paths - PASSED ✅
- Zero `D:\M3` references (local file paths)
- Zero `C:\Users` references
- No credentials or proprietary information

**Content Migrated** (13 files, ~10,000 lines):
- 11 specification documents (development_plan/)
- 1 comparison analysis (reports/)
- FEMA disclaimer added to all files

**Content Excluded**:
- FEMA installer files (proprietary)
- Decompiled source code (copyright restrictions)
- M3-specific scripts (local dependencies)
- Test project binary files (size constraints)

**Original Content**: Available in gitignored `feature_dev_notes/` for development reference only (not accessible to automated agents).

---

**Last Updated**: 2025-12-12
**Status**: Production Ready ✅
**Security**: Audited and Verified ✅
**FEMA Compliance**: Based on public NFIP standards ✅
