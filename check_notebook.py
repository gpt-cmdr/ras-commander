import json
from pathlib import Path

nb_path = Path("C:/GH/ras-commander/examples/09_plan_parameter_operations.ipynb")
with open(nb_path, encoding='utf-8') as f:
    nb = json.load(f)

print(f"Total cells: {len(nb['cells'])}")
print("\nFirst 3 cells:")
for i, cell in enumerate(nb['cells'][:3]):
    cell_type = cell.get('cell_type', 'unknown')
    source = cell.get('source', [])
    source_text = ''.join(source)[:100] if source else 'empty'
    print(f"Cell {i}: {cell_type} - {source_text}")

# Check for toggle cell
print("\n\nSearching for toggle cell (USE_LOCAL_SOURCE):")
for i, cell in enumerate(nb['cells']):
    source = ''.join(cell.get('source', []))
    if 'USE_LOCAL_SOURCE' in source:
        print(f"Found at cell {i}:")
        print(source[:300])
        break
else:
    print("No toggle cell found")
