# Notebook Standards

**Context**: Jupyter notebook documentation and testing standards
**Priority**: High - affects documentation quality
**Auto-loads**: Yes (all code)
**Path-Specific**: Relevant to `examples/*.ipynb`

## Overview

Example notebooks in `examples/` serve dual purpose:
1. **User Documentation**: Show how to use ras-commander
2. **Functional Tests**: Validate library works correctly

## Required: H1 Title in First Cell

### Mandatory First Cell

**Every notebook MUST have**:
- First cell: Markdown cell
- Content: H1 heading (`# Title`)
- Purpose: Page title in documentation

**Example**:
```markdown
# Basic Usage of ras-commander

This notebook demonstrates the basic workflow for executing HEC-RAS plans
using ras-commander.
```

**Why Required**:
- mkdocs-jupyter uses H1 for page title
- Missing H1 → title becomes filename ("01_basic_usage")
- H1 provides context in documentation site

### Title Best Practices

**✅ Good Titles**:
```markdown
# Basic Usage of ras-commander
# Parallel Execution with Multiple Plans
# Extracting Results from HDF Files
# Real-Time Monitoring with Stream Callbacks
```

**❌ Bad Titles**:
```markdown
# Example  # Too generic
# Test  # Unclear purpose
# 01_basic_usage  # Redundant with filename
```

## Cell Organization

### Recommended Structure

1. **Title Cell** (Markdown, H1)
   ```markdown
   # Notebook Title

   Brief description of what this notebook demonstrates.
   ```

2. **Setup Cell** (Code)
   ```python
   from pathlib import Path
   import sys

   # Flexible imports
   try:
       from ras_commander import init_ras_project, RasCmdr
   except ImportError:
       current_file = Path(__file__).resolve()
       parent_directory = current_file.parent.parent
       sys.path.append(str(parent_directory))
       from ras_commander import init_ras_project, RasCmdr
   ```

3. **Extract Example Project** (Code)
   ```python
   from ras_commander import RasExamples

   project_path = RasExamples.extract_project("Muncie")
   ```

4. **Main Content** (Alternating Code and Markdown)
   - Explain what you're about to do (Markdown)
   - Do it (Code)
   - Show results (Code output or Markdown)

5. **Cleanup** (Code, optional)
   ```python
   # Clean up extracted project
   import shutil
   shutil.rmtree(project_path.parent / "example_projects", ignore_errors=True)
   ```

## mkdocs-jupyter Configuration

### Current Settings

**mkdocs.yml**:
```yaml
plugins:
  - mkdocs-jupyter:
      include_source: true          # Show source code
      execute: false                # DON'T run during build
      include: ["notebooks/*.ipynb"]
      ignore: ["notebooks/example_projects/**"]
      ignore_h1_titles: true        # Use nav titles
```

### Setting Implications

**execute: false**:
- Notebooks NOT executed during doc build
- Must be pre-executed with outputs saved
- Faster builds, no HEC-RAS requirement

**Result**: Run notebooks locally, save outputs, commit

### Updating Notebooks

**Workflow**:
1. Edit notebook locally
2. Run all cells (`Kernel → Restart & Run All`)
3. Verify outputs look good
4. Save notebook (outputs included)
5. Commit to git

**Don't Commit**:
- Notebooks with errors
- Notebooks without outputs (if execute: false)
- Notebooks with absolute paths in outputs

## Content Guidelines

### Use RasExamples

**✅ Always extract example projects**:
```python
from ras_commander import RasExamples

# Good - reproducible
path = RasExamples.extract_project("Muncie")
```

**❌ Don't use hard-coded paths**:
```python
# Bad - only works on your machine
path = Path("/Users/me/Projects/Muncie")
```

### Show Expected Behavior

**Include assertions or verifications**:
```python
# Execute plan
RasCmdr.compute_plan("01")

# Verify HDF created
hdf_file = project_path / "Muncie.p01.hdf"
assert hdf_file.exists(), "HDF file should be created"

# Verify results
from ras_commander.hdf import HdfResultsPlan
hdf = HdfResultsPlan(hdf_file)
wse = hdf.get_wse(time_index=-1)
print(f"✓ Extracted {len(wse)} water surface elevations")
```

**Why**: Shows users what to expect, serves as validation

### Explain, Don't Just Show

**Bad** (code only):
```python
RasCmdr.compute_plan("01", dest_folder="/output", num_cores=4)
```

**Good** (explain first):
```markdown
### Execute Plan with Custom Settings

We'll run the plan in a separate folder to preserve the original project,
using 4 CPU cores for faster computation.
```
```python
RasCmdr.compute_plan(
    "01",
    dest_folder="/output/run1",
    num_cores=4
)
```

## Markdown Cells

### Section Headers

**Use ## for major sections**:
```markdown
## Setup

## Execute Plan

## Extract Results

## Cleanup
```

**Why**: H1 reserved for title, H2 for sections, H3+ for subsections

### Code Examples in Markdown

**Inline code**: Use backticks
```markdown
The `compute_plan()` function executes a HEC-RAS plan.
```

**Code blocks**: Use triple backticks with language
````markdown
```python
from ras_commander import RasCmdr
RasCmdr.compute_plan("01")
```
````

### Links and References

**Internal links to other notebooks**:
```markdown
See [Parallel Execution](02_parallel_execution.ipynb) for running multiple plans.
```

**External links**:
```markdown
For more information, see the [HEC-RAS documentation](https://www.hec.usace.army.mil/software/hec-ras/).
```

## Code Cells

### Output Display

**Print Important Information**:
```python
print(f"Project: {project_path}")
print(f"Plans found: {len(ras.plan_df)}")
print(f"Geometry files: {len(ras.geom_df)}")
```

**Show DataFrames**:
```python
# Show first few rows
ras.plan_df.head()

# Or specific columns
ras.plan_df[['plan_id', 'plan_title', 'geom_file']].head()
```

**Visualizations**:
```python
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 6))
plt.plot(time_series['datetime'], time_series['wse'])
plt.xlabel('Date')
plt.ylabel('Water Surface Elevation (ft)')
plt.title('Hydrograph at Cross Section 12345')
plt.grid(True)
plt.show()
```

### Error Handling

**Show how to handle common errors**:
```python
try:
    RasCmdr.compute_plan("01")
except FileNotFoundError as e:
    print(f"Error: {e}")
    print("Make sure project is initialized first")
```

## Testing Notebooks

### nbmake Integration

**Run notebooks as tests**:
```bash
# Test all notebooks
pytest --nbmake examples/*.ipynb

# Test specific notebook
pytest --nbmake examples/01_basic_usage.ipynb
```

**Requirements**:
```bash
pip install pytest pytest-nbmake
```

### Making Notebooks Testable

**✅ DO**:
- Use RasExamples (reproducible)
- Include cleanup (remove temp files)
- Handle errors gracefully
- Keep execution time reasonable (<5 min)

**❌ DON'T**:
- Require user input
- Use absolute paths
- Leave large files uncommitted
- Have side effects between cells

## Common Pitfalls

### ❌ Missing H1 Title

**Problem**:
```python
# First cell is code, not markdown
from ras_commander import RasCmdr
```

**Result**: Documentation title is "01_basic_usage" (filename)

**Fix**: Add markdown cell with H1 first

### ❌ Hard-Coded Paths

**Problem**:
```python
project_path = Path("/Users/billk/Documents/Projects/Muncie")
```

**Result**: Notebook only works on your machine

**Fix**: Use RasExamples

### ❌ Not Running Before Committing

**Problem**: Committed notebook has no outputs

**Result**: Documentation shows code but no results (if execute: false)

**Fix**: Run `Kernel → Restart & Run All` before committing

### ❌ Absolute Paths in Output

**Problem**: Output shows `/Users/billk/...`

**Result**: Confusing for users (different paths)

**Fix**: Use relative paths or Path.name in output

## Notebook Naming

### Convention

**Format**: `##_descriptive_name.ipynb`

**Examples**:
- `01_basic_usage.ipynb`
- `02_parallel_execution.ipynb`
- `15_usgs_gauge_integration.ipynb`

**Why Two Digits**: Allows up to 99 notebooks, sorts correctly

### Naming Guidelines

**✅ Good Names**:
- Descriptive (describes content)
- Lowercase with underscores
- Numbered for ordering
- Concise but clear

**❌ Bad Names**:
- `test.ipynb` (too generic)
- `MyNotebook.ipynb` (wrong case)
- `notebook_about_how_to_use_ras_commander_to_execute_plans.ipynb` (too long)

## Metadata

### Kernel Selection

**Recommended**: Python 3

**Set in notebook metadata**:
```json
{
  "kernelspec": {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3"
  }
}
```

### Clear All Outputs

**Before committing** (optional):
- Use `Edit → Clear All Outputs` to reduce file size
- Useful for notebooks with large outputs
- Re-run before building docs if execute: false

**Keep Outputs** (recommended):
- If execute: false in mkdocs.yml
- Shows results in documentation
- Helps users verify expected behavior

## Documentation Build

### Local Preview

```bash
# Create notebooks folder
cp -r examples docs/notebooks

# Build and serve
mkdocs serve

# View at http://127.0.0.1:8000
```

### Check Rendering

**Verify**:
1. Title appears correctly (H1 from first cell)
2. Code cells render with syntax highlighting
3. Outputs display properly
4. Images/plots show
5. Links work

## See Also

- **MkDocs Config**: `.claude/rules/documentation/mkdocs-config.md`
- **Testing**: `.claude/rules/testing/tdd-approach.md`
- **Import Patterns**: `.claude/rules/python/import-patterns.md`

---

**Key Takeaway**: Every notebook MUST have H1 title in first markdown cell. Use RasExamples for reproducibility. Run all cells before committing (if execute: false in mkdocs.yml).
