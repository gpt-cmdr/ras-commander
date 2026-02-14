# Installation

## Requirements

- **Python**: 3.10 or higher (3.13 recommended for new installations)
- **HEC-RAS**: 6.0+ recommended (3.x-5.x supported via RasControl)
- **Operating System**: Windows (for full HEC-RAS execution), Linux (map generation via Wine), Mac (HDF analysis only)

## Prerequisites

### Install Astral uv (Recommended)

uv is a fast Python package manager required for Claude Code agent operations and recommended for all users:

=== "Windows (PowerShell)"
    ```powershell
    irm https://astral.sh/uv/install.ps1 | iex
    ```

=== "macOS/Linux"
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

Verify installation:
```bash
uv --version  # Should show: uv 0.5.x or later
```

!!! info "Why uv?"
    - 10-100x faster than pip for package installation
    - Required for Claude Code agent scripts and skills
    - Enables one-off script execution with `uvx`
    - Better dependency resolution

### Install Anaconda (Recommended for Notebooks)

For Jupyter notebook work, we recommend Anaconda:

- **Download**: [https://www.anaconda.com/download](https://www.anaconda.com/download)
- **Verify**: `conda --version`

## Standard Environment Names

RAS Commander uses two standard environment names:

| Environment | Purpose | Install Type |
|-------------|---------|--------------|
| **`RasCommander`** | Standard user environment | pip package |
| **`rascmdr_local`** | Development environment | editable install |

## Install from PyPI (Most Users)

**Environment name**: `RasCommander`

**Use this if**: You're using ras-commander, NOT editing its source code.

```bash
# Create environment
conda create -n RasCommander python=3.13
conda activate RasCommander

# Install ras-commander
pip install ras-commander

# Install Jupyter (for notebooks)
pip install jupyter ipykernel
python -m ipykernel install --user --name RasCommander --display-name "Python (RasCommander)"
```

!!! tip "Quick Install"
    For a quick install without Jupyter:
    ```bash
    pip install --upgrade ras-commander
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

### Linux/Wine (Headless Map Generation)

On Linux, `RasProcess.exe` can run under Wine to generate stored maps (WSE, Depth, Velocity TIFs) without a display. This enables headless CI/CD pipelines and cloud-based map generation.

**Requirements**:

- Wine 8.0+ (64-bit prefix)
- .NET Framework 4.8 (installed via winetricks)
- HEC-RAS DLLs copied from a Windows installation

```bash
# Step 1: Install Wine
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install -y wine wine64 wine32 winetricks cabextract

# Step 2: Create Wine prefix with .NET 4.8
export WINEPREFIX=/opt/hecras-wine
export WINEARCH=win64
wineboot --init
winetricks -q dotnet48      # ~15 min, installs .NET Framework 4.8
winetricks -q gdiplus       # Native GDI+ (required for System.Drawing)
winetricks -q corefonts     # Arial, Times New Roman, etc.

# Step 3: Copy HEC-RAS DLLs from a Windows machine
# From C:\Program Files (x86)\HEC\HEC-RAS\6.6\ copy all DLLs and the GDAL/ folder
# to /opt/hecras-wine/drive_c/HEC-RAS/6.6/
```

!!! tip "Detailed Setup Instructions"
    Run `RasProcess.setup_wine_environment()` in Python to print the complete list of required DLLs and step-by-step instructions.

!!! note "Scope"
    Wine support covers `RasProcess.exe` (stored map generation) only. Full HEC-RAS simulation (`Ras.exe`) still requires Windows. HDF analysis works natively on Linux without Wine.

**Verify installation**:

```python
from ras_commander import RasProcess

# Check Wine environment is configured correctly
status = RasProcess.check_wine_environment()
print(status)
```

**Usage** (no code changes needed -- auto-detected):

```python
from ras_commander import RasProcess

# Same API as Windows -- Wine wrapping is automatic
results = RasProcess.store_maps(plan_number="01", wse=True, depth=True)
```

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

**Environment name**: `rascmdr_local`

**Use this if**: You're editing ras-commander source code or contributing to the library.

```bash
# Clone the repository
git clone https://github.com/gpt-cmdr/ras-commander.git
cd ras-commander

# Create development environment
conda create -n rascmdr_local python=3.13
conda activate rascmdr_local

# Install in editable mode
pip install -e .

# Install Jupyter (for notebooks)
pip install jupyter ipykernel
python -m ipykernel install --user --name rascmdr_local --display-name "Python (rascmdr_local)"
```

!!! tip "Using uv for Development"
    For faster package installation during development:
    ```bash
    uv venv .venv
    .venv\Scripts\activate  # Windows
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
