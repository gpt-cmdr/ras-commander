---
paths: ras_commander/**
---

# HEC-RAS Terrain Creation

**Context**: Creating terrain HDF files programmatically via CLI
**Priority**: Medium - terrain workflows
**Auto-loads**: Yes (terrain-related code)
**Path-Specific**: Relevant to `ras_commander/terrain/`

## Primary Source

**See**: `ras_commander/terrain/RasTerrain.py` for complete terrain API.

**Future**: `ras_commander/terrain/CLAUDE.md` will provide workflow documentation (to be created).

## Overview

Create HEC-RAS terrain files (`.hdf`) programmatically. These files store multi-resolution elevation data with pyramid levels and multi-source stitching. Use CLI-based terrain creation via `RasProcess.exe` (HEC-RAS 6.6+).

## Key Classes

| Class | Purpose |
|-------|---------|
| `RasTerrain` | Terrain HDF creation, VRT conversion via RasProcess.exe CLI |
| `Usgs3depAws` | USGS 3DEP elevation tile download from AWS S3 |
| `RasTerrainMod` | Terrain modification analysis via pythonnet (cut/fill, no-net-fill) |

## RasProcess.exe CreateTerrain Command

### Discovery

**Found**: 2025-12-25 during terrain CLI research

**Location**: `C:\Program Files (x86)\HEC\HEC-RAS\{version}\RasProcess.exe`

**Available in**: HEC-RAS 6.6+ (possibly 6.5, untested)

**Older versions**: HEC-RAS 5.0.4-5.0.7 have separate `CreateTerrain.exe` (untested)

### Command Syntax

```bash
RasProcess.exe CreateTerrain units=Feet stitch=true prj="C:\Path\Projection.prj" out="C:\Path\Terrain.hdf" "C:\Path\input1.tif" "C:\Path\input2.tif"
```

### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `units=Feet` | string | Yes | Vertical units: "Feet" or "Meters" |
| `stitch=true` | bool | Yes | Enable TIN stitching: "true" or "false" |
| `prj="path.prj"` | string | Yes | ESRI PRJ file (coordinate system) |
| `out="path.hdf"` | string | Yes | Output terrain HDF path |
| `"input.tif"` | string(s) | Yes | Input rasters (highest to lowest priority) |

### Critical Requirements

**Path Quoting**:
- ALL file paths must be in double quotes
- Executable path must be quoted (spaces in "Program Files")

**Example**:
```python
cmd_str = f'"{ras_process_exe}" CreateTerrain units=Feet stitch=true prj="{prj_file}" out="{output_hdf}" "{input_tif}"'
subprocess.run(cmd_str, shell=True)
```

**Priority Order**:
Input files are processed in command-line order:
- First file = highest priority
- Last file = lowest priority (fills gaps)

**Use case**: Bathymetric data first (high priority), base terrain second (fill)

### Output Structure

Creates terrain HDF with:
- **Stitch TIN Points** - X, Y, Z, M coordinates for stitching
- **Stitch TIN Triangles** - Triangle vertex indices
- **Stitches** - Metadata for multi-source blending
- **Source layers** - One per input raster, each with:
  - Pyramid levels 0-6 (7 levels total)
  - Mask, Min-Max, Perimeter datasets per level
  - Tile-based storage (65536 cells per tile row)

### Progress Output

Command outputs progress to stdout:
```
Importing 1 of 1: input.tif -> Terrain.input.tif
Final Processing: Terrain.hdf
PROGRESS=0
PROGRESS=1
...
PROGRESS=100
```

**Execution time**: ~10 seconds for 50ft DEM, scales with resolution and extent

## Quick Reference

```python
from ras_commander.terrain import RasTerrain
from pathlib import Path

# Create terrain HDF from TIFF
terrain = RasTerrain.create_terrain_hdf(
    input_rasters=[Path("dem.tif")],
    output_hdf=Path("Terrain/Terrain.hdf"),
    projection_prj=Path("Terrain/Projection.prj"),
    units="Feet",
    hecras_version="7.0"
)

# Convert VRT to TIFF (preprocessing)
tiff = RasTerrain.vrt_to_tiff(
    vrt_path=Path("combined.vrt"),
    output_path=Path("combined.tif"),
    compression="LZW",
    create_overviews=True
)

# Register terrain in RasMapper
from ras_commander import RasMap
RasMap.add_terrain_layer(
    terrain_hdf=terrain,
    rasmap_path=Path("Project.rasmap"),
    layer_name="MyTerrain"
)
```

## Troubleshooting

### Command Fails with "Program is not recognized"

**Symptom**: `'C:\Program' is not recognized as an internal or external command`

**Cause**: Spaces in path without proper quoting

**Fix**: Quote the executable path:
```python
# ❌ Wrong
cmd = [str(ras_process_exe), "CreateTerrain", ...]
subprocess.run(cmd, shell=True)

# ✅ Correct
cmd_str = f'"{ras_process_exe}" CreateTerrain ...'
subprocess.run(cmd_str, shell=True)
```

### Output HDF Not Created

**Check**:
1. RasProcess.exe exists? (HEC-RAS 6.6+ installed?)
2. Input TIFF files valid? (try opening in QGIS/ArcGIS)
3. Projection PRJ file exists and valid?
4. Output folder has write permissions?
5. Check stderr for error messages

### Terrain Not Visible in RasMapper

**Check**:
1. Terrain layer added to .rasmap? (use `RasMap.add_terrain_layer()`)
2. Relative path correct? (should be `.\Terrain\{name}.hdf`)
3. TerrainDestinationFolder set in .rasmap?
4. Projection file referenced in .rasmap?

## Terrain Modification Analysis (RasTerrainMod)

**New**: Sample terrain WITH modifications applied via pythonnet + RasMapperLib.dll. No GUI required.

```python
from ras_commander.terrain import RasTerrainMod

# One-time setup (creates GDAL junction)
RasTerrainMod.setup_gdal_bridge()

# Sample terrain profile with channels/levees/polygon overrides applied
profile = RasTerrainMod.get_terrain_profile(
    "project.rasmap", "project.g01.hdf",
    x_coords=[3400000, 3410000], y_coords=[612000, 612000]
)

# Elevation-volume curve for a polygon (for pond sizing / no-net-fill)
ev = RasTerrainMod.get_terrain_volume_elevation(
    "project.rasmap", "project.g01.hdf",
    x_coords=pond_polygon_x, y_coords=pond_polygon_y,
    volume_factor=43560.0  # acre-feet
)
```

**Requirements**: pythonnet (`pip install pythonnet`), HEC-RAS 6.6+, Windows.

**How it works**: Loads `RasMapperLib.dll` via pythonnet and calls `RASMapperCom` methods directly. Terrain modifications (channels, levees, polygon overrides stored in `/Modifications/` within terrain HDF) are applied on-the-fly by the .NET code, identical to RASMapper.

**See**: `examples/930_terrain_modification_analysis.ipynb` for complete cut/fill workflow.

## Cross-References

**Primary sources**:
- `ras_commander/terrain/` -- Terrain module implementation
- `ras_commander/terrain/RasTerrainMod.py` -- Terrain modification analysis via pythonnet
- `examples/920_terrain_creation.ipynb` -- Terrain creation workflow
- `examples/930_terrain_modification_analysis.ipynb` -- Cut/fill analysis workflow

**Research**:
- `feature_dev_notes/Terrain_Modifications/` -- HDF format research, API design, rasterization path

---

**Key Takeaway**: Use `RasTerrain.create_terrain_hdf()` for terrain creation, `RasTerrainMod.get_terrain_profile()` for sampling terrain with modifications. Register terrains with `RasMap.add_terrain_layer()`. For cut/fill: use `RasTerrainMod.compare_terrain_volumes()`.
