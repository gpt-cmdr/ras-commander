# HEC-RAS File Formats

Reference for HEC-RAS file types and naming conventions.

## Project Files

| Extension | Description |
|-----------|-------------|
| `.prj` | Project file - master index of all project files |
| `.rasmap` | RASMapper configuration (terrain, land cover paths) |

## Plan Files

| Extension | Description |
|-----------|-------------|
| `.p##` | Plan file (e.g., `.p01`, `.p02`) |
| `.p##.hdf` | Plan results HDF file |
| `.p##.tmp.hdf` | Temporary results during computation |
| `.computeMsgs.txt` | Computation messages log |

## Geometry Files

| Extension | Description |
|-----------|-------------|
| `.g##` | Geometry file (e.g., `.g01`, `.g02`) |
| `.g##.hdf` | Preprocessed geometry HDF (hydraulic tables) |
| `.c##` | Geometry preprocessor cache files |

## Flow Files

| Extension | Description |
|-----------|-------------|
| `.f##` | Steady flow file |
| `.u##` | Unsteady flow file |
| `.b##` | Boundary conditions (older format) |

## File Numbering

Files use two-digit numbering: `01` through `99`.

```
MyProject.prj          # Project file
MyProject.p01          # Plan 01
MyProject.p01.hdf      # Plan 01 results
MyProject.g01          # Geometry 01
MyProject.g01.hdf      # Geometry 01 preprocessed
MyProject.u01          # Unsteady flow 01
```

## Plan File Structure

Plan files (`.p##`) are ASCII text with key-value pairs:

```
Plan Title=My Simulation Plan
Short Identifier=Plan01
Geom File=g01
Flow File=u01
Computation Interval=5MIN
Output Interval=15MIN
Run HTab=1
Run UNet=1
Run SedTran=0
```

## Geometry File Structure

Geometry files (`.g##`) use FORTRAN-style fixed-width formatting:

```
River Reach=Big Creek,Upper
Type RM Length L Ch R = 1 ,1000   ,500    ,300    ,400
XS GIS Cut Line=2
     -100.0      500.0
      100.0      500.0
#Sta/Elev= 5
        0      105
       50      100
      100       98
      150      100
      200      105
```

### Cross Section Format

- 8-character fixed-width fields
- Station-elevation pairs
- Maximum 450 points per cross section
- Bank stations require interpolation

## Unsteady Flow File Structure

Unsteady flow files (`.u##`) contain boundary condition definitions:

```
Flow Title=100-Year Event
Program Version=6.50
Boundary Location=Big Creek,Upper,1000,         ,                ,                ,                ,
Interval=15MIN
Flow Hydrograph= 10
         0       100
       0.5       200
         1       500
       1.5      1000
         2      2000
         3      1500
         4      1000
         5       500
         6       300
         7       200
```

## HDF File Structure

HEC-RAS 6.x+ stores results in HDF5 format:

```
/
├── Plan Data/
│   ├── Plan Information/
│   └── Plan Parameters/
├── Geometry/
│   ├── Cross Sections/
│   ├── 2D Flow Areas/
│   └── Structures/
└── Results/
    ├── Unsteady/
    │   └── Output/
    │       ├── Output Blocks/
    │       │   └── Base Output/
    │       │       ├── Unsteady Time Series/
    │       │       └── Summary Output/
    │       └── Geometry Info/
    └── Summary/
        ├── Compute Messages (text)
        └── Volume Accounting/
```

### Key HDF Paths

| Path | Description |
|------|-------------|
| `/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/` | 2D mesh time series |
| `/Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/` | 2D mesh summary |
| `/Geometry/2D Flow Areas/{area}/Cells Center Coordinate` | Cell center points |
| `/Results/Summary/Compute Messages (text)` | Computation messages |

## RASMapper Configuration

`.rasmap` files are XML format:

```xml
<RASMapper>
  <Results>
    <Layer Name="depth" Type="RASResultsMap">
      <LegendFilename>depth_legend.xml</LegendFilename>
    </Layer>
  </Results>
  <Terrain>
    <Layer Name="Terrain">
      <Filename>.\Terrain\terrain.hdf</Filename>
    </Layer>
  </Terrain>
</RASMapper>
```
