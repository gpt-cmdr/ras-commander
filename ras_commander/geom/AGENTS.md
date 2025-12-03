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
