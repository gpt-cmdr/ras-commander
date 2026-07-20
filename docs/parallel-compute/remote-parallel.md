# Remote Parallel Execution

The `compute_parallel_remote()` function enables distributed HEC-RAS execution across multiple machines, dramatically increasing throughput for large-scale modeling efforts.

## Overview

Remote parallel execution distributes queued HEC-RAS plans across a pool of worker machines. A plan is assigned only when a worker has capacity:

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
     │  capacity 2 │  │  capacity 1 │  │  capacity 2 │
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
    init_ras_worker(
        "local",
        worker_folder=r"C:\RasRemote",
        cores_total=8,
        cores_per_plan=4,
    ),
    init_ras_worker("psexec",
        hostname="192.168.1.100",
        share_path=r"\\192.168.1.100\RasRemote",
        worker_folder=r"C:\RasRemote",
        ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
        session_id=2,
        cores_total=16,
        cores_per_plan=4,
    ),
]

# Execute across workers
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04", "05", "06"],
    workers=workers,
    num_cores=4,
)

# Check results
for plan, result in results.items():
    print(f"Plan {plan}: {'succeeded' if result.success else 'failed'}")
```

## The init_ras_worker Factory

`init_ras_worker()` creates worker instances and performs backend-specific
configuration checks:

```python
from ras_commander.remote import init_ras_worker

# Local worker - uses current machine
local = init_ras_worker(
    "local",
    worker_folder=r"C:\RasRemote",
    cores_total=8,
    cores_per_plan=4,
)

# PsExec worker - Windows remote via PsExec
psexec = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    worker_folder=r"C:\RasRemote",
    ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
    session_id=2,      # Required: GUI session ID
    cores_total=16,
    cores_per_plan=4,
)

# Docker worker - Container execution
docker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    staging_directory=r"C:\RasDocker",
    cores_total=8,
    cores_per_plan=4,
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
    force_geompre: bool = False,
    force_rerun: bool = False,
    max_concurrent: Optional[int] = None,
    autoclean: bool = True,
    copy_geometry_outputs: bool = True,
) -> Dict[str, ExecutionResult]:
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `plan_numbers` | str or list | Required | Single plan or list of plans to execute |
| `workers` | list | Required | Worker instances from `init_ras_worker()` |
| `ras_object` | RasPrj | None | Project object (uses global `ras` if None) |
| `num_cores` | int | 4 | CPU cores allocated per plan; must be at least 1 |
| `clear_geompre` | bool | False | Clear geometry preprocessor files before run |
| `force_geompre` | bool | False | Clear geometry HDF and preprocessor files before run |
| `force_rerun` | bool | False | Run even when existing results are current |
| `max_concurrent` | int | None | Max concurrent executions (default: sum of worker slots) |
| `autoclean` | bool | True | Delete temp worker folders after execution |
| `copy_geometry_outputs` | bool | True | For local and PsExec workers, copy geometry outputs back with the plan HDF |

!!! warning "Concurrent geometry copyback"
    `copy_geometry_outputs=True` is backward compatible, but concurrent local or
    PsExec plans that share a geometry can race while copying the same geometry
    HDF and preprocessor outputs. For concurrent scenario ensembles using
    preprocessed shared geometry, set `copy_geometry_outputs=False`.

The effective capacity of each worker is
`min(max_parallel_plans, cores_total // num_cores)`. A worker configured with
`cores_total=16` and `cores_per_plan=4` normally has four slots. Calling
`compute_parallel_remote(..., num_cores=8)` reduces that worker to two slots.
Workers that cannot provide `num_cores` for one plan are skipped; execution fails
early if no worker has capacity.

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
    init_ras_worker(
        "local",
        worker_folder=r"C:\RasRemote",
        cores_total=16,
        cores_per_plan=4,
    ),
    init_ras_worker(
        "psexec",
        hostname="worker-a",
        share_path=r"\\worker-a\RasRemote",
        ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
        session_id=2,
        cores_total=8,
        cores_per_plan=4,
    ),
    init_ras_worker(
        "psexec",
        hostname="worker-b",
        share_path=r"\\worker-b\RasRemote",
        ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
        session_id=2,
        cores_total=4,
        cores_per_plan=4,
    ),
]

results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04", "05",
                  "06", "07", "08", "09", "10"],
    workers=workers
)

# Fast worker completes more plans automatically
# No manual load balancing required
```

The scheduler tracks actual in-flight work per host. A queued plan is submitted
only after a slot on that worker is released, preventing the executor queue from
oversubscribing a slow host. Lower `queue_priority` values are preferred whenever
those workers have free capacity.

For PsExec workers, `num_cores` is written to the staged plan after project copy.
The source plan and its project dataframes remain unchanged.

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
4. **GUI session available** (use its positive ID as `session_id`)
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
    Use the active session ID reported by `query user`; it is often, but not
    always, `2`. `session_id` must be a positive integer. Normal execution uses
    `-i <session_id>`. With `system_account=True`, PsExec uses both `-s` and `-i
    <session_id>`, but SYSTEM is still not recommended for interactive HEC-RAS
    execution.

### Docker Worker Requirements

1. **Docker daemon** available locally or through `docker_host`
2. **HEC-RAS Docker image** available (native Linux binaries from HEC)
3. **Remote Linux hosts** accessible through an `ssh://` Docker host, with SSH authentication configured
4. **Remote Windows hosts** configured with `share_path` and `remote_staging_path`

See [Worker Types](worker-types.md#dockerworker) for Docker image building details.

## Example: Heterogeneous Worker Pool

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

init_ras_project("/path/to/project", "6.5")

# Mix of worker types
workers = [
    # Local workstation
    init_ras_worker(
        "local",
        worker_folder=r"C:\RasRemote",
        cores_total=8,
        cores_per_plan=8,
    ),

    # Remote workstation 1
    init_ras_worker("psexec",
        hostname="192.168.1.101",
        share_path=r"\\192.168.1.101\RasRemote",
        ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
        session_id=2,
        cores_total=16,
        cores_per_plan=8,
    ),

    # Remote workstation 2
    init_ras_worker("psexec",
        hostname="192.168.1.102",
        share_path=r"\\192.168.1.102\RasRemote",
        ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
        session_id=2,
        cores_total=32,
        cores_per_plan=8,
    ),
]

# Execute 20 plans across pool
results = compute_parallel_remote(
    plan_numbers=[f"{i:02d}" for i in range(1, 21)],
    workers=workers,
    num_cores=8,
)
```

## Example: Configuration File

Store worker configurations in a JSON file:

```json
{
  "workers": [
    {
      "type": "local",
      "worker_folder": "C:\\RasRemote",
      "cores_total": 8,
      "cores_per_plan": 4
    },
    {
      "type": "psexec",
      "hostname": "192.168.1.100",
      "share_path": "\\\\192.168.1.100\\RasRemote",
      "ras_exe_path": "C:\\Program Files\\HEC\\HEC-RAS\\6.5\\Ras.exe",
      "session_id": 2,
      "cores_total": 16,
      "cores_per_plan": 4
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

try:
    workers = [
        init_ras_worker("local", cores_total=4, cores_per_plan=4),
        init_ras_worker(
            "psexec",
            hostname="192.168.1.100",
            share_path=r"\\192.168.1.100\RasRemote",
            ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
            session_id=2,
            cores_total=8,
            cores_per_plan=4,
        ),
    ]
    results = compute_parallel_remote(
        plan_numbers=["01", "02", "03"],
        workers=workers,
    )
except (ValueError, FileNotFoundError) as exc:
    raise RuntimeError(f"Invalid worker pool configuration: {exc}") from exc

# Handle individual plan failures
failed = {plan: result for plan, result in results.items() if not result.success}
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
    hostname=os.environ["RAS_WORKER_HOST"],
    share_path=rf"\\{os.environ['RAS_WORKER_HOST']}\RasRemote",
    credentials={
        "username": os.environ["RAS_WORKER_USER"],
        "password": os.environ["RAS_WORKER_PASS"],
    },
    ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.5\Ras.exe",
    session_id=2
)
```

## Performance Monitoring

```python
import time
from ras_commander.remote import compute_parallel_remote

start = time.time()

results = compute_parallel_remote(
    plan_numbers=plans,
    workers=workers
)

elapsed = time.time() - start
successful = sum(1 for result in results.values() if result.success)

print(f"Completed {successful}/{len(plans)} plans in {elapsed:.1f}s")
print(f"Average: {elapsed/len(plans):.1f}s per plan")
print(f"Throughput: {len(plans)/elapsed*3600:.1f} plans/hour")
```

## Related

- [Local Parallel Execution](local-parallel.md) - Single machine parallelism
- [Worker Types](worker-types.md) - Detailed worker configuration
- [Scaling Strategies](scaling-strategies.md) - Optimization techniques
