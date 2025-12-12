#!/usr/bin/env python
"""
Remove anti-pattern try/except blocks from example notebooks.

Identifies and removes broad exception handling that swallows errors,
while preserving legitimate exception handling (flexible imports,
optional dependencies, intentional demonstrations).
"""
import json
import shutil
from pathlib import Path
from datetime import datetime

# Notebooks to process with their specific fixes
NOTEBOOKS_TO_FIX = {
    "23_remote_execution_psexec.ipynb": [
        {
            "find": '        try:\n            msgs = HdfResultsPlan.get_compute_messages(hdf_path)\n            if "completed successfully" in msgs.lower() or "complete process" in msgs.lower():\n                print(f"  Status: SUCCESS")\n            else:\n                print(f"  Status: Check messages")\n        except:\n            print(f"  Status: Could not read messages")',
            "replace": '        msgs = HdfResultsPlan.get_compute_messages(hdf_path)\n        if "completed successfully" in msgs.lower() or "complete process" in msgs.lower():\n            print(f"  Status: SUCCESS")\n        else:\n            print(f"  Status: Check messages")'
        },
        {
            "find": '        try:\n            vol = HdfResultsPlan.get_volume_accounting(hdf_path)\n            if vol is not None and len(vol) > 0:\n                error_pct = vol[\'Error Percent\'].iloc[0]\n                print(f"  Volume Error: {error_pct:.4f}%")\n        except:\n            pass',
            "replace": '        vol = HdfResultsPlan.get_volume_accounting(hdf_path)\n        if vol is not None and len(vol) > 0:\n            error_pct = vol[\'Error Percent\'].iloc[0]\n            print(f"  Volume Error: {error_pct:.4f}%")'
        },
        {
            "find": '        try:\n            if not share_path.exists():\n                continue',
            "replace": '        # Check if share exists before accessing\n        if not share_path.exists():\n            continue'
        },
    ],
    "20_plaintext_geometry_operations.ipynb": [
        {
            "find": '        try:\n            # Get weir profile\n            profile = RasGeometry.get_connection_weir_profile(dam_geom_file, conn_name)',
            "replace": '        # Get weir profile\n        profile = RasGeometry.get_connection_weir_profile(dam_geom_file, conn_name)'
        },
        {
            "find": '    try:\n        sta_elev = RasGeometry.get_station_elevation(geom_file, xs[\'River\'], xs[\'Reach\'], xs[\'RS\'])',
            "replace": '    sta_elev = RasGeometry.get_station_elevation(geom_file, xs[\'River\'], xs[\'Reach\'], xs[\'RS\'])'
        },
    ],
    "21_rasmap_raster_exports.ipynb": [
        {
            "find": '        try:\n            folder = RasMap.get_results_folder(plan_num)',
            "replace": '        folder = RasMap.get_results_folder(plan_num)'
        },
    ],
    "24_aorc_precipitation.ipynb": [
        {
            "find": '        try:\n            with h5py.File(hdf_path, \'r\') as f:',
            "replace": '        with h5py.File(hdf_path, \'r\') as f:'
        },
        {
            "find": '        try:\n            # Create year-specific working folder\n            year_folder = base_project.parent / f"BaldEagleCrkMulti2D_AORC_{year}"',
            "replace": '        # Create year-specific working folder\n        year_folder = base_project.parent / f"BaldEagleCrkMulti2D_AORC_{year}"'
        },
    ],
    "25_programmatic_result_mapping.ipynb": [
        {
            "find": 'try:\n    rasmapper_folder = RasMap.get_results_folder(plan_number)\n    rasmapper_wse = RasMap.get_results_raster(plan_number, "WSE (Max)")\n    \n    print("Comparing programmatic WSE with RASMapper WSE:")\n    print("=" * 50)\n    compare_rasters(outputs["WSE"], rasmapper_wse)\n    \nexcept (ValueError, FileNotFoundError) as e:\n    print(f"RASMapper output not found: {e}")\n    print("\\nTo generate RASMapper output for comparison:")\n    print("  1. Set generate_rasmapper_output = True in the cell above")\n    print("  2. Re-run the cell to generate ground truth")',
            "replace": '# Check if RASMapper output exists - let errors surface if files don\'t exist\nrasmapper_folder = RasMap.get_results_folder(plan_number)\nrasmapper_wse = RasMap.get_results_raster(plan_number, "WSE (Max)")\n\nprint("Comparing programmatic WSE with RASMapper WSE:")\nprint("=" * 50)\ncompare_rasters(outputs["WSE"], rasmapper_wse)\n\n# NOTE: If RASMapper output doesn\'t exist, you will see a ValueError or FileNotFoundError.\n# To generate RASMapper output:\n# 1. Set generate_rasmapper_output = True in the previous cell\n# 2. Re-run that cell to generate ground truth'
        },
    ],
}

def clean_notebook(notebook_path, fixes):
    """Clean a single notebook by applying fixes."""
    print(f"\nProcessing: {notebook_path.name}")

    # Backup original
    backup_path = notebook_path.with_suffix(f".ipynb.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(notebook_path, backup_path)
    print(f"  Backup created: {backup_path.name}")

    # Load notebook
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    changes_made = 0
    for fix in fixes:
        find_text = fix["find"]
        replace_text = fix["replace"]

        # Search through all cells
        for cell in nb["cells"]:
            if cell["cell_type"] != "code":
                continue

            # Join source lines
            source = "".join(cell["source"])

            # Check if pattern exists
            if find_text in source:
                # Replace
                new_source = source.replace(find_text, replace_text)

                # Split back into lines
                cell["source"] = new_source.splitlines(keepends=True)

                changes_made += 1
                print(f"  [OK] Applied fix: {find_text[:60]}...")

    if changes_made > 0:
        # Save modified notebook
        with open(notebook_path, 'w', encoding='utf-8') as f:
            json.dump(nb, f, indent=1, ensure_ascii=False)

        print(f"  => {changes_made} changes applied")
    else:
        print(f"  => No changes needed")

    return changes_made

def main():
    """Main execution."""
    examples_dir = Path(__file__).parent
    total_changes = 0

    print("="*80)
    print("NOTEBOOK TRY/EXCEPT ANTI-PATTERN CLEANUP")
    print("="*80)
    print(f"\nWorking directory: {examples_dir}")
    print(f"Notebooks to process: {len(NOTEBOOKS_TO_FIX)}")

    for notebook_name, fixes in NOTEBOOKS_TO_FIX.items():
        notebook_path = examples_dir / notebook_name

        if not notebook_path.exists():
            print(f"\n[WARNING] {notebook_name} not found, skipping")
            continue

        changes = clean_notebook(notebook_path, fixes)
        total_changes += changes

    print("\n" + "="*80)
    print(f"SUMMARY: {total_changes} total changes applied across {len(NOTEBOOKS_TO_FIX)} notebooks")
    print("="*80)
    print("\nBackup files created with timestamp. Review changes before committing.")
    print("\nNotebooks left unchanged (already clean or legitimate exception handling):")
    print("  - 22_dss_boundary_extraction.ipynb (flexible import - legitimate)")
    print("  - 26_rasprocess_stored_maps.ipynb (no try/except blocks)")
    print("  - 27_fixit_blocked_obstructions.ipynb (no anti-patterns)")
    print("  - 28_quality_assurance_rascheck.ipynb (no anti-patterns)")
    print("  - 29_usgs_gauge_data_integration.ipynb (TBD - needs review)")
    print("  - 29_usgs_gauge_data_integration_executed.ipynb (TBD - needs review)")

if __name__ == "__main__":
    main()
