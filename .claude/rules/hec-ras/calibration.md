---
description: RasCalibrate patterns — CalibrationPoint setup, metric selection, extraction methods, and optimization workflow
paths:
  - ras_commander/RasCalibrate.py
  - ras_commander/usgs/metrics.py
---

# HEC-RAS Calibration Rules

## CalibrationPoint Construction

Always use the `CalibrationPoint` dataclass directly — do not build dicts and pass to `RasCalibrate` unless you prefer the dict-coercion path.

```python
from ras_commander import CalibrationPoint

pt = CalibrationPoint(
    name="Gauge_12040104",
    variable="wse",                    # wse | flow | depth | velocity
    extraction_method="ref_point",     # 1d_xs | 2d_cell | ref_line | ref_point
    observed=42.3,                     # scalar → time_index required; Series → full-series mode
    ref_feature_name="Gauge_12040104",
    metric="nse",                      # nse | kge | rmse | mae | pbias
    weight=1.0,
    time_index="max",                  # "max" = peak value; None/"all" = full time series
)
```

**Extraction method requirements**:

| Method | Required fields |
|--------|----------------|
| `1d_xs` | `river`, `reach`, `station` |
| `2d_cell` | `x`, `y` (projected CRS matching model) |
| `ref_line` | `ref_feature_name` |
| `ref_point` | `ref_feature_name` |

## Metric Selection

| Metric | Direction | Use when |
|--------|-----------|----------|
| `nse` | higher is better | Peak discharge / WSE time series — primary calibration metric |
| `kge` | higher is better | Balanced bias + timing — use alongside NSE for USGS gauge matching |
| `rmse` | lower is better | Absolute error in physical units — use for WSE vs. survey data |
| `mae` | lower is better | Outlier-robust error |
| `pbias` | lower is better | Volume bias check |

**Default**: use `nse` for first-pass calibration. Add `kge` as a secondary metric (weight = 0.5) when timing matters as well as magnitude.

## time_index Rules

- `time_index="max"` — extracts the peak (scalar) value. Use with scalar `observed`.
- `time_index=None` (or `"all"` / `"series"`) — extracts full time series. Use with `pd.Series` `observed`.
- Integer: extracts a specific time step index. Rarely used outside unit tests.
- **Mismatch error**: scalar `observed` + full-series `time_index` → raises `ValueError`. Always pair correctly.

## Scipy Optimization

`RasCalibrate` supports these `scipy.optimize.minimize` methods:

```python
from ras_commander import RasCalibrate

result = RasCalibrate.optimize(
    calibration_points=points,
    param_bounds={"mannings_n": (0.025, 0.06), "infiltration_rate": (0.01, 0.10)},
    method="nelder-mead",    # Start with nelder-mead; switch to l-bfgs-b for many params
    max_iter=50,
    plan_number="01",
)
```

**Method guidance**:
- `nelder-mead`: good for 1–5 parameters, no gradient required. Default starting point.
- `powell`: good for separable objectives.
- `l-bfgs-b`: efficient for 5+ parameters; requires well-behaved objective.
- `slsqp`: use when you have inequality constraints (e.g., Manning's n ≥ 0.025).

## Batch Calibration Pattern

RasCalibrate composes `RasPermutation` internally. Each optimizer iteration runs a full HEC-RAS compute. For expensive calibration runs:

1. Start with a coarse Nelder-Mead pass (10–20 iterations) to identify the basin
2. Use the best result as the starting point for a refinement pass
3. Always read compute messages after each run — calibration errors often manifest as convergence failures, not Python exceptions

```python
# After calibration, always inspect messages
from ras_commander import HdfResultsPlan
msgs = HdfResultsPlan.get_compute_messages(plan_number="01")
errors = [l for l in msgs if "ERROR" in l.upper()]
if errors:
    raise RuntimeError(f"Model errors during calibration: {errors[:5]}")
```

## Composite Objectives

When using multiple calibration points, each point's metric is computed separately and then weighted:

```python
points = [
    CalibrationPoint(name="Q_upstream", variable="flow", ..., weight=2.0, metric="nse"),
    CalibrationPoint(name="WSE_mid",    variable="wse",  ..., weight=1.0, metric="rmse"),
    CalibrationPoint(name="WSE_down",   variable="wse",  ..., weight=1.0, metric="rmse"),
]
```

Higher weight = more influence on the objective. Normalize weights when in doubt (sum to 1).

## Cross-References

- `ras_commander/RasCalibrate.py` — CalibrationPoint, RasCalibrate class, _SCIPY_METHODS
- `ras_commander/usgs/metrics.py` — calculate_all_metrics, nash_sutcliffe_efficiency, kling_gupta_efficiency
- `ras_commander/RasPermutation.py` — underlying batch execution engine
- `.claude/rules/hec-ras/execution.md` — mandatory Post-Execution Protocol for compute messages
- `.claude/rules/hec-ras/usgs.md` — USGS gauge integration for observed data sourcing
