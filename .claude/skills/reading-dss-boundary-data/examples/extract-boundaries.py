"""
Extract DSS Boundary Data Example

Demonstrates how to extract all DSS boundary condition data from a HEC-RAS project.
"""

from pathlib import Path
from ras_commander import RasExamples, init_ras_project, RasDss
import pandas as pd
import matplotlib.pyplot as plt

# Extract example project
print("Extracting BaldEagleCrkMulti2D example...")
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")

# Initialize project
print("\nInitializing HEC-RAS project...")
ras = init_ras_project(project_path, "6.6")

print(f"Project: {ras.project_name}")
print(f"Plans: {len(ras.plan_df)}")
print(f"Boundaries: {len(ras.boundaries_df)}")

# Focus on plan 07
plan_number = "07"
plan_boundaries = ras.boundaries_df[
    ras.boundaries_df['unsteady_number'] == plan_number
].copy()

print(f"\nPlan {plan_number} has {len(plan_boundaries)} boundary conditions")

# Extract all DSS boundary data
print("\n" + "=" * 80)
print("Extracting DSS Boundary Data")
print("=" * 80)

enhanced = RasDss.extract_boundary_timeseries(
    plan_boundaries,
    ras_object=ras
)

# Summary statistics
print("\n" + "=" * 80)
print("Extraction Results")
print("=" * 80)

manual_bc = enhanced[
    (enhanced['Use DSS'] == False) |
    (enhanced['Use DSS'].isna())
]
dss_bc = enhanced[
    (enhanced['Use DSS'] == True) |
    (enhanced['Use DSS'] == 'True')
]

print(f"\nTotal boundaries: {len(enhanced)}")
print(f"Manual boundaries: {len(manual_bc)}")
print(f"DSS boundaries: {len(dss_bc)}")

# DSS boundary details
print("\n" + "=" * 80)
print("DSS Boundary Details")
print("=" * 80)

for idx, row in dss_bc.iterrows():
    if row['dss_timeseries'] is not None:
        df = row['dss_timeseries']

        print(f"\n{row['bc_type']}:")
        print(f"  Location: {row['river_reach_name']} RS {row['river_station']}")
        print(f"  DSS File: {row['DSS File']}")
        print(f"  DSS Path: {row['DSS Path']}")
        print(f"  Data Points: {len(df)}")
        print(f"  Date Range: {df.index.min()} to {df.index.max()}")
        print(f"  Value Range: {df['value'].min():.2f} to {df['value'].max():.2f} {df.attrs['units']}")
        print(f"  Mean: {df['value'].mean():.2f} {df.attrs['units']}")

# Manual boundary details
print("\n" + "=" * 80)
print("Manual Boundary Details")
print("=" * 80)

for idx, row in manual_bc.iterrows():
    print(f"\n{row['bc_type']}:")
    print(f"  Location: {row.get('river_reach_name', 'N/A')} RS {row.get('river_station', 'N/A')}")

    if row.get('hydrograph_num_values'):
        print(f"  Data Points: {row['hydrograph_num_values']}")

# Export summary to CSV
print("\n" + "=" * 80)
print("Exporting Data")
print("=" * 80)

# Create export DataFrame (without DataFrame column)
export_df = enhanced.drop(columns=['dss_timeseries']).copy()

# Add DSS summary statistics
for idx, row in enhanced.iterrows():
    is_dss = (row['Use DSS'] == True) or (row['Use DSS'] == 'True')
    if is_dss and row['dss_timeseries'] is not None:
        df = row['dss_timeseries']
        export_df.at[idx, 'dss_points'] = len(df)
        export_df.at[idx, 'dss_mean'] = df['value'].mean()
        export_df.at[idx, 'dss_max'] = df['value'].max()
        export_df.at[idx, 'dss_min'] = df['value'].min()
        export_df.at[idx, 'dss_units'] = df.attrs.get('units', '')

# Save summary
summary_file = project_path / f"plan_{plan_number}_boundaries_summary.csv"
export_df.to_csv(summary_file, index=False)
print(f"\nSummary saved to: {summary_file}")

# Export individual DSS time series to CSV
dss_export_dir = project_path / "dss_timeseries"
dss_export_dir.mkdir(exist_ok=True)

for idx, row in dss_bc.iterrows():
    if row['dss_timeseries'] is not None:
        df = row['dss_timeseries']

        # Create safe filename
        bc_type = row['bc_type'].replace(' ', '_').replace('/', '_')
        location = str(row['river_station']).replace('.', '_')
        filename = f"{bc_type}_{location}.csv"

        # Save with metadata header
        filepath = dss_export_dir / filename
        with open(filepath, 'w') as f:
            # Write metadata
            f.write(f"# Boundary Type: {row['bc_type']}\n")
            f.write(f"# Location: {row['river_reach_name']} RS {row['river_station']}\n")
            f.write(f"# DSS File: {row['DSS File']}\n")
            f.write(f"# DSS Path: {row['DSS Path']}\n")
            f.write(f"# Units: {df.attrs.get('units', 'N/A')}\n")
            f.write(f"# Points: {len(df)}\n")
            f.write("#\n")

        # Append data
        df.to_csv(filepath, mode='a', header=True)
        print(f"Exported: {filename}")

print(f"\nTime series exported to: {dss_export_dir}")

# Create visualization
print("\n" + "=" * 80)
print("Creating Plots")
print("=" * 80)

successful_dss = enhanced[
    ((enhanced['Use DSS'] == True) | (enhanced['Use DSS'] == 'True')) &
    (enhanced['dss_timeseries'].notna())
]

if len(successful_dss) > 0:
    n_plots = len(successful_dss)
    fig, axes = plt.subplots(n_plots, 1, figsize=(14, 4 * n_plots))

    if n_plots == 1:
        axes = [axes]

    for ax, (idx, row) in zip(axes, successful_dss.iterrows()):
        df = row['dss_timeseries']

        # Plot
        df['value'].plot(ax=ax, linewidth=1.5, color='steelblue')

        # Format
        title = f"{row['bc_type']} - {row['river_reach_name']} RS {row['river_station']}"
        ax.set_title(title, fontsize=11, fontweight='bold')
        ax.set_xlabel('Date/Time', fontsize=9)
        ax.set_ylabel(f"Flow ({df.attrs.get('units', '')})", fontsize=9)
        ax.grid(True, alpha=0.3)

        # Add DSS path
        ax.text(0.02, 0.98, f"DSS: {row['DSS Path']}",
                transform=ax.transAxes, fontsize=8,
                verticalalignment='top', family='monospace',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.3))

    plt.tight_layout()

    # Save plot
    plot_file = project_path / f"plan_{plan_number}_dss_boundaries.png"
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    print(f"\nPlot saved to: {plot_file}")

    plt.show()
else:
    print("\nNo DSS boundaries to plot")

# Final summary
print("\n" + "=" * 80)
print("Complete!")
print("=" * 80)
print(f"\nExtracted {len(successful_dss)} DSS boundary time series")
print(f"Total data points: {sum(len(row['dss_timeseries']) for _, row in successful_dss.iterrows())}")
print(f"\nOutputs:")
print(f"  - {summary_file}")
print(f"  - {dss_export_dir}")
if len(successful_dss) > 0:
    print(f"  - {plot_file}")
