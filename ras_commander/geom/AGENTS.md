# AGENTS.md for ras_commander/geom

This file provides guidance for AI agents working within the `geom` subpackage.

## Subpackage Overview

The `geom` subpackage provides comprehensive functionality for parsing and modifying HEC-RAS plain text geometry files (.g##). It handles 1D cross sections, storage areas, lateral structures, connections, inline weirs, bridges, and culverts.

## Module Organization

| Module | Class | Description |
|--------|-------|-------------|
| GeomParser.py | `GeomParser` | Core parsing utilities for fixed-width formats |
| GeomPreprocessor.py | `GeomPreprocessor` | Geometry preprocessor file management |
| GeomLandCover.py | `GeomLandCover` | 2D Manning's n land cover tables |
| GeomCrossSection.py | `GeomCrossSection` | 1D cross section operations |
| GeomStorage.py | `GeomStorage` | Storage area elevation-volume curves |
| GeomLateral.py | `GeomLateral` | Lateral structures and SA/2D connections |
| GeomInlineWeir.py | `GeomInlineWeir` | Inline weir structures |
| GeomBridge.py | `GeomBridge` | Bridge/culvert structure geometry |
| GeomCulvert.py | `GeomCulvert` | Culvert data extraction |
| GeomHtab.py | `GeomHtab` | Unified HTAB parameter optimization |
| GeomHtabUtils.py | `GeomHtabUtils` | HTAB calculation utilities |
| GeomMetadata.py | `GeomMetadata` | Efficient geometry element count extraction |

## Technical Patterns

### Fixed-Width Parsing
All geometry files use FORTRAN-era fixed-width format:
- **8-character columns** for numeric data
- **10 values per line** (80 characters total)
- **Count interpretation**: "#Sta/Elev= 40" means 40 PAIRS (80 total values)

Use `GeomParser.parse_fixed_width()` for reading and `GeomParser.format_fixed_width()` for writing.

### Import Patterns
Within this subpackage, use relative imports:
```python
from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser  # For inter-module dependencies
```

### Static Method Pattern
All classes use static methods with `@log_call` decorators:
```python
@staticmethod
@log_call
def get_something(geom_file: Union[str, Path], ...) -> pd.DataFrame:
    ...
```

### Error Handling
Standard exception hierarchy:
- `FileNotFoundError`: Geometry file doesn't exist
- `ValueError`: Invalid parameters or data not found
- `IOError`: File read/write failures

## API Reference

### GeomParser (Parsing Utilities)
- `parse_fixed_width(line, column_width=8)` - Parse fixed-width numeric data
- `format_fixed_width(values, column_width=8, values_per_line=10, precision=2)` - Format for writing
- `interpret_count(keyword, count_value)` - Interpret count declarations
- `identify_section(lines, keyword, start_index=0)` - Find section boundaries
- `extract_keyword_value(line, keyword)` - Extract value following keyword
- `extract_comma_list(line, keyword)` - Extract comma-separated list
- `create_backup(file_path)` - Create .bak backup

### GeomCrossSection (Cross Sections)
- `get_cross_sections(geom_file, river=None, reach=None)` - List all XS metadata
- `get_station_elevation(geom_file, river, reach, rs)` - Get XS geometry
- `set_station_elevation(geom_file, river, reach, rs, df, bank_left=None, bank_right=None)` - Modify XS
- `get_bank_stations(geom_file, river, reach, rs)` - Get bank locations
- `get_expansion_contraction(geom_file, river, reach, rs)` - Get coefficients
- `get_mannings_n(geom_file, river, reach, rs)` - Get roughness values

### GeomStorage (Storage Areas)
- `get_storage_areas(geom_file, exclude_2d=True)` - List storage area names
- `get_elevation_volume(geom_file, area_name)` - Get elevation-volume curve

### GeomLateral (Laterals & Connections)
- `get_lateral_structures(geom_file, river=None, reach=None)` - List lateral structures
- `get_weir_profile(geom_file, river, reach, rs, position=0)` - Get weir profile
- `get_connections(geom_file)` - List SA/2D connections
- `get_connection_profile(geom_file, connection_name)` - Get connection weir profile
- `get_connection_gates(geom_file, connection_name)` - Get gate definitions

### GeomInlineWeir (Inline Weirs)
- `get_weirs(geom_file, river=None, reach=None)` - List inline weirs
- `get_profile(geom_file, river, reach, rs)` - Get weir crest profile
- `get_gates(geom_file, river, reach, rs)` - Get gate definitions

### GeomBridge (Bridges)
- `get_bridges(geom_file, river=None, reach=None)` - List bridge structures
- `get_deck(geom_file, river, reach, rs)` - Get deck geometry
- `get_piers(geom_file, river, reach, rs)` - Get pier data
- `get_abutment(geom_file, river, reach, rs)` - Get abutment data
- `get_approach_sections(geom_file, river, reach, rs)` - Get approach XS data
- `get_coefficients(geom_file, river, reach, rs)` - Get loss coefficients
- `get_htab(geom_file, river, reach, rs)` - Get HTAB parameters

### GeomCulvert (Culverts)
- `get_culverts(geom_file, river, reach, rs)` - Get culverts at a location
- `get_all(geom_file, river=None, reach=None)` - Get all culverts in file

### GeomLandCover (2D Manning's n)
- `get_base_mannings_n(geom_file)` - Read base Manning's n table
- `set_base_mannings_n(geom_file, df)` - Write base Manning's n table
- `get_region_mannings_n(geom_file)` - Read region overrides
- `set_region_mannings_n(geom_file, df)` - Write region overrides

### GeomPreprocessor
- `clear_geompre_files(plan_files=None, ras_object=None)` - Clear preprocessor files

### GeomHtab (HTAB Optimization)
- `optimize_all_htab_from_results(geom_file, hdf_results_path, ...)` - One-call optimization of ALL HTAB in geometry file
- `optimize_xs_htab_from_results(geom_file, hdf_results_path, ...)` - Optimize all cross section HTAB from HDF results
- `optimize_structures_htab_from_results(geom_file, hdf_results_path, ...)` - Optimize all structure HTAB from HDF results
- `get_optimization_report(geom_file, hdf_results_path, ...)` - Generate markdown report showing current vs recommended HTAB

### GeomHtabUtils (HTAB Calculations)
- `calculate_optimal_xs_htab(invert, max_wse, safety_factor=1.3, ...)` - Calculate optimal XS HTAB parameters
- `calculate_optimal_structure_htab(struct_invert, max_hw, max_tw, max_flow, ...)` - Calculate optimal structure HTAB parameters
- `validate_xs_htab_params(params, xs_invert, xs_top)` - Validate XS HTAB parameters against HEC-RAS limits
- `validate_structure_htab_params(params, struct_invert, max_expected_hw, max_expected_flow)` - Validate structure HTAB parameters
- `get_xs_htab_defaults()` - Get default XS HTAB parameter recommendations
- `get_structure_htab_defaults()` - Get default structure HTAB parameter recommendations

### GeomMetadata (Element Count Extraction)
- `get_geometry_counts(geom_path, hdf_path=None)` - Extract all geometry element counts efficiently

**Returns dict with:**
- `has_1d_xs` (bool) - True if num_cross_sections > 0
- `has_2d_mesh` (bool) - True if mesh_area_names is not empty
- `num_cross_sections` (int) - Count of 1D cross sections
- `num_inline_structures` (int) - Total bridges + culverts + weirs
- `num_bridges` (int) - Bridge count
- `num_culverts` (int) - Culvert count
- `num_weirs` (int) - Inline weir count
- `num_gates` (int) - Gate count
- `num_lateral_structures` (int) - Lateral structure count
- `num_sa_2d_connections` (int) - SA to 2D connections count
- `mesh_cell_count` (int) - Total 2D mesh cells
- `mesh_area_names` (list[str]) - Names of 2D flow areas

**Performance:**
- HDF path: ~10-50ms for all counts (single file read)
- Text path: ~100-500ms per geometry file (full file parse)

**Example:**
```python
from ras_commander.geom import GeomMetadata

# Prefer HDF when available (fast)
counts = GeomMetadata.get_geometry_counts(
    geom_path="model.g01",
    hdf_path="model.g01.hdf"
)

print(f"1D XS: {counts['num_cross_sections']}")
print(f"2D Mesh: {counts['mesh_area_names']}")
print(f"Total cells: {counts['mesh_cell_count']}")
```

## geom_df Metadata Integration

Starting with v0.88+, `ras.geom_df` automatically includes 12 metadata columns extracted via `GeomMetadata`. These columns provide quick access to geometry element counts without needing to parse individual files.

### Metadata Columns in geom_df

When you initialize a project with `init_ras_project()`, the following columns are automatically populated in `ras.geom_df`:

| Column | Type | Description |
|--------|------|-------------|
| `has_1d_xs` | bool | True if num_cross_sections > 0 |
| `has_2d_mesh` | bool | True if mesh_area_names is not empty |
| `num_cross_sections` | int | Count of 1D cross sections |
| `num_inline_structures` | int | Total bridges + culverts + weirs |
| `num_bridges` | int | Bridge count |
| `num_culverts` | int | Culvert count |
| `num_weirs` | int | Inline weir count |
| `num_gates` | int | Gate count |
| `num_lateral_structures` | int | Lateral structure count |
| `num_sa_2d_connections` | int | SA to 2D connections count |
| `mesh_cell_count` | int | Total 2D mesh cells |
| `mesh_area_names` | list[str] | Names of 2D flow areas |

### Usage Example

```python
from ras_commander import init_ras_project, ras

init_ras_project("path/to/project", "6.6")

# Access metadata directly from geom_df
for _, row in ras.geom_df.iterrows():
    print(f"Geometry: {row['geom_file']}")
    print(f"  1D Cross Sections: {row['num_cross_sections']}")
    print(f"  2D Mesh Cells: {row['mesh_cell_count']}")
    print(f"  2D Areas: {row['mesh_area_names']}")
    print(f"  Bridges: {row['num_bridges']}")
    print(f"  Inline Weirs: {row['num_weirs']}")

# Filter geometries by type
mixed_models = ras.geom_df[(ras.geom_df['has_1d_xs']) & (ras.geom_df['has_2d_mesh'])]
pure_2d = ras.geom_df[(~ras.geom_df['has_1d_xs']) & (ras.geom_df['has_2d_mesh'])]
```

### Extraction Behavior

The metadata extraction uses a two-tier approach for optimal performance:

1. **HDF-based extraction (fast)**: When `.g##.hdf` files exist, counts are extracted from HDF structures in ~10-50ms
2. **Plain text fallback (slower)**: When no HDF exists, parses the `.g##` file directly (~100-500ms)

**Note**: Lateral structures and SA/2D connections are always extracted from plain text (not stored in HDF).

### Graceful Degradation

If metadata extraction fails for any geometry file, default values are used:
- Integer columns default to `0`
- Boolean columns default to `False`
- `mesh_area_names` defaults to empty list `[]`

This ensures `geom_df` is always complete and consistent, even if some geometry files are malformed or inaccessible.

## HTAB Optimization

HTAB (Hydraulic Table) parameters control how HEC-RAS pre-computes hydraulic property tables. Poorly configured HTAB can cause extrapolation errors during simulation.

### When to Use HTAB Optimization

- **After initial simulation**: Optimize HTAB based on observed max WSE/flows
- **Before production runs**: Ensure HTAB covers expected range with safety factor
- **Dam break analysis**: Use higher safety factors (2.0x) for extreme events

### Optimization Workflow

```python
from ras_commander.geom import GeomHtab

# One-call optimization of ALL HTAB from existing results
result = GeomHtab.optimize_all_htab_from_results(
    geom_file="model.g01",
    hdf_results_path="model.p01.hdf",
    xs_safety_factor=1.3,       # 30% safety on XS depth
    structure_hw_safety=2.0     # 100% safety on structure HW
)
print(f"Modified {result['xs_modified']} XS, {result['structures_modified']} structures")
print(f"Backup at: {result['backup']}")

# After optimization, re-run geometric preprocessor
from ras_commander import RasCmdr
RasCmdr.compute_plan("01", clear_geompre=True)
```

### Safety Factor Recommendations

| Scenario | XS Safety Factor | Structure Safety Factor |
|----------|-----------------|------------------------|
| Typical flood | 1.2 - 1.5 | 1.5 - 2.0 |
| Dam break | 2.0 | 2.0 - 3.0 |
| Calibration runs | 1.3 (default) | 2.0 (default) |

### Key Technical Details

- **XS HTAB**: Starting elevation set to invert (no offset), 500 points max, increment auto-adjusted
- **Structure HTAB**: Safety applied to RANGE above invert, not absolute elevation
- **Backup**: Single backup created before any modifications
- **Example Notebook**: `examples/830_htab_optimization.ipynb` (when created)

See `feature_dev_notes/HTAB_Parameter_Modification/` for algorithm details.

## Culvert Shape Codes

| Code | Shape |
|------|-------|
| 1 | Circular |
| 2 | Box |
| 3 | Pipe Arch |
| 4 | Ellipse |
| 5 | Arch |
| 6 | Semi-Circle |
| 7 | Low Profile Arch |
| 8 | High Profile Arch |
| 9 | Con Span |

## Critical Implementation Notes

1. **Bank Station Interpolation**: When modifying cross sections with `set_station_elevation()`, bank stations MUST appear as exact points in the station/elevation data. The method handles this automatically.

2. **450 Point Limit**: HEC-RAS enforces a maximum of 450 points per cross section. Validate before writing.

3. **Backup Files**: All write operations create `.bak` backup files automatically.

4. **Case Sensitivity**: River, reach, and RS parameters are case-sensitive and must match exactly.

## Deprecated Classes (Backward Compatibility)

The following classes provide backward compatibility and will be removed before v1.0:
- `RasGeo` → Use `GeomPreprocessor` and `GeomLandCover`
- `RasGeometry` → Use `GeomCrossSection`, `GeomStorage`, `GeomLateral`
- `RasGeometryUtils` → Use `GeomParser`

**Note**: `RasStruct` has been removed without backward compatibility.
