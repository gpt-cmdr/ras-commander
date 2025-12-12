# Precipitation Data Integration for HEC-RAS - Research Notes

## Overview

This document compiles research on integrating gridded precipitation data (AORC, MRMS, NWS QPF)
and LiDAR terrain data (USGS 3DEP) into ras-commander for HEC-RAS rain-on-grid modeling.

---

## 1. HEC-RAS Gridded Precipitation File Formats

### 1.1 Supported Sources (from .u## file analysis)

HEC-RAS supports two gridded precipitation sources:
1. **HEC-DSS** - Standard HEC format
2. **GDAL Raster Files** - NetCDF or GRIB formats

### 1.2 DSS Format Configuration (.u## file)

From `BaldEagleDamBrk.u03`:
```
Met BC=Precipitation|Mode=Gridded
Met BC=Precipitation|Gridded Source=DSS
Met BC=Precipitation|Gridded DSS Filename=.\Precipitation\precip.2018.09.dss
Met BC=Precipitation|Gridded DSS Pathname=/SHG/MARFC/PRECIP/01SEP2018:0200/01SEP2018:0300/NEXRAD/
```

**DSS Pathname Structure:**
- `/SHG/` - Standard Hydrologic Grid (projection)
- `/MARFC/` - Mid-Atlantic River Forecast Center (location)
- `/PRECIP/` - Data type (parameter)
- `/01SEP2018:0200/01SEP2018:0300/` - Time range (D-part)
- `/NEXRAD/` - Data source (F-part)

### 1.3 GDAL Raster Configuration

HEC-RAS supports:
- **Single Raster File** - One file containing all timesteps
- **Multiple Raster Files** - Multiple files for the event window

**Supported formats:** NetCDF (.nc), GRIB (.grib2)

**Override options:**
- `Projection Override` - When metadata cannot be interpreted
- `Units Override` - When automatic detection fails
- `Ratio` - Multiplier for all precipitation values

### 1.4 Import Process

Using GDAL Raster option:
1. Data is imported to HDF file at selection time
2. No precipitation import time added during compute
3. Data integrated into HEC-RAS Mapper Event Conditions layer
4. Supports animation as incremental or accumulated precipitation

---

## 2. AORC (Analysis of Record for Calibration)

### 2.1 Dataset Overview

- **Coverage:** CONUS (1979-present), Alaska (1981-present)
- **Spatial Resolution:** 30 arc seconds (~800 meters)
- **Temporal Resolution:** Hourly
- **Grid:** 4,201 lat × 8,401 lon values
- **Format:** Zarr (converted from NetCDF for 500x faster access)

### 2.2 AWS Access

- **Bucket:** `noaa-nws-aorc-v1-1-1km`
- **Region:** us-east-1
- **Access:** Public (--no-sign-request)

### 2.3 Variables

| Variable | Description | Units |
|----------|-------------|-------|
| APCP_surface | Hourly precipitation | kg/m² |
| TMP_2maboveground | Air temperature at 2m | K |
| SPFH_2maboveground | Specific humidity at 2m | g/g |
| DLWRF_surface | Longwave radiation | W/m² |
| DSWRF_surface | Shortwave radiation | W/m² |
| PRES_surface | Surface air pressure | Pa |
| UGRD_10maboveground | West-east wind | m/s |
| VGRD_10maboveground | South-north wind | m/s |

### 2.4 Python Access

```python
import xarray as xr
import s3fs

# Open Zarr store from AWS
s3 = s3fs.S3FileSystem(anon=True)
store = s3fs.S3Map(root='noaa-nws-aorc-v1-1-1km/zarr/2020/', s3=s3)
ds = xr.open_zarr(store)

# Extract precipitation for bounding box
precip = ds['APCP_surface'].sel(
    latitude=slice(lat_max, lat_min),
    longitude=slice(lon_min, lon_max),
    time=slice(start_time, end_time)
)
```

### 2.5 Key Resources

- AWS Registry: https://registry.opendata.aws/noaa-nws-aorc/
- NOAA-OWP Notebooks: https://github.com/NOAA-OWP/AORC-jupyter-notebooks
- CUAHSI Notebooks: https://github.com/CUAHSI/notebooks
- HydroShare Resource: http://www.hydroshare.org/resource/72ea9726187e43d7b50a624f2acf591f

---

## 3. MRMS (Multi-Radar Multi-Sensor)

### 3.1 Dataset Overview

- **Spatial Resolution:** 1 km
- **Temporal Resolution:** Hourly (and sub-hourly products)
- **Coverage:** CONUS, Alaska, Hawaii
- **Format:** GRIB2 (compressed as .gz)
- **Data Sources:** Multiple radars + surface observations + NWP models

### 3.2 Data Sources

1. **AWS Open Data:** https://registry.opendata.aws/noaa-mrms-pds/
2. **Iowa State Archive:** https://mtarchive.geol.iastate.edu (historical)
3. **HEC Data Retrieval Scripts:** https://github.com/HydrologicEngineeringCenter/data-retrieval-scripts

### 3.3 HEC Download Script

Script: `retrieve_qpe_gagecorr_01h.py`

Configuration:
```python
# Line 7-8: Set start/end times
start_time = datetime(2018, 9, 1, 0, 0)
end_time = datetime(2018, 9, 2, 0, 0)

# Line 15: Output folder
output_folder = "C:/temp/mrms_data"
```

Execution:
```cmd
python retrieve_qpe_gagecorr_01h.py
```

Output: `.gz` files (one per hour) containing GRIB2 data

### 3.4 Python Access (AWS)

```python
import xarray as xr
import s3fs

s3 = s3fs.S3FileSystem(anon=True)
# Access MRMS data from AWS
files = s3.glob('s3://noaa-mrms-pds/CONUS/MergedBaseReflectivity/*')
```

### 3.5 Key Resources

- Project Pythia Cookbook: https://projectpythia.org/mrms-cookbook/
- HEC Download Tutorial: https://www.hec.usace.army.mil/confluence/hmsdocs/hmsguides/gridded-boundary-condition-data/downloading-multi-radar-multi-sensor-mrms-precipitation-data
- CUAHSI Notebook: https://www.hydroshare.org/resource/455294614cd34379a8e95593bd1e38ac/

---

## 4. NWS QPF (Quantitative Precipitation Forecast)

### 4.1 Data Products

- **WPC QPF:** 24-hour forecasts up to 7 days
- **NDFD QPF:** 6-hour periods (00, 06, 12, 18 UTC)
- **GFS:** Global model forecasts

### 4.2 Access Methods

1. **GRIB2 Direct Download:**
   ```
   https://tgftp.nws.noaa.gov/SL.us008001/ST.opnl/DF.gr2/DC.ndfd/
   ```

2. **NWS API (api.weather.gov):**
   ```python
   import requests

   url = f"https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast"
   headers = {"User-Agent": "your-app-name"}
   response = requests.get(url, headers=headers)
   ```

3. **WPC MapServer:**
   ```
   https://mapservices.weather.noaa.gov/vector/rest/services/precip/wpc_qpf/MapServer
   ```

4. **water.noaa.gov:**
   ```
   https://water.noaa.gov/resources/downloads/precip/YYYY/MM/DD/nws_precip_[XXXXX]_YYYYMMDD_conus.[nc,tif]
   ```

### 4.3 Key Resources

- WPC QPF: https://www.wpc.ncep.noaa.gov/qpf/navqpf.php
- NDFD Metadata: https://www.weather.gov/gis/NDFD_metadata.html
- Precipitation Data Access: https://water.noaa.gov/about/precipitation-data-access

---

## 5. HEC-Vortex for Format Conversion

### 5.1 Overview

HEC-Vortex converts various formats to HEC-DSS for use with HEC-HMS/HEC-RAS.

### 5.2 Supported Input Formats

- NetCDF (.nc)
- GRIB (.grib, .grib2)
- HDF (.hdf)
- ASC (ASCII raster)
- BIL (Band Interleaved by Line)
- HEC-DSS (.dss)

### 5.3 Capabilities

- Clip to geographic area
- Re-project to different coordinate systems
- Resample to different spatial resolutions
- Convert grid to point (basin-average)
- Export to GeoTIFF or ASC

### 5.4 Tested Data Sources

- NOAA MRMS, RTMA, HRRR, GFS, CPC, CMORPH
- NASA GPM, NLDAS
- PRISM, DayMet

### 5.5 Scripting

Uses Jython scripts for batch processing (Java-based, not Python).

### 5.6 Key Resources

- GitHub: https://github.com/HydrologicEngineeringCenter/Vortex
- Documentation: https://www.hec.usace.army.mil/confluence/hecnews/spring-2022/hec-vortex-a-collection-of-lightweight-data-processing-utilities-targeted-for-hec-applications

---

## 6. Project Extent Extraction

### 6.1 Existing ras-commander Methods

| Class | Method | Returns |
|-------|--------|---------|
| HdfMesh | get_mesh_areas() | 2D flow area perimeter polygons (GeoDataFrame) |
| HdfXsec | get_cross_sections() | Cross section lines (GeoDataFrame) |
| HdfXsec | get_river_centerlines() | River centerlines (GeoDataFrame) |
| GeomStorage | get_storage_areas() | Storage area metadata (DataFrame) |
| RasGeometry | get_storage_areas() | Storage area polygons and metadata |

### 6.2 Proposed New Method: HdfProject.get_project_extent()

Location: `ras_commander/hdf/HdfProject.py` (new file)

```python
@staticmethod
def get_project_extent(
    hdf_path: Path,
    include_1d: bool = True,
    include_2d: bool = True,
    include_storage: bool = True,
    buffer_percent: float = 15.0
) -> Tuple[GeoDataFrame, BoundingBox]:
    """
    Calculate combined project extent from all model elements.

    Returns:
        Tuple of (combined_geometry_gdf, buffered_bbox)
    """
```

### 6.3 Buffer Logic (default 50% for precipitation)

```python
def buffer_extent_by_axes_percentage(gdf, x_buffer_percent=10, y_buffer_percent=20):
    minx, miny, maxx, maxy = gdf.total_bounds
    width = maxx - minx
    height = maxy - miny

    x_buffer_factor = 1 + (x_buffer_percent / 100)
    y_buffer_factor = 1 + (y_buffer_percent / 100)

    new_width = width * x_buffer_factor
    new_height = height * y_buffer_factor

    width_expansion = (new_width - width) / 2
    height_expansion = (new_height - height) / 2

    return (
        minx - width_expansion,
        miny - height_expansion,
        maxx + width_expansion,
        maxy + height_expansion
    )
```

---

## 7. Dependencies

### 7.1 Required Packages

```
xarray          # For Zarr/NetCDF data access
zarr            # For Zarr format
s3fs            # For AWS S3 access
geopandas       # For spatial data
rioxarray       # For raster I/O with xarray
netCDF4         # For NetCDF output
```

---

## 8. Workflow Summary

### 8.1 For AORC Historical Data

1. Calculate project extent from HEC-RAS HDF
2. Convert to lat/lon bounds (WGS84)
3. Query AORC Zarr store on AWS with spatial/temporal subset
4. Download precipitation data as xarray Dataset
5. Option A: Convert to NetCDF → Import directly in HEC-RAS
6. Option B: Convert to DSS using pyjnius → Reference in .u## file

### 8.2 For MRMS Real-Time/Historical Data

1. Calculate project extent from HEC-RAS HDF
2. Download GRIB2 files using HEC scripts or AWS
3. Option A: Import GRIB2 directly in HEC-RAS
4. Option B: Convert to DSS using HEC-Vortex

### 8.3 For NWS QPF Forecasts

1. Calculate project extent
2. Download GRIB2 from NWS servers
3. Import directly in HEC-RAS or convert via Vortex

---

## 9. Next Steps

1. Create `HdfProject.get_project_extent()` method
2. Implement AORC download module using xarray/zarr
3. Implement MRMS download module using AWS/HEC scripts
4. Test NetCDF/GRIB import in HEC-RAS
5. Optionally implement DSS conversion using pyjnius
6. Create example notebooks demonstrating workflows
