"""
Docker Worker Example

Demonstrates Docker-based remote execution of HEC-RAS plans in Linux containers.
"""

from pathlib import Path
from ras_commander import (
    init_ras_project,
    init_ras_worker,
    compute_parallel_remote,
    RasExamples
)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Docker configuration
DOCKER_IMAGE = "hecras:6.6"  # Docker image name

# Local Docker execution
USE_LOCAL_DOCKER = True

# Remote Docker execution (via SSH)
USE_REMOTE_DOCKER = False
REMOTE_DOCKER_HOST = "ssh://user@192.168.1.100"
SSH_KEY_PATH = "~/.ssh/docker_worker"
REMOTE_SHARE = r"\\192.168.1.100\DockerShare"
REMOTE_STAGING = r"C:\DockerShare"

# Worker capacity
CORES_TOTAL = 8
CORES_PER_PLAN = 4

# Container limits
CPU_LIMIT = "4"      # 4 CPU cores max per container
MEMORY_LIMIT = "8g"  # 8 GB RAM max per container

# Plans to execute
PLANS_TO_RUN = ["01", "02", "03", "04"]

# =============================================================================
# STEP 1: SETUP PROJECT
# =============================================================================

print("=" * 80)
print("Docker Remote Execution Example")
print("=" * 80)

# Extract example project
print("\n1. Extracting example project...")
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")
print(f"   Project: {project_path}")

# Initialize project
print("\n2. Initializing HEC-RAS project...")
ras = init_ras_project(project_path, "6.6")
print(f"   Project name: {ras.project_name}")
print(f"   Plans available: {list(ras.plan_df['plan_number'])}")

# =============================================================================
# STEP 2: INITIALIZE WORKER
# =============================================================================

print("\n3. Initializing Docker worker...")

if USE_LOCAL_DOCKER:
    print("   Mode: Local Docker")

    worker = init_ras_worker(
        "docker",
        docker_image=DOCKER_IMAGE,
        cores_total=CORES_TOTAL,
        cores_per_plan=CORES_PER_PLAN,
        cpu_limit=CPU_LIMIT,
        memory_limit=MEMORY_LIMIT,
        preprocess_on_host=True,
        queue_priority=0
    )

    print(f"   Worker ID: {worker.worker_id}")
    print(f"   Image: {worker.docker_image}")
    print(f"   Docker host: Local")

elif USE_REMOTE_DOCKER:
    print("   Mode: Remote Docker (SSH)")

    worker = init_ras_worker(
        "docker",
        docker_image=DOCKER_IMAGE,
        docker_host=REMOTE_DOCKER_HOST,
        ssh_key_path=SSH_KEY_PATH,
        share_path=REMOTE_SHARE,
        remote_staging_path=REMOTE_STAGING,
        cores_total=CORES_TOTAL,
        cores_per_plan=CORES_PER_PLAN,
        cpu_limit=CPU_LIMIT,
        memory_limit=MEMORY_LIMIT,
        preprocess_on_host=True,
        queue_priority=0
    )

    print(f"   Worker ID: {worker.worker_id}")
    print(f"   Image: {worker.docker_image}")
    print(f"   Docker host: {worker.docker_host}")
    print(f"   SSH key: {worker.ssh_key_path}")
    print(f"   Share: {worker.share_path}")

else:
    raise ValueError("Set USE_LOCAL_DOCKER=True or USE_REMOTE_DOCKER=True")

print(f"   CPU limit: {worker.cpu_limit}")
print(f"   Memory limit: {worker.memory_limit}")
print(f"   Parallel capacity: {worker.max_parallel_plans} containers")

# =============================================================================
# STEP 3: EXECUTE PLANS IN CONTAINERS
# =============================================================================

print(f"\n4. Executing {len(PLANS_TO_RUN)} plans in Docker containers...")
print(f"   Plans: {PLANS_TO_RUN}")
print(f"   Workflow: Windows preprocessing → Linux container execution")

import time
start_time = time.time()

results = compute_parallel_remote(
    plan_numbers=PLANS_TO_RUN,
    workers=[worker],
    num_cores=CORES_PER_PLAN,
    autoclean=True  # Clean up temp folders and containers
)

elapsed_time = time.time() - start_time

# =============================================================================
# STEP 4: PROCESS RESULTS
# =============================================================================

print("\n5. Processing results...")
print("=" * 80)

success_count = 0
fail_count = 0

for plan_num, result in results.items():
    print(f"\nPlan {plan_num}:")
    print(f"  Worker: {result.worker_id}")
    print(f"  Time: {result.execution_time:.1f}s")

    if result.success:
        print(f"  Status: SUCCESS")
        print(f"  HDF: {result.hdf_path}")
        success_count += 1

        # Verify HDF
        from ras_commander import HdfResultsPlan
        try:
            msgs = HdfResultsPlan.get_compute_messages(result.hdf_path)
            if "completed successfully" in msgs.lower():
                print(f"  Verification: HDF valid")

            # Get volume accounting
            vol = HdfResultsPlan.get_volume_accounting(result.hdf_path)
            if vol is not None and len(vol) > 0:
                error_pct = vol['Error Percent'].iloc[0]
                print(f"  Volume error: {error_pct:.4f}%")
        except Exception as e:
            print(f"  Verification: Could not read HDF - {e}")
    else:
        print(f"  Status: FAILED")
        print(f"  Error: {result.error_message}")
        fail_count += 1

# =============================================================================
# STEP 5: SUMMARY
# =============================================================================

print("\n" + "=" * 80)
print("EXECUTION SUMMARY")
print("=" * 80)
print(f"Total plans: {len(results)}")
print(f"Successful: {success_count}")
print(f"Failed: {fail_count}")
print(f"Total time: {elapsed_time:.1f}s ({elapsed_time/60:.1f} minutes)")
print(f"Average time per plan: {elapsed_time/len(results):.1f}s")

if success_count == len(results):
    print("\n✓ All plans executed successfully in Docker containers!")
else:
    print(f"\n⚠ {fail_count} plan(s) failed. Check error messages above.")

print("\nResults location:")
print(f"  {project_path}")

# =============================================================================
# OPTIONAL: MIXED WORKER POOL (LOCAL + PSEXEC + DOCKER)
# =============================================================================

print("\n" + "=" * 80)
print("BONUS: Mixed Local + PsExec + Docker Execution")
print("=" * 80)

# Local worker (priority 0 - execute first)
local_worker = init_ras_worker(
    "local",
    worker_folder=r"C:\RasRemote",
    cores_total=8,
    cores_per_plan=2,
    queue_priority=0
)

# PsExec worker (priority 1 - execute second)
# NOTE: Configure REMOTE_* variables at top of file
try:
    psexec_worker = init_ras_worker(
        "psexec",
        hostname="192.168.1.100",
        share_path=r"\\192.168.1.100\RasRemote",
        session_id=2,
        cores_total=16,
        cores_per_plan=4,
        queue_priority=1
    )
    psexec_available = True
except Exception as e:
    print(f"   PsExec worker not available: {e}")
    psexec_available = False

# Docker worker (priority 2 - execute third, overflow capacity)
docker_worker = init_ras_worker(
    "docker",
    docker_image=DOCKER_IMAGE,
    cores_total=CORES_TOTAL,
    cores_per_plan=CORES_PER_PLAN,
    queue_priority=2
)

# Build worker pool
workers = [local_worker]
if psexec_available:
    workers.append(psexec_worker)
workers.append(docker_worker)

print(f"\nWorker pool:")
print(f"  Local: {local_worker.max_parallel_plans} slots (priority 0)")
if psexec_available:
    print(f"  PsExec: {psexec_worker.max_parallel_plans} slots (priority 1)")
print(f"  Docker: {docker_worker.max_parallel_plans} slots (priority 2)")

total_capacity = sum(w.max_parallel_plans for w in workers)
print(f"  Total capacity: {total_capacity} plans")

# Execute with mixed pool
print(f"\nExecuting {len(PLANS_TO_RUN)} plans across mixed worker pool...")
print("Execution order: Local first, then PsExec, then Docker (overflow)")

start_time = time.time()

mixed_results = compute_parallel_remote(
    plan_numbers=PLANS_TO_RUN,
    workers=workers,
    num_cores=4
)

elapsed_time = time.time() - start_time

print(f"\nMixed execution completed in {elapsed_time:.1f}s")

# Show which worker executed each plan
worker_map = {
    local_worker.worker_id: "LOCAL",
    docker_worker.worker_id: "DOCKER"
}
if psexec_available:
    worker_map[psexec_worker.worker_id] = "PSEXEC"

for plan_num, result in mixed_results.items():
    if result.success:
        worker_type = worker_map.get(result.worker_id, "UNKNOWN")
        print(f"  Plan {plan_num}: {worker_type} ({result.execution_time:.1f}s)")

print("\n" + "=" * 80)
print("Example complete!")
print("=" * 80)
print("\nKey takeaways:")
print("  • Docker workers provide isolated execution environment")
print("  • Two-step workflow: Windows preprocessing + Linux execution")
print("  • Mix Docker with local/PsExec for flexible capacity")
print("  • Queue priority controls execution order (0=local, 1=remote, 2=cloud)")
