"""Backend selection and shadow comparison for ``RasDss`` read and write methods.

``RasDss`` reads and writes DSS files through one of three backends:

- ``"java"`` (default in this release): HEC Monolith through pyjnius.
- ``"native"``: the optional ``ras_commander_fast_dss`` package (pure-Rust engine). It never
  starts a JVM and never downloads HEC Monolith.
- ``"shadow"``: returns the native result, also runs the Java path, and logs every
  difference. The comparison never raises. Differences that the migration plan
  classifies as intended (D15 cleanups and known Java-path bugs) are logged at
  DEBUG/INFO; anything else is logged at WARNING.

The environment variable ``RAS_COMMANDER_DSS_BACKEND``, when set, overrides
``RasDss.backend``. Catalog, time-series, paired-data and file-version reads switch.
Native grid reads are gated until the wheel advertises qualified CRS (``native_grid_qualified()``).
Writes switch as well: ``native`` needs the engine writers (``native_writes_available()``);
``shadow`` writes run on Java and are repeated natively on a temporary copy for comparison
(see "Shadow writes" below). ``CAPABILITIES`` lists the support matrix that
``RasDss.get_capabilities()`` reports.

This module is private. Its time-series comparison rules mirror the native-vs-Java
parity harness used to qualify the native backend on the public RasExamples corpus.

The Java backend never imports ``ras_commander_fast_dss``. Every import of the native engine
is guarded so that a missing or broken wheel (``ImportError``, or for example an
``OSError`` while loading its extension) cannot break the Java backend.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from collections import Counter, deque
from collections.abc import Mapping
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
    "The 'native' DSS backend requires the optional ras-commander-fast-dss package "
    "(import name ras_commander_fast_dss). It is not yet published; install the "
    "ras-commander-fast-dss wheel you were given with "
    "'uv pip install ras_commander_fast_dss-<version>-<tag>.whl', or use "
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
    """True when ``ras_commander_fast_dss`` can be imported (a broken wheel counts as absent)."""
    return _maybe_native() is not None


def import_native():
    """Import ``ras_commander_fast_dss`` or raise an ``ImportError`` naming the extra.

    A wheel that fails to load (for example an ``OSError`` from its extension)
    also raises ``ImportError``, with the original error chained.
    """
    try:
        return importlib.import_module("ras_commander_fast_dss")
    except ImportError as exc:
        raise ImportError(_NATIVE_INSTALL_HINT) from exc
    except Exception as exc:  # broken native wheel
        raise ImportError(
            f"ras-commander-fast-dss is installed but failed to load ({type(exc).__name__}: {exc}). "
            + _NATIVE_INSTALL_HINT
        ) from exc


def effective_backend(attribute_value: Any) -> str:
    """Backend to use for this call.

    ``native`` without ``ras_commander_fast_dss`` raises ``ImportError``. ``shadow`` without
    ``ras_commander_fast_dss`` falls back to ``java`` and logs one warning per process.
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
                    "DSS backend 'shadow' requested but ras-commander-fast-dss is not "
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

    Rules: columns, index name and dtype, value dtype, length,
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
    ``HecDss.get(path, start, end)`` (verified on the public RasExamples corpus):

    - One-sided windows: stamps ``>= start`` or ``<= end``.
    - Both ends, regular data: each end selects the standard interval period that
      contains it (periods end on multiples of the interval from the HEC epoch);
      every stamp whose period lies between the two is kept. Without a time offset
      this means both ends move forward to the next stamp; for offset data (for
      example 6HOUR stamps at 00:30) an end inside a period selects that period's
      stamp, which can precede the requested time.
    - Both ends, irregular data: stamps in ``[start, end]``.

    The cut is then trimmed of leading and trailing HEC missing markers (regular
    data), as heclib's ``ztsTrim`` trims them; a stored NaN is a value and is kept.
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
        # heclib ztsTrim trims HEC markers only; a stored NaN is a value.
        miss = np.isin(out["value"].to_numpy(dtype=np.float64), JAVA_MISSING_MARKERS)
        valid = np.flatnonzero(~miss)
        out = out.iloc[valid[0]: valid[-1] + 1] if len(valid) else out.iloc[:0]
    out = out.copy()
    out.attrs = dict(java_df.attrs)
    return out


def verification_window(frame: Optional[pd.DataFrame]):
    """Minute-aligned native span suitable for an independent Java window read."""
    if frame is None or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return None
    index = frame.index
    if index.hasnans or not index.is_unique or not index.is_monotonic_increasing:
        return None
    first, last = index[0], index[-1]
    if any((stamp.second or stamp.microsecond or stamp.nanosecond) for stamp in (first, last)):
        return None
    return first.strftime("%d%b%Y %H%M"), last.strftime("%d%b%Y %H%M")


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


#: Shadow label for a native not-found error that HEC's DSS6 "no data" rule explains.
HEC_NO_DATA_LABEL = "D4 HEC DSS6 no-data rule (native refusal, status 4)"


def native_refuses_no_data(read, native_exc: Optional[BaseException]) -> bool:
    """True when HEC's DSS6 "no data" rule explains a native not-found error.

    For parity and testing only; never used for the value a read returns. HEC
    Monolith (the Java path) reports a DSS6 regular time-series request as not
    found when every value it reads is -901 or -902 (heclib ``zrrtsi.f`` status 4,
    Monolith status -2). By default the native engine finds those blocks and, with
    its default trim, then reports "no values" with the same not-found error type,
    so the two errors look alike but have different causes. the engine's opt-in
    ``no_data="refuse"`` applies HEC's rule and raises ``DssNoDataError`` (a
    ``DssPathnameNotFoundError`` with ``status == 4``). Shadow mode uses it to tell
    this case apart from an absent pathname.

    ``read`` repeats the native read with extra keyword arguments. It is called
    only when ``native_exc`` is a plain not-found error and the installed
    ras-commander-fast-dss provides ``DssNoDataError``; any other failure returns False.
    """
    dc = _maybe_native()
    no_data_error = getattr(dc, "DssNoDataError", None) if dc else None
    not_found = getattr(dc, "DssPathnameNotFoundError", None) if dc else None
    if no_data_error is None or not_found is None:
        return False
    if isinstance(native_exc, no_data_error):
        return True
    if not isinstance(native_exc, not_found):
        return False
    try:
        read(no_data="refuse")
    except no_data_error:
        return True
    except Exception:
        return False
    return False


def classify_timeseries(
    pathname: str,
    java_df: Optional[pd.DataFrame],
    java_exc: Optional[BaseException],
    native_df: Optional[pd.DataFrame],
    native_exc: Optional[BaseException],
    *,
    java_window_df: Optional[pd.DataFrame] = None,
    native_hec_no_data: bool = False,
) -> Tuple[str, str, List[str]]:
    """Classify one ``read_timeseries`` comparison.

    Returns ``(outcome, label, diffs)`` where outcome is ``identical``, ``expected``,
    ``skipped`` (Java could not run) or ``unexpected``. Labels name the classes in
    ``docs/user-guide/dss-native-backend.md``.

    ``native_hec_no_data`` is True when a native re-read with ``no_data="refuse"``
    raised ``ras_commander_fast_dss.DssNoDataError`` (see ``native_refuses_no_data``): HEC's
    DSS6 rule reports the request as "no data" because every value read is -901 or
    -902. A native not-found error is then labelled ``HEC_NO_DATA_LABEL`` instead
    of the broader D4 labels.
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
        # #591 fixes Java base-date and granularity handling. A new clock or
        # interval disagreement is unexpected, regardless of its magnitude.
        # Monolith's independently observed whole-minute tail truncation remains
        # recognizable only with an identical timestamped prefix and a short tail.
        if (isinstance(n_int, float) and not float(n_int).is_integer()
                and dset == {"length"} and _values_prefix(java_df, native_df)):
            return "expected", "J2b Java sub-minute tail cut to whole minute", diffs
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
        known_no_data = (isinstance(java_exc, ValueError) and
                         str(java_exc) == f"No data found for pathname: {pathname}")
        if known_no_data and java_window_df is not None:
            diffs = compare_frames(java_window_df, native_df)
            if not diffs:
                return "expected", "D3 Java whole read misses data; window verified", []
            return "unexpected", "Java window differs after whole-read failure", diffs
        parts = pathname.split("/")
        if (known_no_data and len(parts) == 8 and parts[4] == "TS-PATTERN"
                and len(stamps) and stamps[0].year == 3000):
            return "expected", "D5 pattern record (Java cannot read)", []
        if known_no_data and not _is_ascii(pathname):
            return "expected", "D7 Latin-1 pathname (Java cannot address)", []
        # An error alone cannot prove an all-missing first block. Keep this
        # disagreement visible instead of assuming a known Java producer defect.
        return "unexpected", "native data, Java error", []

    if java_df is not None and native_df is None:
        if not_found and isinstance(native_exc, not_found):
            if "value" in java_df and java_missing(java_df["value"].to_numpy()).all():
                if native_hec_no_data:
                    return "expected", HEC_NO_DATA_LABEL, []
                return "expected", "D4 all-missing dataset (error type)", []
        return "unexpected", "Java data, native error", []

    # Both failed.
    if native_hec_no_data and not_found and isinstance(native_exc, not_found):
        return "expected", HEC_NO_DATA_LABEL, []
    if (not_found and isinstance(native_exc, not_found)) or (
        unsupported and isinstance(native_exc, unsupported)
    ):
        return "expected", "D4/D6 no data: typed native error", []
    return "unexpected", "both failed, untyped native error", []


def _values_prefix(java_df: pd.DataFrame, native_df: pd.DataFrame) -> bool:
    """Verify a matching timestamped prefix ending at the last whole minute."""
    n = len(java_df)
    if not 0 < n < len(native_df):
        return False
    jt, nt = _stamps(java_df), _stamps(native_df)
    if (not np.array_equal(jt, nt[:n]) or jt[-1] % 60 != 0
            or not 0 < nt[-1] - jt[-1] < 60):
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
    """``ras_commander_fast_dss`` or None. Never raises: a broken wheel counts as absent."""
    try:
        return importlib.import_module("ras_commander_fast_dss")
    except Exception:
        return None


def summary() -> Dict[str, int]:
    """Shadow outcome counts as ``{"operation|outcome|label": n}``."""
    with _lock:
        return {"|".join(k): v for k, v in sorted(SHADOW_STATS.items())}


# ---------------------------------------------------------------------------
# Capabilities: paired data, grids and file version
# ---------------------------------------------------------------------------

#: Feature name a ras-commander-fast-dss wheel advertises (in ``ras_commander_fast_dss.FEATURES``) once
#: its grid CRS strings are qualified against HEC Monolith.
NATIVE_GRID_FEATURE = "grid_srs_monolith_parity"


def native_grid_qualified() -> bool:
    """True when the installed ras-commander-fast-dss advertises qualified grid CRS strings.

    This is a capability check, not a version pin. ``ras_commander_fast_dss.FEATURES`` must be
    a set, frozenset, tuple or list of ``str`` containing ``NATIVE_GRID_FEATURE``, or
    a mapping whose ``NATIVE_GRID_FEATURE`` value is truthy. Anything else, a missing
    attribute (every wheel up to and including 0.0.1), or an engine that fails to
    import, is not qualified.
    """
    dc = _maybe_native()
    if dc is None:
        return False
    try:
        features = getattr(dc, "FEATURES", None)
        if isinstance(features, Mapping):
            return bool(features.get(NATIVE_GRID_FEATURE, False))
        if isinstance(features, (set, frozenset, tuple, list)):
            return any(isinstance(f, str) and f == NATIVE_GRID_FEATURE for f in features)
    except Exception:
        return False
    return False


NATIVE_GRID_GATE_MESSAGE = (
    "Native DSS grid reads are not yet qualified: the native CRS string can differ "
    "from HEC Monolith's for some legacy Albers grids, and the installed "
    "ras-commander-fast-dss does not advertise the 'grid_srs_monolith_parity' feature. RasDss does not "
    "fall back to Java. Use RasDss.backend = 'java' (or 'shadow'), or pass "
    "allow_unqualified_native=True to accept native cells and metadata with an "
    "unqualified CRS (metadata['crs_qualified'] is False)."
)

#: ras_commander_fast_dss attributes that make up the native writer API (DSS7 and DSS6, regular
#: and irregular time series, paired data and grids). ``native_writes_available`` requires
#: all of them; a build without writer support has none.
NATIVE_WRITE_API = (
    "create", "write_timeseries", "write_paired_data", "write_grid",
    "HEC_MISSING_DSS6", "GRID_NODATA",
)


def native_writes_available() -> bool:
    """True when the installed ras-commander-fast-dss provides the native writers.

    A capability check, not a version pin: ``ras_commander_fast_dss`` must import and expose
    every name in ``NATIVE_WRITE_API`` (``create``, ``write_timeseries``,
    ``write_paired_data`` and ``write_grid`` callable). ``HEC_MISSING_DSS6`` marks the DSS6 time-series writer
    and ``GRID_NODATA`` the grid writer. Never raises.
    """
    dc = _maybe_native()
    if dc is None:
        return False
    try:
        for name in NATIVE_WRITE_API:
            value = getattr(dc, name, None)
            if value is None:
                return False
            if name in ("create", "write_timeseries", "write_paired_data", "write_grid") and not callable(value):
                return False
    except Exception:
        return False
    return True


NATIVE_WRITES_GATE_MESSAGE = (
    "The installed ras-commander-fast-dss does not provide the native DSS writers "
    "(ras_commander_fast_dss.create, write_timeseries, write_paired_data and write_grid "
    "with DSS6 support). "
    "RasDss does not fall back to Java. Use a ras-commander-fast-dss build with writer support "
    "(RasDss.get_capabilities().attrs['native_writes_available']), or use "
    "RasDss.backend = 'java'."
)


def require_native_writes():
    """``ras_commander_fast_dss`` with its writers, or ``DssCapabilityError`` (never Java)."""
    from . import _errors

    dc = import_native()
    if not native_writes_available():
        raise _errors.get("DssCapabilityError")(NATIVE_WRITES_GATE_MESSAGE)
    return dc


#: Shadow writes copy an existing target file to a temporary directory before the Java
#: write, so that the native writer can repeat the write on the copy. Larger files are
#: not copied and the comparison is skipped. Default limit in MB; override it with
#: ``RasDss.shadow_copy_limit_mb`` or the environment variable ``SHADOW_COPY_LIMIT_ENV``.
SHADOW_COPY_LIMIT_MB_DEFAULT = 256.0
SHADOW_COPY_LIMIT_ENV = "RAS_COMMANDER_DSS_SHADOW_COPY_LIMIT_MB"


def shadow_copy_limit_bytes(attribute_mb: Any) -> int:
    """Byte limit for shadow-write copies.

    The environment variable ``RAS_COMMANDER_DSS_SHADOW_COPY_LIMIT_MB``, when set,
    overrides ``RasDss.shadow_copy_limit_mb`` (default 256). The value is megabytes
    (2**20 bytes) and must be a finite number >= 0; 0 skips every comparison on an
    existing file. Raises ``ValueError`` for anything else (the shadow write then logs
    the comparison as skipped).
    """
    env_value = os.environ.get(SHADOW_COPY_LIMIT_ENV, "").strip()
    raw, source = (env_value, f"environment variable {SHADOW_COPY_LIMIT_ENV}") if env_value \
        else (attribute_mb, "RasDss.shadow_copy_limit_mb")
    try:
        mb = float(raw)
    except (TypeError, ValueError):
        mb = float("nan")
    if not np.isfinite(mb) or mb < 0:
        raise ValueError(f"invalid shadow copy limit {raw!r} from {source}: expected MB >= 0")
    return int(mb * 1024 * 1024)


def make_parents(path: Any) -> List[Any]:
    """Create the missing parent directories of ``path``; return them, deepest first."""
    from pathlib import Path

    created = []
    parent = Path(path).parent
    while not parent.exists():
        created.append(parent)
        if parent.parent == parent:
            break
        parent = parent.parent
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return created


def remove_created_dirs(created: List[Any]) -> None:
    """Remove directories made by ``make_parents`` if they are still empty. Never raises."""
    for directory in created:
        try:
            directory.rmdir()
        except OSError:
            break

#: Backend support per public DSS operation. Values: "yes"; "gated" (needs a qualified
#: or writer-capable engine, or an explicit opt-in); "java" (runs on Java whatever the
#: backend); "no".
CAPABILITIES = (
    # operation, java, native, shadow, note
    ("get_catalog", "yes", "yes", "yes", ""),
    ("read_timeseries", "yes", "yes", "yes", "native and shadow honor start_date/end_date"),
    ("read_multiple_timeseries", "yes", "yes", "yes", ""),
    ("read_paired_data", "yes", "yes", "yes", "all curves, labels, units, types, stored precision"),
    ("read_grid", "yes", "gated", "yes",
     "native requires a ras-commander-fast-dss wheel advertising 'grid_srs_monolith_parity' "
     "or allow_unqualified_native=True; shadow returns Java's grid and only compares "
     "the native result"),
    ("get_file_version", "yes", "yes", "yes", ""),
    ("write_timeseries", "yes", "gated", "java",
     "native requires the ras-commander-fast-dss writers (native_writes_available); shadow "
     "writes with Java, repeats the write natively on a temporary copy and compares "
     "the read-back"),
    ("write_timeseries_from_dataframe", "yes", "gated", "java", "as write_timeseries"),
    ("write_grid_timeseries", "yes", "gated", "java", "as write_timeseries"),
    ("copy_grid_with_zero_tail", "yes", "gated", "java",
     "native reads the source and writes the derivative without Java; shadow builds "
     "a second derivative natively in a temporary directory and compares it"),
    ("write_precip_grid_arrays", "yes", "gated", "yes",
     "java column: pydsstools, not Java; native writes through ras-commander-fast-dss; shadow "
     "writes with pydsstools and compares a native copy"),
    ("write_paired_data", "yes", "gated", "java", "as write_timeseries"),
)


def _float_bits_equal(a: np.ndarray, b: np.ndarray) -> bool:
    """Bitwise equality of two float arrays of the same dtype and shape."""
    a, b = np.asarray(a), np.asarray(b)
    if a.dtype != b.dtype or a.shape != b.shape:
        return False
    width = {4: np.int32, 8: np.int64}.get(a.dtype.itemsize)
    if width is None or a.dtype.kind != "f":
        return bool(np.array_equal(a, b))
    return bool(np.array_equal(np.ascontiguousarray(a).view(width),
                               np.ascontiguousarray(b).view(width)))


def compare_paired_data(java_df: pd.DataFrame, native_df: pd.DataFrame) -> List[str]:
    """Differences between a Java and a native ``read_paired_data`` frame.

    Compares the index (name, dtype, bits), the columns (names, order, dtype and
    bits of every curve) and every ``attrs`` key.
    """
    diffs: List[str] = []
    if java_df.index.name != native_df.index.name:
        diffs.append("index_name")
    if java_df.index.dtype != native_df.index.dtype:
        diffs.append(f"index_dtype:{java_df.index.dtype}->{native_df.index.dtype}")
    elif not _float_bits_equal(java_df.index.to_numpy(), native_df.index.to_numpy()):
        diffs.append("ordinates_bits")
    if list(java_df.columns) != list(native_df.columns):
        diffs.append("columns")
    if java_df.shape != native_df.shape:
        diffs.append("shape")
    else:
        for i in range(java_df.shape[1]):
            jv, nv = java_df.iloc[:, i].to_numpy(), native_df.iloc[:, i].to_numpy()
            if jv.dtype != nv.dtype:
                diffs.append(f"curve_dtype:{i}")
            elif not _float_bits_equal(jv, nv):
                diffs.append(f"curve_bits:{i}")
    for key in sorted(set(java_df.attrs) | set(native_df.attrs)):
        jv_ = java_df.attrs.get(key, "<absent>")
        nv_ = native_df.attrs.get(key, "<absent>")
        if jv_ != nv_:
            if isinstance(jv_, str) and isinstance(nv_, str) and jv_.strip() == nv_.strip():
                diffs.append(f"attr_ws:{key}")
            else:
                diffs.append(f"attr:{key}")
    return diffs


def _default_curve_names(df: pd.DataFrame) -> bool:
    return list(df.columns) == [f"curve_{i + 1}" for i in range(df.shape[1])]


def classify_paired_data(
    java_df: Optional[pd.DataFrame],
    java_exc: Optional[BaseException],
    native_df: Optional[pd.DataFrame],
    native_exc: Optional[BaseException],
) -> Tuple[str, str, List[str]]:
    """Classify one ``read_paired_data`` comparison.

    Known differences (logged as ``expected``):

    - ``PD1`` (DSS6 only): the Java DSS6 reader strips leading blanks from curve labels; HEC's
      C library (and native) keeps them. Labels must agree after ``lstrip``; the
      column names derived from them may differ accordingly.
    - ``PD2``: Java does not expose the DSS7 paired-data time zone.
    - ``PD3``: whitespace-only differences in unit/type/parameter strings.
    - ``PD4``: DSS6 precision: Monolith reports -1 (unset); native decodes the stored
      ``KIPREC`` word (``zpdRetrieve6.c``) to a value ``>= 0``. Both sides must be DSS6.
    """
    from . import _errors

    if java_unavailable(java_exc):
        return "skipped", "java unavailable", []
    not_found = _errors.get("DssPathnameNotFoundError")
    if java_df is not None and native_df is not None:
        diffs = compare_paired_data(java_df, native_df)
        if not diffs:
            return "identical", "identical", diffs
        labels: List[str] = []
        rest = set(diffs)
        dss6 = (native_df.attrs.get("dss_version") == 6
                and java_df.attrs.get("dss_version") == 6)
        if "attr:labels" in rest and dss6:
            jl = [s.lstrip() for s in java_df.attrs.get("labels", [])]
            nl = [s.lstrip() for s in native_df.attrs.get("labels", [])]
            if jl == nl:
                rest.discard("attr:labels")
                if "columns" in rest and (
                    [str(c).lstrip() for c in java_df.columns]
                    == [str(c).lstrip() for c in native_df.columns]
                    or _default_curve_names(java_df) or _default_curve_names(native_df)
                ):
                    rest.discard("columns")
                labels.append("PD1 DSS6 label leading blanks (Java strips)")
        if "attr:time_zone" in rest and java_df.attrs.get("time_zone") is None:
            rest.discard("attr:time_zone")
            labels.append("PD2 DSS7 time zone (Java does not report it)")
        precision = {"attr:x_precision", "attr:y_precision"} & rest
        if (precision and dss6
                and all(java_df.attrs.get(k.split(":", 1)[1]) == -1 for k in precision)
                and all(isinstance(native_df.attrs.get(k.split(":", 1)[1]), int)
                        and native_df.attrs.get(k.split(":", 1)[1]) >= 0 for k in precision)):
            rest -= precision
            labels.append("PD4 DSS6 precision (Java reports -1; native reads KIPREC)")
        ws = {d for d in rest if d.startswith("attr_ws:")}
        if ws:
            rest -= ws
            labels.append("PD3 unit/type whitespace")
        if not rest:
            return "expected", "; ".join(labels), diffs
        return "unexpected", "paired-data difference", diffs
    if java_df is None and native_df is None:
        if isinstance(native_exc, not_found) and isinstance(java_exc, not_found):
            return "expected", "not found on both backends", []
        return "unexpected", "both failed", []
    if native_df is not None:
        return "unexpected", "native data, Java error", []
    return "unexpected", "Java data, native error", []


def _same(a: Any, b: Any) -> bool:
    """Equality that treats None/NaT pairs as equal."""
    a_missing = a is None or (isinstance(a, (pd.Timestamp, type(pd.NaT))) and pd.isna(a))
    b_missing = b is None or (isinstance(b, (pd.Timestamp, type(pd.NaT))) and pd.isna(b))
    if a_missing or b_missing:
        return a_missing and b_missing
    try:
        return bool(a == b)
    except Exception:  # pragma: no cover - defensive
        return False


def _grid_meta_diffs(java: Dict[str, Any], native: Dict[str, Any]) -> List[str]:
    """Metadata differences between two ``read_grid`` dictionaries (cells excluded)."""
    diffs: List[str] = []
    for key in ("pathname", "shape", "units", "data_type", "grid_type", "crs",
                "cell_size", "start_time", "end_time", "row_order"):
        jv, nv = java.get(key), native.get(key)
        if not _same(jv, nv):
            if isinstance(jv, str) and isinstance(nv, str) and jv.strip() == nv.strip():
                diffs.append(f"ws:{key}")
            else:
                diffs.append(key)
    jm, nm = java.get("metadata", {}) or {}, native.get("metadata", {}) or {}
    for key in ("pathname_parts", "grid_class", "grid_type_code", "data_type_code",
                "shape", "number_of_cells_x", "number_of_cells_y", "lower_left_cell",
                "origin", "nodata_value", "compression", "number_missing", "timing"):
        if not _same(jm.get(key), nm.get(key)):
            diffs.append(f"metadata.{key}")
    jp, np_ = jm.get("projection", {}) or {}, nm.get("projection", {}) or {}
    for key in sorted(set(jp) | set(np_)):
        jv, nv = jp.get(key), np_.get(key)
        if not _same(jv, nv):
            if isinstance(jv, str) and isinstance(nv, str) and jv.strip() == nv.strip():
                diffs.append(f"ws:projection.{key}")
            else:
                diffs.append(f"projection.{key}")
    return diffs


def _grid_cell_diffs(java: Dict[str, Any], native: Dict[str, Any]) -> Tuple[List[str], bool]:
    """Cell differences, and whether extra native NaN cells are the known G1 case.

    Java maps only the grid no-data marker (-FLT_MAX) to NaN; native also maps the
    grid's null value and -901/-902.
    """
    jd = np.asarray(java.get("data"), dtype=np.float32)
    nd = np.asarray(native.get("data"), dtype=np.float32)
    if jd.shape != nd.shape:
        return ["cells_shape"], False
    jm, nm = np.isnan(jd), np.isnan(nd)
    diffs: List[str] = []
    extra_ok = False
    if np.any(jm & ~nm):
        diffs.append("cells_missing_java_only")
    extra = nm & ~jm
    if np.any(extra):
        null = ((native.get("metadata") or {}).get("native") or {}).get("null_value")
        markers = [-901.0, -902.0] + ([null] if null is not None else [])
        extra_ok = bool(np.all(np.isin(jd[extra], np.asarray(markers, dtype=np.float32))))
        diffs.append("cells_missing_native_only")
    both = ~jm & ~nm
    if not np.array_equal(jd[both].view(np.int32), nd[both].view(np.int32)):
        diffs.append("cells_bits")
    return diffs, extra_ok


def classify_grid(
    java: Optional[Dict[str, Any]],
    java_exc: Optional[BaseException],
    native: Optional[Dict[str, Any]],
    native_exc: Optional[BaseException],
) -> Tuple[str, str, List[str]]:
    """Classify one ``read_grid`` comparison. Cells and metadata are judged separately
    (diffs are prefixed ``cells:`` or ``meta:``).

    Known differences (logged as ``expected``):

    - ``G-CRS``: the CRS string differs while the native grid CRS is unqualified
      (``native_grid_qualified()`` is False). Once qualified it is unexpected.
    - ``G1``: native maps the grid null value and -901/-902 to NaN; Java maps only
      -FLT_MAX.
    - ``G2``: whitespace-only differences (Java pads legacy unit strings).
    - ``G3``: untimed grid records (odd record types): native reports no time;
      Java reports the header times.
    - ``G4``: ``number_missing``: Java reports its own count; native counts NaN cells.

    Any cell bit difference is ``unexpected``.
    """
    from . import _errors

    if java_unavailable(java_exc):
        return "skipped", "java unavailable", []
    if java is not None and native is not None:
        cell_diffs, extra_ok = _grid_cell_diffs(java, native)
        meta_diffs = _grid_meta_diffs(java, native)
        diffs = [f"cells:{d}" for d in cell_diffs] + [f"meta:{d}" for d in meta_diffs]
        if not diffs:
            return "identical", "identical", diffs
        labels: List[str] = []
        rest_cells = set(cell_diffs)
        if rest_cells == {"cells_missing_native_only"} and extra_ok:
            rest_cells.clear()
            labels.append("G1 native maps grid null/-901/-902 to NaN")
        rest_meta = set(meta_diffs)
        if rest_meta & {"crs", "ws:crs"} and not native_grid_qualified():
            rest_meta -= {"crs", "ws:crs"}
            labels.insert(0, "G-CRS native grid CRS unqualified")
        ws = {d for d in rest_meta if d.startswith("ws:")}
        if ws:
            rest_meta -= ws
            labels.append("G2 whitespace")
        native_md = (native.get("metadata") or {}).get("native") or {}
        untimed = int(native_md.get("record_type", 0) or 0) % 2 == 1
        timing = {"start_time", "end_time", "metadata.timing"}
        if untimed and rest_meta & timing:
            rest_meta -= timing
            labels.append("G3 untimed grid: native reports no time")
        if "metadata.number_missing" in rest_meta:
            rest_meta.discard("metadata.number_missing")
            labels.append("G4 number_missing count rule")
        if rest_cells:
            return "unexpected", "grid cell difference", diffs
        if rest_meta:
            return "unexpected", "grid metadata difference", diffs
        return "expected", "; ".join(labels), diffs
    if java is None and native is None:
        for name in ("DssPathnameNotFoundError", "DssRecordTypeError"):
            cls = _errors.get(name)
            if isinstance(java_exc, cls) and isinstance(native_exc, cls):
                return "expected", f"{name} on both backends", []
        return "unexpected", "both failed", []
    if native is not None:
        return "unexpected", "native grid, Java error", []
    return "unexpected", "Java grid, native error", []


def classify_file_version(
    java_version: Optional[int],
    java_exc: Optional[BaseException],
    native_version: Optional[int],
    native_exc: Optional[BaseException],
) -> Tuple[str, str, List[str]]:
    """Classify one ``get_file_version`` comparison."""
    from . import _errors

    if java_unavailable(java_exc):
        return "skipped", "java unavailable", []
    if java_exc is None and native_exc is None:
        if java_version == native_version:
            return "identical", "identical", []
        return "unexpected", "version difference", ["version"]
    invalid = _errors.get("DssInvalidFileError")
    if isinstance(java_exc, invalid) and isinstance(native_exc, invalid):
        return "expected", "invalid file on both backends", []
    return "unexpected", "error difference", []


# ---------------------------------------------------------------------------
# Shadow writes
# ---------------------------------------------------------------------------
#
# Under ``shadow`` every write runs on Java (its result and errors are what the caller
# gets). The native writer then repeats the write on a temporary copy of the target
# (or into a temporary new file), and both files are read back through the native
# reader and compared. Both read-backs use the same reader, so any difference comes
# from the writers. The comparison never raises.

_write_state = threading.local()


def java_writes_forced() -> bool:
    """True inside ``forced_java_writes()`` (on this thread)."""
    return bool(getattr(_write_state, "depth", 0))


class forced_java_writes:
    """Context manager: public writers called inside it use Java under ``shadow``.

    A shadow ``copy_grid_with_zero_tail`` writes its records through the public
    ``write_grid_timeseries``; this keeps those nested writes from running their own
    shadow comparison on the temporary derivative.
    """

    def __enter__(self):
        _write_state.depth = getattr(_write_state, "depth", 0) + 1
        return self

    def __exit__(self, *exc):
        _write_state.depth -= 1
        return False


#: Known differences between a Java-written and a native-written file, both read back
#: natively. Labels are logged as ``expected``.
WRITE_REFUSAL_LABEL = "W1 native writer refuses input the Java path accepts"
GRID_NULL_LABEL = "W2 DSS7 HRAP/Albers grid null value (Monolith 0.0, native -FLT_MAX)"
GRID_ZLIB_WORDS_LABEL = "W3 ZLIB grid scale/base words (unused by ZLIB)"
NATIVE_WRITERS_MISSING_LABEL = "native writers not available"
PAIRED_PRECISION_LABEL = "W10 DSS6 paired-data display precision (Monolith keeps an earlier write's)"


def compare_written_timeseries(java_df: pd.DataFrame, native_df: pd.DataFrame) -> List[str]:
    """Differences between the native read-backs of a Java- and a native-written series.

    The ``read_timeseries`` rules (``compare_frames``) without the ``dss_file``
    attribute, which names the two different files.
    """
    return [d for d in compare_frames(java_df, native_df)
            if d not in ("attr:dss_file", "attr_ws:dss_file")]


#: PRECIP_2_BYTE: the scale factor and base decode the cells, so they must agree.
_PRECIP_2_BYTE = 101001


def compare_written_grids(
    java: Dict[str, Any], native: Dict[str, Any]
) -> Tuple[List[str], List[str]]:
    """Differences between the native read-backs of a Java- and a native-written grid.

    Returns ``(diffs, labels)``. ``diffs`` are unexpected: cell bits or missing
    positions, the ``read_grid`` metadata, the compression method, and for
    PRECIP_2_BYTE its scale factor and base. ``labels`` name the known differences
    found (``W2`` null value, ``W3`` ZLIB scale/base words). The compressed size and
    bytes are not compared (a different deflate library writes other bytes for the
    same cells).
    """
    cell_diffs, _ = _grid_cell_diffs(java, native)
    diffs = [f"cells:{d}" for d in cell_diffs]
    meta = [d for d in _grid_meta_diffs(java, native) if d != "metadata.compression"]
    diffs += [f"meta:{d}" for d in meta]
    labels: List[str] = []
    jm, nm = java.get("metadata") or {}, native.get("metadata") or {}
    jc, nc = jm.get("compression") or {}, nm.get("compression") or {}
    if jc.get("method") != nc.get("method"):
        diffs.append("meta:compression.method")
    else:
        for key in ("scale_factor", "base"):
            if not _same(jc.get(key), nc.get(key)):
                if jc.get("method") == _PRECIP_2_BYTE:
                    diffs.append(f"meta:compression.{key}")
                elif GRID_ZLIB_WORDS_LABEL not in labels:
                    labels.append(GRID_ZLIB_WORDS_LABEL)
    jn, nn = jm.get("native") or {}, nm.get("native") or {}
    if not _same(jn.get("null_value"), nn.get("null_value")):
        if (java.get("grid_type") in ("albers", "hrap") and int(jn.get("dss_version") or 0) == 7
                and float(jn.get("null_value")) == 0.0):
            labels.append(GRID_NULL_LABEL)
        else:
            diffs.append("meta:native.null_value")
    for key in ("time_zone_id", "time_zone_raw_offset", "is_interval", "srs_name",
                "data_source"):
        if not _same(jn.get(key), nn.get(key)):
            diffs.append(f"meta:native.{key}")
    return diffs, labels


def compare_written_paired_data(
    java_df: pd.DataFrame, native_df: pd.DataFrame
) -> Tuple[List[str], List[str]]:
    """Differences between the native read-backs of a Java-written and a native-written
    paired-data record, and the labels of the known ones found.

    Same rules as ``compare_paired_data``, without the file path. ``W10``: on DSS6,
    Monolith keeps the display precision of an earlier write in the same process.
    """
    diffs = [d for d in compare_paired_data(java_df, native_df) if d != "attr:dss_file"]
    labels: List[str] = []
    if native_df.attrs.get("dss_version") == 6:
        precision = [d for d in diffs if d in ("attr:x_precision", "attr:y_precision")]
        if precision:
            diffs = [d for d in diffs if d not in precision]
            labels.append(PAIRED_PRECISION_LABEL)
    return diffs, labels


def classify_write(
    native_exc: Optional[BaseException], diffs: List[str], labels: List[str]
) -> Tuple[str, str, List[str]]:
    """Classify one shadow write comparison.

    - The native writer refused the input (``ValueError``, or
      ``DssUnsupportedRecordError``): ``expected`` ``W1``. These are the documented
      refusals where the Java path truncates, reinterprets or writes an unreadable
      record.
    - ``DssCapabilityError`` (the installed ras-commander-fast-dss has no writers):
      ``skipped``.
    - ``DssLockedError`` on the temporary copy: ``skipped``.
    - Any other native error, or any unexpected difference: ``unexpected``.
    """
    from . import _errors

    if native_exc is not None:
        if isinstance(native_exc, _errors.get("DssCapabilityError")):
            return "skipped", NATIVE_WRITERS_MISSING_LABEL, list(diffs)
        if isinstance(native_exc, (ValueError, _errors.get("DssUnsupportedRecordError"))):
            return "expected", WRITE_REFUSAL_LABEL, list(diffs)
        dc = _maybe_native()
        locked = getattr(dc, "DssLockedError", None) if dc is not None else None
        if locked is not None and isinstance(native_exc, locked):
            return "skipped", "native write: temporary copy locked", list(diffs)
        return "unexpected", "native write error", list(diffs)
    if diffs:
        return "unexpected", "write difference", list(diffs)
    if labels:
        return "expected", "; ".join(labels), []
    return "identical", "identical", []
