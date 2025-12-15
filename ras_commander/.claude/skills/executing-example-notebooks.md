---
name: executing-example-notebooks
description: |
  Execute ras-commander example notebooks with proper setup, artifact capture, and validation.
  Uses pytest+nbmake for parallel execution, generates timestamped output artifacts, creates
  reproducibility metadata, and produces audit digests for review. Follows ras-commander
  testing philosophy: real HEC-RAS projects, not mocks.

  Use when: running example notebooks as tests, validating notebook execution, generating
  execution artifacts, testing notebooks in parallel, creating reproducibility snapshots.
---

# Executing Example Notebooks

Run ras-commander example notebooks with full artifact capture and validation.

## Purpose

Execute Jupyter notebooks following ras-commander's testing philosophy:
- Use **real HEC-RAS example projects** (via `RasExamples.extract_project()`)
- Generate **timestamped artifacts** for reproducibility
- Create **audit digests** for review without context overflow
- Support **parallel execution** (notebooks use isolated project folders)
- Capture **environment snapshots** for debugging version-specific issues

## Execution Workflow

### Standard Execution (pytest + nbmake)

**Preferred method** - industry standard with parallel support:

```bash
# Create timestamped run directory
RUN_DIR="working/notebook_runs/$(date +%Y%m%d_%H%M%S)"
mkdir -p $RUN_DIR

# Execute notebooks in parallel
pytest --nbmake examples/*.ipynb -n auto -vv \
  > $RUN_DIR/stdout.txt 2> $RUN_DIR/stderr.txt

# Record command
echo "pytest --nbmake examples/*.ipynb -n auto -vv" > $RUN_DIR/run_command.txt

# Generate audit digest
python scripts/notebooks/audit_ipynb.py examples/*.ipynb --out-dir $RUN_DIR

# Create reproducibility snapshot
python -c "
import sys
import json
from pathlib import Path
from datetime import datetime

snapshot = {
    'timestamp': datetime.now().isoformat(),
    'interpreter': sys.executable,
    'python_version': sys.version,
    'execution_mode': 'pytest+nbmake',
    'working_directory': str(Path.cwd())
}

# Try to get package versions
try:
    import ras_commander
    snapshot['ras_commander_version'] = getattr(ras_commander, '__version__', 'unknown')
    snapshot['ras_commander_path'] = str(Path(ras_commander.__file__).parent)
except:
    pass

with open('$RUN_DIR/reproducibility.json', 'w') as f:
    json.dump(snapshot, f, indent=2)
"

echo "✅ Execution complete. Artifacts in: $RUN_DIR"
```

### Single Notebook Execution (nbconvert)

**Fallback method** - creates executed notebook copy:

```bash
# Create timestamped run directory
RUN_DIR="working/notebook_runs/$(date +%Y%m%d_%H%M%S)"
mkdir -p $RUN_DIR

# Execute single notebook (never overwrites original)
jupyter nbconvert --execute --to notebook \
  --output "$RUN_DIR/11_2d_hdf_data_extraction_executed.ipynb" \
  --ExecutePreprocessor.timeout=600 \
  examples/11_2d_hdf_data_extraction.ipynb \
  > $RUN_DIR/stdout.txt 2> $RUN_DIR/stderr.txt

# Record command
echo "jupyter nbconvert --execute ..." > $RUN_DIR/run_command.txt

# Generate audit digest
python scripts/notebooks/audit_ipynb.py \
  "$RUN_DIR/11_2d_hdf_data_extraction_executed.ipynb" \
  --out-dir $RUN_DIR

echo "✅ Execution complete. Artifacts in: $RUN_DIR"
```

## Parallel Execution Support

**Key feature**: Notebooks can run in parallel because each uses isolated project folders:

```python
# Example: Notebook 11 uses BaldEagleCrkMulti2D
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")

# Example: Notebook 12 uses different project
project_path = RasExamples.extract_project("Muncie")
```

**Parallel execution**:
```bash
# Use pytest-xdist for parallel execution
pytest --nbmake examples/*.ipynb -n auto -vv

# Or specify worker count
pytest --nbmake examples/*.ipynb -n 4 -vv
```

**Benefits**:
- 4-8x faster execution on multi-core systems
- No conflicts (isolated project folders)
- Individual failure reporting

## Output Artifacts

**Standard artifact structure**:

```
working/notebook_runs/20251214_103045/
├── run_command.txt           # Exact command executed
├── stdout.txt                # Captured stdout
├── stderr.txt                # Captured stderr
├── audit.json                # Structured audit findings
├── audit.md                  # Human-readable audit summary
├── audit_<notebook>.md       # Individual notebook reports
├── reproducibility.json      # Environment snapshot
└── <notebook>_executed.ipynb # Executed copy (nbconvert mode only)
```

**Reproducibility snapshot** (reproducibility.json):
```json
{
  "timestamp": "2025-12-14T10:30:45",
  "interpreter": "/path/to/python",
  "python_version": "3.10.12",
  "execution_mode": "pytest+nbmake",
  "working_directory": "/path/to/ras-commander",
  "ras_commander_version": "1.2.3",
  "ras_commander_path": "/path/to/ras_commander",
  "environment_name": "rascmdr_local",
  "key_dependencies": {
    "h5py": "3.10.0",
    "pandas": "2.1.4",
    "pytest": "7.4.3",
    "nbmake": "1.4.6"
  }
}
```

## Integration with Subagents

**Typical workflow**:

1. **User** or **example-notebook-librarian** invokes this skill
2. **Skill** executes notebooks → Generates artifacts
3. **Skill** calls `audit_ipynb.py` → Creates digest
4. **Skill** returns artifact location to caller
5. **Caller** reviews `audit.md` or delegates to Haiku reviewers:
   - `notebook-output-auditor` for exceptions/stderr
   - `notebook-anomaly-spotter` for anomalies/purpose validation

**Example invocation** (from example-notebook-librarian):
```markdown
I need to validate that all example notebooks still execute successfully.

[Librarian invokes executing-example-notebooks skill]
[Skill generates artifacts in working/notebook_runs/20251214_103045/]
[Librarian reviews audit.md summary]
[Librarian delegates detailed review to notebook-output-auditor]
```

## Common Workflows

### Workflow 1: Run All Notebooks (CI/CD)

```bash
#!/bin/bash
# scripts/notebooks/run_all_notebooks.sh

set -e  # Exit on error

RUN_DIR="working/notebook_runs/$(date +%Y%m%d_%H%M%S)"
mkdir -p $RUN_DIR

echo "Running all example notebooks..."
pytest --nbmake examples/*.ipynb -n auto -vv \
  > $RUN_DIR/stdout.txt 2> $RUN_DIR/stderr.txt

echo "Generating audit digest..."
python scripts/notebooks/audit_ipynb.py examples/*.ipynb --out-dir $RUN_DIR

echo "Creating reproducibility snapshot..."
# ... (see above for snapshot code)

echo "✅ Complete. Review: $RUN_DIR/audit.md"
```

### Workflow 2: Run Specific Notebooks (Development)

```bash
# Test specific workflow (HDF extraction notebooks)
pytest --nbmake examples/*hdf*.ipynb -vv

# Test new notebook before committing
pytest --nbmake examples/25_new_feature.ipynb -vv
```

### Workflow 3: Debug Notebook Failures

```bash
# Run single notebook with detailed output
RUN_DIR="working/notebook_runs/debug_$(date +%Y%m%d_%H%M%S)"
mkdir -p $RUN_DIR

pytest --nbmake examples/11_2d_hdf_data_extraction.ipynb -vv --tb=long \
  > $RUN_DIR/stdout.txt 2> $RUN_DIR/stderr.txt

# Review full output
cat $RUN_DIR/stdout.txt
cat $RUN_DIR/stderr.txt
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Test Example Notebooks

on: [push, pull_request]

jobs:
  test-notebooks:
    runs-on: windows-latest  # HEC-RAS requires Windows

    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest pytest-nbmake pytest-xdist

      - name: Run example notebooks
        run: |
          $RUN_DIR = "working/notebook_runs/ci_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
          New-Item -ItemType Directory -Path $RUN_DIR
          pytest --nbmake examples/*.ipynb -n auto -vv | Tee-Object $RUN_DIR/stdout.txt

      - name: Upload artifacts
        if: always()
        uses: actions/upload-artifact@v2
        with:
          name: notebook-execution-artifacts
          path: working/notebook_runs/
```

## Best Practices

**✅ DO**:
- Always use timestamped output directories
- Capture both stdout and stderr
- Generate audit digests after execution
- Create reproducibility snapshots
- Use isolated project folders per notebook
- Run with `-n auto` for parallel execution
- Review audit.md before analyzing individual notebooks

**❌ DON'T**:
- Execute notebooks in-place (always copy to working directory)
- Skip reproducibility metadata (needed for debugging)
- Ignore stderr (contains important warnings)
- Run notebooks sequentially if parallel is possible
- Commit executed notebooks to git (outputs belong in working/)
- Delete execution artifacts immediately (useful for debugging)

## Troubleshooting

**Notebook fails with missing HEC-RAS**:
```bash
# Check if HEC-RAS is installed
python -c "from ras_commander import get_ras_exe; print(get_ras_exe('6.5'))"

# Skip HEC-RAS dependent notebooks in CI
pytest --nbmake examples/*.ipynb -n auto -vv \
  -k "not requires_hecras"  # Mark notebooks with pytest.mark.requires_hecras
```

**Notebooks timeout**:
```bash
# Increase timeout (default 600s)
jupyter nbconvert --execute --to notebook \
  --ExecutePreprocessor.timeout=1800 \
  examples/long_running_notebook.ipynb
```

**Parallel execution conflicts**:
- Verify each notebook uses different `RasExamples.extract_project()` folder
- Check for shared file access (should not exist)
- Review notebook for global state modifications

## See Also

- **notebook-runner** - Subagent that orchestrates execution (.claude/subagents/)
- **audit_ipynb.py** - Scan outputs for issues (scripts/notebooks/)
- **notebook-standards.md** - Notebook requirements (.claude/rules/documentation/)
- **pytest-nbmake** - https://github.com/treebeardtech/nbmake
