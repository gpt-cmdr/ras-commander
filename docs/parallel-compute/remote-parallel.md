# Remote Parallel Execution

The `compute_parallel_remote()` function enables distributed HEC-RAS execution across multiple machines, dramatically increasing throughput for large-scale modeling efforts.

## Overview

Remote parallel execution distributes HEC-RAS plans across a pool of worker machines:

```
                    ┌─────────────────┐
                    │  Control Machine │
                    │  (ras-commander) │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
     ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
     │  Worker 1   │  │  Worker 2   │  │  Worker 3   │
     │  (Local)    │  │  (PsExec)   │  │  (Docker)   │
     │  Plans 1,4  │  │  Plans 2,5  │  │  Plans 3,6  │
     └─────────────┘  └─────────────┘  └─────────────┘
```

## Basic Usage

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Create workers
workers = [
    init_ras_worker("local", ras_version="6.5", num_cores=8),
    init_ras_worker("psexec",
        host="192.168.1.100",
        username="domain\\user",
        password="password",
        ras_version="6.5",
        session_id=2,
        num_cores=8
    ),
]

# Execute across workers
results = compute_parallel_remote(
    plan_number=["01", "02", "03", "04", "05", "06"],
    workers=workers
)

# Check results
for plan, result in results.items():
    print(f"Plan {plan}: {result}")
```

## The init_ras_worker Factory

`init_ras_worker()` creates and validates worker instances:

```python
from ras_commander.remote import init_ras_worker

# Local worker - uses current machine
local = init_ras_worker(
    "local",
    ras_version="6.5",
    num_cores=4,
    max_concurrent=2  # Simultaneous plans
)

# PsExec worker - Windows remote via PsExec
psexec = init_ras_worker(
    "psexec",
    host="192.168.1.100",
    username="DOMAIN\\user",
    password="password",
    ras_version="6.5",
    session_id=2,      # Required: GUI session ID
    num_cores=8
)

# Docker worker - Container execution
docker = init_ras_worker(
    "docker",
    host="docker-host.local",
    ssh_key="/path/to/key",
    image="hec-ras:6.5",
    ras_version="6.5",
    num_cores=4
)
```

## compute_parallel_remote Parameters

```python
def compute_parallel_remote(
    plan_numbers: Union[str, List[str]],
    workers: List[RasWorker],
    ras_object=None,
    num_cores: int = 4,
    clear_geompre: bool = False,
    max_concurrent: Optional[int] = None,
    autoclean: bool = True
) -> Dict[str, ExecutionResult]:
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `plan_numbers` | str or list | Required | Single plan or list of plans to execute |
| `workers` | list | Required | Worker instances from `init_ras_worker()` |
| `ras_object` | RasPrj | None | Project object (uses global `ras` if None) |
| `num_cores` | int | 4 | CPU cores allocated per plan execution |
| `clear_geompre` | bool | False | Clear geometry preprocessor files before run |
| `max_concurrent` | int | None | Max concurrent executions (default: sum of worker slots) |
| `autoclean` | bool | True | Delete temp worker folders after execution |

!!! tip "Debugging with autoclean=False"
    Set `autoclean=False` to preserve worker folders for debugging failed executions:
    ```python
    results = compute_parallel_remote(
        plan_numbers=plans,
        workers=workers,
        autoclean=False  # Keep temp folders
    )
    ```

## ExecutionResult Dataclass

Each plan execution returns an `ExecutionResult` object:

```python
@dataclass
class ExecutionResult:
    plan_number: str          # Plan that was executed
    worker_id: str            # Worker that ran this plan
    success: bool             # True if completed successfully
    hdf_path: Optional[str]   # Path to output HDF (if success)
    error_message: Optional[str]  # Error details (if failed)
    execution_time: float     # Execution time in seconds
```

**Accessing Results:**

```python
results = compute_parallel_remote(plans, workers)

for plan_num, result in results.items():
    if result.success:
        print(f"Plan {plan_num}: completed in {result.execution_time:.1f}s")
        print(f"  Output: {result.hdf_path}")
        print(f"  Worker: {result.worker_id}")
    else:
        print(f"Plan {plan_num}: FAILED")
        print(f"  Error: {result.error_message}")
```

**Aggregating Statistics:**

```python
results = compute_parallel_remote(plans, workers)

# Summary statistics
successful = [r for r in results.values() if r.success]
failed = [r for r in results.values() if not r.success]

print(f"Success: {len(successful)}/{len(results)}")
print(f"Total time: {sum(r.execution_time for r in successful):.1f}s")
print(f"Average: {sum(r.execution_time for r in successful)/len(successful):.1f}s")

# Plans by worker
from collections import Counter
worker_counts = Counter(r.worker_id for r in results.values())
for worker_id, count in worker_counts.items():
    print(f"  {worker_id}: {count} plans")
```

## Worker Pool Execution

### Queue-Based Distribution

Plans are distributed using a queue. Workers pull plans as they become available:

```python
# 10 plans, 3 workers with different speeds
workers = [
    init_ras_worker("local", ...),       # Fast (local SSD)
    init_ras_worker("psexec", host=A),   # Medium (network)
    init_ras_worker("psexec", host=B),   # Slow (older hardware)
]

results = compute_parallel_remote(
    plan_number=["01", "02", "03", "04", "05",
                 "06", "07", "08", "09", "10"],
    workers=workers
)

# Fast worker completes more plans automatically
# No manual load balancing required
```

### Wave Scheduling

For large plan sets, workers execute in waves:

```
Wave 1: Workers 1-3 execute plans 1-3
Wave 2: As workers finish, they pick up plans 4-6
...continues until all plans complete
```

## Setting Up Remote Workers

### PsExec Worker Requirements

1. **PsExec installed** on control machine (from [Sysinternals](https://docs.microsoft.com/en-us/sysinternals/downloads/psexec))
2. **Network share** created on remote machine (`C:\RasRemote` shared as `RasRemote`)
3. **HEC-RAS installed** on remote machine
4. **GUI session available** (HEC-RAS requires interactive session - `session_id=2`)
5. **Firewall rules** allowing PsExec communication

**Required Ports:**

| Port | Protocol | Purpose |
|------|----------|---------|
| 445 | TCP | SMB (file sharing) |
| 135 | TCP | RPC (Remote Registry) |
| 139 | TCP | NetBIOS (legacy SMB) |
| 49152-65535 | TCP | Dynamic ports (PsExec) |

**Remote Machine Configuration:**

```powershell
# 1. Create and share folder
mkdir C:\RasRemote
net share RasRemote=C:\RasRemote /GRANT:Everyone,FULL

# 2. Enable Remote Registry service
Set-Service RemoteRegistry -StartupType Automatic
Start-Service RemoteRegistry

# 3. Set LocalAccountTokenFilterPolicy (allows admin over network)
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f

# 4. Add user to Administrators group
net localgroup Administrators youruser /add

# 5. Enable firewall rules
netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes

# 6. REBOOT (required for registry changes)
```

**Group Policy Configuration (gpedit.msc):**

Navigate to: `Computer Configuration > Windows Settings > Security Settings > Local Policies > User Rights Assignment`

| Policy | Action |
|--------|--------|
| Access this computer from the network | Add your user |
| Allow log on locally | Add your user |
| Log on as a batch job | Add your user |

After changes: `gpupdate /force` and **REBOOT**

### Finding the Session ID

```powershell
# On remote machine, run:
query user

# Output:
# USERNAME    SESSIONNAME    ID  STATE
# bill        console         2  Active
#                             ^-- Use this ID
```

!!! warning "Session ID Required"
    **Always use `session_id=2`** (typical for workstations). Never use `system_account=True` - HEC-RAS is a GUI application and will hang without a user session.

### Docker Worker Requirements

1. **Docker host** accessible via SSH
2. **HEC-RAS Docker image** available (native Linux binaries from HEC)
3. **SSH key authentication** configured
4. **Network share** for file transfer between Windows control and Docker host

See [Worker Types](worker-types.md#dockerworker) for Docker image building details.

## Example: Heterogeneous Worker Pool

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

init_ras_project("/path/to/project", "6.5")

# Mix of worker types
workers = [
    # Local workstation
    init_ras_worker("local", ras_version="6.5", num_cores=8),

    # Remote workstation 1
    init_ras_worker("psexec",
        host="192.168.1.101",
        username="user",
        password="pass",
        ras_version="6.5",
        session_id=2,
        num_cores=8
    ),

    # Remote workstation 2
    init_ras_worker("psexec",
        host="192.168.1.102",
        username="user",
        password="pass",
        ras_version="6.5",
        session_id=2,
        num_cores=16
    ),
]

# Validate all workers before execution
for i, worker in enumerate(workers):
    if not worker.validate():
        print(f"Worker {i} validation failed!")

# Execute 20 plans across pool
results = compute_parallel_remote(
    plan_number=[f"{i:02d}" for i in range(1, 21)],
    workers=workers
)
```

## Example: Configuration File

Store worker configurations in a JSON file:

```json
{
  "workers": [
    {
      "type": "local",
      "ras_version": "6.5",
      "num_cores": 8
    },
    {
      "type": "psexec",
      "host": "192.168.1.100",
      "username": "DOMAIN\\user",
      "ras_version": "6.5",
      "session_id": 2,
      "num_cores": 8
    }
  ]
}
```

```python
import json
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Load configuration
with open("workers.json") as f:
    config = json.load(f)

# Create workers from config
workers = []
for w in config["workers"]:
    worker_type = w.pop("type")
    workers.append(init_ras_worker(worker_type, **w))

# Passwords should be retrieved securely, not stored in JSON
```

## Error Handling

```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote

workers = [
    init_ras_worker("local", ras_version="6.5", num_cores=4),
    init_ras_worker("psexec", host="192.168.1.100", ...),
]

# Validate before running
valid_workers = []
for worker in workers:
    try:
        if worker.validate():
            valid_workers.append(worker)
        else:
            print(f"Worker {worker} failed validation")
    except Exception as e:
        print(f"Worker error: {e}")

if not valid_workers:
    raise RuntimeError("No valid workers available")

# Run with valid workers only
results = compute_parallel_remote(
    plan_number=["01", "02", "03"],
    workers=valid_workers
)

# Handle individual plan failures
failed = {k: v for k, v in results.items() if not v}
if failed:
    print(f"Failed plans: {list(failed.keys())}")
```

## Security Considerations

!!! warning "Credentials"
    - Never store passwords in source code or config files
    - Use environment variables or secure credential stores
    - Consider SSH key authentication for Docker workers

```python
import os
from ras_commander.remote import init_ras_worker

# Secure credential retrieval
worker = init_ras_worker(
    "psexec",
    host=os.environ["RAS_WORKER_HOST"],
    username=os.environ["RAS_WORKER_USER"],
    password=os.environ["RAS_WORKER_PASS"],
    ras_version="6.5",
    session_id=2
)
```

## Performance Monitoring

```python
import time
from ras_commander.remote import compute_parallel_remote

start = time.time()

results = compute_parallel_remote(
    plan_number=plans,
    workers=workers
)

elapsed = time.time() - start
successful = sum(1 for v in results.values() if v)

print(f"Completed {successful}/{len(plans)} plans in {elapsed:.1f}s")
print(f"Average: {elapsed/len(plans):.1f}s per plan")
print(f"Throughput: {len(plans)/elapsed*3600:.1f} plans/hour")
```

## Related

- [Local Parallel Execution](local-parallel.md) - Single machine parallelism
- [Worker Types](worker-types.md) - Detailed worker configuration
- [Scaling Strategies](scaling-strategies.md) - Optimization techniques
