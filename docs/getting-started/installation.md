# Installation

## Requirements

- **Python**: 3.10 or higher
- **HEC-RAS**: 6.0+ recommended (3.x-5.x supported via RasControl)
- **Operating System**: Windows (for HEC-RAS execution), Linux/Mac (for HDF analysis only)

## Install from PyPI

The simplest way to install RAS Commander:

```bash
pip install --upgrade ras-commander
```

!!! tip "Use a Virtual Environment"
    Always install in a virtual environment to avoid dependency conflicts:

    ```bash
    # Using venv
    python -m venv ras_env
    ras_env\Scripts\activate  # Windows

    # Using conda
    conda create -n ras_env python=3.11
    conda activate ras_env

    # Using uv (recommended)
    uv venv .venv
    .venv\Scripts\activate  # Windows
    ```

## Core Dependencies

These are installed automatically with `pip install ras-commander`:

```bash
h5py numpy pandas requests tqdm scipy xarray geopandas matplotlib shapely rasterstats rtree pywin32 psutil
```

## Optional Dependencies

### Notebook Examples

Additional packages for running the example notebooks:

```bash
pip install rasterio pyproj
```

### DSS File Operations

For reading HEC-DSS boundary condition files:

```bash
pip install pyjnius
```

!!! note "Java Required"
    DSS operations require Java 8+ (JRE or JDK) installed on your system.

### Remote Execution

For distributed computation across multiple machines:

```bash
# Individual backends
pip install paramiko      # SSH remote execution
pip install pywinrm       # WinRM remote execution
pip install docker        # Docker container execution
pip install boto3         # AWS EC2 execution
pip install azure-identity azure-mgmt-compute  # Azure execution

# Or install all at once
pip install ras-commander[remote-all]
```

## Development Installation

For contributing or modifying the library:

```bash
# Clone the repository
git clone https://github.com/gpt-cmdr/ras-commander.git
cd ras-commander

# Install in editable mode
pip install -e .

# Or with uv
uv pip install -e .
```

### Flexible Import Pattern

Scripts in the repository use this pattern to work both with installed packages and development mode:

```python
from pathlib import Path
import sys

try:
    from ras_commander import init_ras_project, RasCmdr
except ImportError:
    # Add parent directory to path for development
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from ras_commander import init_ras_project, RasCmdr
```

## Verifying Installation

```python
import ras_commander
print(f"RAS Commander version: {ras_commander.__version__}")

# Test basic imports
from ras_commander import (
    init_ras_project,
    RasCmdr,
    RasPlan,
    RasExamples,
    ras
)
print("All imports successful!")
```

## Troubleshooting

### Dependency Conflicts with NumPy

If you encounter numpy-related errors:

```bash
# Clear local pip packages
# Windows: Delete C:\Users\<username>\AppData\Roaming\Python\

# Create fresh environment
python -m venv fresh_env
fresh_env\Scripts\activate
pip install ras-commander
```

### HEC-RAS Not Found

If HEC-RAS execution fails:

1. Verify HEC-RAS is installed (default: `C:\Program Files\HEC\HEC-RAS\6.x\`)
2. Specify the full path to Ras.exe:

```python
init_ras_project("/path/to/project", r"D:\Programs\HEC\HEC-RAS\6.5\Ras.exe")
```

### pywin32 Errors

For COM interface issues on Windows:

```bash
pip uninstall pywin32
pip install pywin32
python -c "import win32com.client"  # Test import
```
