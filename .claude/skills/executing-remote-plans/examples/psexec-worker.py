"""
PsExec Worker Example

Demonstrates PsExec-based remote execution of HEC-RAS plans on Windows machines.
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

# Remote machine settings
REMOTE_HOSTNAME = "192.168.1.100"
REMOTE_SHARE = r"\\192.168.1.100\RasRemote"
REMOTE_FOLDER = r"C:\RasRemote"  # Local path on remote machine

# Credentials (OPTIONAL - use Windows auth if possible)
CREDENTIALS = {
    "username": "DOMAIN\\user",
    "password": "password"
}

# Session ID - query with: query session /server:192.168.1.100
SESSION_ID = 2  # Typical for single-user workstation

# Worker capacity
CORES_TOTAL = 16
CORES_PER_PLAN = 4

# Plans to execute
PLANS_TO_RUN = ["01", "02", "03", "04"]

# =============================================================================
# STEP 1: SETUP PROJECT
# =============================================================================

print("=" * 80)
print("PsExec Remote Execution Example")
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

print("\n3. Initializing PsExec worker...")

# Create worker
worker = init_ras_worker(
    "psexec",
    hostname=REMOTE_HOSTNAME,
    share_path=REMOTE_SHARE,
    worker_folder=REMOTE_FOLDER,
    session_id=SESSION_ID,
    credentials=CREDENTIALS if CREDENTIALS["username"] else {},  # Omit if empty
    cores_total=CORES_TOTAL,
    cores_per_plan=CORES_PER_PLAN,
    process_priority="low",  # Minimize impact on remote user
    queue_priority=0
)

print(f"   Worker ID: {worker.worker_id}")
print(f"   Hostname: {worker.hostname}")
print(f"   Share: {worker.share_path}")
print(f"   Folder: {worker.worker_folder}")
print(f"   Session: {worker.session_id}")
print(f"   Parallel capacity: {worker.max_parallel_plans} plans")

# =============================================================================
# STEP 3: EXECUTE PLANS REMOTELY
# =============================================================================

print(f"\n4. Executing {len(PLANS_TO_RUN)} plans on remote worker...")
print(f"   Plans: {PLANS_TO_RUN}")

import time
start_time = time.time()

results = compute_parallel_remote(
    plan_numbers=PLANS_TO_RUN,
    workers=[worker],
    num_cores=CORES_PER_PLAN,
    autoclean=True  # Clean up temp folders
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
    print("\n✓ All plans executed successfully!")
else:
    print(f"\n⚠ {fail_count} plan(s) failed. Check error messages above.")

print("\nResults location:")
print(f"  {project_path}")

# =============================================================================
# OPTIONAL: MIXED LOCAL + REMOTE EXECUTION
# =============================================================================

print("\n" + "=" * 80)
print("BONUS: Mixed Local + Remote Execution")
print("=" * 80)

# Create local worker
local_worker = init_ras_worker(
    "local",
    worker_folder=r"C:\RasRemote",
    cores_total=8,
    cores_per_plan=2,
    queue_priority=0  # Execute local first
)

# Remote worker with lower priority
remote_worker = init_ras_worker(
    "psexec",
    hostname=REMOTE_HOSTNAME,
    share_path=REMOTE_SHARE,
    session_id=SESSION_ID,
    credentials=CREDENTIALS if CREDENTIALS["username"] else {},
    cores_total=CORES_TOTAL,
    cores_per_plan=CORES_PER_PLAN,
    queue_priority=1  # Execute remote second (overflow)
)

print(f"\nLocal worker: {local_worker.max_parallel_plans} slots (priority 0)")
print(f"Remote worker: {remote_worker.max_parallel_plans} slots (priority 1)")
print(f"Total capacity: {local_worker.max_parallel_plans + remote_worker.max_parallel_plans} plans")

# Execute with mixed pool
print(f"\nExecuting {len(PLANS_TO_RUN)} plans across local + remote...")

start_time = time.time()

mixed_results = compute_parallel_remote(
    plan_numbers=PLANS_TO_RUN,
    workers=[local_worker, remote_worker],
    num_cores=4
)

elapsed_time = time.time() - start_time

print(f"\nMixed execution completed in {elapsed_time:.1f}s")

# Show which worker executed each plan
for plan_num, result in mixed_results.items():
    if result.success:
        worker_type = "LOCAL" if result.worker_id == local_worker.worker_id else "REMOTE"
        print(f"  Plan {plan_num}: {worker_type} ({result.execution_time:.1f}s)")

print("\n" + "=" * 80)
print("Example complete!")
print("=" * 80)
