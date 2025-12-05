# Quick Reference

Fast lookup tables for common HEC-RAS keywords, paths, and formats.

## Geometry File Keywords

### Cross Section Keywords

| Keyword | Description | Example |
|---------|-------------|---------|
| `River Reach=` | Start of river/reach block | `River Reach=River1,Reach1` |
| `Type RM Length L Ch R =` | Cross section header | `Type RM Length L Ch R = 1 ,1000,500,500,500` |
| `#Sta/Elev=` | Station-elevation pairs count | `#Sta/Elev= 40` |
| `#Mann=` | Manning's n segments | `#Mann= 3 , 0 , 0` |
| `Bank Sta=` | Bank station locations | `Bank Sta=190,375` |
| `XS GIS Cut Line=` | Cross section GIS coordinates | `XS GIS Cut Line= 5` |
| `Levee=` | Levee data | `Levee= 12 , 0` |
| `Ineffective=` | Ineffective flow areas | `Ineffective= 2 , 0 , 0` |
| `Blocked=` | Blocked obstruction | `Blocked= 2 , 0` |

### 2D Flow Area Keywords

| Keyword | Description |
|---------|-------------|
| `Storage Area=` | Storage area definition |
| `2D Flow Area=` | 2D mesh area definition |
| `Storage Area Conn=` | SA/2D connection |
| `Connection=` | Generic connection |
| `BC Line Name=` | Boundary condition line |

### Structure Keywords

| Keyword | Description |
|---------|-------------|
| `Type RM Length L Ch R = 2` | Bridge |
| `Type RM Length L Ch R = 3` | Inline weir |
| `Culvert=` | Culvert definition |
| `Lateral Weir=` | Lateral structure |
| `Inline Structure=` | Inline structure |

## Plan File Keywords

| Keyword | Description | Example |
|---------|-------------|---------|
| `Plan Title=` | Plan name | `Plan Title=Base Run` |
| `Short Identifier=` | Short ID | `Short Identifier=p01` |
| `Geom File=` | Geometry reference | `Geom File=g01` |
| `Flow File=` | Flow file reference | `Flow File=u01` |
| `Run HTab=` | Run hydraulic tables flag | `Run HTab= -1` |
| `Run UNet=` | Run unsteady flag | `Run UNet= -1` |
| `Run PostProcess=` | Run RASMapper flag | `Run PostProcess= 0` |
| `Computation Interval=` | Time step | `Computation Interval=2MIN` |
| `Output Interval=` | Output frequency | `Output Interval=15MIN` |
| `UNET D1 Cores=` | 1D cores | `UNET D1 Cores= 1` |
| `UNET D2 Cores=` | 2D cores | `UNET D2 Cores= 4` |

## HDF Path Quick Reference

### Most Common Paths

```python
# Plan Info
"/Plan Data/Plan Information"

# 2D Max Results
"/Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/{area}/Maximum Water Surface"

# 2D Time Series
"/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{area}/Water Surface"

# 1D Cross Section Results
"/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections/{river}_{reach}/Water Surface"

# Timestamps
"/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp"

# Mesh Geometry
"/Geometry/2D Flow Areas/{area}/Cells Center Coordinate"

# Steady Results
"/Results/Steady/Output/Geometry/Cross Sections/{river}_{reach}/Water Surface"
```

### Path Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `{area}` | 2D flow area name | `"Floodplain"` |
| `{river}` | River name | `"White River"` |
| `{reach}` | Reach name | `"Upper"` |
| `{river}_{reach}` | Combined (spaces removed) | `"WhiteRiver_Upper"` |

## Data Format Cheat Sheet

### Fixed-Width Columns

| Data Type | Width | Per Line | Example |
|-----------|-------|----------|---------|
| 1D Sta/Elev | 8 chars | 10 values | `       0  660.41` |
| 2D Coordinates | 16 chars | 4 values | `   648224.43125` |
| Manning's n | 8 chars | 9 values (3 triplets) | `       0     .06       0` |

### Count Interpretation

| Keyword | Count Means | Total Values |
|---------|-------------|--------------|
| `#Sta/Elev=` | PAIRS | count × 2 |
| `#Mann=` | SEGMENTS | count × 3 |
| `Reach XY=` | PAIRS | count × 2 |
| `Storage Area Surface Line=` | POINTS | count × 2 |
| `Levee=` | TOTAL values | count |

### Time Formats

| Source | Format | Example |
|--------|--------|---------|
| HDF timestamp | `%d%b%Y %H:%M:%S:%f` | `01JAN2000 00:00:00:000` |
| COM timestamp | `%d%b%Y %H%M` | `01JAN2000 0000` |
| Plan file | `ddMMMYYYY,HHMM` | `01Jan2000,0000` |

## Computation Interval Strings

| String | Interval |
|--------|----------|
| `1SEC` | 1 second |
| `2SEC` | 2 seconds |
| `5SEC` | 5 seconds |
| `10SEC` | 10 seconds |
| `15SEC` | 15 seconds |
| `30SEC` | 30 seconds |
| `1MIN` | 1 minute |
| `2MIN` | 2 minutes |
| `5MIN` | 5 minutes |
| `10MIN` | 10 minutes |
| `15MIN` | 15 minutes |
| `30MIN` | 30 minutes |
| `1HOUR` | 1 hour |

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

## Run Flag Values

| Value | Meaning |
|-------|---------|
| `-1` | True/Enabled |
| `0` | False/Disabled |

!!! warning "RASMapper Inversion"
    `Run PostProcess=` uses **inverted logic**: `0` = True, `-1` = False

## See Also

- [Geometry Parsing](geometry-parsing.md) - Detailed parsing reference
- [HDF Structure](hdf-structure.md) - Complete HDF documentation
- [File Formats](file-formats.md) - File naming conventions
