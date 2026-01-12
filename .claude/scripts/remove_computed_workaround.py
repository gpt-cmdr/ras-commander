#!/usr/bin/env python
"""
Remove [Computed] folder workaround code from notebooks.

This script removes the obsolete workaround code that was needed before v0.88.1
when compute_parallel() and compute_test_mode() created separate [Computed] and [Test] folders.

After v0.88.1, results are consolidated directly to the original project folder,
so the workaround is no longer needed.
"""

import json
from pathlib import Path
import sys

def remove_workaround_pattern_1(source_code):
    """
    Remove pattern 1: original_project_path fallback

    Before:
        computed_folder = original_project_path.parent / f"{original_project_path.name} [Computed]"
        if computed_folder.exists():
            project_path = computed_folder
            print(f"  Using computed folder: {computed_folder.name}")
        else:
            project_path = original_project_path
            print(f"  [!] Computed folder not found, using original: {original_project_path.name}")

    After:
        # Results are consolidated to original folder (v0.88.1+)
        project_path = original_project_path
    """
    # Try with the full comment
    old_pattern_1 = '''        # compute_parallel() consolidates results to "[Computed]" folder
        computed_folder = original_project_path.parent / f"{original_project_path.name} [Computed]"

        # Use computed folder if it exists, otherwise fall back to original
        if computed_folder.exists():
            project_path = computed_folder
            print(f"  Using computed folder: {computed_folder.name}")
        else:
            project_path = original_project_path
            print(f"  [!] Computed folder not found, using original: {original_project_path.name}")
        '''

    # Try without the trailing space after last line
    old_pattern_2 = '''        # compute_parallel() consolidates results to "[Computed]" folder
        computed_folder = original_project_path.parent / f"{original_project_path.name} [Computed]"

        # Use computed folder if it exists, otherwise fall back to original
        if computed_folder.exists():
            project_path = computed_folder
            print(f"  Using computed folder: {computed_folder.name}")
        else:
            project_path = original_project_path
            print(f"  [!] Computed folder not found, using original: {original_project_path.name}")'''

    new_pattern = '''        # Results are consolidated to original folder (v0.88.1+)
        project_path = original_project_path'''

    source_code = source_code.replace(old_pattern_1, new_pattern)
    source_code = source_code.replace(old_pattern_2, new_pattern)

    return source_code

def remove_workaround_pattern_2(source_code):
    """
    Remove pattern 2: project_path -> analysis_path fallback

    Before:
        # Detect [Computed] folder if exists
        computed_folder = project_path.parent / f"{project_path.name} [Computed]"
        if computed_folder.exists():
            analysis_path = computed_folder
            print(f"  Using computed folder: {computed_folder.name}")
        else:
            analysis_path = project_path

    After:
        # Results are consolidated to original folder (v0.88.1+)
        analysis_path = project_path
    """
    old_pattern = '''        # Detect [Computed] folder if exists
        computed_folder = project_path.parent / f"{project_path.name} [Computed]"
        if computed_folder.exists():
            analysis_path = computed_folder
            print(f"  Using computed folder: {computed_folder.name}")
        else:
            analysis_path = project_path'''

    new_pattern = '''        # Results are consolidated to original folder (v0.88.1+)
        analysis_path = project_path'''

    return source_code.replace(old_pattern, new_pattern)

def remove_workaround_pattern_3(source_code):
    """
    Remove pattern 3: [Computed] folder with different print message (notebook 722)

    Before:
        # Detect [Computed] folder
        computed_folder = project_path.parent / f"{project_path.name} [Computed]"
        if computed_folder.exists():
            analysis_path = computed_folder
            print(f"\n  Using computed folder: {computed_folder.name}")
        else:
            analysis_path = project_path

    After:
        # Results are consolidated to original folder (v0.88.1+)
        analysis_path = project_path
    """
    old_pattern = '''        # Detect [Computed] folder
        computed_folder = project_path.parent / f"{project_path.name} [Computed]"
        if computed_folder.exists():
            analysis_path = computed_folder
            print(f"\\n  Using computed folder: {computed_folder.name}")
        else:
            analysis_path = project_path'''

    new_pattern = '''        # Results are consolidated to original folder (v0.88.1+)
        analysis_path = project_path'''

    return source_code.replace(old_pattern, new_pattern)

def remove_workaround_pattern_4(source_code):
    """
    Remove pattern 4: Re-initialization workaround (notebooks 900, 901)

    Before:
        # Re-initialize from computed folder
        computed_folder = ras.project_folder.parent / f"{ras.project_folder.name} [Computed]"
        if computed_folder.exists():
            ras = init_ras_project(computed_folder, RAS_VERSION)
            print(f"Re-initialized from: {computed_folder}")
        else:
            print(f"Warning: Computed folder not found")

    After:
        # Results are already in original folder (v0.88.1+) - no re-initialization needed
    """
    old_pattern = '''# Re-initialize from computed folder
computed_folder = ras.project_folder.parent / f"{ras.project_folder.name} [Computed]"
if computed_folder.exists():
    ras = init_ras_project(computed_folder, RAS_VERSION)
    print(f"Re-initialized from: {computed_folder}")
else:
    print(f"Warning: Computed folder not found")'''

    new_pattern = '''# Results are already in original folder (v0.88.1+) - no re-initialization needed'''

    return source_code.replace(old_pattern, new_pattern)

def process_notebook(notebook_path):
    """Process a single notebook to remove workaround patterns."""
    print(f"\nProcessing: {notebook_path.name}")

    # Read notebook
    with open(notebook_path, 'r', encoding='utf-8') as f:
        notebook = json.load(f)

    changes_made = 0

    # Process each cell
    for cell in notebook.get('cells', []):
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            if isinstance(source, list):
                original_source = ''.join(source)
            else:
                original_source = source

            # Apply all workaround removals
            modified_source = original_source
            modified_source = remove_workaround_pattern_1(modified_source)
            modified_source = remove_workaround_pattern_2(modified_source)
            modified_source = remove_workaround_pattern_3(modified_source)
            modified_source = remove_workaround_pattern_4(modified_source)

            # Check if changes were made
            if modified_source != original_source:
                changes_made += 1
                # Convert back to list format (preserving line breaks)
                if isinstance(source, list):
                    cell['source'] = modified_source.splitlines(keepends=True)
                else:
                    cell['source'] = modified_source

                print(f"  [OK] Removed workaround code from cell")

    if changes_made > 0:
        # Write modified notebook
        with open(notebook_path, 'w', encoding='utf-8') as f:
            json.dump(notebook, f, indent=1, ensure_ascii=False)
        print(f"  [OK] Saved {changes_made} changes to {notebook_path.name}")
    else:
        print(f"  [--] No workaround code found in {notebook_path.name}")

    return changes_made

def main():
    """Main function to process all notebooks."""
    examples_dir = Path(__file__).parent.parent.parent / 'examples'

    notebooks_to_process = [
        '721_Precipitation_Hyetograph_Comparison.ipynb',
        '722_gridded_precipitation_atlas14.ipynb',
        '900_aorc_precipitation.ipynb',
        '901_aorc_precipitation_catalog.ipynb'
    ]

    print("Removing [Computed] folder workaround code from notebooks...")
    print("=" * 70)

    total_changes = 0
    for notebook_name in notebooks_to_process:
        notebook_path = examples_dir / notebook_name
        if notebook_path.exists():
            changes = process_notebook(notebook_path)
            total_changes += changes
        else:
            print(f"\n[WARNING] Notebook not found: {notebook_name}")

    print("\n" + "=" * 70)
    print(f"[OK] Complete! Total changes: {total_changes}")

    if total_changes > 0:
        print("\nNotebooks have been simplified:")
        print("  • Removed obsolete [Computed] folder detection code")
        print("  • Results now accessed directly from original project folder")
        print("  • Consistent with v0.88.1+ behavior")

    return 0

if __name__ == '__main__':
    sys.exit(main())
