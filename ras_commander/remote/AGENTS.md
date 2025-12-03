# AGENTS.md - Remote Execution Subpackage

This file provides guidance for AI agents working with the `ras_commander.remote` subpackage.

## Overview

The `remote` subpackage provides distributed execution capabilities for HEC-RAS simulations across local, remote, and cloud compute resources.

## Module Structure

```
ras_commander/remote/
├── __init__.py         # Exports all public classes and functions
├── RasWorker.py        # RasWorker base dataclass + init_ras_worker()
├── PsexecWorker.py     # PsexecWorker (IMPLEMENTED)
├── LocalWorker.py      # LocalWorker (IMPLEMENTED)
├── SshWorker.py        # SshWorker (stub, requires paramiko)
├── WinrmWorker.py      # WinrmWorker (stub, requires pywinrm)
├── DockerWorker.py     # DockerWorker (IMPLEMENTED, requires docker+paramiko)
├── SlurmWorker.py      # SlurmWorker (stub)
├── AwsEc2Worker.py     # AwsEc2Worker (stub, requires boto3)
├── AzureFrWorker.py    # AzureFrWorker (stub, requires azure-*)
├── Execution.py        # compute_parallel_remote() + helpers
├── Utils.py            # Shared utilities
└── AGENTS.md           # This file
```

## Naming Convention

This subpackage follows the **PascalCase module naming** convention used throughout ras-commander:
- Module names match the primary class they contain (e.g., `RasWorker.py` contains `RasWorker` class)
- Factory functions are co-located with their classes (e.g., `init_ras_worker()` is in `RasWorker.py`)
- This pattern mirrors `RasPrj.py` which contains both `RasPrj` class and `init_ras_project()`

## Import Patterns

### Recommended (Top-Level)
```python
from ras_commander import init_ras_worker, compute_parallel_remote
```

### Direct Subpackage Import
```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote
from ras_commander.remote import PsexecWorker
```

## Coding Conventions

### Internal Imports
All modules in this subpackage use **relative imports** to reference:
- Other modules within `remote/`: `from .RasWorker import RasWorker`
- Parent package modules: `from ..RasPrj import ras, RasPrj`
- Decorators and logging: `from ..Decorators import log_call`, `from ..LoggingConfig import get_logger`

### Lazy Loading for Optional Dependencies
Workers with optional dependencies implement a `check_*_dependencies()` function:
```python
def check_ssh_dependencies():
    try:
        import paramiko
        return paramiko
    except ImportError:
        raise ImportError(
            "SSH worker requires paramiko.\n"
            "Install with: pip install ras-commander[remote-ssh]"
        )
```

### Worker Implementation Pattern
Each worker module follows this pattern:
1. **Dataclass definition**: Extends `RasWorker` with worker-specific fields
2. **Validation in `__post_init__`**: Calls `super().__post_init__()`, raises `NotImplementedError` for stubs
3. **Init function**: `init_*_worker(**kwargs)` for factory routing
4. **Execute function**: `execute_*_plan(...)` for actual execution (if implemented)

### Factory Function Pattern
The `init_ras_worker()` factory function in `RasWorker.py`:
- Uses **lazy imports** inside the function body to avoid circular dependencies
- Routes to worker-specific `init_*_worker()` functions based on `worker_type`
- Auto-generates `worker_id` if not provided

```python
def init_ras_worker(worker_type: str, **kwargs) -> RasWorker:
    if worker_type == "psexec":
        from .PsexecWorker import init_psexec_worker
        return init_psexec_worker(**kwargs)
    elif worker_type == "local":
        from .LocalWorker import init_local_worker
        return init_local_worker(**kwargs)
    # ... etc
```

## Critical Implementation Notes

### PsExec Worker
- **HEC-RAS requires a desktop session**: Use `system_account=False, session_id=2`
- **Never use `system_account=True`**: HEC-RAS will hang without a desktop
- **UNC to local path conversion**: PsExec runs on remote filesystem, not UNC
- **Credentials are optional**: Windows auth preferred for GUI access

### Docker Worker
- **Requires docker and paramiko packages**: `pip install docker paramiko`
- **Preprocesses locally first**: Windows preprocessing runs locally, then copies to remote
- **Supports Docker over SSH**: Use `docker_host: "ssh://user@host"` for remote Docker daemons
- **Path conversion**: Automatically converts `/mnt/c/` paths to `C:/` for Docker Desktop
- **SSH key authentication required**: For remote Docker hosts, SSH keys must be configured

### Adding New Workers
1. Create `NewWorker.py` following PascalCase naming (module name = class name)
2. Add dataclass extending `RasWorker` from `.RasWorker`
3. Implement `check_*_dependencies()` if optional deps required
4. Add `init_*_worker()` function
5. Add execution function if implementing (not just stub)
6. Update `RasWorker.py` to route to new worker in `init_ras_worker()`
7. Update `Execution.py` to dispatch execution in `_execute_single_plan()`
8. Update `__init__.py` exports
9. Update `setup.py` extras_require if new deps

### Function Naming
- Public functions: `snake_case` (e.g., `init_ras_worker`, `compute_parallel_remote`)
- Worker init: `init_*_worker(**kwargs)` (e.g., `init_psexec_worker`)
- Execution: `execute_*_plan(worker, plan_number, ras_obj, ...)` (e.g., `execute_psexec_plan`)
- Dependency check: `check_*_dependencies()` (e.g., `check_ssh_dependencies`)

## Testing

Tests are in the example notebooks:
- `examples/23_remote_execution_psexec.ipynb` - Primary test for PsExec worker

Run the notebook to verify the remote subpackage works correctly.

## Dependencies by Worker

| Worker | Extra | Dependencies |
|--------|-------|--------------|
| PsexecWorker | (none) | Standard library only |
| SshWorker | `remote-ssh` | paramiko>=3.0 |
| WinrmWorker | `remote-winrm` | pywinrm>=0.4.3 |
| DockerWorker | `remote-docker` | docker>=6.0 |
| AwsEc2Worker | `remote-aws` | boto3>=1.28 |
| AzureFrWorker | `remote-azure` | azure-identity, azure-mgmt-compute |

## Common Issues

### Import Error on Missing Dependency
Expected behavior - clear error message directs to correct install command.

### PsExec Worker Hangs
Check `system_account` and `session_id` settings. HEC-RAS needs desktop access.

### UNC Path Errors
Ensure `local_path` matches the network share's local mount point on remote machine.
