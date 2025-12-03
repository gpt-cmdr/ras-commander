#!/usr/bin/env python
"""
Test Docker Worker on Remote Machine via SSH

This script tests the Docker worker executing HEC-RAS on 192.168.3.8
using Docker over SSH.
"""
import os
import sys
import time
from pathlib import Path

# Add parent directory to path for local development
current_file = Path(os.getcwd()).resolve()
rascmdr_directory = current_file.parent
if str(rascmdr_directory) not in sys.path:
    sys.path.insert(0, str(rascmdr_directory))

print("Loading ras-commander...")
from ras_commander import init_ras_project, RasExamples, ras
from ras_commander.remote import init_ras_worker, compute_parallel_remote, load_workers_from_json

print("=" * 70)
print("DOCKER WORKER TEST - Remote Execution via SSH")
print("=" * 70)

# Extract Muncie example project
print("\n1. Extracting Muncie example project...")
muncie_path = RasExamples.extract_project("Muncie")
print(f"   Project extracted to: {muncie_path}")

# Initialize project
print("\n2. Initializing project...")
init_ras_project(muncie_path, "6.6")
print(f"   Project: {ras.project_name}")
print(f"   Plans: {list(ras.plan_df.index)}")

# Load workers from JSON
print("\n3. Loading workers from RemoteWorkers.json...")
workers = load_workers_from_json("RemoteWorkers.json")

# Find Docker workers
docker_workers = [w for w in workers if w.worker_type == "docker"]
print(f"   Found {len(docker_workers)} Docker worker(s):")
for w in docker_workers:
    print(f"   - {w.worker_id}")
    print(f"     Image: {w.docker_image}")
    print(f"     Host: {w.docker_host}")
    print(f"     Share: {w.share_path}")
    print(f"     Remote Path: {w.remote_staging_path}")

if not docker_workers:
    print("\nERROR: No Docker workers found in RemoteWorkers.json")
    print("Make sure 'CLB-04 Docker 6.6' is enabled.")
    sys.exit(1)

# Use first Docker worker
worker = docker_workers[0]
print(f"\n4. Using worker: {worker.worker_id}")

# Execute Plan 01
print("\n5. Executing Plan 01 on Docker worker...")
print("   This will:")
print("   - Copy project to remote share")
print("   - Run HEC-RAS in Docker container via SSH")
print("   - Copy results back")
print()

start_time = time.time()

try:
    results = compute_parallel_remote(
        plan_numbers="01",
        workers=[worker],
        num_cores=4,
        autoclean=False  # Keep files for debugging
    )

    elapsed = time.time() - start_time

    print(f"\n6. Execution complete in {elapsed:.1f} seconds")
    print("\nResults:")
    for plan_num, result in results.items():
        if result.success:
            print(f"   Plan {plan_num}: SUCCESS")
            print(f"   HDF Path: {result.hdf_path}")
            print(f"   Execution Time: {result.execution_time:.1f}s")
        else:
            print(f"   Plan {plan_num}: FAILED")
            print(f"   Error: {result.error_message}")

except Exception as e:
    elapsed = time.time() - start_time
    print(f"\nERROR after {elapsed:.1f}s: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)
