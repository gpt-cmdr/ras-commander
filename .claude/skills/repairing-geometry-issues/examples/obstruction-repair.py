"""
Blocked Obstruction Repair Example

This example demonstrates the blocked obstruction repair workflow using RasFixit.
Includes detection, repair, visualization, and verification steps.

Use this script for:
- Fixing overlapping blocked obstructions
- Pre-flight checks before HEC-RAS execution
- Generating engineering review documentation
"""

from pathlib import Path
import shutil
from ras_commander import RasExamples, RasFixit

# ==============================================================================
# Configuration
# ==============================================================================

# Example project with known obstruction issues (15 affected cross sections)
PROJECT_NAME = "A120-00-00"  # HCFCD M3 Model
GEOM_FILE = "A120_00_00.g01"

# Extract to temporary location
OUTPUT_DIR = Path("temp_obstruction_repair")
OUTPUT_DIR.mkdir(exist_ok=True)

# ==============================================================================
# Step 1: Extract Example Project
# ==============================================================================

print("="*80)
print("STEP 1: Extract Example Project")
print("="*80)

# Extract to custom location
project_path = RasExamples.extract_project(PROJECT_NAME, output_path=OUTPUT_DIR)
print(f"\nExtracted project to: {project_path}")

# Locate geometry file
geom_path = project_path / GEOM_FILE
print(f"Geometry file: {geom_path}")
print(f"File exists: {geom_path.exists()}")

if not geom_path.exists():
    print(f"ERROR: Geometry file not found: {geom_path}")
    exit(1)

# ==============================================================================
# Step 2: Detection (Non-Destructive)
# ==============================================================================

print("\n" + "="*80)
print("STEP 2: Detection (Non-Destructive Scan)")
print("="*80)

# Scan for overlapping obstructions without modifying file
print("\nScanning geometry file for overlapping obstructions...")
detection_results = RasFixit.detect_obstruction_overlaps(geom_path)

print(f"\nDetection Results:")
print(f"  Cross sections scanned: {detection_results.total_xs_checked}")
print(f"  Cross sections with overlaps: {detection_results.total_xs_fixed}")

if detection_results.total_xs_fixed == 0:
    print("\nNo overlapping obstructions detected - geometry file is clean!")
    exit(0)

# Display affected cross sections
print(f"\nAffected Cross Sections ({detection_results.total_xs_fixed}):")
print(f"  {'Station':<15} {'Original':<10} {'Would Become':<12} {'Status'}")
print(f"  {'-'*15} {'-'*10} {'-'*12} {'-'*30}")

for msg in detection_results.messages:
    status = "Needs repair" if msg.original_count > msg.fixed_count else "Needs gap insertion"
    print(f"  {msg.station:<15} {msg.original_count:<10} {msg.fixed_count:<12} {status}")

# ==============================================================================
# Step 3: Examine Detailed Data
# ==============================================================================

print("\n" + "="*80)
print("STEP 3: Examine Obstruction Details")
print("="*80)

# Look at first affected cross section in detail
sample_msg = detection_results.messages[0]

print(f"\nDetailed View: Cross Section RS {sample_msg.station}")
print(f"\nOriginal Obstructions ({sample_msg.original_count}):")
print(f"  {'#':<5} {'Start':<12} {'End':<12} {'Elevation':<12}")
print(f"  {'-'*5} {'-'*12} {'-'*12} {'-'*12}")

for i, (start, end, elev) in enumerate(sample_msg.original_data, 1):
    print(f"  {i:<5} {start:<12.2f} {end:<12.2f} {elev:<12.2f}")

print(f"\nFixed Obstructions ({sample_msg.fixed_count}) - Elevation Envelope:")
print(f"  {'#':<5} {'Start':<12} {'End':<12} {'Elevation':<12} {'Notes'}")
print(f"  {'-'*5} {'-'*12} {'-'*12} {'-'*12} {'-'*30}")

for i, (start, end, elev) in enumerate(sample_msg.fixed_data, 1):
    # Check if gap was inserted (start doesn't match any original end exactly)
    gap_inserted = not any(abs(orig_end - start) < 0.001
                          for _, orig_end, _ in sample_msg.original_data)
    notes = "0.02 gap inserted" if gap_inserted and i > 1 else ""
    print(f"  {i:<5} {start:<12.2f} {end:<12.2f} {elev:<12.2f} {notes}")

# ==============================================================================
# Step 4: Create Working Copy
# ==============================================================================

print("\n" + "="*80)
print("STEP 4: Create Working Copy (Preserve Original)")
print("="*80)

# Create working copy to preserve original
working_copy = geom_path.parent / f"{geom_path.stem}_working_copy{geom_path.suffix}"
shutil.copy(geom_path, working_copy)
print(f"\nCreated working copy: {working_copy.name}")
print(f"Original preserved: {geom_path.name}")

# ==============================================================================
# Step 5: Apply Fixes
# ==============================================================================

print("\n" + "="*80)
print("STEP 5: Apply Automated Fixes")
print("="*80)

print("\nApplying elevation envelope algorithm...")
print("Options:")
print("  - backup=True       (creates timestamped backup)")
print("  - visualize=True    (generates before/after PNGs)")

fix_results = RasFixit.fix_blocked_obstructions(
    working_copy,
    backup=True,      # Create .g01.backup_YYYYMMDD_HHMMSS
    visualize=True    # Create PNG visualizations
)

print(f"\nFix Results:")
print(f"  Cross sections checked: {fix_results.total_xs_checked}")
print(f"  Cross sections fixed: {fix_results.total_xs_fixed}")
print(f"  Backup created: {fix_results.backup_path}")
print(f"  Visualization folder: {fix_results.visualization_folder}")

# ==============================================================================
# Step 6: Review Fix Details
# ==============================================================================

print("\n" + "="*80)
print("STEP 6: Review Fix Details")
print("="*80)

# Convert to DataFrame for analysis
fix_df = fix_results.to_dataframe()

print(f"\nFix Summary:")
print(fix_df[['station', 'action', 'original_count', 'fixed_count', 'message']].to_string())

# Export to CSV for documentation
csv_path = project_path / "obstruction_fixes_audit_trail.csv"
fix_df.to_csv(csv_path, index=False)
print(f"\nAudit trail exported: {csv_path}")

# ==============================================================================
# Step 7: Examine Visualizations
# ==============================================================================

print("\n" + "="*80)
print("STEP 7: Examine Visualizations")
print("="*80)

if fix_results.visualization_folder and fix_results.visualization_folder.exists():
    png_files = sorted(fix_results.visualization_folder.glob("*.png"))

    print(f"\nGenerated {len(png_files)} before/after visualizations:")
    for png_file in png_files:
        print(f"  - {png_file.name}")

    print(f"\nVisualization folder: {fix_results.visualization_folder}")
    print("\nEach PNG shows:")
    print("  - Top panel: Original obstruction configuration (red)")
    print("  - Bottom panel: Fixed obstruction configuration (green)")
    print("  - Legend: Obstruction numbers and elevations")

    # Optional: Display first visualization
    try:
        import matplotlib.pyplot as plt
        from matplotlib.image import imread

        print("\nDisplaying first visualization...")
        img = imread(png_files[0])
        plt.figure(figsize=(14, 10))
        plt.imshow(img)
        plt.axis('off')
        plt.title(f"Sample: {png_files[0].name}")
        plt.tight_layout()
        plt.show()

    except ImportError:
        print("\nmatplotlib not available - skip visualization display")
        print(f"Open PNG files manually: {fix_results.visualization_folder}")
else:
    print("\nNo visualizations generated (visualize=False)")

# ==============================================================================
# Step 8: Verify Fixes
# ==============================================================================

print("\n" + "="*80)
print("STEP 8: Verify Fixes")
print("="*80)

# Verify no overlaps remain
print("\nVerifying fixes...")
verify_results = RasFixit.detect_obstruction_overlaps(working_copy)

print(f"\nVerification Results:")
print(f"  Cross sections scanned: {verify_results.total_xs_checked}")
print(f"  Cross sections with overlaps: {verify_results.total_xs_fixed}")

if verify_results.total_xs_fixed == 0:
    print("\nSUCCESS: All overlapping obstructions resolved!")
else:
    print(f"\nWARNING: {verify_results.total_xs_fixed} cross sections still have overlaps")
    print("Manual review required!")

    print("\nRemaining issues:")
    for msg in verify_results.messages:
        print(f"  RS {msg.station}: {msg.original_count} obstructions")

# ==============================================================================
# Step 9: Engineering Review Package
# ==============================================================================

print("\n" + "="*80)
print("STEP 9: Engineering Review Package")
print("="*80)

print("\nThe following files are ready for Professional Engineer review:")

print("\n1. Modified Geometry:")
print(f"   - Fixed geometry: {working_copy}")
print(f"   - Original geometry: {geom_path}")

print("\n2. Backup:")
print(f"   - Timestamped backup: {fix_results.backup_path}")

print("\n3. Visualizations:")
print(f"   - Before/after PNGs: {len(png_files)} files")
print(f"   - Location: {fix_results.visualization_folder}")

print("\n4. Audit Trail:")
print(f"   - Fix details CSV: {csv_path}")

print("\n5. Algorithm Documentation:")
print("   - Elevation envelope algorithm (see reference/rasfixit.md)")
print("   - Maximum elevation used in overlap zones (hydraulically conservative)")
print("   - 0.02-unit gaps inserted where elevations differ")

# ==============================================================================
# Step 10: Cleanup (Optional)
# ==============================================================================

print("\n" + "="*80)
print("STEP 10: Cleanup Options")
print("="*80)

cleanup = False  # Set to True to remove temporary files

if cleanup:
    print("\nRemoving temporary files...")

    # Remove working copy
    if working_copy.exists():
        working_copy.unlink()
        print(f"  Removed: {working_copy.name}")

    # Remove backup
    if fix_results.backup_path and fix_results.backup_path.exists():
        fix_results.backup_path.unlink()
        print(f"  Removed: {fix_results.backup_path.name}")

    # Remove visualizations
    if fix_results.visualization_folder and fix_results.visualization_folder.exists():
        shutil.rmtree(fix_results.visualization_folder)
        print(f"  Removed: {fix_results.visualization_folder.name}")

    # Remove CSV
    if csv_path.exists():
        csv_path.unlink()
        print(f"  Removed: {csv_path.name}")

    print("\nCleanup complete!")
else:
    print("\nTemporary files preserved for review (cleanup=False)")
    print("Set cleanup=True to remove temporary files")

# ==============================================================================
# Summary
# ==============================================================================

print("\n" + "="*80)
print("SUMMARY")
print("="*80)

print(f"""
Blocked Obstruction Repair Complete

Project: {PROJECT_NAME}
Geometry File: {GEOM_FILE}

Results:
  - Cross sections scanned: {fix_results.total_xs_checked}
  - Cross sections fixed: {fix_results.total_xs_fixed}
  - Verification: {'PASSED' if verify_results.total_xs_fixed == 0 else 'FAILED'}

Documentation:
  - Working copy: {working_copy}
  - Backup: {fix_results.backup_path}
  - Visualizations: {fix_results.visualization_folder}
  - Audit trail: {csv_path}

Next Steps:
  1. Review all PNG visualizations
  2. Run HEC-RAS geometry preprocessor on working copy
  3. Compare hydraulics (original vs fixed)
  4. Professional Engineer sign-off
  5. Replace original with fixed (after approval)

IMPORTANT: All automated fixes require Professional Engineer review
before use in production models or FEMA/USACE submission.
""")

print("="*80)
