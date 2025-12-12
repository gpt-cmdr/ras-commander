"""
Parallel HEC-RAS Plan Execution Example

Demonstrates parallel execution patterns using compute_parallel().
"""

from pathlib import Path
import sys
import time

# Import flexibility pattern for development
try:
    from ras_commander import init_ras_project, RasCmdr, RasExamples
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasCmdr, RasExamples


def example_1_basic_parallel():
    """Example 1: Basic parallel execution of 3 plans."""
    print("=" * 80)
    print("Example 1: Basic Parallel Execution")
    print("=" * 80)

    # Extract example project with multiple plans
    project_path = RasExamples.extract_project("Bald Eagle Creek")
    print(f"\nProject extracted to: {project_path}")

    # Initialize project
    init_ras_project(project_path, "6.5")
    print("Project initialized")

    # Get available plans
    from ras_commander import ras
    print(f"\nAvailable plans:")
    print(ras.plan_df[['plan_number', 'plan_title']])

    # Execute 3 plans in parallel
    plans = ["01", "02", "03"]
    print(f"\nExecuting {len(plans)} plans in parallel: {plans}")
    print("(Each plan will run in a separate worker folder)")

    start_time = time.time()

    results = RasCmdr.compute_parallel(plans_to_run=plans)

    duration = time.time() - start_time

    # Report results
    print(f"\nParallel execution completed in {duration:.1f} seconds")
    print("\nResults:")
    for plan, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"  Plan {plan}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'✓ All plans passed' if all_passed else '✗ Some plans failed'}")
    print()


def example_2_parallel_with_cores():
    """Example 2: Parallel execution with specific core count."""
    print("=" * 80)
    print("Example 2: Parallel Execution with Core Count")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Bald Eagle Creek")
    init_ras_project(project_path, "6.5")

    # Execute with specific core count per plan
    plans = ["01", "02"]
    print(f"\nExecuting {len(plans)} plans in parallel")
    print("Each plan will use 4 cores")

    start_time = time.time()

    results = RasCmdr.compute_parallel(
        plans_to_run=plans,
        num_cores=4  # Each plan uses 4 cores
    )

    duration = time.time() - start_time

    print(f"\nCompleted in {duration:.1f} seconds")
    for plan, success in results.items():
        status = "✓" if success else "✗"
        print(f"  {status} Plan {plan}")

    print()


def example_3_parallel_with_monitoring():
    """Example 3: Parallel execution with real-time monitoring."""
    print("=" * 80)
    print("Example 3: Parallel Execution with Monitoring")
    print("=" * 80)

    # Import callback
    from ras_commander.callbacks import ConsoleCallback

    # Extract example project
    project_path = RasExamples.extract_project("Bald Eagle Creek")
    init_ras_project(project_path, "6.5")

    # Create thread-safe callback
    callback = ConsoleCallback()  # Already thread-safe

    plans = ["01", "02"]
    print(f"\nExecuting {len(plans)} plans with real-time monitoring")
    print("(Watch for concurrent output from multiple plans)")

    results = RasCmdr.compute_parallel(
        plans_to_run=plans,
        stream_callback=callback
    )

    # Summary
    print("\n" + "=" * 80)
    print("PARALLEL EXECUTION SUMMARY")
    print("=" * 80)
    for plan, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"Plan {plan}: {status}")

    print()


def example_4_parallel_with_file_logging():
    """Example 4: Parallel execution with file logging."""
    print("=" * 80)
    print("Example 4: Parallel Execution with File Logging")
    print("=" * 80)

    # Import file logger callback
    from ras_commander.callbacks import FileLoggerCallback

    # Extract example project
    project_path = RasExamples.extract_project("Bald Eagle Creek")
    init_ras_project(project_path, "6.5")

    # Create file logger
    log_dir = Path(project_path).parent / "parallel_logs"
    callback = FileLoggerCallback(output_dir=log_dir)

    plans = ["01", "02", "03"]
    print(f"\nExecuting {len(plans)} plans with file logging")
    print(f"Logs will be written to: {log_dir}")

    results = RasCmdr.compute_parallel(
        plans_to_run=plans,
        stream_callback=callback
    )

    # Report results
    print("\nExecution complete. Log files created:")
    for plan in plans:
        log_file = log_dir / f"plan_{plan}_execution.log"
        if log_file.exists():
            size_kb = log_file.stat().st_size / 1024
            print(f"  ✓ plan_{plan}_execution.log ({size_kb:.1f} KB)")

    print()


def example_5_sequential_test_mode():
    """Example 5: Sequential test mode for debugging."""
    print("=" * 80)
    print("Example 5: Sequential Test Mode")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Bald Eagle Creek")
    init_ras_project(project_path, "6.5")

    # Execute plans sequentially (not in parallel)
    plans = ["01", "02"]
    print(f"\nExecuting {len(plans)} plans SEQUENTIALLY in test mode")
    print("(Useful for debugging - runs one at a time)")

    from ras_commander.callbacks import ConsoleCallback
    callback = ConsoleCallback(verbose=True)

    start_time = time.time()

    results = RasCmdr.compute_test_mode(
        plans_to_run=plans,
        stream_callback=callback
    )

    duration = time.time() - start_time

    print(f"\nSequential execution completed in {duration:.1f} seconds")
    for plan, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"  Plan {plan}: {status}")

    print()


def example_6_parallel_vs_sequential_comparison():
    """Example 6: Compare parallel vs sequential execution times."""
    print("=" * 80)
    print("Example 6: Parallel vs Sequential Comparison")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Bald Eagle Creek")
    init_ras_project(project_path, "6.5")

    plans = ["01", "02"]

    # Sequential execution
    print(f"\n1. SEQUENTIAL EXECUTION ({len(plans)} plans)")
    print("   Running one plan at a time...")

    start_seq = time.time()
    results_seq = RasCmdr.compute_test_mode(plans_to_run=plans)
    duration_seq = time.time() - start_seq

    print(f"   Completed in {duration_seq:.1f} seconds")

    # Parallel execution
    print(f"\n2. PARALLEL EXECUTION ({len(plans)} plans)")
    print("   Running all plans simultaneously...")

    start_par = time.time()
    results_par = RasCmdr.compute_parallel(plans_to_run=plans)
    duration_par = time.time() - start_par

    print(f"   Completed in {duration_par:.1f} seconds")

    # Comparison
    print("\n" + "=" * 80)
    print("PERFORMANCE COMPARISON")
    print("=" * 80)
    print(f"Sequential: {duration_seq:.1f}s")
    print(f"Parallel:   {duration_par:.1f}s")

    if duration_par < duration_seq:
        speedup = duration_seq / duration_par
        print(f"\nSpeedup: {speedup:.2f}x faster with parallel execution")
    else:
        print("\nNote: Parallel overhead may exceed benefits for small/fast models")

    print()


def example_7_handle_failures():
    """Example 7: Handle failures in parallel execution."""
    print("=" * 80)
    print("Example 7: Handling Failures in Parallel Execution")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Bald Eagle Creek")
    init_ras_project(project_path, "6.5")

    plans = ["01", "02", "03"]
    print(f"\nExecuting {len(plans)} plans with error handling...")

    results = RasCmdr.compute_parallel(
        plans_to_run=plans,
        num_cores=4
    )

    # Analyze results
    successful = [plan for plan, success in results.items() if success]
    failed = [plan for plan, success in results.items() if not success]

    print("\n" + "=" * 80)
    print("EXECUTION RESULTS")
    print("=" * 80)

    if successful:
        print(f"\n✓ Successful plans ({len(successful)}):")
        for plan in successful:
            print(f"  - Plan {plan}")

    if failed:
        print(f"\n✗ Failed plans ({len(failed)}):")
        for plan in failed:
            print(f"  - Plan {plan}")

            # Could investigate failures here
            from ras_commander import ras
            hdf_path = Path(ras.project_folder) / f"{ras.project_name}.p{plan}.hdf"

            if hdf_path.exists():
                print(f"    HDF exists - check compute messages for errors")
            else:
                print(f"    HDF not created - execution failed completely")

    else:
        print("\n✓ All plans executed successfully!")

    # Retry failed plans if any
    if failed:
        print(f"\nRetrying {len(failed)} failed plans sequentially for debugging...")

        for plan in failed:
            print(f"\n  Retrying plan {plan}...")
            success = RasCmdr.compute_plan(
                plan,
                verify=True,
                dest_folder=f"retry_{plan}",
                overwrite_dest=True
            )

            if success:
                print(f"    ✓ Plan {plan} succeeded on retry")
            else:
                print(f"    ✗ Plan {plan} failed again")

    print()


def main():
    """Run all examples."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 18 + "PARALLEL HEC-RAS PLAN EXECUTION EXAMPLES" + " " * 19 + "║")
    print("╚" + "=" * 78 + "╝")
    print()

    examples = [
        ("Basic Parallel", example_1_basic_parallel),
        ("With Core Count", example_2_parallel_with_cores),
        ("With Monitoring", example_3_parallel_with_monitoring),
        ("With File Logging", example_4_parallel_with_file_logging),
        ("Sequential Test Mode", example_5_sequential_test_mode),
        ("Parallel vs Sequential", example_6_parallel_vs_sequential_comparison),
        ("Handle Failures", example_7_handle_failures),
    ]

    print("Available examples:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")

    print("\nRunning all examples...\n")

    for name, example_func in examples:
        try:
            example_func()
        except Exception as e:
            print(f"✗ Example '{name}' failed with error: {e}")
            import traceback
            traceback.print_exc()
            print()

    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 28 + "EXAMPLES COMPLETE" + " " * 33 + "║")
    print("╚" + "=" * 78 + "╝")
    print()


if __name__ == "__main__":
    main()
