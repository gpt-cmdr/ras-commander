# HEC-RAS Geometry Files

**Context**: Parsing and modifying HEC-RAS geometry files
**Priority**: High - affects model structure operations
**Auto-loads**: Yes (geometry-related code)

## Primary Source

**See**: `ras_commander/geom/AGENTS.md` for complete geometry documentation.

## Overview

HEC-RAS geometry files (`.g##`) use fixed-width text format. Use ras-commander's static class methods to parse and modify geometry data.

## Key Classes

| Class | Purpose |
|-------|---------|
| `RasGeometry` | 1D cross section parsing, reach/river structure |
| `RasGeo` | 2D mesh Manning's n modification |
| `RasGeometryUtils` | Fixed-width parsing utilities |
| `RasStruct` | Inline structures (bridges, culverts, weirs) |

## Critical Pattern: Fixed-Width Parsing

Always parse geometry files using **fixed-width columns**, not delimiters:

```
# Example cross section header (fixed positions)
Type RM Length L Ch R  = 1 ,12345.67,   100.0,   100.0,   100.0

# Positions matter:
# Cols 1-6: Type code
# Cols 7-12: River mile
# etc.
```

**Warning**: Incorrect parsing will corrupt geometry files. Never attempt manual fixed-width parsing -- use the API classes instead.

## Quick Reference

Call these static methods directly for common geometry operations:

```python
from ras_commander import RasGeometry
from ras_commander.geom import GeomLandCover
from ras_commander.hdf import HdfLandCover

# Get cross sections from geometry file
xs_df = RasGeometry.get_cross_sections(geom_file)

# Get river/reach structure
rivers = RasGeometry.get_rivers(geom_file)

# Modify 2D Manning's n base table (plain text geometry)
GeomLandCover.set_base_mannings_n(geom_file, mannings_df)

# Modify land cover sidecar (raster class -> n mapping)
HdfLandCover.set_landcover_raster_map(sidecar_hdf, {"Forest": 0.12})
```

## Bank Station Interpolation

Apply the 0.02-unit gap constant for bank station interpolation:

```python
# Bank stations use 0.02-unit offset for HEC-RAS format compliance
left_bank = station - 0.02
right_bank = station + 0.02
```

**Why**: HEC-RAS requires specific precision for bank station definitions.

## Cross Section Limits

- **Maximum Points**: 500 per cross section (HEC-RAS computational limit)
- **Minimum Points**: 3 (left bank, thalweg, right bank)
- **GIS Cut Line Points**: Can exceed 500 (up to 5,000 pasted in GUI), but must be filtered before computation

```python
# Check point count before writing
if len(stations) > 500:
    raise ValueError("Cross section exceeds 500-point limit")
```

## Dynamic Section Search

Use `_find_xs_section_end()` to dynamically search to the end of each XS section. Do not impose a fixed search range limit -- the parser searches until it finds the next `Type RM Length L Ch R =` header, `River Reach=` block, or end of file. This handles XS with arbitrarily many GIS cut line points (verified with 462-point real-world FEMA models).

## 2D Flow Area Subgrid Sampling Options

For HEC-RAS 6.x 2D models, check and configure subgrid sampling:

```python
from ras_commander import GeomStorage

# Read current settings
settings = GeomStorage.get_2d_flow_area_settings("model.g01")
print(settings[['name', 'spatially_varied_mann_on_faces', 'composite_classification']])

# Enable both (recommended best practice)
GeomStorage.set_2d_flow_area_settings(
    "model.g01", "Perimeter 1",
    spatially_varied_mann_on_faces=True,
    composite_classification=True,
)
```

**Reference**: [HEC-RAS Subgrid Concept](https://www.hec.usace.army.mil/confluence/rasdocs/d2sd/ras2dsedtr/latest/numerical-methods/subgrid-concept)

`RasCheck` automatically suggests enabling these when disabled (WARNING severity).

## Cross-References

**Agents** (delegate when needed):
- `geometry-parser` -- Delegate for geometry file parsing and cross-section analysis
- `quality-assurance` -- Delegate for geometry repair with RasFixit

**Skills** (related workflows):
- `hecras_parse_geometry` -- Use for geometry parsing workflows
- `qa_repair_geometry` -- Use to fix blocked obstructions and geometry errors

**Rules** (auto-loaded context):
- `.claude/rules/hec-ras/land-cover-mannings-n.md` -- Land cover Manning's n override architecture and NaN semantics
- `.claude/rules/python/state-machine-empty-line-handling.md` -- Read when parsing multi-line geometry blocks

**Primary sources**:
- `ras_commander/geom/AGENTS.md` -- Complete geometry subpackage documentation
- `examples/201_1d_plaintext_geometry.ipynb` -- 1D geometry parsing examples
- `examples/202_2d_plaintext_geometry.ipynb` -- 2D Manning's n modification

---

**Key Takeaway**: HEC-RAS geometry uses fixed-width format. Respect the 500-point computational limit and 0.02-unit bank station precision. Section search is dynamic (no fixed range limit).
