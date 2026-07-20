# Remote Modules

Classes and functions for distributed HEC-RAS execution across local, PsExec,
and Docker workers.

## Factory Function

### init_ras_worker

Create workers with `init_ras_worker()` and the options for the selected worker
type. The factory returns a `LocalWorker`, `PsexecWorker`, or `DockerWorker` for
the implemented backends.

## Worker Classes

### LocalWorker

Run plans in isolated folders on the control machine:

```python
from ras_commander.remote import init_ras_worker

local = init_ras_worker(
    "local",
    worker_folder=r"C:\RasRemote",
    cores_total=8,
    cores_per_plan=4,
)
```

### PsexecWorker

Run plans on a Windows machine through PsExec and an accessible network share:

```python
from ras_commander.remote import init_ras_worker

remote = init_ras_worker(
    "psexec",
    hostname="WORKSTATION-01",
    share_path=r"\\WORKSTATION-01\RasRemote",
    worker_folder=r"C:\RasRemote",
    ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.6\Ras.exe",
    session_id=2,
    cores_total=16,
    cores_per_plan=4,
)
```

`session_id` must be a positive integer. PsExec always targets that desktop
session with `-i <session_id>`. When `system_account=True`, the command uses both
`-s` and `-i <session_id>`; SYSTEM remains unsuitable for most interactive
HEC-RAS runs.

### DockerWorker

Run plans with a local Docker daemon and an HEC-RAS Linux image:

```python
from ras_commander.remote import init_ras_worker

docker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    staging_directory=r"C:\RasDocker",
    cores_total=8,
    cores_per_plan=4,
)
```

## Execution

### compute_parallel_remote

Execute queued plans across the worker pool:

```python
from ras_commander.remote import compute_parallel_remote

results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04"],
    workers=[local, remote],
    num_cores=4,
    force_rerun=False,
    max_concurrent=None,
    autoclean=True,
    copy_geometry_outputs=True,
)
```

`num_cores` must be at least 1. The scheduler enforces each worker's effective
capacity as the smaller of its configured `max_parallel_plans` and
`cores_total // num_cores`. Plans remain queued until a real worker slot is free,
so a slow host cannot be oversubscribed and a faster host can accept later plans.
Workers with lower `queue_priority` values are preferred when capacity is
available.

For PsExec runs, the staged plan is rewritten to use `num_cores`; the source plan
and source project dataframes are not changed. For local and PsExec workers, set
`copy_geometry_outputs=False` to copy the plan-result HDF back without copying
geometry HDF and preprocessor outputs. The default remains `True`.

!!! warning "Concurrent geometry copyback"
    `copy_geometry_outputs=True` preserves the previous behavior, but concurrent
    local or PsExec plans that share a geometry can race while copying the same
    geometry outputs. For concurrent scenario ensembles using already-preprocessed
    shared geometry, set `copy_geometry_outputs=False`.

The return value maps each plan number to an `ExecutionResult` with `success`,
`worker_id`, `hdf_path`, `error_message`, and `execution_time` fields.

The progress watchdog stops queued submissions when no plan finishes within the
slowest worker's `max_runtime_minutes` plus a staging/copy-back margin. It then
waits for already-started worker tasks before returning so those tasks cannot
continue mutating copied project outputs after the API call has returned.

## Installation

```bash
# Base package, including local and PsExec workers
pip install ras-commander

# Docker and all optional remote backends
pip install ras-commander[remote-docker]
pip install ras-commander[remote-all]
```
