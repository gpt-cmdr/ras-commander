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


def crs_any(record) -> bool:
    """Whether an engine method record accepts a CRS without an EPSG code.

    Fast-Map 0.20+ advertises ``crs_any: true`` on methods that take
    ``crs_geokeys``: the GeoKey tags of a GeoTIFF in that CRS, which the
    engine writes back verbatim into its GeoTIFFs. Older engines label
    outputs from an EPSG code alone.
    """
    return isinstance(record, dict) and record.get("crs_any") is True


def crs_any_kwargs(record) -> dict:
    """``{"crs_any": True}`` for :func:`terrain_identity` when ``record`` advertises it, else ``{}``."""
    return {"crs_any": True} if crs_any(record) else {}


def request_crs(identity: dict) -> dict:
    """The CRS fields of an engine request for a :func:`terrain_identity` result.

    ``{"epsg": code}`` as before, or ``{"crs_geokeys": {...}}`` for a CRS
    without an EPSG code (the engine's ``epsg`` then defaults to 0).
    """
    if identity.get("epsg") is not None:
        return {"epsg": int(identity["epsg"])}
    keys = identity.get("crs_geokeys")
    if not isinstance(keys, dict):
        raise FimEngineError("terrain identity has neither an EPSG code nor crs_geokeys")
    return {"crs_geokeys": keys}


def _crs_equal(a, b) -> bool:
    from pyproj import CRS
    return CRS.from_user_input(a).equals(CRS.from_user_input(b))


def geokeys_for_crs(engine: Path, crs, folder: Path, *, timeout: Optional[float] = None) -> dict:
    """GeoKey tags that GDAL writes for ``crs``, checked by a GDAL round trip.

    For a CRS that has no GeoTIFF to copy tags from (RAS Mapper terrain
    sources carry none when the CRS has no EPSG code; 1D grids), GDAL
    encodes ``crs`` in a one-pixel GeoTIFF under ``folder`` and the engine
    reads its tags (``terrain-info``). The tags are used only when GDAL
    reads that file back as the same CRS (``pyproj.CRS.equals``); otherwise
    the CRS has no faithful GeoTIFF encoding here and the request is refused.
    For RAS Mapper's ESRI:102630 terrain these are the tags of RAS Mapper's
    own export of that terrain.
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    reference = folder / "crs_reference.tif"
    declared = rasterio.crs.CRS.from_user_input(crs)
    with rasterio.open(reference, "w", driver="GTiff", width=1, height=1, count=1,
                       dtype="float32", crs=declared, transform=from_origin(0.0, 1.0, 1.0, 1.0)) as dst:
        dst.write(np.zeros((1, 1), dtype="float32"), 1)
    with rasterio.open(reference) as src:
        written = src.crs
    if written is None or not _crs_equal(written.to_wkt(), declared.to_wkt()):
        raise FimUnsupportedError(
            f"GDAL does not write CRS {declared.to_string()} to GeoTIFF keys that read back as the same CRS; "
            "the native engine cannot label its output faithfully"
        )
    command = [str(engine), "terrain-info", str(reference)]
    info = _json_stdout(run_engine(command, "terrain-info") if timeout is None else
                        run_engine(command, "terrain-info", timeout), "ras2fim-batch terrain-info")
    keys = info.get("geokeys")
    if not isinstance(keys, dict):
        raise FimEngineError(f"the engine read no GeoKeys from {reference}: {info.get('geokeys_error')}")
    return keys


def untagged_source_hdf(tiff, terrain_hdf=None):
    """For a terrain TIFF without CRS tags, the terrain HDF that registers it
    (its CRS source, to watch with the other inputs); None for tagged TIFFs."""
    import rasterio

    with rasterio.open(tiff) as src:
        if src.crs:
            return None
    from ._effective_terrain import registered_source_hdf
    return registered_source_hdf(tiff, terrain_hdf)


def source_identity(engine: Path, tiff: Path, results_crs, terrain_crs_fnv1a64: Optional[str] = None, *,
                    crs_any: bool = False, declared_crs=None, keys_folder: Optional[Path] = None,
                    timeout: Optional[float] = None, source_crs_identity: bool = False,
                    terrain_hdf=None) -> dict:
    """:func:`terrain_identity`, plus RAS Mapper sources that carry no CRS.

    A TIFF without any CRS tags (RAS Mapper's terrain sources in a CRS without
    an EPSG code) is accepted only with ``crs_any`` and an explicit
    ``declared_crs`` (the terrain HDF's ``Projection``) equal to
    ``results_crs``: the identity is ``untagged`` with GDAL's GeoKeys for
    that CRS (:func:`geokeys_for_crs`, round-trip checked). Without
    ``declared_crs`` it is the Projection of the terrain HDF that registers
    the TIFF (``terrain_hdf`` when given; see
    :func:`_effective_terrain.registered_source_hdf`).
    """
    import rasterio
    from pyproj import CRS

    with rasterio.open(tiff) as src:
        tagged = bool(src.crs)
    if not tagged and crs_any and declared_crs is None:
        from ._effective_terrain import registered_source_crs
        declared_crs = registered_source_crs(tiff, terrain_hdf)
    if tagged or not crs_any or declared_crs is None:
        kwargs = {"timeout": timeout} if timeout is not None else {}
        if crs_any:
            kwargs["crs_any"] = True
        if source_crs_identity:
            kwargs["source_crs_identity"] = True
        return terrain_identity(engine, tiff, results_crs, terrain_crs_fnv1a64, **kwargs)
    declared = CRS.from_user_input(declared_crs)
    if results_crs is None or not declared.equals(CRS.from_user_input(results_crs)):
        raise FimUnsupportedError(
            f"terrain {Path(tiff).name} carries no CRS and the declared terrain CRS differs from the results CRS")
    if keys_folder is None:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ras-fim-crs-") as folder:
            keys = geokeys_for_crs(engine, declared, Path(folder), timeout=timeout)
    else:
        keys = geokeys_for_crs(engine, declared, Path(keys_folder), timeout=timeout)
    return {"path": str(tiff), "epsg": None, "crs_identity": {"kind": "untagged"}, "crs_geokeys": keys,
            "declared_crs": declared.to_wkt()}


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


def terrain_identity(engine: Path, terrain_path: Path, results_crs, terrain_crs_fnv1a64: Optional[str] = None, *, timeout: Optional[float] = None, source_crs_identity: bool = False, crs_any: bool = False) -> dict:
    """Cross-check terrain identity, optionally retaining an unapplied BoundCRS.

    The default compares complete definitions. Explicit source identity unwraps
    only BoundCRS and preserves its original definition/binding in provenance.
    No coordinate or datum conversion is performed.

    ``crs_any`` (the engine method advertises it, see :func:`crs_any`) accepts
    a terrain CRS without an EPSG code: the result has ``epsg: None``,
    ``crs_identity: {"kind": "geokeys"}`` and the terrain's own GeoKey tags
    as ``crs_geokeys``, which the engine checks against the terrain and
    writes verbatim. Whether the CRS has an EPSG code is decided by
    rasterio/PROJ, never by the engine's reading. Build request fields with
    :func:`request_crs`.
    """
    import rasterio
    from pyproj import CRS
    from ._source_crs import source_crs, describe_crs

    if not isinstance(source_crs_identity, bool):
        raise ValueError("source_crs_identity must be a boolean")

    command = [str(engine), "terrain-info", str(terrain_path)]
    probe = (run_engine(command, "terrain-info") if timeout is None else
             run_engine(command, "terrain-info", timeout))
    info = _json_stdout(probe,
                        "ras2fim-batch terrain-info")
    with rasterio.open(terrain_path) as src:
        gt = tuple(src.transform.to_gdal())
        width, height = src.width, src.height
        crs_rio = CRS.from_user_input(src.crs) if src.crs else None
    if crs_rio is None:
        raise FimUnsupportedError(f"terrain {terrain_path.name} has no CRS")
    original_rio = crs_rio
    original_results = CRS.from_user_input(results_crs) if results_crs is not None else None
    if source_crs_identity:
        crs_rio = source_crs(crs_rio)
        compared_results = source_crs(original_results) if original_results is not None else None
    else:
        compared_results = original_results
    if compared_results is None or compared_results != crs_rio:
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
    if epsg is None and crs_any:
        keys = info.get("geokeys")
        if not isinstance(keys, dict):
            raise FimUnsupportedError(
                f"terrain {Path(terrain_path).name} has CRS {crs_rio.to_string()} without an EPSG code "
                f"and no GeoKey tags the engine can copy ({info.get('geokeys_error') or 'none'})"
            )
        result = {"path": str(terrain_path), "epsg": None, "crs_identity": {"kind": "geokeys"},
                  "crs_geokeys": keys, "crs_geokeys_fnv1a64": info.get("geokeys_fnv1a64")}
        if source_crs_identity:
            result["crs_provenance"] = {"policy": "bound-source-identity/1",
                "rasterio": describe_crs(original_rio), "results": describe_crs(original_results),
                "engine": None, "engine_wkt": _find_wkt(info.get("crs")), "engine_wkt_parse_error": None,
                "engine_epsg": info.get("epsg"), "engine_crs_wkt_fnv1a64": info.get("crs_wkt_fnv1a64"),
                "terrain_crs_fnv1a64_requested": terrain_crs_fnv1a64}
        return result
    if epsg is None:
        raise FimUnsupportedError(
            f"terrain CRS has no EPSG code: {crs_rio.to_string()} ({crs_rio.name}). This engine "
            "method does not advertise crs_any, so its requests carry the terrain CRS as an EPSG "
            "code; terrain_crs_fnv1a64 only pins the engine's WKT reading of a CRS that rasterio "
            "identifies by EPSG and cannot replace the code. Use ras-commander-fast-map 0.20+ "
            "(crs_any), or a terrain (and results) in a CRS with an EPSG code."
        )
    fnv = info.get("crs_wkt_fnv1a64")
    original_engine = None
    engine_wkt = None
    engine_wkt_error = None
    if source_crs_identity:
        if info.get("epsg") is not None and int(info["epsg"]) != epsg:
            raise FimEngineError(f"terrain EPSG differs: engine {info['epsg']}, rasterio {epsg}")
        if info.get("epsg") is None and terrain_crs_fnv1a64 and fnv != terrain_crs_fnv1a64:
            raise FimEngineError(
                f"terrain_crs_fnv1a64={terrain_crs_fnv1a64} does not match the engine WKT hash {fnv}"
            )
        automatic_wkt_identity = info.get("epsg") is None and not terrain_crs_fnv1a64
        engine_wkt = _find_wkt(info.get("crs"))
        if engine_wkt is not None:
            try:
                original_engine = CRS.from_wkt(engine_wkt)
            except Exception as exc:
                if automatic_wkt_identity:
                    raise FimEngineError(f"engine terrain WKT is not parseable: {exc}") from exc
                engine_wkt_error = str(exc)
            # Retain the established authority order: identified matching EPSG,
            # then explicit verified raw pin, then automatic WKT equivalence.
            # Legacy WKT is diagnostic when either earlier authority applies.
            if (original_engine is not None and automatic_wkt_identity
                    and source_crs(original_engine) != crs_rio):
                raise FimUnsupportedError(f"engine terrain source CRS differs from rasterio CRS {crs_rio.to_string()}")
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
        if (source_crs(crs_engine) if source_crs_identity else crs_engine) != crs_rio:
            raise FimUnsupportedError(f"engine terrain CRS differs from rasterio CRS {crs_rio.to_string()}")
        identity = {"kind": "caller_verified_wkt", "fnv1a64": fnv}
    result = {"path": str(terrain_path), "epsg": epsg, "crs_identity": identity}
    if source_crs_identity:
        result["crs_provenance"] = {"policy": "bound-source-identity/1",
            "rasterio": describe_crs(original_rio), "results": describe_crs(original_results),
            "engine": describe_crs(original_engine) if original_engine is not None else None,
            "engine_wkt": engine_wkt, "engine_wkt_parse_error": engine_wkt_error,
            "engine_epsg": info.get("epsg"), "engine_crs_wkt_fnv1a64": fnv,
            "terrain_crs_fnv1a64_requested": terrain_crs_fnv1a64}
    return result


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
                  max_inflight_profiles: int = 1, dst_wkt: Optional[str] = None) -> dict:
    """Return a ``ras2fim-step05-request/1`` document.

    ``terrain`` is a :func:`terrain_identity` result (EPSG code or GeoKeys).
    ``dst_wkt`` (with ``dst_epsg`` 0) names a destination CRS without an EPSG
    code, for engines whose ``step05_r2`` advertises ``crs_any``.
    """
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
        "terrain": {"path": terrain["path"], **request_crs(terrain),
                    "crs_identity": terrain["crs_identity"]},
        "source_crs": {"kind": "terrain"},
        "budgets": {"threads": int(threads), "max_cache_bytes": int(max_cache_bytes),
                    "max_profile_bytes": int(max_profile_bytes),
                    "max_inflight_profiles": int(max_inflight_profiles)},
        "interpolation": {"selection": "auto"},
        "nudge": {"dst_epsg": int(dst_epsg), **({"dst_wkt": dst_wkt} if dst_wkt is not None else {}),
                  "error_threshold": NUDGE_ERROR_THRESHOLD,
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
