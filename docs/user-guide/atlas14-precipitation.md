# Atlas 14 Precipitation

NOAA Atlas 14 provides official precipitation frequency estimates for design storm modeling. The ras-commander Atlas 14 integration automates design storm generation for AEP (Annual Exceedance Probability) event analysis.

## Overview

Atlas 14 is the authoritative source for precipitation frequency estimates in the United States, used for:

- Regulatory floodplain mapping (1% AEP / 100-year events)
- Infrastructure design (drainage, culverts, bridges)
- Dam breach inundation studies (PMF, 0.2% AEP)
- Sensitivity analysis across multiple AEP events

**Key Features**:

- **Coverage**: CONUS, Hawaii, Puerto Rico, Pacific Islands
- **AEP Range**: 50% (2-year) to 0.2% (500-year) and beyond
- **Durations**: 5 minutes to 60 days
- **Regional distributions**: SCS Type I/IA/II/III temporal patterns

## Quick Start

Generate a 24-hour, 1% AEP (100-year) design storm:

```python
from ras_commander.precip import StormGenerator

# 1. Query Atlas 14 for location and AEP
precip_depth = StormGenerator.get_precipitation_frequency(
    location=(38.9072, -77.0369),  # Washington, DC (lat, lon)
    duration_hours=24,
    aep_percent=1.0  # 1% = 100-year event
)

print(f"24-hr, 1% AEP: {precip_depth:.2f} inches")

# 2. Generate temporal distribution
hyetograph = StormGenerator.generate_design_storm(
    total_precip=precip_depth,
    duration_hours=24,
    distribution="SCS_Type_II",  # Standard for most of US
    interval_minutes=15
)

# 3. Export for HEC-RAS
hyetograph.to_csv("design_storm_100yr.csv")
```

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

### Generate Suite of AEP Events

```python
from ras_commander.precip import StormGenerator

# Define AEP suite for flood frequency analysis
aep_events = [50, 20, 10, 4, 2, 1, 0.5, 0.2]
location = (38.9072, -77.0369)  # Project location

design_storms = {}

for aep in aep_events:
    # Query Atlas 14
    precip = StormGenerator.get_precipitation_frequency(
        location=location,
        duration_hours=24,
        aep_percent=aep
    )

    # Generate hyetograph
    hyetograph = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=24,
        distribution="SCS_Type_II",
        interval_minutes=15
    )

    # Store for later use
    design_storms[aep] = hyetograph

    # Export to file
    output_file = f"storm_{aep}pct_AEP_24hr.csv"
    hyetograph.to_csv(output_file)
    print(f"Generated {aep}% AEP: {precip:.2f} inches → {output_file}")
```

## Temporal Distributions

Different regions use different temporal patterns based on climatic characteristics:

### Distribution Types

```python
# SCS Type II - Most of US (default)
hyeto_type2 = StormGenerator.generate_design_storm(
    total_precip=8.5,
    duration_hours=24,
    distribution="SCS_Type_II"
)

# SCS Type IA - Pacific maritime climate
hyeto_type1a = StormGenerator.generate_design_storm(
    total_precip=8.5,
    duration_hours=24,
    distribution="SCS_Type_IA"
)

# SCS Type III - Gulf Coast and Florida
hyeto_type3 = StormGenerator.generate_design_storm(
    total_precip=8.5,
    duration_hours=24,
    distribution="SCS_Type_III"
)
```

### Regional Selection Guide

**SCS Type II** (Most of US):
- Central and eastern states
- Midwest, Great Plains
- Mountain states
- Default for most applications

**SCS Type IA** (Pacific maritime):
- Pacific Northwest (WA, OR)
- Coastal California
- Alaska

**SCS Type III** (Gulf Coast):
- Florida peninsula
- Gulf of Mexico coast
- Tropical/subtropical climates

**Atlas 14 automatically detects region** from lat/lon coordinates.

## Multiple Durations

Generate storms for different durations to support frequency analysis:

```python
# Standard storm durations
durations = [6, 12, 24, 48]  # hours
aep = 1.0  # 1% AEP (100-year)

for duration in durations:
    # Query Atlas 14
    precip = StormGenerator.get_precipitation_frequency(
        location=(38.9, -77.0),
        duration_hours=duration,
        aep_percent=aep
    )

    # Generate hyetograph
    hyetograph = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=duration,
        distribution="SCS_Type_II",
        interval_minutes=15
    )

    # Export
    output = f"storm_100yr_{duration}hr.csv"
    hyetograph.to_csv(output)
    print(f"{duration}-hr: {precip:.2f} inches")
```

## Areal Reduction Factors (ARF)

For large watersheds, apply areal reduction to point precipitation values:

```python
# Query point precipitation from Atlas 14
point_precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),
    duration_hours=24,
    aep_percent=1.0
)

# Apply ARF for 250 sq mi watershed
watershed_area_sqmi = 250
reduced_precip = StormGenerator.apply_areal_reduction(
    point_precip=point_precip,
    area_sqmi=watershed_area_sqmi,
    duration_hours=24
)

print(f"Point precipitation: {point_precip:.2f} in")
print(f"Areal (250 sq mi): {reduced_precip:.2f} in")
print(f"Reduction: {(1 - reduced_precip/point_precip)*100:.1f}%")

# Generate design storm with reduced depth
hyetograph = StormGenerator.generate_design_storm(
    total_precip=reduced_precip,
    duration_hours=24,
    distribution="SCS_Type_II"
)
```

### ARF Guidance

Typical areal reduction factors for 24-hour duration:

| Watershed Area | ARF Factor | Example |
|----------------|------------|---------|
| < 10 sq mi | ~1.00 | No reduction needed |
| 50 sq mi | ~0.97 | 3% reduction |
| 100 sq mi | ~0.95 | 5% reduction |
| 250 sq mi | ~0.92 | 8% reduction |
| 500 sq mi | ~0.90 | 10% reduction |
| 1000 sq mi | ~0.85 | 15% reduction |

**When to apply ARF**:

- ✅ Large watersheds (> 10 sq mi)
- ✅ Uniformly distributed storms
- ✅ Design events (not actual storms)
- ❌ Small urban watersheds
- ❌ Historical event reconstruction

## Integration with HEC-RAS

### Batch Scenario Generation

Create multiple design storm scenarios for a project:

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan
from ras_commander.precip import StormGenerator

# Initialize project
init_ras_project("C:/Projects/MyModel", "6.6")

# Define AEP suite
aep_events = [10, 2, 1, 0.5, 0.2]  # 10% to 0.2%
location = (38.9, -77.0)

for aep in aep_events:
    # Query Atlas 14
    precip = StormGenerator.get_precipitation_frequency(
        location=location,
        duration_hours=24,
        aep_percent=aep
    )

    # Generate design storm
    hyetograph = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=24,
        distribution="SCS_Type_II"
    )

    # Clone plan for this event
    plan_id = RasPlan.clone_plan(
        "01",
        new_plan_shortid=f"AEP_{aep}pct"
    )

    # Update plan description
    RasPlan.set_description(
        plan_id,
        f"Design Storm - {aep}% AEP ({int(100/aep)}-year)"
    )

    # Export precipitation to DSS
    dss_file = f"MyModel_AEP{aep}.dss"
    StormGenerator.export_to_dss(
        hyetograph,
        dss_file=dss_file,
        pathname=f"//BASIN/PRECIP/DESIGN//15MIN/AEP{aep}/"
    )

    # Execute plan
    RasCmdr.compute_plan(plan_id, num_cores=4)

    print(f"✓ Completed {aep}% AEP: {precip:.2f} inches")
```

### Export to DSS

Export design storms to HEC-DSS format for HEC-RAS/HMS:

```python
# Generate design storm
hyetograph = StormGenerator.generate_design_storm(
    total_precip=8.5,
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15
)

# Export to DSS
from ras_commander.usgs import RasUsgsFileIo

RasUsgsFileIo.export_to_dss(
    hyetograph,
    dss_file="design_storms.dss",
    pathname="//BASIN/PRECIP/DESIGN//15MIN/100YR/"
)
```

### Export to HEC-HMS

Generate HEC-HMS precipitation gage file:

```python
# Export to HEC-HMS format
StormGenerator.export_to_hms_gage(
    hyetograph,
    output_file="design_storm_100yr.gage",
    gage_id="PRECIP1",
    description="24-hr, 1% AEP Design Storm"
)
```

## Multi-Project Analysis

Process multiple projects with same AEP suite:

```python
from ras_commander import init_ras_project, RasCmdr
from ras_commander.precip import StormGenerator

# Define projects and AEP events
projects = [
    {"name": "ModelA", "location": (38.9, -77.0)},
    {"name": "ModelB", "location": (39.1, -76.8)},
    {"name": "ModelC", "location": (38.7, -77.2)}
]
aep_events = [10, 2, 1, 0.2]

results = {}

for project in projects:
    project_folder = f"C:/Projects/{project['name']}"
    init_ras_project(project_folder, "6.6")

    results[project['name']] = {}

    for aep in aep_events:
        # Query Atlas 14 (location-specific)
        precip = StormGenerator.get_precipitation_frequency(
            location=project['location'],
            duration_hours=24,
            aep_percent=aep
        )

        # Generate and export design storm
        hyeto = StormGenerator.generate_design_storm(
            total_precip=precip,
            duration_hours=24,
            distribution="SCS_Type_II"
        )

        dss_file = f"{project['name']}_AEP{aep}.dss"
        StormGenerator.export_to_dss(hyeto, dss_file)

        # Clone plan and execute
        plan_id = RasPlan.clone_plan("01", new_plan_shortid=f"AEP{aep}")
        RasCmdr.compute_plan(plan_id, num_cores=4)

        # Store peak results
        from ras_commander import HdfResultsMesh
        max_wse = HdfResultsMesh.get_mesh_max_ws(plan_id)

        results[project['name']][aep] = {
            'precip': precip,
            'max_wse': max_wse['Max WS'].max()
        }

        print(f"✓ {project['name']} - {aep}% AEP: {precip:.2f} in")

# Results summary
import pandas as pd
summary_df = pd.DataFrame(results).T
print(summary_df)
```

## Sensitivity Analysis

Test model sensitivity to precipitation depth variations:

```python
# Get base Atlas 14 estimate
base_precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),
    duration_hours=24,
    aep_percent=1.0  # 100-year
)

# Test ±20% scenarios
sensitivity_factors = [0.8, 0.9, 1.0, 1.1, 1.2]

for factor in sensitivity_factors:
    scaled_precip = base_precip * factor

    hyeto = StormGenerator.generate_design_storm(
        total_precip=scaled_precip,
        duration_hours=24,
        distribution="SCS_Type_II"
    )

    # Clone plan with descriptive ID
    plan_id = RasPlan.clone_plan(
        "01",
        new_plan_shortid=f"precip_{int(factor*100)}"
    )

    # Export and execute
    dss_file = f"storm_{int(factor*100)}pct.dss"
    StormGenerator.export_to_dss(hyeto, dss_file)

    RasCmdr.compute_plan(plan_id, num_cores=4)

    print(f"Factor {factor}: {scaled_precip:.2f} inches")
```

## Atlas 14 Coverage Regions

Atlas 14 is published in volumes covering different regions:

| Volume | Region | Status |
|--------|--------|--------|
| **1** | Semiarid Southwest | Published |
| **2** | Ohio River Basin and Surrounding States | Published |
| **3** | Puerto Rico and U.S. Virgin Islands | Published |
| **4** | Hawaiian Islands | Published |
| **5** | Selected Pacific Islands | Published |
| **6** | California | Published |
| **7** | Alaska | Published |
| **8** | Midwestern States | Published |
| **9** | Southeastern States | Published |
| **10** | Northeastern States | Published |
| **11** | Texas | Published |

**Automatic region detection**: `StormGenerator` automatically determines which volume to use based on latitude/longitude.

```python
# Location determines which Atlas 14 volume is used
precip_dc = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),  # Washington, DC → Volume 2
    duration_hours=24,
    aep_percent=1.0
)

precip_ca = StormGenerator.get_precipitation_frequency(
    location=(34.05, -118.25),  # Los Angeles → Volume 6
    duration_hours=24,
    aep_percent=1.0
)
```

## Temporal Distributions

### SCS Distributions

The SCS (Soil Conservation Service, now NRCS) developed standard temporal distributions based on regional climate:

```python
# Type II: Standard for most US locations
hyeto = StormGenerator.generate_design_storm(
    total_precip=8.5,
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15
)

# Key characteristics of SCS Type II:
# - Peak at ~12 hours (50% into storm)
# - Sharp peak (front-loaded after midpoint)
# - Standard for central/eastern US
```

**Type II peak intensity**: ~50% of total rainfall falls in middle 6 hours of 24-hour storm.

### Custom Temporal Distributions

Define custom hyetograph patterns:

```python
# Custom distribution (e.g., early peak for flash flood analysis)
custom_distribution = [
    0.05, 0.10, 0.20, 0.30,  # Hour 1-4: rapid rise
    0.15, 0.10, 0.05, 0.03,  # Hour 5-8: recession
    0.02, 0.00, 0.00, 0.00   # Hour 9-12: dry
]

hyeto = StormGenerator.generate_design_storm(
    total_precip=6.0,
    duration_hours=12,
    distribution=custom_distribution,  # Pass list of fractions
    interval_minutes=60  # Hourly intervals
)
```

## Advanced Features

### Spatially Distributed Storms

Generate spatially varying design storms for large basins:

```python
# Define sub-basin locations
sub_basins = [
    {"name": "Upper", "location": (39.0, -77.0)},
    {"name": "Middle", "location": (38.9, -77.0)},
    {"name": "Lower", "location": (38.8, -77.0)}
]

# Generate location-specific storms
for basin in sub_basins:
    precip = StormGenerator.get_precipitation_frequency(
        location=basin['location'],
        duration_hours=24,
        aep_percent=1.0
    )

    hyeto = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=24,
        distribution="SCS_Type_II"
    )

    # Export with basin-specific pathname
    dss_pathname = f"//BASIN/{basin['name']}/PRECIP//15MIN/100YR/"
    StormGenerator.export_to_dss(hyeto, "design_storms.dss", dss_pathname)

    print(f"{basin['name']}: {precip:.2f} inches")
```

### Depth-Duration-Frequency (DDF) Analysis

Extract complete DDF curves for a location:

```python
# Define AEP and duration ranges
aep_range = [50, 20, 10, 4, 2, 1, 0.5, 0.2]
duration_range = [6, 12, 24, 48]  # hours

ddf_matrix = {}

for aep in aep_range:
    ddf_matrix[f"{aep}% AEP"] = {}

    for duration in duration_range:
        precip = StormGenerator.get_precipitation_frequency(
            location=(38.9, -77.0),
            duration_hours=duration,
            aep_percent=aep
        )
        ddf_matrix[f"{aep}% AEP"][f"{duration}hr"] = precip

# Convert to DataFrame for analysis
import pandas as pd
ddf_df = pd.DataFrame(ddf_matrix).T
print(ddf_df)
```

## Integration with HEC-RAS Workflows

### Complete Design Storm Workflow

End-to-end workflow from Atlas 14 query to peak results:

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan
from ras_commander.precip import StormGenerator
from ras_commander import HdfResultsMesh

# 1. Initialize project
project_folder = "C:/Projects/FloodStudy"
init_ras_project(project_folder, "6.6")

# 2. Query Atlas 14 for 100-year, 24-hour storm
precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),
    duration_hours=24,
    aep_percent=1.0
)

# 3. Apply ARF if needed (large watershed)
watershed_area = 150  # sq mi
if watershed_area > 10:
    precip = StormGenerator.apply_areal_reduction(
        precip, watershed_area, duration_hours=24
    )

# 4. Generate design storm
hyetograph = StormGenerator.generate_design_storm(
    total_precip=precip,
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15
)

# 5. Export to DSS
StormGenerator.export_to_dss(
    hyetograph,
    dss_file="design_storm_100yr.dss",
    pathname="//BASIN/PRECIP/DESIGN//15MIN/100YR/"
)

# 6. Clone plan for design storm
design_plan = RasPlan.clone_plan("01", new_plan_shortid="100yr")
RasPlan.set_description(design_plan, "100-Year Design Storm")

# 7. Execute HEC-RAS
RasCmdr.compute_plan(design_plan, num_cores=4)

# 8. Extract peak results
max_wse = HdfResultsMesh.get_mesh_max_ws(design_plan)

print(f"Precipitation: {precip:.2f} inches")
print(f"Peak WSE: {max_wse['Max WS'].max():.2f} ft")
```

### Uncertainty Analysis

Model uncertainty in precipitation estimates:

```python
# Atlas 14 provides confidence intervals (not yet in API)
# For now, use sensitivity analysis with ±20% bounds

base_precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),
    duration_hours=24,
    aep_percent=1.0
)

# Conservative (upper bound): +20%
upper_precip = base_precip * 1.2

# Best estimate: Atlas 14 value
nominal_precip = base_precip

# Lower bound: -20%
lower_precip = base_precip * 0.8

# Run all three scenarios
for label, precip in [("Lower", lower_precip),
                       ("Nominal", nominal_precip),
                       ("Upper", upper_precip)]:
    hyeto = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=24,
        distribution="SCS_Type_II"
    )

    plan_id = RasPlan.clone_plan("01", new_plan_shortid=label)
    # ... export DSS, execute, extract results
```

## Performance

### Query Speed

Atlas 14 queries are fast:

- **Typical query**: < 5 seconds
- **Caching**: Automatic caching of API responses
- **Rate limiting**: Built-in delays to respect NOAA service limits

### Batch Processing

For large batch jobs:

```python
# Query multiple locations efficiently
locations = [
    (38.9, -77.0),
    (39.1, -76.8),
    (38.7, -77.2)
]

# Queries are automatically rate-limited
for lat, lon in locations:
    precip = StormGenerator.get_precipitation_frequency(
        location=(lat, lon),
        duration_hours=24,
        aep_percent=1.0
    )
    # Built-in delays prevent overwhelming NOAA API
    print(f"({lat}, {lon}): {precip:.2f} inches")
```

## Example Notebooks

Comprehensive Atlas 14 workflow demonstrations:

- [Atlas 14 AEP Events](../notebooks/720_atlas14_aep_events.ipynb) - Design storm generation
- [Atlas 14 Caching Demo](../notebooks/721_atlas14_caching_demo.ipynb) - Efficient caching strategies
- [Atlas 14 Multi-Project](../notebooks/722_atlas14_multi_project.ipynb) - Batch processing workflows

## Common Workflows

### Regulatory Floodplain Mapping

Standard FEMA 100-year floodplain mapping:

1. **Query Atlas 14** for 1% AEP, 24-hour storm
2. **Apply ARF** if watershed > 10 sq mi
3. **Generate SCS Type II** hyetograph
4. **Export to DSS** for HEC-RAS
5. **Execute model** with design storm
6. **Extract peak WSE** for floodplain delineation

### Infrastructure Design

Culvert/bridge design with multiple return periods:

1. **Define AEP suite** (e.g., 50%, 20%, 10%, 2%)
2. **Query Atlas 14** for each AEP
3. **Generate design storms** with appropriate duration
4. **Run HEC-RAS scenarios**
5. **Extract peak flow/velocity** at structure locations
6. **Size infrastructure** based on peak hydraulics

### Dam Breach PMF

Probable Maximum Flood (PMF) estimation:

1. **Query extreme AEPs** (0.2%, 0.1%, or lower)
2. **Apply large ARF** for watershed size
3. **Use critical duration** (typically 6-24 hours for dam breach)
4. **Generate hyetograph**
5. **Combine with snowmelt** if applicable
6. **Run dam breach scenario**

## See Also

- [Gridded Historic Precipitation](gridded-precipitation.md) - AORC historical data
- [Boundary Conditions](boundary-conditions.md) - General boundary workflows
- [DSS Operations](dss-operations.md) - Working with DSS files
- [Plan Execution](plan-execution.md) - Batch scenario execution
