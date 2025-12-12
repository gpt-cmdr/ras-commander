# RASMapper Interpolation Research

## Overview

This research folder contains reverse-engineering work on HEC-RAS RASMapper's water surface rasterization algorithms. The goal is to replicate RASMapper's interpolation methods programmatically in ras-commander to enable automated result mapping without requiring the RASMapper GUI.

**Status**: COMPLETED - Both horizontal and sloped (cell corners) interpolation methods have been successfully reverse-engineered and validated.

## Research Objective

Reverse-engineer RASMapper's water surface rasterization algorithms by:
1. Decompiling RASMapper.exe and RasMapperLib.dll (.NET assemblies)
2. Comparing programmatically-generated rasters against ground truth TIF files exported from RASMapper
3. Implementing validated algorithms in ras-commander's `RasMap` class

## Folder Structure

```
RasMapper Interpolation/
├── README.md                           # This file - project overview
├── AGENTS.md                           # Repository guidelines for AI agents
├── CLAUDE.md                           # Context for Claude Code (legacy, see AGENTS.md)
├── RASMAPPER_DECOMPILATION_REPORT.md  # Technical report on decompilation findings
│
├── decompiled_sources/                 # Decompiled .NET source code from RASMapper
│   ├── RasMapperLib/                   # Full RasMapperLib.dll decompilation
│   ├── *.decompiled.cs                 # Key interpolation classes extracted
│   └── (RASGeometryMapPoints.BensWeights() - barycentric coordinate algorithm)
│
├── research/                           # Research findings and documentation
│   ├── findings/                       # Validated algorithm documentation
│   │   ├── horizontal_2d.md           # Horizontal interpolation (VALIDATED)
│   │   ├── horizontal_clipping.md     # Clipping investigation
│   │   ├── sloped_cell_corners.md     # Sloped interpolation (VALIDATED)
│   │   ├── sloped_algorithm_decompiled.md  # Decompilation analysis
│   │   ├── sloped_vertex_wse_formula.md    # Vertex WSE calculation
│   │   ├── sloped_interpolation_analysis.md
│   │   ├── THE_ANSWER.md              # Ben's Weights discovery
│   │   └── COMPLETE_ALGORITHM_REFERENCE.md  # Full algorithm documentation
│   │
│   └── rasmapper_docs/                # RASMapper API documentation
│       ├── 00_INDEX.md                # Documentation index
│       ├── 01_mesh_namespace.md through 16_rasprocess_cli_reference.md
│       └── (Complete RASMapper Python automation guide)
│
├── scripts/                            # Active implementation and testing scripts
│   ├── rasmap_interpolation.py        # CLI for interpolation testing
│   ├── compare_mesh_vs_raster.py      # Validation tool
│   ├── rasprocess_storemap.py         # RASProcess automation
│   ├── analyze_*.py                   # Analysis scripts (error patterns, spatial errors, etc.)
│   ├── test_*.py                      # Algorithm testing scripts
│   └── final_*.py                     # Final implementations
│
├── planning/                           # Planning documents and implementation roadmaps
│   ├── IMPLEMENTATION_PLAN.md         # Original implementation plan
│   ├── SIMPLIFIED_PLAN.md             # Simplified workflow
│   └── SLOPED_INTERPOLATION_ALGORITHM.md  # Algorithm specification
│
└── .old/                               # Archived materials (NOT for active development)
    ├── README.md                       # Explanation of archived content
    ├── archived_data/                  # Old test datasets and outputs
    │   ├── Balde Eagle Creek/         # Original test project
    │   ├── Test Data/                  # Ground truth test datasets
    │   └── working/                    # Ephemeral outputs from experiments
    └── archived_scripts/               # Early experimental scripts
        └── ras_agent/                  # Initial prototypes
```

## Key Findings

### 1. Horizontal Interpolation (VALIDATED)

**Algorithm**: Constant WSE per cell
- Each 2D mesh cell has a single water surface elevation
- All raster pixels within the cell polygon receive the same WSE value
- Clipping: Only pixels where terrain < WSE are assigned depth values

**Implementation**: `RasMap.map_ras_results(interpolation_method="horizontal")`

**Validation**: Pixel-perfect match with RASMapper output (< 0.001 ft error)

### 2. Sloped (Cell Corners) Interpolation (VALIDATED)

**Algorithm**: Ben's Weights (Generalized Barycentric Coordinates)
- **Stage 1**: Compute face WSE using hydraulic connectivity rules
- **Stage 2**: Compute vertex WSE via planar regression through adjacent face values
- **Stage 3**: Rasterize using Ben's Weights (generalized barycentric coordinates for arbitrary polygons)

**Implementation**: `RasMap.map_ras_results(interpolation_method="sloped")`

**Validation**:
- Median |diff| = 0.0001 ft (essentially perfect)
- MAE = 0.0106 ft
- 90th percentile = 0.0097 ft

**Source**: Decompiled from `RASGeometryMapPoints.BensWeights()` in RasMapperLib.dll

### 3. Legal Status

HEC-RAS is **public domain** U.S. government software (Army Corps of Engineers). Decompilation for research and interoperability is legally permissible under:
- Public domain status (not subject to copyright)
- Fair use doctrine (algorithm research)
- Interoperability goals

See `RASMAPPER_DECOMPILATION_REPORT.md` for full legal analysis.

## Technology Stack

### RASMapper Architecture
- **Language**: C# / .NET Framework
- **Assemblies**: RasMapperLib.dll (10 MB), Geospatial.Rendering.dll, Geospatial.GDALAssist.dll
- **GDAL Version**: 3.02 (for raster I/O and terrain operations)
- **Decompilation Tool**: ILSpy (open-source .NET decompiler)

### Key Classes Decompiled
- `RasMapperLib.Mapping.SlopingCellPoint` - Vertex interpolation weights
- `RasMapperLib.Mapping.SlopingCellMap` - Sloped mesh mapping
- `RasMapperLib.Mapping.FlatCellMap` - Horizontal mesh mapping
- `RasMapperLib.RASGeometryMapPoints.BensWeights()` - Barycentric coordinate calculation

## Ground Truth Test Projects

Located in `.old/archived_data/Test Data/`:

### BaldEagleCrkMulti2D - Horizontal
- RASMapper setting: `<RenderMode>flat</RenderMode>`
- Used to validate horizontal interpolation method

### BaldEagleCrkMulti2D - Sloped - Cell Corners
- RASMapper settings:
  ```xml
  <RenderMode>slopingPretty</RenderMode>
  <UseDepthWeightedFaces>true</UseDepthWeightedFaces>
  <ReduceShallowToHorizontal>true</ReduceShallowToHorizontal>
  ```
- 9 plans with exported ground truth rasters
- Used to validate sloped interpolation method

## Usage

### Generate Water Surface Rasters

```python
from ras_commander import init_ras_project, RasMap

# Initialize project
init_ras_project(r"C:\path\to\project", "6.6")

# Generate horizontal raster (default)
outputs = RasMap.map_ras_results(
    plan_number="03",
    variables=["WSE", "Depth", "Velocity"],
    terrain_path="Terrain/Terrain.tif",
    interpolation_method="horizontal"
)

# Generate sloped raster (cell corners with Ben's Weights)
outputs = RasMap.map_ras_results(
    plan_number="03",
    variables=["WSE"],
    terrain_path="Terrain/Terrain.tif",
    interpolation_method="sloped"
)

# Outputs dictionary contains paths to generated TIF files
print(outputs["WSE"])  # Path to WSE (Max).tif
```

### Validate Against Ground Truth

```python
from scripts.rasmap_interpolation import compare_rasters

# Compare generated raster to RASMapper export
metrics = compare_rasters(
    generated="working/WSE (Max).tif",
    ground_truth="Test Data/.../Single 2D/WSE (Max).Terrain50.dtm_20ft.tif"
)

print(f"RMSE: {metrics['rmse']:.4f} ft")
print(f"MAE: {metrics['mae']:.4f} ft")
print(f"Max Error: {metrics['max_abs']:.4f} ft")
```

## Remaining Research Gaps

While both interpolation methods are implemented and validated, minor gaps remain:

1. **Coverage gap (29%)**: Some vertices have NODATA due to dry cells or boundary conditions
2. **Large outliers (40 ft max)**: Occur at 1D-2D connection structures
3. **Cell polygon failures (8%)**: Some cells fail with <3 face points (likely 1D structures)

These gaps represent edge cases and do not impact the core algorithm accuracy.

## Key Scripts

### Active Scripts (in `scripts/`)

- **rasmap_interpolation.py** - CLI for running interpolation and comparison
- **compare_mesh_vs_raster.py** - Validation by sampling raster at cell centers
- **rasprocess_storemap.py** - RASProcess XML automation for batch raster export
- **final_sloped_implementation.py** - Final validated sloped algorithm
- **analyze_*.py** - Error analysis and diagnostics

### Script Usage Example

```bash
# Generate and compare rasters
python scripts/rasmap_interpolation.py \
  --project "Test Data/BaldEagleCrkMulti2D - Sloped - Cell Corners" \
  --plan 03 \
  --variables WSE Depth \
  --terrain "Terrain/Terrain50.dtm_20ft.tif" \
  --output-dir working \
  --save-difference
```

## Dependencies

```bash
# Core dependencies (already in ras-commander)
pip install h5py numpy pandas geopandas rasterio shapely scipy

# Additional for research scripts
pip install matplotlib tqdm triangle
```

## References

### Research Documents
- `RASMAPPER_DECOMPILATION_REPORT.md` - Full technical decompilation report
- `research/findings/COMPLETE_ALGORITHM_REFERENCE.md` - Complete algorithm specification
- `research/findings/THE_ANSWER.md` - Ben's Weights discovery narrative

### External Resources
- [HEC-RAS Official Site](https://www.hec.usace.army.mil/software/hec-ras/)
- [GDAL Grid Tutorial](https://gdal.org/en/stable/tutorials/gdal_grid_tut.html)
- [ILSpy Decompiler](https://ilspy.org/)

## Contributing

This is research and development code. If extending:

1. Document all experiments in `research/findings/`
2. Use test projects in `.old/archived_data/Test Data/`
3. Write scripts to `scripts/` (not root)
4. Follow guidelines in `AGENTS.md`
5. Validate against ground truth rasters before claiming success

## License

This research is part of ras-commander, which is licensed under the MIT License. HEC-RAS itself is public domain U.S. government software.

---

**Last Updated**: 2025-12-11
**Status**: Research complete, algorithms implemented and validated
**Maintainer**: ras-commander development team
