"""Adapter for the external ``ras2fim-batch`` mapping engine.

The engine contract is ``ras2fim-step05-request/1``: Python writes global,
prepared per-profile inputs and a request; the engine writes per-profile
depth and WSE arrays for each requested output window. This module never
builds, downloads, or installs the engine.

Portions adapted from ras2fim-2D (``src/rust_mapping.py``), Copyright (c)
2026, The University of Texas at Austin, BSD 3-Clause License. See
``ras_commander/fim/THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from importlib import metadata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import numpy as np

from .errors import FimEngineError, FimEngineNotFoundError, FimUnsupportedError

ENGINE_NAME = "ras2fim-batch"
ENGINE_ENV_VAR = "RAS_COMMANDER_FIM_ENGINE"
REQUEST_SCHEMA = "ras2fim-step05-request/1"
UNIT_SCHEMA = "ras2fim-step05-unit/1"
REPORT_SCHEMA = "ras2fim-step05-report/1"

# rasterio.warp.reproject defaults used by the method: GDAL's approximate
# transformer (0.125 px) and a 64 MiB warp memory limit, which sets the
# chunking and therefore the approximation.
NUDGE_ERROR_THRESHOLD = 0.125
NUDGE_MEMORY_LIMIT_BYTES = 64 * 1024 * 1024

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_STDERR_TAIL = 4000


def find_engine(engine_path=None) -> Path:
    """Resolve an explicit path, environment, PATH, then the installed wheel."""
    if engine_path is None:
        engine_path = os.environ.get(ENGINE_ENV_VAR) or None
        source = ENGINE_ENV_VAR
    else:
        source = "engine_path"
    if engine_path is not None:
        path = Path(os.fspath(engine_path)).expanduser()
        if not path.is_file():
            raise FimEngineNotFoundError(f"{source}: {ENGINE_NAME} executable not found: {path}")
        if not os.access(path, os.X_OK):
            raise FimEngineNotFoundError(f"{source}: {path} is not executable")
        return path.resolve()
    found = shutil.which(ENGINE_NAME) or _installed_engine()
    if found is None:
        raise FimEngineNotFoundError(
            f"{ENGINE_NAME} was not found. Pass engine_path, set {ENGINE_ENV_VAR}, or put "
            f"{ENGINE_NAME} on PATH. RAS Commander does not build or install the engine and "
            "has no Python fallback for this method. Install ras-commander[fim] or "
            "ras-commander-fast-map on a supported platform before mapping."
        )
    return Path(found).resolve()


def _installed_engine() -> Optional[Path]:
    """Find the external wheel's script when its environment is not on PATH."""
    try:
        distribution = metadata.distribution("ras-commander-fast-map")
    except metadata.PackageNotFoundError:
        return None
    executable = ENGINE_NAME + (".exe" if os.name == "nt" else "")
    for entry in distribution.files or ():
        if entry.name == executable:
            path = Path(distribution.locate_file(entry))
            if path.is_file() and os.access(path, os.X_OK):
                return path.resolve()
    return None


def run_engine(args: List[str], what: str, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    """Run the engine without a shell."""
    try:
        return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise FimEngineError(f"{what}: {ENGINE_NAME} did not finish within {timeout} s") from exc
    except OSError as exc:
        raise FimEngineNotFoundError(f"{what}: cannot execute {args[0]}: {exc}") from exc


def _json_stdout(proc: subprocess.CompletedProcess, what: str) -> dict:
    if proc.returncode != 0:
        raise FimEngineError(f"{what} failed with exit {proc.returncode}: {proc.stderr.strip()[-_STDERR_TAIL:]}")
    text = proc.stdout.strip()
    if not text:
        raise FimEngineError(f"{what} wrote no JSON")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FimEngineError(f"{what} wrote invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise FimEngineError(f"{what} wrote JSON that is not an object")
    return value


class EngineRefusal(FimUnsupportedError):
    """The engine refused the request as outside its qualified contract."""


def engine_refusal(*texts) -> Optional[FimUnsupportedError]:
    """Return a FimUnsupportedError when the engine reported an ``unsupported:`` refusal.

    The engine formats contract refusals (for example terrain pixels outside a
    top-priority source footprint) as ``unsupported: ...``. Callers raise the
    result so mapping callers can fall back instead of treating it as a crash.
    """
    for text in texts:
        if not text:
            continue
        text = str(text)
        index = text.find("unsupported:")
        if index >= 0:
            return EngineRefusal(f"engine refused the request: {text[index:].strip()[:_STDERR_TAIL]}")
    return None


def read_refusal(out_dir: Path, stderr: str = "") -> Optional[FimUnsupportedError]:
    """Inspect a best-effort report and stderr for an engine refusal."""
    error = None
    try:
        report = json.loads((Path(out_dir) / "report.json").read_text(encoding="utf-8"))
        if isinstance(report, dict):
            error = report.get("error")
    except (OSError, ValueError, UnicodeError):
        pass
    return engine_refusal(error, stderr)


def engine_method(engine: Path) -> dict:
    """Return the engine's method record (``ras2fim-batch method``)."""
    return _json_stdout(run_engine([str(engine), "method"], "method"), "ras2fim-batch method")


def _find_wkt(obj):
    if isinstance(obj, str):
        head = obj.lstrip().upper()
        return obj if head.startswith(("PROJCS", "GEOGCS", "PROJCRS", "GEOGCRS", "COMPD", "BOUNDCRS")) else None
    if isinstance(obj, dict):
        for key in ("wkt", "wkt2", "wkt1"):
            if isinstance(obj.get(key), str):
                return obj[key]
        for value in obj.values():
            found = _find_wkt(value)
            if found:
                return found
    return None


def terrain_identity(engine: Path, terrain_path: Path, results_crs, terrain_crs_fnv1a64: Optional[str] = None) -> dict:
    """Build the request ``terrain`` block after cross-checking engine and rasterio views."""
    import rasterio
    from pyproj import CRS

    info = _json_stdout(run_engine([str(engine), "terrain-info", str(terrain_path)], "terrain-info"),
                        "ras2fim-batch terrain-info")
    with rasterio.open(terrain_path) as src:
        gt = tuple(src.transform.to_gdal())
        width, height = src.width, src.height
        crs_rio = CRS.from_user_input(src.crs) if src.crs else None
    if crs_rio is None:
        raise FimUnsupportedError(f"terrain {terrain_path.name} has no CRS")
    if results_crs is None or CRS.from_user_input(results_crs) != crs_rio:
        raise FimUnsupportedError(
            f"the hydraulic results CRS must equal the terrain CRS ({crs_rio.to_string()})"
        )
    if (info.get("width"), info.get("height")) != (width, height):
        raise FimEngineError(
            f"terrain size differs: engine {info.get('width')}x{info.get('height')}, rasterio {width}x{height}"
        )
    engine_gt = info.get("geo_transform")
    if engine_gt is None or len(engine_gt) != 6 or any(float(a) != float(b) for a, b in zip(engine_gt, gt)):
        raise FimEngineError(f"terrain geotransform differs: engine {engine_gt}, rasterio {gt}")

    epsg = crs_rio.to_epsg()
    if epsg is None:
        raise FimUnsupportedError(f"terrain CRS has no EPSG code: {crs_rio.to_string()}")
    fnv = info.get("crs_wkt_fnv1a64")
    if info.get("epsg") is not None:
        if int(info["epsg"]) != epsg:
            raise FimEngineError(f"terrain EPSG differs: engine {info['epsg']}, rasterio {epsg}")
        identity = {"kind": "epsg"}
    elif terrain_crs_fnv1a64:
        if fnv != terrain_crs_fnv1a64:
            raise FimEngineError(
                f"terrain_crs_fnv1a64={terrain_crs_fnv1a64} does not match the engine WKT hash {fnv}"
            )
        identity = {"kind": "caller_verified_wkt", "fnv1a64": fnv}
    else:
        wkt = _find_wkt(info.get("crs"))
        if wkt is None or fnv is None:
            raise FimUnsupportedError(
                "the engine did not identify an EPSG code for the terrain and exposed no WKT to verify; "
                "after checking `ras2fim-batch terrain-info`, pass terrain_crs_fnv1a64"
            )
        try:
            crs_engine = CRS.from_wkt(wkt)
        except Exception as exc:
            raise FimEngineError(f"engine terrain WKT is not parseable: {exc}") from exc
        if crs_engine != crs_rio:
            raise FimUnsupportedError(f"engine terrain CRS differs from rasterio CRS {crs_rio.to_string()}")
        identity = {"kind": "caller_verified_wkt", "fnv1a64": fnv}
    return {"path": str(terrain_path), "epsg": epsg, "crs_identity": identity}


@dataclass
class ProfileRequest:
    """One profile in a batch request."""

    profile: str
    inputs_dir: str
    grids: Any
    window: Any = None  # FimAoiWindow or None for the full grid
    mask_file: Optional[str] = None


@dataclass
class ProfileOutput:
    """One profile's engine result."""

    profile: str
    status: str
    depth: Optional[np.ndarray] = None
    wse: Optional[np.ndarray] = None
    transform: Any = None
    error: Optional[str] = None
    unit: dict = field(default_factory=dict)


def _dest_geotransform(grids) -> list:
    t = grids.dest_transform
    return [t.c, t.a, t.b, t.f, t.d, t.e]


def build_request(terrain: dict, profiles: List[ProfileRequest], *, dst_epsg: int, threads: int,
                  max_cache_bytes: int, max_profile_bytes: int, nudge_method: str,
                  max_inflight_profiles: int = 1) -> dict:
    """Return a ``ras2fim-step05-request/1`` document."""
    items = []
    for p in profiles:
        if not _SAFE_ID.match(p.profile):
            raise FimUnsupportedError(f"profile name {p.profile!r} must match {_SAFE_ID.pattern}")
        if p.window is None:
            aoi = {"id": "full"}
        else:
            aoi = {"id": "aoi", "window": p.window.window}
            if p.mask_file is not None:
                aoi["mask_u8"] = p.mask_file
        items.append({
            "id": p.profile,
            "inputs_dir": p.inputs_dir,
            "dest_grid": {"geotransform": _dest_geotransform(p.grids),
                          "width": p.grids.dest_width, "height": p.grids.dest_height},
            "aois": [aoi],
        })
    return {
        "schema": REQUEST_SCHEMA,
        "terrain": terrain,
        "source_crs": {"kind": "terrain"},
        "budgets": {"threads": int(threads), "max_cache_bytes": int(max_cache_bytes),
                    "max_profile_bytes": int(max_profile_bytes),
                    "max_inflight_profiles": int(max_inflight_profiles)},
        "interpolation": {"selection": "auto"},
        "nudge": {"dst_epsg": int(dst_epsg), "error_threshold": NUDGE_ERROR_THRESHOLD,
                  "memory_limit_bytes": NUDGE_MEMORY_LIMIT_BYTES, "method": nudge_method},
        "stages": [],
        "profiles": items,
    }


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_numbers(values, count: int) -> bool:
    return (isinstance(values, list) and len(values) == count
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v) for v in values))


def read_report(out_dir: Path, exit_code: int, profiles: List[str]) -> dict:
    """Read ``report.json`` and check it against the exit status and the request."""
    path = Path(out_dir) / "report.json"
    if not path.is_file():
        raise FimEngineError(f"{ENGINE_NAME} step05 exited {exit_code} without report.json")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FimEngineError(f"malformed engine report.json: {exc}") from exc
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA:
        raise FimEngineError(f"engine report.json schema is not {REPORT_SCHEMA}")
    expected = "complete" if exit_code == 0 else "failed"
    if report.get("status") != expected:
        raise FimEngineError(f"engine report status {report.get('status')!r} disagrees with exit {exit_code}")
    items = report.get("profiles")
    if not isinstance(items, list) or not all(isinstance(d, dict) for d in items):
        raise FimEngineError("engine report.json has no profile list")
    ids = [d.get("id") for d in items]
    if ids != profiles:
        raise FimEngineError(f"engine report profiles {ids} differ from the request {profiles}")
    return report


def read_unit(p: ProfileRequest, out_dir: Path) -> ProfileOutput:
    """Read and validate one unit. Raises :class:`FimEngineError` unless it is complete and consistent."""
    from affine import Affine

    aoi_id = "full" if p.window is None else "aoi"
    unit_dir = Path(out_dir) / "units" / p.profile / aoi_id
    unit_path = unit_dir / "unit.json"
    if not unit_path.is_file():
        raise FimEngineError(f"{p.profile}: engine wrote no unit.json")
    try:
        unit = json.loads(unit_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FimEngineError(f"{p.profile}: malformed unit.json: {exc}") from exc
    if not isinstance(unit, dict) or unit.get("schema") != UNIT_SCHEMA:
        raise FimEngineError(f"{p.profile}: unit.json schema is not {UNIT_SCHEMA}")
    if unit.get("profile") != p.profile or unit.get("aoi") != aoi_id:
        raise FimEngineError(f"{p.profile}: unit.json identifies {unit.get('profile')!r}/{unit.get('aoi')!r}, "
                             f"expected {p.profile!r}/{aoi_id!r}")
    if unit.get("status") != "complete":
        raise FimEngineError(f"{p.profile}: engine unit status {unit.get('status')!r}: {unit.get('error', '')}")

    window = unit.get("window")
    if not (isinstance(window, list) and len(window) == 4 and all(_is_int(v) for v in window)
            and min(window) >= 0):
        raise FimEngineError(f"{p.profile}: unit.json window {window!r} is not four non-negative integers")
    gt = unit.get("window_geotransform")
    if not _finite_numbers(gt, 6):
        raise FimEngineError(f"{p.profile}: unit.json window_geotransform {gt!r} is not six finite numbers")
    if p.window is None:
        expected = [0, 0, p.grids.dest_width, p.grids.dest_height]
        transform = p.grids.dest_transform
    else:
        expected = p.window.window
        transform = p.window.transform
    if window != expected:
        raise FimEngineError(f"{p.profile}: engine window {window} differs from requested {expected}")
    tol = 1e-6 * abs(transform.a)
    if any(abs(u - v) > tol for u, v in zip(tuple(Affine.from_gdal(*gt))[:6], tuple(transform)[:6])):
        raise FimEngineError(f"{p.profile}: engine window geotransform {gt} differs from {tuple(transform)[:6]}")
    if "polygon_mask_applied" in unit and bool(unit["polygon_mask_applied"]) != (p.mask_file is not None):
        raise FimEngineError(f"{p.profile}: polygon_mask_applied={unit['polygon_mask_applied']} is inconsistent")

    width, height = window[2], window[3]
    for key, value in (("width", width), ("height", height)):
        if key in unit and unit[key] != value:
            raise FimEngineError(f"{p.profile}: unit.json {key} {unit[key]!r} differs from the window")
    counts = unit.get("finite_counts")
    if not isinstance(counts, dict):
        raise FimEngineError(f"{p.profile}: unit.json has no finite_counts")
    arrays = {}
    for name in ("depth", "wse"):
        path = unit_dir / f"{name}.f32"
        if not path.is_file():
            raise FimEngineError(f"{p.profile}: unit is complete but {name}.f32 is missing")
        size = path.stat().st_size
        if size != 4 * width * height:
            raise FimEngineError(f"{p.profile}: {name}.f32 has {size} bytes, expected {4 * width * height}")
        arr = np.fromfile(path, dtype="<f4").reshape(height, width)
        key = next((k for k in counts if k.split(".")[0] == name), None)
        if key is None:
            raise FimEngineError(f"{p.profile}: finite_counts lacks {name}")
        finite = int(np.isfinite(arr).sum())
        if not _is_int(counts[key]) or counts[key] != finite:
            raise FimEngineError(f"{p.profile}: {name}.f32 has {finite} finite values, unit.json says {counts[key]}")
        if p.window is not None and p.window.mask is not None and np.isfinite(arr[~p.window.mask]).any():
            raise FimEngineError(f"{p.profile}: {name} has finite values outside the polygon mask")
        arrays[name] = arr
    return ProfileOutput(p.profile, "complete", arrays["depth"], arrays["wse"], transform, unit=unit)


def run_request(engine: Path, work_dir: Path, batch: int, request: dict, profiles: List[ProfileRequest],
                timeout: Optional[float] = None):
    """Write and run one batch request. Returns ``(outputs, report)``.

    Exit 0 and 2 are read per profile. Any other exit raises
    :class:`FimEngineError`. The engine report is required and must agree
    with the exit status and the requested profiles. A profile that is not
    complete in both the report and a consistent unit is returned with
    status ``failed``.
    """
    request_path = Path(work_dir) / f"request_{batch:04d}.json"
    request_path.write_text(json.dumps(request, indent=1), encoding="utf-8")
    out_dir = Path(work_dir) / f"out_{batch:04d}"
    proc = run_engine([str(engine), "step05", str(request_path), str(out_dir)], "step05", timeout)
    stderr = proc.stderr.strip()
    if proc.returncode not in (0, 2):
        raise FimEngineError(f"{ENGINE_NAME} step05 failed with exit {proc.returncode}: {stderr[-_STDERR_TAIL:]}")

    report = read_report(out_dir, proc.returncode, [p.profile for p in profiles])
    report_status = {d["id"]: d for d in report["profiles"]}
    outputs = []
    for p in profiles:
        item = report_status[p.profile]
        if item.get("status") != "complete":
            detail = f"{item.get('error_kind', '')} {item.get('error', '')}".strip()
            outputs.append(ProfileOutput(p.profile, "failed",
                                         error=f"engine report status {item.get('status')!r}: {detail}"))
            continue
        try:
            outputs.append(read_unit(p, out_dir))
        except (FimEngineError, OSError, ValueError) as exc:
            outputs.append(ProfileOutput(p.profile, "failed",
                                         error=f"{exc} (engine exit {proc.returncode}; stderr: {stderr[-1000:]})"))
    if proc.returncode == 2 and all(o.status == "complete" for o in outputs):
        raise FimEngineError(f"{ENGINE_NAME} step05 exited 2 but every unit reads as complete: {stderr[-2000:]}")
    if proc.returncode == 0 and any(o.status != "complete" for o in outputs):
        failed = [o.profile for o in outputs if o.status != "complete"]
        raise FimEngineError(f"{ENGINE_NAME} step05 exited 0 but units are not complete: {failed}")
    return outputs, report
