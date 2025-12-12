# RasProcess.exe CLI Reference

**UNDOCUMENTED** - This command-line interface is not covered in official HEC-RAS documentation. This reference was reverse-engineered from RasMapperLib.dll decompilation.

---

## Overview

`RasProcess.exe` is a hidden CLI tool installed with HEC-RAS that exposes RASMapper automation functionality. It enables headless execution of mapping, preprocessing, and geometry operations without launching the GUI.

**Location**: `C:\Program Files (x86)\HEC\HEC-RAS\<version>\RasProcess.exe`

---

## Command-Line Syntax

### Method 1: XML Command File
```bash
RasProcess.exe -CommandFile="path\to\command.xml"
```

### Method 2: Direct Command Arguments
```bash
RasProcess.exe -Command=<CommandName> -<Arg1>=<Value1> -<Arg2>=<Value2> ...
```

### Method 3: Positional Arguments (some commands only)
```bash
RasProcess.exe <CommandName> <arg1> <arg2> ...
```

### Debug Mode
Add `-debug` to any command for verbose output:
```bash
RasProcess.exe -Command=StoreMap -debug ...
```

---

## Available Commands

| Command | Description | Status |
|---------|-------------|--------|
| [StoreMap](#storemap) | Generate a single result map (WSE, Depth, etc.) | Implemented |
| [StoreAllMaps](#storeallmaps) | Generate all stored maps from a .rasmap file | Implemented |
| [GenerateMesh](#generatemesh) | Create 2D mesh from perimeter shapefile | Implemented |
| [CreateGeometry](#creategeometry) | Create a new empty geometry HDF file | Implemented |
| [CompleteGeometry](#completegeometry) | Write/finalize geometry for computations | Implemented |
| [CompletePreprocess](#completepreprocess) | Run full preprocessing (Plan + Geometry + Event) | Implemented |
| [CompleteEventConditions](#completeeventconditions) | Write event conditions data | Implemented |
| [ComputePropertyTables](#computepropertytables) | Compute 2D property tables (HTAB) | Implemented |
| [SetGeometryAssociation](#setgeometryassociation) | Set terrain/land cover associations | Implemented |
| [LoadSaveGeometry](#loadsavegeometry) | Reload and save all geometry layers | Implemented |
| [RemoveResults](#removeresults) | Copy HDF file without Results group | Implemented |
| [GeneratePostProcess](#generatepostprocess) | Generate time series post-processing file | Implemented |
| [DiffH5](#diffh5) | Compare two HDF5 files | Implemented |
| [MergePolygon](#mergepolygon) | Merge polygon binary files (internal) | Implemented |
| [LaunchRasMapper](#launchrasmapper) | Launch RASMapper with files (dev tool) | Partial |
| [ExportGeometry](#exportgeometry) | Export geometry to various formats | Not Implemented |

---

## Command Reference

### StoreMap

Generate a single result map to raster file.

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="StoreMap">
  <MapType>Depth</MapType>
  <Result>C:\path\to\project.p01.hdf</Result>
  <ProfileName>Max</ProfileName>
  <OutputBaseFilename>C:\output\depth_max</OutputBaseFilename>
  <Terrain>C:\path\to\terrain.hdf</Terrain>
  <ArrivalStartProfile>01Jan2020 00:00</ArrivalStartProfile>
  <ArrivalEndProfile>02Jan2020 00:00</ArrivalEndProfile>
  <TimeUnits>Hours</TimeUnits>
</Command>
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `MapType` | Yes | Map type name (see [Map Types](#map-types)) |
| `Result` | Yes | Path to plan HDF file (.p##.hdf) |
| `ProfileName` | Depends | Profile name: "Max", "Min", or timestep. Required if MapType.NeedsProfile |
| `OutputBaseFilename` | No | Output path without extension (auto-generated if omitted) |
| `Terrain` | No | Override terrain HDF path (uses geometry's terrain if omitted) |
| `ArrivalStartProfile` | No | Start profile for arrival time maps |
| `ArrivalEndProfile` | No | End profile for arrival time maps |
| `TimeUnits` | No | Time units for duration/arrival: None, Seconds, Minutes, Hours, Days |

#### Output
Generates GeoTIFF files named: `<OutputBaseFilename>.<TerrainName>.tif`

#### Known Bug: Missing Georeferencing

**Bug**: StoreMap crashes with `NullReferenceException` at `SetProjectionInfo()` after generating the TIF data. The output file is created but lacks CRS and proper georeferencing.

**Cause**: StoreMap uses `SetSRSHelper(terrainLayer)` which fails to read projection from terrain rasters in CLI mode.

**Workarounds**:
1. **Use StoreAllMaps instead** - Configure stored maps in RASMapper GUI first, then use StoreAllMaps which properly reads projection from the .rasmap file
2. **Post-process with Python** - Apply georeferencing after generation:

```python
import rasterio
from rasterio.crs import CRS

def fix_georeferencing(output_tif, prj_path, terrain_tif):
    """Apply georeferencing from projection file and terrain."""
    # Read CRS from .prj file
    with open(prj_path, 'r') as f:
        crs = CRS.from_wkt(f.read())

    # Get transform from terrain
    with rasterio.open(terrain_tif) as terrain:
        transform = terrain.transform

    # Read and rewrite with georeferencing
    with rasterio.open(output_tif) as src:
        data = src.read(1)
        profile = src.profile.copy()

    profile.update(crs=crs, transform=transform)
    with rasterio.open(output_tif, 'w', **profile) as dst:
        dst.write(data, 1)
```

The .prj file path can be found in the .rasmap file:
```xml
<RASProjectionFilename Filename=".\Terrain\Projection.prj" />
```

---

### StoreAllMaps

Generate all stored (pre-configured) maps from a .rasmap file.

#### CLI Format
```bash
RasProcess.exe -Command=StoreAllMaps -RasMapFilename="project.rasmap" -ResultFilename="project.p01.hdf"
```

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="StoreAllMaps">
  <RasMapFilename>C:\path\to\project.rasmap</RasMapFilename>
  <ResultFilename>C:\path\to\project.p01.hdf</ResultFilename>
</Command>
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `RasMapFilename` | Yes | Path to .rasmap file containing map configurations |
| `ResultFilename` | No | Specific result HDF to process (all if omitted) |

#### Stored Map Configuration in .rasmap Files

StoreAllMaps reads stored map definitions from `<Layer Type="RASResultsMap">` elements within each result layer. Maps must have `OutputMode` set to a "Stored" type to be processed.

##### Basic Stored Raster Map (WSE, Depth, Velocity)
```xml
<Layer Name="WSE" Type="RASResultsMap" Checked="True" Filename=".\OutputFolder\WSE (Max).vrt">
  <MapParameters MapType="elevation" OutputMode="Stored Current Terrain"
                 StoredFilename=".\OutputFolder\WSE (Max).vrt"
                 ProfileIndex="2147483647" ProfileName="Max" />
</Layer>
```

##### Stored Raster - Specific Timestep
```xml
<Layer Name="WSE" Type="RASResultsMap" Checked="True" Filename=".\OutputFolder\WSE (10SEP2018 02 30 00).vrt">
  <MapParameters MapType="elevation" OutputMode="Stored Current Terrain"
                 StoredFilename=".\OutputFolder\WSE (10SEP2018 02 30 00).vrt"
                 ProfileIndex="159" ProfileName="10SEP2018 02:30:00" />
</Layer>
```

##### Stored Polygon (Inundation Boundary)
```xml
<Layer Name="Depth" Type="RASResultsMap" Checked="True" Filename=".\OutputFolder\Inundation Boundary (Max Value_0).shp">
  <MapParameters MapType="depth" OutputMode="Stored Polygon Specified Depth"
                 StoredFilename=".\OutputFolder\Inundation Boundary (Max Value_0).shp"
                 ProfileIndex="2147483647" ProfileName="Max" />
</Layer>
```

##### Non-Stored Map (Display Only - Not Processed by StoreAllMaps)
```xml
<Layer Name="Depth" Type="RASResultsMap">
  <MapParameters MapType="depth" ProfileIndex="2147483647" ProfileName="Max" />
</Layer>
```

#### MapParameters Attributes

| Attribute | Description | Example Values |
|-----------|-------------|----------------|
| `MapType` | Map variable type | `elevation`, `depth`, `velocity`, `froude`, `Shear`, `depth and velocity`, `depth and velocity squared`, `flow` |
| `OutputMode` | Storage mode | `Stored Current Terrain`, `Stored Polygon Specified Depth`, `Stored Default Terrain` |
| `StoredFilename` | Output path (relative to .rasmap) | `.\OutputFolder\WSE (Max).vrt` |
| `ProfileIndex` | Timestep index (2147483647 = Max/Min) | `2147483647`, `159`, `0` |
| `ProfileName` | Profile name for display/file naming | `Max`, `Min`, `10SEP2018 02:30:00` |

#### OutputMode Values

| OutputMode | Output Format | Description |
|------------|---------------|-------------|
| `Stored Current Terrain` | GeoTIFF + VRT | Raster at terrain resolution, one TIF per terrain tile |
| `Stored Default Terrain` | GeoTIFF + VRT | Raster at default terrain resolution |
| `Stored Polygon Specified Depth` | Shapefile | Inundation boundary polygon at specified depth threshold |

#### Complete Results Layer Structure
```xml
<Results>
  <Layer Name="Plan Name" Type="RASResults" Filename=".\Project.p01.hdf">
    <!-- Geometry and event condition layers (auto-generated) -->
    <Layer Type="RASGeometry" Filename=".\Project.p01.hdf">
      <!-- ... -->
    </Layer>

    <!-- Non-stored maps (display only) -->
    <Layer Name="Depth" Type="RASResultsMap">
      <MapParameters MapType="depth" ProfileIndex="2147483647" ProfileName="Max" />
    </Layer>

    <!-- Stored maps (processed by StoreAllMaps) -->
    <Layer Name="WSE" Type="RASResultsMap" Checked="True" Filename=".\Output\WSE (Max).vrt">
      <MapParameters MapType="elevation" OutputMode="Stored Current Terrain"
                     StoredFilename=".\Output\WSE (Max).vrt"
                     ProfileIndex="2147483647" ProfileName="Max" />
    </Layer>
  </Layer>
</Results>
```

#### Global Render Settings

The `.rasmap` file also contains global render settings that affect map generation:

```xml
<RASMapper>
  <!-- ... other settings ... -->
  <RenderMode>sloping</RenderMode>  <!-- or "horizontal" -->
  <Units>US Customary</Units>
</RASMapper>
```

| RenderMode | Description |
|------------|-------------|
| `horizontal` | Constant WSE within each cell |
| `sloping` | Interpolated WSE using cell corner values (Ben's Weights) |
| `slopingPretty` | Sloping with additional smoothing |

---

### GenerateMesh

Create a 2D mesh from a perimeter shapefile.

#### CLI Format
```bash
RasProcess.exe -Command=GenerateMesh ^
  -PerimeterFilename="perimeter.shp" ^
  -GeometryFilename="project.g01.hdf" ^
  -CellSize=100 ^
  -Name="2D Flow Area" ^
  -MinFaceLengthRatio=0.1
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `PerimeterFilename` | Yes | Path to shapefile with mesh perimeter polygon |
| `GeometryFilename` | Yes | Path to geometry HDF file (must exist) |
| `CellSize` | Yes | Target cell size in map units |
| `Name` | Yes | Name for the 2D flow area |
| `MinFaceLengthRatio` | No | Minimum face length ratio (default: -1, auto) |

**Note**: If a 2D flow area with the same name exists, it will be replaced.

---

### CreateGeometry

Create a new empty geometry HDF file.

#### CLI Format
```bash
RasProcess.exe -Command=CreateGeometry ^
  -GeometryFilename="project.g01.hdf" ^
  -Title="My Geometry" ^
  -UnitSystem=USC
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `GeometryFilename` | Yes | Path for new geometry HDF file (must NOT exist) |
| `Title` | No | Geometry title (default: "Geometry Title") |
| `UnitSystem` | No | "USC" or "USCustomary" for US units, "SI" for metric |

---

### CompleteGeometry

Finalize geometry for computations (writes preprocessed data).

#### CLI Format
```bash
RasProcess.exe -Command=CompleteGeometry ^
  -GeomFilename="project.g01.hdf" ^
  -RasMapFilename="project.rasmap"
```

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="CompleteGeometry">
  <GeometryFilename>C:\path\to\project.g01.hdf</GeometryFilename>
</Command>
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `GeomFilename` / `GeometryFilename` | Yes | Path to geometry HDF file |
| `RasMapFilename` | No | Path to .rasmap for projection info |

---

### CompletePreprocess

Run full preprocessing: Plan GIS data + Geometry + Event Conditions.

#### CLI Format
```bash
RasProcess.exe -Command=CompletePreprocess ^
  -ResultFilename="project.p01.hdf" ^
  -RasMapFilename="project.rasmap" ^
  -Units=USC
```

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="CompletePreprocess">
  <ResultFilename>C:\path\to\project.p01.hdf</ResultFilename>
</Command>
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `ResultFilename` | Yes | Path to plan HDF file |
| `RasMapFilename` | No | Path to .rasmap for projection info |
| `Units` | No | Unit system: "USC" or "SI" |

---

### CompleteEventConditions

Write event conditions data to plan HDF.

#### CLI Format
```bash
RasProcess.exe -Command=CompleteEventConditions ^
  -ResultFilename="project.p01.hdf" ^
  -Units=USC
```

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="CompleteEventConditions">
  <ResultFilename>C:\path\to\project.p01.hdf</ResultFilename>
</Command>
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `ResultFilename` | Yes | Path to plan HDF file |
| `Units` | No | Unit system: "USC" or "SI" |

---

### ComputePropertyTables

Compute 2D hydraulic property tables (HTAB) for a geometry.

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="ComputePropertyTables">
  <Geometry>C:\path\to\project.g01.hdf</Geometry>
</Command>
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `Geometry` | Yes | Path to geometry HDF file |

---

### SetGeometryAssociation

Set terrain and land cover associations for a geometry.

#### CLI Format
```bash
RasProcess.exe -Command=SetGeometryAssociation ^
  -GeometryFilename="project.g01.hdf" ^
  -TerrainFilename="Terrain/terrain.hdf" ^
  -NValueFilename="LandCover/manning.hdf" ^
  -InfiltrationFilename="Soils/infiltration.hdf" ^
  -SedimentSoilsFilename="Soils/sediment.hdf"
```

#### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `GeometryFilename` | Yes | Path to geometry HDF file |
| `TerrainFilename` | No | Path to terrain HDF file |
| `NValueFilename` | No | Path to Manning's n land cover HDF |
| `InfiltrationFilename` | No | Path to infiltration land cover HDF |
| `SedimentSoilsFilename` | No | Path to sediment soils land cover HDF |

---

### LoadSaveGeometry

Reload and save all layers in a geometry (useful for updating associations).

#### CLI Format
```bash
RasProcess.exe -Command=LoadSaveGeometry -Filename="project.g01.hdf"
```

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="LoadSaveGeometry">
  <Filename>C:\path\to\project.g01.hdf</Filename>
</Command>
```

---

### RemoveResults

Copy an HDF file without the Results group (creates geometry-only version).

#### CLI Format
```bash
RasProcess.exe -Command=RemoveResults -Source="project.p01.hdf" -Destination="project.g01.hdf"
```

Or positional:
```bash
RasProcess.exe RemoveResults "project.p01.hdf" "output.hdf"
```

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="RemoveResults">
  <Source>C:\path\to\project.p01.hdf</Source>
  <Destination>C:\path\to\output.hdf</Destination>
</Command>
```

---

### GeneratePostProcess

Generate time series post-processing file for results.

#### CLI Format
```bash
RasProcess.exe -Command=GeneratePostProcess -ResultFilename="project.p01.hdf"
```

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="GeneratePostProcess">
  <ResultFilename>C:\path\to\project.p01.hdf</ResultFilename>
</Command>
```

---

### DiffH5

Compare two HDF5 files and report differences.

#### CLI Format
```bash
RasProcess.exe DiffH5 "baseline.hdf" "test.hdf"
```

---

### MergePolygon

Merge polygon binary files (internal use for contour generation).

#### XML Format
```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="MergePolygon">
  <PolygonBinaryFile>C:\temp\polygons.bin</PolygonBinaryFile>
</Command>
```

---

## Map Types

Valid values for the `MapType` parameter in StoreMap:

### Primary Map Types

| XML Name | Display Name | Description | 1D | 2D | Storage |
|----------|--------------|-------------|----|----|---------|
| `depth` | Depth | Flood inundation depths | Yes | Yes | Yes |
| `elevation` | Water Surface Elevation | WSE values | Yes | Yes | Yes |
| `velocity` | Velocity | Flow velocities | Yes | Yes | No |
| `depth and velocity` | Depth * Velocity | D*V hazard metric | Yes | Yes | No |
| `depth and velocity squared` | Depth * Velocity^2 | D*V^2 impact force | Yes | Yes | No |
| `froude` | Froude | Froude number | Yes | Yes | No |
| `flow` | Flow (1D Only) | Total flow | Yes | No | No |
| `Shear` | Shear Stress | Shear stress | Yes | Yes | No |
| `stream power` | Stream Power | Stream power | Yes | Yes | No |

### Time-Based Map Types

| XML Name | Display Name | Description |
|----------|--------------|-------------|
| `arrivaltime` | Arrival Time | Time when depth exceeds threshold |
| `duration` | Duration | Length of time inundated |
| `recession` | Recession | Time until water recedes |

### Energy Map Types

| XML Name | Display Name | Description |
|----------|--------------|-------------|
| `energy_depth` | Energy (Depth) | Kinetic + potential energy as depth |
| `energy_elevation` | Energy (Elevation) | Kinetic + potential energy as elevation |

### Special Map Types

| XML Name | Display Name | Description |
|----------|--------------|-------------|
| `Final N Values` | Final N Values | Manning's n values used |
| `wet cells` | Wet Cells | Binary wet/dry map |
| `volume` | Volume | Water volume |
| `hydraulicdepth` | Hydraulic Depth | Hydraulic depth |
| `terrain` | Terrain | Terrain elevations |
| `Mesh Cell Size` | Mesh Cell Size | 2D mesh cell sizes |
| `pressure` | Pressure | Pressure values |
| `WaveForcing` | Wave Forcing | Wave forcing values |

### Pipe Network Map Types

| XML Name | Display Name |
|----------|--------------|
| `pipeelevation` | Pipe Water Surface Elevation |
| `pipedepth` | Pipe Depth |
| `pipepercentfull` | Pipe Percent Full |
| `pipeinvert` | Pipe Invert Elevations |
| `pipevelocity` | Pipe Velocity |
| `pipediameter` | Pipe Diameter |

---

## Profile Names

The `ProfileName` parameter accepts:

- **"Max"** - Maximum values across all timesteps
- **"Min"** - Minimum values across all timesteps
- **Timestep string** - Specific timestep, e.g., "01Jan2020 12:00:00"
- **Profile index** - Numeric index into output timesteps

---

## Example Workflows

### Generate All Maximum Maps for a Plan

```xml
<?xml version="1.0" encoding="utf-8"?>
<Command Type="StoreMap">
  <MapType>depth</MapType>
  <Result>C:\Project\MyProject.p01.hdf</Result>
  <ProfileName>Max</ProfileName>
  <OutputBaseFilename>C:\Project\Maps\Depth_Max</OutputBaseFilename>
</Command>
```

Save as `depth_max.xml` and run:
```bash
"C:\Program Files (x86)\HEC\HEC-RAS\6.6\RasProcess.exe" -CommandFile="depth_max.xml"
```

### Create New Geometry with Mesh

```bash
REM Step 1: Create empty geometry
RasProcess.exe -Command=CreateGeometry ^
  -GeometryFilename="C:\Project\newproject.g01.hdf" ^
  -Title="Dam Break Model" ^
  -UnitSystem=USC

REM Step 2: Set terrain association
RasProcess.exe -Command=SetGeometryAssociation ^
  -GeometryFilename="C:\Project\newproject.g01.hdf" ^
  -TerrainFilename="C:\Project\Terrain\terrain.hdf"

REM Step 3: Generate 2D mesh
RasProcess.exe -Command=GenerateMesh ^
  -GeometryFilename="C:\Project\newproject.g01.hdf" ^
  -PerimeterFilename="C:\Project\GIS\perimeter.shp" ^
  -CellSize=50 ^
  -Name="Floodplain"

REM Step 4: Finalize geometry
RasProcess.exe -Command=CompleteGeometry ^
  -GeomFilename="C:\Project\newproject.g01.hdf"
```

### Batch Process Multiple Plans

```python
import subprocess
import os

ras_process = r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\RasProcess.exe"
project_dir = r"C:\Project"
plans = ["p01", "p02", "p03"]
map_types = ["depth", "velocity", "elevation"]

for plan in plans:
    for map_type in map_types:
        result_file = os.path.join(project_dir, f"MyProject.{plan}.hdf")
        output_base = os.path.join(project_dir, "Maps", f"{map_type}_max_{plan}")

        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<Command Type="StoreMap">
  <MapType>{map_type}</MapType>
  <Result>{result_file}</Result>
  <ProfileName>Max</ProfileName>
  <OutputBaseFilename>{output_base}</OutputBaseFilename>
</Command>'''

        xml_file = os.path.join(project_dir, "temp_command.xml")
        with open(xml_file, "w") as f:
            f.write(xml)

        subprocess.run([ras_process, f"-CommandFile={xml_file}"])
```

---

## Python Wrapper (ras-commander)

For programmatic access, use the `ras_commander.RasMap` module instead of calling RasProcess directly:

```python
from ras_commander import init_ras_project, RasMap

init_ras_project(r"C:\Project", "6.6")

# Generate maps using ras-commander's implementation
outputs = RasMap.map_ras_results(
    plan_number="01",
    variables=["WSE", "Depth", "Velocity"],
    terrain_path="Terrain/terrain.tif",
    interpolation_method="sloped"
)
```

---

## Troubleshooting

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "Could not find command X" | Invalid command name | Check spelling, use exact CommandName |
| "Result could not be identified" | Invalid HDF path | Verify file exists and is valid plan HDF |
| "Invalid terrain" | Terrain files missing | Check terrain HDF and source TIFs exist |
| "ProfileName was not provided" | MapType requires profile | Add `<ProfileName>Max</ProfileName>` |

### Performance Tips

1. **Use XML files** for complex commands - easier to debug
2. **Batch similar operations** to reduce startup overhead
3. **StoreAllMaps** is faster than multiple StoreMap calls when maps are pre-configured in .rasmap
4. **Run on SSD** - map generation is I/O intensive

---

## Source Files

| Command | Source File |
|---------|-------------|
| Base Command class | `RasMapperLib.Scripting/Command.cs` |
| StoreMapCommand | `RasMapperLib.Scripting/StoreMapCommand.cs` |
| StoreAllMapsCommand | `RasMapperLib.Scripting/StoreAllMapsCommand.cs` |
| GenerateMeshCommand | `RasMapperLib.Scripting/GenerateMeshCommand.cs` |
| CreateGeometryCommand | `RasMapperLib.Scripting/CreateGeometryCommand.cs` |
| CompleteGeometryCommand | `RasMapperLib.Scripting/CompleteGeometryCommand.cs` |
| CompletePreprocess | `RasMapperLib.Scripting/CompletePreprocess.cs` |
| CompleteEventCommand | `RasMapperLib.Scripting/CompleteEventCommand.cs` |
| SetGeometryAssociationCommand | `RasMapperLib.Scripting/SetGeometryAssociationCommand.cs` |
| MapTypes | `RasMapperLib.Mapping/MapTypes.cs` |

---

*Generated: 2025-12-09*
*Source: RasMapperLib.dll decompilation (HEC-RAS 6.x)*
*Status: UNDOCUMENTED - Not officially supported by HEC*
