# RASMapper Scripting Namespace Documentation

**Purpose:** The `RasMapperLib.Scripting` namespace provides a comprehensive automation API for executing RASMapper operations programmatically via command-line interface or XML-based scripting.

**Key Insight:** This namespace enables headless/batch processing of HEC-RAS geometry preprocessing, results processing, and map generation without requiring the RASMapper GUI.

---

## Architecture Overview

### Command Pattern Design

All commands inherit from the abstract `Command` base class and implement a consistent execution interface:

```csharp
public abstract class Command
{
    public abstract string CommandName { get; }
    public abstract bool ValidateArguments(ProgressReporter prog = null);
    public abstract void Execute(ProgressReporter prog = null);
    public abstract void ExecuteWith(Dictionary<string, string> kvpArgs,
                                      List<string> otherArgs,
                                      ProgressReporter prog = null);
}
```

### Execution Modes

1. **In-Process Execution:** `Execute()` - Run command in current process
2. **Out-of-Process Execution:** `ExecuteOutOfProcess()` - Launch via `RasProcess.exe`
3. **Async Out-of-Process:** `ExecuteOutOfProcessAsync()` - Non-blocking execution
4. **Command-Line Parsing:** `ParseExecute(string[] args)` - Parse and execute from CLI

### Command Discovery

Commands are auto-discovered via reflection at startup:
- `RefreshCommandTypeList()` scans assemblies for `Command` subclasses
- Commands registered by `CommandName` property in case-insensitive dictionary
- Factory pattern: `TryConstructFromCommandName(string cmdName)`

---

## Command Invocation Methods

### 1. Command-Line Arguments

**Via XML File:**
```bash
RasProcess.exe -CommandFile="C:\path\to\command.xml"
```

**Via Direct Arguments:**
```bash
RasProcess.exe -Command=CompleteGeometry -GeomFilename="model.g01.hdf"
```

**With Key-Value Pairs:**
```bash
RasProcess.exe -Command=GenerateMesh -GeometryFilename="model.g01.hdf" ^
  -PerimeterFilename="perimeter.shp" -CellSize=50 -Name="Mesh2D"
```

**Debug Mode:**
```bash
RasProcess.exe -debug -CommandFile="command.xml"
```

### 2. Programmatic Invocation (C#)

```csharp
// Create and execute directly
var cmd = new CompleteGeometryCommand("model.g01.hdf");
cmd.Execute(ProgressReporter.ConsoleWrite());

// Execute out-of-process
cmd.ExecuteOutOfProcess(showWindow: false);

// Execute with arguments
Command.ExecuteWith("CompleteGeometry",
    new Dictionary<string, string> { ["GeomFilename"] = "model.g01.hdf" },
    new List<string>());
```

### 3. XML Configuration

```xml
<Command Type="CompleteGeometry">
  <GeometryFilename>C:\Projects\model.g01.hdf</GeometryFilename>
</Command>
```

---

## Available Commands

### Geometry Preprocessing Commands

#### `CompleteGeometry` - Complete Geometry HDF File
**Purpose:** Preprocess geometry file to populate all required datasets for computation

**Arguments:**
- `GeometryFilename` (required) - Path to `.g##.hdf` file
- `RasMapFilename` (optional) - Path to `.rasmap` file for SRS

**CLI Example:**
```bash
RasProcess.exe CompleteGeometry "C:\model.g01.hdf"
```

**What It Does:**
- Calls `RASGeometry.CompleteForComputations()`
- Writes mesh data, cross-section properties, terrain sampling, etc.
- Required before running HEC-RAS computations

---

#### `CreateGeometry` - Create New Geometry File
**Purpose:** Create an empty geometry HDF file with specified units

**Arguments:**
- `GeometryFilename` (required) - Output path for new `.g##.hdf`
- `Title` (optional) - Geometry title (default: "Geometry Title")
- `UnitSystem` (optional) - "si" or "usc" (default: USCustomary)

**CLI Example:**
```bash
RasProcess.exe CreateGeometry -GeometryFilename="newmodel.g01.hdf" ^
  -Title="My Model" -UnitSystem=usc
```

---

#### `SetGeometryAssociation` - Associate Terrain and Land Cover
**Purpose:** Set terrain and land cover layer associations for geometry

**Arguments:**
- `GeometryFilename` (required) - Path to geometry HDF
- `TerrainFilename` (optional) - Path to terrain TIF/VRT
- `NValueFilename` (optional) - Path to Manning's n land cover XML
- `InfiltrationFilename` (optional) - Path to infiltration land cover XML
- `SedimentSoilsFilename` (optional) - Path to sediment/soils land cover XML

**CLI Example:**
```bash
RasProcess.exe SetGeometryAssociation -GeometryFilename="model.g01.hdf" ^
  -TerrainFilename="terrain.tif" -NValueFilename="landcover.xml"
```

---

#### `GenerateMesh` - Generate 2D Mesh from Perimeter
**Purpose:** Programmatically generate 2D mesh from perimeter polygon shapefile

**Arguments:**
- `GeometryFilename` (required) - Target geometry HDF file
- `PerimeterFilename` (required) - Shapefile with single polygon perimeter
- `CellSize` (required) - Cell size (in project units)
- `Name` (required) - Name for the 2D flow area
- `MinFaceLengthRatio` (optional) - Minimum face length ratio (default: -1)

**CLI Example:**
```bash
RasProcess.exe GenerateMesh -GeometryFilename="model.g01.hdf" ^
  -PerimeterFilename="perimeter.shp" -CellSize=100 -Name="FloodArea"
```

**Internal Process:**
1. Reads perimeter polygon from shapefile
2. Generates cell center points using `PointGenerator.GeneratePoints()`
3. Creates `MeshFV2D` mesh object
4. Adds/replaces mesh in geometry HDF file

---

#### `ComputePropertyTables` - Compute 2D Property Tables
**Purpose:** Generate property tables (HTAB) for 2D flow areas

**Arguments:**
- `Geometry` (required) - Path to geometry HDF file

**CLI Example:**
```bash
RasProcess.exe ComputePropertyTables "model.g01.hdf"
```

**What It Does:**
- Calls `RASGeometry.D2FlowArea.EnsurePropertyTables(forceRecompute: true)`
- Computes elevation-volume, elevation-area tables for each 2D cell

---

#### `LoadSaveGeometry` - Load and Save All Layers
**Purpose:** Force reload and save of all geometry layers (refresh operation)

**Arguments:**
- `Filename` (required) - Path to geometry HDF file

**CLI Example:**
```bash
RasProcess.exe LoadSaveGeometry "model.g01.hdf"
```

---

#### `ExportGeometry` - Export Geometry (NOT IMPLEMENTED)
**Status:** Stub class, all methods throw `NotImplementedException`

---

### Results Processing Commands

#### `CompletePreprocess` - Complete All Preprocessing
**Purpose:** Complete all preprocessing steps (Plan GIS, Geometry, Event Conditions)

**Arguments:**
- `ResultFilename` (required) - Path to result HDF file (`.p##.hdf`)
- `RasMapFilename` (optional) - Path to `.rasmap` file
- `Units` (optional) - Unit system override

**CLI Example:**
```bash
RasProcess.exe CompletePreprocess "model.p01.hdf"
```

**Execution Order:**
1. **Plan GIS Data:** Writes plan-specific GIS features
2. **Geometry:** Completes geometry preprocessing
3. **Event Conditions:** Writes boundary condition datasets
4. **HDF Squeeze:** Optimizes file size

---

#### `CompleteEventConditions` - Complete Event Conditions Only
**Purpose:** Write event condition (boundary condition) datasets to result HDF

**Arguments:**
- `ResultFilename` (required) - Path to result HDF file
- `Units` (optional) - Unit system override

**CLI Example:**
```bash
RasProcess.exe CompleteEventConditions "model.p01.hdf"
```

**What It Does:**
- Calls `RASResults.EventConditions.CompleteForComputations()`
- Writes time series boundary condition data
- Squeezes HDF file after completion

---

#### `GeneratePostProcess` - Generate Post-Processor File
**Purpose:** Create time series post-processing dataset for results

**Arguments:**
- `ResultFilename` (required) - Path to result HDF file

**CLI Example:**
```bash
RasProcess.exe GeneratePostProcess "model.p01.hdf"
```

**What It Does:**
- Calls `RASResults.GetPostProcessor().EnsurePostProcess()`
- Generates time series datasets for visualization

---

#### `RemoveResults` - Strip Results from HDF
**Purpose:** Copy HDF file without `/Results` group (create geometry-only file)

**Arguments:**
- `Source` (required) - Source HDF file with results
- `Destination` (required) - Output HDF file without results

**CLI Example:**
```bash
RasProcess.exe RemoveResults -Source="model.p01.hdf" ^
  -Destination="model.g01.hdf"
```

**Use Case:** Extract clean geometry file from plan results file

---

### Map Generation Commands

#### `StoreMap` - Generate Single Stored Map
**Purpose:** Rasterize a single result variable to GeoTIFF

**Arguments:**
- `Result` (required) - Path to result HDF file or result identifier
- `MapType` (required) - Map type (see `MapTypes` enum)
- `ProfileName` (conditional) - Profile name (required for profile maps)
- `Terrain` (optional) - Override terrain file
- `OutputBaseFilename` (optional) - Override output filename
- `ArrivalStartProfile` (optional) - Arrival time start profile
- `ArrivalEndProfile` (optional) - Arrival time end profile
- `TimeUnits` (optional) - Time units for arrival maps

**CLI Example:**
```bash
RasProcess.exe StoreMap -Result="model.p01.hdf" -MapType="Depth" ^
  -ProfileName="Max" -OutputBaseFilename="depth_max.tif"
```

**Factory Methods (C# API):**
```csharp
StoreMapCommand.Depth(resultFile, "Max", "output.tif");
StoreMapCommand.Velocity(resultFile, "Max");
StoreMapCommand.WSEL(resultFile, "12JAN2020 1200");
StoreMapCommand.DepthTimesVelocity(resultFile, "Max");
StoreMapCommand.DepthTimesVelocitySquared(resultFile, "Max");
```

**Output Modes:**
- `OutputMode = OutputModes.StoredDefaultTerrain` (stored to file)

---

#### `StoreAllMaps` - Batch Generate All Stored Maps
**Purpose:** Process all "stored" map configurations from `.rasmap` file

**Arguments:**
- `RasMapFilename` (required) - Path to `.rasmap` file
- `ResultFilename` (optional) - Filter to specific result file

**CLI Example:**
```bash
RasProcess.exe StoreAllMaps -RasMapFilename="project.rasmap"
```

**What It Does:**
1. Parses `.rasmap` XML for all result layers
2. Finds layers with `OutputMode="stored"`
3. Generates GeoTIFF for each stored map configuration
4. Reports count of maps generated per result file

**Terrain Override:**
- Reads all terrain layers from `.rasmap`
- Passes terrain dictionary to `RASResultsMap.SetOverrideTerrainFilenamesDictionary()`

---

### Utility Commands

#### `DiffH5` - Compare Two HDF Files
**Purpose:** Perform dataset-by-dataset comparison of two HDF5 files

**Arguments:**
- Two positional arguments: `BaseFilename` and `NewFilename`
- `ExtraArgs` - Additional arguments passed to `H5Diff.Diff()`

**CLI Example:**
```bash
RasProcess.exe DiffH5 "baseline.hdf" "test.hdf"
```

**Static Helper:**
```csharp
DiffH5Command.ExecuteWithRasProcess(baseFile, testFile);
// Opens CMD window with diff output and PAUSE
```

---

#### `DownloadFiles` - Download Files from URLs
**Purpose:** Multi-threaded file download with progress tracking and validation

**Arguments:**
- `DownloadDirectory` (required) - Destination folder
- `URI` (multiple) - File URLs to download
- `OpenFolderAfterDownload` (optional) - Open folder when complete
- `AuthenticationScheme` (optional) - HTTP auth scheme (e.g., "Bearer")
- `AuthenticationParameter` (optional) - Auth token/parameter

**CLI Example:**
```bash
RasProcess.exe DownloadFiles ^
  -DownloadDirectory="C:\Downloads" ^
  -URI="https://example.com/file1.zip" ^
  -URI="https://example.com/file2.zip"
```

**Features:**
- **Validation:** Pre-validates URLs, checks file existence and size
- **Multi-threaded:** Parallel downloads with per-file progress
- **Resumable:** Handles partial downloads
- **Authentication:** Supports Bearer tokens, TLS 1.2
- **Conflict Resolution:** Interactive file replace/rename/skip dialogs
- **Cancellation:** Per-file or global cancellation support

**GUI Integration:**
```csharp
var cmd = new DownloadFilesCommand(downloadDir, urls, openFolder: true,
    callingFormCenter, authentication);
cmd.ExecuteOutOfProcessShowComputeWindow();
```

---

#### `WebTaskQueryCommand` - Async Web Export Workflow
**Purpose:** Poll web service task status and download exported files

**Workflow:**
1. POST to generate export (returns task ID and export ID)
2. Poll task status until success/failure
3. Retrieve export download URL
4. Launch `DownloadFilesCommand` to download

**Arguments:**
- `DownloadDirectory` (required)
- `GenerateExportURI` (required) - POST endpoint to start export
- `GenerateExportHTTPContents` (required) - POST body key-value pairs
- `ExportStartedResponseType` (required) - .NET Type for JSON deserialization
- `TaskIDField` (required) - JSON property name for task ID
- `ExportIDField` (required) - JSON property name for export ID
- `GetTaskURI` (required) - GET endpoint template for task status
- `TaskURIFormatStr` (required) - Format string token (replaced with task ID)
- `TaskResponseType` (required) - .NET Type for task status JSON
- `StateField` (required) - JSON property name for task state
- `SuccessStates` (required) - Array of success state strings
- `FailureStates` (required) - Array of failure state strings
- `GetExportURI` (required) - GET endpoint template for export info
- `ExportURIFormatStr` (required) - Format string token (replaced with export ID)
- `ExportResponseType` (required) - .NET Type for export info JSON
- `ExportURLField` (required) - JSON property name for download URL

**Example (Conceptual):**
```csharp
var cmd = new WebTaskQueryCommand(
    downloadDir: "C:\\Downloads",
    generateExportURI: "https://api.example.com/exports",
    generateExportHTTPContents: new[] {
        new KeyValuePair("format", "tif"),
        new KeyValuePair("bbox", "...")
    },
    exportedStartedResponseType: typeof(ExportStartResponse),
    taskIDField: "task_id",
    exportIDField: "export_id",
    getTaskURI: "https://api.example.com/tasks/{TASKID}",
    taskURLFormatStr: "{TASKID}",
    taskResponseType: typeof(TaskStatusResponse),
    stateField: "state",
    successStates: new[] { "COMPLETED", "SUCCESS" },
    failureStates: new[] { "FAILED", "ERROR" },
    getExportURI: "https://api.example.com/exports/{EXPORTID}",
    exportURIFormatStr: "{EXPORTID}",
    exportResponseType: typeof(ExportInfoResponse),
    exportURLField: "download_url",
    openFolderAfterDownload: true,
    callingFormAbsoluteCenterPoint: new Point(500, 400)
);
cmd.Execute();
```

**Internal Behavior:**
- Polls task every 60 seconds (`Thread.Sleep(60000)`)
- Uses reflection to deserialize JSON to specified types
- Recursively searches JSON properties to find field names
- Appends `access_token` query parameter if authentication provided

---

#### `LaunchRasMapper` - Launch RASMapper GUI
**Purpose:** Launch RASMapper.exe with specified files

**Arguments:**
- `Files` - List of files to open in RASMapper

**Static Helper:**
```csharp
LaunchRasMapperCommand.LaunchWith(new[] { "project.prj", "model.p01.hdf" });
```

**Hardcoded Path:**
```csharp
"C:\\Programs\\6.x Development\\rasmapper.exe"
```
*Note: This would need to be configurable for production use*

---

#### `MergePolygon` - Merge Polygon Binary File
**Purpose:** Merge polygon data from binary file (contour band processing)

**Arguments:**
- `PolygonBinaryFile` (required) - Path to `.bin` file with polygon data

**Internal Use:**
- Called by `ContourBandRaster.ExternalProcessMerge()`
- Used for contour band map generation

---

## Supporting Classes

### `ArrivalTimeParameters`
**Purpose:** Parameter object for arrival time maps

**Properties:**
- `ArrivalStart` (string) - Start profile name
- `ArrivalEnd` (string) - End profile name
- `TimeUnits` (enum) - Hours, Days, or None

---

### `TimeUnits` Enum
```csharp
public enum TimeUnits
{
    None,
    Hours,
    Days
}
```

---

### `SetSRSHelper` - Spatial Reference Helper
**Purpose:** RAII pattern for temporarily setting SharedData.SRSFilename

**Constructors:**
```csharp
// From terrain layer
new SetSRSHelper(TerrainLayer trLayer, bool forceOverwriteSRSFilename = false)

// From .rasmap file
new SetSRSHelper(string rasmapFile, bool forceOverwriteSRSFilename = false)
```

**Behavior:**
1. Saves current `SharedData.SRSFilename`
2. Reads projection from terrain or `.rasmap`
3. Creates temp `.prj` file and sets `SharedData.SRSFilename`
4. On `Dispose()`: restores original SRS, deletes temp file

**Usage Pattern:**
```csharp
using (new SetSRSHelper(terrainLayer))
{
    // Operations that need correct SRS
    resultMap.StoreMap(prog);
}
// SRS automatically restored
```

---

## Python Integration Guide

### Option 1: Command-Line Invocation (subprocess)

```python
import subprocess
import xml.etree.ElementTree as ET

def complete_geometry(geom_hdf: str, ras_process_exe: str = "RasProcess.exe"):
    """Complete geometry preprocessing via RasProcess.exe"""
    cmd = [
        ras_process_exe,
        "CompleteGeometry",
        geom_hdf
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"CompleteGeometry failed: {result.stderr}")
    return result.stdout

def store_map(result_hdf: str, map_type: str, profile_name: str,
              output_file: str = None, ras_process_exe: str = "RasProcess.exe"):
    """Generate stored map via RasProcess.exe"""
    cmd = [
        ras_process_exe,
        "StoreMap",
        f"-Result={result_hdf}",
        f"-MapType={map_type}",
        f"-ProfileName={profile_name}"
    ]
    if output_file:
        cmd.append(f"-OutputBaseFilename={output_file}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"StoreMap failed: {result.stderr}")
    return result.stdout
```

---

### Option 2: XML Command Files

```python
import xml.etree.ElementTree as ET
import subprocess
import tempfile
import os

def create_command_xml(command_name: str, **kwargs) -> str:
    """Generate XML command file"""
    root = ET.Element("Command")
    root.set("Type", command_name)

    for key, value in kwargs.items():
        elem = ET.SubElement(root, key)
        elem.text = str(value)

    tree = ET.ElementTree(root)

    # Write to temp file
    fd, path = tempfile.mkstemp(suffix='.xml', text=True)
    with os.fdopen(fd, 'w') as f:
        tree.write(f, encoding='unicode', xml_declaration=True)

    return path

def execute_command_xml(xml_path: str, ras_process_exe: str = "RasProcess.exe"):
    """Execute command from XML file"""
    cmd = [ras_process_exe, f"-CommandFile={xml_path}"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up temp file
    try:
        os.remove(xml_path)
    except:
        pass

    if result.returncode != 0:
        raise RuntimeError(f"Command execution failed: {result.stderr}")

    return result.stdout

# Usage
xml_file = create_command_xml(
    "GenerateMesh",
    GeometryFilename="model.g01.hdf",
    PerimeterFilename="perimeter.shp",
    CellSize="100",
    Name="Mesh2D"
)
output = execute_command_xml(xml_file)
```

---

### Option 3: COM Interop (pythonnet/comtypes)

**Not Recommended:** The Scripting namespace is designed for CLI/batch use. For COM automation, use the main RASMapper COM interface documented in the RASMapperCom namespace.

---

## Automation Opportunities

### 1. Headless Geometry Preprocessing Pipeline

```python
def preprocess_geometry(geom_hdf: str, terrain_tif: str, landcover_xml: str):
    """Complete geometry preprocessing pipeline"""
    # Associate terrain and land cover
    subprocess.run([
        "RasProcess.exe", "SetGeometryAssociation",
        f"-GeometryFilename={geom_hdf}",
        f"-TerrainFilename={terrain_tif}",
        f"-NValueFilename={landcover_xml}"
    ], check=True)

    # Complete geometry preprocessing
    subprocess.run([
        "RasProcess.exe", "CompleteGeometry",
        geom_hdf
    ], check=True)

    # Compute property tables
    subprocess.run([
        "RasProcess.exe", "ComputePropertyTables",
        geom_hdf
    ], check=True)
```

---

### 2. Batch Map Generation

```python
def generate_all_max_maps(result_hdf: str, output_dir: str):
    """Generate all maximum result maps"""
    map_types = ["Depth", "Velocity", "WSE", "DepthTimesVelocity"]

    for map_type in map_types:
        output_file = os.path.join(output_dir, f"{map_type}_Max.tif")
        subprocess.run([
            "RasProcess.exe", "StoreMap",
            f"-Result={result_hdf}",
            f"-MapType={map_type}",
            "-ProfileName=Max",
            f"-OutputBaseFilename={output_file}"
        ], check=True)
        print(f"Generated {map_type} map")
```

---

### 3. Automated Results Processing

```python
def postprocess_results(result_hdf: str):
    """Complete all post-processing steps"""
    # Complete preprocessing
    subprocess.run([
        "RasProcess.exe", "CompletePreprocess",
        result_hdf
    ], check=True)

    # Generate post-processor file
    subprocess.run([
        "RasProcess.exe", "GeneratePostProcess",
        result_hdf
    ], check=True)

    print("Post-processing complete")
```

---

### 4. Programmatic Mesh Generation

```python
def create_mesh_from_shapefile(geom_hdf: str, perimeter_shp: str,
                                cell_size: float, mesh_name: str):
    """Generate 2D mesh from perimeter shapefile"""
    subprocess.run([
        "RasProcess.exe", "GenerateMesh",
        f"-GeometryFilename={geom_hdf}",
        f"-PerimeterFilename={perimeter_shp}",
        f"-CellSize={cell_size}",
        f"-Name={mesh_name}"
    ], check=True)

    print(f"Mesh '{mesh_name}' created with cell size {cell_size}")
```

---

### 5. RASMapper Batch Processing Workflow

```python
def complete_rasmapper_workflow(rasmap_file: str):
    """Execute complete RASMapper batch workflow"""
    # Store all configured maps
    subprocess.run([
        "RasProcess.exe", "StoreAllMaps",
        f"-RasMapFilename={rasmap_file}"
    ], check=True)

    print("All stored maps generated from .rasmap configuration")
```

---

## Command Reference Table

| Command Name | Primary Use Case | Key Arguments | Output |
|--------------|------------------|---------------|--------|
| **CompleteGeometry** | Preprocess geometry HDF | `GeometryFilename` | Populated geometry HDF |
| **CreateGeometry** | Create new geometry file | `GeometryFilename`, `Title`, `UnitSystem` | Empty geometry HDF |
| **SetGeometryAssociation** | Link terrain/land cover | `GeometryFilename`, `TerrainFilename`, `NValueFilename` | Updated HDF associations |
| **GenerateMesh** | Create 2D mesh | `GeometryFilename`, `PerimeterFilename`, `CellSize`, `Name` | Mesh added to geometry |
| **ComputePropertyTables** | Generate 2D property tables | `Geometry` | HTAB datasets in HDF |
| **LoadSaveGeometry** | Refresh geometry layers | `Filename` | Rewritten HDF |
| **CompletePreprocess** | Complete all preprocessing | `ResultFilename` | Fully preprocessed result HDF |
| **CompleteEventConditions** | Write boundary conditions | `ResultFilename` | Event condition datasets |
| **GeneratePostProcess** | Create post-processor file | `ResultFilename` | Time series datasets |
| **RemoveResults** | Strip results from HDF | `Source`, `Destination` | Geometry-only HDF |
| **StoreMap** | Generate single map | `Result`, `MapType`, `ProfileName` | GeoTIFF raster |
| **StoreAllMaps** | Batch generate maps | `RasMapFilename` | Multiple GeoTIFF files |
| **DiffH5** | Compare HDF files | `BaseFilename`, `NewFilename` | Diff report |
| **DownloadFiles** | Download from URLs | `DownloadDirectory`, `URI` (multiple) | Downloaded files |
| **WebTaskQueryCommand** | Web export workflow | Many (see details above) | Downloaded export |
| **LaunchRasMapper** | Open RASMapper GUI | `Files` (list) | GUI application |
| **MergePolygon** | Merge polygon binary | `PolygonBinaryFile` | Internal processing |

---

## Advanced Features

### Progress Reporting

All commands support `ProgressReporter` for monitoring execution:

```csharp
var prog = ProgressReporter.ConsoleWrite();
prog.MessageReported += (msg, msgType) => {
    Console.WriteLine($"[{msgType}] {msg}");
};

command.Execute(prog);
```

**Message Types:**
- `MessageType.Normal` - Informational messages
- `MessageType.Error` - Error messages
- `MessageType.Warning` - Warning messages

---

### Cancellation Support

Commands like `DownloadFilesCommand` support cancellation:

```csharp
prog.RequestCancel();  // Triggers cancellation
```

---

### Validation

All commands implement `ValidateArguments()`:
- Checks file existence
- Validates required parameters
- Reports errors via `ProgressReporter`
- Returns `false` if validation fails

---

### XML Persistence

Commands can be saved/loaded as XML:

```csharp
// Save
XElement xml = command.XMLSave();
xml.Save("command.xml");

// Load
XElement xml = XElement.Load("command.xml");
Command cmd = Command.XMLLoad(xml);
cmd.Execute();
```

---

## RasProcess.exe Entry Point

**Location:** Same directory as `RasMapperLib.dll`

**Static Field:**
```csharp
Command.RASProcessEXE = Path.Combine(
    Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location),
    "RasProcess.exe"
);
```

**Expected Behavior:**
- Parses command-line arguments via `Command.ParseExecute(args)`
- Executes command with console progress reporting
- Returns exit code (0 = success, non-zero = error)

---

## Best Practices for Python Integration

### 1. Error Handling
```python
import subprocess

def run_command(args: list[str]) -> str:
    """Run RasProcess.exe with error handling"""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False  # Don't raise exception yet
    )

    if result.returncode != 0:
        # Parse error from stderr
        raise RuntimeError(
            f"Command failed with code {result.returncode}\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )

    return result.stdout
```

---

### 2. Path Handling
```python
import os

def normalize_path(path: str) -> str:
    """Convert to absolute path with correct separators"""
    return os.path.abspath(path).replace('/', '\\')

# Usage
geom_hdf = normalize_path("../models/model.g01.hdf")
```

---

### 3. Argument Quoting
```python
def quote_arg(arg: str) -> str:
    """Quote argument if it contains spaces"""
    if ' ' in arg:
        return f'"{arg}"'
    return arg

cmd = [
    "RasProcess.exe",
    "CompleteGeometry",
    quote_arg(geom_hdf_path)
]
```

---

### 4. Parallel Execution
```python
from concurrent.futures import ThreadPoolExecutor
import subprocess

def store_map(result_hdf: str, map_type: str, profile: str):
    """Store single map"""
    subprocess.run([
        "RasProcess.exe", "StoreMap",
        f"-Result={result_hdf}",
        f"-MapType={map_type}",
        f"-ProfileName={profile}"
    ], check=True)

# Parallel map generation
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [
        executor.submit(store_map, "model.p01.hdf", map_type, "Max")
        for map_type in ["Depth", "Velocity", "WSE"]
    ]
    for future in futures:
        future.result()  # Wait for completion
```

---

## Summary

The `RasMapperLib.Scripting` namespace provides:

1. **Complete CLI automation** of RASMapper operations
2. **Batch processing** capabilities for geometry and results
3. **Headless execution** without GUI requirement
4. **Progress tracking** and cancellation support
5. **XML-based** command persistence
6. **Validation** and error reporting
7. **Python-friendly** subprocess invocation

**Primary Use Cases:**
- Automated geometry preprocessing pipelines
- Batch map generation for flood modeling
- CI/CD integration for HEC-RAS workflows
- Headless server-side processing
- Scripted result analysis workflows

**Limitations:**
- Some commands are stubs (`ExportGeometry`)
- Hardcoded paths in some commands (`LaunchRasMapperCommand`)
- Limited COM interface (use CLI invocation instead)
- No direct Python bindings (use subprocess calls)

**Recommended Approach for ras-commander:**
Implement Python wrappers around `RasProcess.exe` subprocess calls, focusing on the most valuable commands:
- `CompleteGeometry`, `CompletePreprocess` - Preprocessing automation
- `StoreMap`, `StoreAllMaps` - Map generation
- `GenerateMesh` - Programmatic mesh creation
