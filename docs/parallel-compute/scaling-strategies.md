# Scaling Strategies

This guide covers best practices for maximizing HEC-RAS compute throughput using ras-commander's parallel execution capabilities.

## Understanding HEC-RAS Scaling

### Single Plan Performance

HEC-RAS 2D computations scale with CPU cores, but with diminishing returns:

| Cores | Relative Speed | Efficiency |
|-------|----------------|------------|
| 1 | 1.0x | 100% |
| 2 | 1.8x | 90% |
| 4 | 3.2x | 80% |
| 8 | 5.0x | 62% |
| 16 | 6.5x | 41% |
| 32 | 7.5x | 23% |

*Actual performance varies by model size and complexity*

### Throughput vs. Latency

Two optimization targets:

- **Latency**: Minimize time to complete a single plan (more cores per plan)
- **Throughput**: Maximize plans completed per hour (more parallel plans)

For batch processing, throughput is usually more important.

## Scaling Tiers

### Tier 1: Single Machine Optimization

**Goal**: Maximize throughput on one workstation

```python
from ras_commander import RasCmdr, init_ras_project
import os

init_ras_project("/path/to/project", "6.5")

# Determine optimal configuration
total_cores = os.cpu_count()
cores_per_plan = 4  # Sweet spot for most 2D models
num_workers = total_cores // cores_per_plan

results = RasCmdr.compute_parallel(
    plan_number=plans,
    num_workers=num_workers,
    num_cores=cores_per_plan
)
```

**Configuration Matrix (16-core machine):**

| Model Size | Workers | Cores/Plan | Rationale |
|------------|---------|------------|-----------|
| Small (<10K cells) | 8 | 2 | I/O bound, parallelize |
| Medium (10-100K) | 4 | 4 | Balanced |
| Large (>100K) | 2 | 8 | CPU bound, more cores help |

### Tier 2: Multi-Machine Parallel

**Goal**: Scale beyond single machine limits

```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Create heterogeneous worker pool
workers = [
    # Local workstation (16 cores)
    init_ras_worker("local", ras_version="6.5", num_cores=8),
    init_ras_worker("local", ras_version="6.5", num_cores=8),

    # Remote workstation 1 (32 cores)
    init_ras_worker("psexec", host="ws1.local", ras_version="6.5",
                    num_cores=8, session_id=2, ...),
    init_ras_worker("psexec", host="ws1.local", ras_version="6.5",
                    num_cores=8, session_id=2, ...),
    init_ras_worker("psexec", host="ws1.local", ras_version="6.5",
                    num_cores=8, session_id=2, ...),
    init_ras_worker("psexec", host="ws1.local", ras_version="6.5",
                    num_cores=8, session_id=2, ...),

    # Remote workstation 2 (16 cores)
    init_ras_worker("psexec", host="ws2.local", ras_version="6.5",
                    num_cores=8, session_id=2, ...),
    init_ras_worker("psexec", host="ws2.local", ras_version="6.5",
                    num_cores=8, session_id=2, ...),
]

# 8 workers, 64 total cores utilized
results = compute_parallel_remote(plan_number=plans, workers=workers)
```

### Tier 3: Hybrid Cloud

**Goal**: Burst capacity using cloud resources

```python
# Mix of on-premise and cloud workers
workers = [
    # On-premise (always available)
    init_ras_worker("local", ras_version="6.5", num_cores=8),
    init_ras_worker("psexec", host="office-ws1", ...),

    # Cloud burst (Docker on cloud VMs)
    init_ras_worker("docker", host="cloud-vm1.example.com",
                    image="hec-ras:6.5", num_cores=8, ...),
    init_ras_worker("docker", host="cloud-vm2.example.com",
                    image="hec-ras:6.5", num_cores=8, ...),
]
```

## Optimization Techniques

### 1. Pre-process Geometry

Run geometry preprocessing once before parallel execution:

```python
from ras_commander import RasCmdr, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Pre-process geometry (modifies original)
RasCmdr.compute_plan("01", clear_geompre=False)  # First run builds geom

# Parallel runs use cached geometry
results = RasCmdr.compute_parallel(
    plan_number=["02", "03", "04", "05"],
    num_workers=4,
    num_cores=4,
    clear_geompre=False  # Don't clear cached geometry
)
```

### 2. Use Fast Storage

Worker folder creation is I/O intensive. Storage hierarchy:

| Storage Type | Copy Speed | Recommendation |
|--------------|------------|----------------|
| NVMe SSD | Excellent | Use for worker folders |
| SATA SSD | Good | Acceptable |
| HDD | Poor | Avoid for parallel work |
| Network | Variable | Only for remote workers |

```python
from pathlib import Path

# Use fast local storage for workers
fast_drive = Path("D:/temp/ras_workers")  # SSD/NVMe

results = RasCmdr.compute_parallel(
    plan_number=plans,
    dest_folder=fast_drive,
    num_workers=8
)
```

### 3. Right-size Worker Count

More workers isn't always better:

```python
import psutil

def optimal_worker_config(model_cells, total_cores=None):
    """Suggest optimal worker configuration."""
    if total_cores is None:
        total_cores = psutil.cpu_count(logical=False)

    # Reserve cores for system
    available_cores = max(1, total_cores - 2)

    if model_cells < 10000:
        cores_per_plan = 2
    elif model_cells < 100000:
        cores_per_plan = 4
    else:
        cores_per_plan = 8

    num_workers = available_cores // cores_per_plan

    return {
        "num_workers": max(1, num_workers),
        "num_cores": cores_per_plan,
        "total_utilized": num_workers * cores_per_plan
    }

# Usage
config = optimal_worker_config(model_cells=50000)
print(f"Recommended: {config['num_workers']} workers, "
      f"{config['num_cores']} cores each")
```

### 4. Batch Processing Strategy

For very large plan sets, process in batches:

```python
from ras_commander import RasCmdr

def process_in_batches(all_plans, batch_size=20, **kwargs):
    """Process plans in batches to manage memory/resources."""
    all_results = {}

    for i in range(0, len(all_plans), batch_size):
        batch = all_plans[i:i + batch_size]
        print(f"Processing batch {i//batch_size + 1}: plans {batch[0]}-{batch[-1]}")

        results = RasCmdr.compute_parallel(
            plan_number=batch,
            **kwargs
        )
        all_results.update(results)

        # Optional: cleanup between batches
        # cleanup_worker_folders(kwargs.get('dest_folder'))

    return all_results

# Process 100 plans in batches of 20
all_plans = [f"{i:02d}" for i in range(1, 101)]
results = process_in_batches(all_plans, batch_size=20, num_workers=4, num_cores=4)
```

### 5. Memory Management

Monitor memory usage to avoid swapping:

```python
import psutil

def check_memory_for_workers(num_workers, mem_per_plan_gb=4):
    """Check if system has enough memory for planned workers."""
    available_gb = psutil.virtual_memory().available / (1024**3)
    required_gb = num_workers * mem_per_plan_gb

    if required_gb > available_gb * 0.8:  # 80% threshold
        suggested = int(available_gb * 0.8 / mem_per_plan_gb)
        print(f"Warning: {num_workers} workers need ~{required_gb:.1f} GB")
        print(f"Available: {available_gb:.1f} GB")
        print(f"Suggested max workers: {suggested}")
        return False
    return True

# Check before running
if check_memory_for_workers(num_workers=8, mem_per_plan_gb=4):
    results = RasCmdr.compute_parallel(...)
```

## Performance Benchmarking

### Measuring Throughput

```python
import time
from ras_commander import RasCmdr

def benchmark_config(plans, num_workers, num_cores, **kwargs):
    """Benchmark a specific configuration."""
    start = time.time()

    results = RasCmdr.compute_parallel(
        plan_number=plans,
        num_workers=num_workers,
        num_cores=num_cores,
        **kwargs
    )

    elapsed = time.time() - start
    successful = sum(1 for v in results.values() if v)

    return {
        "num_workers": num_workers,
        "num_cores": num_cores,
        "total_plans": len(plans),
        "successful": successful,
        "elapsed_seconds": elapsed,
        "plans_per_hour": len(plans) / elapsed * 3600,
        "avg_seconds_per_plan": elapsed / len(plans)
    }

# Compare configurations
configs = [
    {"num_workers": 2, "num_cores": 8},
    {"num_workers": 4, "num_cores": 4},
    {"num_workers": 8, "num_cores": 2},
]

for config in configs:
    result = benchmark_config(plans[:8], **config)
    print(f"Workers={config['num_workers']}, Cores={config['num_cores']}: "
          f"{result['plans_per_hour']:.1f} plans/hour")
```

## Common Bottlenecks

| Symptom | Cause | Solution |
|---------|-------|----------|
| Low CPU usage | Too few workers | Increase num_workers |
| High CPU but slow | Too many cores/plan | Decrease num_cores |
| Disk thrashing | HDD storage | Use SSD for workers |
| Memory pressure | Too many workers | Reduce num_workers |
| Network bottleneck | Remote workers | Check bandwidth |

## Summary Recommendations

1. **Start conservative**: Begin with fewer workers and scale up
2. **Monitor resources**: Watch CPU, memory, and disk I/O
3. **Benchmark your model**: Optimal config depends on model size
4. **Use SSDs**: Critical for worker folder creation
5. **Pre-process geometry**: Avoid redundant preprocessing
6. **Consider throughput over latency**: More parallel plans usually wins
