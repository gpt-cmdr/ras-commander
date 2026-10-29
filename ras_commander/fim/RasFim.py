"""Optional ras2fim-2D flood inundation mapping (FIM) from 2D cell WSE profiles.

``RasFim`` maps one or more water-surface-elevation (WSE) profiles defined on
HEC-RAS 2D cells to depth and WSE rasters with the ras2fim-2D Step 05 method:

1. linear (Delaunay) interpolation of WSE from the wet cell centres plus the
   wet-cell vertices outside their convex hull;
2. masking to the union of the wet cells;
3. subtraction of the terrain (nearest sample at each pixel centre) and
   removal of negative depths;
4. nearest-neighbour reprojection to an output grid whose origin is snapped
   to a multiple of the output resolution.

This is a different method from RAS Mapper stored maps
(:meth:`ras_commander.RasProcess.store_maps`). The two produce different
rasters and are not interchangeable.

The mapping arithmetic runs in the external ``ras2fim-batch`` engine. RAS
Commander prepares the global inputs in Python, runs the engine in bounded
batches over one shared terrain, validates every output unit, and writes
GeoTIFF and GeoPackage products with a product manifest. RAS Commander does
not build, download, or install the engine, and has no Python fallback for
the mapping arithmetic.

Requires the ``fim`` extra (``pip install "ras-commander[fim]"``) and an
engine executable.

``map_horizontal_profiles`` is a separate optional Rust method for cell-constant
horizontal WSE, with an explicit NumPy qualification reference. It reuses
terrain-lattice ownership across profiles and never substitutes for a failed
Step05 run.

``map_sloping_profiles`` is a separate experimental plain cell-corner sloping
method reconstructed against native RAS Mapper 7.0.1. It reads complete mesh
topology from HDF, uses terrio terrain/ownership and has no extra depth cutoff.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Union

if TYPE_CHECKING:
    import geopandas as gpd
    from ..RasPrj import RasPrj
    from ._sloping_context import FimPreparedSlopingModel
    from .._execution_types import StoreMapPerformanceOptions

import numpy as np
import pandas as pd

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from . import _aoi, _engine, _prepare, _products
from ._aoi import FimAoi
from ._prepare import FimPreparedProfile
from .errors import FimEngineError, FimMappingError, FimUnsupportedError

logger = get_logger(__name__)

MANIFEST_SCHEMA = "ras-commander-fim-manifest/1"
MANIFEST_NAME = "fim_manifest.json"
RAS2FIM_CELLS_LAYER = "02_cells_wsel_ar"
DEFAULT_PROFILE_PREFIX = "wsel"
NUDGE_METHODS = ("lookup", "full_warp")

# Column order of the product manifest returned by map_profiles(); declared
# in ras_commander.schemas as "fim_product_manifest".
MANIFEST_COLUMNS = [
    "profile",
    "status",
    "wet_cells",
    "samples",
    "depth_tif",
    "wse_tif",
    "floodplain_gpkg",
    "col_off",
    "row_off",
    "width",
    "height",
    "transform",
    "crs",
    "depth_finite_pixels",
    "flooded_pixels",
    "error",
    "velocity_tif",
]

PathLike = Union[str, os.PathLike]


def _require_dependencies(*, triangulation: bool = True) -> None:
    """Fail early with installation guidance when the ``fim`` extra is missing."""
    from .._optional_deps import require_module

    modules = ("geopandas", "shapely", "rasterio", "pyproj")
    if triangulation:
        modules = ("scipy.spatial",) + modules
    for name in modules:
        require_module(name, "RasFim")


def _file_identity(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _require_path(value: PathLike, what: str) -> Path:
    path = Path(os.fspath(value))
    if not path.is_file():
        raise FileNotFoundError(f"{what} not found: {path}")
    return path.resolve()


def _prepare_output_folder(output_folder: PathLike) -> Path:
    folder = Path(os.fspath(output_folder))
    if folder.exists():
        if not folder.is_dir():
            raise NotADirectoryError(f"output_folder is not a directory: {folder}")
        if any(folder.iterdir()):
            raise FileExistsError(
                f"output_folder must be new or empty so no existing file is replaced: {folder}"
            )
    folder.mkdir(parents=True, exist_ok=True)
    return folder.resolve()


def _positive_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return int(value)


def _default_threads() -> int:
    return max(1, min((os.cpu_count() or 2) - 1, 16))


def _validate_cells(cells, profiles: Optional[Sequence[str]], profile_prefix: str) -> List[str]:
    if not hasattr(cells, "geometry") or not hasattr(cells, "crs"):
        raise TypeError("cells must be a GeoDataFrame of cell polygons")
    if cells.crs is None:
        raise FimUnsupportedError("cells has no CRS")
    if "cell_idx" not in cells.columns:
        raise KeyError("cells needs a 'cell_idx' column (zero-based HEC-RAS cell index)")
    if not pd.api.types.is_integer_dtype(cells["cell_idx"]):
        raise TypeError("cells 'cell_idx' must be an integer column")
    if cells["cell_idx"].duplicated().any():
        raise ValueError("cells 'cell_idx' values must be unique")
    if profiles is None:
        profiles = [c for c in cells.columns if isinstance(c, str) and c.startswith(profile_prefix)]
        if not profiles:
            raise KeyError(f"cells has no profile columns starting with {profile_prefix!r}")
    else:
        profiles = [profiles] if isinstance(profiles, str) else list(profiles)
        if not profiles:
            raise ValueError("profiles is empty")
        missing = [p for p in profiles if p not in cells.columns]
        if missing:
            raise KeyError(f"profile columns not in cells: {missing}")
        if len(set(profiles)) != len(profiles):
            raise ValueError("profiles contains duplicates")
    if any(not isinstance(p, str) or not _engine._SAFE_ID.fullmatch(p) for p in profiles):
        raise FimUnsupportedError("profile names must match [A-Za-z0-9_.-]+")
    if len({p.casefold() for p in profiles}) != len(profiles):
        raise ValueError("profile names must be unique ignoring case")
    for p in profiles:
        if not pd.api.types.is_numeric_dtype(cells[p]):
            raise TypeError(f"profile column {p!r} must be numeric")
    return profiles


def _validate_centers(centers, cells):
    """Validate caller centres and preserve the upstream ascending id order."""
    from pyproj import CRS

    if not hasattr(centers, "geometry") or not hasattr(centers, "crs"):
        raise TypeError("centers must be a GeoDataFrame of points")
    if "cell_idx" not in centers.columns:
        raise KeyError("centers needs a 'cell_idx' column")
    if not pd.api.types.is_integer_dtype(centers["cell_idx"]):
        raise TypeError("centers 'cell_idx' must be an integer column")
    if centers["cell_idx"].isna().any() or centers["cell_idx"].duplicated().any():
        raise ValueError("centers 'cell_idx' values must be non-null and unique")
    if (
        centers.geometry.isna().any()
        or centers.geometry.is_empty.any()
        or not centers.geom_type.eq("Point").all()
    ):
        raise FimUnsupportedError("centers geometries must be non-empty points")
    if centers.crs is not None and CRS.from_user_input(centers.crs) != CRS.from_user_input(
        cells.crs
    ):
        raise FimUnsupportedError("centers and cells have different CRSs")
    return centers.sort_values("cell_idx", kind="stable").reset_index(drop=True)


def _empty_row(profile: str, status: str, **values) -> dict:
    row = {name: None for name in MANIFEST_COLUMNS}
    row.update(profile=profile, status=status, **values)
    return row


class RasFim:
    """Static namespace for optional triangulated and horizontal FIM methods.

    All methods are static; do not instantiate.
    """

    ENGINE_NAME = _engine.ENGINE_NAME
    ENGINE_ENV_VAR = _engine.ENGINE_ENV_VAR
    MANIFEST_COLUMNS = tuple(MANIFEST_COLUMNS)

    @staticmethod
    @log_call
    def prepare_corner_elevations(
        hdf_path: PathLike, output_folder: PathLike, *, rasmap_path: PathLike,
        terrain_name: str, hecras_version: str = "7.0.1",
    ) -> dict:
        """Prepare a fresh native corner-ground cache for depth-weighted mapping.

        Windows/HEC-RAS 7.0.1 only; uses the exact registered terrain, including
        its modifications. Copies stored property-table elevations when present,
        otherwise invokes native terrain corner sampling with obstructions.
        It does not run hydraulics or modify the source HDF/rasmap. The output
        folder must be new/empty. Returns cache path, preparation seconds and a
        provenance receipt. Preparation is explicit and outside mapping clocks.
        Ordinary Rust mapping never loads HEC-RAS assemblies.

        Args:
            hdf_path: Computed 2D-only plan HDF.
            output_folder: New or empty folder for the cache and receipt.
            rasmap_path: Model rasmap containing the registered terrain.
            terrain_name: Exact registered terrain layer name.
            hecras_version: Qualified native runtime version, currently 7.0.1.

        Returns:
            Dictionary containing ``postprocessing_hdf``, ``receipt_path``,
            ``elapsed_seconds``, per-mesh operations and source provenance.

        Raises:
            ValueError: Unsupported model, runtime, terrain or input binding.
            FileExistsError: Output folder contains existing files.
            RuntimeError: Native preparation fails or changes a source input.
        """
        from ._corner_preparation import prepare

        return prepare(hdf_path, output_folder, rasmap_path=rasmap_path,
                       terrain_name=terrain_name, hecras_version=hecras_version)

    @staticmethod
    @log_call
    def map_catalog(
        jobs: Sequence[Dict[str, Any]], output_folder: PathLike, *,
        threads: int = 4, max_workers: int = 1, strategy: str = "reuse",
        max_memory_mib: int = 8192, max_working_mib: int = 2048,
        max_prepared_mib: int = 1024, memory_headroom_mib: int = 256,
        max_profiles_per_batch: int = 64, writer_threads: int = 1,
        max_inflight_profiles: int = 1,
        window_cache_mib: int = 64, hydraulic_cache_mib: int = 64,
        validation_cache_mib: int = 8, product_writer: str = "rasterio",
        engine_path: Optional[PathLike] = None,
        timeout: Optional[float] = None, cancel_event: Any = None,
        raise_on_failure: bool = True,
    ) -> pd.DataFrame:
        """Map ordered reach/timestep groups under shared CPU/memory budgets.

        Each job is a mapping with ``job_id``, ``hdf_path``, ``terrain_path``,
        ``timesteps`` (saved zero-based indices or ``"Max"``), and ``polygon``
        or ``bbox``. Optional ``polygon_layer``, ``aoi_crs`` and ``reach_id``
        follow the existing AOI contract. ``interpolation`` defaults to
        ``"sloping"``; ``"horizontal"`` selects cell-constant mapping. Sloping
        jobs also accept ``render_mode``, ``reduce_shallow_to_horizontal``,
        ``use_depth_weighted_faces``, ``postprocessing_hdf``,
        ``corner_elevation_source`` and ``invalid_cells``. Unknown fields raise.

        Cache controls follow :meth:`prepare_sloping_model` and are shared
        within each actor's prepared model. ``product_writer="native"`` opts
        into terrio LZW output on engines advertising native_geotiff_outputs;
        it currently requires sloping jobs. The default is ``"rasterio"``.
        Native compression uses one worker. Output masks and float32 values
        are unchanged by the writer.

        Batch known timesteps per reach. Compatible jobs share prepared inputs
        and a serialized native session within each bounded selector union.
        ``max_profiles_per_batch`` limits both request occurrences and staged
        unique selectors per source group; larger lists create additional
        preparation waves. Requested order and duplicate selectors are retained
        as separate ordinal output files. Complete hydraulic topology remains
        available outside the output AOI; no depth postprocessing is added.

        ``threads`` is the global logical-CPU affinity budget (at most 64).
        ``max_workers=1`` favors reuse; ``strategy="reuse"`` combines compatible
        source groups, while ``"parallel"`` keeps jobs as independent work units.
        The latter can duplicate model state and should be timed on the caller's
        workload. Additional workers are opt-in and each
        owns a CPU partition that also contains its compression work. Memory
        admission reserves ``max_working_mib + max_prepared_mib +
        memory_headroom_mib`` per worker before launch. The scheduler reduces
        worker count to fit CPU/memory admission. Each worker's native pool is
        bounded by its partition; ``writer_threads`` must fit that partition.
        Windows/Linux process affinity is required. Sloping requires an engine
        advertising persistent sessions; polygons require the global-lattice
        mask capability. No numerical fallback or engine installation occurs.

        Sampled aggregate worker/descendant RSS and private memory trigger an
        abort when exceeding ``max_memory_mib``; low available host memory also
        aborts. Admission and sampling are not hard OS memory limits and exclude
        the caller's existing memory. ``timeout`` applies to each native batch.
        ``cancel_event`` accepts an object with ``is_set()``. Cancellation or a
        failed job stops admission, terminates owned workers/native children,
        removes uncommitted products and retains acknowledged products/receipts.

        ``output_folder`` must be new or empty. Returns the declared
        ``fim_catalog_manifest`` DataFrame in original job/timestep order.
        ``attrs`` contain performance, catalog status and the JSON receipt path.
        Failures raise ``FimMappingError`` with that DataFrame as ``manifest``;
        ``raise_on_failure=False`` returns it instead. No HEC-RAS execution is
        performed. Terrain preparation, velocity, polygonization and supplied
        WSEL tables remain separate operations.

        Args:
            jobs: Ordered mappings describing model, terrain, AOI and times.
            output_folder: New or empty catalog destination (str or Path).
            threads: Shared logical-CPU budget for owned worker processes.
            max_workers: Upper bound on simultaneous prepared workers.
            strategy: Source reuse, or independent parallel job units.
            max_memory_mib: Aggregate planned/sampled worker memory budget.
            max_working_mib: Per-worker native request admission limit.
            max_prepared_mib: Per-worker retained input admission limit.
            memory_headroom_mib: Reserved per-worker overhead and minimum
                available host memory required while running.
            max_profiles_per_batch: Maximum request occurrences and staged
                unique selectors per preparation wave.
            writer_threads: Compression workers within each CPU partition.
            max_inflight_profiles: Requested native profile concurrency.
            engine_path: Optional explicit native mapping executable.
            timeout: Optional per-native-batch timeout in seconds.
            cancel_event: Optional object exposing is_set().
            raise_on_failure: Raise with partial results, or return them.

        Returns:
            pd.DataFrame: Ordered fim_catalog_manifest rows with status,
            product paths and catalog performance/receipt attrs.

        Raises:
            ValueError: Invalid controls, job fields or destination.
            FimUnsupportedError: Unsupported engine, platform or admission.
            FimMappingError: Execution failed or was cancelled; manifest
                contains acknowledged results when raise_on_failure is True.
        """
        from ._catalog import map_catalog

        return map_catalog(
            jobs, output_folder, threads=threads, max_workers=max_workers,
            strategy=strategy,
            max_memory_mib=max_memory_mib, max_working_mib=max_working_mib,
            max_prepared_mib=max_prepared_mib,
            memory_headroom_mib=memory_headroom_mib,
            max_profiles_per_batch=max_profiles_per_batch,
            writer_threads=writer_threads,
            max_inflight_profiles=max_inflight_profiles,
            window_cache_mib=window_cache_mib, hydraulic_cache_mib=hydraulic_cache_mib,
            validation_cache_mib=validation_cache_mib, product_writer=product_writer,
            engine_path=engine_path, timeout=timeout,
            cancel_event=cancel_event, raise_on_failure=raise_on_failure,
        )

    @staticmethod
    @log_call
    def prepare_sloping_model(
        hdf_path: PathLike, terrain_path: PathLike, *,
        profiles: Optional[Dict[str, Union[str, int]]] = None,
        wsel_profiles: Optional[pd.DataFrame] = None,
        invalid_cells: str = "repair",
        render_mode: str = "sloping",
        reduce_shallow_to_horizontal: bool = False,
        use_depth_weighted_faces: bool = False,
        postprocessing_hdf: Optional[PathLike] = None,
        corner_elevation_source: str = "auto",
        engine_path: Optional[PathLike] = None, threads: int = 1,
        max_working_mib: int = 1024, max_prepared_mib: int = 1024,
        native_session: bool = True,
        window_cache_mib: int = 64, hydraulic_cache_mib: int = 64,
        validation_cache_mib: int = 8,
    ) -> "FimPreparedSlopingModel":
        """Prepare fixed 2D sloping inputs for repeated reach/AOI requests.

        ``profiles`` maps names to Max or stored timestep indices, as in
        :meth:`map_sloping_profiles`. Geometry, spatial index and complete
        staged mesh/WSE inputs are reused. Repeated selectors share files.
        Alternatively pass ``wsel_profiles`` as documented by
        :meth:`map_sloping_profiles`, leaving ``profiles=None``. Values and
        keys are copied and staged during preparation; later caller edits
        do not change the prepared profiles. ``max_prepared_mib`` also admits
        the planned caller-vector snapshot. ``info`` records its provenance.
        Rendering options and threads are fixed for the context's lifetime.
        ``postprocessing_hdf`` optionally supplies a prepared native corner
        cache. ``corner_elevation_source`` is auto, geometry or mapping_cache;
        cache-only use requires the adjacent native preparation receipt.
        ``native_session=True`` retains one serialized native process when the
        engine advertises persistent sessions (0.9+). It reuses geometry,
        stencils, terrain blocks and bounded window/plain-weight caches.
        False, or an older engine, starts a fresh CLI per request. Capable
        engines share reconstructed timestep state across reaches. No depth
        cutoff is added. ``window_cache_mib`` and ``hydraulic_cache_mib`` are
        retained native cache ceilings (default 64 each; 0 disables), admitted
        inside the working budget. Configurable windows require
        ``multi_window_cache``; older engines disable hydraulic caching and
        record zero. ``validation_cache_mib`` (default 8) retains passed checks
        for identical immutable cell subsets, reserving at most one eighth of
        the prepared budget. Each cache accepts integer MiB from 0 to 4096.

        Use the returned context in a ``with`` block or call ``close()``.
        Changes to HDF, terrain, engine or resolved source-text geometry
        size/mtime invalidate and close it.
        Calls are serialized; timestep parallelism is controlled per request
        with ``max_inflight_profiles``. ``max_prepared_mib`` admits estimated
        retained geometry plus actual staged bytes, independently of the
        per-request ``max_working_mib``. Persistent requests admit both native
        cache ceilings, and the prepared budget reserves validation retention.
        Neither is a hard RSS limit;
        decoder and preparation allocations are outside retained admission.
        Numeric profile staging uses native-HDF slabs of at most 8 MiB source
        values, with a bounded float32 conversion buffer.

        Returns:
            FimPreparedSlopingModel: Owned inputs with ``map_profiles``,
            ``info``, ``closed`` and idempotent ``close``. Its mapping method
            accepts an optional ordered subset of prepared names, bbox or
            polygon, and the ordinary delivery/concurrency controls.

        ``invalid_cells`` is fixed at preparation and handled as in
        :meth:`map_sloping_profiles`; ``info["invalid_cells"]`` lists the
        affected cells. With ``"raise"``, preparation succeeds and each request
        refuses only when its AOI (or the whole mesh, without one) intersects
        an invalid cell.
        """
        _require_dependencies(triangulation=False)
        from ._sloping_context import FimPreparedSlopingModel

        return FimPreparedSlopingModel(
            hdf_path, terrain_path, profiles=profiles, wsel_profiles=wsel_profiles, render_mode=render_mode,
            reduce_shallow_to_horizontal=reduce_shallow_to_horizontal,
            use_depth_weighted_faces=use_depth_weighted_faces,
            invalid_cells=invalid_cells,
            postprocessing_hdf=postprocessing_hdf,
            corner_elevation_source=corner_elevation_source,
            engine_path=engine_path, threads=threads,
            max_working_mib=max_working_mib, max_prepared_mib=max_prepared_mib,
            native_session=native_session,
            window_cache_mib=window_cache_mib, hydraulic_cache_mib=hydraulic_cache_mib,
            validation_cache_mib=validation_cache_mib,
        )

    @staticmethod
    @log_call
    def map_sloping_profiles(
        hdf_path: PathLike, terrain_path: PathLike, output_folder: PathLike, *,
        profiles: Optional[Dict[str, Union[str, int]]] = None,
        wsel_profiles: Optional[pd.DataFrame] = None,
        render_mode: str = "sloping",
        reduce_shallow_to_horizontal: bool = False,
        use_depth_weighted_faces: bool = False,
        postprocessing_hdf: Optional[PathLike] = None,
        corner_elevation_source: str = "auto",
        bbox: Optional[Sequence[float]] = None, polygon: Any = None,
        polygon_layer: Optional[str] = None, aoi_crs: Any = None,
        engine_path: Optional[PathLike] = None, threads: int = 1,
        writer_threads: int = 1,
        product_writer: str = "rasterio",
        max_working_mib: int = 1024, timeout: Optional[float] = None,
        max_inflight_profiles: int = 1,
        write_floodplain: bool = False,
        template_raster: Optional[PathLike] = None,
        terrain_hdf: Optional[PathLike] = None,
        velocity: bool = False,
        invalid_cells: str = "repair",
    ) -> pd.DataFrame:
        """Map 2D HDF WSE with the experimental Rust sloping engine.

        ``profiles`` maps output names to ``"Max"`` or zero-based stored
        timestep indices; omitted selects ``{"Max": "Max"}``. Geometry,
        terrio ownership and terrain are reused across profiles. ``threads``
        bounds native reconstruction and pixel workers (1 through 64).

        Alternatively supply ``wsel_profiles`` and leave ``profiles=None``.
        This wide DataFrame has ``mesh_name``, integer ``cell_id``, and one
        real numeric column per named profile. Include every cell of every
        HDF mesh, including ghost cells, exactly once. Row order is arbitrary;
        IDs are zero-based HDF cell IDs, local to each exact mesh name.
        Missing, duplicate, extra or unknown IDs are errors. NaN explicitly
        means dry and is staged as finite float32 minimum. Other values cast
        to float32 without aggregation or decimal rounding; infinity and
        overflow are errors. Finite stored dry sentinels remain unchanged.
        Values are absolute elevations in the same vertical units and datum
        as the original HDF and selected terrain; no conversion is inferred.
        ``hdf_path`` binds identities and hydraulic geometry. Optional table
        attrs ``fim_source_hdf`` and ``crs`` must match when present. Matching
        numeric IDs alone cannot prove a caller used the right source model.
        Do not mutate the input during the call. Prepared contexts own their
        staged snapshot after construction.

        A supplied aggregate or healed terrain does not acquire native parity
        from selector-equivalence tests. The selected rendering options remain
        explicit, and the manifest records caller-vector hashes and scope.

        Defaults to plain cell-corner sloping. ``render_mode="slopingPretty"``
        includes cell faces and accepts the shallow/depth-weighting flags.
        Neither mode adds depth postprocessing. It preserves the native
        float32 plot tolerance. Plain-mode native 7.0.1 Max products were qualified
        on Davis pipes and Bald Eagle bridge/dam examples, and two Davis
        timesteps. Bounded Spring River/Spring Creek comparisons retain the
        complete mesh. Models containing 1D river or cross-section elements
        are rejected before mapping.
        Standalone storage-area surfaces outside the 2D mesh are not mapped.

        ``terrain_path`` must be a same-CRS float32 square-pixel GeoTIFF with
        declared nodata. ``bbox`` or ``polygon`` constrains output pixels;
        polygon masks require the engine's ``global-terrain-lattice/1``
        capability (0.10.1+). AOI edge inclusion uses global source pixel
        coordinates with lower-y/left endpoints included, upper-y/right
        excluded, and northward y. No geometric epsilon is applied. This
        intentionally replaces crop-dependent legacy boundary ties.
        Hydraulic connectivity uses the complete mesh. Polygon constraints accept the
        same geometry/frame/file forms as :meth:`resolve_aoi`.

        Outputs require a new or empty folder. The returned
        ``fim_product_manifest`` DataFrame includes performance evidence in
        ``attrs["performance"]``; the JSON manifest retains the same evidence.
        ``max_working_mib`` is planned admission, not an enforced RSS ceiling.
        ``timeout`` covers the engine stream including product writes.
        A missing or incompatible engine raises; no arithmetic fallback runs.

        Args:
            hdf_path: Computed 2D plan-results HDF, as a string or Path.
            terrain_path: Same-CRS, single-band float32 GeoTIFF with declared
                nodata and north-up square pixels.
            output_folder: New or empty directory for products and manifest.
            profiles: Output names mapped to ``"Max"`` or nonnegative
                zero-based stored timestep indices. Defaults to Max.
            wsel_profiles: Optional complete cell-keyed WSEL table, mutually
                exclusive with profiles. Requires physical and ghost rows in
                every mesh. See ``fim_cell_wsel_profiles`` schema and above.
            render_mode: ``"sloping"`` for corners or ``"slopingPretty"`` for
                corners and faces. Defaults to plain sloping.
            reduce_shallow_to_horizontal: Native connectivity-based horizontal
                rendering for shallow cells; requires slopingPretty.
            use_depth_weighted_faces: Rebalance donated corner/face weights by
                native depth; requires slopingPretty and stored corner elevations.
            postprocessing_hdf: Optional native corner cache. Cache-only input
                requires the adjacent receipt from prepare_corner_elevations.
            corner_elevation_source: auto compares supplied layouts and refuses
                conflicts; geometry or mapping_cache explicitly selects one.
            bbox: Optional output bounds in ``aoi_crs`` or the model CRS.
            polygon: Optional polygon geometry, frame or vector-file AOI.
            polygon_layer: Layer name when the AOI file has multiple layers.
            aoi_crs: Coordinate reference system of the AOI.
            engine_path: Matching engine executable, otherwise environment/PATH.
            threads: Bounded Rust worker count, 1 through 64.
            writer_threads: GeoTIFF compression workers, 1 through 64. Defaults
                to one and can overlap native preparation of later profiles;
                budget both pools. Compression and raster layout are unchanged.
                Overrides GDAL_NUM_THREADS during writes and restores it after
                success or failure, including when the default is used.
            max_working_mib: Planned engine memory admission budget in MiB;
                HDF/Python preparation and polygonization also use memory.
            max_inflight_profiles: Maximum concurrent timestep/profile maps,
                1 through 64. Defaults to sequential processing. Effective
                concurrency is capped by threads, profile count and planned
                memory admission, and recorded in the engine report. Requests
                greater than one require engine concurrency support. All maps
                share the same Rust worker pool, terrain and geometry.
            timeout: Engine stream lifetime in seconds, including output writes.
            product_writer: ``"rasterio"`` (default), or ``"native"`` for
                direct terrio LZW GeoTIFF output on a capable engine. Native
                output preserves the requested CRS/grid and float32 results,
                uses one compression worker, and excludes templates,
                floodplain polygonization and velocity.
            write_floodplain: Also polygonize positive retained depth pixels.
            template_raster: Optional float32 GeoTIFF defining the delivered
                grid, nodata and storage profile. Must share the terrain pixel
                lattice and contain the processing window. Values are written
                once, with nodata padding and no resampling. Offsets in the
                returned manifest then refer to this template grid.
            terrain_hdf: Optional registered terrain HDF. When given,
                ``terrain_path`` must be its unmodified priority-1 source TIFF
                (:meth:`top_priority_terrain_source`), mapped directly without
                a RAS Mapper terrain export. The level-0 mask is staged as the
                request's ``terrain_scope``. Pixels outside that source's
                footprint are accepted only in cells that fail the wet gate;
                otherwise the engine refuses and FimUnsupportedError is raised
                so callers can map on an exported terrain. Plain sloping only;
                terrains with modifications and plans with storage areas are
                refused. Requires engine ``top-priority-source-footprint/1``.
            velocity: Also render velocity magnitude (``rasmapper-sloping-velocity/0``)
                and add ``velocity_tif`` (``12_<profile>_velocity.tif``,
                float32, NaN nodata, model velocity units) to each row. Max
                uses ``Maximum Face Velocity`` with Maximum Water Surface; a
                timestep index uses ``Face Velocity`` at that output time.
                Face normals use face polyline lengths. Drawn where rendered
                depth > 0; native velocity masks can differ from that on a
                small fraction of edge pixels, while values on common pixels
                match native Max maps on the qualified models (see
                ``attrs["velocity"]``). Plain sloping with HDF profiles only; refuses
                ``wsel_profiles``, ``template_raster`` and storage-area plans.
            invalid_cells: Pixel ownership for physical cells whose face
                polylines do not form a valid polygon (for example, a face that
                crosses back over another face of the same cell). HEC-RAS
                computes such cells; strict polygon assembly refuses them.
                ``"repair"`` (default) polygonizes the cell's noded face
                polylines, removes area owned by valid cells and keeps the
                largest part. ``"hull"`` uses the face-point convex hull with
                the same overlap removal. ``"omit"`` leaves the cell unmapped.
                ``"raise"`` keeps the strict refusal, but only when the AOI (or
                the whole mesh, without one) intersects an affected cell.
                Overlapping neighbours of an invalid cell are resolved by
                ascending cell ID; split cells keep every piece and fully
                overlapped cells own no pixels. Hydraulic connectivity,
                corners and interpolation stencils always use the complete HDF
                topology. Horizontal and whole-simulation mapping remain strict.
                ``fim_manifest.json`` and ``attrs["invalid_cells"]`` record each
                cell, the reason and the action taken.

        Returns:
            DataFrame: ``fim_product_manifest`` rows with timing evidence in
            ``attrs["performance"]`` and the JSON manifest. ``mapping_scope``
            and ``model_scope`` attributes identify the included model elements.
            Supplied vectors add ``attrs["profile_source"]`` with canonical
            per-mesh/profile hashes for rendered requests. ``terrain_hdf`` adds
            ``attrs["terrain_scope"]``; ``velocity`` adds ``attrs["velocity"]``.

        Raises:
            FimUnsupportedError: Unsupported model, geometry, AOI or terrain.
            FimEngineNotFoundError: The optional executable is unavailable.
            FimEngineError: Engine failure, inconsistent output or changed input.
            MeshCellPolygonError: ``invalid_cells="raise"`` and an invalid
                cell intersects the requested output.
            ValueError: Invalid profile selectors, supplied identities/values,
                source metadata or resource options.
            TypeError: wsel_profiles is not a pandas DataFrame.
            FileExistsError: The output directory is not empty.
        """
        _require_dependencies(triangulation=False)
        from . import _sloping
        return _sloping.map_profiles(hdf_path, terrain_path, output_folder,
            profiles=profiles, wsel_profiles=wsel_profiles, render_mode=render_mode,
            reduce_shallow_to_horizontal=reduce_shallow_to_horizontal,
            use_depth_weighted_faces=use_depth_weighted_faces,
            postprocessing_hdf=postprocessing_hdf,
            corner_elevation_source=corner_elevation_source,
            bbox=bbox, polygon=polygon, polygon_layer=polygon_layer,
            aoi_crs=aoi_crs, engine_path=engine_path, threads=threads, writer_threads=writer_threads,
            max_working_mib=max_working_mib, timeout=timeout, write_floodplain=write_floodplain,
            max_inflight_profiles=max_inflight_profiles,
            template_raster=template_raster, terrain_hdf=terrain_hdf,
            velocity=velocity, invalid_cells=invalid_cells, product_writer=product_writer)

    @staticmethod
    @log_call
    def top_priority_terrain_source(
        terrain_hdf: PathLike, *, rasmap_path: Optional[PathLike] = None,
    ) -> Dict[str, Any]:
        """Identify the priority-1 source TIFF of a registered terrain HDF.

        RAS Mapper writes stored maps per terrain source, on the source's own
        grid; inside the highest-priority source's footprint the effective
        terrain is that source's original TIFF. Priority is read from the
        source groups' integer ``Priority`` attributes (0 highest) or, when no
        source carries one, from the terrain's own VRT beside the HDF, which
        lists sources highest priority first. Both must agree when present.

        Args:
            terrain_hdf: Registered terrain HDF.
            rasmap_path: Optional rasmap; its terrain layer's elevation
                modification layers are then also reported.

        Returns:
            dict: ``tif`` (Path of the priority-1 source TIFF), ``source_count``,
            ``terrain_hdf``, ``modified`` (terrain modifications present),
            ``source``, ``sources`` (file names in priority order),
            ``priority_basis``, ``mask_dataset``, ``mask_shape``,
            ``modifications`` and ``rasmap_checked``.

        Raises:
            FimUnsupportedError: Priority cannot be proven (missing, partial,
                duplicate or conflicting declarations), the source TIFF or its
                level-0 ``Mask`` is missing, or the rasmap does not register it.
        """
        from . import _terrain_scope

        return _terrain_scope.top_priority_source(terrain_hdf, rasmap_path)

    @staticmethod
    @log_call
    def map_whole_simulation(
        hdf_path: PathLike, terrain_path: PathLike, output_folder: PathLike, *,
        products: Sequence[str] = ("arrival_time", "percent_inundated"),
        threshold: float,
        allow_unqualified: bool = False,
        terrain_hdf: Optional[PathLike] = None,
        threads: int = 1, writer_threads: int = 1,
        max_working_mib: int = 1024, timeout: Optional[float] = None,
        engine_path: Optional[PathLike] = None,
    ) -> pd.DataFrame:
        """Map arrival time, percent time inundated and (opt-in) duration.

        Uses the engine's ``native-whole-simulation-horizontal/1`` method:
        every stored output time of the plan is rendered over the physical 2D
        cells and accumulated per pixel. A pixel is wet at an output time when
        its rendered depth is strictly greater than ``threshold`` and its cell
        passes RAS Mapper's thresholded gate ``wse > cell minimum + threshold``
        (float32). These are RAS Mapper's definitions:

        - ``arrival_time``: first wet output time in **hours since the plan's
          simulation start** (``Plan Information/Simulation Start Time``),
          float32;
        - ``percent_inundated``: ``100 * wet output times / all output times``;
        - ``duration`` (needs ``allow_unqualified=True``): hours from arrival
          to the first dry output time after the last wet one, or to the last
          wet time when that dry time is the final output or there is none.

        Never-wet pixels are NaN. Arrival time and percent inundated are
        qualified against RAS Mapper output: pixel conformance with native
        HEC-RAS 7.0.1 stored maps on Davis p02 and BaldEagleCrkMulti2D bridges
        p05 at a 0.5 ft threshold. RAS Mapper produces the same products in
        horizontal and sloping render modes on those models. Duration differs
        on a few recession pixels by one output interval and is unqualified;
        irregular output intervals are refused unless ``allow_unqualified``.

        Scope: pure 2D plans. Plans with 1D elements or storage areas are
        refused (use RAS Mapper for them).

        Args:
            hdf_path: Computed 2D plan-results HDF.
            terrain_path: Same-CRS float32 GeoTIFF (a RAS Mapper terrain
                export, or with ``terrain_hdf`` the priority-1 source TIFF).
            output_folder: New or empty folder for ``<product>.tif`` and
                ``fim_manifest.json``.
            products: Any of ``arrival_time``, ``percent_inundated``,
                ``duration``. Defaults to the two qualified products.
            threshold: Wet depth threshold in model vertical units (RAS Mapper's
                arrival depth; 0.5 is a half foot only in feet models).
            allow_unqualified: Required for ``duration`` and irregular intervals.
            terrain_hdf: Optional registered terrain HDF whose unmodified
                priority-1 source TIFF is ``terrain_path``. Horizontal
                rendering refuses any mapped pixel outside that source's
                footprint (FimUnsupportedError); map on an export instead.
            threads: Rust worker count, 1 through 64.
            writer_threads: GeoTIFF compression workers, 1 through 64.
            max_working_mib: Planned engine admission budget in MiB.
            timeout: Engine lifetime in seconds, or None.
            engine_path: Engine executable, otherwise environment/PATH.

        Returns:
            DataFrame: ``fim_whole_simulation_manifest`` rows (one per product)
            with ``tif`` paths. ``attrs`` hold ``performance``,
            ``time_reference``, ``model_scope``, ``unqualified`` case counts
            and, with ``terrain_hdf``, ``terrain_scope``.

        Raises:
            FimUnsupportedError: Duration without ``allow_unqualified``, storage
                areas, 1D elements, unprovable or modified terrain, engine
                refusals, or an engine without the method.
            FimEngineNotFoundError: The engine executable is unavailable.
            FimEngineError: Engine failure, inconsistent output or changed input.
            ValueError: Invalid products, threshold or resource options.
            FileExistsError: The output directory is not empty.
        """
        _require_dependencies(triangulation=False)
        from . import _whole_simulation

        return _whole_simulation.map_whole_simulation(
            hdf_path, terrain_path, output_folder, products=products,
            threshold=threshold, allow_unqualified=allow_unqualified,
            terrain_hdf=terrain_hdf, threads=threads, writer_threads=writer_threads,
            max_working_mib=max_working_mib, timeout=timeout, engine_path=engine_path,
        )

    @staticmethod
    @log_call
    def map_horizontal_profiles(
        cells: "gpd.GeoDataFrame",
        terrain_path: PathLike,
        output_folder: PathLike,
        *,
        profiles: Optional[Sequence[str]] = None,
        profile_prefix: str = DEFAULT_PROFILE_PREFIX,
        bbox: Optional[Sequence[float]] = None,
        polygon: Any = None,
        polygon_layer: Optional[str] = None,
        aoi_crs: Any = None,
        min_depth: float = 0.0,
        backend: str = "rust",
        engine_path: Optional[PathLike] = None,
        threads: int = 1,
        writer_threads: int = 1,
        timeout: Optional[float] = None,
        max_working_mib: int = 1024,
        write_floodplain: bool = True,
        raise_on_failure: bool = True,
        hdf_path: Optional[PathLike] = None,
        terrain_hdf: Optional[PathLike] = None,
    ) -> pd.DataFrame:
        """Map cell-constant horizontal WSE using a shared terrain-lattice grid.

        This explicit horizontal method fills each cell with its own WSE. It
        uses the Rust engine by default; NumPy is an explicit reference backend.
        It does not fall back from a failed engine run, interpolate
        between cells, or reproject the output. Cell ownership and terrain
        are prepared once and reused across every requested profile.

        Args:
            cells (geopandas.GeoDataFrame): Valid non-overlapping cell Polygons
                with unique integer ``cell_idx`` and numeric WSE columns.
                NaN marks a dry cell. Not modified.
            terrain_path: Single-band float32 terrain GeoTIFF in the cells'
                CRS, with north-up square pixels and declared nodata.
                Its nodata pixels stay dry.
            output_folder: New or empty folder for rasters and the manifest.
            profiles: Profile columns; defaults to ``profile_prefix`` matches.
            profile_prefix: Prefix for selecting profile columns.
            bbox: Output constraint in ``aoi_crs`` or the terrain CRS.
            polygon: Polygon, MultiPolygon, frame or vector file constraint.
            polygon_layer: Layer name for a multi-layer vector file.
            aoi_crs: CRS of the constraint; see :meth:`resolve_aoi`.
            min_depth: Optional strict positive depth cutoff after native
                visibility, in model elevation units. Zero adds no cutoff.
                Native visibility uses float32 WSE >= float32(terrain + 0.001),
                preserving operation order. Positive cutoffs filter both products;
                0.5 is a half-foot filter only when elevation units are feet.
            backend: "rust" (default) or explicit "numpy" reference arithmetic.
            engine_path: Optional executable path for the Rust backend.
            threads: Rust pixel worker count, 1 through 64.
            writer_threads: GeoTIFF compression workers, 1 through 64. Can
                overlap native work on the next profile; budget both pools.
                Overrides caller GDAL_NUM_THREADS during writes, including
                the default of one; restores it afterwards.
            timeout: Rust subprocess/pipe lifetime in seconds, or None. Includes
                consumer product-writing backpressure; no automatic retry.
            max_working_mib: Planned array admission budget, not an RSS cap.
                Includes planned terrain-cache/decoder terms; excludes
                polygonization and unaccounted runtime overhead. Large
                windows fail before terrain or ownership arrays load.
            write_floodplain: Write product 11 from retained depth pixels.
            raise_on_failure: Raise after writing the manifest if any profile
                failed; otherwise return the failed rows too.
            hdf_path: Source model HDF for the 2D-only scope check. Tables from
                get_cells_from_plan_hdf retain this provenance automatically.
                Standalone tables must contain only 2D cell polygons; without
                model provenance the model's other elements cannot be inspected.
            terrain_hdf: Optional registered terrain HDF. When given,
                ``terrain_path`` must be its unmodified priority-1 source TIFF
                (see :meth:`top_priority_terrain_source`); the level-0 mask is
                staged as ``terrain_scope`` and no terrain export is needed.
                Horizontal rendering has no cell minimum, so the engine refuses
                any mapped pixel outside the source footprint; the refusal is
                raised as FimUnsupportedError so callers can map on an
                exported terrain instead. Requires the Rust backend and an
                engine advertising ``top-priority-source-footprint/1``.

        Returns:
            DataFrame: ``fim_product_manifest`` rows. Offsets refer to the
                terrain grid, shared by all profiles. Product names match
                :meth:`map_profiles`; no nudge is performed in this method.

        Raises:
            FimUnsupportedError: Invalid or overlapping cells, grid/CRS
                mismatch, unsupported terrain or an over-budget window.
            FimMappingError: A failed profile or a changed input file.
            FileExistsError: The output folder is not empty.

        Notes:
            Shared polygon edges use rasterio centre ownership, with the
            higher sorted cell index written last. This is a horizontal
            2D-cell method; it does not reproduce native sloping, 1D or
            structure-specific rendering. Finite input WSE must already
            reflect the caller's cell wet/dry policy. WSE is cast to float32
            before native plotting visibility and subtraction. The intrinsic
            0.001 plotting tolerance is compared in elevation space, not after
            depth subtraction. Positive optional cutoffs compare in float32.
            Product names are layout conventions, not method identifiers.
        """
        _require_dependencies()
        from types import SimpleNamespace
        from . import _horizontal

        names = _validate_cells(cells, profiles, profile_prefix)
        source_hdf = cells.attrs.get("fim_source_hdf")
        if hdf_path is not None and source_hdf is not None:
            if Path(hdf_path).resolve() != Path(source_hdf).resolve():
                raise ValueError("hdf_path differs from the cells' source model")
        if hdf_path is not None or source_hdf is not None:
            RasFim.validate_2d_model(hdf_path if hdf_path is not None else source_hdf)
        if len(cells) == 0:
            raise ValueError("horizontal cells must not be empty")
        if (
            isinstance(min_depth, bool)
            or not np.isfinite(min_depth)
            or min_depth < 0
            or min_depth > np.finfo(np.float32).max
        ):
            raise ValueError("min_depth must be finite and >= 0 in model vertical units")
        if backend not in ("rust", "numpy"):
            raise ValueError("backend must be rust or numpy")
        writer_threads = _positive_int(writer_threads, "writer_threads")
        if writer_threads > 64:
            raise ValueError("writer_threads must be <= 64")
        threads = _positive_int(threads, "threads")
        if threads > 64:
            raise ValueError("threads must be <= 64")
        if timeout is not None and (
            isinstance(timeout, bool) or not np.isfinite(timeout) or timeout <= 0
        ):
            raise ValueError("timeout must be positive and finite, or None")
        engine = _engine.find_engine(engine_path) if backend == "rust" else None
        budget = _positive_int(max_working_mib, "max_working_mib")
        terrain = _require_path(terrain_path, "terrain_path")
        scope_info = None
        if terrain_hdf is not None:
            if backend != "rust":
                raise FimUnsupportedError("terrain_hdf requires the Rust backend")
            from . import _terrain_scope

            scope_info = _terrain_scope.resolve(terrain_hdf, terrain)
        constraint = _aoi.resolve_aoi(
            bbox=bbox,
            polygon=polygon,
            polygon_layer=polygon_layer,
            aoi_crs=aoi_crs,
            default_crs=cells.crs,
        )
        watched = {"terrain": terrain}
        if scope_info is not None:
            watched["terrain_hdf"] = scope_info["terrain_hdf"]
        if isinstance(polygon, (str, os.PathLike)):
            watched["polygon"] = _require_path(polygon, "polygon")
        before = {key: _file_identity(path) for key, path in watched.items()}
        mapping_started = time.perf_counter()
        ordered = cells.sort_values("cell_idx", kind="stable").reset_index(drop=True)
        plan = _horizontal.plan_grid(ordered, terrain, constraint, budget, native=backend == "rust")
        folder = _prepare_output_folder(output_folder)
        rows = {name: _empty_row(name, "not_run") for name in names}
        details = {
            "method": f"horizontal cell-constant WSE / terrain lattice / {backend}",
            "method_id": "horizontal-cell-constant/2",
            "backend": backend,
            "options": {
                "min_depth": float(min_depth),
                "native_plot_tolerance": float(np.float32(0.001)),
                "extra_depth_cutoff": float(min_depth) if min_depth > 0 else None,
                "max_working_mib": budget,
                "write_floodplain": bool(write_floodplain),
                "writer_threads": writer_threads,
                "arithmetic": "float32 gather and subtract",
            },
            "grid": {
                "crs": plan.crs.to_string(),
                "window": list(plan.window.flatten()),
                "transform": tuple(plan.transform)[:6],
                "planned_bytes": plan.planned_bytes,
            },
            "aoi": constraint.describe() if constraint else None,
            "aoi_mask": "global-terrain-lattice/1" if constraint else None,
            "inputs": {
                k: {"path": str(path), "size": before[k][0], "mtime_ns": before[k][1]}
                for k, path in watched.items()
            },
            "status": "in_progress",
        }
        if scope_info is not None:
            from . import _terrain_scope

            details["terrain_scope"] = _terrain_scope.describe(scope_info)

        def manifest():
            frame = pd.DataFrame([rows[name] for name in names], columns=MANIFEST_COLUMNS)
            if scope_info is not None:
                frame.attrs["terrain_scope"] = details["terrain_scope"]
            return frame

        RasFim._write_manifest(folder, manifest(), details)
        try:
            from contextlib import nullcontext
            from . import _horizontal_engine

            prepare_started = time.perf_counter()
            grid = (
                _horizontal.prepare_grid(ordered, terrain, plan)
                if backend == "numpy"
                else _horizontal.prepare_grid(ordered, terrain, plan, False)
            )
            details["timings"] = {
                "prepare_grid_seconds": time.perf_counter() - prepare_started,
                "product_write_seconds": {},
            }
            context = (
                _horizontal_engine.run_batch(
                    engine,
                    terrain,
                    grid,
                    ordered,
                    names,
                    min_depth,
                    threads,
                    budget,
                    details,
                    folder,
                    timeout,
                    scope_info,
                )
                if backend == "rust" and all(plan.shape)
                else nullcontext(None)
            )
            with context as native:
                for name in names:
                    if not all(plan.shape):
                        rows[name] = _empty_row(name, "empty_aoi", crs=plan.crs.to_string())
                        continue
                    try:
                        values = (
                            ordered[name]
                            .iloc[plan.cell_positions]
                            .to_numpy(dtype=np.float64, na_value=np.nan)
                        )
                        if native is None:
                            depth, wse = _horizontal.render(grid, values, float(min_depth))
                        else:
                            unit = native(name)
                            if unit["status"] != "complete":
                                raise FimMappingError(
                                    unit.get("error", "horizontal profile failed")
                                )
                            depth, wse = unit["depth"], unit["wse"]
                            del unit
                        result = SimpleNamespace(
                            profile=name,
                            depth=depth,
                            wse=wse,
                            transform=plan.transform,
                            unit={"window": list(plan.window.flatten())},
                        )
                        rows[name] = _empty_row(
                            name, "pending", samples=0, wet_cells=int(np.isfinite(values).sum())
                        )
                        write_started = time.perf_counter()
                        import rasterio

                        with rasterio.Env(GDAL_NUM_THREADS=str(writer_threads)):
                            rows[name].update(
                                RasFim._write_products(folder, result, plan.crs, write_floodplain)
                            )
                        details["timings"]["product_write_seconds"][name] = (
                            time.perf_counter() - write_started
                        )
                        del depth, wse, result
                    except (FimEngineError, _engine.EngineRefusal):
                        raise
                    except Exception as exc:
                        for path in _products.product_paths(folder, name):
                            path.unlink(missing_ok=True)
                        rows[name] = _empty_row(
                            name, "failed", error=f"{type(exc).__name__}: {exc}"
                        )
            details["timings"]["mapping_seconds"] = time.perf_counter() - mapping_started
            changed = [key for key, path in watched.items() if _file_identity(path) != before[key]]
            if changed:
                raise FimMappingError(
                    f"input files changed during horizontal mapping: {changed}", manifest()
                )
            details["status"] = (
                "failed" if any(row["status"] == "failed" for row in rows.values()) else "complete"
            )
        except BaseException as exc:
            details["status"] = "aborted"
            for name in names:
                for path in _products.product_paths(folder, name):
                    path.unlink(missing_ok=True)
                rows[name] = _empty_row(name, "not_run", error=f"{type(exc).__name__}: {exc}")
            if isinstance(exc, FimMappingError):
                raise FimMappingError(str(exc), manifest()) from exc
            raise
        finally:
            RasFim._write_manifest(folder, manifest(), details)
        output = manifest()
        failed = output.loc[output.status == "failed", "profile"].tolist()
        if failed and raise_on_failure:
            raise FimMappingError(f"horizontal mapping failed for {failed}", output)
        return output

    @staticmethod
    @log_call
    def compare_with_rasmapper(
        plan_number: str,
        terrain_path: PathLike,
        output_folder: PathLike,
        *,
        cells: Optional["gpd.GeoDataFrame"] = None,
        profiles: Optional[Dict[str, str]] = None,
        mesh_name: Optional[str] = None,
        bbox: Optional[Sequence[float]] = None,
        polygon: Any = None,
        polygon_layer: Optional[str] = None,
        aoi_crs: Any = None,
        min_depth: float = 0.0,
        engine_path: Optional[PathLike] = None,
        threads: int = 1,
        writer_threads: int = 1,
        max_working_mib: int = 1024,
        postprocess_reference: bool = False,
        native_performance: Optional["StoreMapPerformanceOptions"] = None,
        terrain_name: Optional[str] = None,
        ras_object: Optional["RasPrj"] = None,
        ras_version: Optional[str] = None,
        timeout: int = 1800,
    ) -> pd.DataFrame:
        """Generate native horizontal stored maps and compare with Rust mapping.

        Native execution goes through :meth:`RasProcess.store_maps`. The
        original .rasmap bytes are verified and restored on success or failure
        under the same project lock. Work on a staged project: native mapping
        can generate other project-side caches. No solver is run.

        Args:
            plan_number: Computed plan in the initialized project.
            terrain_path: Float32 export of the exact registered native terrain,
                including modifications. Matching terrain is the caller's
                responsibility; this function does not export or resample it.
            output_folder: New or empty comparison folder.
            cells: Optional cell polygons and WSE columns. When omitted, use
                the plan's cell maximum results for the selected mesh or "*".
            profiles: Mapping from WSE column to "Max" or an exact native
                timestamp. Required with cells; caller ensures matching WSE.
            mesh_name: Required for automatic extraction from multi-mesh plans;
                use "*" to map all physical 2D cells with globally unique row IDs.
            bbox: Optional comparison/output bounds in aoi_crs.
            polygon: Optional polygon constraint, mutually exclusive with bbox.
            polygon_layer: Layer in a multi-layer polygon file.
            aoi_crs: Constraint CRS; defaults to the cells' CRS.
            min_depth: Zero (default) preserves all native-visible pixels.
                Positive optional cutoffs apply independently to both products
                in model elevation units; 0.5 means half a foot only in feet.
            engine_path: Explicit Rust engine executable, or normal discovery.
            threads: Rust pixel workers (1 through 64).
            writer_threads: Delivery GeoTIFF compression workers (1 through
                64) for Rust and optional filtered native products; same
                resource policy as map_horizontal_profiles.
            max_working_mib: Horizontal array admission budget, not RSS.
            postprocess_reference: Write thresholded native depth/WSE LZW
                products and time this postprocessing separately. Raw native
                products are preserved. Defaults to True.
            native_performance: Optional native StoreMap execution policy.
                Default preserves aggregate StoreAllMaps. Independent helpers
                require a sole registered terrain; their requested policy is
                recorded. Useful for Davis's intermittent aggregate WSE output.
            terrain_name: Exact registered terrain selected for native mapping.
            ras_object: Initialized project object for multi-project use.
            ras_version: Installed native mapping runtime version.
            timeout: Native per-profile mapping/lock timeout in seconds.

        Returns:
            DataFrame: ``fim_comparison`` metrics and raster paths. The JSON
                report retains native runtime, original/restored rasmap hashes,
                strict threshold and batch timing. ``result.attrs["performance"]``
                additionally returns Rust batch, native mapping/postprocessing,
                and comparison timings. Candidate per-profile time is NaN for
                shared batches. A CSV is also written. Ratios are withheld for
                AOIs, unestablished full coverage or native storage-area surfaces.

        Raises:
            FimUnsupportedError: Unsupported or misaligned grids, unavailable
                products, or ambiguous native terrain mosaics.
            ValueError: Invalid profiles, threshold or plan selection.
            RuntimeError: Native mapping or configuration restoration failed.

        Notes:
            The whole source model must be 2D-only: any river centerline/reach
            or cross section is rejected before native execution, even with
            an explicitly selected 2D mesh. Pipe networks are permitted.
            Equality is evaluated only inside the selected 2D cell footprint
            and AOI, on matching lattice pixels without reference resampling.
            Missing WSE is counted separately. This is qualification evidence,
            not automatic acceptance of hydraulic accuracy. Timing includes
            different preparation stages and is not a controlled speed benchmark.
        """
        _require_dependencies()
        from . import _comparison

        return _comparison.run(
            plan_number,
            terrain_path,
            output_folder,
            cells=cells,
            profiles=profiles,
            mesh_name=mesh_name,
            bbox=bbox,
            polygon=polygon,
            polygon_layer=polygon_layer,
            aoi_crs=aoi_crs,
            min_depth=min_depth,
            engine_path=engine_path,
            threads=threads,
            writer_threads=writer_threads,
            max_working_mib=max_working_mib,
            postprocess_reference=postprocess_reference,
            native_performance=native_performance,
            terrain_name=terrain_name,
            ras_object=ras_object,
            ras_version=ras_version,
            timeout=timeout,
        )

    @staticmethod
    @log_call
    def compare_rasters(
        candidate_depth: PathLike, candidate_wse: PathLike,
        reference_depth: PathLike, reference_wse: PathLike, *,
        cells: "gpd.GeoDataFrame", min_depth: float = 0.0,
        terrain_path: Optional[PathLike] = None,
    ) -> Dict[str, Any]:
        """Compare existing depth/WSE rasters on a physical 2D cell footprint.

        Positive cutoffs apply the same strict float32 depth filter independently
        to both products. Zero preserves every valid pixel, including native-valid
        zero depths. Exact fractions compare float32 bits. Files are not changed;
        no maps are generated and references are never resampled. Inputs must share a CRS, resolution and integer-offset
        north-up lattice; cells must use that CRS. Missing WSE is counted
        separately from jointly finite WSE differences. Optional terrain
        supplies native implied-terrain residuals. Returns the numerical
        metrics used by compare_with_rasmapper, without generation timings.

        Reuse qualified raw native maps to demonstrate varying postprocessing
        cutoffs. Candidate inputs must retain all depths needed by the cutoff;
        filtering cannot recover pixels already removed by a higher cutoff.
        Model provenance on cells is checked for the 2D-only scope. A numeric
        comparison does not establish the provenance of caller-supplied files.
        """
        _require_dependencies()
        import rasterio
        from . import _comparison

        if isinstance(min_depth, bool) or not np.isfinite(min_depth) or min_depth < 0 or min_depth > np.finfo(np.float32).max:
            raise ValueError("min_depth must be finite and >= 0 in model elevation units")
        if not hasattr(cells, "geometry") or cells.crs is None or not len(cells):
            raise FimUnsupportedError("comparison requires nonempty 2D cell polygons with CRS")
        if (cells.geometry.isna().any() or cells.geometry.is_empty.any()
                or not cells.geometry.is_valid.all()
                or not cells.geom_type.isin(["Polygon", "MultiPolygon"]).all()):
            raise FimUnsupportedError("comparison requires valid nonempty 2D cell polygons")
        source = cells.attrs.get("fim_source_hdf")
        if source is not None:
            RasFim.validate_2d_model(source)
        paths = [_require_path(p, "comparison raster") for p in
                 (candidate_depth, candidate_wse, reference_depth, reference_wse)]
        terrain = _require_path(terrain_path, "terrain_path") if terrain_path is not None else None
        with rasterio.open(paths[0]) as candidate:
            if not _prepare.same_crs(cells.crs, candidate.crs):
                raise FimUnsupportedError("comparison cells and raster must use the same CRS")
            if terrain is not None:
                with rasterio.open(terrain) as ground:
                    if not _prepare.same_crs(candidate.crs, ground.crs):
                        raise FimUnsupportedError("comparison terrain must use the raster CRS")
        watched = [*paths, *([terrain] if terrain is not None else [])]
        before = {p: _file_identity(p) for p in watched}
        result = _comparison.compare_rasters(*paths, cells, None, min_depth, terrain)
        if any(_file_identity(p) != identity for p, identity in before.items()):
            raise RuntimeError("comparison raster inputs changed during scanning")
        return result

    @staticmethod
    @log_call
    def canonicalize_terrain_crs(terrain_path: PathLike, output_path: PathLike) -> Path:
        """Copy float32 terrain with equivalent canonical EPSG GeoTIFF keys.

        Use explicitly when a native reader cannot interpret custom CRS keys,
        such as the Davis HARN terrain. This is metadata encoding, with no
        reprojection, resampling or elevation change. The source stays read-only.
        Requires an equivalent EPSG CRS and nodata, rejects dataset/alpha masks,
        and verifies all output pixel bits and the grid. Both output_path and
        its .json receipt must be new. Returns the prepared path; raises on
        unsupported input, existing outputs or failed verification. Preparation
        is separate from mapping performance timing.
        """
        from . import _terrain

        return _terrain.canonicalize(terrain_path, output_path)

    @staticmethod
    @log_call
    def validate_2d_model(hdf_path: PathLike, *, geom_path: Optional[PathLike] = None) -> Dict[str, Any]:
        """Require compiled 2D cells and reject any 1D river/reach or cross section.

        Inspect the whole model, even when mapping a selected 2D mesh. Pipes,
        conduits, storage areas and SA/2D connections are permitted. This check
        establishes dimensional scope, not structure-rendering equivalence.
        Source geometry is checked when supplied or resolved from the HDF.
        Returns a scope dictionary; raises FimUnsupportedError for 1D/mixed
        geometry. Unreadable or missing inputs raise instead of passing.
        """
        from . import _scope

        return _scope.inspect_model(hdf_path, geom_path)

    @staticmethod
    @log_call
    def find_engine(engine_path: Optional[PathLike] = None) -> Path:
        """Return the path of the ``ras2fim-batch`` engine executable.

        Resolution order: ``engine_path``, then the ``RAS_COMMANDER_FIM_ENGINE``
        environment variable, ``ras2fim-batch`` on ``PATH``, then the installed
        ``ras-commander-fast-map`` distribution's script. The optional ``fim``
        extra installs that external wheel on qualified platforms.

        Raises:
            FimEngineNotFoundError: No executable was found. The engine is
                never built or installed by a runtime mapping call.
        """
        return _engine.find_engine(engine_path)

    @staticmethod
    @log_call
    def get_engine_info(engine_path: Optional[PathLike] = None) -> Dict[str, Any]:
        """Return the engine path and its method record (``ras2fim-batch method``)."""
        engine = _engine.find_engine(engine_path)
        return {"engine_path": str(engine), "method": _engine.engine_method(engine)}

    @staticmethod
    @log_call
    def get_cells_from_results_gpkg(
        results_gpkg: PathLike,
        layer: str = RAS2FIM_CELLS_LAYER,
    ) -> "gpd.GeoDataFrame":
        """Read a ras2fim-2D hydraulic-results cell layer.

        The ras2fim-2D layer ``02_cells_wsel_ar`` holds one polygon per cell
        with ``cell_idx`` and WSE profile columns (``wsel_*``), NaN where the
        cell is dry for that profile. The file is opened read-only.

        Returns:
            GeoDataFrame: The layer as stored.
        """
        _require_dependencies()
        import geopandas as gpd

        path = _require_path(results_gpkg, "results_gpkg")
        layers = list(gpd.list_layers(path)["name"])
        if layer not in layers:
            raise KeyError(f"layer {layer!r} not in {path.name} (layers: {layers})")
        return gpd.read_file(path, layer=layer)

    @staticmethod
    @log_call
    def get_cell_centers(
        hdf_path: PathLike,
        cell_ids: Optional[Iterable[int]] = None,
        *,
        mesh_name: Optional[str] = None,
    ) -> "gpd.GeoDataFrame":
        """Return HEC-RAS 2D cell centres for the FIM method.

        Centres are the computational cell centres (``HdfMesh.get_mesh_cell_points``),
        not polygon centroids.

        Args:
            hdf_path: Plan or geometry HDF that contains the 2D mesh geometry.
            cell_ids: Zero-based cell indices to return. ``None`` returns every
                cell. Duplicates are removed and the result is sorted by
                ``cell_idx``.
            mesh_name: 2D flow area name. Required when the HDF has more than one.

        Returns:
            gpd.GeoDataFrame: Cell indices and point geometries.

        Raises:
            FimUnsupportedError: No mesh, an ambiguous or unknown mesh, or a
                requested cell that is not in the mesh.
        """
        _require_dependencies()
        from ..hdf.HdfMesh import HdfMesh

        path = _require_path(hdf_path, "hdf_path")
        points = HdfMesh.get_mesh_cell_points(path, include_ghost_cells=True)
        if points is None or len(points) == 0:
            raise FimUnsupportedError(f"{path.name}: no 2D mesh cell centres could be read")
        names = list(dict.fromkeys(points["mesh_name"]))
        if mesh_name is None:
            if len(names) != 1:
                raise FimUnsupportedError(
                    f"{path.name} has {len(names)} 2D flow areas {names}; pass mesh_name"
                )
            mesh_name = names[0]
        elif mesh_name not in names:
            raise FimUnsupportedError(f"mesh {mesh_name!r} not in {path.name} (meshes: {names})")
        mesh = points[points["mesh_name"] == mesh_name]
        by_id = mesh.set_index("cell_id")
        if cell_ids is None:
            ids = np.asarray(sorted(by_id.index))
        else:
            ids = np.asarray(sorted(set(int(v) for v in cell_ids)), dtype=np.int64)
            missing = ids[~np.isin(ids, by_id.index.to_numpy())]
            if len(missing):
                raise FimUnsupportedError(
                    f"{len(missing)} cell_idx values are not in mesh {mesh_name!r}: {missing[:10].tolist()}"
                )
        import geopandas as gpd

        return gpd.GeoDataFrame(
            {"cell_idx": ids, "geometry": by_id.loc[ids, "geometry"].to_numpy()},
            geometry="geometry",
            crs=points.crs,
        )

    @staticmethod
    @log_call
    def get_cells_from_plan_hdf(
        hdf_path: PathLike,
        *,
        mesh_name: Optional[str] = None,
        profile_name: str = "wsel_max",
        min_depth: float = 0.0,
    ) -> "gpd.GeoDataFrame":
        """Build a one-profile cell table from a plan HDF's maximum results.

        Uses ``HdfMesh.get_mesh_cell_polygons(strict=True)``,
        ``HdfResultsMesh.get_mesh_max_ws`` and ``HdfResultsMesh.get_mesh_max_depth``.
        A cell is wet when its maximum depth is greater than ``min_depth``;
        dry cells get NaN. This is the cell wet/dry policy; mapping's pixel
        ``min_depth`` independently filters the resulting terrain-based depths.
        Models with 1D river/reach elements are rejected. ``mesh_name="*"``
        combines all meshes and assigns global positional ``cell_idx`` values;
        a single mesh retains its original cell IDs. Source-HDF provenance is
        retained in the returned frame's attrs for later mapping scope checks.

        Returns:
            gpd.GeoDataFrame: Cell indices, profile WSE and polygon geometries.
                Frames from plans on the same geometry can be joined on
                ``cell_idx`` to map a batch of profiles.
        """
        _require_dependencies()
        import geopandas as gpd

        from ..hdf.HdfMesh import HdfMesh
        from ..hdf.HdfResultsMesh import HdfResultsMesh

        path = _require_path(hdf_path, "hdf_path")
        scope = RasFim.validate_2d_model(path)
        if not np.isfinite(min_depth) or min_depth < 0:
            raise ValueError(f"min_depth must be finite and >= 0, got {min_depth!r}")
        polygons = HdfMesh.get_mesh_cell_polygons(path, strict=True)
        if polygons is None or len(polygons) == 0:
            raise FimUnsupportedError(f"{path.name}: no 2D mesh cell polygons could be read")
        names = list(dict.fromkeys(polygons["mesh_name"]))
        if mesh_name is None:
            if len(names) != 1:
                raise FimUnsupportedError(
                    f"{path.name} has {len(names)} 2D flow areas {names}; pass mesh_name"
                )
            mesh_name = names[0]
        elif mesh_name != "*" and mesh_name not in names:
            raise FimUnsupportedError(f"mesh {mesh_name!r} not in {path.name} (meshes: {names})")

        def _one(frame, column_hint, selected_mesh):
            frame = frame[frame["mesh_name"] == selected_mesh]
            columns = [
                c
                for c in frame.columns
                if column_hint in str(c).lower() and "time" not in str(c).lower()
            ]
            if len(columns) != 1:
                raise FimUnsupportedError(
                    f"cannot identify the {column_hint} column in {list(frame.columns)}"
                )
            return frame.set_index("cell_id")[columns[0]]

        maximum_wse = HdfResultsMesh.get_mesh_max_ws(path, include_geometry=False)
        maximum_depth = HdfResultsMesh.get_mesh_max_depth(path, include_geometry=False)
        parts = []
        for selected_mesh in (names if mesh_name == "*" else [mesh_name]):
            wse = _one(maximum_wse, "water_surface", selected_mesh)
            depth = _one(maximum_depth, "depth", selected_mesh)
            cells = polygons[polygons["mesh_name"] == selected_mesh]
            ids = cells["cell_id"].to_numpy(dtype=np.int64)
            if len(np.setdiff1d(ids, wse.index)) or len(np.setdiff1d(ids, depth.index)):
                raise FimUnsupportedError("maximum results are missing for mesh cells")
            values = wse.loc[ids].to_numpy(dtype=np.float64)
            wet = depth.loc[ids].to_numpy(dtype=np.float64) > float(min_depth)
            parts.append(gpd.GeoDataFrame({"cell_idx": ids,
                profile_name: np.where(wet, values, np.nan),
                "geometry": cells.geometry.to_numpy()}, crs=polygons.crs))
        output = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=polygons.crs)
        if mesh_name == "*":
            # Mesh-local identifiers can collide; ownership needs one global row key.
            output["cell_idx"] = np.arange(len(output), dtype=np.int64)
        output.attrs.update(fim_source_hdf=str(path.resolve()),
                            fim_mesh_names=names if mesh_name == "*" else [mesh_name],
                            fim_full_2d_coverage=(mesh_name == "*" or len(names) == 1),
                            fim_model_scope=scope)
        return output

    @staticmethod
    @log_call
    def resolve_aoi(
        bbox: Optional[Sequence[float]] = None,
        polygon: Any = None,
        *,
        polygon_layer: Optional[str] = None,
        aoi_crs: Any = None,
        default_crs: Any = None,
    ) -> Optional[FimAoi]:
        """Validate a bounding box OR polygon area of interest.

        Args:
            bbox: ``(xmin, ymin, xmax, ymax)``. Its CRS is ``aoi_crs``, else
                ``default_crs``.
            polygon: A Shapely Polygon/MultiPolygon (needs ``aoi_crs``), a
                GeoDataFrame, or a vector file path (GeoJSON, GeoPackage, ...).
                Holes and multiple parts are kept; features are unioned.
            polygon_layer: Layer of a multi-layer polygon file.
            aoi_crs: CRS of the AOI. Must agree with a frame or file CRS.
            default_crs: CRS used for a bbox without ``aoi_crs``.

        Returns:
            FimAoi, or None when neither bbox nor polygon is given.

        Raises:
            FimAoiError: Both or invalid AOIs, a missing or conflicting CRS,
                invalid or empty geometry.
        """
        _require_dependencies()
        return _aoi.resolve_aoi(
            bbox=bbox,
            polygon=polygon,
            polygon_layer=polygon_layer,
            aoi_crs=aoi_crs,
            default_crs=default_crs,
        )

    @staticmethod
    @log_call
    def prepare_profile(
        cells,
        centers,
        profile: str,
        pixel_size: float,
        lattice_origin: Optional[Sequence[float]] = None,
    ) -> FimPreparedProfile:
        """Prepare the global interpolation samples and axes for one profile.

        This is the preparation ``map_profiles`` sends to the engine, exposed
        for inspection and qualification. It always uses every wet cell.
        Inputs are not modified. ``lattice_origin`` (a terrain pixel corner
        ``(x, y)``) gives the ``grid_anchor="terrain"`` query axes.
        """
        _require_dependencies()
        _validate_cells(cells, [profile], DEFAULT_PROFILE_PREFIX)
        if not (np.isfinite(pixel_size) and pixel_size > 0):
            raise ValueError(f"pixel_size must be positive, got {pixel_size!r}")
        if lattice_origin is not None:
            lattice_origin = tuple(float(v) for v in lattice_origin)
            if len(lattice_origin) != 2 or not np.isfinite(lattice_origin).all():
                raise ValueError(
                    f"lattice_origin must be two finite numbers, got {lattice_origin!r}"
                )
        return _prepare.prepare_profile(
            cells,
            _validate_centers(centers, cells),
            profile,
            float(pixel_size),
            lattice_origin=lattice_origin,
        )

    @staticmethod
    @log_call
    def map_profiles(
        cells,
        terrain_path: PathLike,
        output_folder: PathLike,
        *,
        profiles: Optional[Sequence[str]] = None,
        profile_prefix: str = DEFAULT_PROFILE_PREFIX,
        centers=None,
        hdf_path: Optional[PathLike] = None,
        mesh_name: Optional[str] = None,
        output_crs: Any = "EPSG:3857",
        output_resolution: float = 3.0,
        bbox: Optional[Sequence[float]] = None,
        polygon: Any = None,
        polygon_layer: Optional[str] = None,
        aoi_crs: Any = None,
        aoi: Optional[FimAoi] = None,
        engine_path: Optional[PathLike] = None,
        threads: Optional[int] = None,
        profiles_per_request: int = 4,
        max_inflight_profiles: int = 1,
        max_cache_mib: int = 64,
        max_profile_mib: int = 1024,
        nudge_method: str = "lookup",
        grid_anchor: str = "ras2fim",
        coplanar: str = "error",
        terrain_crs_fnv1a64: Optional[str] = None,
        write_floodplain: bool = True,
        keep_work: bool = False,
        timeout: Optional[float] = None,
        raise_on_failure: bool = True,
    ) -> pd.DataFrame:
        """Map a batch of cell WSE profiles to depth and WSE rasters.

        This is the triangulated ras2fim-2D Step 05 method. It can produce
        different wet extents from native horizontal cell filling. Use
        :meth:`map_horizontal_profiles` when cell-constant horizontal WSE is
        the intended mapping method; changing a grid anchor does not change
        triangulation into cell filling.

        Every profile shares one terrain and one engine session per request
        of ``profiles_per_request`` profiles. Sample preparation, Delaunay
        topology, query axes and the wet mask always use every wet cell of a
        profile. An AOI only selects pixels of the final output grid, so an
        AOI product equals the crop of the full product. The preparation cost
        therefore does not shrink with the AOI.

        Args:
            cells (geopandas.GeoDataFrame): Cell polygons with ``cell_idx`` and WSE
                profile columns (NaN = dry), in the terrain CRS. Not modified.
            terrain_path: Single-band terrain GeoTIFF, same CRS as ``cells``.
                Its pixel width is the interpolation pixel size.
            output_folder: New or empty folder for products and the manifest.
            profiles: Profile columns to map. Default: columns starting with
                ``profile_prefix``.
            centers (geopandas.GeoDataFrame): Unique integer ``cell_idx`` and centre points.
                Give either ``centers`` or ``hdf_path``.
            hdf_path: Plan or geometry HDF; centres are read through
                :meth:`get_cell_centers`.
            mesh_name: 2D flow area for ``hdf_path`` (required for several).
            output_crs: CRS of the final grid (must have an EPSG code).
            output_resolution: Final pixel size in ``output_crs`` units.
            bbox: Bounding box; without ``aoi_crs`` it is in ``output_crs``.
            polygon: Polygon area of interest; see :meth:`resolve_aoi`.
            polygon_layer: Layer name for a polygon file.
            aoi_crs: CRS of the area of interest.
            aoi: A :class:`FimAoi` from :meth:`resolve_aoi` (instead of the
                bbox/polygon arguments).
            engine_path: Engine executable; see :meth:`find_engine`.
            threads: Engine threads. Default ``min(cpu_count - 1, 16)``.
            profiles_per_request: Profiles prepared and run per engine call.
                This bounds the prepared inputs on disk at one time.
            max_inflight_profiles: Profiles the engine evaluates concurrently
                within one call (default 1). Concurrent profiles share one
                decoded-terrain cache and the ``threads`` pool; each counts
                against ``max_profile_mib``.
            max_cache_mib: Engine decoded-terrain cache budget.
            max_profile_mib: Engine per-profile working-set budget; a profile
                whose planned peak exceeds it fails before allocation.
            nudge_method: ``"lookup"`` (one full-grid index warp, AOI pixels
                gathered from it) or ``"full_warp"``.
            grid_anchor: ``"ras2fim"`` (default, the upstream grids: query
                axes from the wet-union bounds, final origin snapped to a
                multiple of ``output_resolution``) or ``"terrain"``: both grids
                on the terrain pixel lattice, so each pixel takes the terrain
                pixel it lies on and products stack with the terrain. Needs a
                north-up terrain with square pixels, ``output_crs`` equal to the
                results CRS and ``output_resolution`` equal to the terrain
                pixel size. Not the upstream Step 05 grid.
            coplanar: ``"error"`` (default) fails a profile whose samples
                include points Qhull reports as coplanar or duplicate;
                ``"ignore"`` maps it without them, as upstream ``griddata``
                does, and records the count in the manifest.
            terrain_crs_fnv1a64: Engine WKT hash to accept when the engine
                cannot identify the terrain EPSG code.
            write_floodplain: Write product 11.
            keep_work: Keep the engine requests and raw outputs in
                ``output_folder/.fim_work`` for review.
            timeout: Seconds allowed per engine call (default no limit).
            raise_on_failure: Raise :class:`FimMappingError` when any profile
                fails (default). The manifest is written first either way.

        Returns:
            DataFrame with one row per profile (``fim_product_manifest``
            schema). ``status`` is ``complete``, ``no_flooded_pixels``,
            ``empty_aoi``, ``failed``, or ``not_run`` (a fatal engine error
            stopped the batch sequence). The manifest is also written to
            ``fim_manifest.json`` before any error is raised.

        Raises:
            FimEngineNotFoundError: No engine executable.
            FimEngineError: The engine rejected a request or crashed.
            FimUnsupportedError: Input outside the engine contract.
            FimAoiError: Invalid area of interest.
            FimMappingError: One or more profiles failed.
            FileExistsError: ``output_folder`` is not empty.
        """
        _require_dependencies()
        import rasterio
        from pyproj import CRS

        profiles = _validate_cells(cells, profiles, profile_prefix)
        terrain = _require_path(terrain_path, "terrain_path")
        if (centers is None) == (hdf_path is None):
            raise ValueError("give exactly one of centers or hdf_path")
        if nudge_method not in NUDGE_METHODS:
            raise ValueError(f"nudge_method must be one of {NUDGE_METHODS}, got {nudge_method!r}")
        if grid_anchor not in _prepare.GRID_ANCHORS:
            raise ValueError(
                f"grid_anchor must be one of {_prepare.GRID_ANCHORS}, got {grid_anchor!r}"
            )
        if coplanar not in _prepare.COPLANAR_POLICIES:
            raise ValueError(
                f"coplanar must be one of {_prepare.COPLANAR_POLICIES}, got {coplanar!r}"
            )
        threads = _default_threads() if threads is None else _positive_int(threads, "threads")
        profiles_per_request = _positive_int(profiles_per_request, "profiles_per_request")
        max_inflight_profiles = _positive_int(max_inflight_profiles, "max_inflight_profiles")
        max_cache_mib = _positive_int(max_cache_mib, "max_cache_mib")
        max_profile_mib = _positive_int(max_profile_mib, "max_profile_mib")
        if not (np.isfinite(output_resolution) and output_resolution > 0):
            raise ValueError(f"output_resolution must be positive, got {output_resolution!r}")
        output_crs = CRS.from_user_input(output_crs)
        dst_epsg = output_crs.to_epsg()
        if dst_epsg is None:
            raise FimUnsupportedError(f"output_crs {output_crs.to_string()} has no EPSG code")
        if aoi is not None:
            if any(v is not None for v in (bbox, polygon, polygon_layer, aoi_crs)):
                raise ValueError("give aoi or the bbox/polygon arguments, not both")
            if not isinstance(aoi, FimAoi):
                raise TypeError("aoi must be a FimAoi from RasFim.resolve_aoi()")
        else:
            aoi = _aoi.resolve_aoi(
                bbox=bbox,
                polygon=polygon,
                polygon_layer=polygon_layer,
                aoi_crs=aoi_crs,
                default_crs=output_crs,
            )

        engine = _engine.find_engine(engine_path)
        method = _engine.engine_method(engine)

        watched = {"terrain": terrain}
        if hdf_path is not None:
            watched["hdf"] = _require_path(hdf_path, "hdf_path")
            RasFim.validate_2d_model(watched["hdf"])
        if isinstance(polygon, (str, os.PathLike)):
            watched["polygon"] = _require_path(polygon, "polygon")
        before = {k: _file_identity(p) for k, p in watched.items()}

        if hdf_path is not None:
            centers = RasFim.get_cell_centers(
                watched["hdf"], cells["cell_idx"].to_numpy(), mesh_name=mesh_name
            )
            # HDF centres are model coordinates; as in ras2fim-2D they take the
            # cells' CRS (HDF and GeoPackage WKT spellings can differ).
            centers = centers.set_crs(cells.crs, allow_override=True)
        else:
            centers = _validate_centers(centers, cells)
        with rasterio.open(terrain) as src:
            pixel_size = float(src.res[0])
            terrain_bounds = tuple(src.bounds)
            terrain_transform = src.transform
        lattice_origin = lattice_bounds = None
        if grid_anchor == "terrain":
            t = terrain_transform
            if (
                t.b
                or t.d
                or t.a <= 0
                or t.e >= 0
                or not np.isclose(t.a, -t.e, rtol=1e-12, atol=0.0)
            ):
                raise FimUnsupportedError(
                    "grid_anchor='terrain' needs a north-up terrain with square pixels"
                )
            if not _prepare.same_crs(output_crs, cells.crs):
                raise FimUnsupportedError(
                    "grid_anchor='terrain' needs output_crs equal to the results CRS"
                )
            if not np.isclose(
                float(output_resolution), pixel_size, rtol=_prepare.LATTICE_TOLERANCE, atol=0.0
            ):
                raise FimUnsupportedError(
                    f"grid_anchor='terrain' needs output_resolution equal to the terrain pixel size {pixel_size!r}"
                )
            output_resolution = pixel_size
            lattice_origin = (float(t.c), float(t.f))
            lattice_bounds = terrain_bounds
        coplanar_samples: Dict[str, int] = {}
        terrain_block = _engine.terrain_identity(engine, terrain, cells.crs, terrain_crs_fnv1a64)

        folder = _prepare_output_folder(output_folder)
        work = Path(tempfile.mkdtemp(prefix=".fim_work_", dir=folder))
        rows: Dict[str, dict] = {}
        reports = []
        fatal: Optional[BaseException] = None
        try:
            for batch, start in enumerate(range(0, len(profiles), profiles_per_request)):
                names = profiles[start : start + profiles_per_request]
                batch_dir = work / f"batch_{batch:04d}"
                (batch_dir / "masks").mkdir(parents=True)
                requests = []
                for name in names:
                    try:
                        prep = _prepare.prepare_profile(
                            cells,
                            centers,
                            name,
                            pixel_size,
                            lattice_origin=lattice_origin,
                            lattice_bounds=lattice_bounds,
                        )
                        grids = _prepare.derive_grids(
                            prep, terrain_bounds, output_crs, output_resolution
                        )
                        window, mask_file = None, None
                        if aoi is not None:
                            window = _aoi.aoi_window(
                                aoi,
                                grids.dest_transform,
                                grids.dest_width,
                                grids.dest_height,
                                output_crs,
                            )
                            if window.is_empty:
                                rows[name] = _empty_row(
                                    name,
                                    _aoi.AOI_STATUS_EMPTY,
                                    wet_cells=prep.wet_cell_count,
                                    samples=prep.sample_count,
                                    crs=output_crs.to_string(),
                                )
                                continue
                            if window.mask is not None:
                                mask_file = f"masks/{name}.u8"
                                np.ascontiguousarray(window.mask, dtype=np.uint8).tofile(
                                    batch_dir / mask_file
                                )
                        inputs_dir = f"inputs/{name}"
                        written = _prepare.write_profile_inputs(
                            batch_dir / inputs_dir, prep, grids, coplanar=coplanar
                        )
                        if written["coplanar_samples"]:
                            coplanar_samples[name] = written["coplanar_samples"]
                        grids.wet_mask = None
                        rows[name] = _empty_row(
                            name,
                            "pending",
                            wet_cells=prep.wet_cell_count,
                            samples=prep.sample_count,
                        )
                        requests.append(
                            _engine.ProfileRequest(name, inputs_dir, grids, window, mask_file)
                        )
                        del prep
                    except (OSError, MemoryError):
                        raise
                    except Exception as exc:  # e.g. Qhull errors on degenerate samples
                        logger.error("FIM profile %s failed during preparation: %s", name, exc)
                        rows[name] = _empty_row(
                            name, "failed", error=f"{type(exc).__name__}: {exc}"
                        )
                if not requests:
                    continue
                request = _engine.build_request(
                    terrain_block,
                    requests,
                    dst_epsg=dst_epsg,
                    threads=threads,
                    max_cache_bytes=max_cache_mib * 1024 * 1024,
                    max_profile_bytes=max_profile_mib * 1024 * 1024,
                    nudge_method=nudge_method,
                    max_inflight_profiles=max_inflight_profiles,
                )
                outputs, report = _engine.run_request(
                    engine, batch_dir, batch, request, requests, timeout
                )
                reports.append(
                    {"batch": batch, "profiles": [r.profile for r in requests], "report": report}
                )
                for result in outputs:
                    row = rows[result.profile]
                    if result.status != "complete":
                        logger.error("FIM profile %s failed: %s", result.profile, result.error)
                        row.update(status="failed", error=result.error)
                        continue
                    row.update(RasFim._write_products(folder, result, output_crs, write_floodplain))
                if not keep_work:
                    shutil.rmtree(batch_dir)
        except Exception as exc:
            fatal = exc
            message = f"not completed: {type(exc).__name__}: {exc}"
            for name in profiles:
                row = rows.get(name)
                if row is None:
                    rows[name] = _empty_row(name, "not_run", error=message)
                elif row["status"] == "pending":
                    row.update(status="failed", error=message)
        finally:
            if keep_work:
                kept = folder / ".fim_work"
                work.rename(kept)
                work = kept
            else:
                shutil.rmtree(work, ignore_errors=True)

        after = {k: _file_identity(p) for k, p in watched.items()}
        changed = [k for k in watched if before[k] != after[k]]

        manifest = pd.DataFrame([rows[p] for p in profiles], columns=MANIFEST_COLUMNS)
        RasFim._write_manifest(
            folder,
            manifest,
            {
                "engine_path": str(engine),
                "method": method,
                "reports": reports,
                "inputs": {
                    k: {"path": str(p), "size": after[k][0], "mtime_ns": after[k][1]}
                    for k, p in watched.items()
                },
                "options": {
                    "output_crs": output_crs.to_string(),
                    "output_resolution": float(output_resolution),
                    "pixel_size": pixel_size,
                    "threads": threads,
                    "profiles_per_request": profiles_per_request,
                    "max_inflight_profiles": max_inflight_profiles,
                    "max_cache_mib": max_cache_mib,
                    "max_profile_mib": max_profile_mib,
                    "nudge_method": nudge_method,
                    "grid_anchor": grid_anchor,
                    "coplanar": coplanar,
                    "write_floodplain": bool(write_floodplain),
                    "mesh_name": mesh_name,
                },
                "coplanar_samples": coplanar_samples,
                "aoi": aoi.describe() if aoi is not None else None,
                "work_folder": str(work) if keep_work else None,
            },
        )
        if fatal is not None:
            raise fatal
        if changed:
            raise FimMappingError(f"input files changed during mapping: {changed}", manifest)
        failed = manifest.loc[manifest["status"].isin(["failed", "not_run"]), "profile"].tolist()
        if failed and raise_on_failure:
            raise FimMappingError(
                f"{len(failed)} of {len(profiles)} profile(s) failed: {failed}; see {folder / MANIFEST_NAME}",
                manifest,
            )
        return manifest

    @staticmethod
    @log_call
    def map_ras2fim_results(
        results_gpkg: PathLike,
        hdf_path: PathLike,
        terrain_path: PathLike,
        output_folder: PathLike,
        **kwargs,
    ) -> pd.DataFrame:
        """Map every ``wsel_*`` profile of a ras2fim-2D hydraulic-results GeoPackage.

        Reads layer ``02_cells_wsel_ar``, takes cell centres from ``hdf_path``,
        and calls :meth:`map_profiles` with ``kwargs``.
        """
        cells = RasFim.get_cells_from_results_gpkg(results_gpkg)
        return RasFim.map_profiles(cells, terrain_path, output_folder, hdf_path=hdf_path, **kwargs)

    @staticmethod
    def _write_products(folder: Path, result, output_crs, write_floodplain: bool) -> dict:
        depth_path, wse_path, floodplain_path = _products.product_paths(folder, result.profile)
        _products.write_raster(depth_path, result.depth, result.transform, output_crs)
        _products.write_raster(wse_path, result.wse, result.transform, output_crs)
        flooded = int(_products.flooded_mask(result.depth).sum())
        status = "complete" if flooded else "no_flooded_pixels"
        floodplain = None
        if write_floodplain and flooded:
            frame = _products.floodplain_frame(result.depth, result.transform, output_crs)
            frame.to_file(floodplain_path)
            floodplain = str(floodplain_path)
        window = result.unit.get("window", [0, 0, result.depth.shape[1], result.depth.shape[0]])
        return {
            "status": status,
            "depth_tif": str(depth_path),
            "wse_tif": str(wse_path),
            "floodplain_gpkg": floodplain,
            "col_off": int(window[0]),
            "row_off": int(window[1]),
            "width": int(result.depth.shape[1]),
            "height": int(result.depth.shape[0]),
            "transform": tuple(float(v) for v in tuple(result.transform)[:6]),
            "crs": output_crs.to_string(),
            "depth_finite_pixels": int(np.isfinite(result.depth).sum()),
            "flooded_pixels": flooded,
            "error": None,
        }

    @staticmethod
    def _write_manifest(folder: Path, manifest: pd.DataFrame, details: dict) -> Path:
        records = json.loads(manifest.to_json(orient="records"))
        document = {
            "schema": MANIFEST_SCHEMA,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "method": "ras2fim-2D Step 05 (ras2fim-batch engine)",
            **details,
            "profiles": records,
        }
        path = folder / MANIFEST_NAME
        partial = path.with_suffix(".json.partial")
        with partial.open("w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=1, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
        return path
