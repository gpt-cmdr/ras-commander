"""
Basic HEC-RAS Plan Execution Example

Demonstrates simple plan execution patterns using RasCmdr.
"""

from pathlib import Path
import sys

# Import flexibility pattern for development
try:
    from ras_commander import init_ras_project, RasCmdr, RasExamples
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasCmdr, RasExamples


def example_1_basic_execution():
    """Example 1: Basic plan execution in original project."""
    print("=" * 80)
    print("Example 1: Basic Plan Execution")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Muncie")
    print(f"\nProject extracted to: {project_path}")

    # Initialize project
    init_ras_project(project_path, "6.5")
    print("Project initialized")

    # Execute plan (modifies original project in-place)
    print("\nExecuting plan 01...")
    success = RasCmdr.compute_plan("01")

    if success:
        print("✓ Plan executed successfully")
    else:
        print("✗ Plan execution failed")

    print()


def example_2_destination_folder():
    """Example 2: Execute in separate destination folder."""
    print("=" * 80)
    print("Example 2: Execution with Destination Folder")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Muncie")
    init_ras_project(project_path, "6.5")

    # Execute in separate folder (preserves original)
    dest = "computation_output"
    print(f"\nExecuting plan 01 in destination folder: {dest}")

    success = RasCmdr.compute_plan(
        "01",
        dest_folder=dest,
        overwrite_dest=True  # Allow re-running
    )

    if success:
        print(f"✓ Plan executed successfully")
        print(f"  Results in: {Path(project_path).parent / dest}")
        print("  Original project unchanged")
    else:
        print("✗ Plan execution failed")

    print()


def example_3_performance_options():
    """Example 3: Execute with performance options."""
    print("=" * 80)
    print("Example 3: Execution with Performance Options")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Muncie")
    init_ras_project(project_path, "6.5")

    # Execute with specific core count
    print("\nExecuting plan 01 with 4 cores...")

    success = RasCmdr.compute_plan(
        "01",
        num_cores=4,           # Use 4 CPU cores
        clear_geompre=True,    # Force geometry reprocessing
        verify=True            # Verify successful completion
    )

    if success:
        print("✓ Plan executed and verified successfully")
    else:
        print("✗ Plan execution or verification failed")

    print()


def example_4_monitoring():
    """Example 4: Execute with real-time monitoring."""
    print("=" * 80)
    print("Example 4: Execution with Real-Time Monitoring")
    print("=" * 80)

    # Import callback
    from ras_commander.callbacks import ConsoleCallback

    # Extract example project
    project_path = RasExamples.extract_project("Muncie")
    init_ras_project(project_path, "6.5")

    # Execute with console monitoring
    print("\nExecuting plan 01 with console monitoring...")

    callback = ConsoleCallback(verbose=True)  # Show all messages

    success = RasCmdr.compute_plan(
        "01",
        stream_callback=callback
    )

    if success:
        print("\n✓ Plan executed successfully")
    else:
        print("\n✗ Plan execution failed")

    print()


def example_5_error_handling():
    """Example 5: Execute with error handling."""
    print("=" * 80)
    print("Example 5: Execution with Error Handling")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Muncie")
    init_ras_project(project_path, "6.5")

    try:
        print("\nExecuting plan 01 with verification...")

        success = RasCmdr.compute_plan(
            "01",
            verify=True,
            dest_folder="verified_run",
            overwrite_dest=True
        )

        if success:
            print("✓ Execution completed and verified")

            # Extract and validate results
            from ras_commander.hdf import HdfResultsPlan

            hdf_path = Path(project_path).parent / "verified_run" / "Muncie.p01.hdf"
            hdf = HdfResultsPlan(hdf_path)

            # Get compute messages
            messages = hdf.get_compute_messages()
            print(f"\nCompute messages preview:")
            print(messages[:200] + "..." if len(messages) > 200 else messages)

        else:
            print("✗ Execution failed verification")

    except Exception as e:
        print(f"✗ Execution error: {e}")
        import traceback
        traceback.print_exc()

    print()


def example_6_batch_scenarios():
    """Example 6: Batch processing multiple scenarios."""
    print("=" * 80)
    print("Example 6: Batch Scenario Processing")
    print("=" * 80)

    # Extract example project
    project_path = RasExamples.extract_project("Muncie")
    init_ras_project(project_path, "6.5")

    # Define scenarios
    scenarios = {
        "baseline": {"plan": "01", "dest": "scenario_baseline"},
        "modified": {"plan": "01", "dest": "scenario_modified"},  # Same plan, different setup
    }

    print(f"\nProcessing {len(scenarios)} scenarios...")

    results = {}
    for name, config in scenarios.items():
        print(f"\n--- Running scenario: {name} ---")

        success = RasCmdr.compute_plan(
            config["plan"],
            dest_folder=config["dest"],
            overwrite_dest=True,
            verify=True
        )

        results[name] = success
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"{name}: {status}")

    # Summary
    print("\n" + "=" * 80)
    print("BATCH PROCESSING SUMMARY")
    print("=" * 80)
    for name, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"{name:20s}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'✓ All scenarios passed' if all_passed else '✗ Some scenarios failed'}")
    print()


def main():
    """Run all examples."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "HEC-RAS PLAN EXECUTION EXAMPLES" + " " * 26 + "║")
    print("╚" + "=" * 78 + "╝")
    print()

    examples = [
        ("Basic Execution", example_1_basic_execution),
        ("Destination Folder", example_2_destination_folder),
        ("Performance Options", example_3_performance_options),
        ("Real-Time Monitoring", example_4_monitoring),
        ("Error Handling", example_5_error_handling),
        ("Batch Scenarios", example_6_batch_scenarios),
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
