---
description: |
  Parses and modifies HEC-RAS plain text geometry files (.g##) using fixed-width
  FORTRAN format. Handles cross sections, storage areas, bridges, culverts,
  lateral structures, and Manning's n tables. Use when reading geometry files,
  modifying cross sections, updating roughness, extracting structure data,
  parsing .g## files, working with XS station-elevation data, or analyzing
  bridge/culvert geometry. Keywords: parse, geometry, .g##, cross section, XS,
  Manning's n, bridge, culvert, storage, fixed-width, lateral structure,
  inline weir, 2D land cover, bank stations.
---

# Parsing HEC-RAS Geometry Files

Parse and modify HEC-RAS plain text geometry files (.g##) using `ras_commander.geom` subpackage. Handles FORTRAN-era fixed-width format for 1D cross sections, storage areas, structures, and 2D Manning's n land cover.

## Quick Start

### Read Cross Section Geometry

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

# List all cross sections
xs_df = GeomCrossSection.get_cross_sections("model.g01")
# Returns: DataFrame with River, Reach, RS, NodeName columns

# Get station-elevation profile
df = GeomCrossSection.get_station_elevation(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000"
)
# Returns: DataFrame with Station, Elevation columns
```

### Modify Cross Section

```python
# Read current geometry
df = GeomCrossSection.get_station_elevation(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000"
)

# Modify elevations (e.g., lower channel 2 feet)
df.loc[df['Station'].between(100, 200), 'Elevation'] -= 2.0

# Write back (creates .bak backup, handles bank station interpolation)
GeomCrossSection.set_station_elevation(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000",
    df,
    bank_left=50.0,
    bank_right=250.0
)
```

### Read Bridge Geometry

```python
from ras_commander.geom.GeomBridge import GeomBridge

# List all bridges
bridges = GeomBridge.get_bridges("model.g01")

# Get bridge deck geometry
deck_df = GeomBridge.get_deck(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000"
)
# Returns: DataFrame with Station, Elevation, Width, Distance

# Get pier data
piers_df = GeomBridge.get_piers(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000"
)
# Returns: DataFrame with Station, Width, CD coefficients
```

### Update 2D Manning's n

```python
from ras_commander.geom.GeomLandCover import GeomLandCover

# Read land cover table
lc_df = GeomLandCover.get_base_mannings_n("model.g01")
# Returns: DataFrame with LandCoverID, ManningsN

# Modify roughness
lc_df.loc[lc_df['LandCoverID'] == 42, 'ManningsN'] = 0.15

# Write back (creates .bak backup)
GeomLandCover.set_base_mannings_n("model.g01", lc_df)
```

## Core Concepts

### Fixed-Width FORTRAN Format

HEC-RAS geometry files use 1970s-era FORTRAN formatting:

**Column Width**: 8 characters per value
```
  12.34   56.78   90.12   34.56   78.90
  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  8 chars 8 chars 8 chars 8 chars 8 chars
```

**Values Per Line**: 10 values (80 characters total)

**Count Interpretation**:
```
#Sta/Elev= 40
```
- Means 40 PAIRS (station, elevation)
- Total values = 80 (40 stations + 40 elevations)
- Lines required = 80 ÷ 10 = 8 lines

**Parsing Example**:
```python
from ras_commander.geom.GeomParser import GeomParser

# Read fixed-width data
line = "  12.34   56.78   90.12   34.56   78.90"
values = GeomParser.parse_fixed_width(line, column_width=8)
# [12.34, 56.78, 90.12, 34.56, 78.90]

# Write fixed-width data
formatted = GeomParser.format_fixed_width(
    [12.34, 56.78, 90.12],
    column_width=8,
    values_per_line=10,
    precision=2
)
# "  12.34   56.78   90.12"
```

### Bank Station Interpolation

**Critical Requirement**: Bank stations MUST appear as exact points in station-elevation data.

**Automatic Handling**:
```python
# User provides XS data (bank stations may be missing):
df = pd.DataFrame({
    'Station': [0, 100, 200, 300],
    'Elevation': [100, 95, 95, 100]
})

# Method automatically:
# 1. Checks if bank_left=50 exists in stations
# 2. Interpolates elevation at station 50
# 3. Inserts (50, 97.5) into sorted arrays
# 4. Writes complete dataset
GeomCrossSection.set_station_elevation(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000",
    df,
    bank_left=50.0,
    bank_right=250.0
)
```

**You don't need to handle interpolation** - `set_station_elevation()` does it automatically.

### 450 Point Limit

**HEC-RAS Constraint**: Maximum 450 points per cross section.

**Always validate before writing**:
```python
if len(df) > 450:
    raise ValueError(f"Cross section has {len(df)} points (max 450)")
```

### Case-Sensitive Identifiers

River, Reach, and RS parameters are **case-sensitive**:
```python
# These are DIFFERENT cross sections:
GeomCrossSection.get_station_elevation(geom_file, "Ohio River", "Reach 1", "1000")
GeomCrossSection.get_station_elevation(geom_file, "ohio river", "reach 1", "1000")
```

Use exact casing from `get_cross_sections()` DataFrame.

### Automatic Backups

All write operations create `.bak` files:
```
Original: model.g01
Modified: model.g01
Backup:   model.g01.bak
```

Restore by renaming `.bak` file if needed.

## Module Organization (9 Modules)

### Core Parsing Infrastructure

**GeomParser** - Fixed-width format parsing
- `parse_fixed_width()` - Read fixed-width numeric data
- `format_fixed_width()` - Write fixed-width format
- `interpret_count()` - Interpret count declarations
- `identify_section()` - Find section boundaries
- `extract_keyword_value()` - Extract keyword values
- `create_backup()` - Create .bak backup

**GeomPreprocessor** - Preprocessor file management
- `clear_geompre_files()` - Clear .g##.hdf and associated files

### 1D Cross Section Features

**GeomCrossSection** - Cross section operations
- `get_cross_sections()` - List all XS metadata
- `get_station_elevation()` - Get XS geometry
- `set_station_elevation()` - Modify XS (handles bank interpolation)
- `get_bank_stations()` - Get bank locations
- `get_mannings_n()` - Get roughness values
- `get_expansion_contraction()` - Get loss coefficients

**GeomStorage** - Storage area elevation-volume curves
- `get_storage_areas()` - List storage areas (exclude 2D option)
- `get_elevation_volume()` - Get elevation-volume curve

**GeomLateral** - Lateral structures and SA/2D connections
- `get_lateral_structures()` - List lateral structures
- `get_weir_profile()` - Get lateral weir profile
- `get_connections()` - List SA/2D connections
- `get_connection_profile()` - Get connection weir profile
- `get_connection_gates()` - Get gate definitions

### Structure Features

**GeomInlineWeir** - Inline weir structures
- `get_weirs()` - List inline weirs
- `get_profile()` - Get weir crest profile
- `get_gates()` - Get gate definitions

**GeomBridge** - Bridge/culvert geometry
- `get_bridges()` - List bridge structures
- `get_deck()` - Get deck geometry
- `get_piers()` - Get pier data
- `get_abutment()` - Get abutment geometry
- `get_approach_sections()` - Get approach XS data
- `get_coefficients()` - Get loss coefficients
- `get_htab()` - Get HTAB parameters

**GeomCulvert** - Culvert data extraction
- `get_culverts()` - Get culverts at specific location
- `get_all()` - Get all culverts in file

**Culvert Shape Codes**:
- 1=Circular, 2=Box, 3=Pipe Arch, 4=Ellipse, 5=Arch
- 6=Semi-Circle, 7=Low Profile Arch, 8=High Profile Arch, 9=Con Span

### 2D Features

**GeomLandCover** - 2D Manning's n land cover tables
- `get_base_mannings_n()` - Read base Manning's n table
- `set_base_mannings_n()` - Write base Manning's n table
- `get_region_mannings_n()` - Read region overrides
- `set_region_mannings_n()` - Write region overrides

## Common Workflows

### Extract All Cross Sections

```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

# List all XS in file
xs_df = GeomCrossSection.get_cross_sections("model.g01")
# Returns: DataFrame with River, Reach, RS, NodeName, etc.

# Filter by river/reach
xs_df = GeomCrossSection.get_cross_sections(
    "model.g01",
    river="Ohio River",
    reach="Reach 1"
)

# Iterate through all cross sections
for _, row in xs_df.iterrows():
    river = row['River']
    reach = row['Reach']
    rs = row['RS']

    # Get geometry for each XS
    df = GeomCrossSection.get_station_elevation(
        "model.g01",
        river,
        reach,
        rs
    )
    print(f"{river} - {reach} - {rs}: {len(df)} points")
```

### Batch Modify Cross Sections

```python
# Get list of all cross sections
xs_df = GeomCrossSection.get_cross_sections("model.g01")

# Modify each cross section
for _, row in xs_df.iterrows():
    river = row['River']
    reach = row['Reach']
    rs = row['RS']

    # Read geometry
    df = GeomCrossSection.get_station_elevation(
        "model.g01",
        river,
        reach,
        rs
    )

    # Apply modification (e.g., raise all elevations 1 foot)
    df['Elevation'] += 1.0

    # Get bank stations
    banks = GeomCrossSection.get_bank_stations(
        "model.g01",
        river,
        reach,
        rs
    )

    # Write back
    GeomCrossSection.set_station_elevation(
        "model.g01",
        river,
        reach,
        rs,
        df,
        bank_left=banks['BankLeft'],
        bank_right=banks['BankRight']
    )
```

### Extract Storage Area Curves

```python
from ras_commander.geom.GeomStorage import GeomStorage

# List storage areas (exclude 2D flow areas)
storage_areas = GeomStorage.get_storage_areas("model.g01", exclude_2d=True)

# Get elevation-volume curve for each
for area_name in storage_areas:
    df = GeomStorage.get_elevation_volume("model.g01", area_name)
    # Returns: DataFrame with Elevation, Area, Volume columns
    print(f"{area_name}: {len(df)} elevation points")
```

### Read All Culverts

```python
from ras_commander.geom.GeomCulvert import GeomCulvert

# Get all culverts in file
culverts_df = GeomCulvert.get_all("model.g01")
# Returns: DataFrame with River, Reach, RS, CulvertNum, Shape, etc.

# Filter by river/reach
culverts_df = GeomCulvert.get_all(
    "model.g01",
    river="Ohio River",
    reach="Reach 1"
)

# Interpret shape codes
shape_map = {
    1: "Circular",
    2: "Box",
    3: "Pipe Arch",
    4: "Ellipse",
    5: "Arch",
    6: "Semi-Circle",
    7: "Low Profile Arch",
    8: "High Profile Arch",
    9: "Con Span"
}

for _, row in culverts_df.iterrows():
    shape_code = row['Shape']
    shape_name = shape_map[shape_code]
    print(f"{row['River']} - {row['RS']}: {shape_name} culvert")
```

## Error Handling

### Common Errors

**FileNotFoundError**: Geometry file doesn't exist
```python
from pathlib import Path

# Verify file exists
if not Path(geom_file).exists():
    raise FileNotFoundError(f"Geometry file not found: {geom_file}")

# Read cross sections
xs_df = GeomCrossSection.get_cross_sections(geom_file)
```

**ValueError**: River/Reach/RS not found
```python
# List available features first
xs_df = GeomCrossSection.get_cross_sections(geom_file)
print(xs_df[['River', 'Reach', 'RS']])

# Use exact casing
df = GeomCrossSection.get_station_elevation(
    geom_file,
    "Ohio River",  # Exact case
    "Reach 1",     # Exact case
    "1000"         # Exact string
)
```

**450 Point Limit Exceeded**:
```python
# Validate before writing
if len(df) > 450:
    # Option 1: Simplify geometry
    from scipy.interpolate import interp1d

    # Reduce to 400 points
    f = interp1d(df['Station'], df['Elevation'])
    new_stations = np.linspace(df['Station'].min(), df['Station'].max(), 400)
    new_elevations = f(new_stations)

    df = pd.DataFrame({
        'Station': new_stations,
        'Elevation': new_elevations
    })

    # Option 2: Raise error and ask user to simplify
    raise ValueError(f"Cross section has {len(df)} points (max 450)")

# Write to file
GeomCrossSection.set_station_elevation(geom_file, river, reach, rs, df)
```

## Reference Documentation

- [Parsing Algorithms](reference/parsing.md) - Fixed-width format details and count interpretation
- [Modification Patterns](reference/modification.md) - Safe geometry modification workflows

## See Also

- **Subagent**: `.claude/subagents/geometry-parser/SUBAGENT.md` - Delegation target
- **Implementation**: `ras_commander/geom/AGENTS.md` - Maintainer documentation
- **CLAUDE.md**: Architecture section on geometry parsing (lines 165-220)

## Important Notes

1. **All methods are static** - No class instantiation required
2. **Thread-safe** - Can parse multiple files simultaneously
3. **Automatic backups** - All write operations create `.bak` files
4. **Bank station interpolation** - Handled automatically by `set_station_elevation()`
5. **Case-sensitive identifiers** - Use exact River/Reach/RS casing
6. **Import pattern**: `from ras_commander.geom.GeomCrossSection import GeomCrossSection`
7. **Logging**: All methods use `@log_call` decorator

## Deprecated Classes (Backward Compatibility)

Old API (being phased out before v1.0):
- `RasGeo` → Use `GeomPreprocessor` + `GeomLandCover`
- `RasGeometry` → Use `GeomCrossSection`, `GeomStorage`, `GeomLateral`
- `RasGeometryUtils` → Use `GeomParser`
- `RasStruct` → Removed (no replacement)

Migration period: Old classes work until v1.0 but log deprecation warnings.
