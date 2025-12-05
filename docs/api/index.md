# API Reference

This section provides documentation for the RAS Commander Python API.

## Core Classes

Primary classes for project management and execution:

- [`RasPrj`](core.md#rasprj) - Project management and data structures
- [`RasCmdr`](core.md#rascmdr) - Plan execution (single, parallel, sequential)
- [`RasPlan`](core.md#rasplan) - Plan file operations
- [`RasGeo`](core.md#rasgeo) - Geometry file operations
- [`RasUnsteady`](core.md#rasunsteady) - Unsteady flow file management
- [`RasUtils`](core.md#rasutils) - Utility functions
- [`RasExamples`](core.md#rasexamples) - Example project management
- [`RasMap`](core.md#rasmap) - RASMapper configuration
- [`RasControl`](core.md#rascontrol) - Legacy COM interface

## HDF Modules

Classes for reading HDF result files:

- [`HdfBase`](hdf.md#hdfbase) - Core HDF operations
- [`HdfPlan`](hdf.md#hdfplan) - Plan information
- [`HdfMesh`](hdf.md#hdfmesh) - Mesh geometry
- [`HdfResultsMesh`](hdf.md#hdfresultsmesh) - 2D mesh results
- [`HdfResultsPlan`](hdf.md#hdfresultsplan) - Plan-level results
- [`HdfResultsXsec`](hdf.md#hdfresultsxsec) - 1D cross-section results
- [`HdfStruc`](hdf.md#hdfstruc) - Structure data
- [`HdfResultsBreach`](hdf.md#hdfresultsbreach) - Dam breach results
- [`HdfHydraulicTables`](hdf.md#hdfhydraulictables) - Cross section HTAB data
- [`HdfPipe`](hdf.md#hdfpipe) - Pipe network analysis
- [`HdfPump`](hdf.md#hdfpump) - Pump station analysis

## Geometry Modules

Classes for parsing geometry files:

- [`RasGeometry`](geometry.md#rasgeometry) - Cross sections, storage, connections
- [`RasGeometryUtils`](geometry.md#rasgeometryutils) - Parsing utilities
- [`RasStruct`](geometry.md#rasstruct) - Inline structures
- [`RasBreach`](geometry.md#rasbreach) - Breach parameters

## DSS Modules

Classes for reading DSS files:

- [`RasDss`](dss.md#rasdss) - DSS file operations

## Remote Modules

Classes for distributed execution:

- [`LocalWorker`](remote.md#localworker) - Local parallel execution
- [`PsexecWorker`](remote.md#psexecworker) - Windows remote execution
- [`DockerWorker`](remote.md#dockerworker) - Container execution
- [`init_ras_worker`](remote.md#factory-function) - Factory function
- [`compute_parallel_remote`](remote.md#execution) - Distributed execution

## Usage Pattern

All primary classes use static methods:

```python
# No instantiation needed
from ras_commander import RasCmdr, RasPlan

# Direct static method calls
RasCmdr.compute_plan("01")
RasPlan.set_num_cores("01", 4)
```

## Decorators

RAS Commander uses two key decorators that affect method behavior:

### @standardize_input

Automatically converts various input types to the correct HDF file path. This decorator is applied to all HDF methods.

**Accepted Input Types:**

| Input Type | Example | Behavior |
|------------|---------|----------|
| Plan number (str) | `"01"`, `"p01"` | Looks up HDF path in `ras.plan_df` |
| Plan number (int) | `1`, `2` | Converted to string, then lookup |
| Path object | `Path("x.hdf")` | Used directly if file exists |
| String path | `"/path/to.hdf"` | Converted to Path, used directly |
| h5py.File | `hdf_file` | Extracts filename from object |

**file_type Parameter:**

```python
@standardize_input(file_type='plan_hdf')  # Default - looks for .p##.hdf
@standardize_input(file_type='geom_hdf')  # Looks for .g##.hdf
@standardize_input(file_type='plan')      # Looks for .p## (plain text)
```

**Usage Examples:**

```python
from ras_commander import HdfResultsMesh, init_ras_project

init_ras_project("/path/to/project", "6.5")

# All of these are equivalent:
HdfResultsMesh.get_mesh_max_ws("01")           # Plan number string
HdfResultsMesh.get_mesh_max_ws(1)              # Integer
HdfResultsMesh.get_mesh_max_ws("p01")          # With 'p' prefix
HdfResultsMesh.get_mesh_max_ws(Path("x.hdf"))  # Path object
HdfResultsMesh.get_mesh_max_ws("/path/to.hdf") # String path
```

!!! warning "Project Initialization Required"
    When using plan/geometry numbers (not direct paths), you must first call `init_ras_project()` to populate the `ras.plan_df` lookup table.

### @log_call

Automatic logging decorator applied to most methods. Logs function entry/exit at DEBUG level.

```python
@log_call
def my_function():
    ...

# Logs: "Calling my_function"
# Logs: "Finished my_function"
```

Enable debug logging to see these messages:

```python
import logging
logging.getLogger('ras_commander').setLevel(logging.DEBUG)
```
