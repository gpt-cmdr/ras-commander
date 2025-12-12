# Import Patterns

**Context**: Flexible imports for development vs installed package
**Priority**: Medium - affects example notebooks and development workflow
**Auto-loads**: Yes (applies to all Python code)

## Overview

ras-commander uses a flexible import pattern that works in both development (local repository) and production (installed package) scenarios. This pattern is especially important for example notebooks that need to run in various environments.

## Standard Import Pattern

### Flexibility Pattern

**Purpose**: Import works whether ras-commander is installed via pip or used from local repository

**Pattern**:
```python
from pathlib import Path
import sys

# Flexible imports for development vs installed package
try:
    # Try installed package first
    from ras_commander import init_ras_project, RasCmdr, RasPlan
except ImportError:
    # Fall back to local repository
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasCmdr, RasPlan
```

**Why This Works**:
1. **Installed Package**: If `pip install ras-commander` was run, first import succeeds
2. **Local Development**: If working from cloned repository, `sys.path.append()` makes local code importable
3. **Examples**: Example notebooks work in both scenarios without modification

## When to Use This Pattern

### ✅ Use in Example Notebooks

**All notebooks in `examples/` should use this pattern**:
```python
# examples/01_basic_usage.ipynb

from pathlib import Path
import sys

try:
    from ras_commander import init_ras_project, RasCmdr
    from ras_commander.hdf import HdfResultsPlan
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasCmdr
    from ras_commander.hdf import HdfResultsPlan
```

### ✅ Use in Standalone Scripts

**Scripts that might run in development or production**:
```python
# tools/my_utility.py

from pathlib import Path
import sys

try:
    from ras_commander import RasGeometry
except ImportError:
    # Assume script is in tools/ folder
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.append(str(repo_root))
    from ras_commander import RasGeometry
```

### ❌ DON'T Use in Library Code

**Library code in `ras_commander/` should use standard imports**:
```python
# ras_commander/core.py

# ✅ Simple imports (no try/except needed)
from pathlib import Path
from .hdf import HdfBase
from .logging_config import log_call

# Library code assumes it's installed or PYTHONPATH is set
```

## Variations by Location

### Pattern for Notebooks in `examples/`

**Location**: `examples/notebook.ipynb`
**Parent Directory**: Repository root (`examples/..`)

```python
from pathlib import Path
import sys

try:
    from ras_commander import RasCmdr
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent  # examples/.. = root
    sys.path.append(str(parent_directory))
    from ras_commander import RasCmdr
```

### Pattern for Scripts in `tools/`

**Location**: `tools/script.py`
**Parent Directory**: Repository root (`tools/..`)

```python
from pathlib import Path
import sys

try:
    from ras_commander import RasUtils
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent  # tools/.. = root
    sys.path.append(str(parent_directory))
    from ras_commander import RasUtils
```

### Pattern for Nested Scripts

**Location**: `examples/advanced/nested_script.py`
**Parent Directory**: Repository root (`examples/advanced/../..`)

```python
from pathlib import Path
import sys

try:
    from ras_commander import RasCmdr
except ImportError:
    current_file = Path(__file__).resolve()
    # Navigate up two levels: nested_script.py -> advanced/ -> examples/ -> root
    repo_root = current_file.parent.parent.parent
    sys.path.append(str(repo_root))
    from ras_commander import RasCmdr
```

## Best Practices

### ✅ Import Once at Top

**Group all ras-commander imports in one try/except block**:
```python
try:
    from ras_commander import init_ras_project, RasCmdr
    from ras_commander.hdf import HdfResultsPlan
    from ras_commander.usgs import RasUsgsCore
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasCmdr
    from ras_commander.hdf import HdfResultsPlan
    from ras_commander.usgs import RasUsgsCore
```

**Why**: Cleaner, avoids multiple `sys.path.append()` calls

### ✅ Use Absolute Imports in Library

**Library code (ras_commander/) should use absolute or relative imports**:
```python
# ras_commander/core.py

# ✅ Absolute import
from ras_commander.hdf import HdfBase

# ✅ Relative import (also good)
from .hdf import HdfBase

# ❌ Don't use flexibility pattern in library code
```

### ✅ Comment the Pattern

**Make it clear why this pattern is used**:
```python
# Flexible imports for development vs installed package
try:
    from ras_commander import RasCmdr
except ImportError:
    # Local repository fallback
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import RasCmdr
```

## Alternative: uv-Managed Virtual Environment

**Recommended modern approach** (avoids `sys.path` manipulation):

```bash
# Create virtual environment with uv
uv venv .venv

# Install ras-commander in editable mode
uv pip install -e .

# All imports now work without try/except pattern
```

**Then in notebooks**:
```python
# Simple imports (if using uv venv with editable install)
from ras_commander import RasCmdr, init_ras_project
from ras_commander.hdf import HdfResultsPlan
```

**See**: Root CLAUDE.md - Development Environment section for details

## Common Pitfalls

### ❌ Wrong Parent Directory Calculation

**Problem**:
```python
# examples/notebook.ipynb
parent_directory = current_file.parent  # This is examples/, not root!
```

**Solution**:
```python
# examples/notebook.ipynb
parent_directory = current_file.parent.parent  # examples/.. = root
```

### ❌ Hardcoded Paths

**Bad**:
```python
sys.path.append("C:/Users/me/ras-commander")  # Breaks on other machines
```

**Good**:
```python
# Compute path relative to current file
parent_directory = current_file.parent.parent
sys.path.append(str(parent_directory))
```

### ❌ Using Flexibility Pattern in Library Code

**Bad** (`ras_commander/core.py`):
```python
# DON'T do this in library code
try:
    from .hdf import HdfBase
except ImportError:
    sys.path.append(...)  # NO! Library should assume proper installation
```

**Good** (`ras_commander/core.py`):
```python
# Simple import in library code
from .hdf import HdfBase
```

## Testing Import Pattern

### Verify Both Scenarios

**Test 1: Installed Package**:
```bash
# Create clean venv
python -m venv test_venv
source test_venv/bin/activate  # or test_venv\Scripts\activate on Windows

# Install ras-commander
pip install ras-commander

# Run notebook - should use installed package
jupyter notebook examples/01_basic_usage.ipynb
```

**Test 2: Local Development**:
```bash
# No ras-commander installed
python -m venv clean_venv
source clean_venv/bin/activate

# Run notebook - should fall back to sys.path.append()
jupyter notebook examples/01_basic_usage.ipynb
```

**Both should work without modification**

## See Also

- **Development Environment**: Root CLAUDE.md - Environment Management section
- **Testing Strategy**: `.claude/rules/testing/tdd-approach.md` - Testing with example projects
- **Path Handling**: `.claude/rules/python/path-handling.md` - pathlib.Path usage

---

**Key Takeaway**: Use try/except import pattern with `sys.path.append()` in example notebooks and standalone scripts. Library code should use simple imports assuming proper installation.
