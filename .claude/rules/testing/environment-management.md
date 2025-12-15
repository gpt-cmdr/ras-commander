# Testing Environment Management

**Context**: Virtual environment setup for testing notebooks and scripts
**Priority**: High - affects all testing and development workflows
**Auto-loads**: Yes (applies to testing tasks)

## Overview

ras-commander uses specific environment management approaches for different development and testing scenarios:

- **Agent scripts and tools**: Use `uv` and `python`
- **Jupyter notebook testing**: Use dedicated Anaconda environments

## Key Decision: No Editable Install for Development

**CRITICAL**: The `rascmdr_local` environment does NOT use `pip install -e .`

Instead, developers use a **toggle cell** in Jupyter notebooks that manipulates `sys.path` to load local source code. This approach:
- Guarantees local source is always loaded (even if pip package exists)
- Is simple to understand and explain
- Works reliably across all environments
- Can be toggled with a single variable

### Why sys.path.insert(0, ...) Works

Python searches `sys.path` in order (index 0 first). By inserting the local repo path at position 0:
1. Python finds `ras_commander/` in the repo first
2. The pip-installed package (if any) is never reached
3. 100% guaranteed local source loading

## Agent Scripts and Tools

### Use uv for Development

**All agent scripts, tools, and utilities should use `uv` for environment management:**

```bash
# Create virtual environment with uv
uv venv .venv

# Activate environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies ONLY (NOT ras-commander itself)
uv pip install h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona pytest
```

**Why uv**:
- Fast dependency resolution
- Reliable package installation
- Modern Python tooling
- Consistent with project standards

**When to use**:
- Running agent scripts
- Development tools
- CLI utilities
- Quick testing scripts

## Jupyter Notebook Testing Environments

### Two Testing Environments

ras-commander uses **two dedicated Anaconda environments** for notebook testing:

1. **`rascmdr_local`** - Dependencies only (uses toggle cell to load local source)
2. **`RasCommander`** - Published pip package version (standard user environment)

### Environment 1: rascmdr_local (Local Development)

**Purpose**: Test notebooks with local development code changes

**When to use**:
- ✅ Making changes to ras-commander library code
- ✅ Testing new features before release
- ✅ Debugging library issues
- ✅ Validating bug fixes
- ✅ Development workflow

**Setup**:
```bash
# Create Anaconda environment
conda create -n rascmdr_local python=3.13

# Activate environment
conda activate rascmdr_local

# Install DEPENDENCIES ONLY - NOT ras-commander itself
pip install h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona

# Install notebook dependencies
pip install jupyter notebook ipykernel

# Register kernel for Jupyter
python -m ipykernel install --user --name rascmdr_local --display-name "Python (rascmdr_local)"
```

**NEVER run `pip install -e .` or `pip install ras-commander` in rascmdr_local!**

**Usage in Jupyter**:
1. Start Jupyter: `jupyter notebook`
2. Open notebook in `examples/`
3. Select kernel: **Kernel → Change Kernel → Python (rascmdr_local)**
4. Ensure toggle cell has `USE_LOCAL_SOURCE = True`
5. Run toggle cell first, then rest of notebook

**Standard Toggle Cell** (included in all example notebooks):
```python
# =============================================================================
# DEVELOPMENT MODE TOGGLE
# =============================================================================
USE_LOCAL_SOURCE = True  # <-- TOGGLE THIS

if USE_LOCAL_SOURCE:
    import sys
    from pathlib import Path
    local_path = str(Path.cwd().parent)
    if local_path not in sys.path:
        sys.path.insert(0, local_path)
    print(f"📁 LOCAL SOURCE MODE: Loading from {local_path}/ras_commander")
else:
    print("📦 PIP PACKAGE MODE: Loading installed ras-commander")

from ras_commander import *
import ras_commander
print(f"✓ Loaded: {ras_commander.__file__}")
```

**Validation**:
```python
# In notebook cell, verify using local version
import ras_commander
print(ras_commander.__file__)
# Should show: C:\GH\ras-commander\ras_commander\__init__.py (or similar local path)
# Should NOT contain 'site-packages'
```

### Environment 2: RasCommander (Published Package)

**Purpose**: Test notebooks with published pip package (standard user environment)

**When to use**:
- ✅ Testing as end-users will experience
- ✅ Validating published package works correctly
- ✅ Regression testing against stable release
- ✅ Documentation verification
- ✅ User support (reproducing reported issues)

**Setup**:
```bash
# Create Anaconda environment
conda create -n RasCommander python=3.13

# Activate environment
conda activate RasCommander

# Install published package from PyPI
pip install ras-commander

# Install notebook dependencies
pip install jupyter notebook ipykernel

# Register kernel for Jupyter
python -m ipykernel install --user --name RasCommander --display-name "Python (RasCommander)"
```

**Usage in Jupyter**:
1. Start Jupyter: `jupyter notebook`
2. Open notebook in `examples/`
3. Select kernel: **Kernel → Change Kernel → Python (RasCommander)**
4. Set toggle cell to `USE_LOCAL_SOURCE = False`
5. Run notebook cells - uses published package

**Validation**:
```python
# In notebook cell, verify using pip package
import ras_commander
print(ras_commander.__file__)
# Should show: .../site-packages/ras_commander/__init__.py
```

## Environment Selection Guide

### Decision Matrix

| Scenario | Environment | Toggle Setting | Rationale |
|----------|-------------|----------------|-----------|
| Testing code changes | `rascmdr_local` | `True` | See immediate impact of changes |
| Validating bug fix | `rascmdr_local` | `True` | Test fix before release |
| Running example notebooks (user) | `RasCommander` | `False` | Matches user experience |
| Updating documentation | `RasCommander` | `False` | Ensure examples work for users |
| Debugging user issue | `RasCommander` | `False` | Reproduce user's environment |
| Pre-release testing | Both | Both | Verify local changes + published package |
| Agent scripts/tools | `uv venv` | N/A | Fast, modern tooling |

## Workflow Examples

### Example 1: Testing New Feature

**Scenario**: Adding new HDF extraction method

```bash
# 1. Make code changes in ras_commander/hdf/
vim ras_commander/hdf/results.py

# 2. Test with local environment
conda activate rascmdr_local
jupyter notebook examples/11_2d_hdf_data_extraction.ipynb

# 3. In notebook: USE_LOCAL_SOURCE = True (default for devs)
# Run toggle cell, then test cells - uses LOCAL code

# 4. Commit and release changes
git commit -am "Add new HDF extraction method"

# 5. After PyPI release, test with pip environment
conda activate RasCommander
pip install --upgrade ras-commander
jupyter notebook examples/11_2d_hdf_data_extraction.ipynb

# 6. In notebook: USE_LOCAL_SOURCE = False
# Run notebook - verify published package works
```

### Example 2: Validating Example Notebooks

**Scenario**: Ensuring notebooks work for end-users

```bash
# Use pip environment to match user experience
conda activate RasCommander

# Ensure latest published version
pip install --upgrade ras-commander

# Test all notebooks
cd examples
jupyter notebook

# For each notebook:
# 1. Select kernel: Python (RasCommander)
# 2. Set USE_LOCAL_SOURCE = False in toggle cell
# 3. Restart kernel and run all cells
# 4. Verify no errors
```

### Example 3: Debugging User-Reported Issue

**Scenario**: User reports notebook error

```bash
# Reproduce in pip environment
conda activate RasCommander

# Install exact version user reported
pip install ras-commander==1.2.3

# Run problematic notebook
jupyter notebook examples/18_breach_results_extraction.ipynb

# Set USE_LOCAL_SOURCE = False, run notebook
# Reproduce error

# Switch to local environment to test fix
conda activate rascmdr_local

# Make fix in code
vim ras_commander/hdf/breach.py

# Test fix with local source
jupyter notebook examples/18_breach_results_extraction.ipynb
# Set USE_LOCAL_SOURCE = True
# Run notebook - verify fix works
```

## Environment Maintenance

### Updating rascmdr_local

**When dependencies change**:
```bash
conda activate rascmdr_local

# Reinstall dependencies
pip install --upgrade h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona
```

**When code changes**: Just restart the Jupyter kernel - the toggle cell reloads local source automatically.

### Updating RasCommander

**When new version published**:
```bash
conda activate RasCommander

# Upgrade to latest published version
pip install --upgrade ras-commander

# Or install specific version
pip install ras-commander==1.2.3
```

### Recreating Environments

**If environment becomes corrupted**:

```bash
# Delete old environment
conda env remove -n rascmdr_local
# or
conda env remove -n RasCommander

# Recreate following setup instructions above
```

## CI/CD Integration

### GitHub Actions Testing

**Use both approaches in CI pipeline**:

```yaml
name: Test Notebooks

on: [push, pull_request]

jobs:
  test-local:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2

      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.13'

      - name: Install dependencies
        run: pip install h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona pytest pytest-nbmake

      - name: Test notebooks with local version
        run: pytest --nbmake examples/*.ipynb
        # Toggle cell defaults to USE_LOCAL_SOURCE = True

  test-RasCommander:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2

      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.13'

      - name: Install published package
        run: pip install ras-commander pytest pytest-nbmake

      - name: Test notebooks with RasCommander package
        run: pytest --nbmake examples/*.ipynb
        # Note: Notebooks should have USE_LOCAL_SOURCE = False for pip testing
```

## Troubleshooting

### Notebook Using Wrong Environment

**Problem**: Notebook runs with wrong kernel

**Solution**:
```python
# Check in notebook cell
import sys
print(sys.executable)
# Should show path to correct environment

# If wrong, select correct kernel:
# Kernel → Change Kernel → Python (rascmdr_local or RasCommander)
```

### Import Errors in Local Environment

**Problem**: `ModuleNotFoundError` in rascmdr_local

**Solution**:
1. Make sure toggle cell has `USE_LOCAL_SOURCE = True`
2. Run the toggle cell before any imports
3. Verify `Path.cwd().parent` points to repo root:
   ```python
   from pathlib import Path
   print(Path.cwd())  # Should be .../examples
   print(Path.cwd().parent)  # Should be repo root
   ```

### Local Changes Not Showing

**Problem**: Changes to code not reflected in notebook

**Solution**:
```python
# In notebook, restart kernel:
# Kernel → Restart

# Then re-run the toggle cell (it will reload local source)
```

### Wrong Source Loading

**Problem**: Pip package loading instead of local source

**Solution**:
```python
# After imports, check where it loaded from:
import ras_commander
print(ras_commander.__file__)

# If shows 'site-packages', your toggle cell isn't working
# Verify USE_LOCAL_SOURCE = True and run toggle cell FIRST
```

## Best Practices

### ✅ DO

- Use `rascmdr_local` with `USE_LOCAL_SOURCE = True` when making code changes
- Use `RasCommander` with `USE_LOCAL_SOURCE = False` for user-facing documentation
- Test with both environments before releases
- Use `uv` for agent scripts and tools
- Keep dependencies updated
- Document which environment was used for testing
- Always run toggle cell first in notebooks

### ❌ DON'T

- Install ras-commander via pip in rascmdr_local environment
- Use `pip install -e .` in rascmdr_local (we use toggle cell instead)
- Mix development code with pip package testing
- Use base conda environment for testing
- Forget to select correct kernel in Jupyter
- Skip testing with RasCommander environment before release
- Use `RasCommander` when debugging library code

## Quick Reference

### Environment Commands

```bash
# Create environments (one-time setup)
conda create -n rascmdr_local python=3.13
conda create -n RasCommander python=3.13

# Activate environments
conda activate rascmdr_local  # For development
conda activate RasCommander   # For pip testing

# Install in each environment
# rascmdr_local (dependencies only):
pip install h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona jupyter ipykernel

# RasCommander (pip package):
pip install ras-commander jupyter ipykernel

# List environments
conda env list

# Remove environment
conda env remove -n rascmdr_local
conda env remove -n RasCommander
```

### Jupyter Kernel Selection

```bash
# List available kernels
jupyter kernelspec list

# Register kernel
python -m ipykernel install --user --name rascmdr_local --display-name "Python (rascmdr_local)"

# Remove kernel
jupyter kernelspec uninstall rascmdr_local
```

## See Also

- **Import Patterns**: `.claude/rules/python/import-patterns.md` - Flexible imports for notebooks
- **Testing Approach**: `.claude/rules/testing/tdd-approach.md` - Testing with example projects
- **Notebook Standards**: `.claude/rules/documentation/notebook-standards.md` - Notebook best practices
- **Environment Manager Subagent**: `.claude/agents/python-environment-manager.md` - Automated setup
- **Example Toggle Cell**: `examples/00_Using_RasExamples.ipynb`

---

**Key Takeaway**: Use `rascmdr_local` (dependencies only + toggle cell) when making code changes, `RasCommander` (published package) when testing user experience, and `uv` for agent scripts and tools. Never use `pip install -e .` - the toggle cell with `sys.path.insert(0, ...)` guarantees local source loading.
