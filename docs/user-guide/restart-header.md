# Native restart timing

`RasRestart.read_header(path, simulation_start=...)` reads native HEC-RAS 6.6
restart timing without modifying the file or reading a plan HDF. It supports
the observed little-endian `21May2021` header. Other versions/layouts fail
explicitly; this is not a general reader for all HEC-RAS restart formats.

```python
from datetime import datetime
from ras_commander import RasRestart

header = RasRestart.read_header(
    "model.p01.some-name.rst",
    simulation_start=datetime(2000, 1, 1),
)
print(header["simulation_time"])
```

Pass the producing plan's simulation start in its naive simulation calendar.
The reader obtains elapsed simulation hours from the binary header, binds
them to that start, and checks the header's initial calendar date and current
clock. The binary header does not independently identify the initial clock
hour. Midnight initial dates use HEC's previous-day/24:00 convention. Both
elapsed counters must agree, and clock consistency has a 1 ms tolerance.
Filenames are never used to determine time.

The result contains `format`, `engine_header`, `initial_date`, `clock_hour`,
`elapsed_hours`, `elapsed_check_hours`, `simulation_start`, `simulation_time`
and `time_tolerance_seconds`. Times are ISO strings; hour fields are floating
point hours. The API reads 321 header bytes and does not hash or move the file.
Callers retaining several candidates should hash every candidate and require
exactly one state time matching the plan end within the stated tolerance.
An unknown/malformed candidate should be reported, rather than guessed from
its name. More than one matching file is ambiguous even if their bytes match.

Layout attribution: this reader is based on retained native 6.6 output,
checked against producing-plan start/end records at midnight, non-midnight
starts, calendar rollovers and fractional run lengths. The initial date is at
byte 293, current clock-hour double at 285, and elapsed-hour doubles at 305
and 313. Synthetic tests establish validation behavior; native qualification
must additionally verify a real chain's state/header/plan bindings. A successful
header read does not establish hydraulic acceptance.
