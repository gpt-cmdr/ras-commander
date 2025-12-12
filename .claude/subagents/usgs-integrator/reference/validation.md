# Model Validation with USGS Data

This document covers validation metrics, interpretation, and visualization for assessing HEC-RAS model performance against USGS gauge observations.

## Overview

Model validation compares simulated results with observed data to assess model performance. The `ras_commander.usgs` module provides comprehensive validation tools including statistical metrics and publication-quality visualizations.

## Validation Metrics

### Nash-Sutcliffe Efficiency (NSE)

**Definition**: Measures how well modeled values match observed values relative to mean of observations.

**Formula**: NSE = 1 - [Σ(Qobs - Qsim)²] / [Σ(Qobs - Qmean)²]

**Range**: −∞ to 1
- **1.0** = Perfect match
- **0.0** = Model performs as well as mean of observations
- **< 0** = Mean of observations is better predictor than model

**Usage**:
```python
from ras_commander.usgs import metrics

nse = metrics.nash_sutcliffe_efficiency(
    observed=observed_flow,
    modeled=modeled_flow
)

print(f"NSE: {nse:.3f}")
```

**Interpretation**:
- **NSE > 0.75** - Very good
- **0.65 < NSE ≤ 0.75** - Good
- **0.50 < NSE ≤ 0.65** - Satisfactory
- **NSE ≤ 0.50** - Unsatisfactory

**Strengths**: Widely used standard, sensitive to peak flows

**Limitations**: Sensitive to outliers, biased toward high flows

### Kling-Gupta Efficiency (KGE)

**Definition**: Improved metric addressing NSE limitations by decomposing into correlation, bias, and variability components.

**Formula**: KGE = 1 - √[(r-1)² + (α-1)² + (β-1)²]

Where:
- **r** = Correlation coefficient
- **α** = Variability ratio (σ_sim / σ_obs)
- **β** = Bias ratio (μ_sim / μ_obs)

**Range**: −∞ to 1 (perfect = 1)

**Usage**:
```python
kge, components = metrics.kling_gupta_efficiency(
    observed=observed_flow,
    modeled=modeled_flow,
    return_components=True
)

print(f"KGE: {kge:.3f}")
print(f"  Correlation (r): {components['r']:.3f}")
print(f"  Variability (α): {components['alpha']:.3f}")
print(f"  Bias (β):        {components['beta']:.3f}")
```

**Interpretation**:
- **KGE > 0.75** - Very good
- **0.65 < KGE ≤ 0.75** - Good
- **0.50 < KGE ≤ 0.65** - Satisfactory
- **KGE ≤ 0.50** - Unsatisfactory

**Components**:
- **r ≈ 1**: Good timing and pattern match
- **α ≈ 1**: Similar variability
- **β ≈ 1**: Minimal bias

**Strengths**: Balanced evaluation, less sensitive to outliers, decomposable

**Limitations**: More complex interpretation than NSE

### Peak Error

**Definition**: Compares peak magnitude and timing between observed and modeled events.

**Usage**:
```python
peak_error = metrics.calculate_peak_error(
    observed=observed_flow,
    modeled=modeled_flow,
    observed_times=observed_timestamps,
    modeled_times=modeled_timestamps
)

print(f"Peak Error:")
print(f"  Observed peak:  {peak_error['observed_peak']:,.0f} cfs at {peak_error['observed_peak_time']}")
print(f"  Modeled peak:   {peak_error['modeled_peak']:,.0f} cfs at {peak_error['modeled_peak_time']}")
print(f"  Magnitude error: {peak_error['magnitude_error_pct']:.1f}%")
print(f"  Timing error:   {peak_error['timing_error_hours']:.1f} hours")
```

**Returns**:
```python
{
    'observed_peak': 52300.0,
    'modeled_peak': 49800.0,
    'observed_peak_time': datetime(...),
    'modeled_peak_time': datetime(...),
    'magnitude_error': -2500.0,
    'magnitude_error_pct': -4.8,
    'timing_error_hours': 1.5
}
```

**Interpretation**:
- **Magnitude error < ±10%** - Good
- **Magnitude error < ±20%** - Acceptable
- **Timing error < 2 hours** - Good (for hourly data)
- **Timing error < 6 hours** - Acceptable (for daily data)

### Volume Error

**Definition**: Compares total volume (cumulative flow) over simulation period.

**Usage**:
```python
volume_error = metrics.calculate_volume_error(
    observed=observed_flow,
    modeled=modeled_flow,
    timestep_hours=1  # Interval between observations
)

print(f"Volume Error:")
print(f"  Observed volume: {volume_error['observed_volume']:,.0f} cfs-hr")
print(f"  Modeled volume:  {volume_error['modeled_volume']:,.0f} cfs-hr")
print(f"  Bias:            {volume_error['bias_pct']:.1f}%")
```

**Interpretation**:
- **Bias < ±5%** - Excellent water balance
- **Bias < ±10%** - Good water balance
- **Bias < ±20%** - Acceptable
- **Positive bias** - Model over-predicting
- **Negative bias** - Model under-predicting

### Comprehensive Metrics Suite

Calculate all metrics at once:

```python
all_metrics = metrics.calculate_all_metrics(
    observed=observed_flow,
    modeled=modeled_flow,
    observed_times=observed_timestamps,
    modeled_times=modeled_timestamps,
    timestep_hours=1
)

print("Validation Metrics Summary:")
print(f"  NSE:            {all_metrics['nse']:.3f}")
print(f"  KGE:            {all_metrics['kge']:.3f}")
print(f"  Correlation:    {all_metrics['correlation']:.3f}")
print(f"  RMSE:           {all_metrics['rmse']:.0f} cfs")
print(f"  MAE:            {all_metrics['mae']:.0f} cfs")
print(f"  Peak Error:     {all_metrics['peak_error_pct']:.1f}%")
print(f"  Timing Error:   {all_metrics['timing_error_hours']:.1f} hrs")
print(f"  Volume Bias:    {all_metrics['volume_bias_pct']:.1f}%")
```

## Visualization

### Time Series Comparison

Publication-quality observed vs modeled time series:

```python
from ras_commander.usgs import visualization

fig = visualization.plot_timeseries_comparison(
    observed=observed_df,
    modeled=modeled_df,
    title="Bald Eagle Creek at Lock Haven, PA - Tropical Storm Lee 2011",
    metrics=all_metrics,
    observed_label="USGS-01548010 Observed",
    modeled_label="HEC-RAS Modeled",
    ylabel="Discharge (cfs)",
    output_file="validation_timeseries.png"
)
```

**Features**:
- Dual time series (observed in blue, modeled in red)
- Peak annotations with markers
- Statistics box with metrics
- Publication-quality formatting
- Automatic legend and grid

### Scatter Plot with 1:1 Line

Scatter comparison showing modeled vs observed correlation:

```python
fig = visualization.plot_scatter_comparison(
    observed=observed_flow,
    modeled=modeled_flow,
    title="Observed vs Modeled Flow",
    metrics=all_metrics,
    output_file="validation_scatter.png"
)
```

**Features**:
- Scatter points colored by density
- 1:1 line (perfect agreement)
- Linear regression line
- R² and equation annotation
- NSE and bias metrics

### Residual Diagnostics

Comprehensive 4-panel residual analysis:

```python
fig = visualization.plot_residuals(
    observed=observed_flow,
    modeled=modeled_flow,
    observed_times=observed_timestamps,
    output_file="validation_residuals.png"
)
```

**Four panels**:
1. **Time Series** - Residuals over time (detect temporal patterns)
2. **Histogram** - Residual distribution (check normality)
3. **Q-Q Plot** - Quantile-quantile (test normal distribution)
4. **Scatter** - Residuals vs predicted (check heteroscedasticity)

**Interpretation**:
- **Random scatter** - Good model
- **Patterns** - Systematic errors (bias or missing physics)
- **Normal distribution** - Unbiased errors
- **Heteroscedasticity** - Error variance changes with magnitude

### Flow Duration Curve

Compare flow exceedance probabilities:

```python
fig = visualization.plot_flow_duration_curve(
    observed=observed_flow,
    modeled=modeled_flow,
    title="Flow Duration Curve Comparison",
    output_file="validation_fdc.png"
)
```

**Features**:
- Exceedance probability (% time flow exceeded)
- Log scale for wide flow ranges
- Useful for low-flow and high-flow assessment

## Complete Validation Workflow

Example workflow from data retrieval to final report:

```python
from ras_commander import init_ras_project, ras
from ras_commander.hdf import HdfResultsXsec
from ras_commander.usgs import (
    RasUsgsCore, RasUsgsTimeSeries, metrics, visualization
)
from datetime import datetime

# 1. Initialize project
init_ras_project("/path/to/project", "6.5")

# 2. Retrieve observed data
observed_df = RasUsgsCore.retrieve_flow_data(
    site_no="01548010",
    start_date="2011-09-05",
    end_date="2011-09-13",
    service='iv'
)

# 3. Extract modeled results
modeled_df = HdfResultsXsec.get_xsec_timeseries(
    plan_number="01",
    river="Bald Eagle Cr.",
    reach="Lock Haven",
    rs="123456"
)

# 4. Align time series
observed_aligned, modeled_aligned = RasUsgsTimeSeries.align_timeseries(
    observed=observed_df,
    modeled=modeled_df,
    method='nearest'
)

# 5. Calculate all metrics
all_metrics = metrics.calculate_all_metrics(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    observed_times=observed_aligned['datetime'],
    modeled_times=modeled_aligned['datetime'],
    timestep_hours=1
)

# 6. Print summary
print("\n" + "="*60)
print("MODEL VALIDATION SUMMARY")
print("="*60)
print(f"Gauge: USGS-01548010")
print(f"Event: Tropical Storm Lee (Sept 2011)")
print(f"Observations: {len(observed_aligned)}")
print("\nGoodness-of-Fit Metrics:")
print(f"  NSE:              {all_metrics['nse']:.3f}")
print(f"  KGE:              {all_metrics['kge']:.3f}")
print(f"  Correlation (r):  {all_metrics['correlation']:.3f}")
print("\nError Metrics:")
print(f"  RMSE:             {all_metrics['rmse']:,.0f} cfs")
print(f"  MAE:              {all_metrics['mae']:,.0f} cfs")
print(f"  Mean Bias:        {all_metrics['bias']:+,.0f} cfs")
print("\nPeak Performance:")
print(f"  Peak Error:       {all_metrics['peak_error_pct']:+.1f}%")
print(f"  Timing Error:     {all_metrics['timing_error_hours']:+.1f} hours")
print("\nVolume Balance:")
print(f"  Volume Bias:      {all_metrics['volume_bias_pct']:+.1f}%")
print("="*60 + "\n")

# 7. Generate all validation plots
output_dir = "/path/to/validation_output"

# Time series comparison
visualization.plot_timeseries_comparison(
    observed=observed_aligned,
    modeled=modeled_aligned,
    title="Bald Eagle Creek Validation - Tropical Storm Lee 2011",
    metrics=all_metrics,
    output_file=f"{output_dir}/timeseries.png"
)

# Scatter plot
visualization.plot_scatter_comparison(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    title="Observed vs Modeled Flow",
    metrics=all_metrics,
    output_file=f"{output_dir}/scatter.png"
)

# Residual diagnostics
visualization.plot_residuals(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    observed_times=observed_aligned['datetime'],
    output_file=f"{output_dir}/residuals.png"
)

# Flow duration curve
visualization.plot_flow_duration_curve(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    output_file=f"{output_dir}/fdc.png"
)

print(f"Validation plots saved to: {output_dir}")
```

## Validation Best Practices

### Data Preparation
1. **Align time series** - Ensure observed and modeled data have matching timestamps
2. **Check for gaps** - Remove or interpolate missing data
3. **Quality control** - Remove erroneous observations (ice-affected, malfunctioning gauges)
4. **Consistent units** - Verify cfs vs cms, ft vs m

### Metric Selection
1. **Use multiple metrics** - No single metric tells full story
2. **NSE for peaks** - Good for flood studies
3. **KGE for balanced** - Good for calibration
4. **Volume for water balance** - Critical for watershed modeling
5. **Peak error for engineering** - Important for design events

### Interpretation Guidelines

**Excellent Performance** (NSE > 0.85, KGE > 0.85):
- Peak error < ±5%
- Volume bias < ±5%
- Timing error < 1 hour
- Model ready for design applications

**Good Performance** (NSE > 0.75, KGE > 0.75):
- Peak error < ±10%
- Volume bias < ±10%
- Timing error < 2 hours
- Model acceptable for most applications

**Satisfactory Performance** (NSE > 0.65, KGE > 0.65):
- Peak error < ±15%
- Volume bias < ±15%
- Timing error < 3 hours
- Model acceptable for screening studies

**Unsatisfactory** (NSE < 0.65, KGE < 0.65):
- Further calibration required
- Check model physics and boundary conditions
- Verify input data quality

### Common Issues and Solutions

**Issue**: Low NSE but good visual fit
- **Cause**: Model underestimates peak
- **Solution**: Adjust roughness, check boundary conditions

**Issue**: Good NSE but poor timing
- **Cause**: Routing parameters incorrect
- **Solution**: Adjust time step, check computational interval

**Issue**: Good correlation but high bias
- **Cause**: Systematic over/under-prediction
- **Solution**: Check rating curves, verify datum

**Issue**: Random residuals but low NSE
- **Cause**: High variability in observations
- **Solution**: Check data quality, consider longer calibration period

## Related Documentation

- **Complete workflow**: `reference/end-to-end.md`
- **Real-time monitoring**: `reference/real-time.md`
- **Primary module docs**: `ras_commander/usgs/CLAUDE.md`
- **Example notebooks**:
  - `examples/32_model_validation_with_usgs.ipynb`
  - `examples/29_usgs_gauge_data_integration.ipynb`
