"""
AbmHyetographGrid: Generate gridded Alternating Block Method hyetographs from NOAA Atlas 14.

Implements per-pixel temporal distribution using the Alternating Block Method
(Chow, Maidment, Mays 1988), outputting to NetCDF for HEC-RAS rain-on-grid.

Implements the standard ABM approach as applied to gridded NOAA Atlas 14 PFE data.

Example (Auto-download)::

    from ras_commander.precip import AbmHyetographGrid

    output = AbmHyetographGrid.generate(
        bounds=(-95.5, 29.5, -95.0, 30.0),  # (west, south, east, north) in decimal degrees
        ari_years=100,
        storm_duration_hours=24,
        timestep_minutes=15,
        peak_position_percent=50.0,
        output_netcdf='houston_100yr_24hr_abm.nc',
    )
    print(f"Output: {output}")

Example (Pre-downloaded .asc files from NOAA Atlas 14)::

    asc_files = {
        5/60: 'atlas14_5min_100yr.asc',
        10/60: 'atlas14_10min_100yr.asc',
        15/60: 'atlas14_15min_100yr.asc',
        30/60: 'atlas14_30min_100yr.asc',
        1.0:   'atlas14_1hr_100yr.asc',
        2.0:   'atlas14_2hr_100yr.asc',
        6.0:   'atlas14_6hr_100yr.asc',
        12.0:  'atlas14_12hr_100yr.asc',
        24.0:  'atlas14_24hr_100yr.asc',
    }
    output = AbmHyetographGrid.generate_from_asc_files(
        asc_files=asc_files,
        ari_years=100,
        storm_duration_hours=24,
        timestep_minutes=15,
    )
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from ..LoggingConfig import get_logger, log_call
from .Atlas14Grid import Atlas14Grid
from .StormGenerator import StormGenerator

logger = get_logger(__name__)


class AbmHyetographGrid:
    """
    Generate gridded ABM hyetographs from NOAA Atlas 14 data.

    Implements per-pixel Alternating Block Method temporal distribution across
    a spatial grid, outputting a NetCDF file with dimensions (time, lat, lon)
    suitable for HEC-RAS rain-on-grid 2D simulations.

    Algorithm (Chow, Maidment, Mays 1988 - Extended to Grid):
        For each pixel:
        1. Get depth-duration curve from NOAA Atlas 14 (target ARI)
        2. Interpolate cumulative depths at each computation interval (log-log)
        3. Compute incremental depths for each interval
        4. Sort blocks in descending order
        5. Place peak block at desired position
        6. Arrange remaining blocks alternately left/right of peak (left first)

    Data Sources:
    - Durations >= 1hr: NOAA Atlas 14 CONUS NetCDF via Atlas14Grid (HTTP range requests)
    - Sub-hourly durations (< 1hr): NOAA HDSC API centroid DDF ratios scaled to grid

    Vectorization:
        The ABM is fully vectorized across all grid pixels using numpy advanced
        indexing. The placement array ``positions[rank] = output_index`` enables
        a single assignment ``abm_flat[:, positions] = sorted_desc`` to place all
        ranked blocks for all pixels simultaneously.

    Note:
        This class uses static methods and should not be instantiated.
    """

    CONUS_RETURN_PERIODS = [2, 5, 10, 25, 50, 100, 200, 500, 1000]
    CONUS_DURATIONS_HR = [1, 2, 3, 6, 12, 24, 48, 72, 96, 168]
    SUBHOURLY_DURATIONS_HR = [5/60, 10/60, 15/60, 30/60]

    @staticmethod
    @log_call
    def to_ras_netcdf(
        abm_netcdf: Union[str, Path],
        output_netcdf: Union[str, Path],
        start_time: Union[str, datetime, pd.Timestamp],
        target_crs: str = "EPSG:5070",
        resolution: Optional[float] = None,
        output_variable: str = "APCP_surface",
        end_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
    ) -> Path:
        """Convert an ABM depth grid to a HEC-RAS GDAL NetCDF forcing file.

        :meth:`generate` writes one incremental precipitation depth in inches
        for each relative-time interval on a WGS84 latitude/longitude grid.
        HEC-RAS' imported-raster workflow instead consumes absolute timestamps,
        projected ``x``/``y`` coordinates, and precipitation rates. This method
        performs that conversion without changing the source design-storm file.

        A zero-rate frame is written at ``start_time``. Each source increment is
        then assigned to its interval-end timestamp and converted to ``mm/hr``.
        This convention preserves every incremental block when
        :meth:`ras_commander.RasUnsteady.set_gridded_precipitation` integrates
        the rate frames into cumulative HDF precipitation.

        Parameters
        ----------
        abm_netcdf : str or Path
            NetCDF created by :meth:`generate` or
            :meth:`generate_from_asc_files`.
        output_netcdf : str or Path
            Destination for the HEC-RAS-compatible NetCDF.
        start_time : str, datetime, or pandas.Timestamp
            Timezone-naive simulation time at the start of the first interval.
        target_crs : str, default "EPSG:5070"
            Projected output CRS. EPSG:5070 is the HEC-RAS SHG convention.
        resolution : float, optional
            Output cell size in target-CRS units. When omitted, GDAL derives a
            resolution from the source grid to avoid forced downsampling.
        output_variable : str, default "APCP_surface"
            NetCDF variable name selected by HEC-RAS.
        end_time : str, datetime, or pandas.Timestamp, optional
            Timezone-naive forcing end. When later than the natural storm end,
            zero-rate frames are appended at the source timestep through this
            exact timestamp. The value must not precede the storm end and must
            align with the source timestep.

        Returns
        -------
        Path
            Resolved path to the converted NetCDF.

        Raises
        ------
        FileNotFoundError
            If ``abm_netcdf`` does not exist.
        ValueError
            If source dimensions, units, times, values, CRS, resolution, or
            converted depth-conservation checks are invalid.
        ImportError
            If xarray, netCDF4, rasterio, or pyproj is unavailable.
        """
        try:
            import netCDF4  # noqa: F401
            import xarray as xr
            from pyproj import CRS
            from rasterio.enums import Resampling
            from rasterio.transform import from_origin
            from rasterio.warp import calculate_default_transform, reproject
        except ImportError as exc:
            raise ImportError(
                "xarray, netCDF4, rasterio, and pyproj are required for "
                "HEC-RAS NetCDF conversion. Install ras-commander[notebooks]."
            ) from exc

        source_path = Path(abm_netcdf).resolve()
        output_path = Path(output_netcdf).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"ABM NetCDF not found: {source_path}")
        if source_path == output_path:
            raise ValueError("output_netcdf must differ from abm_netcdf")

        output_variable = str(output_variable).strip()
        if not output_variable:
            raise ValueError("output_variable must not be empty")

        try:
            output_crs = CRS.from_user_input(target_crs)
        except Exception as exc:
            raise ValueError(f"Invalid target_crs: {target_crs!r}") from exc
        if not output_crs.is_projected:
            raise ValueError("target_crs must be a projected coordinate system")

        if resolution is not None:
            resolution = float(resolution)
            if not np.isfinite(resolution) or resolution <= 0:
                raise ValueError("resolution must be a finite positive value")

        try:
            start_timestamp = pd.Timestamp(start_time)
        except (TypeError, ValueError) as exc:
            raise ValueError("start_time must be a valid timestamp") from exc
        if pd.isna(start_timestamp):
            raise ValueError("start_time must be a valid timestamp")
        if start_timestamp.tzinfo is not None:
            raise ValueError(
                "start_time must be timezone-naive to match HEC-RAS plan times"
            )

        forcing_end_timestamp = None
        if end_time is not None:
            try:
                forcing_end_timestamp = pd.Timestamp(end_time)
            except (TypeError, ValueError) as exc:
                raise ValueError("end_time must be a valid timestamp") from exc
            if pd.isna(forcing_end_timestamp):
                raise ValueError("end_time must be a valid timestamp")
            if forcing_end_timestamp.tzinfo is not None:
                raise ValueError(
                    "end_time must be timezone-naive to match HEC-RAS plan times"
                )

        try:
            source_ds = xr.open_dataset(
                source_path,
                engine="netcdf4",
                decode_timedelta=False,
            )
        except ImportError as exc:
            raise ImportError(
                "netCDF4 is required for HEC-RAS NetCDF conversion. "
                "Install ras-commander[notebooks]."
            ) from exc

        try:
            if "precip_incremental" not in source_ds.data_vars:
                raise ValueError(
                    "ABM NetCDF must contain a 'precip_incremental' variable"
                )

            incremental = source_ds["precip_incremental"]
            required_dims = {"time", "lat", "lon"}
            if set(incremental.dims) != required_dims or incremental.ndim != 3:
                raise ValueError(
                    "precip_incremental must have exactly time, lat, and lon dimensions"
                )
            incremental = incremental.transpose("time", "lat", "lon").load()

            for coord_name in ("time", "lat", "lon"):
                if coord_name not in source_ds.coords:
                    raise ValueError(f"ABM NetCDF is missing {coord_name!r} coordinates")

            units = str(incremental.attrs.get("units", "")).strip().lower()
            if units not in {"in", "inch", "inches"}:
                raise ValueError(
                    "precip_incremental units must be inches; "
                    f"found {incremental.attrs.get('units')!r}"
                )

            time_coord = source_ds["time"]
            time_units = str(time_coord.attrs.get("units", "")).strip().lower()
            if time_units not in {"h", "hour", "hours", "hr", "hrs"}:
                raise ValueError(
                    "ABM time coordinate units must be hours; "
                    f"found {time_coord.attrs.get('units')!r}"
                )
            if not np.issubdtype(time_coord.dtype, np.number):
                raise ValueError(
                    "ABM time coordinate must contain numeric relative-hour values"
                )

            time_values = np.asarray(time_coord.values, dtype=np.float64)
            if time_values.size < 2 or not np.all(np.isfinite(time_values)):
                raise ValueError("ABM time coordinate must contain at least two finite values")
            if not np.isclose(time_values[0], 0.0, atol=1e-9):
                raise ValueError("ABM time coordinate must start at 0 hours")
            time_deltas = np.diff(time_values)
            if np.any(time_deltas <= 0) or not np.allclose(
                time_deltas,
                time_deltas[0],
                rtol=1e-7,
                atol=1e-9,
            ):
                raise ValueError("ABM time coordinate must be strictly increasing and regular")
            interval_hours = float(time_deltas[0])

            coordinates = {}
            for coord_name in ("lat", "lon"):
                coord = np.asarray(source_ds[coord_name].values, dtype=np.float64)
                if coord.size < 2 or not np.all(np.isfinite(coord)):
                    raise ValueError(
                        f"ABM {coord_name} coordinate must contain at least two finite values"
                    )
                coord_deltas = np.diff(coord)
                if not (np.all(coord_deltas > 0) or np.all(coord_deltas < 0)):
                    raise ValueError(f"ABM {coord_name} coordinate must be monotonic")
                if not np.allclose(
                    coord_deltas,
                    coord_deltas[0],
                    # Atlas 14 coordinate centers originate as float32 values;
                    # allow their sub-0.1% quantization without accepting a
                    # materially variable raster spacing.
                    rtol=2e-3,
                    atol=1e-9,
                ):
                    raise ValueError(
                        f"ABM {coord_name} coordinate must be regularly spaced"
                    )
                coordinates[coord_name] = coord

            lat = coordinates["lat"]
            lon = coordinates["lon"]
            if np.any((lat < -90.0) | (lat > 90.0)):
                raise ValueError("ABM latitude values must be within [-90, 90]")
            if np.any((lon < -180.0) | (lon > 180.0)):
                raise ValueError("ABM longitude values must be within [-180, 180]")

            incremental_values = np.asarray(incremental.values, dtype=np.float64)
            finite_mask = np.isfinite(incremental_values)
            if not finite_mask.any():
                raise ValueError("precip_incremental contains no finite precipitation values")
            if np.any(incremental_values[finite_mask] < 0):
                raise ValueError("precip_incremental contains negative precipitation depths")
        finally:
            source_ds.close()

        lon_order = np.argsort(lon)
        lat_order = np.argsort(lat)[::-1]
        lon = lon[lon_order]
        lat = lat[lat_order]
        incremental_values = incremental_values[:, lat_order, :][:, :, lon_order]

        x_resolution = float(abs(lon[1] - lon[0]))
        y_resolution = float(abs(lat[1] - lat[0]))
        source_transform = from_origin(
            float(lon[0] - x_resolution / 2.0),
            float(lat[0] + y_resolution / 2.0),
            x_resolution,
            y_resolution,
        )
        source_height, source_width = incremental_values.shape[1:]
        source_bounds = (
            float(lon[0] - x_resolution / 2.0),
            float(lat[-1] - y_resolution / 2.0),
            float(lon[-1] + x_resolution / 2.0),
            float(lat[0] + y_resolution / 2.0),
        )

        transform_kwargs = {}
        if resolution is not None:
            transform_kwargs["resolution"] = resolution
        target_transform, target_width, target_height = calculate_default_transform(
            "EPSG:4326",
            output_crs.to_wkt(),
            source_width,
            source_height,
            *source_bounds,
            **transform_kwargs,
        )
        if target_width < 1 or target_height < 1:
            raise ValueError("Converted NetCDF has an empty projected grid")

        source_rates_mm_hr = incremental_values * 25.4 / interval_hours
        projected_rates = np.full(
            (source_rates_mm_hr.shape[0], target_height, target_width),
            np.nan,
            dtype=np.float64,
        )
        for index, source_rate in enumerate(source_rates_mm_hr):
            reproject(
                source=source_rate,
                destination=projected_rates[index],
                src_transform=source_transform,
                src_crs="EPSG:4326",
                src_nodata=np.nan,
                dst_transform=target_transform,
                dst_crs=output_crs.to_wkt(),
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
                init_dest_nodata=True,
            )
        # Depth verification must reflect the float32 rates actually written.
        projected_rates = projected_rates.astype(np.float32)

        expected_total_mm = np.full(
            (target_height, target_width),
            np.nan,
            dtype=np.float64,
        )
        reproject(
            source=np.sum(incremental_values, axis=0) * 25.4,
            destination=expected_total_mm,
            src_transform=source_transform,
            src_crs="EPSG:4326",
            src_nodata=np.nan,
            dst_transform=target_transform,
            dst_crs=output_crs.to_wkt(),
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
            init_dest_nodata=True,
        )
        converted_total_mm = (
            np.sum(projected_rates.astype(np.float64), axis=0) * interval_hours
        )

        interval_delta = pd.Timedelta(hours=interval_hours)
        interval_ends = pd.date_range(
            start=start_timestamp + interval_delta,
            periods=projected_rates.shape[0],
            freq=interval_delta,
        )
        natural_storm_end = interval_ends[-1]

        if forcing_end_timestamp is None:
            forcing_end_timestamp = natural_storm_end
        if forcing_end_timestamp < natural_storm_end:
            raise ValueError(
                "end_time must be on or after the natural storm end "
                f"({natural_storm_end.isoformat()})"
            )

        tail_duration = forcing_end_timestamp - natural_storm_end
        if tail_duration.value % interval_delta.value != 0:
            raise ValueError(
                "end_time must align with the source timestep "
                f"({interval_delta.total_seconds() / 60.0:g} minutes)"
            )
        zero_tail_frames = int(tail_duration.value // interval_delta.value)

        valid_depth = np.isfinite(expected_total_mm) & np.isfinite(
            converted_total_mm
        )
        if not valid_depth.any():
            raise ValueError("Converted NetCDF has no valid projected precipitation cells")
        max_depth_error_mm = float(
            np.nanmax(
                np.abs(
                    converted_total_mm[valid_depth]
                    - expected_total_mm[valid_depth]
                )
            )
        )
        max_expected_mm = float(np.nanmax(expected_total_mm[valid_depth]))
        depth_tolerance_mm = max(1e-4, max_expected_mm * 1e-6)
        if max_depth_error_mm > depth_tolerance_mm:
            raise ValueError(
                "Projected precipitation failed depth conservation: "
                f"max error {max_depth_error_mm:.6f} mm exceeds "
                f"{depth_tolerance_mm:.6f} mm"
            )

        valid_coverage = np.isfinite(projected_rates).any(axis=0)
        valid_cells = int(valid_coverage.sum())
        total_cells = int(valid_coverage.size)
        valid_fraction = valid_cells / total_cells
        if valid_cells == 0:
            raise ValueError("Converted NetCDF has no valid forcing coverage")

        forcing_rates = projected_rates
        forcing_times = interval_ends
        if zero_tail_frames:
            zero_rate = np.where(valid_coverage, 0.0, np.nan).astype(np.float32)
            zero_tail = np.repeat(
                zero_rate[np.newaxis, :, :],
                zero_tail_frames,
                axis=0,
            )
            forcing_rates = np.concatenate([projected_rates, zero_tail], axis=0)
            tail_times = pd.date_range(
                start=natural_storm_end + interval_delta,
                periods=zero_tail_frames,
                freq=interval_delta,
            )
            forcing_times = interval_ends.append(tail_times)

        zero_frame = np.where(valid_coverage, 0.0, np.nan).astype(np.float32)[
            np.newaxis, :, :
        ]
        output_rates = np.concatenate([zero_frame, forcing_rates], axis=0)
        output_times = pd.DatetimeIndex([start_timestamp]).append(forcing_times)
        x = target_transform.c + target_transform.a * (
            np.arange(target_width, dtype=np.float64) + 0.5
        )
        y = target_transform.f + target_transform.e * (
            np.arange(target_height, dtype=np.float64) + 0.5
        )

        crs_wkt = output_crs.to_wkt()
        spatial_ref_attrs = output_crs.to_cf()
        spatial_ref_attrs.update(
            {
                "crs_wkt": crs_wkt,
                "spatial_ref": crs_wkt,
                "GeoTransform": " ".join(
                    f"{value:.15g}" for value in target_transform.to_gdal()
                ),
            }
        )
        output_ds = xr.Dataset(
            data_vars={
                output_variable: (
                    ("time", "y", "x"),
                    output_rates,
                    {
                        "long_name": "Atlas 14 ABM precipitation rate",
                        "units": "mm/hr",
                        "grid_mapping": "spatial_ref",
                        "cell_methods": "time: mean (interval ending)",
                        "source": (
                            "NOAA Atlas 14 ABM incremental precipitation depth"
                        ),
                    },
                ),
                "spatial_ref": ((), np.int32(0), spatial_ref_attrs),
            },
            coords={"time": output_times, "x": x, "y": y},
            attrs={
                "Conventions": "CF-1.8",
                "title": "HEC-RAS Atlas 14 ABM gridded precipitation forcing",
                "source_file": source_path.name,
                "storm_start": start_timestamp.isoformat(),
                "storm_end": natural_storm_end.isoformat(),
                "forcing_end": forcing_end_timestamp.isoformat(),
                "zero_tail_hours": tail_duration.total_seconds() / 3600.0,
                "zero_tail_frames": zero_tail_frames,
                "interval_minutes": interval_hours * 60.0,
                "source_depth_units": "inches",
                "forcing_rate_units": "mm/hr",
                "target_crs": output_crs.to_string(),
                "valid_coverage_fraction": valid_fraction,
                "depth_conservation_max_error_mm": max_depth_error_mm,
            },
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        encoding = {
            output_variable: {
                "zlib": True,
                "complevel": 4,
                "dtype": "float32",
                "_FillValue": np.float32(-9999.0),
            }
        }
        output_ds.to_netcdf(
            output_path,
            engine="netcdf4",
            format="NETCDF4",
            encoding=encoding,
        )

        logger.info(
            "Prepared HEC-RAS Atlas 14 forcing %s: %d storm intervals, "
            "%d zero-tail frames (%g hr), %dx%d cells, %.1f%% valid "
            "coverage, max depth error %.6f mm",
            output_path.name,
            projected_rates.shape[0],
            zero_tail_frames,
            tail_duration.total_seconds() / 3600.0,
            target_height,
            target_width,
            valid_fraction * 100.0,
            max_depth_error_mm,
        )
        logger.debug("HEC-RAS Atlas 14 forcing path: %s", output_path)
        return output_path

    @staticmethod
    @log_call
    def generate(
        bounds: Tuple[float, float, float, float],
        ari_years: int,
        storm_duration_hours: float = 24.0,
        timestep_minutes: int = 15,
        peak_position_percent: float = 50.0,
        output_netcdf: Union[str, Path] = 'abm_hyetograph.nc',
        buffer_percent: float = 0.05,
        include_subhourly: bool = True,
    ) -> Path:
        """
        Generate gridded ABM hyetographs using NOAA Atlas 14 (auto-download).

        Downloads NOAA Atlas 14 CONUS NetCDF data for the specified bounds via
        HTTP byte-range requests, then computes per-pixel ABM temporal distributions.
        Sub-hourly depth data (< 1hr intervals) is derived from centroid DDF ratios.

        Args:
            bounds: (west, south, east, north) in decimal degrees (WGS84)
            ari_years: Average recurrence interval in years.
                Valid: 2, 5, 10, 25, 50, 100, 200, 500, 1000
            storm_duration_hours: Total storm duration in hours (default: 24).
                Must be >= 1hr (CONUS NetCDF minimum). For sub-hourly storms
                use generate_from_asc_files().
            timestep_minutes: Computation interval in minutes (default: 15).
                Must evenly divide storm_duration_hours * 60.
            peak_position_percent: Peak block position as % of storm duration.
                Typical values: 25, 33, 50, 67, 75 (default: 50)
            output_netcdf: Output NetCDF file path (default: 'abm_hyetograph.nc')
            buffer_percent: Spatial buffer fraction beyond bounds (default: 0.05)
            include_subhourly: Include sub-hourly intervals via centroid DDF ratios.
                Required when timestep_minutes < 60 (default: True)

        Returns:
            Path: Path to output NetCDF file

        Raises:
            ValueError: If ari_years not in NOAA catalog, or timestep does not
                evenly divide storm_duration_hours
            ImportError: If xarray or netCDF4 not installed
        """
        if ari_years not in AbmHyetographGrid.CONUS_RETURN_PERIODS:
            raise ValueError(
                f"ari_years={ari_years} not in NOAA Atlas 14 CONUS catalog. "
                f"Valid values: {AbmHyetographGrid.CONUS_RETURN_PERIODS}"
            )

        timestep_hours = timestep_minutes / 60.0
        n_intervals = int(round(storm_duration_hours / timestep_hours))
        if abs(n_intervals * timestep_hours - storm_duration_hours) > 1e-6:
            raise ValueError(
                f"timestep_minutes={timestep_minutes} does not evenly divide "
                f"storm_duration_hours={storm_duration_hours}. "
                f"Choose a timestep that divides evenly into the storm duration."
            )

        # Which hourly durations to download (up to storm_duration_hours plus one beyond)
        hourly_durations = [d for d in AbmHyetographGrid.CONUS_DURATIONS_HR
                            if d <= storm_duration_hours]
        beyond = [d for d in AbmHyetographGrid.CONUS_DURATIONS_HR
                  if d > storm_duration_hours]
        if beyond:
            hourly_durations.append(beyond[0])

        if not hourly_durations:
            raise ValueError(
                f"storm_duration_hours={storm_duration_hours} is less than the "
                f"minimum CONUS NetCDF duration (1 hr). "
                f"Use generate_from_asc_files() for sub-hourly-only storms."
            )

        logger.info(
            f"Generating ABM grid: ARI={ari_years}yr, duration={storm_duration_hours}hr, "
            f"dt={timestep_minutes}min, peak@{peak_position_percent}%, bounds={bounds}"
        )

        # Download from NOAA Atlas 14 CONUS NetCDF
        logger.debug(f"Downloading Atlas 14 data for {len(hourly_durations)} hourly durations...")
        pfe_data = Atlas14Grid.get_pfe_for_bounds(
            bounds=bounds,
            durations=hourly_durations,
            buffer_percent=buffer_percent * 100,  # get_pfe_for_bounds uses 0-100
        )

        lats = pfe_data['lat']
        lons = pfe_data['lon']
        ari_array = pfe_data['ari']
        ari_idx = int(np.argmin(np.abs(ari_array - ari_years)))
        logger.debug(f"Using ARI index {ari_idx} → {ari_array[ari_idx]:.0f}-year return period")

        # Extract per-duration grids for target ARI
        depth_grids: Dict[float, np.ndarray] = {}
        for dur in hourly_durations:
            key = f'pfe_{dur}hr'
            if key in pfe_data:
                grid = pfe_data[key][:, :, ari_idx].astype(np.float64)
                depth_grids[float(dur)] = grid
            else:
                logger.warning(f"Duration {dur}hr not found in pfe_data (key '{key}' missing)")

        # Build sub-hourly grids via centroid DDF ratios
        if include_subhourly and timestep_minutes < 60:
            centroid_lat = (bounds[1] + bounds[3]) / 2.0
            centroid_lon = (bounds[0] + bounds[2]) / 2.0

            subhourly_durs = [d for d in AbmHyetographGrid.SUBHOURLY_DURATIONS_HR
                              if d < storm_duration_hours]

            if subhourly_durs and 1.0 in depth_grids:
                logger.debug(
                    f"Building {len(subhourly_durs)} sub-hourly grids via centroid DDF ratios "
                    f"({centroid_lat:.4f}N, {centroid_lon:.4f}E)..."
                )
                subhourly_grids = AbmHyetographGrid._build_subhourly_grids(
                    centroid_lat=centroid_lat,
                    centroid_lon=centroid_lon,
                    ari_years=ari_years,
                    subhourly_durations=subhourly_durs,
                    reference_duration_hr=1.0,
                    reference_grid=depth_grids[1.0],
                )
                depth_grids.update(subhourly_grids)
            elif subhourly_durs and 1.0 not in depth_grids:
                logger.warning(
                    "1-hr duration grid not available for sub-hourly ratio computation. "
                    "Sub-hourly intervals will use log-log extrapolation from available durations."
                )

        # Compute ABM grid → shape (lat, lon, n_intervals)
        logger.debug(f"Computing ABM temporal distribution across grid ({n_intervals} intervals)...")
        incremental_grid = AbmHyetographGrid._compute_abm_grid(
            depth_grids=depth_grids,
            storm_duration_hours=storm_duration_hours,
            timestep_minutes=timestep_minutes,
            peak_position_percent=peak_position_percent,
        )

        output_path = AbmHyetographGrid._write_netcdf(
            incremental_grid=incremental_grid,
            lat=lats,
            lon=lons,
            output_netcdf=output_netcdf,
            timestep_minutes=timestep_minutes,
            ari_years=ari_years,
            storm_duration_hours=storm_duration_hours,
            peak_position_percent=peak_position_percent,
            source='NOAA Atlas 14 CONUS NetCDF + centroid DDF ratios (AbmHyetographGrid)',
        )

        logger.info("ABM grid complete → %s", output_path.name)
        return output_path

    @staticmethod
    @log_call
    def generate_from_asc_files(
        asc_files: Dict[float, Union[str, Path]],
        ari_years: int,
        storm_duration_hours: float,
        timestep_minutes: int = 15,
        peak_position_percent: float = 50.0,
        output_netcdf: Union[str, Path] = 'abm_hyetograph.nc',
        nodata_value: Optional[float] = None,
        scale_factor: float = 0.01,
    ) -> Path:
        """
        Generate gridded ABM hyetographs from pre-downloaded NOAA Atlas 14 .asc files.

        Uses ESRI ASCII raster grids downloaded from NOAA Atlas 14. Values in .asc
        files are in hundredths of inches by default; scale_factor=0.01 converts to
        inches.

        Args:
            asc_files: Dict mapping duration_hours (float) to .asc file path.
                Keys are durations in hours (e.g., 5/60, 0.25, 1.0, 6.0, 24.0).
                Values should span all sub-durations up to storm_duration_hours.
                Example: {5/60: 'atlas14_5min_100yr.asc', 1.0: '1hr_100yr.asc'}
            ari_years: Average recurrence interval in years (used for metadata only;
                the .asc files must already correspond to this return period)
            storm_duration_hours: Total storm duration in hours
            timestep_minutes: Computation interval in minutes (default: 15).
                Must evenly divide storm_duration_hours * 60.
            peak_position_percent: Peak block position as % of storm duration (default: 50)
            output_netcdf: Output NetCDF file path (default: 'abm_hyetograph.nc')
            nodata_value: Override NODATA value from .asc header (post scale_factor).
                If None, reads NODATA_value from header.
            scale_factor: Multiplier to convert raw .asc values to inches (default: 0.01)

        Returns:
            Path: Path to output NetCDF file

        Raises:
            FileNotFoundError: If any .asc file does not exist
            ValueError: If .asc files have incompatible extents/resolutions or
                timestep does not evenly divide storm_duration_hours
        """
        timestep_hours = timestep_minutes / 60.0
        n_intervals = int(round(storm_duration_hours / timestep_hours))
        if abs(n_intervals * timestep_hours - storm_duration_hours) > 1e-6:
            raise ValueError(
                f"timestep_minutes={timestep_minutes} does not evenly divide "
                f"storm_duration_hours={storm_duration_hours}"
            )

        depth_grids: Dict[float, np.ndarray] = {}
        lat_ref: Optional[np.ndarray] = None
        lon_ref: Optional[np.ndarray] = None

        for dur_hr, asc_path in sorted(asc_files.items()):
            asc_path = Path(asc_path)
            if not asc_path.exists():
                raise FileNotFoundError(f"Atlas 14 .asc file not found: {asc_path}")

            data, lat_1d, lon_1d, nodata_from_header = AbmHyetographGrid._load_asc_file(
                asc_path, scale_factor=scale_factor
            )

            nd = nodata_value if nodata_value is not None else nodata_from_header
            data = np.where(data == nd, np.nan, data)

            if lat_ref is None:
                lat_ref = lat_1d
                lon_ref = lon_1d
            else:
                if not (np.allclose(lat_1d, lat_ref, atol=1e-6) and
                        np.allclose(lon_1d, lon_ref, atol=1e-6)):
                    raise ValueError(
                        f"Grid extent mismatch for {asc_path.name}. "
                        f"All .asc files must share the same extent and resolution."
                    )

            depth_grids[float(dur_hr)] = data
            logger.debug(
                f"Loaded {asc_path.name}: shape={data.shape}, "
                f"dur={dur_hr:.4f}hr, max={float(np.nanmax(data)):.3f}in"
            )

        if lat_ref is None:
            raise ValueError("No .asc files provided in asc_files dict")

        logger.info(
            f"Loaded {len(depth_grids)} duration grids from .asc files. "
            f"Computing ABM distribution ({n_intervals} intervals)..."
        )

        incremental_grid = AbmHyetographGrid._compute_abm_grid(
            depth_grids=depth_grids,
            storm_duration_hours=storm_duration_hours,
            timestep_minutes=timestep_minutes,
            peak_position_percent=peak_position_percent,
        )

        output_path = AbmHyetographGrid._write_netcdf(
            incremental_grid=incremental_grid,
            lat=lat_ref,
            lon=lon_ref,
            output_netcdf=output_netcdf,
            timestep_minutes=timestep_minutes,
            ari_years=ari_years,
            storm_duration_hours=storm_duration_hours,
            peak_position_percent=peak_position_percent,
            source='NOAA Atlas 14 ESRI ASCII raster grids (pre-downloaded, AbmHyetographGrid)',
        )

        logger.info(f"ABM grid (from .asc) complete → {output_path}")
        return output_path

    @staticmethod
    @log_call
    def verify_pixel(
        netcdf_path: Union[str, Path],
        lat: float,
        lon: float,
        tolerance_pct: float = 0.1,
    ) -> dict:
        """
        QC verification: internal consistency check for a pixel in the NetCDF output.

        Extracts the incremental time series for the nearest grid cell and verifies
        that its sum matches the stored cumulative depth at the final timestep.
        This validates depth conservation and NetCDF write integrity without
        requiring an external data source.

        The reference depth is taken directly from ``precip_cumulative[-1]`` in
        the NetCDF — this value is the Atlas 14 interpolated depth used during
        generation, so the check confirms that no depth was lost during the ABM
        rearrangement and float32 encoding.

        Args:
            netcdf_path: Path to NetCDF output from generate() or generate_from_asc_files()
            lat: Target latitude in decimal degrees
            lon: Target longitude in decimal degrees
            tolerance_pct: Maximum acceptable deviation as % of reference depth
                (default: 0.1% — float32 encoding introduces ~0.001–0.01% error)

        Returns:
            dict with keys:
                pixel_total_in (float): Sum of incremental depths at pixel
                reference_depth_in (float): Cumulative depth at final timestep from NetCDF
                error_pct (float): Absolute percentage deviation from reference
                passed (bool): True if error_pct <= tolerance_pct
                lat_actual (float): Latitude of the nearest grid cell used
                lon_actual (float): Longitude of the nearest grid cell used
                time_series (numpy.ndarray): Incremental depth series (inches/interval)

        Raises:
            ImportError: If xarray is not installed
        """
        try:
            import xarray as xr
        except ImportError:
            raise ImportError(
                "xarray required for verify_pixel. "
                "Install with: pip install xarray"
            )

        ds = xr.open_dataset(netcdf_path, decode_timedelta=False)

        lat_idx = int(np.argmin(np.abs(ds.lat.values - lat)))
        lon_idx = int(np.argmin(np.abs(ds.lon.values - lon)))

        lat_actual = float(ds.lat.values[lat_idx])
        lon_actual = float(ds.lon.values[lon_idx])
        time_series = ds['precip_incremental'].values[:, lat_idx, lon_idx].astype(np.float64)
        # Reference depth: cumulative depth at final timestep (same Atlas 14 source as generation)
        reference_depth = float(ds['precip_cumulative'].values[-1, lat_idx, lon_idx])
        ds.close()

        pixel_total = float(np.nansum(time_series))

        error_pct = (abs(pixel_total - reference_depth) / reference_depth * 100.0
                     if reference_depth > 1e-9 else 0.0)
        passed = error_pct <= tolerance_pct

        if passed:
            logger.info(
                f"QC PASS: pixel ({lat_actual:.4f}N, {lon_actual:.4f}E) "
                f"total={pixel_total:.4f}in, ref={reference_depth:.4f}in, "
                f"error={error_pct:.4f}%"
            )
        else:
            logger.warning(
                f"QC FAIL: pixel ({lat_actual:.4f}N, {lon_actual:.4f}E) "
                f"total={pixel_total:.4f}in, ref={reference_depth:.4f}in, "
                f"error={error_pct:.4f}% > tolerance={tolerance_pct}%"
            )

        return {
            'pixel_total_in': pixel_total,
            'reference_depth_in': reference_depth,
            'error_pct': error_pct,
            'passed': passed,
            'lat_actual': lat_actual,
            'lon_actual': lon_actual,
            'time_series': time_series,
        }

    @staticmethod
    def _build_subhourly_grids(
        centroid_lat: float,
        centroid_lon: float,
        ari_years: int,
        subhourly_durations: List[float],
        reference_duration_hr: float,
        reference_grid: np.ndarray,
    ) -> Dict[float, np.ndarray]:
        """
        Build sub-hourly depth grids via centroid DDF ratio scaling.

        Downloads sub-hourly DDF for the domain centroid via the NOAA HDSC API,
        computes ratio = D(sub_hr) / D(reference_hr) at the centroid, then
        scales the reference grid by this ratio to produce spatial sub-hourly grids.

        This centroid-ratio approach assumes the spatial pattern of sub-hourly
        depths mirrors the 1-hr pattern (valid for convective storms over typical
        project domains of 10-1000 km²).

        Args:
            centroid_lat: Domain centroid latitude for NOAA API query
            centroid_lon: Domain centroid longitude for NOAA API query
            ari_years: Average recurrence interval (years)
            subhourly_durations: List of sub-hourly durations in hours
                (e.g., [0.0833, 0.1667, 0.25, 0.5])
            reference_duration_hr: Reference hourly duration for ratio base (typically 1.0)
            reference_grid: Depth grid at reference_duration_hr, shape (lat, lon), inches

        Returns:
            Dict mapping duration_hours to scaled depth grid, shape (lat, lon), inches

        Raises:
            ValueError: If centroid reference depth is zero or negative
        """
        logger.debug(
            f"Downloading centroid DDF for sub-hourly scaling: "
            f"({centroid_lat:.4f}N, {centroid_lon:.4f}E), ARI={ari_years}yr"
        )

        ddf = StormGenerator.download_from_coordinates(centroid_lat, centroid_lon)

        # Reference depth at centroid
        D_ref, _ = StormGenerator.interpolate_depths(ddf, ari_years, reference_duration_hr)
        ref_depth_centroid = float(D_ref[-1])

        if ref_depth_centroid <= 1e-9:
            raise ValueError(
                f"Centroid reference depth is zero or negative at "
                f"({centroid_lat}, {centroid_lon}) for ARI={ari_years}yr, "
                f"reference_duration={reference_duration_hr}hr"
            )

        subhourly_grids: Dict[float, np.ndarray] = {}
        for dur_hr in subhourly_durations:
            D_sub, _ = StormGenerator.interpolate_depths(ddf, ari_years, dur_hr)
            subhr_depth_centroid = float(D_sub[-1])
            ratio = subhr_depth_centroid / ref_depth_centroid
            subhourly_grids[float(dur_hr)] = reference_grid * ratio
            logger.debug(
                f"Sub-hourly {dur_hr*60:.0f}min: centroid={subhr_depth_centroid:.4f}in, "
                f"ratio={ratio:.6f}"
            )

        return subhourly_grids

    @staticmethod
    def _compute_abm_grid(
        depth_grids: Dict[float, np.ndarray],
        storm_duration_hours: float,
        timestep_minutes: int,
        peak_position_percent: float,
    ) -> np.ndarray:
        """
        Vectorized ABM computation across all grid pixels.

        Performs per-pixel Alternating Block Method using numpy advanced indexing
        to process all grid cells simultaneously.

        Log-log interpolation is applied at each sub-duration timestep using
        searchsorted bracket finding, followed by vectorized interpolation
        across the entire (lat × lon) pixel dimension. The ABM placement is
        precomputed as a ``positions`` array and applied via a single numpy
        fancy-index assignment.

        Args:
            depth_grids: Dict mapping duration_hours to (lat, lon) depth arrays (inches)
            storm_duration_hours: Total storm duration in hours
            timestep_minutes: Computation interval in minutes
            peak_position_percent: Peak block position as % of storm duration

        Returns:
            numpy.ndarray: Incremental depths, shape (lat, lon, n_intervals), inches
        """
        timestep_hours = timestep_minutes / 60.0
        n_intervals = int(round(storm_duration_hours / timestep_hours))

        # Sort available durations; include one point beyond storm_duration for extrapolation
        all_durs = sorted(depth_grids.keys())
        valid_durs = [d for d in all_durs if d <= storm_duration_hours]
        beyond = [d for d in all_durs if d > storm_duration_hours]
        if beyond:
            valid_durs.append(beyond[0])

        if len(valid_durs) < 2:
            raise ValueError(
                f"Need at least 2 duration points for interpolation. "
                f"Got {len(valid_durs)} within/beyond storm_duration={storm_duration_hours}hr."
            )

        first_grid = depth_grids[valid_durs[0]]
        n_lat, n_lon = first_grid.shape
        n_pixels = n_lat * n_lon
        n_d = len(valid_durs)

        # Build 3D depth array (lat, lon, n_d) then reshape to (n_pixels, n_d)
        depth_3d = np.full((n_lat, n_lon, n_d), np.nan, dtype=np.float64)
        for j, dur in enumerate(valid_durs):
            if dur in depth_grids:
                depth_3d[:, :, j] = depth_grids[dur]

        depth_flat = depth_3d.reshape(n_pixels, n_d)

        # Log transform (guard against zero/nan)
        log_dur = np.log(np.array(valid_durs, dtype=np.float64))
        with np.errstate(divide='ignore', invalid='ignore'):
            log_depth_flat = np.where(depth_flat > 0, np.log(depth_flat), np.nan)

        # Compute target timestep cumulative times: dt, 2dt, ..., storm_duration
        target_times = np.arange(1, n_intervals + 1) * timestep_hours
        log_target_times = np.log(target_times)

        # Log-log interpolation: cumulative depth at each target time for all pixels
        # Result: (n_pixels, n_intervals)
        cumulative_flat = np.zeros((n_pixels, n_intervals), dtype=np.float64)

        for k, log_t in enumerate(log_target_times):
            j = int(np.searchsorted(log_dur, log_t, side='right')) - 1
            j = max(0, min(j, n_d - 2))

            log_t0 = log_dur[j]
            log_t1 = log_dur[j + 1]
            denom = log_t1 - log_t0
            w = (log_t - log_t0) / denom if abs(denom) > 1e-15 else 0.0

            log_d0 = log_depth_flat[:, j]      # (n_pixels,)
            log_d1 = log_depth_flat[:, j + 1]  # (n_pixels,)
            log_cum = log_d0 + w * (log_d1 - log_d0)

            with np.errstate(over='ignore'):
                cumulative_flat[:, k] = np.where(
                    np.isfinite(log_cum), np.exp(log_cum), np.nan
                )

        # Incremental depths: diff of cumulative (first interval = cumulative[0])
        incremental_flat = np.diff(cumulative_flat, prepend=0.0, axis=1)
        incremental_flat = np.maximum(incremental_flat, 0.0)  # clamp numerical artifacts

        # Precompute ABM placement positions
        central_index = int(round((peak_position_percent / 100.0) * n_intervals)) - 1
        central_index = max(0, min(central_index, n_intervals - 1))
        positions = AbmHyetographGrid._precompute_abm_positions(n_intervals, central_index)

        # Vectorized ABM: sort each row descending, place at precomputed positions
        # sorted_desc[:, 0] = max (peak), placed at positions[0] = central_index
        # sorted_desc[:, 1] = 2nd largest, placed at positions[1] = left of peak
        # sorted_desc[:, 2] = 3rd largest, placed at positions[2] = right of peak
        # etc.
        sorted_desc = np.sort(incremental_flat, axis=1)[:, ::-1]  # (n_pixels, n_intervals)
        abm_flat = np.zeros_like(incremental_flat)
        abm_flat[:, positions] = sorted_desc  # key vectorized step

        # Per-pixel depth conservation: scale so total == Atlas 14 depth at storm_duration
        reference_totals = cumulative_flat[:, -1]           # (n_pixels,) — cumul at last step
        computed_totals = abm_flat.sum(axis=1)              # (n_pixels,)
        scale = np.where(computed_totals > 1e-12, reference_totals / computed_totals, 1.0)
        abm_flat *= scale[:, np.newaxis]

        return abm_flat.reshape(n_lat, n_lon, n_intervals)

    @staticmethod
    def _precompute_abm_positions(n_intervals: int, central_index: int) -> np.ndarray:
        """
        Precompute ABM placement array: positions[rank] = output_index.

        Matches StormGenerator._assign_alternating_block() exactly:
          - rank 0 → central_index (peak/maximum block)
          - rank 1 (even, i=0) → central_index - 1 (left of peak)
          - rank 2 (odd,  i=1) → central_index + 1 (right of peak)
          - rank 3 (even, i=2) → central_index - 2
          - rank 4 (odd,  i=3) → central_index + 2
          - ...

        When one side is exhausted, continues on the remaining side.

        Args:
            n_intervals: Total number of time intervals
            central_index: Zero-based index of peak block position

        Returns:
            numpy.ndarray: Integer array of length n_intervals where
                positions[rank] gives the output time-step index for that rank
        """
        positions = np.zeros(n_intervals, dtype=int)
        positions[0] = central_index

        left = central_index - 1
        right = central_index + 1

        for rank in range(1, n_intervals):
            if left >= 0 and right < n_intervals:
                # Both sides still available — even ranks go left, odd go right
                if (rank - 1) % 2 == 0:
                    positions[rank] = left
                    left -= 1
                else:
                    positions[rank] = right
                    right += 1
            elif left >= 0:
                positions[rank] = left
                left -= 1
            elif right < n_intervals:
                positions[rank] = right
                right += 1
            # else: all positions exhausted (shouldn't happen for valid central_index)

        return positions

    @staticmethod
    def _write_netcdf(
        incremental_grid: np.ndarray,
        lat: np.ndarray,
        lon: np.ndarray,
        output_netcdf: Union[str, Path],
        timestep_minutes: int,
        ari_years: int,
        storm_duration_hours: float,
        peak_position_percent: float,
        source: str,
    ) -> Path:
        """
        Write ABM hyetograph grid to NetCDF4 with CF-1.8 conventions.

        Output dimensions: (time, lat, lon)
        Variables:
            - precip_incremental: Incremental depth per interval (inches)
            - precip_cumulative: Cumulative depth (inches)

        Args:
            incremental_grid: Incremental depth array, shape (lat, lon, n_intervals)
            lat: 1D latitude array (degrees_north)
            lon: 1D longitude array (degrees_east)
            output_netcdf: Output file path
            timestep_minutes: Time step in minutes
            ari_years: Return period for metadata
            storm_duration_hours: Storm duration for metadata
            peak_position_percent: Peak position for metadata
            source: Data source description for metadata

        Returns:
            Path: Resolved absolute output path

        Raises:
            ImportError: If xarray is not installed
        """
        try:
            import xarray as xr
        except ImportError:
            raise ImportError(
                "xarray required for NetCDF output. "
                "Install with: pip install ras-commander[precip]"
            )

        output_path = Path(output_netcdf).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        n_lat, n_lon, n_intervals = incremental_grid.shape
        timestep_hours = timestep_minutes / 60.0

        # Time coordinate: start of each interval in hours since storm start
        time_hours = np.arange(n_intervals, dtype=np.float64) * timestep_hours

        # Cumulative from incremental
        cumulative_grid = np.cumsum(incremental_grid, axis=2)  # (lat, lon, time)

        # Transpose to CF convention: (time, lat, lon)
        incremental_tcf = incremental_grid.transpose(2, 0, 1).astype(np.float32)
        cumulative_tcf = cumulative_grid.transpose(2, 0, 1).astype(np.float32)

        ds = xr.Dataset(
            {
                'precip_incremental': xr.DataArray(
                    data=incremental_tcf,
                    dims=['time', 'lat', 'lon'],
                    attrs={
                        'long_name': 'Incremental precipitation depth per time interval',
                        'units': 'inches',
                        'standard_name': 'precipitation_amount',
                        'cell_methods': 'time: sum',
                    },
                ),
                'precip_cumulative': xr.DataArray(
                    data=cumulative_tcf,
                    dims=['time', 'lat', 'lon'],
                    attrs={
                        'long_name': 'Cumulative precipitation depth since storm start',
                        'units': 'inches',
                        'standard_name': 'precipitation_amount',
                        'cell_methods': 'time: sum (interval: from storm start)',
                    },
                ),
            },
            coords={
                'time': xr.DataArray(
                    data=time_hours,
                    dims=['time'],
                    attrs={
                        'long_name': 'Hours since storm start',
                        'units': 'hours',
                        'axis': 'T',
                    },
                ),
                'lat': xr.DataArray(
                    data=lat.astype(np.float64),
                    dims=['lat'],
                    attrs={
                        'long_name': 'Latitude',
                        'units': 'degrees_north',
                        'standard_name': 'latitude',
                        'axis': 'Y',
                    },
                ),
                'lon': xr.DataArray(
                    data=lon.astype(np.float64),
                    dims=['lon'],
                    attrs={
                        'long_name': 'Longitude',
                        'units': 'degrees_east',
                        'standard_name': 'longitude',
                        'axis': 'X',
                    },
                ),
            },
            attrs={
                'Conventions': 'CF-1.8',
                'title': (
                    f'ABM Hyetograph Grid - {ari_years}-yr '
                    f'{storm_duration_hours:.0f}-hr Storm'
                ),
                'institution': 'Generated by ras-commander AbmHyetographGrid',
                'source': source,
                'history': f'Created {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}',
                'comment': (
                    f'Alternating Block Method temporal distribution. '
                    f'ARI={ari_years}yr, duration={storm_duration_hours}hr, '
                    f'timestep={timestep_minutes}min, peak@{peak_position_percent}%. '
                    f'Grid shape: {n_lat}lat x {n_lon}lon x {n_intervals}timesteps.'
                ),
                'references': (
                    'Chow, V.T., Maidment, D.R., Mays, L.W. (1988). Applied Hydrology. '
                    'McGraw-Hill, Section 14.4. | '
                    'NOAA Atlas 14 Precipitation Frequency Atlas of the United States. '
                    'https://hdsc.nws.noaa.gov/pfds/'
                ),
            },
        )

        encoding = {
            'precip_incremental': {
                'zlib': True,
                'complevel': 4,
                'dtype': 'float32',
                '_FillValue': np.float32(-9999.0),
            },
            'precip_cumulative': {
                'zlib': True,
                'complevel': 4,
                'dtype': 'float32',
                '_FillValue': np.float32(-9999.0),
            },
        }

        ds.to_netcdf(str(output_path), encoding=encoding)

        logger.debug(
            f"Wrote NetCDF: {output_path} "
            f"({n_intervals} timesteps × {n_lat} lat × {n_lon} lon)"
        )
        return output_path

    @staticmethod
    def _load_asc_file(
        asc_path: Union[str, Path],
        scale_factor: float = 0.01,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        """
        Load NOAA Atlas 14 ESRI ASCII raster (.asc) file.

        ESRI ASCII format has a 6-line header followed by data rows:
            ncols         <int>
            nrows         <int>
            xllcorner     <float>   (lower-left corner longitude, or xllcenter)
            yllcorner     <float>   (lower-left corner latitude, or yllcenter)
            cellsize      <float>   (degrees)
            NODATA_value  <float>

        NOAA Atlas 14 .asc files store values in hundredths of inches (×0.01 to
        convert to inches) or thousandths of inches (×0.001). Check the product
        documentation for the correct scale_factor.

        Row 0 in the data array is the NORTHERNMOST row (ESRI convention).

        Args:
            asc_path: Path to the ESRI ASCII raster file
            scale_factor: Multiplier applied to raw values to convert to inches
                (default: 0.01 for hundredths-of-inches)

        Returns:
            Tuple of:
                data (ndarray): 2D float64 array shape (nrows, ncols), N→S ordering, inches
                lat_1d (ndarray): 1D latitude array (degrees_north), N→S order
                lon_1d (ndarray): 1D longitude array (degrees_east), W→E order
                nodata (float): NODATA sentinel value (after scale_factor conversion)

        Raises:
            FileNotFoundError: If asc_path does not exist
            ValueError: If data array dimensions do not match header
        """
        asc_path = Path(asc_path)
        if not asc_path.exists():
            raise FileNotFoundError(f"ASC file not found: {asc_path}")

        with open(asc_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Parse header (first 6 keyword lines, case-insensitive)
        header: Dict[str, float] = {}
        data_start = 0
        for i, line in enumerate(lines):
            parts = line.strip().split()
            if len(parts) == 2:
                key = parts[0].lower()
                if key in ('ncols', 'nrows', 'xllcorner', 'yllcorner',
                           'xllcenter', 'yllcenter', 'cellsize', 'nodata_value'):
                    try:
                        header[key] = float(parts[1])
                        data_start = i + 1
                    except ValueError:
                        break
                else:
                    break
            else:
                break

        ncols = int(header['ncols'])
        nrows = int(header['nrows'])
        cellsize = float(header['cellsize'])
        nodata_raw = float(header.get('nodata_value', -9999.0))

        # Cell-center origin (adjust corner→center if needed)
        if 'xllcenter' in header:
            xll_center = float(header['xllcenter'])
            yll_center = float(header['yllcenter'])
        else:
            xll_center = float(header.get('xllcorner', 0.0)) + cellsize / 2.0
            yll_center = float(header.get('yllcorner', 0.0)) + cellsize / 2.0

        # Parse data rows
        data_lines = [ln for ln in lines[data_start:] if ln.strip()]
        data = np.array(
            [row.split() for row in data_lines],
            dtype=np.float64,
        )

        if data.shape != (nrows, ncols):
            raise ValueError(
                f"Expected ({nrows}, {ncols}) data array in {asc_path.name}, "
                f"got {data.shape}"
            )

        data = data * scale_factor
        nodata = nodata_raw * scale_factor

        # Latitude: row 0 = northernmost (ESRI convention)
        lat_north = yll_center + (nrows - 1) * cellsize
        lat_1d = np.array([lat_north - i * cellsize for i in range(nrows)])

        # Longitude: col 0 = westernmost
        lon_1d = np.array([xll_center + j * cellsize for j in range(ncols)])

        return data, lat_1d, lon_1d, nodata
