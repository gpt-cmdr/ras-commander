# Meteorological Data tab `.u##` fixtures

These fixtures were collected for CLB-673 with HEC-RAS 6.6.

- `precip_00_disabled_official_davis.u01`: official Davis example baseline.
- `precip_01_enabled_none_gui_davis.u01`: GUI-saved, top-level Precip/ET enabled, precipitation `Mode=None`.
- `precip_02_constant_gui_davis.u01`: GUI-saved, precipitation `Mode=Constant`.
- `precip_03_point_thiessen_gui_davis.u01`: GUI-saved, precipitation `Mode=Point`, `Point Interpolation=Thiessen Polygon`.
- `precip_04_gridded_dss_gui_davis.u01`: GUI-saved, precipitation `Mode=Gridded`, source `DSS`, no DSS file selected.
- `precip_05_gridded_gdal_gui_davis.u01`: GUI-saved, precipitation `Mode=Gridded`, source `GDAL Raster File(s)`, no raster imported.
- `precip_06_gridded_dss_official_baldeagle.u03`: official Bald Eagle example with real gridded-DSS precipitation filename/path.

See `research/met_data_tab_inventory.md` for the annotated inventory and HDF findings.

Review addendum: the fixtures were not regenerated for the ras-commander coverage cross-reference. That addendum classifies existing Atlas 14, AORC, MRMS/Vortex, GDAL/NetCDF, and gridded-DSS support against these same GUI-saved `.u##` modes.
