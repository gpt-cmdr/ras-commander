# Commit Ready - Precipitation API Standardization

**Date**: 2026-01-06
**Version**: v0.88.0 (suggested)
**Type**: Feature + Breaking Change

---

## Commit Message (Suggested)

```
Standardize precipitation API and add RasUnsteady integration

BREAKING CHANGES:
- StormGenerator now static (instance-based usage deprecated, removed in v0.89.0)
- Requires hms-commander>=0.2.0 (DataFrame returns)

NEW FEATURES:
- RasUnsteady.set_precipitation_hyetograph() - One-line integration to unsteady files
- Spatial analysis maps in notebook 722
- Pre-execution validation in notebook 721

BUG FIXES:
- Fixed return period indexing in notebook 722 (critical - was showing 2-year instead of 100-year data)
- Fixed mesh polygon visualization in notebook 722
- Fixed parallel execution file locking in notebook 721
- Fixed HDF path resolution after compute_parallel()
- Fixed multiple type handling bugs across 720-series notebooks

ENHANCEMENTS:
- All precipitation methods return consistent DataFrame format
- 30 new tests (100% passing)
- Comprehensive debug/validation cells in notebooks

See agent_tasks/2026-01-05_precipitation_api_standardization_COMPLETE.md for details
```

---

## Files to Commit

### Core Library Changes (5 files)

**Modified**:
1. `setup.py` - hms-commander dependency 0.1.0 → 0.2.0
2. `ras_commander/precip/StormGenerator.py` - Static conversion, deprecation warning
3. `ras_commander/RasUnsteady.py` - Added set_precipitation_hyetograph() method
4. `ras_commander/precip/__init__.py` - Updated examples
5. `ras_commander/precip/CLAUDE.md` - Complete StormGenerator section rewrite, integration examples

### Tests (2 NEW files)

**Created**:
6. `tests/test_storm_generator_static.py` - 12 tests for static pattern
7. `tests/test_rasunsteady_precipitation.py` - 18 tests for integration method

### Notebooks (3 files - Moved from old to new)

**Modified** (previously deleted, now replaced):
8. `examples/720_precipitation_methods_comprehensive.ipynb` - DataFrame API updates
9. `examples/721_Precipitation_Hyetograph_Comparison.ipynb` - Debugged, enhanced, simplified
10. `examples/722_gridded_precipitation_atlas14.ipynb` - Spatial maps, bug fixes

### Documentation/Rules (2 files)

**Created**:
11. `.claude/rules/documentation/precipitation-notebook-debugging-patterns.md` - Lessons learned
12. `.claude/rules/testing/precipitation-method-validation.md` - Validation patterns

**Modified**:
13. `.claude/rules/hec-ras/precipitation.md` - RasUnsteady integration section, static API examples

### Task Tracking (3 files)

**Created**:
14. `.claude/outputs/api-consistency-auditor/2026-01-05-precipitation-api-audit.md`
15. `agent_tasks/2026-01-05_precipitation_api_standardization.md`
16. `agent_tasks/2026-01-05_precipitation_api_standardization_COMPLETE.md`

17. `.claude/outputs/2026-01-05_precipitation_api_standardization_session_closeout.md`
18. `.claude/outputs/general-purpose/2026-01-06-notebook-722-spatial-analysis-diagnosis.md`

### Build/Config (1 file)
19. `.gitignore` - Updated for new working artifacts

---

## Files Moved to .old/ (Not in Commit)

**Moved during session cleanup**:
- `.old/working/notebook_runs_2026-01-05_precipitation_api/` - Test artifacts (consolidated into completion report)

**Already in .old/** (from previous sessions):
- `examples/.old/720_atlas14_aep_events.OLD.ipynb` - Reference for integration pattern
- Other deprecated notebooks

---

## Files to Exclude from Commit

**Unrelated**:
- `agent_tasks/BACKLOG.md` - General backlog, not specific to this task
- `.claude/agents/code-oracle-*.md` - Unrelated agents
- `.env.example` - Unrelated configuration
- `examples/914_historical_event_validation.ipynb` - Unrelated notebook
- `examples/95*_ebfe_*.ipynb` - Unrelated eBFE notebooks

**These should be committed separately** or are work-in-progress from other sessions.

---

## Test Status Before Commit

Run final validation:

```bash
# Unit tests
pytest tests/test_storm_generator_static.py tests/test_rasunsteady_precipitation.py -v

# Notebook tests (logic only, EXECUTE_PLANS=False)
pytest --nbmake examples/720_precipitation_methods_comprehensive.ipynb -v
pytest --nbmake examples/721_Precipitation_Hyetograph_Comparison.ipynb -v
pytest --nbmake examples/722_gridded_precipitation_atlas14.ipynb -v
```

**Expected**: 33/33 tests passing, 3/3 notebooks passing

**Actual** (from session):
- ✅ StormGenerator: 12/12 passing
- ✅ RasUnsteady: 18/18 passing
- ✅ Notebook 720: Passing
- ✅ Notebook 721: Passing (logic test)
- ✅ Notebook 722: Passing

---

## Breaking Changes for CHANGELOG

### StormGenerator API Change (v0.88.0)

**Breaking**: Instance-based usage deprecated

**Migration**:
```python
# OLD (deprecated in v0.88.0, removed in v0.89.0)
gen = StormGenerator.download_from_coordinates(lat, lon)
hyeto = gen.generate_hyetograph(total_depth_inches=17.0, duration_hours=24)

# NEW
ddf = StormGenerator.download_from_coordinates(lat, lon)
hyeto = StormGenerator.generate_hyetograph(ddf_data=ddf, total_depth_inches=17.0, duration_hours=24)
```

### HMS-Commander Dependency (v0.88.0)

**Breaking**: Requires hms-commander>=0.2.0

**Impact**: HMS methods now return DataFrame (not ndarray)

**Migration**:
```python
# OLD (hms-commander v0.1.x)
hyeto = Atlas14Storm.generate_hyetograph(...)
total = hyeto.sum()

# NEW (hms-commander v0.2.0)
hyeto = Atlas14Storm.generate_hyetograph(...)
total = hyeto['incremental_depth'].sum()
```

---

## Ready for Commit

**All files tested and validated**
**All documentation updated**
**All tests passing**
**Breaking changes documented**

**Recommended commit**: Include core library + tests + notebooks + docs as single atomic change

---

**Prepared**: 2026-01-06
**Status**: Ready for human review and commit
