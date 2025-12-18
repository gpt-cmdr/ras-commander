# Example Notebooks

RAS Commander includes 40+ Jupyter notebooks demonstrating all major features with working code and outputs. Browse the notebooks in the left navigation pane to view them directly in this documentation, complete with rendered outputs.

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

### Basic Automation & Project Data (100s)

Core library functionality: project initialization, plan operations, and execution modes.

| Notebook | Description | Source |
|----------|-------------|--------|
| Using RasExamples | Download and extract HEC-RAS example projects | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/100_using_ras_examples.ipynb) |
| Project Initialization | Initialize projects and explore components | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/101_project_initialization.ipynb) |
| Multiple Project Operations | Work with multiple projects simultaneously | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/102_multiple_project_operations.ipynb) |
| Plan and Geometry Operations | Clone and modify plan and geometry files | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/103_plan_and_geometry_operations.ipynb) |
| Plan Parameter Operations | Retrieve and update plan parameters | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/104_plan_parameter_operations.ipynb) |
| Single Plan Execution | Execute a single plan with options | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/110_single_plan_execution.ipynb) |
| Executing Plan Sets | Specify and execute sets of plans | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/111_executing_plan_sets.ipynb) |
| Sequential Plan Execution | Run plans in sequence (test mode) | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/112_sequential_plan_execution.ipynb) |
| Parallel Execution | Run plans in parallel across workers | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/113_parallel_execution.ipynb) |
| Win32COM Automation | Direct HEC-RAS automation via Win32COM | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/120_automating_ras_with_win32com.ipynb) |
| Legacy HECRASController | RasControl for HEC-RAS 3.x-5.x | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/121_legacy_hecrascontroller_and_rascontrol.ipynb) |

### Geometry Parsing & Operations (200s)

Work with geometry files: parsing, modification, and repair.

| Notebook | Description | Source |
|----------|-------------|--------|
| Plaintext Geometry Operations | Parse and modify geometry files directly | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/200_plaintext_geometry_operations.ipynb) |
| Fixit Blocked Obstructions | Detect and fix overlapping blocked obstructions | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/210_fixit_blocked_obstructions.ipynb) |

### Boundary Conditions (300s)

Work with unsteady/steady flow files, DSS data, and boundary conditions.

| Notebook | Description | Source |
|----------|-------------|--------|
| Unsteady Flow Operations | Extract and modify BC tables in .uXX files | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/300_unsteady_flow_operations.ipynb) |
| DSS Boundary Extraction | Read HEC-DSS boundary condition time series | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/310_dss_boundary_extraction.ipynb) |
| DSS Path Validation | Validate DSS pathnames and availability | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/311_validating_dss_paths.ipynb) |
| 1D Boundary Visualization | Visualize 1D boundary conditions in RASMapper | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/320_1d_boundary_condition_visualization.ipynb) |

### HDF Data Operations (400s)

Extract and analyze results from HEC-RAS HDF output files.

| Notebook | Description | Source |
|----------|-------------|--------|
| 1D HDF Data Extraction | 1D cross-section time series and maxima | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/400_1d_hdf_data_extraction.ipynb) |
| Steady Flow Analysis | Extract steady state results | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/401_steady_flow_analysis.ipynb) |
| 2D HDF Data Extraction | 2D mesh cells, faces, time series | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/410_2d_hdf_data_extraction.ipynb) |
| Pipes and Pumps | Pipe networks and pump stations | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/411_2d_hdf_pipes_and_pumps.ipynb) |
| 2D Face Data Extraction | Detailed face data for flow analysis | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/412_2d_detail_face_data_extraction.ipynb) |
| Breach Results Extraction | Dam breach time series and statistics | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/420_breach_results_extraction.ipynb) |

### Remote Plan Execution (500s)

Distributed execution across remote machines.

| Notebook | Description | Source |
|----------|-------------|--------|
| Remote Execution (PsExec) | Windows remote execution via PsExec | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/500_remote_execution_psexec.ipynb) |

### Advanced Data Analysis (600s)

Mapping, visualization, and advanced spatial analysis.

| Notebook | Description | Source |
|----------|-------------|--------|
| Floodplain Mapping GUI | RASMapper GUI automation (legacy) | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/600_floodplain_mapping_gui.ipynb) |
| Floodplain Mapping RasProcess | RasProcess CLI (recommended) | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/601_floodplain_mapping_rasprocess.ipynb) |
| Floodplain Mapping Python GIS | Pure Python mesh rasterization | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/602_floodplain_mapping_python_gis.ipynb) |
| Fluvial-Pluvial Delineation | Classify flooding mechanism | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/610_fluvial_pluvial_delineation.ipynb) |
| Map Layer Validation | Validate RASMapper layers | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/611_validating_map_layers.ipynb) |

### Sensitivity & Benchmarking (700s)

Performance testing, version comparison, and parameter sensitivity.

| Notebook | Description | Source |
|----------|-------------|--------|
| Core Sensitivity Testing | Runtime vs core count experiments | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/700_core_sensitivity.ipynb) |
| Version Benchmarking (6.1-6.6) | Cross-version performance comparison | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/701_benchmarking_versions_6.1_to_6.6.ipynb) |
| Manning's n Bulk Analysis | Bulk Manning's n sensitivity | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/710_mannings_sensitivity_bulk_analysis.ipynb) |
| Manning's n Multi-Interval | Multi-interval sensitivity testing | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/711_mannings_sensitivity_multi_interval.ipynb) |
| Atlas 14 AEP Events | Generate AEP storms from Atlas 14 | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/720_atlas14_aep_events.ipynb) |
| Atlas 14 Caching Demo | Atlas 14 data caching | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/721_atlas14_caching_demo.ipynb) |
| Atlas 14 Multi-Project | Run Atlas 14 across multiple projects | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/722_atlas14_multi_project.ipynb) |

### Quality Assurance (800s)

Model validation, QA checks, and certification workflows.

| Notebook | Description | Source |
|----------|-------------|--------|
| RasCheck Validation | Core RasCheck validation suite | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/800_quality_assurance_rascheck.ipynb) |
| Advanced Structure Validation | Structure-specific validation | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/801_advanced_structure_validation.ipynb) |
| Custom Workflows & Standards | Custom QA workflows | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/802_custom_workflows_and_standards.ipynb) |

### External Data Integrations (900s)

Integration with external data sources: precipitation, gauges, etc.

| Notebook | Description | Source |
|----------|-------------|--------|
| AORC Precipitation | Retrieve AORC gridded precipitation | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/900_aorc_precipitation.ipynb) |
| AORC Precipitation Catalog | Comprehensive AORC catalog ops | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/901_aorc_precipitation_catalog.ipynb) |
| USGS Gauge Catalog | Generate gauge catalogs | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/910_usgs_gauge_catalog.ipynb) |
| USGS Gauge Data Integration | Integrate gauge data with models | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/911_usgs_gauge_data_integration.ipynb) |
| USGS Real-Time Monitoring | Real-time gauge monitoring | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/912_usgs_real_time_monitoring.ipynb) |
| BC from Live Gauge | Generate BCs from live data | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/913_bc_generation_from_live_gauge.ipynb) |
| Model Validation with USGS | Validate results against gauges | [:material-github:](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/914_model_validation_with_usgs.ipynb) |

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

## Numbering Scheme

See [NUMBERING_SCHEME.md](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/NUMBERING_SCHEME.md) for the complete category-based numbering system and guidelines for adding new notebooks.
