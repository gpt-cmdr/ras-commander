"""
Unsteady Flow Results Extraction Examples

Demonstrates common patterns for extracting unsteady flow time series
from HEC-RAS HDF files.
"""

from pathlib import Path
from ras_commander import (
    init_ras_project,
    HdfResultsPlan,
    HdfResultsXsec,
    HdfResultsMesh,
    RasExamples
)
import pandas as pd
import matplotlib.pyplot as plt


def extract_cross_section_timeseries(plan_number: str):
    """
    Extract time series for all cross sections.

    Args:
        plan_number: Plan identifier (e.g., "01")

    Returns:
        xarray.Dataset with time series data
    """
    # Verify unsteady plan
    if HdfResultsPlan.is_steady_plan(plan_number):
        raise ValueError(f"Plan {plan_number} is a steady state plan, not unsteady")

    # Extract cross section time series
    xsec_ts = HdfResultsXsec.get_xsec_timeseries(plan_number)

    print(f"Cross Section Time Series:")
    print(f"  Dimensions: {dict(xsec_ts.dims)}")
    print(f"  Variables: {list(xsec_ts.data_vars.keys())}")
    print(f"  Time range: {xsec_ts.time.values[0]} to {xsec_ts.time.values[-1]}")

    return xsec_ts


def analyze_peak_values(xsec_ts) -> pd.DataFrame:
    """
    Find peak water surface elevations at each cross section.

    Args:
        xsec_ts: xarray Dataset from get_xsec_timeseries()

    Returns:
        DataFrame with peak values and timing
    """
    # Find peak WSE at each cross section
    peak_wse = xsec_ts["Water_Surface"].max(dim="time")

    # Find when peak occurred
    peak_time_idx = xsec_ts["Water_Surface"].argmax(dim="time")
    peak_times = xsec_ts["time"].isel(time=peak_time_idx)

    # Create summary DataFrame
    peaks_df = pd.DataFrame({
        'cross_section': peak_wse.cross_section.values,
        'river': xsec_ts["River"].values,
        'reach': xsec_ts["Reach"].values,
        'station': xsec_ts["Station"].values,
        'peak_wse': peak_wse.values,
        'peak_time': peak_times.values
    })

    print("\nPeak Water Surface Elevations:")
    print(f"  Overall maximum: {peaks_df['peak_wse'].max():.2f} ft")
    print(f"  Overall minimum: {peaks_df['peak_wse'].min():.2f} ft")

    print("\nTop 5 highest peaks:")
    print(peaks_df.nlargest(5, 'peak_wse')[['station', 'peak_wse', 'peak_time']])

    return peaks_df


def extract_hydrograph_at_location(xsec_ts, target_xs: str) -> pd.DataFrame:
    """
    Extract flow hydrograph at a specific cross section.

    Args:
        xsec_ts: xarray Dataset from get_xsec_timeseries()
        target_xs: Cross section identifier (e.g., "Bald Eagle       Loc Hav          136202.3")

    Returns:
        DataFrame with time series at location
    """
    # Extract data for specific cross section
    wse = xsec_ts["Water_Surface"].sel(cross_section=target_xs)
    flow = xsec_ts["Flow"].sel(cross_section=target_xs)
    velocity = xsec_ts["Velocity_Total"].sel(cross_section=target_xs)

    # Combine into DataFrame
    df = pd.DataFrame({
        'time': wse.time.values,
        'wse': wse.values,
        'flow': flow.values,
        'velocity': velocity.values
    })

    print(f"\nHydrograph at {target_xs}:")
    print(f"  Peak flow: {df['flow'].max():,.0f} cfs at {df.loc[df['flow'].idxmax(), 'time']}")
    print(f"  Peak WSE: {df['wse'].max():.2f} ft at {df.loc[df['wse'].idxmax(), 'time']}")
    print(f"  Peak velocity: {df['velocity'].max():.2f} ft/s")

    return df


def extract_mesh_maximum_envelope(plan_number: str) -> dict:
    """
    Extract maximum envelopes for 2D mesh.

    Args:
        plan_number: Plan identifier

    Returns:
        Dictionary with maximum WSE, depth, and velocity
    """
    print("Extracting 2D mesh maximum envelopes...")

    # Extract maximum water surface
    max_wse = HdfResultsMesh.get_mesh_maximum(plan_number, variable="Water Surface")
    print(f"  Max WSE: {len(max_wse)} cells")

    # Extract maximum depth
    max_depth = HdfResultsMesh.get_mesh_maximum(plan_number, variable="Depth")
    print(f"  Max Depth: {len(max_depth)} cells")

    # Extract maximum velocity
    max_velocity = HdfResultsMesh.get_mesh_maximum(plan_number, variable="Velocity")
    print(f"  Max Velocity: {len(max_velocity)} cells")

    print(f"\nSummary statistics:")
    print(f"  Max WSE range: {max_wse['max_value'].min():.2f} to {max_wse['max_value'].max():.2f} ft")
    print(f"  Max depth range: {max_depth['max_value'].min():.2f} to {max_depth['max_value'].max():.2f} ft")
    print(f"  Max velocity range: {max_velocity['max_value'].min():.2f} to {max_velocity['max_value'].max():.2f} ft/s")

    return {
        'max_wse': max_wse,
        'max_depth': max_depth,
        'max_velocity': max_velocity
    }


def extract_mesh_at_timesteps(plan_number: str, timesteps: list) -> pd.DataFrame:
    """
    Extract 2D mesh data at specific timesteps.

    Args:
        plan_number: Plan identifier
        timesteps: List of timestep indices

    Returns:
        DataFrame with time series at cells
    """
    print(f"Extracting mesh data at timesteps: {timesteps}")

    mesh_ts = HdfResultsMesh.get_mesh_timeseries(
        plan_number,
        timestep_indices=timesteps,
        variables=["Water Surface", "Depth", "Velocity"]
    )

    print(f"  Extracted {len(mesh_ts)} records")
    print(f"  Timesteps: {mesh_ts['timestep'].unique()}")
    print(f"  Variables: {[c for c in mesh_ts.columns if c not in ['cell_id', 'timestep', 'datetime']]}")

    return mesh_ts


def compare_multiple_plans(plan_numbers: list, target_xs: str):
    """
    Compare hydrographs from multiple plans.

    Args:
        plan_numbers: List of plan identifiers
        target_xs: Cross section identifier
    """
    fig, ax = plt.subplots(figsize=(14, 7))

    for plan_num in plan_numbers:
        # Extract time series
        xsec_ts = HdfResultsXsec.get_xsec_timeseries(plan_num)

        # Get data at target location
        wse = xsec_ts["Water_Surface"].sel(cross_section=target_xs)

        # Plot
        ax.plot(wse.time, wse.values, label=f"Plan {plan_num}", linewidth=2)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Water Surface Elevation (ft)', fontsize=12)
    ax.set_title(f'WSE Comparison at {target_xs}', fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()


def plot_longitudinal_profile(xsec_ts, timestep_index: int):
    """
    Create longitudinal profile at specific time.

    Args:
        xsec_ts: xarray Dataset from get_xsec_timeseries()
        timestep_index: Index of timestep to plot
    """
    # Extract data at specific time
    wse_profile = xsec_ts["Water_Surface"].isel(time=timestep_index)
    time_str = pd.Timestamp(xsec_ts.time.values[timestep_index]).strftime('%Y-%m-%d %H:%M')

    # Get station values
    stations = pd.to_numeric(xsec_ts["Station"].values, errors='coerce')

    # Create plot
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(stations, wse_profile.values, 'b-', linewidth=2)
    ax.set_xlabel('River Station (ft)', fontsize=12)
    ax.set_ylabel('Water Surface Elevation (ft)', fontsize=12)
    ax.set_title(f'Longitudinal Profile at {time_str}', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)

    # Invert X axis (upstream on left)
    ax.invert_xaxis()

    plt.tight_layout()
    plt.show()


def export_time_series(plan_number: str, output_dir: Path):
    """
    Export unsteady time series to files.

    Args:
        plan_number: Plan identifier
        output_dir: Directory for output files
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract cross section time series
    xsec_ts = HdfResultsXsec.get_xsec_timeseries(plan_number)

    # Export maximum values
    peaks_df = analyze_peak_values(xsec_ts)
    peaks_path = output_dir / f"peak_values_p{plan_number}.csv"
    peaks_df.to_csv(peaks_path, index=False)
    print(f"Exported peaks to: {peaks_path}")

    # Export time series for each cross section (can be large)
    for xs in xsec_ts.cross_section.values[:5]:  # Limit to first 5 for example
        # Extract data for this cross section
        df = pd.DataFrame({
            'time': xsec_ts.time.values,
            'wse': xsec_ts["Water_Surface"].sel(cross_section=xs).values,
            'flow': xsec_ts["Flow"].sel(cross_section=xs).values,
            'velocity': xsec_ts["Velocity_Total"].sel(cross_section=xs).values
        })

        # Create safe filename
        safe_xs = xs.replace(' ', '_').replace('.', '')[:50]
        xs_path = output_dir / f"timeseries_{safe_xs}_p{plan_number}.csv"
        df.to_csv(xs_path, index=False)
        print(f"Exported {xs} to: {xs_path.name}")


def main():
    """Example workflow for unsteady flow results extraction."""

    # Extract example project
    project_path = RasExamples.extract_project("Balde Eagle Creek")

    # Initialize project
    init_ras_project(project_path, "6.6")

    # Specify unsteady plan
    plan_number = "01"

    # Verify plan type
    if HdfResultsPlan.is_steady_plan(plan_number):
        print(f"Plan {plan_number} is a steady state plan!")
        return

    print(f"Working with Plan {plan_number}")
    print("=" * 80)

    # Extract cross section time series
    print("\n1. Extracting cross section time series...")
    xsec_ts = extract_cross_section_timeseries(plan_number)

    # Analyze peak values
    print("\n2. Analyzing peak values...")
    peaks_df = analyze_peak_values(xsec_ts)

    # Extract hydrograph at specific location
    print("\n3. Extracting hydrograph at location...")
    target_xs = "Bald Eagle       Loc Hav          136202.3"
    hydrograph = extract_hydrograph_at_location(xsec_ts, target_xs)

    # Extract 2D mesh maximum envelopes
    print("\n4. Extracting 2D mesh maximum envelopes...")
    mesh_max = extract_mesh_maximum_envelope(plan_number)

    # Extract mesh at specific timesteps
    print("\n5. Extracting mesh at specific timesteps...")
    mesh_ts = extract_mesh_at_timesteps(plan_number, [0, 50, 100])

    # Plot longitudinal profile
    print("\n6. Plotting longitudinal profile...")
    plot_longitudinal_profile(xsec_ts, timestep_index=50)

    # Export results
    print("\n7. Exporting results...")
    output_dir = project_path / "unsteady_results"
    export_time_series(plan_number, output_dir)

    print("\n" + "=" * 80)
    print("Unsteady flow extraction complete!")


if __name__ == "__main__":
    main()
