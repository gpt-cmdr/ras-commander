# HDF File Operations

**Context**: Extracting results from HEC-RAS HDF files
**Priority**: High - core results extraction functionality
**Auto-loads**: Yes (HDF-related code)

## Primary Source

**See**: `ras_commander/hdf/AGENTS.md` for complete HDF documentation.

## Overview

HEC-RAS stores simulation results in HDF5 files (`.p##.hdf`). ras-commander provides static class methods for extracting all result types.

## Key Classes

| Class | Purpose |
|-------|---------|
| `HdfBase` | Core HDF operations, file structure |
| `HdfPlan` | Plan metadata extraction |
| `HdfMesh` | 2D mesh geometry extraction |
| `HdfResultsPlan` | General results (WSE, velocity) |
| `HdfResultsMesh` | Mesh cell time series |
| `HdfResultsBreach` | Breach progression data |
| `HdfStruc` | Structure data (bridges, culverts) |
| `HdfHydraulicTables` | Cross section property tables |

## Critical Pattern: Steady vs Unsteady Detection

```python
from ras_commander.hdf import HdfResultsPlan

# Always check plan type before extraction
if HdfResultsPlan.is_steady_plan(hdf_file):
    # Use steady-state methods
    wse = HdfResultsPlan.get_steady_wse(hdf_file)
else:
    # Use unsteady methods with time_index
    wse = HdfResultsPlan.get_wse(hdf_file, time_index=-1)
```

**Why**: Steady and unsteady results have different HDF structures.

## Quick Reference

```python
from ras_commander.hdf import HdfResultsPlan, HdfMesh

# Open HDF file
hdf_file = "project.p01.hdf"

# Extract water surface elevation
wse = HdfResultsPlan.get_wse(hdf_file, time_index=-1)

# Get mesh cell locations
cells = HdfMesh.get_mesh_cell_points(plan_number, ras_object=ras)

# Get time series for specific cells
ts = HdfResultsMesh.get_mesh_cells_timeseries(plan_number, ras_object=ras)
```

## Common Patterns

### ras_object Parameter

When using HDF methods with a local `ras` object (not global), always pass it:

```python
ras = init_ras_project(project_folder, "6.6")

# MUST pass ras_object
mesh = HdfMesh.get_mesh_cell_points(plan, ras_object=ras)
results = HdfResultsMesh.get_mesh_cells_timeseries(plan, ras_object=ras)
```

See `.claude/rules/python/ras-commander-patterns.md` for complete context object discipline.

## See Also

- **Complete Documentation**: `ras_commander/hdf/AGENTS.md`
- **Example Notebooks**: `examples/400_1d_hdf_data_extraction.ipynb`, `examples/410_2d_hdf_data_extraction.ipynb`
- **Context Object Discipline**: `.claude/rules/python/ras-commander-patterns.md`

---

**Key Takeaway**: Use `is_steady_plan()` before extraction. Always pass `ras_object` when using local project context.
