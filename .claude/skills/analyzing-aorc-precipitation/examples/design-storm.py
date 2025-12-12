"""
Atlas 14 Design Storm Generation

This script demonstrates the complete workflow for generating NOAA Atlas 14
design storms for HEC-RAS and HEC-HMS models.

Workflow:
1. Query Atlas 14 for precipitation frequency estimates
2. Apply areal reduction factor (if needed)
3. Generate design storm hyetograph with temporal distribution
4. Export to multiple formats (DSS, CSV, HEC-HMS gage)
5. Run suite of AEP events (optional)

Requirements:
- ras-commander[precip] (includes requests, pandas, pydsstools)
"""

import sys
from pathlib import Path

# For development: add parent directory to path
current_file = Path(__file__).resolve()
parent_directory = current_file.parent.parent.parent.parent
sys.path.insert(0, str(parent_directory))

from ras_commander.precip import StormGenerator

# ============================================================================
# Configuration
# ============================================================================

# Project location (latitude, longitude in WGS84)
LOCATION = (38.9072, -77.0369)  # Washington, DC

# Storm parameters
DURATION_HOURS = 24  # Storm duration
AEP_PERCENT = 1.0    # 1% = 100-year event
TEMPORAL_DISTRIBUTION = "SCS_Type_II"  # SCS Type II for Mid-Atlantic
INTERVAL_MINUTES = 15  # 15-minute timestep

# Areal reduction (for large watersheds)
APPLY_ARF = True
WATERSHED_AREA_SQMI = 250  # Square miles (apply ARF if > 10)

# Output configuration
OUTPUT_FOLDER = Path("design_storms")
OUTPUT_FOLDER.mkdir(exist_ok=True)

# ============================================================================
# Step 1: Query NOAA Atlas 14
# ============================================================================

print("="*70)
print("ATLAS 14 DESIGN STORM GENERATION")
print("="*70)

print(f"\nProject Location: {LOCATION[0]:.4f}°N, {LOCATION[1]:.4f}°W")
print(f"AEP: {AEP_PERCENT}% ({int(100/AEP_PERCENT)}-year event)")
print(f"Duration: {DURATION_HOURS} hours")
print(f"Distribution: {TEMPORAL_DISTRIBUTION}")

print(f"\nQuerying NOAA Atlas 14...")

point_precip = StormGenerator.get_precipitation_frequency(
    location=LOCATION,
    duration_hours=DURATION_HOURS,
    aep_percent=AEP_PERCENT
)

print(f"Point precipitation: {point_precip:.2f} inches")

# ============================================================================
# Step 2: Apply Areal Reduction Factor (if needed)
# ============================================================================

if APPLY_ARF and WATERSHED_AREA_SQMI > 10:
    print(f"\nApplying areal reduction factor...")
    print(f"  Watershed area: {WATERSHED_AREA_SQMI} sq mi")

    total_precip = StormGenerator.apply_areal_reduction(
        point_precip=point_precip,
        area_sqmi=WATERSHED_AREA_SQMI,
        duration_hours=DURATION_HOURS
    )

    reduction_pct = (1 - total_precip / point_precip) * 100
    print(f"  Areal precipitation: {total_precip:.2f} inches ({reduction_pct:.1f}% reduction)")
else:
    total_precip = point_precip
    print(f"\nUsing point precipitation (no ARF applied)")

# ============================================================================
# Step 3: Generate Design Storm Hyetograph
# ============================================================================

print(f"\nGenerating design storm hyetograph...")
print(f"  Interval: {INTERVAL_MINUTES} minutes")

hyetograph = StormGenerator.generate_design_storm(
    total_precip=total_precip,
    duration_hours=DURATION_HOURS,
    distribution=TEMPORAL_DISTRIBUTION,
    interval_minutes=INTERVAL_MINUTES
)

num_intervals = len(hyetograph)
peak_interval = hyetograph.idxmax()
peak_value = hyetograph.max()

print(f"  Timesteps: {num_intervals}")
print(f"  Peak interval: {peak_interval}")
print(f"  Peak intensity: {peak_value:.3f} inches/{INTERVAL_MINUTES}min")

# ============================================================================
# Step 4: Export to Multiple Formats
# ============================================================================

print(f"\nExporting design storm...")

# Export 1: CSV
csv_file = OUTPUT_FOLDER / f"design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.csv"
hyetograph.to_csv(csv_file, header=["Precipitation_in"])
print(f"  ✓ CSV exported: {csv_file}")

# Export 2: DSS (for HEC-RAS/HMS)
try:
    dss_file = OUTPUT_FOLDER / f"design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.dss"
    pathname = f"/PROJECT/PRECIP/DESIGN//{INTERVAL_MINUTES}MIN/SYN/"

    StormGenerator.export_to_dss(
        hyetograph,
        dss_file=dss_file,
        pathname=pathname
    )
    print(f"  ✓ DSS exported: {dss_file}")
    print(f"    Pathname: {pathname}")
except ImportError:
    print(f"  ⚠ DSS export skipped (pydsstools not installed)")
    print(f"    Install with: pip install pydsstools")

# Export 3: HEC-HMS gage file
try:
    gage_file = OUTPUT_FOLDER / f"design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.gage"
    StormGenerator.export_to_hms_gage(
        hyetograph,
        output_file=gage_file,
        gage_id="PRECIP1"
    )
    print(f"  ✓ HEC-HMS gage exported: {gage_file}")
except Exception as e:
    print(f"  ⚠ HEC-HMS gage export failed: {e}")

# ============================================================================
# Step 5: Generate Summary Statistics
# ============================================================================

print(f"\n{'='*70}")
print("DESIGN STORM SUMMARY")
print(f"{'='*70}")

print(f"\nStorm Characteristics:")
print(f"  Location: {LOCATION[0]:.4f}°N, {LOCATION[1]:.4f}°W")
print(f"  AEP: {AEP_PERCENT}% ({int(100/AEP_PERCENT)}-year)")
print(f"  Duration: {DURATION_HOURS} hours")
print(f"  Total depth: {total_precip:.2f} inches")
print(f"  Distribution: {TEMPORAL_DISTRIBUTION}")

print(f"\nHyetograph:")
print(f"  Timestep: {INTERVAL_MINUTES} minutes")
print(f"  Number of intervals: {num_intervals}")
print(f"  Peak interval: {peak_interval}")
print(f"  Peak intensity: {peak_value:.3f} in/{INTERVAL_MINUTES}min ({peak_value * 60 / INTERVAL_MINUTES:.2f} in/hr)")

# Calculate 1-hour and 6-hour maxima
hours_per_interval = INTERVAL_MINUTES / 60.0
intervals_per_hour = int(60 / INTERVAL_MINUTES)
intervals_per_6hr = int(6 * 60 / INTERVAL_MINUTES)

max_1hr = hyetograph.rolling(window=intervals_per_hour).sum().max()
max_6hr = hyetograph.rolling(window=intervals_per_6hr).sum().max()

print(f"\nRolling Maxima:")
print(f"  Maximum 1-hour: {max_1hr:.2f} inches")
print(f"  Maximum 6-hour: {max_6hr:.2f} inches")
print(f"  Maximum {DURATION_HOURS}-hour: {hyetograph.sum():.2f} inches (total)")

# ============================================================================
# Step 6: Generate Visualization
# ============================================================================

try:
    import matplotlib.pyplot as plt
    import numpy as np

    print(f"\nGenerating visualization...")

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    # Plot 1: Hyetograph
    ax1 = axes[0]
    times = np.arange(len(hyetograph)) * INTERVAL_MINUTES / 60.0  # Hours
    ax1.bar(times, hyetograph.values, width=INTERVAL_MINUTES/60.0, color='steelblue', alpha=0.8, edgecolor='darkblue', linewidth=0.5)
    ax1.set_xlabel('Time (hours)')
    ax1.set_ylabel(f'Precipitation (inches / {INTERVAL_MINUTES} min)')
    ax1.set_title(f'{DURATION_HOURS}-Hour, {AEP_PERCENT}% AEP Design Storm - {TEMPORAL_DISTRIBUTION}\n'
                  f'Total: {total_precip:.2f} inches | Peak: {peak_value:.3f} in/{INTERVAL_MINUTES}min')
    ax1.grid(True, alpha=0.3)

    # Add statistics box
    stats_text = (f'Location: {LOCATION[0]:.2f}°N, {LOCATION[1]:.2f}°W\n'
                  f'Watershed: {WATERSHED_AREA_SQMI} sq mi\n'
                  f'Point: {point_precip:.2f} in\n'
                  f'Areal: {total_precip:.2f} in')
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes, fontsize=9,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    # Plot 2: Cumulative
    ax2 = axes[1]
    cumulative = hyetograph.cumsum()
    ax2.plot(times, cumulative.values, linewidth=2, color='darkgreen')
    ax2.fill_between(times, cumulative.values, alpha=0.3, color='green')
    ax2.set_xlabel('Time (hours)')
    ax2.set_ylabel('Cumulative Precipitation (inches)')
    ax2.set_title('Cumulative Hyetograph')
    ax2.grid(True, alpha=0.3)

    # Add 50% line
    ax2.axhline(y=total_precip/2, color='red', linestyle='--', linewidth=1, alpha=0.7, label='50% of total')
    ax2.legend()

    plt.tight_layout()

    plot_file = OUTPUT_FOLDER / f"design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.png"
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    print(f"  ✓ Plot saved: {plot_file}")

    plt.show()

except ImportError:
    print(f"\n  ⚠ Visualization skipped (matplotlib/numpy not installed)")

# ============================================================================
# OPTIONAL: Generate Multi-Event Suite
# ============================================================================

GENERATE_MULTI_EVENT = False  # Set to True to run

if GENERATE_MULTI_EVENT:
    print(f"\n{'='*70}")
    print("MULTI-EVENT SUITE GENERATION")
    print(f"{'='*70}")

    # Define AEP suite
    aep_events = [50, 20, 10, 4, 2, 1, 0.5, 0.2]  # 2-year to 500-year

    print(f"\nGenerating {len(aep_events)} design storms...")

    results = []

    for aep in aep_events:
        # Query Atlas 14
        point = StormGenerator.get_precipitation_frequency(
            location=LOCATION,
            duration_hours=DURATION_HOURS,
            aep_percent=aep
        )

        # Apply ARF
        if APPLY_ARF and WATERSHED_AREA_SQMI > 10:
            total = StormGenerator.apply_areal_reduction(
                point_precip=point,
                area_sqmi=WATERSHED_AREA_SQMI,
                duration_hours=DURATION_HOURS
            )
        else:
            total = point

        # Generate design storm
        hyeto = StormGenerator.generate_design_storm(
            total_precip=total,
            duration_hours=DURATION_HOURS,
            distribution=TEMPORAL_DISTRIBUTION,
            interval_minutes=INTERVAL_MINUTES
        )

        # Export to DSS
        try:
            dss = OUTPUT_FOLDER / f"design_{DURATION_HOURS}hr_{aep}pct.dss"
            StormGenerator.export_to_dss(hyeto, dss_file=dss)
            results.append((aep, int(100/aep), total, dss.name))
            print(f"  {aep:5.1f}% AEP ({int(100/aep):4d}-year): {total:5.2f} in → {dss.name}")
        except ImportError:
            results.append((aep, int(100/aep), total, "DSS export unavailable"))
            print(f"  {aep:5.1f}% AEP ({int(100/aep):4d}-year): {total:5.2f} in")

    print(f"\nGenerated {len(results)} design storms")

else:
    print(f"\nTo generate multi-event suite, set GENERATE_MULTI_EVENT = True")

# ============================================================================
# Complete
# ============================================================================

print(f"\n{'='*70}")
print("WORKFLOW COMPLETE")
print(f"{'='*70}")
print(f"\nOutput files saved to: {OUTPUT_FOLDER}")
print(f"  - {csv_file.name} (CSV time series)")
if (OUTPUT_FOLDER / f"design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.dss").exists():
    print(f"  - design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.dss (HEC-DSS)")
if (OUTPUT_FOLDER / f"design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.gage").exists():
    print(f"  - design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.gage (HEC-HMS)")
if (OUTPUT_FOLDER / f"design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.png").exists():
    print(f"  - design_{DURATION_HOURS}hr_{AEP_PERCENT}pct.png (Visualization)")

print(f"\nNext steps:")
print(f"  1. Import DSS file into HEC-RAS or HEC-HMS")
print(f"  2. Set precipitation boundary condition to DSS pathname")
print(f"  3. Run model simulation")
print(f"  4. Extract peak flow/stage results")
print(f"  5. Repeat for additional AEP events (flood frequency curve)")
