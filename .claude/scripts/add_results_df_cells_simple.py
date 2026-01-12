"""
Add results_df demonstration cells to notebooks at specific positions.
"""

import json
from pathlib import Path

def add_cells_at_position(nb_path, position, markdown_text, code_text):
    """Add markdown and code cells at a specific position (before last 2 cells)."""
    with open(nb_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    total_cells = len(nb['cells'])

    # Insert before last N cells
    insert_index = total_cells - position

    # Create markdown cell
    markdown_cell = {
        'cell_type': 'markdown',
        'metadata': {},
        'source': [markdown_text]
    }

    # Create code cell
    code_cell = {
        'cell_type': 'code',
        'execution_count': None,
        'metadata': {},
        'outputs': [],
        'source': [code_text]
    }

    # Insert cells
    nb['cells'].insert(insert_index, markdown_cell)
    nb['cells'].insert(insert_index + 1, code_cell)

    # Write back
    with open(nb_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)

    print(f"  [OK] Added 2 cells at index {insert_index} in {nb_path.name}")
    return True

# Configuration: insert before last N cells
configs = [
    {
        'file': 'examples/111_executing_plan_sets.ipynb',
        'before_last': 2,  # Insert before last 2 cells (usually summary)
        'markdown': '## Viewing Execution Summary with results_df\n\nThe `results_df` DataFrame provides execution status, timing, and error/warning information for all executed plans.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "has_warnings", "rt_complete_process_hours"]])'
    },
    {
        'file': 'examples/112_sequential_plan_execution.ipynb',
        'before_last': 2,
        'markdown': '## Viewing Execution Summary with results_df\n\nAfter sequential execution, check the status and timing metrics for each plan.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "has_warnings", "rt_complete_process_hours"]])'
    },
    {
        'file': 'examples/113_parallel_execution.ipynb',
        'before_last': 2,
        'markdown': '## Viewing Execution Summary with results_df\n\nAfter parallel execution, verify all plans completed successfully.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "has_warnings", "rt_complete_process_hours"]])'
    },
    {
        'file': 'examples/103_plan_and_geometry_operations.ipynb',
        'before_last': 2,
        'markdown': '## Viewing Execution Summary with results_df\n\nThe `results_df` DataFrame shows which plans have been executed.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "rt_complete_process_hours"]])'
    },
    {
        'file': 'examples/104_plan_parameter_operations.ipynb',
        'before_last': 2,
        'markdown': '## Viewing Execution Summary with results_df\n\nCheck how parameter changes affected execution performance.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "rt_complete_process_hours"]])'
    },
]

# Process each notebook
print("Adding results_df demonstration cells to notebooks...")
print("="*60)

for config in configs:
    nb_path = Path(config['file'])
    if not nb_path.exists():
        print(f"  [X] Not found: {nb_path}")
        continue

    add_cells_at_position(
        nb_path,
        config['before_last'],
        config['markdown'],
        config['code']
    )

print("="*60)
print("Complete!")
