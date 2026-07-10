"""
MRMS precipitation download and visualization helpers.

This module downloads NOAA Multi-Radar Multi-Sensor (MRMS) QPE GRIB2 files
from public archives and prepares them for HEC-RAS rain-on-grid workflows.
It follows the static-class pattern used by the other precipitation helpers in
ras-commander.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import gzip
from numbers import Integral
from pathlib import Path
import re
import shutil
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import quote
import xml.etree.ElementTree as ET

from ..LoggingConfig import get_logger, log_call

logger = get_logger(__name__)

Bounds = Tuple[float, float, float, float]

_TIMESTAMP_RE = re.compile(r"(\d{8})-(\d{6})")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{8}$")
_OSM_TILE_CACHE: Dict[Tuple[int, int, int], Any] = {}


def _check_http_dependencies() -> None:
    missing = []
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    if missing:
        raise ImportError(
            "Missing required packages for MRMS downloads: "
            f"{', '.join(missing)}. Install with: pip install {' '.join(missing)}"
        )


def _check_grib_dependencies() -> None:
    missing = []
    try:
        import xarray  # noqa: F401
    except ImportError:
        missing.append("xarray")
    try:
        import cfgrib  # noqa: F401
    except ImportError:
        missing.append("cfgrib")

    if missing:
        raise ImportError(
            "Missing packages for reading MRMS GRIB2 files: "
            f"{', '.join(missing)}. Install with: pip install {' '.join(missing)}"
        )


def _check_animation_dependencies() -> None:
    missing = []
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        missing.append("matplotlib")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")

    if missing:
        raise ImportError(
            "Missing packages for MRMS animation: "
            f"{', '.join(missing)}. Install with: pip install {' '.join(missing)}"
        )


class PrecipMrms:
    """
    MRMS QPE download, direct processing, and animation utilities.

    The default public product name is ``GaugeCorr_QPE_01H`` because that is
    the historical IEM/MTArchive name. For NOAA Open Data S3, ras-commander
    maps that name to the current
    ``MultiSensor_QPE_01H_Pass2_00.00`` archive prefix.
    """

    NOAA_S3_BASE_URL = "https://noaa-mrms-pds.s3.amazonaws.com"
    IOWA_CATALOG_BASE_URL = "https://mtarchive.geol.iastate.edu/thredds/catalog"
    IOWA_FILESERVER_BASE_URL = "https://mtarchive.geol.iastate.edu/thredds/fileServer"

    # MRMS CONUS grid bounds are approximate and used for validation only.
    CONUS_BOUNDS: Bounds = (-130.0, 20.0, -60.0, 55.0)

    PRODUCT_HOURS = (1, 3, 6, 12, 24, 48, 72)
    DEFAULT_PRODUCT = "GaugeCorr_QPE_01H"
    DEFAULT_S3_PASS = "Pass2"

    @staticmethod
    @log_call
    def catalog(
        bounds: Bounds,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        product: str = DEFAULT_PRODUCT,
        source: str = "auto",
        timeout: int = 60,
    ) -> "pd.DataFrame":
        """
        List MRMS QPE files available for a date range.

        Parameters
        ----------
        bounds
            Bounding box in WGS84 as ``(west, south, east, north)``. MRMS
            archives store full-domain CONUS grids, so bounds are validated and
            carried in metadata but do not spatially subset the catalog.
        start_date, end_date
            Start and end of the time window. Date-only strings include the
            whole UTC day.
        product
            MRMS product name. ``GaugeCorr_QPE_01H`` is the default and maps to
            NOAA S3 ``MultiSensor_QPE_01H_Pass2_00.00``.
        source
            ``"auto"``, ``"noaa_s3"``, or ``"iowa"``. Auto prefers NOAA S3 for
            supported dates and falls back to Iowa MTArchive.
        timeout
            HTTP timeout in seconds.

        Returns
        -------
        pandas.DataFrame
            Columns include ``valid_time``, ``source``, ``product``,
            ``archive_product``, ``url``, ``filename``, ``size_bytes``, and
            ``compressed``.
        """
        _check_http_dependencies()
        PrecipMrms._validate_bounds(bounds)

        start_ts = PrecipMrms._parse_timestamp(start_date, end_of_day=False)
        end_ts = PrecipMrms._parse_timestamp(end_date, end_of_day=True)
        if end_ts < start_ts:
            raise ValueError("end_date must be greater than or equal to start_date")

        source = source.lower().strip()
        if source not in {"auto", "noaa_s3", "s3", "iowa", "mtarchive"}:
            raise ValueError("source must be one of: auto, noaa_s3, iowa")

        frames = []
        if source in {"auto", "noaa_s3", "s3"}:
            try:
                s3_df = PrecipMrms._catalog_noaa_s3(
                    start_ts, end_ts, product, timeout=timeout
                )
                if not s3_df.empty:
                    frames.append(s3_df)
                    if source != "auto":
                        return PrecipMrms._filter_catalog(s3_df, start_ts, end_ts)
            except Exception as exc:
                if source != "auto":
                    raise
                logger.warning("NOAA MRMS S3 catalog lookup failed: %s", exc)

        if source in {"auto", "iowa", "mtarchive"}:
            try:
                iowa_df = PrecipMrms._catalog_iowa_mtarchive(
                    start_ts, end_ts, product, timeout=timeout
                )
                if not iowa_df.empty:
                    frames.append(iowa_df)
                    if source != "auto":
                        return PrecipMrms._filter_catalog(iowa_df, start_ts, end_ts)
            except Exception as exc:
                if source != "auto":
                    raise
                logger.warning("Iowa MTArchive MRMS catalog lookup failed: %s", exc)

        if not frames:
            return PrecipMrms._empty_catalog()

        import pandas as pd

        catalog_df = pd.concat(frames, ignore_index=True)
        catalog_df = PrecipMrms._filter_catalog(catalog_df, start_ts, end_ts)
        if source == "auto" and not catalog_df.empty:
            catalog_df = PrecipMrms._prefer_catalog_source(catalog_df)
        return catalog_df

    @staticmethod
    @log_call
    def download(
        bounds: Bounds,
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        output_dir: Union[str, Path],
        product: str = DEFAULT_PRODUCT,
        source: str = "auto",
        overwrite: bool = False,
        decompress: bool = True,
        timeout: int = 120,
    ) -> List[Path]:
        """
        Download MRMS QPE GRIB2 files for a time range.

        Files are downloaded as full-domain MRMS grids. If the archive object is
        gzip-compressed, the default behavior is to decompress it to ``.grib2``
        because cfgrib consumes the uncompressed GRIB2 file directly.
        """
        catalog_df = PrecipMrms.catalog(
            bounds=bounds,
            start_date=start_time,
            end_date=end_time,
            product=product,
            source=source,
            timeout=timeout,
        )
        if catalog_df.empty:
            raise FileNotFoundError(
                "No MRMS files found for "
                f"{start_time} to {end_time}, product={product}, source={source}"
            )

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        downloaded: List[Path] = []
        for row in catalog_df.itertuples(index=False):
            archive_name = str(row.filename)
            local_name = (
                archive_name[:-3]
                if decompress and archive_name.endswith(".gz")
                else archive_name
            )
            local_path = output_path / local_name

            if local_path.exists() and not overwrite:
                downloaded.append(local_path)
                continue

            logger.debug("Downloading MRMS: %s", archive_name)
            PrecipMrms._download_one(
                url=str(row.url),
                local_path=local_path,
                decompress=decompress and archive_name.endswith(".gz"),
                timeout=timeout,
            )
            downloaded.append(local_path)

        return sorted(downloaded)

    @staticmethod
    @log_call
    def to_dss(
        grib2_files: Union[str, Path, Iterable[Union[str, Path]]],
        output_dss: Union[str, Path],
        clip_shp: Optional[Union[str, Path]] = None,
        product: str = DEFAULT_PRODUCT,
        variables: Optional[List[str]] = None,
        target_wkt: str = "SHG",
        target_cell_size: int = 2000,
        resampling_method: str = "Bilinear",
        dss_parts: Optional[Dict[str, str]] = None,
        vortex_path: Optional[Union[str, Path]] = None,
        jython_jar: Optional[Union[str, Path]] = None,
        timeout: int = 1800,
    ) -> Path:
        """
        Convert MRMS GRIB2 files to HEC-DSS using HEC-Vortex.

        This is the MRMS-specific wrapper around :meth:`VortexCli.import_gridded`.
        It supplies the Vortex variable name for the requested MRMS QPE product
        and preserves the standard SHG output defaults expected by HEC-RAS/HMS
        gridded precipitation workflows.
        """
        from .VortexCli import VortexCli

        grib_paths = PrecipMrms._normalize_paths(grib2_files)
        if not grib_paths:
            raise ValueError("grib2_files must contain at least one file")

        output_path = Path(output_dss)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        product_info = PrecipMrms._product_info(product)
        import_variables = variables or PrecipMrms._vortex_variables_for_files(
            product, grib_paths
        )
        write_parts = {
            "A": "SHG",
            "B": "MRMS_QPE",
            "F": product_info["canonical"].upper(),
        }
        if dss_parts:
            write_parts.update(dss_parts)

        logger.info(
            "Converting %d MRMS GRIB2 file(s) to DSS via HEC-Vortex: %s",
            len(grib_paths),
            output_path,
        )
        return VortexCli.import_gridded(
            input_files=grib_paths,
            output_dss=output_path,
            variables=import_variables,
            clip_shp=clip_shp,
            target_wkt=target_wkt,
            target_cell_size=target_cell_size,
            resampling_method=resampling_method,
            dss_parts=write_parts,
            vortex_path=vortex_path,
            jython_jar=jython_jar,
            timeout=timeout,
        )

    @staticmethod
    @log_call
    def load_grib2_stack(
        grib2_files: Union[str, Path, Iterable[Union[str, Path]]],
        bounds: Optional[Bounds] = None,
        variable: Optional[str] = None,
    ) -> "xr.DataArray":
        """
        Load MRMS GRIB2 files into a time-indexed xarray DataArray.

        Requires ``xarray`` and ``cfgrib``. The returned values are MRMS
        precipitation depths, normally in millimeters for QPE products.
        """
        _check_grib_dependencies()
        import pandas as pd
        import xarray as xr

        grib_paths = PrecipMrms._normalize_paths(grib2_files)
        if not grib_paths:
            raise ValueError("grib2_files must contain at least one file")

        frames = []
        times = []
        for grib_path in grib_paths:
            if not grib_path.exists():
                raise FileNotFoundError(f"GRIB2 file not found: {grib_path}")

            ds = xr.open_dataset(
                grib_path,
                engine="cfgrib",
                backend_kwargs={"indexpath": ""},
            )
            try:
                data_var = PrecipMrms._select_data_var(ds, variable)
                da = ds[data_var].squeeze(drop=True)
                da = PrecipMrms._drop_scalar_coords(da)
                if bounds is not None:
                    da = PrecipMrms._clip_dataarray(da, bounds)
                da = da.load()
            finally:
                ds.close()

            frame_time = PrecipMrms._frame_time_from_dataarray(da, grib_path)
            frames.append(da)
            times.append(frame_time)

        time_index = pd.DatetimeIndex(times, name="time")
        stack = xr.concat(frames, dim=time_index)
        stack.name = "mrms_precipitation"
        if str(stack.attrs.get("units", "")).lower() in {"", "unknown"}:
            stack.attrs["units"] = "mm"
        if str(stack.attrs.get("long_name", "")).lower() in {"", "unknown"}:
            stack.attrs["long_name"] = "MRMS QPE"
        return stack.sortby("time")

    @staticmethod
    @log_call
    def to_hyetograph(
        grib2_files: Any,
        bounds: Optional[Bounds] = None,
        variable: Optional[str] = None,
        depth_units: str = "in",
    ) -> "pd.DataFrame":
        """
        Convert MRMS QPE grids to a spatial-mean HEC-RAS hyetograph.

        ``grib2_files`` may be GRIB2 paths or an already loaded xarray/numpy
        grid stack. The output DataFrame matches
        ``RasUnsteady.set_precipitation_hyetograph()`` with ``hour``,
        ``incremental_depth``, and ``cumulative_depth`` columns.
        """
        import numpy as np
        import pandas as pd

        precip = PrecipMrms._prepare_precipitation_data(
            grib2_files,
            bounds=bounds,
            variable=variable,
        )
        precip_depth = PrecipMrms._convert_precip_units(precip, depth_units)
        values = np.asarray(precip_depth.values, dtype=float)
        if values.ndim != 3:
            raise ValueError(f"MRMS hyetograph expects 3-D time/y/x data, got {values.shape}")

        times = pd.to_datetime(precip_depth.coords["time"].values)
        incremental_depth = np.nanmean(values, axis=(1, 2))
        incremental_depth = np.nan_to_num(incremental_depth, nan=0.0)

        if len(times) > 1:
            interval_hours = float((times[1] - times[0]) / pd.Timedelta(hours=1))
        else:
            interval_hours = 1.0

        hours = (np.arange(len(incremental_depth), dtype=float) + 1.0) * interval_hours
        return pd.DataFrame(
            {
                "time": times,
                "hour": hours,
                "incremental_depth": incremental_depth,
                "cumulative_depth": np.cumsum(incremental_depth),
            }
        )

    @staticmethod
    @log_call
    def to_ras_netcdf(
        grib2_files: Any,
        output_netcdf: Union[str, Path],
        bounds: Optional[Bounds] = None,
        variable: Optional[str] = None,
        target_crs: Optional[str] = "EPSG:5070",
        resolution: Optional[float] = 2000.0,
        output_variable: str = "APCP_surface",
    ) -> Path:
        """
        Export MRMS QPE grids to a HEC-RAS GDAL-raster NetCDF input.

        The export path is intended for ``RasUnsteady.set_gridded_precipitation``.
        MRMS depths are written in millimeters. When ``target_crs`` is provided,
        rioxarray reprojects the WGS84 MRMS grid to that CRS before writing.
        """
        precip = PrecipMrms._prepare_precipitation_data(
            grib2_files,
            bounds=bounds,
            variable=variable,
        )
        precip_mm = PrecipMrms._convert_precip_units(precip, "mm")
        precip_mm = precip_mm.rename(output_variable)
        precip_mm.attrs.update(
            {
                "units": "mm",
                "long_name": "MRMS QPE precipitation depth",
                "source": "NOAA Multi-Radar Multi-Sensor QPE",
            }
        )

        if target_crs is not None:
            try:
                import rioxarray  # noqa: F401
            except ImportError as exc:
                raise ImportError(
                    "rioxarray is required to reproject MRMS grids for HEC-RAS. "
                    "Install with: pip install rioxarray"
                ) from exc

            lat_name = PrecipMrms._find_coord_name(precip_mm, ("latitude", "lat", "y"))
            lon_name = PrecipMrms._find_coord_name(precip_mm, ("longitude", "lon", "x"))
            if lat_name is None or lon_name is None:
                raise ValueError("MRMS data must have latitude/longitude coordinates for reprojection")

            precip_mm = precip_mm.rio.write_crs("EPSG:4326")
            precip_mm = precip_mm.rio.set_spatial_dims(x_dim=lon_name, y_dim=lat_name)
            precip_mm = precip_mm.rio.reproject(target_crs, resolution=resolution)

        output_path = Path(output_netcdf)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        precip_mm.to_dataset(name=output_variable).to_netcdf(output_path)
        return output_path

    @staticmethod
    @log_call
    def animate_precipitation(
        grib2_files: Any,
        output_mp4: Union[str, Path],
        bounds: Optional[Bounds] = None,
        boundary: Optional[Any] = None,
        mesh_boundary: Optional[Any] = None,
        pump_stations: Optional[Any] = None,
        variable: Optional[str] = None,
        units: str = "in/hr",
        terrain: Optional[Any] = None,
        add_basemap: bool = False,
        crs: Optional[Any] = None,
        raster_alpha: float = 0.85,
        fps: int = 2,
        dpi: int = 150,
        cmap: str = "turbo",
        title: str = "MRMS QPE",
    ) -> Path:
        """
        Generate an MP4 animation of MRMS precipitation over time.

        The animation includes a timestamp, colorbar, optional study area
        boundary overlay, and spatial-mean cumulative precipitation counter.
        ``grib2_files`` may be GRIB2 paths or an already loaded xarray/numpy
        grid stack, which keeps notebook smoke tests independent of cfgrib.
        """
        precip = PrecipMrms._prepare_precipitation_data(
            grib2_files,
            bounds=bounds,
            variable=variable,
        )
        return PrecipMrms._animate_grid_stack(
            data=precip,
            output_path=output_mp4,
            title=title,
            value_label=f"Precipitation ({units})",
            units=units,
            terrain=PrecipMrms._prepare_terrain_data(terrain) if terrain is not None else None,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
            crs=crs,
            raster_alpha=raster_alpha,
            cmap=cmap,
            fps=fps,
            dpi=dpi,
            cumulative=True,
        )

    @staticmethod
    @log_call
    def animate_flood_inundation(
        flood_data: Any,
        output_mp4: Union[str, Path],
        times: Optional[Iterable[Any]] = None,
        extent: Optional[Tuple[float, float, float, float]] = None,
        terrain: Optional[Any] = None,
        boundary: Optional[Any] = None,
        mesh_boundary: Optional[Any] = None,
        pump_stations: Optional[Any] = None,
        add_basemap: bool = False,
        crs: Optional[Any] = None,
        raster_alpha: float = 0.85,
        mesh_name: Optional[str] = None,
        variable: str = "Depth",
        max_frames: Optional[int] = 24,
        units: str = "ft",
        fps: int = 2,
        dpi: int = 150,
        cmap: str = "Blues",
        title: str = "Flood Inundation",
        cell_size: Optional[float] = None,
        resampling: str = "nearest",
    ) -> Path:
        """
        Generate an MP4 animation from a gridded flood-depth or WSE stack.

        ``flood_data`` may be a 3-D numpy array, an xarray DataArray, a HEC-RAS
        plan HDF path, one raster per timestep, or grouped terrain rasters per
        timestep. HDF inputs are rendered from 2D mesh cell centers.
        """
        if PrecipMrms._looks_like_raster_paths(flood_data):
            return PrecipMrms.animate_flood_inundation_from_rasters(
                flood_data,
                output_mp4=output_mp4,
                times=times,
                terrain=terrain,
                boundary=boundary,
                mesh_boundary=mesh_boundary,
                pump_stations=pump_stations,
                add_basemap=add_basemap,
                crs=crs,
                raster_alpha=raster_alpha,
                max_frames=max_frames,
                units=units,
                fps=fps,
                dpi=dpi,
                cmap=cmap,
                title=title,
                cell_size=cell_size,
                resampling=resampling,
            )

        if isinstance(flood_data, (str, Path)):
            return PrecipMrms.animate_flood_inundation_from_hdf(
                plan_hdf=flood_data,
                output_mp4=output_mp4,
                variable=variable,
                mesh_name=mesh_name,
                max_frames=max_frames,
                boundary=boundary,
                mesh_boundary=mesh_boundary,
                pump_stations=pump_stations,
                add_basemap=add_basemap,
                crs=crs,
                raster_alpha=raster_alpha,
                units=units,
                fps=fps,
                dpi=dpi,
                cmap=cmap,
                title=title,
            )

        data_array = PrecipMrms._coerce_grid_data(
            flood_data,
            times=times,
            extent=extent,
            name="flood_inundation",
            units=units,
        )
        return PrecipMrms._animate_grid_stack(
            data=data_array,
            output_path=output_mp4,
            title=title,
            value_label=f"Depth ({units})",
            units=units,
            terrain=PrecipMrms._prepare_terrain_data(terrain) if terrain is not None else None,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
            crs=crs,
            raster_alpha=raster_alpha,
            cmap=cmap,
            fps=fps,
            dpi=dpi,
            cumulative=False,
        )

    @staticmethod
    @log_call
    def animate_flood_inundation_from_hdf(
        plan_hdf: Union[str, Path],
        output_mp4: Union[str, Path],
        variable: str = "Depth",
        mesh_name: Optional[str] = None,
        max_frames: Optional[int] = 24,
        boundary: Optional[Any] = None,
        mesh_boundary: Optional[Any] = None,
        pump_stations: Optional[Any] = None,
        add_basemap: bool = False,
        crs: Optional[Any] = None,
        raster_alpha: float = 0.85,
        units: str = "ft",
        fps: int = 2,
        dpi: int = 150,
        cmap: str = "Blues",
        title: str = "HEC-RAS Flood Inundation",
    ) -> Path:
        """
        Generate an MP4 flood animation from HEC-RAS 2D plan HDF results.

        This method uses ras-commander HDF APIs and plots mesh cell centers as
        a point cloud, which is lightweight and works without RAS Mapper GUI
        automation.
        """
        _check_animation_dependencies()
        import matplotlib.pyplot as plt
        import pandas as pd

        flood = PrecipMrms._load_hdf_flood_points(
            plan_hdf=plan_hdf,
            variable=variable,
            mesh_name=mesh_name,
            max_frames=max_frames,
        )
        value_array = flood["values"]
        x = flood["x"]
        y = flood["y"]
        times = flood["times"]
        value_units = units or flood["units"]
        vmax = PrecipMrms._robust_vmax(value_array, 0.1)

        output_path = Path(output_mp4)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
        data_crs = crs or flood.get("crs")
        scat = ax.scatter(
            x,
            y,
            c=value_array[0],
            s=3,
            cmap=cmap,
            vmin=0,
            vmax=vmax,
            linewidths=0,
            alpha=raster_alpha,
            zorder=2,
        )
        cbar = fig.colorbar(scat, ax=ax, shrink=0.8)
        cbar.set_label(f"{variable} ({value_units})")
        label = ax.text(
            0.02,
            0.98,
            "",
            transform=ax.transAxes,
            va="top",
            ha="left",
            color="black",
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none"},
        )
        ax.set_title(title)
        ax.set_aspect("equal", adjustable="box")
        PrecipMrms._plot_spatial_overlays(
            ax,
            data_crs=data_crs,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
        )

        def update(frame_idx: int) -> list:
            scat.set_array(value_array[frame_idx])
            label.set_text(pd.Timestamp(times[frame_idx]).strftime("%Y-%m-%d %H:%M"))
            return [scat, label]

        PrecipMrms._save_animation(fig, update, value_array.shape[0], output_path, fps, dpi)
        return output_path

    @staticmethod
    @log_call
    def animate_flood_inundation_from_rasters(
        raster_files: Union[
            str,
            Path,
            Iterable[Union[str, Path, Iterable[Union[str, Path]]]],
        ],
        output_mp4: Union[str, Path],
        times: Optional[Iterable[Any]] = None,
        terrain: Optional[Any] = None,
        boundary: Optional[Any] = None,
        mesh_boundary: Optional[Any] = None,
        pump_stations: Optional[Any] = None,
        add_basemap: bool = False,
        crs: Optional[Any] = None,
        raster_alpha: float = 0.85,
        max_frames: Optional[int] = None,
        units: str = "ft",
        fps: int = 2,
        dpi: int = 150,
        cmap: str = "Blues",
        title: str = "HEC-RAS Flood Inundation",
        cell_size: Optional[float] = None,
        resampling: str = "nearest",
    ) -> Path:
        """
        Generate a flood animation from stored-map depth rasters.

        This is the raster-video companion for
        ``RasProcess.store_maps_at_timesteps()`` outputs.

        A timestep may be one raster path or a group of terrain-tile paths.
        Nonuniform frames are reconciled onto their union grid. ``cell_size``
        sets that grid's resolution in map units; otherwise the resolution of
        the largest-coverage source raster is used.
        """
        flood = PrecipMrms.load_stored_map_stack(
            raster_files,
            times=times,
            max_frames=max_frames,
            name="flood_inundation",
            units=units,
            cell_size=cell_size,
            resampling=resampling,
        )
        return PrecipMrms._animate_grid_stack(
            data=flood,
            output_path=output_mp4,
            title=title,
            value_label=f"Depth ({units})",
            units=units,
            terrain=PrecipMrms._prepare_terrain_data(terrain) if terrain is not None else None,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
            crs=crs,
            raster_alpha=raster_alpha,
            cmap=cmap,
            fps=fps,
            dpi=dpi,
            cumulative=False,
        )

    @staticmethod
    @log_call
    def animate_combined(
        precip_data: Any,
        flood_data: Any,
        output_mp4: Union[str, Path],
        precip_bounds: Optional[Bounds] = None,
        flood_times: Optional[Iterable[Any]] = None,
        flood_extent: Optional[Tuple[float, float, float, float]] = None,
        boundary: Optional[Any] = None,
        mesh_boundary: Optional[Any] = None,
        pump_stations: Optional[Any] = None,
        add_basemap: bool = False,
        precip_crs: Optional[Any] = None,
        flood_crs: Optional[Any] = None,
        raster_alpha: float = 0.85,
        fps: int = 2,
        dpi: int = 150,
        title: str = "MRMS Precipitation and Flood Response",
        bounds: Optional[Bounds] = None,
        mesh_name: Optional[str] = None,
        flood_variable: str = "Depth",
        max_frames: Optional[int] = 24,
        cell_size: Optional[float] = None,
        resampling: str = "nearest",
    ) -> Path:
        """
        Generate a synchronized split-screen precipitation and flood animation.

        ``precip_data`` can be GRIB2 file paths or an already loaded xarray
        DataArray. ``flood_data`` can be a gridded array, xarray DataArray,
        HEC-RAS plan HDF path, or flat/grouped stored-map raster frames.
        ``bounds`` is accepted as an alias for ``precip_bounds``.
        """
        _check_animation_dependencies()
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        if bounds is not None and precip_bounds is None:
            precip_bounds = bounds

        precip = PrecipMrms._prepare_precipitation_data(
            precip_data,
            bounds=precip_bounds,
        )
        precip_in = PrecipMrms._convert_precip_units(precip, "in/hr")

        if PrecipMrms._looks_like_raster_paths(flood_data):
            flood = PrecipMrms.load_stored_map_stack(
                flood_data,
                times=flood_times,
                max_frames=max_frames,
                name="flood_inundation",
                units="ft",
                cell_size=cell_size,
                resampling=resampling,
            )
        elif isinstance(flood_data, (str, Path)):
            flood_points = PrecipMrms._load_hdf_flood_points(
                plan_hdf=flood_data,
                variable=flood_variable,
                mesh_name=mesh_name,
                max_frames=max_frames,
            )
            return PrecipMrms._animate_combined_hdf_points(
                precip=precip_in,
                flood_points=flood_points,
                output_mp4=output_mp4,
                boundary=boundary,
                mesh_boundary=mesh_boundary,
                pump_stations=pump_stations,
                add_basemap=add_basemap,
                precip_crs=precip_crs,
                flood_crs=flood_crs,
                raster_alpha=raster_alpha,
                fps=fps,
                dpi=dpi,
                title=title,
            )
        else:
            flood = PrecipMrms._coerce_grid_data(
                flood_data,
                times=flood_times,
                extent=flood_extent,
                name="flood_inundation",
                units="ft",
            )
        precip_extent, precip_origin = PrecipMrms._data_extent(precip_in)
        flood_extent_resolved, flood_origin = PrecipMrms._data_extent(flood)
        precip_data_crs = precip_crs or PrecipMrms._data_crs(precip_in, "EPSG:4326")
        flood_data_crs = flood_crs or PrecipMrms._data_crs(flood)
        precip_times = pd.to_datetime(precip_in.coords["time"].values)
        flood_times_index = pd.to_datetime(flood.coords["time"].values)
        n_frames = int(flood.sizes["time"])
        if n_frames < 1 or len(precip_times) < 1:
            raise ValueError("Combined animation requires at least one frame")
        precip_frame_indices = PrecipMrms._nearest_previous_time_indices(
            source_times=precip_times,
            target_times=flood_times_index,
        )
        flood_values = np.asarray(flood.values, dtype=float)
        precip_vmax = PrecipMrms._robust_vmax(np.asarray(precip_in.values), 0.1)
        flood_vmax = PrecipMrms._robust_vmax(flood_values, 0.1)

        output_path = Path(output_mp4)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fig, (ax_p, ax_f) = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
        im_p = ax_p.imshow(
            np.asarray(precip_in.isel(time=int(precip_frame_indices[0])).values, dtype=float),
            extent=precip_extent,
            origin=precip_origin,
            cmap="turbo",
            vmin=0,
            vmax=precip_vmax,
            alpha=raster_alpha,
            zorder=2,
        )
        im_f = ax_f.imshow(
            np.asarray(flood.isel(time=0).values, dtype=float),
            extent=flood_extent_resolved,
            origin=flood_origin,
            cmap="Blues",
            vmin=0,
            vmax=flood_vmax,
            alpha=raster_alpha,
            zorder=2,
        )
        fig.colorbar(im_p, ax=ax_p, shrink=0.8).set_label("Precipitation (in/hr)")
        fig.colorbar(im_f, ax=ax_f, shrink=0.8).set_label("Depth (ft)")
        ax_p.set_title("MRMS QPE")
        ax_f.set_title("Flood Inundation")
        timestamp = fig.suptitle(title)
        PrecipMrms._plot_spatial_overlays(
            ax_p,
            data_crs=precip_data_crs,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
        )
        PrecipMrms._plot_spatial_overlays(
            ax_f,
            data_crs=flood_data_crs,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
        )

        def update(frame_idx: int) -> list:
            precip_idx = int(precip_frame_indices[frame_idx])
            im_p.set_data(np.asarray(precip_in.isel(time=precip_idx).values, dtype=float))
            im_f.set_data(np.asarray(flood.isel(time=frame_idx).values, dtype=float))
            timestamp.set_text(
                f"{title}\n"
                f"Precip: {precip_times[precip_idx].strftime('%Y-%m-%d %H:%M')} | "
                f"Flood: {flood_times_index[frame_idx].strftime('%Y-%m-%d %H:%M')}"
            )
            return [im_p, im_f, timestamp]

        PrecipMrms._save_animation(fig, update, n_frames, output_path, fps, dpi)
        return output_path

    @staticmethod
    def _prepare_precipitation_data(
        precip_data: Any,
        bounds: Optional[Bounds] = None,
        variable: Optional[str] = None,
    ) -> Any:
        if PrecipMrms._looks_like_paths(precip_data):
            return PrecipMrms.load_grib2_stack(
                grib2_files=precip_data,
                bounds=bounds,
                variable=variable,
            )

        precip = PrecipMrms._coerce_grid_data(
            precip_data,
            name="mrms_precipitation",
            units="mm",
        )
        if bounds is not None:
            precip = PrecipMrms._clip_dataarray(precip, bounds)
        return precip

    @staticmethod
    def _load_hdf_flood_points(
        plan_hdf: Union[str, Path],
        variable: str = "Depth",
        mesh_name: Optional[str] = None,
        max_frames: Optional[int] = 24,
    ) -> Dict[str, Any]:
        import numpy as np
        import pandas as pd

        from ..hdf.HdfBase import HdfBase
        from ..hdf.HdfMesh import HdfMesh
        from ..hdf.HdfResultsMesh import HdfResultsMesh

        plan_hdf = Path(plan_hdf)
        cell_points = HdfMesh.get_mesh_cell_points(plan_hdf)
        if cell_points.empty:
            raise ValueError(f"No 2D mesh cell centers found in {plan_hdf}")

        mesh_names = list(cell_points["mesh_name"].astype(str).unique())
        if mesh_name is None:
            mesh_name = mesh_names[0]
        if mesh_name not in mesh_names:
            raise ValueError(f"mesh_name {mesh_name!r} not found; choices: {mesh_names}")

        mesh_points = (
            cell_points[cell_points["mesh_name"].astype(str) == mesh_name]
            .sort_values("cell_id")
            .reset_index(drop=True)
        )
        values = HdfResultsMesh.get_mesh_timeseries(plan_hdf, mesh_name, variable)
        value_array = np.asarray(values.values, dtype=float)
        if value_array.ndim == 1:
            value_array = value_array.reshape((1, -1))
        if value_array.ndim != 2:
            raise ValueError(
                f"HDF flood animation expects 2-D time/cell data, got {value_array.shape}"
            )
        if value_array.shape[1] != len(mesh_points) and value_array.shape[0] == len(mesh_points):
            value_array = value_array.T
        if value_array.shape[1] != len(mesh_points):
            raise ValueError(
                f"HDF {variable!r} cell count {value_array.shape[1]} does not match "
                f"mesh cell centers {len(mesh_points)}"
            )

        if "time" in values.coords:
            time_values = pd.to_datetime(values.coords["time"].values)
        else:
            time_values = pd.date_range("2000-01-01", periods=value_array.shape[0], freq="h")

        if max_frames is not None and value_array.shape[0] > max_frames:
            frame_indices = np.linspace(
                0, value_array.shape[0] - 1, int(max_frames), dtype=int
            )
            value_array = value_array[frame_indices]
            time_values = time_values[frame_indices]

        return {
            "x": mesh_points.geometry.x.to_numpy(dtype=float),
            "y": mesh_points.geometry.y.to_numpy(dtype=float),
            "values": value_array,
            "times": time_values,
            "mesh_name": mesh_name,
            "variable": variable,
            "units": values.attrs.get("units", ""),
            "crs": HdfBase.get_projection(plan_hdf),
        }

    @staticmethod
    def _animate_combined_hdf_points(
        precip: Any,
        flood_points: Dict[str, Any],
        output_mp4: Union[str, Path],
        boundary: Optional[Any],
        mesh_boundary: Optional[Any],
        pump_stations: Optional[Any],
        add_basemap: bool,
        precip_crs: Optional[Any],
        flood_crs: Optional[Any],
        raster_alpha: float,
        fps: int,
        dpi: int,
        title: str,
    ) -> Path:
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        flood_values = flood_points["values"]
        precip_times = pd.to_datetime(precip.coords["time"].values)
        flood_times = pd.to_datetime(flood_points["times"])
        n_frames = int(flood_values.shape[0])
        if n_frames < 1 or len(precip_times) < 1:
            raise ValueError("Combined animation requires at least one frame")
        precip_frame_indices = PrecipMrms._nearest_previous_time_indices(
            source_times=precip_times,
            target_times=flood_times,
        )

        precip_extent, precip_origin = PrecipMrms._data_extent(precip)
        precip_data_crs = precip_crs or PrecipMrms._data_crs(precip, "EPSG:4326")
        flood_data_crs = flood_crs or flood_points.get("crs")
        precip_values = np.asarray(precip.values, dtype=float)
        precip_vmax = PrecipMrms._robust_vmax(precip_values, 0.1)
        flood_vmax = PrecipMrms._robust_vmax(flood_values, 0.1)

        output_path = Path(output_mp4)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fig, (ax_p, ax_f) = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
        im_p = ax_p.imshow(
            np.asarray(precip.isel(time=int(precip_frame_indices[0])).values, dtype=float),
            extent=precip_extent,
            origin=precip_origin,
            cmap="turbo",
            vmin=0,
            vmax=precip_vmax,
            alpha=raster_alpha,
            zorder=2,
        )
        scat = ax_f.scatter(
            flood_points["x"],
            flood_points["y"],
            c=flood_values[0],
            s=3,
            cmap="Blues",
            vmin=0,
            vmax=flood_vmax,
            linewidths=0,
            alpha=raster_alpha,
            zorder=2,
        )
        fig.colorbar(im_p, ax=ax_p, shrink=0.8).set_label("Precipitation (in/hr)")
        flood_label = flood_points["variable"]
        flood_units = flood_points["units"]
        fig.colorbar(scat, ax=ax_f, shrink=0.8).set_label(
            f"{flood_label} ({flood_units})" if flood_units else flood_label
        )
        ax_p.set_title("MRMS QPE")
        ax_f.set_title("Flood Inundation")
        ax_f.set_aspect("equal", adjustable="box")
        timestamp = fig.suptitle(title)
        PrecipMrms._plot_spatial_overlays(
            ax_p,
            data_crs=precip_data_crs,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
        )
        PrecipMrms._plot_spatial_overlays(
            ax_f,
            data_crs=flood_data_crs,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
        )

        def update(frame_idx: int) -> list:
            precip_idx = int(precip_frame_indices[frame_idx])
            im_p.set_data(np.asarray(precip.isel(time=precip_idx).values, dtype=float))
            scat.set_array(flood_values[frame_idx])
            timestamp.set_text(
                f"{title}\n"
                f"Precip: {precip_times[precip_idx].strftime('%Y-%m-%d %H:%M')} | "
                f"Flood: {flood_times[frame_idx].strftime('%Y-%m-%d %H:%M')}"
            )
            return [im_p, scat, timestamp]

        PrecipMrms._save_animation(fig, update, n_frames, output_path, fps, dpi)
        return output_path

    @staticmethod
    def _catalog_noaa_s3(
        start_ts: "pd.Timestamp",
        end_ts: "pd.Timestamp",
        product: str,
        timeout: int,
    ) -> "pd.DataFrame":
        import pandas as pd
        import requests

        product_info = PrecipMrms._product_info(product)
        s3_product = product_info["s3_product"]
        records = []

        for day in PrecipMrms._iter_days(start_ts, end_ts):
            prefix = f"CONUS/{s3_product}/{day:%Y%m%d}/"
            continuation = None
            while True:
                params = {
                    "list-type": "2",
                    "prefix": prefix,
                    "max-keys": "1000",
                }
                if continuation:
                    params["continuation-token"] = continuation
                response = requests.get(
                    PrecipMrms.NOAA_S3_BASE_URL,
                    params=params,
                    timeout=timeout,
                )
                if response.status_code == 404:
                    break
                response.raise_for_status()
                root = ET.fromstring(response.content)
                namespace = PrecipMrms._xml_namespace(root)

                for item in root.findall(f"{namespace}Contents"):
                    key = PrecipMrms._xml_text(item, "Key", namespace)
                    if not key or not key.endswith((".grib2", ".grib2.gz")):
                        continue
                    valid_time = PrecipMrms._timestamp_from_name(Path(key).name)
                    if valid_time is None:
                        continue
                    size_text = PrecipMrms._xml_text(item, "Size", namespace)
                    last_modified = PrecipMrms._xml_text(item, "LastModified", namespace)
                    records.append(
                        {
                            "valid_time": valid_time,
                            "source": "noaa_s3",
                            "product": product_info["canonical"],
                            "archive_product": s3_product,
                            "url": f"{PrecipMrms.NOAA_S3_BASE_URL}/{quote(key)}",
                            "filename": Path(key).name,
                            "size_bytes": int(size_text or 0),
                            "last_modified": pd.to_datetime(last_modified)
                            if last_modified
                            else pd.NaT,
                            "compressed": key.endswith(".gz"),
                        }
                    )

                next_token = PrecipMrms._xml_text(
                    root, "NextContinuationToken", namespace
                )
                truncated = PrecipMrms._xml_text(root, "IsTruncated", namespace)
                if truncated != "true" or not next_token:
                    break
                continuation = next_token

        return PrecipMrms._records_to_catalog(records)

    @staticmethod
    def _catalog_iowa_mtarchive(
        start_ts: "pd.Timestamp",
        end_ts: "pd.Timestamp",
        product: str,
        timeout: int,
    ) -> "pd.DataFrame":
        import pandas as pd
        import requests

        product_info = PrecipMrms._product_info(product)
        iowa_product = product_info["iowa_product"]
        if not iowa_product:
            return PrecipMrms._empty_catalog()

        records = []
        for day in PrecipMrms._iter_days(start_ts, end_ts):
            catalog_url = (
                f"{PrecipMrms.IOWA_CATALOG_BASE_URL}/mtarchive/"
                f"{day:%Y/%m/%d}/mrms/ncep/{iowa_product}/catalog.xml"
            )
            response = requests.get(catalog_url, timeout=timeout)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            root = ET.fromstring(response.content)
            namespace = PrecipMrms._xml_namespace(root)

            for dataset in root.findall(f".//{namespace}dataset"):
                filename = dataset.attrib.get("name", "")
                url_path = dataset.attrib.get("urlPath", "")
                if not filename.endswith((".grib2", ".grib2.gz")) or not url_path:
                    continue
                valid_time = PrecipMrms._timestamp_from_name(filename)
                if valid_time is None:
                    continue
                size_bytes = PrecipMrms._parse_thredds_size(dataset, namespace)
                modified_text = PrecipMrms._xml_text(dataset, "date", namespace)
                records.append(
                    {
                        "valid_time": valid_time,
                        "source": "iowa",
                        "product": product_info["canonical"],
                        "archive_product": iowa_product,
                        "url": f"{PrecipMrms.IOWA_FILESERVER_BASE_URL}/{quote(url_path)}",
                        "filename": filename,
                        "size_bytes": size_bytes,
                        "last_modified": pd.to_datetime(modified_text)
                        if modified_text
                        else pd.NaT,
                        "compressed": filename.endswith(".gz"),
                    }
                )

        return PrecipMrms._records_to_catalog(records)

    @staticmethod
    def _records_to_catalog(records: List[Dict[str, Any]]) -> "pd.DataFrame":
        import pandas as pd

        if not records:
            return PrecipMrms._empty_catalog()

        df = pd.DataFrame.from_records(records)
        df["valid_time"] = pd.to_datetime(df["valid_time"])
        df = PrecipMrms._dedupe_catalog(df)
        return df.sort_values(["valid_time", "source", "filename"]).reset_index(drop=True)

    @staticmethod
    def _empty_catalog() -> "pd.DataFrame":
        import pandas as pd

        return pd.DataFrame(
            columns=[
                "valid_time",
                "source",
                "product",
                "archive_product",
                "url",
                "filename",
                "size_bytes",
                "last_modified",
                "compressed",
            ]
        )

    @staticmethod
    def _filter_catalog(
        catalog_df: "pd.DataFrame",
        start_ts: "pd.Timestamp",
        end_ts: "pd.Timestamp",
    ) -> "pd.DataFrame":
        if catalog_df.empty:
            return catalog_df
        mask = (catalog_df["valid_time"] >= start_ts) & (
            catalog_df["valid_time"] <= end_ts
        )
        return catalog_df.loc[mask].sort_values("valid_time").reset_index(drop=True)

    @staticmethod
    def _dedupe_catalog(catalog_df: "pd.DataFrame") -> "pd.DataFrame":
        if catalog_df.empty:
            return catalog_df
        df = catalog_df.copy()
        df["_prefer_uncompressed"] = df["compressed"].map(lambda value: 1 if not value else 0)
        df = df.sort_values(
            ["valid_time", "source", "_prefer_uncompressed", "filename"],
            ascending=[True, True, False, True],
        )
        df = df.drop_duplicates(
            subset=["valid_time", "source", "archive_product"],
            keep="first",
        )
        return df.drop(columns=["_prefer_uncompressed"]).reset_index(drop=True)

    @staticmethod
    def _prefer_catalog_source(catalog_df: "pd.DataFrame") -> "pd.DataFrame":
        if catalog_df.empty:
            return catalog_df
        source_rank = {"noaa_s3": 0, "iowa": 1}
        df = catalog_df.copy()
        df["_source_rank"] = df["source"].map(source_rank).fillna(99)
        df = df.sort_values(["valid_time", "_source_rank", "filename"])
        df = df.drop_duplicates(subset=["valid_time", "product"], keep="first")
        return df.drop(columns=["_source_rank"]).reset_index(drop=True)

    @staticmethod
    def _download_one(
        url: str,
        local_path: Path,
        decompress: bool,
        timeout: int,
    ) -> None:
        import requests

        tmp_path = local_path.with_name(local_path.name + ".tmp")
        gz_tmp_path = local_path.with_name(local_path.name + ".gz.tmp")

        for stale in (tmp_path, gz_tmp_path):
            if stale.exists():
                stale.unlink()

        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()

        if decompress:
            with open(gz_tmp_path, "wb") as gz_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        gz_file.write(chunk)
            with gzip.open(gz_tmp_path, "rb") as src, open(tmp_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            gz_tmp_path.unlink(missing_ok=True)
        else:
            with open(tmp_path, "wb") as dst:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        dst.write(chunk)

        tmp_path.replace(local_path)

    @staticmethod
    def _product_info(product: str) -> Dict[str, Any]:
        canonical = PrecipMrms._canonical_product(product)
        hours = PrecipMrms._product_hours(canonical)
        if hours not in PrecipMrms.PRODUCT_HOURS:
            raise ValueError(
                f"Unsupported MRMS QPE duration {hours}H. "
                f"Supported durations: {PrecipMrms.PRODUCT_HOURS}"
            )

        hours_text = f"{hours:02d}H"
        is_radar_only = canonical.lower().startswith("radaronly_")
        s3_stem = "RadarOnly_QPE" if is_radar_only else "MultiSensor_QPE"
        return {
            "canonical": canonical,
            "hours": hours,
            "family": "RadarOnly" if is_radar_only else "GaugeCorr",
            "iowa_product": (
                f"GaugeCorr_QPE_{hours_text}"
                if not is_radar_only and hours == 1
                else None
            ),
            "s3_product": (
                f"{s3_stem}_{hours_text}"
                if is_radar_only
                else f"{s3_stem}_{hours_text}_{PrecipMrms.DEFAULT_S3_PASS}_00.00"
            ),
        }

    @staticmethod
    def _canonical_product(product: str) -> str:
        cleaned = str(product).strip()
        compact = cleaned.replace("-", "_")

        if compact.lower().startswith("multisensor_qpe_"):
            hours = PrecipMrms._product_hours(compact)
            return f"GaugeCorr_QPE_{hours:02d}H"

        if compact.lower().startswith("radaronly_qpe"):
            hours = PrecipMrms._product_hours(compact)
            return f"RadarOnly_QPE_{hours:02d}H"

        if compact.lower().startswith("gaugecorr"):
            hours = PrecipMrms._product_hours(compact)
            return f"GaugeCorr_QPE_{hours:02d}H"

        hours_match = re.search(r"(?:QPE_?|QPE)(\d{1,2})H", compact, re.IGNORECASE)
        if hours_match:
            return f"GaugeCorr_QPE_{int(hours_match.group(1)):02d}H"

        match = re.search(r"(\d{1,2})H", compact, re.IGNORECASE)
        if match:
            return f"GaugeCorr_QPE_{int(match.group(1)):02d}H"

        raise ValueError(
            f"Unsupported MRMS product {product!r}. "
            "Use names like 'GaugeCorr_QPE_01H', 'RadarOnly_QPE_01H', "
            "or 'MultiSensor_QPE_01H_Pass2_00.00'."
        )

    @staticmethod
    def _vortex_variables(product: str) -> List[str]:
        compact = str(product).strip().replace("-", "_")
        multisensor_match = re.search(
            r"MultiSensor_QPE_(\d{1,2})H_(Pass\d)",
            compact,
            flags=re.IGNORECASE,
        )
        if multisensor_match:
            hours = int(multisensor_match.group(1))
            pass_name = multisensor_match.group(2)
            return [f"MultiSensor_QPE_{hours:02d}H_{pass_name}_altitude_above_msl"]

        product_info = PrecipMrms._product_info(product)
        hours_text = f"{product_info['hours']:02d}H"
        if product_info["family"] == "RadarOnly":
            stem = "RadarOnlyQPE"
        else:
            stem = "GaugeCorrQPE"
        return [f"{stem}{hours_text}_altitude_above_msl"]

    @staticmethod
    def _vortex_variables_for_files(product: str, grib_paths: Iterable[Path]) -> List[str]:
        for grib_path in grib_paths:
            filename = grib_path.name
            multisensor_match = re.search(
                r"MRMS_(MultiSensor_QPE_(\d{1,2})H_(Pass\d))_",
                filename,
                flags=re.IGNORECASE,
            )
            if multisensor_match:
                hours = int(multisensor_match.group(2))
                pass_name = multisensor_match.group(3)
                return [
                    f"MultiSensor_QPE_{hours:02d}H_{pass_name}_altitude_above_msl"
                ]

            radaronly_match = re.search(
                r"MRMS_(RadarOnly_QPE_(\d{1,2})H)_",
                filename,
                flags=re.IGNORECASE,
            )
            if radaronly_match:
                hours = int(radaronly_match.group(2))
                return [f"RadarOnlyQPE{hours:02d}H_altitude_above_msl"]

        return PrecipMrms._vortex_variables(product)

    @staticmethod
    def _product_hours(product: str) -> int:
        match = re.search(r"(\d{1,2})H", str(product), flags=re.IGNORECASE)
        if not match:
            raise ValueError(f"Could not determine MRMS QPE duration from {product!r}")
        return int(match.group(1))

    @staticmethod
    def _validate_bounds(bounds: Bounds) -> None:
        if len(bounds) != 4:
            raise ValueError("bounds must be (west, south, east, north)")
        west, south, east, north = [float(value) for value in bounds]
        if west >= east or south >= north:
            raise ValueError(f"Invalid bounds: {bounds}")
        conus_west, conus_south, conus_east, conus_north = PrecipMrms.CONUS_BOUNDS
        if (
            east < conus_west
            or west > conus_east
            or north < conus_south
            or south > conus_north
        ):
            logger.warning(
                "Bounds %s do not intersect approximate MRMS CONUS bounds %s",
                bounds,
                PrecipMrms.CONUS_BOUNDS,
            )

    @staticmethod
    def _parse_timestamp(value: Union[str, datetime], end_of_day: bool):
        import pandas as pd

        is_date_only = isinstance(value, str) and bool(_DATE_ONLY_RE.match(value.strip()))
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        if is_date_only and end_of_day:
            ts = ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        return ts

    @staticmethod
    def _iter_days(start_ts: "pd.Timestamp", end_ts: "pd.Timestamp"):
        current = start_ts.normalize()
        last = end_ts.normalize()
        while current <= last:
            yield current.to_pydatetime()
            current += timedelta(days=1)

    @staticmethod
    def _timestamp_from_name(filename: str) -> Optional[datetime]:
        match = _TIMESTAMP_RE.search(filename)
        if not match:
            return None
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")

    @staticmethod
    def _xml_namespace(root: ET.Element) -> str:
        if root.tag.startswith("{"):
            return root.tag.split("}", 1)[0] + "}"
        return ""

    @staticmethod
    def _xml_text(element: ET.Element, tag: str, namespace: str) -> Optional[str]:
        child = element.find(f"{namespace}{tag}")
        if child is None or child.text is None:
            return None
        return child.text.strip()

    @staticmethod
    def _parse_thredds_size(dataset: ET.Element, namespace: str) -> int:
        size_node = dataset.find(f"{namespace}dataSize")
        if size_node is None or not size_node.text:
            return 0

        try:
            size_value = float(size_node.text.strip())
        except ValueError:
            return 0

        units = size_node.attrib.get("units", "").lower()
        if units.startswith("k"):
            return int(size_value * 1024)
        if units.startswith("m"):
            return int(size_value * 1024 * 1024)
        if units.startswith("g"):
            return int(size_value * 1024 * 1024 * 1024)
        return int(size_value)

    @staticmethod
    def _normalize_paths(
        paths: Union[str, Path, Iterable[Union[str, Path]]]
    ) -> List[Path]:
        if isinstance(paths, (str, Path)):
            return [Path(paths)]
        return [Path(path) for path in paths]

    @staticmethod
    def _select_data_var(ds: Any, variable: Optional[str]) -> str:
        if variable is not None:
            if variable not in ds.data_vars:
                raise ValueError(
                    f"Variable {variable!r} not found in GRIB2. "
                    f"Available variables: {list(ds.data_vars)}"
                )
            return variable

        data_vars = list(ds.data_vars)
        if not data_vars:
            raise ValueError("No data variables found in MRMS GRIB2 file")
        if len(data_vars) == 1:
            return data_vars[0]

        priority = ["qpe", "precip", "unknown", "tp"]
        for token in priority:
            for var_name in data_vars:
                if token in var_name.lower():
                    return var_name
        return data_vars[0]

    @staticmethod
    def _drop_scalar_coords(da: Any) -> Any:
        scalar_coords = [
            name for name in da.coords if name not in da.dims and da.coords[name].ndim == 0
        ]
        if scalar_coords:
            try:
                da = da.drop_vars(scalar_coords)
            except ValueError:
                pass
        return da

    @staticmethod
    def _frame_time_from_dataarray(da: Any, grib_path: Path) -> datetime:
        for coord_name in ("valid_time", "time"):
            if coord_name in da.coords:
                timestamp = PrecipMrms._timestamp_from_xarray(da.coords[coord_name])
                if timestamp is not None:
                    return timestamp
        timestamp = PrecipMrms._timestamp_from_name(grib_path.name)
        if timestamp is not None:
            return timestamp
        return datetime.fromtimestamp(grib_path.stat().st_mtime)

    @staticmethod
    def _timestamp_from_xarray(coord: Any) -> Optional[datetime]:
        """Extract a scalar datetime from an xarray coordinate-like object."""
        import numpy as np
        import pandas as pd

        values = getattr(coord, "values", coord)
        array = np.asarray(values)
        if array.size == 0:
            return None

        value = array.reshape(-1)[0]
        try:
            timestamp = pd.Timestamp(value)
        except Exception:
            return None

        if pd.isna(timestamp):
            return None
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return timestamp.to_pydatetime()

    @staticmethod
    def _clip_dataarray(da: Any, bounds: Bounds) -> Any:
        import xarray as xr

        west, south, east, north = bounds
        lat_name = PrecipMrms._find_coord_name(da, ("latitude", "lat", "y"))
        lon_name = PrecipMrms._find_coord_name(da, ("longitude", "lon", "x"))
        if lat_name is None or lon_name is None:
            logger.warning("MRMS grid has no latitude/longitude coordinates; skipping clip")
            return da

        lon = da[lon_name]
        lat = da[lat_name]
        lon_values = xr.where(lon > 180, lon - 360, lon)

        if lat.ndim == 1 and lon.ndim == 1 and lat_name in da.dims and lon_name in da.dims:
            da = da.assign_coords({lon_name: lon_values})
            lat_values = da[lat_name].values
            lon_values_np = da[lon_name].values
            lat_slice = slice(north, south) if lat_values[0] > lat_values[-1] else slice(south, north)
            lon_slice = slice(west, east) if lon_values_np[0] <= lon_values_np[-1] else slice(east, west)
            return da.sel({lat_name: lat_slice, lon_name: lon_slice})

        mask = (
            (lat >= south)
            & (lat <= north)
            & (lon_values >= west)
            & (lon_values <= east)
        )
        if not bool(mask.any()):
            raise ValueError(f"Bounds do not intersect MRMS grid: {bounds}")
        return da.where(mask, drop=True)

    @staticmethod
    def _find_coord_name(da: Any, candidates: Tuple[str, ...]) -> Optional[str]:
        lower_lookup = {name.lower(): name for name in list(da.coords) + list(da.dims)}
        for candidate in candidates:
            if candidate.lower() in lower_lookup:
                return lower_lookup[candidate.lower()]
        return None

    @staticmethod
    def _looks_like_paths(value: Any) -> bool:
        if isinstance(value, (str, Path)):
            return True
        if isinstance(value, (list, tuple, set)) and not hasattr(value, "dims"):
            values = list(value)
            return bool(values) and all(isinstance(item, (str, Path)) for item in values)
        return False

    @staticmethod
    def _looks_like_raster_paths(value: Any) -> bool:
        def _is_raster_path(item: Any) -> bool:
            return isinstance(item, (str, Path)) and Path(item).suffix.lower() in {
                ".tif",
                ".tiff",
            }

        if _is_raster_path(value):
            return True
        if isinstance(value, (list, tuple, set)) and not hasattr(value, "dims"):
            values = list(value)
            if not values:
                return False
            for item in values:
                if _is_raster_path(item):
                    continue
                if not isinstance(item, (list, tuple, set)):
                    return False
                if not all(_is_raster_path(tile) for tile in item):
                    return False
            return True
        return False

    @staticmethod
    def _coerce_grid_data(
        data: Any,
        times: Optional[Iterable[Any]] = None,
        extent: Optional[Tuple[float, float, float, float]] = None,
        name: str = "value",
        units: str = "",
    ) -> Any:
        import numpy as np
        import pandas as pd
        import xarray as xr

        if hasattr(data, "dims") and hasattr(data, "values"):
            da = data
            if "time" not in da.dims:
                da = da.expand_dims(time=[pd.Timestamp("2000-01-01")])
            return da

        array = np.asarray(data, dtype=float)
        if array.ndim == 2:
            array = array.reshape((1, array.shape[0], array.shape[1]))
        if array.ndim != 3:
            raise ValueError("Grid animation data must be 2-D or 3-D")

        if times is None:
            time_index = pd.date_range("2000-01-01", periods=array.shape[0], freq="h")
        else:
            time_index = pd.DatetimeIndex(pd.to_datetime(list(times)), name="time")
            if len(time_index) != array.shape[0]:
                raise ValueError("times length must match flood_data time dimension")

        y_size, x_size = array.shape[1], array.shape[2]
        if extent is None:
            x_coords = np.arange(x_size)
            y_coords = np.arange(y_size)
        else:
            west, east, south, north = extent
            x_coords = np.linspace(west, east, x_size)
            y_coords = np.linspace(south, north, y_size)

        da = xr.DataArray(
            array,
            dims=("time", "y", "x"),
            coords={"time": time_index, "y": y_coords, "x": x_coords},
            name=name,
            attrs={"units": units},
        )
        return da

    @staticmethod
    @log_call
    def load_stored_map_stack(
        raster_files: Union[
            str,
            Path,
            Iterable[Union[str, Path, Iterable[Union[str, Path]]]],
        ],
        times: Optional[Iterable[Any]] = None,
        max_frames: Optional[int] = None,
        name: str = "raster",
        units: str = "",
        cell_size: Optional[float] = None,
        resampling: str = "nearest",
    ) -> "xr.DataArray":
        """
        Load HEC-RAS stored-map rasters as a time-indexed grid stack.

        ``raster_files`` may be a flat sequence with one raster per timestep or
        a sequence of raster groups, where each group contains all terrain tiles
        for one timestep. Nonuniform rasters are mosaicked onto a common union
        grid in input order. ``cell_size`` sets the union-grid resolution in map
        units; otherwise the largest-coverage source raster supplies it.

        Frame limiting occurs before any selected raster metadata or data is
        read. The returned DataArray has ``time``, ``y``, and ``x`` dimensions
        and includes ``units`` and ``crs`` attributes. The returned stack is
        allocated eagerly; specify both ``cell_size`` and ``max_frames`` for
        large multi-terrain domains to bound memory use.
        """
        try:
            import rasterio
            from rasterio.transform import from_origin
            from rasterio.warp import Resampling, reproject
        except ImportError as exc:
            raise ImportError(
                "rasterio is required to animate stored-map rasters. "
                "Install with: pip install rasterio"
            ) from exc

        import numpy as np
        import pandas as pd
        import xarray as xr

        raster_frames, flat_input = PrecipMrms._normalize_stored_map_frames(
            raster_files
        )
        frame_count = len(raster_frames)

        if max_frames is None:
            max_frames_value = None
        else:
            if isinstance(max_frames, bool) or not isinstance(max_frames, Integral):
                raise ValueError("max_frames must be a positive integer")
            max_frames_value = int(max_frames)
            if max_frames_value <= 0:
                raise ValueError("max_frames must be a positive integer")

        if cell_size is None:
            cell_size_value = None
        else:
            if isinstance(cell_size, bool):
                raise ValueError("cell_size must be a positive finite number")
            try:
                cell_size_value = float(cell_size)
            except (TypeError, ValueError) as exc:
                raise ValueError("cell_size must be a positive finite number") from exc
            if not np.isfinite(cell_size_value) or cell_size_value <= 0:
                raise ValueError("cell_size must be a positive finite number")

        resampling_name = str(resampling).strip().lower()
        supported_resampling = tuple(
            item for item in Resampling.__members__ if item != "gauss"
        )
        if resampling_name not in supported_resampling:
            raise ValueError(
                f"Unsupported resampling method {resampling!r}. "
                f"Choose one of: {', '.join(supported_resampling)}"
            )
        resampling_method = Resampling[resampling_name]

        if times is None:
            full_time_index = pd.date_range(
                "2000-01-01",
                periods=frame_count,
                freq="h",
                name="time",
            )
        else:
            time_values = list(times)
            if len(time_values) != frame_count:
                raise ValueError("times length must match raster frame count")
            full_time_index = pd.DatetimeIndex(
                pd.to_datetime(time_values),
                name="time",
            )

        if max_frames_value is not None and frame_count > max_frames_value:
            frame_indices = np.linspace(
                0,
                frame_count - 1,
                max_frames_value,
                dtype=int,
            )
        else:
            frame_indices = np.arange(frame_count, dtype=int)

        selected_frames = [raster_frames[int(index)] for index in frame_indices]
        time_index = full_time_index.take(frame_indices)

        frame_metas: List[List[Dict[str, Any]]] = []
        all_metas: List[Dict[str, Any]] = []
        common_crs = None
        for frame_index, raster_paths in enumerate(selected_frames):
            metas = []
            for raster_path in raster_paths:
                if not raster_path.exists():
                    raise FileNotFoundError(f"Raster file not found: {raster_path}")
                with rasterio.open(raster_path) as src:
                    if src.count < 1:
                        raise ValueError(f"Raster has no data bands: {raster_path}")
                    if src.crs is None:
                        raise ValueError(f"Raster has no CRS: {raster_path}")
                    if common_crs is None:
                        common_crs = src.crs
                    elif src.crs != common_crs:
                        raise ValueError(
                            "All stored-map rasters must use a common CRS; "
                            f"frame {frame_index} raster {raster_path} uses {src.crs}, "
                            f"expected {common_crs}"
                        )

                    src_nodata = src.nodata
                    if src_nodata is None and np.issubdtype(
                        np.dtype(src.dtypes[0]), np.floating
                    ):
                        src_nodata = np.nan
                    meta = {
                        "path": raster_path,
                        "shape": (src.height, src.width),
                        "transform": src.transform,
                        "bounds": src.bounds,
                        "res": (abs(src.res[0]), abs(src.res[1])),
                        "nodata": src_nodata,
                    }
                metas.append(meta)
                all_metas.append(meta)
            frame_metas.append(metas)

        uniform = (
            flat_input
            and cell_size_value is None
            and len({meta["shape"] for meta in all_metas}) == 1
            and len({meta["transform"] for meta in all_metas}) == 1
        )

        if uniform:
            ref_transform = all_metas[0]["transform"]
            rows, cols = all_metas[0]["shape"]
            values = np.empty(
                (len(all_metas), rows, cols),
                dtype=np.float32,
            )
            for frame_index, meta in enumerate(all_metas):
                with rasterio.open(meta["path"]) as src:
                    src.read(1, out=values[frame_index])
                nodata = meta["nodata"]
                if nodata is not None and not np.isnan(nodata):
                    frame = values[frame_index]
                    frame[frame == nodata] = np.nan
        else:
            if cell_size_value is None:
                def _coverage(meta: Dict[str, Any]) -> float:
                    bounds = meta["bounds"]
                    return (bounds.right - bounds.left) * (
                        bounds.top - bounds.bottom
                    )

                base_meta = max(all_metas, key=_coverage)
                xres, yres = base_meta["res"]
            else:
                xres = yres = cell_size_value

            left = min(meta["bounds"].left for meta in all_metas)
            bottom = min(meta["bounds"].bottom for meta in all_metas)
            right = max(meta["bounds"].right for meta in all_metas)
            top = max(meta["bounds"].top for meta in all_metas)
            cols = max(1, int(np.ceil((right - left) / xres)))
            rows = max(1, int(np.ceil((top - bottom) / yres)))
            ref_transform = from_origin(left, top, xres, yres)

            values = np.full(
                (len(frame_metas), rows, cols),
                np.nan,
                dtype=np.float32,
            )
            for frame_index, metas in enumerate(frame_metas):
                destination = values[frame_index]
                for meta in metas:
                    with rasterio.open(meta["path"]) as src:
                        reproject(
                            source=rasterio.band(src, 1),
                            destination=destination,
                            src_transform=src.transform,
                            src_crs=src.crs,
                            src_nodata=meta["nodata"],
                            dst_transform=ref_transform,
                            dst_crs=common_crs,
                            dst_nodata=np.nan,
                            resampling=resampling_method,
                            init_dest_nodata=False,
                        )

        xs = np.arange(cols, dtype=float) + 0.5
        ys = np.arange(rows, dtype=float) + 0.5
        x_coords = ref_transform.c + xs * ref_transform.a
        y_coords = ref_transform.f + ys * ref_transform.e

        return xr.DataArray(
            values,
            dims=("time", "y", "x"),
            coords={"time": time_index, "y": y_coords, "x": x_coords},
            name=name,
            attrs={"units": units, "crs": common_crs.to_string()},
        )

    @staticmethod
    def _normalize_stored_map_frames(
        raster_files: Union[
            str,
            Path,
            Iterable[Union[str, Path, Iterable[Union[str, Path]]]],
        ],
    ) -> Tuple[List[List[Path]], bool]:
        if isinstance(raster_files, (str, Path)):
            return [[Path(raster_files)]], True

        try:
            raw_frames = list(raster_files)
        except TypeError as exc:
            raise TypeError(
                "raster_files must be a raster path or an iterable of raster frames"
            ) from exc
        if isinstance(raster_files, set):
            raw_frames.sort(key=lambda item: str(item))
        if not raw_frames:
            raise ValueError("raster_files must contain at least one frame")

        flat_input = all(isinstance(frame, (str, Path)) for frame in raw_frames)
        frames: List[List[Path]] = []
        for frame_index, frame in enumerate(raw_frames):
            if isinstance(frame, (str, Path)):
                frames.append([Path(frame)])
                continue
            try:
                tiles = list(frame)
            except TypeError as exc:
                raise TypeError(
                    f"Raster frame {frame_index} must be a path or iterable of paths"
                ) from exc
            if isinstance(frame, set):
                tiles.sort(key=lambda item: str(item))
            if not tiles:
                raise ValueError(
                    f"Raster frame {frame_index} must contain at least one raster"
                )
            if not all(isinstance(tile, (str, Path)) for tile in tiles):
                raise TypeError(
                    f"Raster frame {frame_index} must contain only raster paths"
                )
            frames.append([Path(tile) for tile in tiles])
        return frames, flat_input

    @staticmethod
    def _load_raster_stack(
        raster_files: Union[
            str,
            Path,
            Iterable[Union[str, Path, Iterable[Union[str, Path]]]],
        ],
        times: Optional[Iterable[Any]] = None,
        max_frames: Optional[int] = None,
        name: str = "raster",
        units: str = "",
        cell_size: Optional[float] = None,
        resampling: str = "nearest",
    ) -> "xr.DataArray":
        return PrecipMrms.load_stored_map_stack(
            raster_files=raster_files,
            times=times,
            max_frames=max_frames,
            name=name,
            units=units,
            cell_size=cell_size,
            resampling=resampling,
        )

    @staticmethod
    def _prepare_terrain_data(terrain: Any) -> Any:
        if terrain is None:
            return None
        if isinstance(terrain, (str, Path)):
            try:
                import rasterio
            except ImportError as exc:
                raise ImportError(
                    "rasterio is required to use a terrain raster overlay. "
                    "Install with: pip install rasterio"
                ) from exc
            with rasterio.open(terrain) as src:
                terrain_data = src.read(1).astype(float)
                if src.nodata is not None:
                    terrain_data[terrain_data == src.nodata] = float("nan")
            return PrecipMrms._hillshade(terrain_data)
        return terrain

    @staticmethod
    def _hillshade(values: Any, azimuth: float = 315.0, altitude: float = 45.0) -> Any:
        import numpy as np

        data = np.asarray(values, dtype=float)
        if data.ndim != 2:
            return data
        filled = np.where(np.isfinite(data), data, np.nanmean(data))
        dy, dx = np.gradient(filled)
        slope = np.pi / 2.0 - np.arctan(np.hypot(dx, dy))
        aspect = np.arctan2(-dx, dy)
        azimuth_rad = np.deg2rad(azimuth)
        altitude_rad = np.deg2rad(altitude)
        shaded = (
            np.sin(altitude_rad) * np.sin(slope)
            + np.cos(altitude_rad) * np.cos(slope) * np.cos(azimuth_rad - aspect)
        )
        return np.clip((shaded + 1.0) / 2.0, 0.0, 1.0)

    @staticmethod
    def _convert_precip_units(data: Any, units: str) -> Any:
        units_clean = units.lower().strip()
        if units_clean.startswith("in"):
            converted = data / 25.4
            converted.attrs.update(data.attrs)
            converted.attrs["units"] = units
            return converted
        converted = data.copy()
        converted.attrs["units"] = units
        return converted

    @staticmethod
    def _animate_grid_stack(
        data: Any,
        output_path: Union[str, Path],
        title: str,
        value_label: str,
        units: str,
        boundary: Optional[Any] = None,
        mesh_boundary: Optional[Any] = None,
        pump_stations: Optional[Any] = None,
        terrain: Optional[Any] = None,
        add_basemap: bool = False,
        crs: Optional[Any] = None,
        raster_alpha: float = 0.85,
        cmap: str = "viridis",
        fps: int = 2,
        dpi: int = 150,
        cumulative: bool = False,
    ) -> Path:
        _check_animation_dependencies()
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        if "time" not in data.dims:
            raise ValueError("Animation data must have a time dimension")

        plot_data = PrecipMrms._convert_precip_units(data, units) if cumulative else data
        values = np.asarray(plot_data.values, dtype=float)
        if values.ndim != 3:
            raise ValueError(f"Animation data must be 3-D, got shape {values.shape}")

        extent, origin = PrecipMrms._data_extent(plot_data)
        data_crs = crs or PrecipMrms._data_crs(plot_data)
        vmax = PrecipMrms._robust_vmax(values, 0.1)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
        if terrain is not None:
            ax.imshow(
                terrain,
                extent=extent,
                origin=origin,
                cmap="gray",
                alpha=0.35,
                zorder=1,
            )
        image = ax.imshow(
            values[0],
            extent=extent,
            origin=origin,
            cmap=cmap,
            vmin=0,
            vmax=vmax,
            alpha=raster_alpha,
            zorder=2,
        )
        cbar = fig.colorbar(image, ax=ax, shrink=0.8)
        cbar.set_label(value_label)
        annotation = ax.text(
            0.02,
            0.98,
            "",
            transform=ax.transAxes,
            va="top",
            ha="left",
            color="black",
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none"},
        )
        ax.set_title(title)
        ax.set_xlabel("Longitude" if "longitude" in plot_data.coords else "X")
        ax.set_ylabel("Latitude" if "latitude" in plot_data.coords else "Y")
        PrecipMrms._plot_spatial_overlays(
            ax,
            data_crs=data_crs,
            boundary=boundary,
            mesh_boundary=mesh_boundary,
            pump_stations=pump_stations,
            add_basemap=add_basemap,
        )

        times = pd.to_datetime(plot_data.coords["time"].values)
        cumulative_values = (
            np.nanmean(values, axis=(1, 2)).cumsum() if cumulative else None
        )

        def update(frame_idx: int) -> list:
            image.set_data(values[frame_idx])
            timestamp = times[frame_idx].strftime("%Y-%m-%d %H:%M")
            if cumulative:
                annotation.set_text(
                    f"{timestamp}\nMean cumulative: {cumulative_values[frame_idx]:.2f} {units}"
                )
            else:
                annotation.set_text(timestamp)
            return [image, annotation]

        PrecipMrms._save_animation(fig, update, values.shape[0], output, fps, dpi)
        return output

    @staticmethod
    def _save_animation(
        fig: Any,
        update_func: Any,
        frame_count: int,
        output_path: Path,
        fps: int,
        dpi: int,
    ) -> None:
        import matplotlib.pyplot as plt
        from matplotlib import animation

        anim = animation.FuncAnimation(
            fig,
            update_func,
            frames=frame_count,
            blit=False,
            repeat=False,
        )
        suffix = output_path.suffix.lower()
        try:
            if suffix == ".gif":
                writer = animation.PillowWriter(fps=fps)
            else:
                if not animation.writers.is_available("ffmpeg"):
                    raise RuntimeError(
                        "Matplotlib ffmpeg writer is not available. Install ffmpeg "
                        "or save as .gif with PillowWriter."
                    )
                writer = animation.FFMpegWriter(fps=fps, bitrate=1800)
            anim.save(output_path, writer=writer, dpi=dpi)
        finally:
            plt.close(fig)

    @staticmethod
    def _data_extent(data: Any) -> Tuple[Tuple[float, float, float, float], str]:
        import numpy as np

        lat_name = PrecipMrms._find_coord_name(data, ("latitude", "lat"))
        lon_name = PrecipMrms._find_coord_name(data, ("longitude", "lon"))
        if lat_name is not None and lon_name is not None:
            lat = np.asarray(data[lat_name].values, dtype=float)
            lon = np.asarray(data[lon_name].values, dtype=float)
            lon = np.where(lon > 180, lon - 360, lon)
            origin = "upper" if lat.ndim == 1 and lat[0] > lat[-1] else "lower"
            return (
                float(np.nanmin(lon)),
                float(np.nanmax(lon)),
                float(np.nanmin(lat)),
                float(np.nanmax(lat)),
            ), origin

        if "x" in data.coords and "y" in data.coords:
            x = np.asarray(data.coords["x"].values, dtype=float)
            y = np.asarray(data.coords["y"].values, dtype=float)
            origin = "upper" if y.ndim == 1 and y[0] > y[-1] else "lower"
            return (
                float(np.nanmin(x)),
                float(np.nanmax(x)),
                float(np.nanmin(y)),
                float(np.nanmax(y)),
            ), origin

        shape = data.isel(time=0).shape
        return (0.0, float(shape[1]), 0.0, float(shape[0])), "lower"

    @staticmethod
    def _data_crs(data: Any, fallback: Optional[Any] = None) -> Optional[Any]:
        attrs = getattr(data, "attrs", {}) or {}
        crs = attrs.get("crs") or attrs.get("spatial_ref")
        if crs:
            return crs
        rio = getattr(data, "rio", None)
        if rio is not None:
            try:
                if rio.crs is not None:
                    return rio.crs
            except Exception:
                pass
        if "latitude" in getattr(data, "coords", {}) and "longitude" in getattr(data, "coords", {}):
            return "EPSG:4326"
        if "lat" in getattr(data, "coords", {}) and "lon" in getattr(data, "coords", {}):
            return "EPSG:4326"
        return fallback

    @staticmethod
    def _nearest_previous_time_indices(source_times: Any, target_times: Any) -> Any:
        import numpy as np
        import pandas as pd

        source = pd.DatetimeIndex(pd.to_datetime(source_times))
        target = pd.DatetimeIndex(pd.to_datetime(target_times))
        if len(source) == 0:
            raise ValueError("source_times must contain at least one timestamp")
        positions = np.searchsorted(source.values, target.values, side="right") - 1
        return np.clip(positions, 0, len(source) - 1).astype(int)

    @staticmethod
    def _robust_vmax(values: Any, minimum: float) -> float:
        import numpy as np

        finite = np.asarray(values, dtype=float)
        finite = finite[np.isfinite(finite)]
        finite = finite[finite > 0]
        if finite.size == 0:
            return minimum
        return max(float(np.percentile(finite, 98)), minimum)

    @staticmethod
    def _plot_spatial_overlays(
        ax: Any,
        data_crs: Optional[Any],
        boundary: Optional[Any] = None,
        mesh_boundary: Optional[Any] = None,
        pump_stations: Optional[Any] = None,
        add_basemap: bool = False,
    ) -> None:
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()

        if add_basemap:
            PrecipMrms._add_osm_basemap(ax, data_crs)
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)

        PrecipMrms._plot_boundary(
            ax,
            boundary,
            target_crs=data_crs,
            color="black",
            linewidth=1.0,
            zorder=4,
        )
        PrecipMrms._plot_boundary(
            ax,
            mesh_boundary,
            target_crs=data_crs,
            color="white",
            linewidth=2.4,
            zorder=5,
        )
        PrecipMrms._plot_boundary(
            ax,
            mesh_boundary,
            target_crs=data_crs,
            color="#111111",
            linewidth=1.1,
            zorder=6,
        )
        PrecipMrms._plot_pump_stations(ax, pump_stations, target_crs=data_crs)

    @staticmethod
    def _add_osm_basemap(ax: Any, data_crs: Optional[Any]) -> None:
        if data_crs is None:
            logger.warning("Cannot add OSM basemap without a data CRS")
            return

        try:
            import contextily as ctx  # type: ignore

            ctx.add_basemap(
                ax,
                source=ctx.providers.OpenStreetMap.Mapnik,
                crs=data_crs,
                attribution=False,
                reset_extent=False,
                zorder=0,
            )
            return
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("contextily basemap rendering failed; trying fallback: %s", exc)

        try:
            PrecipMrms._add_osm_basemap_fallback(ax, data_crs)
        except Exception as exc:
            logger.warning("OSM basemap fallback failed: %s", exc)

    @staticmethod
    def _add_osm_basemap_fallback(ax: Any, data_crs: Any) -> None:
        import numpy as np
        from PIL import Image
        from pyproj import CRS, Transformer
        import rasterio
        from rasterio.transform import from_bounds
        from rasterio.warp import calculate_default_transform, reproject, Resampling

        crs_obj = CRS.from_user_input(data_crs)
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        west, east = min(xlim), max(xlim)
        south, north = min(ylim), max(ylim)

        to_3857 = Transformer.from_crs(crs_obj, "EPSG:3857", always_xy=True)
        xs, ys = to_3857.transform(
            [west, west, east, east],
            [south, north, south, north],
        )
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)

        from_3857 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
        lon_min, lat_min = from_3857.transform(minx, miny)
        lon_max, lat_max = from_3857.transform(maxx, maxy)
        zoom = PrecipMrms._choose_osm_zoom(lon_min, lat_min, lon_max, lat_max)
        x0, y0 = PrecipMrms._lonlat_to_tile(lon_min, lat_max, zoom)
        x1, y1 = PrecipMrms._lonlat_to_tile(lon_max, lat_min, zoom)
        max_index = (2 ** zoom) - 1
        x0, x1 = max(0, min(x0, max_index)), max(0, min(x1, max_index))
        y0, y1 = max(0, min(y0, max_index)), max(0, min(y1, max_index))
        if x1 < x0 or y1 < y0:
            return

        tile_size = 256
        mosaic = Image.new(
            "RGB",
            ((x1 - x0 + 1) * tile_size, (y1 - y0 + 1) * tile_size),
        )
        for tile_x in range(x0, x1 + 1):
            for tile_y in range(y0, y1 + 1):
                tile = PrecipMrms._fetch_osm_tile(zoom, tile_x, tile_y)
                mosaic.paste(tile, ((tile_x - x0) * tile_size, (tile_y - y0) * tile_size))

        left, bottom, _, _ = PrecipMrms._tile_bounds_mercator(x0, y1, zoom)
        _, _, right, top = PrecipMrms._tile_bounds_mercator(x1, y0, zoom)
        source = np.asarray(mosaic).transpose((2, 0, 1))
        src_transform = from_bounds(left, bottom, right, top, source.shape[2], source.shape[1])

        if crs_obj.to_epsg() == 3857:
            extent = (left, right, bottom, top)
            ax.imshow(source.transpose((1, 2, 0)), extent=extent, origin="upper", zorder=0)
            return

        dst_transform, width, height = calculate_default_transform(
            "EPSG:3857",
            crs_obj,
            source.shape[2],
            source.shape[1],
            left,
            bottom,
            right,
            top,
        )
        dest = np.zeros((3, height, width), dtype=np.uint8)
        for band_idx in range(3):
            reproject(
                source[band_idx],
                dest[band_idx],
                src_transform=src_transform,
                src_crs="EPSG:3857",
                dst_transform=dst_transform,
                dst_crs=crs_obj,
                resampling=Resampling.bilinear,
            )

        bounds = rasterio.transform.array_bounds(height, width, dst_transform)
        ax.imshow(
            dest.transpose((1, 2, 0)),
            extent=(bounds[0], bounds[2], bounds[1], bounds[3]),
            origin="upper",
            zorder=0,
        )

    @staticmethod
    def _choose_osm_zoom(
        lon_min: float,
        lat_min: float,
        lon_max: float,
        lat_max: float,
        max_tiles: int = 24,
    ) -> int:
        for zoom in range(14, 5, -1):
            x0, y0 = PrecipMrms._lonlat_to_tile(lon_min, lat_max, zoom)
            x1, y1 = PrecipMrms._lonlat_to_tile(lon_max, lat_min, zoom)
            tile_count = (abs(x1 - x0) + 1) * (abs(y1 - y0) + 1)
            if tile_count <= max_tiles:
                return zoom
        return 6

    @staticmethod
    def _lonlat_to_tile(lon: float, lat: float, zoom: int) -> Tuple[int, int]:
        import math

        lat = max(min(float(lat), 85.05112878), -85.05112878)
        lon = max(min(float(lon), 180.0), -180.0)
        n = 2 ** zoom
        x_tile = int((lon + 180.0) / 360.0 * n)
        lat_rad = math.radians(lat)
        y_tile = int(
            (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi)
            / 2.0
            * n
        )
        return x_tile, y_tile

    @staticmethod
    def _tile_bounds_mercator(x_tile: int, y_tile: int, zoom: int) -> Tuple[float, float, float, float]:
        origin_shift = 20037508.342789244
        n = 2 ** zoom
        tile_span = 2 * origin_shift / n
        left = -origin_shift + x_tile * tile_span
        right = -origin_shift + (x_tile + 1) * tile_span
        top = origin_shift - y_tile * tile_span
        bottom = origin_shift - (y_tile + 1) * tile_span
        return left, bottom, right, top

    @staticmethod
    def _fetch_osm_tile(zoom: int, x_tile: int, y_tile: int) -> Any:
        from io import BytesIO

        from PIL import Image
        import requests

        key = (zoom, x_tile, y_tile)
        if key in _OSM_TILE_CACHE:
            return _OSM_TILE_CACHE[key].copy()

        url = f"https://tile.openstreetmap.org/{zoom}/{x_tile}/{y_tile}.png"
        response = requests.get(
            url,
            headers={"User-Agent": "ras-commander MRMS notebook/0.96"},
            timeout=20,
        )
        response.raise_for_status()
        tile = Image.open(BytesIO(response.content)).convert("RGB")
        _OSM_TILE_CACHE[key] = tile
        return tile.copy()

    @staticmethod
    def _plot_boundary(
        ax: Any,
        boundary: Optional[Any],
        target_crs: Optional[Any] = None,
        color: str = "black",
        linewidth: float = 1.0,
        zorder: int = 4,
    ) -> None:
        if boundary is None:
            return

        if isinstance(boundary, (str, Path)):
            try:
                import geopandas as gpd

                gdf = gpd.read_file(boundary)
                if target_crs is not None and gdf.crs is not None:
                    gdf = gdf.to_crs(target_crs)
                gdf.boundary.plot(ax=ax, color=color, linewidth=linewidth, zorder=zorder)
                return
            except Exception as exc:
                logger.warning("Could not plot boundary file %s: %s", boundary, exc)
                return

        if isinstance(boundary, tuple) and len(boundary) == 4:
            west, south, east, north = boundary
            ax.plot(
                [west, east, east, west, west],
                [south, south, north, north, south],
                color=color,
                linewidth=linewidth,
                zorder=zorder,
            )
            return

        if hasattr(boundary, "boundary") and hasattr(boundary.boundary, "plot"):
            plot_boundary = boundary
            if target_crs is not None and getattr(plot_boundary, "crs", None) is not None:
                plot_boundary = plot_boundary.to_crs(target_crs)
            plot_boundary.boundary.plot(ax=ax, color=color, linewidth=linewidth, zorder=zorder)
            return

        geom = getattr(boundary, "geometry", boundary)
        if hasattr(geom, "exterior"):
            x, y = geom.exterior.xy
            ax.plot(x, y, color=color, linewidth=linewidth, zorder=zorder)

    @staticmethod
    def _plot_pump_stations(
        ax: Any,
        pump_stations: Optional[Any],
        target_crs: Optional[Any] = None,
    ) -> None:
        if pump_stations is None:
            return

        try:
            import geopandas as gpd

            if isinstance(pump_stations, (str, Path)):
                pumps = gpd.read_file(pump_stations)
            else:
                pumps = pump_stations

            if getattr(pumps, "empty", False):
                return
            if target_crs is not None and getattr(pumps, "crs", None) is not None:
                pumps = pumps.to_crs(target_crs)

            label_column = next(
                (column for column in ("Name", "name", "station_id") if column in pumps.columns),
                None,
            )
            pumps.plot(
                ax=ax,
                marker="^",
                color="#d7191c",
                edgecolor="white",
                linewidth=0.7,
                markersize=45,
                zorder=6,
            )
            for idx, row in pumps.iterrows():
                label = str(row[label_column]) if label_column else f"Pump {idx + 1}"
                point = row.geometry
                ax.annotate(
                    label,
                    xy=(point.x, point.y),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=7,
                    color="black",
                    bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none", "pad": 1.5},
                    zorder=7,
                )
        except Exception as exc:
            logger.warning("Could not plot pump stations: %s", exc)
