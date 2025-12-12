# Precipitation Data Integration - Research Summary

## Overview

Gridded precipitation data integration (AORC, MRMS, NWS QPF) for HEC-RAS rain-on-grid modeling.

## Implementation Status: AORC Complete

AORC (Analysis of Record for Calibration) data retrieval is **fully implemented** and tested.

### Implemented Components

| Component | Location | Status |
|-----------|----------|--------|
| `HdfProject.get_project_extent()` | `ras_commander/hdf/HdfProject.py` | Complete |
| `HdfProject.get_project_bounds_latlon()` | `ras_commander/hdf/HdfProject.py` | Complete |
| `PrecipAorc.download()` | `ras_commander/precip/PrecipAorc.py` | Complete |
| `PrecipAorc.check_availability()` | `ras_commander/precip/PrecipAorc.py` | Complete |
| `PrecipAorc.get_info()` | `ras_commander/precip/PrecipAorc.py` | Complete |

### Test Results (2024-12-05)

- Successfully extracted project bounds from BaldEagleCrkMulti2D
- Downloaded 72 hourly timesteps of AORC precipitation (Sep 15-17, 2018)
- Output: 211.8 KB NetCDF file with proper coordinates and metadata

## Files in This Folder

| File | Description |
|------|-------------|
| `README.md` | This summary document |
| `RESEARCH_NOTES.md` | Comprehensive research findings on data sources and formats |
| `IMPLEMENTATION_PLAN.md` | Detailed implementation plan for new `precip` submodule |
| `LOCAL_REPOS.md` | Local repository reference with paths and update status |
| `test_project_extent.py` | Test script for HdfProject extent extraction |
| `test_aorc_download.py` | Test script for PrecipAorc download |
| `test_full_workflow.py` | End-to-end workflow test |

---

## Key Decisions

1. **Output Format:** NetCDF (direct HEC-RAS GDAL import, no DSS conversion)
2. **Default Buffer:** 50% for precipitation data extent
3. **Terrain:** Separate module (see `feature_dev_notes/terrain/`)

---

## Data Sources

| Source | Type | Resolution | Coverage | Best For |
|--------|------|------------|----------|----------|
| **AORC** | Historical | ~800m hourly | CONUS 1979+ | Calibration, hindcast |
| **MRMS** | Real-time/Historical | 1km hourly | CONUS | Recent events |
| **NWS QPF** | Forecast | ~5km 6-hourly | CONUS | Flood forecasting |

---

## AORC Dataset Details

- **AWS Bucket:** `noaa-nws-aorc-v1-1-1km`
- **Region:** us-east-1
- **Format:** Zarr (cloud-optimized)
- **Resolution:** ~800m hourly
- **Coverage:** CONUS 1979-present, Alaska 1981-present

### Precipitation Variable
- `APCP_surface` - Hourly precipitation (kg/m²)

### Access Pattern
```python
import xarray as xr
import s3fs

s3 = s3fs.S3FileSystem(anon=True)
store = s3fs.S3Map(root='s3://noaa-nws-aorc-v1-1-1km/2020.zarr', s3=s3)
ds = xr.open_zarr(store)

# Subset by bounds (latitude is ascending in AORC)
precip = ds['APCP_surface'].sel(
    latitude=slice(lat_min, lat_max),
    longitude=slice(lon_min, lon_max),
    time=slice(start_date, end_date)  # Use date strings YYYY-MM-DD
).load()

# Export to NetCDF
precip.to_netcdf('precipitation.nc')
```

### Using ras-commander
```python
from ras_commander import HdfProject
from ras_commander.precip import PrecipAorc

# Extract project bounds from HEC-RAS HDF
bounds = HdfProject.get_project_bounds_latlon(
    'project.g01.hdf',
    buffer_percent=50.0  # Capture upstream areas
)

# Download AORC precipitation
PrecipAorc.download(
    bounds=bounds,
    start_time='2018-09-15',
    end_time='2018-09-17',
    output_path='Precipitation/aorc.nc'
)
```

---

## Implementation Steps

1. **HdfProject.get_project_extent()** - Extract project bounds from HDF
2. **PrecipAorc.download()** - Download AORC data for extent
3. **RasUnsteady.set_gridded_precipitation()** - Configure .u file

---

## Dependencies

```toml
[project.optional-dependencies]
precip = [
    "xarray>=2023.0.0",
    "zarr>=2.14.0",
    "s3fs>=2023.0.0",
    "rioxarray>=0.14.0",
    "netCDF4>=1.6.0",
]
```

---

## Key Resources

### AORC
- AWS Registry: https://registry.opendata.aws/noaa-nws-aorc/
- NOAA-OWP Notebooks: https://github.com/NOAA-OWP/AORC-jupyter-notebooks
- CUAHSI Notebooks: https://github.com/CUAHSI/notebooks

### MRMS
- AWS: https://registry.opendata.aws/noaa-mrms-pds/
- HEC Scripts: https://github.com/HydrologicEngineeringCenter/data-retrieval-scripts
- Cookbook: https://projectpythia.org/mrms-cookbook/

### HEC-RAS
- Global BC Docs: https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.3/boundary-and-initial-conditions-for-2d-flow-areas/global-boundary-conditions
