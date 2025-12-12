"""
Complete USGS Gauge Integration Workflow

Demonstrates end-to-end workflow from spatial discovery to model validation.

Stages:
1. Spatial Discovery - Find gauges within project bounds
2. Data Retrieval - Download flow/stage data from USGS NWIS
3. Gauge Matching - Associate gauges with HEC-RAS features
4. Time Series Processing - Resample and prepare for HEC-RAS
5. Boundary Generation - Create BC tables and update .u## files
6. Initial Conditions - Set IC values from observed data
7. Model Execution - Run HEC-RAS with USGS boundaries
8. Results Extraction - Extract modeled time series
9. Validation - Calculate metrics and generate plots

Usage:
    python complete-workflow.py
"""

from pathlib import Path
from datetime import datetime
from ras_commander import init_ras_project, ras, RasCmdr
from ras_commander.hdf import HdfResultsXsec
from ras_commander.usgs import (
    UsgsGaugeSpatial,
    RasUsgsCore,
    GaugeMatcher,
    RasUsgsTimeSeries,
    RasUsgsBoundaryGeneration,
    InitialConditions,
    metrics,
    visualization,
    RasUsgsFileIo
)


def main():
    """Execute complete USGS integration workflow"""

    # ==========================================================================
    # CONFIGURATION
    # ==========================================================================

    project_folder = r"C:\Projects\PotomacRiver"
    ras_version = "6.5"
    sim_start = "2023-09-01"
    sim_end = "2023-09-15"
    primary_gauge = "01646500"  # Potomac River at Little Falls
    downstream_gauge = "01647500"

    # ==========================================================================
    # STAGE 1: SPATIAL DISCOVERY
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 1: SPATIAL DISCOVERY")
    print("=" * 70)

    # Initialize project
    init_ras_project(project_folder, ras_version)
    print(f"Project initialized: {project_folder}")

    # Find gauges within 10 miles
    gauges_gdf = UsgsGaugeSpatial.find_gauges_in_project(
        project_folder=project_folder, buffer_miles=10.0
    )

    print(f"\nFound {len(gauges_gdf)} USGS gauges")
    print(gauges_gdf[["site_no", "station_nm", "drain_area_va"]].head())

    # Filter for gauges with data in simulation period
    gauges_with_data = UsgsGaugeSpatial.get_project_gauges_with_data(
        project_folder=project_folder,
        start_date=sim_start,
        end_date=sim_end,
        buffer_miles=10.0,
    )

    print(f"\nGauges with data ({sim_start} to {sim_end}): {len(gauges_with_data)}")

    # ==========================================================================
    # STAGE 2: DATA RETRIEVAL
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 2: DATA RETRIEVAL")
    print("=" * 70)

    # Check data availability
    available = RasUsgsCore.check_data_availability(
        site_no=primary_gauge,
        start_date=sim_start,
        end_date=sim_end,
        parameter="flow",
    )

    if not available:
        print(f"WARNING: No data available for gauge {primary_gauge}")
        return

    # Retrieve upstream flow data
    print(f"\nRetrieving flow data from USGS NWIS...")
    upstream_flow = RasUsgsCore.retrieve_flow_data(
        site_no=primary_gauge, start_date=sim_start, end_date=sim_end, service="iv"
    )

    print(f"Retrieved {len(upstream_flow)} observations")
    print(f"Flow range: {upstream_flow['value'].min():.0f} to {upstream_flow['value'].max():.0f} cfs")

    # Retrieve downstream stage data
    downstream_stage = RasUsgsCore.retrieve_stage_data(
        site_no=downstream_gauge, start_date=sim_start, end_date=sim_end, service="iv"
    )

    print(f"\nRetrieved stage data: {len(downstream_stage)} observations")

    # Get metadata
    metadata = RasUsgsCore.get_gauge_metadata(site_no=primary_gauge)
    print(f"\nPrimary Gauge: {metadata['station_nm']}")
    print(f"Drainage area: {metadata['drain_area_va']:.1f} sq mi")

    # Cache data locally
    gauge_data_dir = RasUsgsFileIo.get_gauge_data_dir(project_folder)
    RasUsgsFileIo.cache_gauge_data(
        data=upstream_flow,
        site_no=primary_gauge,
        parameter="flow",
        output_dir=gauge_data_dir,
    )
    print(f"\nData cached to: {gauge_data_dir}")

    # ==========================================================================
    # STAGE 3: GAUGE MATCHING
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 3: GAUGE MATCHING")
    print("=" * 70)

    # Automatically match gauges to HEC-RAS features
    matches = GaugeMatcher.auto_match_gauges(
        gauges_gdf=gauges_gdf, project_folder=project_folder
    )

    print(f"\nGauge Matching Results:")
    for idx, match in matches.head().iterrows():
        print(
            f"  {match['site_no']}: {match['matched_feature']} "
            f"(distance: {match['distance_ft']:.0f} ft)"
        )

    # Get primary gauge match
    primary_match = matches[matches["site_no"] == primary_gauge].iloc[0]
    print(f"\nPrimary Gauge Matched to:")
    print(f"  River: {primary_match['river']}")
    print(f"  Reach: {primary_match['reach']}")
    print(f"  RS: {primary_match['rs']}")

    # ==========================================================================
    # STAGE 4: TIME SERIES PROCESSING
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 4: TIME SERIES PROCESSING")
    print("=" * 70)

    # Check for gaps
    gaps = RasUsgsTimeSeries.check_data_gaps(upstream_flow)
    if gaps["has_gaps"]:
        print(f"\nWARNING: {gaps['num_gaps']} gaps detected")
        upstream_flow = RasUsgsTimeSeries.fill_data_gaps(upstream_flow, method="linear")
        print("Gaps filled using linear interpolation")
    else:
        print("\nNo data gaps detected")

    # Resample to HEC-RAS interval
    print("\nResampling to 1HOUR interval...")
    upstream_resampled = RasUsgsTimeSeries.resample_to_hecras_interval(
        upstream_flow, interval="1HOUR"
    )

    print(f"Resampled to {len(upstream_resampled)} hourly values")

    # Extract simulation period
    upstream_sim = RasUsgsTimeSeries.extract_simulation_period(
        upstream_resampled, start_datetime=f"{sim_start} 00:00", end_datetime=f"{sim_end} 23:59"
    )

    print(f"Extracted simulation period: {len(upstream_sim)} values")

    # ==========================================================================
    # STAGE 5: BOUNDARY CONDITION GENERATION
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 5: BOUNDARY CONDITION GENERATION")
    print("=" * 70)

    # Generate upstream flow BC table
    print("\nGenerating upstream flow boundary table...")
    bc_upstream = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
        flow_data=upstream_sim,
        river=primary_match["river"],
        reach=primary_match["reach"],
        rs=primary_match["rs"],
    )

    print(f"Generated {len(bc_upstream)} lines")

    # Validate format
    is_valid = RasUsgsBoundaryGeneration.validate_boundary_format(bc_upstream)
    print(f"Format validation: {'PASS' if is_valid else 'FAIL'}")

    # Generate downstream stage BC
    downstream_match = matches[matches["site_no"] == downstream_gauge].iloc[0]
    downstream_resampled = RasUsgsTimeSeries.resample_to_hecras_interval(
        downstream_stage, interval="1HOUR"
    )

    bc_downstream = RasUsgsBoundaryGeneration.generate_stage_hydrograph_table(
        stage_data=downstream_resampled,
        river=downstream_match["river"],
        reach=downstream_match["reach"],
        rs=downstream_match["rs"],
    )

    # Update unsteady file
    unsteady_file = ras.unsteady_df[ras.unsteady_df["plan_number"] == "01"]["path"].iloc[0]

    RasUsgsBoundaryGeneration.update_boundary_hydrograph(
        unsteady_file=str(unsteady_file), bc_table=bc_upstream, bc_line_number=15
    )

    RasUsgsBoundaryGeneration.update_boundary_hydrograph(
        unsteady_file=str(unsteady_file), bc_table=bc_downstream, bc_line_number=150
    )

    print(f"\nBoundary conditions updated: {unsteady_file.name}")

    # ==========================================================================
    # STAGE 6: INITIAL CONDITIONS
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 6: INITIAL CONDITIONS")
    print("=" * 70)

    # Get IC value
    ic_value = InitialConditions.get_ic_value_from_usgs(
        flow_data=upstream_sim, start_datetime=f"{sim_start} 00:00"
    )

    print(f"\nInitial flow: {ic_value:.0f} cfs")

    # Create IC line
    ic_line = InitialConditions.create_ic_line(
        river=primary_match["river"],
        reach=primary_match["reach"],
        rs=primary_match["rs"],
        value=ic_value,
        ic_type="flow",
    )

    # Update unsteady file
    InitialConditions.update_initial_conditions(
        unsteady_file=str(unsteady_file), ic_line=ic_line, ic_line_number=10
    )

    print("Initial conditions updated")

    # ==========================================================================
    # STAGE 7: MODEL EXECUTION
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 7: MODEL EXECUTION")
    print("=" * 70)

    dest_folder = Path(project_folder) / "runs" / f"USGS_{sim_start}_{sim_end}"

    print(f"\nExecuting HEC-RAS plan 01...")
    print(f"Destination: {dest_folder}")

    RasCmdr.compute_plan(
        plan_number="01", dest_folder=str(dest_folder), num_cores=4, overwrite_dest=True
    )

    print("Model execution complete")

    # ==========================================================================
    # STAGE 8: RESULTS EXTRACTION
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 8: RESULTS EXTRACTION")
    print("=" * 70)

    # Extract modeled time series
    print(f"\nExtracting modeled results...")
    modeled_df = HdfResultsXsec.get_xsec_timeseries(
        plan_number="01",
        river=primary_match["river"],
        reach=primary_match["reach"],
        rs=primary_match["rs"],
        dest_folder=str(dest_folder),
    )

    print(f"Extracted {len(modeled_df)} timesteps")
    print(
        f"Modeled flow range: {modeled_df['Flow'].min():.0f} to {modeled_df['Flow'].max():.0f} cfs"
    )

    # ==========================================================================
    # STAGE 9: VALIDATION
    # ==========================================================================

    print("\n" + "=" * 70)
    print("STAGE 9: VALIDATION")
    print("=" * 70)

    # Align time series
    observed_aligned, modeled_aligned = RasUsgsTimeSeries.align_timeseries(
        observed=upstream_sim, modeled=modeled_df, method="nearest"
    )

    print(f"\nAligned to {len(observed_aligned)} common timesteps")

    # Calculate all metrics
    all_metrics = metrics.calculate_all_metrics(
        observed=observed_aligned["value"].values,
        modeled=modeled_aligned["Flow"].values,
        observed_times=observed_aligned["datetime"].values,
        modeled_times=modeled_aligned.index.values,
        timestep_hours=1,
    )

    # Print summary
    print("\n" + "=" * 70)
    print("VALIDATION METRICS SUMMARY")
    print("=" * 70)
    print(f"Gauge: USGS-{primary_gauge} ({metadata['station_nm']})")
    print(f"Period: {sim_start} to {sim_end}")
    print(f"Observations: {len(observed_aligned)}")
    print("\nGoodness-of-Fit:")
    print(f"  NSE:              {all_metrics['nse']:.3f}")
    print(f"  KGE:              {all_metrics['kge']:.3f}")
    print(f"  Correlation:      {all_metrics['correlation']:.3f}")
    print("\nError Metrics:")
    print(f"  RMSE:             {all_metrics['rmse']:,.0f} cfs")
    print(f"  MAE:              {all_metrics['mae']:,.0f} cfs")
    print(f"  Bias:             {all_metrics['bias']:+,.0f} cfs")
    print("\nPeak Performance:")
    print(f"  Peak Error:       {all_metrics['peak_error_pct']:+.1f}%")
    print(f"  Timing Error:     {all_metrics['timing_error_hours']:+.1f} hours")
    print("\nVolume Balance:")
    print(f"  Volume Bias:      {all_metrics['volume_bias_pct']:+.1f}%")
    print("=" * 70)

    # Interpret performance
    if all_metrics["nse"] > 0.75:
        performance = "VERY GOOD" if all_metrics["nse"] > 0.85 else "GOOD"
    elif all_metrics["nse"] > 0.50:
        performance = "SATISFACTORY"
    else:
        performance = "UNSATISFACTORY - Further calibration required"

    print(f"\nOverall Performance: {performance}")

    # Generate validation plots
    print("\n" + "=" * 70)
    print("GENERATING VALIDATION PLOTS")
    print("=" * 70)

    output_dir = Path(project_folder) / "validation_output"
    output_dir.mkdir(exist_ok=True)

    # Time series comparison
    visualization.plot_timeseries_comparison(
        observed=observed_aligned,
        modeled=modeled_aligned,
        title=f"{metadata['station_nm']} - Model Validation",
        metrics=all_metrics,
        output_file=str(output_dir / "timeseries_comparison.png"),
    )

    # Scatter plot
    visualization.plot_scatter_comparison(
        observed=observed_aligned["value"].values,
        modeled=modeled_aligned["Flow"].values,
        title="Observed vs Modeled Flow",
        metrics=all_metrics,
        output_file=str(output_dir / "scatter_comparison.png"),
    )

    # Residual diagnostics
    visualization.plot_residuals(
        observed=observed_aligned["value"].values,
        modeled=modeled_aligned["Flow"].values,
        observed_times=observed_aligned["datetime"].values,
        output_file=str(output_dir / "residual_diagnostics.png"),
    )

    # Flow duration curve
    visualization.plot_flow_duration_curve(
        observed=observed_aligned["value"].values,
        modeled=modeled_aligned["Flow"].values,
        output_file=str(output_dir / "flow_duration_curve.png"),
    )

    print(f"\nValidation plots saved to: {output_dir}")

    # ==========================================================================
    # WORKFLOW COMPLETE
    # ==========================================================================

    print("\n" + "=" * 70)
    print("WORKFLOW COMPLETE")
    print("=" * 70)
    print(f"\nProject: {project_folder}")
    print(f"Simulation: {sim_start} to {sim_end}")
    print(f"Primary Gauge: USGS-{primary_gauge}")
    print(f"Performance: {performance}")
    print(f"\nOutputs:")
    print(f"  Validation plots: {output_dir}")
    print(f"  Cached data: {gauge_data_dir}")
    print(f"  Model results: {dest_folder}")
    print("\nNext steps:")
    print("  1. Review validation plots")
    print("  2. Check residual patterns for systematic errors")
    print("  3. Document validation results")
    print("  4. If unsatisfactory, adjust calibration parameters")


if __name__ == "__main__":
    main()
