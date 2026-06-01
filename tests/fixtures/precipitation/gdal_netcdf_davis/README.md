# Davis GDAL/NetCDF precipitation fixture

These fixtures support CLB-704 regression coverage for the HEC-RAS 6.6 Davis
example project's GDAL raster precipitation import path.

- `clb704_precip_5step.nc`: 5-step, 2-by-3 EPSG:5070 NetCDF precipitation
  input using the `APCP_surface` variable.
- `DavisStormSystem.gui_imported.u01`: GUI-style Davis unsteady file with
  Meteorological Data precipitation configured as `GDAL Raster File(s)`,
  `APCP_surface`, `Nearest`.
- `DavisStormSystem.gui_imported.p02.precipitation.hdf`: reduced reference HDF
  containing only the GUI-imported precipitation metadata and
  `Imported Raster Data` datasets.

The GUI import workflow recorded for this fixture was:

1. Open Davis in HEC-RAS 6.6.
2. Edit Unsteady Flow Data > Meteorological Data.
3. Import Raster Data for Precipitation from `clb704_precip_5step.nc`.
4. Accept the parsed 5 timesteps in the gridded meteorology import dialog.
5. Preprocess plan `p02` to propagate the precipitation payload into the plan
   temporary HDF, then retain only the relevant precipitation groups/datasets.
