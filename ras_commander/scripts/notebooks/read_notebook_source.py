#!/usr/bin/env python3
"""
Read Jupyter notebook without outputs - extract only code and markdown cells.

Parses .ipynb JSON and displays cell contents without execution outputs, plots,
or results. Useful for code review, structure analysis, and avoiding context overflow.

Usage:
    python read_notebook_source.py <notebook.ipynb>
    python read_notebook_source.py examples/*.ipynb
"""

import json
import sys
from pathlib import Path
from typing import List


def read_notebook_without_outputs(notebook_path: Path) -> str:
    """
    Read Jupyter notebook and extract only code and markdown cells.

    Args:
        notebook_path: Path to .ipynb file

    Returns:
        Formatted string with cell contents (no outputs)
    """
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    lines = []
    lines.append(f"# Notebook: {notebook_path.name}\n")
    lines.append(f"# Total cells: {len(nb.get('cells', []))}\n")
    lines.append("=" * 80 + "\n\n")

    code_cells = 0
    markdown_cells = 0

    for cell_idx, cell in enumerate(nb.get('cells', [])):
        cell_num = cell_idx + 1
        cell_type = cell.get('cell_type', 'unknown')

        # Only process code and markdown cells
        if cell_type not in ('code', 'markdown'):
            continue

        if cell_type == 'code':
            code_cells += 1
        else:
            markdown_cells += 1

        # Header
        lines.append(f"## Cell [{cell_num}] ({cell_type})\n\n")

        # Source content
        source = cell.get('source', [])
        if isinstance(source, list):
            source_text = ''.join(source)
        else:
            source_text = source

        lines.append(source_text.rstrip())
        lines.append("\n\n" + "=" * 80 + "\n\n")

    # Summary at end
    lines.append(f"# Summary: {code_cells} code cells, {markdown_cells} markdown cells\n")

    return ''.join(lines)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python read_notebook_source.py <notebook.ipynb> [<notebook2.ipynb> ...]")
        print("\nExamples:")
        print("  python read_notebook_source.py examples/11_2d_hdf_data_extraction.ipynb")
        print("  python read_notebook_source.py examples/*.ipynb > all_notebooks_source.txt")
        sys.exit(1)

    notebook_paths = [Path(arg) for arg in sys.argv[1:]]

    # Validate all paths exist
    missing = [nb for nb in notebook_paths if not nb.exists()]
    if missing:
        print(f"Error: The following notebooks were not found:")
        for nb in missing:
            print(f"  - {nb}")
        sys.exit(1)

    # Process each notebook
    for notebook_path in notebook_paths:
        try:
            output = read_notebook_without_outputs(notebook_path)
            print(output)

            # Add separator between notebooks if processing multiple
            if len(notebook_paths) > 1:
                print("\n" + "#" * 80)
                print(f"# END OF {notebook_path.name}")
                print("#" * 80 + "\n\n")

        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse {notebook_path}: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error processing {notebook_path}: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
