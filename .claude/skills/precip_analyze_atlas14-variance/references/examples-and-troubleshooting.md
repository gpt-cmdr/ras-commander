# Examples and Troubleshooting

Reference material for Atlas 14 spatial variance analysis — use case examples, troubleshooting, and performance tips.

## Examples by Use Case

### Use Case 1: Pre-Modeling Assessment

**Scenario**: Determine if uniform rainfall is valid before running rain-on-grid model

```python
from ras_commander.precip import Atlas14Variance

# Quick check
stats = Atlas14Variance.analyze_quick("MyProject.g01.hdf")

if stats['range_pct'] <= 10:
    print("Proceed with uniform rainfall")
    # Run HEC-RAS with single precipitation source
else:
    print("Consider spatially variable rainfall")
    # Run full analysis to quantify
```

### Use Case 2: Multi-Event Comparison

**Scenario**: Compare variance across multiple design storms

```python
results = Atlas14Variance.analyze(
    geom_hdf="MyProject.g01.hdf",
    durations=[6, 12, 24, 48],
    return_periods=[10, 25, 50, 100, 200, 500]
)

# Find highest variance event
worst = results.loc[results['range_pct'].idxmax()]
print(f"Highest variance: {worst['duration_hr']}-hr, {worst['return_period_yr']}-yr")
print(f"Range: {worst['range_pct']:.1f}%")
```

### Use Case 3: Engineering Report

**Scenario**: Generate documentation for design report

```python
# Full analysis
results = Atlas14Variance.analyze("MyProject.g01.hdf")

# Generate report with plots
report_dir = Atlas14Variance.generate_report(
    results,
    output_dir="Engineering_Report/Atlas14_Variance",
    project_name="Smith Creek Dam",
    include_plots=True
)

# Files suitable for inclusion in engineering documentation
```

### Use Case 4: Specific 2D Flow Areas

**Scenario**: Analyze variance for specific mesh areas only

```python
pfe = Atlas14Grid.get_pfe_from_project(
    geom_hdf="MyProject.g01.hdf",
    extent_source="2d_flow_area",
    mesh_area_names=["Floodplain_Upper", "Floodplain_Lower"],
    durations=[24],
    return_periods=[100]
)

# Only analyzes specified mesh areas
```

---

## Troubleshooting

### "ImportError: fsspec not installed"

**Cause**: Missing `fsspec` dependency

**Fix**:
```bash
pip install fsspec>=2023.0.0
# or
pip install --upgrade ras-commander
```

### "ValueError: No data within bounds"

**Cause**: Project extent outside CONUS coverage

**Check**:
```python
from ras_commander.hdf import HdfProject

bounds = HdfProject.get_project_bounds_latlon("project.g01.hdf")
print(f"Project bounds: {bounds}")

# Valid CONUS: lon=-125 to -66, lat=24 to 50
```

**Solution**: Project must be within Continental US

### "High variance but uniform rainfall expected"

**Possible Causes**:
1. Orographic effects (mountains causing local gradients)
2. Large model domain (>10 degree extent)
3. Edge of Atlas 14 data coverage

**Validation**:
- Compare with NOAA PFDS maps visually
- Check if variance concentrated at edges
- Consider physical geography (elevation changes)

### "IOError: Cannot access NOAA Atlas 14 CONUS NetCDF"

**Causes**:
1. Network connectivity issues
2. NOAA server temporarily down
3. Firewall blocking HTTPS

**Check**:
```python
# Test server availability
if Atlas14Grid.is_available():
    print("NOAA server reachable")
else:
    print("Cannot reach NOAA server - check network")
```

---

## Performance Tips

### 1. Use Quick Check First

Don't run full analysis unless needed:

```python
# Quick check is fast (~5 seconds)
stats = Atlas14Variance.analyze_quick("project.g01.hdf")

# Only run full analysis if variance is high
if stats['range_pct'] > 10:
    results = Atlas14Variance.analyze("project.g01.hdf")
```

### 2. Cache Coordinates

Coordinates are cached after first access:

```python
# First call downloads coordinates (~11 seconds)
pfe1 = Atlas14Grid.get_pfe_for_bounds(...)

# Subsequent calls use cache (much faster)
pfe2 = Atlas14Grid.get_pfe_for_bounds(...)

# Clear cache when done to free memory
Atlas14Grid.clear_cache()
```

### 3. Minimize Extent

Smaller extent = less data transfer:

```python
# Use 2D flow areas (smaller) instead of project extent (larger)
pfe = Atlas14Grid.get_pfe_from_project(
    geom_hdf="project.g01.hdf",
    extent_source="2d_flow_area",  # Smaller
    buffer_percent=5.0  # Minimal buffer
)
```
