"""TauDEM D8 terrain delineation: stream links and their catchments.

``RasTauDem`` runs the TauDEM 5 command-line tools (PitRemove, D8FlowDir,
AreaD8, Threshold, StreamNet) as separate processes and reads their outputs
into GeoDataFrames. TauDEM is never imported, linked or redistributed; it is
GPL-3 software installed separately (https://hydrology.usu.edu/taudem/). MPI
(MS-MPI on Windows; MPICH or Open MPI on Linux) is optional: without
``mpiexec`` each tool runs as a single process.

The stream links and catchments feed :class:`ras_commander.subdomain.RasSubdomain`,
which uses the downstream end of each link as a pour point and the union of a
link's catchment and every catchment upstream as its contributing area.

Ported from fim-commander ``fim_commander.methods.rog.delineate`` (same owner),
without its container and request layers.

Example:
    >>> from ras_commander.terrain import RasTauDem
    >>> info = RasTauDem.get_taudem_info()                          # doctest: +SKIP
    >>> result = RasTauDem.delineate("Terrain/dem.tif", "work/taudem",
    ...                              stream_area_sqmi=0.5, cell_size=30.0)  # doctest: +SKIP
    >>> result.streams[["LINKNO", "DSLINKNO", "DSContArea"]].head()      # doctest: +SKIP
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..LoggingConfig import get_logger, log_call

logger = get_logger(__name__)

__all__ = ["RasTauDem", "TauDemDelineation", "TauDemError", "TauDemNotFoundError"]

TAUDEM_DIR_ENV_VAR = "RAS_COMMANDER_TAUDEM_DIR"
MPIEXEC_ENV_VAR = "RAS_COMMANDER_MPIEXEC"
TAUDEM_TOOLS = ("PitRemove", "D8FlowDir", "AreaD8", "Threshold", "StreamNet")
SQFT_PER_SQMI = 5280.0 ** 2
_FT_PER_M = 1.0 / 0.3048
_STDERR_TAIL = 4000
_DEFAULT_WINDOWS_DIRS = (
    Path(r"C:\Program Files\TauDEM\TauDEM5Exe"),
    Path(r"C:\Program Files (x86)\TauDEM\TauDEM5Exe"),
)
_DEFAULT_WINDOWS_MPIEXEC = Path(r"C:\Program Files\Microsoft MPI\Bin\mpiexec.exe")


class TauDemNotFoundError(FileNotFoundError):
    """A TauDEM executable or the requested MPI launcher could not be found.

    RAS Commander never downloads or installs TauDEM.
    """


class TauDemError(RuntimeError):
    """A TauDEM tool exited with an error or wrote unusable output."""


@dataclass(frozen=True)
class TauDemDelineation:
    """TauDEM D8 delineation of one DEM.

    Attributes:
        streams: StreamNet links (schema ``taudem_streams``), one row per link,
            in the DEM CRS. ``DSContArea`` is in DEM horizontal units squared;
            ``contributing_area_sqmi`` is the same area in square miles.
            Each LineString runs downstream to upstream: its first vertex is the
            link outlet (TauDEM ``streamnet`` convention).
        catchments: Polygonized StreamNet watershed grid (schema
            ``taudem_catchments``), one row per link.
        raster_paths: Output rasters by role (``dem``, ``filled_dem``, ``d8``,
            ``d8_slope``, ``ad8``, ``src``, ``w``).
        crs: DEM CRS (``pyproj.CRS``).
        cell_size: DEM cell size used by TauDEM, in DEM horizontal units.
        stream_area_sqmi: Contributing-area threshold that defines a stream.
        stream_threshold_cells: The same threshold in D8 cells.
        commands: Exact argument lists that were run, in order.
        edge_contamination_check: Whether AreaD8 checked edge contamination.
    """

    streams: Any
    catchments: Any
    raster_paths: Dict[str, Path]
    crs: Any
    cell_size: float
    stream_area_sqmi: float
    stream_threshold_cells: float
    commands: Tuple[Tuple[str, ...], ...]
    edge_contamination_check: bool = False
    schema: str = field(default="ras-taudem-delineation/1")

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready summary (frames are summarized by row count)."""
        return {
            "schema": self.schema,
            "crs": self.crs.to_string() if self.crs is not None else None,
            "cell_size": self.cell_size,
            "stream_area_sqmi": self.stream_area_sqmi,
            "stream_threshold_cells": self.stream_threshold_cells,
            "edge_contamination_check": self.edge_contamination_check,
            "stream_count": int(len(self.streams)),
            "catchment_count": int(len(self.catchments)),
            "raster_paths": {k: str(v) for k, v in self.raster_paths.items()},
            "commands": [list(c) for c in self.commands],
        }


def _which_tool(name: str, directory: Optional[Path]) -> Optional[Path]:
    """Find a TauDEM tool by case-insensitive name in a folder or on PATH."""
    candidates = (name, name.lower())
    if directory is not None:
        for stem in candidates:
            for suffix in ("", ".exe"):
                path = directory / f"{stem}{suffix}"
                if path.is_file():
                    return path.resolve()
        return None
    for stem in candidates:
        found = shutil.which(stem)
        if found:
            return Path(found).resolve()
    return None


def _resolve_taudem_dir(taudem_dir) -> Tuple[Optional[Path], str]:
    if taudem_dir is not None:
        return Path(os.fspath(taudem_dir)).expanduser(), "taudem_dir"
    env = os.environ.get(TAUDEM_DIR_ENV_VAR)
    if env:
        return Path(env).expanduser(), TAUDEM_DIR_ENV_VAR
    return None, "PATH"


def _resolve_mpiexec(mpiexec_path) -> Tuple[Optional[Path], str]:
    if mpiexec_path is not None:
        path = Path(os.fspath(mpiexec_path)).expanduser()
        if not path.is_file():
            raise TauDemNotFoundError(f"mpiexec_path: MPI launcher not found: {path}")
        return path.resolve(), "mpiexec_path"
    env = os.environ.get(MPIEXEC_ENV_VAR)
    if env:
        path = Path(env).expanduser()
        if not path.is_file():
            raise TauDemNotFoundError(f"{MPIEXEC_ENV_VAR}: MPI launcher not found: {path}")
        return path.resolve(), MPIEXEC_ENV_VAR
    found = shutil.which("mpiexec")
    if found:
        return Path(found).resolve(), "PATH"
    if os.name == "nt" and _DEFAULT_WINDOWS_MPIEXEC.is_file():
        return _DEFAULT_WINDOWS_MPIEXEC, "default MS-MPI location"
    return None, "not found"


def _ft_per_unit(crs) -> float:
    """Feet per horizontal unit of a projected CRS."""
    if crs is None or not crs.is_projected:
        raise ValueError("TauDEM delineation needs a DEM in a projected CRS; geographic or "
                         "missing CRS refused")
    unit = crs.axis_info[0].unit_conversion_factor if crs.axis_info else None
    if not unit or not math.isfinite(unit) or unit <= 0:
        raise ValueError(f"cannot determine the linear unit of CRS {crs.to_string()}")
    return float(unit) * _FT_PER_M


class RasTauDem:
    """Static wrapper around the TauDEM 5 D8 delineation tools."""

    @staticmethod
    @log_call
    def get_taudem_info(taudem_dir: Union[str, Path, None] = None,
                        mpiexec_path: Union[str, Path, None] = None) -> Dict[str, Any]:
        """Locate the TauDEM tools and the MPI launcher.

        Search order for the tools: ``taudem_dir``, then the
        ``RAS_COMMANDER_TAUDEM_DIR`` environment variable, then ``PATH``, then
        the default Windows install folder. For the launcher: ``mpiexec_path``,
        then ``RAS_COMMANDER_MPIEXEC``, then ``PATH``, then the default MS-MPI
        folder. A missing launcher is reported, not raised, unless one was
        named explicitly.

        Args:
            taudem_dir: Folder holding the TauDEM executables.
            mpiexec_path: MPI launcher executable.

        Returns:
            dict with ``executables`` (tool name to resolved Path), ``taudem_source``,
            ``mpiexec_path`` (Path or None) and ``mpiexec_source``.

        Raises:
            TauDemNotFoundError: A required TauDEM tool, or a named launcher, is missing.
        """
        directory, source = _resolve_taudem_dir(taudem_dir)
        if directory is not None and not directory.is_dir():
            raise TauDemNotFoundError(f"{source}: TauDEM folder not found: {directory}")
        executables: Dict[str, Path] = {}
        missing: List[str] = []
        for tool in TAUDEM_TOOLS:
            path = _which_tool(tool, directory)
            if path is None and directory is None and os.name == "nt":
                for default in _DEFAULT_WINDOWS_DIRS:
                    path = _which_tool(tool, default) if default.is_dir() else None
                    if path is not None:
                        source = "default TauDEM location"
                        break
            if path is None:
                missing.append(tool)
            else:
                executables[tool] = path
        if missing:
            raise TauDemNotFoundError(
                f"TauDEM tools not found ({', '.join(missing)}) via {source}. Install TauDEM 5 "
                f"(https://hydrology.usu.edu/taudem/), then pass taudem_dir, set "
                f"{TAUDEM_DIR_ENV_VAR}, or put its executables on PATH. RAS Commander does not "
                "install TauDEM."
            )
        mpiexec, mpi_source = _resolve_mpiexec(mpiexec_path)
        return {
            "executables": executables,
            "taudem_source": source,
            "mpiexec_path": mpiexec,
            "mpiexec_source": mpi_source,
        }

    @staticmethod
    @log_call
    def delineate(dem_path: Union[str, Path],
                  dest_folder: Union[str, Path],
                  *,
                  stream_area_sqmi: float = 0.1,
                  cell_size: Optional[float] = None,
                  num_processes: int = 4,
                  edge_contamination_check: bool = False,
                  taudem_dir: Union[str, Path, None] = None,
                  mpiexec_path: Union[str, Path, None] = None,
                  overwrite: bool = False,
                  timeout: Optional[float] = None) -> TauDemDelineation:
        """Delineate D8 stream links and catchments from a DEM.

        Runs PitRemove, D8FlowDir, AreaD8, Threshold and StreamNet in
        ``dest_folder``, then reads the stream links and polygonizes the
        watershed grid. The source DEM is never modified.

        Args:
            dem_path: DEM raster in a projected CRS with square, north-up cells
                (for example from ``RasTerrain.export_rasmapper_terrain``).
            dest_folder: Output folder. Must be empty or absent unless ``overwrite``.
            stream_area_sqmi: Contributing area, in square miles, at which a
                stream begins (Threshold on D8 accumulation).
            cell_size: Optional cell size, in DEM horizontal units, to resample
                the DEM to (average) before delineation. ``None`` keeps the
                native grid. Coarsening keeps HUC-scale runs tractable.
            num_processes: MPI ranks per tool. Ignored (1) without a launcher.
            edge_contamination_check: Run AreaD8's edge check, which leaves no
                accumulation (so no streams) wherever a cell's contributing area
                touches the DEM edge or NoData. Off by default (TauDEM ``-nc``):
                a terrain clipped at its drainage divide touches the edge
                everywhere, and the check would remove every stream. Turn it on
                only for a DEM buffered well past the divide.
            taudem_dir: Folder of TauDEM executables (see ``get_taudem_info``).
            mpiexec_path: MPI launcher (see ``get_taudem_info``).
            overwrite: Allow a non-empty ``dest_folder``; existing outputs are replaced.
            timeout: Seconds allowed per tool, or ``None``.

        Returns:
            TauDemDelineation

        Raises:
            TauDemNotFoundError: TauDEM is not installed or not found.
            TauDemError: A tool failed, or the threshold produced no streams.
            ValueError: The DEM is not projected or its cells are not square and north-up.
            FileExistsError: ``dest_folder`` is not empty and ``overwrite`` is False.
        """
        import geopandas as gpd
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.features import shapes
        from shapely.geometry import shape

        if not (isinstance(stream_area_sqmi, (int, float)) and math.isfinite(stream_area_sqmi)
                and stream_area_sqmi > 0):
            raise ValueError("stream_area_sqmi must be a finite positive number")
        if cell_size is not None and not (math.isfinite(cell_size) and cell_size > 0):
            raise ValueError("cell_size must be a finite positive number or None")
        if int(num_processes) < 1:
            raise ValueError("num_processes must be at least 1")
        dem_path = Path(dem_path).resolve()
        if not dem_path.is_file():
            raise FileNotFoundError(f"DEM not found: {dem_path}")
        dest = Path(dest_folder).resolve()
        if dest == dem_path.parent or dest in dem_path.parents:
            raise ValueError("dest_folder must not contain the source DEM")
        if dest.exists() and any(dest.iterdir()) and not overwrite:
            raise FileExistsError(f"dest_folder is not empty: {dest} (pass overwrite=True)")
        dest.mkdir(parents=True, exist_ok=True)

        info = RasTauDem.get_taudem_info(taudem_dir=taudem_dir, mpiexec_path=mpiexec_path)
        tools = info["executables"]
        mpiexec = info["mpiexec_path"]
        ranks = int(num_processes) if mpiexec is not None else 1
        if mpiexec is None and int(num_processes) > 1:
            logger.warning("No MPI launcher found; running TauDEM tools as single processes")

        # Stage the DEM as a GeoTIFF on the grid TauDEM will use.
        with rasterio.open(dem_path) as src:
            crs = src.crs
            transform = src.transform
            if crs is None:
                raise ValueError("DEM has no CRS")
            if (transform.b != 0 or transform.d != 0 or transform.e >= 0
                    or not math.isclose(abs(transform.a), abs(transform.e), rel_tol=1e-8)):
                raise ValueError("DEM cells must be square and north-up")
            from pyproj import CRS
            pcrs = CRS.from_user_input(crs.to_wkt())
            ft_per_unit = _ft_per_unit(pcrs)
            native = abs(transform.a)
            target = float(cell_size) if cell_size is not None else native
            scale = target / native
            height = max(1, int(round(src.height / scale)))
            width = max(1, int(round(src.width / scale)))
            nodata = src.nodata if src.nodata is not None else -9999.0
            data = src.read(1, out_shape=(height, width), masked=True,
                            resampling=Resampling.average if scale > 1 else Resampling.bilinear)
            out_transform = src.transform * src.transform.scale(src.width / width,
                                                                src.height / height)
            staged = dest / "dem.tif"
            profile = {
                "driver": "GTiff", "height": height, "width": width, "count": 1,
                "dtype": "float32", "crs": crs, "transform": out_transform,
                "nodata": float(nodata), "tiled": True, "compress": "deflate",
                "BIGTIFF": "IF_SAFER",
            }
            with rasterio.open(staged, "w", **profile) as sink:
                sink.write(np.ma.filled(data.astype("float32"), float(nodata)), 1)
        cell = abs(out_transform.a)
        cell_area_sqft = (cell * ft_per_unit) ** 2
        threshold_cells = stream_area_sqmi * SQFT_PER_SQMI / cell_area_sqft

        def p(name: str) -> str:
            return str(dest / name)

        def cmd(tool: str, *args: str) -> Tuple[str, ...]:
            exe = str(tools[tool])
            if mpiexec is not None:
                return (str(mpiexec), "-n", str(ranks), exe, *args)
            return (exe, *args)

        nc = () if edge_contamination_check else ("-nc",)
        commands = (
            cmd("PitRemove", "-z", p("dem.tif"), "-fel", p("fel.tif")),
            cmd("D8FlowDir", "-fel", p("fel.tif"), "-p", p("p.tif"), "-sd8", p("sd8.tif")),
            cmd("AreaD8", "-p", p("p.tif"), "-ad8", p("ad8.tif"), *nc),
            cmd("Threshold", "-ssa", p("ad8.tif"), "-src", p("src.tif"),
                "-thresh", format(threshold_cells, ".17g")),
            cmd("StreamNet", "-fel", p("fel.tif"), "-p", p("p.tif"), "-ad8", p("ad8.tif"),
                "-src", p("src.tif"), "-ord", p("ord.tif"), "-tree", p("tree.dat"),
                "-coord", p("coord.dat"), "-net", p("streams.shp"), "-w", p("w.tif")),
        )
        log_path = dest / "taudem.log"
        with log_path.open("w", encoding="utf-8") as log:
            for argv in commands:
                log.write("$ " + subprocess.list2cmdline(argv) + "\n")
                try:
                    proc = subprocess.run(list(argv), cwd=dest, capture_output=True, text=True,
                                          check=False, timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    raise TauDemError(f"{Path(argv[0]).name}: did not finish within {timeout} s") from exc
                except OSError as exc:
                    raise TauDemNotFoundError(f"cannot execute {argv[0]}: {exc}") from exc
                log.write(proc.stdout)
                log.write(proc.stderr)
                log.flush()
                tool = next(t for t in TAUDEM_TOOLS if str(tools[t]) in argv)
                if proc.returncode != 0:
                    raise TauDemError(f"{tool} exited {proc.returncode}: "
                                      f"{(proc.stderr or proc.stdout).strip()[-_STDERR_TAIL:]}")

        streams_path = dest / "streams.shp"
        if not streams_path.is_file():
            raise TauDemError("StreamNet wrote no streams.shp")
        streams = gpd.read_file(streams_path)
        if streams.empty:
            raise TauDemError(f"stream_area_sqmi={stream_area_sqmi} produced no stream links")
        if streams.crs is None:
            streams = streams.set_crs(crs.to_wkt())
        names = {c.upper(): c for c in streams.columns}
        rename = {names[k]: k for k in ("LINKNO", "DSLINKNO", "USLINKNO1", "USLINKNO2")
                  if k in names}
        order = names.get("STRMORDER", names.get("ORDER"))
        if order is not None:
            rename[order] = "strmOrder"
        for k in ("LENGTH", "SLOPE", "DSCONTAREA", "USCONTAREA", "STRMDROP", "WSNO",
                  "DOUTEND", "DOUTSTART", "DOUTMID", "MAGNITUDE"):
            if k in names:
                rename[names[k]] = {"LENGTH": "Length", "SLOPE": "Slope", "DSCONTAREA": "DSContArea",
                                    "USCONTAREA": "USContArea", "STRMDROP": "strmDrop", "WSNO": "WSNO",
                                    "DOUTEND": "DOUTEnd", "DOUTSTART": "DOUTStart", "DOUTMID": "DOUTMid",
                                    "MAGNITUDE": "Magnitude"}[k]
        streams = streams.rename(columns=rename)
        required = {"LINKNO", "DSLINKNO", "USLINKNO1", "USLINKNO2", "strmOrder", "Length",
                    "Slope", "DSContArea"}
        if not required.issubset(streams.columns):
            raise TauDemError(f"streams.shp lacks fields {sorted(required - set(streams.columns))}")
        for c in ("LINKNO", "DSLINKNO", "USLINKNO1", "USLINKNO2", "strmOrder"):
            streams[c] = streams[c].astype("int64")
        if streams["LINKNO"].duplicated().any():
            raise TauDemError("streams.shp has duplicate LINKNO values")
        streams["contributing_area_sqmi"] = (streams["DSContArea"].astype(float)
                                             * ft_per_unit ** 2 / SQFT_PER_SQMI)

        with rasterio.open(dest / "w.tif") as src:
            labels = src.read(1, masked=True)
            wt = src.transform
        mask = ~np.ma.getmaskarray(labels) & (labels.filled(-1) >= 0)
        records = [{"LINKNO": int(v), "geometry": shape(g)}
                   for g, v in shapes(labels.filled(-1).astype("int32"), mask=mask, transform=wt)]
        if not records:
            raise TauDemError("StreamNet watershed grid has no labelled cells")
        catchments = gpd.GeoDataFrame(records, crs=streams.crs).dissolve(by="LINKNO").reset_index()
        catchments = catchments.merge(streams[["LINKNO", "DSLINKNO", "strmOrder"]], on="LINKNO",
                                      how="left", validate="one_to_one")
        catchments["area"] = catchments.geometry.area
        catchments["area_sqmi"] = catchments["area"] * ft_per_unit ** 2 / SQFT_PER_SQMI
        catchments = catchments[["LINKNO", "DSLINKNO", "strmOrder", "area", "area_sqmi", "geometry"]]

        raster_paths = {"dem": dest / "dem.tif", "filled_dem": dest / "fel.tif",
                        "d8": dest / "p.tif", "d8_slope": dest / "sd8.tif",
                        "ad8": dest / "ad8.tif", "src": dest / "src.tif", "w": dest / "w.tif"}
        logger.info("TauDEM delineation: %d links, %d catchments at %.6g units, threshold %.6g cells",
                    len(streams), len(catchments), cell, threshold_cells)
        return TauDemDelineation(
            streams=streams, catchments=catchments, raster_paths=raster_paths,
            crs=streams.crs, cell_size=float(cell), stream_area_sqmi=float(stream_area_sqmi),
            stream_threshold_cells=float(threshold_cells), commands=commands,
            edge_contamination_check=bool(edge_contamination_check),
        )
