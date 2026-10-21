"""Shared-temporal-pattern Atlas 14 precipitation grids.

This module applies one explicitly selected NOAA Atlas 14 temporal
distribution to each supplied storm-total depth cell.  It does not construct
per-cell alternating-block storms, apply areal-reduction factors, or convert
between annual-maximum-series and partial-duration-series frequency bases.
"""

import json
from pathlib import Path
from typing import Optional, Union

import numpy as np

from ..LoggingConfig import get_logger, log_call
from .Atlas14Grid import Atlas14Grid

logger = get_logger(__name__)


class Atlas14HyetographGrid:
    """Create gridded interval depths from storm-total depth grids in inches.

    Each valid cell receives the same dimensionless temporal pattern, scaled
    by that cell's supplied storm-total depth.  The output is a CF-style
    NetCDF file with relative-hour interval-end coordinates and explicit
    interval bounds.  It is a design-storm data product; this class neither
    imports the file into a model nor asserts solver compatibility.
    """

    _SUPPORTED_DURATIONS = (6, 12, 24, 96)
    _FREQUENCY_BASES = {"unspecified", "PDS", "AMS"}
    _NOAA_TEMPORAL_SOURCE = "https://hdsc.nws.noaa.gov/pub/hdsc/data/"

    @staticmethod
    def _require_dependencies():
        try:
            import xarray as xr
            from pyproj import CRS
        except ImportError as exc:
            raise ImportError(
                "xarray and pyproj are required to write Atlas 14 grid NetCDF files."
            ) from exc
        return xr, CRS

    @staticmethod
    def _validate_storm_parameters(
        ari_years: int,
        storm_duration_hours: int,
        timestep_minutes: int,
        depth_frequency_basis: str,
    ) -> tuple[int, int, int, str]:
        def whole_number(value, name: str) -> int:
            if isinstance(value, bool):
                raise ValueError(f"{name} must be a positive whole number")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a positive whole number") from exc
            if not np.isfinite(numeric) or numeric <= 0 or not numeric.is_integer():
                raise ValueError(f"{name} must be a positive whole number")
            return int(numeric)

        if isinstance(ari_years, bool):
            raise ValueError("ari_years must be a positive whole number")
        ari = whole_number(ari_years, "ari_years")
        duration = whole_number(storm_duration_hours, "storm_duration_hours")
        if duration not in Atlas14HyetographGrid._SUPPORTED_DURATIONS:
            raise ValueError(
                "storm_duration_hours must be one of "
                f"{list(Atlas14HyetographGrid._SUPPORTED_DURATIONS)}"
            )
        timestep = whole_number(timestep_minutes, "timestep_minutes")
        if timestep <= 0 or duration * 60 % timestep:
            raise ValueError(
                "timestep_minutes must be positive and exactly divide the storm duration"
            )
        basis = str(depth_frequency_basis).strip().upper()
        if basis == "UNSPECIFIED":
            basis = "unspecified"
        if basis not in Atlas14HyetographGrid._FREQUENCY_BASES:
            raise ValueError("depth_frequency_basis must be 'PDS', 'AMS', or 'unspecified'")
        return ari, duration, timestep, basis

    @staticmethod
    def _validate_axis(values, name: str) -> np.ndarray:
        values = np.asarray(values, dtype=np.float64)
        if values.ndim != 1 or values.size == 0 or not np.all(np.isfinite(values)):
            raise ValueError(f"{name} must be a non-empty finite one-dimensional coordinate")
        if values.size > 1:
            differences = np.diff(values)
            if not (np.all(differences > 0) or np.all(differences < 0)):
                raise ValueError(f"{name} must be strictly monotonic")
            if not np.allclose(differences, differences[0], rtol=1e-8, atol=1e-10):
                raise ValueError(f"{name} must be regularly spaced cell centers")
        return values

    @staticmethod
    def _serialize_source_metadata(source_metadata: Optional[dict]) -> Optional[str]:
        """Return a strict JSON source-provenance record for a NetCDF attribute."""
        if source_metadata is None:
            return None
        if not isinstance(source_metadata, dict):
            raise ValueError("source_metadata must be a dictionary when provided")
        try:
            return json.dumps(
                source_metadata,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "source_metadata must contain only JSON-serializable finite values"
            ) from exc

    @staticmethod
    def _shared_fraction(
        *,
        ari_years: int,
        storm_duration_hours: int,
        timestep_minutes: int,
        state: str,
        region: Union[int, str],
        quartile: str,
        probability_column: str,
        cache_dir: Optional[Union[str, Path]],
    ) -> tuple[np.ndarray, dict]:
        """Load a selected NOAA temporal curve once and return its increments."""
        # hms-commander is intentionally optional until a caller invokes this API.
        try:
            from importlib.metadata import version
            from hms_commander.Atlas14Storm import Atlas14Config, Atlas14Storm
        except ImportError as exc:
            raise ImportError(
                "Atlas14HyetographGrid requires hms-commander for NOAA Atlas 14 "
                "temporal-distribution parsing. Install hms-commander to use it."
            ) from exc

        required_text = {
            "state": state,
            "region": region,
            "quartile": quartile,
            "probability_column": probability_column,
        }
        if any(value is None or not str(value).strip() for value in required_text.values()):
            raise ValueError("state, region, quartile, and probability_column must be explicit")
        hyetograph = Atlas14Storm.generate_hyetograph(
            total_depth_inches=1.0,
            state=state,
            region=region,
            duration_hours=storm_duration_hours,
            aep_percent=100.0 / ari_years,
            quartile=quartile,
            interval_minutes=timestep_minutes,
            cache_dir=cache_dir,
            probability_column=probability_column,
        )
        expected_intervals = storm_duration_hours * 60 // timestep_minutes
        hours = np.asarray(hyetograph["hour"].to_numpy(), dtype=np.float64)
        values = np.asarray(hyetograph["incremental_depth"].to_numpy(), dtype=np.float64)
        expected_hours = np.linspace(
            0.0, storm_duration_hours, expected_intervals + 1, dtype=np.float64
        )
        if (
            len(values) != expected_intervals + 1
            or not np.allclose(hours, expected_hours, rtol=1e-10, atol=1e-12)
            or not np.isclose(values[0], 0.0, rtol=0.0, atol=1e-14)
        ):
            raise ValueError("NOAA temporal distribution returned an unexpected time axis")
        fraction = values[1:]
        if not np.all(np.isfinite(fraction)) or np.any(fraction < 0.0):
            raise ValueError("NOAA temporal distribution contains invalid interval fractions")
        if not np.isclose(float(fraction.sum()), 1.0, rtol=1e-10, atol=1e-12):
            raise ValueError("NOAA temporal distribution does not conserve unit storm depth")
        config = Atlas14Config(state=state, region=region, duration=storm_duration_hours)
        noaa_volume = getattr(config, "noaa_volume", str(state).strip().lower())
        noaa_volume_name = getattr(config, "noaa_volume_name", noaa_volume)
        region_code = getattr(config, "region_code", f"{str(state).upper()}_{region}")
        provenance = {
            "source_url": config.url,
            "noaa_volume": noaa_volume,
            "noaa_volume_name": noaa_volume_name,
            "region_code": region_code,
            "hms_commander_version": version("hms-commander"),
        }
        # Newer hms-commander versions attach additional provenance. Preserve
        # it where available, while retaining the independently constructed URL.
        provenance.update(dict(hyetograph.attrs.get("provenance", {})))
        return fraction, provenance

    @staticmethod
    @log_call
    def generate_from_depth_grid(
        depth_grid,
        *,
        x,
        y,
        source_crs: Union[str, object],
        ari_years: int,
        storm_duration_hours: int,
        timestep_minutes: int,
        state: str,
        region: Union[int, str],
        quartile: str,
        probability_column: str,
        output_netcdf: Union[str, Path],
        nodata_value: Optional[float] = None,
        depth_frequency_basis: str = "unspecified",
        source_metadata: Optional[dict] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
    ) -> Path:
        """Scale one selected NOAA temporal curve by supplied inch-depth cells.

        Parameters
        ----------
        depth_grid : array-like
            Two-dimensional storm-total depths in inches with shape
            ``(len(y), len(x))``.
        x, y : array-like
            Regular, monotonic cell-center coordinates in ``source_crs``.
        source_crs : str or CRS-like
            Geographic or projected coordinate reference system for ``x`` and
            ``y``. Geocentric CRS values are not valid horizontal grids.
        ari_years, storm_duration_hours, timestep_minutes : int
            Positive ARI and supported NOAA temporal duration (6, 12, 24, or
            96 hours); timestep must divide duration exactly.
        state, region, quartile, probability_column : str
            Explicit NOAA temporal-distribution selection. No regional or
            probability defaults are supplied by this API.
        output_netcdf : str or Path
            New destination path. Existing files require ``overwrite=True``.
        nodata_value : float, optional
            Source nodata sentinel in inches. It is preserved as missing data.
        depth_frequency_basis : {"PDS", "AMS", "unspecified"}
            Frequency basis of supplied total depths. The API does not infer or
            convert this value.
        source_metadata : dict, optional
            Strict JSON-serializable description of supplied depths, saved as
            ``depth_source_metadata`` without overriding API methodology.
        cache_dir : str or Path, optional
            Optional cache passed to the NOAA temporal-distribution helper.
        overwrite : bool, default False
            Whether an existing output file may be replaced.

        Returns
        -------
        pathlib.Path
            Resolved NetCDF output path.

        Raises
        ------
        ValueError
            If input values, coordinates, CRS, time configuration, metadata,
            or output configuration are invalid.
        ImportError
            If required optional libraries are unavailable.

        Notes
        -----
        ``depth_grid`` must be a two-dimensional array in inches with shape
        ``(len(y), len(x))``.  Its values are treated as final storm totals.
        ``NaN`` values (and an optional ``nodata_value``) remain missing at every
        interval.  Finite values must be non-negative; a zero total remains a
        valid zero-depth cell.  No spatial interpolation, areal reduction, or
        AMS/PDS conversion occurs in this method.

        The numeric ``time`` coordinate is each interval end in hours from the
        synthetic 1970-01-01 origin. It represents relative storm elapsed
        time, not an observed event date; consumers that require an actual
        simulation start must rebase the coordinate. ``time_bounds`` gives the
        inclusive start/exclusive end of each relative-hour accumulation.
        """
        xr, CRS = Atlas14HyetographGrid._require_dependencies()
        ari_years, duration, timestep, frequency_basis = (
            Atlas14HyetographGrid._validate_storm_parameters(
                ari_years, storm_duration_hours, timestep_minutes, depth_frequency_basis
            )
        )
        try:
            crs = CRS.from_user_input(source_crs)
        except Exception as exc:
            raise ValueError(f"source_crs is not a valid CRS: {source_crs!r}") from exc
        if crs.is_geocentric or not (crs.is_geographic or crs.is_projected):
            raise ValueError("source_crs must be a two-dimensional geographic or projected CRS")

        x_values = Atlas14HyetographGrid._validate_axis(x, "x")
        y_values = Atlas14HyetographGrid._validate_axis(y, "y")
        depths = np.asarray(depth_grid, dtype=np.float64)
        if depths.ndim != 2 or depths.shape != (y_values.size, x_values.size):
            raise ValueError(
                "depth_grid must be two-dimensional with shape (len(y), len(x))"
            )
        if nodata_value is not None:
            try:
                nodata = float(nodata_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("nodata_value must be numeric when provided") from exc
            depths = depths.copy()
            depths[depths == nodata] = np.nan
        if np.isinf(depths).any():
            raise ValueError("depth_grid must not contain infinite values")
        finite = np.isfinite(depths)
        if not finite.any():
            raise ValueError("depth_grid has no valid finite depth cells")
        if np.any(depths[finite] < 0.0):
            raise ValueError("depth_grid contains negative precipitation depths")

        output_path = Path(output_netcdf).expanduser().resolve()
        if output_path.exists() and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing output NetCDF: {output_path}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        serialized_source_metadata = Atlas14HyetographGrid._serialize_source_metadata(
            source_metadata
        )

        fraction, temporal_provenance = Atlas14HyetographGrid._shared_fraction(
            ari_years=ari_years,
            storm_duration_hours=duration,
            timestep_minutes=timestep,
            state=state,
            region=region,
            quartile=quartile,
            probability_column=probability_column,
            cache_dir=cache_dir,
        )
        increments = fraction[:, np.newaxis, np.newaxis] * depths[np.newaxis, :, :]
        increments[:, ~finite] = np.nan
        cumulative = np.cumsum(increments, axis=0)
        interval_hours = timestep / 60.0
        interval_end_hours = (np.arange(fraction.size, dtype=np.float64) + 1.0) * interval_hours
        interval_bounds = np.column_stack((interval_end_hours - interval_hours, interval_end_hours))
        if not np.all(np.isfinite(increments[:, finite])) or not np.all(
            np.isfinite(cumulative[:, finite])
        ):
            raise ValueError("shared temporal curve produced non-finite valid-cell depths")
        maximum_error = float(np.nanmax(np.abs(cumulative[-1] - depths)))
        conservation_tolerance = max(1e-12, float(np.nanmax(depths[finite])) * 1e-10)
        if maximum_error > conservation_tolerance:
            raise ValueError(
                "shared temporal curve failed depth conservation: "
                f"{maximum_error:.12g} inches exceeds {conservation_tolerance:.12g} inches"
            )

        crs_attributes = dict(crs.to_cf())
        crs_attributes["crs_wkt"] = crs.to_wkt()
        crs_attributes["spatial_ref"] = crs.to_wkt()
        x_attributes = {"axis": "X"}
        y_attributes = {"axis": "Y"}
        if crs.is_geographic:
            x_attributes.update({"standard_name": "longitude", "units": "degrees_east"})
            y_attributes.update({"standard_name": "latitude", "units": "degrees_north"})
        else:
            axis_units = []
            for axis in crs.axis_info[:2]:
                unit_name = str(axis.unit_name or "").strip()
                normalized = unit_name.lower().replace(" ", "_")
                if normalized in {"metre", "meter", "metres", "meters"}:
                    cf_units = "m"
                elif normalized in {"foot", "feet", "international_foot"}:
                    cf_units = "ft"
                elif normalized in {"us_survey_foot", "us_survey_feet"}:
                    cf_units = "US_survey_foot"
                else:
                    cf_units = unit_name
                axis_units.append((cf_units, float(axis.unit_conversion_factor or 1.0)))
            if len(axis_units) != 2:
                raise ValueError("source_crs must define two horizontal coordinate axes")
            x_attributes.update(
                {
                    "standard_name": "projection_x_coordinate",
                    "units": axis_units[0][0],
                    "unit_conversion_to_meters": axis_units[0][1],
                }
            )
            y_attributes.update(
                {
                    "standard_name": "projection_y_coordinate",
                    "units": axis_units[1][0],
                    "unit_conversion_to_meters": axis_units[1][1],
                }
            )

        source_url = temporal_provenance.get("source_url", Atlas14HyetographGrid._NOAA_TEMPORAL_SOURCE)
        dataset_attributes = {
            "title": "Atlas 14 shared-temporal-pattern precipitation grid",
            "Conventions": "CF-1.8",
            "method_name": "Atlas 14 shared temporal pattern scaled by supplied storm-total grid",
            "temporal_method": "One selected NOAA temporal curve shared by all valid cells",
                "spatial_method": "Supplied single-duration depth grid; no spatial resampling by API",
            "temporal_distribution_source": "NOAA Atlas 14 temporal distribution",
            "temporal_distribution_url": source_url,
            "temporal_noaa_volume": str(temporal_provenance.get("noaa_volume", "")),
            "temporal_region_code": str(temporal_provenance.get("region_code", "")),
            "temporal_generator_version": str(
                temporal_provenance.get("hms_commander_version", "")
            ),
            "temporal_state": str(state),
            "temporal_region": str(region),
            "temporal_quartile": str(quartile),
            "temporal_probability_column": str(probability_column),
            "ari_years": ari_years,
            "storm_duration_hours": duration,
            "timestep_minutes": timestep,
            "time_reference": "synthetic coordinate origin 1970-01-01 00:00:00; not an observed event date",
            "time_reference_is_event_date": 0,
            "depth_units": "inches",
            "depth_frequency_basis": frequency_basis,
            "spatial_resampling": "none",
            "areal_reduction": "none_applied_by_api",
            "ams_conversion": "none_applied_by_api",
            "depth_conservation_max_error_inches": maximum_error,
            "depth_conservation_tolerance_inches": conservation_tolerance,
            "history": "Generated without model execution or model import.",
        }
        if serialized_source_metadata is not None:
            dataset_attributes["depth_source_metadata"] = serialized_source_metadata
        dataset = xr.Dataset(
            data_vars={
                "precip_incremental": (
                    ("time", "y", "x"),
                    increments,
                    {
                        "units": "inches",
                        "long_name": "interval precipitation depth",
                        "cell_methods": "time: sum",
                        "grid_mapping": "spatial_ref",
                    },
                ),
                "precip_cumulative": (
                    ("time", "y", "x"),
                    cumulative,
                    {
                        "units": "inches",
                        "long_name": "cumulative precipitation depth from storm start",
                        "grid_mapping": "spatial_ref",
                    },
                ),
                "storm_total": (
                    ("y", "x"),
                    depths,
                    {
                        "units": "inches",
                        "long_name": "supplied storm-total precipitation depth",
                        "grid_mapping": "spatial_ref",
                    },
                ),
                "temporal_fraction": (
                    ("time",),
                    fraction,
                    {
                        "units": "1",
                        "long_name": "shared interval fraction of storm total",
                        "cell_methods": "time: sum",
                    },
                ),
                "time_bounds": (
                    ("time", "bounds"),
                    interval_bounds,
                    {
                        "units": "hours since 1970-01-01 00:00:00",
                        "calendar": "proleptic_gregorian",
                        "long_name": "relative-hour interval bounds from storm start",
                    },
                ),
                "spatial_ref": ((), np.int32(0), crs_attributes),
            },
            coords={
                "time": (
                    "time",
                    interval_end_hours,
                    {
                        "units": "hours since 1970-01-01 00:00:00",
                        "calendar": "proleptic_gregorian",
                        "standard_name": "time",
                        "axis": "T",
                        "long_name": "synthetic interval-end coordinate",
                        "comment": "Elapsed hours from synthetic storm-start origin; not an observed event date.",
                        "bounds": "time_bounds",
                    },
                ),
                "x": ("x", x_values, x_attributes),
                "y": ("y", y_values, y_attributes),
                "bounds": ("bounds", np.array([0, 1], dtype=np.int8)),
            },
            attrs=dataset_attributes,
        )
        # This output has no NetCDF4-only feature; the portable writer keeps
        # this optional precipitation helper independent of binary NetCDF4.
        dataset.to_netcdf(output_path, engine="scipy")
        logger.info(
            "Wrote shared-pattern Atlas 14 grid %s (%d intervals, %d valid cells)",
            output_path.name,
            fraction.size,
            int(finite.sum()),
        )
        return output_path

    @staticmethod
    @log_call
    def generate(
        bounds,
        ari_years: int,
        storm_duration_hours: int,
        timestep_minutes: int,
        *,
        state: str,
        region: Union[int, str],
        quartile: str,
        probability_column: str,
        output_netcdf: Union[str, Path],
        buffer_percent: float = 5.0,
        depth_frequency_basis: str = "unspecified",
        cache_dir: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
    ) -> Path:
        """Download one duration depth grid and apply a selected shared curve.

        Parameters
        ----------
        bounds : sequence of float
            West, south, east, north geographic bounds passed to Atlas14Grid.
        ari_years, storm_duration_hours, timestep_minutes : int
            Requested frequency, NOAA-supported temporal duration, and exact
            interval size in minutes.
        state, region, quartile, probability_column : str
            Required NOAA temporal-distribution selection.
        output_netcdf : str or Path
            New NetCDF destination.
        buffer_percent : float, default 5.0
            Geographic buffer applied during source-grid download.
        depth_frequency_basis : {"PDS", "AMS", "unspecified"}
            Declared basis of the source depth grid; no conversion is applied.
        cache_dir : str or Path, optional
            Optional temporal-distribution cache directory.
        overwrite : bool, default False
            Replace an existing destination only when true.

        Returns
        -------
        pathlib.Path
            Resolved output NetCDF path.

        Raises
        ------
        ValueError
            If parameters are invalid or the requested ARI is not an exact
            coordinate of the retrieved frequency grid.

        The Atlas 14 grid client returns all available frequency planes even
        when a return period is requested.  This wrapper selects the requested
        ARI only when it is an exact value on that returned axis.
        """
        ari_years, duration, timestep, frequency_basis = (
            Atlas14HyetographGrid._validate_storm_parameters(
                ari_years, storm_duration_hours, timestep_minutes, depth_frequency_basis
            )
        )
        try:
            buffer = float(buffer_percent)
        except (TypeError, ValueError) as exc:
            raise ValueError("buffer_percent must be a finite non-negative number") from exc
        if not np.isfinite(buffer) or buffer < 0.0:
            raise ValueError("buffer_percent must be a finite non-negative number")
        try:
            normalized_bounds = tuple(float(value) for value in bounds)
        except (TypeError, ValueError) as exc:
            raise ValueError("bounds must be four finite numeric values") from exc
        if (
            len(normalized_bounds) != 4
            or not np.all(np.isfinite(normalized_bounds))
            or normalized_bounds[0] >= normalized_bounds[2]
            or normalized_bounds[1] >= normalized_bounds[3]
        ):
            raise ValueError("bounds must be west, south, east, north with positive extent")
        result = Atlas14Grid.get_pfe_for_bounds(
            bounds=normalized_bounds,
            durations=[duration],
            return_periods=[ari_years],
            buffer_percent=buffer,
        )
        available_ari = np.asarray(result.get("ari"))
        matches = np.flatnonzero(available_ari == ari_years)
        if matches.size != 1:
            raise ValueError(
                f"Requested {ari_years}-year return period is not an exact returned Atlas 14 ARI"
            )
        depths = np.asarray(result[f"pfe_{duration}hr"], dtype=np.float64)
        if depths.ndim != 3:
            raise ValueError("Atlas 14 grid returned an unexpected depth-array shape")
        return Atlas14HyetographGrid.generate_from_depth_grid(
            depths[:, :, int(matches[0])],
            x=result["lon"],
            y=result["lat"],
            source_crs="EPSG:4326",
            ari_years=ari_years,
            storm_duration_hours=duration,
            timestep_minutes=timestep,
            state=state,
            region=region,
            quartile=quartile,
            probability_column=probability_column,
            output_netcdf=output_netcdf,
            depth_frequency_basis=frequency_basis,
            source_metadata={
                "source_kind": "NOAA Atlas 14 CONUS precipitation-frequency grid",
                "source_url": Atlas14Grid.CONUS_URL,
                "requested_bounds": list(normalized_bounds),
                "returned_bounds": [
                    float(value) for value in result.get("bounds", normalized_bounds)
                ],
                "buffer_percent": buffer,
                "requested_ari_years": ari_years,
                "requested_duration_hours": duration,
                "selected_ari_years": int(available_ari[int(matches[0])]),
                "native_crs": "EPSG:4326",
                "native_depth_units": str(result.get("units", "inches")),
                "spatial_resampling": "none",
            },
            cache_dir=cache_dir,
            overwrite=overwrite,
        )

    @staticmethod
    @log_call
    def generate_from_asc_file(
        asc_path: Union[str, Path],
        *,
        scale_factor: float,
        source_crs: Union[str, object],
        ari_years: int,
        storm_duration_hours: int,
        timestep_minutes: int,
        state: str,
        region: Union[int, str],
        quartile: str,
        probability_column: str,
        output_netcdf: Union[str, Path],
        bounds=None,
        buffer_percent: float = 0.0,
        depth_frequency_basis: str = "unspecified",
        cache_dir: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
    ) -> Path:
        """Read a bounded ESRI ASCII storm-total grid and write a NetCDF forcing.

        Parameters
        ----------
        asc_path : str or Path
            Source single-band ESRI ASCII raster of storm-total depths.
        scale_factor : float
            Required multiplier converting raw raster values to inches.
        source_crs : str or CRS-like
            Required CRS for raster coordinates; it is not inferred.
        ari_years, storm_duration_hours, timestep_minutes : int
            Requested frequency, supported temporal duration, and interval size.
        state, region, quartile, probability_column : str
            Required NOAA temporal-distribution selection.
        output_netcdf : str or Path
            New NetCDF destination, distinct from ``asc_path``.
        bounds : sequence of float, optional
            Source-CRS bounds used to crop before temporal expansion.
        buffer_percent : float, default 0.0
            Optional percentage buffer around ``bounds``.
        depth_frequency_basis : {"PDS", "AMS", "unspecified"}
            Declared source depth basis; no conversion is applied.
        cache_dir : str or Path, optional
            Optional temporal-distribution cache directory.
        overwrite : bool, default False
            Replace an existing destination only when true.

        Returns
        -------
        pathlib.Path
            Resolved output NetCDF path.

        Raises
        ------
        FileNotFoundError
            If the source ASC raster does not exist.
        ValueError
            If the source is not a single rectilinear band, units/configuration
            are invalid, or bounds select no cell centers.
        ImportError
            If rasterio is unavailable.

        ``scale_factor`` and ``source_crs`` are required because ASCII rasters
        do not reliably convey their units or coordinate reference system.  For
        example, NOAA depth ASCII products stored in thousandths of inches use
        ``scale_factor=0.001``.  If supplied, ``bounds`` are in ``source_crs``
        coordinates and crop before temporal expansion, avoiding statewide
        in-memory time cubes.
        """
        source_path = Path(asc_path).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"ASC file not found: {source_path}")
        output_path = Path(output_netcdf).expanduser().resolve()
        if source_path == output_path:
            raise ValueError("output_netcdf must differ from asc_path")
        try:
            scale = float(scale_factor)
        except (TypeError, ValueError) as exc:
            raise ValueError("scale_factor must be a finite positive number") from exc
        if not np.isfinite(scale) or scale <= 0.0:
            raise ValueError("scale_factor must be a finite positive number")
        try:
            buffer = float(buffer_percent)
        except (TypeError, ValueError) as exc:
            raise ValueError("buffer_percent must be a finite non-negative number") from exc
        if not np.isfinite(buffer) or buffer < 0.0:
            raise ValueError("buffer_percent must be a finite non-negative number")
        if bounds is None and buffer != 0.0:
            raise ValueError("buffer_percent requires bounds")
        try:
            import rasterio
            from pyproj import CRS
        except ImportError as exc:
            raise ImportError(
                "rasterio and pyproj are required to read ESRI ASCII grid files"
            ) from exc
        try:
            supplied_crs = CRS.from_user_input(source_crs)
        except Exception as exc:
            raise ValueError(f"source_crs is not a valid CRS: {source_crs!r}") from exc
        with rasterio.open(source_path) as raster:
            if raster.count != 1:
                raise ValueError("ASC file must contain exactly one raster band")
            raw = raster.read(1).astype(np.float64)
            transform = raster.transform
            if not transform.is_rectilinear:
                raise ValueError("ASC file must have a rectilinear grid transform")
            x_values = transform.c + (np.arange(raster.width) + 0.5) * transform.a
            y_values = transform.f + (np.arange(raster.height) + 0.5) * transform.e
            nodata = raster.nodata
            embedded_crs = raster.crs
        if embedded_crs is None:
            prj_path = source_path.with_suffix(".prj")
            if prj_path.exists():
                try:
                    embedded_crs = CRS.from_wkt(prj_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise ValueError("ASC .prj sidecar does not contain a valid CRS") from exc
        if embedded_crs is not None and not supplied_crs.equals(embedded_crs):
            raise ValueError(
                "source_crs does not match the CRS embedded in the ASC raster"
            )

        if bounds is not None:
            if len(bounds) != 4:
                raise ValueError("bounds must be (west, south, east, north)")
            west, south, east, north = (float(value) for value in bounds)
            if not all(np.isfinite([west, south, east, north])) or west >= east or south >= north:
                raise ValueError("bounds must be finite with west < east and south < north")
            width, height = east - west, north - south
            west -= width * buffer / 100.0
            east += width * buffer / 100.0
            south -= height * buffer / 100.0
            north += height * buffer / 100.0
            x_index = np.flatnonzero((x_values >= west) & (x_values <= east))
            y_index = np.flatnonzero((y_values >= south) & (y_values <= north))
            if x_index.size == 0 or y_index.size == 0:
                raise ValueError("bounds do not include any ASC cell centers")
            raw = raw[np.ix_(y_index, x_index)]
            x_values, y_values = x_values[x_index], y_values[y_index]

        nodata_inches = None if nodata is None else float(nodata) * scale
        return Atlas14HyetographGrid.generate_from_depth_grid(
            raw * scale,
            x=x_values,
            y=y_values,
            source_crs=source_crs,
            ari_years=ari_years,
            storm_duration_hours=storm_duration_hours,
            timestep_minutes=timestep_minutes,
            state=state,
            region=region,
            quartile=quartile,
            probability_column=probability_column,
            output_netcdf=output_path,
            nodata_value=nodata_inches,
            depth_frequency_basis=depth_frequency_basis,
            source_metadata={
                "source_kind": "ESRI ASCII storm-total depth grid",
                "source_filename": source_path.name,
                "source_crs": str(source_crs),
                "embedded_source_crs": (
                    None if embedded_crs is None else embedded_crs.to_string()
                ),
                "scale_factor_to_inches": scale,
                "nodata_value_raw": None if nodata is None else float(nodata),
                "requested_bounds": None if bounds is None else [float(value) for value in bounds],
                "buffer_percent": buffer,
            },
            cache_dir=cache_dir,
            overwrite=overwrite,
        )
