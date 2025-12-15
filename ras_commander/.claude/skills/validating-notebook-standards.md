---
name: validating-notebook-standards
description: |
  Validate Jupyter notebooks against ras-commander standards. Checks H1 title requirement,
  cell structure, import patterns, output hygiene, and compliance with notebook-standards.md.
  Fast validation without execution - scans notebook JSON structure only.

  Use when: validating new notebooks, reviewing notebook quality, enforcing standards,
  preparing notebooks for commit, checking compliance before documentation build.
---

# Validating Notebook Standards

Validate Jupyter notebooks against ras-commander standards without execution.

## Purpose

Enforce notebook quality standards defined in `.claude/rules/documentation/notebook-standards.md`:
- **H1 title in first cell** (REQUIRED for mkdocs)
- **Proper import patterns** (flexible development vs installed package)
- **No committed outputs with errors** (clean notebooks before commit)
- **Security compliance** (no path leaks, IP leaks)
- **Structure compliance** (reasonable cell count, no excessive outputs)

## Standards Checked

### 1. **H1 Title Requirement** (CRITICAL)

**Rule**: First cell must be markdown with H1 heading (`# Title`)

**Why**: mkdocs-jupyter uses H1 for page title. Missing H1 → title becomes filename.

**Validation**:
```python
def check_h1_title(notebook_path: Path) -> dict:
    """Check if first cell has H1 title."""
    with open(notebook_path, 'r') as f:
        nb = json.load(f)

    cells = nb.get('cells', [])
    if not cells:
        return {'valid': False, 'message': 'Notebook has no cells'}

    first_cell = cells[0]
    if first_cell.get('cell_type') != 'markdown':
        return {
            'valid': False,
            'message': f"First cell is {first_cell.get('cell_type')}, not markdown"
        }

    source = ''.join(first_cell.get('source', []))
    if not source.strip().startswith('# '):
        return {
            'valid': False,
            'message': 'First markdown cell does not start with H1 (#)'
        }

    return {'valid': True, 'title': source.split('\n')[0].lstrip('# ')}
```

### 2. **Import Pattern Compliance**

**Rule**: Use flexible import pattern for development vs installed package

**Expected pattern**:
```python
from pathlib import Path
import sys

try:
    from ras_commander import init_ras_project, RasCmdr
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasCmdr
```

**Validation**: Check for `try/except ImportError` with `sys.path.append()` fallback

### 3. **No Error Outputs in Committed Notebooks**

**Rule**: Don't commit notebooks with stored exceptions

**Validation**:
```python
def check_error_outputs(notebook_path: Path) -> dict:
    """Check for stored exception outputs."""
    with open(notebook_path, 'r') as f:
        nb = json.load(f)

    error_cells = []
    for idx, cell in enumerate(nb.get('cells', [])):
        for output in cell.get('outputs', []):
            if output.get('output_type') == 'error':
                error_cells.append({
                    'cell': idx + 1,
                    'error_name': output.get('ename'),
                    'error_value': output.get('evalue')
                })

    if error_cells:
        return {
            'valid': False,
            'message': f"Found {len(error_cells)} cells with error outputs",
            'errors': error_cells
        }

    return {'valid': True}
```

### 4. **Security Compliance**

**Rule**: No path leaks, IP leaks, or sensitive data in outputs

**Patterns to flag**:
- Windows paths: `C:\Users\<username>\`
- Unix paths: `/home/<username>/`
- Private IPs: `192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`

**Validation**: Uses same security scanning as `audit_ipynb.py`

### 5. **Structure Compliance**

**Recommendations** (not strict requirements):
- Cell count: 10-50 cells (reasonable complexity)
- Output size: <100KB per cell (avoid bloat)
- No raw cells (should be code or markdown)

## Validation Script

**Create**: `scripts/notebooks/validate_notebook_standards.py`

```python
#!/usr/bin/env python3
"""
Validate Jupyter notebooks against ras-commander standards.

Checks:
- H1 title in first cell (REQUIRED)
- Import pattern compliance
- No error outputs in committed notebooks
- Security compliance (no leaks)
- Structure compliance

Usage:
    python validate_notebook_standards.py examples/*.ipynb
    python validate_notebook_standards.py --strict examples/new_notebook.ipynb
"""

import json
import re
from pathlib import Path
from typing import Dict, List
import argparse
import sys


def check_h1_title(nb: dict, notebook_path: Path) -> Dict:
    """Check if first cell has H1 title."""
    cells = nb.get('cells', [])
    if not cells:
        return {'valid': False, 'severity': 'ERROR', 'message': 'Notebook has no cells'}

    first_cell = cells[0]
    if first_cell.get('cell_type') != 'markdown':
        return {
            'valid': False,
            'severity': 'ERROR',
            'message': f"First cell must be markdown, not {first_cell.get('cell_type')}"
        }

    source = ''.join(first_cell.get('source', []))
    if not source.strip().startswith('# '):
        return {
            'valid': False,
            'severity': 'ERROR',
            'message': 'First markdown cell must start with H1 (#)'
        }

    title = source.split('\n')[0].lstrip('# ')
    return {'valid': True, 'title': title}


def check_import_pattern(nb: dict) -> Dict:
    """Check for flexible import pattern."""
    # Look for try/except with ImportError and sys.path.append
    has_flexible_import = False

    for cell in nb.get('cells', []):
        if cell.get('cell_type') != 'code':
            continue

        source = ''.join(cell.get('source', []))

        if 'try:' in source and 'except ImportError:' in source and 'sys.path.append' in source:
            has_flexible_import = True
            break

    if not has_flexible_import:
        return {
            'valid': False,
            'severity': 'WARN',
            'message': 'Missing flexible import pattern (try/except ImportError with sys.path.append)'
        }

    return {'valid': True}


def check_error_outputs(nb: dict) -> Dict:
    """Check for stored exception outputs."""
    error_cells = []

    for idx, cell in enumerate(nb.get('cells', [])):
        for output in cell.get('outputs', []):
            if output.get('output_type') == 'error':
                error_cells.append({
                    'cell': idx + 1,
                    'error_name': output.get('ename'),
                    'error_value': output.get('evalue', '')[:100]  # Truncate
                })

    if error_cells:
        return {
            'valid': False,
            'severity': 'ERROR',
            'message': f"Found {len(error_cells)} cells with stored error outputs",
            'errors': error_cells
        }

    return {'valid': True}


def check_security_leaks(nb: dict) -> Dict:
    """Check for path/IP leaks in outputs."""
    leaks = []

    for idx, cell in enumerate(nb.get('cells', [])):
        for output in cell.get('outputs', []):
            text_to_scan = []

            if output.get('output_type') == 'stream':
                text_to_scan.append(''.join(output.get('text', [])))

            if output.get('output_type') in ('display_data', 'execute_result'):
                if 'text/plain' in output.get('data', {}):
                    plain_text = output['data']['text/plain']
                    if isinstance(plain_text, list):
                        text_to_scan.append(''.join(plain_text))
                    else:
                        text_to_scan.append(plain_text)

            for text in text_to_scan:
                # Check for path leaks
                windows_paths = re.findall(r'[A-Z]:\\Users\\([^\\]+)\\', text)
                unix_paths = re.findall(r'/home/([^/]+)/', text)

                if windows_paths:
                    leaks.append({
                        'cell': idx + 1,
                        'type': 'windows_path_leak',
                        'usernames': list(set(windows_paths))
                    })

                if unix_paths:
                    leaks.append({
                        'cell': idx + 1,
                        'type': 'unix_path_leak',
                        'usernames': list(set(unix_paths))
                    })

                # Check for IP leaks
                ip_patterns = [
                    r'\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
                    r'\b172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}\b',
                    r'\b192\.168\.\d{1,3}\.\d{1,3}\b',
                ]

                for pattern in ip_patterns:
                    ips = re.findall(pattern, text)
                    if ips:
                        leaks.append({
                            'cell': idx + 1,
                            'type': 'private_ip_leak',
                            'ips': list(set(ips))
                        })
                        break

    if leaks:
        return {
            'valid': False,
            'severity': 'SECURITY',
            'message': f"Found {len(leaks)} security leaks in outputs",
            'leaks': leaks
        }

    return {'valid': True}


def check_structure(nb: dict) -> Dict:
    """Check notebook structure (recommendations)."""
    warnings = []

    cell_count = len(nb.get('cells', []))

    if cell_count < 5:
        warnings.append(f"Very short notebook ({cell_count} cells)")

    if cell_count > 100:
        warnings.append(f"Very long notebook ({cell_count} cells) - consider splitting")

    # Check for raw cells
    raw_cells = [i+1 for i, cell in enumerate(nb.get('cells', []))
                  if cell.get('cell_type') == 'raw']
    if raw_cells:
        warnings.append(f"Found raw cells at positions: {raw_cells} (should be code or markdown)")

    if warnings:
        return {
            'valid': True,  # Not errors, just warnings
            'severity': 'INFO',
            'message': '; '.join(warnings)
        }

    return {'valid': True}


def validate_notebook(notebook_path: Path, strict: bool = False) -> Dict:
    """
    Validate notebook against all standards.

    Args:
        notebook_path: Path to notebook
        strict: If True, warnings become errors

    Returns:
        Validation results dictionary
    """
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    results = {
        'notebook': notebook_path.name,
        'path': str(notebook_path),
        'checks': {},
        'valid': True,
        'error_count': 0,
        'warning_count': 0
    }

    # Run all checks
    checks = {
        'h1_title': check_h1_title(nb, notebook_path),
        'import_pattern': check_import_pattern(nb),
        'error_outputs': check_error_outputs(nb),
        'security_leaks': check_security_leaks(nb),
        'structure': check_structure(nb),
    }

    results['checks'] = checks

    # Count errors/warnings
    for check_name, check_result in checks.items():
        if not check_result['valid']:
            severity = check_result.get('severity', 'ERROR')

            if severity == 'ERROR' or severity == 'SECURITY':
                results['error_count'] += 1
                results['valid'] = False
            elif severity == 'WARN':
                results['warning_count'] += 1
                if strict:
                    results['error_count'] += 1
                    results['valid'] = False

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Validate Jupyter notebooks against ras-commander standards.'
    )
    parser.add_argument(
        'notebooks',
        nargs='+',
        help='Notebook files to validate'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat warnings as errors (fail on any issue)'
    )

    args = parser.parse_args()

    notebook_paths = [Path(nb) for nb in args.notebooks]

    # Validate all paths exist
    missing = [nb for nb in notebook_paths if not nb.exists()]
    if missing:
        print("ERROR: The following notebooks were not found:")
        for nb in missing:
            print(f"  - {nb}")
        sys.exit(1)

    print(f"Validating {len(notebook_paths)} notebooks...")
    if args.strict:
        print("(Strict mode: warnings will fail validation)")
    print()

    all_valid = True
    results_list = []

    for notebook_path in notebook_paths:
        results = validate_notebook(notebook_path, args.strict)
        results_list.append(results)

        # Print results
        status = "✅" if results['valid'] else "❌"
        print(f"{status} {notebook_path.name}")

        if not results['valid'] or results['warning_count'] > 0:
            for check_name, check_result in results['checks'].items():
                if not check_result['valid']:
                    severity = check_result.get('severity', 'ERROR')
                    symbol = "🔴" if severity in ('ERROR', 'SECURITY') else "⚠️"
                    print(f"  {symbol} {check_name}: {check_result['message']}")

        if not results['valid']:
            all_valid = False

    # Summary
    print()
    print("=" * 80)
    total_errors = sum(r['error_count'] for r in results_list)
    total_warnings = sum(r['warning_count'] for r in results_list)
    print(f"Validated {len(notebook_paths)} notebooks: "
          f"{total_errors} errors, {total_warnings} warnings")

    if all_valid:
        print("✅ All notebooks passed validation")
        sys.exit(0)
    else:
        print("❌ Some notebooks failed validation")
        sys.exit(1)


if __name__ == '__main__':
    main()
```

## Usage

**Validate all notebooks**:
```bash
python scripts/notebooks/validate_notebook_standards.py examples/*.ipynb
```

**Strict mode** (warnings become errors):
```bash
python scripts/notebooks/validate_notebook_standards.py --strict examples/*.ipynb
```

**Single notebook**:
```bash
python scripts/notebooks/validate_notebook_standards.py examples/new_notebook.ipynb
```

## Pre-Commit Hook

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Validate notebooks before commit

echo "Validating notebooks..."
python scripts/notebooks/validate_notebook_standards.py examples/*.ipynb --strict

if [ $? -ne 0 ]; then
  echo "❌ Notebook validation failed. Fix issues before committing."
  exit 1
fi

echo "✅ Notebook validation passed"
```

## CI/CD Integration

```yaml
name: Validate Notebooks

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Validate notebook standards
        run: python scripts/notebooks/validate_notebook_standards.py examples/*.ipynb --strict
```

## See Also

- **notebook-standards.md** - Complete standards documentation (.claude/rules/documentation/)
- **audit_ipynb.py** - Scan outputs for issues (scripts/notebooks/)
- **example-notebook-librarian** - Maintains notebook catalog (.claude/subagents/)
