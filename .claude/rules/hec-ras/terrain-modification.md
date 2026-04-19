---
description: RasTerrainMod rules — Windows-only, pythonnet setup, GDAL junction, thread safety, no-net-fill workflow
paths:
  - ras_commander/terrain/RasTerrainMod.py
  - examples/930_terrain_modification_analysis.ipynb
---

# Terrain Modification Rules (RasTerrainMod)

## Platform Constraint: Windows Only

`RasTerrainMod` wraps `RasMapperLib.dll` via pythonnet. It **will not run on Linux or macOS**, even in containers. All terrain modification sampling must run on a Windows machine with HEC-RAS 6.5+ installed.

```python
# This raises RuntimeError on non-Windows:
RasTerrainMod.get_terrain_profile(...)
```

## Prerequisites (in order)

1. **HEC-RAS 6.5 or 6.6** installed at one of:
   - `C:/Program Files (x86)/HEC/HEC-RAS/6.6/`
   - `C:/Program Files (x86)/HEC/HEC-RAS/6.5/`
   - `C:/Program Files/HEC/HEC-RAS/6.6/`

2. **pythonnet** installed: `pip install pythonnet`

3. **GDAL bridge** set up once per Python environment:
   ```python
   from ras_commander.terrain import RasTerrainMod
   RasTerrainMod.setup_gdal_bridge()  # Creates GDAL junction next to python.exe
   ```
   This creates a directory junction at `<python.exe dir>/GDAL/` pointing to HEC-RAS's GDAL. Only needs to run once. Requires write permission to the Python directory (run as admin if needed).

## Thread Safety

`RasTerrainMod` is **NOT thread-safe**. The internal `RASMapperCom` instance uses COM STA rules. Do not call methods from multiple threads simultaneously. Use a `threading.Lock()` if calling from a multi-threaded context.

```python
# BAD — concurrent calls will corrupt the COM state
with ThreadPoolExecutor() as ex:
    futures = [ex.submit(RasTerrainMod.get_terrain_profile, ...) for ...]

# GOOD — sequential calls only
for profile_args in profiles:
    result = RasTerrainMod.get_terrain_profile(**profile_args)
```

## Core Methods

| Method | Purpose | Key args |
|--------|---------|----------|
| `setup_gdal_bridge()` | One-time GDAL junction creation | `hecras_version`, `python_dir` |
| `get_terrain_extent()` | Bounding box with modifications | `rasmap_path`, `geom_hdf_path` |
| `get_terrain_profile()` | Sample terrain along polyline | + `x_coords`, `y_coords` |
| `get_terrain_volume_elevation()` | Elevation-volume curve for polygon | + polygon coordinates |
| `compare_terrain_profiles()` | Cut/fill analysis (2 profiles) | two profile dicts |
| `compare_terrain_volumes()` | No-net-fill comparison (2 E-V curves) | two volume dicts |

## Terrain Modifications Are Automatic

Modifications stored in the `.rasmap` file (channels, levees, terrain polygons) are automatically applied by `RASMapperCom`. You do not need to apply them manually. This is the entire reason to use `RasTerrainMod` rather than direct raster sampling.

```python
# Both calls sample WITH modifications applied:
profile = RasTerrainMod.get_terrain_profile(
    rasmap_path="project.rasmap",
    geom_hdf_path="project.g01.hdf",
    x_coords=[...],
    y_coords=[...]
)
```

## No-Net-Fill Workflow

```python
# 1. Sample existing terrain (pre-modification)
pre_volume = RasTerrainMod.get_terrain_volume_elevation(
    rasmap_path="project_pre.rasmap",
    geom_hdf_path="project.g01.hdf",
    polygon_x=[...], polygon_y=[...]
)

# 2. Sample with modifications (post)
post_volume = RasTerrainMod.get_terrain_volume_elevation(
    rasmap_path="project_post.rasmap",
    geom_hdf_path="project.g01.hdf",
    polygon_x=[...], polygon_y=[...]
)

# 3. Compare
comparison = RasTerrainMod.compare_terrain_volumes(pre_volume, post_volume)
# Returns: cut_volume, fill_volume, net_fill, net_fill_pct
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `RuntimeError: HEC-RAS not found` | HEC-RAS not installed or wrong version | Install HEC-RAS 6.5+ at expected path |
| `ImportError: pythonnet required` | pythonnet not installed | `pip install pythonnet` |
| `GDAL junction not found` warning | `setup_gdal_bridge()` not called | Call once before any sampling |
| Junction creation fails | No write permission to Python dir | Run as Administrator once |
| COM object errors after concurrent calls | Thread safety violation | Serialize all calls |

## Cross-References

- `ras_commander/terrain/RasTerrainMod.py` — full implementation
- `ras_commander/terrain/RasTerrain.py` — terrain layer operations (no modifications)
- `.claude/MANIFEST.md` — Terrain & Land Cover domain
- `examples/930_terrain_modification_analysis.ipynb` — worked example with no-net-fill
