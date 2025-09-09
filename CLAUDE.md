# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## AGENTS.md Standard (Read Me First)

This repository now uses the AGENTS.md standard alongside CLAUDE.md.

- Treat any `AGENTS.md` in the current folder (and its parents up to the repo root) the same way you treat `CLAUDE.md` files.
- Scope and precedence:
  - The `AGENTS.md` at a folder applies to that folder and all subfolders.
  - More-deeply-nested `AGENTS.md` files override parent guidance when conflicts arise.
  - Direct, explicit instructions in the task or doc you’re reading take precedence.
- Always read both `CLAUDE.md` and `AGENTS.md` for the working directory before editing code or running tools.
- Key locations with scoped guidance:
  - `/AGENTS.md` (root)
  - `/ras_commander/AGENTS.md` (library API and coding conventions)
  - `/examples/AGENTS.md` (notebook index and extraction workflow)
  - `/examples/data/AGENTS.md` (small reference datasets; read-only)
  - `/examples/example_projects/AGENTS.md` (large HEC‑RAS examples; do not commit extractions)
  - `/ai_tools/AGENTS.md` (maintainer-only; ignore when using the library)

Important highlights from AGENTS.md:
- Ignore `ai_tools/` and any generated knowledge bases; they are maintainer-only.
- Prefer cleaned notebooks; otherwise treat notebooks as reference and extract logic into scripts.
- Use a single uv-managed venv at the repo root and install in editable mode (`uv venv .venv`, `uv pip install -e .`).

## Project Overview

**ras-commander** is a Python library for automating HEC-RAS (Hydrologic Engineering Center's River Analysis System) operations. It provides a comprehensive API for interacting with HEC-RAS project files, executing simulations, and processing results through HDF data analysis.

## Development Environment

### Build Commands
- **Build package**: `python setup.py sdist bdist_wheel`
- **Clean build**: Remove `build/`, `dist/`, and `*.egg-info` directories before building
- **Install locally**: `pip install -e .` (for development)
- **Install from build**: `pip install ras-commander`

### Testing Strategy
- Uses **Test Driven Development** with HEC-RAS example projects instead of traditional unit tests
- Example projects are located in `examples/` and `tests/example_projects/`
- Test scripts are in `tests/` directory (e.g., `test_ras_examples_initialization.py`)
- All example notebooks in `examples/` serve as both documentation and functional tests
- Run example tests: `python test_ras_examples_initialization.py`

### Dependencies
- **Python**: Requires 3.10+
- **Core packages**: h5py, numpy, pandas, geopandas, matplotlib, shapely, scipy, xarray, tqdm, requests, rasterstats, rtree
- **Optional**: tkinterdnd2 (for GUI applications with drag-and-drop)
- Install dependencies: `pip install h5py numpy pandas requests tqdm scipy xarray geopandas matplotlib shapely pathlib rasterstats rtree`

### Environment Management
- Supports both pip and uv for package management
- Development pattern: Clone repo and use `sys.path.append()` method (see examples for import pattern)
- Create virtual environment recommended: `python -m venv venv` or `conda create`

## Architecture Overview

### Core Classes and Execution Model

**Primary Execution Class**: `RasCmdr` - Static class for HEC-RAS plan execution
- `RasCmdr.compute_plan(plan_number, dest_folder=None, ras_object=None, clear_geompre=False, num_cores=None, overwrite_dest=False)`
- `RasCmdr.compute_parallel()` - Parallel execution across multiple worker processes
- `RasCmdr.compute_test_mode()` - Sequential execution in test environment

**Project Management**: `RasPrj` class and global `ras` object
- Initialize projects: `init_ras_project(path, ras_version, ras_object=None)`
- Global `ras` object available for single-project workflows
- Multiple project support via separate `RasPrj` instances

**File Operations Classes**:
- `RasPlan` - Plan file operations and modifications  
- `RasGeo` - Geometry file operations
- `RasUnsteady` - Unsteady flow file management
- `RasUtils` - Utility functions for file operations
- `RasMap` - RASMapper configuration parsing
- `RasExamples` - HEC-RAS example project management and extraction

**HDF Data Processing Classes**:
- `HdfBase`, `HdfPlan`, `HdfMesh` - Core HDF file operations
- `HdfResults*` classes - Results processing and analysis
- `HdfStruc`, `HdfPipe`, `HdfPump` - Infrastructure analysis
- `HdfPlot`, `HdfResultsPlot` - Visualization utilities

### Execution Modes
1. **Single Plan**: `RasCmdr.compute_plan()` - Execute one plan with full parameter control
2. **Parallel**: `RasCmdr.compute_parallel()` - Run multiple plans simultaneously using worker folders  
3. **Sequential**: `RasCmdr.compute_test_mode()` - Run multiple plans in order in test folder

## Key Development Patterns

### Static Class Pattern
- Most classes use static methods with `@log_call` decorators
- No instantiation required: `RasCmdr.compute_plan()` not `RasCmdr().compute_plan()`
- Pass `ras_object` parameter when working with multiple projects

### Import Flexibility Pattern
```python
# Flexible imports for development vs installed package
try:
    from ras_commander import init_ras_project, RasCmdr, RasPlan
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasCmdr, RasPlan
```

### Path Handling
- Use `pathlib.Path` objects consistently
- Support both string paths and Path objects in function parameters
- Handle Windows paths with proper escaping

### Error Handling and Logging
- Comprehensive logging using centralized `LoggingConfig`
- Use `@log_call` decorator for automatic function call logging
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs written to both console and rotating file (`ras_commander.log`)

### Naming Conventions
- **Functions/Variables**: snake_case (`compute_plan`, `plan_number`)
- **Classes**: PascalCase (`RasCmdr`, `HdfBase`)
- **Constants**: UPPER_CASE
- **Abbreviations**: ras, prj, geom, geompre, num, init, BC, IC, TW

### Documentation Standards
- Comprehensive docstrings with Args, Returns, Raises, Examples sections
- Include usage examples in all major functions
- Document parameter types and optional parameters clearly

## Working with HEC-RAS Projects

### Project Initialization
```python
# Single project (uses global ras object)
init_ras_project(r"/path/to/project", "6.5")

# Multiple projects
project1 = RasPrj()
init_ras_project(r"/path/to/project1", "6.5", ras_object=project1)
```

### Accessing Project Data
- `ras.plan_df` - Plans dataframe
- `ras.geom_df` - Geometry files dataframe  
- `ras.flow_df` - Flow files dataframe
- `ras.unsteady_df` - Unsteady files dataframe
- `ras.boundaries_df` - Boundary conditions dataframe

### Plan Execution Parameters
- `plan_number`: Plan ID (string, e.g., "01", "02")
- `dest_folder`: Optional computation folder (None = modify original)
- `clear_geompre`: Clear geometry preprocessor files (Boolean)
- `num_cores`: Number of processing cores (Integer)
- `overwrite_dest`: Overwrite existing destination (Boolean)

### Example Project Management with RasExamples
```python
# Extract HEC-RAS example projects for testing
# Default extraction to 'example_projects' folder
path = RasExamples.extract_project("Muncie")

# Extract to custom location (relative or absolute path)
path = RasExamples.extract_project("Dam Breaching", output_path="my_tests")
paths = RasExamples.extract_project(["Muncie", "Balde Eagle Creek"], output_path="C:/tests")

# List available projects and categories
all_projects = RasExamples.list_projects()
categories = RasExamples.list_categories()
category_projects = RasExamples.list_projects("1D Unsteady Flow Hydraulics")
```

## GUI Application Development

### Existing GUI Pattern
- See `tools/1D Mannings to L-MC-R/1D_Mannings_to_L-MC-R.py` for tkinter GUI example
- Uses tkinterdnd2 for drag-and-drop functionality
- Progress bars and real-time logging display
- Error handling with user-friendly messages
- PyInstaller compilation for exe distribution

### Recommended GUI Libraries
- **tkinter** - Built-in, good for simple applications
- **tkinterdnd2** - Add drag-and-drop support
- **PyQt5/PySide2** - For more advanced GUIs
- **PyInstaller** - Create standalone executables

## File Structure Conventions

### Project Organization
- Main library code in `ras_commander/`
- Examples and documentation in `examples/`
- Test projects in `tests/example_projects/`
- GUI applications in `apps/` (create if needed)
- Utility tools in `tools/`
- AI/LLM resources in `ai_tools/`

### Creating New Applications
- Create subdirectory in `apps/` or `tools/`
- Include separate `requirements.txt` or `pyproject.toml`
- Follow existing naming patterns (snake_case for directories)
- Include README.md with installation and usage instructions
- Use uv for environment management when possible

## AI/LLM Integration Notes

- Repository has extensive AI tooling in `ai_tools/`
- Knowledge bases generated automatically during build process
- Cursor IDE integration with `.cursorrules`
- Optimized for LLM code assistance and generation
- Examples serve dual purpose as documentation and tests to reduce hallucination

## Common Pitfalls to Avoid

- Don't instantiate static classes like `RasCmdr()` 
- Always specify `ras_object` parameter when working with multiple projects
- Use pathlib.Path for all path operations
- Don't forget `@log_call` decorator on new functions
- Ensure HEC-RAS project is initialized before calling compute functions
- Handle file permissions carefully on Windows systems
- Test with actual HEC-RAS example projects, not synthetic data
