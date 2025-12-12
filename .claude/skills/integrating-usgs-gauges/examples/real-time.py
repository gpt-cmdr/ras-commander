"""
Real-Time USGS Gauge Monitoring for Operational Forecasting

Demonstrates real-time gauge monitoring patterns for:
1. Latest gauge readings
2. Threshold detection (flood stage)
3. Rapid change detection (flash flood conditions)
4. Continuous monitoring with callbacks
5. Automated model triggering

Use Cases:
- Operational flood forecasting
- Early warning systems
- Automated model execution
- Real-time boundary condition updates

Usage:
    python real-time.py

Requirements:
    pip install dataretrieval
"""

from pathlib import Path
from datetime import datetime, timedelta
from ras_commander import init_ras_project, RasCmdr
from ras_commander.usgs import (
    RasUsgsRealTime,
    RasUsgsCore,
    RasUsgsTimeSeries,
    RasUsgsBoundaryGeneration,
)


# ==============================================================================
# PATTERN 1: GET LATEST GAUGE READING
# ==============================================================================


def get_latest_reading():
    """Get most recent gauge reading (updated hourly by USGS)"""

    print("\n" + "=" * 70)
    print("PATTERN 1: LATEST GAUGE READING")
    print("=" * 70)

    site_no = "01646500"  # Potomac River at Little Falls

    # Get latest flow value
    latest = RasUsgsRealTime.get_latest_value(site_no=site_no, parameter="flow")

    print(f"\nLatest Reading:")
    print(f"  Gauge: USGS-{site_no}")
    print(f"  Value: {latest['value']:,.0f} cfs")
    print(f"  Time: {latest['datetime']}")
    print(f"  Age: {(datetime.now() - latest['datetime']).total_seconds() / 3600:.1f} hours")

    # Get latest stage
    latest_stage = RasUsgsRealTime.get_latest_value(site_no=site_no, parameter="stage")

    print(f"\n  Stage: {latest_stage['value']:.2f} ft")
    print(f"  Time: {latest_stage['datetime']}")


# ==============================================================================
# PATTERN 2: RECENT DATA FOR TREND ANALYSIS
# ==============================================================================


def analyze_recent_trends():
    """Retrieve recent data to analyze trends"""

    print("\n" + "=" * 70)
    print("PATTERN 2: RECENT TREND ANALYSIS")
    print("=" * 70)

    site_no = "01646500"

    # Get last 24 hours of data
    recent_data = RasUsgsRealTime.get_recent_data(
        site_no=site_no, hours=24, parameter="flow"
    )

    print(f"\nRecent Data (last 24 hours):")
    print(f"  Observations: {len(recent_data)}")
    print(f"  Current flow: {recent_data['value'].iloc[-1]:,.0f} cfs")
    print(f"  24hr ago: {recent_data['value'].iloc[0]:,.0f} cfs")
    print(f"  Change: {recent_data['value'].iloc[-1] - recent_data['value'].iloc[0]:+,.0f} cfs")
    print(f"  Peak (24hr): {recent_data['value'].max():,.0f} cfs")
    print(f"  Mean (24hr): {recent_data['value'].mean():,.0f} cfs")

    # Calculate rate of change (last 6 hours)
    recent_6hr = recent_data.tail(6)
    if len(recent_6hr) > 1:
        rate = (recent_6hr["value"].iloc[-1] - recent_6hr["value"].iloc[0]) / 6
        print(f"  Rate (6hr): {rate:+,.0f} cfs/hour")


# ==============================================================================
# PATTERN 3: THRESHOLD DETECTION (FLOOD STAGE)
# ==============================================================================


def detect_threshold_crossing():
    """Detect when gauge exceeds flood stage threshold"""

    print("\n" + "=" * 70)
    print("PATTERN 3: THRESHOLD DETECTION")
    print("=" * 70)

    site_no = "01646500"
    flood_threshold = 50000  # cfs (example flood stage)

    # Check if current reading exceeds threshold
    is_flooding = RasUsgsRealTime.detect_threshold_crossing(
        site_no=site_no, threshold=flood_threshold, parameter="flow"
    )

    latest = RasUsgsRealTime.get_latest_value(site_no=site_no, parameter="flow")

    print(f"\nThreshold Monitoring:")
    print(f"  Flood threshold: {flood_threshold:,.0f} cfs")
    print(f"  Current flow: {latest['value']:,.0f} cfs")
    print(f"  Status: {'FLOODING' if is_flooding else 'Normal'}")

    if is_flooding:
        exceedance = latest["value"] - flood_threshold
        print(f"  Exceedance: {exceedance:,.0f} cfs ({exceedance/flood_threshold*100:.1f}%)")
    else:
        margin = flood_threshold - latest["value"]
        print(f"  Margin: {margin:,.0f} cfs below threshold")


# ==============================================================================
# PATTERN 4: RAPID CHANGE DETECTION (FLASH FLOOD)
# ==============================================================================


def detect_rapid_change():
    """Detect flash flood conditions (rapid rise/recession)"""

    print("\n" + "=" * 70)
    print("PATTERN 4: RAPID CHANGE DETECTION")
    print("=" * 70)

    site_no = "01646500"
    rate_threshold = 5000  # cfs per hour (flash flood indicator)

    # Detect rapid rise
    rapid_rise = RasUsgsRealTime.detect_rapid_change(
        site_no=site_no, rate_threshold=rate_threshold, window_hours=3, parameter="flow"
    )

    print(f"\nFlash Flood Detection:")
    print(f"  Rate threshold: {rate_threshold:,.0f} cfs/hour")
    print(f"  Window: 3 hours")
    print(f"  Rapid rise detected: {'YES - FLASH FLOOD CONDITIONS' if rapid_rise else 'No'}")

    # Get recent data to show actual rate
    recent = RasUsgsRealTime.get_recent_data(site_no=site_no, hours=3, parameter="flow")

    if len(recent) > 1:
        actual_rate = (recent["value"].iloc[-1] - recent["value"].iloc[0]) / 3
        print(f"  Actual rate (3hr): {actual_rate:+,.0f} cfs/hour")

        if abs(actual_rate) > rate_threshold:
            print(f"  WARNING: Rapid {'rise' if actual_rate > 0 else 'recession'} in progress")


# ==============================================================================
# PATTERN 5: CONTINUOUS MONITORING WITH CALLBACK
# ==============================================================================


def continuous_monitoring():
    """Monitor gauge continuously and trigger callback on threshold exceedance"""

    print("\n" + "=" * 70)
    print("PATTERN 5: CONTINUOUS MONITORING")
    print("=" * 70)

    site_no = "01646500"
    threshold = 50000  # cfs

    def alert_callback(site_no, value, threshold):
        """Callback function triggered on threshold exceedance"""
        print(f"\n{'!'*70}")
        print(f"ALERT: Gauge {site_no} exceeded threshold!")
        print(f"  Current: {value:,.0f} cfs")
        print(f"  Threshold: {threshold:,.0f} cfs")
        print(f"  Exceedance: {value - threshold:,.0f} cfs")
        print(f"  Time: {datetime.now()}")
        print(f"{'!'*70}\n")

        # Trigger actions (e.g., send notification, execute model)
        print("Actions triggered:")
        print("  - Email notification sent")
        print("  - Emergency contacts alerted")
        print("  - Forecast model queued for execution")

    print(f"\nMonitoring Setup:")
    print(f"  Gauge: USGS-{site_no}")
    print(f"  Threshold: {threshold:,.0f} cfs")
    print(f"  Check interval: 15 minutes")
    print(f"\nNote: This is a demonstration - monitoring would run continuously")
    print("      Use Ctrl+C to stop actual monitoring loop")

    # In production, this would run continuously:
    # RasUsgsRealTime.monitor_gauge(
    #     site_no=site_no,
    #     threshold=threshold,
    #     callback=alert_callback,
    #     interval_minutes=15,
    #     parameter="flow"
    # )


# ==============================================================================
# PATTERN 6: AUTOMATED MODEL TRIGGERING
# ==============================================================================


def automated_model_triggering():
    """Trigger HEC-RAS model execution when threshold exceeded"""

    print("\n" + "=" * 70)
    print("PATTERN 6: AUTOMATED MODEL TRIGGERING")
    print("=" * 70)

    project_folder = r"C:\Projects\PotomacRiver"
    site_no = "01646500"
    threshold = 50000  # cfs

    def run_forecast_model(site_no, value, threshold):
        """Execute HEC-RAS forecast model when threshold exceeded"""

        print(f"\nThreshold exceeded: {value:,.0f} cfs > {threshold:,.0f} cfs")
        print("Initiating forecast model execution...")

        # Initialize project
        init_ras_project(project_folder, "6.5")

        # Get recent data for boundary conditions (last 24 hours + 48 hour forecast)
        recent_data = RasUsgsRealTime.get_recent_data(
            site_no=site_no, hours=24, parameter="flow"
        )

        print(f"Retrieved {len(recent_data)} recent observations")

        # Resample to HEC-RAS interval
        resampled = RasUsgsTimeSeries.resample_to_hecras_interval(recent_data, interval="1HOUR")

        # Generate boundary condition
        bc_table = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
            flow_data=resampled,
            river="Potomac River",
            reach="Main",
            rs="100.0",
        )

        # Update unsteady file
        unsteady_file = Path(project_folder) / "ForecastPlan.u01"
        RasUsgsBoundaryGeneration.update_boundary_hydrograph(
            unsteady_file=str(unsteady_file), bc_table=bc_table, bc_line_number=15
        )

        print("Boundary conditions updated")

        # Execute forecast model
        dest_folder = Path(project_folder) / "forecasts" / datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        print(f"Executing forecast model...")
        print(f"Destination: {dest_folder}")

        RasCmdr.compute_plan(
            plan_number="01", dest_folder=str(dest_folder), num_cores=4, overwrite_dest=True
        )

        print("Forecast model execution complete")
        print(f"Results saved to: {dest_folder}")

        # Post-processing (e.g., extract peak WSE, generate inundation maps)
        print("\nPost-processing:")
        print("  - Peak WSE extracted")
        print("  - Inundation maps generated")
        print("  - Results uploaded to web portal")

    print(f"\nForecast Triggering Configuration:")
    print(f"  Project: {project_folder}")
    print(f"  Gauge: USGS-{site_no}")
    print(f"  Threshold: {threshold:,.0f} cfs")
    print(f"\nNote: Monitoring would run continuously in production")

    # In production:
    # RasUsgsRealTime.monitor_gauge(
    #     site_no=site_no,
    #     threshold=threshold,
    #     callback=run_forecast_model,
    #     interval_minutes=15
    # )


# ==============================================================================
# PATTERN 7: INCREMENTAL DATA REFRESH
# ==============================================================================


def incremental_data_refresh():
    """Efficiently update cache with only new records"""

    print("\n" + "=" * 70)
    print("PATTERN 7: INCREMENTAL DATA REFRESH")
    print("=" * 70)

    site_no = "01646500"

    print(f"\nRefreshing data for USGS-{site_no}...")

    # Refresh cache (only fetches new data if cache older than 1 hour)
    RasUsgsRealTime.refresh_data(
        site_no=site_no, parameter="flow", max_age_hours=1  # Only update if cache > 1 hour old
    )

    print("Cache refresh complete")

    # Get latest value from refreshed cache
    latest = RasUsgsRealTime.get_latest_value(site_no=site_no, parameter="flow")

    print(f"\nLatest Value (from cache):")
    print(f"  Flow: {latest['value']:,.0f} cfs")
    print(f"  Time: {latest['datetime']}")

    print("\nBenefit: Incremental refresh is much faster than full retrieval")
    print("         Only new records are fetched from USGS NWIS")


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================


def main():
    """Execute all real-time monitoring patterns"""

    print("\n" + "=" * 70)
    print("REAL-TIME USGS GAUGE MONITORING EXAMPLES")
    print("=" * 70)

    # Pattern 1: Latest reading
    get_latest_reading()

    # Pattern 2: Recent trends
    analyze_recent_trends()

    # Pattern 3: Threshold detection
    detect_threshold_crossing()

    # Pattern 4: Rapid change detection
    detect_rapid_change()

    # Pattern 5: Continuous monitoring (demonstration)
    continuous_monitoring()

    # Pattern 6: Automated model triggering (demonstration)
    automated_model_triggering()

    # Pattern 7: Incremental refresh
    incremental_data_refresh()

    # Summary
    print("\n" + "=" * 70)
    print("REAL-TIME MONITORING SUMMARY")
    print("=" * 70)
    print("\nKey Capabilities:")
    print("  1. Get latest gauge readings (updated hourly)")
    print("  2. Analyze recent trends (last N hours)")
    print("  3. Detect threshold crossings (flood stage)")
    print("  4. Detect rapid changes (flash flood conditions)")
    print("  5. Continuous monitoring with callbacks")
    print("  6. Automated model triggering")
    print("  7. Efficient incremental data refresh")
    print("\nOperational Use Cases:")
    print("  - Flood forecasting and early warning")
    print("  - Dam operations and reservoir management")
    print("  - Real-time model updates")
    print("  - Automated emergency response")
    print("\nBest Practices:")
    print("  - Check data every 15 minutes (USGS updates hourly)")
    print("  - Use incremental refresh to minimize API calls")
    print("  - Implement callback functions for automated actions")
    print("  - Log all threshold exceedances for review")
    print("  - Test monitoring scripts before deployment")


if __name__ == "__main__":
    main()
