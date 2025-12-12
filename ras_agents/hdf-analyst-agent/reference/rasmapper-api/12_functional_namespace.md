# RasMapperLib.Functional Namespace Documentation

## Overview

The `RasMapperLib.Functional` namespace provides a comprehensive time series abstraction layer for HEC-RAS data analysis and visualization. It implements a functional programming approach with support for:

- **Discrete time series** (regular and irregular timesteps)
- **Functional time series** (lambda-based continuous functions)
- **HDF5 persistence** via H5Assist library
- **Temporal sampling and interpolation**
- **Type-safe conversions between representations**

This namespace is used throughout RASMapper for handling temporal data from HEC-RAS simulations, including hydrographs, stage time series, and computed results over time.

---

## Class Hierarchy

```
TimeSeries (abstract base)
├── DiscreteTimeSeries (abstract)
│   ├── RegularTimeSeries (fixed timestep)
│   └── IrregularTimeSeries (variable timestep)
└── FunctionalTimeSeries (lambda-based)
    └── ConstantTimeSeries (special case)

TimeSeriesCollection : List<TimeSeries>
```

**Inheritance Pattern:**
- All time series inherit from `TimeSeries` abstract base
- Discrete vs. Functional split for different storage models
- Regular/Irregular for discrete data with different timestep patterns
- Collection class for managing multiple series

---

## Core Abstract Class: TimeSeries

**Purpose:** Base class defining common interface for all time series types

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `Variable` | `string` | Variable name (e.g., "Stage", "Flow") |
| `Units` | `string` | Engineering units (e.g., "ft", "cfs") |
| `StartTime` | `DateTime` | First temporal point (abstract) |
| `EndTime` | `DateTime` | Last temporal point (abstract) |

### Key Methods

#### `Sample(DateTime dt, bool canExtrapolate = false)`
**Signature:** `abstract double Sample(DateTime dt, bool canExtrapolate = false)`

**Purpose:** Temporal interpolation - get value at arbitrary time

**Parameters:**
- `dt`: Target datetime to sample
- `canExtrapolate`: If true, extends first/last values beyond time bounds

**Returns:** Interpolated value at time `dt`, or `double.NaN` if out of bounds and extrapolation disabled

**Behavior by Type:**
- **RegularTimeSeries:** Linear interpolation between adjacent timesteps
- **IrregularTimeSeries:** Linear interpolation using actual datetime spacing
- **FunctionalTimeSeries:** Direct lambda evaluation (always can extrapolate)

---

#### `Save(H5Writer hw, string groupName)`
**Signature:** `virtual void Save(H5Writer hw, string groupName)`

**Purpose:** Persist time series to HDF5 file with metadata

**Implementation:**
1. Delete existing group if present
2. Create new group
3. Write `Variable` and `Units` attributes
4. Call `SaveInternal()` for type-specific data

**HDF5 Structure Created:**
```
/{groupName}/
├── @Variable = "Stage"
├── @Units = "ft"
├── @Type = "Regular Time Series"  (type-specific)
└── ... (type-specific datasets)
```

---

#### `LoadAll(H5Reader h5r, string searchSubFolder)`
**Signature:** `static List<TimeSeries> LoadAll(H5Reader h5r, string searchSubFolder)`

**Purpose:** Load all time series from an HDF5 folder

**Algorithm:**
1. Enumerate all groups in `searchSubFolder`
2. Check `Type` attribute
3. Currently only loads `"Regular Time Series"` type
4. Returns list of loaded series

**Note:** Only `RegularTimeSeries` has fully implemented load logic

---

### HDF5 Attribute Constants

```csharp
public const string sH5TypeAttribute = "Type";
public const string sH5VariableAttribute = "Variable";
public const string sH5UnitsAttribute = "Units";
```

Used for standardized HDF5 metadata storage.

---

## DiscreteTimeSeries (Abstract)

**Purpose:** Base for time series with discrete data points (as opposed to continuous functions)

### Abstract Properties

| Property | Type | Description |
|----------|------|-------------|
| `Count` | `int` | Number of data points |
| `Value` | `double` (get/set) | Value at current index |
| `DateTime` | `DateTime` | Time at current index |
| `Duration` | `TimeSpan` | Total time span covered |

### Abstract Methods

```csharp
public abstract List<double> CopyData();      // Deep copy of values
public abstract List<DateTime> CopyDates();   // Deep copy of timestamps
```

**Note:** The class has an implicit `idx` field (not shown in decompiled source but referenced in getters) that tracks current position for iteration.

---

## RegularTimeSeries

**Purpose:** Fixed-timestep discrete series (most common for HEC-RAS output)

### Private Fields

```csharp
private DateTime _startTime;        // First timestamp
private TimeSpan _timeStep;         // Fixed interval
private List<double> _data;         // Values array
```

### Constructors

```csharp
// Primary constructor
RegularTimeSeries(DateTime start, IList<double> data, TimeSpan timestep, string variableName, string units)

// Convenience overloads
RegularTimeSeries(DateTime start, IList<double> data, TimeSpan timestep)
RegularTimeSeries(DateTime start, IList<double> data, double timestepSeconds)
```

### Key Properties

| Property | Implementation |
|----------|----------------|
| `StartTime` | `_startTime` |
| `EndTime` | `_startTime + Timestep * Count` |
| `Duration` | `Timestep * Count` |
| `Timestep` | `_timeStep` |
| `DateTime` | `_startTime + Timestep * idx` |

### Sample() Implementation

**Algorithm:**
```csharp
if (Count == 0) return double.NaN;
if (dt == StartTime) return _data.First();
if (dt == EndTime) return _data.Last();

if (dt < StartTime) return canExtrapolate ? _data.First() : double.NaN;
if (dt > EndTime) return canExtrapolate ? _data.Last() : double.NaN;

// Linear interpolation
double fractionalIndex = (dt - StartTime).TotalSeconds / Duration.TotalSeconds * Count;
int idx1 = (int)fractionalIndex;
int idx2 = idx1 + 1;
double weight = fractionalIndex - idx1;

return weight * _data[idx2] + (1 - weight) * _data[idx1];
```

**Python Equivalent:**
```python
import numpy as np
from datetime import datetime, timedelta

def sample_regular(start_time, data, timestep_seconds, dt, extrapolate=False):
    if len(data) == 0:
        return np.nan

    duration = len(data) * timestep_seconds
    elapsed = (dt - start_time).total_seconds()

    if elapsed < 0:
        return data[0] if extrapolate else np.nan
    if elapsed > duration:
        return data[-1] if extrapolate else np.nan

    # Linear interpolation
    frac_idx = elapsed / duration * len(data)
    idx1 = int(frac_idx)
    idx2 = min(idx1 + 1, len(data) - 1)
    weight = frac_idx - idx1

    return weight * data[idx2] + (1 - weight) * data[idx1]
```

---

### HDF5 Persistence

#### Save Format

```
/{groupName}/
├── @Type = "Regular Time Series"
├── @Variable = "Flow"
├── @Units = "cfs"
├── @Start Date = "2024-01-15 00:00:00"  (string)
├── @Timestep (seconds) = 3600.0
└── Data = [1.2, 3.4, 5.6, ...]  (1D array)
```

#### Load Implementation

**Method:** `static RegularTimeSeries TryLoad(H5Reader hr, string groupName)`

**Algorithm:**
1. Check group exists
2. Read `Start Date` attribute and parse to DateTime
3. Read `Timestep (seconds)` attribute
4. Read `Data` dataset as double array
5. Read optional `Variable` and `Units` attributes
6. Construct new `RegularTimeSeries` instance

**Error Handling:** Returns `null` on any failure (try-catch wrapper)

---

### Utility Methods

```csharp
public void Add(double v)  // Append value (increments time automatically)

public IrregularTimeSeries ToIrregularTimeSeries()  // Convert to irregular format
```

---

## IrregularTimeSeries

**Purpose:** Variable-timestep discrete series (for non-uniform data)

### Private Fields

```csharp
private List<DateTime> _dateTimes;  // Timestamp for each value
private List<double> _data;         // Corresponding values
```

### Constructors

```csharp
IrregularTimeSeries(IList<double> data, IList<DateTime> dateTimes, string variable, string units)
IrregularTimeSeries(IList<double> data, IList<DateTime> dateTimes)  // Unnamed
```

**Note:** Arrays must be same length and chronologically sorted

### Key Properties

| Property | Implementation |
|----------|----------------|
| `StartTime` | `_dateTimes.FirstOrDefault()` |
| `EndTime` | `_dateTimes.LastOrDefault()` |
| `Duration` | `EndTime - StartTime` |

### Sample() Implementation

**Algorithm:**
```csharp
if (Count == 0) return double.NaN;
if (dt == StartTime) return _data.First();
if (dt == EndTime) return _data.Last();

if (dt < StartTime) return canExtrapolate ? _data.First() : double.NaN;
if (dt > EndTime) return canExtrapolate ? _data.Last() : double.NaN;

// Find bracketing timestamps
for (int i = 0; i < Count; i++)
{
    if (dt < _dateTimes[i])
    {
        DateTime t1 = _dateTimes[i - 1];
        DateTime t2 = _dateTimes[i];
        double weight = (dt - t1).TotalSeconds / (t2 - t1).TotalSeconds;
        return weight * _data[i] + (1 - weight) * _data[i - 1];
    }
}
return double.NaN;
```

**Python Equivalent:**
```python
import numpy as np

def sample_irregular(datetimes, data, dt, extrapolate=False):
    if len(data) == 0:
        return np.nan

    if dt < datetimes[0]:
        return data[0] if extrapolate else np.nan
    if dt > datetimes[-1]:
        return data[-1] if extrapolate else np.nan

    # Binary search or linear scan for bracketing times
    for i in range(1, len(datetimes)):
        if dt < datetimes[i]:
            t1, t2 = datetimes[i-1], datetimes[i]
            v1, v2 = data[i-1], data[i]
            weight = (dt - t1).total_seconds() / (t2 - t1).total_seconds()
            return weight * v2 + (1 - weight) * v1

    return np.nan
```

---

### Utility Methods

```csharp
public void Add(double v, DateTime dt)  // Append value with explicit timestamp
```

**HDF5 Save:** Not implemented (throws `NotImplementedException`)

---

## FunctionalTimeSeries

**Purpose:** Continuous time series defined by a lambda function (mathematical representation)

### Private Fields

```csharp
private Func<DateTime, double> _lambda;  // Function defining value at any time
```

### Constructors

```csharp
FunctionalTimeSeries(Func<DateTime, double> lambda, string varName, string units)
FunctionalTimeSeries(Func<DateTime, double> lambda)  // Unnamed
```

### Key Properties

```csharp
public override DateTime StartTime => DateTime.MinValue;  // Unbounded
public override DateTime EndTime => DateTime.MaxValue;    // Unbounded
```

**Implication:** Functional series are always valid for any timestamp (no boundary checks)

---

### Sample() Implementation

```csharp
public override double Sample(DateTime dt, bool canExtrapolate = false)
{
    return _lambda(dt);  // Direct function evaluation (extrapolate ignored)
}
```

**Note:** `canExtrapolate` parameter has no effect - function is always evaluated

---

### Factory Methods

#### SineWave()
**Signature:** `static FunctionalTimeSeries SineWave(double amplitude = 1.0, double frequency = 1.0, DateTime? offsetDate = null)`

**Purpose:** Create sinusoidal test signal

**Implementation:**
```csharp
DateTime offset = offsetDate ?? DateTime.MinValue;
return new FunctionalTimeSeries(
    dt => amplitude * Math.Sin(frequency * (dt - offset).TotalSeconds)
);
```

**Python Equivalent:**
```python
import numpy as np
from datetime import datetime

def sine_wave(amplitude=1.0, frequency=1.0, offset_date=None):
    offset = offset_date or datetime.min
    return lambda dt: amplitude * np.sin(frequency * (dt - offset).total_seconds())
```

---

### Discretize()

**Signature:** `RegularTimeSeries Discretize(DateTime startDate, TimeSpan dt, int count)`

**Purpose:** Convert functional series to discrete regular series by sampling

**Algorithm:**
```csharp
List<double> samples = new List<double>();
for (int i = 0; i < count; i++)
{
    samples.Add(Sample(startDate.AddSeconds(dt.TotalSeconds * i)));
}
return new RegularTimeSeries(startDate, samples, dt, Variable, Units);
```

**Use Case:** Convert analytical function to data array for HDF5 storage or plotting

---

### HDF5 Persistence

**Save:** Not implemented (throws `NotImplementedException`)

**Reason:** Lambda functions cannot be serialized directly - must discretize first

---

## ConstantTimeSeries

**Purpose:** Special case of functional series with constant value (step function)

### Implementation

```csharp
public class ConstantTimeSeries : FunctionalTimeSeries
{
    public ConstantTimeSeries(double constVal, string variableName, string units)
        : base(dt => constVal, variableName, units)
    {
    }
}
```

**Inheritance:** Leverages `FunctionalTimeSeries` with trivial lambda

**Python Equivalent:**
```python
class ConstantTimeSeries:
    def __init__(self, value):
        self._value = value

    def sample(self, dt, extrapolate=False):
        return self._value
```

---

## TimeSeriesCollection

**Purpose:** Typed collection for managing multiple related time series

### Implementation

```csharp
public class TimeSeriesCollection : List<TimeSeries>
{
    public override string ToString()
    {
        return string.Join(",", this.Select(ts => ts.Variable)).InParentheses();
    }
}
```

**Inheritance:** Extends `List<TimeSeries>` for LINQ compatibility

**Example Output:** `"(Stage,Flow,Velocity)"`

**Python Equivalent:**
```python
class TimeSeriesCollection(list):
    def __repr__(self):
        variables = [ts.variable for ts in self]
        return f"({', '.join(variables)})"
```

---

## Functional Programming Patterns

### 1. Lambda-Based Abstraction

**C# Pattern:**
```csharp
Func<DateTime, double> lambda = dt => Math.Sin((dt - start).TotalSeconds);
FunctionalTimeSeries ts = new FunctionalTimeSeries(lambda);
```

**Python Equivalent:**
```python
from typing import Callable
from datetime import datetime

lambda_func: Callable[[datetime], float] = lambda dt: np.sin((dt - start).total_seconds())
```

### 2. Immutable Data with Copy Methods

**C# Pattern:**
```csharp
public abstract List<double> CopyData();  // Deep copy required
public abstract List<DateTime> CopyDates();
```

**Design:** Forces defensive copying to prevent external mutation

**Python Equivalent:**
```python
def copy_data(self) -> list[float]:
    return self._data.copy()  # Shallow copy sufficient for immutables
```

### 3. Type Conversion Chain

**Pattern:** `Functional → Regular → Irregular`

```csharp
// Start with function
FunctionalTimeSeries func = FunctionalTimeSeries.SineWave();

// Convert to discrete
RegularTimeSeries regular = func.Discretize(start, dt, count);

// Convert to irregular
IrregularTimeSeries irregular = regular.ToIrregularTimeSeries();
```

**Use Case:** Progressive refinement for different analysis needs

---

## Python Implementation Guide

### Recommended Architecture

```python
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import numpy as np
import h5py

class TimeSeries(ABC):
    """Base class for all time series types"""

    def __init__(self, variable: str = "", units: str = ""):
        self.variable = variable
        self.units = units

    @property
    @abstractmethod
    def start_time(self) -> datetime:
        pass

    @property
    @abstractmethod
    def end_time(self) -> datetime:
        pass

    @abstractmethod
    def sample(self, dt: datetime, extrapolate: bool = False) -> float:
        """Interpolate value at arbitrary time"""
        pass

    def save_hdf5(self, h5file: h5py.File, group_name: str):
        """Persist to HDF5 with metadata"""
        if group_name in h5file:
            del h5file[group_name]
        grp = h5file.create_group(group_name)
        grp.attrs['Variable'] = self.variable
        grp.attrs['Units'] = self.units
        self._save_internal(grp)

    @abstractmethod
    def _save_internal(self, grp: h5py.Group):
        pass


class RegularTimeSeries(TimeSeries):
    """Fixed-timestep discrete series"""

    def __init__(self, start: datetime, data: list[float],
                 timestep: timedelta, variable: str = "", units: str = ""):
        super().__init__(variable, units)
        self._start = start
        self._data = np.array(data)
        self._timestep = timestep

    @property
    def start_time(self) -> datetime:
        return self._start

    @property
    def end_time(self) -> datetime:
        return self._start + self._timestep * len(self._data)

    def sample(self, dt: datetime, extrapolate: bool = False) -> float:
        """Linear interpolation between timesteps"""
        if len(self._data) == 0:
            return np.nan

        elapsed = (dt - self._start).total_seconds()
        duration = (len(self._data) * self._timestep.total_seconds())

        if elapsed < 0:
            return self._data[0] if extrapolate else np.nan
        if elapsed > duration:
            return self._data[-1] if extrapolate else np.nan

        frac_idx = elapsed / duration * len(self._data)
        idx1 = int(frac_idx)
        idx2 = min(idx1 + 1, len(self._data) - 1)
        weight = frac_idx - idx1

        return weight * self._data[idx2] + (1 - weight) * self._data[idx1]

    def _save_internal(self, grp: h5py.Group):
        grp.attrs['Type'] = 'Regular Time Series'
        grp.attrs['Start Date'] = self._start.isoformat()
        grp.attrs['Timestep (seconds)'] = self._timestep.total_seconds()
        grp.create_dataset('Data', data=self._data)

    @classmethod
    def load_hdf5(cls, h5file: h5py.File, group_name: str):
        """Load from HDF5 group"""
        grp = h5file[group_name]
        start = datetime.fromisoformat(grp.attrs['Start Date'])
        timestep = timedelta(seconds=grp.attrs['Timestep (seconds)'])
        data = grp['Data'][:]
        variable = grp.attrs.get('Variable', '')
        units = grp.attrs.get('Units', '')
        return cls(start, data, timestep, variable, units)


class FunctionalTimeSeries(TimeSeries):
    """Lambda-based continuous series"""

    def __init__(self, lambda_func: Callable[[datetime], float],
                 variable: str = "", units: str = ""):
        super().__init__(variable, units)
        self._lambda = lambda_func

    @property
    def start_time(self) -> datetime:
        return datetime.min

    @property
    def end_time(self) -> datetime:
        return datetime.max

    def sample(self, dt: datetime, extrapolate: bool = False) -> float:
        return self._lambda(dt)

    def discretize(self, start: datetime, timestep: timedelta, count: int) -> RegularTimeSeries:
        """Convert to regular series by sampling"""
        data = [self.sample(start + timestep * i) for i in range(count)]
        return RegularTimeSeries(start, data, timestep, self.variable, self.units)

    @staticmethod
    def sine_wave(amplitude: float = 1.0, frequency: float = 1.0,
                  offset_date: datetime = None) -> 'FunctionalTimeSeries':
        offset = offset_date or datetime.min
        return FunctionalTimeSeries(
            lambda dt: amplitude * np.sin(frequency * (dt - offset).total_seconds())
        )

    def _save_internal(self, grp: h5py.Group):
        raise NotImplementedError("Cannot serialize lambda functions")
```

### Usage Examples

```python
# Create regular time series from HEC-RAS results
start = datetime(2024, 1, 15, 0, 0, 0)
timestep = timedelta(hours=1)
stage_data = [10.2, 10.5, 10.8, 11.1, 10.9]
stage_ts = RegularTimeSeries(start, stage_data, timestep, "Stage", "ft")

# Sample at arbitrary time
sample_time = datetime(2024, 1, 15, 1, 30, 0)  # 1.5 hours in
stage_value = stage_ts.sample(sample_time)  # Linear interpolation

# Create functional test signal
sine = FunctionalTimeSeries.sine_wave(amplitude=5.0, frequency=0.01)
discrete_sine = sine.discretize(start, timestep, 100)

# Save to HDF5
with h5py.File('timeseries.hdf', 'w') as f:
    stage_ts.save_hdf5(f, 'Stage_Data')
    discrete_sine.save_hdf5(f, 'Test_Signal')
```

---

## Integration with ras-commander

### Current State

ras-commander does **not** currently implement time series abstractions like RASMapper.

### Recommended Integration Points

1. **Boundary Condition Processing**
   - Parse DSS time series into `RegularTimeSeries` objects
   - Standardize temporal sampling across different BC types
   - Enable programmatic BC modification and interpolation

2. **Results Animation**
   - Wrap HDF timestep data in time series abstraction
   - Allow arbitrary time sampling for smooth animations
   - Support irregular HEC-RAS output intervals

3. **Hydrograph Analysis**
   - Extract hydrographs as `RegularTimeSeries` from HDF
   - Implement peak detection, volume calculations
   - Compare observed vs. simulated with temporal alignment

### Proposed API

```python
from ras_commander import HdfResultsMesh, TimeSeries

# Extract mesh results as time series
plan_hdf = "BaldEagle.p01.hdf"
cell_id = 12345

# Get stage time series for specific cell
stage_ts = HdfResultsMesh.get_cell_timeseries(
    plan_hdf, cell_id, variable="WSE"
)  # Returns RegularTimeSeries

# Sample at arbitrary time
sample_time = datetime(2024, 1, 15, 13, 47, 23)
wse_value = stage_ts.sample(sample_time, extrapolate=False)

# Convert to pandas for analysis
import pandas as pd
df = pd.DataFrame({
    'Time': stage_ts.copy_dates(),
    'WSE': stage_ts.copy_data()
})
```

---

## Automation Opportunities

### 1. HDF5 Time Series Extraction

**C# Pattern:**
```csharp
List<TimeSeries> allSeries = TimeSeries.LoadAll(h5r, "/Results/Unsteady/Output/Output Blocks/Base Output");
```

**Python Automation:**
```python
def extract_all_timeseries(hdf_path: str, search_path: str) -> list[RegularTimeSeries]:
    """Load all time series from HDF Results file"""
    with h5py.File(hdf_path, 'r') as f:
        series_list = []
        for grp_name in f[search_path].keys():
            grp = f[f"{search_path}/{grp_name}"]
            if grp.attrs.get('Type') == 'Regular Time Series':
                series_list.append(RegularTimeSeries.load_hdf5(f, f"{search_path}/{grp_name}"))
        return series_list
```

### 2. Temporal Alignment for Comparisons

**Use Case:** Compare simulations with different output intervals

```python
def align_timeseries(ts1: RegularTimeSeries, ts2: RegularTimeSeries,
                     timestep: timedelta) -> tuple[np.ndarray, np.ndarray]:
    """Resample both series to common timestep"""
    start = max(ts1.start_time, ts2.start_time)
    end = min(ts1.end_time, ts2.end_time)

    times = []
    current = start
    while current <= end:
        times.append(current)
        current += timestep

    values1 = [ts1.sample(t) for t in times]
    values2 = [ts2.sample(t) for t in times]

    return np.array(values1), np.array(values2)
```

### 3. Boundary Condition Scripting

**Use Case:** Generate synthetic hydrographs for testing

```python
# Create rising limb + falling limb hydrograph
from scipy.interpolate import interp1d

def synthetic_hydrograph(baseflow: float, peak: float,
                         time_to_peak: timedelta, recession_time: timedelta,
                         start: datetime, timestep: timedelta) -> RegularTimeSeries:
    """Generate triangular hydrograph"""
    total_time = time_to_peak + recession_time
    count = int(total_time / timestep)

    # Piecewise linear function
    time_points = [0, time_to_peak.total_seconds(), total_time.total_seconds()]
    flow_points = [baseflow, peak, baseflow]
    interp = interp1d(time_points, flow_points, kind='linear')

    flows = [interp(i * timestep.total_seconds()) for i in range(count)]
    return RegularTimeSeries(start, flows, timestep, "Flow", "cfs")
```

---

## Performance Considerations

### Memory Efficiency

**C# Implementation:**
- Uses `List<double>` for dynamic sizing
- `ToList()` creates defensive copies to prevent mutation
- No memory pooling or reuse

**Python Optimization:**
```python
# Use numpy arrays instead of lists for large datasets
self._data = np.array(data, dtype=np.float64)  # Contiguous memory

# Avoid unnecessary copies in hot paths
def sample_batch(self, times: list[datetime]) -> np.ndarray:
    """Vectorized sampling for multiple times"""
    elapsed = np.array([(t - self._start).total_seconds() for t in times])
    duration = len(self._data) * self._timestep.total_seconds()
    frac_idx = elapsed / duration * len(self._data)
    # Use numpy's clip and interpolation for speed
    return np.interp(frac_idx, np.arange(len(self._data)), self._data)
```

### Interpolation Performance

**RegularTimeSeries:** O(1) lookup via fractional indexing
**IrregularTimeSeries:** O(n) linear search - use binary search for large datasets

**Python Optimization:**
```python
import bisect

def sample_irregular_fast(self, dt: datetime, extrapolate: bool = False) -> float:
    """O(log n) binary search instead of O(n) scan"""
    idx = bisect.bisect_left(self._datetimes, dt)
    # ... interpolation logic
```

---

## Summary

The `RasMapperLib.Functional` namespace provides a well-architected time series framework with:

**Strengths:**
- Clean abstraction hierarchy separating discrete vs. continuous representations
- Type-safe conversions between formats
- HDF5 persistence for `RegularTimeSeries`
- Temporal interpolation with extrapolation control
- Functional programming patterns (lambdas, immutability)

**Limitations:**
- No HDF5 save for `IrregularTimeSeries` or `FunctionalTimeSeries`
- Linear interpolation only (no spline or advanced methods)
- `IrregularTimeSeries` uses O(n) search instead of binary search
- No built-in peak detection, statistics, or signal processing

**ras-commander Integration:**
- Implement `RegularTimeSeries` as foundation for HDF results extraction
- Add `get_cell_timeseries()` methods to `HdfResultsMesh`
- Support pandas DataFrame conversion for analysis workflows
- Consider vectorized numpy operations for batch sampling

**Key Files:**
- `TimeSeries.cs` - Base abstraction and HDF5 loading
- `RegularTimeSeries.cs` - Fixed-timestep implementation (most important)
- `FunctionalTimeSeries.cs` - Lambda-based continuous functions
- `IrregularTimeSeries.cs` - Variable-timestep discrete data
