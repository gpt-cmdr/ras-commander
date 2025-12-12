"""
AORC Precipitation Retrieval - Basic Workflow

This script demonstrates the complete workflow for retrieving and processing
AORC (Analysis of Record for Calibration) precipitation data for use with
HEC-RAS and HEC-HMS models.

Workflow:
1. Define watershed boundary (HUC or shapefile)
2. Retrieve AORC precipitation data
3. Calculate spatial average over watershed
4. Aggregate to model timestep
5. Export to multiple formats (DSS, CSV, NetCDF)

Requirements:
- ras-commander[precip] (includes xarray, rasterio, geopandas, pydsstools)
"""

import sys
from pathlib import Path

# For development: add parent directory to path
current_file = Path(__file__).resolve()
parent_directory = current_file.parent.parent.parent.parent
sys.path.insert(0, str(parent_directory))

from ras_commander.precip import PrecipAorc

# ============================================================================
# Configuration
# ============================================================================

# Define watershed (Option 1: HUC code)
WATERSHED = "02070010"  # HUC-8 for Potomac River

# Or Option 2: Shapefile path
# WATERSHED = Path("watershed_boundary.shp")

# Time period for analysis
START_DATE = "2015-05-01"
END_DATE = "2015-05-15"

# Output configuration
OUTPUT_FOLDER = Path("precipitation_output")
OUTPUT_FOLDER.mkdir(exist_ok=True)

# Target HEC-RAS/HMS timestep
INTERVAL = "1HR"  # Options: 15MIN, 30MIN, 1HR, 6HR, 1DAY

# ============================================================================
# Step 1: Retrieve AORC Data
# ============================================================================

print("="*70)
print("AORC PRECIPITATION RETRIEVAL")
print("="*70)

print(f"\nWatershed: {WATERSHED}")
print(f"Period: {START_DATE} to {END_DATE}")
print(f"Retrieving AORC data...")

aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed=WATERSHED,
    start_date=START_DATE,
    end_date=END_DATE
)

print(f"Retrieved data:")
print(f"  Spatial extent: {aorc_data.x.shape[0]} x {aorc_data.y.shape[0]} grid cells")
print(f"  Temporal extent: {len(aorc_data.time)} hourly timesteps")
print(f"  Variable: {list(aorc_data.data_vars)[0]}")

# ============================================================================
# Step 2: Calculate Spatial Average
# ============================================================================

print(f"\nCalculating spatial average over watershed...")

avg_precip = PrecipAorc.spatial_average(aorc_data, WATERSHED)

print(f"Spatial average complete:")
print(f"  Time series length: {len(avg_precip)}")
print(f"  Total precipitation: {avg_precip.sum():.2f} mm")
print(f"  Maximum hourly rate: {avg_precip.max():.2f} mm/hr")

# ============================================================================
# Step 3: Temporal Aggregation
# ============================================================================

print(f"\nAggregating to {INTERVAL} intervals...")

aggregated = PrecipAorc.aggregate_to_interval(avg_precip, interval=INTERVAL)

print(f"Aggregation complete:")
print(f"  Timesteps: {len(aggregated)}")
print(f"  Interval: {INTERVAL}")
print(f"  Total precipitation: {aggregated.sum():.2f} mm (unchanged)")

# ============================================================================
# Step 4: Export to Multiple Formats
# ============================================================================

print(f"\nExporting precipitation data...")

# Export 1: CSV (for HEC-HMS)
csv_file = OUTPUT_FOLDER / "aorc_precipitation.csv"
aggregated.to_csv(csv_file, header=["Precipitation_mm"])
print(f"  ✓ CSV exported: {csv_file}")

# Export 2: DSS (for HEC-RAS/HMS)
try:
    dss_file = OUTPUT_FOLDER / "aorc_precipitation.dss"
    pathname = f"/AORC/PRECIP/{WATERSHED}//{INTERVAL}/OBS/"

    PrecipAorc.export_to_dss(
        aggregated,
        dss_file=dss_file,
        pathname=pathname
    )
    print(f"  ✓ DSS exported: {dss_file}")
    print(f"    Pathname: {pathname}")
except ImportError:
    print(f"  ⚠ DSS export skipped (pydsstools not installed)")
    print(f"    Install with: pip install pydsstools")

# Export 3: NetCDF (for further analysis)
nc_file = OUTPUT_FOLDER / "aorc_data.nc"
PrecipAorc.export_to_netcdf(aorc_data, nc_file)
print(f"  ✓ NetCDF exported: {nc_file}")

# ============================================================================
# Step 5: Generate Summary Statistics
# ============================================================================

print(f"\n{'='*70}")
print("SUMMARY STATISTICS")
print(f"{'='*70}")

# Time series statistics
print(f"\nPrecipitation Summary:")
print(f"  Total depth: {aggregated.sum():.2f} mm ({aggregated.sum() / 25.4:.2f} inches)")
print(f"  Maximum rate: {aggregated.max():.2f} mm/interval")
print(f"  Mean rate: {aggregated.mean():.2f} mm/interval")
print(f"  Wet intervals: {(aggregated > 0).sum()} of {len(aggregated)}")

# Peak identification
peak_idx = aggregated.idxmax()
peak_value = aggregated.max()
print(f"\nPeak Precipitation:")
print(f"  Time: {peak_idx}")
print(f"  Value: {peak_value:.2f} mm")

# Calculate rolling totals
rolling_24hr = PrecipAorc.calculate_rolling_totals(aggregated, window_hours=24)
max_24hr = rolling_24hr.max()
max_24hr_time = rolling_24hr.idxmax()

print(f"\n24-Hour Rolling Maximum:")
print(f"  Time: {max_24hr_time}")
print(f"  Value: {max_24hr:.2f} mm ({max_24hr / 25.4:.2f} inches)")

# ============================================================================
# Step 6: Generate Visualization (Optional)
# ============================================================================

try:
    import matplotlib.pyplot as plt

    print(f"\nGenerating visualization...")

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    # Plot 1: Time series
    ax1 = axes[0]
    ax1.bar(aggregated.index, aggregated.values, width=0.04, color='steelblue', alpha=0.8)
    ax1.set_xlabel('Date/Time')
    ax1.set_ylabel(f'Precipitation ({INTERVAL})')
    ax1.set_title(f'AORC Precipitation - Watershed {WATERSHED}\n{START_DATE} to {END_DATE}')
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='x', rotation=45)

    # Plot 2: Cumulative precipitation
    ax2 = axes[1]
    cumulative = aggregated.cumsum()
    ax2.plot(cumulative.index, cumulative.values, linewidth=2, color='darkgreen')
    ax2.fill_between(cumulative.index, cumulative.values, alpha=0.3, color='green')
    ax2.set_xlabel('Date/Time')
    ax2.set_ylabel('Cumulative Precipitation (mm)')
    ax2.set_title('Cumulative Precipitation')
    ax2.grid(True, alpha=0.3)
    ax2.tick_params(axis='x', rotation=45)

    plt.tight_layout()

    plot_file = OUTPUT_FOLDER / "aorc_precipitation.png"
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    print(f"  ✓ Plot saved: {plot_file}")

    plt.show()

except ImportError:
    print(f"\n  ⚠ Visualization skipped (matplotlib not installed)")
    print(f"    Install with: pip install matplotlib")

# ============================================================================
# Complete
# ============================================================================

print(f"\n{'='*70}")
print("WORKFLOW COMPLETE")
print(f"{'='*70}")
print(f"\nOutput files saved to: {OUTPUT_FOLDER}")
print(f"  - {csv_file.name} (CSV time series)")
if (OUTPUT_FOLDER / "aorc_precipitation.dss").exists():
    print(f"  - aorc_precipitation.dss (HEC-DSS)")
print(f"  - {nc_file.name} (NetCDF grid)")
if (OUTPUT_FOLDER / "aorc_precipitation.png").exists():
    print(f"  - aorc_precipitation.png (Visualization)")

print(f"\nNext steps:")
print(f"  1. Import DSS file into HEC-RAS or HEC-HMS")
print(f"  2. Set precipitation boundary condition to DSS pathname")
print(f"  3. Run model simulation")
print(f"  4. Compare results with observed data (if available)")
