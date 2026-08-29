"""Supervised out-of-process native RAS Mapper terrain export."""

from __future__ import annotations

import contextlib
import ctypes
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Any, Optional, Sequence, Union

import pandas as pd

from ..ComputeResults import TerrainExportResult
from ..LoggingConfig import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1
ALLOWED_DOWNSAMPLE_FACTORS = frozenset({1, 2, 4, 8})
_HELPER_NAME = "RasMapperTerrainExportHelper.exe"
_NATIVE_HDF_LIBRARIES = ("hdf5.dll", "hdf5_hl.dll", "szip.dll", "zlib.dll")
_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def select_terrain_row(layers: pd.DataFrame, terrain_name: Optional[str]) -> pd.Series:
    """Select one exact registered terrain without arbitrary first-row behavior."""
    if layers.empty:
        raise ValueError("The project has no registered terrain layers")
    if "name" not in layers.columns:
        raise ValueError("Terrain inventory is missing its 'name' column")

    if terrain_name is None:
        if len(layers.index) != 1:
            names = ", ".join(repr(str(value)) for value in layers["name"].tolist())
            raise ValueError(
                "terrain_name is required when a project has multiple registered "
                f"terrains: {names}"
            )
        return layers.iloc[0]

    selected = layers.loc[layers["name"].map(str) == str(terrain_name)]
    if selected.empty:
        raise ValueError(f"Registered terrain not found: {terrain_name!r}")
    if len(selected.index) != 1:
        raise ValueError(
            f"Registered terrain name is not unique: {terrain_name!r}"
        )
    return selected.iloc[0]


def validate_downsample_factor(value: int) -> int:
    """Return an allowed exact source-derived factor."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("downsample_factor must be one of 1, 2, 4, or 8")
    if value not in ALLOWED_DOWNSAMPLE_FACTORS:
        raise ValueError("downsample_factor must be one of 1, 2, 4, or 8")
    return value


def normalize_extent(
    extent: Optional[Sequence[float]],
) -> Optional[tuple[float, float, float, float]]:
    """Validate public `(xmin, ymin, xmax, ymax)` bounds."""
    if extent is None:
        return None
    if isinstance(extent, (str, bytes)) or len(extent) != 4:
        raise ValueError("extent must be (xmin, ymin, xmax, ymax)")
    bounds = tuple(float(value) for value in extent)
    if not all(math.isfinite(value) for value in bounds):
        raise ValueError("extent values must be finite")
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError("extent must have positive width and height")
    return bounds


def _source_cell(source: dict[str, Any]) -> float:
    values = source.get("cell_sizes")
    if not isinstance(values, list) or not values:
        raise ValueError("A registered terrain source has no level-zero cell size")
    cell = float(values[0])
    if not math.isfinite(cell) or cell <= 0:
        raise ValueError("Registered terrain source cell sizes must be finite and positive")
    return cell


def select_authoritative_source(
    sources: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], float]:
    """Choose the finest source, then native priority/order, and audit ratios."""
    if not sources:
        raise ValueError("The registered terrain contains no raster sources")

    source_cells = [(source, _source_cell(source)) for source in sources]
    native_cell = min(cell for _, cell in source_cells)
    tolerance = max(abs(native_cell) * 1e-9, 1e-12)
    finest = [
        source for source, cell in source_cells
        if math.isclose(cell, native_cell, rel_tol=1e-9, abs_tol=tolerance)
    ]

    def priority(source: dict[str, Any]) -> tuple[int, int, int]:
        raw = int(source.get("priority", -1))
        return (0 if raw >= 0 else 1, raw if raw >= 0 else 0, int(source["index"]))

    authoritative = min(finest, key=priority)
    for source, cell in source_cells:
        ratio = cell / native_cell
        if not math.isclose(ratio, round(ratio), rel_tol=1e-8, abs_tol=1e-8):
            raise ValueError(
                "Registered terrain sources have incompatible level-zero cell "
                f"sizes ({cell!r} is not an integer multiple of {native_cell!r})"
            )
    return authoritative, native_cell


def _near_integer(value: float) -> float:
    rounded = round(value)
    if math.isclose(value, rounded, rel_tol=1e-12, abs_tol=1e-10):
        return float(rounded)
    return value


def snap_extent_to_grid(
    extent: Sequence[float],
    origin_x: float,
    origin_y: float,
    cell_size: float,
) -> tuple[tuple[float, float, float, float], int, int]:
    """Snap bounds outward, including negative coordinates, to a source grid."""
    bounds = normalize_extent(extent)
    assert bounds is not None
    if not math.isfinite(cell_size) or cell_size <= 0:
        raise ValueError("cell_size must be finite and positive")

    left = math.floor(_near_integer((bounds[0] - origin_x) / cell_size))
    right = math.ceil(_near_integer((bounds[2] - origin_x) / cell_size))
    top = math.floor(_near_integer((origin_y - bounds[3]) / cell_size))
    bottom = math.ceil(_near_integer((origin_y - bounds[1]) / cell_size))
    columns = right - left
    rows = bottom - top
    if columns <= 0 or rows <= 0:
        raise ValueError("Snapped extent has no raster cells")

    snapped = (
        origin_x + left * cell_size,
        origin_y - bottom * cell_size,
        origin_x + right * cell_size,
        origin_y - top * cell_size,
    )
    return snapped, columns, rows


def vendor_invocation_extent(
    snapped_extent: Sequence[float], cell_size: float
) -> tuple[float, float, float, float]:
    """Avoid the vendor floating-point `Ceiling` extra-row/column failure."""
    bounds = normalize_extent(snapped_extent)
    assert bounds is not None
    epsilon = max(abs(cell_size) * 1e-9, math.ulp(max(map(abs, bounds))))
    if bounds[2] - epsilon <= bounds[0] or bounds[1] + epsilon >= bounds[3]:
        raise ValueError("Grid is too small for a stable native invocation extent")
    return bounds[0], bounds[1] + epsilon, bounds[2] - epsilon, bounds[3]


def validate_helper_request(request: dict[str, Any]) -> None:
    """Validate the versioned JSON request before crossing the process boundary."""
    required = {"schema_version", "operation", "rasmap_path", "terrain_name"}
    missing = sorted(required.difference(request))
    if missing:
        raise ValueError(f"Helper request is missing fields: {', '.join(missing)}")
    if request["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported terrain helper request schema")
    if request["operation"] not in {"inspect", "export"}:
        raise ValueError("Helper request operation must be inspect or export")
    if request["operation"] == "export":
        export_required = {
            "output_path",
            "invocation_extent",
            "cell_size",
            "rasterize_modifications",
        }
        missing = sorted(export_required.difference(request))
        if missing:
            raise ValueError(f"Export request is missing fields: {', '.join(missing)}")
        normalize_extent(request["invocation_extent"])
        if float(request["cell_size"]) <= 0:
            raise ValueError("Export request cell_size must be positive")
        if not isinstance(request["rasterize_modifications"], bool):
            raise ValueError("rasterize_modifications must be boolean")


def validate_helper_response(
    response: dict[str, Any], operation: str, require_success: bool = True
) -> None:
    """Validate helper identity, schema, operation, and required payload."""
    if not isinstance(response, dict):
        raise RuntimeError("Terrain helper response is not a JSON object")
    if response.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("Terrain helper response schema is incompatible")
    if response.get("helper") != "RasMapperTerrainExportHelper":
        raise RuntimeError("Terrain helper response identity is invalid")
    if not isinstance(response.get("success"), bool):
        raise RuntimeError("Terrain helper response success field is invalid")
    if not response["success"]:
        if require_success:
            raise RuntimeError(str(response.get("error") or "Native terrain helper failed"))
        return
    if response.get("operation") != operation:
        raise RuntimeError("Terrain helper response operation does not match its request")
    if not isinstance(response.get("sources"), list) or not response["sources"]:
        raise RuntimeError("Terrain helper returned no registered source inventory")
    if operation == "export":
        if response.get("resample_method") != "near":
            raise RuntimeError("Native terrain helper did not use nearest-neighbor")
        if response.get("resample_to_one_rfi") is not True:
            raise RuntimeError("Native terrain helper did not consolidate to one raster")
        if response.get("generate_method_is_public") is not False:
            raise RuntimeError("Native terrain helper resolved an unexpected API surface")
        if len(response.get("new_rfis", [])) != 1:
            raise RuntimeError("Native terrain helper did not report exactly one output TIFF")


def _normalize_host_path(value: Union[str, os.PathLike[str]]) -> Path:
    """Convert Windows/Wine-visible input to this host's filesystem path."""
    text = os.fspath(value)
    if platform.system() == "Linux" and _WINDOWS_PATH.match(text):
        from ..RasProcess import RasProcess

        config = RasProcess._get_wine_config()
        if config is None:
            raise RuntimeError("Wine is not configured for Windows path conversion")
        winepath = RasProcess._resolve_wine_tool_executable("winepath", config)
        result = subprocess.run(
            [winepath, "-u", text],
            capture_output=True,
            text=True,
            check=False,
            env=RasProcess._build_wine_env(config),
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise ValueError(f"Wine could not resolve path: {text!r}")
        return Path(result.stdout.strip())
    return Path(text).expanduser()


def _helper_path(path: Path) -> str:
    if platform.system() != "Linux":
        return str(path)
    from ..RasProcess import RasProcess

    return RasProcess._resolve_path_for_rasprocess(path)


def _resolve_hecras_source(
    hecras_version: Optional[str], ras_object: Any
) -> tuple[str, Path, Any]:
    """Resolve an explicit generation and installation without arbitrary fallback."""
    from ..RasPrj import get_ras_exe, ras

    project = ras_object if ras_object is not None else ras
    version = hecras_version or getattr(project, "ras_version", None)
    if not version:
        raise ValueError(
            "hecras_version is required when no initialized ras_object provides ras_version"
        )
    version_text = str(version)

    if platform.system() == "Linux":
        from ..RasProcess import RasProcess

        config = RasProcess._get_wine_config()
        if config is None:
            raise RuntimeError(
                "Wine is not configured. Call RasProcess.configure_wine() first."
            )
        if config.ras_install_dir is not None:
            directory = Path(config.ras_install_dir)
        else:
            rasprocess = RasProcess.find_rasprocess(version_text)
            if rasprocess is None:
                raise FileNotFoundError(f"HEC-RAS {version_text} was not found under Wine")
            directory = rasprocess.parent
        wine_config = config
    else:
        explicit_exe = getattr(project, "ras_exe_path", None)
        if hecras_version is None and explicit_exe and Path(str(explicit_exe)).is_file():
            ras_exe = str(explicit_exe)
        else:
            ras_exe = get_ras_exe(version)
        if ras_exe == "Ras.exe" or not Path(ras_exe).is_file():
            raise FileNotFoundError(f"HEC-RAS {version_text} installation was not found")
        directory = Path(ras_exe).parent
        wine_config = None

    version_label = version_text
    if Path(version_text).suffix.lower() == ".exe":
        version_label = directory.name
    if not (version_label.startswith("6.6") or version_label.startswith("7.0")):
        raise ValueError(
            "Native RAS Mapper terrain export is qualified only for HEC-RAS "
            "6.6 and checked 7.0-family APIs"
        )
    if not (directory / "RasMapperLib.dll").is_file():
        raise FileNotFoundError(f"RasMapperLib.dll not found in {directory}")
    return version_label, directory, wine_config


def _clone_wine_prefix(source: Path, destination: Path, timeout: float) -> None:
    """Create isolated copy-on-write Wine state; never share a writable prefix."""
    if not (source / "drive_c").is_dir():
        raise FileNotFoundError(f"Configured Wine prefix is incomplete: {source}")
    destination.mkdir(parents=True, exist_ok=False)
    result = subprocess.run(
        ["cp", "--archive", "--reflink=auto", str(source) + "/.", str(destination)],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not create task-local Wine prefix: " + result.stderr.strip()
        )


def _stage_runtime(
    stage: Path, hecras_source: Path, wine_config: Any, timeout: float
) -> tuple[Path, Path, Any]:
    """Stage the packaged helper, GDAL view, native HDF libraries, and Wine state."""
    if timeout <= 0:
        raise subprocess.TimeoutExpired(["terrain-runtime-stage"], timeout)
    hecras_dir = hecras_source
    run_config = wine_config
    if wine_config is not None:
        from ..RasProcess import WineConfig

        source_prefix = Path(wine_config.wine_prefix)
        prefix_is_task_local = (
            os.environ.get("RAS_COMMANDER_TERRAIN_WINE_PREFIX_IS_TASK_LOCAL") == "1"
        )
        if not prefix_is_task_local:
            local_prefix = stage / "wineprefix"
            _clone_wine_prefix(source_prefix, local_prefix, timeout)
            try:
                relative_ras = hecras_source.resolve().relative_to(
                    source_prefix.resolve()
                )
            except ValueError as exc:
                raise RuntimeError(
                    "Wine HEC-RAS installation must be inside the configured Wine prefix"
                ) from exc
            hecras_dir = local_prefix / relative_ras
            run_config = WineConfig(
                wine_prefix=local_prefix,
                wine_executable=wine_config.wine_executable,
                ras_install_dir=hecras_dir,
            )
        else:
            logger.info(
                "Using explicitly declared task-local Wine prefix for terrain export: %s",
                source_prefix,
            )

    helper_resource = resources.files("ras_commander.native").joinpath(_HELPER_NAME)
    with resources.as_file(helper_resource) as packaged_helper:
        helper = stage / _HELPER_NAME
        shutil.copy2(packaged_helper, helper)

    gdal_source = hecras_dir / "GDAL"
    if not gdal_source.is_dir():
        raise FileNotFoundError(f"HEC-RAS GDAL runtime not found: {gdal_source}")
    gdal_view = stage / "GDAL"
    if platform.system() == "Windows":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(gdal_view), str(gdal_source)],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError("Could not stage task-local GDAL junction: " + result.stderr)
    else:
        gdal_view.symlink_to(gdal_source, target_is_directory=True)

    native_dir = hecras_dir / "bin32"
    for filename in _NATIVE_HDF_LIBRARIES:
        source = native_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"Required 32-bit HEC-RAS native library missing: {source}")
        destination = stage / filename
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
    return helper, hecras_dir, run_config


def _runtime_env(hecras_dir: Path, wine_config: Any) -> dict[str, str]:
    env = dict(os.environ)
    gdal = hecras_dir / "GDAL"
    prefixes = [hecras_dir / "bin32", gdal / "bin32", hecras_dir]
    env["PATH"] = os.pathsep.join([str(path) for path in prefixes] + [env.get("PATH", "")])
    env["GDAL_DATA"] = str(gdal / "common" / "data")
    env["PROJ_LIB"] = env["GDAL_DATA"]
    env["PROJ_DATA"] = env["GDAL_DATA"]
    env["GDAL_NUM_THREADS"] = "1"
    if wine_config is not None:
        env["WINEPREFIX"] = str(wine_config.wine_prefix)
        env["DISPLAY"] = ""
        env["WINEDEBUG"] = "-all"
    return env


class _WindowsJob:
    """Kill-on-close Job Object for one owned native helper tree."""

    def __init__(self, process: subprocess.Popen[str]):
        from ctypes import wintypes

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(handle, int(process._handle)):
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        self._kernel32 = kernel32
        self._handle = handle

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def run_owned_process(
    command: Sequence[str],
    timeout: float,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run a process with bounded ownership and terminate only its descendants."""
    if timeout <= 0:
        raise subprocess.TimeoutExpired(command, timeout)
    is_windows = platform.system() == "Windows"
    creationflags = 0
    if is_windows:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        creationflags=creationflags,
        start_new_session=not is_windows,
    )
    job = None
    if is_windows:
        try:
            job = _WindowsJob(process)
        except OSError:
            logger.warning(
                "Could not assign terrain helper to a Windows Job Object; "
                "timeout cleanup will target its owned PID tree."
            )
            logger.debug("Windows Job Object assignment failed", exc_info=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        if job is not None:
            job.close()
            job = None
        elif is_windows:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            process.communicate(timeout=10)
        raise
    finally:
        if job is not None:
            job.close()


def _run_helper(
    helper: Path,
    hecras_dir: Path,
    wine_config: Any,
    request: dict[str, Any],
    stage: Path,
    timeout: float,
) -> dict[str, Any]:
    validate_helper_request(request)
    request_path = stage / ("request-" + uuid.uuid4().hex + ".json")
    response_path = stage / ("response-" + uuid.uuid4().hex + ".json")
    request_path.write_text(json.dumps(request, allow_nan=False), encoding="utf-8")

    if wine_config is None:
        command = [str(helper), str(hecras_dir), str(request_path), str(response_path)]
    else:
        command = [
            str(wine_config.wine_executable),
            str(helper),
            _helper_path(hecras_dir),
            _helper_path(request_path),
            _helper_path(response_path),
        ]
    completed = run_owned_process(
        command,
        timeout=timeout,
        cwd=stage,
        env=_runtime_env(hecras_dir, wine_config),
    )
    if not response_path.is_file():
        raise RuntimeError(
            "Terrain helper returned no response "
            f"(exit={completed.returncode}, stderr={completed.stderr.strip()!r})"
        )
    try:
        response = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Terrain helper returned invalid JSON") from exc
    validate_helper_response(response, request["operation"], require_success=False)
    if completed.returncode != 0 or not response["success"]:
        detail = response.get("error") or completed.stderr.strip() or "unknown native error"
        raise RuntimeError(f"Native terrain helper failed: {detail}")
    validate_helper_response(response, request["operation"])
    return response


def _run_gdalinfo(
    tif_path: Path,
    hecras_dir: Path,
    wine_config: Any,
    stage: Path,
    timeout: float,
) -> dict[str, Any]:
    gdalinfo = hecras_dir / "GDAL" / "bin32" / "gdalinfo.exe"
    if not gdalinfo.is_file():
        raise FileNotFoundError(f"HEC-RAS gdalinfo not found: {gdalinfo}")
    if wine_config is None:
        command = [str(gdalinfo), "-json", "-mm", "-checksum", str(tif_path)]
    else:
        command = [
            str(wine_config.wine_executable),
            str(gdalinfo),
            "-json",
            "-mm",
            "-checksum",
            _helper_path(tif_path),
        ]
    completed = run_owned_process(
        command,
        timeout=timeout,
        cwd=stage,
        env=_runtime_env(hecras_dir, wine_config),
    )
    if completed.returncode != 0:
        raise RuntimeError("gdalinfo rejected native output: " + completed.stderr.strip())
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gdalinfo returned invalid semantic metadata") from exc


def validate_output_semantics(
    info: dict[str, Any],
    tif_path: Path,
    snapped_extent: Sequence[float],
    cell_size: float,
    columns: int,
    rows: int,
) -> dict[str, Any]:
    """Fail closed on grid, type, CRS, nodata, and valid-value semantics."""
    failures: list[str] = []
    if info.get("driverShortName") != "GTiff":
        failures.append("driver is not GTiff")
    if info.get("size") != [columns, rows]:
        failures.append(f"size is {info.get('size')!r}, expected {[columns, rows]!r}")
    transform = info.get("geoTransform")
    expected = [snapped_extent[0], cell_size, 0.0, snapped_extent[3], 0.0, -cell_size]
    tolerance = max(abs(cell_size) * 1e-8, 1e-9)
    if not isinstance(transform, list) or len(transform) != 6 or any(
        not math.isclose(float(actual), target, rel_tol=1e-9, abs_tol=tolerance)
        for actual, target in zip(transform or [], expected)
    ):
        failures.append(f"geotransform is {transform!r}, expected {expected!r}")
    coordinate_system = info.get("coordinateSystem") or {}
    if not str(coordinate_system.get("wkt") or "").strip():
        failures.append("coordinate reference system is missing")
    bands = info.get("bands")
    if not isinstance(bands, list) or len(bands) != 1:
        failures.append("output must contain exactly one band")
        band = {}
    else:
        band = bands[0]
    if band.get("type") != "Float32":
        failures.append(f"band type is {band.get('type')!r}, expected 'Float32'")
    nodata = band.get("noDataValue")
    if nodata is None or not math.isfinite(float(nodata)):
        failures.append("finite nodata metadata is missing")
    minimum = band.get("computedMin")
    maximum = band.get("computedMax")
    if minimum is None or maximum is None:
        failures.append("output contains no computable valid-value range")
    elif not math.isfinite(float(minimum)) or not math.isfinite(float(maximum)):
        failures.append("valid-value range is not finite")
    if not tif_path.is_file() or tif_path.stat().st_size <= 0:
        failures.append("output TIFF is missing or empty")

    sidecars = [
        Path(str(tif_path) + suffix)
        for suffix in (".aux.xml", ".ovr")
    ] + [tif_path.with_suffix(suffix) for suffix in (".tfw", ".prj")]
    unexpected = [str(path) for path in sidecars if path.exists()]
    if unexpected:
        failures.append("native export created unexpected sidecars: " + ", ".join(unexpected))
    if failures:
        raise RuntimeError("Semantic GeoTIFF validation failed: " + "; ".join(failures))

    actual_extent = (
        float(transform[0]),
        float(transform[3]) + rows * float(transform[5]),
        float(transform[0]) + columns * float(transform[1]),
        float(transform[3]),
    )
    return {
        "driver": "GTiff",
        "columns": columns,
        "rows": rows,
        "band_count": 1,
        "data_type": "Float32",
        "nodata": float(nodata),
        "computed_min": float(minimum),
        "computed_max": float(maximum),
        "checksum": band.get("checksum"),
        "geotransform": [float(value) for value in transform],
        "actual_extent": list(actual_extent),
        "crs_present": True,
        "sidecars": [],
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _receipt_payload(
    result: TerrainExportResult,
    project_path: Path,
    rasmap_path: Path,
    hecras_version: str,
    helper_response: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    fields = asdict(result)
    fields.pop("source_inventory", None)
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "rasmapper_terrain_export",
        "status": "success" if result.success else "failed",
        "project_path": str(project_path),
        "rasmap_path": str(rasmap_path),
        "hecras_version": hecras_version,
        "result": _json_safe(fields),
        "sources": _json_safe(result.source_inventory),
        "native_helper": _json_safe(helper_response or {}),
    }


def _write_receipt_atomic(path: Path, payload: dict[str, Any]) -> Path:
    partial = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".partial")
    try:
        partial.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(partial, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
    return path


def _cleanup_stage(stage: Path) -> None:
    """Remove only the uniquely named task-local stage owned by this call."""
    if not stage.name.startswith(".ras-terrain-export-"):
        raise RuntimeError(f"Refusing to clean unexpected terrain stage: {stage}")
    gdal_view = stage / "GDAL"
    if gdal_view.is_symlink():
        gdal_view.unlink()
    elif platform.system() == "Windows" and gdal_view.exists():
        os.rmdir(gdal_view)
    shutil.rmtree(stage, ignore_errors=False)


def export_rasmapper_terrain(
    ras_project_path: Union[str, Path],
    output_tif: Union[str, Path],
    terrain_name: Optional[str] = None,
    extent: Optional[Sequence[float]] = None,
    downsample_factor: int = 1,
    rasterize_modifications: bool = True,
    overwrite: bool = False,
    timeout_seconds: float = 1800.0,
    hecras_version: Optional[str] = None,
    ras_object: Any = None,
    receipt_path: Optional[Union[str, Path]] = None,
) -> TerrainExportResult:
    """Implement the public supervised export contract used by ``RasTerrain``."""
    started = time.monotonic()
    factor = validate_downsample_factor(downsample_factor)
    requested_extent = normalize_extent(extent)
    if not isinstance(rasterize_modifications, bool):
        raise ValueError("rasterize_modifications must be boolean")
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be boolean")
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be finite and positive")

    project_input = _normalize_host_path(ras_project_path)
    output = _normalize_host_path(output_tif).absolute()
    if output.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("output_tif must have a .tif or .tiff extension")
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = (
        _normalize_host_path(receipt_path).absolute()
        if receipt_path is not None
        else Path(str(output) + ".receipt.json")
    )
    if output == receipt:
        raise ValueError("receipt_path must differ from output_tif")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    for protected in (output, receipt):
        if protected.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {protected}")

    from .. import _land_classification_helper as _lch
    from ..RasMap import RasMap

    project_paths = _lch.resolve_project_paths(project_input)
    rasmap_path = Path(project_paths.rasmap_path).absolute()
    if not rasmap_path.is_file():
        raise FileNotFoundError(f"RAS Mapper file not found: {rasmap_path}")
    layers = RasMap.list_terrain_layers(project_input, ras_object=ras_object)
    terrain_row = select_terrain_row(layers, terrain_name)
    selected_name = str(terrain_row["name"])
    terrain_hdf = (
        Path(str(terrain_row["resolved_path"]))
        if terrain_row.get("resolved_path")
        else None
    )
    version, hecras_source, wine_config = _resolve_hecras_source(
        hecras_version, ras_object
    )

    stage = output.parent / (".ras-terrain-export-" + uuid.uuid4().hex)
    stage.mkdir(parents=False, exist_ok=False)
    partial_tif = output.with_name(
        "." + output.stem + "." + uuid.uuid4().hex + ".partial" + output.suffix
    )
    result = TerrainExportResult(
        success=False,
        output_path=output,
        receipt_path=receipt,
        terrain_name=selected_name,
        terrain_hdf_path=terrain_hdf,
        requested_extent=requested_extent,
        downsample_factor=factor,
        rasterize_modifications=rasterize_modifications,
    )
    helper_response: Optional[dict[str, Any]] = None
    promoted = False
    receipt_promoted = False
    success_receipt_partial: Optional[Path] = None
    output_existed_before = output.exists()
    receipt_existed_before = receipt.exists()
    output_backup = stage / ("previous" + output.suffix)
    receipt_backup = receipt.with_name(
        "." + receipt.name + "." + uuid.uuid4().hex + ".backup"
    )

    try:
        remaining = timeout - (time.monotonic() - started)
        helper, hecras_dir, run_config = _stage_runtime(
            stage, hecras_source, wine_config, remaining
        )
        inspect_request = {
            "schema_version": SCHEMA_VERSION,
            "operation": "inspect",
            "rasmap_path": _helper_path(rasmap_path),
            "terrain_name": selected_name,
        }
        remaining = timeout - (time.monotonic() - started)
        inspection = _run_helper(
            helper, hecras_dir, run_config, inspect_request, stage, remaining
        )
        sources = inspection["sources"]
        authoritative, native_cell = select_authoritative_source(sources)
        source_extent = authoritative.get("extent") or {}
        origin_x = float(source_extent["min_x"])
        origin_y = float(source_extent["max_y"])
        terrain_extent_data = inspection.get("terrain_extent") or {}
        terrain_extent = (
            float(terrain_extent_data["min_x"]),
            float(terrain_extent_data["min_y"]),
            float(terrain_extent_data["max_x"]),
            float(terrain_extent_data["max_y"]),
        )
        export_extent = requested_extent or terrain_extent
        if (
            export_extent[2] <= terrain_extent[0]
            or export_extent[0] >= terrain_extent[2]
            or export_extent[3] <= terrain_extent[1]
            or export_extent[1] >= terrain_extent[3]
        ):
            raise ValueError("Requested extent does not intersect the registered terrain")
        output_cell = native_cell * factor
        snapped, columns, rows = snap_extent_to_grid(
            export_extent, origin_x, origin_y, output_cell
        )
        invocation = vendor_invocation_extent(snapped, output_cell)

        source_records = []
        for source in sources:
            record = dict(source)
            bounds = record.get("extent") or {}
            record["intersects_output"] = not (
                float(bounds["max_x"]) <= snapped[0]
                or float(bounds["min_x"]) >= snapped[2]
                or float(bounds["max_y"]) <= snapped[1]
                or float(bounds["min_y"]) >= snapped[3]
            )
            record["authoritative_grid"] = (
                int(record["index"]) == int(authoritative["index"])
            )
            source_records.append(record)
        result.source_inventory = pd.DataFrame(source_records)
        result.native_cell_size = native_cell
        result.output_cell_size = output_cell
        result.snapped_extent = snapped

        export_request = {
            "schema_version": SCHEMA_VERSION,
            "operation": "export",
            "rasmap_path": _helper_path(rasmap_path),
            "terrain_name": selected_name,
            "output_path": _helper_path(partial_tif),
            "invocation_extent": list(invocation),
            "cell_size": output_cell,
            "rasterize_modifications": rasterize_modifications,
        }
        remaining = timeout - (time.monotonic() - started)
        helper_response = _run_helper(
            helper, hecras_dir, run_config, export_request, stage, remaining
        )
        result.messages = [
            f"{item.get('type', 'Message')}: {item.get('message', '')}"
            for item in helper_response.get("messages", [])
        ]
        remaining = timeout - (time.monotonic() - started)
        info = _run_gdalinfo(
            partial_tif, hecras_dir, run_config, stage, remaining
        )
        result.validation = validate_output_semantics(
            info, partial_tif, snapped, output_cell, columns, rows
        )
        result.success = True
        result.elapsed_seconds = time.monotonic() - started
        payload = _receipt_payload(
            result, project_input.absolute(), rasmap_path, version, helper_response
        )
        success_receipt_partial = receipt.with_name(
            "." + receipt.name + "." + uuid.uuid4().hex + ".partial"
        )
        success_receipt_partial.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        if not overwrite:
            for protected in (output, receipt):
                if protected.exists():
                    raise FileExistsError(
                        f"A protected output appeared during export: {protected}"
                    )
        if overwrite and output_existed_before:
            os.replace(output, output_backup)
        if overwrite and receipt_existed_before:
            os.replace(receipt, receipt_backup)
        os.replace(partial_tif, output)
        promoted = True
        os.replace(success_receipt_partial, receipt)
        success_receipt_partial = None
        receipt_promoted = True
        with contextlib.suppress(FileNotFoundError):
            output_backup.unlink()
        with contextlib.suppress(FileNotFoundError):
            receipt_backup.unlink()
        return result
    except subprocess.TimeoutExpired as exc:
        result.success = False
        result.timed_out = True
        result.error = f"Native terrain export timed out after {timeout:.1f} seconds"
        result.messages.append(str(exc))
    except Exception as exc:
        result.success = False
        result.error = str(exc)
        logger.error("Native RAS Mapper terrain export failed: %s", exc)
        logger.debug("Native terrain export failure", exc_info=True)
    finally:
        result.elapsed_seconds = time.monotonic() - started
        with contextlib.suppress(FileNotFoundError):
            partial_tif.unlink()
        for suffix in (".aux.xml", ".ovr"):
            with contextlib.suppress(FileNotFoundError):
                Path(str(partial_tif) + suffix).unlink()
        if success_receipt_partial is not None:
            with contextlib.suppress(FileNotFoundError):
                success_receipt_partial.unlink()
        if not result.success:
            try:
                failure_receipt = receipt
                if receipt_existed_before or receipt.exists():
                    failure_receipt = receipt.with_name(
                        receipt.name + ".failed." + uuid.uuid4().hex + ".json"
                    )
                    result.receipt_path = failure_receipt
                payload = _receipt_payload(
                    result, project_input.absolute(), rasmap_path, version, helper_response
                )
                _write_receipt_atomic(failure_receipt, payload)
            except Exception as receipt_error:
                result.messages.append(f"Could not write failure receipt: {receipt_error}")
        if promoted and (not result.success or not receipt_promoted):
            with contextlib.suppress(OSError):
                output.unlink()
        if output_backup.exists():
            os.replace(output_backup, output)
        if receipt_backup.exists():
            with contextlib.suppress(OSError):
                receipt.unlink()
            os.replace(receipt_backup, receipt)
        if stage.exists():
            try:
                _cleanup_stage(stage)
            except Exception:
                logger.warning("Could not completely remove terrain export stage %s", stage)
                logger.debug("Terrain stage cleanup failed", exc_info=True)
        if promoted and not receipt_promoted:
            result.success = False
            result.error = "Output promotion was rolled back because receipt promotion failed"
    return result


__all__ = [
    "ALLOWED_DOWNSAMPLE_FACTORS",
    "export_rasmapper_terrain",
    "normalize_extent",
    "run_owned_process",
    "select_authoritative_source",
    "select_terrain_row",
    "snap_extent_to_grid",
    "validate_downsample_factor",
    "validate_helper_request",
    "validate_helper_response",
    "validate_output_semantics",
    "vendor_invocation_extent",
]
