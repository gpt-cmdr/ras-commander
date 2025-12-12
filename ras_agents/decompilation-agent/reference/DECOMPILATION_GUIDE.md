# .NET Assembly Decompilation Guide

This guide documents the methodology for decompiling .NET assemblies to understand proprietary algorithms. Successfully used to reverse-engineer RASMapper's water surface interpolation algorithms from HEC-RAS 6.6.

## Prerequisites

### Required Tools

1. **ILSpyCMD** - Command-line .NET decompiler
   - Install via .NET tool: `dotnet tool install -g ilspycmd`
   - Alternative: Download from https://github.com/icsharpcode/ILSpy/releases

2. **PowerShell** - For assembly inspection and file operations

3. **.NET Runtime** - Required for running ILSpyCMD

### Identifying .NET Assemblies

Before decompiling, verify the target is a .NET assembly:

```powershell
# Check if file is a .NET assembly by examining headers
[System.Reflection.AssemblyName]::GetAssemblyName("path\to\assembly.dll")

# This returns assembly info if valid .NET, throws exception if not
```

## Decompilation Process

### Step 1: Locate Target Assemblies

For HEC-RAS 6.6, key assemblies are in:
```
C:\Program Files (x86)\HEC\HEC-RAS\6.6\
```

Common targets:
- `RasMapperLib.dll` - RASMapper rendering and mapping algorithms
- `Geospatial.Rendering.dll` - Geospatial rendering utilities
- `Geospatial.Core.dll` - Core geospatial operations

### Step 2: Verify Assembly Type

```powershell
# Check assembly version and type
$asm = [System.Reflection.AssemblyName]::GetAssemblyName("C:\Program Files (x86)\HEC\HEC-RAS\6.6\RasMapperLib.dll")
$asm.Version  # Returns version like 2.0.0.0
```

### Step 3: Decompile to Project

Use ILSpyCMD to decompile the entire assembly to a C# project:

```bash
# Decompile to project folder with full source
ilspycmd "C:\Program Files (x86)\HEC\HEC-RAS\6.6\RasMapperLib.dll" -p -o "output\RasMapperLib"
```

Options:
- `-p` - Generate a complete C# project
- `-o <path>` - Output directory
- `-lv CSharp10` - Target C# language version (optional)

### Step 4: Navigate Decompiled Source

The output structure typically follows namespaces:
```
RasMapperLib/
├── RasMapperLib.csproj
├── RasMapperLib/           # Root namespace classes
│   ├── MeshFV2D.cs
│   ├── PlanarRegressionZ.cs
│   └── ...
├── RasMapperLib.Mapping/   # Subnamespace
│   ├── SlopingCellPoint.cs
│   └── ...
├── RasMapperLib.Mesh/      # Mesh-related classes
│   ├── Face.cs
│   ├── FacePoint.cs
│   └── ...
└── RasMapperLib.Render/    # Rendering classes
    ├── SlopingFactors.cs
    ├── WaterSurfaceRenderer.cs
    └── ...
```

### Step 5: Search for Relevant Code

Use grep/search to find algorithms of interest:

```bash
# Find method definitions
grep -rn "ComputeFaceWaterSurfaces" decompiled/

# Find class definitions
grep -rn "class PlanarRegression" decompiled/

# Find specific calculations
grep -rn "planarRegressionZ.SolveZ" decompiled/
```

## Best Practices

### Reading Decompiled Code

1. **Variable Names**: Decompiled code often has generic names like `num`, `num2`, `flag`. Rename them mentally based on context.

2. **Compiler-Generated Code**: Look for `[CompilerGenerated]` attributes - these are lambda closures and can be complex.

3. **VB.NET Origins**: If you see `_0024VB_0024Local_` prefixes, the original was VB.NET (RASMapper was written in VB.NET).

4. **Checked Arithmetic**: `checked { }` blocks indicate overflow checking was enabled.

### Tracing Algorithm Flow

1. Start from public entry points (public methods)
2. Follow method calls to find implementations
3. Document data flow between methods
4. Look for configuration flags that change behavior

### Common Patterns in HEC Software

- **Static Methods**: Many utility functions are static
- **Parallel Processing**: `Parallel.SmartFor` for multi-threaded loops
- **Nullable Handling**: Extensive null checks
- **Float vs Double**: HEC-RAS uses both, watch for precision

## Example: RASMapper Analysis

### Target: Sloped Water Surface Interpolation

**Entry Point**: `SlopingFactors.ComputeSlopingWSFacePointValues()`

**Key Methods Found**:
1. `MeshFV2D.ComputeFaceWaterSurfaces()` - Face WSE calculation
2. `MeshFV2D.ComputeFacePointWSs()` - Vertex WSE via planar regression
3. `PlanarRegressionZ.SolveZ()` - Least-squares plane fitting
4. `RASD2FlowArea.GetFaceLocationFunc()` - Face application point

**Configuration Flags**:
- `SharedData.FaceWSMode` - Adjusted vs BENPrev algorithm
- `RASResults.UseFaceCentroidAdjustment` - Face point location
- `SharedData.CellRenderMode` - Horizontal vs Sloping

### Output Documentation

Create comprehensive documentation:
1. **Algorithm pseudocode** - Readable version of the logic
2. **Python implementation** - Portable version for testing
3. **Validation plan** - How to verify correctness against ground truth

## Troubleshooting

### "Assembly could not be loaded"
- Check .NET version compatibility
- May need to copy dependent DLLs to same folder

### "GetTypes() throws exception"
- Some assemblies have complex dependencies
- Use ILSpyCMD instead of reflection

### "Decompiled code has errors"
- Some constructs don't decompile cleanly
- Focus on the algorithm logic, not perfect compilation

## Legal Considerations

- Decompilation for interoperability is generally permitted
- Document findings for internal use
- Don't redistribute decompiled source code
- Respect software licenses and terms of use

## File Organization

Recommended structure for decompilation projects:
```
feature_dev_notes/
└── [Feature Name]/
    ├── decompiled/
    │   └── [AssemblyName]/     # ILSpyCMD output
    ├── findings/
    │   └── algorithm_name.md   # Documentation
    └── implementation/
        └── algorithm.py        # Python port
```

## Commands Reference

```bash
# Install ILSpyCMD
dotnet tool install -g ilspycmd

# Decompile to project
ilspycmd "assembly.dll" -p -o "output_folder"

# Decompile single type
ilspycmd "assembly.dll" -t "Namespace.ClassName" -o "output.cs"

# List types in assembly
ilspycmd "assembly.dll" --list
```

## Success Metrics

A successful decompilation analysis should produce:
1. Clear understanding of the algorithm
2. Documented pseudocode or flowchart
3. Working implementation in target language
4. Validation against known outputs
