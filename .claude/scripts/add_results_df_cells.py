"""
Add results_df demonstration cells to notebooks 102-113.

This script adds proper results_df display cells to demonstrate the
new results_df feature added in v0.88.0+.
"""

import json
from pathlib import Path

def add_results_df_cells(nb_path, insert_after_text, markdown_text, code_text):
    """Add markdown and code cells after a specific cell."""
    with open(nb_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    # Find insertion point
    insert_index = None
    for i, cell in enumerate(nb['cells']):
        source = ''.join(cell.get('source', []))
        if insert_after_text in source:
            insert_index = i + 1
            break

    if insert_index is None:
        print(f"  [!] Could not find insertion point in {nb_path.name}")
        return False

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

# Configuration for each notebook
configs = [
    {
        'file': 'examples/111_executing_plan_sets.ipynb',
        'insert_after': 'All executions complete!',
        'markdown': '## Viewing Execution Summary with results_df\n\nThe `results_df` DataFrame provides a lightweight summary of plan execution status, timing, and key metrics for all executed plans.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "has_warnings", "rt_complete_process_hours"]])'
    },
    {
        'file': 'examples/112_sequential_plan_execution.ipynb',
        'insert_after': 'Sequential execution complete!',
        'markdown': '## Viewing Execution Summary with results_df\n\nAfter sequential execution, the `results_df` shows completion status and timing for each plan in order.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "has_warnings", "rt_complete_process_hours"]])'
    },
    {
        'file': 'examples/113_parallel_execution.ipynb',
        'insert_after': 'All parallel executions complete!',
        'markdown': '## Viewing Execution Summary with results_df\n\nAfter parallel execution, verify all plans completed successfully with their performance metrics.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "has_warnings", "rt_complete_process_hours"]])'
    },
    {
        'file': 'examples/102_multiple_project_operations.ipynb',
        'insert_after': 'All executions complete!',
        'markdown': '## Viewing Execution Summary with results_df\n\nFor multi-project operations, each RAS object has its own `results_df`. Note that the global `ras` object shows the last initialized project (Muncie in this case).',
        'code': '# Display results for both projects\nprint("Bald Eagle Creek Results:")\ndisplay.display(bald_eagle_ras.results_df[["plan_number", "plan_title", "completed", "has_errors"]])\n\nprint("\\nMuncie Results:")\ndisplay.display(muncie_ras.results_df[["plan_number", "plan_title", "completed", "has_errors"]])'
    },
    {
        'file': 'examples/103_plan_and_geometry_operations.ipynb',
        'insert_after': 'Plan execution complete!',
        'markdown': '## Viewing Execution Summary with results_df\n\nThe `results_df` shows which plans have been executed and their status.',
        'code': '# Display execution summary from results_df\nprint("Execution Summary:")\ndisplay.display(ras.results_df[["plan_number", "plan_title", "completed", "has_errors", "rt_complete_process_hours"]])'
    },
    {
        'file': 'examples/104_plan_parameter_operations.ipynb',
        'insert_after': 'Execution complete!',
        'markdown': '## Viewing Execution Summary with results_df\n\nCheck execution metrics to see the impact of parameter changes on runtime.',
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

    add_results_df_cells(
        nb_path,
        config['insert_after'],
        config['markdown'],
        config['code']
    )

print("="*60)
print("Complete!")
