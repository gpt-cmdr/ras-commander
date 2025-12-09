# Example Notebooks

RAS Commander includes 30+ Jupyter notebooks demonstrating all major features with working code and outputs. Browse the notebooks in the left navigation pane to view them directly in this documentation, complete with rendered outputs.

## Running Examples Locally

```bash
# Clone the repository
git clone https://github.com/gpt-cmdr/ras-commander.git
cd ras-commander

# Install dependencies
pip install -e .
pip install jupyter rasterio pyproj

# Start Jupyter
jupyter notebook examples/
```

## Notebook Categories

### Getting Started

Foundational notebooks for setting up projects and extracting example data.

| Notebook | Description | Source |
|----------|-------------|--------|
| Using RasExamples | Download and extract HEC-RAS example projects from the official distribution | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/00_Using_RasExamples.ipynb) |
| Project Initialization | Initialize projects and explore their components (plans, geometry, flows) | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/01_project_initialization.ipynb) |

### File Operations

Work with plan files, geometry files, unsteady flow files, and their parameters.

| Notebook | Description | Source |
|----------|-------------|--------|
| Plan and Geometry Operations | Clone and modify plan and geometry files programmatically | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/02_plan_and_geometry_operations.ipynb) |
| Unsteady Flow Operations | Extract and modify boundary conditions in unsteady flow files | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/03_unsteady_flow_operations.ipynb) |
| Multiple Project Operations | Work with multiple HEC-RAS projects simultaneously | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/04_multiple_project_operations.ipynb) |
| Plan Parameter Operations | Retrieve and update plan parameters (simulation window, cores, etc.) | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/09_plan_parameter_operations.ipynb) |
| Plaintext Geometry Parsing | Parse and modify geometry files directly (cross sections, Manning's n) | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/20_plaintext_geometry_operations.ipynb) |

### Execution Modes

Different approaches for running HEC-RAS simulations.

| Notebook | Description | Source |
|----------|-------------|--------|
| Single Plan Execution | Execute a single plan with options (cores, preprocessor, destination) | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/05_single_plan_execution.ipynb) |
| Executing Plan Sets | Different ways to specify and execute sets of plans | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/06_executing_plan_sets.ipynb) |
| Sequential Plan Execution | Run plans in sequence using test mode | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/07_sequential_plan_execution.ipynb) |
| Parallel Execution | Run plans in parallel across worker folders | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/08_parallel_execution.ipynb) |
| Remote Execution (PsExec) | Distributed execution across remote machines via PsExec | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/23_remote_execution_psexec.ipynb) |

### HDF Data Extraction

Extract and analyze results from HEC-RAS HDF output files.

| Notebook | Description | Source |
|----------|-------------|--------|
| 1D HDF Data Extraction | Extract 1D cross-section time series data and maximum values | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/10_1d_hdf_data_extraction.ipynb) |
| 2D HDF Data Extraction | Extract 2D mesh data including cells, faces, and time series | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/11_2d_hdf_data_extraction.ipynb) |
| Pipes and Pumps | Extract pipe network and pump station data from HDF files | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/12_2d_hdf_data_extraction%20pipes%20and%20pumps.ipynb) |
| 2D Face Data Extraction | Detailed face data extraction for flow analysis | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/13_2d_detail_face_data_extraction.ipynb) |
| Fluvial-Pluvial Delineation | Classify flooding as fluvial (riverine) or pluvial (rainfall) | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/14_fluvial_pluvial_delineation.ipynb) |

### Analysis & Results

Steady flow analysis, dam breach results, and legacy interface access.

| Notebook | Description | Source |
|----------|-------------|--------|
| Steady Flow Analysis | Extract and analyze steady state results from HDF files | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/19_steady_flow_analysis.ipynb) |
| Dam Breach Results | Extract dam breach time series and summary statistics | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/18_breach_results_extraction.ipynb) |
| HECRASController Profiles | Use the legacy COM interface (RasControl) for profile extraction | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/17_extracting_profiles_with_hecrascontroller%20and%20RasControl.ipynb) |
| DSS Boundary Extraction | Read HEC-DSS files for boundary condition time series | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/22_dss_boundary_extraction.ipynb) |

### Mapping & Visualization

Generate maps and export raster results.

| Notebook | Description | Source |
|----------|-------------|--------|
| Stored Map Generation | Generate stored maps from RASMapper configurations | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/15_stored_map_generation.ipynb) |
| RASMapper Raster Exports | Export raster results using RASMapper automation | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/21_rasmap_raster_exports.ipynb) |
| Programmatic Result Mapping | Create flood maps programmatically from HDF results | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/25_programmatic_result_mapping.ipynb) |

### Automation

Automate HEC-RAS with COM interfaces and precipitation data.

| Notebook | Description | Source |
|----------|-------------|--------|
| Win32COM Automation | Direct HEC-RAS automation using the Win32COM interface | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/16_automating_ras_with_win32com.ipynb) |
| AORC Precipitation | Retrieve AORC gridded precipitation data for model input | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/24_aorc_precipitation.ipynb) |

### Sensitivity & Benchmarking

Performance testing and sensitivity analysis workflows.

| Notebook | Description | Source |
|----------|-------------|--------|
| Core Sensitivity Testing | Test how CPU core count affects computation time | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/101_Core_Sensitivity.ipynb) |
| Version Benchmarking (6.1-6.6) | Compare performance across HEC-RAS versions | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/102_benchmarking_versions_6.1_to_6.6.ipynb) |
| Manning's n Bulk Analysis | Bulk sensitivity analysis for Manning's n values | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/105_mannings_sensitivity_bulk_analysis.ipynb) |
| Manning's n Multi-Interval | Multi-interval Manning's n sensitivity testing | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/106_mannings_sensitivity_multi-interval.ipynb) |

### Advanced Workflows

Complex workflows combining multiple features.

| Notebook | Description | Source |
|----------|-------------|--------|
| Atlas 14 AEP Events | Generate AEP storm events from NOAA Atlas 14 data | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/103_Running_AEP_Events_from_Atlas_14.ipynb) |
| Atlas 14 Multi-Project | Run Atlas 14 AEP events across multiple projects | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/104_Atlas14_AEP_Multi_Project.ipynb) |

## Using Notebooks as Templates

All notebooks follow a consistent pattern:

```python
# 1. Flexible imports
try:
    from ras_commander import init_ras_project, RasCmdr
except ImportError:
    import sys
    from pathlib import Path
    sys.path.append(str(Path().resolve().parent))
    from ras_commander import init_ras_project, RasCmdr

# 2. Extract example project
from ras_commander import RasExamples
path = RasExamples.extract_project("Muncie")

# 3. Initialize
init_ras_project(path, "6.5")

# 4. Perform operations
# ...
```

## Test-Driven Development

These notebooks serve dual purposes:

1. **Documentation**: Working examples for users
2. **Functional Tests**: Verify library behavior with real HEC-RAS projects

This approach reduces LLM hallucinations by providing concrete, executable examples.
