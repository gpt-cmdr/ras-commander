# Example Notebooks

RAS Commander includes 30+ Jupyter notebooks demonstrating all major features with working code.

## Running Examples

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

## Project Setup

| Notebook | Description |
|----------|-------------|
| [00_Using_RasExamples](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/00_Using_RasExamples.ipynb) | Download and extract HEC-RAS example projects |
| [01_project_initialization](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/01_project_initialization.ipynb) | Initialize projects and explore components |

## File Operations

| Notebook | Description |
|----------|-------------|
| [02_plan_and_geometry_operations](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/02_plan_and_geometry_operations.ipynb) | Clone and modify plan/geometry files |
| [03_unsteady_flow_operations](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/03_unsteady_flow_operations.ipynb) | Extract and modify boundary conditions |
| [04_multiple_project_operations](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/04_multiple_project_operations.ipynb) | Work with multiple HEC-RAS projects |
| [09_plan_parameter_operations](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/09_plan_parameter_operations.ipynb) | Retrieve and update plan parameters |
| [20_plaintext_geometry_operations](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/20_plaintext_geometry_operations.ipynb) | Parse and modify geometry files |

## Execution Modes

| Notebook | Description |
|----------|-------------|
| [05_single_plan_execution](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/05_single_plan_execution.ipynb) | Execute single plan with options |
| [06_executing_plan_sets](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/06_executing_plan_sets.ipynb) | Different ways to specify plan sets |
| [07_sequential_plan_execution](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/07_sequential_plan_execution.ipynb) | Run plans in sequence |
| [08_parallel_execution](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/08_parallel_execution.ipynb) | Run plans in parallel |
| [23_remote_execution_psexec](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/23_remote_execution_psexec.ipynb) | Distributed execution with PsExec |

## HDF Data Extraction

| Notebook | Description |
|----------|-------------|
| [10_1d_hdf_data_extraction](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/10_1d_hdf_data_extraction.ipynb) | Extract 1D cross-section data |
| [11_2d_hdf_data_extraction](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/11_2d_hdf_data_extraction.ipynb) | Extract 2D mesh data |
| [12_2d_hdf_data_extraction_pipes_and_pumps](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/12_2d_hdf_data_extraction_pipes_and_pumps.ipynb) | Pipe networks and pump stations |
| [13_2d_detail_face_data_extraction](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/13_2d_detail_face_data_extraction.ipynb) | Detailed face data extraction |
| [14_fluvial_pluvial_delineation](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/14_fluvial_pluvial_delineation.ipynb) | Fluvial-pluvial boundary analysis |

## Steady and Unsteady Analysis

| Notebook | Description |
|----------|-------------|
| [17_extracting_profiles_with_hecrascontroller](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/17_extracting_profiles_with_hecrascontroller.ipynb) | Legacy COM interface (RasControl) |
| [18_breach_results_extraction](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/18_breach_results_extraction.ipynb) | Dam breach results extraction |
| [19_steady_flow_analysis](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/19_steady_flow_analysis.ipynb) | Steady flow analysis |
| [22_dss_boundary_extraction](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/22_dss_boundary_extraction.ipynb) | DSS file boundary extraction |

## Sensitivity Analysis

| Notebook | Description |
|----------|-------------|
| [15_mannings_sensitivity_bulk_analysis](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/15_mannings_sensitivity_bulk_analysis.ipynb) | Bulk Manning's n sensitivity |
| [16_mannings_sensitivity_multi-interval](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/16_mannings_sensitivity_multi-interval.ipynb) | Multi-interval Manning's n sensitivity |
| [101_Core_Sensitivity](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/101_Core_Sensitivity.ipynb) | CPU core performance testing |
| [102_benchmarking_versions_6.1_to_6.6](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/102_benchmarking_versions_6.1_to_6.6.ipynb) | Version comparison benchmarks |

## Advanced Workflows

| Notebook | Description |
|----------|-------------|
| [103_Generating_AEP_Events_from_Atlas_14](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/103_Generating_AEP_Events_from_Atlas_14.ipynb) | Generate AEP events from NOAA Atlas 14 |

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
