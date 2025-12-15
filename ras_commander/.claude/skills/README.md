# Jupyter Notebook Skills for ras-commander

This directory contains reusable skills for working with Jupyter notebooks in the ras-commander repository.

## Overview

The ras-commander repository has **3 specialized skills** that complement the existing subagent system for notebook testing and validation.

## Available Skills

### 1. reading-notebooks-without-outputs

**Purpose**: Extract only code and markdown cells from notebooks, skipping all execution outputs.

**Key Features**:
- Parses .ipynb JSON to extract cell source without outputs
- 90-95% context reduction (500KB notebook → 10KB source)
- Fast analysis of notebook structure and logic
- No execution required

**Usage**:
```bash
# Read single notebook source
python scripts/notebooks/read_notebook_source.py examples/11_2d_hdf_data_extraction.ipynb

# Read multiple notebooks
python scripts/notebooks/read_notebook_source.py examples/*.ipynb > all_sources.txt
```

**When to Use**:
- Reviewing notebook code structure
- Understanding notebook purpose (title and markdown cells)
- Comparing notebooks across versions
- Avoiding output cell context bloat

**Integration**: Used by `notebook-anomaly-spotter` to understand notebook purpose without loading massive output cells.

---

### 2. executing-example-notebooks

**Purpose**: Execute ras-commander example notebooks with full artifact capture and validation.

**Key Features**:
- Supports pytest+nbmake (parallel) and nbconvert (fallback) execution modes
- Generates timestamped artifacts in `working/notebook_runs/<timestamp>/`
- Creates reproducibility snapshots (environment, interpreter, versions)
- Produces audit digests for review
- Enables parallel execution (notebooks use isolated project folders)

**Usage**:
```bash
# Run all notebooks in parallel
RUN_DIR="working/notebook_runs/$(date +%Y%m%d_%H%M%S)"
mkdir -p $RUN_DIR
pytest --nbmake examples/*.ipynb -n auto -vv > $RUN_DIR/stdout.txt 2> $RUN_DIR/stderr.txt
python scripts/notebooks/audit_ipynb.py examples/*.ipynb --out-dir $RUN_DIR

# Run single notebook with nbconvert
jupyter nbconvert --execute --to notebook \
  --output $RUN_DIR/11_executed.ipynb \
  examples/11_2d_hdf_data_extraction.ipynb
```

**Output Artifacts**:
- `run_command.txt` - Exact command executed
- `stdout.txt` / `stderr.txt` - Captured outputs
- `audit.json` / `audit.md` - Structured and human-readable audit
- `reproducibility.json` - Environment snapshot
- Executed notebook copy (nbconvert mode)

**When to Use**:
- Running notebooks as functional tests
- Validating notebook execution
- Generating execution artifacts for review
- CI/CD notebook testing

---

### 3. validating-notebook-standards

**Purpose**: Validate notebooks against ras-commander standards without execution.

**Key Features**:
- Checks H1 title requirement (first cell must be markdown with `# Title`)
- Validates flexible import pattern (try/except ImportError)
- Detects error outputs in committed notebooks
- Security scanning (path leaks, IP leaks)
- Structure validation (cell count, raw cells)

**Usage**:
```bash
# Validate all notebooks
python scripts/notebooks/validate_notebook_standards.py examples/*.ipynb

# Strict mode (warnings become errors)
python scripts/notebooks/validate_notebook_standards.py --strict examples/*.ipynb

# Single notebook
python scripts/notebooks/validate_notebook_standards.py examples/new_notebook.ipynb
```

**Standards Checked**:
- ✅ H1 title in first cell (REQUIRED)
- ✅ Flexible import pattern
- ✅ No stored error outputs
- ✅ No security leaks (paths, IPs)
- ✅ Reasonable structure (cell count, types)

**When to Use**:
- Before committing new notebooks
- Pre-commit hooks
- CI/CD validation
- Enforcing documentation standards

---

## How Skills Complement Subagents

### Subagents vs Skills

**Subagents** (`.claude/subagents/`):
- Multi-step orchestration agents
- Handle complex workflows with delegation
- Maintain state and context across tasks
- Examples: `notebook-runner`, `example-notebook-librarian`

**Skills** (`.claude/skills/`):
- Focused, reusable workflows
- Single-purpose utilities
- Can be used by both humans and subagents
- Examples: `reading-notebooks-without-outputs`, `executing-example-notebooks`

### Integration Pattern

```
User or Librarian
    ↓
notebook-runner (Sonnet subagent)
    ↓
executing-example-notebooks (Skill) → Generates artifacts
    ↓
audit_ipynb.py (Script) → Creates digest
    ↓
reading-notebooks-without-outputs (Skill) → Reads source
    ↓
notebook-anomaly-spotter (Haiku subagent) → Reviews purpose
    ↓
Report back to notebook-runner
```

## Complete Notebook Testing Ecosystem

### Components

1. **Subagents** (`.claude/subagents/`):
   - `notebook-runner` - Orchestrates execution and review
   - `example-notebook-librarian` - Maintains catalog and standards
   - `notebook-output-auditor` - Reviews exceptions/stderr (Haiku)
   - `notebook-anomaly-spotter` - Reviews anomalies + purpose (Haiku)

2. **Skills** (`.claude/skills/`):
   - `reading-notebooks-without-outputs` - Extract source only
   - `executing-example-notebooks` - Run with artifact capture
   - `validating-notebook-standards` - Check compliance

3. **Scripts** (`scripts/notebooks/`):
   - `audit_ipynb.py` - Scan outputs without execution
   - `read_notebook_source.py` - Extract source only
   - `validate_notebook_standards.py` - Check standards

4. **Standards** (`.claude/rules/documentation/`):
   - `notebook-standards.md` - Complete requirements

5. **Catalog** (`examples/`):
   - `AGENTS.md` - Notebook index (single source of truth)

### Workflow Example: Complete Notebook Validation

```bash
# 1. Validate standards (fast, no execution)
python scripts/notebooks/validate_notebook_standards.py examples/*.ipynb

# 2. Execute notebooks with artifact capture
RUN_DIR="working/notebook_runs/$(date +%Y%m%d_%H%M%S)"
mkdir -p $RUN_DIR
pytest --nbmake examples/*.ipynb -n auto -vv > $RUN_DIR/stdout.txt 2> $RUN_DIR/stderr.txt

# 3. Generate audit digest
python scripts/notebooks/audit_ipynb.py examples/*.ipynb --out-dir $RUN_DIR

# 4. Review audit summary
cat $RUN_DIR/audit.md

# 5. If large notebooks, extract source for code review
python scripts/notebooks/read_notebook_source.py examples/large_notebook.ipynb

# 6. Delegate detailed review to subagents (via Claude Code)
# "Review the notebook execution artifacts in $RUN_DIR and report findings"
```

## Built-in Claude Code Tools

**Claude Code provides these tools natively**:

- **Read** - Can read .ipynb files natively (includes outputs)
- **NotebookEdit** - Edit notebook cells (replace, insert, delete)
- **Write** - Create new notebooks
- **Glob** - Find notebooks by pattern
- **Grep** - Search within notebooks

**Our skills extend these by**:
- Reading notebooks WITHOUT outputs (context efficiency)
- Executing with full artifact capture (reproducibility)
- Validating against standards (quality assurance)

## When to Use What

| Task | Use This |
|------|----------|
| **Read notebook code only** | `reading-notebooks-without-outputs` skill |
| **Read notebook with outputs** | Read tool (built-in) |
| **Execute notebooks** | `executing-example-notebooks` skill |
| **Validate standards** | `validating-notebook-standards` skill |
| **Scan for issues (no execution)** | `audit_ipynb.py` script |
| **Edit notebook cells** | NotebookEdit tool (built-in) |
| **Orchestrate workflow** | `notebook-runner` subagent |
| **Maintain catalog** | `example-notebook-librarian` subagent |
| **Review output quality** | `notebook-output-auditor` subagent |
| **Review purpose/anomalies** | `notebook-anomaly-spotter` subagent |

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Notebook Quality Pipeline

on: [push, pull_request]

jobs:
  validate-standards:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Validate notebook standards
        run: python scripts/notebooks/validate_notebook_standards.py examples/*.ipynb --strict

  test-notebooks:
    runs-on: windows-latest  # HEC-RAS requires Windows
    needs: validate-standards
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
      - name: Run notebooks
        run: |
          $RUN_DIR = "working/notebook_runs/ci_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
          New-Item -ItemType Directory -Path $RUN_DIR
          pytest --nbmake examples/*.ipynb -n auto -vv | Tee-Object $RUN_DIR/stdout.txt
      - name: Generate audit
        run: python scripts/notebooks/audit_ipynb.py examples/*.ipynb --out-dir $RUN_DIR
      - name: Upload artifacts
        if: always()
        uses: actions/upload-artifact@v2
        with:
          name: notebook-artifacts
          path: working/notebook_runs/
```

## Future Enhancements

**Potential additional skills** (not currently needed, but could be added):

- **extracting-hdf-results** - Common HDF extraction workflows
- **running-atlas14-storms** - Atlas 14 storm generation
- **notebook-to-script** - Convert notebooks to Python scripts
- **notebook-diff** - Compare notebook versions ignoring outputs

**Only add skills if**:
- Pattern emerges across multiple notebooks
- Workflow is reusable and well-defined
- Provides clear value over existing tools

## See Also

- **Notebook Standards**: `.claude/rules/documentation/notebook-standards.md`
- **Notebook Index**: `examples/AGENTS.md`
- **Subagents**: `.claude/subagents/notebook-*.md`
- **Testing Philosophy**: `.claude/rules/testing/tdd-approach.md`
