# Precipitation API Standardization - Cross-Repo Coordination

**Date**: 2026-01-05
**Priority**: High
**Status**: Awaiting hms-commander implementation
**Type**: Cross-repository coordination

---

## Overview

Standardizing precipitation hyetograph generation API across ras-commander and hms-commander to:
1. Use consistent `pd.DataFrame` return type with columns `['hour', 'incremental_depth', 'cumulative_depth']`
2. Enable direct integration with `RasUnsteady` file writing
3. Fix bugs in ras-commander notebooks (721 and others)

---

## Coordination Status

### Phase 1: ras-commander Analysis ✅ COMPLETE

**Completed**:
- ✅ API consistency audit completed (api-consistency-auditor agent)
- ✅ Audit report: `.claude/outputs/api-consistency-auditor/2026-01-05-precipitation-api-audit.md`
- ✅ Identified inconsistencies and integration gaps
- ✅ Created handoff document for hms-commander

### Phase 2: hms-commander Implementation ⏳ PENDING

**Handoff Document**: `C:\GH\hms-commander\agent_tasks\cross-repo\2026-01-05_ras_to_hms_precipitation-dataframe-api.md`

**Waiting for**:
- Human authorization in hms-commander repo
- hms-commander agent to implement API changes:
  - Atlas14Storm.generate_hyetograph() → returns DataFrame
  - FrequencyStorm.generate_hyetograph() → returns DataFrame + rename `total_depth` to `total_depth_inches`
  - ScsTypeStorm.generate_hyetograph() → returns DataFrame
- Completion report from hms-commander agent

**Expected timeline**: TBD (depends on human availability)

### Phase 3: ras-commander Implementation 🔲 BLOCKED

**Blocked by**: Phase 2 completion

**Tasks** (to be done after hms-commander completes):

1. **Make StormGenerator static** (BREAKING CHANGE)
   - File: `ras_commander/precip/StormGenerator.py`
   - Remove `__init__` method
   - Change `download_from_coordinates()` to return DataFrame (not instance)
   - Add `ddf_data` parameter to `generate_hyetograph()`
   - Add deprecation warning for migration path

2. **Add RasUnsteady integration method** (NEW FEATURE)
   - File: `ras_commander/RasUnsteady.py`
   - Add `set_precipitation_hyetograph()` method after line 681
   - Accept DataFrame with standard columns
   - Write to "Precipitation Hydrograph=" section in .u## files
   - Handle interval detection, validation, logging

3. **Update notebooks** (BUG FIXES)
   - `examples/720_precipitation_methods_comprehensive.ipynb` - Update StormGenerator usage
   - `examples/721_Precipitation_Hyetograph_Comparison.ipynb` - Update StormGenerator usage, remove type handling workarounds
   - `examples/722_gridded_precipitation_atlas14.ipynb` - Verify compatibility
   - Create `examples/723_precipitation_unsteady_integration.ipynb` - NEW

4. **Update documentation**
   - `ras_commander/precip/CLAUDE.md` - Update all examples, add integration section
   - `.claude/rules/hec-ras/precipitation.md` - Add RasUnsteady integration notes
   - Release notes for breaking changes

---

## Technical Specification

### Standardized DataFrame Format

All precipitation methods will return:

```python
pd.DataFrame({
    'hour': [0.5, 1.0, 1.5, ..., 24.0],      # Time from start (hours, float)
    'incremental_depth': [0.04, 0.05, ...],  # Rainfall this interval (inches, float)
    'cumulative_depth': [0.04, 0.09, ...]    # Total rainfall (inches, float)
})
```

**Column Definitions**:
- `hour`: Time in hours from storm start (end of interval)
- `incremental_depth`: Precipitation depth during this interval (inches)
- `cumulative_depth`: Cumulative precipitation from start to end of this interval (inches)

**Units Note**: Default is inches. SI units (mm) depend on HEC-RAS project units being set to metric.

### Integration with RasUnsteady (Phase 3)

**New method to add**:

```python
@staticmethod
@log_call
def set_precipitation_hyetograph(
    unsteady_file: Union[str, Path],
    hyetograph_df: pd.DataFrame,
    boundary_number: Optional[int] = None,
    ras_object: Optional[Any] = None
) -> None:
    """
    Set precipitation hyetograph in unsteady flow file from DataFrame.

    Args:
        unsteady_file: Path to unsteady flow file (.u##)
        hyetograph_df: DataFrame with columns:
            - 'hour': Time in hours
            - 'incremental_depth': Precipitation depth (inches)
            - 'cumulative_depth': Cumulative depth (inches)
        boundary_number: Optional BC number (auto-finds if None)
        ras_object: Optional RasPrj object

    Example:
        >>> from ras_commander.precip import StormGenerator
        >>> ddf = StormGenerator.download_from_coordinates(29.76, -95.37)
        >>> hyeto = StormGenerator.generate_hyetograph(
        ...     ddf_data=ddf,
        ...     total_depth_inches=17.0,
        ...     duration_hours=24
        ... )
        >>> RasUnsteady.set_precipitation_hyetograph("project.u01", hyeto)
    """
```

**Implementation location**: `ras_commander/RasUnsteady.py:681` (insert after write_table_to_file)

**What it does**:
1. Validates DataFrame has required columns
2. Finds "Precipitation Hydrograph=" section in unsteady file
3. Calculates interval from `hour` column spacing
4. Formats `incremental_depth` values as fixed-width (8.2f, 10 per line)
5. Updates unsteady file in-place
6. Logs total depth and validates conservation

---

## Files to Track

### hms-commander (external)

**Handoff document**:
- `C:\GH\hms-commander\agent_tasks\cross-repo\2026-01-05_ras_to_hms_precipitation-dataframe-api.md`

**Expected completion report**:
- `C:\GH\hms-commander\agent_tasks\cross-repo\2026-01-05_ras_to_hms_precipitation-dataframe-api_COMPLETE.md`

**Files to be modified** (by hms-commander agent):
- `hms_commander/Atlas14Storm.py`
- `hms_commander/FrequencyStorm.py`
- `hms_commander/ScsTypeStorm.py`
- `tests/test_atlas14_integration.py`
- `tests/test_scs_type.py`
- `README.md`
- `CHANGELOG.md`

### ras-commander (this repo)

**Planning documents**:
- `.claude/outputs/api-consistency-auditor/2026-01-05-precipitation-api-audit.md` (audit report)
- `agent_tasks/2026-01-05_precipitation_api_standardization.md` (this file)

**Files to be modified** (Phase 3, after hms-commander):
- `ras_commander/precip/StormGenerator.py` - Make static
- `ras_commander/RasUnsteady.py` - Add set_precipitation_hyetograph()
- `examples/720_precipitation_methods_comprehensive.ipynb` - Update usage
- `examples/721_Precipitation_Hyetograph_Comparison.ipynb` - Update usage, remove workarounds
- `examples/722_gridded_precipitation_atlas14.ipynb` - Verify
- `examples/723_precipitation_unsteady_integration.ipynb` - NEW
- `ras_commander/precip/CLAUDE.md` - Update docs
- `.claude/rules/hec-ras/precipitation.md` - Update docs

---

## Checklist

### Phase 2: hms-commander (BLOCKED - Awaiting Human)

- [ ] Human authorizes implementation request
- [ ] hms-commander agent implements DataFrame returns
- [ ] hms-commander agent renames FrequencyStorm parameter
- [ ] hms-commander agent updates tests
- [ ] hms-commander agent writes completion report
- [ ] hms-commander releases new version
- [ ] Human notifies ras-commander of completion

### Phase 3: ras-commander (BLOCKED - Awaiting Phase 2)

- [ ] Update requirements.txt with new hms-commander version
- [ ] Make StormGenerator static
- [ ] Add RasUnsteady.set_precipitation_hyetograph()
- [ ] Update notebook 720
- [ ] Update notebook 721 (remove type handling workarounds)
- [ ] Create notebook 723 (integration example)
- [ ] Update documentation
- [ ] Run all 720-series notebook tests
- [ ] Release ras-commander with coordinated changes

---

## Coordination Protocol

### Human Handoff Process

1. **ras-commander → Human**:
   - This task file documents what's needed
   - Handoff document ready in hms-commander/agent_tasks/cross-repo/

2. **Human → hms-commander Agent**:
   - Human opens hms-commander repo
   - Human authorizes implementation request
   - Human instructs hms-commander agent to proceed

3. **hms-commander Agent → Human**:
   - hms-commander agent implements changes
   - hms-commander agent writes completion report
   - hms-commander releases new version

4. **Human → ras-commander Agent**:
   - Human provides completion report location
   - Human instructs ras-commander agent to proceed with Phase 3
   - ras-commander agent completes integration

### Estimated Timeline

- **Phase 2** (hms-commander): 4-6 hours implementation + testing
- **Phase 3** (ras-commander): 8-10 hours implementation + notebook updates
- **Total**: 12-16 hours across both repos

---

## Notes

### Why This Approach?

User explicitly requested: "Do NOT wrap the hms-commander functions. Instead, write a task handoff to hms-commander agent to implement changes."

This ensures:
- Single source of truth (no wrapper layer)
- API consistency maintained long-term
- Both repos use identical interfaces
- No duplicate code maintenance

### Alternative Considered (Rejected)

Creating wrappers in ras-commander (`_hms_wrappers.py`) was rejected because:
- Adds maintenance burden
- Creates two ways to use hms-commander methods
- Doesn't fix root inconsistency
- User explicitly requested direct API change

---

**Last updated**: 2026-01-05
**Next action**: Human reviews handoff document and authorizes hms-commander implementation
