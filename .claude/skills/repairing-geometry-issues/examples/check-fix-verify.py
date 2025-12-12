"""
Complete Check → Fix → Verify Workflow

This example demonstrates the full geometry quality workflow:
1. Check for issues using RasCheck
2. Fix detected issues using RasFixit
3. Verify fixes were successful

Use this workflow for:
- Pre-submission FEMA/USACE validation
- Automated geometry repair in production workflows
- Quality assurance before peer review
"""

from pathlib import Path
from ras_commander import (
    RasExamples, init_ras_project, ras,
    RasCmdr, RasFixit
)
from ras_commander.check import RasCheck, ReportMetadata

# ==============================================================================
# Step 1: Setup Project
# ==============================================================================

# Extract example project with known geometry issues
project_path = RasExamples.extract_project("Muncie")
print(f"Extracted project: {project_path}")

# Initialize project
init_ras_project(project_path, "6.6")
print(f"Initialized: {ras.project_name}")

# ==============================================================================
# Step 2: Run Plan (if needed)
# ==============================================================================

plan_number = "01"

# Execute plan to generate HDF results
print(f"\nRunning Plan {plan_number}...")
success = RasCmdr.compute_plan(plan_number, skip_existing=True)

if not success:
    print("ERROR: Plan execution failed")
    exit(1)

print(f"Plan {plan_number} executed successfully")

# ==============================================================================
# Step 3: Initial Quality Check
# ==============================================================================

print("\n" + "="*80)
print("STEP 1: CHECK (Initial Validation)")
print("="*80)

# Run all quality checks
initial_results = RasCheck.run_all(plan_number)

print(f"\nInitial Validation Results:")
print(f"  Total Messages: {len(initial_results.messages)}")
print(f"  Errors: {initial_results.get_error_count()}")
print(f"  Warnings: {initial_results.get_warning_count()}")

# Generate initial report
initial_report_path = project_path / "ras_check_initial.html"
metadata = ReportMetadata(
    project_name=ras.project_name,
    plan_number=plan_number,
    checked_by="Automated QA Workflow"
)
initial_results.to_html(initial_report_path, metadata=metadata)
print(f"\nInitial report: {initial_report_path}")

# ==============================================================================
# Step 4: Identify Geometry Issues
# ==============================================================================

# Get geometry file path
plan_row = ras.plan_df[ras.plan_df['plan_number'] == plan_number].iloc[0]
geom_path = Path(plan_row['Geom Path'])

print(f"\nGeometry file: {geom_path}")

# Check for blocked obstruction issues
print("\nScanning for blocked obstruction overlaps...")
obstruction_results = RasFixit.detect_obstruction_overlaps(geom_path)

print(f"  Cross sections checked: {obstruction_results.total_xs_checked}")
print(f"  Cross sections with overlaps: {obstruction_results.total_xs_fixed}")

if obstruction_results.total_xs_fixed > 0:
    print("\nAffected cross sections:")
    for msg in obstruction_results.messages[:10]:  # First 10
        print(f"  RS {msg.station}: {msg.original_count} → {msg.fixed_count}")

# ==============================================================================
# Step 5: Apply Automated Fixes
# ==============================================================================

if obstruction_results.total_xs_fixed > 0:
    print("\n" + "="*80)
    print("STEP 2: FIX (Automated Repair)")
    print("="*80)

    # Fix blocked obstructions
    print("\nApplying elevation envelope algorithm...")
    fix_results = RasFixit.fix_blocked_obstructions(
        geom_path,
        backup=True,      # Create timestamped backup
        visualize=True    # Generate before/after PNGs
    )

    print(f"\nFix Results:")
    print(f"  Cross sections fixed: {fix_results.total_xs_fixed}")
    print(f"  Backup created: {fix_results.backup_path}")
    print(f"  Visualizations: {fix_results.visualization_folder}")

    # Export audit trail
    audit_trail_path = project_path / "obstruction_fixes_audit.csv"
    fix_df = fix_results.to_dataframe()
    fix_df.to_csv(audit_trail_path, index=False)
    print(f"  Audit trail: {audit_trail_path}")

    # Print summary of fixes
    print("\nFix Summary:")
    for msg in fix_results.messages:
        print(f"  RS {msg.station}: {msg.message}")

else:
    print("\nNo obstruction overlaps detected - skipping repair step")

# ==============================================================================
# Step 6: Verify Fixes
# ==============================================================================

print("\n" + "="*80)
print("STEP 3: VERIFY (Post-Fix Validation)")
print("="*80)

# Verify no obstruction overlaps remain
print("\nVerifying obstruction fixes...")
verify_obstruction = RasFixit.detect_obstruction_overlaps(geom_path)

if verify_obstruction.total_xs_fixed == 0:
    print("SUCCESS: No overlapping obstructions remaining")
else:
    print(f"WARNING: {verify_obstruction.total_xs_fixed} cross sections still have overlaps")
    print("Manual review required!")

# Re-run geometry preprocessing
print("\nRe-running HEC-RAS geometry preprocessing...")
success = RasCmdr.compute_plan(
    plan_number,
    clear_geompre=True,  # Force geometry reprocessing
    overwrite_dest=True
)

if not success:
    print("ERROR: Geometry preprocessing failed after fixes")
    exit(1)

print("Geometry preprocessing successful")

# ==============================================================================
# Step 7: Final Quality Check
# ==============================================================================

print("\nRunning final quality validation...")
final_results = RasCheck.run_all(plan_number)

print(f"\nFinal Validation Results:")
print(f"  Total Messages: {len(final_results.messages)}")
print(f"  Errors: {final_results.get_error_count()}")
print(f"  Warnings: {final_results.get_warning_count()}")

# Generate final report
final_report_path = project_path / "ras_check_final.html"
final_results.to_html(final_report_path, metadata=metadata)
print(f"\nFinal report: {final_report_path}")

# ==============================================================================
# Step 8: Compare Results
# ==============================================================================

print("\n" + "="*80)
print("COMPARISON: Initial vs Final")
print("="*80)

print(f"\nErrors:")
print(f"  Initial: {initial_results.get_error_count()}")
print(f"  Final:   {final_results.get_error_count()}")
print(f"  Change:  {final_results.get_error_count() - initial_results.get_error_count():+d}")

print(f"\nWarnings:")
print(f"  Initial: {initial_results.get_warning_count()}")
print(f"  Final:   {final_results.get_warning_count()}")
print(f"  Change:  {final_results.get_warning_count() - initial_results.get_warning_count():+d}")

# ==============================================================================
# Step 9: Engineering Review Package
# ==============================================================================

print("\n" + "="*80)
print("ENGINEERING REVIEW PACKAGE")
print("="*80)

print("\nThe following files are ready for professional engineering review:")

if obstruction_results.total_xs_fixed > 0:
    print("\n1. Backup Files:")
    print(f"   - Original geometry: {fix_results.backup_path}")

    print("\n2. Visualizations:")
    png_files = sorted(fix_results.visualization_folder.glob("*.png"))
    print(f"   - Before/after PNGs: {len(png_files)} files")
    print(f"   - Location: {fix_results.visualization_folder}")

    print("\n3. Audit Trail:")
    print(f"   - Fix details: {audit_trail_path}")

print("\n4. Validation Reports:")
print(f"   - Initial: {initial_report_path}")
print(f"   - Final:   {final_report_path}")

print("\n5. Model Files:")
print(f"   - Project: {project_path}")
print(f"   - Geometry: {geom_path}")

print("\n" + "="*80)
print("WORKFLOW COMPLETE")
print("="*80)

print("""
Next Steps:
1. Review all PNG visualizations for engineering appropriateness
2. Compare hydraulics (original vs fixed geometry)
3. Document review findings and approval
4. Archive backup files and audit trail

IMPORTANT: All automated fixes require Professional Engineer review
before use in production models or FEMA/USACE submission.
""")
