---
name: hecras_extract_results
description: |
  Extract HEC-RAS hydraulic results from HDF files including water surface elevations (WSE),
  depths, velocities, and flows for both steady and unsteady simulations. Handles cross section
  time series, 2D mesh results, maximum envelopes, and dam breach results. Use when you need to
  extract, analyze, or post-process HEC-RAS simulation outputs, retrieve water levels, query
  velocity fields, get depth grids, extract flow data, analyze breach hydrographs, or pull
  hydraulic variables from .hdf result files.
  Triggers: HDF results, extract WSE, water surface elevation, depth grid, velocity,
  flow data, mesh results, cross section time series, maximum envelope, breach results,
  HdfResultsPlan, HdfResultsMesh, HdfResultsBreach, steady results, unsteady results,
  plan HDF, .p01.hdf, get_wse, get_depth, get_velocity, post-process, simulation output.
---

# Extracting HEC-RAS Results

When the user asks to extract HEC-RAS results, use the patterns below. Read the primary sources for complete details -- do not duplicate their content here.

**Primary Sources**:
- **HDF Class Reference**: `ras_commander/hdf/AGENTS.md` (215 lines) - Complete class hierarchy, lazy loading patterns, decorators
- **Library Context**: `ras_commander/CLAUDE.md` - HDF architecture overview, subpackage organization
- **Example Notebooks**:
  - `examples/400_1d_hdf_data_extraction.ipynb` - 1D cross section results (unsteady)
  - `examples/410_2d_hdf_data_extraction.ipynb` - 2D mesh results (comprehensive)
  - `examples/401_steady_flow_analysis.ipynb` - Steady state results (complete workflow)
  - `examples/420_breach_results_extraction.ipynb` - Dam breach results
- **Code Docstrings**: All HDF classes have comprehensive docstrings with parameter details

---

## Quick Start

### Minimal Working Example

```python
from ras_commander import init_ras_project, HdfResultsPlan, HdfResultsMesh

# Initialize project
init_ras_project("path/to/project", "7.0")

# Check simulation type
is_steady = HdfResultsPlan.is_steady_plan("01")

# Extract results based on type
if is_steady:
    profiles = HdfResultsPlan.get_steady_profile_names("01")
    wse = HdfResultsPlan.get_steady_wse("01", profile_name="100 year")
else:
    max_wse = HdfResultsMesh.get_mesh_maximum("01", variable="Water Surface")
```

---

## Navigation Guide

### 1. Architecture & Organization

**Read First**: `ras_commander/hdf/AGENTS.md`

Read this first for:
- 18 HDF classes and their organization
- Module structure (Core, Geometry, Results, Infrastructure, Visualization)
- Class hierarchy and dependencies
- Lazy loading patterns for heavy dependencies
- Decorator usage (`@staticmethod`, `@log_call`, `@standardize_input`)
- File type expectations (plan_hdf vs geom_hdf)
- Common HDF paths in files

**Key Sections**:
- Lines 5-45: Module structure and organization
- Lines 47-114: Class hierarchy and dependencies
- Lines 116-138: Import patterns
- Lines 140-215: Adding new methods (decorator patterns, error handling)

---

### 2. Complete Workflows

**1D Unsteady Results**: `examples/400_1d_hdf_data_extraction.ipynb`

Read this notebook when you need:
- Cross section time series extraction (`HdfResultsXsec`)
- Output time handling
- Computation message extraction
- 1D hydraulic variables

**2D Unsteady Results**: `examples/410_2d_hdf_data_extraction.ipynb`

Read this notebook when you need:
- 2D mesh maximum envelopes (`HdfResultsMesh.get_mesh_maximum`)
- Time series at specific locations
- Spatial grids and polygons
- Complete working examples with real data

**Steady Flow Results**: `examples/401_steady_flow_analysis.ipynb`

Read this notebook when you need:
- Profile detection (`get_steady_profile_names`)
- Water surface elevation extraction by profile
- Multiple profile comparison
- Steady state metadata extraction
- Variable discovery (`list_steady_variables`)

**Dam Breach Results**: `examples/420_breach_results_extraction.ipynb`

Read this notebook when you need:
- Structure identification (`HdfStruc.list_sa2d_connections`)
- Breach time series (`HdfResultsBreach.get_breach_timeseries`)
- Summary statistics and peak values
- Breach geometry evolution
- Complete breach workflow from detection to visualization

---

### 3. Class Reference

**Core HDF Classes** (all in `ras_commander/hdf/`):

| Class | Purpose | Primary Use |
|-------|---------|-------------|
| **HdfResultsPlan** | Plan-level results | Steady profiles, metadata, plan info, output times, computation messages |
| **HdfResultsMesh** | 2D mesh results | Maximum envelopes, time series, spatial grids |
| **HdfResultsXsec** | Cross section results | 1D time series, longitudinal profiles |
| **HdfResultsBreach** | Breach results | Dam breach time series, summary statistics, geometry evolution |
| **HdfMesh** | Mesh geometry | Cell polygons, face points, perimeter extraction |
| **HdfXsec** | XS geometry | Cross section coordinates, attributes |
| **HdfStruc** | Structure geometry | SA/2D connections, breach capability info |
| **HdfHydraulicTables** | HTAB extraction | Rating curves, property tables |

**Read**: `ras_commander/hdf/AGENTS.md` lines 5-45 for complete class list and organization.

---

### 4. Method Signatures

**Instead of duplicating API documentation here**, use these strategies:

#### Strategy 1: Read Docstrings Directly
```python
from ras_commander import HdfResultsPlan
help(HdfResultsPlan.get_steady_wse)  # Complete parameter docs
```

#### Strategy 2: Check Source Files
Navigate to class files in `ras_commander/hdf/`:
- `HdfResultsPlan.py` - Lines 1-500 contain all steady/unsteady methods
- `HdfResultsMesh.py` - Lines 1-400 contain mesh extraction methods
- `HdfResultsXsec.py` - Lines 1-300 contain cross section methods
- `HdfResultsBreach.py` - Lines 1-400 contain breach methods

#### Strategy 3: Use Example Notebooks
Example notebooks show **actual usage** with real HEC-RAS projects:
- See notebook cells for working code patterns
- Notebook markdown explains each step
- Output cells show expected return structures

---

## Common Workflows (Quick Reference)

### Detect Plan Type

```python
is_steady = HdfResultsPlan.is_steady_plan("02")
plan_info = HdfResultsPlan.get_plan_info("02")
```

**Return**: Boolean for `is_steady_plan()`, DataFrame with program version, run type, etc. for `get_plan_info()`

---

### Steady Flow Extraction

```python
# List profiles
profiles = HdfResultsPlan.get_steady_profile_names("02")

# Extract specific profile
wse = HdfResultsPlan.get_steady_wse("02", profile_name="100 year")

# Extract all profiles
wse_all = HdfResultsPlan.get_steady_wse("02")

# Discover variables
vars_dict = HdfResultsPlan.list_steady_variables("02")
```

**Returns**: List of profile names, DataFrame with River/Reach/Station/WSE columns

**Full Details**: `examples/401_steady_flow_analysis.ipynb`

---

### Unsteady Cross Section Time Series

```python
# Get all variables as xarray Dataset
xsec_data = HdfResultsXsec.get_xsec_timeseries("01")

# Access specific variable
wse_ts = xsec_data["Water_Surface"]  # (time, cross_section)
velocity_ts = xsec_data["Velocity_Total"]

# Select specific cross section
target_xs = "River Reach 12345.6"
wse_at_xs = wse_ts.sel(cross_section=target_xs)
```

**Returns**: xarray Dataset with dimensions (time, cross_section), coordinates for River/Reach/Station

**Full Details**: `examples/400_1d_hdf_data_extraction.ipynb`

---

### 2D Mesh Maximum Envelopes

```python
# Get maximum water surface
max_wse = HdfResultsMesh.get_mesh_maximum("01", variable="Water Surface")

# Get maximum depth
max_depth = HdfResultsMesh.get_mesh_maximum("01", variable="Depth")

# Get maximum velocity
max_vel = HdfResultsMesh.get_mesh_maximum("01", variable="Velocity")
```

**Returns**: GeoDataFrame with columns: cell_id, max_value, max_time, geometry (Polygon)

**Full Details**: `examples/410_2d_hdf_data_extraction.ipynb`

---

### Dam Breach Results

```python
from ras_commander import HdfStruc, HdfResultsBreach

# List structures
structures = HdfStruc.list_sa2d_connections("02")

# Get breach info
breach_info = HdfStruc.get_sa2d_breach_info("02")

# Extract time series
breach_ts = HdfResultsBreach.get_breach_timeseries("02", "Dam")

# Get summary statistics
summary = HdfResultsBreach.get_breach_summary("02", "Dam")
```

**Returns**: DataFrames with structure names, breach timing, flows, geometry evolution

**Full Details**: `examples/420_breach_results_extraction.ipynb`

---

## Integration Patterns

### With hdf-analyst Skill

Use this skill for standard API-based extraction. Delegate to `hdf-analyst` agent for custom HDF path navigation, advanced xarray operations, or performance optimization.

**Example Handoff**:
```python
# You handle standard extraction
max_wse = HdfResultsMesh.get_mesh_maximum("01", variable="Water Surface")

# Delegate to hdf-analyst for:
# - Custom HDF group navigation
# - Non-standard path queries
# - Advanced xarray transformations
# - Memory optimization for large files
```

---

## Common Issues & Solutions

### Structure Name Mismatches

**Issue**: Structure names differ between plan files and HDF
**Solution**: Always use `HdfStruc.list_sa2d_connections()` to get HDF names
**Example**: Plan file "Dam" might be "BaldEagleCr Dam" in HDF

### Missing Timesteps

**Issue**: Fewer timesteps than expected in results
**Solution**: Check if simulation completed with `HdfResultsPlan.get_compute_messages()`
**Details**: Partial runs will have truncated output

### Large Memory Usage

**Issue**: Mesh time series extraction uses too much RAM
**Solution**: Extract specific timesteps, not all
**Example**: Use `timestep_indices=[0, 50, 100]` instead of `timestep_indices="all"`

### Variable Not Found

**Issue**: Cannot find expected variable in HDF
**Solution**: Use `HdfResultsPlan.list_steady_variables()` or inspect HDF structure directly
**Note**: Variable names differ between HEC-RAS versions

---

## Cross-References

**Rules** (auto-loaded context):
- `.claude/rules/hec-ras/hdf-files.md` -- Read for HDF domain overview and steady/unsteady detection
- `.claude/rules/python/api-first-principle.md` -- Follow the API-first mandate for all extraction

**Agents** (delegate when needed):
- `hdf-analyst` -- Delegate for advanced HDF analysis beyond standard API
- `hecras-results-analyst` -- Delegate for results interpretation and quality assessment

**Skills** (related workflows):
- `hecras_compute_plans` -- Upstream: run simulations that produce HDF results
- `hecras_parse_compute-messages` -- Use to verify execution completed before extracting

**Primary sources**:
- `ras_commander/hdf/AGENTS.md` -- Complete class hierarchy and architecture
- `examples/400_1d_hdf_data_extraction.ipynb` -- 1D unsteady extraction workflow
- `examples/410_2d_hdf_data_extraction.ipynb` -- 2D mesh results workflow
- `examples/401_steady_flow_analysis.ipynb` -- Steady state extraction workflow
- `examples/420_breach_results_extraction.ipynb` -- Dam breach results workflow
