# geom_df Enhancement Specification

**Created**: 2026-01-07
**Priority**: HIGH
**Backlog Item**: arch-df-002
**Effort Estimate**: 8-12 hours

---

## Overview

Enhance `ras.geom_df` with comprehensive geometry metadata columns that provide project overview at a glance. Currently, geom_df only contains basic information (file paths, numbers). This enhancement adds detailed geometry type detection and structure counts.

---

## Current geom_df Structure

```python
geom_df columns:
- geom_number (str): "01", "02", etc.
- file_path (str): Full path to .g## file
- Geom Title (str): Geometry title from .prj file
- [other basic metadata]
```

---

## Proposed New Columns

### Boolean Geometry Type Flags

| Column | Type | Description | Source |
|--------|------|-------------|--------|
| `has_1d_xs` | bool | Contains 1D cross sections | Parse geometry file or HDF |
| `has_2d_mesh` | bool | Contains 2D mesh areas | Parse geometry file or HDF |
| `has_storage_areas` | bool | Contains storage areas | Parse geometry file |
| `has_inline_structures` | bool | Has inline structures (bridges, culverts, etc.) | Parse geometry file |
| `has_lateral_structures` | bool | Has lateral structures | Parse geometry file |
| `has_sa_2d_connections` | bool | Has SA-to-2D connections | Parse geometry file |

### Count Columns - Cross Sections & Basic Geometry

| Column | Type | Description | How to Get |
|--------|------|-------------|------------|
| `num_cross_sections` | int | Total 1D cross sections | `len(RasGeometry.get_cross_sections(geom_file))` |
| `num_rivers` | int | Number of river centerlines | `len(RasGeometry.get_rivers(geom_file))` |
| `num_reaches` | int | Number of reaches (across all rivers) | Count from rivers structure |
| `num_storage_areas` | int | Storage area count | Parse "Type RM Length" lines with SA flag |

### Count Columns - Inline Structures (Main Channel)

| Column | Type | Description | How to Get |
|--------|------|-------------|------------|
| `num_inline_structures` | int | Total inline structures | Sum of bridge+culvert+gate+weir+etc |
| `num_bridges` | int | Bridge count | `RasStruct` parse for "Type RM Length" bridge lines |
| `num_culverts` | int | Culvert count | `RasStruct` parse for culvert lines |
| `num_gates` | int | Inline gate count | Parse gate lines |
| `num_weirs` | int | Inline weir count | Parse weir lines |
| `num_rating_curves` | int | Rating curve structures | Parse rating curve lines |

### Count Columns - Lateral Structures

| Column | Type | Description | How to Get |
|--------|------|-------------|------------|
| `num_lateral_structures` | int | Total lateral structures | Sum of lateral weir+gate+culvert+pump |
| `num_lateral_weirs` | int | Lateral weir count | Parse lateral weir lines |
| `num_lateral_gates` | int | Lateral gate count | Parse lateral gate lines |
| `num_lateral_culverts` | int | Lateral culvert count | Parse lateral culvert lines |
| `num_pumps` | int | Pump station count | Parse pump lines |

### Count Columns - 2D Mesh & Connections

| Column | Type | Description | How to Get |
|--------|------|-------------|------------|
| `mesh_cell_count` | int | Total 2D mesh cells (all areas) | `HdfMesh.get_mesh_cell_points(geom_hdf)` or parse .g## |
| `num_2d_areas` | int | Count of 2D flow areas | `len(HdfMesh.get_mesh_area_names(geom_hdf))` |
| `mesh_area_names` | list[str] | Names of 2D flow areas | `HdfMesh.get_mesh_area_names(geom_hdf)` |
| `num_sa_2d_connections` | int | Storage Area to 2D connections | Parse connection lines |
| `num_2d_connections` | int | 2D-to-2D connections | Parse 2D area connection lines |
| `num_1d_2d_connections` | int | 1D-to-2D connection count | Parse connection weirs/culverts |

---

## Implementation Strategy

### Phase 1: Geometry HDF Parsing (Preferred)

If `.g##.hdf` exists (HEC-RAS 6.x):
```python
def _enhance_geom_metadata_from_hdf(geom_row):
    """Extract geometry metadata from preprocessed HDF file."""
    geom_hdf = Path(geom_row['file_path']).with_suffix('.hdf')

    if not geom_hdf.exists():
        return _enhance_geom_metadata_from_plaintext(geom_row)

    with h5py.File(geom_hdf, 'r') as hdf:
        # 2D Mesh detection
        has_2d = 'Geometry/2D Flow Areas' in hdf
        if has_2d:
            mesh_names = HdfMesh.get_mesh_area_names(hdf)
            mesh_cells = HdfMesh.get_mesh_cell_points(hdf)
            cell_count = len(mesh_cells)
        else:
            mesh_names = []
            cell_count = 0

        # 1D Cross section detection
        has_1d = 'Geometry/Cross Sections' in hdf
        if has_1d:
            xs_count = len(hdf['Geometry/Cross Sections/Attributes'])
        else:
            xs_count = 0

        # Structures (need to parse plain text or add HDF extraction)
        # For now, fall back to plain text parsing

    return {
        'has_2d_mesh': has_2d,
        'has_1d_xs': has_1d,
        'num_cross_sections': xs_count,
        'mesh_cell_count': cell_count,
        'mesh_area_names': mesh_names,
        'num_2d_areas': len(mesh_names),
        # ... other fields from plain text
    }
```

### Phase 2: Plain Text Parsing (Fallback & Legacy)

For HEC-RAS 5.x or when .g##.hdf doesn't exist:
```python
def _enhance_geom_metadata_from_plaintext(geom_row):
    """Extract geometry metadata from plain text .g## file."""
    geom_file = Path(geom_row['file_path'])

    # Use existing RasGeometry, RasStruct methods
    xs_df = RasGeometry.get_cross_sections(geom_file)
    rivers = RasGeometry.get_rivers(geom_file)

    # Parse structures (may need new methods in RasStruct)
    # Count "Type RM Length" lines by structure type

    return {
        'has_1d_xs': len(xs_df) > 0,
        'num_cross_sections': len(xs_df),
        'num_rivers': len(rivers),
        # ... count structures from parse
    }
```

### Phase 3: Integration into RasPrj

Modify `RasPrj.get_geom_entries()`:
```python
def get_geom_entries(self):
    """Get geometry file entries with enhanced metadata."""
    # Current logic to parse basic geom entries
    geom_df = self._parse_basic_geom_entries()

    # Enhance each row with detailed metadata
    for idx, row in geom_df.iterrows():
        metadata = self._enhance_geom_metadata(row)
        for key, value in metadata.items():
            geom_df.at[idx, key] = value

    return geom_df
```

---

## Example Usage (After Implementation)

### Quick Project Overview
```python
from ras_commander import init_ras_project

init_ras_project("MyModel", "6.6")

# Get quick overview of all geometries
print(ras.geom_df[[
    'geom_number', 'Geom Title',
    'has_1d_xs', 'has_2d_mesh',
    'num_cross_sections', 'mesh_cell_count',
    'num_inline_structures', 'num_sa_2d_connections'
]])

# Output:
#   geom  Geom Title        has_1d  has_2d  num_xs  mesh_cells  inline_struct  sa_2d_conn
#   01    Base Geometry     True    False   245     0           12             0
#   02    With 2D Area      True    True    245     89879       12             3
#   03    Future Conditions False   True    0       125000      0              0
```

### Filter Geometries by Type
```python
# Find 2D-only geometries
mesh_geoms = ras.geom_df[ras.geom_df['has_2d_mesh'] & ~ras.geom_df['has_1d_xs']]

# Find complex geometries (1D + 2D + structures)
complex_geoms = ras.geom_df[
    ras.geom_df['has_1d_xs'] &
    ras.geom_df['has_2d_mesh'] &
    (ras.geom_df['num_inline_structures'] > 0)
]

# Find geometries with SA-2D connections
sa_2d_geoms = ras.geom_df[ras.geom_df['num_sa_2d_connections'] > 0]
```

### Agent Decision Making
```python
# Agent can quickly determine project complexity
total_xs = ras.geom_df['num_cross_sections'].sum()
total_mesh = ras.geom_df['mesh_cell_count'].sum()
total_structures = ras.geom_df['num_inline_structures'].sum()

if total_mesh > 100000:
    print("Large 2D model - recommend parallel execution with multiple cores")
elif total_structures > 50:
    print("Many structures - geometry preprocessing may be slow")
elif total_xs > 500:
    print("Large 1D network - recommend efficient result extraction methods")
```

---

## Implementation Files to Modify

| File | Changes Required |
|------|------------------|
| `ras_commander/RasPrj.py` | Add `_enhance_geom_metadata()` method, integrate into `get_geom_entries()` |
| `ras_commander/geom/RasGeometry.py` | Add structure counting methods if not already present |
| `ras_commander/geom/RasStruct.py` | Add methods to count specific structure types |
| `ras_commander/hdf/HdfMesh.py` | Already has needed methods (get_mesh_area_names, get_mesh_cell_points) |

---

## Testing Requirements

1. **Test with various geometry types**:
   - 1D-only (Muncie)
   - 2D-only
   - Mixed 1D/2D (BaldEagleCrkMulti2D)
   - With structures (bridges, culverts, weirs)
   - With SA-2D connections

2. **Test with HEC-RAS versions**:
   - 6.x (with .g##.hdf)
   - 5.x (plain text only)
   - Verify fallback logic works

3. **Validate counts**:
   - Compare against GUI (open in RAS Mapper, count manually)
   - Ensure all structure types detected correctly

---

## Documentation Requirements

After implementation:
1. Update `ras_commander/AGENTS.md` with new geom_df columns
2. Add example notebook demonstrating enhanced geom_df usage
3. Update `.claude/rules/python/dataframe-first-principle.md` with new columns
4. Document in DataFrame Navigator skill (arch-df-004)

---

## Benefits

1. **Users**: Instant project overview without opening GUI
2. **Agents**: Make informed decisions about execution strategies
3. **Automation**: Filter/select geometries by characteristics
4. **Validation**: Quickly identify geometry complexity before execution
5. **Reporting**: Generate project summaries programmatically

---

## Future Enhancements (Beyond arch-df-002)

- `num_breach_locations` - Dam breach locations
- `num_inline_pumps` - Inline pump stations
- `terrain_source` - Terrain file used
- `crs_epsg` - Coordinate system EPSG code
- `extent_bounds` - Bounding box (minx, miny, maxx, maxy)
- `upstream_xs` - Upstream-most cross section ID
- `downstream_xs` - Downstream-most cross section ID

---

**See Also**:
- Backlog item: `agent_tasks/BACKLOG.md` (arch-df-002)
- Rule: `.claude/rules/python/dataframe-first-principle.md`
- API: `ras_commander/geom/AGENTS.md`
