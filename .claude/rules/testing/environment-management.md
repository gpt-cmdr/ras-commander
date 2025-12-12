# Testing Environment Management

**Context**: Virtual environment setup for testing notebooks and scripts
**Priority**: High - affects all testing and development workflows
**Auto-loads**: Yes (applies to testing tasks)

## Overview

ras-commander uses specific environment management approaches for different development and testing scenarios:

- **Agent scripts and tools**: Use `uv` and `python`
- **Jupyter notebook testing**: Use dedicated Anaconda environments

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

# Install dependencies
uv pip install -e .
uv pip install jupyter pytest
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

1. **`rascmdr_local`** - Local development version
2. **`rascmdr_pip`** - Published pip package version

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
conda create -n rascmdr_local python=3.10

# Activate environment
conda activate rascmdr_local

# Install ras-commander in editable mode (uses local code)
pip install -e .

# Install notebook dependencies
pip install jupyter notebook ipykernel

# Register kernel for Jupyter
python -m ipykernel install --user --name rascmdr_local --display-name "Python (rascmdr_local)"
```

**Usage in Jupyter**:
1. Start Jupyter: `jupyter notebook`
2. Open notebook in `examples/`
3. Select kernel: **Kernel → Change Kernel → Python (rascmdr_local)**
4. Run notebook cells - uses local development code

**Validation**:
```python
# In notebook cell, verify using local version
import ras_commander
print(ras_commander.__file__)
# Should show: /path/to/ras-commander/ras_commander/__init__.py
```

### Environment 2: rascmdr_pip (Published Package)

**Purpose**: Test notebooks with published pip package

**When to use**:
- ✅ Testing as end-users will experience
- ✅ Validating published package works correctly
- ✅ Regression testing against stable release
- ✅ Documentation verification
- ✅ User support (reproducing reported issues)

**Setup**:
```bash
# Create Anaconda environment
conda create -n rascmdr_pip python=3.10

# Activate environment
conda activate rascmdr_pip

# Install published package from PyPI
pip install ras-commander

# Install notebook dependencies
pip install jupyter notebook ipykernel

# Register kernel for Jupyter
python -m ipykernel install --user --name rascmdr_pip --display-name "Python (rascmdr_pip)"
```

**Usage in Jupyter**:
1. Start Jupyter: `jupyter notebook`
2. Open notebook in `examples/`
3. Select kernel: **Kernel → Change Kernel → Python (rascmdr_pip)**
4. Run notebook cells - uses published package

**Validation**:
```python
# In notebook cell, verify using pip package
import ras_commander
print(ras_commander.__file__)
# Should show: /path/to/anaconda/envs/rascmdr_pip/lib/python3.10/site-packages/ras_commander/__init__.py
```

## Environment Selection Guide

### Decision Matrix

| Scenario | Environment | Rationale |
|----------|-------------|-----------|
| Testing code changes | `rascmdr_local` | See immediate impact of changes |
| Validating bug fix | `rascmdr_local` | Test fix before release |
| Running example notebooks | `rascmdr_pip` | Matches user experience |
| Updating documentation | `rascmdr_pip` | Ensure examples work for users |
| Debugging user issue | `rascmdr_pip` | Reproduce user's environment |
| Pre-release testing | Both | Verify local changes + published package |
| Agent scripts/tools | `uv venv` | Fast, modern tooling |

## Workflow Examples

### Example 1: Testing New Feature

**Scenario**: Adding new HDF extraction method

```bash
# 1. Make code changes in ras_commander/hdf/
vim ras_commander/hdf/results.py

# 2. Test with local environment
conda activate rascmdr_local
jupyter notebook examples/11_2d_hdf_data_extraction.ipynb

# 3. Run notebook with kernel: Python (rascmdr_local)
# Verify new method works

# 4. Commit and release changes
git commit -am "Add new HDF extraction method"

# 5. After PyPI release, test with pip environment
conda activate rascmdr_pip
pip install --upgrade ras-commander
jupyter notebook examples/11_2d_hdf_data_extraction.ipynb

# 6. Run notebook with kernel: Python (rascmdr_pip)
# Verify published package works
```

### Example 2: Validating Example Notebooks

**Scenario**: Ensuring notebooks work for end-users

```bash
# Use pip environment to match user experience
conda activate rascmdr_pip

# Ensure latest published version
pip install --upgrade ras-commander

# Test all notebooks
cd examples
jupyter notebook

# For each notebook:
# 1. Select kernel: Python (rascmdr_pip)
# 2. Restart kernel and run all cells
# 3. Verify no errors
```

### Example 3: Debugging User-Reported Issue

**Scenario**: User reports notebook error

```bash
# Reproduce in pip environment
conda activate rascmdr_pip

# Install exact version user reported
pip install ras-commander==1.2.3

# Run problematic notebook
jupyter notebook examples/18_breach_results_extraction.ipynb

# Select kernel: Python (rascmdr_pip)
# Reproduce error

# Switch to local environment to test fix
conda activate rascmdr_local

# Make fix in code
vim ras_commander/hdf/breach.py

# Test fix
jupyter notebook examples/18_breach_results_extraction.ipynb
# Select kernel: Python (rascmdr_local)
# Verify fix works
```

## Environment Maintenance

### Updating rascmdr_local

**When code changes**:
```bash
conda activate rascmdr_local

# Editable install picks up changes automatically
# No reinstall needed for most changes

# For dependency changes (setup.py):
pip install -e .
```

### Updating rascmdr_pip

**When new version published**:
```bash
conda activate rascmdr_pip

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
conda env remove -n rascmdr_pip

# Recreate following setup instructions above
```

## CI/CD Integration

### GitHub Actions Testing

**Use both environments in CI pipeline**:

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
          python-version: '3.10'

      - name: Install local version
        run: pip install -e .

      - name: Test notebooks with local version
        run: pytest --nbmake examples/*.ipynb

  test-pip:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2

      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install published package
        run: pip install ras-commander

      - name: Test notebooks with pip version
        run: pytest --nbmake examples/*.ipynb
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
# Kernel → Change Kernel → Python (rascmdr_local or rascmdr_pip)
```

### Import Errors in Local Environment

**Problem**: `ModuleNotFoundError` in rascmdr_local

**Solution**:
```bash
# Reinstall in editable mode
conda activate rascmdr_local
pip install -e .

# Verify installation
python -c "import ras_commander; print(ras_commander.__file__)"
```

### Stale Code in Local Environment

**Problem**: Changes to code not reflected in notebook

**Solution**:
```python
# In notebook, restart kernel:
# Kernel → Restart

# For persistent issues, reload module:
import importlib
import ras_commander
importlib.reload(ras_commander)
```

## Best Practices

### ✅ DO

- Use `rascmdr_local` when making code changes
- Use `rascmdr_pip` for user-facing documentation
- Test with both environments before releases
- Use `uv` for agent scripts and tools
- Keep environments updated
- Document which environment was used for testing

### ❌ DON'T

- Mix development code with pip package testing
- Use base conda environment for testing
- Forget to select correct kernel in Jupyter
- Skip testing with pip environment before release
- Use `rascmdr_pip` when debugging library code

## Quick Reference

### Environment Commands

```bash
# Create environments (one-time setup)
conda create -n rascmdr_local python=3.10
conda create -n rascmdr_pip python=3.10

# Activate environments
conda activate rascmdr_local  # For development
conda activate rascmdr_pip    # For pip testing

# Install in each environment
# rascmdr_local:
pip install -e .

# rascmdr_pip:
pip install ras-commander

# List environments
conda env list

# Remove environment
conda env remove -n rascmdr_local
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
- **Root CLAUDE.md**: Development Environment section

---

**Key Takeaway**: Use `rascmdr_local` (editable install) when making code changes, `rascmdr_pip` (published package) when testing user experience, and `uv` for agent scripts and tools.
