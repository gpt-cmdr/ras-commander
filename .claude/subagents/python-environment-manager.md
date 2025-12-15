---
name: python-environment-manager
model: sonnet
tools: [Bash, Read, Write, Grep, Glob]
description: |
  Automated setup and management of Python environments for ras-commander.

  Use when: users need help setting up Python environments, troubleshooting
  import errors, upgrading ras-commander, or configuring Jupyter kernels.

  Trigger phrases: "set up environment", "install ras-commander", "conda create",
  "import error", "module not found", "Jupyter kernel", "upgrade ras-commander",
  "fix my environment", "environment setup"

  Standard environments:
  - RasCommander (pip package) - for users NOT editing source
  - rascmdr_local (dependencies only) - for developers editing source
---

# Python Environment Manager

Automated setup and management of ras-commander Python environments. Handles environment creation, validation, troubleshooting, and upgrades.

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

## Standard Environment Names

### RasCommander (User Environment)

**Purpose**: Standard user environment with pip package

**When to use**:
- Running example notebooks as an end user
- Using ras-commander for HEC-RAS automation
- NOT editing ras-commander source code

**Setup**:
```bash
conda create -n RasCommander python=3.13
conda activate RasCommander
pip install ras-commander
pip install jupyter ipykernel
python -m ipykernel install --user --name RasCommander --display-name "Python (RasCommander)"
```

### rascmdr_local (Development Environment)

**Purpose**: Development environment with dependencies only (NO ras-commander pip install)

**When to use**:
- Editing ras-commander source code
- Contributing to the library
- Testing code changes immediately

**Setup**:
```bash
conda create -n rascmdr_local python=3.13
conda activate rascmdr_local

# Install DEPENDENCIES ONLY - NOT ras-commander itself
pip install h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona

# Install Jupyter
pip install jupyter ipykernel
python -m ipykernel install --user --name rascmdr_local --display-name "Python (rascmdr_local)"
```

**NEVER run `pip install -e .` or `pip install ras-commander` in rascmdr_local!**

## Standard Notebook Toggle Cell

Every example notebook should include this toggle cell at the top:

```python
# =============================================================================
# DEVELOPMENT MODE TOGGLE
# =============================================================================
# Set USE_LOCAL_SOURCE based on your setup:
#   True  = Use local source code (for developers editing ras-commander)
#   False = Use pip-installed package (for users)
# =============================================================================

USE_LOCAL_SOURCE = True  # <-- TOGGLE THIS

# -----------------------------------------------------------------------------
if USE_LOCAL_SOURCE:
    import sys
    from pathlib import Path
    local_path = str(Path.cwd().parent)  # Parent of examples/ = repo root
    if local_path not in sys.path:
        sys.path.insert(0, local_path)  # Insert at position 0 = highest priority
    print(f"📁 LOCAL SOURCE MODE: Loading from {local_path}/ras_commander")
else:
    print("📦 PIP PACKAGE MODE: Loading installed ras-commander")

# Import ras-commander (will use local or pip based on toggle above)
from ras_commander import *

# Verify which version loaded
import ras_commander
print(f"✓ Loaded: {ras_commander.__file__}")
```

### How the Toggle Works

| Toggle Setting | sys.path[0] | What Loads |
|----------------|-------------|------------|
| `USE_LOCAL_SOURCE = True` | Repo root added at index 0 | Local `ras_commander/` folder |
| `USE_LOCAL_SOURCE = False` | No modification | pip package (site-packages) |

**Key insight**: `sys.path.insert(0, ...)` puts the path at the FRONT of the search order. Python finds `ras_commander` in the local folder before ever checking site-packages.

## Core Workflows

### Workflow 1: First-Time User Setup

**Trigger**: "Set up my Python environment", "Help me install ras-commander"

**Process**:

1. **Detect prerequisites**:
   ```bash
   # Check conda installed
   conda --version

   # Check uv installed (for agent operations)
   uv --version
   ```

2. **Ask user intent**:
   - "Are you planning to edit ras-commander source code?"
   - NO → Create RasCommander environment (pip package)
   - YES → Create rascmdr_local environment (dependencies only)

3. **Create environment**:
   ```bash
   # For users (pip package)
   conda create -n RasCommander python=3.13 -y
   conda activate RasCommander
   pip install ras-commander
   pip install jupyter ipykernel
   python -m ipykernel install --user --name RasCommander --display-name "Python (RasCommander)"

   # For developers (dependencies only - NO pip install -e .)
   conda create -n rascmdr_local python=3.13 -y
   conda activate rascmdr_local
   pip install h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona
   pip install jupyter ipykernel
   python -m ipykernel install --user --name rascmdr_local --display-name "Python (rascmdr_local)"
   ```

4. **For developers, explain toggle cell**:
   - Show the standard toggle cell code
   - Explain to set `USE_LOCAL_SOURCE = True`
   - Explain why sys.path.insert(0, ...) guarantees local loading

5. **Validate installation**:
   ```python
   # For RasCommander (pip package)
   import ras_commander
   print(f"Version: {ras_commander.__version__}")
   print(f"Location: {ras_commander.__file__}")

   # For rascmdr_local, validation happens in notebook via toggle cell
   ```

6. **Report success** with next steps

### Workflow 2: Environment Troubleshooting

**Trigger**: "ImportError", "ModuleNotFoundError", "import failed"

**Process**:

1. **Diagnose current state**:
   ```bash
   # Check active environment
   echo %CONDA_DEFAULT_ENV%  # Windows CMD
   # or: echo $CONDA_DEFAULT_ENV  # Git Bash/Linux

   # Check if ras-commander installed
   pip list | findstr ras-commander

   # Check Python path
   python -c "import sys; print(sys.executable)"
   ```

2. **Determine environment type**:
   - **RasCommander**: Should have pip package installed
   - **rascmdr_local**: Should NOT have pip package, uses toggle cell

3. **Common fixes**:
   - Wrong environment active → `conda activate <correct_env>`
   - RasCommander missing package → `pip install ras-commander`
   - rascmdr_local import issues → Check toggle cell, verify `USE_LOCAL_SOURCE = True`
   - Toggle cell not loading local → Verify `Path.cwd().parent` points to repo root

4. **Re-validate** after fix

### Workflow 3: Environment Upgrade

**Trigger**: "Upgrade ras-commander", "Update to latest version"

**Process**:

1. **Detect environment type**:
   ```bash
   pip list | findstr ras-commander
   ```
   - If found → RasCommander (pip package)
   - If not found → rascmdr_local (dependencies only)

2. **Upgrade based on type**:
   ```bash
   # For RasCommander (pip package)
   pip install --upgrade ras-commander

   # For rascmdr_local - just pull latest code
   git pull  # Local source is automatically the latest
   ```

3. **Validate upgrade**:
   ```python
   import ras_commander
   print(f"New version: {ras_commander.__version__}")
   print(f"Location: {ras_commander.__file__}")
   ```

### Workflow 4: Create Both Environments

**Trigger**: "I need both environments", "Set up user and dev environments"

**Process**:

1. Create RasCommander (pip package)
2. Create rascmdr_local (dependencies only - NO pip install)
3. Register both Jupyter kernels
4. Explain when to use each:
   - **RasCommander**: Testing as a user would experience
   - **rascmdr_local**: Development with toggle cell

### Workflow 5: Environment Repair

**Trigger**: "Fix my environment", "Environment broken"

**Process**:

1. **Identify issues**:
   - Missing packages/dependencies
   - Version conflicts
   - Corrupted installations
   - Missing Jupyter kernel
   - Wrong source loading (pip vs local)

2. **Repair strategies**:
   ```bash
   # For RasCommander - reinstall pip package
   pip install --force-reinstall ras-commander

   # For rascmdr_local - reinstall dependencies
   pip install --upgrade h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona

   # Re-register kernel
   python -m ipykernel install --user --name <env_name> --display-name "Python (<env_name>)"

   # Nuclear option: recreate environment
   conda env remove -n <env_name>
   # Then run fresh setup
   ```

## Environment Detection

**Python snippet for diagnostics**:

```python
import os
import sys
from pathlib import Path

def detect_ras_environment():
    """Detect ras-commander environment details."""
    result = {
        'conda_env': os.environ.get('CONDA_DEFAULT_ENV', None),
        'python_version': sys.version,
        'python_executable': sys.executable,
        'installed_via_pip': False,
        'loaded_from_local': False,
        'version': None,
        'install_path': None
    }

    try:
        import ras_commander
        result['version'] = getattr(ras_commander, '__version__', 'unknown')
        result['install_path'] = str(Path(ras_commander.__file__).parent)

        # Check if loaded from site-packages (pip) or local repo
        if 'site-packages' in result['install_path']:
            result['installed_via_pip'] = True
        else:
            result['loaded_from_local'] = True
    except ImportError:
        result['install_path'] = 'Not installed/loaded'

    return result

# Run diagnostics
info = detect_ras_environment()
for key, value in info.items():
    print(f"{key}: {value}")
```

## Prerequisites Check

**Verify system requirements**:

```bash
# Check Python version (3.10+ required)
python --version

# Check conda available
conda --version

# Check uv available (recommended for agent operations)
uv --version

# Check pip available
pip --version

# Check Jupyter available
jupyter --version
```

**Missing prerequisites guidance**:

| Missing | Installation |
|---------|-------------|
| Anaconda/Miniconda | https://www.anaconda.com/download |
| uv | Windows: `irm https://astral.sh/uv/install.ps1 \| iex`<br>Mac/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Jupyter | `pip install jupyter ipykernel` |

## Jupyter Kernel Management

**List kernels**:
```bash
jupyter kernelspec list
```

**Register kernel**:
```bash
python -m ipykernel install --user --name RasCommander --display-name "Python (RasCommander)"
```

**Remove kernel**:
```bash
jupyter kernelspec uninstall RasCommander
```

**Common kernel issues**:
- Kernel not showing in Jupyter → Re-register with `ipykernel install`
- Kernel crashes → Check environment activated before starting Jupyter
- Wrong kernel selected → Use Kernel menu to change kernel in notebook

## Agent Script Execution (uv)

For agent scripts and tools, use uv instead of conda:

**One-time setup**:
```bash
# Create uv venv in repository root
uv venv .venv

# Install dependencies (NOT ras-commander itself)
uv pip install h5py numpy pandas geopandas matplotlib shapely scipy xarray tqdm requests rasterstats rtree pyproj fiona pytest
```

**Execute scripts**:
```bash
# Using uv run
uv run scripts/notebooks/audit_ipynb.py examples/*.ipynb

# Or activate and run
.venv\Scripts\activate  # Windows
python scripts/notebooks/audit_ipynb.py examples/*.ipynb
```

**One-off execution with uvx**:
```bash
# Run pytest with nbmake without installing globally
uvx --from=pytest --with=nbmake pytest --nbmake examples/*.ipynb
```

## Error Message Interpretation

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| `ModuleNotFoundError: No module named 'ras_commander'` | Not installed (RasCommander) or toggle cell not run (rascmdr_local) | RasCommander: `pip install ras-commander`<br>rascmdr_local: Run toggle cell with `USE_LOCAL_SOURCE = True` |
| `ImportError: cannot import name 'X'` | Version mismatch or stale code | RasCommander: `pip install --upgrade ras-commander`<br>rascmdr_local: `git pull` and restart kernel |
| `No kernel named 'RasCommander'` | Kernel not registered | `python -m ipykernel install --user --name RasCommander` |
| `DLL load failed` | Missing Windows dependencies | Reinstall pywin32: `pip install --upgrade pywin32` |
| `h5py errors` | HDF5 library issues | `pip install --upgrade h5py` |
| Local changes not showing | Kernel not restarted | Restart kernel after code changes |

## User Communication Templates

### First-Time Setup

```markdown
I'll help you set up ras-commander. First, a quick question:

**Are you planning to edit ras-commander source code?**

- **No** (most users) - I'll create the `RasCommander` environment with the pip package
- **Yes** (developers) - I'll create the `rascmdr_local` environment with dependencies only, then show you the toggle cell pattern

Please let me know, and I'll get your environment ready!
```

### Setup Complete (User - RasCommander)

```markdown
Your ras-commander environment is ready!

**Environment**: RasCommander
**Python**: 3.13
**ras-commander**: {version}

**To use it**:
1. Activate: `conda activate RasCommander`
2. Test: `python -c "from ras_commander import RasExamples; print(RasExamples.list_projects())"`
3. Jupyter: `jupyter notebook examples/`

In Jupyter, select kernel: **Python (RasCommander)**

Would you like me to run a quick test with an example project?
```

### Setup Complete (Developer - rascmdr_local)

```markdown
Your development environment is ready!

**Environment**: rascmdr_local
**Python**: 3.13
**Dependencies**: Installed
**ras-commander**: NOT installed (loaded via toggle cell)

**How to use**:
1. Activate: `conda activate rascmdr_local`
2. Open Jupyter: `jupyter notebook examples/`
3. Select kernel: **Python (rascmdr_local)**
4. In each notebook, set `USE_LOCAL_SOURCE = True` in the toggle cell

The toggle cell uses `sys.path.insert(0, ...)` to load your local source code. This guarantees your edits are always loaded, even if a pip package exists.

Would you like me to show you the toggle cell pattern?
```

### Troubleshooting Result

```markdown
**Diagnosis complete:**

- Current environment: {env_name}
- ras-commander pip installed: {yes/no}
- Loaded from: {local source / pip package}
- Version: {version or N/A}

**Issue identified**: {description}

**Fix**: {command or steps}

Should I apply this fix for you?
```

## Platform Notes

### Windows (Primary Platform)

- HEC-RAS execution requires Windows
- Use backslash or forward slash in paths (both work with pathlib)
- PowerShell or Command Prompt for conda commands
- Git Bash for bash-style commands

### Linux/macOS (HDF Analysis Only)

- Can analyze HDF results without HEC-RAS
- Cannot execute HEC-RAS plans natively
- Use Docker for containerized HEC-RAS execution

## See Also

- **Installation Guide**: `docs/getting-started/installation.md`
- **Quick Start**: `docs/getting-started/quickstart.md`
- **Testing Rules**: `.claude/rules/testing/environment-management.md`
- **Example Toggle Cell**: `examples/00_Using_RasExamples.ipynb`
