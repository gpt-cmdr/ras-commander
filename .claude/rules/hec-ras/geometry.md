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

- **Maximum Points**: 450 per cross section (HEC-RAS hard limit)
- **Minimum Points**: 3 (left bank, thalweg, right bank)

```python
# Check point count before writing
if len(stations) > 450:
    raise ValueError("Cross section exceeds 450-point limit")
```

## See Also

- **Complete Documentation**: `ras_commander/geom/AGENTS.md`
- **Example Notebooks**: `examples/201_1d_plaintext_geometry.ipynb`, `examples/202_2d_plaintext_geometry.ipynb`
- **Geometry Repair**: `ras_commander/fixit/AGENTS.md`

---

**Key Takeaway**: HEC-RAS geometry uses fixed-width format. Respect 450-point limit and 0.02-unit bank station precision.
