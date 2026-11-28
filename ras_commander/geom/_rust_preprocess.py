"""Experimental Rust 2D geometry preprocessing and its native-equivalence harness.

The Rust engine (``ras-preprocess``, from the private
``gpt-cmdr/ras-commander-fast-preprocess`` repository) computes the 2D flow-area
property tables that native HEC-RAS 7.0.1 preprocessing writes into a geometry
HDF: face profiles, face-point elevations, Manning's n and classification
families, face area-elevation tables and cell volume-elevation tables.

This module is **experimental**. It is not a replacement for native
preprocessing. Before any production use, prove equivalence on your own model
with :func:`validate_rust_equivalence`, which runs native preprocessing and the
Rust engine side by side on copies of the model and compares every product.

Public entry points are the ``GeomPreprocessor.compute_rust_experimental`` and
``GeomPreprocessor.validate_rust_equivalence`` static methods; this module
holds their implementation.

The engine binary is not bundled. It is located from an explicit path, the
``RAS_COMMANDER_PREPROCESS_EXE`` environment variable, or ``PATH``
(``ras-preprocess``), in that order.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from ..LoggingConfig import get_logger

logger = get_logger(__name__)

__all__ = [
    "ENGINE_ENV_VAR",
    "SUPPORTED_FILE_VERSIONS",
    "ExperimentalWarning",
    "RustPreprocessError",
    "RustPreprocessNotFoundError",
    "RustPreprocessRefusedError",
    "RustEngineInfo",
    "RustPreprocessResult",
    "RustDatasetComparison",
    "RustEquivalenceReport",
]

ENGINE_ENV_VAR = "RAS_COMMANDER_PREPROCESS_EXE"
ENGINE_NAMES = ("ras-preprocess",)
# The engine reproduces HEC-RAS 7.0.1 only. The write-back refuses any other
# geometry HDF schema rather than guessing.
SUPPORTED_FILE_VERSIONS = ("HEC-RAS 7.0.1 June 2026",)
DEFAULT_ENGINE_TIMEOUT = 3600.0
_STDERR_TAIL = 4000
AREAS = "Geometry/2D Flow Areas"

# Products of native 2D preprocessing, per 2D flow area. Classification and
# parameter families (``Infiltration/...``, ``Percent Impervious/...``,
# sediment) live in subgroups of the area and are products too.
PRODUCT_DATASETS = (
    "Cells Center Manning's n",
    "Cells Minimum Elevation",
    "Cells Surface Area",
    "Cells Volume Elevation Info",
    "Cells Volume Elevation Values",
    "Faces Area Elevation Info",
    "Faces Area Elevation Values",
    "Faces Low Elevation Centroid",
    "Faces Minimum Elevation",
    "Faces Profile Info",
    "Faces Profile Values",
    "FacePoints Elevation",
)
LONG_FACE_POINTS = 1000  # L-1: native integrates these faces with a racy parallel loop

# Currency attributes. A native HEC-RAS 7.0.1 RAS Mapper recompute
# (``RasMap.recompute_property_tables``) changes exactly these attributes and
# nothing else outside the product datasets, as an attribute-only diff of
# every HDF object shows (Muncie g02 and Bald Eagle g09, two runs each):
#
# - ``Property Tables Last Computed`` on every recomputed 2D area: the local
#   wall-clock time at which the area's tables completed, as a fixed-length
#   ``|S18`` string ``DDMONYYYY HH:MM:SS`` with an upper-case English month.
#   The Rust write-back restamps it the same way (see ``_native_timestamp``).
# - ``Property Tables LC Hash`` (32-byte SHA-256) on areas with a land-cover
#   association. Native rewrites it only when its input-derived value differs
#   (a second recompute kept it and reported "Mesh property tables are
#   current"). Its construction (a SHA-256 over RasMapperLib's calibration-
#   region feature-layer hash, the region class maps, the land-cover names
#   and the base n values) is not specified exactly enough to reproduce, and
#   the engine does not compute it. The write-back therefore keeps the
#   source's value and warns; it never guesses a hash.
LAST_COMPUTED_ATTR = "Property Tables Last Computed"
LC_HASH_ATTR = "Property Tables LC Hash"
NOT_RESTAMPED_ATTRS = (LC_HASH_ATTR,)
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
# Classification families of Stage 2 whose coverage by the engine's own
# ``--compare`` arrives with the engine's workstream P (in progress).
STAGE2_FAMILIES = ("Infiltration", "Percent Impervious")


def _native_timestamp(now: Optional[datetime] = None) -> str:
    """Return ``now`` (default: local time) as native writes currency stamps.

    Native HEC-RAS 7.0.1 writes ``Property Tables Last Computed`` as local
    time in ``DDMONYYYY HH:MM:SS`` with an upper-case English month, for
    example ``27NOV2026 22:59:52``. The month table is fixed, so the stamp
    does not depend on the process locale.
    """
    now = now or datetime.now()
    return f"{now.day:02d}{_MONTHS[now.month - 1]}{now.year:04d} {now:%H:%M:%S}"

# Engine messages that mean "input outside the qualified scope" rather than a
# crash. The engine names each refused layer and form in the message.
_REFUSAL_MARKERS = (
    "refused",
    "refusing",
    "not supported",
    "unsupported",
    "not traced",
    "not reproduced",
    "not tiled",
    "not a north-up",
    "non-square tiles",
    "no readable /terrain",
    "no terrain filename",
    # A layer association the engine cannot open (it does not resolve layers
    # through the .rasmap, as native does).
    "does not resolve layers",
    "which does not exist",
)

KNOWN_NATIVE_BEHAVIOURS = {
    "D-4": (
        "Composite LC: native never clears the per-worker cell mask, so composite "
        "Manning's n and classification parameters mix in pixels of earlier cells. "
        "Native-compatible mode reproduces native at worker limits 1, 2 and 4 "
        "(RAS Commander's recompute uses 1); corrected mode clears it."
    ),
    "D-5": (
        "Multiple Face Mann n: native drops LCMann Table base overrides from the "
        "face profiles when the calibration-table row count differs from the class "
        "count. Native-compatible mode reproduces the drop; corrected mode applies them."
    ),
    "L-1": (
        f"Faces with more than {LONG_FACE_POINTS} profile points: native integrates "
        "them with an unsynchronized parallel loop, so native output is not reproducible."
    ),
    "N-1": (
        "Polygon terrain modifications with control points: native builds TINs from a "
        "lazily created shared quadtree; some native runs differ or abort."
    ),
    "N-2": (
        "Stage 1 tile-piece order follows thread scheduling under the default .NET pool; "
        "RAS Commander's one-worker pool matches the engine."
    ),
    "N-3": (
        "Stitch-edge order depends on a process-assigned CLR type id; observed stable."
    ),
}


class ExperimentalWarning(UserWarning):
    """Warns that an experimental RAS Commander workflow is in use."""


class RustPreprocessError(RuntimeError):
    """The Rust preprocessor failed, or its output failed validation."""


class RustPreprocessNotFoundError(FileNotFoundError):
    """The ``ras-preprocess`` executable could not be located.

    RAS Commander never downloads or installs the engine.
    """


class RustPreprocessRefusedError(RustPreprocessError):
    """The engine refused an input outside its qualified scope.

    Attributes:
        refusal: The engine's message, which names what was refused (for
            example each terrain-modification layer and its form).
        geometry_hdf: The geometry HDF that was refused.
    """

    def __init__(self, refusal: str, geometry_hdf: Optional[Path] = None):
        self.refusal = refusal
        self.geometry_hdf = geometry_hdf
        where = f" ({geometry_hdf})" if geometry_hdf else ""
        super().__init__(f"Rust preprocessor refused the input{where}: {refusal}")


# ---------------------------------------------------------------------------
# Engine discovery and execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RustEngineInfo:
    """Provenance of the engine binary that was run.

    Attributes:
        path: Resolved executable path.
        version: ``ras-preprocess --version`` output.
        sha256: SHA-256 of the executable.
        source: How it was found: ``engine_exe``, ``RAS_COMMANDER_PREPROCESS_EXE`` or ``PATH``.
    """

    path: Path
    version: str
    sha256: str
    source: str

    def to_dict(self) -> Dict[str, str]:
        return {"path": str(self.path), "version": self.version, "sha256": self.sha256, "source": self.source}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as s:
        for chunk in iter(lambda: s.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_engine(engine_exe: Union[str, Path, None] = None) -> RustEngineInfo:
    """Locate the engine: ``engine_exe``, then ``RAS_COMMANDER_PREPROCESS_EXE``, then ``PATH``."""
    if engine_exe is not None:
        path, source = Path(os.fspath(engine_exe)).expanduser(), "engine_exe"
    elif os.environ.get(ENGINE_ENV_VAR):
        path, source = Path(os.environ[ENGINE_ENV_VAR]).expanduser(), ENGINE_ENV_VAR
    else:
        found = next((shutil.which(n) for n in ENGINE_NAMES if shutil.which(n)), None)
        if not found:
            raise RustPreprocessNotFoundError(
                "The experimental Rust preprocessor (ras-preprocess) was not found. Pass "
                f"engine_exe=..., or set {ENGINE_ENV_VAR} to the executable path. The engine "
                "is not distributed with RAS Commander."
            )
        path, source = Path(found), "PATH"
    if not path.is_file():
        raise RustPreprocessNotFoundError(f"{source}: ras-preprocess executable not found: {path}")
    path = path.resolve()
    try:
        out = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RustPreprocessError(f"cannot run {path} --version: {exc}") from exc
    version = (out.stdout or out.stderr).strip()
    if out.returncode != 0 or "ras-preprocess" not in version:
        raise RustPreprocessError(
            f"{path} does not look like ras-preprocess (--version exit {out.returncode}: {version[:200]!r})"
        )
    return RustEngineInfo(path=path, version=version, sha256=_sha256(path), source=source)


def _is_refusal(message: str) -> bool:
    low = message.lower()
    return any(m in low for m in _REFUSAL_MARKERS)


def _engine_options(
    native_compatible: bool, sort: str, units: Optional[str], threads: Optional[int]
) -> Dict[str, Any]:
    if sort not in ("introsort", "legacy"):
        raise ValueError("sort must be 'introsort' or 'legacy'")
    if units not in (None, "us", "si", "root"):
        raise ValueError("units must be None, 'us', 'si' or 'root'")
    if threads is not None and (not isinstance(threads, int) or threads < 1):
        raise ValueError("threads must be a positive integer or None")
    return {
        "mode": "native" if native_compatible else "corrected",
        "sort": sort,
        "units": units,
        "threads": threads,
    }


def run_engine(
    engine: RustEngineInfo,
    geom_hdf: Path,
    *,
    out_bundle: Optional[Path],
    options: Mapping[str, Any],
    compare: bool = False,
    timeout: Optional[float] = DEFAULT_ENGINE_TIMEOUT,
) -> Tuple[Dict[str, Any], List[str]]:
    """Run ``ras-preprocess all`` and return its JSON report and the command.

    The engine opens ``geom_hdf`` read-only. Raises
    :class:`RustPreprocessRefusedError` when the engine refuses the input and
    :class:`RustPreprocessError` on any other failure.
    """
    geom_hdf = Path(geom_hdf)
    with tempfile.TemporaryDirectory(prefix="ras-preprocess-") as tmp:
        report_path = Path(tmp) / "report.json"
        cmd = [str(engine.path), "all", str(geom_hdf), "--report", str(report_path)]
        if out_bundle is not None:
            cmd += ["--out", str(out_bundle)]
        if compare:
            cmd.append("--compare")
        cmd += ["--mode", options["mode"], "--sort", options["sort"]]
        if options.get("units"):
            cmd += ["--units", options["units"]]
        if options.get("threads"):
            cmd += ["--threads", str(options["threads"])]
        logger.info("Running experimental Rust preprocessor on %s", geom_hdf.name)
        logger.debug("Rust preprocessor command: %s", cmd)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RustPreprocessError(f"ras-preprocess timed out after {timeout} s on {geom_hdf}") from exc
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            message = stderr[-_STDERR_TAIL:] or f"exit code {proc.returncode}"
            message = message.removeprefix("ras-preprocess: ")
            if _is_refusal(message):
                raise RustPreprocessRefusedError(message, geom_hdf)
            raise RustPreprocessError(f"ras-preprocess failed on {geom_hdf} (exit {proc.returncode}): {message}")
        if not report_path.is_file():
            raise RustPreprocessError("ras-preprocess exited 0 but wrote no report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
    return report, cmd


# ---------------------------------------------------------------------------
# Guarded write-back of an engine bundle into a geometry HDF
# ---------------------------------------------------------------------------


def _decode(value: Any) -> str:
    if isinstance(value, np.ndarray):
        value = value.ravel()[0] if value.size else b""
    if isinstance(value, (bytes, np.bytes_)):
        return bytes(value).decode("utf-8", "replace").strip("\x00 ")
    return str(value)


def _dataset_hashes(path: Path) -> Dict[str, str]:
    import h5py

    out: Dict[str, str] = {}
    with h5py.File(path, "r") as f:
        def visit(name, obj):
            if isinstance(obj, h5py.Dataset):
                a = obj[()]
                b = a.tobytes() if isinstance(a, np.ndarray) else repr(a).encode()
                out[name] = hashlib.sha256(str(obj.dtype).encode() + str(obj.shape).encode() + b).hexdigest()
        f.visititems(visit)
    return out


def load_bundle(bundle: Path) -> Tuple[Dict[str, Any], Dict[Tuple[str, str], np.ndarray]]:
    """Read an engine bundle: ``manifest.json`` plus raw little-endian arrays."""
    bundle = Path(bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    arrays: Dict[Tuple[str, str], np.ndarray] = {}
    for entry in manifest["datasets"]:
        a = np.fromfile(bundle / entry["file"], dtype=np.dtype(entry["dtype"]))
        arrays[(entry["area"], entry["dataset"])] = a.reshape(entry["shape"])
    return manifest, arrays


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise RustPreprocessError(f"engine output failed validation: {msg}")


def _packed(info: np.ndarray, rows: int, what: str, allow_zero: bool) -> Tuple[np.ndarray, np.ndarray]:
    _check(info.ndim == 2 and info.shape[1] == 2, f"{what} Info must be [n, 2]")
    starts, counts = info[:, 0].astype(np.int64), info[:, 1].astype(np.int64)
    _check(bool(np.all(counts >= (0 if allow_zero else 1))), f"{what} Info has invalid counts")
    _check(np.array_equal(starts, np.concatenate(([0], np.cumsum(counts[:-1])))), f"{what} Info is not contiguous")
    _check(int(counts.sum()) == rows, f"{what} Info does not cover Values exactly")
    return starts, counts


def _strictly_increasing(z: np.ndarray, counts: np.ndarray, what: str) -> None:
    owner = np.repeat(np.arange(counts.size), counts)
    same = owner[1:] == owner[:-1]
    _check(bool(np.all(np.diff(z.astype(np.float64))[same] > 0)), f"{what}: elevations must strictly increase")


def _validate_area(t: Dict[str, np.ndarray], g) -> List[str]:
    """Check engine products for one area before they are written.

    HEC-RAS accepts any table without checking it, so these rules are enforced
    here: finite positive cell n, finite family parameters, contiguous and
    monotone tables, ghost-cell conventions, and every real cell's minimum at
    or below each adjacent face minimum.
    """
    checked = []
    n_cells = g["Cells Face and Orientation Info"].shape[0]
    n_faces = g["Faces FacePoint Indexes"].shape[0]
    if "Cells Center Manning's n" in t:
        n = t["Cells Center Manning's n"]
        _check(n.shape == (n_cells,), "Cells Center Manning's n: one value per cell")
        _check(bool(np.all(np.isfinite(n) & (n > 0))), "Cells Center Manning's n must be finite and positive")
        checked.append("cell Manning's n finite and positive")
    for k, v in t.items():
        if "/" not in k:
            continue
        if k.endswith("Classifications"):
            _check(bool(np.all(v >= -1)), f"{k}: class indices must be >= -1")
            if k.endswith("Face Center Classifications"):
                _check(v.shape == (n_faces,), f"{k}: one value per face")
        else:
            _check(bool(np.all(np.isfinite(v))), f"{k}: values must be finite")
    if any("/" in k for k in t):
        checked.append("family parameters finite, classes >= -1")
    if "Faces Area Elevation Info" in t:
        info, vals = t["Faces Area Elevation Info"], t["Faces Area Elevation Values"]
        _check(info.shape == (n_faces, 2) and vals.ndim == 2 and vals.shape[1] == 4, "face table shapes")
        starts, counts = _packed(info, vals.shape[0], "Faces Area Elevation", allow_zero=False)
        _check(bool(np.all(np.isfinite(vals)) and np.all(vals[:, 1:] >= 0)), "face table values non-finite or negative")
        _strictly_increasing(vals[:, 0], counts, "Faces Area Elevation Values")
        for k in ("Faces Minimum Elevation", "Faces Low Elevation Centroid"):
            _check(t[k].shape == (n_faces,), f"{k}: one value per face")
        _check(np.array_equal(t["Faces Minimum Elevation"], vals[starts, 0]), "Faces Minimum Elevation != first row")
        checked.append("face tables")
    if "Cells Volume Elevation Info" in t:
        info, vals = t["Cells Volume Elevation Info"], t["Cells Volume Elevation Values"]
        _check(info.shape == (n_cells, 2) and vals.ndim == 2 and vals.shape[1] == 2, "cell table shapes")
        starts, counts = _packed(info, vals.shape[0], "Cells Volume Elevation", allow_zero=True)
        _check(bool(np.all(np.isfinite(vals))), "cell table values must be finite")
        _strictly_increasing(vals[:, 0], counts, "Cells Volume Elevation Values")
        owner = np.repeat(np.arange(n_cells), counts)
        same = owner[1:] == owner[:-1]
        _check(bool(np.all(np.diff(vals[:, 1].astype(np.float64))[same] >= 0)), "cell volumes must not decrease")
        real = counts > 0
        _check(bool(np.all(vals[starts[real], 1] == 0)), "cell volume curves must start at 0")
        cmin = t["Cells Minimum Elevation"]
        _check(cmin.shape == (n_cells,), "Cells Minimum Elevation: one value per cell")
        _check(bool(np.all(np.isnan(cmin[~real]))), "ghost cells must have a NaN minimum")
        _check(np.array_equal(cmin[real], vals[starts[real], 0]), "Cells Minimum Elevation != first curve elevation")
        sa = t["Cells Surface Area"]
        _check(sa.shape == (n_cells,) and bool(np.all(np.isfinite(sa))), "Cells Surface Area must be finite")
        _check(bool(np.all(sa[real] > 0)), "real cells must have a positive surface area")
        checked.append("cell tables")
        fmin = t.get("Faces Minimum Elevation")
        if fmin is None:
            fmin = g["Faces Minimum Elevation"][()]
        cfi = g["Cells Face and Orientation Info"][()]
        cfv = g["Cells Face and Orientation Values"][()]
        cell_of = np.repeat(np.arange(n_cells), cfi[:, 1])
        fm = fmin[cfv[:, 0]].astype(np.float64)
        cm = cmin[cell_of].astype(np.float64)
        ok = np.isnan(fm) | np.isnan(cm) | (cm <= fm)
        _check(bool(np.all(ok)), f"cell minimum above an adjacent face minimum in {int((~ok).sum())} cell-face pairs")
        checked.append("cell minimum <= adjacent face minima")
    if "FacePoints Elevation" in t:
        fp = t["FacePoints Elevation"]
        _check(fp.shape == g["FacePoints Coordinate"].shape[:1], "FacePoints Elevation: one value per face point")
        _check(bool(np.all(np.isfinite(fp))), "FacePoints Elevation must be finite")
        checked.append("face-point elevations")
    return checked


def _attr_equal(a: Any, want: Any) -> bool:
    if want is None:
        return True
    v = np.asarray(a).ravel()
    if v.size != 1:
        return False
    v = v[0]
    if isinstance(want, bool) or (isinstance(want, int) and not isinstance(v, (float, np.floating))):
        return int(v) == int(want)
    return np.float32(v) == np.float32(want)


def geometry_preconditions(geom_hdf: Path) -> Tuple[str, bool, List[str]]:
    """Return ``(File Version, Complete Geometry, 2D area names)`` of a geometry HDF."""
    import h5py

    with h5py.File(geom_hdf, "r") as f:
        fv = _decode(f.attrs.get("File Version", b""))
        geometry = f.get("Geometry")
        complete = geometry is not None and _decode(geometry.attrs.get("Complete Geometry", b"")).lower() == "true"
        areas = []
        if AREAS in f:
            areas = [k for k, v in f[AREAS].items() if isinstance(v, h5py.Group)]
    return fv, complete, areas


def _restore(backup: Path, target: Path) -> None:
    """Restore ``target`` from ``backup``; a failed h5py close can hold the file briefly."""
    import gc

    for attempt in range(5):
        try:
            shutil.copy2(backup, target)
            backup.unlink(missing_ok=True)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.5 * (attempt + 1))
    raise RustPreprocessError(f"could not restore {target} from its backup {backup}; restore it manually")


def _attribute_snapshot(path: Path) -> Dict[str, bytes]:
    """``object@attribute`` -> stored type and raw value bytes, for every HDF object."""
    import h5py

    out: Dict[str, bytes] = {}
    with h5py.File(path, "r") as f:
        def rec(name, obj):
            for k in obj.attrs:
                aid = obj.attrs.get_id(k)
                a = np.asarray(obj.attrs[k])
                out[f"{name or '/'}@{k}"] = (str(aid.dtype).encode() + b"|" + str(a.shape).encode()
                                            + b"|" + a.tobytes())
        rec("", f)
        f.visititems(rec)
    return out


def _restamp_area(g, stamp: str) -> Dict[str, Any]:
    """Overwrite an area's existing ``Property Tables Last Computed`` in place.

    The attribute is written through its existing HDF5 attribute, so its
    stored type (fixed-length string size and padding) is unchanged. It is
    never created: an area without it is left without it.
    """
    import h5py

    if LAST_COMPUTED_ATTR not in g.attrs:
        return {"status": "absent", "note": "not present in the source; not created"}
    aid = g.attrs.get_id(LAST_COMPUTED_ATTR)
    tid = aid.get_type()
    if not isinstance(tid, h5py.h5t.TypeStringID) or tid.is_variable_str() or aid.shape not in ((), (1,)):
        return {"status": "kept", "note": f"stored as {aid.dtype} {aid.shape}, not a fixed-length string; kept"}
    size = tid.get_size()
    raw = stamp.encode("ascii")
    if len(raw) > size:
        return {"status": "kept", "note": f"stamp needs {len(raw)} bytes, stored type holds {size}; kept"}
    before = _decode(g.attrs[LAST_COMPUTED_ATTR])
    # Write with the stored type as the memory type: no string conversion, so
    # the bytes land as given. Native stores 18 characters in an 18-byte
    # NULLTERM type (no terminator); a NULLPAD-to-NULLTERM conversion would
    # truncate the last character.
    aid.write(np.array(raw.ljust(size, b"\x00"), dtype=f"S{size}").reshape(aid.shape), mtype=tid)
    return {"status": "restamped", "before": before, "after": stamp}


def write_bundle(
    geom_hdf: Path,
    bundle: Path,
    *,
    restore_mtime: bool = True,
    restamp_currency: bool = True,
    stamp_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Write an engine bundle into ``geom_hdf`` in place, guarded, and return a receipt.

    Preconditions: a supported ``File Version``, ``Complete Geometry=True``,
    every target dataset already present with the same dtype (no dataset is
    created; one is resized only where its ``maxshape`` allows), and the
    engine's area attributes equal to the file's. Products are validated
    first. A full-file backup is restored on any failure, every write is
    read back exactly, and the receipt proves that no dataset outside the
    bundle changed.

    With ``restamp_currency`` (the default), each written area's existing
    ``Property Tables Last Computed`` is set to the write time in native's
    format, as native recomputation does. No other attribute is written or
    created; the receipt proves it with a before/after snapshot of every
    attribute in the file. ``Property Tables LC Hash`` is kept (it cannot be
    reproduced exactly) and reported under ``currency["not_restamped"]``.
    """
    import h5py

    geom_hdf = Path(geom_hdf)
    manifest, arrays = load_bundle(bundle)
    st = geom_hdf.stat()
    rec: Dict[str, Any] = {"geometry_hdf": str(geom_hdf), "mode": manifest.get("mode"), "areas": {}}
    by_area: Dict[str, Dict[str, np.ndarray]] = {}
    for (area, ds), a in arrays.items():
        by_area.setdefault(area, {})[ds] = a
    fv, complete, _ = geometry_preconditions(geom_hdf)
    if fv not in SUPPORTED_FILE_VERSIONS:
        raise RustPreprocessError(
            f"{geom_hdf.name}: File Version {fv!r} is not supported; the engine reproduces "
            f"{', '.join(SUPPORTED_FILE_VERSIONS)} only"
        )
    if not complete:
        raise RustPreprocessError(f"{geom_hdf.name}: Complete Geometry is not True")
    with h5py.File(geom_hdf, "r") as f:
        for am in manifest["areas"]:
            area = am["area"]
            g = f[f"{AREAS}/{area}"]
            bad = [k for k, v in am["attributes"].items() if k not in g.attrs or not _attr_equal(g.attrs[k], v)]
            if bad:
                raise RustPreprocessError(f"{area}: engine attributes differ from the file: {bad}")
            t = by_area.get(area, {})
            for ds, a in t.items():
                if ds not in g:
                    raise RustPreprocessError(f"{area}/{ds} does not exist; the write-back never creates datasets")
                d = g[ds]
                if d.dtype.newbyteorder("=") != a.dtype.newbyteorder("="):
                    raise RustPreprocessError(f"{area}/{ds}: dtype {a.dtype} != stored {d.dtype}")
                if d.shape != a.shape:
                    if d.ndim != a.ndim or d.shape[1:] != a.shape[1:]:
                        raise RustPreprocessError(f"{area}/{ds}: shape {a.shape} incompatible with {d.shape}")
                    if d.maxshape[0] is not None and d.maxshape[0] < a.shape[0]:
                        raise RustPreprocessError(f"{area}/{ds}: {a.shape[0]} rows exceed maxshape {d.maxshape}")
            rec["areas"][area] = {
                "validation": _validate_area(t, g),
                "attributes_verified": sorted(am["attributes"]),
                "datasets": sorted(t),
            }
    rec["sha256_before"] = _sha256(geom_hdf)
    before = _dataset_hashes(geom_hdf)
    attrs_before = _attribute_snapshot(geom_hdf)
    stamp = _native_timestamp(stamp_time) if restamp_currency else None
    currency: Dict[str, Any] = {
        "restamp_currency": restamp_currency,
        "stamp": stamp,
        "clock": "local time at write-back" if restamp_currency else None,
        "format": "DDMONYYYY HH:MM:SS, upper-case English month (native HEC-RAS 7.0.1)",
        "areas": {},
        "not_restamped": {},
    }
    backup = geom_hdf.with_name(geom_hdf.name + ".pre-rust.bak")
    shutil.copy2(geom_hdf, backup)
    try:
        with h5py.File(geom_hdf, "r+") as f:
            for area, t in by_area.items():
                g = f[f"{AREAS}/{area}"]
                for ds, a in t.items():
                    d = g[ds]
                    if d.shape != a.shape:
                        d.resize(a.shape)
                    d[...] = a.astype(d.dtype)
                if restamp_currency:
                    currency["areas"][area] = {LAST_COMPUTED_ATTR: _restamp_area(g, stamp)}
                kept = {k: _jsonable(g.attrs[k]) for k in NOT_RESTAMPED_ATTRS if k in g.attrs}
                if kept:
                    currency["not_restamped"][area] = kept
        with h5py.File(geom_hdf, "r") as f:
            for area, t in by_area.items():
                g = f[f"{AREAS}/{area}"]
                for ds, a in t.items():
                    if g[ds][()].tobytes() != a.astype(g[ds].dtype).tobytes():
                        raise RustPreprocessError(f"{area}/{ds} failed exact readback")
                st_ = currency["areas"].get(area, {}).get(LAST_COMPUTED_ATTR, {})
                if st_.get("status") == "restamped" and _decode(g.attrs[LAST_COMPUTED_ATTR]) != stamp:
                    raise RustPreprocessError(f"{area}/{LAST_COMPUTED_ATTR} failed exact readback")
        after = _dataset_hashes(geom_hdf)
        written = {f"{AREAS}/{a}/{ds}" for a, t in by_area.items() for ds in t}
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        untouched_changed = [k for k in changed if k not in written]
        if untouched_changed:
            raise RustPreprocessError(f"datasets outside the bundle changed: {untouched_changed[:5]}")
        attrs_after = _attribute_snapshot(geom_hdf)
        stamped = {f"{AREAS}/{a}@{LAST_COMPUTED_ATTR}" for a, v in currency["areas"].items()
                   if v[LAST_COMPUTED_ATTR]["status"] == "restamped"}
        attrs_changed = sorted(k for k in attrs_before.keys() | attrs_after.keys()
                               if attrs_before.get(k) != attrs_after.get(k))
        unexpected = [k for k in attrs_changed if k not in stamped]
        if unexpected:
            raise RustPreprocessError(f"attributes other than the currency stamps changed: {unexpected[:5]}")
        currency["attributes_changed"] = attrs_changed
        currency["attributes_tracked"] = len(attrs_before)
    except Exception:
        _restore(backup, geom_hdf)
        raise
    rec["currency"] = currency
    if currency["not_restamped"]:
        msg = (
            f"{geom_hdf.name}: {LC_HASH_ATTR} was kept from the source in "
            f"{sorted(currency['not_restamped'])}. Native HEC-RAS recomputes it from the "
            "land-cover inputs; the Rust write-back cannot reproduce it exactly and does not "
            "guess. HEC-RAS treats the tables as current only while the source's hash still "
            "matches its inputs; check the compute messages for 'Mesh property tables are current'."
        )
        logger.warning(msg)
        warnings.warn(msg, ExperimentalWarning, stacklevel=3)
    for area, v in currency["areas"].items():
        if v[LAST_COMPUTED_ATTR]["status"] != "restamped":
            logger.warning("%s/%s: %s", area, LAST_COMPUTED_ATTR, v[LAST_COMPUTED_ATTR]["note"])
    if restore_mtime:
        os.utime(geom_hdf, ns=(st.st_atime_ns, st.st_mtime_ns))
    rec.update(
        datasets_tracked=len(before),
        datasets_written=len(written),
        datasets_changed=changed,
        sha256_after=_sha256(geom_hdf),
        mtime_restored=restore_mtime,
        backup=str(backup),
    )
    return rec


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


@dataclass
class RustDatasetComparison:
    """Comparison of one dataset between a native and a Rust geometry HDF.

    Attributes:
        area: 2D flow area name.
        dataset: Dataset path below the area group.
        category: ``product`` (a preprocessing output) or ``input`` (topology
            and other datasets neither side should change).
        status: ``bitwise``, ``within_tolerance``, ``matches_other_native_run``,
            ``different``, ``missing_native`` or ``missing_rust``.
        passed: Whether the dataset counts as equivalent.
        values: Number of values compared.
        n_different: Values that are not bitwise equal.
        max_abs_diff: Largest absolute difference (NaN if not numeric).
        max_ulp: Largest float32 units-in-the-last-place distance (floats only).
        id_kind: ``cell``, ``face``, ``facepoint`` or ``row``.
        n_ids_different: Cells, faces or face points with any difference.
        ids_different: The first differing IDs (up to the report limit).
        tolerance: Absolute tolerance applied (``None`` = bitwise).
        labels: Known native behaviours that bear on this dataset.
    """

    area: str
    dataset: str
    category: str
    status: str
    passed: bool
    dtype: str = ""
    shape_native: Tuple[int, ...] = ()
    shape_rust: Tuple[int, ...] = ()
    values: int = 0
    n_different: int = 0
    max_abs_diff: float = 0.0
    max_ulp: int = 0
    id_kind: str = "row"
    n_ids_different: int = 0
    ids_different: List[int] = field(default_factory=list)
    tolerance: Optional[float] = None
    labels: List[str] = field(default_factory=list)

    @property
    def bitwise(self) -> bool:
        return self.status == "bitwise"


def _ordered_f32(a: np.ndarray) -> np.ndarray:
    b = np.ascontiguousarray(a, dtype=np.float32).view(np.int32).astype(np.int64)
    return np.where(b < 0, np.int64(-(2**31)) - b, b)


def _value_diffs(a: np.ndarray, b: np.ndarray) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """Per-element (not bitwise equal, abs diff, ulp or None) for same-shaped arrays."""
    if a.dtype.kind == "f" and b.dtype.kind == "f":
        a64, b64 = a.astype(np.float64), b.astype(np.float64)
        both_nan = np.isnan(a64) & np.isnan(b64)
        if a.dtype == np.float32 and b.dtype == np.float32:
            neq = np.ascontiguousarray(a).view(np.int32) != np.ascontiguousarray(b).view(np.int32)
            ulp = np.where(both_nan, 0, np.abs(_ordered_f32(a) - _ordered_f32(b)))
        elif a.dtype == b.dtype and a.dtype.itemsize in (2, 4, 8):
            iv = np.dtype(f"i{a.dtype.itemsize}")
            neq = np.ascontiguousarray(a).view(iv) != np.ascontiguousarray(b).view(iv)
            ulp = None
        else:
            neq = a64 != b64
            ulp = None
        neq = np.asarray(neq) & ~both_nan
        diff = np.where(both_nan, 0.0, np.abs(a64 - b64))
        diff = np.where(np.isnan(diff), np.inf, diff)
        return neq, diff, ulp
    if a.dtype.kind in "iub" and b.dtype.kind in "iub":
        neq = a != b
        return neq, np.abs(a.astype(np.float64) - b.astype(np.float64)), None
    # Strings, compounds: bytes only.
    flat_a = a.reshape(a.shape[0], -1) if a.ndim else a.reshape(1, -1)
    flat_b = b.reshape(b.shape[0], -1) if b.ndim else b.reshape(1, -1)
    neq = np.array([x.tobytes() != y.tobytes() for x, y in zip(flat_a, flat_b)])
    return neq, np.where(neq, np.inf, 0.0), None


def _id_kind(name: str, rows: int, counts: Mapping[str, int]) -> str:
    leaf = name.rsplit("/", 1)[-1]
    if leaf.startswith("FacePoints"):
        return "facepoint"
    if leaf.startswith("Faces") or leaf.startswith("Face Center"):
        return "face"
    if leaf.startswith("Cells") or leaf.startswith("Cell Center"):
        return "cell"
    if "/" in name:  # family parameters: one value per (interior) cell
        return "cell"
    for kind in ("cell", "face", "facepoint"):
        if counts.get(kind) == rows:
            return kind
    return "row"


def _tolerance_for(tolerance: Union[None, float, Mapping[str, float]], dataset: str) -> Optional[float]:
    if tolerance is None:
        return None
    if isinstance(tolerance, Mapping):
        if dataset in tolerance:
            return float(tolerance[dataset])
        leaf = dataset.rsplit("/", 1)[-1]
        return float(tolerance[leaf]) if leaf in tolerance else (
            float(tolerance["*"]) if "*" in tolerance else None
        )
    return float(tolerance)


def _finish(cmp: RustDatasetComparison, neq_rows: np.ndarray, neq: np.ndarray, diff: np.ndarray,
            ulp: Optional[np.ndarray], structural: np.ndarray, max_ids: int) -> RustDatasetComparison:
    """Fill difference statistics. ``neq_rows`` / ``structural`` are per owner ID."""
    cmp.n_different = int(np.count_nonzero(neq))
    finite = diff[neq] if cmp.n_different else np.zeros(0)
    cmp.max_abs_diff = float(finite.max()) if finite.size else 0.0
    if ulp is not None and cmp.n_different:
        cmp.max_ulp = int(ulp[neq].max())
    bad = neq_rows | structural
    ids = np.flatnonzero(bad)
    cmp.n_ids_different = int(ids.size)
    cmp.ids_different = [int(i) for i in ids[:max_ids]]
    if not bad.any():
        cmp.status, cmp.passed = "bitwise", True
    elif cmp.tolerance is not None and not structural.any() and cmp.max_abs_diff <= cmp.tolerance:
        cmp.status, cmp.passed = "within_tolerance", True
    else:
        cmp.status, cmp.passed = "different", False
    return cmp


def _compare_plain(area: str, name: str, category: str, a: np.ndarray, b: np.ndarray,
                   tol: Optional[float], counts: Mapping[str, int], max_ids: int) -> RustDatasetComparison:
    cmp = RustDatasetComparison(
        area=area, dataset=name, category=category, status="", passed=False,
        dtype=str(b.dtype), shape_native=tuple(a.shape), shape_rust=tuple(b.shape),
        values=int(b.size), tolerance=tol,
    )
    rows = a.shape[0] if a.ndim else 1
    cmp.id_kind = _id_kind(name, rows, counts)
    if a.shape != b.shape or a.dtype.kind != b.dtype.kind:
        cmp.status, cmp.passed = "different", False
        cmp.n_different = max(a.size, b.size)
        cmp.max_abs_diff = math.inf
        n = max(a.shape[0] if a.ndim else 1, b.shape[0] if b.ndim else 1)
        cmp.n_ids_different = n
        cmp.ids_different = list(range(min(n, max_ids)))
        return cmp
    if a.ndim == 0:
        a, b = a.reshape(1), b.reshape(1)
    neq, diff, ulp = _value_diffs(a, b)
    neq = np.asarray(neq).reshape(a.shape[0], -1)
    diff = diff.reshape(a.shape[0], -1)
    ulp = ulp.reshape(a.shape[0], -1) if ulp is not None else None
    neq_rows = neq.any(axis=1)
    return _finish(cmp, neq_rows, neq, diff, ulp, np.zeros(a.shape[0], bool), max_ids)


def _compare_packed(area: str, name: str, category: str, info_a: np.ndarray, vals_a: np.ndarray,
                    info_b: np.ndarray, vals_b: np.ndarray, tol: Optional[float],
                    counts: Mapping[str, int], max_ids: int) -> RustDatasetComparison:
    """Compare an Info/Values ``Values`` table per owner (face or cell)."""
    cmp = RustDatasetComparison(
        area=area, dataset=name, category=category, status="", passed=False,
        dtype=str(vals_b.dtype), shape_native=tuple(vals_a.shape), shape_rust=tuple(vals_b.shape),
        values=int(vals_b.size), tolerance=tol,
    )
    cmp.id_kind = _id_kind(name, info_a.shape[0], counts)
    if info_a.shape != info_b.shape or vals_a.shape[1:] != vals_b.shape[1:]:
        return _compare_plain(area, name, category, vals_a, vals_b, tol, counts, max_ids)
    ca, cb = info_a[:, 1].astype(np.int64), info_b[:, 1].astype(np.int64)
    sa, sb = info_a[:, 0].astype(np.int64), info_b[:, 0].astype(np.int64)
    structural = ca != cb
    same = np.flatnonzero(~structural)
    lengths = ca[same]
    total = int(lengths.sum())
    within = np.arange(total) - np.repeat(np.cumsum(lengths) - lengths, lengths)
    ia = np.repeat(sa[same], lengths) + within
    ib = np.repeat(sb[same], lengths) + within
    owner = np.repeat(same, lengths)
    a, b = vals_a[ia], vals_b[ib]
    neq, diff, ulp = _value_diffs(a, b)
    neq = np.asarray(neq).reshape(total, -1)
    diff = diff.reshape(total, -1)
    ulp = ulp.reshape(total, -1) if ulp is not None else None
    neq_rows = np.zeros(info_a.shape[0], bool)
    if total:
        neq_rows[owner[neq.any(axis=1)]] = True
    cmp.values = int(vals_b.size)
    cmp = _finish(cmp, neq_rows, neq, diff, ulp, structural, max_ids)
    if structural.any():
        cmp.n_different += int(np.abs(ca - cb)[structural].sum()) * max(1, vals_a.shape[1] if vals_a.ndim > 1 else 1)
    return cmp


def _is_product(name: str) -> bool:
    return "/" in name or name in PRODUCT_DATASETS


def _read_area(f, area: str) -> Dict[str, np.ndarray]:
    import h5py

    out: Dict[str, np.ndarray] = {}
    g = f[f"{AREAS}/{area}"]

    def visit(name, obj):
        if isinstance(obj, h5py.Dataset):
            out[name] = obj[()]
    g.visititems(visit)
    return out


def _area_counts(t: Mapping[str, np.ndarray]) -> Dict[str, int]:
    c = {}
    for kind, ds in (("cell", "Cells Face and Orientation Info"), ("face", "Faces FacePoint Indexes"),
                     ("facepoint", "FacePoints Coordinate")):
        if ds in t:
            c[kind] = int(t[ds].shape[0])
    return c


def compare_area_arrays(
    area: str,
    native: Mapping[str, np.ndarray],
    rust: Mapping[str, np.ndarray],
    *,
    tolerance: Union[None, float, Mapping[str, float]] = None,
    datasets: Optional[Sequence[str]] = None,
    max_ids: int = 20,
) -> List[RustDatasetComparison]:
    """Compare the datasets of one 2D area, given as ``{name: array}`` mappings.

    ``Values`` datasets of an ``Info``/``Values`` pair are compared per owner,
    so a face whose profile gains a point is reported as that face. Integer
    datasets are always compared exactly; ``tolerance`` (absolute, in the
    dataset's units) applies to floating-point values only. A mapping
    tolerance is looked up by dataset path, then leaf name, then ``"*"``.
    """
    counts = _area_counts(native) or _area_counts(rust)
    names = sorted(set(native) | set(rust)) if datasets is None else list(datasets)
    out: List[RustDatasetComparison] = []
    for name in names:
        category = "product" if _is_product(name) else "input"
        if name not in native or name not in rust:
            status = "missing_native" if name not in native else "missing_rust"
            out.append(RustDatasetComparison(area=area, dataset=name, category=category, status=status, passed=False))
            continue
        a, b = np.asarray(native[name]), np.asarray(rust[name])
        tol = _tolerance_for(tolerance, name) if a.dtype.kind == "f" else None
        info = name[: -len("Values")] + "Info" if name.endswith(" Values") else None
        if info and info in native and info in rust and a.ndim >= 1:
            out.append(_compare_packed(area, name, category, np.asarray(native[info]), a,
                                       np.asarray(rust[info]), b, tol, counts, max_ids))
        else:
            out.append(_compare_plain(area, name, category, a, b, tol, counts, max_ids))
    return out


def compare_geometry_hdfs(
    native_hdf: Path,
    rust_hdf: Path,
    *,
    tolerance: Union[None, float, Mapping[str, float]] = None,
    max_ids: int = 20,
) -> Tuple[List[RustDatasetComparison], Dict[str, Dict[str, Any]]]:
    """Compare every dataset of every 2D area of two geometry HDFs.

    Returns the comparisons and, per area, the area-attribute differences
    (informational; the Rust write-back never writes attributes).
    """
    import h5py

    comparisons: List[RustDatasetComparison] = []
    attr_diffs: Dict[str, Dict[str, Any]] = {}
    with h5py.File(native_hdf, "r") as fn, h5py.File(rust_hdf, "r") as fr:
        an = set(fn[AREAS].keys()) if AREAS in fn else set()
        ar = set(fr[AREAS].keys()) if AREAS in fr else set()
        areas = sorted(a for a in an | ar if isinstance((fn.get(f"{AREAS}/{a}") or fr.get(f"{AREAS}/{a}")), h5py.Group))
        for area in areas:
            if area not in an or area not in ar:
                comparisons.append(RustDatasetComparison(
                    area=area, dataset="(area group)", category="input",
                    status="missing_native" if area not in an else "missing_rust", passed=False))
                continue
            comparisons += compare_area_arrays(
                area, _read_area(fn, area), _read_area(fr, area), tolerance=tolerance, max_ids=max_ids)
            gn, gr = fn[f"{AREAS}/{area}"].attrs, fr[f"{AREAS}/{area}"].attrs
            diffs = {}
            for k in sorted(set(gn) | set(gr)):
                vn, vr = gn.get(k), gr.get(k)
                if vn is None or vr is None or np.asarray(vn).tobytes() != np.asarray(vr).tobytes():
                    diffs[k] = {"native": _jsonable(vn), "rust": _jsonable(vr)}
            if diffs:
                attr_diffs[area] = diffs
    return comparisons, attr_diffs


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (bytes, np.bytes_)):
        return _decode(v)
    a = np.asarray(v)
    if a.dtype == np.uint8 and a.size > 1:
        return a.tobytes().hex()
    if a.dtype.kind == "S":
        return [_decode(x) for x in a.ravel()] if a.size > 1 else _decode(a)
    if a.dtype.names:
        return str(a.tolist())
    if a.size == 1:
        x = a.ravel()[0].item()
        return None if isinstance(x, float) and not math.isfinite(x) else x
    return [None if isinstance(x, float) and not math.isfinite(x) else x for x in a.ravel().tolist()]


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class RustPreprocessResult:
    """Result of :func:`compute_rust_experimental`.

    Attributes:
        geometry_hdf: The geometry HDF that now holds the Rust products.
        source_geometry_hdf: The geometry HDF the engine read.
        in_place: Whether the source itself was written.
        engine: Engine provenance.
        options: Engine options (mode, sort, units, threads).
        command: The exact engine command.
        engine_report: The engine's JSON report (per-area timings and counts).
        writeback: Write-back receipt (validation, dataset hashes, SHA-256).
        currency: Currency-attribute provenance: whether
            ``Property Tables Last Computed`` was restamped, the stamp, each
            area's before/after value, the attributes kept from the source
            (``Property Tables LC Hash``) and the attributes that changed.
        source_sha256: SHA-256 of the source geometry HDF before the run.
        elapsed_seconds: Wall time of the engine run and write-back.
        started_utc: ISO-8601 start time.
    """

    geometry_hdf: Path
    source_geometry_hdf: Path
    in_place: bool
    engine: RustEngineInfo
    options: Dict[str, Any]
    command: List[str]
    engine_report: Dict[str, Any]
    writeback: Dict[str, Any]
    source_sha256: str
    elapsed_seconds: float
    started_utc: str
    currency: Dict[str, Any] = field(default_factory=dict)
    experimental: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "ras-commander-rust-preprocess/1",
            "experimental": True,
            "geometry_hdf": str(self.geometry_hdf),
            "source_geometry_hdf": str(self.source_geometry_hdf),
            "in_place": self.in_place,
            "engine": self.engine.to_dict(),
            "options": dict(self.options),
            "command": list(self.command),
            "source_sha256": self.source_sha256,
            "elapsed_seconds": self.elapsed_seconds,
            "started_utc": self.started_utc,
            "currency": self.currency,
            "writeback": self.writeback,
            "engine_report": self.engine_report,
        }


@dataclass
class RustEquivalenceReport:
    """Result of :func:`validate_rust_equivalence`.

    ``verdict`` is ``equivalent`` (every dataset bitwise, within tolerance,
    or equal to one of several disagreeing native runs), ``not equivalent``,
    or ``refused`` (the engine refused the input; nothing was compared).
    """

    verdict: str
    project_folder: Path
    geometry: str
    hecras_version: str
    engine: Optional[RustEngineInfo]
    options: Dict[str, Any]
    tolerance: Union[None, float, Dict[str, float]]
    comparisons: List[RustDatasetComparison] = field(default_factory=list)
    native_runs: int = 0
    native_nondeterminism: List[Dict[str, Any]] = field(default_factory=list)
    corrected_departure: List[RustDatasetComparison] = field(default_factory=list)
    attribute_differences: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    engine_compare: Optional[Dict[str, Any]] = None
    labels: Dict[str, str] = field(default_factory=dict)
    refusal: Optional[str] = None
    work_dir: Optional[Path] = None
    native_geometry_hdfs: List[Path] = field(default_factory=list)
    rust_geometry_hdf: Optional[Path] = None
    report_json: Optional[Path] = None
    report_markdown: Optional[Path] = None
    timings: Dict[str, float] = field(default_factory=dict)
    started_utc: str = ""
    notes: List[str] = field(default_factory=list)
    currency: Dict[str, Any] = field(default_factory=dict)
    stage2_coverage: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def equivalent(self) -> bool:
        return self.verdict == "equivalent"

    def failures(self) -> List[RustDatasetComparison]:
        return [c for c in self.comparisons if not c.passed]

    def to_dataframe(self):
        """One row per compared dataset (schema ``rust_preprocess_equivalence``)."""
        import pandas as pd

        cols = ["area", "dataset", "category", "status", "passed", "dtype", "values", "n_different",
                "max_abs_diff", "max_ulp", "id_kind", "n_ids_different", "ids_different", "tolerance", "labels"]
        rows = [{k: getattr(c, k) for k in cols} for c in self.comparisons]
        return pd.DataFrame(rows, columns=cols)

    def to_dict(self) -> Dict[str, Any]:
        def cmp(c: RustDatasetComparison) -> Dict[str, Any]:
            d = asdict(c)
            d["max_abs_diff"] = None if not math.isfinite(d["max_abs_diff"]) else d["max_abs_diff"]
            d["shape_native"], d["shape_rust"] = list(c.shape_native), list(c.shape_rust)
            return d

        return {
            "schema": "ras-commander-rust-preprocess-equivalence/1",
            "experimental": True,
            "verdict": self.verdict,
            "project_folder": str(self.project_folder),
            "geometry": self.geometry,
            "hecras_version": self.hecras_version,
            "engine": self.engine.to_dict() if self.engine else None,
            "options": self.options,
            "tolerance": self.tolerance,
            "native_runs": self.native_runs,
            "refusal": self.refusal,
            "summary": self.summary(),
            "comparisons": [cmp(c) for c in self.comparisons],
            "native_nondeterminism": self.native_nondeterminism,
            "corrected_departure": [cmp(c) for c in self.corrected_departure],
            "attribute_differences": self.attribute_differences,
            "currency": self.currency,
            "stage2_coverage": self.stage2_coverage,
            "engine_compare": self.engine_compare,
            "labels": self.labels,
            "notes": self.notes,
            "work_dir": str(self.work_dir) if self.work_dir else None,
            "native_geometry_hdfs": [str(p) for p in self.native_geometry_hdfs],
            "rust_geometry_hdf": str(self.rust_geometry_hdf) if self.rust_geometry_hdf else None,
            "timings": self.timings,
            "started_utc": self.started_utc,
        }

    def summary(self) -> Dict[str, Any]:
        by = {}
        for c in self.comparisons:
            by[c.status] = by.get(c.status, 0) + 1
        products = [c for c in self.comparisons if c.category == "product"]
        return {
            "datasets": len(self.comparisons),
            "product_datasets": len(products),
            "by_status": by,
            "failed": [f"{c.area}/{c.dataset}" for c in self.failures()],
        }

    def to_markdown(self) -> str:
        s = self.summary()
        lines = [
            "# Experimental Rust geometry preprocessing: equivalence report",
            "",
            "> **Experimental.** This report compares the Rust engine with native HEC-RAS "
            "preprocessing on this model only. It is evidence for this model, engine build and "
            "HEC-RAS version; it does not qualify other models, and it is not a hydraulic review.",
            "",
            f"- **Verdict:** **{self.verdict}**",
            f"- Project: `{self.project_folder}`",
            f"- Geometry: `{self.geometry}`",
            f"- HEC-RAS (native side): {self.hecras_version}, via `RasMap.recompute_property_tables`",
        ]
        if self.engine:
            lines.append(f"- Engine: `{self.engine.version}`, sha256 `{self.engine.sha256}`")
        lines += [
            f"- Engine options: `{json.dumps(self.options)}`",
            f"- Tolerance: {'bitwise' if self.tolerance is None else json.dumps(self.tolerance)}",
            f"- Native runs: {self.native_runs}",
            f"- Started (UTC): {self.started_utc}",
            "",
        ]
        if self.refusal:
            lines += ["## Refused", "", "The engine refused this input; nothing was compared:", "",
                      "```text", self.refusal, "```", ""]
        if self.comparisons:
            lines += [
                f"## Datasets ({s['datasets']} compared, {s['product_datasets']} products)", "",
                "| Area | Dataset | Kind | Status | Values | Differing | Max abs | Max ulp | IDs differing | Labels |",
                "|---|---|---|---|---:|---:|---:|---:|---|---|",
            ]
            for c in self.comparisons:
                ids = f"{c.n_ids_different} {c.id_kind}" + (
                    f" ({', '.join(map(str, c.ids_different[:8]))}{', …' if c.n_ids_different > 8 else ''})"
                    if c.n_ids_different else "")
                mad = "inf" if not math.isfinite(c.max_abs_diff) else f"{c.max_abs_diff:.6g}"
                lines.append(
                    f"| {c.area} | {c.dataset} | {c.category} | {c.status} | {c.values:,} | "
                    f"{c.n_different:,} | {mad} | {c.max_ulp} | {ids if c.n_ids_different else '—'} | "
                    f"{', '.join(c.labels) or '—'} |"
                )
            lines.append("")
        if self.native_nondeterminism:
            lines += ["## Native run-to-run differences", "",
                      "Native runs on identical copies disagreed on these datasets:", ""]
            for d in self.native_nondeterminism:
                lines.append(f"- run {d['run']} vs run 1: `{d['area']}/{d['dataset']}`, "
                             f"{d['n_ids_different']} {d['id_kind']} (first: {d['ids_different'][:8]})")
            lines.append("")
        if self.corrected_departure:
            lines += ["## Corrected-mode departure from native (informational)", "",
                      "Corrected mode fixes native defects D-4 and D-5; it is expected to differ "
                      "wherever those defects act. These rows do not affect the verdict.", "",
                      "| Area | Dataset | Status | Differing values | IDs differing |",
                      "|---|---|---|---:|---:|"]
            for c in self.corrected_departure:
                lines.append(f"| {c.area} | {c.dataset} | {c.status} | {c.n_different:,} | "
                             f"{c.n_ids_different} {c.id_kind} |")
            lines.append("")
        if self.attribute_differences:
            lines += ["## Area attribute differences (informational)", "",
                      f"Both sides stamp `{LAST_COMPUTED_ATTR}` with their own completion time, so "
                      f"it differs by the time between runs. The Rust write-back keeps `{LC_HASH_ATTR}` "
                      "from the staged input, because the native hash cannot be reproduced exactly; "
                      "native rewrites it when its input-derived value differs.", ""]
            for area, diffs in self.attribute_differences.items():
                for k, v in diffs.items():
                    why = {LAST_COMPUTED_ATTR: " (timestamp; expected)",
                           LC_HASH_ATTR: " (kept from input by the Rust write-back; not reproduced)"}.get(k, "")
                    lines.append(f"- `{area}` `{k}`: native `{v['native']}`, Rust `{v['rust']}`{why}")
            lines.append("")
        if any(c.get("present") for c in self.stage2_coverage.values()):
            lines += ["## Stage 2 infiltration and impervious coverage", "",
                      "Infiltration and Percent Impervious datasets are present. The engine's "
                      "`--compare` checks Stage 2 only through `Cells Center Manning's n`, so it does "
                      "**not** compare these arrays; that coverage arrives with the engine's "
                      "workstream P (in progress). The dataset table above compares the arrays the "
                      "engine computed. Arrays it did not compute keep the staged input and are listed "
                      "here as not compared.", ""]
            for area, c in self.stage2_coverage.items():
                if not c.get("present"):
                    continue
                lines.append(f"- `{area}`: compared (engine output) {len(c['compared'])}: "
                             f"{', '.join(f'`{d}`' for d in c['compared']) or 'none'}")
                lines.append(f"- `{area}`: **not compared** (not computed by the engine; carried from "
                             f"the input) {len(c['not_compared'])}: "
                             f"{', '.join(f'`{d}`' for d in c['not_compared']) or 'none'}")
                lines.append(f"- `{area}`: engine `--compare`: not covered ({len(c['present'])} datasets)")
            lines.append("")
        if self.engine_compare:
            lines += ["## Engine `--compare` against native run 1", "",
                      "The engine's own per-stage parity check, run on the native output:", ""]
            for area, parity in self.engine_compare.items():
                lines.append(f"- `{area}`: " + "; ".join(_parity_summary(parity or {})))
            lines.append("")
        if self.labels:
            lines += ["## Known native behaviours referenced", ""]
            lines += [f"- **{k}.** {v}" for k, v in self.labels.items()]
            lines.append("")
        if self.notes:
            lines += ["## Notes", ""] + [f"- {n}" for n in self.notes] + [""]
        lines += ["## Files", ""]
        if self.work_dir:
            lines.append(f"- Work folder: `{self.work_dir}`")
        for p in self.native_geometry_hdfs:
            lines.append(f"- Native geometry HDF: `{p}`")
        if self.rust_geometry_hdf:
            lines.append(f"- Rust geometry HDF: `{self.rust_geometry_hdf}`")
        if self.timings:
            lines += ["", "## Timings (s)", ""] + [f"- {k}: {v:.1f}" for k, v in self.timings.items()]
        return "\n".join(lines) + "\n"

    def write(self, folder: Path, stem: str = "rust_equivalence_report") -> Tuple[Path, Path]:
        """Write the JSON and markdown reports into ``folder`` and return both paths."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.report_json = folder / f"{stem}.json"
        self.report_markdown = folder / f"{stem}.md"
        self.report_json.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        self.report_markdown.write_text(self.to_markdown(), encoding="utf-8")
        return self.report_json, self.report_markdown


def _parity_summary(parity: Mapping[str, Any]) -> List[str]:
    """One phrase per stage of an engine ``--compare`` parity block."""
    out = []
    s1 = parity.get("stage1") or {}
    if s1:
        out.append(f"stage 1 faces bitwise {s1.get('bitwise_faces_all', s1.get('bitwise_faces'))}/{s1.get('faces')}")
    s2 = parity.get("stage2_cell_n") or {}
    if "values" in s2:
        out.append(f"cell n bitwise {s2.get('bitwise')}/{s2.get('values')}")
    s3 = parity.get("stage3") or {}
    if "faces" in s3:
        out.append(f"stage 3 faces bitwise {s3.get('faces_bitwise')}/{s3.get('faces')}")
    s4 = (parity.get("stage4") or {}).get("volume_all") or {}
    if "cells" in s4:
        out.append(f"stage 4 cells bitwise {s4.get('bitwise_cells')}/{s4.get('cells')}")
    return out or ["no parity data"]


# ---------------------------------------------------------------------------
# Compute (experimental)
# ---------------------------------------------------------------------------


def _warn_experimental(what: str) -> None:
    warnings.warn(
        f"{what} uses the EXPERIMENTAL Rust geometry preprocessor. It is not a drop-in "
        "replacement for native HEC-RAS preprocessing: prove equivalence on your own model "
        "with GeomPreprocessor.validate_rust_equivalence() before any production use.",
        ExperimentalWarning,
        stacklevel=3,
    )


def _as_geometry_hdf(geom: Union[str, Path]) -> Path:
    p = Path(geom)
    if p.suffix.lower() != ".hdf":
        p = p.with_name(p.name + ".hdf")
    return p


def compute_rust_experimental(
    geom: Union[str, Path],
    *,
    engine_exe: Union[str, Path, None] = None,
    out_path: Union[str, Path, None] = None,
    in_place: bool = False,
    threads: Optional[int] = None,
    native_compatible: bool = True,
    sort: str = "introsort",
    units: Optional[str] = None,
    restore_mtime: bool = True,
    restamp_currency: bool = True,
    timeout: Optional[float] = DEFAULT_ENGINE_TIMEOUT,
    keep_bundle: bool = False,
) -> RustPreprocessResult:
    """Implementation of :meth:`GeomPreprocessor.compute_rust_experimental`."""
    _warn_experimental("compute_rust_experimental()")
    src = _as_geometry_hdf(geom).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"geometry HDF not found: {src}")
    if in_place and out_path is not None:
        raise ValueError("give out_path or in_place=True, not both")
    if not in_place and out_path is None:
        raise ValueError(
            "out_path is required unless in_place=True; the source geometry HDF is never "
            "modified unless asked explicitly"
        )
    target = src if in_place else Path(out_path).resolve()
    if not in_place:
        if target == src:
            raise ValueError("out_path is the source geometry HDF; pass in_place=True to write it")
        if target.exists():
            raise FileExistsError(f"out_path exists: {target}")
    fv, complete, areas = geometry_preconditions(src)
    if fv not in SUPPORTED_FILE_VERSIONS:
        raise RustPreprocessError(
            f"{src.name}: File Version {fv!r} is not supported. Convert the geometry with native "
            f"HEC-RAS {SUPPORTED_FILE_VERSIONS[0].split()[1]} first (for example "
            "GeomPreprocessor.run_geometry_preprocessor on a project copy)."
        )
    if not complete:
        raise RustPreprocessError(f"{src.name}: Complete Geometry is not True; run native geometry preprocessing first")
    if not areas:
        raise RustPreprocessError(f"{src.name}: no 2D flow areas; the Rust preprocessor is 2D only")
    options = _engine_options(native_compatible, sort, units, threads)
    engine = resolve_engine(engine_exe)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    source_sha = _sha256(src)
    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="ras-preprocess-bundle-", dir=target.parent))
    bundle = work / "bundle"
    try:
        report, cmd = run_engine(engine, src, out_bundle=bundle, options=options, timeout=timeout)
        if not in_place:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        try:
            receipt = write_bundle(target, bundle, restore_mtime=restore_mtime,
                                   restamp_currency=restamp_currency)
        except Exception:
            if not in_place:
                target.unlink(missing_ok=True)
            raise
        if not in_place:
            Path(receipt["backup"]).unlink(missing_ok=True)
            receipt["backup"] = None
    finally:
        if keep_bundle:
            logger.info("Kept engine bundle at %s", bundle)
        else:
            shutil.rmtree(work, ignore_errors=True)
    if keep_bundle:
        receipt["bundle"] = str(bundle)
    return RustPreprocessResult(
        geometry_hdf=target,
        source_geometry_hdf=src,
        in_place=in_place,
        engine=engine,
        options={**options, "restamp_currency": restamp_currency},
        command=cmd,
        engine_report=report,
        writeback=receipt,
        currency=receipt.get("currency", {}),
        source_sha256=source_sha,
        elapsed_seconds=time.perf_counter() - t0,
        started_utc=started,
    )


# ---------------------------------------------------------------------------
# Equivalence harness
# ---------------------------------------------------------------------------


_COPY_IGNORE = shutil.ignore_patterns(
    "*.p[0-9][0-9].hdf", "*.p[0-9][0-9].tmp.hdf", "*.bak", "*.pre-rust.bak", "*.dss.lock",
    "*.computeMsgs.txt", "*.log",
)


def _resolve_project(project: Union[str, Path]) -> Tuple[Path, Optional[Path]]:
    p = Path(project).resolve()
    if p.is_file() and p.suffix.lower() == ".prj":
        return p.parent, p
    if p.is_dir():
        return p, None
    raise FileNotFoundError(f"project folder or .prj not found: {project}")


def _resolve_geom(ras_obj, geom: Union[str, int, Path]) -> Tuple[str, Path]:
    """Return (geometry number, plain-text geometry path) in the initialized project."""
    folder = Path(ras_obj.project_folder)
    name = ras_obj.project_name
    if isinstance(geom, Path) or (isinstance(geom, str) and ("." in geom or os.sep in geom or "/" in geom)):
        g = Path(geom)
        text = g.name[:-4] if g.name.lower().endswith(".hdf") else g.name
        suffix = text.rsplit(".", 1)[-1]
        if not (suffix[:1].lower() == "g" and suffix[1:].isdigit()):
            raise ValueError(f"not a geometry file: {geom}")
        return suffix[1:].zfill(2), folder / text
    num = str(geom).strip().lower().removeprefix("g").zfill(2)
    return num, folder / f"{name}.g{num}"


def _plan_for_geom(ras_obj, geom_num: str, plan_number: Optional[str]) -> Optional[str]:
    if plan_number is not None:
        return str(plan_number).zfill(2)
    df = ras_obj.plan_df
    for col in ("geometry_number", "Geom File"):
        if col in df.columns:
            hits = df[df[col].astype(str).str.lower().str.removeprefix("g").str.zfill(2) == geom_num]
            if len(hits):
                return str(hits.iloc[0]["plan_number"]).zfill(2)
    return None


def _poison_products(geom_hdf: Path) -> List[str]:
    """Overwrite stored float products with NaN so the engine cannot use them.

    The engine documents that it reads no stored Stage 1-4 product. This
    makes that a tested fact for each harness run: any product the engine did
    read would turn its output non-finite and fail validation, and any product
    it did not rewrite stays NaN and is reported as a difference.
    """
    import h5py

    poisoned = []
    with h5py.File(geom_hdf, "r+") as f:
        for area, g in f[AREAS].items():
            if not isinstance(g, h5py.Group):
                continue

            def visit(name, obj):
                if isinstance(obj, h5py.Dataset) and _is_product(name) and obj.dtype.kind == "f" and obj.size:
                    obj[...] = np.nan
                    poisoned.append(f"{area}/{name}")
            g.visititems(visit)
    return poisoned


def _nan_masks(geom_hdf: Path) -> Dict[str, np.ndarray]:
    """NaN masks of the float products (ghost cells carry NaN by convention)."""
    import h5py

    out: Dict[str, np.ndarray] = {}
    with h5py.File(geom_hdf, "r") as f:
        for area, g in f[AREAS].items():
            if not isinstance(g, h5py.Group):
                continue

            def visit(name, obj):
                if isinstance(obj, h5py.Dataset) and _is_product(name) and obj.dtype.kind == "f":
                    out[f"{area}/{name}"] = np.isnan(obj[()])
            g.visititems(visit)
    return out


def _unrecomputed(geom_hdf: Path, poisoned: Sequence[str], before_nan: Mapping[str, np.ndarray]) -> List[str]:
    """Poisoned datasets that still hold NaN where the unpoisoned input did not.

    Native preprocessing reports success when it skips an area, keeping its old
    tables (the stale-success failure). Poisoning the copy turns that into
    detectable NaN instead of a silent reuse of the input tables.
    """
    import h5py

    stale = []
    with h5py.File(geom_hdf, "r") as f:
        for item in poisoned:
            area, name = item.split("/", 1)
            v = f[f"{AREAS}/{area}/{name}"][()]
            nan = np.isnan(v)
            ref = before_nan.get(item)
            extra = nan if ref is None or ref.shape != nan.shape else nan & ~ref
            if extra.any():
                stale.append(f"{item} ({int(extra.sum())} values)")
    return stale


def _long_faces(t: Mapping[str, np.ndarray]) -> np.ndarray:
    info = t.get("Faces Profile Info")
    if info is None or not len(info):
        return np.zeros(0, int)
    return np.flatnonzero(np.asarray(info)[:, 1] > LONG_FACE_POINTS)


def validate_rust_equivalence(
    project: Union[str, Path],
    geom: Union[str, int, Path],
    *,
    work_dir: Union[str, Path],
    engine_exe: Union[str, Path, None] = None,
    hecras_version: str = "7.0.1",
    plan_number: Optional[str] = None,
    tolerance: Union[None, float, Mapping[str, float]] = None,
    native_repeats: int = 1,
    include_corrected: bool = False,
    engine_compare: bool = True,
    threads: Optional[int] = None,
    sort: str = "introsort",
    units: Optional[str] = None,
    isolate_inputs: bool = True,
    max_ids: int = 20,
    keep_work: bool = True,
    timeout: Optional[float] = DEFAULT_ENGINE_TIMEOUT,
) -> RustEquivalenceReport:
    """Implementation of :meth:`GeomPreprocessor.validate_rust_equivalence`."""
    from ..RasMap import RasMap
    from ..RasPrj import RasPrj, init_ras_project
    from .GeomPreprocessor import GeomPreprocessor

    _warn_experimental("validate_rust_equivalence()")
    if native_repeats < 1:
        raise ValueError("native_repeats must be >= 1")
    options = _engine_options(True, sort, units, threads)
    engine = resolve_engine(engine_exe)
    src_folder, _ = _resolve_project(project)
    work = Path(work_dir).resolve()
    if work == src_folder or src_folder in work.parents:
        raise ValueError("work_dir must be outside the source project folder")
    if work.exists() and any(work.iterdir()):
        raise FileExistsError(f"work_dir exists and is not empty: {work}")
    work.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    timings: Dict[str, float] = {}
    notes: List[str] = []
    t = time.perf_counter()

    def lap(key: str) -> None:
        nonlocal t
        timings[key] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()

    # 1. Stage: one copy of the project; the original is never written.
    staged = work / "staged"
    shutil.copytree(src_folder, staged, ignore=_COPY_IGNORE)
    sras = init_ras_project(staged, hecras_version, ras_object=RasPrj(), load_results_summary=False, hide_intro=True)
    geom_num, geom_text = _resolve_geom(sras, geom)
    if not geom_text.is_file():
        raise FileNotFoundError(f"geometry not found in the project: {geom_text.name}")
    g_hdf = _as_geometry_hdf(geom_text)
    fv = complete = None
    if g_hdf.is_file():
        fv, complete, _ = geometry_preconditions(g_hdf)
    if fv not in SUPPORTED_FILE_VERSIONS or not complete:
        plan = _plan_for_geom(sras, geom_num, plan_number)
        if plan is None:
            raise RustPreprocessError(
                f"{geom_text.name}: the geometry HDF needs native {hecras_version} conversion "
                f"(File Version {fv!r}, complete={complete}) and no plan uses this geometry; pass plan_number"
            )
        logger.info("Converting %s with native HEC-RAS %s (plan %s) on the staged copy", geom_text.name, hecras_version, plan)
        res = GeomPreprocessor.run_geometry_preprocessor(plan, ras_object=sras)
        if not res.success:
            raise RustPreprocessError(f"native conversion of {geom_text.name} failed: {res.error or res.first_error_line}")
        fv, complete, _ = geometry_preconditions(g_hdf)
        if fv not in SUPPORTED_FILE_VERSIONS or not complete:
            raise RustPreprocessError(
                f"{g_hdf.name} after native conversion: File Version {fv!r}, complete={complete}; "
                f"the engine reproduces {SUPPORTED_FILE_VERSIONS[0]} only")
        notes.append(f"The geometry HDF was converted with native HEC-RAS {hecras_version} "
                     f"(geometry-only compute of plan {plan}) before both sides ran.")
    lap("stage")
    staged_hdf = work / f"staged_{g_hdf.name}"
    shutil.copy2(g_hdf, staged_hdf)

    report = RustEquivalenceReport(
        verdict="not equivalent", project_folder=src_folder, geometry=g_hdf.name,
        hecras_version=hecras_version, engine=engine, options=options,
        tolerance=dict(tolerance) if isinstance(tolerance, Mapping) else tolerance,
        work_dir=work, started_utc=started, notes=notes, timings=timings,
    )

    # 2. Rust side, on its own copy, first (it is fast and may refuse).
    rust_proj = work / "rust"
    shutil.copytree(staged, rust_proj)
    rust_hdf = rust_proj / g_hdf.name
    poisoned = _poison_products(rust_hdf) if isolate_inputs else []
    bundle = work / "rust_bundle"
    try:
        _, cmd = run_engine(engine, rust_hdf, out_bundle=bundle, options=options, timeout=timeout)
    except RustPreprocessRefusedError as exc:
        report.verdict, report.refusal = "refused", exc.refusal
        lap("rust")
        report.write(work)
        return report
    receipt = write_bundle(rust_hdf, bundle, restore_mtime=True, restamp_currency=True)
    Path(receipt["backup"]).unlink(missing_ok=True)
    unwritten = sorted(set(poisoned) - {f"{a}/{d}" for a, v in receipt["areas"].items() for d in v["datasets"]})
    if unwritten:
        notes.append(f"Products the engine did not write (left NaN by isolation): {unwritten}")
    report.rust_geometry_hdf = rust_hdf
    report.options = {**options, "command": cmd, "isolate_inputs": isolate_inputs,
                      "restamp_currency": True}
    report.currency = receipt.get("currency", {})
    written_sets = {a: set(v["datasets"]) for a, v in receipt["areas"].items()}
    lap("rust")

    # 3. Native side: RAS Commander only, on its own copy, repeated on request.
    native_proj = work / "native"
    shutil.copytree(staged, native_proj)
    nras = init_ras_project(native_proj, hecras_version, ras_object=RasPrj(), load_results_summary=False, hide_intro=True)
    native_live = native_proj / g_hdf.name
    native_hdfs: List[Path] = []
    staged_nan = _nan_masks(staged_hdf) if isolate_inputs else {}
    for k in range(1, native_repeats + 1):
        shutil.copy2(staged_hdf, native_live)
        native_poisoned = _poison_products(native_live) if isolate_inputs else []
        RasMap.recompute_property_tables(nras.prj_file, native_proj / geom_text.name,
                                         hecras_version=hecras_version, ras_object=nras)
        if native_poisoned:
            stale = _unrecomputed(native_live, native_poisoned, staged_nan)
            if stale:
                raise RustPreprocessError(
                    f"native run {k}: RASMapper reported success but left stored values "
                    f"unrecomputed in {stale}; the native side cannot serve as the reference")
        out = work / f"native_{k}_{g_hdf.name}"
        shutil.copy2(native_live, out)
        native_hdfs.append(out)
        lap(f"native_{k}")
    report.native_geometry_hdfs = native_hdfs
    report.native_runs = native_repeats
    if native_repeats > 1:
        shutil.copy2(native_hdfs[0], native_live)  # engine runs below resolve layers here

    # 4. Compare (native run 1 is the reference; later runs reveal native nondeterminism).
    import h5py

    comparisons, attr_diffs = compare_geometry_hdfs(native_hdfs[0], rust_hdf, tolerance=tolerance, max_ids=max_ids)
    report.attribute_differences = attr_diffs
    areas = sorted({c.area for c in comparisons})
    with h5py.File(native_hdfs[0], "r") as fn, h5py.File(rust_hdf, "r") as fr:
        native_arrays = {a: _read_area(fn, a) for a in areas if f"{AREAS}/{a}" in fn}
        rust_arrays = {a: _read_area(fr, a) for a in areas if f"{AREAS}/{a}" in fr}
        area_meta = {
            a: {
                "composite_lc": _flag(fn[f"{AREAS}/{a}"].attrs, "Composite LC"),
                "mfn": _flag(fn[f"{AREAS}/{a}"].attrs, "Multiple Face Mann n"),
                "long_faces": set(_long_faces(native_arrays[a]).tolist()),
            }
            for a in native_arrays
        }
    other_runs: List[Dict[str, Dict[str, np.ndarray]]] = []
    for k, other in enumerate(native_hdfs[1:], start=2):
        nd, _ = compare_geometry_hdfs(native_hdfs[0], other, max_ids=max_ids)
        for c in nd:
            if not c.bitwise:
                report.native_nondeterminism.append({
                    "run": k, "area": c.area, "dataset": c.dataset, "id_kind": c.id_kind,
                    "n_ids_different": c.n_ids_different, "ids_different": c.ids_different})
        with h5py.File(other, "r") as f:
            other_runs.append({a: _read_area(f, a) for a in areas if f"{AREAS}/{a}" in f})

    nondet = {(d["area"], d["dataset"]) for d in report.native_nondeterminism}
    for c in comparisons:
        meta = area_meta.get(c.area, {})
        if (c.area, c.dataset) in nondet:
            c.labels.append("native runs disagree (N-1/N-2)")
            report.labels.setdefault("N-1", KNOWN_NATIVE_BEHAVIOURS["N-1"])
            report.labels.setdefault("N-2", KNOWN_NATIVE_BEHAVIOURS["N-2"])
            if not c.passed and c.area in rust_arrays:
                for k, run in enumerate(other_runs, start=2):
                    if c.area not in run:
                        continue
                    alt = compare_area_arrays(c.area, run[c.area], rust_arrays[c.area],
                                              tolerance=tolerance, datasets=[c.dataset], max_ids=max_ids)[0]
                    if alt.passed:
                        c.status, c.passed = "matches_other_native_run", True
                        c.labels.append(f"equals native run {k}")
                        break
        if c.category == "product" and meta.get("composite_lc") and (
                c.dataset == "Cells Center Manning's n" or "/" in c.dataset):
            c.labels.append("D-4 (Composite LC)")
            report.labels.setdefault("D-4", KNOWN_NATIVE_BEHAVIOURS["D-4"])
        if c.category == "product" and meta.get("mfn") and c.dataset.startswith("Faces Area Elevation"):
            c.labels.append("D-5 (Multiple Face Mann n)")
            report.labels.setdefault("D-5", KNOWN_NATIVE_BEHAVIOURS["D-5"])
        if c.id_kind == "face" and c.ids_different and meta.get("long_faces") and (
                set(c.ids_different) & meta["long_faces"]):
            c.labels.append("L-1 long faces among differences")
            report.labels.setdefault("L-1", KNOWN_NATIVE_BEHAVIOURS["L-1"])
    for a, meta in area_meta.items():
        if meta["long_faces"]:
            notes.append(f"{a}: {len(meta['long_faces'])} faces have more than {LONG_FACE_POINTS} profile "
                         f"points (L-1); native output on them is not reproducible.")
    report.stage2_coverage = _stage2_coverage(comparisons, written_sets)
    report.comparisons = comparisons
    lap("compare")

    # Optional: corrected-mode departure from native (informational only).
    corrected_bundle = None
    if include_corrected:
        corrected_bundle = work / "rust_bundle_corrected"
        run_engine(engine, rust_hdf, out_bundle=corrected_bundle,
                   options=_engine_options(False, sort, units, threads), timeout=timeout)
        _, arrays = load_bundle(corrected_bundle)
        for area in sorted({a for a, _ in arrays}):
            cor = {d: v for (a, d), v in arrays.items() if a == area}
            nat = native_arrays.get(area, {})
            # Topology the bundle does not carry comes from the native side.
            report.corrected_departure += compare_area_arrays(
                area, nat, {**{k: v for k, v in nat.items() if k not in cor}, **cor},
                datasets=sorted(cor), max_ids=max_ids)
        for c in report.corrected_departure:
            c.labels.append("corrected mode (informational)")
        triggers = [a for a, m in area_meta.items() if m["composite_lc"] or m["mfn"]]
        if triggers:
            report.labels.setdefault("D-4", KNOWN_NATIVE_BEHAVIOURS["D-4"])
            report.labels.setdefault("D-5", KNOWN_NATIVE_BEHAVIOURS["D-5"])
        else:
            notes.append("Composite LC and Multiple Face Mann n are off in every area, so defects D-4 "
                         "and D-5 cannot act; corrected mode is expected to equal native here.")
        lap("rust_corrected")

    # Optional: the engine's own --compare against native run 1.
    if engine_compare:
        try:
            ec, _ = run_engine(engine, native_live, out_bundle=None, options=options, compare=True, timeout=timeout)
            report.engine_compare = {a["area"]: a.get("parity") for a in ec.get("areas", [])}
        except RustPreprocessError as exc:
            notes.append(f"engine --compare against native run 1 failed: {exc}")
        lap("engine_compare")

    report.verdict = "equivalent" if comparisons and all(c.passed for c in comparisons) else "not equivalent"
    if not keep_work:
        kept = work / f"rust_{g_hdf.name}"
        shutil.copy2(rust_hdf, kept)
        report.rust_geometry_hdf = kept
        for folder in (staged, rust_proj, native_proj, bundle, corrected_bundle):
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
        notes.append("Project copies were removed (keep_work=False); the geometry HDFs were kept.")
    report.write(work)
    logger.info("Rust preprocessing equivalence for %s: %s", g_hdf.name, report.verdict)
    return report


def _stage2_coverage(
    comparisons: Sequence[RustDatasetComparison], written: Mapping[str, set]
) -> Dict[str, Dict[str, Any]]:
    """Per area: Stage 2 infiltration/impervious datasets present, compared and not compared.

    A family dataset that the engine bundle did not write still holds the
    staged input on the Rust side, so equal values prove nothing about the
    engine. It is recategorized ``carried`` and labeled; it stays in the
    table (and in the verdict, as an unchanged input) but is listed as not
    compared.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for c in comparisons:
        fam = c.dataset.split("/", 1)[0]
        if "/" not in c.dataset or fam not in STAGE2_FAMILIES:
            continue
        cov = out.setdefault(c.area, {"present": [], "compared": [], "not_compared": [],
                                      "engine_compare": "not covered (Stage 2 only through Cells Center Manning's n; "
                                                        "workstream P in progress)"})
        cov["present"].append(c.dataset)
        if c.dataset in written.get(c.area, set()):
            cov["compared"].append(c.dataset)
        else:
            cov["not_compared"].append(c.dataset)
            c.category = "carried"
            c.labels.append("not computed by the engine; carried from the input (not compared)")
    return out


def _flag(attrs, name: str) -> bool:
    if name not in attrs:
        return False
    v = np.asarray(attrs[name]).ravel()
    return bool(v.size and int(v[0]))
