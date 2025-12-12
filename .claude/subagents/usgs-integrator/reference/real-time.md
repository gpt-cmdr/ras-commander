# Real-Time USGS Monitoring

The `RasUsgsRealTime` module (introduced in v0.87.0) provides real-time access to USGS gauge data for operational forecasting and early warning systems.

## Overview

**Key capabilities**:
- Get latest gauge readings (updated hourly by USGS)
- Retrieve recent trends (last N hours)
- Incremental cache updates (efficient data sync)
- Continuous monitoring with callbacks
- Threshold detection (flood stages)
- Rapid change detection (flash floods)

**Use cases**:
- Automated model triggering based on observed conditions
- Operational forecasting workflows
- Early warning systems for flood response
- Real-time boundary condition updates
- Emergency management dashboards

## Core Functions

### Get Latest Value

Retrieve the most recent gauge reading:

```python
from ras_commander.usgs import RasUsgsRealTime

# Get latest flow reading
latest_flow = RasUsgsRealTime.get_latest_value(
    site_no="01646500",  # Potomac River at Little Falls
    parameter="flow"
)

print(f"Latest flow: {latest_flow['value']} cfs")
print(f"Timestamp:   {latest_flow['timestamp']}")
print(f"Age:         {latest_flow['age_minutes']:.0f} minutes")
```

**Returns**:
```python
{
    'value': 5420.0,           # Current reading
    'timestamp': datetime(...), # UTC timestamp
    'age_minutes': 15.3,       # Minutes since observation
    'site_no': '01646500',
    'parameter': 'flow'
}
```

### Get Recent Data

Retrieve last N hours for trend analysis:

```python
# Get last 6 hours of data
recent_data = RasUsgsRealTime.get_recent_data(
    site_no="01646500",
    parameter="flow",
    hours=6
)

print(f"Retrieved {len(recent_data)} observations")
print(f"Period: {recent_data['datetime'].min()} to {recent_data['datetime'].max()}")

# Calculate trend
delta_flow = recent_data['value'].iloc[-1] - recent_data['value'].iloc[0]
print(f"6-hour change: {delta_flow:+.0f} cfs")
```

### Refresh Data

Incrementally update cache with only new records (efficient):

```python
# Refresh cached data (only downloads new records)
updated_data = RasUsgsRealTime.refresh_data(
    site_no="01646500",
    parameter="flow",
    max_age_hours=24  # Keep last 24 hours
)

print(f"Total records: {len(updated_data)}")
print(f"New records added: {updated_data['new_count']}")
```

**Efficiency**: Only downloads records newer than cache, significantly faster than re-downloading entire dataset.

## Threshold Detection

### Detect Threshold Crossing

Check if current reading exceeds a threshold:

```python
# Check if flow exceeds flood stage
is_flooding = RasUsgsRealTime.detect_threshold_crossing(
    site_no="01646500",
    threshold=50000,  # cfs
    parameter="flow",
    direction="above"  # or "below", "either"
)

if is_flooding:
    print("ALERT: Flow exceeds flood threshold")
    print(f"  Current: {is_flooding['current_value']} cfs")
    print(f"  Threshold: {is_flooding['threshold']} cfs")
    print(f"  Exceedance: {is_flooding['exceedance']} cfs")
    print(f"  Duration: {is_flooding['duration_hours']:.1f} hours")
```

**Returns** (if threshold exceeded):
```python
{
    'exceeded': True,
    'current_value': 52300.0,
    'threshold': 50000.0,
    'exceedance': 2300.0,
    'duration_hours': 2.5,
    'crossing_time': datetime(...),
    'parameter': 'flow'
}
```

### Detect Rapid Change

Identify flash flood conditions (rapid rise/recession):

```python
# Detect rapid rise (flash flood warning)
rapid_change = RasUsgsRealTime.detect_rapid_change(
    site_no="01646500",
    parameter="flow",
    rate_threshold=1000,  # cfs per hour
    window_hours=3
)

if rapid_change['rapid_rise']:
    print("FLASH FLOOD WARNING: Rapid flow increase detected")
    print(f"  Rate: {rapid_change['rate_per_hour']:+.0f} cfs/hr")
    print(f"  3-hour change: {rapid_change['total_change']:+.0f} cfs")
```

**Returns**:
```python
{
    'rapid_rise': True,
    'rapid_recession': False,
    'rate_per_hour': 1250.0,
    'total_change': 3750.0,
    'window_hours': 3,
    'parameter': 'flow'
}
```

## Continuous Monitoring

### Monitor with Callback

Setup continuous monitoring with periodic refresh and alert callbacks:

```python
def flood_alert(site_no, value, threshold, **kwargs):
    """Custom alert function called when threshold exceeded."""
    print(f"\n{'='*60}")
    print(f"FLOOD ALERT: USGS-{site_no}")
    print(f"  Current Flow: {value:,.0f} cfs")
    print(f"  Threshold:    {threshold:,.0f} cfs")
    print(f"  Exceedance:   {value - threshold:+,.0f} cfs")
    print(f"  Time:         {kwargs.get('timestamp', 'Unknown')}")
    print(f"{'='*60}\n")

    # Trigger automated response
    trigger_emergency_model(site_no, value)

def trigger_emergency_model(site_no, flow):
    """Example: Auto-trigger HEC-RAS model for emergency forecasting."""
    from ras_commander import RasCmdr

    print(f"Triggering emergency forecast model...")
    print(f"Using observed flow: {flow:,.0f} cfs")

    # Update boundary condition with observed flow
    # Run emergency forecast
    # Generate inundation maps
    # Alert emergency managers

# Start monitoring
RasUsgsRealTime.monitor_gauge(
    site_no="01646500",
    threshold=50000,
    callback=flood_alert,
    interval_minutes=15,  # Check every 15 minutes
    parameter="flow",
    run_forever=True  # Continuous monitoring
)
```

### Monitoring with Multiple Thresholds

Monitor for different alert levels:

```python
# Define alert levels
ALERT_LEVELS = {
    'watch': 30000,      # Flood watch
    'warning': 40000,    # Flood warning
    'major': 50000,      # Major flooding
    'record': 60000      # Record stage
}

def multi_level_alert(site_no, value, **kwargs):
    """Alert with severity levels."""
    for level, threshold in sorted(ALERT_LEVELS.items(), reverse=True):
        if value >= threshold:
            severity = level.upper()
            print(f"[{severity}] USGS-{site_no}: {value:,.0f} cfs (exceeds {level} threshold)")

            # Send alerts based on severity
            if level == 'record':
                send_emergency_alert(site_no, value)
            elif level == 'major':
                send_warning_alert(site_no, value)
            elif level == 'warning':
                send_watch_alert(site_no, value)
            break

# Monitor with lowest threshold, callback handles levels
RasUsgsRealTime.monitor_gauge(
    site_no="01646500",
    threshold=ALERT_LEVELS['watch'],
    callback=multi_level_alert,
    interval_minutes=15
)
```

## Caching System

The real-time module uses automatic cache management:

```python
from ras_commander.usgs.real_time import RealTimeCache

# Configure cache settings
cache = RealTimeCache(
    cache_dir="/path/to/cache",
    max_age_hours=24,  # Keep last 24 hours
    refresh_threshold_minutes=30  # Refresh if older than 30 min
)

# Get data (auto-refreshes if needed)
data = cache.get_data(
    site_no="01646500",
    parameter="flow"
)

# Manual refresh
cache.refresh(site_no="01646500", parameter="flow")

# Clear old data
cache.cleanup(max_age_hours=48)
```

## Example Workflows

### Workflow 1: Automated Model Triggering

Trigger HEC-RAS model when observed flow exceeds threshold:

```python
from ras_commander import RasCmdr, RasUnsteady
from ras_commander.usgs import RasUsgsRealTime, RasUsgsBoundaryGeneration

def auto_trigger_forecast(site_no, flow, **kwargs):
    """Automatically run forecast when flow exceeds threshold."""

    # Get recent 48 hours for initial/boundary conditions
    recent_data = RasUsgsRealTime.get_recent_data(
        site_no=site_no,
        parameter="flow",
        hours=48
    )

    # Generate boundary condition from observed data
    bc_table = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
        flow_data=recent_data,
        river="Potomac River",
        reach="Main",
        rs="1000.0"
    )

    # Update unsteady file
    unsteady_file = "/path/to/project/Plan.u01"
    RasUsgsBoundaryGeneration.update_boundary_hydrograph(
        unsteady_file=unsteady_file,
        bc_table=bc_table,
        bc_line_number=15
    )

    # Run forecast
    print("Running emergency forecast...")
    RasCmdr.compute_plan(
        plan_number="01",
        dest_folder="/path/to/forecast_output"
    )

    print("Forecast complete. Generating maps...")

# Start monitoring
RasUsgsRealTime.monitor_gauge(
    site_no="01646500",
    threshold=40000,
    callback=auto_trigger_forecast,
    interval_minutes=15
)
```

### Workflow 2: Early Warning Dashboard

Real-time dashboard with multiple gauges and rapid rise detection:

```python
import pandas as pd
from datetime import datetime

# Define gauge network
GAUGE_NETWORK = {
    '01646500': {'name': 'Potomac at Little Falls', 'threshold': 50000},
    '01638500': {'name': 'Potomac at Point of Rocks', 'threshold': 60000},
    '01636500': {'name': 'Shenandoah at Millville', 'threshold': 30000}
}

def update_dashboard():
    """Update real-time dashboard with latest data."""
    dashboard_data = []

    for site_no, info in GAUGE_NETWORK.items():
        try:
            # Get latest value
            latest = RasUsgsRealTime.get_latest_value(site_no, parameter="flow")

            # Check threshold
            status = "ALERT" if latest['value'] > info['threshold'] else "Normal"

            # Check rapid change
            rapid = RasUsgsRealTime.detect_rapid_change(
                site_no=site_no,
                parameter="flow",
                rate_threshold=500,
                window_hours=3
            )

            dashboard_data.append({
                'Site': site_no,
                'Name': info['name'],
                'Flow (cfs)': f"{latest['value']:,.0f}",
                'Status': status,
                'Rapid Rise': "YES" if rapid['rapid_rise'] else "No",
                'Age (min)': f"{latest['age_minutes']:.0f}",
                'Updated': latest['timestamp'].strftime('%Y-%m-%d %H:%M')
            })

        except Exception as e:
            print(f"Error updating {site_no}: {e}")

    # Display dashboard
    df = pd.DataFrame(dashboard_data)
    print("\n" + "="*80)
    print(f"REAL-TIME FLOOD MONITORING DASHBOARD - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    print(df.to_string(index=False))
    print("="*80 + "\n")

# Update every 15 minutes
import time
while True:
    update_dashboard()
    time.sleep(15 * 60)  # 15 minutes
```

### Workflow 3: Flash Flood Detection

Specialized monitoring for flash flood warning based on rapid rise rates:

```python
def flash_flood_monitor(site_no, **kwargs):
    """Monitor for flash flood conditions."""

    # Check rapid change over multiple windows
    windows = [1, 3, 6]  # hours
    alerts = []

    for hours in windows:
        rapid = RasUsgsRealTime.detect_rapid_change(
            site_no=site_no,
            parameter="flow",
            rate_threshold=500,  # cfs per hour
            window_hours=hours
        )

        if rapid['rapid_rise']:
            alerts.append(f"{hours}-hour rise: {rapid['rate_per_hour']:+.0f} cfs/hr")

    if alerts:
        print(f"\n*** FLASH FLOOD WARNING: USGS-{site_no} ***")
        for alert in alerts:
            print(f"  {alert}")

        # Trigger emergency response
        send_flash_flood_warning(site_no)

# Monitor high-risk gauges
for site_no in ['01646500', '01638500']:
    RasUsgsRealTime.monitor_gauge(
        site_no=site_no,
        threshold=10000,  # Low threshold for rapid rise detection
        callback=flash_flood_monitor,
        interval_minutes=5  # Frequent checks for flash floods
    )
```

## Best Practices

### Cache Management
- Set `max_age_hours` based on forecast horizon
- Use `refresh_data()` for incremental updates
- Clear old cache files periodically with `cleanup()`

### Alert Thresholds
- Use USGS flood stage definitions when available
- Test thresholds with historical events
- Implement multiple alert levels (watch, warning, major)

### Callback Functions
- Keep callbacks fast (avoid blocking operations)
- Use separate threads for model execution
- Log all alert events for auditing

### Error Handling
- Implement retry logic for network failures
- Handle missing data gracefully
- Monitor USGS service status

### Data Freshness
- USGS updates instantaneous data hourly
- Check `age_minutes` to verify data freshness
- Alert if data becomes stale (> 2 hours old)

## Related Documentation

- **Complete workflow**: `reference/end-to-end.md`
- **Validation metrics**: `reference/validation.md`
- **Primary module docs**: `ras_commander/usgs/CLAUDE.md`
- **Example notebooks**:
  - `examples/30_usgs_real_time_monitoring.ipynb`
  - `examples/31_bc_generation_from_live_gauge.ipynb`
