---
description: Check ras-commander's existing API before writing new HEC-RAS automation code. Prevents duplicate implementation of functionality that already exists.
paths:
  - "**/*.py"
  - "**/*.ipynb"
---

# ras-commander First Principle

Before writing any new HEC-RAS automation code, always check whether ras-commander already provides the functionality.

## Why This Rule Exists

ras-commander is the canonical Python library for HEC-RAS automation in this codebase. New code that reimplements existing ras-commander methods:
- Creates maintenance debt (two places to fix bugs)
- Misses edge cases already handled by the library (Unicode paths, HDF locking, plan number normalization, etc.)
- Diverges from the static-class API pattern used everywhere

## What to Check First

Before writing file parsing, HDF reads, plan manipulation, or geometry ops, check:

```
ras_commander/
├── RasCmdr.py          ← plan execution (compute_plan, compute_plans)
├── RasCalibrate.py     ← calibration workflows (CalibrationPoint, RasCalibrate)
├── RasPermutation.py   ← batch permutation / parameter sweeps
├── RasPlan.py          ← plan file read/write
├── RasGeometry.py      ← geometry file operations
├── RasUtils.py         ← normalize_ras_number, path helpers
├── hdf/
│   ├── HdfResultsPlan.py     ← compute messages, plan results
│   ├── HdfResultsMesh.py     ← 2D mesh results (depth, WSE, velocity)
│   ├── HdfResultsXsec.py     ← 1D cross-section results
│   └── HdfLandCover.py       ← land cover / Manning's n
├── usgs/
│   ├── core.py               ← USGS gauge data retrieval
│   └── metrics.py            ← NSE, KGE, RMSE, MAE, pbias
├── terrain/
│   └── RasTerrainMod.py      ← terrain sampling with modifications
└── precip/
    ├── PrecipAorc.py         ← AORC historical precipitation
    └── Atlas14Grid.py        ← Atlas 14 design storms
```

## How to Apply This

1. **Describe what you need** — e.g., "read maximum WSE from 2D mesh at coordinates (x, y)"
2. **Grep ras-commander first**: `Grep pattern="def.*wse|get.*wse" path="G:/GH/ras-commander/ras_commander/"`
3. **Read the method signature** before assuming it doesn't exist
4. **Use it** — call ras-commander directly rather than writing equivalent logic

## What to Do When ras-commander Doesn't Have It

If functionality is genuinely missing:
1. Implement it using ras-commander's internal helpers (`RasUtils`, `HdfUtils`, `Decorators`)
2. Follow the static-class pattern: `class MyClass:` with `@staticmethod` methods
3. Use `@log_call` decorator from `Decorators.py`
4. Consider contributing it back to ras-commander via a feature branch

## Applied to RASAlphaCLI

This rule was written partly because RASAlphaCLI scripts (`notebooks/`, `tools/`) have repeatedly reimplemented HDF reads, plan manipulation, and path handling that already exist in ras-commander. When working in RASAlphaCLI:

```python
# BAD — reimplemented path normalization
plan_num = str(plan_number).zfill(2)

# GOOD — use ras-commander
from ras_commander import RasUtils
plan_num = RasUtils.normalize_ras_number(plan_number)
```

## Cross-References

- `.claude/rules/python/api-first-principle.md` — broader API-first guidance
- `.claude/rules/python/static-classes.md` — static class pattern
- `G:/GH/RASAlphaCLI/.claude/rules/ras-commander-first.md` — mirror rule in RASAlphaCLI
