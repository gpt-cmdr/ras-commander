# Model Validation with USGS Data

Comprehensive guide to validation metrics, interpretation guidelines, and visualization patterns for assessing HEC-RAS model performance against USGS gauge observations.

## Validation Metrics

### Nash-Sutcliffe Efficiency (NSE)

**Definition**: Measures how well modeled values match observed values relative to mean of observations.

**Formula**:
```
NSE = 1 - [Σ(Qobs - Qsim)²] / [Σ(Qobs - Qmean)²]
```

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

**Interpretation Guidelines**:
- **NSE > 0.75** - Very good (model ready for design applications)
- **0.65 < NSE ≤ 0.75** - Good (acceptable for most applications)
- **0.50 < NSE ≤ 0.65** - Satisfactory (acceptable for screening studies)
- **NSE ≤ 0.50** - Unsatisfactory (further calibration required)

**Strengths**:
- Widely used standard in hydrology
- Sensitive to peak flows
- Easy to interpret

**Limitations**:
- Sensitive to outliers
- Biased toward high flows
- Penalizes systematic over/under-prediction equally

### Kling-Gupta Efficiency (KGE)

**Definition**: Improved metric addressing NSE limitations by decomposing into correlation, bias, and variability components.

**Formula**:
```
KGE = 1 - √[(r-1)² + (α-1)² + (β-1)²]

Where:
  r = Correlation coefficient
  α = Variability ratio (σ_sim / σ_obs)
  β = Bias ratio (μ_sim / μ_obs)
```

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

**Interpretation Guidelines**:
- **KGE > 0.75** - Very good
- **0.65 < KGE ≤ 0.75** - Good
- **0.50 < KGE ≤ 0.65** - Satisfactory
- **KGE ≤ 0.50** - Unsatisfactory

**Component Interpretation**:
- **r ≈ 1**: Good timing and pattern match
- **α ≈ 1**: Similar variability (model captures flow range)
- **β ≈ 1**: Minimal bias (no systematic over/under-prediction)

**Example Diagnosis**:
```python
# KGE = 0.65, r = 0.85, α = 0.70, β = 1.05
# Interpretation:
#   - Good timing (r high)
#   - Model underestimates variability (α < 1)
#   - Slight overprediction bias (β > 1)
# Action: Increase roughness variability, check rating curves
```

**Strengths**:
- Balanced evaluation across different flow regimes
- Less sensitive to outliers than NSE
- Decomposable for diagnosis

**Limitations**:
- More complex interpretation than NSE
- Components not independent

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
    'observed_peak_time': datetime(2023, 9, 10, 14, 0),
    'modeled_peak_time': datetime(2023, 9, 10, 15, 30),
    'magnitude_error': -2500.0,
    'magnitude_error_pct': -4.8,
    'timing_error_hours': 1.5
}
```

**Interpretation Guidelines**:
- **Magnitude error < ±10%** - Good (acceptable for design)
- **Magnitude error < ±20%** - Acceptable (adequate for planning)
- **Timing error < 2 hours** - Good (for hourly data)
- **Timing error < 6 hours** - Acceptable (for daily data)

**Engineering Significance**:
- Critical for flood warning systems
- Important for dam operations
- Essential for design flood studies

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

**Interpretation Guidelines**:
- **Bias < ±5%** - Excellent water balance
- **Bias < ±10%** - Good water balance
- **Bias < ±20%** - Acceptable
- **Positive bias** - Model over-predicting (excess volume)
- **Negative bias** - Model under-predicting (deficit volume)

**Significance**:
- Critical for watershed modeling
- Important for reservoir operations
- Essential for water supply studies

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

**Returned metrics**:
```python
{
    'nse': 0.852,
    'kge': 0.878,
    'correlation': 0.935,
    'rmse': 1250.0,
    'mae': 850.0,
    'bias': -120.0,
    'peak_error_pct': -4.8,
    'timing_error_hours': 1.5,
    'volume_bias_pct': -2.3
}
```

## Validation Visualizations

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

**Plot Features**:
- Dual time series (observed in blue, modeled in red)
- Peak annotations with markers
- Statistics box with metrics (NSE, KGE, RMSE, peak error)
- Publication-quality formatting (300 DPI)
- Automatic legend and grid

**Best Practices**:
- Use descriptive title with location and event
- Include gauge number in label
- Save high-resolution PNG for reports

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

**Plot Features**:
- Scatter points colored by density
- 1:1 line (perfect agreement in black)
- Linear regression line (actual relationship in red)
- R² and regression equation annotation
- NSE and bias metrics displayed

**Interpretation**:
- Points on 1:1 line → Perfect agreement
- Points above 1:1 → Model over-predicting
- Points below 1:1 → Model under-predicting
- Tight clustering → Low scatter (good)
- Systematic offset → Bias

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

**Four Panels**:

1. **Residuals vs Time** - Detect temporal patterns
   - Random scatter → Good (unbiased errors)
   - Patterns → Systematic errors
   - Clustering → Missing physics

2. **Histogram** - Check residual distribution
   - Bell curve → Normal distribution (good)
   - Skewed → Systematic bias
   - Heavy tails → Outliers

3. **Q-Q Plot** - Test normal distribution
   - Points on diagonal → Normal distribution
   - Deviation → Non-normal errors

4. **Residuals vs Predicted** - Check heteroscedasticity
   - Random scatter → Constant variance (good)
   - Funnel shape → Variance increases with magnitude
   - Pattern → Non-linear relationship

**Interpretation Example**:
```
Panel 1: Residuals oscillate with period ~12 hours
  → Diurnal pattern (missing process or boundary condition)

Panel 2: Right-skewed distribution
  → Model tends to underpredict (negative bias)

Panel 3: Points curve above diagonal at extremes
  → Model underestimates extreme events

Panel 4: Scatter increases at high flows
  → Model uncertainty increases during floods
```

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

**Plot Features**:
- Exceedance probability (% time flow exceeded)
- Log scale for wide flow ranges
- Useful for low-flow and high-flow assessment

**Interpretation**:
- Curves match → Good across all flow regimes
- Modeled above observed at high % → Overpredict low flows
- Modeled below observed at low % → Underpredict high flows

## Validation Best Practices

### Data Preparation

1. **Align time series** - Ensure matching timestamps
   ```python
   observed_aligned, modeled_aligned = RasUsgsTimeSeries.align_timeseries(
       observed=observed_data,
       modeled=modeled_data,
       method='nearest'
   )
   ```

2. **Check for gaps** - Remove or interpolate missing data
   ```python
   gaps = RasUsgsTimeSeries.check_data_gaps(observed_data)
   if gaps['has_gaps']:
       observed_data = RasUsgsTimeSeries.fill_data_gaps(observed_data)
   ```

3. **Quality control** - Remove erroneous observations
   - Ice-affected periods
   - Malfunctioning gauges
   - Rating curve shifts

4. **Consistent units** - Verify cfs vs cms, ft vs m
   ```python
   # Convert if needed
   if units == 'cms':
       observed_flow *= 35.3147  # cms to cfs
   ```

### Metric Selection

**Use multiple metrics** - No single metric tells full story

**Recommended combinations**:
- **Flood studies**: NSE + Peak Error + Timing Error
- **Water balance**: Volume Error + KGE
- **Calibration**: KGE + RMSE + Correlation
- **Engineering design**: Peak Error + NSE

**Avoid over-reliance on NSE**:
- Can be high even with poor peak prediction
- Biased toward high flows
- Supplement with KGE and peak metrics

### Performance Thresholds

**Excellent Performance** (NSE > 0.85, KGE > 0.85):
- Peak error < ±5%
- Volume bias < ±5%
- Timing error < 1 hour
- **Status**: Model ready for design applications
- **Use**: Final design, permit applications, regulatory review

**Good Performance** (NSE > 0.75, KGE > 0.75):
- Peak error < ±10%
- Volume bias < ±10%
- Timing error < 2 hours
- **Status**: Model acceptable for most applications
- **Use**: Planning studies, alternatives analysis, screening

**Satisfactory Performance** (NSE > 0.65, KGE > 0.65):
- Peak error < ±15%
- Volume bias < ±15%
- Timing error < 3 hours
- **Status**: Model acceptable for screening studies
- **Use**: Preliminary analysis, feasibility studies

**Unsatisfactory** (NSE < 0.65, KGE < 0.65):
- Further calibration required
- Check model physics and boundary conditions
- Verify input data quality
- **Action**: Re-calibrate, review conceptual model

## Troubleshooting Common Issues

### Issue 1: Low NSE but Good Visual Fit

**Symptoms**: NSE < 0.5 but plots look reasonable

**Possible Causes**:
- Model underestimates peak (NSE penalizes heavily)
- High variability in observations
- Outliers in observed data

**Solutions**:
1. Check KGE (may be better than NSE)
2. Adjust roughness coefficients
3. Review boundary conditions
4. Remove outliers from observed data
5. Use longer calibration period

### Issue 2: Good NSE but Poor Timing

**Symptoms**: NSE > 0.75 but timing error > 3 hours

**Possible Causes**:
- Routing parameters incorrect
- Time step too large
- Wave celerity inaccurate

**Solutions**:
1. Reduce computational time step
2. Adjust routing interval in plan settings
3. Check cross section spacing
4. Verify roughness distribution

### Issue 3: Good Correlation but High Bias

**Symptoms**: r > 0.9 but bias > ±15%

**Possible Causes**:
- Systematic over/under-prediction
- Rating curve shift
- Datum error
- Uniform scaling error

**Solutions**:
1. Check rating curves at gauge locations
2. Verify datum references
3. Adjust Manning's n uniformly
4. Review cross section geometry

### Issue 4: Heteroscedastic Residuals

**Symptoms**: Residual scatter increases with magnitude

**Possible Causes**:
- Model physics break down at extremes
- Non-linear processes not captured
- Measurement errors increase with flow

**Solutions**:
1. Use different roughness for high flows
2. Check for overbank flow activation
3. Review structure operations
4. Consider rating curve uncertainty

## Example Validation Workflow

Complete validation workflow with interpretation:

```python
from ras_commander import init_ras_project, ras
from ras_commander.hdf import HdfResultsXsec
from ras_commander.usgs import (
    RasUsgsCore, RasUsgsTimeSeries, metrics, visualization
)

# Initialize and extract data
init_ras_project(r"C:\Projects\MyModel", "6.5")

observed_df = RasUsgsCore.retrieve_flow_data(
    site_no="01548010",
    start_date="2011-09-05",
    end_date="2011-09-13"
)

modeled_df = HdfResultsXsec.get_xsec_timeseries(
    "01", "Bald Eagle Cr.", "Lock Haven", "123456"
)

# Align and validate
observed_aligned, modeled_aligned = RasUsgsTimeSeries.align_timeseries(
    observed=observed_df,
    modeled=modeled_df
)

all_metrics = metrics.calculate_all_metrics(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['Flow'],
    observed_times=observed_aligned['datetime'],
    modeled_times=modeled_aligned.index,
    timestep_hours=1
)

# Generate report
print("\n" + "="*60)
print("MODEL VALIDATION SUMMARY")
print("="*60)
print(f"Event: Tropical Storm Lee (Sept 2011)")
print(f"Gauge: USGS-01548010")
print(f"\nGoodness-of-Fit:")
print(f"  NSE:     {all_metrics['nse']:.3f}")
print(f"  KGE:     {all_metrics['kge']:.3f}")
print(f"\nPeak Performance:")
print(f"  Error:   {all_metrics['peak_error_pct']:+.1f}%")
print(f"  Timing:  {all_metrics['timing_error_hours']:+.1f} hrs")
print(f"\nVolume:")
print(f"  Bias:    {all_metrics['volume_bias_pct']:+.1f}%")
print("="*60)

# Interpret
if all_metrics['nse'] > 0.85:
    print("\nVERY GOOD - Model ready for design applications")
elif all_metrics['nse'] > 0.75:
    print("\nGOOD - Model acceptable for most applications")
elif all_metrics['nse'] > 0.65:
    print("\nSATISFACTORY - Model acceptable for screening")
else:
    print("\nUNSATISFACTORY - Further calibration required")

# Generate all plots
output_dir = r"C:\Projects\MyModel\validation"
visualization.plot_timeseries_comparison(
    observed_aligned, modeled_aligned,
    title="Bald Eagle Creek Validation",
    metrics=all_metrics,
    output_file=f"{output_dir}/timeseries.png"
)
visualization.plot_scatter_comparison(
    observed_aligned['value'], modeled_aligned['Flow'],
    metrics=all_metrics,
    output_file=f"{output_dir}/scatter.png"
)
visualization.plot_residuals(
    observed_aligned['value'], modeled_aligned['Flow'],
    observed_aligned['datetime'],
    output_file=f"{output_dir}/residuals.png"
)
visualization.plot_flow_duration_curve(
    observed_aligned['value'], modeled_aligned['Flow'],
    output_file=f"{output_dir}/fdc.png"
)

print(f"\nValidation plots saved to: {output_dir}")
```

## See Also

- **Complete workflow**: [workflow.md](workflow.md)
- **Main skill**: [../SKILL.md](../SKILL.md)
- **Module documentation**: `ras_commander/usgs/CLAUDE.md`
- **Subagent reference**: `.claude/subagents/usgs-integrator/reference/validation.md`
