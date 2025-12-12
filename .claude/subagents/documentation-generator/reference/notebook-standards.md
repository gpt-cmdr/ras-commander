# Notebook Standards Reference

**Quick reference for creating and maintaining example notebooks in ras-commander.**

## Mandatory Requirements

### H1 Title in First Cell

**Every notebook MUST start with**:
```markdown
# Descriptive Title

Brief introduction explaining what this notebook demonstrates and its purpose.
```

**Why**: mkdocs-jupyter uses this H1 for the documentation page title. Missing H1 results in filename being used as title ("01_basic_usage" instead of "Basic Usage of ras-commander").

### RasExamples Pattern for Reproducibility

**Always extract example projects programmatically**:
```python
from ras_commander import RasExamples

# Good - works on any machine
project_path = RasExamples.extract_project("Muncie")
init_ras_project(project_path, "6.5")
```

**Never use hard-coded paths**:
```python
# Bad - only works on your machine
project_path = Path("/Users/me/Documents/Projects/Muncie")
```

**Why**: Notebooks serve as functional tests AND documentation. They must be reproducible on any machine.

### Dual Import Cell Pattern

**Cell 0 (Code - ACTIVE by default)**:
```python
# Uncomment to install/upgrade ras-commander from pip
#!pip install --upgrade ras-commander

#Import the ras-commander package
from ras_commander import *
```

**Cell 1 (Markdown - INACTIVE by default)**:
```markdown
**Development Mode** (uncomment to use local copy):

```python
from pathlib import Path
import sys
current_file = Path(__file__).resolve()
parent_directory = current_file.parent.parent
sys.path.append(str(parent_directory))
from ras_commander import *
```
```

**Important**:
- Default state: Cell 0 is code, Cell 1 is markdown
- For local testing: Convert Cell 0 to markdown, Cell 1 to code
- Never have both as code cells simultaneously
- Always restore default state before committing

### Pre-Execute with Outputs

**Because `execute: false` in mkdocs.yml**:
```yaml
plugins:
  - mkdocs-jupyter:
      execute: false  # Notebooks NOT run during build
```

**You must**:
1. Run all cells locally (`Kernel → Restart & Run All`)
2. Verify outputs look correct
3. Save notebook with outputs included
4. Commit to git

**Why**: Documentation site shows saved outputs. Without outputs, users only see code (not helpful).

## Recommended Cell Structure

### 1. Title Cell (Markdown)
```markdown
# [Descriptive Title]

[Brief introduction explaining purpose, scope, and what users will learn]
```

### 2. Import Cells (Code + Markdown)
Follow dual import pattern above.

### 3. Project Setup (Code)
```python
from ras_commander import RasExamples

# Extract example project
project_path = RasExamples.extract_project("Muncie")
print(f"Project extracted to: {project_path}")

# Initialize project
init_ras_project(project_path, "6.5")
print(f"✓ Project initialized")
```

### 4. Main Content (Alternating Markdown/Code)

**Markdown cells** - Explain what you're about to do:
```markdown
## Execute Plan with Custom Parameters

We'll run the plan in a separate folder to preserve the original project,
using 4 CPU cores for faster computation.
```

**Code cells** - Do it:
```python
RasCmdr.compute_plan(
    "01",
    dest_folder="output/run1",
    num_cores=4
)
```

**Output cells** - Show results:
```python
# Verify HDF created
hdf_file = project_path / "Muncie.p01.hdf"
assert hdf_file.exists(), "HDF file should be created"
print(f"✓ HDF file created: {hdf_file.name}")
```

### 5. Optional Cleanup (Code)
```python
# Clean up extracted project
import shutil
shutil.rmtree(project_path.parent / "example_projects", ignore_errors=True)
print("✓ Cleaned up example project")
```

## Content Guidelines

### Good Markdown Practices

**Use ## for major sections** (H1 reserved for title):
```markdown
## Setup
## Execute Plan
## Extract Results
## Visualization
## Cleanup
```

**Explain concepts, don't just show code**:
```markdown
### Understanding Plan Cloning

Plan cloning creates a new plan file while preserving the original.
This is useful for parameter sweeps or sensitivity analysis where
you want to run variations without modifying base configurations.
```

**Code examples in markdown** use triple backticks:
````markdown
```python
RasPlan.clone_plan("01", "02", "Sensitivity Run")
```
````

### Good Code Practices

**Print important information**:
```python
print(f"Project: {project_path.name}")
print(f"Plans found: {len(ras.plan_df)}")
print(f"Active plan: {ras.plan_df.loc[ras.plan_df['plan_id']=='01', 'plan_title'].iloc[0]}")
```

**Show DataFrames strategically** (not entire tables):
```python
# Show key columns only
ras.plan_df[['plan_id', 'plan_title', 'geom_file', 'unsteady_file']].head()
```

**Include verification/assertions**:
```python
# Verify results
from ras_commander.hdf import HdfResultsPlan
hdf = HdfResultsPlan(hdf_file)
wse = hdf.get_max_wse()
print(f"✓ Extracted {len(wse)} max water surface elevations")
assert len(wse) > 0, "Should have results"
```

**Handle errors gracefully**:
```python
try:
    RasCmdr.compute_plan("01")
    print("✓ Plan executed successfully")
except FileNotFoundError as e:
    print(f"❌ Error: {e}")
    print("Make sure project is initialized first")
except Exception as e:
    print(f"❌ Execution failed: {e}")
```

**Use visualizations with context**:
```python
import matplotlib.pyplot as plt

plt.figure(figsize=(12, 6))
plt.plot(times, wse_values, marker='o')
plt.xlabel('Time (hours)')
plt.ylabel('Water Surface Elevation (ft)')
plt.title('Hydrograph at XS 12345 - Peak WSE 123.45 ft')
plt.grid(True)
plt.tight_layout()
plt.show()
```

## Notebook Naming Convention

**Format**: `##_descriptive_name.ipynb`

**Examples**:
- `01_project_initialization.ipynb`
- `05_single_plan_execution.ipynb`
- `24_aorc_precipitation.ipynb`
- `101_Core_Sensitivity.ipynb`

**Guidelines**:
- Two digits for proper sorting (allows up to 99)
- Descriptive name (explains content)
- Lowercase with underscores (no spaces, hyphens, or camelCase)
- Concise but clear (avoid overly long names)

**Good names**:
- `08_parallel_execution.ipynb`
- `19_steady_flow_analysis.ipynb`
- `27_fixit_blocked_obstructions.ipynb`

**Bad names**:
- `test.ipynb` (too generic)
- `MyNotebook.ipynb` (wrong case)
- `8_parallel.ipynb` (single digit, hard to sort)
- `notebook-about-parallel-execution.ipynb` (hyphens, too long)

## Title Best Practices

### Good Titles (H1 in first cell)

**Descriptive and specific**:
```markdown
# Basic Usage of ras-commander
# Parallel Execution with Multiple Plans
# Extracting 2D Mesh Results from HDF Files
# Real-Time Monitoring with Stream Callbacks
# Quality Assurance with RasCheck
```

**Why**: Clear purpose, appropriate detail level, useful in documentation nav.

### Bad Titles

**Too generic**:
```markdown
# Example
# Test
# Tutorial
```

**Too technical**:
```markdown
# RasCmdr.compute_plan() Function Demonstration
# HdfResultsMesh Class Usage
```

**Redundant with filename**:
```markdown
# 01_project_initialization  # Just use "Project Initialization"
```

## Making Notebooks Testable

### DO:
- ✅ Use RasExamples (reproducible)
- ✅ Include cleanup (remove temp files)
- ✅ Handle errors gracefully
- ✅ Keep execution time reasonable (<5 min preferred)
- ✅ Verify outputs with assertions
- ✅ Use relative paths or Path.name in outputs

### DON'T:
- ❌ Require user input
- ❌ Use absolute paths (like `/Users/me/...`)
- ❌ Leave large files uncommitted
- ❌ Have side effects between cells
- ❌ Depend on external resources without checking availability
- ❌ Show absolute paths in output

## Integration with Testing

### pytest + nbmake

Notebooks can be run as tests:
```bash
# Test all notebooks
pytest --nbmake examples/*.ipynb

# Test specific notebook
pytest --nbmake examples/01_project_initialization.ipynb

# Skip slow notebooks
pytest --nbmake examples/*.ipynb -k "not benchmark"
```

**Requirements**:
```bash
pip install pytest pytest-nbmake
```

## Integration with MkDocs

### Adding to Navigation

Edit `mkdocs.yml`:
```yaml
nav:
  - Example Notebooks:
    - Getting Started:
      - Project Initialization: notebooks/01_project_initialization.ipynb
      - Plan Execution: notebooks/05_single_plan_execution.ipynb
    - Advanced:
      - Parallel Execution: notebooks/08_parallel_execution.ipynb
```

**Note**: With `ignore_h1_titles: true`, the nav title is used (not notebook H1).

### Local Preview

```bash
# Copy notebooks into docs
cp -r examples docs/notebooks

# Serve documentation locally
mkdocs serve

# Visit http://127.0.0.1:8000
```

**Verify**:
- Title appears correctly
- Code cells render with syntax highlighting
- Outputs display (tables, plots, text)
- Links work
- No broken references

## Pre-Commit Checklist

Before committing a new or modified notebook:

- [ ] First cell is markdown with H1 title
- [ ] Uses RasExamples (no hard-coded paths)
- [ ] Import cells follow 2-cell pattern
- [ ] Cell 0 is code (pip mode active)
- [ ] Cell 1 is markdown (dev mode inactive)
- [ ] Ran `Kernel → Restart & Run All` successfully
- [ ] All outputs saved and look correct
- [ ] No absolute paths in outputs
- [ ] Added to mkdocs.yml navigation
- [ ] Tested locally with `mkdocs serve`
- [ ] Execution time reasonable (<5 min preferred)
- [ ] Includes cleanup (removes temp files)

## Common Pitfalls

### Missing H1 → Filename as Title
**Problem**: First cell is code
**Result**: Docs show "01_basic_usage" instead of "Basic Usage"
**Fix**: Add markdown cell with H1 first

### Hard-Coded Paths → Not Reproducible
**Problem**: `project_path = Path("/Users/me/...")`
**Result**: Fails on other machines
**Fix**: Use RasExamples

### No Outputs → Empty Documentation
**Problem**: Committed without running cells
**Result**: Docs show code but no results (execute: false)
**Fix**: Run all cells before committing

### Absolute Paths in Output → Confusing Users
**Problem**: Output shows `/Users/billk/Documents/...`
**Result**: Users confused by different paths
**Fix**: Use `Path.name` or relative paths in print statements

### Both Import Cells Active → Import Conflicts
**Problem**: Cell 0 and Cell 1 both code cells
**Result**: Imports from both pip and local copy (conflict)
**Fix**: Only one import method active at a time

## See Also

- **SUBAGENT.md** - Complete documentation-generator guide
- **mkdocs-deployment.md** - ReadTheDocs vs GitHub Pages configuration
- `examples/AGENTS.md` - Notebook index and extraction workflow
- `.claude/rules/documentation/notebook-standards.md` - Full standards

---

**Quick Summary**: Start with H1 markdown cell. Use RasExamples. Run all cells before committing. Default to pip mode (Cell 0 code, Cell 1 markdown). Add to mkdocs.yml nav. Test with `mkdocs serve`.
