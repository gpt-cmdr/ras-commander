"""
RasDssGrid - gridded import and grid tools for HEC-DSS files.

Thin wrappers around the ``ras_commander_fast_dss.gridded`` namespace of the
optional ras-commander-fast-dss package: import gridded source files (GRIB2,
NetCDF, HDF5, GeoTIFF, ASCII grid, local Zarr v2) or arrays into DSS grid
records, and process DSS grids (calculator, sanitizer, clipper, normalizer,
time shift, time-step resampling, zonal statistics) without Java, Vortex or
GDAL.

Every method runs on the native engine, whatever ``RasDss.backend`` is: these
operations have no Java route in ras-commander. Arguments other than the leading
ones are passed to the engine unchanged, and each method returns the engine's
result unchanged, so ``help(ras_commander_fast_dss.gridded.<name>)`` is the full
reference for every option.

Usage:
    from ras_commander import RasDssGrid

    result = RasDssGrid.import_gridded(
        ["MRMS_MultiSensor_QPE_01H_Pass2_00.00_20240926-220000.grib2"],
        "storm.dss",
        product="mrms_qpe",
        envelope=(-646000, 1922000, -444000, 2124000),
        parts={"A": "SHG", "B": "MRMS_QPE", "F": "PASS2"},
    )
    print(result.pathnames)

List of Functions:
    get_features() - Which gridded feature groups the installed engine provides
    import_gridded() - Import gridded files (or a Zarr store) into DSS grids
    import_arrays() - Import arrays into DSS grids
    import_zarr() - Import a variable of local Zarr v2 stores into DSS grids
    list_variables() - Variables a source file offers
    zarr_variables() - Variables of a local Zarr v2 store
    read_zarr() - Read a window of a Zarr variable
    calculate() - Apply one operation by a constant to every valid cell
    calculate_raster() - Combine each grid with a raster
    sanitize() - Replace cells at or beyond thresholds
    clip() - Clip grids to an envelope
    normalize() - Scale grids so interval totals match normals
    shift_times() - Move grid records in time
    resample_times() - Resample each grid series to a fixed time step
    time_steps() - Time steps resample_times() takes
    series_info() - What a grid series states
    read_window() - One resampled window of a grid series
    read_nearest() - The grid record nearest a time
    read_min_max() - Minimum and maximum grids over a window
    grid_to_point() - Zonal statistics written as time series
    zonal_statistics() - Zonal statistics as a table
    zone_masks() - Each zone's cell indices
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from . import _backend

logger = get_logger(__name__)

PathLike = Union[str, Path]


def _path(value: PathLike) -> str:
    """Absolute path string, keeping a mapped drive letter (no UNC conversion)."""
    from ras_commander.RasUtils import RasUtils

    return str(RasUtils.safe_resolve(Path(value)))


def _paths(value: Union[PathLike, Sequence[PathLike]]) -> Union[str, List[str]]:
    if isinstance(value, (str, Path)):
        return _path(value)
    return [_path(item) for item in value]


class RasDssGrid:
    """
    Static class for gridded import and grid processing on HEC-DSS files.

    Each method is a thin wrapper around the function of the same name in
    ``ras_commander_fast_dss.gridded``. All methods are static; do not instantiate.

    Requires the optional ras-commander-fast-dss package
    (``pip install "ras-commander[dss]"``). A method raises ``ImportError`` when
    the package is missing and ``DssCapabilityError`` (a ``NotImplementedError``)
    when the installed version does not provide the operation. ``RasDss.backend``
    does not select anything here.

    The engine plans each run before it writes: a refused run leaves the output
    untouched. The engine reports where its results differ from HEC-Vortex by
    design; those notes are in each engine function's documentation.

    ``sync`` (on the methods that write): the engine's flush policy, passed through
    unchanged. ``None`` (default) states nothing, so the installed engine's own
    default applies; that default can change between engine releases.
    """

    @staticmethod
    def _call(method: str, *args: Any, sync: Any = None, **kwargs: Any) -> Any:
        function = _backend.require_gridded(method)
        kwargs.update(_backend.engine_sync_kwargs(function, sync, f"gridded.{method}"))
        return function(*args, **kwargs)

    @staticmethod
    @log_call
    def get_features() -> Dict[str, bool]:
        """Report which gridded feature groups the installed engine provides.

        Does not raise when ras-commander-fast-dss is missing (every value is False).

        Returns:
            ``dict`` of engine feature name to ``bool``: ``gridded_import``,
            ``gridded_netcdf``, ``gridded_zarr``, ``gridded_accumulation_window``,
            ``gridded_time_tools``, ``grid_tools`` and ``grid_to_point``.
        """
        names = sorted(set(_backend.GRIDDED_FEATURES.values())
                       | {"gridded_netcdf", "gridded_accumulation_window"})
        return {name: _backend.native_feature(name) for name in names}

    # ------------------------------------------------------------------ import

    @staticmethod
    @log_call
    def import_gridded(
        inputs: Union[PathLike, Sequence[PathLike]],
        output: PathLike,
        *,
        sync: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        """Import grids from files into a DSS file, one frame at a time.

        Args:
            inputs: One path or a sequence, read in the order given: GRIB2, NetCDF
                (classic and NetCDF-4), HDF5, GeoTIFF, ASCII grid, or the folder of
                a local Zarr v2 store.
            output: DSS file to write. It is created when the first record is written.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: Options of ``ras_commander_fast_dss.gridded.import_gridded``,
                passed unchanged: ``variable``, ``product``, ``envelope``,
                ``envelope_crs``, ``shapefile``, ``target_crs`` (default ``"SHG"``),
                ``cell_size`` (metres, default 2000), ``method``, ``parts``,
                ``units`` (relabels; it does not convert), ``data_type``,
                ``version``, ``align``, ``window_rule``, ``duplicates``,
                ``threads``, ``progress``, ``bbox``, ``times`` and the reader limits.

        Returns:
            The engine's ``ImportResult`` (``output``, ``records``, ``pathnames``).

        Raises:
            ImportError: ras-commander-fast-dss is not installed.
            DssCapabilityError: The installed engine has no ``gridded_import``.
            ValueError: The engine refuses the run (nothing is written).
        """
        return RasDssGrid._call("import_gridded", _paths(inputs), _path(output),
                                sync=sync, **kwargs)

    @staticmethod
    @log_call
    def import_arrays(
        data: Any,
        output: PathLike,
        *,
        times: Sequence[Any],
        transform: Sequence[float],
        crs: str,
        variable: str,
        source_units: str,
        sync: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        """Import arrays through the same warp, unit, naming and writer steps as a file.

        Args:
            data: Shape ``(frames, rows, columns)``, or ``(rows, columns)``.
            output: DSS file to write.
            times: One per frame: ``None``, an instant, or ``(start, end)``.
            transform: ``(origin_x, dx, origin_y, dy)``; the origin is the outer
                corner of the first cell, and negative ``dy`` means row 0 is north.
            crs: ``"SHG"``, ``"HRAP"`` or WKT of the arrays.
            variable: Variable name; it sets the C part.
            source_units: Units the cells are in.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: Other ``ras_commander_fast_dss.gridded.import_arrays`` options.

        Returns:
            The engine's ``ImportResult``.

        Raises:
            ImportError: ras-commander-fast-dss is not installed.
            DssCapabilityError: The installed engine has no ``gridded_import``.
        """
        return RasDssGrid._call(
            "import_arrays", data, _path(output), times=times, transform=transform,
            crs=crs, variable=variable, source_units=source_units, sync=sync, **kwargs,
        )

    @staticmethod
    @log_call
    def import_zarr(
        inputs: Union[PathLike, Sequence[PathLike]],
        output: PathLike,
        *,
        variable: str,
        sync: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        """Import a variable of local Zarr v2 stores (for example AORC v1.1) into DSS.

        Args:
            inputs: One store folder or a sequence of them.
            output: DSS file to write.
            variable: Variable name (see ``zarr_variables``).
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: Other ``ras_commander_fast_dss.gridded.import_zarr`` options
                (``bbox``, ``times``, ``envelope``, ``target_crs``, ``cell_size``,
                ``parts``, ``window_rule``, ``limits``, ``stop``, ``strict``, ...).

        Returns:
            The engine's ``ImportResult``.

        Raises:
            ImportError: ras-commander-fast-dss is not installed.
            DssCapabilityError: The installed engine has no ``gridded_zarr``.
        """
        return RasDssGrid._call("import_zarr", _paths(inputs), _path(output),
                                variable=variable, sync=sync, **kwargs)

    @staticmethod
    @log_call
    def list_variables(path: PathLike) -> List[str]:
        """Variables a source file offers, by the names ``variable=`` takes.

        Args:
            path: A GRIB2, NetCDF, HDF5, GeoTIFF or ASCII grid file (not a DSS file).
                Only metadata is read.

        Returns:
            List of variable names.
        """
        return RasDssGrid._call("list_variables", _path(path))

    @staticmethod
    @log_call
    def zarr_variables(path: PathLike) -> List[Dict[str, Any]]:
        """Variables of a local Zarr v2 store, one ``dict`` each.

        Args:
            path: The store's folder. Only metadata and axes are read.

        Returns:
            The engine's list of dicts (``name``, ``error``, ``steps``, ``ny``,
            ``nx``, ``units``, ``crs``, ``first_time``, ``last_time``, ...).
        """
        return RasDssGrid._call("zarr_variables", _path(path))

    @staticmethod
    @log_call
    def read_zarr(path: PathLike, variable: str, *, steps: Tuple[int, int], **kwargs: Any) -> Any:
        """Read steps of a Zarr variable on a window, writing nothing.

        Args:
            path: The store's folder.
            variable: Variable name.
            steps: ``(first, end)`` step indexes.
            **kwargs: ``bbox``, ``rows``, ``cols``, ``limits``, ``stop``, ``strict``.

        Returns:
            The engine's ``ZarrWindow`` (``cells``, ``transform``, ``crs``, ``times``).
        """
        return RasDssGrid._call("read_zarr", _path(path), variable, steps=steps, **kwargs)

    # ------------------------------------------------------------- grid tools

    @staticmethod
    @log_call
    def calculate(input: PathLike, output: PathLike, *, sync: Optional[Any] = None,
                  **kwargs: Any) -> Any:
        """Apply one operation by one constant to every valid cell of each grid.

        Args:
            input: Source grids (a DSS file or a gridded source file).
            output: DSS file to write.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: Exactly one of ``multiply``, ``divide``, ``add``, ``subtract``;
                and ``variables``, ``parts``, ``units``, ``data_type``, ``version``,
                ``align``. A, B and F are empty unless ``parts`` states them.

        Returns:
            The engine's ``ImportResult``.
        """
        return RasDssGrid._call("calculate", _path(input), _path(output), sync=sync, **kwargs)

    @staticmethod
    @log_call
    def calculate_raster(input: PathLike, raster: PathLike, output: PathLike, *,
                         operation: str, sync: Optional[Any] = None, **kwargs: Any) -> Any:
        """Combine each grid, on the left, with a raster resampled to it.

        Args:
            input: Source grids.
            raster: The raster operand (GeoTIFF, ASCII grid or a DSS grid).
            output: DSS file to write.
            operation: ``multiply``, ``divide``, ``add`` or ``subtract``.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: ``method``, ``raster_variable``, ``variables``, ``parts``,
                ``units``, ``data_type``, ``version``, ``align``, ``static_raster``.

        Returns:
            The engine's ``ImportResult``.
        """
        return RasDssGrid._call("calculate_raster", _path(input), _path(raster),
                                _path(output), operation=operation, sync=sync, **kwargs)

    @staticmethod
    @log_call
    def sanitize(input: PathLike, output: PathLike, *, sync: Optional[Any] = None,
                 **kwargs: Any) -> Any:
        """Replace valid cells at or beyond thresholds.

        Args:
            input: Source grids.
            output: DSS file to write.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: ``minimum``, ``maximum`` (inclusive), ``minimum_replacement``,
                ``maximum_replacement`` (NaN, the default, makes the cell missing),
                ``variables``, ``parts``, ``units``, ``data_type``, ``version``, ``align``.

        Returns:
            The engine's ``ImportResult``.
        """
        return RasDssGrid._call("sanitize", _path(input), _path(output), sync=sync, **kwargs)

    @staticmethod
    @log_call
    def clip(input: PathLike, output: PathLike, *, sync: Optional[Any] = None,
             **kwargs: Any) -> Any:
        """Clip grids to an envelope, by nearest neighbour, in their own CRS.

        Args:
            input: Source grids.
            output: DSS file to write.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: ``envelope=(min_x, min_y, max_x, max_y)`` with
                ``envelope_crs``, or ``shapefile`` (its features' combined extent;
                not a polygon mask); ``variables``, ``parts``, ``units``,
                ``data_type``, ``version``, ``align``.

        Returns:
            The engine's ``ImportResult``.
        """
        if kwargs.get("shapefile") is not None:
            kwargs["shapefile"] = _path(kwargs["shapefile"])
        return RasDssGrid._call("clip", _path(input), _path(output), sync=sync, **kwargs)

    @staticmethod
    @log_call
    def normalize(input: PathLike, normals: PathLike, output: PathLike, *, start: Any,
                  end: Any, interval: Any, sync: Optional[Any] = None, **kwargs: Any) -> Any:
        """Scale each interval's source grids so their total matches its normals.

        Args:
            input: Source grids.
            normals: Grids holding the totals to match.
            output: DSS file to write.
            start: Start of the first interval.
            end: End of the last interval.
            interval: A ``datetime.timedelta`` or a number of seconds.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: ``source_variables``, ``normals_variables``, ``parts``,
                ``units``, ``data_type``, ``version``, ``align``.

        Returns:
            The engine's ``NormalizeResult``. Check ``sources_left_out``,
            ``normals_left_out`` and ``cells_made_missing_by_normal``.
        """
        return RasDssGrid._call(
            "normalize", _path(input), _path(normals), _path(output),
            start=start, end=end, interval=interval, sync=sync, **kwargs,
        )

    # -------------------------------------------------------------- time tools

    @staticmethod
    @log_call
    def shift_times(input: PathLike, output: PathLike, *, sync: Optional[Any] = None,
                    **kwargs: Any) -> Any:
        """Move grid records in time. Cell values are kept.

        Args:
            input: DSS file holding the grids.
            output: DSS file to write.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: ``shift`` (a ``datetime.timedelta``), or ``shift_start`` and
                ``shift_end``; ``select``, ``parts``, ``units``, ``data_type``,
                ``version``, ``progress``. A source's A and B parts are not kept
                unless ``parts`` states them.

        Returns:
            The engine's ``TimeToolResult``.
        """
        return RasDssGrid._call("shift_times", _path(input), _path(output), sync=sync, **kwargs)

    @staticmethod
    @log_call
    def resample_times(input: PathLike, output: PathLike, step_minutes: int, *,
                       sync: Optional[Any] = None, **kwargs: Any) -> Any:
        """Resample each grid series to a fixed time step.

        Args:
            input: DSS file holding the grids.
            output: DSS file to write.
            step_minutes: One of ``time_steps()``.
            sync: Flush policy, passed to the engine unchanged (see the class notes).
            **kwargs: ``rule`` (``"strict"`` or ``"vortex"``), ``select``, ``parts``,
                ``units``, ``data_type``, ``version``, ``progress``.

        Returns:
            The engine's ``TimeToolResult``. ``dropped_tail_seconds`` is time after
            the last whole window, which is not in the output.
        """
        return RasDssGrid._call("resample_times", _path(input), _path(output),
                                step_minutes, sync=sync, **kwargs)

    @staticmethod
    @log_call
    def time_steps() -> List[int]:
        """The steps ``resample_times`` takes, in minutes.

        Returns:
            List of ``int`` minutes.
        """
        return RasDssGrid._call("time_steps")

    @staticmethod
    @log_call
    def series_info(input: PathLike, pathname: str) -> Dict[str, Any]:
        """What a grid series states: records, start, end, data type, units and grid.

        Args:
            input: DSS file.
            pathname: Any record of the series.

        Returns:
            The engine's ``dict``.
        """
        return RasDssGrid._call("series_info", _path(input), pathname)

    @staticmethod
    @log_call
    def read_window(input: PathLike, pathname: str, start: Any, end: Optional[Any] = None,
                    **kwargs: Any) -> Any:
        """One window of a grid series, computed as ``resample_times`` computes it.

        Args:
            input: DSS file.
            pathname: Any record of the series.
            start: Window start.
            end: Window end; ``None`` asks for an instant.
            **kwargs: ``rule`` and ``missing`` (``"nan"`` or ``"raw"``).

        Returns:
            The engine's ``WindowGrid`` (``data`` is ``(ny, nx)``, rows south to north).
        """
        return RasDssGrid._call("read_window", _path(input), pathname, start, end, **kwargs)

    @staticmethod
    @log_call
    def read_nearest(input: PathLike, pathname: str, time: Any, **kwargs: Any) -> Any:
        """The grid record of a series nearest a time.

        Args:
            input: DSS file.
            pathname: Any record of the series.
            time: The time to look near.
            **kwargs: ``missing`` (``"nan"`` or ``"raw"``).

        Returns:
            The engine's ``WindowGrid``.
        """
        return RasDssGrid._call("read_nearest", _path(input), pathname, time, **kwargs)

    @staticmethod
    @log_call
    def read_min_max(input: PathLike, pathname: str, start: Any, end: Any,
                     **kwargs: Any) -> Tuple[Any, Any]:
        """The minimum and maximum grids of a series over a window.

        Args:
            input: DSS file.
            pathname: Any record of the series.
            start: Window start.
            end: Window end.
            **kwargs: ``missing`` (``"nan"`` or ``"raw"``).

        Returns:
            ``(minimum, maximum)``, two engine ``WindowGrid`` objects.
        """
        return RasDssGrid._call("read_min_max", _path(input), pathname, start, end, **kwargs)

    # ------------------------------------------------------------------ zonal

    @staticmethod
    @log_call
    def grid_to_point(grids: PathLike, zones: PathLike, zone_field: str, output: PathLike, *,
                      sync: Optional[Any] = None, **kwargs: Any) -> Any:
        """Zonal statistics of each grid, written as one time series per zone and statistic.

        Args:
            grids: A DSS file, GRIB2 file, GeoTIFF or ASCII grid.
            zones: A shapefile or GeoJSON file of zones.
            zone_field: The field that names each zone; it becomes the B part.
            output: DSS file to write the time series to.
            sync: Flush policy, passed to the engine unchanged. ras-commander-fast-dss
                0.1.1 has no such option on this function: stating it then raises
                ``DssCapabilityError``.
            **kwargs: ``statistics`` (default ``("average",)``), ``accumulate``,
                ``parts`` (A and F), ``variables``, ``zones_crs``, ``area_weighted``,
                ``compatibility``, ``version``, ``assume_no_datum_shift``,
                ``allow_in_place``.

        Returns:
            The engine's ``GridToPointResult`` (``records``, ``zones``, ``pathnames``).
        """
        return RasDssGrid._call("grid_to_point", _path(grids), _path(zones), zone_field,
                                _path(output), sync=sync, **kwargs)

    @staticmethod
    @log_call
    def zonal_statistics(grids: PathLike, zones: PathLike, zone_field: str, **kwargs: Any) -> Any:
        """The statistics of ``grid_to_point`` as a table, writing nothing.

        Args:
            grids: A DSS file, GRIB2 file, GeoTIFF or ASCII grid.
            zones: A shapefile or GeoJSON file of zones.
            zone_field: The field that names each zone.
            **kwargs: ``variables``, ``zones_crs``, ``area_weighted``,
                ``compatibility``, ``assume_no_datum_shift``, ``raw``.

        Returns:
            The engine's ``pandas.DataFrame``, one row per frame and zone, unchanged.
            Missing statistics are NaN unless ``raw=True``.
        """
        return RasDssGrid._call("zonal_statistics", _path(grids), _path(zones),
                                zone_field, **kwargs)

    @staticmethod
    @log_call
    def zone_masks(grids: PathLike, zones: PathLike, zone_field: str, **kwargs: Any) -> Dict[str, Any]:
        """Each zone's flat cell indices on the source's last grid.

        Args:
            grids: A DSS file, GRIB2 file, GeoTIFF or ASCII grid.
            zones: A shapefile or GeoJSON file of zones.
            zone_field: The field that names each zone.
            **kwargs: ``variables``, ``zones_crs``, ``assume_no_datum_shift``.

        Returns:
            ``dict`` of zone name to a NumPy index array.
        """
        return RasDssGrid._call("zone_masks", _path(grids), _path(zones), zone_field, **kwargs)
