# CLB-258 Creating a RAS Terrain Gap Analysis

Issue: CLB-258
Reviewed: 2026-05-01
Official tutorial: https://www.hec.usace.army.mil/confluence/rasdocs/hgt/latest/tutorials/terrain/creating-a-ras-terrain

## Scope

Reviewed the official HEC-RAS "Creating a RAS Terrain" tutorial against the
current ras-commander API surface and updated
`examples/920_terrain_creation.ipynb` to map the tutorial workflow to available
Python APIs.

## Tutorial Operation Mapping

| Tutorial operation | Current status | ras-commander coverage |
| --- | --- | --- |
| Set project projection from `projection.prj` | Partial | `RasMap.add_terrain_layer(..., projection_prj=...)` can update the `.rasmap` projection reference while registering a terrain. `RasPrj.refresh_project_crs()` can resolve project CRS from geometry HDF, plan HDF, rasmap projection path, terrain HDF, or terrain raster. A standalone `set_project_projection()` API is tracked by CLB-270. |
| Create terrain from `base.tif` | Covered | `RasTerrain.create_terrain_hdf()` creates HEC-RAS terrain HDFs from GeoTIFF/FLT rasters through `RasProcess.exe CreateTerrain`. |
| Multi-source terrain merge and priority ordering | Covered | `RasTerrain.create_terrain_hdf()` accepts multiple rasters and documents that the first raster has highest overlap priority. `RasTerrain.create_terrain_from_rasters()` is the convenience wrapper with automatic `Projection.prj` generation. |
| Query and download USGS terrain | Partial | `Usgs3depAws.find_tiles_for_bbox()`, `list_projects_for_bbox()`, `download_tiles()`, and `create_vrt()` cover USGS 3DEP discovery, 1m AWS downloads, and VRT mosaics. Remaining gap: full RAS Mapper product type/year filtering and non-1m download parity is tracked by CLB-271. |
| Merge downloaded USGS tiles into a single terrain raster | Covered | `Usgs3depAws.create_vrt()` plus `RasTerrain.vrt_to_tiff()` creates a single GeoTIFF mosaic using HEC-RAS bundled GDAL tools. |
| Export XS channel bathymetry as GeoTIFF | Missing, linked | This is the same channel-raster export gap documented in CLB-253. |
| Terrain visualization settings | Missing | `RasMap.set_terrain_layer_visibility()` can toggle layer visibility, but hillshade, contour, and stitch TIN edge display settings are not exposed. Tracked by CLB-272. |

## Notebook Update

Updated `examples/920_terrain_creation.ipynb` to:

- Reference the official USACE HEC-RAS tutorial URL.
- Add an explicit API coverage table and current gap notes.
- Keep USGS downloads, terrain HDF creation, and multi-source terrain creation behind opt-in flags:
  - `RUN_USGS_DOWNLOAD`
  - `RUN_TERRAIN_CREATION`
  - `RUN_MULTI_SOURCE_TERRAIN_CREATION`
- Demonstrate single-source terrain creation with `RasTerrain.create_terrain_hdf()`.
- Demonstrate multi-source channel-over-base priority ordering when `Channel.tif` is available.
- Document the CLB-253 overlap for XS channel GeoTIFF export.
- Document the remaining terrain display setting gaps.

## Linear Follow-Ups

Created or linked follow-up work:

- CLB-253: linked for XS interpolation/channel bathymetry GeoTIFF export and stitch-edge overlap.
- CLB-270: standalone project projection assignment API.
- CLB-271: expanded USGS product filtering/download parity.
- CLB-272: terrain visualization settings for hillshade, contours, and stitch TIN edges.

## Validation Commands

Use the shared `symphony-dev` environment with `PYTHONPATH` set to the active
workspace:

```powershell
$env:PYTHONPATH = (Get-Location).Path
C:\Users\billk_clb\anaconda3\envs\symphony-dev\python.exe scripts\notebooks\audit_ipynb.py examples\920_terrain_creation.ipynb --out-dir working\notebook_runs\CLB-258
C:\Users\billk_clb\anaconda3\envs\symphony-dev\python.exe -m pytest tests\test_terrain_tutorial_notebook.py tests\test_ras_terrain_create_hdf.py tests\test_usgs3dep_create_vrt.py
```
