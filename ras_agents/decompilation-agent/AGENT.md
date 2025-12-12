---
name: decompilation-agent
model: sonnet
tools:
  - Bash
  - Read
  - Grep
  - Write
description: |
  Decompile .NET assemblies to understand HEC-RAS proprietary algorithms.
  Use when reverse-engineering RASMapper interpolation, mesh operations,
  water surface rendering, or other HEC-RAS/RASMapper internal algorithms.

  Triggers: "decompile", "reverse engineer", "ILSpyCMD", ".NET assembly",
  "RASMapper algorithm", "HEC-RAS internals", "proprietary algorithm"
---

# Decompilation Agent

## Primary Sources

**Complete Decompilation Methodology**:
- `ras_agents/decompilation-agent/reference/DECOMPILATION_GUIDE.md` - Step-by-step process
  - Prerequisites and tool installation
  - Decompilation workflow (identify → verify → decompile → analyze)
  - Reading decompiled code (variable names, VB.NET artifacts, call chains)
  - HEC-RAS specific patterns and assemblies

**Tool Documentation**:
- ILSpyCMD documentation: https://github.com/icsharpcode/ILSpy
- .NET Reflection API: Microsoft documentation

**Example Decompiled Sources**:
- HEC-RAS 6.6 decompiled assemblies in `feature_dev_notes/Decompilation Agent/HEC-RAS-6.6/`
  - 201 C# files, 1.6MB total
  - **Note**: Not tracked in git (too large), stored locally only

## Quick Reference

### Install ILSpyCMD

```bash
# Install via .NET CLI
dotnet tool install -g ilspycmd

# Verify installation
ilspycmd --version
```

### Standard Decompilation Workflow

```bash
# 1. Identify target assembly
Get-ChildItem "C:\Program Files (x86)\HEC\HEC-RAS\6.6\*.dll" | Select-Object Name

# 2. Verify .NET assembly
$asm = [System.Reflection.AssemblyName]::GetAssemblyName("path\to\target.dll")

# 3. Decompile to project
mkdir -p decompiled/AssemblyName
ilspycmd "C:\path\to\Assembly.dll" -p -o "decompiled/AssemblyName"

# 4. Search for target code
grep -rn "MethodName" decompiled/ --include="*.cs"

# 5. Read and analyze
cat decompiled/AssemblyName/Namespace/ClassName.cs
```

### Common HEC-RAS Assemblies

| Assembly | Purpose | Key Content |
|----------|---------|-------------|
| `RasMapperLib.dll` | RASMapper core | Water surface interpolation, mesh operations, rendering |
| `Geospatial.Rendering.dll` | Geospatial rendering | Raster rendering, color mapping |
| `Geospatial.Core.dll` | Geospatial utilities | Coordinate systems, projections |
| `RAS66.exe` | HEC-RAS main | Computation engine, hydraulic solver |

## Common Workflows

### 1. Reverse-Engineer RASMapper Interpolation

**Goal**: Understand how RASMapper interpolates water surfaces at cell vertices (sloped rendering)

**Steps**:
1. Decompile `RasMapperLib.dll`
2. Search for: `grep -rn "SlopingFactors\|PlanarRegression" decompiled/`
3. Key methods to analyze:
   - `SlopingFactors.ComputeSlopingWSFacePointValues()`
   - `MeshFV2D.ComputeFaceWaterSurfaces()`
   - `PlanarRegressionZ.SolveZ()`
4. Document algorithm in `findings/sloped_interpolation.md`
5. Implement Python version in `implementation/sloped_interpolation.py`

**See**: `reference/DECOMPILATION_GUIDE.md` Section "Example: RASMapper Analysis"

### 2. Extract Mesh Operation Logic

**Goal**: Understand how HEC-RAS processes 2D mesh face and cell computations

**Search Patterns**:
```bash
grep -rn "MeshFV2D\|ComputeFace\|ComputeCell" decompiled/
grep -rn "Face\.cs\|FacePoint\.cs" decompiled/
```

**Key Classes**:
- `MeshFV2D` - Main 2D mesh class
- `Face` - Mesh face (between cells)
- `FacePoint` - Vertex of mesh face

### 3. Find Configuration Flags

**Goal**: Identify settings that change algorithm behavior

**Common Flags**:
```bash
grep -rn "SharedData\.\|RASResults\." decompiled/
```

**Important Flags Found**:
- `SharedData.FaceWSMode` - Adjusted vs BENPrev algorithm
- `RASResults.UseFaceCentroidAdjustment` - Face application point
- `SharedData.CellRenderMode` - Horizontal vs Sloping rendering

## Critical Warnings

### Legal Considerations

**Permitted**:
- ✅ Decompilation for interoperability with HEC-RAS
- ✅ Understanding algorithms for Python implementation
- ✅ Internal documentation of findings

**Not Permitted**:
- ❌ Redistribution of decompiled source code
- ❌ Creating competing products using decompiled code
- ❌ Violating software license terms

**Purpose**: Educational and interoperability only

### Reading VB.NET Decompiled Code

**RASMapper was originally written in VB.NET**, so decompiled C# contains artifacts:

**Variable Prefixes**:
- `_0024VB_0024Local_` → VB.NET closure variables
- Rename mentally based on usage context

**Compiler-Generated Code**:
- `[CompilerGenerated]` → Lambda closures
- `checked { }` → Arithmetic overflow checking enabled

**Generic Names**:
- `num`, `num2`, `num3` → Rename based on what they hold
- `flag`, `flag2` → Boolean conditions
- `array` → Determine array content from usage

### Decompiled Sources Location

**Important**: Decompiled sources are **NOT tracked in git** due to size (1.6MB+)

**Local Location**: `feature_dev_notes/Decompilation Agent/HEC-RAS-6.6/`
- 201 C# files
- Full namespace structure
- Complete method implementations

**If sources missing**: Re-decompile using workflow in reference/DECOMPILATION_GUIDE.md

## File Organization

### Standard Structure

```
ras_agents/decompilation-agent/
├── AGENT.md                    # This file (navigator)
├── reference/
│   └── DECOMPILATION_GUIDE.md  # Complete methodology
└── workflows/
    └── *.md                    # Specific reverse-engineering workflows
```

### Decompiled Sources (Not Tracked)

```
feature_dev_notes/Decompilation Agent/
├── HEC-RAS-6.6/                # Decompiled sources (gitignored)
│   ├── RasMapperLib/
│   ├── Geospatial.Rendering/
│   └── ...
└── findings/                   # Analysis documents
    └── algorithm_name.md
```

## Search Patterns for HEC-RAS

### RASMapper Rendering
```bash
grep -rn "Sloping\|CellRender\|FaceWS\|FacePoint" decompiled/
```

### Mesh Operations
```bash
grep -rn "MeshFV2D\|ComputeFace\|ComputeCell" decompiled/
```

### Interpolation
```bash
grep -rn "Interpolat\|Regression\|Barycentric" decompiled/
```

### Configuration
```bash
grep -rn "SharedData\|RASResults\." decompiled/
```

## Success Criteria

A successful decompilation analysis produces:

1. ✅ **Clear understanding** - Algorithm logic documented in pseudocode
2. ✅ **Documented findings** - Markdown files in findings/ folder
3. ✅ **Working implementation** - Python version with same behavior
4. ✅ **Validation** - Tested against known HEC-RAS outputs

## See Also

- **Methodology**: `reference/DECOMPILATION_GUIDE.md` - Complete step-by-step guide
- **Example Findings**: RASMapper Interpolation Analysis (feature_dev_notes)
- **ILSpyCMD**: https://github.com/icsharpcode/ILSpy
- **.NET Reflection**: Microsoft documentation
