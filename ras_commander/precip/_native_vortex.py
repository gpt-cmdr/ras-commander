"""Native and shadow backends for :meth:`PrecipMrms.to_dss`.

``PrecipMrms.to_dss`` converts MRMS GRIB2 files to DSS grids through one of three backends:

- ``"java"`` (default): HEC-Vortex through :class:`VortexCli`.
- ``"native"``: the gridded importer of the optional ``ras-commander-fast-dss`` package. It starts
  no JVM and needs no HEC-Vortex install.
- ``"shadow"``: runs Java on the requested output and the native importer on a temporary copy of
  what that output held before, compares the two results and returns Java's output. Java's result
  and Java's failures are the caller's. The comparison never raises. See :func:`compare_outputs`
  for what it can and cannot tell.

The argument ``backend=`` wins, then the environment variable ``RAS_COMMANDER_MRMS_BACKEND``, then
``PrecipMrms.backend``.

**Precipitation periods.** A DSS precipitation grid needs a period in its D and E parts: HEC-HMS has
read precipitation stored without a period as no rain. MRMS GRIB2 states an instant, so the period
of an accumulation comes from the product. HEC-Vortex and the native importer apply a one-hour
window to file names matching their 01H rules. Observed behaviour we did not implement: HEC-Vortex
1.1.0 and 0.13.3 store other MRMS durations (15M and 24H were read) as PRECIPITATION, MM, INST-VAL
with a D part only. The native importer refuses precipitation at an instant unless a data type is
stated, and takes no window for a GRIB2 input. This adapter never states that type. The native
backend refuses every duration other than one hour before the importer runs, and checks each written
record's period. The Java and shadow routes refuse those durations too, before writing anything,
unless the caller passes ``allow_instantaneous_precip=True``: Java then writes them as above, and
logs a warning. The override does not change the native backend.

This module is private. It imports the engine only inside functions, so ``import ras_commander``
works without the wheel.
"""

from __future__ import annotations

from collections import Counter, deque
from contextlib import nullcontext
import dataclasses
from datetime import datetime, timedelta
import importlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from ..LoggingConfig import get_logger, log_call

logger = get_logger(__name__)

#: Environment variable that overrides ``PrecipMrms.backend`` when set.
ENV_VAR = "RAS_COMMANDER_MRMS_BACKEND"
#: Allowed backend names.
BACKENDS = ("java", "native", "shadow")
#: Default backend. The native importer is not the default in this release.
DEFAULT_BACKEND = "java"

_INSTALL_HINT = (
    "The 'native' MRMS backend requires the optional ras-commander-fast-dss package with its "
    "gridded importer. It is not yet on PyPI; install the wheel you were given with "
    "'uv pip install ras_commander_fast_dss-<version>-<tag>.whl', or use backend='java'."
)

_RESAMPLING = {
    "bilinear": "bilinear",
    "near": "near",
    "nearest": "near",
    "nearestneighbor": "near",
    "average": "average",
}

_DURATION_RE = re.compile(r"(?:^|[_.\-]|QPE)(\d{1,2})([HM])(?=[_.\-]|$)", re.IGNORECASE)
#: HEC-Vortex 0.13.3 gives a one-hour period only to names matching its three rules for these
#: products (``GridDatasetReader.SpecialFileType``). Other names get an instant, even for a 01H file.
_VORTEX_ONE_HOUR_NAME_RE = re.compile(r"(gaugecorr|radaronly|multisensor).*qpe.*01h.*grib2", re.IGNORECASE)
_TIME_PART_RE = re.compile(r"^(\d{2})([A-Za-z]{3})(\d{4}):(\d{4})$")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

#: The data type an import record states for a depth over a period.
_PER_CUM = "PER-CUM"

_PRECIP_2_BYTE = 101001
_ZLIB = 26
_MINUS_FLT_MAX = float(-np.finfo(np.float32).max)
#: Native metadata that a writer's compressor or clock decides, not the record's content.
_WRITER_METADATA = {"sizeof_compressed_elements"}
_P2B_METADATA = {"compression_method", "compression_base", "compression_scale_factor"}
_GRID_FIELDS = (
    "record_type",
    "grid_type",
    "nx",
    "ny",
    "cell_size",
    "lower_left_cell_x",
    "lower_left_cell_y",
    "x_coord_of_grid_cell_zero",
    "y_coord_of_grid_cell_zero",
    "srs_name",
    "srs_definition_type",
    "srs_definition",
    "data_units",
    "data_type",
    "start_time",
    "end_time",
)
_GRID_STATISTICS = ("min_value", "max_value", "mean_value", "range_limit_table", "range_counts")
#: Far above a CONUS grid, which is the largest MRMS holds; the reader's default limit is lower.
_MAX_CELLS = 2**28

_lock = threading.Lock()
_fallback_warned = False

#: Outcome counts of shadow comparisons, keyed by (outcome, label).
SHADOW_STATS: Counter = Counter()
#: Most recent shadow comparison records, for diagnostics and evidence scripts.
SHADOW_RECORDS: Deque[Dict[str, Any]] = deque(maxlen=500)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def normalize_backend(value: Any, source: str) -> str:
    """Validate a backend name and return it lower-cased."""
    name = str(value).strip().lower()
    if name not in BACKENDS:
        raise ValueError(
            f"Invalid MRMS backend {value!r} from {source}; expected one of {', '.join(BACKENDS)}"
        )
    return name


def requested_backend(explicit: Any, attribute_value: Any) -> str:
    """Backend requested by the argument, the environment variable or ``PrecipMrms.backend``."""
    if explicit is not None:
        return normalize_backend(explicit, "backend=")
    env_value = os.environ.get(ENV_VAR, "").strip()
    if env_value:
        return normalize_backend(env_value, f"environment variable {ENV_VAR}")
    if attribute_value is None or str(attribute_value).strip() == "":
        return DEFAULT_BACKEND
    return normalize_backend(attribute_value, "PrecipMrms.backend")


def import_gridded_module():
    """Import the engine's importer, or raise an ``ImportError`` that says how to install it.

    A wheel that fails to load, or one without the gridded importer, also raises ``ImportError``,
    with the original error chained.
    """
    try:
        module = importlib.import_module("ras_commander_fast_dss.gridded")
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc
    except Exception as exc:  # A broken native wheel.
        raise ImportError(
            f"ras-commander-fast-dss is installed but failed to load "
            f"({type(exc).__name__}: {exc}). {_INSTALL_HINT}"
        ) from exc
    if not callable(getattr(module, "import_gridded", None)):
        raise ImportError(f"This ras-commander-fast-dss has no gridded importer. {_INSTALL_HINT}")
    return module


def native_available() -> bool:
    """True when the engine's importer can be imported. A broken wheel counts as absent."""
    try:
        import_gridded_module()
    except ImportError:
        return False
    return True


def effective_backend(explicit: Any, attribute_value: Any) -> str:
    """Backend to use for this call.

    ``native`` without the wheel raises ``ImportError``. ``shadow`` without the wheel runs ``java``
    and logs one warning per process.
    """
    global _fallback_warned
    backend = requested_backend(explicit, attribute_value)
    if backend == "native":
        import_gridded_module()
    elif backend == "shadow" and not native_available():
        with _lock:
            warn = not _fallback_warned
            _fallback_warned = True
        if warn:
            logger.warning(
                "MRMS backend 'shadow' requested but ras-commander-fast-dss is not available; "
                "using HEC-Vortex only, with no comparison. %s",
                _INSTALL_HINT,
            )
        return "java"
    return backend


def reset_fallback_warning() -> None:
    """Allow the shadow-fallback warning to be logged again (tests)."""
    global _fallback_warned
    with _lock:
        _fallback_warned = False


# ---------------------------------------------------------------------------
# Product periods
# ---------------------------------------------------------------------------


def _duration_seconds(name: str) -> Optional[int]:
    """Accumulation stated in an MRMS file, product or variable name, in seconds."""
    match = _DURATION_RE.search(name)
    if not match:
        return None
    return int(match.group(1)) * (3600 if match.group(2).upper() == "H" else 60)


def period_problems(
    product: str, grib_paths: Sequence[Path], variables: Optional[Sequence[str]]
) -> List[str]:
    """Each name that states an MRMS accumulation other than one hour."""
    named = [("product", product)]
    named += [("file", path.name) for path in grib_paths]
    named += [("variable", name) for name in variables or ()]
    problems = []
    for kind, name in named:
        seconds = _duration_seconds(str(name))
        if seconds is not None and seconds != 3600:
            problems.append(f"{kind} {name!r} states {seconds // 60} minutes")
    return list(dict.fromkeys(problems))


def find_period_problems(
    product: str,
    grib_paths: Sequence[Path],
    variables: Optional[Sequence[str]],
    list_variables: Callable[[Path], Optional[Sequence[str]]],
) -> Tuple[List[str], Dict[Path, List[str]]]:
    """Duration check shared by every backend. Returns the problems and the variables listed.

    Names come first, and need no decoding. Then, when the caller stated no variable, the file's own
    variables: a file's name can be changed, and they are its statement of its accumulation.
    ``list_variables`` returns ``None`` for a file it cannot list, whose name is then all there is.
    """
    problems = period_problems(product, grib_paths, variables)
    held: Dict[Path, List[str]] = {}
    if problems:
        return problems, held
    for path in grib_paths:
        names = list_variables(path)
        if names is not None:
            held[path] = [str(name) for name in names]
    if not variables:
        listed = [name for names in held.values() for name in names if "qpe" in name.lower()]
        problems = period_problems(product, grib_paths, listed)
    return problems, held


def _vortex_name_problems(grib_paths: Sequence[Path]) -> List[str]:
    """Each file whose name HEC-Vortex gives no period, whatever its accumulation."""
    return [
        f"file {Path(path).name!r} has a name HEC-Vortex gives no one-hour period: it needs "
        "gaugecorr, radaronly or multisensor, then qpe, then 01h, and to end in grib2"
        for path in grib_paths
        if not _VORTEX_ONE_HOUR_NAME_RE.search(Path(path).name)
    ]


def _engine_listing(path: Path) -> Optional[List[str]]:
    """The engine's variable names for the Java route, or ``None`` if it cannot read this file."""
    try:
        return list(import_gridded_module().list_variables(str(path)))
    except Exception as exc:
        if Path(path).exists():
            logger.warning(
                "Could not list the variables of %s (%s); checking its name only.", Path(path).name, exc
            )
        return None


def _shortened(items: Sequence[str], limit: int = 5) -> str:
    shown = "; ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown}; and {len(items) - limit} more"


def settle_java_periods(
    problems: Sequence[str], grib_paths: Sequence[Path], allow_instantaneous_precip: bool
) -> None:
    """Refuse a duration Java cannot state a period for, or warn when the caller overrides that."""
    if not problems:
        return
    if allow_instantaneous_precip:
        logger.warning(
            "allow_instantaneous_precip=True: writing MRMS precipitation with no period. HEC-Vortex "
            "has been observed to store these durations as PRECIPITATION, INST-VAL, with a D part "
            "only, and HEC-HMS has read this shape as no rain. Check the records before use. (%s)",
            _shortened(list(problems)),
        )
        return
    files = _shortened([Path(path).name for path in grib_paths])
    raise ValueError(
        f"PrecipMrms.to_dss refused {files}: {_shortened(list(problems))}. Nothing was written. MRMS "
        "GRIB2 states an instant, and the HEC-Vortex route can state a period for one-hour QPE only. "
        "HEC-Vortex has been observed to store other durations as PRECIPITATION, INST-VAL, with a D "
        "part only, and HEC-HMS has read this shape as no rain. Use a 01H product, or pass "
        "allow_instantaneous_precip=True to write this shape anyway."
    )


def check_java_periods(
    product: str,
    grib_paths: Sequence[Path],
    variables: Optional[Sequence[str]],
    allow_instantaneous_precip: bool,
) -> Tuple[List[str], Dict[Path, List[str]]]:
    """Check the Java and shadow routes before HEC-Vortex starts, with the engine if it is present.

    Without the wheel, only the names of the product, the files and any stated variable are read.
    Returns the problems found, which were overridden if it returns at all with any, and the variables
    the engine listed.
    """
    lister = _engine_listing if native_available() else (lambda _path: None)
    problems, held = find_period_problems(product, grib_paths, variables, lister)
    problems = problems or _vortex_name_problems(grib_paths)
    settle_java_periods(problems, grib_paths, allow_instantaneous_precip)
    return problems, held


def _part_time(text: str) -> datetime:
    """A D or E part as a time. 2400 is midnight of the next day."""
    match = _TIME_PART_RE.match(text)
    if not match:
        raise ValueError(f"{text!r} is not a DSS time part")
    day, month, year, clock = match.groups()
    base = datetime(int(year), _MONTHS.index(month.upper()) + 1, int(day))
    return base + timedelta(hours=int(clock[:2]), minutes=int(clock[2:]))


def record_period_problem(record: Dict[str, Any]) -> Optional[str]:
    """Why one imported record is not a one-hour PER-CUM depth, or ``None``."""
    pathname = str(record.get("pathname", ""))
    parts = pathname.split("/")
    if len(parts) != 8:
        return f"{pathname}: not a six-part pathname"
    if record.get("data_type") != _PER_CUM:
        return f"{pathname}: data type {record.get('data_type')!r}, expected PER-CUM"
    if not parts[4] or not parts[5]:
        return f"{pathname}: no period in the D and E parts"
    try:
        seconds = (_part_time(parts[5]) - _part_time(parts[4])).total_seconds()
    except ValueError as exc:
        return f"{pathname}: {exc}"
    if seconds != 3600:
        return f"{pathname}: period of {seconds:g} seconds, expected 3600"
    return None


# ---------------------------------------------------------------------------
# Native import
# ---------------------------------------------------------------------------


def _engine_errors():
    return importlib.import_module("ras_commander_fast_dss.exceptions")


def _native_parts(dss_parts: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Part names upper-cased, as ``VortexCli`` reads them. D and E are refused by the engine."""
    return {str(key).upper(): value for key, value in (dss_parts or {}).items()}


def _native_method(resampling_method: str) -> str:
    key = re.sub(r"[\s_\-]", "", str(resampling_method)).lower()
    if key not in _RESAMPLING:
        raise ValueError(
            f"Unsupported resampling_method {resampling_method!r} for the native MRMS backend; "
            "use 'Bilinear', 'Nearest Neighbor' or 'Average'"
        )
    return _RESAMPLING[key]


def _native_target(target_wkt: str) -> str:
    return "SHG" if str(target_wkt).strip().upper() == "SHG" else str(target_wkt)


@log_call
def import_native(
    grib_paths: Sequence[Path],
    output_path: Path,
    *,
    product: str,
    variables: Optional[Sequence[str]] = None,
    clip_shp: Any = None,
    target_wkt: str = "SHG",
    target_cell_size: float = 2000,
    resampling_method: str = "Bilinear",
    dss_parts: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    version: Optional[int] = None,
    align: str = "refuse",
) -> List[Dict[str, Any]]:
    """Run the native importer and return its records, each checked to hold a one-hour period.

    Every selection is checked before the first write: its name, its duration and, for a stated
    variable, that each input holds it. The importer then plans and writes one selection per call,
    so each stated variable is a separate call. A failure in a later call leaves the records of the
    earlier calls in ``output_path``. The raised error states the total, and its ``completed``
    attribute lists those records with any the failing call wrote.

    Raises:
        ImportError: The wheel is missing, broken or has no importer.
        FileNotFoundError: An input or ``clip_shp`` does not exist.
        ValueError: Invalid arguments, including a variable that is not an MRMS QPE or is stated
            twice. Nothing has been written.
        DssUnsupportedRecordError: A duration without a one-hour period, or a stated variable that
            an input does not hold: nothing has been written. Also any refusal by the importer:
            nothing has been written for that selection, and records of earlier selections remain.
        DssError: A written record did not hold a one-hour period, or two selections wrote one
            pathname. The records remain. A ``RuntimeError``.
        TimeoutError: ``timeout`` passed. Checked after each record; records written remain.
    """
    gridded = import_gridded_module()
    errors = _engine_errors()

    paths = [Path(path).resolve() for path in grib_paths]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")
    clip = None
    if clip_shp is not None:
        clip = Path(clip_shp).resolve()
        if not clip.exists():
            raise FileNotFoundError(f"Clip shapefile not found: {clip}")

    for name in variables or ():
        # Other variables reach the importer's rules by other names: it does not read
        # VAR209-6-250 as precipitation, for example. Each QPE name does.
        if "qpe" not in str(name).lower():
            raise ValueError(
                f"Variable {name!r} is not an MRMS QPE. The native MRMS backend imports QPE "
                "variables only; use ras_commander_fast_dss.gridded.import_gridded for others."
            )
    repeated = [name for name, count in Counter(map(str, variables or ())).items() if count > 1]
    if repeated:
        raise ValueError(f"Variables stated more than once: {', '.join(repeated)}")
    method = _native_method(resampling_method)
    parts = _native_parts(dss_parts)

    # The importer's window rule reads the file name, so a 24H file renamed 01H is caught here,
    # before one-hour stamps go on it.
    problems, held = find_period_problems(
        product, paths, variables, lambda path: gridded.list_variables(str(path))
    )
    if problems:
        raise errors.DssUnsupportedRecordError(
            "The native MRMS backend writes one-hour QPE only: "
            + "; ".join(problems)
            + ". MRMS GRIB2 states an instant, and the importer takes no window for GRIB2, so this "
            "accumulation's period cannot be stated. It is not written without one, as HEC-HMS has "
            "read precipitation stored without a period as no rain. Use a 01H product. Observed "
            "behaviour we did not implement: HEC-Vortex stores such files as INST-VAL with a D "
            "part only. allow_instantaneous_precip applies to the Java route only."
        )
    absent = [
        f"{path.name} does not hold {name!r}"
        for path, names in held.items()
        for name in map(str, variables or ())
        if name not in names
    ]
    if absent:
        raise errors.DssUnsupportedRecordError(
            "Nothing was written, as a stated variable is not in every input: " + "; ".join(absent)
        )

    selection: List[Dict[str, Optional[str]]]
    if variables:
        selection = [{"variable": str(name)} for name in variables]
    else:
        selection = [{"product": "mrms_qpe"}]

    deadline = None if timeout is None else time.monotonic() + float(timeout)

    def progress(_state: Dict[str, Any]) -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError(
                f"Native MRMS import timed out after {timeout} seconds. Try increasing timeout= "
                "or reducing input data. Records already written remain."
            )

    def run(destination: Path, chosen: Dict[str, Optional[str]]) -> Any:
        return gridded.import_gridded(
            [str(path) for path in paths],
            str(destination),
            shapefile=None if clip is None else str(clip),
            target_crs=_native_target(target_wkt),
            cell_size=float(target_cell_size),
            method=method,
            parts=parts,
            version=version,
            align=align,
            progress=progress,
            **chosen,
        )

    # The importer plans one selection at a time, and nothing plans them together. Two selections could
    # write one pathname, or a later one could be refused, so several are first run into a scratch file:
    # the caller's file is not touched until the whole request has worked.
    if len(selection) > 1:
        _rehearse(selection, run, output_path, errors)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    for chosen in selection:
        try:
            result = run(output_path, chosen)
        except Exception as exc:
            if not records:
                raise
            raise _with_total_written(exc, records, output_path, errors)
        records.extend(result.records)

    if not records:
        raise errors.DssError(f"The native MRMS import wrote no records to {output_path}")
    twice = sorted(name for name, count in Counter(r.get("pathname") for r in records).items() if count > 1)
    if twice:
        raise errors.DssError(
            f"Two selections wrote one pathname to {output_path}, and the last stays. These records "
            "hold one selection only, so do not use them: " + "; ".join(map(str, twice[:5]))
        )
    bad = [why for why in map(record_period_problem, records) if why]
    if bad:
        raise errors.DssError(
            f"The native MRMS import wrote {len(bad)} record(s) to {output_path} that do not hold a "
            "one-hour period, which HEC-HMS or HEC-RAS could read as no rain. Do not use them: "
            + "; ".join(bad[:5])
        )
    return records


def _rehearse(
    selection: List[Dict[str, Optional[str]]], run: Callable[..., Any], output_path: Path, errors: Any
) -> None:
    """Run every selection into a scratch file, and refuse what would collide. Costs a second import."""
    parent = Path(output_path).parent
    scratch = Path(tempfile.mkdtemp(prefix="mrms_rehearsal_", dir=parent if parent.is_dir() else None))
    try:
        planned: List[Any] = []
        for chosen in selection:
            planned.extend(r.get("pathname") for r in run(scratch / "rehearsal.dss", chosen).records)
    finally:
        _remove_scratch(scratch)
    twice = sorted(name for name, count in Counter(planned).items() if count > 1)
    if twice:
        raise errors.DssUnsupportedRecordError(
            f"Nothing was written to {output_path}: two selections would write one pathname, and only "
            "the last would stay: " + "; ".join(map(str, twice[:5]))
        )


def _remove_scratch(path: Path, attempts: int = 3, pause: float = 0.2) -> None:
    """Remove a scratch folder, or say that it stays. It cannot change a result already returned."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if attempt + 1 == attempts:
                logger.warning(f"Could not remove the scratch folder {path}, which remains: {exc}")
            else:
                time.sleep(pause)


def _with_total_written(
    exc: Exception, earlier: List[Dict[str, Any]], output_path: Path, errors: Any
) -> Exception:
    """``exc``, also stating the records of this whole run. Its type stays when its text can change."""
    done = earlier + list(getattr(exc, "completed", None) or [])
    note = (
        f"This run wrote {len(done)} record(s) to {output_path} in total, across its variables, "
        "and they remain"
    )
    text = str(exc)
    exc.args = (f"{text}. {note}.",)
    if note not in str(exc):  # An OSError shows its errno fields, not args.
        exc = errors.DssError(f"{text}. {note}.")
    exc.completed = done
    return exc


@log_call
def to_dss_native(grib_paths: Sequence[Path], output_path: Path, **kwargs: Any) -> Path:
    """Convert MRMS GRIB2 to DSS with the native importer. Arguments as :func:`import_native`."""
    records = import_native(grib_paths, output_path, **kwargs)
    resolved = Path(output_path).resolve()
    logger.info("DSS file written by the native MRMS backend: %s (%d records)", resolved.name, len(records))
    return resolved


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _same(a: Any, b: Any) -> bool:
    """Equality with no tolerance. NaN equals NaN, and arrays compare whole."""
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        a, b = np.asarray(a), np.asarray(b)
        if a.shape != b.shape:
            return False
        if a.dtype.kind in "fc" and b.dtype.kind in "fc":
            return bool(np.array_equal(a, b, equal_nan=True))
        return bool(np.array_equal(a, b))
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True
    if isinstance(a, np.datetime64) and isinstance(b, np.datetime64):
        return bool(a == b)
    result = a == b
    return bool(result) if not isinstance(result, np.ndarray) else bool(result.all())


def _brief(value: Any) -> str:
    if isinstance(value, np.ndarray):
        return f"array{value.shape}"
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


def _monolith_rounding(cells: np.ndarray, scale: float, base: float) -> np.ndarray:
    """What PRECIP_2_BYTE keeps of native cells, with HEC's marker as NaN.

    Monolith's ``DataCompression.compress``, as in the engine's ``compare_import.py``.
    """
    s, b = np.float32(scale), np.float32(base)
    missing = np.isnan(cells) | (cells < b)
    with np.errstate(over="ignore", invalid="ignore"):
        steps = np.where(missing, 0.0, ((cells - b) * s).astype(np.float64) + 0.5).astype(np.int64)
    kept = (steps.astype(np.float32) / s) + b
    return np.where(missing, np.float32(np.nan), kept).astype(np.float32)


def _p2b_shape(java_meta: Dict[str, Any], native_meta: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Scale and base when the pair is the one documented DSS6 shape, otherwise ``None``.

    Monolith stores PRECIP_2_BYTE with scale 100 and base 0; the engine stores ZLIB with HEC's
    undefined value in those fields. No other value qualifies.
    """
    scale = java_meta.get("compression_scale_factor")
    base = java_meta.get("compression_base")
    if (
        java_meta.get("compression_method") == _PRECIP_2_BYTE
        and scale == 100.0
        and base == 0.0
        and native_meta.get("compression_method") == _ZLIB
        and native_meta.get("compression_scale_factor") == _MINUS_FLT_MAX
        and native_meta.get("compression_base") == _MINUS_FLT_MAX
    ):
        return float(scale), float(base)
    return None


def compare_cells(java: np.ndarray, native: np.ndarray) -> Optional[str]:
    """How two float32 grids differ, by bits and mask, or ``None``. There is no tolerance."""
    if java.shape != native.shape:
        return f"cells: shape {java.shape} and {native.shape}"
    jm, nm = np.isnan(java), np.isnan(native)
    both = ~jm & ~nm
    different = both & (java.view(np.uint32) != native.view(np.uint32))
    mask = jm != nm
    if not different.any() and not mask.any():
        return None
    detail = [f"cells: {int(different.sum())} of {java.size} differ, {int(mask.sum())} in mask"]
    if different.any():
        gap = np.abs(java[different].astype(np.float64) - native[different].astype(np.float64))
        rows, cols = np.nonzero(different)
        samples = ", ".join(
            f"[{r},{c}] java {java[r, c]!r} native {native[r, c]!r}"
            for r, c in list(zip(rows[:3].tolist(), cols[:3].tolist()))
        )
        detail.append(f"max abs {gap.max():g}; first {samples}")
    if mask.any():
        rows, cols = np.nonzero(mask)
        detail.append(f"first mask difference at [{int(rows[0])},{int(cols[0])}]")
    return "; ".join(detail)


def compare_grids(java: Any, native: Any) -> Tuple[List[str], List[str]]:
    """Unexpected and documented differences between two :class:`Grid` records of one pathname.

    Pathname, stamps, units, data type, geometry, CRS, statistics, the range table and all other
    metadata must be identical, and cells identical in bits. Documented differences: DSS7 HRAP and
    Albers ``null_value``, compressed size, and DSS6 PRECIP_2_BYTE, which Monolith rounds to 1/100
    and this engine does not. That allowance covers the compression fields and the cells only.
    Observed on real files, Monolith's statistics describe the cells before rounding, as the
    engine's do, so they must be equal in every case.
    """
    unexpected: List[str] = []
    expected: List[str] = []
    for name in ("dss_version",) + _GRID_FIELDS:
        a, b = getattr(java, name), getattr(native, name)
        if not _same(a, b):
            unexpected.append(f"{name}: java {_brief(a)} native {_brief(b)}")

    version = java.dss_version
    if not _same(java.null_value, native.null_value):
        known = (
            version == 7
            and any(kind in str(java.grid_type).lower() for kind in ("albers", "hrap"))
            and java.null_value == 0.0
            and native.null_value == _MINUS_FLT_MAX
        )
        if known:
            expected.append("null_value")
        else:
            unexpected.append(f"null_value: java {java.null_value!r} native {native.null_value!r}")

    java_meta, native_meta = dict(java.metadata), dict(native.metadata)
    rounding = _p2b_shape(java_meta, native_meta) if version == 6 else None
    for key in sorted(set(java_meta) | set(native_meta)):
        a, b = java_meta.get(key, "<absent>"), native_meta.get(key, "<absent>")
        if _same(a, b):
            continue
        if key in _WRITER_METADATA and isinstance(a, int) and isinstance(b, int) and a > 0 and b > 0:
            expected.append(key)
        elif rounding is not None and key in _P2B_METADATA:
            expected.append(key)
        else:
            unexpected.append(f"metadata {key}: java {_brief(a)} native {_brief(b)}")

    native_cells = native.data
    if rounding is not None:
        native_cells = _monolith_rounding(native.data, *rounding)
        rounded = int(
            (~np.isnan(native.data) & (native_cells.view(np.uint32) != native.data.view(np.uint32))).sum()
        )
        expected.append(f"dss6_precip_2_byte:{rounded}")
    for name in _GRID_STATISTICS:
        a, b = getattr(java, name), getattr(native, name)
        if not _same(a, b):
            unexpected.append(f"{name}: java {_brief(a)} native {_brief(b)}")
    cells = compare_cells(java.data, native_cells)
    if cells:
        unexpected.append(cells)
    return unexpected, expected


def _catalog(handle: Any) -> Dict[str, Tuple[int, Any]]:
    """Each live pathname's record type and DSS7 write time (NaT in DSS6)."""
    frame = handle.catalog()
    frame = frame[~frame["duplicate"]]
    return {
        str(name): (int(kind), written)
        for name, kind, written in zip(frame["pathname"], frame["record_type"], frame["last_write"])
    }


def _read_record(handle: Any, name: str, kind: int) -> Any:
    """One record's decoded content, or ``None`` for a type with no reader here."""
    if 400 <= kind < 500:
        return handle.read_grid(name, max_cells=_MAX_CELLS)
    if 100 <= kind < 200:
        return handle.read_record_arrays(name)
    if 200 <= kind < 300:
        return handle.read_paired_data(name, ignore_d_part=False)
    return None


def _fields(value: Any) -> Optional[Dict[str, Any]]:
    """A record's fields to compare. ``dss_file`` names the file read, not the record."""
    if isinstance(value, dict):
        return value
    if dataclasses.is_dataclass(value):
        return {
            field.name: getattr(value, field.name)
            for field in dataclasses.fields(value)
            if field.name != "dss_file"
        }
    return None


def _identical(a: Any, b: Any) -> bool:
    """Exact equality of decoded content, by bits for arrays. No writer allowance applies."""
    a_fields, b_fields = _fields(a), _fields(b)
    if a_fields is not None or b_fields is not None:
        if a_fields is None or b_fields is None or a_fields.keys() != b_fields.keys():
            return False
        return all(_identical(a_fields[key], b_fields[key]) for key in a_fields)
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        if not (isinstance(a, np.ndarray) and isinstance(b, np.ndarray)):
            return False
        return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()
    return _same(a, b)


def compare_outputs(
    java_file: Path,
    native_file: Path,
    *,
    baseline_file: Optional[Path] = None,
    written: Iterable[str] = (),
) -> Dict[str, Any]:
    """Compare the outputs of the two writers, each started from the same content.

    Every pathname in any of the files is checked. A record both outputs hold exactly as the
    baseline held it, and that the native run did not report writing, counts as ``unchanged``. Any
    other record is compared, so a baseline record that Java rewrote and the native run omitted is
    a difference.

    One case cannot show in content: Java rewrites a baseline record with the same content and the
    native run omits it. Both outputs then end the same. In DSS7 the catalog's write time shows
    Java's write, and it is reported. DSS6 has no such time, so there it counts as unchanged.

    Args:
        java_file: Java's output.
        native_file: The native run's output, on a copy of the baseline if there is one.
        baseline_file: A copy of what the output held before either run.
        written: Pathnames the native run reports writing.

    Returns:
        ``records`` compared, ``unchanged`` baseline records, ``differences`` (pathname to unexpected
        differences; pathnames on one side only are entries too), ``expected`` (documented difference
        to count) and ``rounded_cells``.
    """
    engine = importlib.import_module("ras_commander_fast_dss")
    wrote = set(written)
    differences: Dict[str, List[str]] = {}
    expected: Counter = Counter()
    rounded_cells = 0
    compared = 0
    unchanged = 0
    baseline_open = nullcontext(None) if baseline_file is None else engine.open(str(baseline_file))
    with engine.open(str(java_file)) as java_dss, engine.open(str(native_file)) as native_dss, baseline_open as base_dss:
        java_names = _catalog(java_dss)
        native_names = _catalog(native_dss)
        base_names = {} if base_dss is None else _catalog(base_dss)
        for name in sorted(set(native_names) - set(java_names)):
            differences[name] = [
                "pathname: removed by java" if name in base_names else "pathname: written by native only"
            ]
        for name in sorted(set(java_names) - set(native_names)):
            differences[name] = [
                "pathname: removed by native" if name in base_names else "pathname: written by java only"
            ]
        for name in sorted(set(base_names) - set(java_names) - set(native_names)):
            differences[name] = ["pathname: removed by both"]
        for name in sorted(set(native_names) & set(java_names)):
            java_kind, java_time = java_names[name]
            native_kind, _ = native_names[name]
            if java_kind != native_kind:
                compared += 1
                differences[name] = [f"record type: java {java_kind} native {native_kind}"]
                continue
            java_record = _read_record(java_dss, name, java_kind)
            native_record = _read_record(native_dss, name, native_kind)
            if java_record is None or native_record is None:
                differences[name] = [f"record type {java_kind} has no reader here, so it was not compared"]
                continue
            java_kept = native_kept = False
            if name in base_names:
                base_kind, base_time = base_names[name]
                base_record = _read_record(base_dss, name, base_kind) if base_kind == java_kind else None
                java_kept = base_record is not None and _identical(java_record, base_record)
                native_kept = base_record is not None and _identical(native_record, base_record)
                if java_kept and native_kept and name not in wrote:
                    if base_time == base_time and java_time != base_time:  # NaT in DSS6 is never equal.
                        compared += 1
                        differences[name] = ["rewritten by java with the same content, omitted by native"]
                    else:
                        unchanged += 1
                    continue
            compared += 1
            if isinstance(java_record, dict) or not hasattr(java_record, "nx"):
                problems = [] if _identical(java_record, native_record) else ["content: java and native differ"]
            else:
                problems, known = compare_grids(java_record, native_record)
                for item in known:
                    key, _, count = item.partition(":")
                    expected[key] += 1
                    rounded_cells += int(count or 0)
            if problems:
                if native_kept:
                    problems.insert(0, "rewritten by java, omitted by native")
                elif java_kept:
                    problems.insert(0, "rewritten by native, not by java")
                differences[name] = problems
    return {
        "records": compared,
        "unchanged": unchanged,
        "differences": differences,
        "expected": dict(expected),
        "rounded_cells": rounded_cells,
    }


# ---------------------------------------------------------------------------
# Shadow
# ---------------------------------------------------------------------------


def _err(exc: Optional[BaseException]) -> Optional[str]:
    return None if exc is None else f"{type(exc).__name__}: {str(exc)[:500]}"


def record_shadow(
    outcome: str,
    label: str,
    *,
    output: Any,
    comparison: Optional[Dict[str, Any]] = None,
    java_seconds: Optional[float] = None,
    native_seconds: Optional[float] = None,
    java_error: Optional[BaseException] = None,
    native_error: Optional[BaseException] = None,
) -> None:
    """Count, store and log one shadow run. Never raises."""
    try:
        rec = {
            "outcome": outcome,
            "label": label,
            "output": str(output),
            "java_seconds": java_seconds,
            "native_seconds": native_seconds,
            "java_error": _err(java_error),
            "native_error": _err(native_error),
            **(comparison or {}),
        }
        with _lock:
            SHADOW_STATS[(outcome, label)] += 1
            SHADOW_RECORDS.append(rec)
        if outcome == "identical":
            logger.info(
                "MRMS shadow identical: %s, %d record(s) compared, %d existing record(s) unchanged by "
                "both, documented differences %s",
                output, rec.get("records", 0), rec.get("unchanged", 0), rec.get("expected"),
            )
        elif outcome == "expected":
            logger.info(
                "MRMS shadow expected [%s]: %s (native_error=%s)", label, output, rec["native_error"]
            )
        else:
            differences = rec.get("differences") or {}
            logger.warning(
                "MRMS shadow UNEXPECTED difference [%s]: %s, %d of %d record(s) differ "
                "(java_error=%s, native_error=%s)",
                label, output, len(differences), rec.get("records", 0),
                rec["java_error"], rec["native_error"],
            )
            for name, items in list(differences.items())[:20]:
                logger.warning("MRMS shadow %s: %s", name, " | ".join(items))
            if len(differences) > 20:
                logger.warning("MRMS shadow: %d more record(s) differ", len(differences) - 20)
    except Exception as exc:  # pragma: no cover - logging must never break the conversion
        logger.debug("MRMS shadow record failed: %s", exc)


def reset_shadow_stats() -> None:
    """Clear shadow counters and records."""
    with _lock:
        SHADOW_STATS.clear()
        SHADOW_RECORDS.clear()


@log_call
def to_dss_shadow(
    java_call: Callable[[], Path],
    grib_paths: Sequence[Path],
    output_path: Path,
    **native_kwargs: Any,
) -> Path:
    """Run Java on ``output_path``, the importer on a temporary copy, and compare the results.

    An existing output is copied first, so the importer starts from the content Java started from.
    The copies sit in a temporary folder beside the output, and need that much disk space. Only Java
    writes ``output_path``.

    Returns Java's result. Java's exception is raised as itself, and the importer does not run. A
    native failure or a difference is logged and recorded, and never raised. The importer runs with
    ``align="vortex"``, whatever was asked, since Java's record is what it is compared with.

    The outcome ``identical`` means what :func:`compare_outputs` checked: the two writers left the
    same decoded content, apart from its documented differences. It says nothing about how HEC-HMS
    or HEC-RAS read the records.
    """
    native_kwargs["align"] = "vortex"
    workspace: Optional[Path] = None
    baseline: Optional[Path] = None
    baseline_error: Optional[BaseException] = None
    native_seconds = None
    try:
        if Path(output_path).exists():
            try:
                workspace = Path(tempfile.mkdtemp(prefix="mrms_shadow_", dir=str(Path(output_path).parent)))
                baseline = workspace / f"baseline_{Path(output_path).name}"
                shutil.copy2(output_path, baseline)
            except Exception as exc:
                baseline_error = exc

        started = time.monotonic()
        try:
            result = java_call()
        except Exception as exc:
            record_shadow(
                "unexpected", "java_failed", output=output_path,
                java_seconds=time.monotonic() - started, java_error=exc,
            )
            raise
        java_seconds = time.monotonic() - started

        if baseline_error is not None:
            record_shadow(
                "unexpected", "existing_output_not_copied", output=result,
                java_seconds=java_seconds, native_error=baseline_error,
            )
            return result

        try:
            if workspace is None:
                workspace = Path(tempfile.mkdtemp(prefix="mrms_shadow_", dir=str(Path(result).parent)))
            sidecar = workspace / Path(result).name
            if baseline is not None:
                shutil.copy2(baseline, sidecar)
            engine = importlib.import_module("ras_commander_fast_dss")
            with engine.open(str(result)) as handle:
                version = handle.version

            started = time.monotonic()
            try:
                records = import_native(grib_paths, sidecar, version=version, **native_kwargs)
            except Exception as exc:
                native_seconds = time.monotonic() - started
                refused, _ = find_period_problems(
                    native_kwargs.get("product", ""), grib_paths, native_kwargs.get("variables"),
                    _engine_listing,
                )
                refused = refused or _vortex_name_problems(grib_paths)
                is_refusal = isinstance(exc, _engine_errors().DssUnsupportedRecordError)
                if refused and is_refusal:
                    record_shadow(
                        "expected", "native_refuses_instant_precipitation", output=result,
                        java_seconds=java_seconds, native_seconds=native_seconds, native_error=exc,
                    )
                else:
                    record_shadow(
                        "unexpected", "native_failed", output=result,
                        java_seconds=java_seconds, native_seconds=native_seconds, native_error=exc,
                    )
                return result
            native_seconds = time.monotonic() - started

            comparison = compare_outputs(
                Path(result), sidecar, baseline_file=baseline,
                written=[str(record.get("pathname")) for record in records],
            )
            if comparison["differences"]:
                label, outcome = "records_differ", "unexpected"
            elif comparison["records"] == 0:
                label, outcome = "nothing_compared", "unexpected"
            else:
                label, outcome = "identical", "identical"
            record_shadow(
                outcome, label, output=result, comparison=comparison,
                java_seconds=java_seconds, native_seconds=native_seconds,
            )
        except Exception as exc:
            record_shadow(
                "unexpected", "comparison_failed", output=result,
                java_seconds=java_seconds, native_seconds=native_seconds, native_error=exc,
            )
        return result
    finally:
        if workspace is not None:
            _remove_scratch(workspace)


__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND",
    "ENV_VAR",
    "SHADOW_RECORDS",
    "SHADOW_STATS",
    "compare_cells",
    "compare_grids",
    "compare_outputs",
    "effective_backend",
    "import_gridded_module",
    "import_native",
    "native_available",
    "normalize_backend",
    "check_java_periods",
    "find_period_problems",
    "period_problems",
    "record_period_problem",
    "record_shadow",
    "requested_backend",
    "reset_fallback_warning",
    "reset_shadow_stats",
    "to_dss_native",
    "settle_java_periods",
    "to_dss_shadow",
]
