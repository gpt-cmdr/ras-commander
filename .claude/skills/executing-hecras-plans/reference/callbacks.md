# Real-Time Monitoring with Callbacks

Complete reference for monitoring HEC-RAS execution progress in real-time using callback objects.

## Overview

The `stream_callback` parameter in `RasCmdr.compute_plan()` and `compute_parallel()` enables real-time monitoring of HEC-RAS execution by processing messages from the `.bco` file as they are written.

**Benefits**:
- See execution progress in real-time (no waiting for completion)
- Detect issues immediately
- Log detailed execution traces
- Create custom monitoring dashboards
- Send alerts on completion/failure

**Available Since**: v0.88.0+

## Callback Protocol

Callbacks must implement the `ExecutionCallback` protocol. All methods are **optional** - implement only what you need.

```python
from typing import Protocol

class ExecutionCallback(Protocol):
    """Protocol for HEC-RAS execution monitoring callbacks."""

    def on_prep_start(self, plan_number: str) -> None:
        """Called before geometry preprocessing begins."""
        ...

    def on_prep_complete(self, plan_number: str) -> None:
        """Called after geometry preprocessing completes."""
        ...

    def on_exec_start(self, plan_number: str, command: str) -> None:
        """Called when HEC-RAS subprocess starts."""
        ...

    def on_exec_message(self, plan_number: str, message: str) -> None:
        """Called for each new .bco file message (real-time streaming)."""
        ...

    def on_exec_complete(self, plan_number: str, success: bool, duration: float) -> None:
        """Called when execution finishes (success or failure)."""
        ...

    def on_verify_result(self, plan_number: str, verified: bool) -> None:
        """Called after HDF verification (if verify=True)."""
        ...
```

## Built-In Callbacks

ras-commander provides three ready-to-use callback implementations in `ras_commander.callbacks`:

### ConsoleCallback

Simple console output for interactive sessions and debugging.

**Features**:
- Prints to stdout with atomic writes (thread-safe)
- Verbose mode for all messages or summary only
- Minimal overhead

**Usage**:
```python
from ras_commander.callbacks import ConsoleCallback

# Simple mode - start/complete only
callback = ConsoleCallback()
RasCmdr.compute_plan("01", stream_callback=callback)

# Verbose mode - all messages
callback = ConsoleCallback(verbose=True)
RasCmdr.compute_plan("01", stream_callback=callback)
```

**Output Example** (verbose=False):
```
[Plan 01] Starting execution...
[Plan 01] SUCCESS in 45.2s
```

**Output Example** (verbose=True):
```
[Plan 01] Starting execution...
[Plan 01] Command: C:\...\HEC-RAS.exe project.prj 01
[Plan 01] Geometry Preprocessor Version 6.6
[Plan 01] Processing 2D Flow Areas...
[Plan 01] Computing Plan: 01
[Plan 01] Timestep 1 of 240
[Plan 01] Timestep 100 of 240
[Plan 01] SUCCESS in 45.2s
```

**Thread Safety**: Yes (uses `print()` with `file=sys.stdout, flush=True`)

---

### FileLoggerCallback

Writes execution progress to per-plan log files.

**Features**:
- Creates separate log file for each plan
- Full execution trace with timestamps
- Thread-safe file operations (uses Lock)
- Auto-cleanup on completion

**Usage**:
```python
from ras_commander.callbacks import FileLoggerCallback
from pathlib import Path

# Create callback with output directory
callback = FileLoggerCallback(output_dir=Path("logs"))

RasCmdr.compute_plan("01", stream_callback=callback)
# Creates: logs/plan_01_execution.log

# For parallel execution
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    stream_callback=callback
)
# Creates: logs/plan_01_execution.log
#          logs/plan_02_execution.log
#          logs/plan_03_execution.log
```

**Log File Format**:
```
=== Plan 01 Execution Log ===
Command: C:\...\HEC-RAS.exe project.prj 01
================================================================================

Geometry Preprocessor Version 6.6
Processing 2D Flow Areas...
Computing Plan: 01
Timestep 1 of 240
Timestep 100 of 240
...

================================================================================
Execution SUCCESS in 45.1 seconds
```

**Thread Safety**: Yes (uses `threading.Lock`)

---

### ProgressBarCallback

Displays tqdm progress bars with real-time message updates.

**Features**:
- Visual progress bar with message counter
- Shows last message received
- Thread-safe tqdm operations
- Multiple concurrent progress bars for parallel execution

**Requirements**:
```bash
pip install tqdm
```

**Usage**:
```python
from ras_commander.callbacks import ProgressBarCallback

callback = ProgressBarCallback()
RasCmdr.compute_plan("01", stream_callback=callback)
```

**Output Example**:
```
Plan 01: 100%|████████████████| 1234/1234 [00:45<00:00, 27.42msg/s]
```

**Parallel Execution**:
```python
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    stream_callback=ProgressBarCallback()
)
```

**Output Example** (parallel):
```
Plan 01: 100%|████████████████| 1234/1234 [00:45<00:00, 27.42msg/s]
Plan 02:  67%|██████████▋     |  890/1334 [00:32<00:16, 27.81msg/s]
Plan 03:  34%|█████▍          |  456/1350 [00:18<00:35, 25.33msg/s]
```

**Thread Safety**: Yes (uses `threading.Lock`)

---

## Custom Callbacks

Create custom callbacks by implementing the `ExecutionCallback` protocol methods.

### Example: Email Alert Callback

```python
from ras_commander.callbacks import ExecutionCallback
import smtplib
from email.mime.text import MIMEText

class EmailAlertCallback(ExecutionCallback):
    """Send email alerts on plan completion."""

    def __init__(self, smtp_server: str, recipient: str):
        self.smtp_server = smtp_server
        self.recipient = recipient

    def on_exec_complete(self, plan_number: str, success: bool, duration: float):
        """Send email when execution completes."""
        status = "SUCCESS" if success else "FAILED"
        subject = f"HEC-RAS Plan {plan_number} {status}"
        body = f"Plan {plan_number} execution completed in {duration:.1f} seconds.\nStatus: {status}"

        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = 'ras-commander@example.com'
        msg['To'] = self.recipient

        with smtplib.SMTP(self.smtp_server) as server:
            server.send_message(msg)

# Use it
callback = EmailAlertCallback(
    smtp_server='smtp.example.com',
    recipient='engineer@example.com'
)

RasCmdr.compute_plan("01", stream_callback=callback)
```

### Example: Database Logging Callback

```python
from ras_commander.callbacks import ExecutionCallback
from datetime import datetime
import sqlite3

class DatabaseCallback(ExecutionCallback):
    """Log execution progress to SQLite database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create database table if doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY,
                plan_number TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                success BOOLEAN,
                duration REAL,
                command TEXT
            )
        """)
        conn.commit()
        conn.close()

    def on_exec_start(self, plan_number: str, command: str):
        """Record execution start."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO executions (plan_number, start_time, command) VALUES (?, ?, ?)",
            (plan_number, datetime.now(), command)
        )
        conn.commit()
        conn.close()

    def on_exec_complete(self, plan_number: str, success: bool, duration: float):
        """Update execution completion."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """UPDATE executions
               SET end_time = ?, success = ?, duration = ?
               WHERE plan_number = ? AND end_time IS NULL""",
            (datetime.now(), success, duration, plan_number)
        )
        conn.commit()
        conn.close()

# Use it
callback = DatabaseCallback("executions.db")
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    stream_callback=callback
)
```

### Example: Multi-Channel Callback

Combine multiple callbacks (console + file + email):

```python
from ras_commander.callbacks import ExecutionCallback, ConsoleCallback, FileLoggerCallback

class MultiCallback(ExecutionCallback):
    """Dispatch to multiple callbacks."""

    def __init__(self, *callbacks):
        self.callbacks = callbacks

    def on_exec_start(self, plan_number: str, command: str):
        for cb in self.callbacks:
            if hasattr(cb, 'on_exec_start'):
                cb.on_exec_start(plan_number, command)

    def on_exec_message(self, plan_number: str, message: str):
        for cb in self.callbacks:
            if hasattr(cb, 'on_exec_message'):
                cb.on_exec_message(plan_number, message)

    def on_exec_complete(self, plan_number: str, success: bool, duration: float):
        for cb in self.callbacks:
            if hasattr(cb, 'on_exec_complete'):
                cb.on_exec_complete(plan_number, success, duration)

# Use it
callback = MultiCallback(
    ConsoleCallback(),
    FileLoggerCallback("logs"),
    EmailAlertCallback("smtp.example.com", "engineer@example.com")
)

RasCmdr.compute_plan("01", stream_callback=callback)
```

---

## Thread Safety

### Thread Safety Requirements

Callbacks used with `compute_parallel()` **MUST** be thread-safe because multiple plans execute concurrently.

**Built-in callbacks** are all thread-safe:
- `ConsoleCallback` - Uses atomic `print()` calls
- `FileLoggerCallback` - Uses `threading.Lock`
- `ProgressBarCallback` - Uses `threading.Lock`

**Custom callbacks** should use locks for shared state:

```python
from threading import Lock
from ras_commander.callbacks import ExecutionCallback

class ThreadSafeCallback(ExecutionCallback):
    def __init__(self):
        self.lock = Lock()
        self.results = {}

    def on_exec_complete(self, plan_number: str, success: bool, duration: float):
        with self.lock:  # Protect shared state
            self.results[plan_number] = {
                'success': success,
                'duration': duration
            }
```

### SynchronizedCallback Wrapper

For callbacks that are NOT thread-safe, use the `SynchronizedCallback` wrapper:

```python
from ras_commander.callbacks import SynchronizedCallback

class UnsafeCallback:
    """Not thread-safe - uses shared state without locks."""
    def __init__(self):
        self.messages = []

    def on_exec_message(self, plan_number: str, message: str):
        self.messages.append(message)  # Not thread-safe!

# Make it safe
unsafe_callback = UnsafeCallback()
safe_callback = SynchronizedCallback(unsafe_callback)

# Now safe for parallel execution
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    stream_callback=safe_callback
)
```

---

## Callback Method Details

### on_prep_start(plan_number)

**Called**: Before geometry preprocessing begins

**Parameters**:
- `plan_number` (str): Plan being processed

**Use Cases**:
- Log preprocessing start
- Display status message
- Start timer

**Example**:
```python
def on_prep_start(self, plan_number: str):
    print(f"[{plan_number}] Starting geometry preprocessing...")
```

---

### on_prep_complete(plan_number)

**Called**: After geometry preprocessing completes

**Parameters**:
- `plan_number` (str): Plan that was processed

**Use Cases**:
- Log preprocessing completion
- Check preprocessing time
- Proceed to execution phase

**Example**:
```python
def on_prep_complete(self, plan_number: str):
    print(f"[{plan_number}] Geometry preprocessing complete")
```

---

### on_exec_start(plan_number, command)

**Called**: When HEC-RAS subprocess starts

**Parameters**:
- `plan_number` (str): Plan being executed
- `command` (str): Full command line used to start HEC-RAS

**Use Cases**:
- Log execution start
- Record command for debugging
- Initialize progress tracking

**Example**:
```python
def on_exec_start(self, plan_number: str, command: str):
    self.start_times[plan_number] = time.time()
    print(f"[{plan_number}] Execution started: {command}")
```

---

### on_exec_message(plan_number, message)

**Called**: For each new line written to `.bco` file (real-time streaming)

**Parameters**:
- `plan_number` (str): Plan generating message
- `message` (str): Single line from .bco file

**Frequency**: Very high (hundreds to thousands of calls per execution)

**Use Cases**:
- Real-time progress display
- Parse for specific patterns (errors, warnings, timesteps)
- Update progress bars
- Stream to logs

**Example**:
```python
def on_exec_message(self, plan_number: str, message: str):
    # Parse timestep progress
    if "Timestep" in message:
        print(f"[{plan_number}] {message.strip()}")

    # Detect errors
    if "ERROR" in message.upper():
        self.errors[plan_number].append(message)
```

**Performance Note**: This method is called VERY frequently - keep it fast!

---

### on_exec_complete(plan_number, success, duration)

**Called**: When execution finishes (success or failure)

**Parameters**:
- `plan_number` (str): Plan that completed
- `success` (bool): True if execution succeeded, False if failed
- `duration` (float): Execution time in seconds

**Use Cases**:
- Log completion status
- Send alerts
- Calculate statistics
- Cleanup resources

**Example**:
```python
def on_exec_complete(self, plan_number: str, success: bool, duration: float):
    status = "SUCCESS" if success else "FAILED"
    print(f"[{plan_number}] {status} in {duration:.1f} seconds")

    if not success:
        send_alert(f"Plan {plan_number} failed")
```

---

### on_verify_result(plan_number, verified)

**Called**: After HDF verification (only if `verify=True` parameter used)

**Parameters**:
- `plan_number` (str): Plan that was verified
- `verified` (bool): True if "Complete Process" found in HDF, False otherwise

**Use Cases**:
- Log verification results
- Trigger post-processing only for verified plans
- Alert on verification failure

**Example**:
```python
def on_verify_result(self, plan_number: str, verified: bool):
    if verified:
        print(f"[{plan_number}] Verification PASSED")
    else:
        print(f"[{plan_number}] Verification FAILED - results may be incomplete")
        send_alert(f"Plan {plan_number} failed verification")
```

---

## How .bco Monitoring Works

### Background

HEC-RAS writes detailed execution messages to `.bco` files when "Write Detailed=1" is set in the plan file.

**Process**:
1. `RasCmdr` automatically enables "Write Detailed=1" when `stream_callback` is provided
2. `BcoMonitor` polls the `.bco` file during execution
3. New messages are read incrementally and passed to callback
4. Monitoring stops when execution completes

**File Location**: `{project_name}.p{plan_number}.bco`

**Example**: `MyProject.p01.bco`

### Message Types

Typical `.bco` messages include:
- **Preprocessing**: "Geometry Preprocessor Version 6.6"
- **Progress**: "Computing Plan: 01"
- **Timesteps**: "Timestep 100 of 240"
- **Warnings**: "Warning: Flow exceeded critical depth"
- **Errors**: "ERROR: Model did not converge"
- **Completion**: "Complete Process"

---

## Best Practices

### 1. Keep on_exec_message() Fast

This method is called hundreds/thousands of times - optimize for speed:

```python
# ❌ BAD - Slow I/O on every message
def on_exec_message(self, plan_number: str, message: str):
    with open(f"plan_{plan_number}.log", "a") as f:  # Opens file repeatedly
        f.write(message)

# ✅ GOOD - Buffer messages, write in batches
def on_exec_message(self, plan_number: str, message: str):
    self.buffer.append(message)
    if len(self.buffer) >= 100:
        self.flush()
```

### 2. Use Thread-Safe Patterns for Parallel Execution

```python
from threading import Lock

class MyCallback:
    def __init__(self):
        self.lock = Lock()
        self.shared_state = {}

    def on_exec_complete(self, plan_number: str, success: bool, duration: float):
        with self.lock:  # Protect shared state
            self.shared_state[plan_number] = success
```

### 3. Implement Only Methods You Need

All callback methods are optional:

```python
# Minimal callback - only completion notification
class MinimalCallback:
    def on_exec_complete(self, plan_number: str, success: bool, duration: float):
        print(f"Plan {plan_number} done: {success}")

# Full callback - all methods
class FullCallback:
    def on_prep_start(self, plan_number: str): ...
    def on_prep_complete(self, plan_number: str): ...
    def on_exec_start(self, plan_number: str, command: str): ...
    def on_exec_message(self, plan_number: str, message: str): ...
    def on_exec_complete(self, plan_number: str, success: bool, duration: float): ...
    def on_verify_result(self, plan_number: str, verified: bool): ...
```

### 4. Handle Exceptions Gracefully

Callback exceptions are logged but don't stop execution:

```python
def on_exec_complete(self, plan_number: str, success: bool, duration: float):
    try:
        send_email_alert(plan_number, success)
    except Exception as e:
        # Log error but don't crash execution
        logging.error(f"Failed to send alert: {e}")
```

---

## See Also

- **Main Skill**: [../skill.md](../skill.md) - Common execution patterns
- **API Reference**: [api.md](api.md) - Complete RasCmdr API
- **Real-Time Monitoring Docs**: `C:\GH\ras-commander\ras_commander\BcoMonitor.py`
- **Example Callbacks**: `C:\GH\ras-commander\ras_commander\callbacks.py`
