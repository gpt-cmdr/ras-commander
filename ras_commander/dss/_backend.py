"""Backend selection and shadow comparison for ``RasDss`` read methods.

``RasDss`` reads DSS catalogs and time series through one of three backends:

- ``"java"`` (default in this release): HEC Monolith through pyjnius.
- ``"native"``: the optional ``dss_commander`` package (pure-Rust engine). It never
  starts a JVM and never downloads HEC Monolith.
- ``"shadow"``: returns the native result, also runs the Java path, and logs every
  difference. The comparison never raises. Differences that the migration plan
  classifies as intended (D15 cleanups and known Java-path bugs) are logged at
  DEBUG/INFO; anything else is logged at WARNING.

The environment variable ``RAS_COMMANDER_DSS_BACKEND``, when set, overrides
``RasDss.backend``. Writes, grid reads and ``get_file_version()`` stay on Java under
every backend in this release.

This module is private. Its comparison rules mirror the P09a parity harness
(``feature_dev_notes/rust_dss/packets/evidence/P09a/scripts/parity.py``).
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from collections import Counter, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("ras_commander.dss.RasDss")

#: Environment variable that overrides ``RasDss.backend`` when set.
ENV_VAR = "RAS_COMMANDER_DSS_BACKEND"
#: Allowed backend names.
BACKENDS = ("java", "native", "shadow")
#: Default backend for this release (decision D4: native becomes the default later).
DEFAULT_BACKEND = "java"

#: HEC missing markers that the Java path returns raw (-FLT_MAX after Monolith's
#: normalization; -901/-902 kept for safety). The native path maps them to NaN.
JAVA_MISSING_MARKERS = np.array([-901.0, -902.0, float(-np.finfo(np.float32).max)])

_NATIVE_INSTALL_HINT = (
    "The 'native' DSS backend requires the optional dss-commander package "
    "(ras-commander[dss-native] extra once published). The dss-commander wheel is "
    "not yet on PyPI; install the wheel you were given with "
    "'uv pip install dss_commander-<version>-<tag>.whl', or use "
    "RasDss.backend = 'java'."
)

_lock = threading.Lock()
_fallback_warned = False

#: Outcome counts of shadow comparisons: key (operation, outcome, label).
SHADOW_STATS: Counter = Counter()
#: Most recent shadow comparison records (for diagnostics and evidence scripts).
SHADOW_RECORDS: Deque[Dict[str, Any]] = deque(maxlen=5000)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def normalize_backend(value: Any, source: str) -> str:
    """Validate a backend name and return it lower-cased."""
    name = str(value).strip().lower()
    if name not in BACKENDS:
        raise ValueError(
            f"Invalid DSS backend {value!r} from {source}; "
            f"expected one of {', '.join(BACKENDS)}"
        )
    return name


def requested_backend(attribute_value: Any) -> str:
    """Backend requested by the environment variable or ``RasDss.backend``."""
    env_value = os.environ.get(ENV_VAR, "").strip()
    if env_value:
        return normalize_backend(env_value, f"environment variable {ENV_VAR}")
    if attribute_value is None or str(attribute_value).strip() == "":
        return DEFAULT_BACKEND
    return normalize_backend(attribute_value, "RasDss.backend")


def native_available() -> bool:
    """True when ``dss_commander`` can be imported."""
    try:
        importlib.import_module("dss_commander")
    except ImportError:
        return False
    return True


def import_native():
    """Import ``dss_commander`` or raise an ``ImportError`` naming the extra."""
    try:
        return importlib.import_module("dss_commander")
    except ImportError as exc:
        raise ImportError(_NATIVE_INSTALL_HINT) from exc


def effective_backend(attribute_value: Any) -> str:
    """Backend to use for this call.

    ``native`` without ``dss_commander`` raises ``ImportError``. ``shadow`` without
    ``dss_commander`` falls back to ``java`` and logs one warning per process.
    """
    global _fallback_warned
    backend = requested_backend(attribute_value)
    if backend == "native":
        import_native()
    elif backend == "shadow" and not native_available():
        with _lock:
            if not _fallback_warned:
                _fallback_warned = True
                logger.warning(
                    "DSS backend 'shadow' requested but dss-commander is not "
                    "installed; using the Java backend only. %s",
                    _NATIVE_INSTALL_HINT,
                )
        return "java"
    return backend


def reset_fallback_warning() -> None:
    """Allow the shadow-fallback warning to be logged again (tests)."""
    global _fallback_warned
    with _lock:
        _fallback_warned = False


# ---------------------------------------------------------------------------
# Shadow comparison
# ---------------------------------------------------------------------------


def _err(exc: Optional[BaseException]) -> Optional[str]:
    if exc is None:
        return None
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def record(
    operation: str,
    outcome: str,
    label: str,
    *,
    dss_file: Any,
    pathname: Optional[str] = None,
    diffs: Optional[List[str]] = None,
    java_seconds: Optional[float] = None,
    native_seconds: Optional[float] = None,
    java_error: Optional[BaseException] = None,
    native_error: Optional[BaseException] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Count, store and log one shadow comparison. Never raises."""
    try:
        rec = {
            "operation": operation,
            "outcome": outcome,
            "label": label,
            "dss_file": str(dss_file),
            "pathname": pathname,
            "diffs": list(diffs or []),
            "java_seconds": java_seconds,
            "native_seconds": native_seconds,
            "java_error": _err(java_error),
            "native_error": _err(native_error),
        }
        if detail:
            rec.update(detail)
        with _lock:
            SHADOW_STATS[(operation, outcome, label)] += 1
            SHADOW_RECORDS.append(rec)
        where = f"{dss_file}" + (f" {pathname}" if pathname else "")
        if outcome == "identical":
            logger.debug("DSS shadow %s identical: %s", operation, where)
        elif outcome in ("expected", "skipped"):
            level = logging.DEBUG if label.startswith("D1") else logging.INFO
            logger.log(
                level,
                "DSS shadow %s %s [%s]: %s (diffs=%s, java_error=%s, native_error=%s)",
                operation, outcome, label, where, rec["diffs"], rec["java_error"], rec["native_error"],
            )
        else:
            logger.warning(
                "DSS shadow %s UNEXPECTED difference [%s]: %s (diffs=%s, java_error=%s, native_error=%s)",
                operation, label, where, rec["diffs"], rec["java_error"], rec["native_error"],
            )
    except Exception as exc:  # pragma: no cover - logging must never break reads
        logger.debug("DSS shadow record failed: %s", exc)


def reset_shadow_stats() -> None:
    """Clear shadow counters and records."""
    with _lock:
        SHADOW_STATS.clear()
        SHADOW_RECORDS.clear()


def java_missing(values: np.ndarray) -> np.ndarray:
    """Missing mask for Java-path values: NaN or a raw HEC marker."""
    v = np.asarray(values, dtype=np.float64)
    return np.isnan(v) | np.isin(v, JAVA_MISSING_MARKERS)


def compare_frames(java_df: pd.DataFrame, native_df: pd.DataFrame) -> List[str]:
    """Differences between a Java and a native ``read_timeseries`` frame.

    Rules (P09a ``compare_df``): columns, index name and dtype, value dtype, length,
    index stamps (int64), missing positions (Java markers or NaN against native NaN),
    the remaining values bitwise, and every ``attrs`` key. ``attr_ws:<key>`` marks
    string attributes that differ only in surrounding whitespace.
    """
    diffs: List[str] = []
    if list(java_df.columns) != list(native_df.columns):
        diffs.append("columns")
    if java_df.index.name != native_df.index.name:
        diffs.append("index_name")
    if java_df.index.dtype != native_df.index.dtype:
        diffs.append(f"index_dtype:{java_df.index.dtype}->{native_df.index.dtype}")
    if "value" in java_df and "value" in native_df:
        if java_df["value"].dtype != native_df["value"].dtype:
            diffs.append(
                f"value_dtype:{java_df['value'].dtype}->{native_df['value'].dtype}"
            )
        jv = java_df["value"].to_numpy(dtype=np.float64)
        nv = native_df["value"].to_numpy(dtype=np.float64)
        if len(java_df) != len(native_df):
            diffs.append("length")
        else:
            if not np.array_equal(_stamps(java_df), _stamps(native_df)):
                diffs.append("index_values")
            jm = java_missing(jv)
            nm = np.isnan(nv)
            if not np.array_equal(jm, nm):
                diffs.append("missing_positions")
            both = ~jm & ~nm
            if not np.array_equal(jv[both].view(np.int64), nv[both].view(np.int64)):
                diffs.append("values_bits")
    for key in sorted(set(java_df.attrs) | set(native_df.attrs)):
        jv_ = java_df.attrs.get(key, "<absent>")
        nv_ = native_df.attrs.get(key, "<absent>")
        if jv_ != nv_:
            if isinstance(jv_, str) and isinstance(nv_, str) and jv_.strip() == nv_.strip():
                diffs.append(f"attr_ws:{key}")
            else:
                diffs.append(f"attr:{key}")
    return diffs


def _stamps(df: pd.DataFrame) -> np.ndarray:
    """Index stamps as int64 seconds, independent of the index unit."""
    return df.index.to_numpy(dtype="datetime64[s]").astype(np.int64)


def java_marker_count(java_df: pd.DataFrame) -> int:
    """Number of raw HEC markers in a Java frame (D1: NaN in native frames)."""
    if "value" not in java_df:
        return 0
    v = java_df["value"].to_numpy(dtype=np.float64)
    return int(np.isin(v, JAVA_MISSING_MARKERS).sum())


def _to_datetime64(dc, value) -> np.datetime64:
    return dc.HEC_EPOCH + np.timedelta64(int(dc.to_hec_seconds(value)), "s")


#: Intervals at or above one week (minutes) use calendar or week alignment; for them the
#: window rule falls back to "next stamp at or after each end".
_CALENDAR_INTERVAL_MINUTES = 10080


def _period_end(seconds, interval_s: int):
    """End of the standard interval period that contains each HEC-second value."""
    return -(-seconds // interval_s) * interval_s


def cut_window(
    java_df: pd.DataFrame, start, end, interval_minutes, dc
) -> pd.DataFrame:
    """Cut a whole-dataset Java frame to a ``read_timeseries`` window.

    Mirrors the native window semantics, which equal HEC Monolith's own windowed
    ``HecDss.get(path, start, end)`` (verified in P09b):

    - One-sided windows: stamps ``>= start`` or ``<= end``.
    - Both ends, regular data: each end selects the standard interval period that
      contains it (periods end on multiples of the interval from the HEC epoch);
      every stamp whose period lies between the two is kept. Without a time offset
      this means both ends move forward to the next stamp; for offset data (for
      example 6HOUR stamps at 00:30) an end inside a period selects that period's
      stamp, which can precede the requested time.
    - Both ends, irregular data: stamps in ``[start, end]``.

    The cut is then trimmed of leading and trailing missing values (regular data).
    ``interval_minutes`` is the native frame's ``interval`` attribute (0 = irregular).
    """
    if start is None and end is None:
        return java_df
    regular = bool(interval_minutes)
    stamps = java_df.index.to_numpy(dtype="datetime64[s]")
    keep = np.ones(len(stamps), dtype=bool)
    if start is not None and end is not None and regular:
        s_sec = int(dc.to_hec_seconds(start))
        e_sec = int(dc.to_hec_seconds(end))
        x_sec = (stamps - dc.HEC_EPOCH).astype("timedelta64[s]").astype(np.int64)
        interval_s = int(round(float(interval_minutes) * 60))
        if 0 < interval_s and float(interval_minutes) < _CALENDAR_INTERVAL_MINUTES:
            pe = _period_end(x_sec, interval_s)
            keep &= (pe >= _period_end(s_sec, interval_s)) & (
                pe <= _period_end(e_sec, interval_s)
            )
        else:
            keep &= x_sec >= s_sec
            later = x_sec[x_sec >= e_sec]
            keep &= x_sec <= (later[0] if len(later) else e_sec)
    else:
        if start is not None:
            keep &= stamps >= _to_datetime64(dc, start)
        if end is not None:
            keep &= stamps <= _to_datetime64(dc, end)
    out = java_df.iloc[np.flatnonzero(keep)]
    if regular and len(out):
        miss = java_missing(out["value"].to_numpy())
        valid = np.flatnonzero(~miss)
        out = out.iloc[valid[0]: valid[-1] + 1] if len(valid) else out.iloc[:0]
    out = out.copy()
    out.attrs = dict(java_df.attrs)
    return out


def java_unavailable(exc: Optional[BaseException]) -> bool:
    """True when the Java path could not run at all (no pyjnius, Java or Monolith)."""
    if exc is None:
        return False
    if isinstance(exc, ImportError):
        return True
    return isinstance(exc, RuntimeError) and str(exc).startswith("Java not found")


def _is_ascii(text: Optional[str]) -> bool:
    try:
        (text or "").encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def classify_timeseries(
    pathname: str,
    java_df: Optional[pd.DataFrame],
    java_exc: Optional[BaseException],
    native_df: Optional[pd.DataFrame],
    native_exc: Optional[BaseException],
) -> Tuple[str, str, List[str]]:
    """Classify one ``read_timeseries`` comparison.

    Returns ``(outcome, label, diffs)`` where outcome is ``identical``, ``expected``,
    ``skipped`` (Java could not run) or ``unexpected``. Labels name the P09a classes (REPORT.md section 6.3).
    """
    if java_unavailable(java_exc):
        return "skipped", "java unavailable", []
    dc = _maybe_native()
    not_found = getattr(dc, "DssPathnameNotFoundError", ()) if dc else ()
    unsupported = getattr(dc, "DssUnsupportedRecordError", ()) if dc else ()

    if java_df is not None and native_df is not None:
        diffs = compare_frames(java_df, native_df)
        if not diffs:
            if java_marker_count(java_df):
                return "expected", "D1 missing markers mapped to NaN", diffs
            return "identical", "identical", diffs
        dset = set(diffs)
        if dset <= {"attr_ws:type", "attr_ws:units"}:
            return "expected", "D9 blank units/type whitespace", diffs
        n_int = native_df.attrs.get("interval")
        if isinstance(n_int, float) and not float(n_int).is_integer():
            if dset <= {"index_values", "attr:interval"}:
                return "expected", "J2 sub-minute data (Java stamps/interval wrong)", diffs
            if dset <= {"length", "attr:interval"} and _values_prefix(java_df, native_df):
                return (
                    "expected",
                    "J2b sub-minute data (Java stamps wrong, end cut to whole minute)",
                    diffs,
                )
        if dset == {"index_values"}:
            offset = np.unique(_stamps(native_df) - _stamps(java_df))
            if len(offset) == 1 and offset[0] % 86400 == 0:
                return "expected", "J1 Java base-date offset", diffs
        if (
            "length" in dset
            and len(native_df) == len(java_df) + 1
            and n_int == 10080
            and not compare_frames(java_df, _with_attrs(native_df.iloc[1:], native_df))
        ):
            return "expected", "D8 weekly data: Java drops first value", diffs
        return "unexpected", "frame difference", diffs

    if java_df is None and native_df is not None:
        stamps = native_df.index
        if len(stamps) and stamps[0].year == 3000:
            return "expected", "D5 pattern record (Java cannot read)", []
        if not _is_ascii(pathname):
            return "expected", "D7 Latin-1 pathname (Java cannot address)", []
        # Monolith returns an empty container when its whole-dataset range lookup
        # gives up (first block all missing). Older RasDss raised an accidental
        # TypeError there; it now raises ValueError("No data found ...").
        if isinstance(java_exc, TypeError) or (
            isinstance(java_exc, ValueError) and "No data found" in str(java_exc)
        ):
            return "expected", "D3 Java misses data (first block all missing)", []
        return "unexpected", "native data, Java error", []

    if java_df is not None and native_df is None:
        if not_found and isinstance(native_exc, not_found):
            if "value" in java_df and java_missing(java_df["value"].to_numpy()).all():
                return "expected", "D4 all-missing dataset (error type)", []
        return "unexpected", "Java data, native error", []

    # Both failed.
    if (not_found and isinstance(native_exc, not_found)) or (
        unsupported and isinstance(native_exc, unsupported)
    ):
        return "expected", "D4/D6 no data: typed native error", []
    return "unexpected", "both failed, untyped native error", []


def _values_prefix(java_df: pd.DataFrame, native_df: pd.DataFrame) -> bool:
    """True when Java holds fewer values and they equal native's leading values."""
    n = len(java_df)
    if not 0 < n < len(native_df):
        return False
    jv = java_df["value"].to_numpy(dtype=np.float64)
    nv = native_df["value"].to_numpy(dtype=np.float64)[:n]
    jm, nm = java_missing(jv), np.isnan(nv)
    if not np.array_equal(jm, nm):
        return False
    both = ~jm & ~nm
    return bool(np.array_equal(jv[both].view(np.int64), nv[both].view(np.int64)))


def _with_attrs(df: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.attrs = dict(source.attrs)
    return out


def classify_catalog(
    java_df: Optional[pd.DataFrame],
    java_exc: Optional[BaseException],
    native_df: pd.DataFrame,
) -> Tuple[str, str, List[str]]:
    """Classify one ``get_catalog`` comparison."""
    if java_unavailable(java_exc):
        return "skipped", "java unavailable", []
    if java_df is None:
        return "unexpected", "native catalog, Java error", []
    diffs: List[str] = []
    jp = java_df["pathname"].astype(str).tolist()
    npaths = native_df["pathname"].astype(str).tolist()
    if str(java_df["pathname"].dtype) != str(native_df["pathname"].dtype):
        diffs.append("dtype")
    if list(java_df.columns) != list(native_df.columns):
        diffs.append("columns")
    if jp != npaths:
        diffs.append("order" if Counter(jp) == Counter(npaths) else "entries")
    if not diffs:
        return "identical", "identical", diffs
    if diffs == ["order"]:
        return "expected", "D15 catalog order", diffs
    return "unexpected", "catalog difference", diffs


def _maybe_native():
    try:
        return importlib.import_module("dss_commander")
    except ImportError:
        return None


def summary() -> Dict[str, int]:
    """Shadow outcome counts as ``{"operation|outcome|label": n}``."""
    with _lock:
        return {"|".join(k): v for k, v in sorted(SHADOW_STATS.items())}
