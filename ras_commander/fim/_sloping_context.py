"""Bounded, explicitly owned HDF staging for repeated 2D reach mapping."""

from copy import deepcopy
from collections import OrderedDict
from pathlib import Path
import tempfile
import threading
import time

from .. import get_logger, log_call
from . import _engine, _sloping
from .errors import FimEngineError, FimUnsupportedError

logger = get_logger(__name__)


class FimPreparedSlopingModel:
    """Reusable sloping inputs created by :meth:`RasFim.prepare_sloping_model`.

    Use a context manager or call :meth:`close` to release staged files and
    geometry. Calls on one context are serialized. Capable engines retain one
    owned process, geometry, terrain blocks and a bounded output/weight cache.
    Capable engines share bounded reconstructed timestep state across reaches.
    Metadata is returned by copy.
    """

    def __init__(
        self,
        hdf_path,
        terrain_path,
        *,
        profiles=None,
        wsel_profiles=None,
        render_mode="sloping",
        reduce_shallow_to_horizontal=False,
        use_depth_weighted_faces=False,
        invalid_cells=None,
        postprocessing_hdf=None,
        corner_elevation_source="auto",
        engine_path=None,
        threads=1,
        max_working_mib=1024,
        max_prepared_mib=1024,
        native_session=True,
        window_cache_mib=64,
        hydraulic_cache_mib=64,
        validation_cache_mib=8,
        terrain_crs_fnv1a64=None,
    ):
        from .RasFim import RasFim, _file_identity, _positive_int
        import rasterio
        import shapely

        started = time.perf_counter()
        self._lock = threading.RLock()
        self._temporary = None
        self._closed = True
        self._info = {}
        self._native_session = None
        self._validated_positions = OrderedDict()
        self._validation_bytes = 0
        for label, value in (
            ("window_cache_mib", window_cache_mib),
            ("hydraulic_cache_mib", hydraulic_cache_mib),
            ("validation_cache_mib", validation_cache_mib),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 4096
            ):
                raise ValueError(f"{label} must be an integer from 0 through 4096")
        self._window_cache_bytes = window_cache_mib << 20
        self._hydraulic_cache_bytes = hydraulic_cache_mib << 20
        self._validation_limit = validation_cache_mib << 20
        if not isinstance(native_session, bool):
            raise TypeError("native_session must be boolean")
        self._reuse_native = native_session
        self._options = _sloping._validate_options(
            render_mode, reduce_shallow_to_horizontal, use_depth_weighted_faces
        )
        from . import _invalid_cells

        self._invalid_records = []
        self._terrain_crs_fnv1a64 = terrain_crs_fnv1a64
        self._invalid_policy = _invalid_cells.validate_policy(
            _invalid_cells.DEFAULT_POLICY if invalid_cells is None else invalid_cells
        )
        self._postprocessing_hdf = postprocessing_hdf
        self._corner_elevation_source = corner_elevation_source
        self._threads = _positive_int(threads, "threads")
        if self._threads > 64:
            raise ValueError("threads must be <= 64")
        self._budget = _positive_int(max_working_mib, "max_working_mib")
        prepared_budget = _positive_int(max_prepared_mib, "max_prepared_mib") * (
            1 << 20
        )
        self._validation_limit = min(self._validation_limit, prepared_budget // 8)
        prepared_budget -= self._validation_limit
        self._supplied = wsel_profiles is not None
        supplied = None
        if self._supplied:
            from ._supplied_wsel import snapshot

            supplied = snapshot(
                wsel_profiles, hdf_path, profiles=profiles, max_bytes=prepared_budget
            )
        self._selected = (
            supplied.selection
            if supplied is not None
            else _sloping._validate_selection(profiles)
        )
        self._hdf = Path(hdf_path).resolve(strict=True)
        self._terrain = Path(terrain_path).resolve(strict=True)
        self._engine = _engine.find_engine(engine_path)
        self._watched = dict(hdf=self._hdf, terrain=self._terrain, engine=self._engine)
        if postprocessing_hdf is not None:
            self._watched["postprocessing_hdf"] = Path(postprocessing_hdf).resolve(
                strict=True
            )
        self._identities = {
            key: _file_identity(path) for key, path in self._watched.items()
        }
        try:
            self._model_scope = RasFim.validate_2d_model(self._hdf)
            geometry = self._model_scope.get("geometry_path")
            if geometry:
                self._watched["geometry"] = Path(geometry).resolve(strict=True)
                self._identities["geometry"] = _file_identity(self._watched["geometry"])
                # Bracket the text-based 1D guard as well as the compiled HDF.
                self._model_scope = RasFim.validate_2d_model(self._hdf)
            self._method = _engine.engine_method(self._engine).get("sloping", {})
            if window_cache_mib != 64 and not self._method.get("multi_window_cache"):
                raise FimEngineError(
                    "Configurable windows require multi_window_cache capability"
                )
            if not self._method.get("hydraulic_cache"):
                self._hydraulic_cache_bytes = 0
            self._reuse_native = (
                self._reuse_native and self._method.get("persistent_session") is True
            )
            _sloping._validate_method(self._method, render_mode, 1)
            if use_depth_weighted_faces and not self._method.get(
                "depth_weighted_faces"
            ):
                raise FimEngineError(
                    "Depth weighting requires an engine advertising depth_weighted_faces (0.8+)"
                )
            if (
                postprocessing_hdf is not None
                and (
                    Path(postprocessing_hdf).parent / "corner_elevation_receipt.json"
                ).exists()
            ):
                from ._corner_preparation import validate_receipt

                _, sources = validate_receipt(self._hdf, postprocessing_hdf)
                self._watched.update(sources)
                self._identities.update(
                    {key: _file_identity(path) for key, path in sources.items()}
                )
            cell_started = time.perf_counter()
            # "raise" defers to each request's AOI; other policies are fixed here.
            self._cells, self._invalid_records = _invalid_cells.load_cells(
                self._hdf, policy=self._invalid_policy, threads=self._threads
            )
            cell_seconds = time.perf_counter() - cell_started
            _invalid_cells.require_cells(
                self._cells, self._invalid_records, self._invalid_policy
            )
            if supplied is not None:
                supplied.check_crs(self._cells.crs)
            # Planned retained frame/GEOS/index allowance, not an RSS limit.
            geometry_bytes = (
                int(self._cells.memory_usage(deep=True).sum())
                + int(shapely.count_coordinates(self._cells.geometry.to_numpy())) * 16
                + len(self._cells) * 256
            )
            if geometry_bytes >= prepared_budget:
                raise FimUnsupportedError("Prepared geometry exceeds max_prepared_mib")
            # Retain the model-wide spatial index once, before reach planning.
            self._cells.sindex
            self._terrain_identity = _engine.terrain_identity(
                self._engine, self._terrain, self._cells.crs, terrain_crs_fnv1a64
            )
            with rasterio.open(self._terrain) as source:
                self._terrain_transform = list(source.transform.to_gdal())
            self._temporary = tempfile.TemporaryDirectory(prefix="ras-fim-prepared-")
            root = Path(self._temporary.name)
            files, self._meshes, max_values = _sloping.write_binary_mesh_inputs(
                self._hdf,
                root,
                threads=self._threads,
                include_max="Max" in self._selected.values(),
                include_vertex_elevations=use_depth_weighted_faces,
                postprocessing_hdf=postprocessing_hdf,
                corner_elevation_source=corner_elevation_source,
                max_staged_bytes=prepared_budget - geometry_bytes,
            )
            mesh_bytes = sum(p.stat().st_size for p in root.iterdir())
            profile_source = None
            if supplied is not None:
                from ._supplied_wsel import stage

                units, values_bytes, profile_source = stage(
                    supplied,
                    root,
                    self._meshes,
                    max_staged_bytes=prepared_budget - geometry_bytes - mesh_bytes,
                )
                views = 0
            else:
                units, views, values_bytes = _sloping._stage_profiles(
                    self._hdf,
                    root,
                    self._meshes,
                    max_values,
                    self._selected,
                    deduplicate=True,
                    max_staged_bytes=prepared_budget - geometry_bytes - mesh_bytes,
                )
            self._mesh_files = [str(root / name) for name in files]
            self._units = {
                unit["id"]: dict(
                    id=unit["id"],
                    values_files=[str(root / name) for name in unit["values_files"]],
                )
                for unit in units
            }
            self._info = dict(
                cache_kind="python-geometry-and-staged-inputs/1",
                profiles=dict(self._selected),
                physical_cells=int(
                    self._cells[["mesh_name", "cell_id"]].drop_duplicates().shape[0]
                ),
                mesh_count=len(self._meshes),
                corner_elevations={
                    m["mesh_name"]: m.get("corner_elevations") for m in self._meshes
                },
                unique_selectors=0
                if self._supplied
                else len(set(self._selected.values())),
                profile_views_prepared=views,
                planned_geometry_bytes=geometry_bytes,
                staged_bytes=mesh_bytes + values_bytes,
                planned_prepared_bytes=geometry_bytes
                + mesh_bytes
                + values_bytes
                + self._validation_limit,
                max_prepared_bytes=prepared_budget + self._validation_limit,
                validation_cache_budget_bytes=self._validation_limit,
                prepare_seconds=time.perf_counter() - started,
                cell_polygon_seconds=cell_seconds,
                invalid_cells=_invalid_cells.describe(
                    self._invalid_records, self._invalid_policy, None
                ),
                native_state_reused=False,
                native_session_enabled=self._reuse_native,
                native_window_cache_budget_bytes=self._window_cache_bytes
                if self._reuse_native
                else 0,
                native_hydraulic_cache_budget_bytes=self._hydraulic_cache_bytes
                if self._reuse_native
                else 0,
                profile_staging_chunk_bytes=8 << 20,
                terrain_crs_identity=dict(self._terrain_identity["crs_identity"]),
            )
            if profile_source is not None:
                self._info["profile_source"] = profile_source
            self._check_sources()
            if (
                postprocessing_hdf is not None
                and (
                    Path(postprocessing_hdf).parent / "corner_elevation_receipt.json"
                ).exists()
            ):
                validate_receipt(self._hdf, postprocessing_hdf)
            self._closed = False
        except BaseException:
            self.close()
            raise

    @property
    def info(self) -> dict:
        """Copy of preparation timing, fixed selectors and planned cache ceilings."""
        with self._lock:
            return deepcopy(self._info)

    @property
    def closed(self) -> bool:
        """Whether this context has released its retained inputs."""
        with self._lock:
            return self._closed

    def _check_sources(self):
        from .RasFim import _file_identity

        changed = []
        for key, path in self._watched.items():
            try:
                if _file_identity(path) != self._identities[key]:
                    changed.append(key)
            except OSError:
                changed.append(key)
        if changed:
            self.close()
            raise FimEngineError(
                f"Prepared sloping sources changed; create a new context: {changed}"
            )
        if "geometry" not in self._watched:
            # An absent optional text file can appear after preparation. Retain
            # the whole-model 1D guard rather than trusting its earlier absence.
            from .RasFim import RasFim

            try:
                scope = RasFim.validate_2d_model(self._hdf)
            except BaseException:
                self.close()
                raise
            if scope.get("geometry_path"):
                self.close()
                raise FimEngineError(
                    "Source geometry appeared; create a new prepared context"
                )

    def _validate_grid(self, plan):
        """Reuse a passed validation only for the identical immutable cell subset."""
        from . import _horizontal

        key = plan.cell_positions.tobytes()
        if key in self._validated_positions:
            self._validated_positions.move_to_end(key)
            return True
        _horizontal.prepare_grid(self._cells, self._terrain, plan, False)
        size = len(key) + 128
        if size <= self._validation_limit:
            while self._validation_bytes + size > self._validation_limit:
                old, _ = self._validated_positions.popitem(last=False)
                self._validation_bytes -= len(old) + 128
            self._validated_positions[key] = None
            self._validation_bytes += size
        return False

    @log_call
    def map_profiles(
        self,
        output_folder,
        *,
        profiles=None,
        bbox=None,
        polygon=None,
        polygon_layer=None,
        aoi_crs=None,
        writer_threads=1,
        max_inflight_profiles=1,
        max_working_mib=None,
        timeout=None,
        write_floodplain=False,
        template_raster=None,
        invalid_cells=None,
        product_writer="rasterio",
        products=None,
        compression=None,
    ):
        """Map all prepared names or an ordered subset into a new/empty folder.

        ``profiles`` is a sequence of prepared names, not timestep selectors.
        Bounding boxes and polygons constrain output pixels, preserving complete
        model connectivity. Working memory and concurrency use the same planned
        admission as ``RasFim.map_sloping_profiles``. The returned manifest's
        performance includes a copy of preparation evidence; its total time
        covers this call only. No additional depth cutoff is applied.
        ``max_working_mib=None`` inherits the factory budget. Source changes
        close the context; invalid profile names leave it usable.
        ``invalid_cells`` is fixed at preparation; ``None`` or the prepared
        policy is accepted and any other value raises ``ValueError``.
        ``product_writer="native"`` requires native_geotiff_outputs and writes
        lossless LZW TIFFs through terrio without raster-array pipe transfers.
        It excludes templates, floodplain polygonization and velocity. The
        default ``"rasterio"`` preserves the existing delivery path. Native
        compression uses one worker; ``writer_threads`` controls Rasterio only.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Prepared sloping context is closed")
            self._check_sources()
            if profiles is None:
                names = list(self._selected)
            elif isinstance(profiles, str):
                names = [profiles]
            elif isinstance(profiles, dict):
                raise TypeError("profiles must be prepared names, not selectors")
            else:
                names = list(profiles)
            if (
                not names
                or any(not isinstance(name, str) for name in names)
                or len(set(names)) != len(names)
            ):
                raise ValueError("profiles must contain unique prepared names")
            unknown = [name for name in names if name not in self._selected]
            if unknown:
                raise ValueError(f"Profiles were not prepared: {unknown}")
            try:
                return _sloping.map_profiles(
                    self._hdf,
                    self._terrain,
                    output_folder,
                    profiles={name: self._selected[name] for name in names},
                    **self._options,
                    postprocessing_hdf=self._postprocessing_hdf,
                    corner_elevation_source=self._corner_elevation_source,
                    engine_path=self._engine,
                    threads=self._threads,
                    writer_threads=writer_threads,
                    max_inflight_profiles=max_inflight_profiles,
                    max_working_mib=(
                        self._budget if max_working_mib is None else max_working_mib
                    ),
                    bbox=bbox,
                    polygon=polygon,
                    polygon_layer=polygon_layer,
                    aoi_crs=aoi_crs,
                    timeout=timeout,
                    write_floodplain=write_floodplain,
                    template_raster=template_raster,
                    invalid_cells=invalid_cells,
                    _prepared=self,
                    product_writer=product_writer, products=products, compression=compression,
                )
            except BaseException:
                self._check_sources()
                if (
                    self._native_session is not None
                    and self._native_session.process.poll() is not None
                ):
                    self._native_session.close()
                    self._native_session = None
                raise

    @log_call
    def close(self) -> None:
        """Release staged files and geometry; safe to call repeatedly."""
        with self._lock:
            self._closed = True
            self._cells = None
            self._validated_positions.clear()
            self._validation_bytes = 0
            if self._native_session is not None:
                self._native_session.close()
                self._native_session = None
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None

    def __enter__(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("Prepared sloping context is closed")
            self._check_sources()
            return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
