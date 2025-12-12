# RASMapper ArrivalTime Namespace Documentation

**Decompiled from:** RasMapperLib.dll
**Purpose:** Flood arrival time and inundation duration calculations for temporal flood analysis
**Date:** 2025-12-09

---

## Table of Contents

1. [Namespace Overview](#namespace-overview)
2. [Class Hierarchy](#class-hierarchy)
3. [Core Data Structures](#core-data-structures)
4. [Arrival Time Algorithms](#arrival-time-algorithms)
5. [Duration Calculation Workflow](#duration-calculation-workflow)
6. [Python Implementation Guide](#python-implementation-guide)
7. [Automation Opportunities](#automation-opportunities)

---

## Namespace Overview

The `RasMapperLib.ArrivalTime` namespace implements algorithms for calculating:

1. **Flood Arrival Time** - When water first reaches a threshold depth at each location
2. **Inundation Duration** - How long water stays above threshold at each location
3. **Recession Time** - When water recedes below threshold

### Key Concepts

- **Local Extrema** - Local minima/maxima in water surface time series
- **Windows** - Time intervals between extrema with defined slope direction (increasing/decreasing)
- **Multi-Location Combining** - Aggregating arrival times across multiple cells (e.g., for mesh face vertices)
- **Slope Analysis** - Tracking whether water is rising, falling, or indeterminate

### Computational Workflow

```
Time Series Data (per cell)
    ↓
Extract Local Extrema (minima/maxima)
    ↓
Convert to Windows (intervals between extrema)
    ↓
Combine Multi-Location Windows (aggregate across vertices)
    ↓
Fill Indeterminate Regions
    ↓
Arrival Time / Duration Results
```

---

## Class Hierarchy

### Inheritance Structure

```
(no inheritance - mostly standalone classes)

Enums:
├── ExtremaType (Minima, Maxima)
└── Slope (Increasing, Decreasing, Indeterminate)

Structs:
├── LocalExtrema (ExtremaType + Time)
├── LocalExtremaValue (LocalExtrema + Value)
└── Window (StartTime, StopTime, MinValue, MaxValue, Slope)

Collections:
├── TimeSeriesExtrema : List<LocalExtremaValue>
├── WindowSeries : List<Window>
├── MultiLocationTimeSeriesExtrema : List<TimeSeriesExtrema>
└── MultiLocationWindowSeries : List<WindowSeries>

Utilities:
├── ArrivalTimeExtensions (extension methods)
└── TwoD_ExtremaGroup (HDF data grouping)
```

### Type Relationships

```
LocalExtrema → LocalExtremaValue → TimeSeriesExtrema → WindowSeries
                                         ↓
                            MultiLocationTimeSeriesExtrema → Combined WindowSeries
                                                                    ↓
                                                        FillWithIndeterminateRegions
                                                                    ↓
                                                            Complete Timeline
```

---

## Core Data Structures

### 1. ExtremaType (Enum)

**File:** `ExtremaType.cs`

```csharp
public enum ExtremaType
{
    Minima,   // Local minimum
    Maxima    // Local maximum
}
```

**Purpose:** Classify local extrema in time series as peaks or troughs.

**Python Equivalent:**
```python
from enum import Enum

class ExtremaType(Enum):
    MINIMA = 0
    MAXIMA = 1
```

---

### 2. Slope (Enum)

**File:** `Slope.cs`

```csharp
public enum Slope
{
    Increasing,      // Water rising
    Decreasing,      // Water falling
    Indeterminate    // Unclear direction (multiple locations disagree)
}
```

**Purpose:** Track water surface trend direction within time windows.

**Python Equivalent:**
```python
class Slope(Enum):
    INCREASING = 0
    DECREASING = 1
    INDETERMINATE = 2
```

---

### 3. LocalExtrema (Struct)

**File:** `LocalExtrema.cs`

```csharp
public struct LocalExtrema
{
    public ExtremaType Extrema;  // Type (min/max)
    public int Time;             // Timestep index

    public LocalExtrema(ExtremaType extrema, int time)

    public override string ToString()
    // Output: "Minima at time 42"
}
```

**Purpose:** Represent a single local extremum (peak or trough) at a specific timestep.

**Python Equivalent:**
```python
@dataclass
class LocalExtrema:
    extrema: ExtremaType
    time: int

    def __str__(self):
        return f"{self.extrema.name} at time {self.time}"
```

---

### 4. LocalExtremaValue (Struct)

**File:** `LocalExtremaValue.cs`

```csharp
public struct LocalExtremaValue
{
    public LocalExtrema LocalExtrema;  // When/what type
    public float Value;                // Water surface elevation

    public LocalExtremaValue(LocalExtrema localExtrema, float value)
}
```

**Purpose:** Pair a local extremum with its actual water surface value.

**Python Equivalent:**
```python
@dataclass
class LocalExtremaValue:
    local_extrema: LocalExtrema
    value: float  # WSE in feet
```

---

### 5. Window (Struct)

**File:** `Window.cs`

```csharp
public struct Window
{
    public int StartTime;     // Start timestep
    public int StopTime;      // End timestep
    public float MinValue;    // Minimum WS in window
    public float MaxValue;    // Maximum WS in window
    public Slope Slope;       // Rising/falling direction

    public Window(int startTime, int stopTime, float min, float max, Slope slope)

    public string DirectionString()  // "Increasing", "Decreasing", "Indeterminate"

    public override string ToString()
    // Output: "0->10 Increasing [5.2, 8.7]"
}
```

**Purpose:** Represent a time interval between extrema with bounded water surface range.

**Key Properties:**
- Time windows are half-open: `[StartTime, StopTime)`
- MinValue/MaxValue bound the water surface within the window
- Slope indicates overall trend

**Python Equivalent:**
```python
@dataclass
class Window:
    start_time: int
    stop_time: int
    min_value: float
    max_value: float
    slope: Slope

    def __str__(self):
        direction = self.slope.name.capitalize()
        return f"{self.start_time}->{self.stop_time} {direction} [{self.min_value}, {self.max_value}]"
```

---

### 6. TimeSeriesExtrema (Class)

**File:** `TimeSeriesExtrema.cs`

```csharp
public class TimeSeriesExtrema : List<LocalExtremaValue>
{
    public TimeSeriesExtrema(int ct)

    // Add multiple extrema with values
    public void AddRange(List<LocalExtrema> extrema, List<float> values)

    // Convert extrema sequence to time windows
    public WindowSeries ToWindowSeries()

    // Combine with another location's extrema
    public WindowSeries Combine(TimeSeriesExtrema other)
}
```

**Key Method: `ToWindowSeries()`**

Converts a sequence of extrema into time windows:

```csharp
WindowSeries windowSeries = new WindowSeries();
for (int i = 0; i <= Count - 2; i++)
{
    LocalExtremaValue current = this[i];
    LocalExtremaValue next = this[i + 1];

    if (next.Value >= current.Value)
    {
        // Rising water
        windowSeries.Add(new Window(
            current.LocalExtrema.Time,
            next.LocalExtrema.Time,
            current.Value,      // min
            next.Value,         // max
            Slope.Increasing
        ));
    }
    else
    {
        // Falling water
        windowSeries.Add(new Window(
            current.LocalExtrema.Time,
            next.LocalExtrema.Time,
            next.Value,         // min (swapped!)
            current.Value,      // max
            Slope.Decreasing
        ));
    }
}
```

**Algorithm Logic:**
1. Walk through consecutive extrema pairs
2. Determine slope from value comparison
3. Create window with min/max bounds
4. Time span is from first extremum to second

**Python Equivalent:**
```python
class TimeSeriesExtrema(list):
    """List of LocalExtremaValue objects."""

    def add_range(self, extrema: List[LocalExtrema], values: List[float]):
        if len(extrema) != len(values):
            raise ValueError("Extrema and values must have same length")
        for e, v in zip(extrema, values):
            self.append(LocalExtremaValue(e, v))

    def to_window_series(self) -> 'WindowSeries':
        windows = WindowSeries()
        for i in range(len(self) - 1):
            current = self[i]
            next_val = self[i + 1]

            if next_val.value >= current.value:
                slope = Slope.INCREASING
                min_val, max_val = current.value, next_val.value
            else:
                slope = Slope.DECREASING
                min_val, max_val = next_val.value, current.value

            windows.add(Window(
                current.local_extrema.time,
                next_val.local_extrema.time,
                min_val, max_val, slope
            ))
        return windows
```

---

### 7. WindowSeries (Class)

**File:** `WindowSeries.cs`

```csharp
public class WindowSeries
{
    public List<Window> Windows;

    public int Count { get; }
    public Window this[int idx] { get; }  // Indexer

    public WindowSeries()
    public WindowSeries(List<Window> windows)

    public void Add(Window window)
    public Window Last()
    public void Sort()  // Order by StartTime

    // Fill gaps with indeterminate regions
    public void FillWithIndeterminateRegions(
        int lastTime,
        Func<int, int, float> GetAbsMinWS,
        Func<int, int, float> GetAbsMaxWS
    )
}
```

**Key Method: `FillWithIndeterminateRegions()`**

Fills temporal gaps between windows with indeterminate slope regions:

```csharp
public void FillWithIndeterminateRegions(int lastTime,
    Func<int, int, float> GetAbsMinWS,
    Func<int, int, float> GetAbsMaxWS)
{
    Sort();

    // Special case: no windows = entire time is indeterminate
    if (Count == 0)
    {
        Add(new Window(0, lastTime,
            GetAbsMinWS(0, lastTime),
            GetAbsMaxWS(0, lastTime),
            Slope.Indeterminate));
        return;
    }

    // Fill gaps between consecutive windows
    for (int i = 0; i < Count - 1; i++)
    {
        int gapStart = this[i].StopTime;
        int gapEnd = this[i + 1].StartTime;

        if (gapStart != gapEnd)
        {
            float min = GetAbsMinWS(gapStart, gapEnd);
            float max = GetAbsMaxWS(gapStart, gapEnd);
            Add(new Window(gapStart, gapEnd, min, max, Slope.Indeterminate));
        }
    }

    // Fill gap after last window
    if (this[Count - 1].StopTime != lastTime)
    {
        int gapStart = this[Count - 1].StopTime;
        float min = GetAbsMinWS(gapStart, lastTime);
        float max = GetAbsMaxWS(gapStart, lastTime);
        Add(new Window(gapStart, lastTime, min, max, Slope.Indeterminate));
    }

    // Fill gap before first window
    if (this[0].StartTime != 0)
    {
        int gapEnd = this[0].StartTime;
        float min = GetAbsMinWS(0, gapEnd);
        float max = GetAbsMaxWS(0, gapEnd);
        Add(new Window(0, gapEnd, min, max, Slope.Indeterminate));
    }

    Sort();
}
```

**Algorithm:**
1. Sort windows by start time
2. Identify temporal gaps (no window coverage)
3. For each gap, query min/max water surface
4. Insert indeterminate window to fill gap
5. Re-sort to maintain chronological order

**Python Equivalent:**
```python
class WindowSeries(list):
    """List of Window objects."""

    def add(self, window: Window):
        self.append(window)

    def last(self) -> Window:
        return self[-1]

    def sort_windows(self):
        self.sort(key=lambda w: w.start_time)

    def fill_with_indeterminate_regions(self, last_time: int,
                                       get_abs_min_ws, get_abs_max_ws):
        self.sort_windows()

        if len(self) == 0:
            self.add(Window(0, last_time,
                           get_abs_min_ws(0, last_time),
                           get_abs_max_ws(0, last_time),
                           Slope.INDETERMINATE))
            return

        # Fill internal gaps
        for i in range(len(self) - 1):
            gap_start = self[i].stop_time
            gap_end = self[i + 1].start_time
            if gap_start != gap_end:
                min_ws = get_abs_min_ws(gap_start, gap_end)
                max_ws = get_abs_max_ws(gap_start, gap_end)
                self.add(Window(gap_start, gap_end, min_ws, max_ws,
                               Slope.INDETERMINATE))

        # Fill trailing gap
        if self[-1].stop_time != last_time:
            gap_start = self[-1].stop_time
            min_ws = get_abs_min_ws(gap_start, last_time)
            max_ws = get_abs_max_ws(gap_start, last_time)
            self.add(Window(gap_start, last_time, min_ws, max_ws,
                           Slope.INDETERMINATE))

        # Fill leading gap
        if self[0].start_time != 0:
            gap_end = self[0].start_time
            min_ws = get_abs_min_ws(0, gap_end)
            max_ws = get_abs_max_ws(0, gap_end)
            self.add(Window(0, gap_end, min_ws, max_ws,
                           Slope.INDETERMINATE))

        self.sort_windows()
```

---

### 8. MultiLocationTimeSeriesExtrema (Class)

**File:** `MultiLocationTimeSeriesExtrema.cs`

```csharp
public class MultiLocationTimeSeriesExtrema : List<TimeSeriesExtrema>
{
    // Combine extrema from multiple locations into unified window series
    public WindowSeries Combine()

    private void Validate()  // Empty - for future validation
}
```

**Key Method: `Combine()`**

This is the **core algorithm** for multi-location arrival time analysis. It aggregates extrema from multiple locations (e.g., mesh cell vertices) to determine when water is definitively rising, falling, or indeterminate.

#### Algorithm Breakdown

**Step 1: Initialize Per-Timestep Tracking Arrays**

```csharp
int lastTime = this[0].Last().LocalExtrema.Time;
float[] minWSPerTimestep = new float[lastTime + 1];
float[] maxWSPerTimestep = new float[lastTime + 1];
Slope[] slopePerTimestep = new Slope[lastTime + 1];

// Initialize to extremes
for (int i = 0; i <= lastTime; i++)
{
    minWSPerTimestep[i] = float.MaxValue;
    maxWSPerTimestep[i] = float.MinValue;
}
```

**Step 2: Process Each Location's Extrema**

For each location, iterate through consecutive extrema pairs and update timestep arrays:

```csharp
for (int loc = 0; loc < this.Count; loc++)
{
    for (int k = 0; k < this[loc].Count - 1; k++)
    {
        LocalExtremaValue current = this[loc][k];
        LocalExtremaValue next = this[loc][k + 1];

        int startTime = current.LocalExtrema.Time;
        int endTime = next.LocalExtrema.Time - 1;

        // Update min/max bounds for each timestep in window
        for (int t = startTime; t <= endTime; t++)
        {
            minWSPerTimestep[t] = Math.Min(minWSPerTimestep[t], current.Value);
            maxWSPerTimestep[t] = Math.Max(maxWSPerTimestep[t], current.Value);
            minWSPerTimestep[t] = Math.Min(minWSPerTimestep[t], next.Value);
            maxWSPerTimestep[t] = Math.Max(maxWSPerTimestep[t], next.Value);

            // Update slope consensus
            if (current.LocalExtrema.Extrema == ExtremaType.Minima)
            {
                // Rising water at this location
                if (loc == 0 || slopePerTimestep[t] == Slope.Increasing)
                    slopePerTimestep[t] = Slope.Increasing;
                else
                    slopePerTimestep[t] = Slope.Indeterminate;
            }
            else  // Maxima
            {
                // Falling water at this location
                if (loc == 0 || slopePerTimestep[t] == Slope.Decreasing)
                    slopePerTimestep[t] = Slope.Decreasing;
                else
                    slopePerTimestep[t] = Slope.Indeterminate;
            }
        }
    }
}
```

**Step 3: Identify Slope Streaks**

Group consecutive timesteps with same slope into "streaks":

```csharp
List<Streak> increasingStreaks = MutuallyExclusiveStreaks(
    slopePerTimestep,
    sl => sl == Slope.Increasing
);

List<Streak> decreasingStreaks = MutuallyExclusiveStreaks(
    slopePerTimestep,
    sl => sl == Slope.Decreasing
);

List<Streak> indeterminateStreaks = MutuallyExclusiveStreaks(
    slopePerTimestep,
    sl => sl == Slope.Indeterminate
);
```

**Step 4: Convert Streaks to Windows**

For each streak, create a window with min/max bounds:

```csharp
WindowSeries result = new WindowSeries();

foreach (Streak streak in increasingStreaks)
{
    int start = streak.StartIndex;
    int stop = streak.StopIndex + 1;

    float min = GetMinInRange(minWSPerTimestep, start, stop);
    float max = GetMaxInRange(maxWSPerTimestep, start, stop);

    result.Add(new Window(start, stop, min, max, Slope.Increasing));
}

// Repeat for decreasing and indeterminate streaks...

result.Sort();
```

**Key Insight:**
- If all locations agree on slope direction → use that slope
- If locations disagree → mark as `Indeterminate`
- Min/max bounds envelope all location values

**Python Equivalent:**
```python
class MultiLocationTimeSeriesExtrema(list):
    """List of TimeSeriesExtrema objects."""

    def combine(self) -> WindowSeries:
        if len(self) == 0:
            return None
        if len(self) == 1:
            return self[0].to_window_series()

        # Get time extent
        last_time = self[0][-1].local_extrema.time

        # Initialize per-timestep tracking
        min_ws_per_timestep = np.full(last_time + 1, np.inf, dtype=float)
        max_ws_per_timestep = np.full(last_time + 1, -np.inf, dtype=float)
        slope_per_timestep = np.full(last_time + 1, None)

        # Process each location's extrema
        for loc_idx, loc_extrema in enumerate(self):
            for i in range(len(loc_extrema) - 1):
                current = loc_extrema[i]
                next_val = loc_extrema[i + 1]

                start_t = current.local_extrema.time
                end_t = next_val.local_extrema.time - 1

                for t in range(start_t, end_t + 1):
                    # Update bounds
                    min_ws_per_timestep[t] = min(min_ws_per_timestep[t],
                                                 current.value, next_val.value)
                    max_ws_per_timestep[t] = max(max_ws_per_timestep[t],
                                                 current.value, next_val.value)

                    # Update slope consensus
                    if current.local_extrema.extrema == ExtremaType.MINIMA:
                        new_slope = Slope.INCREASING
                    else:
                        new_slope = Slope.DECREASING

                    if slope_per_timestep[t] is None:
                        slope_per_timestep[t] = new_slope
                    elif slope_per_timestep[t] != new_slope:
                        slope_per_timestep[t] = Slope.INDETERMINATE

        # Group into streaks
        def find_streaks(arr, target_slope):
            streaks = []
            start = None
            for i, slope in enumerate(arr):
                if slope == target_slope:
                    if start is None:
                        start = i
                elif start is not None:
                    streaks.append((start, i - 1))
                    start = None
            if start is not None:
                streaks.append((start, len(arr) - 1))
            return streaks

        # Create windows from streaks
        windows = WindowSeries()

        for slope_type in [Slope.INCREASING, Slope.DECREASING, Slope.INDETERMINATE]:
            for start, stop in find_streaks(slope_per_timestep, slope_type):
                min_val = min_ws_per_timestep[start:stop+1].min()
                max_val = max_ws_per_timestep[start:stop+1].max()
                windows.add(Window(start, stop + 1, min_val, max_val, slope_type))

        windows.sort_windows()
        return windows
```

---

### 9. MultiLocationWindowSeries (Class)

**File:** `MultiLocationWindowSeries.cs`

```csharp
public class MultiLocationWindowSeries
{
    public List<WindowSeries> Locations;

    public int Count { get; }
    public WindowSeries this[int idx] { get; }

    public MultiLocationWindowSeries()
    public MultiLocationWindowSeries(List<WindowSeries> locations)

    public void Add(WindowSeries location)
}
```

**Purpose:** Container for window series from multiple locations (simpler aggregation than `MultiLocationTimeSeriesExtrema`).

**Python Equivalent:**
```python
class MultiLocationWindowSeries(list):
    """List of WindowSeries objects."""

    def add(self, location: WindowSeries):
        self.append(location)
```

---

### 10. TwoD_ExtremaGroup (Class)

**File:** `TwoD_ExtremaGroup.cs`

```csharp
public class TwoD_ExtremaGroup
{
    public int TwoD_Area;      // 2D area index
    public int StartCell;      // First cell in group
    public int NumCells;       // Number of cells
    public int EndCell;        // Last cell in group

    public int[,] Info;        // Cell metadata [cell, column]
    public int[] Extrema;      // Extrema types
    public float[,] WSValues;  // Water surface values [cell, time]

    public TwoD_ExtremaGroup(int[,] info, int[] extrema, float[,] wsValues,
                            int twoD_area, int startCell)

    public bool Contains(int twoD_area, int cellIndex)

    public ExtremaType ExtremaStartType(int cellIndex)
    // Returns: (ExtremaType)Info[cellIndex, 2]
}
```

**Purpose:** Group extrema data for contiguous cells in a 2D mesh area (performance optimization for HDF reading).

**Key Properties:**
- `Info[cellIndex, 2]` stores extrema type for cell's first extremum
- Groups cells by 2D area for efficient HDF access
- Used when reading arrival time data from HDF files

**Python Equivalent:**
```python
class TwoD_ExtremaGroup:
    def __init__(self, info: np.ndarray, extrema: np.ndarray, ws_values: np.ndarray,
                 twod_area: int, start_cell: int):
        self.twod_area = twod_area
        self.start_cell = start_cell
        self.num_cells = info.shape[0]
        self.end_cell = start_cell + self.num_cells - 1
        self.info = info          # shape: (num_cells, n_cols)
        self.extrema = extrema
        self.ws_values = ws_values  # shape: (num_cells, num_times)

    def contains(self, twod_area: int, cell_index: int) -> bool:
        return (twod_area == self.twod_area and
                self.start_cell <= cell_index <= self.end_cell)

    def extrema_start_type(self, cell_index: int) -> ExtremaType:
        return ExtremaType(self.info[cell_index, 2])
```

---

### 11. ArrivalTimeExtensions (Extension Methods)

**File:** `ArrivalTimeExtensions.cs`

```csharp
internal sealed class ArrivalTimeExtensions
{
    public static ExtremaType SwapType(this ExtremaType eType)
    {
        if (eType == ExtremaType.Maxima)
            return ExtremaType.Minima;
        return ExtremaType.Maxima;
    }
}
```

**Purpose:** Helper method to toggle between minima and maxima.

**Python Equivalent:**
```python
def swap_extrema_type(extrema_type: ExtremaType) -> ExtremaType:
    if extrema_type == ExtremaType.MAXIMA:
        return ExtremaType.MINIMA
    return ExtremaType.MAXIMA
```

---

## Arrival Time Algorithms

### Conceptual Framework

Flood arrival time analysis answers:
1. **When does water arrive?** First time depth > threshold
2. **How long does it stay?** Duration above threshold
3. **When does it recede?** Last time depth > threshold

### Algorithm Pipeline

```
Raw Time Series → Extract Extrema → Build Windows → Combine Locations → Compute Arrival
```

#### Stage 1: Extrema Detection

**Not present in decompiled code** - RASMapper must extract extrema elsewhere (likely in HDF reading logic or `RASMapperRaster` class).

Expected algorithm (not in this namespace):
```python
def detect_extrema(time_series: np.ndarray) -> List[LocalExtrema]:
    extrema = []
    for i in range(1, len(time_series) - 1):
        if time_series[i] > time_series[i-1] and time_series[i] > time_series[i+1]:
            extrema.append(LocalExtrema(ExtremaType.MAXIMA, i))
        elif time_series[i] < time_series[i-1] and time_series[i] < time_series[i+1]:
            extrema.append(LocalExtrema(ExtremaType.MINIMA, i))
    return extrema
```

#### Stage 2: Window Construction

**Method:** `TimeSeriesExtrema.ToWindowSeries()`

Converts extrema sequence to time intervals with slope direction:

```
Extrema: [Min@t0, Max@t5, Min@t10, Max@t15]
         ↓
Windows: [t0→t5 Increasing, t5→t10 Decreasing, t10→t15 Increasing]
```

#### Stage 3: Multi-Location Combination

**Method:** `MultiLocationTimeSeriesExtrema.Combine()`

Aggregates windows from multiple locations (e.g., cell face vertices):

```
Location A: [Increasing, Decreasing, Increasing]
Location B: [Increasing, Indeterminate, Increasing]
            ↓
Combined:   [Increasing, Indeterminate, Increasing]
```

**Slope Consensus Rules:**
- All locations agree → use agreed slope
- Locations disagree → mark `Indeterminate`

#### Stage 4: Gap Filling

**Method:** `WindowSeries.FillWithIndeterminateRegions()`

Ensures complete timeline coverage:

```
Windows: [t0→t5, t10→t15]  (gap at t5→t10)
         ↓
Filled:  [t0→t5, t5→t10 (Indeterminate), t10→t15]
```

#### Stage 5: Arrival Time Extraction

**Not explicitly in decompiled code** - likely in `RASMapperRaster` or result export logic.

Expected algorithm:
```python
def compute_arrival_time(windows: WindowSeries, threshold_depth: float,
                        terrain_elev: float) -> Optional[int]:
    """Find first time water exceeds threshold depth."""
    threshold_wse = terrain_elev + threshold_depth

    for window in windows:
        if window.max_value >= threshold_wse:
            return window.start_time  # Arrival at start of exceeding window

    return None  # Never exceeds threshold
```

#### Stage 6: Duration Calculation

```python
def compute_inundation_duration(windows: WindowSeries, threshold_depth: float,
                               terrain_elev: float) -> int:
    """Total time above threshold."""
    threshold_wse = terrain_elev + threshold_depth
    duration = 0

    for window in windows:
        if window.min_value >= threshold_wse:
            # Entire window above threshold
            duration += (window.stop_time - window.start_time)
        elif window.max_value >= threshold_wse:
            # Partially above (indeterminate - conservative estimate)
            # Could interpolate, but RASMapper likely counts entire window
            duration += (window.stop_time - window.start_time)

    return duration
```

---

## Duration Calculation Workflow

### Use Case: Rasterized Inundation Duration

**Goal:** For each grid cell, calculate total hours above threshold depth.

**Input:**
- Mesh cell time series (water surface elevations)
- Terrain elevation raster
- Threshold depth (e.g., 0.5 ft)

**Workflow:**

```python
def compute_duration_raster(mesh_time_series: Dict[int, np.ndarray],
                           cell_polygons: gpd.GeoDataFrame,
                           terrain_raster: np.ndarray,
                           threshold_depth: float,
                           raster_transform) -> np.ndarray:
    """
    Compute inundation duration raster.

    Args:
        mesh_time_series: {cell_id: wse_array[timesteps]}
        cell_polygons: Mesh cell geometries
        terrain_raster: Terrain elevations
        threshold_depth: Depth threshold (ft)
        raster_transform: Rasterio affine transform

    Returns:
        duration_raster: Hours above threshold per pixel
    """

    # 1. Extract extrema for each cell
    cell_extrema = {}
    for cell_id, wse_series in mesh_time_series.items():
        extrema = detect_local_extrema(wse_series)
        values = [wse_series[e.time] for e in extrema]

        ts_extrema = TimeSeriesExtrema()
        ts_extrema.add_range(extrema, values)
        cell_extrema[cell_id] = ts_extrema

    # 2. For each raster pixel
    duration_raster = np.zeros_like(terrain_raster)

    for row in range(terrain_raster.shape[0]):
        for col in range(terrain_raster.shape[1]):
            pixel_x, pixel_y = rasterio.transform.xy(raster_transform, row, col)
            pixel_point = Point(pixel_x, pixel_y)

            # Find containing cell
            cell_id = find_containing_cell(pixel_point, cell_polygons)
            if cell_id is None:
                continue

            # Get terrain elevation
            terrain_elev = terrain_raster[row, col]
            if np.isnan(terrain_elev):
                continue

            # Convert extrema to windows
            windows = cell_extrema[cell_id].to_window_series()

            # Compute duration above threshold
            threshold_wse = terrain_elev + threshold_depth
            duration_hours = 0

            for window in windows:
                if window.max_value >= threshold_wse:
                    duration_hours += (window.stop_time - window.start_time)

            duration_raster[row, col] = duration_hours

    return duration_raster
```

### Multi-Location Variant (for Face Interpolation)

When using sloped interpolation (Ben's Weights), water surface at pixel is interpolated from face vertices. Need to combine extrema from multiple vertices:

```python
def compute_duration_raster_sloped(mesh_time_series: Dict[int, np.ndarray],
                                  cell_polygons: gpd.GeoDataFrame,
                                  cell_faces: gpd.GeoDataFrame,
                                  terrain_raster: np.ndarray,
                                  threshold_depth: float,
                                  raster_transform) -> np.ndarray:

    duration_raster = np.zeros_like(terrain_raster)

    for row in range(terrain_raster.shape[0]):
        for col in range(terrain_raster.shape[1]):
            pixel_x, pixel_y = rasterio.transform.xy(raster_transform, row, col)
            pixel_point = Point(pixel_x, pixel_y)

            cell_id = find_containing_cell(pixel_point, cell_polygons)
            if cell_id is None:
                continue

            # Get vertices for this cell
            vertex_ids = get_cell_vertex_ids(cell_id, cell_faces)

            # Combine extrema from all vertices
            multi_extrema = MultiLocationTimeSeriesExtrema()
            for vertex_id in vertex_ids:
                vertex_series = mesh_time_series[vertex_id]
                extrema = detect_local_extrema(vertex_series)
                values = [vertex_series[e.time] for e in extrema]

                ts_extrema = TimeSeriesExtrema()
                ts_extrema.add_range(extrema, values)
                multi_extrema.append(ts_extrema)

            # Combine into unified window series
            combined_windows = multi_extrema.combine()

            # Fill gaps
            last_time = len(mesh_time_series[vertex_ids[0]]) - 1
            combined_windows.fill_with_indeterminate_regions(
                last_time,
                lambda t1, t2: min_ws_in_range(mesh_time_series, vertex_ids, t1, t2),
                lambda t1, t2: max_ws_in_range(mesh_time_series, vertex_ids, t1, t2)
            )

            # Compute duration
            terrain_elev = terrain_raster[row, col]
            threshold_wse = terrain_elev + threshold_depth
            duration_hours = 0

            for window in combined_windows:
                if window.max_value >= threshold_wse:
                    duration_hours += (window.stop_time - window.start_time)

            duration_raster[row, col] = duration_hours

    return duration_raster
```

---

## Python Implementation Guide

### Recommended Package Structure

```python
# ras_commander/mapping/arrival_time.py

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Callable
import numpy as np

class ExtremaType(Enum):
    MINIMA = 0
    MAXIMA = 1

class Slope(Enum):
    INCREASING = 0
    DECREASING = 1
    INDETERMINATE = 2

@dataclass
class LocalExtrema:
    extrema: ExtremaType
    time: int

@dataclass
class LocalExtremaValue:
    local_extrema: LocalExtrema
    value: float

@dataclass
class Window:
    start_time: int
    stop_time: int
    min_value: float
    max_value: float
    slope: Slope

class TimeSeriesExtrema(list):
    def to_window_series(self) -> 'WindowSeries': ...

class WindowSeries(list):
    def fill_with_indeterminate_regions(self, ...): ...

class MultiLocationTimeSeriesExtrema(list):
    def combine(self) -> WindowSeries: ...
```

### Integration with Existing APIs

Add to `RasMap` class:

```python
# ras_commander/RasMap.py

class RasMap:

    @staticmethod
    def map_arrival_time(
        plan_number: str,
        threshold_depth: float = 0.5,
        terrain_path: str = None,
        output_dir: str = None,
        interpolation_method: str = "horizontal",
        ras_object=None
    ) -> Path:
        """
        Generate flood arrival time raster.

        Args:
            plan_number: Plan ID (e.g., "01")
            threshold_depth: Depth threshold in feet
            terrain_path: Path to terrain raster
            output_dir: Output directory for results
            interpolation_method: "horizontal" or "sloped"
            ras_object: RasPrj instance (uses global ras if None)

        Returns:
            Path to arrival time raster (hours since start)
        """
        # Implementation using algorithms above
        ...

    @staticmethod
    def map_inundation_duration(
        plan_number: str,
        threshold_depth: float = 0.5,
        terrain_path: str = None,
        output_dir: str = None,
        interpolation_method: str = "horizontal",
        ras_object=None
    ) -> Path:
        """
        Generate inundation duration raster.

        Args:
            plan_number: Plan ID
            threshold_depth: Depth threshold in feet
            terrain_path: Path to terrain raster
            output_dir: Output directory for results
            interpolation_method: "horizontal" or "sloped"
            ras_object: RasPrj instance

        Returns:
            Path to duration raster (total hours above threshold)
        """
        # Implementation using algorithms above
        ...
```

### HDF Data Reading

Need to extract time series extrema from HDF files. Based on `TwoD_ExtremaGroup`, RASMapper likely stores pre-computed extrema:

```python
# ras_commander/hdf/HdfResultsMesh.py

class HdfResultsMesh:

    @staticmethod
    def get_mesh_extrema(hdf_path: str, mesh_name: str = None) -> Dict[int, TimeSeriesExtrema]:
        """
        Extract pre-computed extrema for mesh cells.

        Returns:
            {cell_id: TimeSeriesExtrema}
        """
        # Search HDF for extrema datasets (path unknown from decompilation)
        # Likely under: Results/Unsteady/Output/Output Blocks/Base Output/
        #               Unsteady Time Series/2D Flow Areas/{mesh}/
        #               Extrema/ (?)
        ...
```

**Note:** Exact HDF paths for extrema data are not revealed in decompiled `ArrivalTime` namespace. Need to explore HDF structure or decompile HDF reading classes.

### Helper Functions

```python
def detect_local_extrema(time_series: np.ndarray) -> List[LocalExtrema]:
    """Detect local minima/maxima in time series."""
    extrema = []
    for i in range(1, len(time_series) - 1):
        if time_series[i] > time_series[i-1] and time_series[i] > time_series[i+1]:
            extrema.append(LocalExtrema(ExtremaType.MAXIMA, i))
        elif time_series[i] < time_series[i-1] and time_series[i] < time_series[i+1]:
            extrema.append(LocalExtrema(ExtremaType.MINIMA, i))
    return extrema

def min_ws_in_range(time_series_dict: Dict[int, np.ndarray],
                    ids: List[int], start: int, stop: int) -> float:
    """Get minimum water surface across multiple locations in time range."""
    min_val = np.inf
    for id in ids:
        min_val = min(min_val, time_series_dict[id][start:stop+1].min())
    return min_val

def max_ws_in_range(time_series_dict: Dict[int, np.ndarray],
                    ids: List[int], start: int, stop: int) -> float:
    """Get maximum water surface across multiple locations in time range."""
    max_val = -np.inf
    for id in ids:
        max_val = max(max_val, time_series_dict[id][start:stop+1].max())
    return max_val
```

---

## Automation Opportunities

### 1. Batch Arrival Time Analysis

**Use Case:** Generate arrival time maps for all plans in a project.

```python
from ras_commander import init_ras_project, RasMap

init_ras_project(r"C:/Projects/MyFlood", "6.6")

for plan_id in ras.plan_df['plan_num']:
    RasMap.map_arrival_time(
        plan_number=plan_id,
        threshold_depth=0.5,
        terrain_path="Terrain/DTM.tif",
        output_dir=f"Results/ArrivalTime"
    )
```

### 2. Multi-Threshold Duration Analysis

**Use Case:** Compare inundation durations for various depth thresholds.

```python
thresholds = [0.5, 1.0, 2.0, 5.0]  # feet

for threshold in thresholds:
    RasMap.map_inundation_duration(
        plan_number="01",
        threshold_depth=threshold,
        terrain_path="Terrain/DTM.tif",
        output_dir=f"Results/Duration_{threshold}ft"
    )
```

### 3. Direct RASMapper Automation (Call .NET Methods)

Use `pythonnet` to call RASMapper directly for arrival time calculations:

```python
import clr
clr.AddReference(r"C:\Program Files\HEC\HEC-RAS\6.6\RasMapperLib.dll")

from RasMapperLib.ArrivalTime import MultiLocationTimeSeriesExtrema, TimeSeriesExtrema

# Build extrema from Python-extracted HDF data
multi_extrema = MultiLocationTimeSeriesExtrema()
for vertex_id in vertex_ids:
    extrema_list = detect_local_extrema(hdf_data[vertex_id])
    ts_extrema = TimeSeriesExtrema(len(extrema_list))
    # ... populate ...
    multi_extrema.Add(ts_extrema)

# Call RASMapper's combine method
combined_windows = multi_extrema.Combine()

# Extract results
for window in combined_windows.Windows:
    print(f"{window.StartTime} -> {window.StopTime}: {window.Slope}")
```

**Pros:**
- Uses battle-tested RASMapper algorithms
- No need to re-implement complex logic

**Cons:**
- Requires .NET runtime and RASMapper installation
- Less portable than pure Python

### 4. Result Comparison Validation

**Use Case:** Validate Python implementation against RASMapper exports.

```python
# Export from RASMapper
rasmapper_arrival = rasterio.open("RASMapper_ArrivalTime.tif").read(1)

# Generate with Python
python_arrival = RasMap.map_arrival_time("01", threshold_depth=0.5)
python_arrival_data = rasterio.open(python_arrival).read(1)

# Compare
diff = python_arrival_data - rasmapper_arrival
print(f"Max difference: {np.nanmax(np.abs(diff))} hours")
print(f"Mean difference: {np.nanmean(np.abs(diff))} hours")
```

### 5. Custom Arrival Time Animations

**Use Case:** Create animated arrival time progression.

```python
import matplotlib.pyplot as plt
import matplotlib.animation as animation

def create_arrival_animation(windows: WindowSeries, terrain: np.ndarray,
                            output_path: str = "arrival.mp4"):
    """
    Animate flood arrival progression.

    Each frame shows areas inundated by that timestep.
    """
    fig, ax = plt.subplots()

    def update_frame(timestep):
        ax.clear()

        # Show terrain
        ax.imshow(terrain, cmap='terrain', alpha=0.5)

        # Overlay inundated areas up to this timestep
        inundation_mask = np.zeros_like(terrain)
        for window in windows:
            if window.start_time <= timestep:
                # Mark cells as inundated
                inundation_mask[...] = 1  # (simplified)

        ax.imshow(inundation_mask, cmap='Blues', alpha=0.7)
        ax.set_title(f"Arrival Time: Hour {timestep}")

    last_time = windows[-1].stop_time
    anim = animation.FuncAnimation(fig, update_frame, frames=last_time,
                                  interval=200)
    anim.save(output_path, writer='ffmpeg')
```

### 6. Recession Time Analysis

**Use Case:** Find when water recedes below threshold (inverse of arrival).

```python
def compute_recession_time(windows: WindowSeries, threshold_depth: float,
                          terrain_elev: float) -> Optional[int]:
    """Find last time water exceeds threshold depth."""
    threshold_wse = terrain_elev + threshold_depth
    recession_time = None

    for window in windows:
        if window.max_value >= threshold_wse:
            recession_time = window.stop_time

    return recession_time

# Add to RasMap class
RasMap.map_recession_time(plan_number="01", threshold_depth=0.5, ...)
```

### 7. Evacuation Warning Time Calculation

**Use Case:** Compute time between breach and arrival at critical locations.

```python
def compute_warning_time(breach_time: int, arrival_raster: np.ndarray,
                        critical_locations: List[Tuple[int, int]]) -> Dict:
    """
    Calculate evacuation warning times.

    Args:
        breach_time: Timestep of dam breach
        arrival_raster: Arrival time raster (hours)
        critical_locations: List of (row, col) pixel coordinates

    Returns:
        {location: warning_hours}
    """
    warnings = {}
    for loc in critical_locations:
        arrival_time = arrival_raster[loc]
        if not np.isnan(arrival_time):
            warning_hours = arrival_time - breach_time
            warnings[loc] = max(0, warning_hours)
    return warnings
```

### 8. Spatial Arrival Time Gradient

**Use Case:** Identify areas with rapid flood progression.

```python
def compute_arrival_gradient(arrival_raster: np.ndarray,
                             cell_size: float) -> np.ndarray:
    """
    Compute spatial gradient of arrival times (hours/mile).

    High gradients = rapid flood progression zones.
    """
    grad_y, grad_x = np.gradient(arrival_raster, cell_size)
    gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)

    # Convert to hours/mile
    feet_per_mile = 5280
    gradient_hrs_per_mile = gradient_magnitude * (feet_per_mile / cell_size)

    return gradient_hrs_per_mile
```

---

## Summary

### Key Takeaways

1. **Window-Based Approach:** RASMapper uses time windows (bounded intervals) rather than raw time series for arrival analysis.

2. **Multi-Location Aggregation:** The `MultiLocationTimeSeriesExtrema.Combine()` method is the core algorithm for combining extrema from multiple locations (vertices) into consensus slope directions.

3. **Slope Consensus Rules:**
   - All locations agree → use agreed slope
   - Locations disagree → mark `Indeterminate`

4. **Gap Filling:** `WindowSeries.FillWithIndeterminateRegions()` ensures complete timeline coverage by inserting indeterminate windows in temporal gaps.

5. **Extensibility:** The namespace is designed for flexible arrival/duration/recession analysis without hardcoding specific algorithms (those are likely in `RASMapperRaster` or export logic).

### Implementation Roadmap

**Phase 1: Core Data Structures** (Low Hanging Fruit)
- Implement enums, structs, and collection classes
- Unit test window construction and sorting

**Phase 2: Extrema Detection** (Need HDF Investigation)
- Explore HDF structure for pre-computed extrema
- Implement fallback: detect extrema from raw time series

**Phase 3: Multi-Location Combination** (Core Algorithm)
- Implement `MultiLocationTimeSeriesExtrema.Combine()`
- Validate against manual test cases

**Phase 4: Rasterization** (Integration)
- Add `RasMap.map_arrival_time()` and `map_inundation_duration()`
- Integrate with existing horizontal/sloped interpolation

**Phase 5: Validation** (Critical)
- Export arrival time rasters from RASMapper
- Compare Python-generated vs ground truth
- Target: <0.1 hour difference (6 minutes)

**Phase 6: Advanced Features** (Nice to Have)
- Recession time analysis
- Arrival time animations
- Evacuation warning calculations

### Unknown/Missing Information

From decompilation, we do NOT know:
1. **HDF extrema storage format** - Where/how RASMapper stores pre-computed extrema
2. **Threshold application logic** - How RASMapper determines "arrival" from windows
3. **Interpolation integration** - How arrival times are interpolated to raster pixels
4. **Time unit conversion** - How timestep indices map to real-world hours/dates

These gaps require either:
- Further decompilation of `RASMapperRaster` or HDF reading classes
- Empirical testing against RASMapper exports
- Direct inspection of HDF file structure

---

**Document Version:** 1.0
**Last Updated:** 2025-12-09
**Decompiled Assembly:** RasMapperLib.dll (HEC-RAS 6.6)
