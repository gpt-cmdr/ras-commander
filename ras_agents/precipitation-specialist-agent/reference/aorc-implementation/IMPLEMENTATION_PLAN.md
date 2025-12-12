# Precipitation Submodule Implementation Plan

## Key Decisions

- **Output Format:** NetCDF only (no DSS conversion)
- **Default Buffer:** 50% for precipitation data extent
- **Terrain:** Separate module (see `feature_dev_notes/terrain/`)

## Module Structure

```
ras_commander/
├── precip/                          # New submodule
│   ├── __init__.py                  # Exports: RasPrecip, PrecipAorc, PrecipMrms, PrecipQpf
│   ├── AGENTS.md                    # AI guidance for precip module
│   ├── RasPrecip.py                 # Main interface class
│   ├── PrecipAorc.py                # AORC data access (PRIORITY)
│   ├── PrecipMrms.py                # MRMS data access
│   ├── PrecipQpf.py                 # NWS QPF forecast data
│   └── PrecipUtils.py               # Shared utilities (coordinate transforms, time handling)
│
└── hdf/
    └── HdfProject.py                # NEW: Project extent extraction
```

---

## Phase 1: Project Extent Extraction (HDF Module)

### 1.1 New File: `ras_commander/hdf/HdfProject.py`

```python
"""
HdfProject - Project-level geometry extraction from HEC-RAS HDF files.

Provides methods to extract combined project extents from all model elements
(1D rivers, cross sections, 2D areas, storage areas) for use in data downloads.
"""

class HdfProject:
    """Extract project-level geometry and metadata from HEC-RAS HDF files."""

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_project_extent(
        hdf_path: Path,
        include_1d: bool = True,
        include_2d: bool = True,
        include_storage: bool = True,
        buffer_percent: float = 50.0,
        buffer_x_percent: float = None,
        buffer_y_percent: float = None
    ) -> Tuple[GeoDataFrame, Tuple[float, float, float, float]]:
        """
        Calculate combined project extent from all model elements.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS geometry HDF file
        include_1d : bool
            Include 1D river centerlines and cross sections
        include_2d : bool
            Include 2D flow area perimeters
        include_storage : bool
            Include storage area extents
        buffer_percent : float
            Default buffer percentage applied to all directions
        buffer_x_percent : float, optional
            Override buffer for X axis
        buffer_y_percent : float, optional
            Override buffer for Y axis

        Returns
        -------
        Tuple[GeoDataFrame, Tuple]
            - GeoDataFrame with combined geometry and CRS
            - Buffered bounding box (minx, miny, maxx, maxy)
        """
        pass

    @staticmethod
    def get_project_bounds_latlon(
        hdf_path: Path,
        buffer_percent: float = 50.0
    ) -> Tuple[float, float, float, float]:
        """
        Get project bounds in WGS84 lat/lon coordinates.

        Returns
        -------
        Tuple[float, float, float, float]
            (west, south, east, north) in decimal degrees
        """
        pass

    @staticmethod
    def get_project_crs(hdf_path: Path) -> str:
        """Get the coordinate reference system from HDF file."""
        pass
```

### 1.2 Update `ras_commander/hdf/__init__.py`

Add export for `HdfProject`.

---

## Phase 2: Precipitation Submodule Core

### 2.1 File: `ras_commander/precip/__init__.py`

```python
"""
Precipitation data access for HEC-RAS rain-on-grid modeling.

This submodule provides tools to download and prepare gridded precipitation data
from various sources for use in HEC-RAS 2D models:

- AORC (Analysis of Record for Calibration) - Historical reanalysis
- MRMS (Multi-Radar Multi-Sensor) - Real-time and historical radar
- QPF (Quantitative Precipitation Forecast) - NWS forecasts

Example:
    >>> from ras_commander.precip import RasPrecip
    >>> from ras_commander import init_ras_project
    >>>
    >>> init_ras_project("/path/to/project", "6.5")
    >>> RasPrecip.download_aorc(
    ...     start_time="2018-09-01",
    ...     end_time="2018-09-03",
    ...     output_path="Precipitation/aorc_precip.nc"
    ... )
"""

from .RasPrecip import RasPrecip
from .PrecipAorc import PrecipAorc
from .PrecipMrms import PrecipMrms
from .PrecipQpf import PrecipQpf

__all__ = ['RasPrecip', 'PrecipAorc', 'PrecipMrms', 'PrecipQpf']
```

### 2.2 File: `ras_commander/precip/RasPrecip.py`

```python
"""
RasPrecip - Main interface for precipitation data operations.

Provides high-level methods for downloading and configuring gridded
precipitation data for HEC-RAS models.
"""

class RasPrecip:
    """
    Main precipitation data interface for HEC-RAS models.

    All methods are static and designed to work with the global `ras` object
    or accept a `ras_object` parameter for multi-project workflows.
    """

    @staticmethod
    @log_call
    def download_aorc(
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        output_path: Union[str, Path] = None,
        output_format: str = "netcdf",  # "netcdf", "dss"
        ras_object = None
    ) -> Path:
        """
        Download AORC precipitation data for the project extent.

        Parameters
        ----------
        start_time : str or datetime
            Start of time window (e.g., "2018-09-01" or "2018-09-01 00:00")
        end_time : str or datetime
            End of time window
        output_path : str or Path, optional
            Output file path. If None, creates in project Precipitation folder
        output_format : str
            Output format: "netcdf" or "dss"
        ras_object : RasPrj, optional
            RAS project object. Uses global `ras` if None.

        Returns
        -------
        Path
            Path to downloaded precipitation file

        Example
        -------
        >>> RasPrecip.download_aorc(
        ...     start_time="2018-09-01",
        ...     end_time="2018-09-03",
        ...     output_format="netcdf"
        ... )
        """
        pass

    @staticmethod
    @log_call
    def download_mrms(
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        product: str = "GaugeCorr_QPE_01H",
        output_path: Union[str, Path] = None,
        ras_object = None
    ) -> Path:
        """
        Download MRMS precipitation data for the project extent.

        Parameters
        ----------
        product : str
            MRMS product name. Options:
            - "GaugeCorr_QPE_01H" - Gauge-corrected hourly QPE (default)
            - "RadarOnly_QPE_01H" - Radar-only hourly QPE
            - "MultiSensor_QPE_01H" - Multi-sensor hourly QPE
        """
        pass

    @staticmethod
    @log_call
    def download_qpf(
        forecast_days: int = 3,
        output_path: Union[str, Path] = None,
        ras_object = None
    ) -> Path:
        """
        Download NWS QPF forecast data for the project extent.

        Parameters
        ----------
        forecast_days : int
            Number of forecast days (1-7)
        """
        pass

    @staticmethod
    @log_call
    def configure_unsteady_file(
        unsteady_number: str,
        precip_file: Union[str, Path],
        source_type: str = "auto",  # "dss", "netcdf", "grib"
        dss_pathname: str = None,
        ras_object = None
    ) -> bool:
        """
        Configure an unsteady flow file to use gridded precipitation.

        Parameters
        ----------
        unsteady_number : str
            Unsteady flow file number (e.g., "03")
        precip_file : str or Path
            Path to precipitation file (relative to project folder)
        source_type : str
            Source type: "auto", "dss", "netcdf", or "grib"
        dss_pathname : str, optional
            DSS pathname for DSS files

        Returns
        -------
        bool
            True if configuration successful
        """
        pass

    @staticmethod
    def get_available_sources() -> dict:
        """Return information about available precipitation sources."""
        return {
            "aorc": {
                "name": "Analysis of Record for Calibration",
                "coverage": "CONUS (1979-present), Alaska (1981-present)",
                "resolution": "~800m hourly",
                "format": "Zarr on AWS"
            },
            "mrms": {
                "name": "Multi-Radar Multi-Sensor",
                "coverage": "CONUS, Alaska, Hawaii",
                "resolution": "1km sub-hourly to hourly",
                "format": "GRIB2"
            },
            "qpf": {
                "name": "NWS Quantitative Precipitation Forecast",
                "coverage": "CONUS",
                "resolution": "~5km 6-hourly",
                "format": "GRIB2"
            }
        }
```

### 2.3 File: `ras_commander/precip/PrecipAorc.py`

```python
"""
PrecipAorc - AORC data access from AWS.

Provides access to NOAA's Analysis of Record for Calibration dataset
stored in Zarr format on AWS S3.
"""

class PrecipAorc:
    """
    AORC precipitation data access.

    The AORC dataset provides hourly precipitation data at ~800m resolution
    from 1979-present for CONUS and 1981-present for Alaska.
    """

    # AWS bucket configuration
    BUCKET = "noaa-nws-aorc-v1-1-1km"
    REGION = "us-east-1"

    # Variable names
    PRECIP_VAR = "APCP_surface"

    @staticmethod
    @log_call
    def download(
        bounds: Tuple[float, float, float, float],  # (west, south, east, north) in WGS84
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        output_path: Path,
        output_format: str = "netcdf"
    ) -> Path:
        """
        Download AORC data for specified bounds and time range.

        Parameters
        ----------
        bounds : Tuple[float, float, float, float]
            Bounding box in WGS84 (west, south, east, north)
        start_time : str or datetime
            Start time
        end_time : str or datetime
            End time
        output_path : Path
            Output file path
        output_format : str
            Output format: "netcdf" or "zarr"

        Returns
        -------
        Path
            Path to output file
        """
        import xarray as xr
        import s3fs

        # Parse times
        start_dt = pd.to_datetime(start_time)
        end_dt = pd.to_datetime(end_time)

        # Extract lat/lon bounds
        west, south, east, north = bounds

        # Connect to S3
        s3 = s3fs.S3FileSystem(anon=True)

        # Build Zarr store paths for each year in range
        years = range(start_dt.year, end_dt.year + 1)
        datasets = []

        for year in years:
            store_path = f"{PrecipAorc.BUCKET}/zarr/{year}/"
            store = s3fs.S3Map(root=store_path, s3=s3)
            ds = xr.open_zarr(store)

            # Subset spatially and temporally
            ds_subset = ds[PrecipAorc.PRECIP_VAR].sel(
                latitude=slice(north, south),
                longitude=slice(west, east),
                time=slice(str(start_dt), str(end_dt))
            )
            datasets.append(ds_subset)

        # Combine and write
        combined = xr.concat(datasets, dim='time')

        if output_format == "netcdf":
            combined.to_netcdf(output_path)
        else:
            combined.to_zarr(output_path)

        return output_path

    @staticmethod
    def get_catalog(year: int) -> dict:
        """Get metadata about AORC data for a specific year."""
        pass

    @staticmethod
    def check_availability(
        bounds: Tuple[float, float, float, float],
        start_time: Union[str, datetime],
        end_time: Union[str, datetime]
    ) -> bool:
        """Check if data is available for the specified region and time."""
        pass
```

### 2.4 File: `ras_commander/precip/PrecipMrms.py`

```python
"""
PrecipMrms - MRMS data access from AWS and Iowa State archive.
"""

class PrecipMrms:
    """
    MRMS precipitation data access.

    Provides access to Multi-Radar Multi-Sensor QPE products from
    AWS and historical data from Iowa State archive.
    """

    # AWS bucket
    AWS_BUCKET = "noaa-mrms-pds"

    # Iowa State archive
    IOWA_STATE_URL = "https://mtarchive.geol.iastate.edu"

    # Available products
    PRODUCTS = {
        "GaugeCorr_QPE_01H": "Gauge-corrected 1-hour QPE",
        "RadarOnly_QPE_01H": "Radar-only 1-hour QPE",
        "MultiSensor_QPE_01H": "Multi-sensor 1-hour QPE",
    }

    @staticmethod
    @log_call
    def download(
        bounds: Tuple[float, float, float, float],
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        product: str = "GaugeCorr_QPE_01H",
        output_path: Path = None,
        output_format: str = "grib"  # "grib" or "netcdf"
    ) -> Path:
        """
        Download MRMS data for specified bounds and time range.

        For historical data, uses Iowa State archive.
        For recent data (< 48 hours), uses AWS real-time feed.
        """
        pass

    @staticmethod
    def list_products() -> dict:
        """List available MRMS products."""
        return PrecipMrms.PRODUCTS
```

### 2.5 File: `ras_commander/precip/PrecipQpf.py`

```python
"""
PrecipQpf - NWS Quantitative Precipitation Forecast access.
"""

class PrecipQpf:
    """
    NWS QPF forecast data access.

    Provides access to Weather Prediction Center quantitative
    precipitation forecasts.
    """

    # WPC QPF base URL
    BASE_URL = "https://tgftp.nws.noaa.gov/SL.us008001/ST.opnl/DF.gr2/DC.ndfd/"

    @staticmethod
    @log_call
    def download(
        bounds: Tuple[float, float, float, float],
        forecast_days: int = 3,
        output_path: Path = None
    ) -> Path:
        """
        Download QPF forecast data for specified region.

        Parameters
        ----------
        bounds : Tuple
            Bounding box in WGS84
        forecast_days : int
            Number of forecast days (1-7)
        output_path : Path, optional
            Output file path

        Returns
        -------
        Path
            Path to downloaded GRIB file
        """
        pass
```

---

## Phase 3: Unsteady Flow File Configuration

### 3.1 Update `ras_commander/RasUnsteady.py`

Add methods for meteorological boundary condition configuration:

```python
@staticmethod
@log_call
def set_gridded_precipitation(
    unsteady_number: str,
    source_type: str,  # "DSS" or "GDAL"
    file_path: str,
    dss_pathname: str = None,
    projection_override: str = None,
    units_override: str = None,
    ratio: float = None,
    ras_object = None
) -> bool:
    """
    Configure gridded precipitation in an unsteady flow file.

    Modifies the Met BC=Precipitation lines in the .u## file.
    """
    pass

@staticmethod
def get_precipitation_config(
    unsteady_number: str,
    ras_object = None
) -> dict:
    """
    Get current precipitation configuration from unsteady file.

    Returns
    -------
    dict
        Configuration including mode, source, file path, pathname, etc.
    """
    pass
```

---

## Phase 4: Optional DSS Output Support

### 4.1 Extend `ras_commander/RasDss.py`

Add methods for writing gridded precipitation to DSS:

```python
@staticmethod
@log_call
def write_gridded_precip(
    dss_file: Union[str, Path],
    precip_data: xr.DataArray,
    pathname_template: str = "/SHG/{LOCATION}/PRECIP/{START}/{END}/IMPORTED/",
    units: str = "MM"
) -> bool:
    """
    Write gridded precipitation data to DSS file.

    Uses HEC Monolith libraries via pyjnius (same approach as existing DSS support).

    Parameters
    ----------
    dss_file : str or Path
        Output DSS file path
    precip_data : xr.DataArray
        Precipitation data with time, latitude, longitude dimensions
    pathname_template : str
        DSS pathname template with placeholders
    units : str
        Precipitation units (default "MM")
    """
    pass
```

---

## Phase 5: Testing and Examples

### 5.1 New Example Notebook

`examples/24_gridded_precipitation.ipynb`

```markdown
# Gridded Precipitation for Rain-on-Grid Modeling

This notebook demonstrates:
1. Extracting project extent from HEC-RAS model
2. Downloading AORC historical precipitation
3. Downloading MRMS real-time precipitation
4. Downloading NWS QPF forecasts
5. Configuring HEC-RAS unsteady flow files for gridded precipitation
```

### 5.2 Test Script

`tests/test_precip_download.py`

```python
"""Test precipitation download functionality."""

def test_project_extent_extraction():
    """Test HdfProject.get_project_extent()."""
    pass

def test_aorc_download():
    """Test AORC data download."""
    pass

def test_mrms_download():
    """Test MRMS data download."""
    pass

def test_unsteady_file_configuration():
    """Test RasUnsteady.set_gridded_precipitation()."""
    pass
```

---

## Dependencies to Add

### 6.1 Core Requirements (pyproject.toml)

```toml
[project.optional-dependencies]
precip = [
    "xarray>=2023.0.0",
    "zarr>=2.14.0",
    "s3fs>=2023.0.0",
    "rioxarray>=0.14.0",
    "netCDF4>=1.6.0",
]

terrain = [
    "py3dep>=0.16.0",
]

all = [
    "ras-commander[precip,terrain,remote-all]",
]
```

### 6.2 Lazy Loading

All imports in the precip submodule should use lazy loading pattern:

```python
def _get_xarray():
    try:
        import xarray
        return xarray
    except ImportError:
        raise ImportError(
            "xarray is required for precipitation data access. "
            "Install with: pip install ras-commander[precip]"
        )
```

---

## Implementation Order

1. **Week 1:** HdfProject.get_project_extent()
   - Extract 2D areas, cross sections, river lines, storage areas
   - Calculate buffered bounds
   - Convert to lat/lon

2. **Week 2:** PrecipAorc.download()
   - AWS S3 access with s3fs
   - Zarr data loading with xarray
   - Spatial/temporal subsetting
   - NetCDF output

3. **Week 3:** PrecipMrms.download()
   - Iowa State archive access
   - AWS real-time feed
   - GRIB2 handling

4. **Week 4:** RasUnsteady integration
   - .u## file parsing for Met BC
   - Configuration writing
   - Testing with HEC-RAS

5. **Week 5:** Example notebook and testing
   - Comprehensive example workflow
   - Test with real project data

---

## Questions for User

1. **NetCDF vs DSS preference:** Should we prioritize NetCDF (simpler) or DSS (native HEC format)?
   - NetCDF: Works directly with HEC-RAS 6.x via GDAL import
   - DSS: Requires additional conversion but is native format

2. **Terrain integration:** Should py3dep/3DEP LiDAR download be part of this phase or a separate terrain module?

3. **Test project:** Which HEC-RAS project should we use for testing the full workflow?
