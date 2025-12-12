# Reference Documentation - Geometry Parser

Technical reference for parsing and modifying HEC-RAS geometry files.

## Document Overview

This folder contains detailed technical documentation for the geometry parser subagent.

### [api-patterns.md](api-patterns.md)
Complete API reference for all 9 modules in `ras_commander.geom`:

- **GeomParser** - Core parsing utilities (fixed-width, count interpretation)
- **GeomPreprocessor** - Preprocessor file management
- **GeomCrossSection** - Cross section operations (read/write station-elevation)
- **GeomStorage** - Storage area elevation-volume curves
- **GeomLateral** - Lateral structures and SA/2D connections
- **GeomInlineWeir** - Inline weir structures
- **GeomBridge** - Bridge/culvert geometry
- **GeomCulvert** - Culvert data extraction
- **GeomLandCover** - 2D Manning's n land cover tables

**Use When**: Need function signatures, parameters, return types, or usage examples.

### [parsing-algorithms.md](parsing-algorithms.md)
Technical details of FORTRAN-era fixed-width format parsing:

- **Fixed-Width Column Format** - 8-character columns, 10 values per line
- **Count Interpretation** - Pair vs value-based counts (#Sta/Elev= 40 means 80 values)
- **Section Terminators** - Blank lines and keyword markers
- **Keyword Extraction** - Fixed-width and comma-separated formats
- **Common Parsing Patterns** - XS, storage areas, bridges, inline weirs
- **Performance Considerations** - Large files, error recovery, caching

**Use When**: Need to understand file format structure, implement new parsers, or debug parsing issues.

### [modification-patterns.md](modification-patterns.md)
Best practices for safe geometry file modification:

- **Backup File Creation** - Automatic `.bak` files before writing
- **Bank Station Requirements** - Automatic interpolation and insertion
- **450 Point Limit Validation** - Point count checks and simplification strategies
- **Safe File Writing** - Atomic writes with temp files
- **Common Modification Workflows** - Real-world examples
- **Error Handling** - Validation, rollback, audit logging

**Use When**: Need to modify geometry files, handle bank stations, validate data, or implement error recovery.

## Quick Reference

### Most Common Operations

**List all cross sections**:
```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection
xs_df = GeomCrossSection.get_cross_sections("model.g01")
```

**Read cross section geometry**:
```python
df = GeomCrossSection.get_station_elevation(
    "model.g01", "Ohio River", "Reach 1", "1000"
)
```

**Modify cross section** (bank stations auto-handled):
```python
GeomCrossSection.set_station_elevation(
    "model.g01", "Ohio River", "Reach 1", "1000",
    df, bank_left=50.0, bank_right=250.0
)
```

**Read bridge geometry**:
```python
from ras_commander.geom.GeomBridge import GeomBridge
deck_df = GeomBridge.get_deck("model.g01", "Ohio River", "Reach 1", "1000")
```

**Update 2D Manning's n**:
```python
from ras_commander.geom.GeomLandCover import GeomLandCover
lc_df = GeomLandCover.get_base_mannings_n("model.g01")
lc_df.loc[lc_df['LandCoverID'] == 42, 'ManningsN'] = 0.15
GeomLandCover.set_base_mannings_n("model.g01", lc_df)
```

## Implementation Guide

For implementation details and coding conventions, see:
**[../../ras_commander/geom/AGENTS.md](../../../ras_commander/geom/AGENTS.md)**

That file contains:
- Module organization and dependencies
- Static method patterns
- Import conventions
- Error handling standards
- Deprecated class mappings

## File Format Examples

### Cross Section (Fixed-Width Format)
```
Type RM Length L Ch R = 1 ,1000    ,500   ,100   ,300
#Sta/Elev= 40
    0.00   100.00    10.00    99.50    20.00    99.00    30.00    98.50    40.00    98.00
   50.00    97.50    60.00    97.00    70.00    96.50    80.00    96.00    90.00    95.50
  100.00    95.00   110.00    95.50   120.00    96.00   130.00    96.50   140.00    97.00
Bank Sta=      50.00,     250.00
#Mann= 3
    0.04    0.03    0.04
```

### Storage Area Elevation-Volume
```
Storage Area= Detention Basin 1
#Elev/Volume= 25
  100.00   0.00  101.00   5.50  102.00   12.00  103.00   20.00  104.00   30.00
  105.00   42.00  106.00   56.00  107.00   72.00  108.00   90.00  109.00  110.00
```

### Bridge Deck
```
Type RM Length L Ch R = 3 ,1000    ,500   ,100   ,300
US/DS=U
Deck/Roadway
Sta/Elev= 30
    0.00   105.00    20.00   105.00    40.00   105.00    60.00   105.00    80.00   105.00
Dist Deck=    0.00
Width Deck=    50.00
```

## Key Concepts

### Fixed-Width Format
- **8 characters per value** (FORTRAN convention)
- **10 values per line** (80 characters total)
- Right-aligned with leading spaces
- 2 decimal places typical precision

### Count Interpretation
- `#Sta/Elev= 40` → 40 PAIRS → 80 values → 8 lines
- `#Elev/Volume= 25` → 25 PAIRS → 50 values → 5 lines
- `#Mann= 3` → 3 VALUES → 1 line

### Bank Station Interpolation
- Bank stations MUST exist in station-elevation data
- `set_station_elevation()` handles automatically:
  1. Checks if bank stations present
  2. Interpolates elevations at bank locations
  3. Inserts bank points into sorted array
  4. Writes complete dataset

### 450 Point Limit
- HEC-RAS enforces 450 points per cross section
- Always validate before writing
- Use simplification if needed (Douglas-Peucker, uniform sampling)

## Error Messages

### Common Errors

**FileNotFoundError**: Geometry file doesn't exist
```
Solution: Verify file path and extension (.g01, .g02, etc.)
```

**ValueError: River/Reach/RS not found**
```
Solution: List available features first with get_cross_sections()
```

**ValueError: Too many points (450 limit exceeded)**
```
Solution: Simplify geometry or remove redundant points
```

**ValueError: Bank stations out of order**
```
Solution: Ensure bank_left < bank_right
```

## Related Documentation

- **Main Subagent**: `../SUBAGENT.md` - Overview and when to delegate
- **Implementation Guide**: `../../../ras_commander/geom/AGENTS.md` - For maintainers
- **Example Notebooks**: `../../../examples/` - Real-world usage examples

## Versioning

Documentation corresponds to `ras_commander` v0.81.0+ (geometry parsing support).

For deprecated classes (`RasGeo`, `RasGeometry`, `RasGeometryUtils`), see backward compatibility notes in implementation guide.
