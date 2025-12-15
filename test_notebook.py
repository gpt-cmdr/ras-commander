#!/usr/bin/env python
import json
import sys
from pathlib import Path

notebook_path = Path("examples/02_plan_and_geometry_operations.ipynb")
print(f"Testing notebook: {notebook_path}")

# Load notebook
with open(notebook_path) as f:
    nb = json.load(f)

print(f"Total cells: {len(nb['cells'])}")

# Find and check toggle cell
toggle_cells = [c for c in nb['cells'] if 'USE_LOCAL_SOURCE' in str(c.get('source', []))]
if toggle_cells:
    toggle_cell = toggle_cells[0]
    source = ''.join(toggle_cell.get('source', []))
    print("\nToggle cell found:")
    print("  USE_LOCAL_SOURCE value:", "False" if "USE_LOCAL_SOURCE = False" in source else "True")
    print("  Path import location:", "OUTSIDE conditional" if "from pathlib import Path" in source.split("if USE_LOCAL_SOURCE:")[0] else "INSIDE conditional")
    print("  Source preview:")
    for i, line in enumerate(source.split('\n')[:15]):
        print(f"    {i+1}: {line}")
else:
    print("WARNING: No toggle cell found!")

# Check Cell 23 for Path usage
if len(nb['cells']) > 23:
    cell_23 = nb['cells'][23]
    cell_23_source = ''.join(cell_23.get('source', []))
    print("\nCell 23 content (first 200 chars):")
    print("  ", cell_23_source[:200])
    if 'Path' in cell_23_source:
        print("  Contains Path reference: YES")
    else:
        print("  Contains Path reference: NO")

