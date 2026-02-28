# HEC-RAS Geometry Files

**Context**: Parsing and modifying HEC-RAS geometry files
**Priority**: High - affects model structure operations
**Auto-loads**: Yes (geometry-related code)

## Primary Source

**See**: `ras_commander/geom/AGENTS.md` for complete geometry documentation.

## Overview

HEC-RAS geometry files (`.g##`) use fixed-width text format. ras-commander provides parsing and modification capabilities through static class methods.

## Key Classes

| Class | Purpose |
|-------|---------|
| `RasGeometry` | 1D cross section parsing, reach/river structure |
| `RasGeo` | 2D mesh Manning's n modification |
| `RasGeometryUtils` | Fixed-width parsing utilities |
| `RasStruct` | Inline structures (bridges, culverts, weirs) |

## Critical Pattern: Fixed-Width Parsing

HEC-RAS geometry files use **fixed-width columns**, not delimiters:

```
# Example cross section header (fixed positions)
Type RM Length L Ch R  = 1 ,12345.67,   100.0,   100.0,   100.0

# Positions matter:
# Cols 1-6: Type code
# Cols 7-12: River mile
# etc.
```

**Warning**: Incorrect parsing can corrupt geometry files.

## Quick Reference

```python
from ras_commander import RasGeometry, RasGeo

# Get cross sections from geometry file
xs_df = RasGeometry.get_cross_sections(geom_file)

# Get river/reach structure
rivers = RasGeometry.get_rivers(geom_file)

# Modify 2D Manning's n values
RasGeo.set_2d_mannings_n(geom_file, new_n_values)
```

## Bank Station Interpolation

The 0.02-unit gap constant is critical for bank station interpolation:

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

Cross section parsing uses `_find_xs_section_end()` to dynamically search to the end of each XS section. There is no fixed search range limit — the parser searches until it finds the next `Type RM Length L Ch R =` header, `River Reach=` block, or end of file. This handles XS with arbitrarily many GIS cut line points (verified with 462-point real-world FEMA models).

## See Also

- **Complete Documentation**: `ras_commander/geom/AGENTS.md`
- **Example Notebooks**: `examples/201_1d_plaintext_geometry.ipynb`, `examples/202_2d_plaintext_geometry.ipynb`
- **Geometry Repair**: `ras_commander/fixit/AGENTS.md`

---

**Key Takeaway**: HEC-RAS geometry uses fixed-width format. Respect 500-point computational limit and 0.02-unit bank station precision. Section search is dynamic (no fixed range limit).
