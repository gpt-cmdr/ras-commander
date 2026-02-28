# Atlas 14 Precipitation

NOAA Atlas 14 provides official precipitation frequency estimates for design storm modeling in the United States. The ras-commander precipitation subpackage provides four hyetograph generation methods and two spatial analysis tools for integrating Atlas 14 data into HEC-RAS workflows.

## Overview

Atlas 14 is the authoritative source for precipitation frequency estimates, used for:

- Regulatory floodplain mapping (1% AEP / 100-year events)
- Infrastructure design (drainage, culverts, bridges)
- Dam breach inundation studies (PMF, 0.2% AEP)
- Sensitivity analysis across multiple AEP events

**Important**: ras-commander hyetograph methods take `total_depth_inches` as an **input parameter**. You specify the depth from the NOAA PFDS website for your location and AEP; the methods generate the temporal distribution for that depth. They do not automatically query NOAA for depth values.

Verify Atlas 14 depths at: https://hdsc.nws.noaa.gov/pfds/pfds_map_cont.html

## Quick Start

Generate a 24-hour, 1% AEP (100-year) design storm using the Alternating Block Method:

```python
from ras_commander.precip import StormGenerator

# Step 1: Download DDF data for the temporal pattern (returns DataFrame)
# This queries the NOAA DDF tables used for temporal shape only
ddf_data = StormGenerator.download_from_coordinates(29.76, -95.37)  # Houston, TX

# Step 2: Generate hyetograph with your Atlas 14 depth from NOAA PFDS
# (e.g., 17.0 inches for Houston 100-yr 24-hr, from hdsc.nws.noaa.gov/pfds)
hyeto = StormGenerator.generate_hyetograph(
    ddf_data=ddf_data,
    total_depth_inches=17.0,   # Your Atlas 14 depth from NOAA PFDS
    duration_hours=24,
    position_percent=50        # Peak at 50% of storm (centered)
)

# hyeto is a DataFrame with columns: hour, incremental_depth, cumulative_depth
print(f"Total: {hyeto['cumulative_depth'].iloc[-1]:.6f} inches")  # Exact: 17.000000
```

For HMS-equivalent results, use `Atlas14Storm` from hms-commander:

```python
from ras_commander.precip import Atlas14Storm, ATLAS14_AVAILABLE

if ATLAS14_AVAILABLE:
    hyeto = Atlas14Storm.generate_hyetograph(
        total_depth_inches=17.0,   # Your Atlas 14 depth from NOAA PFDS
        state="tx",
        region=3,
        aep_percent=1.0,
        quartile="All Cases"
    )
    print(f"Total: {hyeto['cumulative_depth'].iloc[-1]:.6f} inches")  # Exact: 17.000000
```

## Method Selection Guide

### Summary Table

| Method | HMS Equivalent | Depth Conservation | Durations | Best For |
|--------|----------------|-------------------|-----------|----------|
| **Atlas14Storm** | YES (10^-6) | Exact | 6h, 12h, 24h, 96h | Modern Atlas 14, regulatory submittals |
| **FrequencyStorm** | YES (10^-6) | Exact | 6-48hr | TP-40 legacy data, variable duration, 48hr gap |
| **ScsTypeStorm** | YES (10^-6) | Exact | 24hr only | SCS Type I/IA/II/III distributions |
| **StormGenerator** | NO | Exact | Any | Flexible peak positioning (0-100%) |

### Decision Tree

```
Need precipitation hyetograph for HEC-RAS?
|
+- Need HMS-equivalent results?
|  |
|  +- Modern Atlas 14 (6h, 12h, 24h, or 96h)?
|  |  --> Use Atlas14Storm
|  |
|  +- TP-40 or variable duration (6-48hr, including 48hr)?
|  |  --> Use FrequencyStorm
|  |
|  +- SCS Type I/IA/II/III (24hr only)?
|     --> Use ScsTypeStorm
|
+- Need flexible peak positioning (0-100%)?
   --> Use StormGenerator
```

### Known Duration Limitations

**48-hour duration**: `Atlas14Storm` does not support 48-hour (NOAA does not publish 48h temporal CSVs). Use `FrequencyStorm` for 48-hour HMS-equivalent storms.

**Duration coverage**:
- 6h: Atlas14Storm or FrequencyStorm
- 12h: Atlas14Storm or FrequencyStorm
- 24h: Atlas14Storm, FrequencyStorm, or ScsTypeStorm
- 48h: FrequencyStorm only
- 96h: Atlas14Storm only

## Standard AEP Events

Common AEP events for design and regulatory analysis:

| AEP | Return Period | Typical Application |
|-----|---------------|---------------------|
| **50%** | 2-year | Frequent flooding, erosion, minor drainage |
| **20%** | 5-year | Storm sewer design, minor structures |
| **10%** | 10-year | Regulatory (some jurisdictions), street flooding |
| **4%** | 25-year | Floodplain management, local regulations |
| **2%** | 50-year | Infrastructure design, bridge hydraulics |
| **1%** | 100-year | **FEMA regulatory**, base flood elevation |
| **0.5%** | 200-year | Critical infrastructure, freeboard calculations |
| **0.2%** | 500-year | High-hazard dams, PMF approximation |

## Method Details

### StormGenerator (Alternating Block Method)

Native ras-commander method using the Alternating Block Method (Chow, Maidment, Mays 1988). DDF data controls the temporal shape only; actual depth comes from `total_depth_inches`.

**Key characteristics**:
- Flexible peak positioning (0% to 100% of storm duration)
- NOT HMS-equivalent (different temporal algorithm)
- Exact depth conservation via scaling
- Any duration supported

```python
from ras_commander.precip import StormGenerator

# Download DDF data (used for temporal pattern shape)
ddf_data = StormGenerator.download_from_coordinates(
    lat=29.76,
    lon=-95.37
)

# Generate with peak at 50% (centered), a common engineering choice
hyeto_centered = StormGenerator.generate_hyetograph(
    ddf_data=ddf_data,
    total_depth_inches=17.0,
    duration_hours=24,
    position_percent=50     # Peak centered at hour 12
)

# Generate with peak at 25% (early peak, more conservative)
hyeto_early = StormGenerator.generate_hyetograph(
    ddf_data=ddf_data,
    total_depth_inches=17.0,
    duration_hours=24,
    position_percent=25     # Peak at hour 6
)

# Return value: DataFrame with columns hour, incremental_depth, cumulative_depth
print(hyeto_centered.columns.tolist())
# ['hour', 'incremental_depth', 'cumulative_depth']
```

**Supporting methods**:
- `StormGenerator.load_csv(csv_file)` - Load DDF data from CSV
- `StormGenerator.validate_hyetograph(hyetograph, expected_total_depth)` - Verify depth
- `StormGenerator.generate_all(ddf_data, events, ...)` - Batch generate multiple events
- `StormGenerator.save_hyetograph(hyetograph, output_path, format)` - Save to CSV or HEC-RAS format

### Atlas14Storm (HMS-Equivalent)

Imported from `hms-commander`. Matches HEC-RAS/HMS "Specified Pattern" at 10^-6 precision using official NOAA Atlas 14 temporal distributions.

**Requires**: `hms-commander>=0.1.0` (installed automatically with ras-commander).

```python
from ras_commander.precip import Atlas14Storm, ATLAS14_AVAILABLE

if ATLAS14_AVAILABLE:
    # Generate HMS-equivalent hyetograph
    # total_depth_inches comes from NOAA PFDS for your location and AEP
    hyeto = Atlas14Storm.generate_hyetograph(
        total_depth_inches=17.0,   # From NOAA PFDS
        state="tx",
        region=3,
        aep_percent=1.0,           # 1.0 = 100-year, 2.0 = 50-year, etc.
        quartile="All Cases"
    )

    total = hyeto['cumulative_depth'].iloc[-1]
    print(f"Total depth: {total:.6f} inches")   # Exact: 17.000000

# Check availability without importing conditionally
from ras_commander.precip import ATLAS14_AVAILABLE
if not ATLAS14_AVAILABLE:
    print("hms-commander not installed: pip install hms-commander")
```

**Quartile options**: "First Quartile", "Second Quartile", "Third Quartile", "Fourth Quartile", "All Cases"

**Supported durations**: 6h, 12h, 24h, 96h (no 48h - use FrequencyStorm instead)

### FrequencyStorm (HMS-Equivalent, TP-40)

Imported from `hms-commander`. TP-40/Hydro-35 pattern, HMS-equivalent for variable durations from 6 to 48 hours. Fill the 48-hour gap left by Atlas14Storm.

```python
from ras_commander.precip import FrequencyStorm, FREQUENCY_STORM_AVAILABLE

if FREQUENCY_STORM_AVAILABLE:
    # 24-hour storm (TP-40 defaults: 5-min interval, 67% peak position)
    hyeto_24hr = FrequencyStorm.generate_hyetograph(
        total_depth=13.20         # From NOAA PFDS for your location
    )

    # 6-hour storm with explicit parameters
    hyeto_6hr = FrequencyStorm.generate_hyetograph(
        total_depth=9.10,
        total_duration_min=360,   # 6 hours
        time_interval_min=5
    )

    # 48-hour storm (not available in Atlas14Storm)
    hyeto_48hr = FrequencyStorm.generate_hyetograph(
        total_depth=20.5,
        total_duration_min=2880,  # 48 hours
        time_interval_min=60
    )

    total = hyeto_24hr['cumulative_depth'].iloc[-1]
    print(f"Total: {total:.6f} inches")   # Exact depth conservation
```

**Use FrequencyStorm when**:
- Working with legacy TP-40 data (Houston area and similar)
- Need 48-hour duration HMS-equivalent storms
- Need variable duration between 6-48 hours

### ScsTypeStorm (HMS-Equivalent, SCS Distributions)

Imported from `hms-commander`. Implements SCS Type I, IA, II, and III temporal distributions extracted from HEC-HMS 4.13 source code.

**SCS type guide**:
- **Type I**: Pacific maritime climate (early peak ~42%)
- **Type IA**: Coastal areas, Atlantic/Gulf (early peak ~33%)
- **Type II**: Most of US, central and eastern states (peak ~50%)
- **Type III**: Gulf Coast, Florida, tropical/subtropical (late peak ~50%)

```python
from ras_commander.precip import ScsTypeStorm, SCS_TYPE_AVAILABLE

if SCS_TYPE_AVAILABLE:
    # SCS Type II (most common for central/eastern US)
    hyeto_ii = ScsTypeStorm.generate_hyetograph(
        total_depth_inches=10.0,
        scs_type='II',
        time_interval_min=60
    )
    print(f"Total: {hyeto_ii['cumulative_depth'].iloc[-1]:.6f} inches")  # Exact: 10.000000

    # Gulf Coast application
    hyeto_iii = ScsTypeStorm.generate_hyetograph(
        total_depth_inches=10.0,
        scs_type='III',
        time_interval_min=60
    )

    # Generate all 4 types at once
    all_types = ScsTypeStorm.generate_all_types(
        total_depth_inches=10.0,
        time_interval_min=60
    )
    for scs_type, hyeto in all_types.items():
        peak = hyeto['incremental_depth'].max()
        print(f"Type {scs_type}: peak = {peak:.4f} in/hr")
```

**SCS type options**: `'I'`, `'IA'`, `'II'`, `'III'` (case-insensitive)

**Constraint**: 24-hour duration only (HMS constraint, matches TR-55 specification)

## Atlas 14 Grid and Spatial Variance

### Atlas14Grid - Remote Grid Access

Downloads only data within your project extent using HTTP byte-range requests. Achieves ~99.9% data reduction compared to full state dataset downloads.

**Data specifications**:
- Coverage: CONUS (24N-50N, 125W-66W)
- Resolution: ~0.0083 degrees (~830m)
- Durations: 1, 2, 3, 6, 12, 24, 48, 72, 96, 168 hours
- Return periods: 2, 5, 10, 25, 50, 100, 200, 500, 1000 years
- Performance: ~5-15 seconds for a typical project extent

```python
from ras_commander.precip import Atlas14Grid

# Get PFE data for HEC-RAS project extent
pfe = Atlas14Grid.get_pfe_from_project(
    geom_hdf="MyProject.g01.hdf",
    extent_source="2d_flow_area",  # or "project_extent"
    durations=[6, 12, 24],
    return_periods=[10, 50, 100]
)

# Access data
lat = pfe['lat']
lon = pfe['lon']
ari = pfe['ari']   # Return period array (e.g., [10, 50, 100])

# Use dynamic indexing to find the correct return period index
import numpy as np
target_rp = 100
ari_idx = np.argmin(np.abs(ari - target_rp))
print(f"Using {ari[ari_idx]}-year (index {ari_idx})")

# 100-year, 24-hour max precipitation over project
precip_100yr_24hr = pfe['pfe_24hr'][:, :, ari_idx]
print(f"Max: {np.nanmax(precip_100yr_24hr):.2f} inches")
print(f"Min: {np.nanmin(precip_100yr_24hr):.2f} inches")
```

**Important**: Always use dynamic indexing to find return period array indices. Never hardcode array indices (index 0 is the 2-year period, not the first period you requested).

### Atlas14Variance - Spatial Variance Analysis

Assesses whether uniform rainfall assumptions are appropriate for rain-on-grid modeling. A range percentage greater than 10% suggests spatially variable rainfall should be considered.

```python
from ras_commander.precip import Atlas14Variance

# Quick check for representative event (100-yr, 24-hr)
stats = Atlas14Variance.analyze_quick(
    geom_hdf="MyProject.g01.hdf",
    duration=24,
    return_period=100
)

print(f"Precipitation range: {stats['range_pct']:.1f}%")

if stats['range_pct'] > 10:
    print("High variance - consider spatially variable rainfall")
else:
    print("Uniform rainfall likely appropriate")
```

Full multi-event analysis:

```python
# Full analysis across durations and return periods
results = Atlas14Variance.analyze(
    geom_hdf="MyProject.g01.hdf",
    durations=[6, 12, 24, 48],
    return_periods=[10, 25, 50, 100, 500],
    extent_source="2d_flow_area",
    variance_denominator='min'   # range_pct = (max-min)/min * 100
)

# Review results DataFrame
print(results[['duration_hr', 'return_period_yr', 'min_inches', 'max_inches', 'range_pct']])

# Check decision support
ok, msg = Atlas14Variance.is_uniform_rainfall_appropriate(results, threshold_pct=10.0)
print(msg)

# Generate report with plots
report_dir = Atlas14Variance.generate_report(
    results_df=results,
    output_dir="Atlas14_Variance_Report",
    project_name="My Project",
    include_plots=True
)
```

**HUC12 watershed option**: Analyze within the full HUC12 watershed instead of the 2D flow area:

```python
results = Atlas14Variance.analyze(
    geom_hdf="MyProject.g01.hdf",
    use_huc12_boundary=True   # Finds HUC12 containing 2D flow area center
)
```

## Integration with HEC-RAS

### Writing Hyetographs to Unsteady Files

Use `RasUnsteady.set_precipitation_hyetograph()` to write any hyetograph DataFrame directly to a HEC-RAS unsteady file:

```python
from ras_commander import init_ras_project, RasUnsteady, RasCmdr
from ras_commander.precip import Atlas14Storm, ATLAS14_AVAILABLE

# Initialize project
init_ras_project("C:/Projects/MyModel", "6.6")

if ATLAS14_AVAILABLE:
    # Generate HMS-equivalent hyetograph
    # Depth from NOAA PFDS: https://hdsc.nws.noaa.gov/pfds/
    hyeto = Atlas14Storm.generate_hyetograph(
        total_depth_inches=17.0,
        state="tx",
        region=3,
        aep_percent=1.0,
        quartile="All Cases"
    )

    # Write directly to unsteady file (one call)
    # Detects time interval from hour spacing (1HOUR, 30MIN, 5MIN, etc.)
    RasUnsteady.set_precipitation_hyetograph("MyModel.u01", hyeto)

    # Execute plan
    RasCmdr.compute_plan("01")
```

`RasUnsteady.set_precipitation_hyetograph()` validates that the DataFrame has the required columns (`hour`, `incremental_depth`, `cumulative_depth`), finds the "Precipitation Hydrograph=" section, detects the time interval automatically, and formats values in HEC-RAS fixed-width format.

### Multi-AEP Batch Workflow

Generate and execute a suite of AEP design storms:

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan, RasUnsteady
from ras_commander.precip import StormGenerator

init_ras_project("C:/Projects/FloodStudy", "6.6")

# DDF data for temporal pattern (download once, reuse for all AEPs)
ddf_data = StormGenerator.download_from_coordinates(29.76, -95.37)

# Atlas 14 depths for Houston from NOAA PFDS (100-yr=17.0, 50-yr=14.5, etc.)
# Verify at: https://hdsc.nws.noaa.gov/pfds/pfds_map_cont.html?lat=29.76&lon=-95.37
aep_depths = {
    10.0: 11.5,   # 10% AEP (10-yr), 24-hr depth in inches
    2.0:  15.0,   # 2% AEP (50-yr)
    1.0:  17.0,   # 1% AEP (100-yr)
    0.2:  22.0,   # 0.2% AEP (500-yr)
}

for aep_pct, total_depth in aep_depths.items():
    return_period = int(100 / aep_pct)

    # Generate hyetograph with Atlas 14 depth
    hyeto = StormGenerator.generate_hyetograph(
        ddf_data=ddf_data,
        total_depth_inches=total_depth,
        duration_hours=24,
        position_percent=50
    )

    # Clone plan for this AEP
    new_plan = RasPlan.clone_plan("01", new_plan_shortid=f"{return_period}yr")
    RasPlan.set_description(new_plan, f"{return_period}-Year Design Storm ({aep_pct}% AEP)")

    # Get the unsteady file number for this plan
    from ras_commander import ras
    plan_row = ras.plan_df[ras.plan_df['plan_number'] == new_plan]
    unsteady_num = plan_row['unsteady_number'].iloc[0]

    # Write hyetograph to unsteady file
    unsteady_file = f"FloodStudy.u{unsteady_num}"
    RasUnsteady.set_precipitation_hyetograph(unsteady_file, hyeto)

    # Execute
    RasCmdr.compute_plan(new_plan, num_cores=4)
    print(f"Completed {return_period}-yr ({total_depth} inches)")
```

## Example Notebooks

Complete workflow demonstrations:

- `examples/720_precipitation_methods_comprehensive.ipynb` - Side-by-side comparison of all four hyetograph methods (Atlas14Storm, FrequencyStorm, ScsTypeStorm, StormGenerator) with validation
- `examples/721_Precipitation_Hyetograph_Comparison.ipynb` - Multi-method, multi-AEP workflow; parallel HEC-RAS execution; pre-execution validation
- `examples/722_gridded_precipitation_atlas14.ipynb` - Gridded precipitation workflow; spatial variance analysis; mesh polygon visualization
- `examples/725_atlas14_spatial_variance.ipynb` - Spatial variance analysis for uniform vs. distributed rainfall assessment; HUC12 watershed option

## See Also

- [Gridded Historic Precipitation](gridded-precipitation.md) - AORC historical data
- [Boundary Conditions](boundary-conditions.md) - General boundary condition workflows
- [DSS Operations](dss-operations.md) - Working with HEC-DSS files
- [Plan Execution](plan-execution.md) - Batch scenario execution
- `ras_commander/precip/CLAUDE.md` - Complete method comparison and validation details
- NOAA PFDS: https://hdsc.nws.noaa.gov/pfds/pfds_map_cont.html
