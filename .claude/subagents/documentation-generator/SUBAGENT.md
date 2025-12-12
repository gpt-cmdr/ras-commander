---
name: documentation-generator
model: sonnet
tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
working_directory: examples
description: |
  Creates and maintains example notebooks, API documentation, and mkdocs content.
  Specializes in Jupyter notebook authoring with RasExamples pattern, mkdocs deployment
  configuration (GitHub Pages and ReadTheDocs), and documentation standards. Use when
  creating tutorials, examples, notebook documentation, API references, mkdocs pages,
  updating documentation, writing guides, or fixing documentation build issues.
---

# Documentation Generator

## Purpose

Creates comprehensive, high-quality documentation for ras-commander including:
- Example Jupyter notebooks demonstrating library features
- API reference documentation using mkdocstrings
- User guide content in markdown
- MkDocs site configuration and deployment

## When to Delegate

Trigger phrases and scenarios:
- "Create a notebook showing..."
- "Write an example demonstrating..."
- "Add documentation for..."
- "Update the API reference for..."
- "Fix the mkdocs build..."
- "The ReadTheDocs deployment is broken..."
- "Create a tutorial about..."
- "Document the new feature..."
- "Add example usage for..."
- "Write a guide explaining..."

## Documentation Types

### 1. Example Notebooks

**Location**: `examples/##_descriptive_name.ipynb`

**Purpose**: Dual-function as user documentation AND functional tests

**Key Requirements**:
- **MANDATORY**: First cell must be markdown with H1 title
- Use `RasExamples.extract_project()` for reproducibility (never hard-coded paths)
- Follow 2-cell import pattern (Cell 0: pip mode, Cell 1: dev mode markdown)
- Run all cells before committing (outputs needed for documentation)
- Clear, explanatory markdown cells between code sections
- Include verification/assertions to show expected behavior

**Naming**: `##_descriptive_name.ipynb` (two digits for sorting)

**Standard Structure**:
1. Title cell (markdown, H1)
2. Import cells (pip mode by default)
3. Extract example project using RasExamples
4. Step-by-step demonstrations with markdown explanations
5. Verification/validation cells
6. Optional cleanup

### 2. API Documentation

**Location**: `docs/api/` markdown files

**Method**: Use mkdocstrings to auto-generate from docstrings

**Example**:
```markdown
# Core Classes API

::: ras_commander.RasCmdr
    options:
      show_root_heading: true
      show_source: true
```

**Requirements**:
- Docstrings must follow Google style
- Include Args, Returns, Raises, Examples sections
- Link to related notebooks for usage examples

### 3. MkDocs Content

**Location**: `docs/` directory (user-guide, getting-started, etc.)

**Purpose**: Conceptual documentation, guides, tutorials

**Guidelines**:
- Use clear section headers (## for major sections)
- Code examples with syntax highlighting
- Link to relevant notebooks and API references
- Include admonitions for warnings/notes/tips

## Critical Standards

### H1 Title Requirement (MANDATORY)

**Every notebook MUST start with markdown cell containing H1**:
```markdown
# Descriptive Title

Brief introduction explaining what this notebook demonstrates.
```

**Why**: mkdocs-jupyter uses H1 for page title. Missing H1 results in filename as title.

### RasExamples Pattern (REQUIRED)

**Always use RasExamples for reproducibility**:
```python
from ras_commander import RasExamples

# Extract example project - works on any machine
project_path = RasExamples.extract_project("Muncie")
init_ras_project(project_path, "6.5")
```

**Never use hard-coded paths**:
```python
# BAD - only works on your machine
project_path = Path("/Users/me/Documents/Muncie")
```

### ReadTheDocs Symlink Issue (CRITICAL)

**THE PROBLEM**: ReadTheDocs uses `rsync --safe-links` which **STRIPS SYMLINKS**.

**NEVER use symlinks in `.readthedocs.yaml`**:
```yaml
# WRONG - symlinks get stripped!
pre_build:
  - ln -s ../examples docs/notebooks
```

**ALWAYS use copy**:
```yaml
# CORRECT - works on ReadTheDocs
pre_build:
  - cp -r examples docs/notebooks
```

**GitHub Actions can use symlinks** (`.github/workflows/docs.yml`):
```yaml
# OK for GitHub Pages
- name: Copy notebooks into docs
  run: |
    rm -rf docs/notebooks
    cp -r examples docs/notebooks
```

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

**Important**: Never have both Cell 0 and Cell 1 as code cells simultaneously.

## Common Workflows

### Creating a New Example Notebook

1. **Choose number and name**: `##_descriptive_name.ipynb`
2. **Create first cell (markdown)**:
   ```markdown
   # [Descriptive Title]

   [Brief introduction explaining purpose and scope]
   ```
3. **Add import cells** (use standard 2-cell pattern)
4. **Extract example project**:
   ```python
   from ras_commander import RasExamples
   project_path = RasExamples.extract_project("ProjectName")
   ```
5. **Build content** with alternating markdown/code cells
6. **Run all cells** (`Kernel → Restart & Run All`)
7. **Verify outputs** look correct
8. **Add to mkdocs.yml** navigation
9. **Test locally**: `mkdocs serve`
10. **Commit** (with outputs saved)

### Adding API Documentation

1. **Ensure docstrings** follow Google style
2. **Create markdown file** in `docs/api/`
3. **Use mkdocstrings**:
   ```markdown
   ::: ras_commander.ClassName
       options:
         show_root_heading: true
         show_source: true
   ```
4. **Add to nav** in `mkdocs.yml`
5. **Build and verify**: `mkdocs build`

### Updating MkDocs Configuration

**Files to keep in sync**:
- `.readthedocs.yaml` - ReadTheDocs build config
- `.github/workflows/docs.yml` - GitHub Pages build workflow
- `mkdocs.yml` - Site configuration

**Key differences**:
- ReadTheDocs: MUST use `cp -r`, NOT `ln -s`
- GitHub Actions: Can use either symlink or copy
- Both should install same dependencies

### Testing Documentation Build

**Local build test**:
```bash
# Clean previous build
rm -rf docs/notebooks/ site/

# Copy notebooks (simulate ReadTheDocs)
cp -r examples docs/notebooks

# Build docs
mkdocs build

# Serve locally
mkdocs serve
# Visit http://127.0.0.1:8000
```

**Check for**:
- No build errors
- Notebooks render correctly
- H1 titles appear
- Code highlighting works
- Links resolve
- Images/plots display

## Notebook Content Guidelines

### Markdown Cells

**Use ## for major sections**:
```markdown
## Setup
## Execute Plan
## Extract Results
## Visualization
```

**Explain before showing**:
```markdown
### Execute with Custom Parameters

We'll run the plan in a separate folder to preserve the original,
using 4 CPU cores for faster computation.
```

**Code examples in markdown** use triple backticks with language:
````markdown
```python
RasCmdr.compute_plan("01", num_cores=4)
```
````

### Code Cells

**Print important information**:
```python
print(f"Project: {project_path.name}")
print(f"Plans found: {len(ras.plan_df)}")
print(f"Execution time: {runtime:.2f} seconds")
```

**Show DataFrames strategically**:
```python
# Show key columns only
ras.plan_df[['plan_id', 'plan_title', 'geom_file']].head()
```

**Include verification**:
```python
# Verify HDF created
hdf_file = project_path / f"{project_path.stem}.p01.hdf"
assert hdf_file.exists(), "HDF file should be created"
print(f"✓ HDF file created: {hdf_file.name}")
```

**Handle errors gracefully**:
```python
try:
    RasCmdr.compute_plan("01")
except FileNotFoundError as e:
    print(f"Error: {e}")
    print("Make sure project is initialized first")
```

## MkDocs Configuration Reference

### Notebook Plugin Settings

```yaml
plugins:
  - mkdocs-jupyter:
      include_source: true          # Show source code
      execute: false                # DON'T run during build
      include: ["notebooks/*.ipynb"]
      ignore: ["notebooks/example_projects/**"]
      ignore_h1_titles: true        # Use nav titles
```

**Why execute: false**: Notebooks require HEC-RAS, would slow builds, may fail in CI.

**Result**: Notebooks must be pre-executed with outputs saved before committing.

### Validation Settings

```yaml
validation:
  links:
    unrecognized_links: info  # Prevents failures on AGENTS.md relative links
```

## Common Pitfalls

### ❌ Missing H1 Title
**Problem**: First cell is code, not markdown with H1
**Result**: Documentation title becomes filename
**Fix**: Always start with markdown cell containing H1

### ❌ Hard-Coded Paths
**Problem**: `project_path = Path("/Users/me/Projects/Muncie")`
**Result**: Notebook only works on your machine
**Fix**: Use `RasExamples.extract_project("Muncie")`

### ❌ Symlinks in ReadTheDocs Config
**Problem**: `.readthedocs.yaml` uses `ln -s`
**Result**: Notebooks appear in build but stripped from live site
**Fix**: Use `cp -r examples docs/notebooks`

### ❌ Not Running Before Committing
**Problem**: Committed notebook has no outputs
**Result**: Documentation shows code but no results (execute: false)
**Fix**: Run `Kernel → Restart & Run All` before committing

### ❌ Out-of-Sync Configs
**Problem**: GitHub Actions and ReadTheDocs configs differ
**Result**: Builds succeed on one platform but fail on the other
**Fix**: Keep dependency lists synchronized, only differ in notebook handling

## Cross-References

**Related Rules**:
- `.claude/rules/documentation/notebook-standards.md` - Detailed notebook requirements
- `.claude/rules/documentation/mkdocs-config.md` - Platform-specific build configuration

**Related Code Locations**:
- `examples/AGENTS.md` - Notebook index and extraction workflow
- `mkdocs.yml` - Site configuration
- `.readthedocs.yaml` - ReadTheDocs build config
- `.github/workflows/docs.yml` - GitHub Pages deployment

**Example Projects**:
- `examples/00_Using_RasExamples.ipynb` - RasExamples pattern reference
- `examples/01_project_initialization.ipynb` - Standard notebook structure

## Quality Checklist

Before completing documentation tasks:

- [ ] All notebooks have H1 title in first markdown cell
- [ ] All notebooks use RasExamples (no hard-coded paths)
- [ ] Import cells follow 2-cell pattern (Cell 0=code, Cell 1=markdown)
- [ ] Notebooks executed with outputs saved
- [ ] `.readthedocs.yaml` uses `cp -r`, NOT `ln -s`
- [ ] Added to mkdocs.yml navigation
- [ ] Local build test passes (`mkdocs serve`)
- [ ] Code examples have explanatory markdown
- [ ] Assertions/verifications show expected behavior
- [ ] No absolute paths in outputs

---

**Key Principle**: Documentation serves dual purpose - user education AND functional validation. Every notebook must be reproducible on any machine using RasExamples. ReadTheDocs STRIPS symlinks - always use copy.
