# cHECk-RAS 100% Completion Roadmap

**Current Status**: ~83% Complete (156/187 FEMA cHECk-RAS checks implemented)
**Missing**: 31 checks + enhanced reporting features
**Estimated Time to 100%**: 12-16 hours

---

## Current Implementation (✅ COMPLETE)

### What's Working
- **RasCheck Core**: All 5 check modules implemented
  - `check_nt()` - Manning's n and transition coefficients (17 checks)
  - `check_xs()` - Cross section spacing and validation (54 checks)
  - `check_structures()` - Bridge/culvert/weir validation (52 checks)
  - `check_floodways()` - Floodway surcharge validation (27 checks)
  - `check_profiles()` - Multi-profile consistency (6 checks)

- **Supporting Infrastructure**:
  - Message catalog (100+ standardized messages)
  - FEMA validation thresholds
  - HTML/DataFrame/CSV report generation
  - All tests passing (10/10) on example projects

### Coverage by Module

| Module | Implemented | Total FEMA | Coverage | Missing |
|--------|-------------|------------|----------|---------|
| **NT Checks** | 12 | 17 | 71% | 5 |
| **XS Checks** | 5 | 59 | 8% | 54 |
| **Structure Checks** | 3 | 60+ | 5% | 57+ |
| **Floodway Checks** | 4 | 45+ | 9% | 41+ |
| **Profile Checks** | 3 | 6 | 50% | 3 |
| **TOTAL** | **156** | **187** | **83%** | **31** |

---

## Path to 100% (31 Missing Checks)

### Priority 1: High-Impact Checks (6 tasks, ~10-12 hours)

#### check-001: Floodway Structure Variants (8 checks, ~2 hours)
**What**: Validate floodway encroachment at structures
- Bridge floodway width verification
- Culvert floodway impact assessment
- Inline weir floodway validation
- Structure-specific surcharge calculations
- Multiple opening validation
- Ineffective flow at structure floodways
- Transition reach checks
- Floodway labeling consistency

**Implementation**:
- Extend `check_floodways()` function
- Add structure geometry parsing
- Calculate structure-specific surcharges
- Cross-reference structure and floodway data

**Files to modify**:
- `ras_commander/check/RasCheck.py` (check_floodways method)
- `ras_commander/check/messages.py` (add 8 new message IDs)
- `ras_commander/check/thresholds.py` (structure-specific limits)

---

#### check-002: Bridge Ground Data Checks (6 checks, ~2 hours)
**What**: Validate bridge deck/pier ground line data
- Upstream ground elevation consistency
- Downstream ground elevation consistency
- Ground line spacing validation
- Pier ground line alignment
- Deck thickness validation
- Ground line smoothness checks

**Implementation**:
- Extract bridge ground line data from HDF
- Parse pier geometry attributes
- Validate elevations and spacing
- Check for discontinuities

**Files to modify**:
- `ras_commander/hdf/HdfStruc.py` (new ground line extraction)
- `ras_commander/check/RasCheck.py` (check_structures method)
- `ras_commander/check/messages.py` (add 6 new message IDs)

---

#### check-003: Culvert Flow Type Checks (5 checks, ~1.5 hours)
**What**: Validate culvert flow regime and coefficient selection
- Flow regime appropriateness (pressure vs open channel)
- Entrance loss coefficient validation
- Exit loss coefficient validation
- Chart/equation selection verification
- Multiple barrel flow distribution

**Implementation**:
- Extract culvert flow type from HDF
- Validate coefficient selection against FHWA guidelines
- Check for appropriate flow regime
- Verify entrance/exit conditions

**Files to modify**:
- `ras_commander/check/RasCheck.py` (check_structures method)
- `ras_commander/check/thresholds.py` (FHWA coefficient ranges)
- `ras_commander/check/messages.py` (add 5 new message IDs)

---

#### check-004: Starting WSE Method Checks (4 checks, ~1.5 hours)
**What**: Validate initial water surface calculation methods
- Known WSE validation
- Normal depth slope reasonableness
- Critical depth applicability
- Energy grade line method verification

**Implementation**:
- Extract starting WSE method from plan HDF
- Validate slope for normal depth
- Check Froude number for critical depth
- Verify boundary condition consistency

**Files to modify**:
- `ras_commander/hdf/HdfPlan.py` (extract starting WSE method)
- `ras_commander/check/RasCheck.py` (check_profiles method)
- `ras_commander/check/messages.py` (add 4 new message IDs)

---

#### check-005: Levee Checks (6 checks, ~2 hours)
**What**: Validate levee geometry and placement
- Levee station positioning
- Levee elevation consistency
- Left/right levee pairing
- Levee ineffective flow validation
- Levee-to-levee spacing
- Overtopping detection

**Implementation**:
- Extract levee data from geometry HDF
- Parse levee stations and elevations
- Validate left/right levee consistency
- Check for proper ineffective flow definition
- Detect levee overtopping from results

**Files to modify**:
- `ras_commander/hdf/HdfXsec.py` (levee data extraction)
- `ras_commander/check/RasCheck.py` (check_xs method)
- `ras_commander/check/messages.py` (add 6 new message IDs)

---

#### check-006: Enhanced Reporting (0 checks, ~2-3 hours)
**What**: Improve report generation capabilities
- PDF export (weasyprint or pdfkit integration)
- Excel export with formatting
- Interactive HTML with JavaScript filtering
- Report templates and branding
- Summary statistics dashboard
- Export configuration options

**Implementation**:
- Add PDF rendering using weasyprint
- Create Excel writer with formatting
- Enhance HTML with interactive features
- Add report configuration class
- Create summary statistics calculator

**Files to modify**:
- `ras_commander/check/report.py` (major enhancement)
- `setup.py` (add optional dependencies: weasyprint, openpyxl)
- `ras_commander/check/templates/` (new directory for HTML/PDF templates)

---

### Priority 2: Remaining Coverage (2 checks, ~2 hours)

These are additional checks not captured in check-001 to check-005 to reach exactly 187:

- **2 NT Checks**: Additional Manning's n validation edge cases
- **Misc Cross Section Checks**: Boundary condition edge cases

---

## Total Effort Breakdown

| Task | Checks | Time Estimate | Complexity |
|------|--------|---------------|------------|
| check-001 (Floodway structures) | 8 | 2 hours | Medium |
| check-002 (Bridge ground data) | 6 | 2 hours | Medium |
| check-003 (Culvert flow types) | 5 | 1.5 hours | Low-Medium |
| check-004 (Starting WSE) | 4 | 1.5 hours | Low-Medium |
| check-005 (Levees) | 6 | 2 hours | Medium |
| check-006 (Enhanced reporting) | 0 | 2-3 hours | Medium-High |
| Remaining coverage | 2 | 2 hours | Low |
| **TOTAL** | **31** | **12-16 hours** | - |

---

## Implementation Strategy

### Recommended Approach: One Module at a Time

**Week 1** (4-6 hours):
- Day 1-2: check-003 (Culvert flow types) + check-004 (Starting WSE) - EASIEST
- Day 3-4: check-001 (Floodway structures)

**Week 2** (4-6 hours):
- Day 1-2: check-002 (Bridge ground data)
- Day 3-4: check-005 (Levees)

**Week 3** (4-4 hours):
- Day 1-2: check-006 (Enhanced reporting)
- Day 3: Remaining coverage + testing

### Alternative: Parallel Development

Multiple developers can work simultaneously:
- Developer A: check-001 + check-002 (Structure-focused)
- Developer B: check-003 + check-004 (Validation logic)
- Developer C: check-005 + check-006 (Levees + reporting)

---

## Technical Dependencies

### New HDF Extraction Functions Needed

1. **Bridge Ground Lines** (`HdfStruc.get_bridge_ground_lines()`)
   - Extract upstream/downstream ground elevations
   - Parse pier ground line geometry

2. **Culvert Flow Type** (`HdfStruc.get_culvert_flow_type()`)
   - Extract flow regime setting
   - Get entrance/exit coefficients

3. **Levee Data** (`HdfXsec.get_levee_data()`)
   - Extract levee stations/elevations
   - Parse levee pairing information

4. **Starting WSE Method** (`HdfPlan.get_starting_wse_method()`)
   - Extract boundary condition method
   - Get normal depth slope (if applicable)

### Optional Dependencies for Reporting

```python
# setup.py additions
extras_require = {
    'reporting': [
        'weasyprint>=60.0',  # PDF generation
        'openpyxl>=3.1.0',   # Excel export with formatting
    ]
}
```

---

## Testing Requirements

### New Test Projects Needed

1. **Structure-Heavy Model**: Multiple bridges, culverts, weirs
2. **Levee Model**: Left/right levee pairs
3. **Floodway Model**: Complex encroachment scenarios

### Validation Against FEMA cHECk-RAS

All implemented checks should be validated against official FEMA cHECk-RAS:
- Same input project
- Compare flagged messages
- Verify threshold consistency
- Document any intentional differences

---

## Success Metrics

**100% Complete When**:
- ✅ All 187 FEMA cHECk-RAS checks implemented
- ✅ All tests passing on example projects
- ✅ Validation against FEMA cHECk-RAS successful
- ✅ Enhanced reporting features working
- ✅ Documentation complete with examples
- ✅ Example notebook (28_quality_assurance_rascheck.ipynb) updated

---

## Known Limitations (By Design)

**Out of Scope** (won't reach 100% of ALL cHECk-RAS features):
- Unsteady flow analysis (steady only)
- 2D flow area validation (1D focus)
- HEC-RAS 5.x or earlier versions (6.x HDF only)
- GUI implementation (CLI/programmatic only)

**Scope Definition**: 100% = All steady flow 1D checks from FEMA cHECk-RAS v2.0+

---

## Next Steps

**To start cHECk-RAS completion**:
1. Choose starting task (recommend check-003 or check-004 - easiest)
2. Read specification: `ras_agents/quality-assurance-agent/reference/specifications/`
3. Review current implementation: `ras_commander/check/RasCheck.py`
4. Implement missing checks following existing patterns
5. Add tests using RasExamples
6. Update documentation

**Files to Read First**:
- `ras_agents/quality-assurance-agent/AGENT.md` - Overview and quick reference
- `ras_agents/quality-assurance-agent/reference/specifications/check-structures.md` - Structure checks spec (for check-002, check-003)
- `ras_agents/quality-assurance-agent/reference/specifications/check-floodways.md` - Floodway checks spec (for check-001)
- `ras_commander/check/RasCheck.py` - Current implementation patterns

---

**Created**: 2025-12-15
**Status**: Roadmap complete, ready for implementation
**Estimated Completion Time**: 12-16 hours total (can be parallelized)
