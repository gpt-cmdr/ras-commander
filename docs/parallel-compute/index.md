# Parallel Compute

RAS Commander provides multiple strategies for scaling HEC-RAS computations, from single-machine parallelization to distributed execution across multiple remote workers.

## Scaling Strategies Overview

| Strategy | Use Case | Throughput | Complexity |
|----------|----------|------------|------------|
| **Sequential** | Debugging, simple workflows | 1x | Low |
| **Local Parallel** | Multi-core workstation | 2-8x | Low |
| **Remote Parallel** | Multiple machines | 10-100x+ | Medium |
| **Hybrid** | Mixed local + remote | Maximum | High |

## Key Concepts

### Worker Folders

All parallel execution methods use **worker folders** - isolated copies of the HEC-RAS project where computations run independently. This approach:

- Prevents file locking conflicts
- Enables concurrent plan execution
- Preserves the original project files
- Allows results collection from multiple runs

### Plan Independence

HEC-RAS plans can run independently when they:

- Don't share geometry preprocessor files
- Don't write to the same output locations
- Have no interdependencies (e.g., initial conditions from another run)

### Core Allocation

HEC-RAS 2D computations can use multiple CPU cores. The optimal allocation depends on:

- **Model size**: Larger meshes benefit from more cores
- **Available cores**: Diminishing returns beyond 8-16 cores per plan
- **Concurrent plans**: Balance cores per plan vs. simultaneous plans

## Quick Comparison

```python
from ras_commander import RasCmdr, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Sequential - one plan at a time
result = RasCmdr.compute_plan("01")

# Local Parallel - multiple plans on same machine
results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03", "04"],
    num_workers=4,
    num_cores=4
)

# Remote Parallel - distributed across machines
from ras_commander.remote import init_ras_worker, compute_parallel_remote

workers = [
    init_ras_worker("local", ras_version="6.5", num_cores=8),
    init_ras_worker("psexec", host="192.168.1.100", ...),
]
results = compute_parallel_remote(
    plan_number=["01", "02", "03", "04"],
    workers=workers
)
```

## Documentation Sections

- [**Local Parallel Execution**](local-parallel.md) - Scale on a single machine with `compute_parallel`
- [**Remote Parallel Execution**](remote-parallel.md) - Distribute across multiple machines with `compute_parallel_remote`
- [**Scaling Strategies**](scaling-strategies.md) - Best practices for maximizing throughput
- [**Worker Types**](worker-types.md) - Available worker backends and configuration
