# RAS Commander API Documentation

The `ras_commander` library API documentation has been split into two files for easier navigation:

## API Documentation Files

### [api-ras.md](api-ras.md) - HEC-RAS Classes and Functions
Complete reference for HEC-RAS project management, plan execution, and file operations:
- **RasPrj**: Project initialization and management
- **RasPlan**: Plan file operations and modifications
- **RasGeo**: Geometry file operations
- **RasUnsteady**: Unsteady flow file management
- **RasUtils**: Utility functions
- **RasExamples**: Example project management
- **RasCmdr**: Plan execution and computation
- **RasMap**: RASMapper configuration and post-processing
- **Standalone Functions**: `init_ras_project()`, `get_ras_exe()`

### [api-hdf.md](api-hdf.md) - HDF Data Extraction and Analysis Classes
Complete reference for extracting and analyzing data from HEC-RAS HDF files:
- **HdfBase**: Core HDF file operations
- **HdfBndry**: Boundary condition geometry
- **HdfFluvialPluvial**: Fluvial-pluvial boundary analysis
- **HdfInfiltration**: Infiltration data handling
- **HdfMesh**: 2D mesh geometry extraction
- **HdfPipe**: Pipe network geometry and results
- **HdfPlan**: Plan-level information and metadata
- **HdfPlot**: Basic plotting utilities
- **HdfPump**: Pump station geometry and results
- **HdfResultsMesh**: 2D mesh results extraction
- **HdfResultsPlan**: Plan-level results (both unsteady and **steady state**)
- **HdfResultsPlot**: Results plotting utilities
- **HdfResultsXsec**: 1D cross-section results
- **HdfStruc**: Hydraulic structure geometry
- **HdfUtils**: HDF utility functions
- **HdfXsec**: 1D cross-section geometry

## Quick Start

For getting started with the library, see the [README.md](README.md) and example notebooks in the `examples/` directory.

## New Features

### Steady State Support
The library now includes full support for steady state flow analysis. See the new steady state methods in `HdfResultsPlan`:
- `is_steady_plan()` - Check if HDF contains steady state results
- `get_steady_profile_names()` - Extract profile names
- `get_steady_wse()` - Extract water surface elevations
- `get_steady_info()` - Extract steady flow metadata

For usage examples, see the steady state example notebook in `examples/`.
