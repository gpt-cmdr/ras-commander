"""
Steady Flow Results Extraction Examples

Demonstrates common patterns for extracting steady state flow results
from HEC-RAS HDF files.
"""

from pathlib import Path
from ras_commander import (
    init_ras_project,
    HdfResultsPlan,
    RasExamples
)
import pandas as pd
import matplotlib.pyplot as plt


def extract_all_profiles(plan_number: str) -> pd.DataFrame:
    """
    Extract water surface elevations for all steady state profiles.

    Args:
        plan_number: Plan identifier (e.g., "02")

    Returns:
        DataFrame with columns: River, Reach, Station, Profile, WSE
    """
    # Check if plan is steady state
    if not HdfResultsPlan.is_steady_plan(plan_number):
        raise ValueError(f"Plan {plan_number} is not a steady state plan")

    # Extract all profiles at once
    wse_all = HdfResultsPlan.get_steady_wse(plan_number)

    print(f"Extracted {len(wse_all)} records")
    print(f"Profiles: {wse_all['Profile'].unique().tolist()}")

    return wse_all


def extract_single_profile(plan_number: str, profile_name: str) -> pd.DataFrame:
    """
    Extract water surface elevations for a specific profile.

    Args:
        plan_number: Plan identifier
        profile_name: Profile name (e.g., "100 year")

    Returns:
        DataFrame with columns: River, Reach, Station, WSE
    """
    wse = HdfResultsPlan.get_steady_wse(plan_number, profile_name=profile_name)

    print(f"Profile '{profile_name}':")
    print(f"  Number of cross sections: {len(wse)}")
    print(f"  Min WSE: {wse['WSE'].min():.2f} ft")
    print(f"  Max WSE: {wse['WSE'].max():.2f} ft")
    print(f"  Mean WSE: {wse['WSE'].mean():.2f} ft")

    return wse


def compare_return_periods(plan_number: str) -> pd.DataFrame:
    """
    Compare water surface elevations across return periods.

    Args:
        plan_number: Plan identifier

    Returns:
        Pivot table with profiles as columns
    """
    # Extract all profiles
    wse_all = HdfResultsPlan.get_steady_wse(plan_number)

    # Create pivot table for easy comparison
    wse_pivot = wse_all.pivot_table(
        index=['River', 'Reach', 'Station'],
        columns='Profile',
        values='WSE'
    )

    # Calculate differences
    if '100 year' in wse_pivot.columns and '.5 year' in wse_pivot.columns:
        wse_pivot['Diff_100yr_vs_05yr'] = wse_pivot['100 year'] - wse_pivot['.5 year']

        print("\nDifference between 100-year and 0.5-year profiles:")
        print(f"  Maximum difference: {wse_pivot['Diff_100yr_vs_05yr'].max():.2f} ft")
        print(f"  Minimum difference: {wse_pivot['Diff_100yr_vs_05yr'].min():.2f} ft")
        print(f"  Average difference: {wse_pivot['Diff_100yr_vs_05yr'].mean():.2f} ft")

        # Show locations with largest differences
        print("\nTop 5 locations with largest increase:")
        top_diff = wse_pivot.nlargest(5, 'Diff_100yr_vs_05yr')[
            ['.5 year', '100 year', 'Diff_100yr_vs_05yr']
        ]
        print(top_diff)

    return wse_pivot


def extract_velocity_and_flow(plan_number: str, profile_name: str) -> dict:
    """
    Extract velocity and flow data for a specific profile.

    Args:
        plan_number: Plan identifier
        profile_name: Profile name

    Returns:
        Dictionary with DataFrames for velocity and flow
    """
    # First discover available variables
    vars_dict = HdfResultsPlan.list_steady_variables(plan_number)

    print(f"Available variables for extraction:")
    print(f"  Cross section vars: {vars_dict['cross_sections']}")
    print(f"  Additional vars: {len(vars_dict['additional'])} available")

    # Extract velocity and flow
    velocity = HdfResultsPlan.get_steady_data(
        plan_number,
        variable="Velocity Total",
        profile_name=profile_name
    )

    flow = HdfResultsPlan.get_steady_data(
        plan_number,
        variable="Flow Total",
        profile_name=profile_name
    )

    return {
        'velocity': velocity,
        'flow': flow
    }


def plot_water_surface_profiles(plan_number: str, output_path: Path = None):
    """
    Plot water surface profiles for all return periods.

    Args:
        plan_number: Plan identifier
        output_path: Optional path to save figure
    """
    # Extract all profiles
    wse_all = HdfResultsPlan.get_steady_wse(plan_number)
    profiles = wse_all['Profile'].unique()

    # Create plot
    fig, ax = plt.subplots(figsize=(15, 8))

    # Plot each profile
    for profile in profiles:
        profile_data = wse_all[wse_all['Profile'] == profile]
        # Convert station to numeric for plotting
        stations = pd.to_numeric(profile_data['Station'], errors='coerce')
        ax.plot(stations, profile_data['WSE'], label=profile, linewidth=2)

    ax.set_xlabel('River Station (ft)', fontsize=12)
    ax.set_ylabel('Water Surface Elevation (ft)', fontsize=12)
    ax.set_title('Steady State Water Surface Profiles', fontsize=14, fontweight='bold')
    ax.legend(title='Return Period', loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Invert X axis (upstream on left)
    ax.invert_xaxis()

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"\nPlot saved to: {output_path}")

    plt.show()


def export_results(plan_number: str, output_dir: Path):
    """
    Export steady state results to CSV files.

    Args:
        plan_number: Plan identifier
        output_dir: Directory for output files
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract all profiles
    wse_all = HdfResultsPlan.get_steady_wse(plan_number)

    # Export all profiles combined
    all_profiles_path = output_dir / f"steady_wse_all_profiles_p{plan_number}.csv"
    wse_all.to_csv(all_profiles_path, index=False)
    print(f"Exported all profiles to: {all_profiles_path}")

    # Export individual profiles
    for profile in wse_all['Profile'].unique():
        profile_data = wse_all[wse_all['Profile'] == profile]
        safe_name = profile.replace(' ', '_').replace('.', '')
        profile_path = output_dir / f"steady_wse_{safe_name}_p{plan_number}.csv"
        profile_data.to_csv(profile_path, index=False)
        print(f"Exported {profile} to: {profile_path.name}")

    # Export comparison table
    wse_pivot = wse_all.pivot_table(
        index=['River', 'Reach', 'Station'],
        columns='Profile',
        values='WSE'
    )
    comparison_path = output_dir / f"steady_wse_comparison_p{plan_number}.csv"
    wse_pivot.to_csv(comparison_path)
    print(f"Exported comparison to: {comparison_path}")


def main():
    """Example workflow for steady flow results extraction."""

    # Extract example project
    project_path = RasExamples.extract_project("Balde Eagle Creek")

    # Initialize project
    init_ras_project(project_path, "6.6")

    # Specify steady state plan
    plan_number = "02"

    # Verify plan type
    if not HdfResultsPlan.is_steady_plan(plan_number):
        print(f"Plan {plan_number} is not a steady state plan!")
        return

    print(f"Working with Plan {plan_number}")
    print("=" * 80)

    # List available profiles
    profiles = HdfResultsPlan.get_steady_profile_names(plan_number)
    print(f"\nAvailable profiles: {profiles}")

    # Extract all profiles
    print("\n1. Extracting all profiles...")
    wse_all = extract_all_profiles(plan_number)

    # Extract single profile
    print("\n2. Extracting 100-year profile...")
    wse_100 = extract_single_profile(plan_number, "100 year")

    # Compare return periods
    print("\n3. Comparing return periods...")
    wse_pivot = compare_return_periods(plan_number)

    # Extract velocity and flow
    print("\n4. Extracting velocity and flow...")
    hydraulics = extract_velocity_and_flow(plan_number, "100 year")

    # Plot profiles
    print("\n5. Plotting water surface profiles...")
    plot_water_surface_profiles(plan_number)

    # Export results
    print("\n6. Exporting results...")
    output_dir = project_path / "steady_results"
    export_results(plan_number, output_dir)

    print("\n" + "=" * 80)
    print("Steady flow extraction complete!")


if __name__ == "__main__":
    main()
