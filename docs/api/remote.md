# Remote Modules

Classes for distributed HEC-RAS execution across multiple machines.

## Factory Function

### init_ras_worker

Create and validate a remote worker.

```python
from ras_commander.remote import init_ras_worker

worker = init_ras_worker(
    worker_type,      # "local", "psexec", or "docker"
    ras_version,      # HEC-RAS version string
    **worker_options  # Worker-specific options
)
```

## Execution

### compute_parallel_remote

Execute plans across distributed worker pool.

```python
from ras_commander.remote import compute_parallel_remote

results = compute_parallel_remote(
    plan_number,      # List of plan numbers
    workers,          # List of worker instances
    dest_folder=None  # Optional destination folder
)
```

## Worker Classes

### LocalWorker

Local parallel execution.

```python
worker = init_ras_worker(
    "local",
    ras_version="6.5",
    num_cores=4,        # Cores per plan
    max_concurrent=2    # Simultaneous plans
)
```

### PsexecWorker

Windows remote execution via PsExec.

```python
worker = init_ras_worker(
    "psexec",
    host="192.168.1.100",
    username="domain\\user",
    password="password",
    ras_version="6.5",
    session_id=2,       # GUI session (required)
    num_cores=4
)
```

### DockerWorker

Container-based execution.

```python
worker = init_ras_worker(
    "docker",
    host="docker-host.local",
    ssh_key="/path/to/key",
    image="hec-ras:6.5",
    ras_version="6.5",
    num_cores=4
)
```

## Worker Interface

All workers implement:

- `validate()` - Test connectivity, returns bool
- `execute_plan(plan, dest)` - Run plan, returns bool
- `cleanup()` - Clean up resources

## Usage

```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Create workers
workers = [
    init_ras_worker("local", ras_version="6.5", num_cores=4),
    init_ras_worker("psexec",
        host="192.168.1.100",
        username="user",
        password="pass",
        ras_version="6.5",
        session_id=2
    ),
]

# Execute across workers
results = compute_parallel_remote(
    plan_number=["01", "02", "03", "04"],
    workers=workers
)
```

## Installation

```bash
# Basic (LocalWorker only)
pip install ras-commander

# SSH/Docker support
pip install ras-commander[remote-ssh]

# All backends
pip install ras-commander[remote-all]
```
