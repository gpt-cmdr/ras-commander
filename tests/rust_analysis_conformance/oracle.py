"""Independent full-array NumPy oracle for temporal reductions.

Formulated by equality search on the whole materialized array, unlike the
streaming argmax used by both implementations under test.
"""
import numpy as np


def oracle(values, offset=None, threshold=None):
    v = np.asarray(values).astype(np.float32)
    if offset is not None:
        v = v - np.asarray(offset, dtype=np.float32)[np.newaxis, :]
    finite = np.isfinite(v)
    if offset is not None:
        v = np.where(finite & (v < 0), np.float32(0.0), v)
    times, elements = v.shape
    has = finite.any(axis=0) if times else np.zeros(elements, dtype=bool)
    masked = np.ma.MaskedArray(v, mask=~finite)
    maximum = np.full(elements, np.nan, dtype=np.float32)
    if times:
        maximum[has] = masked.max(axis=0).filled(np.nan)[has]
    at_max = finite & (v == maximum[np.newaxis, :])
    peak = np.where(has, at_max.argmax(axis=0) if times else 0, -1).astype(np.int64)
    result = {
        "maximum": maximum,
        "peak_index": peak,
        "finite_count": finite.sum(axis=0).astype(np.uint64),
    }
    if threshold is not None:
        hit = finite & (v >= np.float32(threshold))
        any_hit = hit.any(axis=0) if times else np.zeros(elements, dtype=bool)
        result["exceed_count"] = hit.sum(axis=0).astype(np.uint64)
        result["first_exceed_index"] = np.where(
            any_hit, hit.argmax(axis=0) if times else 0, -1
        ).astype(np.int64)
    return result


def assert_matches(reduction, expected):
    """Exact comparison; -0.0 and +0.0 compare equal, NaN positions must match."""
    np.testing.assert_array_equal(reduction.maximum, expected["maximum"])
    assert reduction.maximum.dtype == np.float32
    np.testing.assert_array_equal(reduction.peak_index, expected["peak_index"])
    np.testing.assert_array_equal(reduction.finite_count, expected["finite_count"])
    if "exceed_count" in expected:
        np.testing.assert_array_equal(reduction.exceed_count, expected["exceed_count"])
        np.testing.assert_array_equal(
            reduction.first_exceed_index, expected["first_exceed_index"]
        )
    else:
        assert reduction.exceed_count is None and reduction.first_exceed_index is None
