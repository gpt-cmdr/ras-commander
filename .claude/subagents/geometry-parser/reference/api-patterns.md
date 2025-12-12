# API Patterns - Geometry Parser

Complete API reference for all 9 modules in `ras_commander.geom` subpackage.

## Module Index

1. [GeomParser](#geomparser) - Core parsing utilities
2. [GeomPreprocessor](#geompreprocessor) - Preprocessor management
3. [GeomCrossSection](#geomcrosssection) - Cross section operations
4. [GeomStorage](#geomstorage) - Storage area curves
5. [GeomLateral](#geomlateral) - Lateral structures and connections
6. [GeomInlineWeir](#geominlineweir) - Inline weir structures
7. [GeomBridge](#geombridge) - Bridge/culvert geometry
8. [GeomCulvert](#geomculvert) - Culvert data extraction
9. [GeomLandCover](#geomlandcover) - 2D Manning's n tables

---

## GeomParser

**Module**: `ras_commander.geom.GeomParser`
**Class**: `GeomParser`
**Purpose**: Core parsing utilities for fixed-width FORTRAN format

### Methods

#### `parse_fixed_width(line, column_width=8)`
Parse fixed-width numeric data from a line.

**Parameters**:
- `line` (str): Line containing fixed-width data
- `column_width` (int): Width of each column (default: 8)

**Returns**: `list[float]` - Parsed numeric values

**Example**:
```python
line = "  12.34   56.78   90.12"
values = GeomParser.parse_fixed_width(line, column_width=8)
# [12.34, 56.78, 90.12]
```

#### `format_fixed_width(values, column_width=8, values_per_line=10, precision=2)`
Format numeric values as fixed-width strings.

**Parameters**:
- `values` (list[float]): Values to format
- `column_width` (int): Width of each column (default: 8)
- `values_per_line` (int): Values per line (default: 10)
- `precision` (int): Decimal places (default: 2)

**Returns**: `list[str]` - Formatted lines

**Example**:
```python
values = [12.34, 56.78, 90.12]
lines = GeomParser.format_fixed_width(values, precision=2)
# ["  12.34   56.78   90.12"]
```

#### `interpret_count(keyword, count_value)`
Interpret count declarations (handles PAIRS vs VALUES).

**Parameters**:
- `keyword` (str): Count keyword (e.g., "#Sta/Elev", "#Elev/Volume")
- `count_value` (int): Declared count

**Returns**: `int` - Total number of values

**Example**:
```python
# "#Sta/Elev= 40" means 40 PAIRS
total = GeomParser.interpret_count("#Sta/Elev", 40)
# 80 (40 stations + 40 elevations)

# "#Elev/Volume= 20" means 20 PAIRS
total = GeomParser.interpret_count("#Elev/Volume", 20)
# 40 (20 elevations + 20 volumes)
```

#### `identify_section(lines, keyword, start_index=0)`
Find section boundaries using keyword markers.

**Parameters**:
- `lines` (list[str]): All file lines
- `keyword` (str): Section start keyword
- `start_index` (int): Line to start search (default: 0)

**Returns**: `tuple[int, int]` - (start_line, end_line) or (None, None)

#### `extract_keyword_value(line, keyword)`
Extract value following a keyword.

**Parameters**:
- `line` (str): Line containing keyword
- `keyword` (str): Keyword to search for

**Returns**: `str` - Value after keyword

**Example**:
```python
line = "River Reach=Ohio River"
value = GeomParser.extract_keyword_value(line, "River Reach=")
# "Ohio River"
```

#### `extract_comma_list(line, keyword)`
Extract comma-separated list after keyword.

**Parameters**:
- `line` (str): Line containing keyword and list
- `keyword` (str): Keyword before list

**Returns**: `list[str]` - Parsed values

#### `create_backup(file_path)`
Create `.bak` backup of file.

**Parameters**:
- `file_path` (str|Path): File to backup

**Returns**: `Path` - Path to backup file

---

## GeomPreprocessor

**Module**: `ras_commander.geom.GeomPreprocessor`
**Class**: `GeomPreprocessor`
**Purpose**: Geometry preprocessor file management

### Methods

#### `clear_geompre_files(plan_files=None, ras_object=None)`
Clear geometry preprocessor HDF files.

**Parameters**:
- `plan_files` (list[str]): Plan numbers to clear (e.g., ["01", "02"])
- `ras_object` (RasPrj): Project object (uses global `ras` if None)

**Returns**: `None`

**Example**:
```python
from ras_commander.geom.GeomPreprocessor import GeomPreprocessor

# Clear all geometry preprocessor files
GeomPreprocessor.clear_geompre_files()

# Clear specific plans
GeomPreprocessor.clear_geompre_files(plan_files=["01", "02"])
```

---

## GeomCrossSection

**Module**: `ras_commander.geom.GeomCrossSection`
**Class**: `GeomCrossSection`
**Purpose**: 1D cross section operations

### Methods

#### `get_cross_sections(geom_file, river=None, reach=None)`
List all cross sections in geometry file.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `river` (str): Filter by river name (optional)
- `reach` (str): Filter by reach name (optional)

**Returns**: `pd.DataFrame` with columns:
- `River` (str): River name
- `Reach` (str): Reach name
- `RS` (str): River station
- `NodeName` (str): Node identifier
- `Downstream` (bool): Downstream XS flag
- `Bank Left` (float): Left bank station
- `Bank Right` (float): Right bank station

**Example**:
```python
from ras_commander.geom.GeomCrossSection import GeomCrossSection

# Get all cross sections
xs_df = GeomCrossSection.get_cross_sections("model.g01")

# Filter by river
xs_df = GeomCrossSection.get_cross_sections("model.g01", river="Ohio River")

# Filter by river and reach
xs_df = GeomCrossSection.get_cross_sections(
    "model.g01",
    river="Ohio River",
    reach="Reach 1"
)
```

#### `get_station_elevation(geom_file, river, reach, rs)`
Get station-elevation profile for a cross section.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `river` (str): River name (case-sensitive)
- `reach` (str): Reach name (case-sensitive)
- `rs` (str): River station

**Returns**: `pd.DataFrame` with columns:
- `Station` (float): Horizontal station
- `Elevation` (float): Vertical elevation

**Example**:
```python
df = GeomCrossSection.get_station_elevation(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000"
)
```

#### `set_station_elevation(geom_file, river, reach, rs, df, bank_left=None, bank_right=None)`
Modify station-elevation profile (with automatic bank station interpolation).

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `river` (str): River name
- `reach` (str): Reach name
- `rs` (str): River station
- `df` (pd.DataFrame): New station-elevation data
- `bank_left` (float): Left bank station (optional)
- `bank_right` (float): Right bank station (optional)

**Returns**: `None`

**Critical Features**:
- Automatically interpolates elevations at bank stations
- Inserts bank points into sorted arrays
- Creates `.bak` backup file
- Validates 450 point limit

**Example**:
```python
# Modify XS geometry
df = pd.DataFrame({
    'Station': [0, 100, 200, 300],
    'Elevation': [100, 95, 95, 100]
})

GeomCrossSection.set_station_elevation(
    "model.g01",
    "Ohio River",
    "Reach 1",
    "1000",
    df,
    bank_left=50.0,    # Will be interpolated and inserted
    bank_right=250.0   # Will be interpolated and inserted
)
```

#### `get_bank_stations(geom_file, river, reach, rs)`
Get bank station locations.

**Parameters**: Same as `get_station_elevation`

**Returns**: `dict` with keys:
- `bank_left` (float): Left bank station
- `bank_right` (float): Right bank station

#### `get_expansion_contraction(geom_file, river, reach, rs)`
Get expansion/contraction coefficients.

**Parameters**: Same as `get_station_elevation`

**Returns**: `dict` with keys:
- `expansion` (float): Expansion coefficient
- `contraction` (float): Contraction coefficient

#### `get_mannings_n(geom_file, river, reach, rs)`
Get Manning's n roughness values.

**Parameters**: Same as `get_station_elevation`

**Returns**: `pd.DataFrame` with Manning's n values and breakpoints

---

## GeomStorage

**Module**: `ras_commander.geom.GeomStorage`
**Class**: `GeomStorage`
**Purpose**: Storage area elevation-volume curves

### Methods

#### `get_storage_areas(geom_file, exclude_2d=True)`
List all storage areas in geometry file.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `exclude_2d` (bool): Exclude 2D flow areas (default: True)

**Returns**: `list[str]` - Storage area names

**Example**:
```python
from ras_commander.geom.GeomStorage import GeomStorage

areas = GeomStorage.get_storage_areas("model.g01")
# ['Detention Basin 1', 'Wetland Area 2']
```

#### `get_elevation_volume(geom_file, area_name)`
Get elevation-volume curve for a storage area.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `area_name` (str): Storage area name

**Returns**: `pd.DataFrame` with columns:
- `Elevation` (float): Water surface elevation
- `Volume` (float): Storage volume (acre-feet or cubic feet)

**Example**:
```python
curve_df = GeomStorage.get_elevation_volume("model.g01", "Detention Basin 1")
```

---

## GeomLateral

**Module**: `ras_commander.geom.GeomLateral`
**Class**: `GeomLateral`
**Purpose**: Lateral structures and SA/2D connections

### Methods

#### `get_lateral_structures(geom_file, river=None, reach=None)`
List all lateral structures.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `river` (str): Filter by river (optional)
- `reach` (str): Filter by reach (optional)

**Returns**: `pd.DataFrame` with lateral structure metadata

#### `get_weir_profile(geom_file, river, reach, rs, position=0)`
Get lateral weir profile.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `river` (str): River name
- `reach` (str): Reach name
- `rs` (str): River station
- `position` (int): Weir position if multiple (default: 0)

**Returns**: `pd.DataFrame` with Station, Elevation columns

#### `get_connections(geom_file)`
List all SA/2D connections.

**Parameters**:
- `geom_file` (str|Path): Geometry file path

**Returns**: `pd.DataFrame` with connection metadata

#### `get_connection_profile(geom_file, connection_name)`
Get connection weir profile.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `connection_name` (str): Connection identifier

**Returns**: `pd.DataFrame` with Station, Elevation columns

#### `get_connection_gates(geom_file, connection_name)`
Get gate definitions for a connection.

**Parameters**: Same as `get_connection_profile`

**Returns**: `pd.DataFrame` with gate parameters

---

## GeomInlineWeir

**Module**: `ras_commander.geom.GeomInlineWeir`
**Class**: `GeomInlineWeir`
**Purpose**: Inline weir structure parsing

### Methods

#### `get_weirs(geom_file, river=None, reach=None)`
List all inline weirs.

**Parameters**: Same as `get_lateral_structures`

**Returns**: `pd.DataFrame` with inline weir metadata

#### `get_profile(geom_file, river, reach, rs)`
Get inline weir crest profile.

**Parameters**: Same as `get_station_elevation` (river, reach, rs)

**Returns**: `pd.DataFrame` with Station, Elevation columns

#### `get_gates(geom_file, river, reach, rs)`
Get inline weir gate definitions.

**Parameters**: Same as `get_profile`

**Returns**: `pd.DataFrame` with gate parameters

---

## GeomBridge

**Module**: `ras_commander.geom.GeomBridge`
**Class**: `GeomBridge`
**Purpose**: Bridge/culvert structure geometry

### Methods

#### `get_bridges(geom_file, river=None, reach=None)`
List all bridges.

**Parameters**: Same as `get_lateral_structures`

**Returns**: `pd.DataFrame` with bridge metadata

#### `get_deck(geom_file, river, reach, rs)`
Get bridge deck geometry.

**Parameters**: Same as `get_station_elevation`

**Returns**: `pd.DataFrame` with columns:
- `Station` (float): Horizontal station
- `Elevation` (float): Deck elevation
- `Width` (float): Deck width
- `Distance` (float): Distance from XS

#### `get_piers(geom_file, river, reach, rs)`
Get bridge pier data.

**Parameters**: Same as `get_station_elevation`

**Returns**: `pd.DataFrame` with columns:
- `Station` (float): Pier centerline station
- `Width` (float): Pier width
- `CD_Coefficient` (float): Drag coefficient

#### `get_abutment(geom_file, river, reach, rs)`
Get abutment geometry.

**Parameters**: Same as `get_station_elevation`

**Returns**: `dict` with abutment parameters

#### `get_approach_sections(geom_file, river, reach, rs)`
Get approach cross section data.

**Parameters**: Same as `get_station_elevation`

**Returns**: `dict` with upstream/downstream XS references

#### `get_coefficients(geom_file, river, reach, rs)`
Get bridge loss coefficients.

**Parameters**: Same as `get_station_elevation`

**Returns**: `dict` with coefficient values

#### `get_htab(geom_file, river, reach, rs)`
Get HTAB computation parameters.

**Parameters**: Same as `get_station_elevation`

**Returns**: `dict` with HTAB settings

---

## GeomCulvert

**Module**: `ras_commander.geom.GeomCulvert`
**Class**: `GeomCulvert`
**Purpose**: Culvert data extraction

### Methods

#### `get_culverts(geom_file, river, reach, rs)`
Get all culverts at a specific location.

**Parameters**: Same as `get_station_elevation`

**Returns**: `pd.DataFrame` with columns:
- `CulvertNumber` (int): Culvert index
- `Shape` (int): Shape code (1=Circular, 2=Box, etc.)
- `Span` (float): Culvert width
- `Rise` (float): Culvert height
- `Length` (float): Culvert length
- `ManningsN` (float): Roughness coefficient
- `InletLoss` (float): Entrance loss coefficient
- `OutletLoss` (float): Exit loss coefficient

#### `get_all(geom_file, river=None, reach=None)`
Get all culverts in file.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `river` (str): Filter by river (optional)
- `reach` (str): Filter by reach (optional)

**Returns**: `pd.DataFrame` with all culvert data

### Culvert Shape Codes

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

---

## GeomLandCover

**Module**: `ras_commander.geom.GeomLandCover`
**Class**: `GeomLandCover`
**Purpose**: 2D Manning's n land cover tables

### Methods

#### `get_base_mannings_n(geom_file)`
Read base Manning's n table.

**Parameters**:
- `geom_file` (str|Path): Geometry file path

**Returns**: `pd.DataFrame` with columns:
- `LandCoverID` (int): Land cover classification ID
- `ManningsN` (float): Roughness value

**Example**:
```python
from ras_commander.geom.GeomLandCover import GeomLandCover

lc_df = GeomLandCover.get_base_mannings_n("model.g01")
```

#### `set_base_mannings_n(geom_file, df)`
Write base Manning's n table.

**Parameters**:
- `geom_file` (str|Path): Geometry file path
- `df` (pd.DataFrame): Manning's n table (LandCoverID, ManningsN)

**Returns**: `None`

**Example**:
```python
# Modify roughness values
lc_df.loc[lc_df['LandCoverID'] == 42, 'ManningsN'] = 0.15

# Write back
GeomLandCover.set_base_mannings_n("model.g01", lc_df)
```

#### `get_region_mannings_n(geom_file)`
Read region-specific Manning's n overrides.

**Parameters**: Same as `get_base_mannings_n`

**Returns**: `pd.DataFrame` with region override data

#### `set_region_mannings_n(geom_file, df)`
Write region-specific Manning's n overrides.

**Parameters**: Same as `set_base_mannings_n`

**Returns**: `None`
