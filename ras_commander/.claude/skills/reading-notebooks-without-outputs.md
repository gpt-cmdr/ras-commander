---
name: reading-notebooks-without-outputs
description: |
  Read Jupyter notebook source code and markdown without output cells. Parses .ipynb JSON
  to extract only code and markdown cell content, skipping all execution outputs, plots,
  and results. Useful for analyzing notebook logic without context overflow from large outputs.

  Use when: reviewing notebook code structure, analyzing cell logic, comparing notebook
  source across versions, preparing for notebook editing, avoiding output cell clutter.
---

# Reading Notebooks Without Outputs

Parse Jupyter notebooks to extract only code and markdown cells, excluding all outputs.

## Purpose

When reviewing Jupyter notebooks, output cells can create **massive context overhead**:
- Plot outputs (base64-encoded images)
- DataFrame displays (hundreds of rows)
- Traceback outputs (long stack traces)
- Execution results (large arrays, nested JSON)

This skill **extracts only the source** (code + markdown), making notebooks readable and analyzable without context bloat.

## When to Use

**✅ Use this skill when**:
- Analyzing notebook code structure and logic
- Reviewing notebook source for code quality
- Comparing notebooks across versions (git diff alternative)
- Preparing to edit notebook cells
- Understanding notebook workflow without execution results
- Working with notebooks that have large outputs (>50KB)

**❌ Don't use this skill when**:
- You need to see execution results or outputs
- Debugging notebook execution failures (use full Read)
- Reviewing plots or visualizations
- Analyzing output quality (use notebook-anomaly-spotter)

## Implementation

### Python Function

```python
import json
from pathlib import Path
from typing import Dict, List

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

    for cell_idx, cell in enumerate(nb.get('cells', [])):
        cell_num = cell_idx + 1
        cell_type = cell.get('cell_type', 'unknown')

        # Only process code and markdown cells
        if cell_type not in ('code', 'markdown'):
            continue

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

    return ''.join(lines)
```

### Usage in Subagents

**In notebook-anomaly-spotter or example-notebook-librarian**:

```python
# Instead of reading full notebook with outputs:
full_notebook = Read("examples/11_2d_hdf_data_extraction.ipynb")  # May be 500KB+

# Read only source code and markdown:
from pathlib import Path
notebook_source = read_notebook_without_outputs(
    Path("examples/11_2d_hdf_data_extraction.ipynb")
)
# Returns ~20KB instead of 500KB
```

## Output Format

**Example output**:

```markdown
# Notebook: 11_2d_hdf_data_extraction.ipynb
# Total cells: 25
================================================================================

## Cell [1] (markdown)

# 2D HDF Data Extraction

This notebook demonstrates extracting results from 2D unsteady flow HDF files.

================================================================================

## Cell [2] (code)

from pathlib import Path
import sys

try:
    from ras_commander import RasExamples, init_ras_project, RasCmdr
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import RasExamples, init_ras_project, RasCmdr

================================================================================

## Cell [3] (code)

# Extract example project
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")

================================================================================

... (continues for all cells, NO OUTPUTS)
```

## Integration with Audit Workflow

This skill complements the audit workflow:

1. **audit_ipynb.py** scans notebook outputs → Creates digest
2. **reading-notebooks-without-outputs** extracts source → For code review
3. **notebook-output-auditor** reviews exception/stderr → From digest
4. **notebook-anomaly-spotter** reviews anomalies → From digest

**Workflow example**:
```bash
# 1. Get source code only (for structure analysis)
python -c "from skills import read_notebook_without_outputs;
           print(read_notebook_without_outputs('examples/11_2d_hdf.ipynb'))" > source_only.txt

# 2. Generate output audit (for quality analysis)
python scripts/notebooks/audit_ipynb.py examples/11_2d_hdf.ipynb --out-dir audit_01
```

## Benefits

**Context Efficiency**:
- Full notebook with outputs: 500KB - 5MB
- Source only (this skill): 10KB - 50KB
- **90-95% context reduction** for large notebooks

**Code Review Focus**:
- See notebook logic flow without output clutter
- Compare cell structure across notebooks
- Identify duplicated code patterns
- Spot missing imports or undefined variables

**Git-Friendly**:
- Generate clean diffs for version comparison
- Review notebook changes without output noise
- Identify actual code changes vs output changes

## Python Implementation (Standalone Script)

For use outside of skills framework:

```python
#!/usr/bin/env python3
"""Read Jupyter notebook without outputs."""

import json
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python read_notebook_source.py <notebook.ipynb>")
        sys.exit(1)

    notebook_path = Path(sys.argv[1])

    if not notebook_path.exists():
        print(f"Error: {notebook_path} not found")
        sys.exit(1)

    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    print(f"# Notebook: {notebook_path.name}")
    print(f"# Total cells: {len(nb.get('cells', []))}")
    print("=" * 80)
    print()

    for cell_idx, cell in enumerate(nb.get('cells', [])):
        cell_num = cell_idx + 1
        cell_type = cell.get('cell_type', 'unknown')

        if cell_type not in ('code', 'markdown'):
            continue

        print(f"## Cell [{cell_num}] ({cell_type})")
        print()

        source = cell.get('source', [])
        if isinstance(source, list):
            source_text = ''.join(source)
        else:
            source_text = source

        print(source_text.rstrip())
        print()
        print("=" * 80)
        print()

if __name__ == '__main__':
    main()
```

**Save as**: `scripts/notebooks/read_notebook_source.py`

**Usage**:
```bash
python scripts/notebooks/read_notebook_source.py examples/11_2d_hdf_data_extraction.ipynb
```

## See Also

- **NotebookEdit tool** - Claude Code built-in for editing cells
- **Read tool** - Claude Code built-in (includes outputs)
- **audit_ipynb.py** - Scan outputs for issues (scripts/notebooks/)
- **notebook-anomaly-spotter** - Review output quality (.claude/subagents/)
