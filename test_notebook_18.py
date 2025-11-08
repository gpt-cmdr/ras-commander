"""
Test script to execute notebook 18_breach_results_extraction.ipynb cell by cell
and identify any errors.
"""

import sys
from pathlib import Path
import traceback

# Setup path
repo_root = Path(__file__).parent
sys.path.append(str(repo_root))

# Change to examples directory for correct relative paths
import os
os.chdir(repo_root / "examples")

print("="*80)
print("TESTING NOTEBOOK: 18_breach_results_extraction.ipynb")
print("="*80)
print(f"Working directory: {Path.cwd()}")
print()

# Track results
results = {
    'passed': [],
    'failed': [],
    'warnings': []
}

def test_cell(cell_num, cell_name, code):
    """Execute a cell and track results"""
    print(f"\n{'='*80}")
    print(f"CELL {cell_num}: {cell_name}")
    print(f"{'='*80}")
    try:
        exec(code, globals())
        results['passed'].append(f"Cell {cell_num}: {cell_name}")
        print(f"\n[PASS] Cell {cell_num} PASSED")
        return True
    except Exception as e:
        results['failed'].append(f"Cell {cell_num}: {cell_name}")
        print(f"\n[FAIL] Cell {cell_num} FAILED")
        print(f"Error: {type(e).__name__}: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        return False

# CELL 2: Setup and Imports
test_cell(2, "Setup and Imports", """
import sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import shutil

# Add ras-commander to path (if running from examples folder)
repo_root = Path.cwd().parent
if repo_root not in sys.path:
    sys.path.append(str(repo_root))

# Import ras-commander
from ras_commander import (
    init_ras_project,
    RasExamples,
    RasBreach,
    ras
)

print("Imports successful!")
print(f"Working directory: {Path.cwd()}")
""")

# CELL 4: Extract and Initialize Project
test_cell(4, "Extract and Initialize Project", """
# Extract BaldEagleCrkMulti2D example project
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")
print(f"Extracted project to: {project_path}")

# Initialize the project
init_ras_project(project_path, "6.6")
print(f"\\nInitialized project: {ras.prj_name}")
print(f"\\nAvailable plans:")
print(ras.plan_df[['plan_name', 'plan_num', 'plan_path']].to_string(index=False))
""")

# CELL 7: Identify Breach Structures
test_cell(7, "Identify Breach Structures", """
# List all SA/2D connection structures in HDF results
hdf_structures = RasBreach.list_breach_structures_hdf("02")
print("SA/2D Connection Structures in HDF:")
for struct in hdf_structures:
    print(f"  - {struct}")

# Get breach capability information
breach_info = RasBreach.get_breach_info("02")
print("\\nBreach Capability Information:")
print(breach_info.to_string(index=False))

# Get list of structures with breach capability
breach_structures = breach_info[breach_info['has_breach']]['structure'].tolist()
print(f"\\nStructures with breach capability: {breach_structures}")

# Select first breach structure for analysis
if breach_structures:
    target_structure = breach_structures[0]
    print(f"\\nTarget structure for analysis: {target_structure}")
else:
    print("\\nWARNING: No breach structures found! Cannot proceed with analysis.")
    target_structure = None
""")

# CELL 9: Extract Baseline Time Series
test_cell(9, "Extract Baseline Time Series", """
if target_structure:
    # Extract complete breach time series
    baseline_ts = RasBreach.get_breach_timeseries("02", target_structure)

    print(f"Baseline Time Series Extracted: {baseline_ts.shape}")
    print(f"\\nColumns: {list(baseline_ts.columns)}")
    print(f"\\nFirst few timesteps:")
    print(baseline_ts.head())

    # Get summary statistics
    baseline_summary = RasBreach.get_breach_summary("02", target_structure)
    print(f"\\nBaseline Summary Statistics:")
    print(baseline_summary.to_string(index=False))

    # Store baseline for later comparison
    scenarios = {
        'Baseline (Plan 02)': baseline_ts.copy()
    }
    summaries = {
        'Baseline (Plan 02)': baseline_summary.copy()
    }
else:
    print("Skipping baseline extraction - no breach structure available")
    scenarios = {}
    summaries = {}
""")

# CELL 11: Read Baseline Parameters
test_cell(11, "Read Baseline Parameters", """
if target_structure:
    # Read breach parameters from plan file
    baseline_params = RasBreach.read_breach_block("02", target_structure)

    print(f"Baseline Parameters for {target_structure}:")
    print("=" * 80)
    print(f"\\nActivation: {baseline_params['is_active']}")
    print(f"\\nKey Parameter Values:")
    for key in ['Breach Method', 'Breach Geom', 'Breach Start', 'Breach Progression']:
        if key in baseline_params['values']:
            print(f"  {key}: {baseline_params['values'][key]}")

    # Parse geometry values for modification
    geom_str = baseline_params['values'].get('Breach Geom', '')
    baseline_geom = [x.strip() for x in geom_str.split(',') if x.strip()]
    print(f"\\nBaseline Geometry (parsed): {baseline_geom}")
else:
    print("Skipping parameter reading - no breach structure available")
""")

# CELL 13: Visualize Baseline Results (skip - just plotting)
print("\n" + "="*80)
print("CELL 13: Visualize Baseline Results")
print("="*80)
print("SKIPPED - Visualization cell (would create plots)")
results['passed'].append("Cell 13: Visualize Baseline Results (skipped - plotting)")

# CELL 16: Helper Function
test_cell(16, "Helper Function: Clone Plan File", """
def clone_plan(source_plan_num, new_plan_num, new_plan_name=None):
    '''
    Clone a plan file to a new plan number.

    Parameters:
    -----------
    source_plan_num : str
        Source plan number (e.g., "02")
    new_plan_num : str
        New plan number (e.g., "03")
    new_plan_name : str, optional
        Name for the new plan

    Returns:
    --------
    Path
        Path to the cloned plan file
    '''
    # Get source plan path
    source_row = ras.plan_df[ras.plan_df['plan_num'] == source_plan_num]
    if source_row.empty:
        raise ValueError(f"Source plan {source_plan_num} not found")
    source_path = Path(source_row.iloc[0]['plan_path'])

    # Create new plan path
    new_path = source_path.parent / f"{source_path.stem.rsplit('.', 1)[0]}.p{new_plan_num}"

    # Copy file
    shutil.copy2(source_path, new_path)

    # Update plan name in the file if provided
    if new_plan_name:
        content = new_path.read_text()
        # Simple name replacement (may need adjustment based on file format)
        content = content.replace(
            f"Plan Title={source_row.iloc[0]['plan_name']}",
            f"Plan Title={new_plan_name}"
        )
        new_path.write_text(content)

    print(f"Cloned {source_plan_num} → {new_plan_num}")
    print(f"  Path: {new_path}")

    # Reinitialize project to pick up new plan
    init_ras_project(project_path, "6.6")

    return new_path

print("Helper function defined")
""")

# CELL 18: Scenario 1
test_cell(18, "Scenario 1: Increase Breach Width by 50%", """
if target_structure and len(baseline_geom) >= 2:
    # Clone plan
    plan_num_1 = "03"
    clone_plan("02", plan_num_1, "Scenario 1: +50% Width")

    # Modify breach width (assuming index 1 is width)
    try:
        new_geom = baseline_geom.copy()
        original_width = float(baseline_geom[1])
        new_width = original_width * 1.5
        new_geom[1] = new_width

        print(f"\\nModifying breach width:")
        print(f"  Original: {original_width} ft")
        print(f"  New: {new_width} ft (+50%)")

        # Update the plan
        RasBreach.update_breach_block(
            plan_num_1,
            target_structure,
            geom_values=new_geom
        )

        print(f"\\n✓ Scenario 1 plan created: {plan_num_1}")
        print(f"  Next step: Run HEC-RAS simulation for plan {plan_num_1}")
    except (ValueError, IndexError) as e:
        print(f"Could not parse geometry values: {e}")
else:
    print("Skipping Scenario 1 - insufficient baseline data")
""")

# CELL 20: Scenario 2
test_cell(20, "Scenario 2: Decrease Breach Formation Time by 50%", """
if target_structure and len(baseline_geom) >= 7:
    # Clone plan
    plan_num_2 = "04"
    clone_plan("02", plan_num_2, "Scenario 2: -50% Formation Time")

    # Modify formation time (assuming index 6 is formation time)
    try:
        new_geom = baseline_geom.copy()
        original_time = float(baseline_geom[6])
        new_time = original_time * 0.5
        new_geom[6] = new_time

        print(f"\\nModifying breach formation time:")
        print(f"  Original: {original_time} hrs")
        print(f"  New: {new_time} hrs (-50%)")

        # Update the plan
        RasBreach.update_breach_block(
            plan_num_2,
            target_structure,
            geom_values=new_geom
        )

        print(f"\\n✓ Scenario 2 plan created: {plan_num_2}")
        print(f"  Next step: Run HEC-RAS simulation for plan {plan_num_2}")
    except (ValueError, IndexError) as e:
        print(f"Could not parse geometry values: {e}")
else:
    print("Skipping Scenario 2 - insufficient baseline data")
""")

# CELL 22: Scenario 3
test_cell(22, "Scenario 3: Change Breach Method", """
if target_structure:
    # Clone plan
    plan_num_3 = "05"
    clone_plan("02", plan_num_3, "Scenario 3: Different Method")

    # Get current method
    current_method = int(baseline_params['values'].get('Breach Method', '0').strip())
    new_method = 1 if current_method == 0 else 0  # Toggle method

    print(f"\\nModifying breach method:")
    print(f"  Original: {current_method}")
    print(f"  New: {new_method}")

    # Update the plan
    RasBreach.update_breach_block(
        plan_num_3,
        target_structure,
        method=new_method
    )

    print(f"\\n✓ Scenario 3 plan created: {plan_num_3}")
    print(f"  Next step: Run HEC-RAS simulation for plan {plan_num_3}")
else:
    print("Skipping Scenario 3 - no breach structure available")
""")

# Remaining cells are result extraction and plotting - skip for now
print("\n" + "="*80)
print("REMAINING CELLS: Results extraction and visualization")
print("="*80)
print("SKIPPED - Cells 24-37 require HEC-RAS runs and are primarily visualization")
results['warnings'].append("Cells 24-37: Skipped (require HEC-RAS results)")

# SUMMARY
print("\n\n" + "="*80)
print("TEST SUMMARY")
print("="*80)

print(f"\n[PASS] PASSED ({len(results['passed'])} cells):")
for item in results['passed']:
    print(f"  {item}")

if results['failed']:
    print(f"\n[FAIL] FAILED ({len(results['failed'])} cells):")
    for item in results['failed']:
        print(f"  {item}")
else:
    print(f"\n[FAIL] FAILED (0 cells)")

if results['warnings']:
    print(f"\n[WARN] WARNINGS/SKIPPED ({len(results['warnings'])} items):")
    for item in results['warnings']:
        print(f"  {item}")

print("\n" + "="*80)
if results['failed']:
    print("RESULT: ERRORS FOUND")
    sys.exit(1)
else:
    print("RESULT: ALL TESTED CELLS PASSED")
    sys.exit(0)
